import os
import sys
import csv
import re
import json
import matplotlib.pyplot as plt
import numpy as np


def parse_status_file(file_path):
    """
    Parse a status file and extract its metrics.
    Returns a dict with issued, completed, target_rps, real_rps.
    """
    data = {}
    try:
        with open(file_path, 'r') as f:
            content = f.read()
            
        # Extract values using regex
        issued_match = re.search(r'Issued:\s*(\d+)', content)
        completed_match = re.search(r'Completed:\s*(\d+)', content)
        target_rps_match = re.search(r'Target RPS:\s*([\d.]+)', content)
        real_rps_match = re.search(r'Real RPS:\s*([\d.]+)', content)
        
        if not all([issued_match, completed_match, target_rps_match, real_rps_match]):
            raise ValueError(f"Missing fields in {file_path}")
        
        data['issued'] = int(issued_match.group(1))
        data['completed'] = int(completed_match.group(1))
        data['target_rps'] = float(target_rps_match.group(1))
        data['real_rps'] = float(real_rps_match.group(1))
        
        # Validate that values are not zero or empty
        if data['issued'] == 0:
            raise ValueError(f"Issued is 0 in {file_path}")
        if data['completed'] == 0:
            raise ValueError(f"Completed is 0 in {file_path}")
        if data['target_rps'] == 0:
            raise ValueError(f"Target RPS is 0 in {file_path}")
        if data['real_rps'] == 0:
            raise ValueError(f"Real RPS is 0 in {file_path}")
        
        return data
    except Exception as e:
        raise ValueError(f"Error parsing {file_path}: {str(e)}")


def parse_rps_file(file_path):
    """
    Parse an RPS file containing latency values (one per line).
    Returns a list of integer latency values.
    """
    try:
        with open(file_path, 'r') as f:
            lines = f.readlines()
        
        latencies = []
        for line in lines:
            line = line.strip()
            if line:
                try:
                    latencies.append(int(line))
                except ValueError:
                    raise ValueError(f"Invalid latency value '{line}' in {file_path}")
        
        if not latencies:
            raise ValueError(f"No latency values found in {file_path}")
        
        return latencies
    except Exception as e:
        raise ValueError(f"Error parsing {file_path}: {str(e)}")


def is_scale_up_event(log):
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
    if object_ref.get('namespace') != 'default':
        return False
    if object_ref.get('apiGroup') != 'apps' and object_ref.get('apiGroup') != 'rtgroup.critical.com':
        return False
    if object_ref.get('apiVersion') != 'v1':
        return False
    
    # Check response status
    response_status = log.get('responseStatus', {})
    if response_status.get('code') != 200:
        return False
    
    return True


def is_starts_processing_event(log):
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
    if object_ref.get('namespace') != 'default':
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


def is_pod_created_event(log):
    """
    Check if a log entry represents a pod creation event.
    NOTE: used also as starts_processing event for Deployments.
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
    if object_ref.get('namespace') != 'default':
        return False
    if object_ref.get('apiVersion') != 'v1':
        return False
    
    # Check response status
    response_status = log.get('responseStatus', {})
    if response_status.get('code') != 201:
        return False
    
    return True


def is_pod_started_event(log):
    """
    Check if a log entry represents a pod started event (kubelet patch).
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
    if object_ref.get('namespace') != 'default':
        return False
    if object_ref.get('apiVersion') != 'v1':
        return False
    if object_ref.get('subresource') != 'status':
        return False
    
    # Check response status
    response_status = log.get('responseStatus', {})
    if response_status.get('code') != 200:
        return False
    
    # Check responseObject for Running phase and all conditions True
    response_object = log.get('responseObject', {})
    status = response_object.get('status', {})
    
    if status.get('phase') != 'Running':
        return False
    
    conditions = status.get('conditions', [])
    required_conditions = ['PodReadyToStartContainers', 'Initialized', 'Ready', 'ContainersReady', 'PodScheduled']
    
    conditions_status = {}
    for condition in conditions:
        cond_type = condition.get('type')
        if cond_type in required_conditions:
            conditions_status[cond_type] = condition.get('status')
    
    # Verify all required conditions are True
    for req_cond in required_conditions:
        if conditions_status.get(req_cond) != 'True':
            return False
    
    return True


