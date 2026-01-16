use axum::{Router, extract::State, http::StatusCode, response::Json, routing::get};
use chrono::Utc;
use serde_json::json;
use std::net::SocketAddr;
use std::sync::Arc;
use tokio::sync::RwLock;
use tower_http::cors::CorsLayer;
use tower_http::trace::TraceLayer;
use tracing::{error, info};

use crate::extractor::ExtractorState;

pub struct HealthServer {
    port: u16,
    state: Arc<RwLock<ExtractorState>>,
}

impl HealthServer {
    pub fn new(port: u16, state: Arc<RwLock<ExtractorState>>) -> Self {
        Self { port, state }
    }

    pub async fn run(self) -> anyhow::Result<()> {
        let app = Router::new()
            .route("/health", get(health_handler))
            .route("/metrics", get(metrics_handler))
            .route("/ready", get(ready_handler))
            .layer(CorsLayer::permissive())
            .layer(TraceLayer::new_for_http())
            .with_state(self.state);

        let addr = SocketAddr::from(([0, 0, 0, 0], self.port));
        info!("🏥 Health server listening on {}", addr);

        let listener = tokio::net::TcpListener::bind(addr).await?;
        axum::serve(listener, app).await.map_err(|e| {
            error!("Health server error: {}", e);
            e.into()
        })
    }
}

async fn health_handler(State(state): State<Arc<RwLock<ExtractorState>>>) -> (StatusCode, Json<serde_json::Value>) {
    let state = state.read().await;

    let health = json!({
        "status": "healthy",
        "service": "rust-extractor",
        "current_task": state.current_task.as_deref(),
        "progress": state.current_progress,
        "extraction_progress": {
            "artists": state.extraction_progress.artists,
            "labels": state.extraction_progress.labels,
            "masters": state.extraction_progress.masters,
            "releases": state.extraction_progress.releases,
            "total": state.extraction_progress.total(),
        },
        "last_extraction_time": {
            "artists": state.last_extraction_time.get(&crate::types::DataType::Artists).copied().unwrap_or(0.0),
            "labels": state.last_extraction_time.get(&crate::types::DataType::Labels).copied().unwrap_or(0.0),
            "masters": state.last_extraction_time.get(&crate::types::DataType::Masters).copied().unwrap_or(0.0),
            "releases": state.last_extraction_time.get(&crate::types::DataType::Releases).copied().unwrap_or(0.0),
        },
        "timestamp": Utc::now().to_rfc3339(),
    });

    (StatusCode::OK, Json(health))
}

async fn metrics_handler(State(state): State<Arc<RwLock<ExtractorState>>>) -> (StatusCode, Json<serde_json::Value>) {
    let state = state.read().await;

    let metrics = json!({
        "extraction_progress_artists": state.extraction_progress.artists,
        "extraction_progress_labels": state.extraction_progress.labels,
        "extraction_progress_masters": state.extraction_progress.masters,
        "extraction_progress_releases": state.extraction_progress.releases,
        "extraction_progress_total": state.extraction_progress.total(),
        "completed_files": state.completed_files.len(),
        "active_connections": state.active_connections.len(),
        "error_count": state.error_count,
    });

    (StatusCode::OK, Json(metrics))
}

async fn ready_handler(State(state): State<Arc<RwLock<ExtractorState>>>) -> StatusCode {
    let state = state.read().await;

    // Service is ready if it has initialized (has connections or has completed files)
    if !state.active_connections.is_empty() || !state.completed_files.is_empty() {
        StatusCode::OK
    } else {
        StatusCode::SERVICE_UNAVAILABLE
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::extractor::ExtractorState;
    use crate::types::DataType;

    #[tokio::test]
    async fn test_ready_handler_not_ready() {
        let state = Arc::new(RwLock::new(ExtractorState::default()));
        let status = ready_handler(State(state)).await;
        assert_eq!(status, StatusCode::SERVICE_UNAVAILABLE);
    }

    #[tokio::test]
    async fn test_ready_handler_ready() {
        let state = Arc::new(RwLock::new(ExtractorState::default()));
        {
            let mut s = state.write().await;
            s.completed_files.insert("test.xml".to_string());
        }
        let status = ready_handler(State(state)).await;
        assert_eq!(status, StatusCode::OK);
    }

    #[tokio::test]
    async fn test_ready_handler_with_active_connections() {
        let state = Arc::new(RwLock::new(ExtractorState::default()));
        {
            let mut s = state.write().await;
            s.active_connections.insert(DataType::Artists, "test.xml".to_string());
        }
        let status = ready_handler(State(state)).await;
        assert_eq!(status, StatusCode::OK);
    }

    #[tokio::test]
    async fn test_health_handler_default_state() {
        let state = Arc::new(RwLock::new(ExtractorState::default()));
        let (status, json) = health_handler(State(state)).await;

        assert_eq!(status, StatusCode::OK);

        let value = json.0;
        assert_eq!(value["status"], "healthy");
        assert_eq!(value["service"], "rust-extractor");
        assert!(value["current_task"].is_null());
        assert_eq!(value["progress"], 0.0);
        assert_eq!(value["extraction_progress"]["total"], 0);
    }

    #[tokio::test]
    async fn test_health_handler_with_progress() {
        let state = Arc::new(RwLock::new(ExtractorState::default()));
        {
            let mut s = state.write().await;
            s.current_task = Some("Processing artists".to_string());
            s.current_progress = 0.5;
            s.extraction_progress.artists = 100;
            s.extraction_progress.labels = 50;
            s.last_extraction_time.insert(DataType::Artists, 1.5);
        }

        let (status, json) = health_handler(State(state)).await;

        assert_eq!(status, StatusCode::OK);

        let value = json.0;
        assert_eq!(value["status"], "healthy");
        assert_eq!(value["current_task"], "Processing artists");
        assert_eq!(value["progress"], 0.5);
        assert_eq!(value["extraction_progress"]["artists"], 100);
        assert_eq!(value["extraction_progress"]["labels"], 50);
        assert_eq!(value["extraction_progress"]["total"], 150);
        assert_eq!(value["last_extraction_time"]["artists"], 1.5);
    }

    #[tokio::test]
    async fn test_metrics_handler_default_state() {
        let state = Arc::new(RwLock::new(ExtractorState::default()));
        let (status, json) = metrics_handler(State(state)).await;

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

        let (status, json) = metrics_handler(State(state)).await;

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
        let server = HealthServer::new(8000, state.clone());

        assert_eq!(server.port, 8000);
    }

    #[tokio::test]
    async fn test_health_json_format() {
        let state = Arc::new(RwLock::new(ExtractorState::default()));
        {
            let mut s = state.write().await;
            s.extraction_progress.artists = 10;
        }

        let (_, json) = health_handler(State(state)).await;
        let value = json.0;

        // Verify JSON structure
        assert!(value.get("status").is_some());
        assert!(value.get("service").is_some());
        assert!(value.get("current_task").is_some());
        assert!(value.get("progress").is_some());
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
    async fn test_metrics_json_format() {
        let state = Arc::new(RwLock::new(ExtractorState::default()));
        let (_, json) = metrics_handler(State(state)).await;
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
}
