extern crate libc;

use kube::{Client, Api, CustomResource, ResourceExt, runtime::{watcher, watcher::{Config, Event}}, api::{PostParams, ListParams, DeleteParams}};
use serde::{Deserialize, Serialize};
use k8s_openapi::{api::core::v1::{Pod, PodSpec, Container, ContainerPort, ResourceRequirements, EnvVar, EnvVarSource, ObjectFieldSelector, Probe, HTTPGetAction, HTTPHeader}, apimachinery::pkg::{api::resource::Quantity, util::intstr::IntOrString}};
use libc::*;
use std::{mem, ptr, sync::Arc, error::Error, ffi::{c_void, CString}, collections::BTreeMap, time::{SystemTime, UNIX_EPOCH}};
use anyhow::Result;
use schemars::JsonSchema;
use futures::stream::StreamExt;
use tokio::runtime::Runtime;
use rand::Rng;

const BASE_WATCHDOG_THREAD_NUMBER: usize = 10; //Minimum Number of Threads
const MAX_WATCHDOG_THREAD_NUMBER: usize = 20; //Max Number of Threads

const THRESHOLD: usize = 3; //The Treshold that lets us detrmine when to create new Worker Threads or when to delete them

static mut active_threads: usize = 0; //Currently active Threads
static mut working_threads: u32 = 0; //Currently working Threads

static mut COND: pthread_cond_t = PTHREAD_COND_INITIALIZER; //The Condition Variable used for sinchronization on common datas
static mut MUTEX: pthread_mutex_t = PTHREAD_MUTEX_INITIALIZER; //The Mutex used for sinchronization on common datas

//Working Thread Array, the watchdogs can easly communicate their decision to terminate
#[derive(Copy, Clone)]
pub struct worker {
    pub id: pthread_t,
    pub active: bool,
}
static mut active_watchdogs: [worker; MAX_WATCHDOG_THREAD_NUMBER] = [unsafe { std::mem::zeroed() }; MAX_WATCHDOG_THREAD_NUMBER];

//Controller Context Struct
pub struct CRDReplicaSetController {
    pub client: Client, //It's the Interface with Kubernets API Server
    pub rt_resources: Api<RTResource>, //It's the Interface with the type of Resources the Controller is working on
    pub namespace: String, //It's the Namespace the Controller is working on
}

//The Controller works on a specific type of Custom Resource structured as follows
#[derive(CustomResource, Deserialize, Serialize, Clone, Debug, JsonSchema)]
#[kube(group = "rtgroup.critical.com", version = "v1", kind = "RTResource", namespaced)]
pub struct RTResourceSpec {
    pub namespace: String, //Namespace of the Resource
    pub replicaCount: i32, //Number of Replicas
    pub cpu: String, //CPU Requirements
    pub memory: String, //Memory Requirements
    pub criticality: u32, //Criticality Level
    pub image: String, //Container Image
}

//These struct contains the datas used as parameters when creating new Threads
struct data {
    queue: CString,
    context: CRDReplicaSetController,
    runtime: Arc<Runtime>,
}

