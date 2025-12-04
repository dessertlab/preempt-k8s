/*
This file contains the component in charge
of handling all RTResoirces and relative Pods events
retrieved from the event priority queue.
*/

use std::{
    mem,
    ptr,
    process::exit,
    os::raw::c_char,
    ffi::c_void
};
use libc::{
    sched_param,
    SCHED_FIFO,
    pthread_self,
    pthread_setschedparam,
    pthread_getschedparam,
    mqd_t,
    O_RDONLY,
    mq_attr,
    mq_open,
    mq_unlink,
    mq_close,
    mq_receive,
    pthread_cond_signal,
    pthread_mutex_lock,
    pthread_mutex_unlock
};
use kube::Api;

use crate::utils::vars::SharedState;
use crate::utils::vars::QueueMessage;
use crate::utils::rtresource::RTResource;

use crate::components::scheduling::create_pod;
use crate::components::scheduling::delete_pod;



pub extern "C" fn watchdog(thread_data: *mut c_void) -> *mut c_void {

    let shared_state = unsafe {&mut*(thread_data as *mut SharedState)};
    
    //We open the queue to retrieve the Event to handle
    unsafe {
        /*
        We get a reference to the watchdog itself
        for two main reasons:
            1. to be able to change its scheduling priority
               according to the criticality of the event being handled;
            2. to be able to stop itself if too many watchdogs
               are running when it stops handling an event.
        */
        let thread = pthread_self();

        /*
        We open the priority queue to
        retrieve events published on it.
        */
        let mut queue_attr: mq_attr = { mem::zeroed() };
        queue_attr.mq_flags = 0;
        queue_attr.mq_maxmsg = 500;
        queue_attr.mq_msgsize = 256;
        queue_attr.mq_curmsgs = 0;
        let queue_des: mqd_t = mq_open(
            shared_state.queue.as_ptr() as *const c_char,
            O_RDONLY,
            0664,
            &queue_attr
        );
        if queue_des == -1 {
            eprintln!("Watchdog - An error occurred while opening the queue!");
            exit(-1);
        }
	
        loop {
            /*
            Each time the watchdog start the infinite loop,
            it waits for a new event to handle.
            Once events are available, it will retrieve the
            higher priority one not already collected by
            concurrent watchdogs.
            The message retrieved containe name, UID and
            namespace of the RTResource related to the event
            and a priority equal to the criticality level.
            */
            let mut msg: [u8; 1024] = [0; 1024];
            let mut criticality: u32 = 0;
            let result = mq_receive(
                queue_des,
                msg.as_mut_ptr() as *mut c_char,
                msg.len(),
                &mut criticality as *mut u32
            );
            if result == -1 {
                eprintln!("Watchdog - An error occurred while retrieving a message from the queue!");
                continue;
            }
            let actual_data = &msg[..result as usize];
            let rtresource_data = match QueueMessage::from_bytes(actual_data) {
                Ok(data) => {
                    data
                },
                Err(e) => {
                    eprintln!("Watchdog - An error occurred while deserializing the message from the queue: {}", e);
                    continue;
                }
            };
            println!(
                "Watchdog - Retrieved event for RTResource {}, {} in namespace {}!",
                rtresource_data.name,
                rtresource_data.uid,
                rtresource_data.namespace
            );
            
            /*
            The event server must be aware theat the watchdog
            is now working on an event, so that it can decide
            whether to spawn new watchdogs or not.
            */
            pthread_mutex_lock(&mut shared_state.mutex);
            shared_state.working_threads = shared_state.working_threads + 1;
            pthread_cond_signal(&mut shared_state.cond);
            pthread_mutex_unlock(&mut shared_state.mutex);
            
            /*
            The thread priority is temporarily changed
            according to the criticality of the event being handled.
            */
            let param = sched_param{sched_priority: 94 - criticality as i32};
            pthread_setschedparam(thread, SCHED_FIFO, &param);
            let mut debug_param = sched_param {sched_priority: 0};
            let mut debug_policy = 0;
    	    pthread_getschedparam(thread, &mut debug_policy, &mut debug_param);
    	    println!("Watchdog - Started handling event with priority {}!", debug_param.sched_priority);

            let client = shared_state.context.client.clone();
            let rtresource_api = Api::<RTResource>::namespaced(
                shared_state.context.client.clone(),
                rtresource_data.namespace.as_str()
            );
            let pods_api = shared_state.context.pods.clone();
            let pod_lp = kube::api::ListParams::default()
                .labels(&format!("rtresource_id={}", rtresource_data.uid));
            let rtresource_data_clone = rtresource_data.clone();
            shared_state.runtime.block_on(async {
                /*
                We proceed to acquire the RTResource
                wirh the corresponding UID.
                */
		        match rtresource_api.get(rtresource_data_clone.name.as_str()).await {
		        	/*
                    The next step is to understand wether the RTResource still exists or not.
                    If it doesn't exist, it means that it has been deleted and we have to delete
                    all the pods associated to it that are still running.
                    If it still exists it means that the event that occurred is a change
                    in the desired number of replicas or in the already deployed ones
                    (this includes the case of a RTResource creation).
                    In any of these cases, the actions to take are the the same: first we get a list of all
                    pods associated to the RTResource (all accociated pods have the label rtresource_id
                    equal to the UID of the RTResource) and, then we compare the number of deployed replicas 
                    to the desired one and decide whether to scale up or down.
		        	*/
                    Ok(r) => {
		        		println!(
                            "Watchdog - The RTResource {}, {} in namespace {} was either created/updated or some of its pods were deleted!",
                            rtresource_data_clone.name,
                            rtresource_data_clone.uid,
                            rtresource_data_clone.namespace
                        );

                        /*
                        If the RTResource exists, we must update its status first.
                            1. We set the observed generation to the current one.
                            2. We set the desired replicas to the current spec.replicas
                               (current replicas will be updated by the status updater accordingly).
                            3. We set the conditions accordingly:
                                - Progressing = True
                                - Ready = False
                            4. We update the status in the apiserver.
                        */
                        let mut new_rtresource_status = r.status.clone().unwrap_or_default();

                        new_rtresource_status.observed_generation = r.metadata.generation;

                        new_rtresource_status.desired_replicas = Some(r.spec.replicas);

                        let mut new_rtresource_conditions =  new_rtresource_status.conditions.unwrap_or_default();
                        for cond in &mut new_rtresource_conditions {
                            if cond.condition_type == "Progressing" {
                                cond.status = "True".to_string();
                                cond.reason = Some("RTResource Spec changed!".to_string());
                                cond.message = Some("RTResource Spec changed!!".to_string());
                                cond.last_transition_time = Some(chrono::Utc::now().to_rfc3339());
                            }
                            if cond.condition_type == "Ready" {
                                cond.status = "False".to_string();
                                cond.reason = Some("RTResource Spec changed!!".to_string());
                                cond.message = Some("RTResource Spec changed!!".to_string());
                                cond.last_transition_time = Some(chrono::Utc::now().to_rfc3339());
                            }
                        }
                        new_rtresource_status.conditions = Some(new_rtresource_conditions);

                        let rtresource_status_json = serde_json::to_vec(&new_rtresource_status).unwrap();
                        let rtresource_namespaced_api = Api::<RTResource>::namespaced(
                            client.clone(),
                            r.metadata.namespace.as_ref().unwrap()
                        );
                        match rtresource_namespaced_api.replace_status(
                            &r.metadata.name.as_ref().unwrap(),
                            &Default::default(),
                            rtresource_status_json
                        ).await {
                            Ok(_) => {
                                println!(
                                    "State Updater - Updated status for RTResource: {}, {} in namespace {}",
                                    rtresource_data_clone.name,
                                    rtresource_data_clone.uid,
                                    rtresource_data_clone.namespace
                                );
                            }
                            Err(e) => {
                                eprintln!(
                                    "State Updater - An error occurred while updating status for RTResource {}, {} in namespace {}: {}",
                                    rtresource_data_clone.name,
                                    rtresource_data_clone.uid,
                                    rtresource_data_clone.namespace,
                                    e
                                );
                            }
                        }

                        /*
                        Now we can proceed to scale the number of pods
                        associated to the RTResource according to the desired
                        number of replicas.
                        */
                        let pod_list = pods_api.list(&pod_lp).await.unwrap();
                        let pod_count = pod_list.items.len() as i32;
                        let desired_pod_count = r.spec.replicas;
                        let pods_needed = (desired_pod_count - pod_count as i32).abs();
                        if desired_pod_count > pod_count {
                            for _i in 0..pods_needed {
                                if let Err(e) = create_pod("Watchdog".to_string(), client.clone(), &r).await{
                                    eprintln!("{}", e);
                                }
                            }
                        } else if desired_pod_count < pod_count {
                            for i in pod_list.items.iter().take(pods_needed as usize) {
                                if let Err(e) = delete_pod("Watchdog".to_string(), client.clone(), i.clone()).await{
                                    eprintln!("{}", e);
                                }
                            }
                        }
                    }
		        	Err(e) => {
		        		match e.to_string().find("404") {
		        			Some(_found) => {
		        				println!(
                                    "Watchdog - The RTResource {}, {} in namespace {} was deleted!",
                                    rtresource_data_clone.name,
                                    rtresource_data_clone.uid,
                                    rtresource_data_clone.namespace
                                );

                                /*
                                If the RTResource received from the priority queue was deleted,
                                then we must delete all the pods associated to it.
                                */
                                let pod_list = pods_api.list(&pod_lp).await.unwrap();
                                for i in pod_list.items.iter() {
                                    if let Err(e) = delete_pod("Watchdog".to_string(), client.clone(), i.clone()).await{
                                        eprintln!("{}", e);
                                    }
                                }
                                }
		        			None => {
		        				println!("Watchdog - An error occurred while retrieving Custom Resource List: {}", e);
		        			}
		        		}
		        	}
		        };
            });
	    
	        /*
            Once the event has been handled, the watchdog
            it must return to its original schedling priority,
            which is '94', since it must retrieve new events and
            it must not be slowed down by other watchdogs (this is
            imperative since a new event could have higher priority
            than those being handled).
            */
            let param = sched_param {sched_priority: 94};
            pthread_setschedparam(thread, SCHED_FIFO, &param);
            debug_param = sched_param { sched_priority: 0 };
            debug_policy = 0;
    	    pthread_getschedparam(thread, &mut debug_policy, &mut debug_param);
    	    println!("Watchdog - Returned to base priority {}!", debug_param.sched_priority);
    	    
    	    /*
            The watchdog must now check whether there are too many
            active watchdogs in the system. If so, it must terminate itself
            to free resources.
            In any case, it first notifies the event server that it is no longer
            working on an event.
            */
    	    pthread_mutex_lock(&mut shared_state.mutex);
            shared_state.working_threads = shared_state.working_threads - 1;
            let decision = shared_state.active_threads - shared_state.working_threads;
            if decision > shared_state.config.threshold && shared_state.active_threads > shared_state.config.min_watchdogs {
                break;
            }
            pthread_mutex_unlock(&mut shared_state.mutex);
        }
        
        /*
        Once the Thread decides to terminate,
        it updates the worker array to free its position,
        thus letting the event server know that it stopped.
        */
        let mut i = 0;
        let mut found = false;
        while i < shared_state.config.max_watchdogs && !found {
        	if shared_state.workers[i].id == thread {
                shared_state.workers[i].id = 0;
        		shared_state.workers[i].active = false;
        		found = true;
        		shared_state.active_threads = shared_state.active_threads - 1;
	    		pthread_mutex_unlock(&mut shared_state.mutex);
        	}
        	i = i + 1;
        }
        
        /*
        Cleanup phase.
        */
    	mq_close(queue_des);
        mq_unlink(shared_state.queue.as_ptr());
    }
    
    println!("Watchdog - Too many Watchdogs! Terminating...");

    ptr::null_mut()

}