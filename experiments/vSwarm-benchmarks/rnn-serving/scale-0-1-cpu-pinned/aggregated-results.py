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


def save_comparative_boxplot(data_km, data_pk8s, title, ylabel, filename, directory):
    """
    Create a comparative boxplot with two boxes total (kube-manager and preempt-k8s).
    Data is aggregated across all services and iterations.
    """
    fig, ax = plt.subplots(figsize=(5, 6))
    
    # Prepare data - two boxes total
    all_data = [data_km, data_pk8s]
    positions = [1, 2]
    labels = ['kube-manager', 'preempt-k8s']
    
    # Create boxplot
    bp = ax.boxplot(all_data, positions=positions, widths=0.4, patch_artist=True)
    
    # Color boxes
    colors = ['#3498db', '#e74c3c']  # Blue for KM, Red/Orange for PK8s
    
    for i, patch in enumerate(bp['boxes']):
        patch.set_facecolor(colors[i])
        patch.set_edgecolor('black')
        patch.set_alpha(0.7)
    
    for median in bp['medians']:
        median.set(color='black', linewidth=2)
    
    # Set x-axis ticks and labels
    ax.set_xticks(positions)
    ax.set_xticklabels(labels)
    
    ax.grid(True, axis='y', linestyle='--', alpha=0.7)
    ax.set_xlabel('Controller', fontsize=12)
    ax.set_ylabel(ylabel, fontsize=12)
    ax.set_title(title, fontsize=14, fontweight='bold')
    
    plt.tight_layout()
    plot_path = os.path.join(directory, filename)
    plt.savefig(plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"{title} saved to: {plot_path}")


def save_comparative_cdf_plot(data_km, data_pk8s, title, xlabel, filename, directory):
    """
    Create comparative CDF plots with two lines total (kube-manager and preempt-k8s).
    Data is aggregated across all services and iterations.
    """
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # CDF for kube-manager
    sorted_data_km = np.sort(data_km)
    if len(sorted_data_km) > 0:
        cdf_km = np.arange(1, len(sorted_data_km) + 1) / len(sorted_data_km)
        ax.plot(sorted_data_km, cdf_km, 
                label='kube-manager', 
                color='#3498db', 
                linestyle='-', 
                linewidth=2.5)
    
    # CDF for preempt-k8s
    sorted_data_pk8s = np.sort(data_pk8s)
    if len(sorted_data_pk8s) > 0:
        cdf_pk8s = np.arange(1, len(sorted_data_pk8s) + 1) / len(sorted_data_pk8s)
        ax.plot(sorted_data_pk8s, cdf_pk8s, 
                label='preempt-k8s', 
                color='#e74c3c', 
                linestyle='--', 
                linewidth=2.5)
    
    ax.grid(True, linestyle='--', alpha=0.7)
    ax.set_xlabel(xlabel, fontsize=12)
    ax.set_ylabel('CDF', fontsize=12)
    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.legend(loc='best', fontsize=10)
    
    plt.tight_layout()
    plot_path = os.path.join(directory, filename)
    plt.savefig(plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"{title} saved to: {plot_path}")


