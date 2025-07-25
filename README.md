
# Preempt-K8s

This project aims at implementing the first step towards a co-orchestrator Kubernetes architecture. We developed a Controller dedicated to a new kind of Custom Resource that brings with it the concept of criticality level.
For the moment, this is just an additional component in the classic Kubernetes Vanilla Version.
The Controller and the CRD allow to replicate the Deployment and ReplicaSet Control Loop and Deployment lifecycle in a Real Time fashion using Rust code allowing full control over Event handling Threads and their scheduling priority.

## Requirements

- A Kubernetes Cluster with Kubernetes Version 1.29.0
- Cargo tool
- Kubectl command line tool
- Docker
- Python3
- vim tool

## Repository Overview

The preempt-k8s main branch contains:
- CRD_Controller, which is the directory related to the Controller project with its manifests and main resources.

Check for more detailed README files to understand each part of the project.

## Build and Installation

Clone this repository in the work environment and build the Controller.

```bash
  cd <work-dir>/preempt-k8s/CRD_Controller/
  cargo build --release
  sudo docker build -t <path-to-your-docker-image> .
  sudo docker push <path-to-your-docker-image>
```

You now need to modify the Controller Manifest by changing the image field to your "path-to-your-docker-image¨.

```bash
  cd <work-dir>/preempt-k8s/CRD_Controller/src/Resources/
  vim controller.yaml
```
Now use the manifests in this directory to deploy the CRD Object and the Controller.

```bash
  kubectl create namespace realtime
  kubectl apply -f ./auth/role.yaml
  kubectl apply -f ./auth/binding.yaml
  kubectl apply -f crd.yaml
  kubectl apply -f controller.yaml
```
Verify that the namespace is created, the CRD is installed and the Controller is running.

```bash
  kubectl get crd
  kubectl get namespaces
  kubectl get pod -n realtime rt-controller
```
Now use the resource already given and execute the followiong commands to verify everything is working properly.

First change the the 'replicaCount' field to '1'.

```bash
  vim resource.yaml
```

Now create the resource, you should see a Pod related to that resource appear.

```bash
  kubectl apply -f resource.yaml
  kubectl get pods -n realtime
```
Change the 'replicaCount' to other values and use the above commands to verify the Controller scales accordingly.

After that, delete the resource and verify the Controller deletes all Pods related to that resource.

```bash
  kubectl delete -f resource.yaml
  kubectl get pods -n realtime
```
Now the Controller is ready to be used.


To uninstall everything use the following commands.

```bash
  kubectl delete -f controller.yaml
  kubectl delete -f crd.yaml
  kubectl delete -f ./auth/role.yaml
  kubectl delete -f ./auth/binding.yaml
  kubectl delete namespace realtime
```
Then, verify the uninstall.

```bash
  kubectl get pods -A -o wide
  kubectl get crd
  kubectl get namespaces

