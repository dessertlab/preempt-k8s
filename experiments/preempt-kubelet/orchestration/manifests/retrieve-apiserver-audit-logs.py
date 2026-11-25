#!/usr/bin/env python3

"""
Builds the summary of an orchestration experiment run over all its iterations, from the
Kubernetes logs. Only the critical Knative services whose criticality level falls in [1, 10] are analyzed.

For each iteration the kubelet analysis summary (summary.json) is checked first:
  mode                - bands enabled or disabled, as declared in the experiment configuration
  pods                - number of pods equal to services + interfering resources
  missing pods        - no pod with missing timestamps
  limit violations    - no creation slots limit violated (bands enabled only)
  order inversions    - no dequeue order inversion within a band (bands enabled only)
If any check fails, the analysis stops without writing any file.

For each iteration and service the following events are extracted from the audit logs:
  scale_up            - the Knative Autoscaler updates the `replicas` field of a KSVC to `1` (Deployment or RTResource)
  starts_processing   - Preempt-FaaS initial KSVC RTResource `status` update (RTResource tests only, informative)
  pod_created         - pod creation by the Kube-Manager Controller or Preempt-FaaS
  container_started   - first kubelet status patch with the service container running

and the following intervals are computed:
  scale_up -> pod_created
  scale_up -> container_started

Output files in ./results/<run>/analysis:
  events.csv                - one row per iteration, service and event with its timestamp
  intervals.csv             - one row per iteration and service with the two intervals
  stats.csv                 - mean, median, min, max, variance, standard deviation and IQR of each interval,
                              per service and aggregated over all the services
  slots.csv                 - one row per iteration with the peak used creation slots and their limit,
                              in total and per band (bands enabled only)
  bands.csv                 - one row per iteration and band with the kubelet average wait and creation times
  bands-stats.csv           - mean, median, min, max, variance, standard deviation and IQR of the average
                              wait and creation times of each band, one sample per iteration
  boxplot-<service>.png     - box plot of the two intervals of a single service
  boxplot-all.png           - box plot of the two intervals aggregated over all the services
  boxplot-band-<band>.png   - box plot of the average wait and creation times of a single band

After the analysis the whole run directory is moved to ./results/<test-case>/<run>,
where <test-case> is derived from the experiment configuration.
"""


import argparse
from pathlib import Path
import shutil
import json
import csv
import statistics
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


# File names and paths
RESULTS_BASE_DIR = Path("./results")
OUTPUT_DIR = Path("analysis")
CONFIG_FILE = "config.json"
VANILLA_VANILLA_DIR = "vanilla-vanilla"
PATCH_VANILLA_DIR = "patch-vanilla"
PATCH_PATCH_FIFO_DIR = "patch-patch-fifo"
PATCH_PATCH_BANDS_DIR = "patch-patch-bands"
PATCH_PATCH_STEALING_DIR = "patch-patch-stealing"
PATCH_PATCH_ALL_DIR = "patch-patch-all"
VANILLA_VANILLA_STRESS_DIR = "vanilla-vanilla-stress"
PATCH_PATCH_ALL_STRESS_DIR = "patch-patch-all-stress"

# Services metadata
DEPLOYMENT_SERVICE_BASE_NAME = "knservice-deployment"
RTRESOURCE_SERVICE_BASE_NAME = "knservice-rtresource"

# Critical services levels range (high band)
CRITICAL_LEVEL_FROM = 1
CRITICAL_LEVEL_TO = 10

# Iteration files
ITERATION_PREFIX = "iteration-"
LOKI_LOGS_FILE = "loki-logs.json"
KUBELET_SUMMARY_FILE = "summary.json"
EVENTS_FILE = "events.csv"
INTERVALS_FILE = "intervals.csv"
STATS_FILE = "stats.csv"
SLOTS_FILE = "slots.csv"
BANDS_FILE = "bands.csv"
BANDS_STATS_FILE = "bands-stats.csv"


