use super::*;
use crate::extractor::{ExtractionStatus, ExtractorState};
use crate::types::DataType;
use tokio::sync::Mutex;

#[tokio::test]
async fn test_ready_handler_not_ready() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let trigger = Arc::new(Mutex::new(None::<bool>));
    let status = ready_handler(State((state, trigger))).await;
    assert_eq!(status, StatusCode::SERVICE_UNAVAILABLE);
}

#[tokio::test]
async fn test_ready_handler_ready() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    {
        let mut s = state.write().await;
        s.completed_files.insert("test.xml".to_string());
    }
    let trigger = Arc::new(Mutex::new(None::<bool>));
    let status = ready_handler(State((state, trigger))).await;
    assert_eq!(status, StatusCode::OK);
}

#[tokio::test]
async fn test_ready_handler_with_active_connections() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    {
        let mut s = state.write().await;
        s.active_connections.insert(DataType::Artists, "test.xml".to_string());
    }
    let trigger = Arc::new(Mutex::new(None::<bool>));
    let status = ready_handler(State((state, trigger))).await;
    assert_eq!(status, StatusCode::OK);
}

#[tokio::test]
async fn test_health_handler_default_state() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let trigger = Arc::new(Mutex::new(None::<bool>));
    let (status, json) = health_handler(State((state, trigger))).await;

    assert_eq!(status, StatusCode::OK);

    let value = json.0;
    assert_eq!(value["status"], "healthy");
    assert_eq!(value["service"], "rust-extractor");
    assert_eq!(value["extraction_progress"]["total"], 0);
    // With no extraction activity, last_extraction_time values should be null
    assert!(value["last_extraction_time"]["artists"].is_null());
}

#[tokio::test]
async fn test_health_handler_with_progress() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    {
        let mut s = state.write().await;
        s.extraction_progress.artists = 100;
        s.extraction_progress.labels = 50;
        s.last_extraction_time.insert(DataType::Artists, std::time::Instant::now());
    }

    let trigger = Arc::new(Mutex::new(None::<bool>));
    let (status, json) = health_handler(State((state, trigger))).await;

    assert_eq!(status, StatusCode::OK);

    let value = json.0;
    assert_eq!(value["status"], "healthy");
    assert_eq!(value["extraction_progress"]["artists"], 100);
    assert_eq!(value["extraction_progress"]["labels"], 50);
    assert_eq!(value["extraction_progress"]["total"], 150);
    // Should be a small number of seconds elapsed since Instant::now()
    assert!(value["last_extraction_time"]["artists"].is_number());
    assert!(value["last_extraction_time"]["labels"].is_null());
}

#[tokio::test]
async fn test_metrics_handler_default_state() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let trigger = Arc::new(Mutex::new(None::<bool>));
    let (status, json) = metrics_handler(State((state, trigger))).await;

    assert_eq!(status, StatusCode::OK);

    let value = json.0;
    assert_eq!(value["extraction_progress_total"], 0);
    assert_eq!(value["completed_files"], 0);
    assert_eq!(value["active_connections"], 0);
    assert_eq!(value["error_count"], 0);
}

#[tokio::test]
async fn test_metrics_handler_with_data() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    {
        let mut s = state.write().await;
        s.extraction_progress.artists = 1000;
        s.extraction_progress.labels = 500;
        s.extraction_progress.masters = 300;
        s.extraction_progress.releases = 2000;
        s.completed_files.insert("file1.xml".to_string());
        s.completed_files.insert("file2.xml".to_string());
        s.active_connections.insert(DataType::Artists, "file3.xml".to_string());
        s.error_count = 5;
    }

    let trigger = Arc::new(Mutex::new(None::<bool>));
    let (status, json) = metrics_handler(State((state, trigger))).await;

    assert_eq!(status, StatusCode::OK);

    let value = json.0;
    assert_eq!(value["extraction_progress_artists"], 1000);
    assert_eq!(value["extraction_progress_labels"], 500);
    assert_eq!(value["extraction_progress_masters"], 300);
    assert_eq!(value["extraction_progress_releases"], 2000);
    assert_eq!(value["extraction_progress_total"], 3800);
    assert_eq!(value["completed_files"], 2);
    assert_eq!(value["active_connections"], 1);
    assert_eq!(value["error_count"], 5);
}

#[tokio::test]
async fn test_health_server_new() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let trigger = Arc::new(Mutex::new(None::<bool>));
    let server = HealthServer::new(8000, state.clone(), trigger);

    assert_eq!(server.port, 8000);
}

#[tokio::test]
async fn test_health_json_format() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    {
        let mut s = state.write().await;
        s.extraction_progress.artists = 10;
    }

    let trigger = Arc::new(Mutex::new(None::<bool>));
    let (_, json) = health_handler(State((state, trigger))).await;
    let value = json.0;

    // Verify JSON structure
    assert!(value.get("status").is_some());
    assert!(value.get("service").is_some());
    assert!(value.get("extraction_status").is_some());
    assert!(value.get("extraction_progress").is_some());
    assert!(value.get("last_extraction_time").is_some());
    assert!(value.get("timestamp").is_some());

    // Verify nested structure
    let extraction = &value["extraction_progress"];
    assert!(extraction.get("artists").is_some());
    assert!(extraction.get("labels").is_some());
    assert!(extraction.get("masters").is_some());
    assert!(extraction.get("releases").is_some());
    assert!(extraction.get("total").is_some());
}

