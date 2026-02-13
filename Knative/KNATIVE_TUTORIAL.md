
# Knative Tutorial

This file will serve as a guide to install and use both the Knative original and patched version.

Skip the build tutorial if you want to use the already patched version.

## Build Custom Version (in Development Environment)

```bash
  git clone https://github.com/knative/serving.git
  cd serving
```

Modify Files according to "CREATE_CUSTOM_VERSION.md" File.

```bash
  go mod tidy
  go mod vendor
  go build ./cmd/activator
  go build ./cmd/autoscaler
  go build ./cmd/controller
  go build ./cmd/queue
  go build ./cmd/webhook
```

Now Create a separate directory called "DOCKER".

Create 5 sub-directories (one for each generated binary)

- "ACTIVATOR"
- "AUTOSCALER"
- "CONTROLLER"
- "QUEUE"
- "WEBHOOK"

Put in them the respective images and Dockerfiles. Then build and push them.

```bash
  sudo docker build -t <docker repo>:activator . -> "in DOCKER/ACTIVATOR"
  sudo docker build -t <docker repo>:autoscaler . -> "in DOCKER/AUTOSCLAER"
  sudo docker build -t <docker repo>:controller . -> "in DOCKER/CONTROLLER"
  sudo docker build -t <docker repo>:queue . -> "in DOCKER/QUEUE"
  sudo docker build -t <docker repo>:webhook . -> "in DOCKER/WEBHOOK"
  sudo docker push <docker repo>:activator
  sudo docker push <docker repo>:autoscaler
  sudo docker push <docker repo>:controller
  sudo docker push <docker repo>:queue
  sudo docker push <docker repo>:webhook
```

Now download the serving core manifests.

```bash
  curl -LO https://github.com/knative/serving/releases/download/knative-v1.16.0/serving-core.yaml
```

Modify them to use your images and correct env variables. Copy all needed files to Cluster Environment. Use the "serving-core.yaml" file in our Knative manifests directory as reference.


## Install Vanilla Version

### Install Procedure

Before launching each command, ensure the components installed with the previous one are up and running.

```bash
  kubectl apply -f https://github.com/knative/serving/releases/download/knative-v1.16.0/serving-crds.yaml
  kubectl apply -f https://github.com/knative/serving/releases/download/knative-v1.16.0/serving-core.yaml
  kubectl apply -f https://github.com/knative/net-kourier/releases/download/knative-v1.16.0/kourier.yaml
  kubectl patch configmap/config-network \
    --namespace knative-serving \
    --type merge \
    --patch '{"data":{"ingress-class":"kourier.ingress.networking.knative.dev"}}'
```

You might need to restart the components in the exact followiong order to ensure a proper connection between components is established, launch each one after the previous component is up and running.

```bash
  kubectl rollout restart deployment/controller -n knative-serving
  kubectl rollout restart deployment/autoscaler -n knative-serving
  kubectl rollout restart deployment/activator -n knative-serving
```

### Uninstall Procedure

```bash
  kubectl delete -f https://github.com/knative/net-kourier/releases/download/knative-v1.16.0/kourier.yaml
  kubectl delete -f https://github.com/knative/serving/releases/download/knative-v1.16.0/serving-core.yaml
  kubectl delete -f https://github.com/knative/serving/releases/download/knative-v1.16.0/serving-crds.yaml
```

### Enable Init Containers in Services' Manifests

ConfigMap editing is done in Vim as default.

```bash
  kubectl edit configmap config-features -n knative-serving 
```
Copy this directly under "data" -> kubernetes.podspec-init-containers: "enabled"

### Enable Node Affinity in Services' Manifests

ConfigMap editing is done in Vim as default.

```bash
  kubectl edit configmap config-features -n knative-serving
```
Copy this directly under "data" -> kubernetes.podspec-affinity: "enabled"

## Install Custom Version

### Install Procedure

Before launching each command, ensure the components installed with the previous one are up and running.