//The main takes care of the creation of our CRD Controller Pipeline
#[tokio::main]
async fn main() -> Result<(), Box<dyn Error + Send + Sync + 'static>> {
    
    unsafe {
        //We first create the context for our Controller using its struct
        let client = Client::try_default().await?;
        let context = CRDReplicaSetController {
            client: client.clone(),
            rt_resources: Api::namespaced(client.clone(), "realtime"),
            namespace: "realtime".to_string(),
        };
	
	//We now create the runtime used by the Worker Threads
	let runtime = Arc::new(Runtime::new().unwrap());
	
        //We create a queue that contains events marked by the application priority
        let queue = CString::new("/eventqueue").unwrap();
        
        //We create a mutex to access the global variables
        let mut mutex_attr: pthread_mutexattr_t = std::mem::zeroed();
        pthread_mutexattr_init(&mut mutex_attr as *mut _);
        pthread_mutexattr_setprotocol(&mut mutex_attr as *mut _, PTHREAD_PRIO_INHERIT);
        pthread_mutex_init(&mut MUTEX as *mut _, &mutex_attr);

        //We must now create all the Threads needed for the Pipeline (a CRD Watcher, a Pod Event Watcher and a Server)
        let datas = data {
            queue: queue,
            context: CRDReplicaSetController {
                client: context.client.clone(),
                rt_resources: context.rt_resources.clone(),
                namespace : context.namespace.clone(),
            },
            runtime: runtime.clone(),
        };
        let mut crd_watcher_thread: pthread_t = 0;
        let mut pod_watcher_thread: pthread_t = 0;
        let mut server_thread: pthread_t = 0;
        let mut result: i32;
        let mut param: sched_param = sched_param{sched_priority: 0};
        let mut attr: pthread_attr_t = std::mem::zeroed();
        pthread_attr_init(&mut attr);
        pthread_attr_setschedpolicy(&mut attr, SCHED_FIFO);
        pthread_attr_setinheritsched(&mut attr, PTHREAD_EXPLICIT_SCHED);

        //The first step is to create the two Threads that will take care of event catching and forwarding
        param.sched_priority = 96;
        pthread_attr_setschedparam(&mut attr, &param);
        result = pthread_create(&mut crd_watcher_thread, &attr as *const _ as *const pthread_attr_t, crd_watcher, &datas as *const _ as *mut c_void);
        if result != 0 {
            eprintln!("An error occurred while creating the CRD Watcher thread! {}", result);
        }
        result = pthread_create(&mut pod_watcher_thread, &attr as *const _ as *const pthread_attr_t, pod_watcher, &datas as *const _ as *mut c_void);
        if result != 0 {
            eprintln!("An error occurred while creating the Pod Event Watcher thread!");
        }

        //We then create the thread that will take care of serving Events on the queue creating a correct amount of threads that will actually handle an Event
        param.sched_priority = 95;
        pthread_attr_setschedparam(&mut attr, &param);
        result = pthread_create(&mut server_thread, &attr as *const _ as *const pthread_attr_t, server, &datas as *const _ as *mut c_void);
        if result != 0 {
            eprintln!("An error occurred while creating the Server thread! {}", result);
        }

        //Waits for the conclusion of created threads
        pthread_join(crd_watcher_thread, ptr::null_mut());
        pthread_join(pod_watcher_thread, ptr::null_mut());
        pthread_join(server_thread, ptr::null_mut());

        //Let's destory what we don't need anymore
        pthread_attr_destroy(&mut attr);
        pthread_mutexattr_destroy(&mut mutex_attr);
    }
    
    Ok(())

}

//We need a watcher that checks for Events on our Custom Resources
extern "C" fn crd_watcher(thread_data: *mut c_void) -> *mut c_void {

    let datas = unsafe {&*(thread_data as *mut data)};
    
    unsafe {
    	//The queue is opened to send events on it
    	let mut queue_attr: mq_attr = { mem::zeroed() };
	queue_attr.mq_flags = 0;
	queue_attr.mq_maxmsg = 500;
	queue_attr.mq_msgsize = 256;
	queue_attr.mq_curmsgs = 0;
        let queue_des: mqd_t = mq_open(datas.queue.as_ptr() as *const c_char, O_CREAT | O_WRONLY, 0664, &queue_attr);
        if queue_des == -1 {
            eprintln!("CRD Watcher - An error occurred while opening the queue!");
            exit(-1);
        }
    
	//The crd_watcher starts to collect events and forwarding them to the appropriate queue
	let runtime = Runtime::new().unwrap();
	runtime.block_on(async {
		let watcher_config = Config {
		    timeout: Some(100),
		    ..Config::default()
		};
    		let mut watcher = watcher(datas.context.rt_resources.clone(), watcher_config).boxed();
		while let Some(event) = watcher.next().await {
			match event{
				Ok(Event::Applied(object)) | Ok(Event::Deleted(object)) => {
					let msg = object.name_any();
					let result;
					let mut c_msg = msg.clone().into_bytes();
					c_msg.push(0);
					result = mq_send(queue_des, c_msg.as_ptr() as *const i8, c_msg.len(), object.spec.criticality);
					if result == -1 {
					    eprintln!("CRD Watcher - An error occurred while sending a message to the queue!");
					}
				}
				Err(e) => {
					println!("{}", e);
				}
				_ => {
					println!("Nothing happened yet!");
				}
			}
		}
	});
    
    	//Let's close the queue
    	mq_close(queue_des);
    	mq_unlink(datas.queue.as_ptr());
    }

    ptr::null_mut()

}

