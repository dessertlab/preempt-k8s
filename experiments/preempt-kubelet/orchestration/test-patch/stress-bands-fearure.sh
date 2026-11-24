#!/usr/bin/env bash

# Exits immediately if a command exits with a non-zero status,
# if an undefined variable is used,
# or if any command in a pipeline fails
set -e
set -u
set -o pipefail

# Default values and working variables
NODE="dessertw2"
NAMESPACE="default"
PER_GROUP=10
PARALLEL=40

SEED=42

HIGH_MIN=10
MEDIUM_MIN=30
MIN_LEVEL=80

IMAGE="registry.k8s.io/pause:3.10"

TIMEOUT="300s"
KEEP=false

# Parse command line flags
while getopts ":n:p:d:c:f:s:l:t:k:h" opt; do
    case ${opt} in
        n) NODE="${OPTARG}" ;;
        p) NAMESPACE="${OPTARG}" ;;
        d) PER_GROUP="${OPTARG}" ;;
        c) PARALLEL="${OPTARG}" ;;
        f) HIGH_MIN="${OPTARG}" ;;
        s) MEDIUM_MIN="${OPTARG}" ;;
        l) MIN_LEVEL="${OPTARG}" ;;
        t) TIMEOUT="${OPTARG}" ;;
        k) KEEP="${OPTARG}" ;;
        h) 
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  -n <node>                           Name of the node (default: dessertw2)"
            echo "  -p <namespace>                      Test Namespace (default: default)"
            echo "  -d <pod-per-group>                  Number of pods per band (default: 10)"
            echo "  -c <concurrent-requests>            Number of concurrent requests (default: 40)"
            echo "  -f <first-band-min-priority>        Minimum priority level of the first band (default: 10)"
            echo "  -s <second-band-min-priority>       Minimum priority level of the second band (default: 30)"
            echo "  -l <min-priority>                   Minimum priority level allowed (default: 80)"
            echo "  -t <creation-req-timeout>           Total creation requests timeout (default: 300s)"
            echo "  -k <keep-pods>                      Keep test pods after the test [REQUIRES MANUAL DELETION] (default: false)"
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

# Create results directory
RUN_ID="$(date '+%Y-%m-%d_%H-%M-%S')"
RESULTS_DIR="./kubelet-patch-tests/$RUN_ID"
echo "Creating results directory..."
mkdir -p "$RESULTS_DIR"
echo "Results will be stored in: $RESULTS_DIR"
echo ""

# Manifest generation
awk -v seed="${SEED}" -v n="${PER_GROUP}" -v h="${HIGH_MIN}" -v m="${MEDIUM_MIN}" -v x="${MIN_LEVEL}" 'BEGIN {
  srand(seed)
  for (i = 0; i < n; i++) print 1 + int(rand() * h)
  for (i = 0; i < n; i++) print h + 1 + int(rand() * (m - h))
  for (i = 0; i < n; i++) print m + 1 + int(rand() * (x - m))
  for (i = 0; i < n; i++) print "none"
}' | awk -v seed="$((SEED + 1))" 'BEGIN { srand(seed) } { printf "%.12f\t%s\n", rand(), $0 }' \
  | sort -k1,1 | cut -f2 > "${RESULTS_DIR}/levels"

idx=0
while read -r level; do
  idx=$((idx + 1))
  name="band-pod-$(printf '%03d' "${idx}")-l${level}"
  label=""
  if [[ "${level}" != "none" ]]; then
    label="    criticality: \"${level}\""
  fi
  cat > "${RESULTS_DIR}/${name}.yaml" <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: ${name}
  namespace: ${NAMESPACE}
  labels:
    app: bands-test
    run: ${RUN_ID}
${label}
spec:
  nodeName: ${NODE}
  terminationGracePeriodSeconds: 0
  containers:
  - name: bands-test-container
    image: ${IMAGE}
    imagePullPolicy: IfNotPresent
EOF
done < "${RESULTS_DIR}/levels"

# Test
TOTAL=$((PER_GROUP * 4))
echo "Run ${RUN_ID}: ${TOTAL} pods on ${NODE}, ${PARALLEL} concurrent creations, seed ${SEED}"
echo ""

SINCE="$(date -d '-15 sec' '+%Y-%m-%d %H:%M:%S')"
START_NS="$(date +%s%N)"
ls "${RESULTS_DIR}"/*.yaml | xargs -P "${PARALLEL}" -n1 kubectl create -f >/dev/null
CREATED_NS="$(date +%s%N)"
echo "Creation requests sent in $(( (CREATED_NS - START_NS) / 1000000 )) ms, waiting for Pods to become Ready..."
echo ""

kubectl wait --for=condition=Ready pod -l "run=${RUN_ID}" -n "${NAMESPACE}" --timeout="${TIMEOUT}" >/dev/null
READY_NS="$(date +%s%N)"
UNTIL="$(date -d '+15 sec' '+%Y-%m-%d %H:%M:%S')"
echo "All pods Ready after $(( (READY_NS - START_NS) / 1000000 )) ms from start"
echo ""

if [[ "${KEEP}" == false ]]; then
  echo "Deleting Pods..."
  kubectl delete pod -l "run=${RUN_ID}" -n "${NAMESPACE}" --grace-period=0 --wait=true >/dev/null
  echo ""
fi

echo "On node ${NODE}, after at least 15 seconds:"
echo "  stealing enabled: python3 ./analyze-bands-feature.py -r ${RUN_ID} -s '${SINCE}' -u '${UNTIL}'"
echo "  stealing disabled: python3 ./analyze-bands-feature.py -r ${RUN_ID} -s '${SINCE}' -u '${UNTIL}' -t false"
echo ""

echo "Test Completed!"
