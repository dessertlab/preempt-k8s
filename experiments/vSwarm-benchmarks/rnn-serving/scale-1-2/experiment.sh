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
INVOKER_POD_BASE_NAME="benchmark-pod"
INVOKER_PATH="/home"
NUMBER_OF_SERVICES="5"
SERVICE_MANIFEST_BASE_NAME="kn-rnn-serving-python"
SERVICE_PORT="80"
RPS="50"
TIMEOUT="40"
DURATION="30"
ITERATIONS="1"
OFFSET="0"
INTERFERENCE_SCRIPT="interfering-load.sh"
NUMBER_OF_INTERFERING_RESOURCES="40"
BASE_SCALE="1"
SCALE_UPS_ALLOWED="1"
LOKI_NAMESPACE="observability"
LOKI_NAME="loki-0"
LOKI_IP_ADDRESS="10.244.1.216"
LOKI_FLUSH="false"
FORCE_CLEANUP="true"

# Parse command line flags
while getopts "f:t:i:e:c:m:p:q:o:d:n:g:s:r:b:u:l:v:a:k:w:h" opt; do
    case $opt in
        f) EXPERIMENT_NAME="$OPTARG" ;;
        t) TEST_TYPE="$OPTARG" ;;
        i) INVOKER_POD_BASE_NAME="$OPTARG" ;;
        e) INVOKER_PATH="$OPTARG" ;;
        c) NUMBER_OF_SERVICES="$OPTARG" ;;
        m) SERVICE_MANIFEST_BASE_NAME="$OPTARG" ;;
        p) SERVICE_PORT="$OPTARG" ;;
        q) RPS="$OPTARG" ;;
        o) TIMEOUT="$OPTARG" ;;
        d) DURATION="$OPTARG" ;;
        n) ITERATIONS="$OPTARG" ;;
        g) OFFSET="$OPTARG" ;;
        s) INTERFERENCE_SCRIPT="$OPTARG" ;;
        r) NUMBER_OF_INTERFERING_RESOURCES="$OPTARG" ;;
        b) BASE_SCALE="$OPTARG" ;;
        u) SCALE_UPS_ALLOWED="$OPTARG" ;;
        l) LOKI_NAMESPACE="$OPTARG" ;;
        v) LOKI_NAME="$OPTARG" ;;
        a) LOKI_IP_ADDRESS="$OPTARG" ;;
        k) LOKI_FLUSH="$OPTARG" ;;
        w) FORCE_CLEANUP="$OPTARG" ;;
        h) 
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  -f <experiment-name>                Name of the experiment (default: rnn-serving-benchmark)"
            echo "  -t <test-type>                      Type of test to run (default: Deployment)"
            echo "  -i <invoker-pod-base-name>          Invoker pod base name in default namespace (default: benchmark-pod)"
            echo "  -e <invoker-path>                   Path to invoker binary inside the pods (default: /home)"
            echo "  -c <number-of-services>             Number of concurrent RNN Knative services to deploy (default: 5)"
            echo "  -m <service-manifest-base-name>     Services manifest file base name (default: kn-rnn-serving-python)"
            echo "  -p <service-port>                   Services port (default: 80)"
            echo "  -q <requests-per-second>            Requests per second per service (default: 50)"
            echo "  -o <timeout>                        Timeout for each request in seconds (default: 40)"
            echo "  -d <duration>                       Duration of the test in seconds (default: 30)"
            echo "  -n <iterations>                     Number of test iterations (default: 1)"
            echo "  -g <offset>                         Iterations offset (default: 0)"
            echo "  -s <interference-script>            Interference script to run (default: interfering-load.sh)"
            echo "  -r <number-of-resources>            Number of interfering resources (default: 40)"
            echo "  -b <base-scale>                     Base scale for the tested services (default: 1)"
            echo "  -u <scale-ups-allowed>              Number of allowed scale-up pods per service (default: 1)"
            echo "  -l <loki-namespace>                 Namespace where the Loki instance is deployed (default: observability)"
            echo "  -v <loki-name>                      Name of the Loki pod (default: loki-0)"
            echo "  -a <loki-ip-address>                IP address of the Loki instance to query for control plane logs (default: 10.244.1.216)"
            echo "  -k <loki-flush>                     Whether to flush Loki logs before each iteration (default: false)"
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

# Validate invoker pods
EXISTING_PODS=$(kubectl get pods --no-headers 2>/dev/null | { grep "^$INVOKER_POD_BASE_NAME" || true; } | wc -l)
if [[ "$EXISTING_PODS" -ne "$NUMBER_OF_SERVICES" ]]; then
    echo "Error: Invoker pods number ($EXISTING_PODS) does not match the specified number ($NUMBER_OF_SERVICES)" >&2
    exit 1
