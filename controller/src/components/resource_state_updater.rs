/*
This file contains the component in charge
of updating the state of RTResources based on
the state  of managed Pods.
*/

use std::{
    ptr,
    ffi::c_void
};
use kube::Api;

use crate::utils::vars::SharedState;
use crate::utils::rtresource::RTResource;




pub extern "C" fn resource_state_updater(thread_data: *mut c_void) -> *mut c_void {
    let shared_state = unsafe {&*(thread_data as *mut SharedState)};

    shared_state.runtime.block_on(async {
        let mut error_count: usize = 0;
        let lp = kube::api::ListParams::default();
        'outer: loop {
            match shared_state.context.rt_resources.list(&lp).await {
                /*
                We must first obtain a list of all RTResources
                currently managed by the controller and, thus, deployed in the cluster.
                We sort them by criticality to process the most critical ones first.
                */
                Ok(list) => {
                    let mut items = list.items;
                    items.sort_by_key(|r| r.spec.criticality);
                    for r in items {
                        if let Some(conditions) = r.status.as_ref().and_then(|s| s.conditions.as_ref()) {
                            let is_progressing = conditions.iter().any(|c| c.condition_type == "Progressing" && c.status == "True");
                            if is_progressing {
                                let uid = r.metadata.uid.as_ref().unwrap();
                                let desired_replicas = r.status.as_ref().and_then(|s| s.desired_replicas).unwrap_or(0);

                                /*
                                1. We list the pods belonging to this RTResource
                                identified by the label rtresource_id=uid.
                                */
                                let pod_lp = kube::api::ListParams::default()
                                    .labels(&format!("rtresource_id={}", uid));
                                let pods = match shared_state.context.pods.list(&pod_lp).await {
                                    Ok(pod_list) => pod_list.items,
                                    Err(e) => {
                                        eprintln!("State Updater - Error listing pods for RTResource {}: {}", uid, e);
                                        continue;
                                    }
                                };

                                /*
                                2. We count the number of pods in Running state.
                                */
                                let running_count = pods.iter().filter(|p| {
                                    if let Some(status) = &p.status {
                                        status.phase.as_deref() == Some("Running")
                                    } else {
                                        false
                                    }
                                }).count() as i32;

                                /*
                                3. We update the RTResource status with the
                                current number of running replicas and update
                                the conditions accordingly.
                                If the number of running replicas matches the desired one,
                                we set the "Progressing" to 'False' and "Ready" to 'True',
                                then we update running replicas status field.
                                Otherwise, we only update the replicas count.
                                */
                                let mut new_status = r.status.clone().unwrap_or_default();
                                
                                new_status.replicas = Some(running_count);

                                let mut new_conditions = new_status.conditions.unwrap_or_default();
                                if running_count == desired_replicas {
                                    for cond in &mut new_conditions {
                                        if cond.condition_type == "Progressing" {
                                            cond.status = "False".to_string();
                                            cond.reason = Some("All desired replicas are running!".to_string());
                                            cond.message = Some("All desired replicas are running!".to_string());
                                            cond.last_transition_time = Some(chrono::Utc::now().to_rfc3339());
                                        }
                                        if cond.condition_type == "Ready" {
                                            cond.status = "True".to_string();
                                            cond.reason = Some("All desired replicas are running!".to_string());
                                            cond.message = Some("All desired replicas are running!".to_string());
                                            cond.last_transition_time = Some(chrono::Utc::now().to_rfc3339());
                                        }
                                    }
                                }

                                new_status.conditions = Some(new_conditions);

                                /*
                                4. We push the status update to the Kubernetes API
                                server for the RTResource.
                                */
                                let status_json = serde_json::to_vec(&new_status).unwrap();
                                let rtresource_namespaced_api = Api::<RTResource>::namespaced(
                                    shared_state.context.client.clone(),
                                    r.metadata.namespace.as_ref().unwrap()
                                );
                                match rtresource_namespaced_api.replace_status(
                                    &r.metadata.name.as_ref().unwrap(),
                                    &Default::default(),
                                    status_json
                                ).await {
                                    Ok(_) => {
                                        println!("State Updater - Updated status for RTResource {}: replicas={}, desired={}", uid, running_count, desired_replicas);
                                    }
                                    Err(e) => {
                                        eprintln!("State Updater - An error occurred while updating status for RTResource {}: {}", uid, e);
                                    }
                                }
                            }
                        }
                    }
                }
                Err(e) => {
                    eprintln!("State Updater - An error occurred while listing RTResources: {}", e);
                    error_count = error_count + 1;
                    if error_count >= 10 {
                        eprintln!("State Updater - Too many errors occurred while listing RTResources! Exiting...");
                        break 'outer;
                    }
                }
            }
        }
    });
    
    println!("State Updater - Something went wrong, no new RTResource updates will be processed! Restart the controller to recover!");

    ptr::null_mut()
}
