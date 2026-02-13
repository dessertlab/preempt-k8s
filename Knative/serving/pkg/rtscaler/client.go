package rtscaler

import (
    "context"
    "k8s.io/client-go/rest"
    "k8s.io/apimachinery/pkg/runtime/schema"
    "k8s.io/client-go/kubernetes/scheme"
)

var RTResourceGV = schema.GroupVersion{
    Group:   "rtgroup.critical.com",
    Version: "v1",
}

type RTResourceClient interface {
    Create(ctx context.Context, rt *RTResource) error
    Update(ctx context.Context, rt *RTResource) error
    Get(ctx context.Context, name, namespace string) (*RTResource, error)
    CreateOrUpdate(ctx context.Context, rt *RTResource) error
}

type rtResourceClient struct {
    restClient rest.Interface
}

func NewRTResourceClient(config *rest.Config) (RTResourceClient, error) {
    config.GroupVersion = &RTResourceGV
    config.APIPath = "/apis"
    config.NegotiatedSerializer = scheme.Codecs.WithoutConversion()
    
    restClient, err := rest.RESTClientFor(config)
    if err != nil {
        return nil, err
    }
    return &rtResourceClient{restClient: restClient}, nil
}

func (c *rtResourceClient) Create(ctx context.Context, rt *RTResource) error {
    result := &RTResource{}
    err := c.restClient.Post().
        Namespace(rt.Namespace).
        Resource("rtresources").
        Body(rt).
        Do(ctx).
        Into(result)
    return err
}

func (c *rtResourceClient) Update(ctx context.Context, rt *RTResource) error {
    result := &RTResource{}
    err := c.restClient.Put().
        Namespace(rt.Namespace).
        Resource("rtresources").
        Name(rt.Name).
        Body(rt).
        Do(ctx).
        Into(result)
    return err
}

func (c *rtResourceClient) Get(ctx context.Context, name, namespace string) (*RTResource, error) {
    result := &RTResource{}
    err := c.restClient.Get().
        Namespace(namespace).
        Resource("rtresources").
        Name(name).
        Do(ctx).
        Into(result)
    return result, err
}

func (c *rtResourceClient) CreateOrUpdate(ctx context.Context, rt *RTResource) error {
    existing, err := c.Get(ctx, rt.Name, rt.Namespace)
    if err == nil {
        rt.ResourceVersion = existing.ResourceVersion
        rt.Spec.CPU = existing.Spec.CPU
        rt.Spec.Memory = existing.Spec.Memory
        rt.Spec.Image = existing.Spec.Image
        rt.Spec.Criticality = existing.Spec.Criticality
        rt.Spec.Namespace = existing.Spec.Namespace
        return c.Update(ctx, rt)
    }
    return c.Create(ctx, rt)
}

