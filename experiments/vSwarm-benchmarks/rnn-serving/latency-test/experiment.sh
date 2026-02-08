#!/bin/bash

# Exits immediately if a command exits with a non-zero status,
# if an undefined variable is used,
# or if any command in a pipeline fails
set -e
set -u
set -o pipefail

# Default values
EXPERIMENT_NAME="rnn-serving-benchmark"
TEST_TYPE="Deployment"
TEST_POD_BASE_NAME="benchmark-pod"
TEST_PATH="/home"
NUMBER_OF_SERVICES="10"
SERVICE_MANIFEST_BASE_NAME="kn-rnn-serving-python"
SERVICE_PORT="80"
ITERATIONS="1"
OFFSET="0"
INTERFERENCE_SCRIPT="interfering-load.sh"
NUMBER_OF_INTERFERING_RESOURCES="40"
BASE_SCALE="0"
SCALE_UPS_ALLOWED="1"
FORCE_CLEANUP="true"

# Parse command line flags
while getopts "f:t:i:e:c:m:p:n:g:s:r:b:u:w:h" opt; do
    case $opt in
        f) EXPERIMENT_NAME="$OPTARG" ;;
        t) TEST_TYPE="$OPTARG" ;;
        i) TEST_POD_BASE_NAME="$OPTARG" ;;
        e) TEST_PATH="$OPTARG" ;;
        c) NUMBER_OF_SERVICES="$OPTARG" ;;
        m) SERVICE_MANIFEST_BASE_NAME="$OPTARG" ;;
        p) SERVICE_PORT="$OPTARG" ;;
        n) ITERATIONS="$OPTARG" ;;
        g) OFFSET="$OPTARG" ;;
        s) INTERFERENCE_SCRIPT="$OPTARG" ;;
        r) NUMBER_OF_INTERFERING_RESOURCES="$OPTARG" ;;
        b) BASE_SCALE="$OPTARG" ;;
        u) SCALE_UPS_ALLOWED="$OPTARG" ;;
        w) FORCE_CLEANUP="$OPTARG" ;;
        h) 
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  -f <experiment-name>                Name of the experiment (default: rnn-serving-benchmark)"
            echo "  -t <test-type>                      Type of test to run (default: Deployment)"
            echo "  -i <test-pod-base-name>             Test pod base name in default namespace (default: benchmark-pod)"
            echo "  -e <test-path>                      Path to test directory inside the pods (default: /home)"
            echo "  -c <number-of-services>             Number of concurrent RNN Knative services to deploy (default: 10)"
            echo "  -m <service-manifest-base-name>     Services manifest file base name (default: kn-rnn-serving-python)"
            echo "  -p <service-port>                   Services port (default: 80)"
            echo "  -n <iterations>                     Number of test iterations (default: 1)"
            echo "  -g <offset>                         Iterations offset (default: 0)"
            echo "  -s <interference-script>            Interference script to run (default: interfering-load.sh)"
            echo "  -r <number-of-resources>            Number of interfering resources (default: 40)"
            echo "  -b <base-scale>                     Base scale for the tested services (default: 0)"
            echo "  -u <scale-ups-allowed>              Number of allowed scale-up pods per service (default: 1)"
            echo "  -w <force-cleanup>                  Force cleanup of tested services' resources after test, use when pods require too much time to terminate (default: true)"
            echo "  -h                                  Show this help message"
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

# Validate test pods
EXISTING_PODS=$(kubectl get pods --no-headers 2>/dev/null | { grep "^$TEST_POD_BASE_NAME" || true; } | wc -l)
if [[ "$EXISTING_PODS" -ne "$NUMBER_OF_SERVICES" ]]; then
    echo "Error: Test pods number ($EXISTING_PODS) does not match the specified number ($NUMBER_OF_SERVICES)" >&2
    exit 1
fi