fi

# Validate invoker path
for i in $(seq 1 "$NUMBER_OF_SERVICES"); do
    INVOKER_POD="${INVOKER_POD_BASE_NAME}-$i"
    if ! kubectl exec "$INVOKER_POD" -- bash -c "[ -x \"$INVOKER_PATH/invoker\" ]"; then
        echo "Error: Invoker binary '$INVOKER_PATH/invoker' does not exist or is not executable in pod '$INVOKER_POD'" >&2
        exit 1
    fi
done

# Ensure invoker endpoints file exists
for i in $(seq 1 "$NUMBER_OF_SERVICES"); do
    INVOKER_POD="${INVOKER_POD_BASE_NAME}-$i"
    if ! kubectl exec "$INVOKER_POD" -- bash -c "[ -f \"$INVOKER_PATH/endpoints.json\" ]"; then
        echo "Error: Invoker endpoints file '$INVOKER_PATH/endpoints.json' does not exist in pod '$INVOKER_POD'" >&2
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

# Validate Loki namespace
if ! kubectl get namespace "$LOKI_NAMESPACE" &>/dev/null; then
    echo "Error: Loki namespace '$LOKI_NAMESPACE' does not exist" >&2
    exit 1
fi

# Validate Loki pod
if ! kubectl get pod "$LOKI_NAME" -n "$LOKI_NAMESPACE" &>/dev/null; then
    echo "Error: Loki pod '$LOKI_NAME' does not exist in namespace '$LOKI_NAMESPACE'" >&2
    exit 1
fi

# Validate Loki IP address
if [ $(kubectl get pod "$LOKI_NAME" -n "$LOKI_NAMESPACE" -o jsonpath="{.status.podIP}") != "$LOKI_IP_ADDRESS" ]; then
    echo "Error: the provided Loki IP address does not match the actual IP address in namespace '$LOKI_NAMESPACE'" >&2
    exit 1
fi

# Validate Loki flush is either true or false
if [[ "$LOKI_FLUSH" != "true" && "$LOKI_FLUSH" != "false" ]]; then
    echo "Error: Loki flush must be either 'true' or 'false' (got: $LOKI_FLUSH)" >&2
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
echo "Invoker Pod Base Name: $INVOKER_POD_BASE_NAME"
echo "Invoker Path: $INVOKER_PATH"
echo "Number of Services: $NUMBER_OF_SERVICES"
echo "Service Manifest Base Name: $SERVICE_MANIFEST_BASE_NAME"
echo "Service Port: $SERVICE_PORT"
echo "RPS: $RPS"
echo "Timeout: $TIMEOUT seconds"
echo "Duration: $DURATION seconds"
echo "Iterations: $ITERATIONS"
echo "Offset: $OFFSET"
echo "Interference Script: $INTERFERENCE_SCRIPT"
echo "Number of Interfering Resources: $NUMBER_OF_INTERFERING_RESOURCES"
echo "Base Scale: $BASE_SCALE"
echo "Scale-Ups Allowed: $SCALE_UPS_ALLOWED"
echo "Loki Namespace: $LOKI_NAMESPACE"
echo "Loki Name: $LOKI_NAME"
echo "Loki IP Address: $LOKI_IP_ADDRESS"
echo "Loki Flush: $LOKI_FLUSH"
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
    kubectl exec "${INVOKER_POD_BASE_NAME}-1" -- bash -c "
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
    kubectl exec "${INVOKER_POD_BASE_NAME}-1" -- bash -c "
        cat > $RESULTS_DIR/config.txt <<EOF
