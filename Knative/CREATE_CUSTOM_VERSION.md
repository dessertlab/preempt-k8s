
# New Version Creation Tutorial

This file will help to modify the Knative Serving source code.

The root directory is "serving"

## Files To Add

In "serving/pkg" create directory "rtscaler"
Enter above directory and add the 3 following files ("serving/pkg/rtscaler")

- client.go -> "serving/pkg/rtscaler/client.go"
- scaler.go -> "serving/pkg/rtscaler/scaler.go"
- types.go -> "serving/pkg/rtscaler/types.go"

## Files To Modify

- main.go in "serving/cmd/autoscaler" -> "serving/cmd/autoscaler/main.go"
- controller.go in "serving/pkg/reconciler/autoscaling/kpa" -> "serving/pkg/reconciler/autoscaling/kpa/controller.go"
- kpa.go in "serving/pkg/reconciler/autoscaling/kpa" -> "serving/pkg/reconciler/autoscaling/kpa/kpa.go"
- deploy.go in "serving/pkg/reconciler/revision/resources" -> "serving/pkg/reconciler/revision/resources/deploy.go"
- serverlessservice.go in "serving/pkg/reconciler/serverlessservice" -> "serving/pkg/reconciler/serverlessservice/serverlessservice.go"
