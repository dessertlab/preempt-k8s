# Longhorn installation

## On Master and Worker nodes

To install prerequisites run on each node on the cluster:
```bash
sudo apt update
sudo apt install open-iscsi nfs-common -y
sudo systemctl enable --now iscsid
```

The second command will show a promt to select which services to restart.
Press "ENTER" to restart the default ones.

## On Master node

To check that the cluster satisfies all prerequisites:

```bash
sudo apt update && sudo apt install jq -y
curl -sSfL https://raw.githubusercontent.com/longhorn/longhorn/v1.5.3/scripts/environment_check.sh | bash
```

Ignore the *WARNING* on volumes multipath, it should work fine.

To install longhorn:

```bash
kubectl apply -f https://raw.githubusercontent.com/longhorn/longhorn/v1.10.1/deploy/longhorn.yaml
```

Wait for a while untill all longhorn pods are up and running:

```bash
watch kubectl get pods -n longhorn-system
```

## Create a new Volume

Longhorn comes with default storage classes. We add a new one for 
Retain volumes which will never be deleted unless the admin explicitly does so.

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: longhorn-retain
allowVolumeExpansion: true
provisioner: driver.longhorn.io
reclaimPolicy: Retain
volumeBindingMode: Immediate
parameters:
  backupTargetName: default
  dataEngine: v1
  dataLocality: disabled
  disableRevisionCounter: "true"
  fromBackup: ""
  fsType: "ext4"
  numberOfReplicas: "3"
  staleReplicaTimeout: "30"
  unmapMarkSnapChainRemoved: ignored
```

A Retain volume will still exist even with no pods mounting it.

To create a new volume, connect first to the dashboard:

```bash
kubectl port-forward svc/longhorn-frontend -n longhorn-system 8080:80
```

Once the service is forwarded on your local machine, see this link: http://localhost:8080/ .

Once you are connected, create a new volume from the GUI to let 
longhron know of the volume.

The parameters set in the GUI must match the your pv k8s manifest:

```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: experiments-results
spec:
  volumeMode: Filesystem
  accessModes:
    - ReadWriteMany
  storageClassName: longhorn-retain
  capacity:
    storage: 10Gi
  persistentVolumeReclaimPolicy: Retain
  csi:
    driver: driver.longhorn.io
    volumeAttributes:
      numberOfReplicas: "3"
    volumeHandle: experiments-results
```

**N.B.** The "volumeHandle" field must match the name given to the volume 
in the longhorn dashboard so that it knows which volume to handle.

**N.B** The "ReadWriteMany" option is mandatory to mount the volume on 
different pods and different nodes at the same time.

Now you must actually create the volume in the cluster by 
applying the previous manifest:

```bash
kubectl apply -f <path-to-pv-yaml-file>
```

Now the volume is deployed. We can create a volume claim that 
pods will use to mount the deployed volume.

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: experiments-results
  namespace: default
spec:
  accessModes:
    - ReadWriteMany
  storageClassName: longhorn-retain
  volumeName: experiments-results
  resources:
    requests:
      storage: 10Gi
```

```bash
kubectl apply -f <path-to-pvc-yaml-file>
```

**N.B**. Claims are namespaced resources unlike the volumes they refer to.
Change the namespace and re-apply the pvc if you need to mount the volume on pods in 
another namespace.

**N.B.** The "volumeName" field in the pvc manifest is used to refer to the volume created. 
If not set, Kubernetes will create a new different volume.

**N.B** The "ReadWriteMany" option is mandatory to mount the volume on 
different pods and different nodes at the same time.

## Throubleshooting

For better information on longhorn installation and usage, please refer to 
the official documentation: https://longhorn.io/docs/1.10.1/what-is-longhorn/ .
