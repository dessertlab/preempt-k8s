import os
import sys
from matplotlib.ticker import FuncFormatter, MaxNLocator
import matplotlib.pyplot as plt
import numpy as np
import math
from pathlib import Path
from results import (
    parse_rps_file,
)


def trim_float(value: float) -> str:
    """Format a float with up to 2 decimals, trimming trailing zeros.

    Examples:
    - 1.00 -> '1'
    - 1.50 -> '1.50'
    - 1.23 -> '1.23'
    """
    # Keep two decimals except when the value is an exact integer (i.e. .00)
    # Round to 2 decimals to avoid floating point noise
    val = round(value, 2)
    if float(val).is_integer():
        return str(int(val))
    return f"{val:.2f}"


def save_comparative_cdf_plot(data_km_15, data_pk8s_15, data_km_30, data_pk8s_30,
                             data_km_45, data_pk8s_45, filename, directory):
    """
    Create sensitivity analysis CDF plots with 6 lines (3 parameter values x 2 controllers).
    Shows how CDFs vary with parameter values (15, 30, 45) for both controllers.
    """
    # Set professional style
    plt.rcParams['font.family'] = 'sans-serif'
    plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Arial', 'Helvetica']
    
    # Arrange subplots horizontally (3 columns), share Y axis (CDF)
    fig, axes = plt.subplots(1, 3, figsize=(17, 7), sharey=True, constrained_layout=True)
    
    # Scientific colorblind-friendly palette
    color_km = '#42a5f5'   # Blue for kube-manager
    color_pk8s = '#FF8000'  # Orange for preempt-k8s (not too bright)
    
    # Define markers for key percentiles
    marker_km = '^'
    marker_pk8s = 's'

    # configs = [
    #     (axes[0], data_km_15, data_pk8s_15, "15", '#FFE680'),
    #     (axes[1], data_km_30, data_pk8s_30, "30", '#FFB366'),
    #     (axes[2], data_km_45, data_pk8s_45, "45", '#FF8FA3'),
    # ]
    configs = [
        (axes[0], data_km_15, data_pk8s_15, "15 Stressload", '#FFFFFF'),
        (axes[1], data_km_30, data_pk8s_30, "30 Stressload", '#FFFFFF'),
        (axes[2], data_km_45, data_pk8s_45, "45 Stressload", '#FFFFFF'),
    ]
    
    # Plot CDFs with markers at key percentiles
    for ax, data_km, data_pk8s, label, bg_color in configs:

        ax.set_ylim([0, 1.02])
        ax.margins(y=0)
        ax.margins(x=0)

        # Background band (like boxplot logic but horizontal)
        ax.set_facecolor(bg_color)
        ax.patch.set_alpha(0.35)

        for data, name, color, marker in [
            (data_km, "Vanilla K8s", color_km, marker_km),
            (data_pk8s, "Preempt-K8s", color_pk8s, marker_pk8s)
        ]:

            sorted_data = np.sort(data)
            if len(sorted_data) > 0:
                cdf = np.arange(1, len(sorted_data) + 1) / len(sorted_data)

                # Choose linestyle: solid for Vanilla, dashed for Preempt
                linestyle = '-' if 'Vanilla' in name else '--'

                # Plot main CDF line
                ax.plot(sorted_data, cdf,
                        label=name,
                        color=color,
                        linestyle=linestyle,
                        linewidth=7.0,
                        alpha=0.95)

                # Add markers at key percentiles
                percentiles = [0.25, 0.50, 0.75, 0.95]
                for p in percentiles:
                    idx = int(p * len(sorted_data))
                    if idx < len(sorted_data):
                        ax.plot(sorted_data[idx],
                                cdf[idx],
                                marker=marker,
                                markersize=20,
                                color=color,
                                markeredgecolor='white',
                                markeredgewidth=1.5,
                                zorder=5)

        # Parameter label: use it as the subplot title (aligned right)
        ax.set_title(f"{label}", fontsize=35, fontweight='bold', loc='center')

        # Professional styling
        ax.grid(True, linestyle='--', alpha=0.25, linewidth=0.8, color='#888888')
        ax.set_ylim([0, 1.02])
        ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
        ax.yaxis.set_major_formatter(FuncFormatter(lambda y, pos: trim_float(y)))
        ax.tick_params(axis='y', which='major', labelsize=35)
        ax.tick_params(axis='x', which='major', labelsize=35)
        # for label in ax.get_yticklabels():
        #     label.set_fontweight('semibold')
        # for label in ax.get_xticklabels():
        #     label.set_fontweight('semibold')

        # Remove top/right spines
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_linewidth(1.2)
        ax.spines['bottom'].set_linewidth(1.2)

    for ax in axes:
        ax.xaxis.set_major_formatter(FuncFormatter(lambda x, pos: trim_float(x/1000)))
        ax.xaxis.set_major_locator(MaxNLocator(nbins=6, steps=[1, 2, 4, 5, 10]))

        # slight left padding so 0 isn't flush with the y-axis
        x0, x1 = ax.get_xlim()
        pad = 0.02 * (x1 - x0)  # 2% of the current x-range; adjust if needed
        ax.set_xlim(left=(x0 - pad), right=x1)

    # Shared X label for the figure (common xlabel)
    fig.supxlabel('Time (s)', fontsize=35, fontweight='semibold', ha='center')

    # Shared Y label for the figure (common CDF label)
    fig.supylabel('E2E Latency CDF', fontsize=35, fontweight='semibold', ha='center')

    # Add legend at the bottom (thicker lines)
    from matplotlib.lines import Line2D

    legend_elements = [
        Line2D([0], [0],
            color=color_km,
            lw=4.0,
            linestyle='-',
            marker='^',
            markersize=15,
            markeredgecolor='white',
            markeredgewidth=1.5,
            label='Vanilla K8s'),

        Line2D([0], [0],
            color=color_pk8s,
            lw=4.0,
            linestyle='--',
            marker='s',
            markersize=15,
            markeredgecolor='white',
            markeredgewidth=1.5,
            label='Preempt-FaaS')
    ]
    fig.legend(handles=legend_elements,
               loc='lower center',
               bbox_to_anchor=(0.5, -0.15),
               ncol=2,
               prop={'size': 30, 'weight': 'semibold'},
               framealpha=0.95,
               edgecolor='gray',
               fancybox=True)

    plot_path_png = os.path.join(directory, filename)
    plt.savefig(plot_path_png, dpi=300, bbox_inches='tight', facecolor='white')
    plt.close()

    print(f"CDF Plot saved to: {plot_path_png}")


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
    rps_files = {}
    for i in range(num_services):
        service_name = f"service-{i+1}"
        service_path = os.path.join(root_path, service_name)
        
        if os.path.isdir(service_path):
            all_files = os.listdir(service_path)
            rps_files[service_name] = sorted([f for f in all_files if f.startswith("rps") and os.path.isfile(os.path.join(service_path, f))])
    
    # Determine number of iterations
    num_iterations = 10
    
    # Process status and rps files - organized by iteration
    print("\nProcessing status and rps files...")
    all_mean_latencies = []
    
    for iter_idx in range(num_iterations):
        print(f"  Processing iteration {iter_idx + 1}")
        
        # Temporary lists to collect data from all services for this iteration
        iteration_all_latencies = []
        
        for i in range(num_services):
            service_name = f"service-{i+1}"
            
            # Process rps file for this iteration - accumulate ALL latencies
            if iter_idx < len(rps_files[service_name]):
                rps_file = rps_files[service_name][iter_idx]
                file_path = os.path.join(root_path, service_name, rps_file)
                try:
                    latencies = parse_rps_file(file_path)
                    iteration_all_latencies.extend(latencies)
                except Exception as e:
                    print(f"    Error parsing {rps_file}: {str(e)}")
        
        # Convert from microseconds to milliseconds
        iteration_all_latencies_ms = [lat / 1000 for lat in iteration_all_latencies]
        
        # Append values for this iteration
        all_mean_latencies.extend(iteration_all_latencies_ms)
    
    return all_mean_latencies


