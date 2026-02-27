import sys
import os
import json
import re
import glob
import textwrap
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D
import numpy as np


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
        service_name = f"{service}-00001-rtresource"
    elif controller == "kube-manager":
        service_name = f"{service}-00001-deployment"

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


def create_scatter_plot(all_experiment_events, output_path, mode, service_name, experiments_per_band=5):
    """
    Create a scatter plot with experiment bands on Y-axis and time on X-axis.
    
    Args:
        all_experiment_events: List of tuples (experiment_index, events_list)
        output_path: Path to save the plot
        mode: 'kube-manager' or 'preempt-k8s'
        service_name: Name of the monitored service
        experiments_per_band: Number of experiments to group in each band (default 5)
    """
    # Define bright colors for each event type (optimized for dark background)
    colors = {
        'scale-up': '#00D9FF',              # Cyan bright
        'starts_processing': '#FF3366',     # Pink/Red bright
        'pod_created': '#FFB800',           # Orange bright
        'pod_started': '#00FF7F',           # Spring green bright
    }
    
    # Define markers for each event type
    markers = {
        'scale-up': 'D',           # Diamond
        'starts_processing': 's',  # Square
        'pod_created': 'o',        # Circle
        'pod_started': '^'         # Triangle
    }
    
    total_experiments = len(all_experiment_events)
    
    # Create figure with default style
    plt.style.use('default')
    fig, ax = plt.subplots(figsize=(24, max(10, total_experiments * 0.6)))
    
    # Set white background for figure and dark gray for plot area
    fig.patch.set_facecolor('#FFFFFF')
    ax.set_facecolor('#FFFFFF')
    
    import numpy as np
    
    # Store points by event type and experiment for connecting lines
    points_by_type_and_exp = {
        'scale-up': [],
        'starts_processing': [],
        'pod_created': [],
        'pod_started': []
    }
    
    # Plot events for each experiment
    for exp_idx, events in all_experiment_events:
        # Place experiments in a single column (one row per experiment).
        # Use reversed order so iteration 0 appears at the top.
        y_base = total_experiments - 1 - exp_idx
        
        # Group events by type
        events_by_type = {}
        for event in events:
            event_type = event['type']
            
            if event_type not in events_by_type:
                events_by_type[event_type] = []
            events_by_type[event_type].append(event['timestamp'])
        
        # Plot each event type and store points per experiment
        exp_points_by_type = {
            'scale-up': [],
            'starts_processing': [],
            'pod_created': [],
            'pod_started': []
        }
        
        for event_type, timestamps in events_by_type.items():
            # Add very small vertical spread to separate exact overlaps
            y_jitter = np.random.uniform(-0.01, 0.01, len(timestamps))
            y_values = [y_base + j for j in y_jitter]
            
            # Store points for this experiment
            for t, y in zip(timestamps, y_values):
                exp_points_by_type[event_type].append((t, y))
            
            ax.scatter(
                timestamps, 
                y_values, 
                c=colors[event_type], 
                marker=markers[event_type],
                s=500,
                alpha=0.9,
                edgecolors='black',
                linewidth=0.7,
                zorder=3
            )
        
        # Store experiment points grouped by type
        for event_type in points_by_type_and_exp.keys():
            if exp_points_by_type[event_type]:
                points_by_type_and_exp[event_type].append(exp_points_by_type[event_type])
    
    # Draw connecting lines for each event type
    for event_type, experiments_points in points_by_type_and_exp.items():
        if not experiments_points:
            continue
        
        prev_last_point = None
        
        for exp_points in experiments_points:
            if not exp_points:
                continue
            
            # Sort points within this experiment by timestamp
            exp_points_sorted = sorted(exp_points, key=lambda p: p[0])
            
            # If there's a previous experiment, connect to it with dashed line
            if prev_last_point is not None:
                first_point = exp_points_sorted[0]
                # Vertical line from last point of previous exp to first point of current exp
                ax.plot(
                    [prev_last_point[0], first_point[0]],
                    [prev_last_point[1], first_point[1]],
                    color=colors[event_type],
                    alpha=0.3,
                    linewidth=5,
                    linestyle='--',
                    zorder=2
                )
            
            # Connect points within this experiment
            for i in range(len(exp_points_sorted) - 1):
                x1, y1 = exp_points_sorted[i]
                x2, y2 = exp_points_sorted[i + 1]
                
                ax.plot(
                    [x1, x2],
                    [y1, y2],
                    color=colors[event_type],
                    alpha=0.3,
                    linewidth=1.5,
                    linestyle='--',
                    zorder=2
                )
            
            # Store last point for connecting to next experiment
            prev_last_point = exp_points_sorted[-1]
    
    # Set Y-axis ticks and labels: one tick per experiment
    y_ticks = [i for i in range(total_experiments)]
    ax.set_yticks(y_ticks)
    y_labels = [str(i + 1) if ((i + 1) % 5 == 0) else '' for i in range(total_experiments)]
    ax.set_yticklabels(y_labels, fontsize=28, color='black')
    ax.set_ylim(-0.5, total_experiments - 0.5)
    
    # Customize tick colors
    ax.tick_params(axis='x', colors='black', labelsize=40)
    ax.tick_params(axis='y', colors='black', labelsize=40)
    
    # Format X-axis to show seconds with 's' suffix
    from matplotlib.ticker import FuncFormatter
    def format_func(value, tick_number):
        return f'{int(value)}'
    ax.xaxis.set_major_formatter(FuncFormatter(format_func))
    
    # Ensure x starts at zero (no negative ticks) and add vertical lines at x-axis ticks
    ax.xaxis.set_major_locator(MultipleLocator(1))
    ax.set_xlim(left=-0.5)
    # x_ticks = ax.get_xticks()
    # for xt in x_ticks:
    #     ax.axvline(x=xt, color='#BBBBBB', linestyle='--', alpha=0.6, linewidth=1, zorder=1)

    # Add horizontal lines at each experiment tick (same color as x ticks)
    # x_min, x_max = ax.get_xlim()
    # for yt in y_ticks:
    #     ax.hlines(y=yt, xmin=x_min, xmax=x_max, colors='#BBBBBB', linestyles='--', alpha=0.6, linewidth=1, zorder=1)

    ax.grid(axis='x', color='#BBBBBB', linestyle='--', alpha=0.6, linewidth=1, zorder=1)
    ax.grid(axis='y', color='#BBBBBB', linestyle='--', alpha=0.6, linewidth=1, zorder=1)
    
    # Create legend using the same markers as the plot (Line2D handles)
    # Set max width for legend labels (in characters)
    max_label_width = 50

    # Choose a markersize that visually matches the scatter `s=500`
    legend_markersize = 18

    if mode == 'kube-manager':
        # For kube-manager, starts_processing and pod_created are collapsed
        legend_elements = [
            Line2D([0], [0], marker=markers['scale-up'], color='w', markerfacecolor=colors['scale-up'], markeredgecolor='black', markersize=legend_markersize, linestyle='None', label=textwrap.fill('Scale-up', max_label_width)),
            Line2D([0], [0], marker=markers['starts_processing'], color='w', markerfacecolor=colors['starts_processing'], markeredgecolor='black', markersize=legend_markersize, linestyle='None', label=textwrap.fill('Starts Processing / Pod Created', max_label_width)),
            Line2D([0], [0], marker=markers['pod_started'], color='w', markerfacecolor=colors['pod_started'], markeredgecolor='black', markersize=legend_markersize, linestyle='None', label=textwrap.fill('Pod Started', max_label_width))
        ]
    else:
        legend_elements = [
            Line2D([0], [0], marker=markers['scale-up'], color='w', markerfacecolor=colors['scale-up'], markeredgecolor='black', markersize=legend_markersize, linestyle='None', label=textwrap.fill('Scale-up', max_label_width)),
            Line2D([0], [0], marker=markers['starts_processing'], color='w', markerfacecolor=colors['starts_processing'], markeredgecolor='black', markersize=legend_markersize, linestyle='None', label=textwrap.fill('Starts Processing', max_label_width)),
            Line2D([0], [0], marker=markers['pod_created'], color='w', markerfacecolor=colors['pod_created'], markeredgecolor='black', markersize=legend_markersize, linestyle='None', label=textwrap.fill('Pod Created', max_label_width)),
            Line2D([0], [0], marker=markers['pod_started'], color='w', markerfacecolor=colors['pod_started'], markeredgecolor='black', markersize=legend_markersize, linestyle='None', label=textwrap.fill('Pod Started', max_label_width))
        ]
    
    legend = ax.legend(
        handles=legend_elements,
        loc='lower center',
        bbox_to_anchor=(0.5, -0.15),
        fontsize=30,
        ncol=len(legend_elements),
        framealpha=0.95,
        edgecolor='black',
        facecolor='white'
    )
    
    # Set legend text color
    for text in legend.get_texts():
        text.set_color('black')

    # Add axis labels
    ax.set_xlabel('Time (seconds)', fontsize=50, color='black', fontweight='semibold')
    ax.set_ylabel('Experiments', fontsize=50, color='black', fontweight='semibold')
    
    # Set spine colors to black
    for spine in ax.spines.values():
        spine.set_edgecolor('black')
        spine.set_linewidth(1.2)
    
    # Adjust layout
    plt.tight_layout()
    
    # Save plot
    plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
    plt.close()
    
    # Reset style to default for next plots
    plt.style.use('default')
    
    print(f"\nScatter plot saved to: {output_path}")


