#!/bin/bash

# Exits immediately if a command exits with a non-zero status,
# if an undefined variable is used,
# or if any command in a pipeline fails
set -e
set -u
set -o pipefail

# Default values
POD_BASE_NAME="benchmark-pod"
SERVICE_BASE_NAME="rnn-serving-python"
CREATE="true"
CRITICAL="true"
NUMBER_OF_PODS=10
DESTINATION_PATH="/home"
INVOKER_BINARY_SOURCE_PATH="./invoker"
BUCKET_NODE="dessertw4"
LIST_OF_NON_FEASIBLE_NODES=("dessertw3" "dessertw4")

# Parse command line flags
while getopts "p:b:g:n:c:d:s:t:l:h" opt; do
    case $opt in
        p) POD_BASE_NAME="$OPTARG" ;;
        b) SERVICE_BASE_NAME="$OPTARG" ;;
        g) CREATE="$OPTARG" ;;
        c) CRITICAL="$OPTARG" ;;
        n) NUMBER_OF_PODS="$OPTARG" ;;
        d) DESTINATION_PATH="$OPTARG" ;;
        s) INVOKER_BINARY_SOURCE_PATH="$OPTARG" ;;
        t) BUCKET_NODE="$OPTARG" ;;
        l) IFS=',' read -r -a LIST_OF_NON_FEASIBLE_NODES <<< "$OPTARG" ;;
        h) 
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  -p <pod-base-name>                      Base name of the pods to create or delete (default: benchmark-pod)"
            echo "  -b <service-base-name>                  Base name of RNN services to create (default: rnn-serving-python)"
            echo "  -g <create>                             Choose whether to create or delete invoker pods (default: true)"
            echo "  -c <critical>                           Choose if the services rely on RTResources - with criticality level = 1 - or Deployments (default: true)"
            echo "  -n <number-of-pods>                     Number of invoker pods to create or delete (default: 10)"
            echo "  -d <destination-path>                   Destination path in for invoker binary and endpoints.json file in the invoker pods (default: /home)"
            echo "  -s <invoker-binary-source-path>         invoker binary source path on local machine (default: ./invoker)"
            echo "  -t <bucket-node>                        The two nodes where to schedule the invoker pods (default: dessertw4)"
            echo "  -l <list-of-non-feasible-nodes>         List of nodes where invoker pods should not be scheduled (default: dessertw3,dessertw4)"
            echo "  -h                                      Show this help message"
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

# Validate create flag
if [[ "$CREATE" != "true" && "$CREATE" != "false" ]]; then
    echo "Error: Create flag must be either 'true' or 'false' (got: $CREATE)" >&2
    exit 1
fi

# Validate pod base name
if [[ "$CREATE" == "true" ]]; then
    EXISTING_PODS=$(kubectl get pods --no-headers 2>/dev/null | { grep "^$POD_BASE_NAME" || true; } | wc -l)
    if [[ "$EXISTING_PODS" -gt 0 ]]; then
        echo "Error: Pods with base name '$POD_BASE_NAME' already exist" >&2
        exit 1
    fi
elif [[ "$CREATE" == "false" ]]; then
    EXISTING_PODS=$(kubectl get pods --no-headers 2>/dev/null | { grep "^$POD_BASE_NAME" || true; } | wc -l)
    if [[ "$EXISTING_PODS" -ne "$NUMBER_OF_PODS" ]]; then
        echo "Error: Pods number to delete ($EXISTING_PODS) does not match the specified number ($NUMBER_OF_PODS)" >&2
        exit 1
    fi
fi

# Validate critical flag
if [[ "$CRITICAL" != "true" && "$CRITICAL" != "false" ]]; then
    echo "Error: Critical flag must be either 'true' or 'false' (got: $CRITICAL)" >&2
    exit 1
fi

# Validate number of pods
if ! [[ "$NUMBER_OF_PODS" =~ ^[0-9]+$ ]] || [[ "$NUMBER_OF_PODS" -le 0 ]]; then
    echo "Error: Number of pods must be a positive integer (got: $NUMBER_OF_PODS)" >&2
    exit 1
fi

# Validate invoker binary source path
if [[ ! -f "$INVOKER_BINARY_SOURCE_PATH" ]]; then
    echo "Error: Invoker binary source path '$INVOKER_BINARY_SOURCE_PATH' does not exist or is not a file" >&2
    exit 1
else
    chmod +x "$INVOKER_BINARY_SOURCE_PATH"
fi

# Validate bucket node
if ! kubectl get nodes --no-headers 2>/dev/null | { grep -q "^$BUCKET_NODE" || true; }; then
    echo "Error: Bucket node '$BUCKET_NODE' does not exist in the cluster" >&2
    exit 1
fi

# Validate list of non-feasible nodes
if [[ "${#LIST_OF_NON_FEASIBLE_NODES[@]}" -ne 2 ]]; then
    echo "Error: Two non-feasible nodes must be specified (got: ${#LIST_OF_NON_FEASIBLE_NODES[@]})" >&2
    exit 1
fi
for NODE in "${LIST_OF_NON_FEASIBLE_NODES[@]}"; do
    if ! kubectl get nodes --no-headers 2>/dev/null | { grep -q "^$NODE" || true; }; then
        echo "Error: Non-feasible node '$NODE' does not exist in the cluster" >&2
        exit 1
    fi
done

