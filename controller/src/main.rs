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
    pthread_cond_t,
    pthread_cond_init,
    pthread_cond_destroy,
    pthread_mutex_t,
    pthread_mutex_init,
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
use components::resource_state_updater::resource_state_updater;
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
            - a resource state updater that updates the status of RTResources
              accordingly to the relative pods state;
            - a server in charge of spwning new watchdogs when needed.
        Note: a watchdog is a thread that handles events from the event queue.
        */
        let mut crd_watcher_thread: pthread_t = 0;
        let mut pod_watcher_thread: pthread_t = 0;
        let mut resource_state_updater_thread: pthread_t = 0;
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

        result = pthread_create(
            &mut resource_state_updater_thread,
            &attr as *const _ as *const pthread_attr_t,
            resource_state_updater,
            &shared_state as *const _ as *mut c_void
        );
        if result != 0 {
            eprintln!("An error occurred while creating the Resource State Updater thread!");
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