```bash
  kubectl apply -f https://github.com/knative/serving/releases/download/knative-v1.16.0/serving-crds.yaml
  kubectl apply -f serving-core.yaml -> "This is the modified version"
  kubectl apply -f https://github.com/knative/net-kourier/releases/download/knative-v1.16.0/kourier.yaml
  kubectl patch configmap/config-network \
    --namespace knative-serving \
    --type merge \
    --patch '{"data":{"ingress-class":"kourier.ingress.networking.knative.dev"}}'
  kubectl patch configmap config-deployment -n knative-serving --patch '{"data": {"registriesSkippingTagResolving": "index.docker.io"}}' -> "This command modifies the config-deployment ConfigMap in the knative-serving namespace to skip tag resolution for Docker Hub (index.docker.io); needed to use our custom images"
  kubectl apply -f https://raw.githubusercontent.com/knative/serving/release-1.16/config/core/300-resources/route.yaml -> "This command applies the crd necessary for routing"
  kubectl apply -f panic_mode.yaml -> "This command configures panic mode to make it less restrictive"
  kubectl apply -f scaler_role.yaml -> "This command gives Knative Autoscaler complete access and privileges to RTResources"
```

You might need to restart the components in the exact followiong order to ensure a proper connection between components is established, launch each one after the previous component is up and running.

```bash
  kubectl rollout restart deployment/controller -n knative-serving
  kubectl rollout restart deployment/autoscaler -n knative-serving
  kubectl rollout restart deployment/activator -n knative-serving
```

### Uninstall Procedure

```bash
  kubectl delete -f scaler_role.yaml
  kubectl delete -f https://raw.githubusercontent.com/knative/serving/release-1.16/config/core/300-resources/route.yaml
  kubectl patch configmap config-deployment -n knative-serving --patch '{"data": {"registriesSkippingTagResolving": ""}}'
  kubectl delete -f https://github.com/knative/net-kourier/releases/download/knative-v1.16.0/kourier.yaml
  kubectl delete -f serving-core.yaml
  kubectl delete -f https://github.com/knative/serving/releases/download/knative-v1.16.0/serving-crds.yaml
```

## Use Case Tutorial

This is a simple test to verify the two Knative setup are properly working.

In "Knative/manifests" there all yaml files needed. Launch the following commands from that directory.

### Service Setup (Vanilla Version)

```bash
  kubectl apply -f knative-service.yaml
```

Generate load (follow the guide in the next sections) and, then, delete the service.

```bash
  kubectl delete -f knative-service.yaml
```

### Service Setup (Patched Version)

We are assuming the Custom Controller is already up and running.

Deploy a Custom Resource with "1" in the "replicaCount" field.

```bash
  kubectl apply -f kn_resource.yaml
```
Once the pod is up and running, create the service.

```bash
  kubectl apply -f knative-service.yaml
```
Generate load (follow the guide in the next sections) and, then, delete the service.

```bash
  kubectl delete -f knative-service.yaml
  kubectl delete -f kn_resource.yaml
```

### Load Generator (in another Terminal)

This is just a quick test pod to verify everything is working properly.

It is a pod with Curl Tool already installed. Since there is no volume mounted for this pod, Hey Tool must be installed everytime one enters the pod.

The following command will create the pod and enter it.

```bash
  kubectl run load-test --image=curlimages/curl -i --tty -- sh
  wget https://hey-release.s3.us-east-2.amazonaws.com/hey_linux_amd64
  chmod +x hey_linux_amd64
  mv hey_linux_amd64 hey
```

Generate load from inside the pod with those tools (Curl for a single request, Hey for multiple requests).

```bash
  curl http://service-1.realtime.svc.cluster.local
  ./hey -c 50 -q 100 -z 60s http://service-1.realtime.svc.cluster.local
```
To delete the Pod, exit from it and delete it as a normal pod.

```bash
  exit
  kubectl delete pod load-test
```

### Check Procedure

The followiong commands will help to monitor the entire system we set up.

```bash
  kubectl get ksvc -n realtime -> "for Service Status"
  kubectl get revisions -n realtime -> "for Revision Status"
  kubectl get sks -n realtime -> "for Serverless Service Status"
  kubectl get podautoscaler -n realtime -> "for Scaling Decisions (add "-w" flag during load generation to see scaling decisions in real time)"
  kubectl get pods -A -o wide -> "for Pods in the cluster (add "-w" flag during load generation to see scaling decisions in real time)"
  kubectl logs -n knative-serving -l app=activator -> "for Activator's Logs"
  kubectl logs -n knative-serving -l app=autoscaler -> "for Autoscaler's Logs"
  kubectl logs -n knative-serving -l app=controller -> "for Controller's Logs"
  kubectl get rtresources -n realtime rt-critical-resource -o yaml -> "to see 'replicaCount' field changes"
```