def is_scale_up_event(log):
    """
    Check if a log entry represents a potential scale-up event.
    """
    if log.get('verb') != 'patch':
        return False
    
    user = log.get('user', {})
    if user.get('username') != 'system:serviceaccount:knative-serving:controller':
        return False
    
    user_agent = log.get('userAgent', '')
    if not user_agent.startswith('autoscaler/'):
        return False
    
    object_ref = log.get('objectRef', {})
    if object_ref.get('resource') != 'deployments' and object_ref.get('resource') != 'rtresources':
        return False
    if object_ref.get('namespace') != 'default':
        return False
    if object_ref.get('apiGroup') != 'apps' and object_ref.get('apiGroup') != 'rtgroup.critical.com':
        return False
    if object_ref.get('apiVersion') != 'v1':
        return False

    request_object = log.get('requestObject', [])
    if not isinstance(request_object, list):
        return False

    has_replicas_patch = False
    for patch_op in request_object:
        if (patch_op.get('op') == 'replace' and 
            patch_op.get('path') == '/spec/replicas' and 
            patch_op.get('value') == 1):
            has_replicas_patch = True
            break
    
    if not has_replicas_patch:
        return False
    
    response_status = log.get('responseStatus', {})
    if response_status.get('code') != 200:
        return False
    
    return True