# Intervals and control plane statistics
INTERVAL_NAMES = ["scale_up_to_pod_created_ms", "scale_up_to_container_started_ms"]
BOXPLOT_PREFIX = "boxplot-"
INTERVAL_LABELS = ["scale-up → pod created", "scale-up → container started"]
AGGREGATED_SERVICE_NAME = "all"


# Kubelet bands metrics
BANDS = ["high", "medium", "low"]
BAND_METRIC_NAMES = ["avg_wait_ms", "avg_creation_ms"]
BAND_METRIC_LABELS = ["avg wait", "avg creation"]
BAND_BOXPLOT_PREFIX = "boxplot-band-"

# Statistics header
STATS_HEADER = ["count", "mean_ms", "median_ms", "min_ms", "max_ms", "variance_ms2", "std_dev_ms", "iqr_ms"]


# --------------------------------------------------------------------------
# Utility Functions
# --------------------------------------------------------------------------


def parse_args():
    """
    Retrieves the input arguments of the script
    """
    parser = argparse.ArgumentParser(description="Analyze the Kubernetes audit logs of an orchestration experiment.")
    parser.add_argument("-e", dest="run", required=True, help="name of the run results directory")
    return parser.parse_args()


def scaled(value, n):
    """
    Integer or percentage of n, rounded down as the preemptive kubelet does
    """
    if value.endswith("%"):
        return n * int(value[:-1]) // 100
    return int(value)


def get_service_names(config):
    """
    Names of the critical KSVCs
    """
    base = RTRESOURCE_SERVICE_BASE_NAME if config["test_type"] == "RTResource" else DEPLOYMENT_SERVICE_BASE_NAME
    levels = CRITICAL_LEVEL_TO - CRITICAL_LEVEL_FROM + 1
    names = []
    for j in range(1, config["number_of_services"] + 1):
        level = CRITICAL_LEVEL_FROM + (j - 1) % levels
        names.append(f"{base}-{level}-{j}")
    return names


def get_test_case_dir(config):
    """
    Test case directory of the run, None if the configuration matches no test case
    """
    if config["kubelet_type"] == "Vanilla":
        if config["test_type"] == "Deployment":
            return VANILLA_VANILLA_STRESS_DIR if config["deploy_stress"] else VANILLA_VANILLA_DIR
        return None if config["deploy_stress"] else PATCH_VANILLA_DIR

    flags = (config["bands_enabled"], config["stealing_enabled"], config["fifo_enabled"])
    test_cases = {
        (False, False, True): PATCH_PATCH_FIFO_DIR,
        (True, False, False): PATCH_PATCH_BANDS_DIR,
        (True, True, False): PATCH_PATCH_STEALING_DIR,
        (True, True, True): PATCH_PATCH_ALL_DIR,
    }
    test_case = test_cases.get(flags)
    if config["deploy_stress"]:
        return PATCH_PATCH_ALL_STRESS_DIR if test_case == PATCH_PATCH_ALL_DIR else None
    return test_case


def compute_stats(values):
    """
    Count, mean, median, min, max, variance, standard deviation and IQR of a list of values
    """
    q1, _, q3 = statistics.quantiles(values, n=4, method="inclusive")
    return [
        len(values),
        round(statistics.mean(values), 3),
        round(statistics.median(values), 3),
        round(min(values), 3),
        round(max(values), 3),
        round(statistics.variance(values), 3),
        round(statistics.stdev(values), 3),
        round(q3 - q1, 3),
    ]


def write_csv(path, header, rows):
    """
    Write a CSV file with the given header and rows
    """
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def write_boxplot(path, title, data, labels):
    """
    Write a box plot with one box per data series
    """
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.boxplot(data)
    ax.set_xticks(range(1, len(labels) + 1), labels)
    ax.set_ylabel("time (ms)")
    ax.set_title(title)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# --------------------------------------------------------------------------
# Config Retrieval
# --------------------------------------------------------------------------


