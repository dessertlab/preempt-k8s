#!/bin/bash

# Exits immediately if a command exits with a non-zero status,
# if an undefined variable is used,
# or if any command in a pipeline fails
set -e
set -u
set -o pipefail

# Default values and working variables
EXPERIMENT_NAME="orchestration"
TEST_TYPE="Deployment"
KUBELET_TYPE="Vanilla"
NAMESPACE="default"
NUMBER_OF_SERVICES="5"
ITERATIONS="30"
OFFSET="0"
NUMBER_OF_INTERFERING_RESOURCES="80"

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
LIST_OF_NON_FEASIBLE_NODES=("dessertw1" "dessertw3")

KSVC_CRITICALITY="1"
INTERFERENCE_CRITICALITY="2"

# Parse command line flags
while getopts ":e:t:k:n:s:i:o:r:l:q:p:f:h" opt; do
    case $opt in
        e) EXPERIMENT_NAME="$OPTARG" ;;
        t) TEST_TYPE="$OPTARG" ;;
        k) KUBELET_TYPE="$OPTARG" ;;
        n) NAMESPACE="$OPTARG" ;;
        s) NUMBER_OF_SERVICES="$OPTARG" ;;
        i) ITERATIONS="$OPTARG" ;;
        o) OFFSET="$OPTARG" ;;
        r) NUMBER_OF_INTERFERING_RESOURCES="$OPTARG" ;;
        l) LOKI_NAMESPACE="$OPTARG" ;;
        q) LOKI_NAME="$OPTARG" ;;
        p) NODE="$OPTARG" ;;
        f) IFS=',' read -r -a LIST_OF_NON_FEASIBLE_NODES <<< "$OPTARG" ;;
        h) 
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  -e <experiment-name>                Name of the experiment (default: orchestration)"
            echo "  -t <test-type>                      Type of test to run (default: Deployment)"
            echo "  -k <kubelet-type>                   Type of Kubelet to use (default: Vanilla)"
            echo "  -n <namespace>                      Namespace where services and interfering resources are deployed (default: default)"
            echo "  -s <number-of-services>             Number of concurrent services to deploy (default: 5)"
            echo "  -i <iterations>                     Number of test iterations (default: 30)"
            echo "  -o <offset>                         Iterations offset (default: 0)"
            echo "  -r <number-of-resources>            Number of interfering resources (default: 80)"
            echo "  -l <loki-namespace>                 Namespace where the Loki service is deployed (default: observability)"
            echo "  -q <loki-name>                      Name of the Loki service (default: loki)"
            echo "  -p <node>                           Node where services and the interfering resources should be scheduled (default: dessertw2)"
            echo "  -f <list-of-non-feasible-nodes>     List of nodes where services should not be scheduled (default: dessertw1,dessertw3)"
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

# Validate kubelet type
if [[ "$KUBELET_TYPE" != "Vanilla" && "$KUBELET_TYPE" != "Preemptive" ]]; then
    echo "Error: Kubelet type must be either 'Vanilla' or 'Preemptive' (got: $KUBELET_TYPE)" >&2
    exit 1
fi

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

# Validate list of non-feasible nodes
if [[ "${#LIST_OF_NON_FEASIBLE_NODES[@]}" -ne 2 ]]; then
    echo "Error: Two non-feasible nodes must be specified (got: ${#LIST_OF_NON_FEASIBLE_NODES[@]})" >&2
    exit 1
fi
for NF_NODE in "${LIST_OF_NON_FEASIBLE_NODES[@]}"; do
    if ! kubectl get node "$NF_NODE" &>/dev/null; then
        echo "Error: Non-feasible node '$NF_NODE' does not exist in the cluster" >&2
        exit 1
    fi
done

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

################ UTILITY FUNCTIONS ################

