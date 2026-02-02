import os
import sys
import csv
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path
from results import (
    parse_status_file, 
    parse_rps_file, 
    parse_audit_logs_file
)


def save_comparative_boxplot(data_km, data_pk8s, labels, title, ylabel, filename, directory):
    """
    Create a comparative boxplot with two boxes per service (kube-manager and preempt-k8s).
    """
    fig, ax = plt.subplots(figsize=(14, 6))
    
    # Prepare data for grouped boxplot
    num_services = len(labels)
    positions_km = []
    positions_pk8s = []
    all_data = []
    all_positions = []
    
    # Create positions for grouped boxes
    group_width = 2.5
    for i in range(num_services):
        pos_km = i * group_width
        pos_pk8s = i * group_width + 0.8
        positions_km.append(pos_km)
        positions_pk8s.append(pos_pk8s)
        all_data.extend([data_km[i], data_pk8s[i]])
        all_positions.extend([pos_km, pos_pk8s])
    
    # Create boxplot
    bp = ax.boxplot(all_data, positions=all_positions, widths=0.6, patch_artist=True)
    
    # Color boxes alternately (kube-manager in blue, preempt-k8s in orange)
    colors_km = '#3498db'  # Blue
    colors_pk8s = '#e74c3c'  # Red/Orange
    
    for i, patch in enumerate(bp['boxes']):
        if i % 2 == 0:  # kube-manager
            patch.set_facecolor(colors_km)
        else:  # preempt-k8s
            patch.set_facecolor(colors_pk8s)
        patch.set_edgecolor('black')
        patch.set_alpha(0.7)
    
    for median in bp['medians']:
        median.set(color='black', linewidth=2)
    
    # Set x-axis ticks and labels
    ax.set_xticks([i * group_width + 0.4 for i in range(num_services)])
    ax.set_xticklabels(labels, rotation=45, ha='right')
    
    ax.grid(True, axis='y', linestyle='--', alpha=0.7)
    ax.set_xlabel('Services', fontsize=12)
    ax.set_ylabel(ylabel, fontsize=12)
    ax.set_title(title, fontsize=14, fontweight='bold')
    
    # Add legend
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor=colors_km, edgecolor='black', label='kube-manager', alpha=0.7),
        Patch(facecolor=colors_pk8s, edgecolor='black', label='preempt-k8s', alpha=0.7)
    ]
    ax.legend(handles=legend_elements, loc='upper right')
    
    plt.tight_layout()
    plot_path = os.path.join(directory, filename)
    plt.savefig(plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"{title} saved to: {plot_path}")


def save_comparative_cdf_plot(data_km, data_pk8s, labels, title, xlabel, filename, directory):
    """
    Create comparative CDF plots with two lines per service (kube-manager and preempt-k8s).
    """
    fig, ax = plt.subplots(figsize=(10, 6))
    cmap = plt.get_cmap('tab10')
    
    for i in range(len(labels)):
        # CDF for kube-manager
        sorted_data_km = np.sort(data_km[i])
        if len(sorted_data_km) > 0:
            cdf_km = np.arange(1, len(sorted_data_km) + 1) / len(sorted_data_km)
            ax.plot(sorted_data_km, cdf_km, 
                    label=f'{labels[i]} (KM)', 
                    color=cmap(i % 10), 
                    linestyle='-', 
                    linewidth=2, 
                    marker='o',
                    markersize=3)
        
        # CDF for preempt-k8s
        sorted_data_pk8s = np.sort(data_pk8s[i])
        if len(sorted_data_pk8s) > 0:
            cdf_pk8s = np.arange(1, len(sorted_data_pk8s) + 1) / len(sorted_data_pk8s)
            ax.plot(sorted_data_pk8s, cdf_pk8s, 
                    label=f'{labels[i]} (PK8s)', 
                    color=cmap(i % 10), 
                    linestyle='--', 
                    linewidth=2,
                    marker='s',
                    markersize=3)
    
    ax.grid(True, linestyle='--', alpha=0.7)
    ax.set_xlabel(xlabel, fontsize=12)
    ax.set_ylabel('CDF', fontsize=12)
    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left', fontsize=8)
    
    plt.tight_layout()
    plot_path = os.path.join(directory, filename)
    plt.savefig(plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"{title} saved to: {plot_path}")