def is_starts_processing_event(log):
    """
    Check if a log entry represents a starts_processing event.
    NOTE: only used with RTResources.
    """
    if log.get('verb') != 'update':
        return False
    
    user = log.get('user', {})
    if user.get('username') != 'system:serviceaccount:realtime:preempt-k8s':
        return False
    
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
    if log.get('verb') != 'create':
        return False
    
    user = log.get('user', {})
    if user.get('username') != 'system:serviceaccount:kube-system:replicaset-controller' and user.get('username') != 'system:serviceaccount:realtime:preempt-k8s':
        return False
    
    object_ref = log.get('objectRef', {})
    if object_ref.get('resource') != 'pods':
        return False
    if object_ref.get('namespace') != 'default':
        return False
    if object_ref.get('apiVersion') != 'v1':
        return False
    
    response_status = log.get('responseStatus', {})
    if response_status.get('code') != 201:
        return False
    
    return True


def is_pod_started_event(log):
    """
    Check if a log entry represents a pod started event (kubelet patch).
    """
    if log.get('verb') != 'patch':
        return False
    
    user_agent = log.get('userAgent', '')
    if not user_agent.startswith('kubelet/'):
        return False
    
    object_ref = log.get('objectRef', {})
    if object_ref.get('resource') != 'pods':
        return False
    if object_ref.get('namespace') != 'default':
        return False
    if object_ref.get('apiVersion') != 'v1':
        return False
    if object_ref.get('subresource') != 'status':
        return False
    
    response_status = log.get('responseStatus', {})
    if response_status.get('code') != 200:
        return False
    
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
    
    for req_cond in required_conditions:
        if conditions_status.get(req_cond) != 'True':
            return False
    
    return True


