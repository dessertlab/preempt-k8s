/*
This File contains useful constants and variables used
by the Preempt-K8s controller threads.
*/

use std::{
    ffi::CString,
    sync::Arc
};
use libc::{
    pthread_t,
    pthread_cond_t,
    pthread_mutex_t
};
use kube::{
    Api, Client
};
use k8s_openapi::api::core::v1::Pod;
use tokio::runtime::Runtime;

use crate::utils::rtresource::RTResource;
use crate::utils::configuration::*;



/*
Controller kubernetes Context struct
used to store Controller-K8s communication parameters
*/
pub struct ClientContext {
    /*
    Interface with Kubernets API Server
    */
    pub client: Client,
    /*
    Interface with the custom resource
    monitored by the controller
    */
    pub rt_resources: Api<RTResource>,
    /*
    Interface with the Kubernetes pods
    */
    pub pods: Api<Pod>,
}

/*
Working Thread Array, it stores watchdog thread ids and their working status
If a watchdog is processing an event, its active field is set to true
*/
#[derive(Copy, Clone)]
pub struct Worker {
    pub id: pthread_t,
    pub active: bool,
}

/*
Shared State struct used to synchronize the
controller threads
*/
pub struct SharedState {
    /*
    The Preempt-K8s controller configuration
    */
    pub config: ControllerConfig,
    /*
    The Kubernetes Client Context
    */
    pub context: ClientContext,
    /*
    The Tokio Runtime
    */
    pub runtime: Runtime,
    /*
    The Condition Variable and Mutex used for sinchronization
    on common datas
    */
    pub cond: pthread_cond_t,
    pub mutex: pthread_mutex_t,
    /*
    The Event Queue
    */
    pub queue: CString,
    /*
    Currently active Threads
    */
    pub active_threads: usize,
    /*
    Currently working Threads
    */
    pub working_threads: usize,
    /*
    The Workers Array
    */
    pub workers: Vec<Worker>,
}

/*
This function creates a new SharedState
and initializes its fields.
*/
pub fn new_shared_state(config: ControllerConfig, client: Client, cond: pthread_cond_t, mutex: pthread_mutex_t, queue_path: &str, workers_number: usize) -> Arc<SharedState> {
    Arc::new(SharedState {
        config: config,
        context: ClientContext {
            client: client.clone(),
            rt_resources: Api::<RTResource>::all(client.clone()),
            pods: Api::<Pod>::all(client.clone()),
        },
        runtime: Runtime::new().expect("Failed to create Tokio Runtime!"),
        cond: cond,
        mutex: mutex,
        queue: CString::new(queue_path).expect("Failed to create Event Queue!"),
        active_threads: 0,
        working_threads: 0,
        workers: vec![Worker {
                id: 0,
                active: false
            };
            workers_number
        ],
    })
}
