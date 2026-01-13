# Kubernetes Tracing

## Introduction

Kubernetes **tracing** features allow to follow the request path a cluster when a user or a software, whether it is a K8s internal or an hosted or external application, interacts with the Kube-apiserver or Kube-etcd. A **trace** is useful to track the overall path from source to destination and back.

The tracing features deliver data with **nanosecond precision**, even though we only leveraged the **miliiisecond precision**.

**Note**: the tracing feature does not grant any information on the **payload** of the requests collected, only highlighting the **entities** involved and the **metadata** necessary to identify the **resources** affected by these requests

For further information, please refer to the K8s official documentation: <https://kubernetes.io/blog/2021/09/03/api-server-tracing/>

## Enable Kubernetes Tracing

Follow the following steps to enable the trcing feature in your cluster for both the Kue-apiserver and Kube-etcd, assuming the Kube-apiserver is deployed as a **static pod**.

### Tracing Configuration

We must first create the **tracing configuration**.

Create a ***tracing-config.yaml*** file as follows:

```yaml
apiVersion: apiserver.config.k8s.io/v1beta1
kind: TracingConfiguration
endpoint: <opentelemetry-collector-k8s-service-IP>:4317
samplingRatePerMillion: 1000000
```

The *endpoint* must point to the the **OpenTelemetry Collector service** deployed in the cluster. You can try to rely on **DNS resolution**, but, in case it should fail at this level, insert the **K8s service IP address**.

The *samplingRatePerMillion* is set to *100%*.

Copy this file in your control plane. The usual path would be the following:

```bash
/etc/kubernetes/tracing-config.yaml
```

### Kube-etcd Deployment

Now modify your Kube-etcd manifest, usually in:

```bash
/etc/kubernetes/manifests/etcd.yaml
```

Add the following command flags:

```yaml
- command:
    <...existing flags>
    - --experimental-enable-distributed-tracing=true
    - --experimental-distributed-tracing-address=<opentelemetry-collector-k8s-service-IP>:4317
    - --experimental-distributed-tracing-service-name=etcd
    - --experimental-distributed-tracing-instance-id=$(hostname)
```

At this level, rely on **IP addresses** and not **DNS resolution**.

Now save the file and the configuration will automatically apply.

### Kube-apiserver Deployment

Now modify your kube-apiserver manifest, usually in:

```bash
/etc/kubernetes/manifests/kube-apiserver.yaml
```

Add the following command flags:

```yaml
- command:
    <...existing flags>
    - --feature-gates=APIServerTracing=true
    - --tracing-config-file=<path-to-your-tracing-config-file>
    - --v=6
```

Add the following volume mounts:

```yaml
- volumeMounts:
    <...existing volume mounts>
    - name: tracing-config
      mountPath: <path-to-your-tracing-config-file>
      readOnly: true
```

Add the following volumes:

```yaml
- volumes:
    <...existing volumes>
    - name: tracing-config
      hostPath:
        path: <path-to-your-tracing-config-file>
        type: File
```

Save the new configuration and the Kube-apiserver should restart itself.
