# Monitoring Infrastructure Deployment

## Helm Installation

Each of the **monitoring services** needed is installed through the **helm tool**. Use the following bash commands:

```bash
kubectl create namespace observability
helm install <service-name> <path-to-helm-chart> -n observability --values <path-to-additional-values>
```

The additional **value file** is passed through the *--values* flag overwrites some default **values**. Take a look on the provided *.yaml* files given with **helm chart** for each service to customize and verify it fits your necessities.

Please refer to the official services' documantations for further information:

- **Open-Telemetry**: <https://opentelemetry.io/docs/>

- **Loki**: <https://grafana.com/oss/loki/>

- **Zipkin**: <https://zipkin.io/>

- **Grafana**: <https://grafana.com/docs/>

## List of Monitoring Services

The monitoring infrastructure requires the following services:

- **OpenTelemetry Collector**: the *otel-collector* is deployed in the cluster as a *K8s Deployment* to collect data, logs and traces from sources and sends them to the other monitoring services;

- **Loki**: receives logs from the *otel-collector* and can be queried from scripts and **Grafana**;

- **Zipkin**: receives traces from the *otel-collector* and can be queried from scripts while offering a GUI to visualize collected traces.

- **Grafana**: a GUI from where to query Loki logs.

**Note**: Check the **Grafana** official docs to set **Loki** as datasource; it could be useful to rely on **Loki IP address** instead of **DNS resolution**.

## Kubernetes Customization

To properly enable log and trace production follow the tutorial in [AUDITING.md](./audit/AUDITING.md) and [TRACING.md](./tracing/TRACING.md).
