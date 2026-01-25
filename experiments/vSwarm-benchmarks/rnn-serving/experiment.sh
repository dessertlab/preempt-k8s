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
INVOKER_POD="benchmark-pod"
INVOKER_PATH="/home"
SERVICE_MANIFEST="kn-rnn-serving-python.yaml"
SERVICE_PORT="80"
RPS="50"
TIMEOUT="30"
DURATION="20"
ITERATIONS="1"
INTERFERENCE_SCRIPT="interfering-load.sh"
NUMBER_OF_INTERFERING_RESOURCES="40"
BASE_SCALE="1"
SCALE_UPS_ALLOWED="1"
FORCE_CLEANUP="true"

# Parse command line flags
while getopts "f:t:i:e:m:p:q:o:d:n:s:r:b:u:c:h" opt; do
    case $opt in
        f) EXPERIMENT_NAME="$OPTARG" ;;
        t) TEST_TYPE="$OPTARG" ;;
        i) INVOKER_POD="$OPTARG" ;;
        e) INVOKER_PATH="$OPTARG" ;;
        m) SERVICE_MANIFEST="$OPTARG" ;;
        p) SERVICE_PORT="$OPTARG" ;;
        q) RPS="$OPTARG" ;;
        o) TIMEOUT="$OPTARG" ;;
        d) DURATION="$OPTARG" ;;
        n) ITERATIONS="$OPTARG" ;;
        s) INTERFERENCE_SCRIPT="$OPTARG" ;;
        r) NUMBER_OF_INTERFERING_RESOURCES="$OPTARG" ;;
        b) BASE_SCALE="$OPTARG" ;;
        u) SCALE_UPS_ALLOWED="$OPTARG" ;;
        c) FORCE_CLEANUP="$OPTARG" ;;
        h) 
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  -f <experiment-name>            Name of the experiment (default: rnn-serving-benchmark)"
            echo "  -t <test-type>                  Type of test to run (default: Deployment)"
            echo "  -i <invoker-pod>                Invoker pod name in default namespace (default: benchmark-pod)"
            echo "  -e <invoker-path>               Path to invoker binary inside the pod (default: /home)"
            echo "  -m <service-manifest>           Service manifest file (default: rnn-serving-service.yaml)"
            echo "  -p <service-port>               Service port (default: 80)"
            echo "  -q <requests-per-second>        Requests per second (default: 50)"
            echo "  -o <timeout>                    Timeout for each request in seconds (default: 30)"
            echo "  -d <duration>                   Duration of the test in seconds (default: 20)"
            echo "  -n <iterations>                 Number of test iterations (default: 1)"
            echo "  -s <interference-script>        Interference script to run (default: interfering-load.sh)"
            echo "  -r <number-of-resources>        Number of interfering resources (default: 40)"
            echo "  -b <base-scale>                 Base scale for the tested service (default: 1)"
            echo "  -u <scale-ups-allowed>          Number of allowed scale-up pods (default: 1)"
            echo "  -c <force-cleanup>              Force cleanup of tested service's resources after test, use when pods require too much time to terminate (default: true)"
            echo "  -h                              Show this help message"
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

# Validate invoker pod
if ! kubectl get pod "$INVOKER_POD" --ignore-not-found 2>/dev/null | { grep -q "$INVOKER_POD" || true; }; then
    echo "Error: Invoker pod '$INVOKER_POD' does not exist" >&2
    exit 1
fi

# Validate invoker path
if ! kubectl exec "$INVOKER_POD" -- bash -c "[ -x \"$INVOKER_PATH/invoker\" ]"; then
    echo "Error: Invoker binary '$INVOKER_PATH/invoker' does not exist or is not executable in pod '$INVOKER_POD'" >&2
    exit 1
fi

# Ensure invoker endpoints file exists
if ! kubectl exec "$INVOKER_POD" -- bash -c "[ -f \"$INVOKER_PATH/endpoints.json\" ]"; then
    echo "Error: Invoker endpoints file '$INVOKER_PATH/endpoints.json' does not exist in pod '$INVOKER_POD'" >&2
    exit 1
fi

# Validate service manifest file
if [[ ! -f "$SERVICE_MANIFEST" ]]; then
    echo "Error: Service manifest file '$SERVICE_MANIFEST' does not exist" >&2
    exit 1
