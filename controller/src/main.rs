/*
This file contains the Preempt-K8s controller entrypoint.
It creates the necessary threads and tools 
to create the controller pipeline.
*/

use std::{
    mem,
    ptr,
    error::Error,
    collections::BTreeMap,
    ffi::c_void,
    time::{
        SystemTime,
        UNIX_EPOCH
    }
};
use libc::{
    pthread_t,
    pthread_create,
    pthread_join,
    pthread_self,
    pthread_attr_t,
    pthread_attr_init,
    pthread_attr_setschedpolicy,
    pthread_attr_setschedparam,
    pthread_attr_setinheritsched,
    pthread_attr_destroy,
    sched_param,
    SCHED_FIFO,
    PTHREAD_PRIO_INHERIT,
    PTHREAD_EXPLICIT_SCHED,
    pthread_setschedparam,
    pthread_getschedparam,
    pthread_cond_t,
    pthread_cond_init,
    pthread_cond_signal,
    pthread_cond_destroy,
    pthread_mutex_t,
    pthread_mutex_init,
    pthread_mutex_lock,
    pthread_mutex_unlock,
    pthread_mutex_destroy,
    pthread_mutexattr_t,
    pthread_mutexattr_init,
    pthread_mutexattr_setprotocol,
    pthread_mutexattr_destroy
};
use kube::{
    Client,
    Api,
    api::{
        PostParams,
        ListParams,
        DeleteParams
    }
};
use k8s_openapi::{
    apimachinery::pkg::api::resource::Quantity,
    api::core::v1::{
        Pod,
        PodSpec,
        Container,
        ResourceRequirements
    }
};
use anyhow::Result;

mod utils;
use utils::configuration::get_controller_configuration;
use utils::vars::new_shared_state;

mod components;
use components::resource_watcher::crd_watcher;
use components::pod_watcher::pod_watcher;
use components::event_server::server;



#[tokio::main]
async fn main() -> Result<(), Box<dyn Error + Send + Sync + 'static>> {
    unsafe {

        /*
        We must first retrieve the controller configuration.
        */
        let config = get_controller_configuration();
        println!("{}", config);

        /*
        We create a mutex and a condition variable
        to access the shared state.
        */
        let mut mutex: pthread_mutex_t = mem::zeroed();
        let mut mutex_attr: pthread_mutexattr_t = mem::zeroed();
        pthread_mutexattr_init(&mut mutex_attr as *mut _);
        pthread_mutexattr_setprotocol(&mut mutex_attr as *mut _, PTHREAD_PRIO_INHERIT);
        pthread_mutex_init(&mut mutex as *mut _, &mutex_attr);
        let mut cond: pthread_cond_t = mem::zeroed();
        pthread_cond_init(&mut cond as *mut _, ptr::null());

        /*
        We create the client to interact with
        the Kubernetes API Server.
        */
        let client = Client::try_default().await?;

        /*
        We must now create the shared state used by the controller threads
        using the information gathered up to this point.
        */
        let shared_state = new_shared_state(
            config.clone(),
            client.clone(),
            cond,
            mutex,
            config.event_queue_path.as_str(),
            config.max_watchdogs
        );

        /*
        We must now create all the threads needed
        for the controller pipeline, in order:
            - a watcher that monitors RTResources events;
            - a pod event watcher that monitors pod deletions
              for pods related to the RTResources;
            - a server in charge of spwning new watchdogs when needed.
        Note: a watchdog is a thread that handles events from the event queue.
        */
        let mut crd_watcher_thread: pthread_t = 0;
        let mut pod_watcher_thread: pthread_t = 0;
        let mut server_thread: pthread_t = 0;
        let mut attr: pthread_attr_t = mem::zeroed();
        let mut param: sched_param = sched_param{sched_priority: 0};
        let mut result: i32;
        pthread_attr_init(&mut attr);
        pthread_attr_setschedpolicy(&mut attr, SCHED_FIFO);
        pthread_attr_setinheritsched(&mut attr, PTHREAD_EXPLICIT_SCHED);

        param.sched_priority = 96;
        pthread_attr_setschedparam(&mut attr, &param);
        result = pthread_create(
            &mut crd_watcher_thread,
            &attr as *const _ as *const pthread_attr_t,
            crd_watcher,
            &shared_state as *const _ as *mut c_void
        );
        if result != 0 {
            eprintln!("An error occurred while creating the CRD Watcher thread! {}", result);
        }
        result = pthread_create(
            &mut pod_watcher_thread,
            &attr as *const _ as *const pthread_attr_t,
            pod_watcher,
            &shared_state as *const _ as *mut c_void
        );
        if result != 0 {
            eprintln!("An error occurred while creating the Pod Event Watcher thread!");
        }

        param.sched_priority = 95;
        pthread_attr_setschedparam(&mut attr, &param);
        result = pthread_create(
            &mut server_thread,
            &attr as *const _ as *const pthread_attr_t,
            server,
            &shared_state as *const _ as *mut c_void
        );
        if result != 0 {
            eprintln!("An error occurred while creating the Server thread! {}", result);
        }

        /*
        Now we wait for the created threads to terminate.
        Note: in the current implementation these threads should
        never terminate, since the controller is supposed to
        run indefinitely.
        */
        pthread_join(crd_watcher_thread, ptr::null_mut());
        pthread_join(pod_watcher_thread, ptr::null_mut());
        pthread_join(server_thread, ptr::null_mut());

        /*
        Cleanup phase.
        */
        pthread_attr_destroy(&mut attr);
        pthread_mutexattr_destroy(&mut mutex_attr);
        pthread_mutex_destroy(&mut mutex);
        pthread_cond_destroy(&mut cond);
    }
    
    Ok(())
}