//We need a watcher that checks for Events on our Custom Resources' Pods
extern "C" fn pod_watcher(thread_data: *mut c_void) -> *mut c_void {

    let datas = unsafe {&*(thread_data as *mut data)};
    
    unsafe {
    	//The queues are opened to send events on them
        let mut queue_attr: mq_attr = { mem::zeroed() };
	queue_attr.mq_flags = 0;
	queue_attr.mq_maxmsg = 500;
	queue_attr.mq_msgsize = 256;
	queue_attr.mq_curmsgs = 0;
        let queue_des: mqd_t = mq_open(datas.queue.as_ptr() as *const c_char, O_CREAT | O_WRONLY, 0664, &queue_attr);
        if queue_des == -1 {
            eprintln!("Pod Watcher - An error occurred while opening the queue!");
            exit(-1);
        }
    
	//The pod_watcher starts to collect events and forwarding them to the appropriate queue
	let runtime = Runtime::new().unwrap();
	runtime.block_on(async {
		let pod_api: Api<Pod> = Api::namespaced(datas.context.client.clone(), datas.context.namespace.clone().as_str());
		let watcher_config = Config {
		    timeout: Some(100),
		    ..Config::default()
		};
    		let mut watcher = watcher(pod_api.clone(), watcher_config).boxed();
		while let Some(event) = watcher.next().await {
			match event{
				Ok(Event::Deleted(object)) => {
					let labels = object.metadata.labels.unwrap();
					let msg = labels.get("crd_id").unwrap();
					let criticality_str = labels.get("criticality").unwrap();
					let result;
					let msg_copy = msg.clone(); 
					let mut c_msg = msg_copy.into_bytes();
					let criticality = criticality_str.parse::<u32>().unwrap();
					c_msg.push(0);
					result = mq_send(queue_des, c_msg.as_ptr() as *const i8, c_msg.len(), criticality);
					if result == -1 {
					    eprintln!("Pod Watcher - An error occurred while sending a message to the queue!");
					}
				}
				Err(e) => {
					println!("{}", e);
				}
				_ => {
					println!("Nothing happened yet!");
				}
			}
		}
	});

    	//Let's close the queues
    	mq_close(queue_des);
        mq_unlink(datas.queue.as_ptr());
    }

    ptr::null_mut()

}