def main():
    # Validate command line arguments
    if len(sys.argv) != 8:
        print(
            "Usage: " \
            "python all-mean-latency-cdf.py " \
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

    # print 50th percentiles (median) for each dataset
    def print_median(data, label):
        if data:
            p50 = np.percentile(data, 50)
            p95 = np.percentile(data, 95)
            print(f"{label} 50th percentile = {p50:.2f} ms")
            print(f"{label} 95th percentile = {p95:.2f} ms")
        else:
            print(f"{label} has no data to calculate percentile")

    print("\nComputed 50th and 95th percentiles:")
    print_median(km_data_45, "kube-manager 45")
    print_median(pk8s_data_45, "preempt-k8s 45")
    
    # Create sensitivity analysis box plots
    print("\n" + "="*60)
    print("Creating sensitivity analysis box plots...")
    print("="*60)
    
    # Create sensitivity analysis CDF plots
    print("\n" + "="*60)
    print("Creating sensitivity analysis CDF plots...")
    print("="*60)
    
    save_comparative_cdf_plot(
        km_data_15, pk8s_data_15,
        km_data_30, pk8s_data_30,
        km_data_45, pk8s_data_45,
        "sensitivity_cdf_all_mean_latencies.png", str(output_dir)
    )
    
    print("\n" + "="*60)
    print("Sensitivity analysis completed successfully!")
    print(f"All results saved to: {output_dir}")
    print("="*60)


if __name__ == "__main__":
    main()
