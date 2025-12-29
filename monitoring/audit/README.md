# Guida completa: Setup Audit Logs con OpenTelemetry

## Panoramica
Questa configurazione abilita audit logs su Kubernetes con precisione al microsecondo per tracciare:
- Modifiche a RTResources
- Modifiche a Deployments/ReplicaSets
- Creazione/modifica/cancellazione di Pod
- Identificare quale controller (RT vs vanilla) agisce

## Fase 1: Configurare l'API Server

### 1.1 Copiare la policy sul control plane node
```bash
# Identifica il control plane node
kubectl get nodes -l node-role.kubernetes.io/control-plane

# Copia la policy (sostituisci <CONTROL_PLANE_NODE>)
scp monitoring/audit/audit-policy.yaml <CONTROL_PLANE_NODE>:/etc/kubernetes/audit-policy.yaml

# Oppure se hai accesso SSH diretto al nodo:
ssh <CONTROL_PLANE_NODE>
sudo cp /path/to/audit-policy.yaml /etc/kubernetes/audit-policy.yaml
```

### 1.2 Creare directory per i log
```bash
ssh <CONTROL_PLANE_NODE>
sudo mkdir -p /var/log/kubernetes/audit
sudo chmod 755 /var/log/kubernetes/audit
```

### 1.3 Modificare il manifest kube-apiserver
```bash
ssh <CONTROL_PLANE_NODE>
sudo nano /etc/kubernetes/manifests/kube-apiserver.yaml
```

Aggiungi queste sezioni (vedi kube-apiserver-example.yaml per l'esempio completo):

**Command flags:**
```yaml
- --audit-policy-file=/etc/kubernetes/audit-policy.yaml
- --audit-log-path=/var/log/kubernetes/audit/audit.log
- --audit-log-format=json
- --audit-log-maxage=7
- --audit-log-maxbackup=10
- --audit-log-maxsize=100
```

**Volume mounts:**
```yaml
- name: audit-policy
  mountPath: /etc/kubernetes/audit-policy.yaml
  readOnly: true
- name: audit-logs
  mountPath: /var/log/kubernetes/audit
  readOnly: false
```

**Volumes:**
```yaml
- name: audit-policy
  hostPath:
    path: /etc/kubernetes/audit-policy.yaml
    type: File
- name: audit-logs
  hostPath:
    path: /var/log/kubernetes/audit
    type: DirectoryOrCreate
```

### 1.4 Verifica riavvio API server
```bash
# L'API server si riavvierà automaticamente (static pod)
kubectl get pods -n kube-system | grep kube-apiserver

# Verifica che i log vengano scritti
ssh <CONTROL_PLANE_NODE>
sudo tail -f /var/log/kubernetes/audit/audit.log
```

## Fase 2: Deploy OpenTelemetry Collector

### 2.1 Merge delle configurazioni
Devi combinare otel-collector-deployment.yaml con otel-collector-audit-values.yaml:

```bash
helm upgrade --install otel-collector ./monitoring/open-telemetry/opentelemetry-collector \
  -f monitoring/open-telemetry/otel-collector-deployment.yaml \
  -f monitoring/open-telemetry/otel-collector-audit-values.yaml \
  --namespace observability --create-namespace
```

### 2.2 Verifica il deployment
```bash
# Verifica che il collector giri sul control plane
kubectl get pods -n observability -o wide | grep otel-collector

# Verifica i log del collector
kubectl logs -n observability -l app.kubernetes.io/name=opentelemetry-collector -f
```

## Fase 3: Testare la raccolta

### 3.1 Crea una RTResource
```bash
kubectl apply -f helm/templates/managed/RTResource.yaml
```

### 3.2 Verifica negli audit logs
```bash
# Cerca nell'audit log
ssh <CONTROL_PLANE_NODE>
sudo grep "rtresources" /var/log/kubernetes/audit/audit.log | jq .

# Oppure nei log del collector
kubectl logs -n observability -l app.kubernetes.io/name=opentelemetry-collector | grep rtresources
```

### 3.3 Cosa cercare
Dovresti vedere:
- `requestReceivedTimestamp` con precisione microsecondo
- `verb`: "create", "patch", "update"
- `objectRef.resource`: "rtresources"
- `user.username`: chi ha fatto la richiesta
- `requestObject`: payload completo della richiesta
- `responseObject`: risposta (se RequestResponse level)

## Fase 4: Analisi performance

### Esempio query per calcolare latenze:
```bash
# Estrai timestamp di modifica RTResource
cat audit.log | jq 'select(.objectRef.resource == "rtresources" and .verb == "patch") | 
  {time: .requestReceivedTimestamp, name: .objectRef.name, user: .user.username}'

# Estrai timestamp di creazione Pod dal tuo controller
cat audit.log | jq 'select(.objectRef.resource == "pods" and .verb == "create" and 
  (.user.username | contains("rt-controller"))) | 
  {time: .requestReceivedTimestamp, pod: .objectRef.name}'

# Calcola latenza end-to-end (richiede script Python/Go per parsing timestamp)
```

## Troubleshooting

### API server non si riavvia
```bash
# Controlla i log del kubelet
ssh <CONTROL_PLANE_NODE>
sudo journalctl -u kubelet -f
```

### Collector non legge i file
```bash
# Verifica permessi
ssh <CONTROL_PLANE_NODE>
ls -la /var/log/kubernetes/audit/

# Verifica che il collector abbia il volume mount
kubectl describe pod -n observability <otel-collector-pod>
```

### Volume troppo alto
Modifica audit-policy.yaml per:
- Ridurre namespace monitorati
- Usare Metadata invece di RequestResponse per alcune risorse
- Escludere più verbs (get, list, watch)

## Export per analisi

### Export a file locale
```bash
kubectl logs -n observability <otel-collector-pod> > audit-events.json
```

### Per produzione: usa exporter Loki o Elasticsearch
Modifica otel-collector-deployment.yaml:
```yaml
exporters:
  loki:
    endpoint: http://loki:3100/loki/api/v1/push
```