def load_config(run_dir):
    """
    Load the experiment configuration from the run config.json file.
    Kubelet fields are None when not applicable.
    """
    with open(run_dir / CONFIG_FILE) as f:
        raw = json.load(f)

    config = {
        "test_type": raw["testType"],
        "kubelet_type": raw["kubeletType"],
        "namespace": raw["namespace"],
        "node": raw["experimentNode"],
        "number_of_services": raw["numberOfServices"],
        "number_of_interfering_resources": raw["numberOfInterferingResources"],
        "iterations": raw["iterations"],
        "deploy_stress": raw["deployStress"],
        "criticality_label": None,
        "criticality_max_level": None,
        "criticality_min_level": None,
        "bands_enabled": False,
        "stealing_enabled": False,
        "fifo_enabled": False,
        "max_concurrent_pod_creations": None,
        "bands": None,
    }

    preemptive = raw["preemptive"]
    if preemptive is None:
        return config

    config["criticality_label"] = preemptive["criticalityLabel"]
    config["criticality_max_level"] = preemptive["criticalityMaxLevel"]
    config["criticality_min_level"] = preemptive["criticalityMinLevel"]
    config["bands_enabled"] = preemptive["priorityBandsEnabled"]
    config["stealing_enabled"] = preemptive["priorityBandsStealingEnabled"]
    config["fifo_enabled"] = preemptive["podWorkerFifoSchedulingEnabled"]

    pb = preemptive["priorityBands"]
    if pb is None:
        return config

    n = pb["maxConcurrentPodCreations"]
    high = scaled(pb["high"]["guaranteedConcurrentCreations"], n)
    medium = scaled(pb["medium"]["guaranteedConcurrentCreations"], n)
    config["max_concurrent_pod_creations"] = n
    config["bands"] = {
        "high": {"from": pb["high"]["range"]["from"], "to": pb["high"]["range"]["to"], "guaranteed": high},
        "medium": {"from": pb["medium"]["range"]["from"], "to": pb["medium"]["range"]["to"], "guaranteed": medium},
        "low": {"from": pb["low"]["range"]["from"], "to": pb["low"]["range"]["to"], "guaranteed": n - high - medium},
    }
    return config


# --------------------------------------------------------------------------
# Events Retrieval
# --------------------------------------------------------------------------


def is_scale_up_event(log, namespace):
    """
    Check if a log entry represents a potential scale-up event.
    """
    # Check verb
    if log.get('verb') != 'patch':
        return False
    
    # Check user
    user = log.get('user', {})
    if user.get('username') != 'system:serviceaccount:knative-serving:controller':
        return False
    
    # Check userAgent
    user_agent = log.get('userAgent', '')
    if not user_agent.startswith('autoscaler/'):
        return False
    
    # Check objectRef
    object_ref = log.get('objectRef', {})
    if object_ref.get('resource') != 'deployments' and object_ref.get('resource') != 'rtresources':
        return False
    if object_ref.get('namespace') != namespace:
        return False
    if object_ref.get('apiGroup') != 'apps' and object_ref.get('apiGroup') != 'rtgroup.critical.com':
        return False
    if object_ref.get('apiVersion') != 'v1':
        return False
    
    # check requestObject for replicas field
    request_object = log.get('requestObject', [])
    if not isinstance(request_object, list):
        return False
    
    # Check if there's a patch operation that sets replicas to 1
    has_replicas_patch = False
    for patch_op in request_object:
        if (patch_op.get('op') == 'replace' and 
            patch_op.get('path') == '/spec/replicas' and 
            patch_op.get('value') == 1):
            has_replicas_patch = True
            break
    
    if not has_replicas_patch:
        return False

    # Check response status
    response_status = log.get('responseStatus', {})
    if response_status.get('code') != 200:
        return False
    
    return True


