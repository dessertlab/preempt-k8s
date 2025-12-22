/*
This file contains the component in charge
of collecting all events related to RTResource
related Pods.
*/

use std::{
    mem,
    ptr,
    process::exit,
    os::raw::c_char,
    ffi::c_void
};
use libc::{
    mqd_t,
    mq_open,
    mq_send,
    mq_close,
    mq_unlink,
    mq_attr,
    O_CREAT,
    O_WRONLY
};
use kube::runtime::watcher::{
        watcher,
        Config,
        Event
};
use futures::StreamExt;

use crate::utils::vars::SharedState;
use crate::utils::vars::QueueMessage;



pub extern "C" fn pod_watcher(thread_data: *mut c_void) -> *mut c_void {
    unsafe {
        let shared_state = &mut *(thread_data as *mut SharedState);

    	/*
		We must first open the message queue
		in case it is not already opened.
		We open it in write-only mode, since
		this thread only sends messages to it.
		*/
        let mut msg = QueueMessage {
			name: "".to_string(),
			uid: "".to_string(),
			namespace: "".to_string(),
		};
        let mut queue_attr: mq_attr = { mem::zeroed() };
        queue_attr.mq_flags = 0;
        queue_attr.mq_maxmsg = 2000;
        queue_attr.mq_msgsize = 256;
        queue_attr.mq_curmsgs = 0;
        let queue_des: mqd_t = mq_open(
            shared_state.queue.as_ptr() as *const c_char,
            O_CREAT | O_WRONLY,
            0664,
            &queue_attr
        );
        if queue_des == -1 {
            eprintln!("Pod Watcher - An error occurred while opening the queue!");
            exit(-1);
        }
        
        /*
		Now we can start the event watcher for RTResources related Pods.
		Each time an event is captured, we send a message to the
		event priority queue with name, UID and namespace of the related
        RTResource. The message priority is set equal to the criticality
		level of the resource.
        Note: we use the Pods label "criticality" to filter RTResource related Pods
        and retrieve the application criticality level.
		*/
        shared_state.runtime_handle.block_on(async {
            let watcher_config = Config {
                timeout: Some(100),
                ..Config::default()
            };
            let mut watcher = watcher(
                shared_state.context.pods.clone(),
                watcher_config
            ).boxed();
            while let Some(event) = watcher.next().await {
                match event{
                    Ok(Event::Deleted(object)) => {
                        if let Some(labels) = &object.metadata.labels {
                            if let (Some(name), Some(uid), Some(namespace), Some(critcality_str)) = (
                                labels.get("rtresource_name"),
                                labels.get("rtresource_uid"),
                                labels.get("rtresource_namespace"),
                                labels.get("criticality")
                            ) {
                                if let Ok(criticality) = critcality_str.parse::<u32>() {
                                    msg.name = name.clone();
                                    msg.uid = uid.clone();
                                    msg.namespace = namespace.clone();
                                    println!(
                                        "Pod Watcher - Detected deletion of Pod {} related to RTResource {}, {} in namespace {} with criticality {}.",
                                        object.metadata.name.clone().unwrap(),
                                        msg.name,
                                        msg.uid,
                                        msg.namespace,
                                        criticality
                                    );
                                    let mut c_msg = msg.clone().into_bytes();
                                    c_msg.push(0);
                                    let result = mq_send(
                                        queue_des,
                                        c_msg.as_ptr() as *const i8,
                                        c_msg.len(),
                                        criticality
                                    );
                                    if result == -1 {
                                        eprintln!("Pod Watcher - An error occurred while sending a message to the queue!");
                                    }
                                } else {
                                    eprintln!("Pod Watcher - Error while parsing criticality!");
                                    continue;
                                }
                            } else {
                                continue;
                            }
                        } else {
                            eprintln!("Pod Watcher - An error occurred while retrieving the Pod labels!");
                            continue;
                        }
                    }
                    Err(e) => {
                        println!("{}", e);
                    }
                    _ => {
                        println!("Pod Watcher - Nothing happened yet!");
                    }
                }
            }
	    });

    	/*
		Cleanup phase.
		*/
    	mq_close(queue_des);
        mq_unlink(shared_state.queue.as_ptr());
    }

    ptr::null_mut()
}