fi

# Validate service port is a positive number
if ! [[ "$SERVICE_PORT" =~ ^[0-9]+$ ]] || [[ "$SERVICE_PORT" -lt 1 ]]; then
    echo "Error: Service port must be a positive number (got: $SERVICE_PORT)" >&2
    exit 1
fi

# Validate RPS is a positive number
if ! [[ "$RPS" =~ ^[0-9]+$ ]] || [[ "$RPS" -lt 1 ]]; then
    echo "Error: RPS must be a positive number (got: $RPS)" >&2
    exit 1
fi

# Validate timeout is a positive number
if ! [[ "$TIMEOUT" =~ ^[0-9]+$ ]] || [[ "$TIMEOUT" -lt 1 ]]; then
    echo "Error: Timeout must be a positive number (got: $TIMEOUT)" >&2
    exit 1
fi

# Validate duration is a positive number
if ! [[ "$DURATION" =~ ^[0-9]+$ ]] || [[ "$DURATION" -lt 1 ]]; then
    echo "Error: Duration must be a positive number (got: $DURATION)" >&2
    exit 1
fi

# Validate iterations is a positive number
if ! [[ "$ITERATIONS" =~ ^[0-9]+$ ]] || [[ "$ITERATIONS" -lt 1 ]]; then
    echo "Error: Iterations must be a positive number (got: $ITERATIONS)" >&2
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
echo "Invoker Pod: $INVOKER_POD"
echo "Invoker Path: $INVOKER_PATH"
echo "Service Manifest: $SERVICE_MANIFEST"
echo "Service Port: $SERVICE_PORT"
echo "RPS: $RPS"
echo "Timeout: $TIMEOUT seconds"
echo "Duration: $DURATION seconds"
echo "Iterations: $ITERATIONS"
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
    RESULTS_DIR="/experiments/knative/vSwarm-benchmarks/rnn-serving/kube-manager/$EXPERIMENT_NAME/$(date '+%Y-%m-%d_%H-%M-%S')"
elif [ "$TEST_TYPE" == "RTResource" ]; then
    RESULTS_DIR="/experiments/knative/vSwarm-benchmarks/rnn-serving/preempt-k8s/$EXPERIMENT_NAME/$(date '+%Y-%m-%d_%H-%M-%S')"
fi
kubectl exec "$INVOKER_POD" -- bash -c "
    mkdir -p $RESULTS_DIR
"
echo "Results will be stored in: $RESULTS_DIR"
echo ""

# Save configuration to file in the pod
echo "Saving test configuration..."
kubectl exec "$INVOKER_POD" -- bash -c "
    cat > $RESULTS_DIR/config.txt <<EOF
================================================
vSwarm RNN Benchmark - Test Configuration
================================================
Experiment Name: $EXPERIMENT_NAME
Test Type: $TEST_TYPE
RPS: $RPS
Timeout: $TIMEOUT seconds
Duration: $DURATION seconds
Iterations: $ITERATIONS
Number of Interfering Resources: $NUMBER_OF_INTERFERING_RESOURCES
Base Scale: $BASE_SCALE
Scale-Ups Allowed: $SCALE_UPS_ALLOWED
================================================
EOF
"
echo ""

# Deploy the service
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Deploying service..."
kubectl apply -f "$SERVICE_MANIFEST" &>/dev/null

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Waiting for rnn-serving-python base pod to be Running..."
while ! kubectl get pods --no-headers | { grep "^rnn-serving-python" || true; } | { grep -q "Running" || true; } | { grep -q "3/3" || true; }; do
    sleep 2
done
sleep 10
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Pod is Running!"