def parse_audit_logs_file(file_path, controller, service):
    """
    Parse a json audit logs file and extract control plane metrics.
    Returns a dict where the keys are the service metrics:
        - scale_up_timestamp;
        - starts_processing_timestamp;
        - pod_created_timestamp;
        - pod_started_timestamp.
    """
    if controller not in ["preempt-k8s", "kube-manager"]:
        raise ValueError(f"Unsupported controller: {controller}")
    
    if controller == "preempt-k8s":
        service_name = f"{service}-00001-deployment"
    elif controller == "kube-manager":
        service_name = f"{service}-00001-rtresource"

    # Load audit logs
    with open(file_path, 'r') as f:
        audit_data = json.load(f)
    
    # Sort logs by timestamp
    audit_data.sort(key=lambda x: int(x.get('timestamp', '0')))

    # Initialize metrics dictionary
    service_metrics = {}

    # Find the timestamp of the first scale-up event across ALL services
    first_scale_up_timestamp = None

    for entry in audit_data:
        log = entry.get('log', {})
        
        if is_scale_up_event(log):
            first_scale_up_timestamp = int(entry.get('timestamp', '0'))
            print(f"  First scale-up found at timestamp {first_scale_up_timestamp}")
            break
    
    if first_scale_up_timestamp is None:
        print(f"  Warning: No scale-up events found in logs")
        return {}

    # Filter audit_data to only include logs after the first scale-up
    audit_data = [entry for entry in audit_data if int(entry.get('timestamp', '0')) >= first_scale_up_timestamp]
    print(f"  After filtering: {len(audit_data)} audit log entries remain")

    # Process each log entry
    for entry in audit_data:
        log = entry.get('log', {})
        
        # Check if this is a scale-up event
        if is_scale_up_event(log):
            object_ref = log.get('objectRef', {})
            resource_name = object_ref.get('name', '')

            if resource_name != service_name:
                continue

            if 'scale_up_timestamp' in service_metrics:
                raise ValueError(f"Duplicate scale-up event for {service_name}")
            service_metrics['scale_up_timestamp'] = int(entry.get('timestamp', '0'))

            print(f"  Scale-up event for {service_name} at timestamp {service_metrics['scale_up_timestamp']}")
            
            continue

        # Check if this is a starts_processing event
        if controller == "preempt-k8s" and is_starts_processing_event(log):
            object_ref = log.get('objectRef', {})
            resource_name = object_ref.get('name', '')
            
            if resource_name != service_name:
                continue
            
            if 'starts_processing_timestamp' in service_metrics:
                raise ValueError(f"Duplicate starts_processing event for {service_name}")
            service_metrics['starts_processing_timestamp'] = int(entry.get('timestamp', '0'))

            print(f"  Starts processing event for {service_name} at timestamp {service_metrics['starts_processing_timestamp']}")

            continue

        # Check if this is a pod creation event
        if is_pod_created_event(log):
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
                    raise ValueError(f"Duplicate starts_processing event for {service_name}")
                service_metrics['starts_processing_timestamp'] = int(entry.get('timestamp', '0'))
            
            if 'pod_created_timestamp' in service_metrics:
                    raise ValueError(f"Duplicate pod_created event for {service_name}")
            service_metrics['pod_created_timestamp'] = int(entry.get('timestamp', '0'))

            print(f"  Pod created event for {service_name} at timestamp {service_metrics['pod_created_timestamp']}")
            
            continue
        
        # Check if this is a pod started event
        if is_pod_started_event(log):
            # Extract deployment_name from responseObject metadata labels
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
            
            if 'pod_started_timestamp' in service_metrics:
                raise ValueError(f"Duplicate pod_started event for {service_name}")
            service_metrics['pod_started_timestamp'] = int(entry.get('timestamp', '0'))

            print(f"  Pod started event for {service_name} at timestamp {service_metrics['pod_started_timestamp']}")
            
            continue
    
    # Validate that all required events were found
    required_keys = [
        'scale_up_timestamp', 
        'starts_processing_timestamp', 
        'pod_created_timestamp', 
        'pod_started_timestamp'
    ]
    for key in required_keys:
        if key not in service_metrics or service_metrics[key] <= 0:
            raise ValueError(f"Missing or invalid event {key} for service {service_name} in audit logs")
    
    return service_metrics
                    