================================================
vSwarm RNN Benchmark - Test Configuration
================================================
Experiment Name: $EXPERIMENT_NAME
Test Type: $TEST_TYPE
Number of Services: $NUMBER_OF_SERVICES
RPS per service: $RPS
Timeout: $TIMEOUT seconds
Duration: $DURATION seconds
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

    # Flush Loki logs
    if [ "$LOKI_FLUSH" == "true" ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Flushing Loki logs..."
        START=$(date -d "30 days ago" +%s)
        END=$(date +%s)
        sleep 20
        curl -X POST -s \"http://${LOKI_IP_ADDRESS}:3100/flush\" >/dev/null 2>&1
        sleep 5
        curl -g -X POST "http://${LOKI_IP_ADDRESS}:3100/loki/api/v1/delete?query={job=\"kubernetes-audit\"}&start=$START&end=$END"
        sleep 180
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Loki logs flushed!"
    fi

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
    START_TIME=$(date +%s%N)
    # sleep 20
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting benchmark..."
    INVOKER_CMD="cd $INVOKER_PATH && ./invoker -port $SERVICE_PORT -time $DURATION -rps $RPS --grpcTimeout $TIMEOUT -latf iteration_${i} > ./invoker-output.log"
    for j in $(seq 1 "$NUMBER_OF_SERVICES"); do
        INVOKER_POD="${INVOKER_POD_BASE_NAME}-$j"
        kubectl exec "$INVOKER_POD" -- bash -c "$INVOKER_CMD" > /dev/null 2>&1 &
        PIDS+=($!)
    done
    sleep $((DURATION + 10))
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

    sleep 20
    END_TIME=$(date +%s%N)

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
        while [ $(kubectl get pods --no-headers | { grep "^rnn-serving-python" || true; } | { grep "Running" || true; } | wc -l) -ne $((BASE_SCALE*NUMBER_OF_SERVICES)) ]; do
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

    # We query Loki to retrieve control plane logs and save them to persistent storage
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Querying Loki for control plane logs..."
    LOKI_QUERY="{job=\"kubernetes-audit\"} | json "
    LOKI_OUTPUT_FILE="./loki-logs-iteration_${i}.json"
    curl -G -s "http://${LOKI_IP_ADDRESS}:3100/loki/api/v1/query_range" \
        --data-urlencode "query=$LOKI_QUERY" \
        --data-urlencode "start=$START_TIME" \
        --data-urlencode "end=$END_TIME" \
        --data-urlencode "limit=5000" \
        --data-urlencode "direction=forward" | \
        jq '[.data.result[].values[] | {
        timestamp: .[0],
        log: (.[1] | fromjson)
        }]' > "$LOKI_OUTPUT_FILE"
    kubectl cp ./"${LOKI_OUTPUT_FILE}" "${INVOKER_POD_BASE_NAME}-1:${RESULTS_DIR}/${LOKI_OUTPUT_FILE}" >/dev/null 2>&1
    rm ./"${LOKI_OUTPUT_FILE}"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Loki logs saved to $LOKI_OUTPUT_FILE!"

    # Save invoker results to persistent storage
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Saving results to persistent storage..."
    for j in $(seq 1 "$NUMBER_OF_SERVICES"); do
        INVOKER_POD="${INVOKER_POD_BASE_NAME}-$j"
        SERVICE_PATH="$RESULTS_DIR/service-$j"
        kubectl exec "$INVOKER_POD" -- bash -c "
            mv $INVOKER_PATH/rps* $SERVICE_PATH
        "
        INVOKER_OUTPUT=$(kubectl exec "$INVOKER_POD" -- bash -c "cat $INVOKER_PATH/invoker-output.log")
        ISSUED=$(echo "$INVOKER_OUTPUT" | sed -n 's/.*Issued \/ completed requests: \([0-9]*\), \([0-9]*\).*/\1/p')
        COMPLETED=$(echo "$INVOKER_OUTPUT" | sed -n 's/.*Issued \/ completed requests: \([0-9]*\), \([0-9]*\).*/\2/p')
        REAL_RPS=$(echo "$INVOKER_OUTPUT" | sed -n 's/.*Real \/ target RPS: \([0-9.]*\) \/ \([0-9.]*\).*/\1/p')
        TARGET_RPS=$(echo "$INVOKER_OUTPUT" | sed -n 's/.*Real \/ target RPS: \([0-9.]*\) \/ \([0-9.]*\).*/\2/p')
        kubectl exec "$INVOKER_POD" -- bash -c "
            mv $INVOKER_PATH/invoker-output.log $SERVICE_PATH/iteration_${i}_invoker-output.log && \
            cat > $SERVICE_PATH/iteration_${i}_status.txt <<EOF
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
    done

    # Page cache flush on all nodes to minimize the effect of caching on subsequent iterations
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Flushing page cache on all nodes..."

    sync; echo 3 | sudo tee /proc/sys/vm/drop_caches >/dev/null 2>&1
    ssh root@192.168.100.22 "sync; echo 3 | sudo tee /proc/sys/vm/drop_caches" >/dev/null 2>&1
    ssh root@192.168.100.23 "sync; echo 3 | sudo tee /proc/sys/vm/drop_caches" >/dev/null 2>&1
    ssh root@192.168.100.24 "sync; echo 3 | sudo tee /proc/sys/vm/drop_caches" >/dev/null 2>&1
    ssh root@192.168.100.53 "sync; echo 3 | sudo tee /proc/sys/vm/drop_caches" >/dev/null 2>&1

    # Iteration completed, results saved
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
