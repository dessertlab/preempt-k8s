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
    O_RDONLY, SCHED_FIFO, mq_attr, mq_close, mq_open, mq_receive, mq_unlink, mqd_t, pthread_cond_signal, pthread_getschedparam, pthread_mutex_lock, pthread_mutex_unlock, pthread_self, pthread_setschedparam, sched_param
};
use kube::api::ListParams;

use crate::utils::vars::SharedState;
use crate::components::scheduling::create_pod;
use crate::components::scheduling::delete_pod;



pub extern "C" fn watchdog(thread_data: *mut c_void) -> *mut c_void {

    let shared_state = unsafe {&*(thread_data as *mut SharedState)};
    
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
            The message retrieved is the UID of the RTResource
            related to the event and a priority equal
            to the criticality level.
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
            let uid = String::from_utf8(msg.to_vec())
                .unwrap_or_else(|_| String::from("Invalid UTF-8"))
                .trim_matches(char::from(0))
                .to_string();
            
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

            shared_state.runtime.block_on(async {
                /*
                We proceed to acquire the RTResource
                wirh the corresponding UID.
                */
		        match shared_state.context.rt_resources.get(uid.as_str()).await {
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
		        		println!("Watchdog - Resource {} found!", uid.as_str());
                        let pod_lp = kube::api::ListParams::default()
                            .labels(&format!("rtresource_id={}", uid));
                        let pod_list = shared_state.context.pods.list(&pod_lp).await.unwrap();
                        let pod_count = pod_list.items.len() as i32;
                        let desired_pod_count = r.spec.replicas;
                        let mut pods_needed = (desired_pod_count - pod_count as i32).abs();
                        if desired_pod_count > pod_count {
                            for i in 0..difference {
                                create_pod("Watchdog".to_string(), shared_state.context.client, &r).await;
                            }
                        } else if desired_pod_count < pod_count {
                            for i in pod_list.items.iter().take(pods_needed as usize) {
                                delete_pod("Watchdog".to_string(), shared_state.context.client, i.clone()).await;
                            }
                        }
                    }
		        	Err(e) => {
		        		match e.to_string().find("404") {
		        			Some(found) => {
		        				println!("Resource Not Found!");
							let pod_api: Api<Pod> = Api::namespaced(client.clone(), datas.context.namespace.clone().as_str());
							let pod_api_critical: Api<Pod> = Api::namespaced(client.clone(), "critical-resource");
							let pod_api_second: Api<Pod> = Api::namespaced(client.clone(), "second-resource");
							let label_selector = format!("crd_id={}", &message);
							let lp_pod = ListParams {
							    label_selector: Some(label_selector),
							    resource_version: Some("0".to_string()),
							    ..ListParams::default()
							};
							let mut pod_list = match pod_api.list(&lp_pod).await {
								Ok(list) => list,
								Err(_) => kube::api::ObjectList { items: vec![], metadata: kube::api::ListMeta::default() }
							};
							let mut critical_pod_list = match pod_api_critical.list(&lp_pod).await {
								Ok(list) => list,
								Err(_) => kube::api::ObjectList { items: vec![], metadata: kube::api::ListMeta::default() }
							};
							let mut second_pod_list = match pod_api_second.list(&lp_pod).await {
								Ok(list) => list,
								Err(_) => kube::api::ObjectList { items: vec![], metadata: kube::api::ListMeta::default() }
							};
							for i in pod_list.items.iter() {
								delete_pod(client.clone(), &datas.context.namespace, &i.metadata.uid.as_deref().unwrap_or(""), &i.metadata.name.clone().unwrap_or("".to_string())).await;
							}
							for i in critical_pod_list.items.iter() {
								delete_pod(client.clone(), "critical-resource", &i.metadata.uid.as_deref().unwrap_or(""), &i.metadata.name.clone().unwrap_or("".to_string())).await;
							}
							for i in second_pod_list.items.iter() {
								delete_pod(client.clone(), "second-resource", &i.metadata.uid.as_deref().unwrap_or(""), &i.metadata.name.clone().unwrap_or("".to_string())).await;
							}
		        			}
		        			None => {
		        				println!("An error occurred while retrieving Custom Resource List: {}", e);
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