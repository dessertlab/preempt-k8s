#!/bin/bash

# Exits immediately if a command exits with a non-zero status,
# if an undefined variable is used,
# or if any command in a pipeline fails
set -e
set -u
set -o pipefail

# Default values and working variables
EXPERIMENT_NAME=""
NAMESPACE="default"
NUMBER_OF_SERVICES="10"
ITERATIONS="30"
OFFSET="0"
NUMBER_OF_INTERFERING_RESOURCES="70"
DEPLOY_STRESS="false"

RT_CONTROLLER_NAMESPACE="realtime"
RT_CONTROLLER_POD="preempt-k8s-0"

LOKI_NAMESPACE="observability"
LOKI_NAME="loki"
LOKI_IP_ADDRESS=""
QUERY_POD_NAME="query-pod"

DEPLOYMENT_MANIFEST_DIR="./manifests/vanilla"
INTERFERING_DEPLOYMENT_TEMPLATE="$DEPLOYMENT_MANIFEST_DIR/interfering-deployment-template.yaml"
KSVC_DEPLOYMENT_TEMPLATE="$DEPLOYMENT_MANIFEST_DIR/knservice-deployment-template.yaml"

RTRESOURCE_MANIFEST_DIR="./manifests/preempt"
KSVC_RTRESOURCE_TEMPLATE="$RTRESOURCE_MANIFEST_DIR/knservice-rtresource-template.yaml"
INTERFERING_RTRESOURCE_TEMPLATE="$RTRESOURCE_MANIFEST_DIR/interfering-rtresource-template.yaml"

NODE="dessertw2"
NODE_IP=""
ANALYSIS_SCRIPT="/root/analyze-bands-feature.py"

WINDOW_MARGIN=20
RUNNING_TIMEOUT=60

# Parse command line flags
while getopts ":e:n:s:i:o:r:c:l:q:p:h" opt; do
    case $opt in
        e) EXPERIMENT_NAME="$OPTARG" ;;
        n) NAMESPACE="$OPTARG" ;;
        s) NUMBER_OF_SERVICES="$OPTARG" ;;
        i) ITERATIONS="$OPTARG" ;;
        o) OFFSET="$OPTARG" ;;
        r) NUMBER_OF_INTERFERING_RESOURCES="$OPTARG" ;;
        c) DEPLOY_STRESS="$OPTARG" ;;
        l) LOKI_NAMESPACE="$OPTARG" ;;
        q) LOKI_NAME="$OPTARG" ;;
        p) NODE="$OPTARG" ;;
        h) 
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  -e <experiment-name>                Name of the experiment, required when resuming an experiment [-o] (default: current timestamp)"
            echo "  -n <namespace>                      Namespace where services and interfering resources are deployed (default: default)"
            echo "  -s <number-of-services>             Number of concurrent services to deploy (default: 10)"
            echo "  -i <iterations>                     Number of test iterations (default: 30)"
            echo "  -o <offset>                         Iterations offset (default: 0)"
            echo "  -r <number-of-resources>            Number of interfering resources (default: 70)"
            echo "  -c <deploy-stress>                  Set to true to deploy CPU stress both on the control plane and the experiment worker NODE (default: false)"
            echo "  -l <loki-namespace>                 Namespace where the Loki service is deployed (default: observability)"
            echo "  -q <loki-name>                      Name of the Loki service (default: loki)"
            echo "  -p <node>                           Node where services and the interfering resources should be scheduled (default: dessertw2)"
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

# Validate experiment namespace
if ! kubectl get namespace "$NAMESPACE" &>/dev/null; then
    echo "Error: Experiment namespace '$NAMESPACE' does not exist" >&2
    exit 1
fi

# Validate number of services is a positive number
if ! [[ "$NUMBER_OF_SERVICES" =~ ^[0-9]+$ ]] || [[ "$NUMBER_OF_SERVICES" -lt 1 ]]; then
    echo "Error: Number of services must be a positive number (got: $NUMBER_OF_SERVICES)" >&2
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