def generate_event_scatter_plot(experiment_path, output_path, audit_files, controller_name):
    """
    Generate scatter plot for a specific service.
    
    Args:
        experiment_path: Directory containing the experiment audit log files
        output_path: Directory to save the generated scatter plot
        audit_files: List of audit log file names
        controller_name: 'kube-manager' or 'preempt-k8s'
    """
    service_id = f"video-analytics-standalone-python-1"
    service_label = f"service-1"
    print(f"\nProcessing events for {service_id}...")
    
    # Sort audit files by iteration number
    def extract_iteration_num(filename):
        match = re.search(r'iteration_(\d+)', filename)
        return int(match.group(1)) if match else 0
    
    audit_files_sorted = sorted(audit_files, key=extract_iteration_num)
    
    # Collect events for each experiment
    all_experiment_events = []
    
    for idx, audit_file in enumerate(audit_files_sorted):
        file_path = os.path.join(experiment_path, audit_file)
        iteration_num = extract_iteration_num(audit_file)
        print(f"\nProcessing iteration {iteration_num} ({audit_file})...")
        
        try:
            # Parse audit logs to get timestamps for this service
            metrics = parse_audit_logs_file(file_path, controller_name, service_id)
            
            if not metrics:
                print(f"  Warning: No metrics found for {service_id} in iteration {iteration_num}")
                continue
            
            # Normalize timestamps relative to scale-up event (start at 0)
            scale_up_ts = metrics['scale_up_timestamp']
            
            # Create event list for this experiment
            events = [
                {'type': 'scale-up', 'timestamp': 0}  # Scale-up is always at 0
            ]
            
            # For kube-manager, collapse starts_processing and pod_created
            if controller_name == 'kube-manager':
                # Use starts_processing timestamp (which is same as pod_created)
                events.append({
                    'type': 'starts_processing',
                    'timestamp': (metrics['starts_processing_timestamp'] - scale_up_ts) / 1_000_000_000  # Convert to seconds
                })
            else:
                # For preempt-k8s, keep them separate
                events.append({
                    'type': 'starts_processing',
                    'timestamp': (metrics['starts_processing_timestamp'] - scale_up_ts) / 1_000_000_000  # Convert to seconds
                })
                events.append({
                    'type': 'pod_created',
                    'timestamp': (metrics['pod_created_timestamp'] - scale_up_ts) / 1_000_000_000  # Convert to seconds
                })
            
            events.append({
                'type': 'pod_started',
                'timestamp': (metrics['pod_started_timestamp'] - scale_up_ts) / 1_000_000_000  # Convert to seconds
            })
            
            # Add to list with zero-based index for plotting
            all_experiment_events.append((idx, events))
            
            print(f"  ✓ Successfully processed {len(events)} events")
            
        except Exception as e:
            print(f"  Error processing iteration {iteration_num}: {e}")
            continue
    
    if not all_experiment_events:
        print(f"\nError: No valid data found for {service_id}!")
        return
    
    print(f"\n{len(all_experiment_events)} experiments successfully processed for {service_id}")
    
    # Generate output in given output path
    output_filename = f"scatter_plot_{controller_name}_{service_label}.png"
    output_file_path = os.path.join(output_path, output_filename)
    
    # Create scatter plot with 5 experiments per band
    create_scatter_plot(
        all_experiment_events=all_experiment_events,
        output_path=output_file_path,
        mode=controller_name,
        service_name=service_label,
        experiments_per_band=5
    )


def main():
    # Validate command line arguments
    if len(sys.argv) != 4:
        print("Usage: python scatter-plot.py <path-to-experiment-directory> <path_to_results_directory> <controller_name>")
        sys.exit(1)
    
    experiment_path = sys.argv[1]
    output_path = sys.argv[2]
    controller_name = sys.argv[3]
    
    # Check if the provided experiment path is a valid directory
    if not os.path.isdir(experiment_path):
        print(f"Error: {experiment_path} is not a valid directory!")
        sys.exit(1)
    
    # Check if the provided output path is a valid directory
    if not os.path.isdir(output_path):
        print(f"Error: {output_path} is not a valid directory!")
        sys.exit(1)

    # Check if controller_name is valid
    if controller_name not in ['kube-manager', 'preempt-k8s']:
        print(f"Error: controller_name must be 'kube-manager' or 'preempt-k8s'!")
        sys.exit(1)
    
    # Collect all audit log files
    all_files = os.listdir(experiment_path)
    audit_files = [f for f in all_files if f.startswith("loki-logs-iteration") and f.endswith(".json") and os.path.isfile(os.path.join(experiment_path, f))]
    
    if not audit_files:
        print("Error: No loki-logs-iteration_*.json files found!")
        sys.exit(1)
    
    audit_count = len(audit_files)
    print(f"Found {audit_count} audit logs files in total!")
    
    print(f"\n{'='*60}")
    print(f"Scatter Plot Generator")
    print(f"{'='*60}")
    print(f"Results directory: {output_path}")
    print(f"Controller name: {controller_name}")
    print(f"Total iterations: {audit_count}")
    print(f"{'='*60}")
    
    # Generate scatter plot for service-1 only
    print("\nGenerating scatter plot for service-1...")
    generate_event_scatter_plot(experiment_path, output_path, audit_files, controller_name)
    
    print(f"\n{'='*60}")
    print("Processing complete!")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