def is_starts_processing_event(log, namespace):
    """
    Check if a log entry represents a starts_processing event.
    NOTE: only used with RTResources.
    """
    # Check verb
    if log.get('verb') != 'update':
        return False
    
    # Check user
    user = log.get('user', {})
    if user.get('username') != 'system:serviceaccount:realtime:preempt-k8s':
        return False
    
    # Check objectRef
    object_ref = log.get('objectRef', {})
    if object_ref.get('resource') != 'rtresources':
        return False
    if object_ref.get('namespace') != namespace:
        return False
    if object_ref.get('apiGroup') != 'rtgroup.critical.com':
        return False
    if object_ref.get('apiVersion') != 'v1':
        return False
    if object_ref.get('subresource') != 'status':
        return False
    
    # Check response status
    response_status = log.get('responseStatus', {})
    if response_status.get('code') != 200:
        return False
    
    # Check responseObject conditions
    response_object = log.get('responseObject', {})
    status = response_object.get('status', {})
    conditions = status.get('conditions', [])
    
    progressing_true = False
    ready_false = False
    progressing_transition_time = None
    ready_transition_time = None
    
    for condition in conditions:
        if condition.get('type') == 'Progressing' and condition.get('status') == 'True':
            progressing_true = True
            progressing_transition_time = condition.get('lastTransitionTime')
        if condition.get('type') == 'Ready' and condition.get('status') == 'False':
            ready_false = True
            ready_transition_time = condition.get('lastTransitionTime')
    
    # Verify both conditions are met and their lastTransitionTime is identical
    if not (progressing_true and ready_false):
        return False
    
    if progressing_transition_time is None or ready_transition_time is None:
        return False
    
    if progressing_transition_time != ready_transition_time:
        return False
    
    return True


def is_pod_created_event(log, namespace):
    """
    Check if a log entry represents a pod creation event
    by the Kube-Manager Controller (Deployment) or Preempt-FaaS (RTResource).
    NOTE: it's the corrsponding starts_processing event for Deployments.
    """
    # Check verb
    if log.get('verb') != 'create':
        return False
    
    # Check user
    user = log.get('user', {})
    if user.get('username') != 'system:serviceaccount:kube-system:replicaset-controller' and user.get('username') != 'system:serviceaccount:realtime:preempt-k8s':
        return False
    
    # Check objectRef
    object_ref = log.get('objectRef', {})
    if object_ref.get('resource') != 'pods':
        return False
    if object_ref.get('namespace') != namespace:
        return False
    if object_ref.get('apiVersion') != 'v1':
        return False
    
    # Check response status
    response_status = log.get('responseStatus', {})
    if response_status.get('code') != 201:
        return False
    
    return True


def is_container_started_event(log, namespace):
    """
    Check if a log entry represents a service container started event.
    """
    # Check verb
    if log.get('verb') != 'patch':
        return False
    
    # Check userAgent (kubelet)
    user_agent = log.get('userAgent', '')
    if not user_agent.startswith('kubelet/'):
        return False
    
    # Check objectRef
    object_ref = log.get('objectRef', {})
    if object_ref.get('resource') != 'pods':
        return False
    if object_ref.get('namespace') != namespace:
        return False
    if object_ref.get('apiVersion') != 'v1':
        return False
    if object_ref.get('subresource') != 'status':
        return False
    
    # Check response status
    response_status = log.get('responseStatus', {})
    if response_status.get('code') != 200:
        return False
    
    # Check responseObject for the service container running
    response_object = log.get('responseObject', {})
    status = response_object.get('status', {})
    container_statuses = status.get('containerStatuses', [])
    
    service_running = False
    for container_status in container_statuses:
        if container_status.get('name') == 'queue-proxy':
            continue
        if 'running' in container_status.get('state', {}):
            service_running = True
    
    if not service_running:
        return False
    
    return True


# --------------------------------------------------------------------------
# Results Parsing
# --------------------------------------------------------------------------


def load_audit_data(file_path, namespace):
    """
    Load an iteration audit logs file, sorted by timestamp and starting from the first scale-up
    """
    with open(file_path, 'r') as f:
        audit_data = json.load(f)

    # Sort logs by timestamp
    audit_data.sort(key=lambda x: int(x.get('timestamp', '0')))

    # Find the timestamp of the first scale-up event across ALL services
    first_scale_up_timestamp = None
    for entry in audit_data:
        if is_scale_up_event(entry.get('log', {}), namespace):
            first_scale_up_timestamp = int(entry.get('timestamp', '0'))
            break

    if first_scale_up_timestamp is None:
        raise ValueError(f"No scale-up events found in audit logs file {file_path}")

    # Filter audit_data to only include logs after the first scale-up
    return [entry for entry in audit_data if int(entry.get('timestamp', '0')) >= first_scale_up_timestamp]


