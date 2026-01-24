#!/bin/bash

# Exits immediately if a command exits with a non-zero status,
# if an undefined variable is used,
# or if any command in a pipeline fails
set -e
set -u
set -o pipefail

# Default values
TEST_TYPE="Deployment"
NUMBER_OF_INTERFERING_RESOURCES="1"
CRITICALITY_LEVEL="2"
BUCKET_NODE="dessertw3"

# Parse command line flags
while getopts "t:i:c:n:h" opt; do
    case $opt in
        t) TEST_TYPE="$OPTARG" ;;
        i) NUMBER_OF_INTERFERING_RESOURCES="$OPTARG" ;;
        c) CRITICALITY_LEVEL="$OPTARG" ;;
        n) BUCKET_NODE="$OPTARG" ;;
        h) 
            echo "Usage: $0 [-t <test-type>] [-i <number-of-interfering-resources>] [-c <criticality-level>] [-h]"
            echo ""
            echo "Options:"
            echo "  -t <test-type>      Type of test to run (default: Deployment)"
            echo "  -i <number>         Number of interfering resources (default: 1)"
            echo "  -c <level>          Criticality level for RTResources, not used for Deployments (default: 2)"
            echo "  -n <node-name>      Node to target for interference (default: dessertw3)"
            echo "  -h                  Show this help message"
            exit 0
            ;;
        \?) 
            echo "Error: Invalid option -$OPTARG" >&2
            echo "Use -h for help" >&2
            exit 1
            ;;
        :)
            echo "Error: Option -$OPTARG requires an argument" >&2
            exit 1
            ;;
    esac
done

# Validate test type
if [[ "$TEST_TYPE" != "Deployment" && "$TEST_TYPE" != "RTResource" ]]; then
    echo "Error: Test type must be either 'Deployment' or 'RTResource' (got: $TEST_TYPE)" >&2
    exit 1
fi

# Validate number of interfering resources is a positive number
if ! [[ "$NUMBER_OF_INTERFERING_RESOURCES" =~ ^[0-9]+$ ]] || [[ "$NUMBER_OF_INTERFERING_RESOURCES" -lt 1 ]]; then
    echo "Error: Number of interfering resources must be a positive number (got: $NUMBER_OF_INTERFERING_RESOURCES)" >&2
    exit 1
fi

# Validate criticality level is a positive number
if ! [[ "$CRITICALITY_LEVEL" =~ ^[0-9]+$ ]] || [[ "$CRITICALITY_LEVEL" -lt 1 ]]; then
    echo "Error: Criticality level must be a positive number (got: $CRITICALITY_LEVEL)" >&2
    exit 1
fi

# Validate bucket node exists
if ! kubectl get node "$BUCKET_NODE" &>/dev/null; then
    echo "Error: Specified bucket node '$BUCKET_NODE' does not exist" >&2
    exit 1
fi

# Display configuration
echo "================================================"
echo "Interfering Load - Starting"
echo "================================================"
echo "Test Type:     $TEST_TYPE"
echo "Number of Interfering Resources: $NUMBER_OF_INTERFERING_RESOURCES"
if [[ "$TEST_TYPE" == "RTResource" ]]; then
    echo "Criticality Level: $CRITICALITY_LEVEL"
fi
echo "Bucket Node: $BUCKET_NODE"
echo "================================================"
echo ""

# Ensure interference namespace exists
if ! kubectl get namespace interference &>/dev/null; then
    echo "Creating interference namespace..."
    if ! kubectl create namespace interference; then
        echo "Error: Failed to create interference namespace" >&2
        exit 1
    fi
else
    echo "Namespace interference already exists"
fi
echo ""

# Array to track created deployments and rtresources for cleanup
CREATED_DEPLOYMENTS=()
CREATED_RTRESOURCES=()

