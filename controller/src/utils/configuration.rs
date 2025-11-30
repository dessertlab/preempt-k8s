/*
This File contains utility functions and variables to retrieve
the Preempt-K8s controller configuration.
*/

use std::{
    env,
    fmt
};



/*
Controller configuration parameters
*/
#[derive(Clone)]
pub struct ControllerConfig {
    pub min_watchdogs: usize,           // Minimum number of watchdog threads
    pub max_watchdogs: usize,           // Maximum number of watchdog threads
    pub threshold: usize,               // Threshold triggering watchdog threads scaling
    pub event_queue_path: String,       // Path to the event priority queue
}

/*
This function implements the Display trait for the
ControllerConfig struct to allow easy printing of its values.
*/
impl fmt::Display for ControllerConfig {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        writeln!(f, "Controller configuration:")?;
        writeln!(f, "    Min watchdogs: {}", self.min_watchdogs)?;
        writeln!(f, "    Max watchdogs: {}", self.max_watchdogs)?;
        writeln!(f, "    Threshold: {}", self.threshold)?;
        writeln!(f, "    Event Queue Path: {}", self.event_queue_path)
    }
}

/*
This function retrieves the minimum number of watchdog
threads from the environment variable "MIN_WATCHDOGS".
*/
fn get_minimum_watchdog_thread_number() -> usize {
    env::var("MIN_WATCHDOGS")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(10) // 10 is the Default Value
}

/*
This function retrieves the maximum number of watchdog
threads from the environment variable "MAX_WATCHDOGS".
*/
fn get_maximum_watchdog_thread_number() -> usize {
    env::var("MAX_WATCHDOGS")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(20) // 20 is the Default Value
}

/*
This function retrieves the threshold value
from the environment variable "THRESHOLD".
*/
fn get_threshold_number() -> usize {
    env::var("THRESHOLD")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(3) // 3 is the Default Value
}

/*
This function retrieves the event queue path
from the environment variable "EVENT_QUEUE".
*/
fn get_event_queue_path() -> String {
    env::var("EVENT_QUEUE")
    .unwrap_or_else(|_| "/eventqueue".to_string())
}


/*
This function retrieves the
controller configuration parameters.
*/
pub fn get_controller_configuration() -> ControllerConfig{
    ControllerConfig {
        min_watchdogs: get_minimum_watchdog_thread_number(),
        max_watchdogs: get_maximum_watchdog_thread_number(),
        threshold: get_threshold_number(),
        event_queue_path: get_event_queue_path(),
    }
}
