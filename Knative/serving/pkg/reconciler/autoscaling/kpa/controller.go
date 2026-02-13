/*
Copyright 2019 The Knative Authors

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package kpa

import (
	"context"

	"k8s.io/client-go/tools/cache"

	networkingclient "knative.dev/networking/pkg/client/injection/client"
	sksinformer "knative.dev/networking/pkg/client/injection/informers/networking/v1alpha1/serverlessservice"
	filteredpodinformer "knative.dev/pkg/client/injection/kube/informers/core/v1/pod/filtered"
	servingclient "knative.dev/serving/pkg/client/injection/client"
	//"knative.dev/serving/pkg/client/injection/ducks/autoscaling/v1alpha1/podscalable" //Not needed anymore
	metricinformer "knative.dev/serving/pkg/client/injection/informers/autoscaling/v1alpha1/metric"
	painformer "knative.dev/serving/pkg/client/injection/informers/autoscaling/v1alpha1/podautoscaler"
	pareconciler "knative.dev/serving/pkg/client/injection/reconciler/autoscaling/v1alpha1/podautoscaler"

	"knative.dev/pkg/configmap"
	"knative.dev/pkg/controller"
	"knative.dev/pkg/logging"
	pkgreconciler "knative.dev/pkg/reconciler"
	"knative.dev/serving/pkg/apis/autoscaling"
	autoscalingv1alpha1 "knative.dev/serving/pkg/apis/autoscaling/v1alpha1"
	"knative.dev/serving/pkg/apis/serving"
	"knative.dev/serving/pkg/autoscaler/config/autoscalerconfig"
	"knative.dev/serving/pkg/deployment"
	areconciler "knative.dev/serving/pkg/reconciler/autoscaling"
	"knative.dev/serving/pkg/reconciler/autoscaling/config"
	"knative.dev/serving/pkg/reconciler/autoscaling/kpa/resources"
	
	//RTResource imports
	"k8s.io/client-go/rest"
    	"knative.dev/serving/pkg/rtscaler"
)

// NewController returns a new KPA reconcile controller.
// TODO(mattmoor): Fix the signature to adhere to the injection type.
func NewController(
	ctx context.Context,
	cmw configmap.Watcher,
	deciders resources.Deciders,
) *controller.Impl {
	logger := logging.FromContext(ctx)
	paInformer := painformer.Get(ctx)
	sksInformer := sksinformer.Get(ctx)
	//podsInformer := filteredpodinformer.Get(ctx, serving.RevisionUID) ////We don't look for pods by Revision UID
	podsInformer := filteredpodinformer.Get(ctx, serving.RevisionLabelKey) //We look for pods by Revision Name
	metricInformer := metricinformer.Get(ctx)
	//psInformerFactory := podscalable.Get(ctx) //Not needed anymore

	onlyKPAClass := pkgreconciler.AnnotationFilterFunc(
		autoscaling.ClassAnnotationKey, autoscaling.KPA, false /*allowUnset*/)
	
	//RTResource Client configuration
	restConfig, err := rest.InClusterConfig()
	if err != nil {
		logger.Fatalf("Failed to get cluster config: %v", err)
	}
	rtClient, err := rtscaler.NewRTResourceClient(restConfig)
	if err != nil {
		logger.Fatalf("Failed to create RTResource client: %v", err)
	}

	c := &Reconciler{
		Base: &areconciler.Base{
			Client:           servingclient.Get(ctx),
			NetworkingClient: networkingclient.Get(ctx),
			SKSLister:        sksInformer.Lister(),
			MetricLister:     metricInformer.Lister(),
		},
		podsLister: podsInformer.Lister(),
		deciders:   deciders,
		scaler:     rtscaler.NewRTScaler(rtClient), //This replace newScaler with our RTScaler
	}
	impl := pareconciler.NewImpl(ctx, c, autoscaling.KPA, func(impl *controller.Impl) controller.Options {
		logger.Info("Setting up ConfigMap receivers")
		configsToResync := []interface{}{
			&autoscalerconfig.Config{},
			&deployment.Config{},
		}
		resync := configmap.TypeFilter(configsToResync...)(func(string, interface{}) {
			impl.FilteredGlobalResync(onlyKPAClass, paInformer.Informer())
		})
		configStore := config.NewStore(logger.Named("config-store"), resync)
		configStore.WatchConfigs(cmw)
		return controller.Options{ConfigStore: configStore}
	})
	//This line was removed since we're using RTScaler directly
	//c.scaler = newScaler(ctx, psInformerFactory, impl.EnqueueAfter)

	logger.Info("Setting up KPA-Class event handlers")

	paInformer.Informer().AddEventHandler(cache.FilteringResourceEventHandler{
		FilterFunc: onlyKPAClass,
		Handler:    controller.HandleAll(impl.Enqueue),
	})

	onlyPAControlled := controller.FilterController(&autoscalingv1alpha1.PodAutoscaler{})
	handleMatchingControllers := cache.FilteringResourceEventHandler{
		FilterFunc: pkgreconciler.ChainFilterFuncs(onlyKPAClass, onlyPAControlled),
		Handler:    controller.HandleAll(impl.EnqueueControllerOf),
	}
	sksInformer.Informer().AddEventHandler(handleMatchingControllers)
	metricInformer.Informer().AddEventHandler(handleMatchingControllers)

	// Watch the knative pods.
	podsInformer.Informer().AddEventHandler(cache.FilteringResourceEventHandler{
		FilterFunc: pkgreconciler.LabelExistsFilterFunc(serving.RevisionLabelKey),
		Handler:    controller.HandleAll(impl.EnqueueLabelOfNamespaceScopedResource("", serving.RevisionLabelKey)),
	})

	// Have the Deciders enqueue the PAs whose decisions have changed.
	deciders.Watch(impl.EnqueueKey)

	return impl
}