//We need a Server that ensures to have enought Threads to handle events
extern "C" fn server(thread_data: *mut c_void) -> *mut c_void {
	
	let datas = unsafe {&*(thread_data as *mut data)};
	
	let watch_data = data {
            queue: datas.queue.clone(),
            context: CRDReplicaSetController {
                client: datas.context.client.clone(),
                rt_resources: datas.context.rt_resources.clone(),
                namespace : datas.context.namespace.clone(),
            },
            runtime: datas.runtime.clone(),
        };
	
	unsafe {
		active_threads = BASE_WATCHDOG_THREAD_NUMBER;
		for i in 0..MAX_WATCHDOG_THREAD_NUMBER {
			active_watchdogs[i].id = 0;
			active_watchdogs[i].active = false;
		}
		let mut last_working = 0;
		let mut result: i32;
		let mut param: sched_param = sched_param{sched_priority: 0};
		let mut attr: pthread_attr_t = std::mem::zeroed();
		pthread_attr_init(&mut attr);
		pthread_attr_setschedpolicy(&mut attr, SCHED_FIFO);
		pthread_attr_setinheritsched(&mut attr, PTHREAD_EXPLICIT_SCHED);

		//The first step is to create the first Threads (the base number)
		param.sched_priority = 94;
		pthread_attr_setschedparam(&mut attr, &param);
		for i in 0..BASE_WATCHDOG_THREAD_NUMBER {
		    result = pthread_create(&mut active_watchdogs[i].id, &attr as *const _ as *const pthread_attr_t, watchdog, &watch_data as *const _ as *mut c_void);
		    if result != 0 {
		        eprintln!("An error occurred while creating a Watchdog thread!");
		    }
		    active_watchdogs[i].active = true;
		    println!("State: {}", active_watchdogs[i].active);
		}
		
		//We create a loop since this watchdog has to keep working forever
		loop {
			pthread_mutex_lock(&mut MUTEX);
			while working_threads == last_working {
				println!("Before Check From the Server: {}", working_threads); //DEBUG
        			pthread_cond_wait(&mut COND, &mut MUTEX);
    			}
    			last_working = working_threads;
    			println!("From Server: {}", working_threads); //DEBUG
    			let difference = active_threads - working_threads as usize;
    			let currently_active = active_threads;
    			if difference < THRESHOLD {
				let needed = THRESHOLD - difference;
				let mut new_active = active_threads + needed;
				if new_active > MAX_WATCHDOG_THREAD_NUMBER {
					active_threads = MAX_WATCHDOG_THREAD_NUMBER
				}
				else {
					active_threads = active_threads + needed;
				}
				new_active = active_threads;
				pthread_mutex_unlock(&mut MUTEX);
				for i in 0..needed {
					println!("There will be a total of {} Active Threads!", new_active);
				    	if currently_active + i >= MAX_WATCHDOG_THREAD_NUMBER {
				    		println!("Max Thread Number reached!");
				    		break;
				    	}
				    	let mut free = 0;
				    	while active_watchdogs[free].active == true {
				    		free = free + 1;
				    	}
					result = pthread_create(&mut active_watchdogs[free].id, &attr as *const _ as *const pthread_attr_t, watchdog, &watch_data as *const _ as *mut c_void);
				    	println!("Thread Created in position {}!", free);
				    	if result != 0 {
						eprintln!("An error occurred while creating a Watchdog thread!");
				    	}
				    	active_watchdogs[free].active = true;
				}
			}
			else {
				pthread_mutex_unlock(&mut MUTEX);
			}
		}
		
		//Let's destory what we don't need anymore
        	pthread_attr_destroy(&mut attr);
        }
        
        ptr::null_mut()
	
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
    
    //We now create the Pod Manifest
    let pod = Pod {
    metadata: kube::core::ObjectMeta {
        name: Some(pod_name.clone()),
        namespace: Some(crd.namespace.clone().to_string()),
        labels: Some({
            let mut labels = BTreeMap::new();
            labels.insert("crd_id".to_string(), crd_id.to_string());
            labels.insert("criticality".to_string(), criticality.to_string());
            labels.insert("serving.knative.dev/configuration".to_string(), crd_id.to_string());
            labels.insert("serving.knative.dev/revision".to_string(), format!("{}-00001", crd_id));
            labels.insert("serving.knative.dev/service".to_string(), crd_id.to_string());
            labels
        }),
        annotations: Some({
            let mut annotations = BTreeMap::new();
            annotations.insert("config.dyn.running-services/allow-http-full-duplex".to_string(), "Enabled".to_string());
            annotations
        }),
        ..Default::default()
    },
    spec: Some(PodSpec {
        containers: vec![
            Container {
                name: "server".to_string(),
                image: Some(crd.image.clone()),
                ports: Some(vec![
                    ContainerPort {
                        container_port: 8080,
                        ..Default::default()
                    }
                ]),
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
            },
            Container {
		    name: "queue-proxy".to_string(),
		    image: Some("stefanost2000/docker-repo:queue".to_string()),
		    image_pull_policy: Some("Always".to_string()),
		    ports: Some(vec![
			ContainerPort {
			    name: Some("http-queueadm".to_string()),
			    container_port: 8022,
			    ..Default::default()
			},
			ContainerPort {
			    name: Some("http-autometric".to_string()),
			    container_port: 9090,
			    ..Default::default()
			},
			ContainerPort {
			    name: Some("http-usermetric".to_string()),
			    container_port: 9091,
			    ..Default::default()
			},
			ContainerPort {
			    name: Some("queue-port".to_string()),
			    container_port: 8012,
			    ..Default::default()
			},
			ContainerPort {
			    name: Some("https-port".to_string()),
			    container_port: 8112,
			    ..Default::default()
			}
		    ]),
		    env: Some(vec![
			EnvVar {
			    name: "CONTAINER_CONCURRENCY".to_string(),
			    value: Some("10".to_string()),
			    ..Default::default()
			},
			EnvVar {
			    name: "QUEUE_SERVING_PORT".to_string(),
			    value: Some("8012".to_string()),
			    ..Default::default()
			},
			EnvVar {
			    name: "QUEUE_SERVING_TLS_PORT".to_string(),
			    value: Some("8112".to_string()),
			    ..Default::default()
			},
			EnvVar {
			    name: "SERVING_NAMESPACE".to_string(),
			    value: Some(crd.namespace.clone().to_string()),
			    ..Default::default()
			},
			EnvVar {
			    name: "SERVING_SERVICE".to_string(),
			    value: Some(crd_id.to_string()),
			    ..Default::default()
			},
			EnvVar {
			    name: "SERVING_CONFIGURATION".to_string(),
			    value: Some(crd_id.to_string()),
			    ..Default::default()
			},
			EnvVar {
			    name: "SERVING_REVISION".to_string(),
			    value: Some(format!("{}-00001", crd_id)),
			    ..Default::default()
			},
			EnvVar {
			    name: "USER_PORT".to_string(),
			    value: Some("80".to_string()),
			    ..Default::default()
			},
			EnvVar {
			    name: "SERVING_POD".to_string(),
			    value: Some(pod_name.clone()),
			    ..Default::default()
			},
			EnvVar {
			    name: "SERVING_POD_IP".to_string(),
			    value_from: Some(EnvVarSource {
				field_ref: Some(ObjectFieldSelector {
				    field_path: "status.podIP".to_string(),
				    ..Default::default()
				}),
				..Default::default()
			    }),
			    ..Default::default()
			},
			EnvVar {
			    name: "METRICS_DOMAIN".to_string(),
			    value: Some("knative.dev/internal/serving".to_string()),
			    ..Default::default()
			},
			EnvVar {
			    name: "ENABLE_PROFILING".to_string(),
			    value: Some("false".to_string()),
			    ..Default::default()
			},
			EnvVar {
			    name: "ENABLE_REQUEST_LOG".to_string(),
			    value: Some("false".to_string()),
			    ..Default::default()
			},
			EnvVar {
			    name: "REVISION_TIMEOUT_SECONDS".to_string(),
			    value: Some("300".to_string()),
			    ..Default::default()
			},
			EnvVar {
			    name: "REVISION_RESPONSE_START_TIMEOUT_SECONDS".to_string(),
			    value: Some("0".to_string()),
			    ..Default::default()
			},
			EnvVar {
			    name: "REVISION_IDLE_TIMEOUT_SECONDS".to_string(),
			    value: Some("0".to_string()),
			    ..Default::default()
			},
			EnvVar {
			    name: "SYSTEM_NAMESPACE".to_string(),
			    value: Some("knative-serving".to_string()),
			    ..Default::default()
			},
			EnvVar {
			    name: "CONFIG_LOGGING_NAME".to_string(),
			    value: Some("config-logging".to_string()),
			    ..Default::default()
			},
			EnvVar {
			    name: "CONFIG_OBSERVABILITY_NAME".to_string(),
			    value: Some("config-observability".to_string()),
			    ..Default::default()
			},
			EnvVar {
			    name: "METRICS_COLLECTOR_ADDRESS".to_string(),
			    value: Some("http://collector-service.knative-serving".to_string()),
			    ..Default::default()
			},
			EnvVar {
			    name: "SERVING_LOGGING_CONFIG".to_string(),
			    value: Some("{}".to_string()),
			    ..Default::default()
			},
			EnvVar {
			    name: "SERVING_LOGGING_LEVEL".to_string(),
			    value: Some("info".to_string()),
			    ..Default::default()
			},
			EnvVar {
			    name: "SERVING_REQUEST_LOG_TEMPLATE".to_string(),
			    value: Some("{\"httpRequest\": {\"requestMethod\": \"{{.Request.Method}}\", \"requestUrl\": \"{{js .Request.RequestURI}}\", \"requestSize\": \"{{.Request.ContentLength}}\", \"status\": {{.Response.Code}}, \"responseSize\": \"{{.Response.Size}}\", \"userAgent\": \"{{js .Request.UserAgent}}\", \"remoteIp\": \"{{js .Request.RemoteAddr}}\", \"serverIp\": \"{{.Revision.PodIP}}\", \"referer\": \"{{js .Request.Referer}}\", \"latency\": \"{{.Response.Latency}}s\", \"protocol\": \"{{.Request.Proto}}\"}, \"traceId\": \"{{index .Request.Header \\\"X-B3-Traceid\\\"}}\"}"
				.to_string()),
			    ..Default::default()
			},
			EnvVar {
			    name: "SERVING_ENABLE_REQUEST_LOG".to_string(),
			    value: Some("false".to_string()),
			    ..Default::default()
			},
			EnvVar {
			    name: "SERVING_REQUEST_METRICS_BACKEND".to_string(),
			    value: Some("prometheus".to_string()),
			    ..Default::default()
			},
			EnvVar {
			    name: "SERVING_REQUEST_METRICS_REPORTING_PERIOD_SECONDS".to_string(),
			    value: Some("5".to_string()),
			    ..Default::default()
			},
			EnvVar {
			    name: "SERVING_ENABLE_REQUEST_METRICS".to_string(),
			    value: Some("true".to_string()),
			    ..Default::default()
			},
			EnvVar {
			    name: "ENABLE_METRICS".to_string(),
			    value: Some("true".to_string()),
			    ..Default::default()
			},
			EnvVar {
			    name: "TRACING_CONFIG_BACKEND".to_string(),
			    value: Some("none".to_string()),
			    ..Default::default()
			},
			EnvVar {
			    name: "TRACING_CONFIG_DEBUG".to_string(),
			    value: Some("false".to_string()),
			    ..Default::default()
			},
			EnvVar {
			    name: "TRACING_CONFIG_SAMPLE_RATE".to_string(),
			    value: Some("0.1".to_string()),
			    ..Default::default()
			},
			EnvVar {
			    name: "ENABLE_HTTP2_AUTO_DETECTION".to_string(),
			    value: Some("false".to_string()),
			    ..Default::default()
			},
			EnvVar {
			    name: "ENABLE_HTTP_FULL_DUPLEX".to_string(),
			    value: Some("true".to_string()),
			    ..Default::default()
			},
			EnvVar {
			    name: "ENABLE_MULTI_CONTAINER_PROBES".to_string(),
			    value: Some("false".to_string()),
			    ..Default::default()
			}
		    ]),
		    readiness_probe: Some(Probe {
			http_get: Some(HTTPGetAction {
			    path: Some("/".to_string()),
			    port: IntOrString::Int(8012),
			    http_headers: Some(vec![
				HTTPHeader {
				    name: "K-Network-Probe".to_string(),
				    value: "queue".to_string(),
				}
			    ]),
			    ..Default::default()
			}),
			period_seconds: Some(10),
			failure_threshold: Some(3),
			timeout_seconds: Some(1),
			..Default::default()
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

//This function simulates the scheduling decision to assign a node name to a pod
fn scheduling(mut pod: Pod) -> Pod {
    
    let node_name = if pod.clone().metadata.name.unwrap().starts_with("service-1-") {
        let random_number = rand::thread_rng().gen_range(1..=2);
        match random_number {
            1 => "orionw1",
            2 => "orionw2",
            _ => "orionw1" //Default
        }
    } else {
        let random_number = rand::thread_rng().gen_range(3..=4);
        match random_number {
            3 => "orionw3",
            4 => "orionw4",
            _ => "orionw3" //Default
        }
    };
    
    if let Some(spec) = pod.spec.as_mut() {
        spec.node_name = Some(node_name.to_string());
    }
    
    pod
    
}

