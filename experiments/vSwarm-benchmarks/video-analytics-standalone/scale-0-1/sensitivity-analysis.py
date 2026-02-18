import os
import sys
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path
from results import (
    parse_status_file, 
    parse_rps_file, 
    parse_audit_logs_file
)


def save_comparative_boxplot(data_km_15, data_pk8s_15, data_km_30, data_pk8s_30, 
                            data_km_45, data_pk8s_45, title, ylabel, filename, directory):
    """
    Create a sensitivity analysis boxplot with 6 boxes (3 parameter values x 2 controllers).
    Shows how metrics vary with parameter values (15, 30, 45) for both controllers.
    """
    # Set professional style
    plt.rcParams['font.family'] = 'sans-serif'
    plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Arial', 'Helvetica']
    
    fig, ax = plt.subplots(figsize=(14, 7), constrained_layout=True)
    
    # Prepare data - 6 boxes grouped by parameter value
    all_data = [data_km_15, data_pk8s_15, data_km_30, data_pk8s_30, data_km_45, data_pk8s_45]
    positions = [1, 2, 4, 5, 7, 8]  # Grouped positions
    
    # Scientific colorblind-friendly palette
    color_km = '#42a5f5'   # Blue for kube-manager
    color_pk8s = '#FF8000'  # Orange for preempt-k8s (not too bright)
    colors = [color_km, color_pk8s, color_km, color_pk8s, color_km, color_pk8s]
    
    # Add colored background for parameter groups (gradient based on interfering resources)
    ax.axvspan(0.5, 3, facecolor='#FFE680', alpha=0.5, zorder=0)      # Yellow for 15 (low interference)
    ax.axvspan(3, 6, facecolor='#FFB366', alpha=0.5, zorder=0)        # Orange for 30 (medium interference)
    ax.axvspan(6, 9, facecolor='#FF8FA3', alpha=0.5, zorder=0)        # Pink for 45 (high interference)
    
    # Create boxplot with refined styling and prominent red outliers
    bp = ax.boxplot(all_data, positions=positions, widths=0.7, patch_artist=True,
                    boxprops=dict(linewidth=1.5),
                    whiskerprops=dict(linewidth=1.5),
                    capprops=dict(linewidth=1.5),
                    medianprops=dict(color='#FFFFFF', linewidth=2),
                    flierprops=dict(marker='D', markerfacecolor='#DC143C', markersize=8, 
                                   markeredgecolor='#8B0000', markeredgewidth=1.2, alpha=0.8))
    
    # Color boxes with professional palette - golden edges for all boxes
    for i, patch in enumerate(bp['boxes']):
        patch.set_facecolor(colors[i])
        patch.set_edgecolor('#000000')  # Black edges for all boxes
        patch.set_alpha(0.7)
        patch.set_linewidth(2)
    
    # Style whiskers and caps
    for whisker in bp['whiskers']:
        whisker.set_color('#555555')
        whisker.set_linestyle('-')
        whisker.set_alpha(0.6)
    
    for cap in bp['caps']:
        cap.set_color('#555555')
        cap.set_alpha(0.6)
    
    # Set two-level x-axis labels
    ax.set_xticks(positions)
    labels_controller = ['KM', 'PK8s', 'KM', 'PK8s', 'KM', 'PK8s']
    ax.set_xticklabels(labels_controller, fontsize=13)
    
    # Add vertical separator lines
    ax.axvline(x=3, color='#CCCCCC', linestyle='-', linewidth=1.5, alpha=0.6)
    ax.axvline(x=6, color='#CCCCCC', linestyle='-', linewidth=1.5, alpha=0.6)
    
    # Professional grid styling
    ax.grid(True, axis='y', linestyle='--', alpha=0.3, linewidth=0.8, color='#888888')
    ax.set_axisbelow(True)
    
    # Remove top and right spines (Tufte style)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_linewidth(1.2)
    ax.spines['bottom'].set_linewidth(1.2)
    
    # Labels with improved typography
    ax.set_xlabel('Controller Type (15 | 30 | 45 Interfering Resources)', fontsize=14, fontweight='semibold', labelpad=10)
    ax.set_ylabel(ylabel, fontsize=14, fontweight='semibold', labelpad=10)
    ax.set_title(title, fontsize=16, fontweight='bold', pad=20)
    
    # Add legend
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor=color_km, edgecolor=color_km, alpha=0.7, label='Kube-Manager'),
        Patch(facecolor=color_pk8s, edgecolor=color_pk8s, alpha=0.7, label='Preempt-K8s')
    ]
    ax.legend(handles=legend_elements, loc='upper right', fontsize=12, framealpha=0.95,
              edgecolor='gray', fancybox=True)
    
    # Adjust tick label sizes
    ax.tick_params(axis='both', which='major', labelsize=12)
    
    # Add parameter group labels as text annotations at the top of each group
    y_pos = ax.get_ylim()[1] * 0.98  # Near top of plot
    ax.text(1.5, y_pos, '15', ha='center', va='top', 
            fontsize=13, fontweight='bold',
            bbox=dict(boxstyle='round,pad=0.4', facecolor='white', edgecolor='gray', alpha=0.9, linewidth=1.5))
    ax.text(4.5, y_pos, '30', ha='center', va='top', 
            fontsize=13, fontweight='bold',
            bbox=dict(boxstyle='round,pad=0.4', facecolor='white', edgecolor='gray', alpha=0.9, linewidth=1.5))
    ax.text(7.5, y_pos, '45', ha='center', va='top', 
            fontsize=13, fontweight='bold',
            bbox=dict(boxstyle='round,pad=0.4', facecolor='white', edgecolor='gray', alpha=0.9, linewidth=1.5))
    
    # Save as PNG
    plot_path_png = os.path.join(directory, filename)
    plt.savefig(plot_path_png, dpi=300, bbox_inches='tight', facecolor='white')
    plt.close()
    print(f"{title} saved to: {plot_path_png}")


