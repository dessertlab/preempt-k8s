import os
import sys
import csv
import re
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


def main():
    # Validate command line arguments
    if len(sys.argv) != 2:
        print("Usage: python analyze_results.py <path_to_results_directory>")
        sys.exit(1)
    
    root_path = sys.argv[1]
    
    # Check if the provided path is a valid directory
    if not os.path.isdir(root_path):
        print(f"Error: {root_path} is not a valid directory!")
        sys.exit(1)
    
    # Check if processed_results directory already exists
    processed_dir = os.path.join(root_path, "processed_results")
    if os.path.exists(processed_dir):
        print(f"Error: Directory {processed_dir} already exists!")
        sys.exit(1)
    
    print(f"Scanning directories in {root_path}...")

    # Count status and rps files
    all_files = os.listdir(root_path)
    status_files = [f for f in all_files if f.startswith("iteration") and os.path.isfile(os.path.join(root_path, f))]
    rps_files = [f for f in all_files if f.startswith("rps") and os.path.isfile(os.path.join(root_path, f))]
    
    status_count = len(status_files)
    rps_count = len(rps_files)
    
    print(f"Found {status_count} status files and {rps_count} rps files!")
    
    # Check if there are exactly 30 status files and 30 rps files
    if status_count != 30:
        print(f"Error: Expected exactly 30 status files, but found {status_count}!")
        sys.exit(1)
    
    if rps_count != 30:
        print(f"Error: Expected exactly 30 rps files, but found {rps_count}!")
        sys.exit(1)
    
    print("File count validation passed!")
    
    # Create processed_results directory
    processed_dir = os.path.join(root_path, "processed_results")
    if not os.path.exists(processed_dir):
        os.makedirs(processed_dir)
        print(f"Created directory: {processed_dir}!")
    else:
        print(f"Directory already exists: {processed_dir}!")
    
    # Process all status files
    print("\nProcessing status files...")
    lost_requests = []
    
    for status_file in sorted(status_files):
        file_path = os.path.join(root_path, status_file)
        try:
            data = parse_status_file(file_path)
            lost = data['issued'] - data['completed']
            lost_requests.append(lost)
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)
    
    # Calculate statistics for lost requests
    mean_lost = sum(lost_requests) / len(lost_requests)
    max_lost = max(lost_requests)
    
    # Process all rps files
    print("\nProcessing rps files...")
    mean_latencies = []
    max_latencies = []
    
    for rps_file in sorted(rps_files):
        file_path = os.path.join(root_path, rps_file)
        try:
            latencies = parse_rps_file(file_path)
            mean_lat = sum(latencies) / len(latencies)
            max_lat = max(latencies)
            mean_latencies.append(mean_lat)
            max_latencies.append(max_lat)
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)
    
    # Calculate statistics for latencies
    mean_of_mean_latencies = sum(mean_latencies) / len(mean_latencies)
    mean_of_max_latencies = sum(max_latencies) / len(max_latencies)

    # Latencies statistics in milliseconds (from microseconds)
    mean_of_mean_latencies_ms = mean_of_mean_latencies / 1000
    mean_of_max_latencies_ms = mean_of_max_latencies / 1000
    
    # Write results to CSV
    csv_path = os.path.join(processed_dir, "metrics.csv")
    with open(csv_path, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['Metric', 'Mean', 'Max'])
        writer.writerow(['Lost-Requests', f"{mean_lost:.2f}", max_lost])
        writer.writerow(['Mean-Latency', f"{mean_of_mean_latencies_ms:.2f}", f"{max(mean_latencies) / 1000:.2f}"])
        writer.writerow(['Max-Latency', f"{mean_of_max_latencies_ms:.2f}", f"{max(max_latencies) / 1000:.2f}"])
    
    print(f"\nResults saved to: {csv_path}")
    
    # Create box plots
    print("\nCreating box plots...")
    
    # Box plot for Lost Requests
    fig, ax = plt.subplots(figsize=(6, 6))
    bp = ax.boxplot([lost_requests], labels=['RNN Service Scale 1->2'], patch_artist=True)
    bp['boxes'][0].set_facecolor('blue')
    ax.grid(True, axis='y', linestyle='--', alpha=0.7)
    ax.set_xlabel('Metric', fontsize=12)
    ax.set_ylabel('Value', fontsize=12)
    ax.set_title('Lost Requests Box Plot', fontsize=14, fontweight='bold')
    plot_path = os.path.join(processed_dir, "boxplot_lost_requests.png")
    plt.tight_layout()
    plt.savefig(plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Lost Requests box plot saved to: {plot_path}")
    
    # Box plot for Mean Latencies
    fig, ax = plt.subplots(figsize=(6, 6))
    mean_latencies_ms = [lat / 1000 for lat in mean_latencies]
    bp = ax.boxplot([mean_latencies_ms], labels=['Mean-Latency'], patch_artist=True)
    bp['boxes'][0].set_facecolor('green')
    ax.grid(True, axis='y', linestyle='--', alpha=0.7)
    ax.set_xlabel('Metric', fontsize=12)
    ax.set_ylabel('Value [ms]', fontsize=12)
    ax.set_title('Mean Latency Box Plot', fontsize=14, fontweight='bold')
    plot_path = os.path.join(processed_dir, "boxplot_mean_latency.png")
    plt.tight_layout()
    plt.savefig(plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Mean Latency box plot saved to: {plot_path}")
    
    # Box plot for Max Latencies
    fig, ax = plt.subplots(figsize=(6, 6))
    max_latencies_ms = [lat / 1000 for lat in max_latencies]
    bp = ax.boxplot([max_latencies_ms], labels=['Max-Latency'], patch_artist=True)
    bp['boxes'][0].set_facecolor('red')
    ax.grid(True, axis='y', linestyle='--', alpha=0.7)
    ax.set_xlabel('Metric', fontsize=12)
    ax.set_ylabel('Value [ms]', fontsize=12)
    ax.set_title('Max Latency Box Plot', fontsize=14, fontweight='bold')
    plot_path = os.path.join(processed_dir, "boxplot_max_latency.png")
    plt.tight_layout()
    plt.savefig(plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Max Latency box plot saved to: {plot_path}")
    
    # CDF for Mean Latencies
    print("\nCreating CDF plots...")
    fig, ax = plt.subplots(figsize=(8, 6))
    sorted_mean_lat = np.sort(mean_latencies_ms)
    cdf_mean = np.arange(1, len(sorted_mean_lat) + 1) / len(sorted_mean_lat)
    ax.plot(sorted_mean_lat, cdf_mean, marker='o', linestyle='-', linewidth=2, markersize=4)
    ax.grid(True, linestyle='--', alpha=0.7)
    ax.set_xlabel('Latency [ms]', fontsize=12)
    ax.set_ylabel('CDF', fontsize=12)
    ax.set_title('CDF of Mean Latencies', fontsize=14, fontweight='bold')
    plot_path = os.path.join(processed_dir, "cdf_mean_latency.png")
    plt.tight_layout()
    plt.savefig(plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Mean Latency CDF saved to: {plot_path}")
    
    # CDF for Max Latencies
    fig, ax = plt.subplots(figsize=(8, 6))
    sorted_max_lat = np.sort(max_latencies_ms)
    cdf_max = np.arange(1, len(sorted_max_lat) + 1) / len(sorted_max_lat)
    ax.plot(sorted_max_lat, cdf_max, marker='o', linestyle='-', linewidth=2, markersize=4, color='red')
    ax.grid(True, linestyle='--', alpha=0.7)
    ax.set_xlabel('Latency [ms]', fontsize=12)
    ax.set_ylabel('CDF', fontsize=12)
    ax.set_title('CDF of Max Latencies', fontsize=14, fontweight='bold')
    plot_path = os.path.join(processed_dir, "cdf_max_latency.png")
    plt.tight_layout()
    plt.savefig(plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Max Latency CDF saved to: {plot_path}")


if __name__ == "__main__":
    main()