def process_experiment_data(root_path, num_services, controller_name):
    """
    Process experiment data for a single controller.
    Returns dictionaries with all metrics organized by service.
    """
    print(f"\n{'='*60}")
    print(f"Processing {controller_name} data from: {root_path}")
    print(f"{'='*60}")
    
    # Collect status and rps files
    status_files = {}
    rps_files = {}
    for i in range(num_services):
        service_name = f"service-{i+1}"
        service_path = os.path.join(root_path, service_name)
        
        if os.path.isdir(service_path):
            all_files = os.listdir(service_path)
            status_files[service_name] = [f for f in all_files if f.startswith("iteration") and os.path.isfile(os.path.join(service_path, f))]
            rps_files[service_name] = [f for f in all_files if f.startswith("rps") and os.path.isfile(os.path.join(service_path, f))]
    
    # Collect audit logs files
    all_audit_files = os.listdir(root_path)
    audit_files = [os.path.join(root_path, f) for f in all_audit_files if f.startswith("loki-logs-iteration") and os.path.isfile(os.path.join(root_path, f))]
    
    print(f"Found {len(audit_files)} audit logs files")
    
    # Process audit logs
    print("\nProcessing audit logs files...")
    all_starts_processing_delays = []
    all_pod_creation_delays = []
    all_pod_startup_delays = []
    
    for i in range(num_services):
        service_id = f"rnn-serving-python-{i+1}"
        service_name = f"service-{i+1}"
        starts_processing_delays = []
        pod_creation_delays = []
        pod_start_delays = []
        
        for audit_file in sorted(audit_files):
            print(f"  Processing {audit_file} for {service_id}...")
            try:
                metrics = parse_audit_logs_file(audit_file, controller_name, service_id)
                if metrics:
                    # Calculate delays (converting nanoseconds to milliseconds)
                    if controller_name == "preempt-k8s":
                        starts_processing_delays.append((metrics['starts_processing_timestamp'] - metrics['scale_up_timestamp']) / 1_000_000)
                    elif controller_name == "kube-manager":
                        starts_processing_delays.append((metrics['pod_created_timestamp'] - metrics['scale_up_timestamp']) / 1_000_000)
                    pod_creation_delays.append((metrics['pod_created_timestamp'] - metrics['scale_up_timestamp']) / 1_000_000)
                    pod_start_delays.append((metrics['pod_started_timestamp'] - metrics['scale_up_timestamp']) / 1_000_000)
            except Exception as e:
                print(f"    Error: {str(e)}")
        
        all_starts_processing_delays.append(starts_processing_delays)
        all_pod_creation_delays.append(pod_creation_delays)
        all_pod_startup_delays.append(pod_start_delays)
    
    # Process status and rps files
    print("\nProcessing status and rps files...")
    all_lost_requests = []
    all_completed_requests = []
    all_mean_latencies = []
    all_max_latencies = []
    
    for i in range(num_services):
        service_name = f"service-{i+1}"
        
        # Process status files
        lost_requests = []
        completed_requests = []
        
        for status_file in sorted(status_files[service_name]):
            file_path = os.path.join(root_path, service_name, status_file)
            try:
                status_data = parse_status_file(file_path)
                lost = status_data['issued'] - status_data['completed']
                lost_requests.append(lost)
                completed_requests.append(status_data['completed'])
            except Exception as e:
                print(f"    Error parsing {status_file}: {str(e)}")
        
        all_lost_requests.append(lost_requests)
        all_completed_requests.append(completed_requests)
        
        # Process rps files
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
            except Exception as e:
                print(f"    Error parsing {rps_file}: {str(e)}")
        
        all_mean_latencies.append(mean_latencies)
        all_max_latencies.append(max_latencies)
    
    return {
        'starts_processing_delays': all_starts_processing_delays,
        'pod_creation_delays': all_pod_creation_delays,
        'pod_startup_delays': all_pod_startup_delays,
        'lost_requests': all_lost_requests,
        'completed_requests': all_completed_requests,
        'mean_latencies': all_mean_latencies,
        'max_latencies': all_max_latencies
    }