# Validate number of interfering resources is a non-negative number
if ! [[ "$NUMBER_OF_INTERFERING_RESOURCES" =~ ^[0-9]+$ ]] || [[ "$NUMBER_OF_INTERFERING_RESOURCES" -lt 0 ]]; then
    echo "Error: Number of interfering resources must be a non-negative number (got: $NUMBER_OF_INTERFERING_RESOURCES)" >&2
    exit 1
fi

# Validate deploy stress is either true or false
if [[ "$DEPLOY_STRESS" != "true" && "$DEPLOY_STRESS" != "false" ]]; then
    echo "Error: Deploy stress must be either 'true' or 'false' (got: $DEPLOY_STRESS)" >&2
    exit 1
fi

# Validate Loki namespace
if ! kubectl get namespace "$LOKI_NAMESPACE" &>/dev/null; then
    echo "Error: Loki namespace '$LOKI_NAMESPACE' does not exist" >&2
    exit 1
fi

# Validate Loki service
if ! kubectl get svc "$LOKI_NAME" -n "$LOKI_NAMESPACE" &>/dev/null; then
    echo "Error: Loki service '$LOKI_NAME' does not exist in namespace '$LOKI_NAMESPACE'" >&2
    exit 1
fi

# Retrieve Loki IP address
LOKI_IP_ADDRESS=$(kubectl get svc "$LOKI_NAME" -n "$LOKI_NAMESPACE" -o jsonpath="{.spec.clusterIP}")
if [ -z "$LOKI_IP_ADDRESS" ]; then
    echo "Error: Failed to retrieve '$LOKI_NAME' IP address in namespace '$LOKI_NAMESPACE'" >&2
    exit 1
fi

# Validate query pod
if ! kubectl get pod "$QUERY_POD_NAME" -n "$NAMESPACE" &>/dev/null; then
    echo "Error: Query pod '$QUERY_POD_NAME' does not exist in namespace '$NAMESPACE'" >&2
    exit 1
fi

# Validate experiment node
if ! kubectl get node "$NODE" &>/dev/null; then
    echo "Error: Experiment node '$NODE' does not exist in the cluster" >&2
    exit 1
fi
NODE_IP=$(kubectl get node "$NODE" -o jsonpath='{.status.addresses[?(@.type=="InternalIP")].address}')
if [ -z "$NODE_IP" ]; then
    echo "Error: Failed to retrieve the InternalIP address of node '$NODE'" >&2
    exit 1
fi
if ! ssh -o BatchMode=yes root@"$NODE_IP" "test -f $ANALYSIS_SCRIPT && command -v python3" &>/dev/null; then
    echo "Error: '$ANALYSIS_SCRIPT' or python3 not found on node '$NODE'" >&2
    exit 1
fi

# Validate envsubst availability (package: gettext-base)
if ! command -v envsubst &>/dev/null; then
    echo "Error: 'envsubst' not found (install gettext-base)" >&2
    exit 1
fi

# Validate jq availability
if ! command -v jq &>/dev/null; then
    echo "Error: 'jq' not found (install jq)" >&2
    exit 1
fi

# Ensure stress-ng is installed on control plane and experiment nodes
if [ "$DEPLOY_STRESS" == "true" ]; then
    if ! command -v stress-ng &>/dev/null; then
        echo "Error: stress-ng is not installed on the control plane node, please install it to run the cpu interfering load" >&2
        exit 1
    fi
    if ! ssh root@"${NODE_IP}" 'command -v stress-ng' &>/dev/null; then
        echo "Error: stress-ng is not installed on the experiment worker node" >&2
        exit 1
    fi
fi

# Detect test configuration
RT_CONTROLLER_PHASE=$(kubectl get pod "$RT_CONTROLLER_POD" -n "$RT_CONTROLLER_NAMESPACE" \
    -o jsonpath='{.status.phase}' 2>/dev/null || true)
