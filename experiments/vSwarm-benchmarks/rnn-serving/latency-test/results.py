import sys
import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path

def read_latency_data(service_dir):
    latencies = []
    for i in range(1, 31):
        file_path = os.path.join(service_dir, f"latency-iteration-{i}.txt")
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                content = f.read().strip()
                if content:
                    latencies.append(float(content))
    return latencies

def calculate_statistics(latencies):
    data = np.array(latencies)
    return {
        'mean': np.mean(data),
        'min': np.min(data),
        'max': np.max(data),
        'variance': np.var(data),
        'std_dev': np.std(data),
    }

def create_boxplot(all_data, services, output_dir):
    plt.figure(figsize=(12, 6))
    
    data_to_plot = [all_data[service] for service in services]
    
    plt.boxplot(data_to_plot, labels=services)
    plt.xlabel('Service', fontsize=12)
    plt.ylabel('Latency [ms]', fontsize=12)
    plt.title('Per Service Latency Boxplot', fontsize=14, fontweight='bold')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    
    file_path = os.path.join(output_dir, 'boxplot.png')
    plt.savefig(file_path, dpi=300, bbox_inches='tight')
    print(f"✓ Boxplot saved in {file_path}")
    plt.close()

def create_cdf(all_data, services, output_dir):
    plt.figure(figsize=(12, 6))
    
    for service in services:
        data = np.sort(all_data[service])
        cdf = np.arange(1, len(data) + 1) / len(data)
        plt.plot(data, cdf, marker='.', linestyle='-', label=service, linewidth=2)
    
    plt.xlabel('Latency [ms]', fontsize=12)
    plt.ylabel('CDF', fontsize=12)
    plt.title('Latency Cumulative Distribution Function', fontsize=14, fontweight='bold')
    plt.legend(loc='best')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    
    file_path = os.path.join(output_dir, 'cdf.png')
    plt.savefig(file_path, dpi=300, bbox_inches='tight')
    print(f"✓ CDF combined saved in {file_path}")
    plt.close()

def create_aggregated_boxplots(all_data, output_dir):
    aggregated_data = []
    for service_data in all_data.values():
        aggregated_data.extend(service_data)
    
    plt.figure(figsize=(8, 6))
    plt.boxplot([aggregated_data], labels=['All Services'])
    plt.xlabel('Aggregated Services', fontsize=12)
    plt.ylabel('Latency [ms]', fontsize=12)
    plt.title('Aggregated Latency Boxplot', fontsize=14, fontweight='bold')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    
    file_path = os.path.join(output_dir, 'boxplot_aggregated.png')
    plt.savefig(file_path, dpi=300, bbox_inches='tight')
    print(f"✓ Aggregated boxplot saved in {file_path}")
    plt.close()

def create_aggregated_cdf(all_data, output_dir):
    aggregated_data = []
    for service_data in all_data.values():
        aggregated_data.extend(service_data)

    plt.figure(figsize=(12, 6))
    data_sorted = np.sort(aggregated_data)
    cdf = np.arange(1, len(data_sorted) + 1) / len(data_sorted)
    plt.plot(data_sorted, cdf, marker='.', linestyle='-', linewidth=2, label='All Services')
    
    plt.xlabel('Latency [ms]', fontsize=12)
    plt.ylabel('CDF', fontsize=12)
    plt.title('Aggregated Latency Cumulative Distribution Function', fontsize=14, fontweight='bold')
    plt.legend(loc='best')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    
    file_path = os.path.join(output_dir, 'cdf_aggregated.png')
    plt.savefig(file_path, dpi=300, bbox_inches='tight')
    print(f"✓ Aggregated CDF saved in {file_path}")
    plt.close()

def save_statistics_to_csv(all_stats, output_dir):
    df = pd.DataFrame(all_stats).T
    df.index.name = 'Service'
    
    columns_order = ['mean', 'min', 'max', 'variance', 'std_dev']
    df = df[columns_order]
    
    csv_path = os.path.join(output_dir, 'statistics.csv')
    df.to_csv(csv_path)
    print(f"\n✓ Statistics saved in {csv_path}")

def main():
    # Validate command line arguments
    if len(sys.argv) != 3:
        print("Usage: python results.py <path_to_results_directory> <path_to_aggregated_output_directory>")
        sys.exit(1)
    
    results_dir = sys.argv[1]
    aggregated_dir = sys.argv[2]
    
    # Check if the provided paths are valid directory
    if not os.path.isdir(results_dir):
        print(f"Error: {results_dir} is not a valid directory!")
        sys.exit(1)

    if not os.path.isdir(aggregated_dir):
        print(f"Error: {aggregated_dir} is not a valid directory!")
        sys.exit(1)
    
    output_dir = os.path.join(results_dir, "processed_results")

    results_dir_obj = Path(results_dir)
    output_aggregated_dir = os.path.join(aggregated_dir, f"{results_dir_obj.parent.name}_{results_dir_obj.name}")
    
    if not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
        print(f"Created output directory: {output_dir}")
    else:
        print(f"Output directory already exists: {output_dir}")
    
    if not os.path.exists(output_aggregated_dir):
        os.makedirs(output_aggregated_dir, exist_ok=True)
        print(f"Created aggregated output directory: {output_aggregated_dir}")
    else:
        print(f"Aggregated output directory already exists: {output_aggregated_dir}")

    # Find all service directories
    services = sorted([d.name for d in os.scandir(results_dir) if d.is_dir() and d.name.startswith('service-')])
    print(f"Services found: {', '.join(services)}\n")
    
    # Read data for each service
    all_data = {}
    all_stats = {}
    
    for service in services:
        service_dir = os.path.join(results_dir, service)
        print(f"Processing {service}...")
        
        # Read data
        latencies = read_latency_data(service_dir)
        all_data[service] = latencies
        
        # Calculate statistics
        stats = calculate_statistics(latencies)
        all_stats[service] = stats
    
    # Create boxplots
    print("Generating box plots...")
    create_boxplot(all_data, services, output_dir)
    
    print()
    
    # Create CDFs
    print("Generating CDF plots...")
    create_cdf(all_data, services, output_dir)
    
    # Save statistics to CSV
    save_statistics_to_csv(all_stats, output_dir)

    # Create aggregated boxplots
    print("\nGenerating aggregated boxplots...")
    create_aggregated_boxplots(all_data, output_aggregated_dir)

    # Create aggregated cdf
    print("\nGenerating aggregated cdf...")
    create_aggregated_cdf(all_data, output_aggregated_dir)
    
    print("Processing completed!")

if __name__ == "__main__":
    main()