def main():
    # Validate command line arguments
    if len(sys.argv) != 4:
        print("Usage: python compare-results.py <path_to_kube_manager_results> <path_to_preempt_k8s_results> <number_of_services>")
        sys.exit(1)
    
    km_path = sys.argv[1]
    pk8s_path = sys.argv[2]
    num_services = int(sys.argv[3])
    
    # Validate paths
    if not os.path.isdir(km_path):
        print(f"Error: {km_path} is not a valid directory!")
        sys.exit(1)
    
    if not os.path.isdir(pk8s_path):
        print(f"Error: {pk8s_path} is not a valid directory!")
        sys.exit(1)
    
    if num_services <= 0:
        print("Error: Number of services must be a positive integer!")
        sys.exit(1)
    
    # Create output directory (results/ is 3 levels up from timestamp dir)
    km_path_obj = Path(km_path).resolve()
    pk8s_path_obj = Path(pk8s_path).resolve()
    
    results_dir = km_path_obj.parent.parent.parent
    compared_dir = results_dir / "compared"

    km_exp = km_path_obj.parent.name
    km_timestamp = km_path_obj.name
    pk8s_exp = pk8s_path_obj.parent.name
    pk8s_timestamp = pk8s_path_obj.name
    
    output_dir = compared_dir / f"{km_exp}_{km_timestamp}--vs--{pk8s_exp}_{pk8s_timestamp}"
    if not output_dir.exists():
        output_dir.mkdir(parents=True, exist_ok=True)
        print(f"Created output directory: {output_dir}")
    else:
        print(f"Output directory already exists: {output_dir}")
    
    # Process both experiments
    km_data = process_experiment_data(km_path, num_services, "kube-manager")
    pk8s_data = process_experiment_data(pk8s_path, num_services, "preempt-k8s")
    
    # Generate service labels
    service_labels = [f"service-{i+1}" for i in range(num_services)]
    
    # Create comparative CSV
    print("\n" + "="*60)
    print("Creating comparative metrics CSV...")
    print("="*60)
    csv_path = str(output_dir / "comparative_metrics.csv")
    with open(csv_path, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow([
            'Service', 'Controller',
            'Mean Latencies [ms]', 'Max Latencies [ms]',
            'Mean Lost Requests', 'Max Lost Requests',
            'Mean Completed Requests', 'Max Completed Requests',
            'Starts Processing Delay Mean [ms]', 'Starts Processing Delay Max [ms]',
            'Pod Creation Delay Mean [ms]', 'Pod Creation Delay Max [ms]',
            'Pod Startup Delay Mean [ms]', 'Pod Startup Delay Max [ms]'
        ])
        
        for i in range(num_services):
            service_name = f"service-{i+1}"
            
            # kube-manager row
            if km_data['mean_latencies'][i]:
                writer.writerow([
                    service_name, 'kube-manager',
                    sum(km_data['mean_latencies'][i]) / len(km_data['mean_latencies'][i]),
                    sum(km_data['max_latencies'][i]) / len(km_data['max_latencies'][i]),
                    sum(km_data['lost_requests'][i]) / len(km_data['lost_requests'][i]),
                    max(km_data['lost_requests'][i]) if km_data['lost_requests'][i] else 0,
                    sum(km_data['completed_requests'][i]) / len(km_data['completed_requests'][i]),
                    max(km_data['completed_requests'][i]) if km_data['completed_requests'][i] else 0,
                    sum(km_data['starts_processing_delays'][i]) / len(km_data['starts_processing_delays'][i]) if km_data['starts_processing_delays'][i] else 0,
                    max(km_data['starts_processing_delays'][i]) if km_data['starts_processing_delays'][i] else 0,
                    sum(km_data['pod_creation_delays'][i]) / len(km_data['pod_creation_delays'][i]) if km_data['pod_creation_delays'][i] else 0,
                    max(km_data['pod_creation_delays'][i]) if km_data['pod_creation_delays'][i] else 0,
                    sum(km_data['pod_startup_delays'][i]) / len(km_data['pod_startup_delays'][i]) if km_data['pod_startup_delays'][i] else 0,
                    max(km_data['pod_startup_delays'][i]) if km_data['pod_startup_delays'][i] else 0
                ])
            
            # preempt-k8s row
            if pk8s_data['mean_latencies'][i]:
                writer.writerow([
                    service_name, 'preempt-k8s',
                    sum(pk8s_data['mean_latencies'][i]) / len(pk8s_data['mean_latencies'][i]),
                    sum(pk8s_data['max_latencies'][i]) / len(pk8s_data['max_latencies'][i]),
                    sum(pk8s_data['lost_requests'][i]) / len(pk8s_data['lost_requests'][i]),
                    max(pk8s_data['lost_requests'][i]) if pk8s_data['lost_requests'][i] else 0,
                    sum(pk8s_data['completed_requests'][i]) / len(pk8s_data['completed_requests'][i]),
                    max(pk8s_data['completed_requests'][i]) if pk8s_data['completed_requests'][i] else 0,
                    sum(pk8s_data['starts_processing_delays'][i]) / len(pk8s_data['starts_processing_delays'][i]) if pk8s_data['starts_processing_delays'][i] else 0,
                    max(pk8s_data['starts_processing_delays'][i]) if pk8s_data['starts_processing_delays'][i] else 0,
                    sum(pk8s_data['pod_creation_delays'][i]) / len(pk8s_data['pod_creation_delays'][i]) if pk8s_data['pod_creation_delays'][i] else 0,
                    max(pk8s_data['pod_creation_delays'][i]) if pk8s_data['pod_creation_delays'][i] else 0,
                    sum(pk8s_data['pod_startup_delays'][i]) / len(pk8s_data['pod_startup_delays'][i]) if pk8s_data['pod_startup_delays'][i] else 0,
                    max(pk8s_data['pod_startup_delays'][i]) if pk8s_data['pod_startup_delays'][i] else 0
                ])
    
    print(f"CSV saved to: {csv_path}")
    
    # Create comparative box plots
    print("\n" + "="*60)
    print("Creating comparative box plots...")
    print("="*60)
    
    box_plots_config = [
        ('starts_processing_delays', "Comparative Starts Processing Delays", "Delays [ms]", "comparative_boxplot_starts_processing_delays.png"),
        ('pod_creation_delays', "Comparative Pod Creation Delays", "Delays [ms]", "comparative_boxplot_pod_creation_delays.png"),
        ('pod_startup_delays', "Comparative Pod Startup Delays", "Delays [ms]", "comparative_boxplot_pod_startup_delays.png"),
        ('lost_requests', "Comparative Lost Requests", "Number of Requests", "comparative_boxplot_lost_requests.png"),
        ('completed_requests', "Comparative Completed Requests", "Number of Requests", "comparative_boxplot_completed_requests.png"),
        ('mean_latencies', "Comparative Mean Latencies", "Latencies [ms]", "comparative_boxplot_mean_latencies.png"),
        ('max_latencies', "Comparative Max Latencies", "Latencies [ms]", "comparative_boxplot_max_latencies.png")
    ]
    
    for metric_key, title, ylabel, fname in box_plots_config:
        save_comparative_boxplot(
            km_data[metric_key], 
            pk8s_data[metric_key], 
            service_labels, 
            title, 
            ylabel, 
            fname, 
            str(output_dir)
        )
    
    # Create comparative CDF plots
    print("\n" + "="*60)
    print("Creating comparative CDF plots...")
    print("="*60)
    
    cdf_plots_config = [
        ('starts_processing_delays', "Comparative CDF of Starts Processing Delays", "Starts Processing Delays [ms]", "comparative_cdf_starts_processing_delays.png"),
        ('pod_creation_delays', "Comparative CDF of Pod Creation Delays", "Pod Creation Delays [ms]", "comparative_cdf_pod_creation_delays.png"),
        ('pod_startup_delays', "Comparative CDF of Pod Startup Delays", "Pod Startup Delays [ms]", "comparative_cdf_pod_startup_delays.png"),
        ('mean_latencies', "Comparative CDF of Mean Latencies", "Mean Latencies [ms]", "comparative_cdf_mean_latencies.png"),
        ('max_latencies', "Comparative CDF of Max Latencies", "Max Latencies [ms]", "comparative_cdf_max_latencies.png")
    ]
    
    for metric_key, title, xlabel, fname in cdf_plots_config:
        save_comparative_cdf_plot(
            km_data[metric_key], 
            pk8s_data[metric_key], 
            service_labels, 
            title, 
            xlabel, 
            fname, 
            str(output_dir)
        )
    
    print("\n" + "="*60)
    print("Comparison completed successfully!")
    print(f"All results saved to: {output_dir}")
    print("="*60)


if __name__ == "__main__":
    main()