def parse_audit_logs_file(config, audit_data, file_path, service):
    """
    Extract the control plane metrics of a service from the sorted audit logs of an iteration.
    Returns a dict where the keys are the service metrics:
        - scale_up_timestamp;
        - starts_processing_timestamp;
        - pod_created_timestamp;
        - container_started_timestamp.
    """
    controller = "kube-manager"
    if config["test_type"] == "RTResource":
        controller = "preempt-k8s"
    
    if controller == "preempt-k8s":
        service_name = f"{service}-00001-rtresource"
    elif controller == "kube-manager":
        service_name = f"{service}-00001-deployment"
    
    namespace = config["namespace"]
    
    # Initialize metrics dictionary
    service_metrics = {}
    
    # Process each log entry
    for entry in audit_data:
        log = entry.get('log', {})
        
        # Check if this is a scale-up event
        if is_scale_up_event(log, namespace):
            object_ref = log.get('objectRef', {})
            resource_name = object_ref.get('name', '')

            if resource_name != service_name:
                continue

            if 'scale_up_timestamp' in service_metrics:
                raise ValueError(f"Duplicate scale-up event for {service_name} in audit logs file {file_path}")
            service_metrics['scale_up_timestamp'] = int(entry.get('timestamp', '0'))

            print(f"  Scale-up event for {service_name} at timestamp {service_metrics['scale_up_timestamp']}")
            
            continue
        
        # Check if this is a starts_processing event
        if controller == "preempt-k8s" and is_starts_processing_event(log, namespace):
            object_ref = log.get('objectRef', {})
            resource_name = object_ref.get('name', '')
            
            if resource_name != service_name:
                continue
            
            if 'starts_processing_timestamp' in service_metrics:
                raise ValueError(f"Duplicate starts_processing event for {service_name} in audit logs file {file_path}")
            service_metrics['starts_processing_timestamp'] = int(entry.get('timestamp', '0'))

            print(f"  Starts processing event for {service_name} at timestamp {service_metrics['starts_processing_timestamp']}")

            continue
        
        # Check if this is a pod creation event
        if is_pod_created_event(log, namespace):
            request_object = log.get('requestObject', {})
            metadata = request_object.get('metadata', {})
            labels = metadata.get('labels', {})
            resource_name = ""
            if controller == "preempt-k8s":
                resource_name = labels.get('rtresource_name', '')
            elif controller == "kube-manager":
                resource_name = labels.get('app', '') + '-deployment'
            
            if resource_name != service_name:
                continue
            
            if controller == "kube-manager":
                if 'starts_processing_timestamp' in service_metrics:
                    raise ValueError(f"Duplicate starts_processing event for {service_name} in audit logs file {file_path}")
                service_metrics['starts_processing_timestamp'] = int(entry.get('timestamp', '0'))
            
            if 'pod_created_timestamp' in service_metrics:
                raise ValueError(f"Duplicate pod_created event for {service_name} in audit logs file {file_path}")
            service_metrics['pod_created_timestamp'] = int(entry.get('timestamp', '0'))

            print(f"  Pod created event for {service_name} at timestamp {service_metrics['pod_created_timestamp']}")
            
            continue
        
        # Check if this is a pod started event
        if is_container_started_event(log, namespace):
            response_object = log.get('responseObject', {})
            metadata = response_object.get('metadata', {})
            labels = metadata.get('labels', {})
            resource_name = ""
            if controller == "preempt-k8s":
                resource_name = labels.get('rtresource_name', '')
            elif controller == "kube-manager":
                resource_name = labels.get('app', '') + '-deployment'
            
            if resource_name != service_name:
                continue
            
            if 'container_started_timestamp' in service_metrics:
                continue
            service_metrics['container_started_timestamp'] = int(entry.get('timestamp', '0'))

            print(f"  Container started event for {service_name} at timestamp {service_metrics['container_started_timestamp']}")
            
            continue
        
    # Validate that all required events were found
    required_keys = [
        'scale_up_timestamp', 
        'starts_processing_timestamp', 
        'pod_created_timestamp', 
        'container_started_timestamp'
    ]
    for key in required_keys:
        if key not in service_metrics or service_metrics[key] <= 0:
            raise ValueError(f"Missing or invalid event {key} for service {service_name} in audit logs file {file_path}")
    
    return service_metrics