#[tokio::test]
async fn test_health_server_run_and_endpoints() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    {
        let mut s = state.write().await;
        s.completed_files.insert("test.xml".to_string());
    }

    // Use a high port unlikely to conflict
    let port = 19876u16;
    let trigger = Arc::new(Mutex::new(None::<bool>));
    let server = HealthServer::new(port, state.clone(), trigger);

    // Spawn the actual server.run() method
    let handle = tokio::spawn(async move {
        server.run().await.unwrap();
    });

    // Give the server a moment to start
    tokio::time::sleep(tokio::time::Duration::from_millis(100)).await;

    let base_url = format!("http://127.0.0.1:{}", port);

    // Test /health endpoint
    let resp = reqwest::get(format!("{}/health", base_url)).await.unwrap();
    assert_eq!(resp.status(), 200);
    let text = resp.text().await.unwrap();
    let body: serde_json::Value = serde_json::from_str(&text).unwrap();
    assert_eq!(body["status"], "healthy");
    assert_eq!(body["service"], "rust-extractor");
    assert_eq!(body["extraction_status"], "idle");

    // Test /metrics endpoint
    let resp = reqwest::get(format!("{}/metrics", base_url)).await.unwrap();
    assert_eq!(resp.status(), 200);
    let text = resp.text().await.unwrap();
    let body: serde_json::Value = serde_json::from_str(&text).unwrap();
    assert_eq!(body["completed_files"], 1);

    // Test /ready endpoint (should be 200 since we added a completed file)
    let resp = reqwest::get(format!("{}/ready", base_url)).await.unwrap();
    assert_eq!(resp.status(), 200);

    // Clean up
    handle.abort();
}

#[tokio::test]
async fn test_ready_handler_transitions() {
    // Start with empty state — should be unavailable
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let trigger = Arc::new(Mutex::new(None::<bool>));
    let status = ready_handler(State((state.clone(), trigger.clone()))).await;
    assert_eq!(status, StatusCode::SERVICE_UNAVAILABLE);

    // Add a completed file — should become ready
    {
        let mut s = state.write().await;
        s.completed_files.insert("discogs_20260101_artists.xml.gz".to_string());
    }
    let status = ready_handler(State((state.clone(), trigger))).await;
    assert_eq!(status, StatusCode::OK);
}

#[tokio::test]
async fn test_metrics_json_format() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let trigger = Arc::new(Mutex::new(None::<bool>));
    let (_, json) = metrics_handler(State((state, trigger))).await;
    let value = json.0;

    // Verify all required metrics are present
    assert!(value.get("extraction_progress_artists").is_some());
    assert!(value.get("extraction_progress_labels").is_some());
    assert!(value.get("extraction_progress_masters").is_some());
    assert!(value.get("extraction_progress_releases").is_some());
    assert!(value.get("extraction_progress_total").is_some());
    assert!(value.get("completed_files").is_some());
    assert!(value.get("active_connections").is_some());
    assert!(value.get("error_count").is_some());
}

#[tokio::test]
async fn test_trigger_handler_success() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let trigger = Arc::new(Mutex::new(None::<bool>));
    let (status, json) = trigger_handler(State((state, trigger.clone())), None).await;
    assert_eq!(status, StatusCode::ACCEPTED);
    assert_eq!(json.0["status"], "started");
    assert_eq!(json.0["force_reprocess"], false);
    assert_eq!(*trigger.lock().await, Some(false));
}

#[tokio::test]
async fn test_trigger_handler_already_running() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    {
        let mut s = state.write().await;
        s.extraction_status = ExtractionStatus::Running;
    }
    let trigger = Arc::new(Mutex::new(None::<bool>));
    let (status, json) = trigger_handler(State((state, trigger.clone())), None).await;
    assert_eq!(status, StatusCode::CONFLICT);
    assert_eq!(json.0["status"], "already_running");
    assert_eq!(*trigger.lock().await, None);
}

#[tokio::test]
async fn test_trigger_handler_force_reprocess() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let trigger = Arc::new(Mutex::new(None::<bool>));
    let body = Some(Json(TriggerRequest { force_reprocess: true }));
    let (status, json) = trigger_handler(State((state, trigger.clone())), body).await;
    assert_eq!(status, StatusCode::ACCEPTED);
    assert_eq!(json.0["status"], "started");
    assert_eq!(json.0["force_reprocess"], true);
    assert_eq!(*trigger.lock().await, Some(true));
}

#[tokio::test]
async fn test_health_includes_extraction_status() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let trigger = Arc::new(Mutex::new(None::<bool>));
    let (_, json) = health_handler(State((state, trigger))).await;
    assert_eq!(json.0["extraction_status"], "idle");
}

#[tokio::test]
async fn test_health_extraction_status_running() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    {
        let mut s = state.write().await;
        s.extraction_status = ExtractionStatus::Running;
    }
    let trigger = Arc::new(Mutex::new(None::<bool>));
    let (_, json) = health_handler(State((state, trigger))).await;
    assert_eq!(json.0["extraction_status"], "running");
}

#[tokio::test]
async fn test_health_extraction_status_waiting() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    {
        let mut s = state.write().await;
        s.extraction_status = ExtractionStatus::Waiting;
    }
    let trigger = Arc::new(Mutex::new(None::<bool>));
    let (_, json) = health_handler(State((state, trigger))).await;
    assert_eq!(json.0["extraction_status"], "waiting");
}

#[tokio::test]
async fn test_health_extraction_status_completed() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    {
        let mut s = state.write().await;
        s.extraction_status = ExtractionStatus::Completed;
    }
    let trigger = Arc::new(Mutex::new(None::<bool>));
    let (_, json) = health_handler(State((state, trigger))).await;
    assert_eq!(json.0["extraction_status"], "completed");
}