if [ "$RT_CONTROLLER_PHASE" == "Running" ]; then
    TEST_TYPE="RTResource"
else
    TEST_TYPE="Deployment"
fi

KUBELET_CONFIG=$(kubectl get --raw "/api/v1/nodes/$NODE/proxy/configz" | jq '.kubeletconfig')
BANDS_ENABLED=$(jq -r '.criticalityBands.enabled // false' <<< "$KUBELET_CONFIG")
STEALING_ENABLED="false"
if [ "$BANDS_ENABLED" == "true" ]; then
    STEALING_ENABLED=$(jq -r '.criticalityBands.stealing // false' <<< "$KUBELET_CONFIG")
fi
FIFO_ENABLED=$(jq -r '.fifoScheduling // false' <<< "$KUBELET_CONFIG")
CRITICALITY_LABEL_KEY=$(jq -r '.criticality.labelKey // "-"' <<< "$KUBELET_CONFIG")
MAX_CRITICALITY_LEVEL=$(jq -r '.criticality.maxLevel // "-"' <<< "$KUBELET_CONFIG")
MIN_CRITICALITY_LEVEL=$(jq -r '.criticality.minLevel // "-"' <<< "$KUBELET_CONFIG")
MAX_CONCURRENT_POD_CREATIONS=$(jq -r '.criticalityBands.maxConcurrentPodCreations // "-"' <<< "$KUBELET_CONFIG")
HIGH_BAND_MIN_LEVEL=$(jq -r '.criticalityBands.highBandMinLevel // "-"' <<< "$KUBELET_CONFIG")
HIGH_BAND_GUARANTEED=$(jq -r '.criticalityBands.highBandGuaranteed // "-"' <<< "$KUBELET_CONFIG")
MEDIUM_BAND_MIN_LEVEL=$(jq -r '.criticalityBands.mediumBandMinLevel // "-"' <<< "$KUBELET_CONFIG")
MEDIUM_BAND_GUARANTEED=$(jq -r '.criticalityBands.mediumBandGuaranteed // "-"' <<< "$KUBELET_CONFIG")
KUBELET_VERBOSITY=$(jq -r '.logging.verbosity // 0' <<< "$KUBELET_CONFIG")

for var in CRITICALITY_LABEL_KEY MAX_CRITICALITY_LEVEL MIN_CRITICALITY_LEVEL \
           MAX_CONCURRENT_POD_CREATIONS \
           HIGH_BAND_MIN_LEVEL HIGH_BAND_GUARANTEED \
           MEDIUM_BAND_MIN_LEVEL MEDIUM_BAND_GUARANTEED; do
    if [ "${!var}" == "-" ]; then
        echo "Error: Kubelet on node '$NODE' does not expose '$var' (is it the Preemptive Kubelet build?)" >&2
        exit 1
    fi
done

if [[ "$BANDS_ENABLED" == "true" || "$FIFO_ENABLED" == "true" ]]; then
    KUBELET_TYPE="Preemptive"
else
    KUBELET_TYPE="Vanilla"
fi

if [ "$TEST_TYPE" == "Deployment" ] && [ "$KUBELET_TYPE" == "Preemptive" ]; then
    echo "Error: Deployment test requires the Vanilla Kubelet, but node '$NODE' runs the Preemptive Kubelet" >&2
    exit 1
fi

if [ "$KUBELET_VERBOSITY" -lt 4 ]; then
    echo "Error: Kubelet log verbosity on node '$NODE' is $KUBELET_VERBOSITY, at least 4 is required (set logging.verbosity in the Kubelet config)" >&2
    exit 1
fi

# Experiment name generation
if [ "$OFFSET" -gt 0 ] && [ -z "$EXPERIMENT_NAME" ]; then
    echo "Error: Experiment name [-e] is required to resume an experiment with offset $OFFSET" >&2
    exit 1
fi
if [ -z "$EXPERIMENT_NAME" ]; then
    EXPERIMENT_NAME="$(date '+%Y-%m-%d_%H-%M-%S')"