# Render a template into a manifest
# $1 = template, $2 = output file, $3 = resource number, $4 = criticality level
render_manifest() {
    local template="$1" output="$2" num="$3" criticality="$4"
    env "$NUM_VAR=$num" \
        NAMESPACE="$NAMESPACE" \
        NODE="$NODE" \
        NON_FEASIBLE_NODE_1="${LIST_OF_NON_FEASIBLE_NODES[0]}" \
        NON_FEASIBLE_NODE_2="${LIST_OF_NON_FEASIBLE_NODES[1]}" \
        CRITICALITY_LEVEL="$criticality" \
        envsubst '${DP_NUM} ${RT_NUM} ${NAMESPACE} ${NODE} ${NON_FEASIBLE_NODE_1} ${NON_FEASIBLE_NODE_2} ${CRITICALITY_LEVEL}' \
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
echo "Namespace: $NAMESPACE"
echo "Number of Services: $NUMBER_OF_SERVICES"
echo "Iterations: $ITERATIONS"
echo "Offset: $OFFSET"
echo "Number of Interfering Resources: $NUMBER_OF_INTERFERING_RESOURCES"
echo "Loki Namespace: $LOKI_NAMESPACE"
echo "Loki Name: $LOKI_NAME"
echo "Experiment Node: $NODE"
echo "List of Non-Feasible Nodes: ${LIST_OF_NON_FEASIBLE_NODES[*]}"
echo "KSVC Criticality Level: $KSVC_CRITICALITY"
echo "Interference Criticality Level: $INTERFERENCE_CRITICALITY"
echo "================================================"
echo ""

# Manifest generation
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
for j in $(seq 1 "$NUMBER_OF_INTERFERING_RESOURCES"); do
    f="$INTERFERING_DIR/$INTERFERING_PREFIX-$j.yaml"
    render_manifest "$INTERFERING_TEMPLATE" "$f" "$j" "$INTERFERENCE_CRITICALITY"
    INTERFERING_MANIFESTS+=("$f")
done
for j in $(seq 1 "$NUMBER_OF_SERVICES"); do
    f="$KSVC_DIR/$KSVC_PREFIX-$j.yaml"
    render_manifest "$KSVC_TEMPLATE" "$f" "$j" "$KSVC_CRITICALITY"
    KSVC_MANIFESTS+=("$f")
    KSVC_NAMES+=("$KSVC_PREFIX-$j")
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
kubectl exec "$QUERY_POD_NAME" -n "$NAMESPACE" -- mkdir -p "$RESULTS_DIR"
echo "Results will be stored in: $RESULTS_DIR"
echo ""

# Save configuration to file in the pod
if [ "$OFFSET" -eq 0 ]; then
    echo "Saving test configuration..."
    kubectl exec "$QUERY_POD_NAME" -n "$NAMESPACE" -- bash -c "
        cat > $RESULTS_DIR/config.txt <<EOF
================================================
Orchestration Benchmark - Test Configuration
================================================
Experiment Name: $EXPERIMENT_NAME
Test Type: $TEST_TYPE
Kubelet Type: $KUBELET_TYPE
Namespace: $NAMESPACE
Number of Services: $NUMBER_OF_SERVICES
Iterations: $ITERATIONS
Number of Interfering Resources: $NUMBER_OF_INTERFERING_RESOURCES
Node: $NODE
List of Non-Feasible Nodes: ${LIST_OF_NON_FEASIBLE_NODES[*]}
KSVC Criticality Level: $KSVC_CRITICALITY
Interference Criticality Level: $INTERFERENCE_CRITICALITY
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
    sleep 20
    for f in "${SHUFFLED_MANIFESTS[@]}"; do
        kubectl apply -f "$f" >/dev/null &
    done
    wait
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] All resources deployed! KSVC positions: ${KSVC_POSITIONS[*]}"
    
    #  Wait for all KSVCs to be ready
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Waiting for all KSVCs to be ready..."
    KSVC_SELECTOR="serving.knative.dev/service in ($(IFS=,; echo "${KSVC_NAMES[*]}"))"
    TIMEOUT=30
    DEADLINE=$((SECONDS + TIMEOUT))
    while true; do
        RUNNING=$({ kubectl get pods -n "$NAMESPACE" -l "$KSVC_SELECTOR" \
            --field-selector=status.phase=Running --no-headers 2>/dev/null || true; } | wc -l)
        if [ "$RUNNING" -eq "$NUMBER_OF_SERVICES" ]; then
            sleep 20
            END_TIME=$(date +%s%N)
            break
        fi
        if [ "$SECONDS" -ge "$DEADLINE" ]; then
            echo "Error: only $RUNNING of $NUMBER_OF_SERVICES KSVC pods running after ${TIMEOUT}s in iteration $i" >&2
            echo "Iteration $i discarded!"
            if [ "$i" -gt 1 ]; then
                echo "Partial results saved to $RESULTS_DIR"
            fi
            exit 1
        fi
        sleep 1
    done
    EXPECTED_PODS=$(( ${NUMBER_OF_SERVICES} + ${NUMBER_OF_INTERFERING_RESOURCES} + 1 ))
    TOTAL_PODS=$({ kubectl get pods -n "$NAMESPACE" --no-headers 2>/dev/null || true; } | wc -l)
    if [ "$TOTAL_PODS" -ne "$EXPECTED_PODS" ]; then
        echo "Error: found $TOTAL_PODS pods in namespace '$NAMESPACE', expected $EXPECTED_PODS in iteration $i" >&2
        echo "Iteration $i discarded!"
        if [ "$i" -gt 1 ]; then
            echo "Partial results saved to $RESULTS_DIR"
        fi
        exit 1
    fi
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] All KSVCs are running!"

    # Iteration cleanup: delete all resources (interfering and KSVCs)
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Cleaning up iteration resources..."
    DELETE_ARGS=()
    for f in "${ALL_MANIFESTS[@]}"; do
        DELETE_ARGS+=(-f "$f")
    done
    kubectl delete "${DELETE_ARGS[@]}" --ignore-not-found --wait=false >/dev/null
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

    # We query Loki to retrieve control plane logs and save them to persistent storage
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Querying Loki for control plane logs..."
    LOKI_QUERY="{job=\"kubernetes-audit\"} | json "
    LOKI_OUTPUT_FILE="loki-logs-iteration_${i}.json"
    curl -G -sSf "http://${LOKI_IP_ADDRESS}:3100/loki/api/v1/query_range" \
        --data-urlencode "query=$LOKI_QUERY" \
        --data-urlencode "start=$START_TIME" \
        --data-urlencode "end=$END_TIME" \
        --data-urlencode "limit=5000" \
        --data-urlencode "direction=forward" | \
        jq '[.data.result[].values[] | {
        timestamp: .[0],
        log: (.[1] | fromjson)
        }] | sort_by(.timestamp)' > "./$LOKI_OUTPUT_FILE"
    kubectl cp ./"${LOKI_OUTPUT_FILE}" "${NAMESPACE}/${QUERY_POD_NAME}:${RESULTS_DIR}/${LOKI_OUTPUT_FILE}" >/dev/null 2>&1
    rm ./"${LOKI_OUTPUT_FILE}"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Loki logs retrieved!"

    # Page cache flush on all nodes to minimize the effect of caching on subsequent iterations
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Flushing page cache on all nodes..."

    sync; echo 3 | sudo tee /proc/sys/vm/drop_caches >/dev/null 2>&1
    ssh root@143.225.229.231 "sync; echo 3 | sudo tee /proc/sys/vm/drop_caches" >/dev/null 2>&1
    ssh root@143.225.229.232 "sync; echo 3 | sudo tee /proc/sys/vm/drop_caches" >/dev/null 2>&1
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
