/*
This file contains the Preempt-K8s controller entrypoint.
It creates the necessary threads and tools 
to create the controller pipeline.
*/

use std::{
    mem,
    ptr,
    error::Error,
    ffi::c_void
};
use libc::{
    pthread_t,
    pthread_create,
    pthread_join,
    cpu_set_t,
    CPU_ZERO,
    CPU_SET,
    pthread_attr_t,
    pthread_attr_init,
    pthread_attr_setschedpolicy,
    pthread_attr_setschedparam,
    pthread_attr_setinheritsched,
    pthread_attr_setaffinity_np,
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
use kube::Client;
use tokio::runtime::Runtime;
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
        let mut config = get_controller_configuration();
        println!("{}", config);

        let resource_watcher_cpu_list: Vec<usize> = config.resource_watcher_cpu_list
            .split(',')
            .filter_map(|s| s.trim().parse().ok())
            .collect();
        let pod_watcher_cpu_list: Vec<usize> = config.pod_watcher_cpu_list
            .split(',')
            .filter_map(|s| s.trim().parse().ok())
            .collect();
        let server_cpu_list: Vec<usize> = config.server_cpu_list
            .split(',')
            .filter_map(|s| s.trim().parse().ok())
            .collect();
        let state_updater_cpu_list: Vec<usize> = config.state_updater_cpu_list
            .split(',')
            .filter_map(|s| s.trim().parse().ok())
            .collect();
        let watchdogs_cpu_list: Vec<usize> = config.watchdogs_cpu_list
            .split(',')
            .filter_map(|s| s.trim().parse().ok())
            .collect();
        if config.thread_cpu_pinning {
            let old_cpu_pinning_flag = config.thread_cpu_pinning;
            config.thread_cpu_pinning = !resource_watcher_cpu_list.is_empty() &&
                !pod_watcher_cpu_list.is_empty() &&
                !server_cpu_list.is_empty() &&
                !state_updater_cpu_list.is_empty() &&
                !watchdogs_cpu_list.is_empty();
            if old_cpu_pinning_flag != config.thread_cpu_pinning {
                eprintln!("Invalid CPU pinning configuration detected! Thread CPU pinning will be disabled.");
            }
            else {
                println!(
                    "Actual thread CPU dispatching:\n\
                    - Resource Watcher CPU list: {:?}\n\
                    - Pod Watcher CPU list:      {:?}\n\
                    - Server CPU list:           {:?}\n\
                    - State Updater CPU list:    {:?}\n\
                    - Watchdogs CPU list:        {:?}\n\
                    Eventual invalid values have been filtered out!",
                    resource_watcher_cpu_list,
                    pod_watcher_cpu_list,
                    server_cpu_list,
                    state_updater_cpu_list,
                    watchdogs_cpu_list
                );
            }
        }

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
        We create the Tokio runtime.
        */
        let runtime = Runtime::new().expect("Failed to create Tokio Runtime!");

        /*
        We must now create the shared state used by the controller threads
        using the information gathered up to this point.
        */
        let shared_state = new_shared_state(
            config.clone(),
            client.clone(),
            runtime.handle().clone(),
            cond,
            mutex,
            config.event_queue_path.as_str(),
            config.max_watchdogs
        );
        let share_state_ptr = Box::into_raw(shared_state) as *mut c_void;

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
        let mut cpuset: cpu_set_t = mem::zeroed();
        pthread_attr_init(&mut attr);
        pthread_attr_setschedpolicy(&mut attr, SCHED_FIFO);
        pthread_attr_setinheritsched(&mut attr, PTHREAD_EXPLICIT_SCHED);

        param.sched_priority = 96;
        pthread_attr_setschedparam(&mut attr, &param);

        if config.thread_cpu_pinning {
            CPU_ZERO(&mut cpuset);
            for &cpu in &resource_watcher_cpu_list {
                CPU_SET(cpu, &mut cpuset);
            }
            pthread_attr_setaffinity_np(
                &mut attr,
                std::mem::size_of::<cpu_set_t>(),
                &cpuset
            );
        }
        result = pthread_create(
            &mut crd_watcher_thread,
            &attr as *const _ as *const pthread_attr_t,
            crd_watcher,
            share_state_ptr
        );
        if result != 0 {
            eprintln!("An error occurred while creating the CRD Watcher thread! {}", result);
        }

        if config.thread_cpu_pinning {
            cpuset = mem::zeroed();
            CPU_ZERO(&mut cpuset);
            for &cpu in &pod_watcher_cpu_list {
                CPU_SET(cpu, &mut cpuset);
            }
            pthread_attr_setaffinity_np(
                &mut attr,
                std::mem::size_of::<cpu_set_t>(),
                &cpuset
            );
        }
        result = pthread_create(
            &mut pod_watcher_thread,
            &attr as *const _ as *const pthread_attr_t,
            pod_watcher,
            share_state_ptr
        );
        if result != 0 {
            eprintln!("An error occurred while creating the Pod Event Watcher thread!");
        }

        if config.thread_cpu_pinning {
            cpuset = mem::zeroed();
            CPU_ZERO(&mut cpuset);
            for &cpu in &state_updater_cpu_list {
                CPU_SET(cpu, &mut cpuset);
            }
            pthread_attr_setaffinity_np(
                &mut attr,
                std::mem::size_of::<cpu_set_t>(),
                &cpuset
            );
        }
        result = pthread_create(
            &mut resource_state_updater_thread,
            &attr as *const _ as *const pthread_attr_t,
            resource_state_updater,
            share_state_ptr
        );
        if result != 0 {
            eprintln!("An error occurred while creating the Resource State Updater thread!");
        }

        param.sched_priority = 95;
        pthread_attr_setschedparam(&mut attr, &param);
        if config.thread_cpu_pinning {
            cpuset = mem::zeroed();
            CPU_ZERO(&mut cpuset);
            for &cpu in &server_cpu_list {
                CPU_SET(cpu, &mut cpuset);
            }
            pthread_attr_setaffinity_np(
                &mut attr,
                std::mem::size_of::<cpu_set_t>(),
                &cpuset
            );
        }
        result = pthread_create(
            &mut server_thread,
            &attr as *const _ as *const pthread_attr_t,
            server,
            share_state_ptr
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
        pthread_join(resource_state_updater_thread, ptr::null_mut());
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
