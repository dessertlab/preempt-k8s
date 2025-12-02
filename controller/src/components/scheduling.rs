/*
This file contains the managed Pods
lifecycle functions.
*/

use std::{
    error::Error,
    collections::BTreeMap,
    time::{
        SystemTime,
        UNIX_EPOCH
    }
};
use kube::{
    Client,
    Api,
    api::{
        PostParams,
        DeleteParams
    }
};
use k8s_openapi::api::core::v1::Pod;
use rand::Rng;

use crate::utils::rtresource::RTResource;



/*
This function creates a Pod in the cluster.
*/
pub async fn create_pod(thread_name: String, client: Client, rtresource: &RTResource) -> Result<(), Box<dyn Error>> {
    /*
    We must create the Pod metadata:
    - name = rtresource_name-timestamp
      (usiamo un timestamp per dare unicità al nome)
    - namespace = rtresource.spec.namespace
    - labels = those specified in the
      rtresource.spec.template.metadata.labels + rtresource_id (UID) + criticality + selector.match_labels
    - annotations = those specified in the rtresource.spec.template.metadata.annotations

    Note: match expressions are not yet supported
    */
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("Time went backwards!")
        .as_millis()
        .to_string();
    let pod_name = format!("{}-{}", rtresource.metadata.name.as_ref().unwrap(), timestamp);
    let pod_namespace = rtresource.spec.namespace.clone();

    let mut labels: BTreeMap<String, String> = BTreeMap::new();
    let mut annotations: BTreeMap<String, String> = BTreeMap::new();
    if let Some(pod_metadata) = rtresource.spec.template.metadata.as_ref() {
        if let Some(pod_labels) = pod_metadata.labels.as_ref() {
            for (key, value) in pod_labels.iter() {
                labels.insert(key.clone(), value.clone());
            }
        }
        if let Some(pod_annotations) = pod_metadata.annotations.as_ref() {
            for (key, value) in pod_annotations.iter() {
                annotations.insert(key.clone(), value.clone());
            }
        }
    }
    if let Some(selector) = rtresource.spec.selector.as_ref() {
        if let Some(match_labels) = selector.match_labels.as_ref() {
            for (key, value) in match_labels.iter() {
                labels.insert(key.clone(), value.clone());
            }
        }
    }
    labels.insert(
        "rtresource_id".to_string(),
        rtresource.metadata.uid.clone().unwrap_or_default(),
    );
    labels.insert(
        "criticality".to_string(),
        rtresource.spec.criticality.to_string(),
    );

    let pod_spec = rtresource.spec.template.spec.clone();

    /*
    Now we can create the Pod object
    and submit it to the cluster.
    The Pod spec is as is in the RTResource spec.template.
    */
    let pod_api: Api<Pod> = Api::namespaced(client.clone(), &pod_namespace);

    let pod = Pod {
        metadata: kube::core::ObjectMeta {
            name: Some(pod_name.clone()),
            namespace: Some(pod_namespace.clone()),
            labels: Some(labels),
            annotations: if annotations.is_empty() { None } else { Some(annotations) },
            ..Default::default()
        },
        spec: pod_spec,
        ..Default::default()
    };

    let scheduled_pod = scheduler(thread_name.clone(), pod);

    let pp = PostParams::default();
    match pod_api.create(&pp, &scheduled_pod).await {
        Ok(o) => println!("{} - Pod created: {:?}!", thread_name, o.metadata.name),
        Err(e) => println!("{} - An error occurred while creating the Pod: {}!", thread_name, e),
    }

    Ok(())
}

/*
This function deletes a Pod from the cluster.
*/
pub async fn delete_pod(thread_name: String, client: Client, pod: Pod) -> Result<(), Box<dyn Error>> {

    let pod_name = pod.metadata.name.as_ref().unwrap();
    let pod_namespace = pod.metadata.namespace.as_ref().unwrap();
    let pod_api: Api<Pod> = Api::namespaced(client.clone(), pod_namespace);
    pod_api.delete(pod_name,  &DeleteParams::default()).await?;
    println!("{} - Pod {} removed from namespace {}!", thread_name, pod_name, pod_namespace);

    Ok(())
}

/*
This function schedules a Pod on a node.

WARNING: at the moment, we only chose a random node frome those available.
*/
fn scheduler(thread_name: String, mut pod: Pod) -> Pod {
    // TODO: take node list from apiserver
    let random_number = rand::thread_rng().gen_range(1..=4);
    let node_name: &str;
    match random_number {
        1 => node_name = "orionw1",
        2 => node_name = "orionw2",
        3 => node_name = "orionw3",
        4 => node_name = "orionw4",
        _ => node_name = "orionw1" // Default
    }
    
    if let Some(spec) = pod.spec.as_mut() {
        spec.node_name = Some(node_name.to_string());
    }

    println!("{} - Pod {} scheduled on node {}!", thread_name, pod.metadata.name.as_ref().unwrap(), node_name);

    pod
}
