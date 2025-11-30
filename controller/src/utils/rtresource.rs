/*
This file contains the custom resource
specification for the RTResource monitored
by the Preempt-K8s controller.
*/

use std::collections::BTreeMap;
use kube::CustomResource;
use schemars::JsonSchema;
use serde::{
    Deserialize,
    Serialize
};


/*
Pod template specification
*/
#[derive(Deserialize, Serialize, Clone, Debug, JsonSchema)]
pub struct Template {
    pub metadata: Option<BTreeMap<String, serde_json::Value>>,
    pub spec: Option<BTreeMap<String, serde_json::Value>>,
}

/*
Match Expression used in the Selector
*/
#[derive(Deserialize, Serialize, Clone, Debug, JsonSchema)]
pub struct MatchExpression {
    pub key: String,
    pub operator: String,
    pub values: Option<Vec<String>>,
}

/*
Selector specification
*/
#[derive(Deserialize, Serialize, Clone, Debug, JsonSchema)]
pub struct Selector {
    pub match_labels: Option<BTreeMap<String, String>>,
    pub match_expressions: Option<Vec<MatchExpression>>,
}

/*
RTResource specification
*/
#[derive(CustomResource, Deserialize, Serialize, Clone, Debug, JsonSchema)]
#[kube(group = "rtgroup.critical.com", version = "v1", kind = "RTResource", namespaced, status = "RTResourceStatus")]
pub struct RTResourceSpec {
    /*
    Namespace where to deploy
    the corresponding pods
    */
    pub namespace: String,
    /*
    Number of Replicas
    */
    pub replicas: i32,
    /*
    Selector to identify the pods
    related to this resource
    */
    pub selector: Option<Selector>,
    /*
    Application criticality level
    */
    pub criticality: u32,
    /*
    Pod template
    */
    pub template: Template,
}

/*
Condition specification
*/
#[derive(Deserialize, Serialize, Clone, Debug, JsonSchema)]
pub struct Condition {
    pub condition_type: String,
    pub status: String,
    pub last_transition_time: Option<String>,
    pub reason: Option<String>,
    pub message: Option<String>,
}

/*
RTResource status specification
*/
#[derive(Deserialize, Serialize, Clone, Debug, JsonSchema, Default)]
pub struct RTResourceStatus {
    pub observed_generation: Option<i64>,
    pub desired_replicas: Option<i32>,
    pub replicas: Option<i32>,
    pub conditions: Option<Vec<Condition>>,
}