# Validate grpcurl binary
for i in $(seq 1 "$NUMBER_OF_SERVICES"); do
    TEST_POD="${TEST_POD_BASE_NAME}-$i"
    if ! kubectl exec "$TEST_POD" -- bash -c "[ -x \"/usr/local/bin/grpcurl\" ]"; then
        echo "Error: grpcurl binary '/usr/local/bin/grpcurl' does not exist or is not executable in pod '$TEST_POD'" >&2
        exit 1
    fi
done

# Ensure test helloworld.proto file exists
for i in $(seq 1 "$NUMBER_OF_SERVICES"); do
    TEST_POD="${TEST_POD_BASE_NAME}-$i"
    if ! kubectl exec "$TEST_POD" -- bash -c "[ -f \"$TEST_PATH/helloworld.proto\" ]"; then
        echo "Error: test helloworld.proto file '$TEST_PATH/helloworld.proto' does not exist in pod '$TEST_POD'" >&2
        exit 1
    fi
done

# Validate number of services is a positive number
if ! [[ "$NUMBER_OF_SERVICES" =~ ^[0-9]+$ ]] || [[ "$NUMBER_OF_SERVICES" -lt 1 ]]; then
    echo "Error: Number of services must be a positive number (got: $NUMBER_OF_SERVICES)" >&2
    exit 1
fi

# Validate services manifest files
for i in $(seq 1 "$NUMBER_OF_SERVICES"); do
    SERVICE_MANIFEST="${SERVICE_MANIFEST_BASE_NAME}-$i.yaml"
    if [[ ! -f "$SERVICE_MANIFEST" ]]; then
        echo "Error: Service manifest file '$SERVICE_MANIFEST' does not exist" >&2
        exit 1
    fi
done

# Validate service port is a positive number
if ! [[ "$SERVICE_PORT" =~ ^[0-9]+$ ]] || [[ "$SERVICE_PORT" -lt 1 ]]; then
    echo "Error: Service port must be a positive number (got: $SERVICE_PORT)" >&2
    exit 1
fi

# Validate iterations is a positive number
if ! [[ "$ITERATIONS" =~ ^[0-9]+$ ]] || [[ "$ITERATIONS" -lt 1 ]]; then
    echo "Error: Iterations must be a positive number (got: $ITERATIONS)" >&2
    exit 1
fi

# Validate offset is a non-negative number and lower than iterations
if ! [[ "$OFFSET" =~ ^[0-9]+$ ]] || [[ "$OFFSET" -lt 0 ]] || [[ "$OFFSET" -ge "$ITERATIONS" ]]; then
    echo "Error: Offset must be a non-negative number and lower than iterations (got: $OFFSET)" >&2
    exit 1
fi

# Validate interference script file
if [[ ! -f "$INTERFERENCE_SCRIPT" ]]; then
    echo "Error: Interference script file '$INTERFERENCE_SCRIPT' does not exist" >&2
    exit 1
fi

# Validate number of interfering resources is a non-negative number
if ! [[ "$NUMBER_OF_INTERFERING_RESOURCES" =~ ^[0-9]+$ ]] || [[ "$NUMBER_OF_INTERFERING_RESOURCES" -lt 0 ]]; then
    echo "Error: Number of interfering resources must be a non-negative number (got: $NUMBER_OF_INTERFERING_RESOURCES)" >&2
    exit 1
fi

# Validate base scale is a non-negative number
if ! [[ "$BASE_SCALE" =~ ^[0-9]+$ ]] || [[ "$BASE_SCALE" -lt 0 ]]; then
    echo "Error: Base scale must be a non-negative number (got: $BASE_SCALE)" >&2
    exit 1
fi

# Validate scale-ups allowed is a non-negative number
if ! [[ "$SCALE_UPS_ALLOWED" =~ ^[0-9]+$ ]] || [[ "$SCALE_UPS_ALLOWED" -lt 0 ]]; then
    echo "Error: Scale-ups allowed must be a non-negative number (got: $SCALE_UPS_ALLOWED)" >&2
    exit 1
fi