# Main test loop
for i in $(seq 1 "$ITERATIONS"); do
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

    # We start the benchmark
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting benchmark..."
    INVOKER_CMD="cd $INVOKER_PATH && ./invoker -port 80 -time $DURATION -rps $RPS --grpcTimeout $TIMEOUT -latf iteration_${i}"
    INVOKER_OUTPUT=$(kubectl exec "$INVOKER_POD" -- bash -c "$INVOKER_CMD")
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
        while [ $(kubectl get pods --no-headers -n interference >/dev/null 2>&1 | wc -l) -gt 0 ]; do
            sleep 2
        done
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Interference namespace cleaned up!"
    fi

    # Service scale-down
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Waiting for service scale-down..."

    # Forced cleanup
    if [ "$FORCE_CLEANUP" == "true" ]; then
        TIMEOUT_SECONDS=90
        ELAPSED=0
        while [ $(kubectl get pods --no-headers | { grep "^rnn-serving-python" || true; } | { grep "Terminating" || true; } | wc -l) -ne "$SCALE_UPS_ALLOWED" ]; do
            if [ $ELAPSED -ge $TIMEOUT_SECONDS ]; then
                echo "[$(date '+%Y-%m-%d %H:%M:%S')] Timeout waiting for pods to enter Terminating state"
                break
            fi
            sleep 2
            ELAPSED=$((ELAPSED + 2))
        done
        TERMINATING_PODS=$(kubectl get pods --no-headers | { grep "^rnn-serving-python" || true; } | { grep "Terminating" || true; } | awk '{print $1}')
        TERMINATING_COUNT=$(echo "$TERMINATING_PODS" | { grep -c . || true; })
        if [ $TERMINATING_COUNT -ne $SCALE_UPS_ALLOWED ]; then
            echo "Error: Number of terminating pods does not match the allowed scale-ups (expected: $SCALE_UPS_ALLOWED, got: $TERMINATING_COUNT)" >&2
            exit 1
        fi
        for pod in $TERMINATING_PODS; do
            kubectl delete pod "$pod" --grace-period=0 --force &>/dev/null || true
        done
    fi
    
    while [ $(kubectl get pods --no-headers | { grep "^rnn-serving-python" || true; } | wc -l) -gt $BASE_SCALE ]; do
        sleep 2
    done
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Service scaled-down to $BASE_SCALE instance(s)!"

    # Save results to persistent storage
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Saving results to persistent storage..."
    kubectl exec "$INVOKER_POD" -- bash -c "
        mv $INVOKER_PATH/rps* $RESULTS_DIR/
    "
    ISSUED=$(echo "$INVOKER_OUTPUT" | sed -n 's/.*Issued \/ completed requests: \([0-9]*\), \([0-9]*\).*/\1/p')
    COMPLETED=$(echo "$INVOKER_OUTPUT" | sed -n 's/.*Issued \/ completed requests: \([0-9]*\), \([0-9]*\).*/\2/p')
    REAL_RPS=$(echo "$INVOKER_OUTPUT" | sed -n 's/.*Real \/ target RPS: \([0-9.]*\) \/ \([0-9.]*\).*/\1/p')
    TARGET_RPS=$(echo "$INVOKER_OUTPUT" | sed -n 's/.*Real \/ target RPS: \([0-9.]*\) \/ \([0-9.]*\).*/\2/p')
    kubectl exec "$INVOKER_POD" -- bash -c "
        cat > $RESULTS_DIR/iteration_${i}_status.txt <<EOF
================================================
vSwarm RNN Benchmark Status - Iteration $i
================================================
Issued: $ISSUED
Completed: $COMPLETED
Target RPS: $TARGET_RPS
Real RPS: $REAL_RPS
================================================
EOF
    "
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Results saved to $RESULTS_DIR!"

    echo "------------------------------------------------"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Iteration $i of $ITERATIONS completed!"
    echo "------------------------------------------------"
done

# Delete the service
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Deleting service..."
kubectl delete -f "$SERVICE_MANIFEST" &>/dev/null

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Waiting for all rnn-serving-python pods to terminate..."
while [ $(kubectl get pods --no-headers | { grep "^rnn-serving-python" || true; } | wc -l) -gt 0 ]; do
    kubectl get pods --no-headers | { grep "^rnn-serving-python" || true; } | awk '{print $1}' | xargs -r kubectl delete pod --grace-period=0 --force 2>/dev/null 2>&1 || true
    sleep 2
done
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Service terminated!"

# Delete interference namespace
if [ "$NUMBER_OF_INTERFERING_RESOURCES" -gt 0 ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Deleting interference namespace..."
    kubectl delete namespace interference --wait=false &>/dev/null
fi

echo "================================================"
echo "All test iterations completed successfully!"
echo "================================================"