def save_comparative_cdf_plot(data_km_15, data_pk8s_15, data_km_30, data_pk8s_30,
                             data_km_45, data_pk8s_45, title, xlabel, filename, directory):
    """
    Create sensitivity analysis CDF plots with 6 lines (3 parameter values x 2 controllers).
    Shows how CDFs vary with parameter values (15, 30, 45) for both controllers.
    """
    # Set professional style
    plt.rcParams['font.family'] = 'sans-serif'
    plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Arial', 'Helvetica']
    
    fig, ax = plt.subplots(figsize=(14, 8), constrained_layout=True)
    
    # Scientific colorblind-friendly palette
    color_km = '#0173B2'    # Blue for kube-manager
    color_pk8s = '#29A329'  # Green for preempt-k8s (not too bright)
    
    # Define markers for key percentiles
    markers = ['o', 's', '^']  # Circle, square, triangle for 15, 30, 45
    
    # Define configs with improved styling
    configs = [
        (data_km_15, 'KM-15', color_km, '-', markers[0]),
        (data_pk8s_15, 'PK8s-15', color_pk8s, '-', markers[0]),
        (data_km_30, 'KM-30', color_km, '--', markers[1]),
        (data_pk8s_30, 'PK8s-30', color_pk8s, '--', markers[1]),
        (data_km_45, 'KM-45', color_km, ':', markers[2]),
        (data_pk8s_45, 'PK8s-45', color_pk8s, ':', markers[2])
    ]
    
    # Plot CDFs with markers at key percentiles
    for data, label, color, linestyle, marker in configs:
        sorted_data = np.sort(data)
        if len(sorted_data) > 0:
            cdf = np.arange(1, len(sorted_data) + 1) / len(sorted_data)
            
            # Plot main line
            ax.plot(sorted_data, cdf, 
                    label=label, 
                    color=color, 
                    linestyle=linestyle, 
                    linewidth=2.8,
                    alpha=0.9)
            
            # Add markers at key percentiles (25%, 50%, 75%, 95%)
            percentiles = [0.25, 0.50, 0.75, 0.95]
            for p in percentiles:
                idx = int(p * len(sorted_data))
                if idx < len(sorted_data):
                    ax.plot(sorted_data[idx], cdf[idx], 
                            marker=marker, 
                            markersize=8, 
                            color=color,
                            markeredgecolor='white',
                            markeredgewidth=1.5,
                            zorder=5)
    
    # Professional grid styling
    ax.grid(True, linestyle='--', alpha=0.25, linewidth=0.8, color='#888888')
    ax.set_axisbelow(True)
    
    # Remove top and right spines
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_linewidth(1.2)
    ax.spines['bottom'].set_linewidth(1.2)
    
    # Labels with improved typography
    ax.set_xlabel(xlabel, fontsize=14, fontweight='semibold', labelpad=10)
    ax.set_ylabel('Cumulative Distribution Function', fontsize=14, fontweight='semibold', labelpad=10)
    ax.set_title(title, fontsize=16, fontweight='bold', pad=20)
    
    # Improved legend
    ax.legend(loc='lower right', fontsize=11, ncol=2, framealpha=0.95,
              edgecolor='gray', fancybox=True, columnspacing=1.5)
    
    # Set y-axis limits to [0, 1] for proper CDF display
    ax.set_ylim([0, 1.02])
    
    # Adjust tick label sizes
    ax.tick_params(axis='both', which='major', labelsize=12)
    
    # Add horizontal reference lines at key percentiles
    for p in [0.25, 0.5, 0.75, 0.95]:
        ax.axhline(y=p, color='#DDDDDD', linestyle=':', linewidth=1, alpha=0.5, zorder=0)
    
    # Save as PNG
    plot_path_png = os.path.join(directory, filename)
    plt.savefig(plot_path_png, dpi=300, bbox_inches='tight', facecolor='white')
    plt.close()
    print(f"{title} saved to: {plot_path_png}")


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
            status_files[service_name] = sorted([f for f in all_files if f.endswith("status.txt") and os.path.isfile(os.path.join(service_path, f))])
            rps_files[service_name] = sorted([f for f in all_files if f.startswith("rps") and os.path.isfile(os.path.join(service_path, f))])
    
    # Collect audit logs files
    all_audit_files = os.listdir(root_path)
    audit_files = sorted([os.path.join(root_path, f) for f in all_audit_files if f.startswith("loki-logs-iteration") and os.path.isfile(os.path.join(root_path, f))])
    
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
            service_id = f"video-analytics-standalone-python-{i+1}"
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
    if len(sys.argv) != 8:
        print(
            "Usage: " \
            "python aggregated-results.py " \
            "<path_to_kube_manager_15_results> <path_to_kube_manager_30_results> <path_to_kube_manager_45_results> " \
            "<path_to_preempt_k8s_15_results> <path_to_preempt_k8s_30_results> <path_to_preempt_k8s_45_results> " \
            "<number_of_services>")
        sys.exit(1)
    
    km_path_15 = sys.argv[1]
    km_path_30 = sys.argv[2]
    km_path_45 = sys.argv[3]
    pk8s_path_15 = sys.argv[4]
    pk8s_path_30 = sys.argv[5]
    pk8s_path_45 = sys.argv[6]
    num_services = int(sys.argv[7])
    
    # Validate paths
    if not os.path.isdir(km_path_15):
        print(f"Error: {km_path_15} is not a valid directory!")
        sys.exit(1)
    
    if not os.path.isdir(km_path_30):
        print(f"Error: {km_path_30} is not a valid directory!")
        sys.exit(1)
    
    if not os.path.isdir(km_path_45):
        print(f"Error: {km_path_45} is not a valid directory!")
        sys.exit(1)
    
    if not os.path.isdir(pk8s_path_15):
        print(f"Error: {pk8s_path_15} is not a valid directory!")
        sys.exit(1)
    
    if not os.path.isdir(pk8s_path_30):
        print(f"Error: {pk8s_path_30} is not a valid directory!")
        sys.exit(1)
    
    if not os.path.isdir(pk8s_path_45):
        print(f"Error: {pk8s_path_45} is not a valid directory!")
        sys.exit(1)
    
    if num_services <= 0:
        print("Error: Number of services must be a positive integer!")
        sys.exit(1)
    
    # Create output directory for sensitivity analysis
    output_dir = Path(f"results/sensitivity-analysis/sensitivity-analysis-{num_services}-services")
    if not output_dir.exists():
        output_dir.mkdir(parents=True, exist_ok=True)
        print(f"Created output directory: {output_dir}")
    else:
        print(f"Output directory already exists: {output_dir}")
    
    # Process all 6 experiments
    km_data_15 = process_experiment_data(km_path_15, num_services, "kube-manager")
    km_data_30 = process_experiment_data(km_path_30, num_services, "kube-manager")
    km_data_45 = process_experiment_data(km_path_45, num_services, "kube-manager")
    pk8s_data_15 = process_experiment_data(pk8s_path_15, num_services, "preempt-k8s")
    pk8s_data_30 = process_experiment_data(pk8s_path_30, num_services, "preempt-k8s")
    pk8s_data_45 = process_experiment_data(pk8s_path_45, num_services, "preempt-k8s")
    
    # Create sensitivity analysis box plots
    print("\n" + "="*60)
    print("Creating sensitivity analysis box plots...")
    print("="*60)
    
    box_plots_config = [
        ('starts_processing_delays', "Sensitivity Analysis: Starts Processing Delays", "Delays [ms]", "sensitivity_boxplot_starts_processing_delays.png"),
        ('pod_creation_delays', "Sensitivity Analysis: Pod Creation Delays", "Delays [ms]", "sensitivity_boxplot_pod_creation_delays.png"),
        ('pod_startup_delays', "Sensitivity Analysis: Pod Startup Delays", "Delays [ms]", "sensitivity_boxplot_pod_startup_delays.png"),
        ('lost_requests', "Sensitivity Analysis: Lost Requests", "Number of Requests", "sensitivity_boxplot_lost_requests.png"),
        ('completed_requests', "Sensitivity Analysis: Completed Requests", "Number of Requests", "sensitivity_boxplot_completed_requests.png"),
        ('real_rps', "Sensitivity Analysis: Real RPS", "Real RPS", "sensitivity_boxplot_real_rps.png"),
        ('mean_latencies', "Sensitivity Analysis: Mean Latencies", "Latencies [ms]", "sensitivity_boxplot_mean_latencies.png"),
        ('max_latencies', "Sensitivity Analysis: Max Latencies", "Latencies [ms]", "sensitivity_boxplot_max_latencies.png")
    ]
    
    for metric_key, title, ylabel, fname in box_plots_config:
        save_comparative_boxplot(
            km_data_15[metric_key], pk8s_data_15[metric_key],
            km_data_30[metric_key], pk8s_data_30[metric_key],
            km_data_45[metric_key], pk8s_data_45[metric_key],
            title, ylabel, fname, str(output_dir)
        )
    
    # Create sensitivity analysis CDF plots
    print("\n" + "="*60)
    print("Creating sensitivity analysis CDF plots...")
    print("="*60)
    
    cdf_plots_config = [
        ('starts_processing_delays', "Sensitivity Analysis: CDF of Starts Processing Delays", "Starts Processing Delays [ms]", "sensitivity_cdf_starts_processing_delays.png"),
        ('pod_creation_delays', "Sensitivity Analysis: CDF of Pod Creation Delays", "Pod Creation Delays [ms]", "sensitivity_cdf_pod_creation_delays.png"),
        ('pod_startup_delays', "Sensitivity Analysis: CDF of Pod Startup Delays", "Pod Startup Delays [ms]", "sensitivity_cdf_pod_startup_delays.png"),
        ('mean_latencies', "Sensitivity Analysis: CDF of Mean Latencies", "Mean Latencies [ms]", "sensitivity_cdf_mean_latencies.png"),
        ('max_latencies', "Sensitivity Analysis: CDF of Max Latencies", "Max Latencies [ms]", "sensitivity_cdf_max_latencies.png")
    ]
    
    for metric_key, title, xlabel, fname in cdf_plots_config:
        save_comparative_cdf_plot(
            km_data_15[metric_key], pk8s_data_15[metric_key],
            km_data_30[metric_key], pk8s_data_30[metric_key],
            km_data_45[metric_key], pk8s_data_45[metric_key],
            title, xlabel, fname, str(output_dir)
        )
    
    print("\n" + "="*60)
    print("Sensitivity analysis completed successfully!")
    print(f"All results saved to: {output_dir}")
    print("="*60)


if __name__ == "__main__":
    main()