# Validate force cleanup is either true or false
if [[ "$FORCE_CLEANUP" != "true" && "$FORCE_CLEANUP" != "false" ]]; then
    echo "Error: Force cleanup must be either 'true' or 'false' (got: $FORCE_CLEANUP)" >&2
    exit 1
fi

# If scale-ups allowed is 0, force cleanup must be false
if [ "$SCALE_UPS_ALLOWED" -eq 0 ]; then
    FORCE_CLEANUP="false"
fi

# Display configuration
echo "================================================"
echo "vSwarm RNN Benchmark - Starting"
echo "================================================"
echo "Experiment Name: $EXPERIMENT_NAME"
echo "Test Type: $TEST_TYPE"
echo "Test Pod Base Name: $TEST_POD_BASE_NAME"
echo "Test Path: $TEST_PATH"
echo "Number of Services: $NUMBER_OF_SERVICES"
echo "Service Manifest Base Name: $SERVICE_MANIFEST_BASE_NAME"
echo "Service Port: $SERVICE_PORT"
echo "Iterations: $ITERATIONS"
echo "Offset: $OFFSET"
echo "Interference Script: $INTERFERENCE_SCRIPT"
echo "Number of Interfering Resources: $NUMBER_OF_INTERFERING_RESOURCES"
echo "Base Scale: $BASE_SCALE"
echo "Scale-Ups Allowed: $SCALE_UPS_ALLOWED"
echo "Force Cleanup: $FORCE_CLEANUP"
echo "================================================"
echo ""

# Ensure interference namespace exists
if [ "$NUMBER_OF_INTERFERING_RESOURCES" -gt 0 ]; then
    echo "Checking for interference namespace..."
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
fi

# Create results directory
echo "Creating results directory..."
if [ "$TEST_TYPE" == "Deployment" ]; then
    RESULTS_DIR="/experiments/knative/vSwarm-benchmarks/rnn-serving/kube-manager/$EXPERIMENT_NAME"
elif [ "$TEST_TYPE" == "RTResource" ]; then
    RESULTS_DIR="/experiments/knative/vSwarm-benchmarks/rnn-serving/preempt-k8s/$EXPERIMENT_NAME"
fi

if [ "$OFFSET" -eq 0 ]; then
    kubectl exec "${TEST_POD_BASE_NAME}-1" -- bash -c "
        mkdir -p $RESULTS_DIR && \
        for i in \$(seq 1 $NUMBER_OF_SERVICES); do
            mkdir -p $RESULTS_DIR/service-\$i
        done
    "
fi
echo "Results will be stored in: $RESULTS_DIR"
echo ""

# Save configuration to file in the pod
if [ "$OFFSET" -eq 0 ]; then
    echo "Saving test configuration..."
    kubectl exec "${TEST_POD_BASE_NAME}-1" -- bash -c "
        cat > $RESULTS_DIR/config.txt <<EOF
================================================
vSwarm RNN Benchmark - Test Configuration
================================================
Experiment Name: $EXPERIMENT_NAME
Test Type: $TEST_TYPE
Number of Services: $NUMBER_OF_SERVICES
Iterations: $ITERATIONS
Number of Interfering Resources: $NUMBER_OF_INTERFERING_RESOURCES
Base Scale per service: $BASE_SCALE
Scale-Ups Allowed per service: $SCALE_UPS_ALLOWED
================================================
EOF
"
    echo ""
fi

# Deploy the services
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Deploying services..."
for i in $(seq 1 "$NUMBER_OF_SERVICES"); do
    SERVICE_MANIFEST="${SERVICE_MANIFEST_BASE_NAME}-$i.yaml"
    kubectl apply -f "$SERVICE_MANIFEST" &>/dev/null
done

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Waiting for rnn-serving-python services base pods to be Running..."
while [ $(kubectl get pods --no-headers | { grep "^rnn-serving-python" || true; } | { grep "Running" || true; } | { grep "3/3" || true; } | wc -l) -ne $NUMBER_OF_SERVICES ]; do
    sleep 2
done
sleep 10
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Pods are Running!"

