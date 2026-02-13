package rtscaler

import (
    "context"
    pav1alpha1 "knative.dev/serving/pkg/apis/autoscaling/v1alpha1"
    metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
    "knative.dev/pkg/logging"
    "knative.dev/serving/pkg/apis/serving"
)

type RTScaler struct {
    rtClient RTResourceClient
}

func NewRTScaler(client RTResourceClient) *RTScaler {
    return &RTScaler{
        rtClient: client,
    }
}

type paClient interface {
    Get(ctx context.Context, name string, options metav1.GetOptions) (*pav1alpha1.PodAutoscaler, error)
    UpdateStatus(ctx context.Context, pa *pav1alpha1.PodAutoscaler, options metav1.UpdateOptions) (*pav1alpha1.PodAutoscaler, error)
}

func (s *RTScaler) Scale(ctx context.Context, pa *pav1alpha1.PodAutoscaler, desiredScale int32) int32 {
    //During certain periods of initialization, Knative sets desiredScale to -1 which is not an accettable value from CRD Controller
    if desiredScale == -1 {
    	return desiredScale
    }

    rt := &RTResource{
        TypeMeta: metav1.TypeMeta{
            Kind:       "RTResource",
            APIVersion: "rtgroup.critical.com/v1",
        },
        ObjectMeta: metav1.ObjectMeta{
            Name:      pa.Labels[serving.ServiceLabelKey],
            Namespace: pa.Namespace,
        },
        Spec: RTResourceSpec{
            ReplicaCount: desiredScale,
        },
    }
    
    err := s.rtClient.CreateOrUpdate(ctx, rt)
    if err != nil {
        logger := logging.FromContext(ctx)
        logger.Infof("RTResource %s/%s scaling to %d failed: %v", rt.Namespace, rt.Name, desiredScale, err)
    }
    
    return desiredScale
}
