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
	unsafe {
        let shared_state = &mut *(thread_data as *mut SharedState);

        /*
		We must first set the pipeline initial conditions:
            - active_threads = min_watchdogs;
            - all workers inactive.
            - no watchdog is busy.
        Note: in this phase there is no race condition for the shared state
        since no watchdogis active yet.
		*/
		shared_state.active_threads = shared_state.config.min_watchdogs;
		for i in 0..shared_state.config.max_watchdogs {
			shared_state.workers[i].id = 0;
			shared_state.workers[i].active = false;
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
		for i in 0..shared_state.config.min_watchdogs {
		    result = pthread_create(
                &mut shared_state.workers[i].id,
                &attr as *const _ as *const pthread_attr_t,
                watchdog,
                thread_data);
		    if result != 0 {
		        eprintln!("Server - An error occurred while creating a Watchdog thread!");
		    }
		    shared_state.workers[i].active = true;
		    println!("Server - Watchdog {} is active: {}!", i, shared_state.workers[i].active);
		}
		
		/*
        Now we can start the server loop that monitors the number of working watchdogs
        and spawns new ones if the number of free watchdogs
        goes below the defined threshold.
        */
		'outer: loop {
            let mut error_count: usize = 0;
			pthread_mutex_lock(&mut shared_state.mutex);
			while shared_state.working_threads == last_working {
                pthread_cond_wait(&mut shared_state.cond, &mut shared_state.mutex);
            }
    		last_working = shared_state.working_threads;
            let difference = shared_state.active_threads - shared_state.working_threads as usize;
            let currently_active = shared_state.active_threads;
            if difference < shared_state.config.threshold {
                let needed = shared_state.config.threshold - difference;
                let mut new_active = shared_state.active_threads + needed;
                if new_active > shared_state.config.max_watchdogs {
                    shared_state.active_threads = shared_state.config.max_watchdogs;
                    new_active = shared_state.active_threads;
                } else {
                    shared_state.active_threads = new_active;
                }
                pthread_mutex_unlock(&mut shared_state.mutex);
                let mut i: usize = 0;
                while i < needed {
                    println!("Server - There will be a total of {} Active Threads!", new_active);
                    if currently_active + i >= shared_state.config.max_watchdogs {
                        println!("Server - Max Thread Number reached!");
                        break;
                    }
                    let mut free = 0;
                    while shared_state.workers[free].active == true {
                        free = free + 1;
                    }
                    result = pthread_create(
                        &mut shared_state.workers[free].id,
                        &attr as *const _ as *const pthread_attr_t,
                        watchdog,
                        thread_data
                    );
                    if result != 0 {
                        i = i - 1;
                        eprintln!("Server - An error occurred while creating a Watchdog thread!");
                        error_count = error_count + 1;
                        if error_count > 5 {
                            eprintln!("Server - Too many errors occurred while creating watchdog threads! Exiting...");
                            break 'outer;
                        }
                    } else {
                        shared_state.workers[free].active = true;
                        println!("Server - Thread Created in position {}!", free);
                        i = i + 1;
                        error_count = 0;
                    }
                }
            } else {
                pthread_mutex_unlock(&mut shared_state.mutex);
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
        for i in 0..shared_state.config.max_watchdogs {
            if shared_state.workers[i].active {
                pthread_join(shared_state.workers[i].id, ptr::null_mut());
            }
        }
		
		/*
        Cleanup phase.
        */
        pthread_attr_destroy(&mut attr);
    }
        
    ptr::null_mut()	
}