def check_kubelet_summary(config, summary, file_path):
    """
    Check the kubelet analysis summary of an iteration, returns the list of the problems found
    """
    problems = []

    expected_mode = "bands enabled" if config["bands_enabled"] else "bands disabled"
    if summary["mode"] != expected_mode:
        problems.append(f"mode '{summary['mode']}', expected '{expected_mode}'")

    expected_pods = config["number_of_services"] + config["number_of_interfering_resources"]
    if summary["pods"]["total"] != expected_pods:
        problems.append(f"{summary['pods']['total']} pods, expected {expected_pods}")

    if summary["missing_pods"]:
        problems.append(f"{len(summary['missing_pods'])} pods with missing timestamps: {summary['missing_pods']}")

    if summary["slots"] is not None and summary["slots"]["violations"]:
        problems.append(f"{len(summary['slots']['violations'])} limit violations: {summary['slots']['violations']}")

    if summary["order"] is not None and summary["order"]["inversions_within_band"]:
        problems.append(f"{len(summary['order']['inversions_within_band'])} order inversions: {summary['order']['inversions_within_band']}")

    return [f"{file_path}: {problem}" for problem in problems]


# --------------------------------------------------------------------------
# Main Function
# --------------------------------------------------------------------------


def main():
    args = parse_args()
    
    run_dir = RESULTS_BASE_DIR / args.run
    if not run_dir.is_dir():
        raise SystemExit(f"Error: run directory '{run_dir}' not found")

    config = load_config(run_dir)
    
    # Resolve the test case directory before the analysis
    test_case = get_test_case_dir(config)
    if test_case is None:
        raise SystemExit("Error: the experiment configuration does not match any expected test case")
    destination = RESULTS_BASE_DIR / test_case / args.run
    if destination.exists():
        raise SystemExit(f"Error: destination directory '{destination}' already exists")

    # Iteration directories, sorted by iteration number
    iteration_dirs = sorted(run_dir.glob(f"{ITERATION_PREFIX}*"),
                            key=lambda d: int(d.name.removeprefix(ITERATION_PREFIX)))
    if len(iteration_dirs) != config["iterations"]:
        raise SystemExit(f"Error: found {len(iteration_dirs)} iterations, expected {config['iterations']}")

    # Check the kubelet analysis of every iteration before the analysis
    problems = []
    slots_rows = []
    bands_rows = []
    for iteration_dir in iteration_dirs:
        iteration = int(iteration_dir.name.removeprefix(ITERATION_PREFIX))
        file_path = iteration_dir / KUBELET_SUMMARY_FILE
        with open(file_path) as f:
            kubelet_summary = json.load(f)
        problems += check_kubelet_summary(config, kubelet_summary, file_path)

        slots = kubelet_summary["slots"]
        if slots is not None:
            row = [iteration]
            for key in ["total", "high", "medium", "low"]:
                row += [slots["peak"][key], slots["expected_limits"][key]]
            slots_rows.append(row)
        for band in BANDS:
            band_summary = kubelet_summary["bands"][band]
            bands_rows.append([iteration, band] + [band_summary[metric] for metric in BAND_METRIC_NAMES])
    if problems:
        print("\n".join(problems))
        raise SystemExit(f"Error: {len(problems)} problems found in the kubelet analysis")
    
    services = get_service_names(config)
    events_rows = []
    intervals_rows = []
    
    print("###################################")
    print("Starting the experiment run analysis...")
    print("###################################")
    print("")

    for iteration_dir in iteration_dirs:
        iteration = int(iteration_dir.name.removeprefix(ITERATION_PREFIX))
        
        print("")
        print(f"Analyzing iteration {iteration}...")
        print("")
        file_path = iteration_dir / LOKI_LOGS_FILE
        audit_data = load_audit_data(file_path, config["namespace"])

        for service in services:
            metrics = parse_audit_logs_file(config, audit_data, file_path, service)

            events_rows.append([iteration, service, "scale_up", metrics["scale_up_timestamp"]])
            if config["test_type"] == "RTResource":
                events_rows.append([iteration, service, "starts_processing", metrics["starts_processing_timestamp"]])
            else:
                events_rows.append([iteration, service, "starts_processing", metrics["pod_created_timestamp"]])
            events_rows.append([iteration, service, "pod_created", metrics["pod_created_timestamp"]])
            events_rows.append([iteration, service, "container_started", metrics["container_started_timestamp"]])

            scale_up = metrics["scale_up_timestamp"]
            intervals_rows.append([
                iteration,
                service,
                (metrics["pod_created_timestamp"] - scale_up) / 1e6,
                (metrics["container_started_timestamp"] - scale_up) / 1e6,
            ])

    # Generate output files
    output_dir = run_dir / OUTPUT_DIR
    output_dir.mkdir(exist_ok=True)
    write_csv(output_dir / EVENTS_FILE, ["iteration", "service", "event", "timestamp_ns"], events_rows)
    write_csv(output_dir / INTERVALS_FILE, ["iteration", "service"] + INTERVAL_NAMES, intervals_rows)
    if slots_rows:
        write_csv(output_dir / SLOTS_FILE,
                  ["iteration", "peak_total", "limit_total", "peak_high", "limit_high",
                   "peak_medium", "limit_medium", "peak_low", "limit_low"],
                  slots_rows)
    write_csv(output_dir / BANDS_FILE, ["iteration", "band"] + BAND_METRIC_NAMES, bands_rows)
    
    # Control plane statistics per service and aggregated over all the services
    control_stats_rows = []
    for service in services + [AGGREGATED_SERVICE_NAME]:
        if service == AGGREGATED_SERVICE_NAME:
            rows = intervals_rows
        else:
            rows = [row for row in intervals_rows if row[1] == service]
        data = []
        for k, interval in enumerate(INTERVAL_NAMES):
            values = [row[2 + k] for row in rows]
            control_stats_rows.append([service, interval] + compute_stats(values))
            data.append(values)
        write_boxplot(output_dir / f"{BOXPLOT_PREFIX}{service}.png", f"{args.run} - {service}", data, INTERVAL_LABELS)
    write_csv(output_dir / STATS_FILE, ["service", "interval"] + STATS_HEADER, control_stats_rows)
    
    # Statistics and box plots per band, one sample per iteration
    bands_stats_rows = []
    for band in BANDS:
        rows = [row for row in bands_rows if row[1] == band]
        data = []
        for k, metric in enumerate(BAND_METRIC_NAMES):
            values = [row[2 + k] for row in rows if row[2 + k] is not None]
            bands_stats_rows.append([band, metric] + compute_stats(values))
            data.append(values)
        write_boxplot(output_dir / f"{BAND_BOXPLOT_PREFIX}{band}.png", f"{args.run} - {band} band", data, BAND_METRIC_LABELS)
    write_csv(output_dir / BANDS_STATS_FILE, ["band", "metric"] + STATS_HEADER, bands_stats_rows)

    # Move the run to its test case directory
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(run_dir), str(destination))
    print(f"Run moved to {destination}")
    
    print("")
    print("###################################")
    print("Experiment run analysis completed!")
    print("###################################")
    

# --------------------------------------------------------------------------
# Entry Point
# --------------------------------------------------------------------------
if __name__ == "__main__":
    main()
