package rtscaler

import (
    metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
    "k8s.io/apimachinery/pkg/runtime"
)

type RTResource struct {
    metav1.TypeMeta   `json:",inline"`
    metav1.ObjectMeta `json:"metadata,omitempty"`
    Spec             RTResourceSpec `json:"spec"`
}

type RTResourceSpec struct {
    Namespace    string `json:"namespace"`
    ReplicaCount int32  `json:"replicaCount"`
    CPU         string `json:"cpu"`
    Memory      string `json:"memory"`
    Criticality int    `json:"criticality"`
    Image       string `json:"image"`
}

func (r *RTResource) DeepCopyObject() runtime.Object {
    if r == nil {
        return nil
    }
    
    copy := &RTResource{
        TypeMeta: r.TypeMeta,
        ObjectMeta: r.ObjectMeta,
        Spec: RTResourceSpec{
            Namespace:    r.Spec.Namespace,
            ReplicaCount: r.Spec.ReplicaCount,
            CPU:         r.Spec.CPU,
            Memory:      r.Spec.Memory,
            Criticality: r.Spec.Criticality,
            Image:       r.Spec.Image,
        },
    }
    return copy
}