fi

################ UTILITY FUNCTIONS ################

# Render a template into a manifest
# $1 = template, $2 = output file, $3 = resource number, $4 = criticality level
render_manifest() {
    local template="$1" output="$2" num="$3" criticality="$4"
    env "$NUM_VAR=$num" \
        NAMESPACE="$NAMESPACE" \
        NODE="$NODE" \
        CRITICALITY_LEVEL="$criticality" \
        envsubst '${DP_NUM} ${RT_NUM} ${NAMESPACE} ${NODE} ${CRITICALITY_LEVEL}' \
        < "$template" > "$output"
}

###################################################


################### MAIN SCRIPT ###################

# Display configuration
echo "================================================"
echo "Orchestration Benchmark - Starting"
echo "================================================"
echo "Experiment Name: $EXPERIMENT_NAME"
echo "Test Type: $TEST_TYPE"
echo "Kubelet Type: $KUBELET_TYPE"
if [ "$KUBELET_TYPE" == "Preemptive" ]; then
    echo "Priority Bands Feature Status: $BANDS_ENABLED"
    echo "Priority Bands Stealing Feature Status: $STEALING_ENABLED"
    echo "Pod Worker FIFO Scheduling Feature Status: $FIFO_ENABLED"
    echo "Criticality Label: $CRITICALITY_LABEL_KEY"
    echo "Criticality Maximum Level: $MAX_CRITICALITY_LEVEL"
    echo "Criticality Minimum Level: $MIN_CRITICALITY_LEVEL"
    if [ "$BANDS_ENABLED" == "true" ]; then
        echo "Number of Concurrent Pod Creations allowed: $MAX_CONCURRENT_POD_CREATIONS"
        echo "High Priority Band range: ${MAX_CRITICALITY_LEVEL}-${HIGH_BAND_MIN_LEVEL}"
        echo "Minimum Number of Concurrent Creations granted to the High Priority Band: $HIGH_BAND_GUARANTEED"
        echo "Medium Priority Band range: $((HIGH_BAND_MIN_LEVEL + 1))-${MEDIUM_BAND_MIN_LEVEL}"
        echo "Minimum Number of Concurrent Creations granted to the Medium Priority Band: $MEDIUM_BAND_GUARANTEED"
        echo "Low Priority Band range: $((MEDIUM_BAND_MIN_LEVEL + 1))-${MIN_CRITICALITY_LEVEL}"
    fi
fi
echo "Namespace: $NAMESPACE"
echo "Number of Services: $NUMBER_OF_SERVICES"
echo "Iterations: $ITERATIONS"
echo "Offset: $OFFSET"
echo "Number of Interfering Resources: $NUMBER_OF_INTERFERING_RESOURCES"
echo "Deploy Stress: $DEPLOY_STRESS"
echo "Preempt-K8s Controller Namespace: $RT_CONTROLLER_NAMESPACE"
echo "Preempt-K8s Controller Pod Name: $RT_CONTROLLER_POD"
echo "Loki Namespace: $LOKI_NAMESPACE"
echo "Loki Name: $LOKI_NAME"
echo "Experiment Node: $NODE"
echo "Kubelet Logs Verbosity Level: $KUBELET_VERBOSITY"
echo "================================================"
echo ""

# Manifest generation
LEVEL_MOST_CRITICAL="$MAX_CRITICALITY_LEVEL"
LEVEL_HIGH_LAST="$HIGH_BAND_MIN_LEVEL"
LEVEL_MEDIUM_LAST="$MEDIUM_BAND_MIN_LEVEL"
LEVEL_LEAST_CRITICAL="$MIN_CRITICALITY_LEVEL"

echo "Generating manifests..."
INTERFERING_MANIFESTS=()
KSVC_MANIFESTS=()
KSVC_NAMES=()
if [ "$TEST_TYPE" == "Deployment" ]; then
    INTERFERING_TEMPLATE="$INTERFERING_DEPLOYMENT_TEMPLATE"
    KSVC_TEMPLATE="$KSVC_DEPLOYMENT_TEMPLATE"
    NUM_VAR="DP_NUM"