def process_experiment_data(root_path, num_services, controller_name):
    """
    Process experiment data for a single controller.
    Returns dictionaries with all metrics aggregated by iteration.
    Each value represents the aggregate (sum or mean) across all services for that iteration.
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
            status_files[service_name] = sorted(
                [f for f in all_files if f.endswith("status.txt") and os.path.isfile(os.path.join(service_path, f))],
                key=lambda fname: int(fname.split('_')[1])
                )
            rps_files[service_name] = sorted(
                [f for f in all_files if f.startswith("rps") and os.path.isfile(os.path.join(service_path, f))],
                key=lambda fname: int(fname.split('_')[-1])
                )
    
    # Collect audit logs files
    all_audit_files = os.listdir(root_path)
    audit_files = sorted(
        [os.path.join(root_path, f) for f in all_audit_files if f.startswith("loki-logs-iteration") and os.path.isfile(os.path.join(root_path, f))],
        key=lambda fname: int(fname.split('iteration_')[1].split('.json')[0])
        )
    
    print(f"Found {len(audit_files)} audit logs files")
    
    # Determine number of iterations
    num_iterations = len(audit_files)
    
    # Process audit logs - organized by iteration
    print("\nProcessing audit logs files...")
    all_starts_processing_delays = []
    all_pod_creation_delays = []
    all_pod_startup_delays = []
    
    for iter_idx, audit_file in enumerate(audit_files):
        print(f"  Processing iteration {iter_idx + 1}: {audit_file}")
        
        # Temporary lists to collect data from all services for this iteration
        iteration_starts_processing_delays = []
        iteration_pod_creation_delays = []
        iteration_pod_start_delays = []
        
        for i in range(num_services):
            service_id = f"rnn-serving-python-{i+1}"
            try:
                metrics = parse_audit_logs_file(audit_file, controller_name, service_id)
                if metrics:
                    # Calculate delays (converting nanoseconds to milliseconds)
                    if controller_name == "preempt-k8s":
                        iteration_starts_processing_delays.append((metrics['starts_processing_timestamp'] - metrics['scale_up_timestamp']) / 1_000_000)
                    elif controller_name == "kube-manager":
                        iteration_starts_processing_delays.append((metrics['pod_created_timestamp'] - metrics['scale_up_timestamp']) / 1_000_000)
                    iteration_pod_creation_delays.append((metrics['pod_created_timestamp'] - metrics['scale_up_timestamp']) / 1_000_000)
                    iteration_pod_start_delays.append((metrics['pod_started_timestamp'] - metrics['scale_up_timestamp']) / 1_000_000)
            except Exception as e:
                print(f"    Error processing {service_id}: {str(e)}")
        
        # Aggregate data across all services for this iteration (average)
        mean_starts_processing = sum(iteration_starts_processing_delays) / len(iteration_starts_processing_delays) if iteration_starts_processing_delays else 0
        mean_pod_creation = sum(iteration_pod_creation_delays) / len(iteration_pod_creation_delays) if iteration_pod_creation_delays else 0
        mean_pod_start = sum(iteration_pod_start_delays) / len(iteration_pod_start_delays) if iteration_pod_start_delays else 0
        
        all_starts_processing_delays.append(mean_starts_processing)
        all_pod_creation_delays.append(mean_pod_creation)
        all_pod_startup_delays.append(mean_pod_start)
    
    # Process status and rps files - organized by iteration
    print("\nProcessing status and rps files...")
    all_lost_requests = []
    all_completed_requests = []
    all_real_rps = []
    all_mean_latencies = []
    all_max_latencies = []
    
    for iter_idx in range(num_iterations):
        print(f"  Processing iteration {iter_idx + 1}")
        
        # Temporary lists to collect data from all services for this iteration
        iteration_lost_requests = []
        iteration_completed_requests = []
        iteration_all_latencies = []
        iteration_real_rps = []
        
        for i in range(num_services):
            service_name = f"service-{i+1}"
            
            # Process status file for this iteration
            if iter_idx < len(status_files[service_name]):
                status_file = status_files[service_name][iter_idx]
                file_path = os.path.join(root_path, service_name, status_file)
                try:
                    status_data = parse_status_file(file_path)
                    lost = status_data['issued'] - status_data['completed']
                    iteration_lost_requests.append(lost)
                    iteration_completed_requests.append(status_data['completed'])
                    iteration_real_rps.append(status_data['real_rps'])
                except Exception as e:
                    print(f"    Error parsing {status_file}: {str(e)}")
            
            # Process rps file for this iteration - accumulate ALL latencies
            if iter_idx < len(rps_files[service_name]):
                rps_file = rps_files[service_name][iter_idx]
                file_path = os.path.join(root_path, service_name, rps_file)
                try:
                    latencies = parse_rps_file(file_path)
                    iteration_all_latencies.extend(latencies)
                except Exception as e:
                    print(f"    Error parsing {rps_file}: {str(e)}")
        
        # Aggregate data across all services for this iteration
        # Sum for requests (total across all services)
        total_lost = sum(iteration_lost_requests) if iteration_lost_requests else 0
        total_completed = sum(iteration_completed_requests) if iteration_completed_requests else 0
        total_real_rps = sum(iteration_real_rps) if iteration_real_rps else 0
        
        # Calculate mean and max on ALL latencies from all services
        if iteration_all_latencies:
            # Convert from microseconds to milliseconds
            iteration_all_latencies_ms = [lat / 1000 for lat in iteration_all_latencies]
            mean_latency = sum(iteration_all_latencies_ms) / len(iteration_all_latencies_ms)
            max_latency = max(iteration_all_latencies_ms)
        else:
            mean_latency = 0
            max_latency = 0
        
        # Append aggregated values for this iteration
        all_lost_requests.append(total_lost)
        all_completed_requests.append(total_completed)
        all_real_rps.append(total_real_rps)
        all_mean_latencies.append(mean_latency)
        all_max_latencies.append(max_latency)
    
    return {
        'starts_processing_delays': all_starts_processing_delays,
        'pod_creation_delays': all_pod_creation_delays,
        'pod_startup_delays': all_pod_startup_delays,
        'lost_requests': all_lost_requests,
        'completed_requests': all_completed_requests,
        'real_rps': all_real_rps,
        'mean_latencies': all_mean_latencies,
        'max_latencies': all_max_latencies
    }


def main():
    # Validate command line arguments
    if len(sys.argv) != 4:
        print("Usage: python aggregated-results.py <path_to_kube_manager_results> <path_to_preempt_k8s_results> <number_of_services>")
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
    
    compared_dir = Path("results/aggregated")

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
    
    # km_data and pk8s_data contain lists with one value per iteration
    km_flat = km_data
    pk8s_flat = pk8s_data
    
    # Create comparative CSV with aggregated metrics
    print("\n" + "="*60)
    print("Creating comparative metrics CSV...")
    print("="*60)
    csv_path = str(output_dir / "comparative_metrics.csv")
    with open(csv_path, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow([
            'Controller',
            'Mean of Mean Latencies [ms]', 'Std of Mean Latencies [ms]',
            'Mean of Max Latencies [ms]', 'Std of Max Latencies [ms]',
            'Mean of Lost Requests', 'Std of Lost Requests',
            'Mean of Completed Requests', 'Std of Completed Requests',
            'Mean of Real RPS', 'Std of Real RPS',
            'Mean Starts Processing Delay [ms]', 'Std Starts Processing Delay [ms]',
            'Mean Pod Creation Delay [ms]', 'Std Pod Creation Delay [ms]',
            'Mean Pod Startup Delay [ms]', 'Std Pod Startup Delay [ms]'
        ])
        
        # kube-manager row
        writer.writerow([
            'kube-manager',
            np.mean(km_flat['mean_latencies']),
            np.std(km_flat['mean_latencies']),
            np.mean(km_flat['max_latencies']),
            np.std(km_flat['max_latencies']),
            np.mean(km_flat['lost_requests']),
            np.std(km_flat['lost_requests']),
            np.mean(km_flat['completed_requests']),
            np.std(km_flat['completed_requests']),
            np.mean(km_flat['real_rps']),
            np.std(km_flat['real_rps']),
            np.mean(km_flat['starts_processing_delays']),
            np.std(km_flat['starts_processing_delays']),
            np.mean(km_flat['pod_creation_delays']),
            np.std(km_flat['pod_creation_delays']),
            np.mean(km_flat['pod_startup_delays']),
            np.std(km_flat['pod_startup_delays'])
        ])
        
        # preempt-k8s row
        writer.writerow([
            'preempt-k8s',
            np.mean(pk8s_flat['mean_latencies']),
            np.std(pk8s_flat['mean_latencies']),
            np.mean(pk8s_flat['max_latencies']),
            np.std(pk8s_flat['max_latencies']),
            np.mean(pk8s_flat['lost_requests']),
            np.std(pk8s_flat['lost_requests']),
            np.mean(pk8s_flat['completed_requests']),
            np.std(pk8s_flat['completed_requests']),
            np.mean(pk8s_flat['real_rps']),
            np.std(pk8s_flat['real_rps']),
            np.mean(pk8s_flat['starts_processing_delays']),
            np.std(pk8s_flat['starts_processing_delays']),
            np.mean(pk8s_flat['pod_creation_delays']),
            np.std(pk8s_flat['pod_creation_delays']),
            np.mean(pk8s_flat['pod_startup_delays']),
            np.std(pk8s_flat['pod_startup_delays'])
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
        ('real_rps', "Comparative Real RPS", "Real RPS", "comparative_boxplot_real_rps.png"),
        ('mean_latencies', "Comparative Mean Latencies", "Latencies [ms]", "comparative_boxplot_mean_latencies.png"),
        ('max_latencies', "Comparative Max Latencies", "Latencies [ms]", "comparative_boxplot_max_latencies.png")
    ]
    
    for metric_key, title, ylabel, fname in box_plots_config:
        save_comparative_boxplot(
            km_flat[metric_key], 
            pk8s_flat[metric_key], 
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
            km_flat[metric_key], 
            pk8s_flat[metric_key], 
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
