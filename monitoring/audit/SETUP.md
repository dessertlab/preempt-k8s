# Istruzioni per configurare audit logs nel kube-apiserver

## Step 1: Copiare la policy nel control plane node

# Copia la policy sul master node
scp monitoring/audit/audit-policy.yaml <master-node>:/etc/kubernetes/audit-policy.yaml

# Oppure se hai accesso diretto:
sudo cp monitoring/audit/audit-policy.yaml /etc/kubernetes/audit-policy.yaml

## Step 2: Creare directory per i log

sudo mkdir -p /var/log/kubernetes/audit
sudo chmod 755 /var/log/kubernetes/audit

## Step 3: Modificare il manifest kube-apiserver

# File: /etc/kubernetes/manifests/kube-apiserver.yaml

# Aggiungere questi flag nel campo spec.containers[0].command:
#   - --audit-policy-file=/etc/kubernetes/audit-policy.yaml
#   - --audit-log-path=/var/log/kubernetes/audit/audit.log
#   - --audit-log-format=json
#   - --audit-log-maxage=7
#   - --audit-log-maxbackup=10
#   - --audit-log-maxsize=100

# Aggiungere questi volumeMounts in spec.containers[0].volumeMounts:
#   - name: audit-policy
#     mountPath: /etc/kubernetes/audit-policy.yaml
#     readOnly: true
#   - name: audit-logs
#     mountPath: /var/log/kubernetes/audit
#     readOnly: false

# Aggiungere questi volumes in spec.volumes:
#   - name: audit-policy
#     hostPath:
#       path: /etc/kubernetes/audit-policy.yaml
#       type: File
#   - name: audit-logs
#     hostPath:
#       path: /var/log/kubernetes/audit
#       type: DirectoryOrCreate

## Step 4: Il kube-apiserver si riavvierà automaticamente (static pod)

# Verifica che sia ripartito:
# kubectl get pods -n kube-system | grep kube-apiserver

## Step 5: Verifica che i log vengano scritti:
# sudo tail -f /var/log/kubernetes/audit/audit.log