else
    INTERFERING_TEMPLATE="$INTERFERING_RTRESOURCE_TEMPLATE"
    KSVC_TEMPLATE="$KSVC_RTRESOURCE_TEMPLATE"
    NUM_VAR="RT_NUM"
fi
INTERFERING_DIR=$(dirname "$INTERFERING_TEMPLATE")
KSVC_DIR=$(dirname "$KSVC_TEMPLATE")
INTERFERING_PREFIX=$(basename "$INTERFERING_TEMPLATE" -template.yaml)
KSVC_PREFIX=$(basename "$KSVC_TEMPLATE" -template.yaml)

SEED=42
RANDOM=$SEED

HIGH_BAND_LEVELS=$((LEVEL_HIGH_LAST - LEVEL_MOST_CRITICAL + 1))
for j in $(seq 1 "$NUMBER_OF_SERVICES"); do
    level=$((LEVEL_MOST_CRITICAL + (j - 1) % HIGH_BAND_LEVELS))
    f="$KSVC_DIR/$KSVC_PREFIX-$j.yaml"
    render_manifest "$KSVC_TEMPLATE" "$f" "$j" "$level"
    KSVC_MANIFESTS+=("$f")
    KSVC_NAMES+=("$KSVC_PREFIX-$level-$j")
done

MEDIUM_INTERFERING=$((NUMBER_OF_INTERFERING_RESOURCES / 2))
for j in $(seq 1 "$NUMBER_OF_INTERFERING_RESOURCES"); do
    if [ "$j" -le "$MEDIUM_INTERFERING" ]; then
        level=$((LEVEL_HIGH_LAST + 1 + RANDOM % (LEVEL_MEDIUM_LAST - LEVEL_HIGH_LAST)))
    else
        level=$((LEVEL_MEDIUM_LAST + 1 + RANDOM % (LEVEL_LEAST_CRITICAL - LEVEL_MEDIUM_LAST)))
    fi
    f="$INTERFERING_DIR/$INTERFERING_PREFIX-$j.yaml"
    render_manifest "$INTERFERING_TEMPLATE" "$f" "$j" "$level"
    INTERFERING_MANIFESTS+=("$f")
done

ALL_MANIFESTS=("${INTERFERING_MANIFESTS[@]}" "${KSVC_MANIFESTS[@]}")
echo "Generated ${#INTERFERING_MANIFESTS[@]} interfering and ${#KSVC_MANIFESTS[@]} KSVC manifests!"
echo ""

# Create results directory
echo "Creating results directory..."
if [[ "$TEST_TYPE" == "Deployment" ]]; then
    CONTROLLER_DIR="kube-manager"
else
    CONTROLLER_DIR="preempt-k8s"
fi
if [[ "$KUBELET_TYPE" == "Vanilla" ]]; then
    KUBELET_DIR="vanilla"
else
    KUBELET_DIR="preemptive"
fi
RESULTS_DIR="/experiments/kubelet/$CONTROLLER_DIR/$KUBELET_DIR/${EXPERIMENT_NAME}"
if [ "$OFFSET" -gt 0 ]; then
    if ! kubectl exec "$QUERY_POD_NAME" -n "$NAMESPACE" -- test -f "$RESULTS_DIR/config.txt"; then
        echo "Error: Experiment '$EXPERIMENT_NAME' not found in '$RESULTS_DIR' (missing config.txt)" >&2
        exit 1
    fi
else
    if kubectl exec "$QUERY_POD_NAME" -n "$NAMESPACE" -- test -e "$RESULTS_DIR"; then
        echo "Error: Results directory '$RESULTS_DIR' already exists" >&2
        exit 1
    fi
