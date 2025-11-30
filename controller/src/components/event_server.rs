/*
This file contains the component in charge
of spawning watchdog threads when free ones
are under a certain threshold.
*/

use std::{
    mem,
    ptr,
    ffi::c_void
};
use libc::{
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
    PTHREAD_EXPLICIT_SCHED,
    pthread_cond_wait,
    pthread_mutex_lock,
    pthread_mutex_unlock
};

use crate::utils::vars::SharedState;
use crate::components::watchdog::watchdog;



pub extern "C" fn server(thread_data: *mut c_void) -> *mut c_void {
	let shared_data = unsafe {&*(thread_data as *mut SharedState)};
	
	unsafe {
        /*
		We must first set the pipeline initial conditions:
            - active_threads = min_watchdogs;
            - all workers inactive.
            - no watchdog is busy.
        Note: in this phase there is no race condition for the shared state
        since no watchdogis active yet.
		*/
		shared_data.active_threads = shared_data.config.min_watchdogs;
		for i in 0..shared_data.config.max_watchdogs {
			shared_data.workers[i].id = 0;
			shared_data.workers[i].active = false;
		}
        let mut last_working: usize = 0;
        
        /*
        Now we can create the initial watchdog threads  
        (the minimum number).
        Each watchdog thread is created with SCHED_FIFO policy
        and a priority level of "94".
        */
        let mut attr: pthread_attr_t = mem::zeroed();
		let mut param: sched_param = sched_param{sched_priority: 0};
        let mut result: i32;
		pthread_attr_init(&mut attr);
		pthread_attr_setschedpolicy(&mut attr, SCHED_FIFO);
		pthread_attr_setinheritsched(&mut attr, PTHREAD_EXPLICIT_SCHED);

		param.sched_priority = 94;
		pthread_attr_setschedparam(&mut attr, &param);
		for i in 0..shared_data.config.min_watchdogs {
		    result = pthread_create(
                &mut shared_data.workers[i].id,
                &attr as *const _ as *const pthread_attr_t,
                watchdog,
                &shared_data as *const _ as *mut c_void);
		    if result != 0 {
		        eprintln!("Server - An error occurred while creating a Watchdog thread!");
		    }
		    shared_data.workers[i].active = true;
		    println!("Server - Watchdog {} is active: {}!", i, shared_data.workers[i].active);
		}
		
		/*
        Now we can start the server loop that monitors the number of working watchdogs
        and spawns new ones if the number of free watchdogs
        goes below the defined threshold.
        */
		'outer: loop {
            let mut error_count: usize = 0;
			pthread_mutex_lock(&mut shared_data.mutex);
			while shared_data.working_threads == last_working {
                pthread_cond_wait(&mut shared_data.cond, &mut shared_data.mutex);
            }
    		last_working = shared_data.working_threads;
            let difference = shared_data.active_threads - shared_data.working_threads as usize;
            let currently_active = shared_data.active_threads;
            if difference < shared_data.config.threshold {
                let mut needed = shared_data.config.threshold - difference;
                let mut new_active = shared_data.active_threads + needed;
                if new_active > shared_data.config.max_watchdogs {
                    shared_data.active_threads = shared_data.config.max_watchdogs;
                    new_active = shared_data.active_threads;
                } else {
                    shared_data.active_threads = new_active;
                }
                pthread_mutex_unlock(&mut shared_data.mutex);
                let mut i: usize = 0;
                while i < needed {
                    println!("Server - There will be a total of {} Active Threads!", new_active);
                    if currently_active + i >= shared_data.config.max_watchdogs {
                        println!("Server - Max Thread Number reached!");
                        break;
                    }
                    let mut free = 0;
                    while shared_data.workers[free].active == true {
                        free = free + 1;
                    }
                    result = pthread_create(
                        &mut shared_data.workers[free].id,
                        &attr as *const _ as *const pthread_attr_t,
                        watchdog,
                        &shared_data as *const _ as *mut c_void
                    );
                    if result != 0 {
                        i = i - 1;
                        eprintln!("Server - An error occurred while creating a Watchdog thread!");
                        error_count = error_count + 1;
                        if error_count > 5 {
                            eprintln!("Server - Too many errors occurred while creating watchdog threads. Exiting...");
                            break 'outer;
                        }
                    } else {
                        shared_data.workers[free].active = true;
                        println!("Server - Thread Created in position {}!", free);
                        i = i + 1;
                        error_count = 0;
                    }
                }
            } else {
                pthread_mutex_unlock(&mut shared_data.mutex);
            }
		}

        /*
        Now we wait for the created threads to terminate.
        Note: in the current implementation these threads should
        never terminate, since the controller is supposed to
        run indefinitely.
        */
        println!("Server - Something went wrong, no new watchdogs will be created! Restart the controller to recover!");
        println!("Server - Waiting for currently active watchdogs to terminate for graceful shutdown...");
        for i in 0..shared_data.config.max_watchdogs {
            if shared_data.workers[i].active {
                pthread_join(shared_data.workers[i].id, ptr::null_mut());
            }
        }
		
		/*
        Cleanup phase.
        */
        pthread_attr_destroy(&mut attr);
    }
        
        ptr::null_mut()	
}