def save_boxplot(data, labels, title, ylabel, filename, directory):
    fig, ax = plt.subplots(figsize=(6, 6))
    bp = ax.boxplot(data, labels=labels, patch_artist=True)
    
    num_boxes = len(labels)
    cmap = plt.get_cmap('tab10') 
    
    for i, patch in enumerate(bp['boxes']):
        patch.set_facecolor(cmap(i % 10))
        patch.set_edgecolor('black')
        
    for median in bp['medians']:
        median.set(color='black', linewidth=2)
        
    ax.grid(True, axis='y', linestyle='--', alpha=0.7)
    ax.set_xlabel('Services', fontsize=12)
    ax.set_ylabel(ylabel, fontsize=12)
    ax.set_title(title, fontsize=14, fontweight='bold')
    
    plt.xticks(rotation=45)
    plt.tight_layout()
    
    plot_path = os.path.join(directory, filename)
    plt.savefig(plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"{title} saved to: {plot_path}")


def save_cdf_plot(all_data, labels, title, xlabel, filename, directory):
    fig, ax = plt.subplots(figsize=(8, 6))
    num_services = len(all_data)
    cmap = plt.get_cmap('tab10')
    
    for i, service_data in enumerate(all_data):
        # Calcolo della CDF
        sorted_data = np.sort(service_data)
        # Protezione per array vuoti
        if len(sorted_data) == 0: continue 
        
        cdf = np.arange(1, len(sorted_data) + 1) / len(sorted_data)
        
        # Plot con colore automatico
        ax.plot(sorted_data, cdf, 
                label=labels[i], 
                color=cmap(i % 10), 
                marker='o', 
                linestyle='-', 
                linewidth=2, 
                markersize=4)
    
    ax.grid(True, linestyle='--', alpha=0.7)
    ax.set_xlabel(xlabel, fontsize=12)
    ax.set_ylabel('CDF', fontsize=12)
    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.legend()
    
    plt.tight_layout()
    plot_path = os.path.join(directory, filename)
    plt.savefig(plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"{title} saved to: {plot_path}")