fi
kubectl exec "$QUERY_POD_NAME" -n "$NAMESPACE" -- mkdir -p "$RESULTS_DIR"
echo "Results will be stored in: $RESULTS_DIR"
echo ""

# Save configuration to file in the pod
if [ "$OFFSET" -eq 0 ]; then
    echo "Saving test configuration..."
    kubectl exec "$QUERY_POD_NAME" -n "$NAMESPACE" -- sh -c "
        cat > $RESULTS_DIR/config.txt <<EOF
================================================
Orchestration Benchmark - Test Configuration
================================================
Experiment Name: $EXPERIMENT_NAME
Test Type: $TEST_TYPE
Kubelet Type: $KUBELET_TYPE
$(if [ "$KUBELET_TYPE" == "Preemptive" ]; then
    echo "Priority Bands Feature Status: $BANDS_ENABLED"
    echo "Priority Bands Stealing Feature Status: $STEALING_ENABLED"
    echo "Pod Worker FIFO Scheduling Feature Status: $FIFO_ENABLED"
    echo "Criticality Label: $CRITICALITY_LABEL_KEY"
    echo "Criticality Maximum Level: $MAX_CRITICALITY_LEVEL"
    echo "Criticality Minimum Level: $MIN_CRITICALITY_LEVEL"
    if [ "$BANDS_ENABLED" == "true" ]; then
        echo "Number of Concurrent Pod Creations allowed: $MAX_CONCURRENT_POD_CREATIONS"
        echo "High Priority Band range: ${MAX_CRITICALITY_LEVEL}-${HIGH_BAND_MIN_LEVEL}"
        echo "Minimum Number of Concurrent Creations granted to the High Priority Band: $HIGH_BAND_GUARANTEED"
        echo "Medium Priority Band range: $((HIGH_BAND_MIN_LEVEL + 1))-${MEDIUM_BAND_MIN_LEVEL}"
        echo "Minimum Number of Concurrent Creations granted to the Medium Priority Band: $MEDIUM_BAND_GUARANTEED"
        echo "Low Priority Band range: $((MEDIUM_BAND_MIN_LEVEL + 1))-${MIN_CRITICALITY_LEVEL}"
    fi
fi)
Namespace: $NAMESPACE
Number of Services: $NUMBER_OF_SERVICES
Iterations: $ITERATIONS
Number of Interfering Resources: $NUMBER_OF_INTERFERING_RESOURCES
Deploy Stress: $DEPLOY_STRESS
Preempt-K8s Controller Namespace: $RT_CONTROLLER_NAMESPACE
Preempt-K8s Controller Pod Name: $RT_CONTROLLER_POD
Loki Namespace: $LOKI_NAMESPACE
Loki Name: $LOKI_NAME
Experiment Node: $NODE
Kubelet Logs Verbosity Level: $KUBELET_VERBOSITY
================================================
EOF
"
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

    # We run the stress-ng cpu interference in the control plane and the experiment worker node
    if [ "$DEPLOY_STRESS" == "true" ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting cpu interference load on control plane..."
        CP_CPUS=$(nproc)
        stress-ng --cpu $(( CP_CPUS > 1 ? CP_CPUS - 1 : 1 )) &>/dev/null &
        CPU_STRESS_PID=$!
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting cpu interference load on experiment worker node..."
        NODE_CPU_STRESS_PID=$(ssh root@"${NODE_IP}" \
            'n=$(nproc); [ "$n" -gt 1 ] && n=$((n - 1)); nohup stress-ng --cpu "$n" >/dev/null 2>&1 & echo $!')
        sleep 10
    fi

    # Deploy all resources (interfering and KSVCs)
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Deploying all resources..."
    mapfile -t SHUFFLED_MANIFESTS < <(printf '%s\n' "${ALL_MANIFESTS[@]}" | shuf)
    KSVC_POSITIONS=()
    for idx in "${!SHUFFLED_MANIFESTS[@]}"; do
        name=$(basename "${SHUFFLED_MANIFESTS[$idx]}" .yaml)
        if [[ "$name" == "$KSVC_PREFIX"-* ]]; then
            KSVC_POSITIONS+=("$name:$((idx + 1))")
        fi
    done
    START_TIME=$(date +%s%N)
    sleep "$WINDOW_MARGIN"
    APPLY_PIDS=()
    for f in "${SHUFFLED_MANIFESTS[@]}"; do
        kubectl apply -f "$f" &>/dev/null &
        APPLY_PIDS+=($!)
    done
    wait "${APPLY_PIDS[@]}" || true
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] All resources deployed! KSVC positions: ${KSVC_POSITIONS[*]}"
    
    # Wait for all pods (KSVCs and interfering) to be running
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Waiting for all pods to be running..."
    KSVC_SELECTOR="serving.knative.dev/service in ($(IFS=,; echo "${KSVC_NAMES[*]}"))"
    EXPECTED_PODS=$((NUMBER_OF_SERVICES + NUMBER_OF_INTERFERING_RESOURCES + 1))
    DEADLINE=$((SECONDS + RUNNING_TIMEOUT))
    while true; do
        RUNNING=$({ kubectl get pods -n "$NAMESPACE" \
            --field-selector=status.phase=Running --no-headers 2>/dev/null || true; } | wc -l)
        if [ "$RUNNING" -eq "$EXPECTED_PODS" ]; then
            sleep "$WINDOW_MARGIN"
            END_TIME=$(date +%s%N)
            break
        fi
        if [ "$SECONDS" -ge "$DEADLINE" ]; then
            echo "Error: only $RUNNING of $EXPECTED_PODS pods running after ${RUNNING_TIMEOUT}s in iteration $i" >&2
            echo "Iteration $i discarded!"
            if [ "$i" -gt 1 ]; then
                echo "Partial results saved to $RESULTS_DIR"
            fi
            exit 1
        fi
        sleep 1
    done
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] All pods are running!"

    # Iteration clean up: cpu interfering load on control plane and experiment worker node
    if [ "$DEPLOY_STRESS" == "true" ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Stopping cpu interference load on control plane and experiment worker node..."
        kill "$CPU_STRESS_PID" 2>/dev/null || true
        ssh root@"${NODE_IP}" "kill $NODE_CPU_STRESS_PID" 2>/dev/null || true
    fi

    # Iteration clean up: delete all resources (interfering and KSVCs)
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Cleaning up iteration resources..."
    DELETE_ARGS=()
    for f in "${ALL_MANIFESTS[@]}"; do
        DELETE_ARGS+=(-f "$f")
    done
    kubectl delete "${DELETE_ARGS[@]}" --ignore-not-found --wait=false &>/dev/null
    CLEANUP_TIMEOUT=60
    DEADLINE=$((SECONDS + CLEANUP_TIMEOUT))
    while true; do
        kubectl delete pod -n "$NAMESPACE" -l "$KSVC_SELECTOR" \
            --grace-period=0 --force --ignore-not-found >/dev/null 2>&1 || true
        REMAINING_RESOURCES=$({ kubectl get "${DELETE_ARGS[@]}" --ignore-not-found --no-headers 2>/dev/null || true; } | awk 'NF' | wc -l)
        REMAINING_PODS=$({ kubectl get pods -n "$NAMESPACE" --no-headers 2>/dev/null || true; } | wc -l)
        if [ "$REMAINING_RESOURCES" -eq 0 ] && [ "$REMAINING_PODS" -eq 1 ]; then
            break
        fi
        if [ "$SECONDS" -ge "$DEADLINE" ]; then
            echo "Error: cleanup not completed after ${CLEANUP_TIMEOUT}s" >&2
            echo "Iteration $i discarded!"
            if [ "$i" -gt 1 ]; then
                echo "Partial results saved to $RESULTS_DIR"
            fi
            exit 1
        fi
        sleep 1
    done
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Cleanup completed!"

    # Local directory collecting all the results of the iteration
    ITERATION_DIR="iteration-${i}"
    mkdir -p "./$ITERATION_DIR"

    # We query Loki to retrieve control plane logs and save them to persistent storage
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Querying Loki for control plane logs..."
    LOKI_QUERY="{job=\"kubernetes-audit\"} | json "
    curl -G -sSf "http://${LOKI_IP_ADDRESS}:3100/loki/api/v1/query_range" \
        --data-urlencode "query=$LOKI_QUERY" \
        --data-urlencode "start=$START_TIME" \
        --data-urlencode "end=$END_TIME" \
        --data-urlencode "limit=1000000" \
        --data-urlencode "direction=forward" | \
        jq '[.data.result[].values[] | {
        timestamp: .[0],
        log: (.[1] | fromjson)
        }] | sort_by(.timestamp)' > "./$ITERATION_DIR/loki-logs.json"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Loki logs retrieved!"

    # We analyze the Kubelet logs on the experiment node and save the results to persistent storage
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Analyzing Kubelet logs on experiment node..."
    ANALYSIS_FOLDER="kubelet-logs"
    ANALYSIS_NODE_DIR="/root/kubelet-patch-analysis/${ANALYSIS_FOLDER}"
    KUBELET_LOGS_SINCE=$(date -d "@$(( START_TIME / 1000000000 ))" '+%Y-%m-%d %H:%M:%S')
    KUBELET_LOGS_UNTIL=$(date -d "@$(( END_TIME / 1000000000 ))" '+%Y-%m-%d %H:%M:%S')
    ssh -o BatchMode=yes root@"$NODE_IP" "cd /root && python3 '$ANALYSIS_SCRIPT' \
        -r '$ANALYSIS_FOLDER' -s '$KUBELET_LOGS_SINCE' -u '$KUBELET_LOGS_UNTIL' \
        -n '$MAX_CONCURRENT_POD_CREATIONS' -g '$HIGH_BAND_GUARANTEED,$MEDIUM_BAND_GUARANTEED' \
        -b '$HIGH_BAND_MIN_LEVEL,$MEDIUM_BAND_MIN_LEVEL' -t '$STEALING_ENABLED'" >/dev/null
    scp -r -o BatchMode=yes root@"$NODE_IP":"$ANALYSIS_NODE_DIR/*" "./$ITERATION_DIR/" >/dev/null
    ssh -o BatchMode=yes root@"$NODE_IP" "rm -rf '$ANALYSIS_NODE_DIR'"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Kubelet logs analyzed!"

    # We save all the results of the iteration to persistent storage
    kubectl cp "./$ITERATION_DIR" "${NAMESPACE}/${QUERY_POD_NAME}:${RESULTS_DIR}/${ITERATION_DIR}" >/dev/null
    rm -rf "./$ITERATION_DIR"

    # Page cache flush on all nodes to minimize the effect of caching on subsequent iterations
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Flushing page cache on all nodes..."

    sync; echo 3 | sudo tee /proc/sys/vm/drop_caches >/dev/null 2>&1
    ssh root@143.225.229.231 "sync; echo 3 | sudo tee /proc/sys/vm/drop_caches" >/dev/null 2>&1
    ssh root@"${NODE_IP}" "sync; echo 3 | sudo tee /proc/sys/vm/drop_caches" >/dev/null 2>&1
    ssh root@143.225.229.233 "sync; echo 3 | sudo tee /proc/sys/vm/drop_caches" >/dev/null 2>&1

    # Iteration completed, results saved
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Results saved to $RESULTS_DIR!"

    echo "------------------------------------------------"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Iteration $i of $ITERATIONS completed!"
    echo "------------------------------------------------"
done

echo "================================================"
echo "All test iterations completed successfully!"
echo "================================================"

# Cleanup
rm -f "${ALL_MANIFESTS[@]}"
echo "Manifests deleted: ${#ALL_MANIFESTS[@]} files removed!"
echo ""

###################################################