//We need an handler that takes care of the controller logic
extern "C" fn watchdog(thread_data: *mut c_void) -> *mut c_void {

    let datas = unsafe {&*(thread_data as *mut data)};
    
    let thread = unsafe { pthread_self() };
    let rt_handle = datas.runtime.handle().clone();
    
    //We open the queue to retrieve the Event to handle
    unsafe {
        let mut queue_attr: mq_attr = { mem::zeroed() };
	queue_attr.mq_flags = 0;
	queue_attr.mq_maxmsg = 500;
	queue_attr.mq_msgsize = 256;
	queue_attr.mq_curmsgs = 0;
        let queue_des: mqd_t = mq_open(datas.queue.as_ptr() as *const c_char, O_RDONLY, 0664, &queue_attr);
        if queue_des == -1 {
            eprintln!("Watchdog - An error occurred while opening the queue!");
            exit(-1);
        }
	
        //We create a loop since this watchdog has to keep working forever
        loop {
            //The first step is to wait for a new event to handle
            let mut msg: [u8; 1024] = [0; 1024];
            let mut msg_priority: u32 = 0;
            let result = mq_receive(queue_des, msg.as_mut_ptr() as *mut c_char, msg.len(), &mut msg_priority as *mut u32);
            if result == -1 {
                eprintln!("Watchdog - An error occurred while retrieving a message from the queue!");
            }
            
            //We inform the server that this Thread is handling an event
            pthread_mutex_lock(&mut MUTEX);
	    working_threads = working_threads + 1;
	    println!("From Watchdog Starting Work: {}", working_threads); //DEBUG
	    pthread_cond_signal(&mut COND);
	    pthread_mutex_unlock(&mut MUTEX);
            
            //Thread priority must be changed according to job's priority
            let param = sched_param { sched_priority: 94 - msg_priority as i32 };
            pthread_setschedparam(thread, SCHED_FIFO, &param);
            let mut debug = sched_param { sched_priority: 0 };
            let mut policy = 0;
    	    pthread_getschedparam(thread, &mut policy, &mut debug);
    	    println!("Scheduling Priority is {} .", debug.sched_priority);
            
            let message = String::from_utf8(msg.to_vec()).unwrap_or_else(|_| String::from("Invalid UTF-8")).trim_matches(char::from(0)).to_string();

            //We use the Custom Resource Name in the message to get a list of said Custom Resource (it should be only one)
            //Then we proceed to get the desired number of Replicas
            rt_handle.block_on(async {
            	let handle = tokio::spawn(async move {
		        let client = datas.context.client.clone();
		        let cr_api = datas.context.rt_resources.clone();
		        match cr_api.get(message.as_str()).await {
		        	//The next step is to understand wether the Custom Resource still exists
				//If it doesn't exist, it means that it has been deleted and this function has to delete all the Pods associated to it that are still running
				//If it still exists it means that the event that occurred is a change in the desired number of Replicas,
				//or in the current one (this includes the case of a Custom Resource creation)
				//In any of these cases, the actions to take are the the same; first we get a list of all
				//Pods associated to the Custom Resource (a specific label will tell us this information),
				//then we compare the number of current Pods to the desired one and decide whether to create or delete a certain number of Pods
		        	Ok(cr) => {
		        		println!("Resource Found!");
					let pod_api: Api<Pod> = Api::namespaced(client.clone(), &cr.spec.namespace.as_str());
					let label_selector = format!("crd_id={}", &message);
					let lp_pod = ListParams {
					    label_selector: Some(label_selector),
					    resource_version: Some("0".to_string()),
					    ..ListParams::default()
					};
					let pod_list = pod_api.list(&lp_pod).await.unwrap();
					let pod_count = pod_list.items.len();
					let desired = cr.spec.replicaCount;
					let mut difference = desired - (pod_count as i32);
					if (desired as usize) < pod_count {
						difference = -difference;
						for i in pod_list.items.iter().take(difference as usize) {
						    delete_pod(client.clone(), &cr.spec.namespace, &i.metadata.uid.as_deref().unwrap_or(""), &i.metadata.name.clone().unwrap_or("".to_string())).await;
						}
					}
					else if (desired as usize) > pod_count {
						for i in 0..difference {
						    create_pod(client.clone(), &cr.spec, &message, cr.spec.criticality.to_string().as_str()).await;
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
		handle.await;
            });
	    
	    //Thread priority must return to its original value
            let param = sched_param { sched_priority: 94 };
            pthread_setschedparam(thread, SCHED_FIFO, &param);
            let mut debug = sched_param { sched_priority: 0 };
            let mut policy = 0;
    	    pthread_getschedparam(thread, &mut policy, &mut debug);
    	    println!("Scheduling Priority is {} .", debug.sched_priority);
    	    
    	    //When a Thread finishes its job, it must check if there are too many active Threads and, in such case, terminate itself
    	    pthread_mutex_lock(&mut MUTEX);
	    working_threads = working_threads - 1;
	    println!("From Watchdog Finishing Work: {}", working_threads); //DEBUG
	    let decision = active_threads - working_threads as usize;
	    if decision > THRESHOLD && active_threads > BASE_WATCHDOG_THREAD_NUMBER {
	    	println!("Decision Process: decision = {} - active_threads = {} - working_threads = {}", decision, active_threads, working_threads);
	    	break;
	    }
	    pthread_mutex_unlock(&mut MUTEX);
        }
        
        //Once the Thread decides to terminate it updates the global variable to communicate to the server it isn't active anymore
        let mut i = 0;
        let mut found = false;
        while i < MAX_WATCHDOG_THREAD_NUMBER && !found {
        	if active_watchdogs[i].id == thread {
        		active_watchdogs[i].active = false;
        		println!("The new free position is: {}", i);
        		found = true;
        		active_threads = active_threads - 1;
	    		pthread_mutex_unlock(&mut MUTEX);
        	}
        	i = i + 1;
        }
        println!("The found state: {}", found);
        
        //Let's close the queue
    	mq_close(queue_des);
    }
    
    println!("Terminating...");

    ptr::null_mut()

}

//This function creates a Pod according to our Custom Resource Specification
async fn create_pod(client: Client, crd: &RTResourceSpec, crd_id: &str, criticality: &str) -> Result<(), Box<dyn Error>> {

    let pod_api: Api<Pod> = Api::namespaced(client, crd.namespace.clone().as_str());
    let timestamp = SystemTime::now().duration_since(UNIX_EPOCH).expect("Time went backwards!").as_millis().to_string();
    let pod_name = format!("{}-{}", crd_id, timestamp);
    let pod = Pod {
        metadata: kube::core::ObjectMeta {
            name: Some(pod_name.clone()),
            labels: Some({
                let mut labels = BTreeMap::new();
                labels.insert("crd_id".to_string(), crd_id.to_string());
                labels.insert("criticality".to_string(), criticality.to_string());
                labels
            }),
            ..Default::default()
        },
        spec: Some(PodSpec {
            containers: vec![Container {
                name: pod_name.clone(),
                image: Some(crd.image.clone()),
                resources: Some(ResourceRequirements {
                    requests: Some({
                        let mut requests = BTreeMap::new();
                        requests.insert("cpu".to_string(), Quantity(crd.cpu.clone()));
                        requests.insert("memory".to_string(), Quantity(crd.memory.clone()));
                        requests
                    }),
                    claims: None,
                    limits: None,
                }),
                ..Default::default()
            }],
            ..Default::default()
        }),
        ..Default::default()
    };
    
    //We now schedule the created Pod on a certain node
    let scheduled_pod = scheduling(pod);
    
    let pp = PostParams::default();
    match pod_api.create(&pp, &scheduled_pod).await {
        Ok(o) => println!("Pod created: {:?}.", o.metadata.name),
        Err(e) => println!("An error occurred while creating the Pod: {}.", e),
    }

    Ok(())

}

//This function deletes a Pod
async fn delete_pod(client: Client, namespace: &str, uid: &str, name: &str) -> Result<(), Box<dyn Error>> {
    
    let pod_api: Api<Pod> = Api::namespaced(client.clone(), namespace.clone());
    if let Some(pod) = pod_api.get(name).await.ok() {
        if let Some(pod_uid) = &pod.metadata.uid.clone() {
            if pod_uid == uid {
                pod_api.delete(name, &DeleteParams::default()).await?;
                println!("Pod {} removed from namespace {}!", name, namespace);
            }
        }
    } else {
        println!("This Pod {} doesn't exist in this namespace {}!", name, namespace);
    }

    Ok(())

}