def main():
    # Validate command line arguments
    if len(sys.argv) != 4:
        print("Usage: python analyze_results.py <path_to_results_directory> <number_of_services> <controller_name>")
        sys.exit(1)
    
    root_path = sys.argv[1]
    num_services = int(sys.argv[2])
    controller_name = sys.argv[3]
    
    # Check if the provided path is a valid directory
    if not os.path.isdir(root_path):
        print(f"Error: {root_path} is not a valid directory!")
        sys.exit(1)

    # Check if number of services is valid
    if num_services <= 0:
        print("Error: Number of services must be a positive integer!")
        sys.exit(1)
    
    # Check if processed_results directory already exists
    processed_dir = os.path.join(root_path, "processed_results")
    if os.path.exists(processed_dir):
        print(f"Error: Directory {processed_dir} already exists!")
        sys.exit(1)
    
    print(f"Scanning directories in {root_path}...")

    # Count status and rps files and check if there are exactly 30 status files, 30 rps files and 30 audit logs files
    status_files = {}
    rps_files = {}
    for i in range(num_services):
        all_files = []
        service_name = f"service-{i+1}"
        service_path = os.path.join(root_path, f"service-{i+1}")

        if os.path.isdir(service_path):
            all_files = os.listdir(service_path)
            status_files[service_name] = [f for f in all_files if f.startswith("iteration") and os.path.isfile(os.path.join(service_path, f))]
            rps_files[service_name] = [f for f in all_files if f.startswith("rps") and os.path.isfile(os.path.join(service_path, f))]
    
            status_count = len(status_files[service_name])
            rps_count = len(rps_files[service_name])
            
            print(f"Found {status_count} status files and {rps_count} rps files for {service_name}!")
            
            if status_count != 30:
                print(f"Error: Expected exactly 30 status files, but found {status_count} for {service_name}!")
                sys.exit(1)
            
            if rps_count != 30:
                print(f"Error: Expected exactly 30 rps files, but found {rps_count} for {service_name}!")
                sys.exit(1)
    
    all_audit_files = []
    all_audit_files = os.listdir(root_path)
    audit_files = [f for f in all_audit_files if f.startswith("loki-logs-iteration") and os.path.isfile(os.path.join(root_path, f))]
    audit_count = len(audit_files)

    print(f"Found {audit_count} audit logs files in total!")

    if audit_count != 30:
        print(f"Error: Expected exactly 30 audit logs files, but found {audit_count}!")
        sys.exit(1)
    
    print("File count validation passed!")
    
    # Create processed_results directory
    processed_dir = os.path.join(root_path, "processed_results")
    if not os.path.exists(processed_dir):
        os.makedirs(processed_dir)
        print(f"Created directory: {processed_dir}!")
    else:
        print(f"Directory already exists: {processed_dir}!")
    
    # Process audit logs files
    print("\nProcessing audit logs files for each service...")

    mean_starts_processing_delay = {}
    max_starts_processing_delay = {}
    all_starts_processing_delays = []

    mean_pod_creation_delay = {}
    max_pod_creation_delay = {}
    all_pod_creation_delays = []

    mean_pod_startup_delay = {}
    max_pod_startup_delay = {}
    all_pod_startup_delays = []

    for i in range(num_services):

        starts_processing_delays = []
        pod_creation_delays = []
        pod_start_delays = []

        for j in range(30):
            service_id = f"rnn-serving-python-{i+1}"
            service_name = f"service-{i+1}"
            audit_logs_file = os.path.join(root_path, f"loki-logs-iteration-{j+1}.json")
            
            if os.path.isfile(audit_logs_file):
                print(f"\nProcessing audit logs for {service_id}...")
                try:
                    service_metrics = parse_audit_logs_file(audit_logs_file, controller_name, service_id)
                    
                    if service_metrics:
                        # Calculate delays (converting nanoseconds to milliseconds)
                        if controller_name == "preempt-k8s":
                            starts_processing_delays.append( (service_metrics['starts_processing_timestamp'] - service_metrics['scale_up_timestamp']) / 1_000_000 )
                        elif controller_name == "kube-manager":
                            starts_processing_delays.append( (service_metrics['pod_created_timestamp'] - service_metrics['scale_up_timestamp']) / 1_000_000 )
                        pod_creation_delays.append( (service_metrics['pod_created_timestamp'] - service_metrics['scale_up_timestamp']) / 1_000_000 )
                        pod_start_delays.append( (service_metrics['pod_started_timestamp'] - service_metrics['scale_up_timestamp']) / 1_000_000 )
                    else:
                        print(f"No control plane metrics extracted for {service_id}.")
                except ValueError as e:
                    print(f"Error: {e}")
                    sys.exit(1)
            else:
                print(f"Warning: Audit logs file not found: {audit_logs_file}")  
        all_starts_processing_delays.append(starts_processing_delays)
        all_pod_creation_delays.append(pod_creation_delays)
        all_pod_startup_delays.append(pod_start_delays)

        # Calculate statistics for starts_processing delays
        mean_starts_processing_delay[service_name] = sum(starts_processing_delays) / len(starts_processing_delays)
        max_starts_processing_delay[service_name] = max(starts_processing_delays)

        # Calculate statistics for pod creation delays
        mean_pod_creation_delay[service_name] = sum(pod_creation_delays) / len(pod_creation_delays)
        max_pod_creation_delay[service_name] = max(pod_creation_delays)

        # Calculate statistics for pod start delays
        mean_pod_startup_delay[service_name] = sum(pod_start_delays) / len(pod_start_delays)
        max_pod_startup_delay[service_name] = max(pod_start_delays)

    # Process all status and rps files
    print("\nProcessing status and rps files for each service...")

    mean_lost = {}
    max_lost = {}
    all_lost_requests = []
    mean_completed = {}
    max_completed = {}
    all_completed_requests = []

    mean_of_mean_latencies = {}
    all_mean_latencies = []
    mean_of_max_latencies = {}
    all_max_latencies = []

    service_labels = []

    for i in range(num_services):
        service_name = f"service-{i+1}"
        service_labels.append(service_name)

        # Process all status files for the current service
        print(f"\nProcessing status files for {service_name}...")

        lost_requests = []
        completed_requests = []
        
        for status_file in sorted(status_files[service_name]):
            file_path = os.path.join(root_path, service_name, status_file)
            try:
                data = parse_status_file(file_path)
                lost = data['issued'] - data['completed']
                lost_requests.append(lost)
                completed_requests.append(data['completed'])
            except ValueError as e:
                print(f"Error: {e}")
                sys.exit(1)
        all_lost_requests.append(lost_requests)
        all_completed_requests.append(completed_requests)

        # Calculate statistics for lost requests
        mean_lost[service_name] = sum(lost_requests) / len(lost_requests)
        max_lost[service_name] = max(lost_requests)

        # Calculate statistics for completed requests
        mean_completed[service_name] = sum(completed_requests) / len(completed_requests)
        max_completed[service_name] = max(completed_requests)
        
        # Process all rps files for the current service
        print(f"\nProcessing rps files for {service_name}...")
    
        mean_latencies = []
        max_latencies = []
        
        for rps_file in sorted(rps_files[service_name]):
            file_path = os.path.join(root_path, service_name, rps_file)
            try:
                latencies = parse_rps_file(file_path)
                mean_lat = sum(latencies) / len(latencies)
                max_lat = max(latencies)
                mean_latencies.append(mean_lat / 1000)  # Convert to milliseconds from microseconds
                max_latencies.append(max_lat / 1000)  # Convert to milliseconds from microseconds
            except ValueError as e:
                print(f"Error: {e}")
                sys.exit(1)
        all_mean_latencies.append(mean_latencies)
        all_max_latencies.append(max_latencies)
        
        # Calculate statistics for latencies
        mean_of_mean_latencies[service_name] = sum(mean_latencies) / len(mean_latencies)
        mean_of_max_latencies[service_name] = sum(max_latencies) / len(max_latencies)
    
    # Write results to CSV
    csv_path = os.path.join(processed_dir, "metrics.csv")
    with open(csv_path, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['Service',
                         'Mean Latencies [ms]', 'Max Latencies [ms]',
                         'Mean Lost Requests', 'Max Lost Requests',
                         'Mean Completed Requests', 'Max Completed Requests',
                         'Starts Processing Delay Mean [ms]', 'Starts Processing Delay Max [ms]',
                         'Pod Creation Delay Mean [ms]', 'Pod Creation Delay Max [ms]',
                         'Pod Startup Delay Mean [ms]', 'Pod Startup Delay Max [ms]'
                         ])
        for i in range(num_services):
            service_name = f"service-{i+1}"
            writer.writerow([
                service_name,
                f"{mean_of_mean_latencies[service_name]:.2f}", f"{mean_of_max_latencies[service_name]:.2f}",
                f"{mean_lost[service_name]:.2f}", max_lost[service_name],
                f"{mean_completed[service_name]:.2f}", max_completed[service_name],
                f"{mean_starts_processing_delay[service_name]:.2f}", f"{max_starts_processing_delay[service_name]:.2f}",
                f"{mean_pod_creation_delay[service_name]:.2f}", f"{max_pod_creation_delay[service_name]:.2f}",
                f"{mean_pod_startup_delay[service_name]:.2f}", f"{max_pod_startup_delay[service_name]:.2f}"
            ])
    print(f"\nResults saved to: {csv_path}")
    
    # Create box plots
    print("\nCreating box plots...")

    box_plots_config = [
        (all_starts_processing_delays, "Starts Processing Delays Box Plot", "Delays [ms]", "boxplot_starts_processing_delays.png"),
        (all_pod_creation_delays, "Pod Creation Delays Box Plot", "Delays [ms]", "boxplot_pod_creation_delays.png"),
        (all_pod_startup_delays, "Pod Startup Delays Box Plot", "Delays [ms]", "boxplot_pod_startup_delays.png"),
        (all_lost_requests, "Lost Requests Box Plot", "Number of Requests", "boxplot_lost_requests.png"),
        (all_completed_requests, "Completed Requests Box Plot", "Number of Requests", "boxplot_completed_requests.png"),
        (all_mean_latencies, "Mean Latencies Box Plot", "Latencies [ms]", "boxplot_mean_latencies.png"),
        (all_max_latencies, "Max Latencies Box Plot", "Latencies [ms]", "boxplot_max_latencies.png")
    ]

    for data, title, ylabel, fname in box_plots_config:
        save_boxplot(data, service_labels, title, ylabel, fname, processed_dir)
    
    # Create CDF plots
    print("\nCreating CDF plots...")

    cdf_plots_configs = [
        (all_starts_processing_delays, "CDF of Starts Processing Delays", "Starts Processing Delays [ms]", "cdf_starts_processing_delays.png"),
        (all_pod_creation_delays, "CDF of Pod Creation Delays", "Pod Creation Delays [ms]", "cdf_pod_creation_delays.png"),
        (all_pod_startup_delays, "CDF of Pod Startup Delays", "Pod Startup Delays [ms]", "cdf_pod_startup_delays.png"),
        (all_mean_latencies, "CDF of Mean Latencies", "Mean Latencies [ms]", "cdf_mean_latencies.png"),
        (all_max_latencies, "CDF of Max Latencies", "Max Latencies [ms]", "cdf_max_latencies.png")
    ]

    for data, title, xlabel, fname in cdf_plots_configs:
        save_cdf_plot(data, service_labels, title, xlabel, fname, processed_dir)


if __name__ == "__main__":
    main()