# Create or delete invoker pods
if [[ "$CREATE" == "true" ]]; then
    echo "Creating $NUMBER_OF_PODS invoker pods with base name '$POD_BASE_NAME'..."

    for i in $(seq 1 "$NUMBER_OF_PODS"); do
        POD_NAME="${POD_BASE_NAME}-${i}"
        SERVICE_NAME="${SERVICE_BASE_NAME}-${i}"
        NON_FEASIBLE_NODE_1="${LIST_OF_NON_FEASIBLE_NODES[0]}"
        NON_FEASIBLE_NODE_2="${LIST_OF_NON_FEASIBLE_NODES[1]}"

        # Create the invoker pod
        cat <<EOF | kubectl apply -f
apiVersion: v1
kind: Pod
metadata:
  name: $POD_NAME
  namespace: default
spec:
  nodeSelector:
    kubernetes.io/hostname: $BUCKET_NODE
  securityContext:
    runAsUser: 0
    runAsGroup: 0
  containers:
    - name: benchmark-container
      image: debian:latest
      command: ["tail", "-f", "/dev/null"]
      resources:
        requests:
          memory: "64Mi"
          cpu: "250m"
        limits:
          memory: "128Mi"
          cpu: "500m"
      securityContext:
        runAsUser: 0
        runAsGroup: 0
        allowPrivilegeEscalation: true
        privileged: true
        readOnlyRootFilesystem: false
      volumeMounts:
        - name: experiments-results
          mountPath: /experiments
  volumes:
    - name: experiments-results
      persistentVolumeClaim:
        claimName: experiments-results
EOF

        # Copy the invoker binary into the pod
        kubectl cp "$INVOKER_BINARY_SOURCE_PATH" "$POD_NAME:$DESTINATION_PATH/invoker"

        # Create endpoints.json file inside the pod
        kubectl exec -i "$POD_NAME" -- bash -c "cat > $DESTINATION_PATH/endpoints.json" <<EOF
[
  {
    "hostname": "$SERVICE_NAME.default.svc.cluster.local"
  }
]
EOF

        # Create local Knative Service manifest
        MANIFEST_FILE="./kn-rnn-serving-python-${i}.yaml"

        if [[ "$CRITICAL" == "true" ]]; then
            cat <<EOF > "$MANIFEST_FILE"
# MIT License

# Copyright (c) 2024 EASE lab

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: $SERVICE_NAME
  namespace: default
spec:
  template:
    metadata:
      annotations:
        autoscaling.knative.dev/minScale: "0"
        autoscaling.knative.dev/maxScale: "1"
        autoscaling.knative.dev/application-criticality-level: "1"
    spec:
      affinity:
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
              - matchExpressions:
                  - key: kubernetes.io/hostname
                    operator: NotIn
                    values:
                      - $NON_FEASIBLE_NODE_1
                      - $NON_FEASIBLE_NODE_2
      containers:
        - image: docker.io/vhiveease/relay:latest
          imagePullPolicy: Never
          ports:
            - name: h2c
              containerPort: 50000
          args:
            - --addr=0.0.0.0:50000
            - --function-endpoint-url=0.0.0.0
            - --function-endpoint-port=50051
            - --function-name=rnn-serving-python
            - --value=French
            - --generator=random
            - --lowerBound=10
            - --upperBound=20
        - image: docker.io/vhiveease/rnn-serving-python:latest
          imagePullPolicy: Never
          args:
            - --addr=0.0.0.0
            - --port=50051
            - --default_language=French
            - --num_strings=15
EOF
        elif [[ "$CRITICAL" == "false" ]]; then
            cat <<EOF > "$MANIFEST_FILE"
# MIT License

# Copyright (c) 2024 EASE lab

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: $SERVICE_NAME
  namespace: default
spec:
  template:
    metadata:
      annotations:
        autoscaling.knative.dev/minScale: "0"
        autoscaling.knative.dev/maxScale: "1"
    spec:
      affinity:
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
              - matchExpressions:
                  - key: kubernetes.io/hostname
                    operator: NotIn
                    values:
                      - $NON_FEASIBLE_NODE_1
                      - $NON_FEASIBLE_NODE_2
      containers:
        - image: docker.io/vhiveease/relay:latest
          imagePullPolicy: Never
          ports:
            - name: h2c
              containerPort: 50000
          args:
            - --addr=0.0.0.0:50000
            - --function-endpoint-url=0.0.0.0
            - --function-endpoint-port=50051
            - --function-name=rnn-serving-python
            - --value=French
            - --generator=random
            - --lowerBound=10
            - --upperBound=20
        - image: docker.io/vhiveease/rnn-serving-python:latest
          imagePullPolicy: Never
          args:
            - --addr=0.0.0.0
            - --port=50051
            - --default_language=French
            - --num_strings=15
EOF
        fi
    done

    echo "✓ All $NUMBER_OF_PODS invoker pods created successfully."

elif [[ "$CREATE" == "false" ]]; then
    echo "Deleting $NUMBER_OF_PODS invoker pods with base name '$POD_BASE_NAME'..."

    for i in $(seq 1 "$NUMBER_OF_PODS"); do
        POD_NAME="${POD_BASE_NAME}-${i}"
        SERVICE_NAME="${SERVICE_BASE_NAME}-${i}"
        MANIFEST_FILE="./kn-rnn-serving-python-${i}.yaml"
        
        # Delete the invoker pod
        kubectl delete pod "$POD_NAME" --ignore-not-found=true
        
        # Remove the manifest file
        rm -f "$MANIFEST_FILE"
    done

    echo "✓ All $NUMBER_OF_PODS invoker pods deleted successfully."
fi
