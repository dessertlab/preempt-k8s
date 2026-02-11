import sys
import os
import json
import re
import glob
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
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
    num_bands = (total_experiments + experiments_per_band - 1) // experiments_per_band
    
    # Create figure with default style
    plt.style.use('default')
    fig, ax = plt.subplots(figsize=(20, max(10, num_bands * 3)))
    
    # Set white background for figure and dark gray for plot area
    fig.patch.set_facecolor('#FFFFFF')
    ax.set_facecolor('#333333')
    
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
        # Determine which band this experiment belongs to
        band_idx = exp_idx // experiments_per_band
        
        # Calculate Y position within the band
        # Band ranges from band_idx to band_idx+1
        # Position experiment uniformly within the band with spacing
        position_in_band = exp_idx % experiments_per_band
        # Add padding (0.1 at top and bottom of band) and distribute uniformly
        band_height = 0.8  # Use 80% of band height
        band_offset = 0.1  # Start 10% from bottom
        y_base = band_idx + band_offset + (position_in_band + 0.5) * (band_height / experiments_per_band)
        
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
                s=100,
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
                    linewidth=1.5,
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
    
    # Configure axes with black text
    ax.set_xlabel('Time (milliseconds)', fontsize=30, fontweight='bold', color='black')
    ax.set_ylabel('Experiment Bands', fontsize=30, fontweight='bold', color='black')
    
    # Set Y-axis ticks and labels for bands
    band_ticks = [i + 0.5 for i in range(num_bands)]
    band_labels = []
    for i in range(num_bands):
        start_exp = i * experiments_per_band + 1
        end_exp = min((i + 1) * experiments_per_band, total_experiments)
        if start_exp == end_exp:
            band_labels.append(f"Exp {start_exp}")
        else:
            band_labels.append(f"Exp {start_exp}-{end_exp}")
    
    ax.set_yticks(band_ticks)
    ax.set_yticklabels(band_labels, fontsize=24, color='black')
    ax.set_ylim(-0.1, num_bands + 0.1)
    
    # Customize tick colors
    ax.tick_params(axis='x', colors='black', labelsize=24)
    ax.tick_params(axis='y', colors='black', labelsize=24)
    
    # Format X-axis to avoid scientific notation
    from matplotlib.ticker import FuncFormatter
    def format_func(value, tick_number):
        return f'{int(value)}'
    ax.xaxis.set_major_formatter(FuncFormatter(format_func))
    
    # Add horizontal grid lines for each band (lighter for visibility)
    for i in range(num_bands + 1):
        ax.axhline(y=i, color='#CCCCCC', linestyle='--', alpha=0.6, linewidth=1, zorder=1)
    
    # Set title with black color
    mode_title = "Kube Manager" if mode == 'kube-manager' else "Preempt-K8s"
    ax.set_title(f'Event Timeline - {mode_title} - Service: {service_name}\n({total_experiments} experiments)', 
                 fontsize=28, fontweight='bold', pad=20, color='black')
    
    # Create legend with bright colors
    if mode == 'kube-manager':
        # For kube-manager, starts_processing and pod_created are collapsed
        legend_elements = [
            mpatches.Patch(color=colors['scale-up'], label='Scale-up'),
            mpatches.Patch(color=colors['starts_processing'], label='Starts Processing / Pod Created'),
            mpatches.Patch(color=colors['pod_started'], label='Pod Started')
        ]
    else:
        legend_elements = [
            mpatches.Patch(color=colors['scale-up'], label='Scale-up'),
            mpatches.Patch(color=colors['starts_processing'], label='Starts Processing'),
            mpatches.Patch(color=colors['pod_created'], label='Pod Created'),
            mpatches.Patch(color=colors['pod_started'], label='Pod Started')
        ]
    
    legend = ax.legend(
        handles=legend_elements,
        loc='upper right',
        fontsize=22,
        framealpha=0.95,
        edgecolor='black',
        facecolor='white'
    )
    
    # Set legend text color
    for text in legend.get_texts():
        text.set_color('black')
    
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
    service_id = f"rnn-serving-python-1"
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
                    'timestamp': (metrics['starts_processing_timestamp'] - scale_up_ts) / 1_000_000  # Convert to milliseconds
                })
            else:
                # For preempt-k8s, keep them separate
                events.append({
                    'type': 'starts_processing',
                    'timestamp': (metrics['starts_processing_timestamp'] - scale_up_ts) / 1_000_000  # Convert to milliseconds
                })
                events.append({
                    'type': 'pod_created',
                    'timestamp': (metrics['pod_created_timestamp'] - scale_up_ts) / 1_000_000  # Convert to milliseconds
                })
            
            events.append({
                'type': 'pod_started',
                'timestamp': (metrics['pod_started_timestamp'] - scale_up_ts) / 1_000_000  # Convert to milliseconds
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