# Cleanup function to remove all created deployments
cleanup() {
    echo ""
    echo "================================================"
    echo "Received termination signal - Cleaning up..."
    echo "================================================"
    
    if [[ ${#CREATED_DEPLOYMENTS[@]} -gt 0 ]]; then
        echo "Deleting created interfering deployments..."
        for deployment in "${CREATED_DEPLOYMENTS[@]}"; do
            kubectl delete deployment "$deployment" -n interference --ignore-not-found=true &
        done
        wait
        echo "All interfering deployments deleted"
    else
        echo "No interfering deployments to clean up"
    fi
    
    if [[ ${#CREATED_RTRESOURCES[@]} -gt 0 ]]; then
        echo "Deleting created interfering rtresources..."
        for rtresource in "${CREATED_RTRESOURCES[@]}"; do
            kubectl delete rtresource "$rtresource" -n interference --ignore-not-found=true &
        done
        wait
        echo "All interfering rtresources deleted"
    else
        echo "No interfering rtresources to clean up"
    fi

    echo "================================================"
    echo "Cleanup completed"
    echo "================================================"
    exit 0
}

# Set up trap to catch termination signals
trap cleanup SIGINT SIGTERM

# Function to generate and apply a deployment
generate_deployment() {
    local deployment_name=$1
    
    cat <<EOF | kubectl apply -f - &>/dev/null
apiVersion: apps/v1
kind: Deployment
metadata:
  name: $deployment_name
  namespace: interference
  labels:
    app: $deployment_name
spec:
  replicas: 1
  selector:
    matchLabels:
      app: $deployment_name
  template:
    metadata:
      labels:
        app: $deployment_name
    spec:
      nodeSelector:
        kubernetes.io/hostname: $BUCKET_NODE
      containers:
      - name: interfering-container
        image: nginx:latest
        ports:
          - containerPort: 80
        resources:
          requests:
            cpu: "700m"
            memory: "200Mi"
          limits:
            cpu: "700m"
            memory: "200Mi"
EOF
    
    return $?
}

# Function to delete a deployment
remove_deployment() {
    local deployment_name=$1

    kubectl delete deployment "$deployment_name" -n interference --ignore-not-found=true
    
    return $?
}

# Function to generate and apply an rtresource
generate_rtresource() {
    local rtresource_name=$1
    
    cat <<EOF | kubectl apply -f - &>/dev/null
apiVersion: rtgroup.critical.com/v1
kind: RTResource
metadata:
  name: $rtresource_name
  namespace: interference
  labels:
    app: $rtresource_name
spec:
  namespace: interference
  replicas: 1
  selector:
    matchLabels:
      app-selector: $rtresource_name
  criticality: $CRITICALITY_LEVEL
  template:
    metadata:
      labels:
        app-selector: $rtresource_name
    spec:
      nodeSelector:
        kubernetes.io/hostname: $BUCKET_NODE
      containers:
        - name: interfering-container
          image: nginx:latest
          ports:
            - containerPort: 80
          resources:
            requests:
              cpu: "700m"
              memory: "200Mi"
            limits:
              cpu: "700m"
              memory: "200Mi"
EOF
    
    return $?
}

# Function to delete an rtresource
remove_rtresource() {
    local rtresource_name=$1

    kubectl delete rtresource "$rtresource_name" -n interference --ignore-not-found=true
    
    return $?
}

# Interference load generation loop
if [[ "$TEST_TYPE" == "Deployment" ]]; then
    echo "================================================"
    echo "Starting continuous deployment interference..."
    echo "Press Ctrl+C to stop and cleanup"
    echo "================================================"
    echo ""
    
    DEPLOYMENT_BATCH=0
    
    while true; do
        DEPLOYMENT_BATCH=$((DEPLOYMENT_BATCH + 1))

        echo "Generating ${DEPLOYMENT_BATCH}th creation burst with $NUMBER_OF_INTERFERING_RESOURCES deployment(s)..."
        for i in $(seq 1 "$NUMBER_OF_INTERFERING_RESOURCES"); do
            DEPLOYMENT_NAME="interfering-deployment-$i"
            
            echo "  Creating deployment: $DEPLOYMENT_NAME"
            
            (
                if generate_deployment "$DEPLOYMENT_NAME"; then
                    echo "    ✓ Deployment created successfully: $DEPLOYMENT_NAME"
                else
                    echo "    ✗ Failed to create deployment: $DEPLOYMENT_NAME" >&2
                fi
            ) &
            CREATED_DEPLOYMENTS+=("$DEPLOYMENT_NAME")
        done
        wait
        
        # Small delay between control plane interfering bursts to avoid overwhelming the API server
        sleep 0.1

        echo "Generating ${DEPLOYMENT_BATCH}th deletion burst with $NUMBER_OF_INTERFERING_RESOURCES deployment(s)..."
        for i in $(seq 1 "$NUMBER_OF_INTERFERING_RESOURCES"); do
            DEPLOYMENT_NAME="interfering-deployment-$i"

            echo "  Deleting deployment: $DEPLOYMENT_NAME"

            (
                if remove_deployment "$DEPLOYMENT_NAME"; then
                    echo "    ✓ Deployment deleted successfully: $DEPLOYMENT_NAME"
                else
                    echo "    ✗ Failed to delete deployment: $DEPLOYMENT_NAME" >&2
                fi
            ) &
        done
        wait
        
        # Clear the array after deletion since we've removed all deployments
        CREATED_DEPLOYMENTS=()

        # Small delay between control plane interfering bursts to avoid overwhelming the API server
        sleep 0.1
    done
    
elif [[ "$TEST_TYPE" == "RTResource" ]]; then
    echo "================================================"
    echo "Starting continuous rtresource interference..."
    echo "Press Ctrl+C to stop and cleanup"
    echo "================================================"
    echo ""
    
    RTRESOURCE_BATCH=0
    
    while true; do
        RTRESOURCE_BATCH=$((RTRESOURCE_BATCH + 1))

        echo "Generating ${RTRESOURCE_BATCH}th creation burst with $NUMBER_OF_INTERFERING_RESOURCES rtresource(s)..."
        for i in $(seq 1 "$NUMBER_OF_INTERFERING_RESOURCES"); do
            RTRESOURCE_NAME="interfering-rtresource-$i"
            
            echo "  Creating rtresource: $RTRESOURCE_NAME"
            
            (
                if generate_rtresource "$RTRESOURCE_NAME"; then
                    echo "    ✓ Rtresource created successfully: $RTRESOURCE_NAME"
                else
                    echo "    ✗ Failed to create rtresource: $RTRESOURCE_NAME" >&2
                fi
            ) &
            CREATED_RTRESOURCES+=("$RTRESOURCE_NAME")
        done
        wait
        
        # Small delay between control plane interfering bursts to avoid overwhelming the API server
        sleep 0.1

        echo "Generating ${RTRESOURCE_BATCH}th deletion burst with $NUMBER_OF_INTERFERING_RESOURCES rtresource(s)..."
        for i in $(seq 1 "$NUMBER_OF_INTERFERING_RESOURCES"); do
            RTRESOURCE_NAME="interfering-rtresource-$i"

            echo "  Deleting rtresource: $RTRESOURCE_NAME"

            (
                if remove_rtresource "$RTRESOURCE_NAME"; then
                    echo "    ✓ Rtresource deleted successfully: $RTRESOURCE_NAME"
                else
                    echo "    ✗ Failed to delete rtresource: $RTRESOURCE_NAME" >&2
                fi
            ) &
        done
        wait
        
        # Clear the array after deletion since we've removed all rtresources
        CREATED_RTRESOURCES=()

        # Small delay between control plane interfering bursts to avoid overwhelming the API server
        sleep 0.1
    done
    
fi

echo "================================================"
echo "All test iterations completed successfully!"
echo "================================================"