# Wait for service scale-to-0
if [ "$BASE_SCALE" -eq 0 ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Waiting for services to scale-down to $BASE_SCALE instance(s)..."

    if [ "$FORCE_CLEANUP" == "true" ]; then
        TIMEOUT_SECONDS=90
        ELAPSED=0
        while [ $(kubectl get pods --no-headers | { grep "^rnn-serving-python" || true; } | { grep "Terminating" || true; } | wc -l) -ne $NUMBER_OF_SERVICES ]; do
            if [ $ELAPSED -ge $TIMEOUT_SECONDS ]; then
                echo "[$(date '+%Y-%m-%d %H:%M:%S')] Timeout waiting for pods to enter Terminating state"
                exit 1
            fi
            sleep 2
            ELAPSED=$((ELAPSED + 2))
        done
        TERMINATING_PODS=$(kubectl get pods --no-headers | { grep "^rnn-serving-python" || true; } | { grep "Terminating" || true; } | awk '{print $1}')
        kubectl delete pods $TERMINATING_PODS --grace-period=0 --force &>/dev/null || true
    fi
    while [ $(kubectl get pods --no-headers | { grep "^rnn-serving-python" || true; } | wc -l) -gt 0 ]; do
        sleep 2
    done
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Service scaled-down to $BASE_SCALE instance(s)!"
    echo ""
fi

# Main test loop
BASE_ITERATION=1
if [ "$OFFSET" -gt 0 ]; then
    BASE_ITERATION=$((OFFSET + 1))
fi
for i in $(seq "$BASE_ITERATION" "$ITERATIONS"); do
    echo "------------------------------------------------"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting test iteration $i of $ITERATIONS"
    echo "------------------------------------------------"

    # We run the interference script in background
    if [ "$NUMBER_OF_INTERFERING_RESOURCES" -gt 0 ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting interference load..."
        if [ "$TEST_TYPE" == "Deployment" ]; then
            bash "$INTERFERENCE_SCRIPT" -t "$TEST_TYPE" -i "$NUMBER_OF_INTERFERING_RESOURCES" &>/dev/null &
        elif [ "$TEST_TYPE" == "RTResource" ]; then
            bash "$INTERFERENCE_SCRIPT" -t "$TEST_TYPE" -i "$NUMBER_OF_INTERFERING_RESOURCES" -c 2 &>/dev/null &
        fi
        INTERFERENCE_PID=$!
    fi
    sleep 2

    # We start the benchmark
    PIDS=()
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting benchmark..."
    for j in $(seq 1 "$NUMBER_OF_SERVICES"); do
        TEST_POD="${TEST_POD_BASE_NAME}-$j"
        kubectl exec "$TEST_POD" -- bash -c "
            cd $TEST_PATH && \
            start=\$(date +%s%3N) && \
            until grpcurl -plaintext -import-path $TEST_PATH -proto helloworld.proto -d '{\"name\": \"Invoke relay\"}' rnn-serving-python-${j}.default.svc.cluster.local:80 helloworld.Greeter/SayHello 2>/dev/null; do :; done && \
            end=\$(date +%s%3N) && \
            duration=\$((end - start)) && \
            echo \$duration > latency-iteration-${i}.txt
        " > /dev/null 2>&1 &
        PIDS+=($!)
    done
    sleep 30
    for pid in "${PIDS[@]}"; do
        kill -9 "$pid" > /dev/null 2>&1 || true
    done
    wait "${PIDS[@]}" 2>/dev/null || true
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Benchmark completed!"

    # We stop the interference script in background
    if [ "$NUMBER_OF_INTERFERING_RESOURCES" -gt 0 ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Stopping interference load..."
        if kill -0 $INTERFERENCE_PID 2>/dev/null; then
            kill $INTERFERENCE_PID
            for _ in {1..10}; do
                if ! kill -0 $INTERFERENCE_PID 2>/dev/null; then
                    break
                fi
                sleep 1
            done
            sleep 2
        fi
    fi

    # Clean up interfering load
    if [ "$NUMBER_OF_INTERFERING_RESOURCES" -gt 0 ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Cleaning up interference namespace..."
        if [ "$TEST_TYPE" == "Deployment" ]; then
            kubectl delete --all deployments -n interference --ignore-not-found >/dev/null 2>&1 || true
        elif [ "$TEST_TYPE" == "RTResource" ]; then
            kubectl delete --all rtresources -n interference --ignore-not-found >/dev/null 2>&1 || true
        fi
        kubectl delete --all pods -n interference --ignore-not-found >/dev/null 2>&1 || true
        while [ $(kubectl get pods --no-headers -n interference | wc -l) -gt 0 ]; do
            sleep 2
        done >/dev/null 2>&1
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Interference namespace cleaned up!"
    fi

    # Service scale-down
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Waiting for services to scale-down..."

    # Forced cleanup
    if [ "$FORCE_CLEANUP" == "true" ]; then
        TIMEOUT_SECONDS=90
        ELAPSED=0
        while [ $(kubectl get pods --no-headers | { grep "^rnn-serving-python" || true; } | { grep "Running" || true; } | wc -l) -ne 0 ]; do
            if [ $ELAPSED -ge $TIMEOUT_SECONDS ]; then
                echo "[$(date '+%Y-%m-%d %H:%M:%S')] Timeout waiting for pods to enter Terminating state"
                break
            fi
            sleep 2
            ELAPSED=$((ELAPSED + 2))
        done
        TERMINATING_PODS=$(kubectl get pods --no-headers | { grep "^rnn-serving-python" || true; } | { grep "Terminating" || true; } | awk '{print $1}')

        for pod in $TERMINATING_PODS; do
            kubectl delete pod "$pod" --grace-period=0 --force &>/dev/null || true
        done
    fi
    
    for j in $(seq 1 "$NUMBER_OF_SERVICES"); do
        while [ $(kubectl get pods --no-headers | { grep "^rnn-serving-python-$j" || true; } | wc -l) -gt $BASE_SCALE ]; do
            sleep 2
        done
    done
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Services scaled-down to $BASE_SCALE instance(s)!"

    # Save test results to persistent storage
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Saving results to persistent storage..."
    for j in $(seq 1 "$NUMBER_OF_SERVICES"); do
        TEST_POD="${TEST_POD_BASE_NAME}-$j"
        SERVICE_PATH="$RESULTS_DIR/service-$j"
        kubectl exec "$TEST_POD" -- bash -c "
            mv $TEST_PATH/latency* $SERVICE_PATH
        "
    done
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Results saved to $RESULTS_DIR!"

    echo "------------------------------------------------"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Iteration $i of $ITERATIONS completed!"
    echo "------------------------------------------------"
done

# Delete the services
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Deleting services..."
for i in $(seq 1 "$NUMBER_OF_SERVICES"); do
    SERVICE_MANIFEST="${SERVICE_MANIFEST_BASE_NAME}-$i.yaml"
    kubectl delete -f "$SERVICE_MANIFEST" &>/dev/null
done

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Waiting for all rnn-serving-python pods to terminate..."
if [ "$FORCE_CLEANUP" == "true" ]; then
    while [ $(kubectl get pods --no-headers | { grep "^rnn-serving-python" || true; } | wc -l) -gt 0 ]; do
        kubectl get pods --no-headers | { grep "^rnn-serving-python" || true; } | awk '{print $1}' | xargs -r kubectl delete pod --grace-period=0 --force 2>/dev/null 2>&1 || true
        sleep 2
    done
else
    while [ $(kubectl get pods --no-headers | { grep "^rnn-serving-python" || true; } | wc -l) -gt 0 ]; do
        sleep 2
    done
fi
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Services terminated!"

# Delete interference namespace
if [ "$NUMBER_OF_INTERFERING_RESOURCES" -gt 0 ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Deleting interference namespace..."
    kubectl delete namespace interference --wait=false &>/dev/null
fi

echo "================================================"
echo "All test iterations completed successfully!"
echo "================================================"
