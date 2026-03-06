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
    pub min_watchdogs: usize,               // Minimum number of watchdog threads
    pub max_watchdogs: usize,               // Maximum number of watchdog threads
    pub threshold: usize,                   // Threshold triggering watchdog threads scaling
    pub event_queue_path: String,           // Path to the event priority queue
    pub thread_cpu_pinning: bool,           // Whether to enable CPU pinning for threads
    pub resource_watcher_cpu_list: String,  // CPU list for the resource watcher thread
    pub pod_watcher_cpu_list: String,       // CPU list for the pod watcher thread
    pub server_cpu_list: String,            // CPU list for the server thread
    pub state_updater_cpu_list: String,     // CPU list for the state updater thread
    pub watchdogs_cpu_list: String,         // CPU list for the watchdog threads
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
        writeln!(f, "    Event Queue Path: {}", self.event_queue_path)?;
        writeln!(f, "    Thread CPU Pinning Enabled: {}", self.thread_cpu_pinning)?;
        writeln!(f, "    Resource Watcher CPU List: {}", self.resource_watcher_cpu_list)?;
        writeln!(f, "    Pod Watcher CPU List: {}", self.pod_watcher_cpu_list)?;
        writeln!(f, "    Server CPU List: {}", self.server_cpu_list)?;
        writeln!(f, "    State Updater CPU List: {}", self.state_updater_cpu_list)?;
        writeln!(f, "    Watchdogs CPU List: {}", self.watchdogs_cpu_list)
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
This function retrieves the thread CPU pinning feature flag
from the environment variable "THREAD_CPU_PINNING".
*/
fn get_thread_cpu_pinning() -> bool {
    env::var("THREAD_CPU_PINNING")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(false) // false is the Default Value
}


/*
This function retrieves the CPU list for the resource watcher thread
from the environment variable "RESOURCE_WATCHER_CPU_LIST".
*/
fn get_resource_watcher_cpu_list() -> String {
    env::var("RESOURCE_WATCHER_CPU_LIST")
        .unwrap_or_else(|_| "0".to_string()) // "0" is the Default Value
}


/*
This function retrieves the CPU list for the pod watcher thread
from the environment variable "POD_WATCHER_CPU_LIST".
*/
fn get_pod_watcher_cpu_list() -> String {
    env::var("POD_WATCHER_CPU_LIST")
        .unwrap_or_else(|_| "1".to_string()) // "1" is the Default Value
}


/*
This function retrieves the CPU list for the server thread
from the environment variable "SERVER_CPU_LIST".
*/
fn get_server_cpu_list() -> String {
    env::var("SERVER_CPU_LIST")
        .unwrap_or_else(|_| "2".to_string()) // "2" is the Default Value
}


/*
This function retrieves the CPU list for the state updater thread
from the environment variable "STATE_UPDATER_CPU_LIST".
*/
fn get_state_updater_cpu_list() -> String {
    env::var("STATE_UPDATER_CPU_LIST")
        .unwrap_or_else(|_| "3".to_string()) // "3" is the Default Value
}


/*
This function retrieves the CPU list for the watchdog threads
from the environment variable "WATCHDOGS_CPU_LIST".
*/
fn get_watchdogs_cpu_list() -> String {
    env::var("WATCHDOGS_CPU_LIST")
        .unwrap_or_else(|_| "4".to_string()) // "4" is the Default Value
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
        thread_cpu_pinning: get_thread_cpu_pinning(),
        resource_watcher_cpu_list: get_resource_watcher_cpu_list(),
        pod_watcher_cpu_list: get_pod_watcher_cpu_list(),
        server_cpu_list: get_server_cpu_list(),
        state_updater_cpu_list: get_state_updater_cpu_list(),
        watchdogs_cpu_list: get_watchdogs_cpu_list(),
    }
}
