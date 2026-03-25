use axum::{
    Router,
    extract::State,
    http::StatusCode,
    response::Json,
    routing::{get, post},
};
use chrono::Utc;
use serde_json::json;
use std::net::SocketAddr;
use std::sync::Arc;
use std::sync::Mutex;
use tokio::sync::RwLock;
use tower_http::cors::CorsLayer;
use tower_http::trace::TraceLayer;
use tracing::{error, info};

use crate::extractor::{ExtractionStatus, ExtractorState};

/// Shared state type for all health server handlers
type AppState = (Arc<RwLock<ExtractorState>>, Arc<Mutex<Option<bool>>>);

#[derive(serde::Deserialize)]
pub struct TriggerRequest {
    #[serde(default)]
    pub force_reprocess: bool,
}

pub struct HealthServer {
    port: u16,
    state: Arc<RwLock<ExtractorState>>,
    trigger: Arc<Mutex<Option<bool>>>,
}

impl HealthServer {
    pub fn new(port: u16, state: Arc<RwLock<ExtractorState>>, trigger: Arc<Mutex<Option<bool>>>) -> Self {
        Self { port, state, trigger }
    }

    pub async fn run(self) -> anyhow::Result<()> {
        let app = Router::new()
            .route("/health", get(health_handler))
            .route("/metrics", get(metrics_handler))
            .route("/ready", get(ready_handler))
            .route("/trigger", post(trigger_handler))
            .layer(CorsLayer::permissive())
            .layer(TraceLayer::new_for_http())
            .with_state((self.state, self.trigger));

        let addr = SocketAddr::from(([0, 0, 0, 0], self.port));
        info!("🏥 Health server listening on {}", addr);

        let listener = tokio::net::TcpListener::bind(addr).await?;
        axum::serve(listener, app).await.map_err(|e| {
            error!("Health server error: {}", e);
            e.into()
        })
    }
}

async fn health_handler(State((state, _)): State<AppState>) -> (StatusCode, Json<serde_json::Value>) {
    let state = state.read().await;

    let health = json!({
        "status": "healthy",
        "service": "rust-extractor",
        "extraction_status": state.extraction_status.as_str(),
        "extraction_progress": {
            "artists": state.extraction_progress.artists,
            "labels": state.extraction_progress.labels,
            "masters": state.extraction_progress.masters,
            "releases": state.extraction_progress.releases,
            "total": state.extraction_progress.total(),
        },
        "last_extraction_time": {
            "artists": state.last_extraction_time.get(&crate::types::DataType::Artists).map(|t| t.elapsed().as_secs_f64()),
            "labels": state.last_extraction_time.get(&crate::types::DataType::Labels).map(|t| t.elapsed().as_secs_f64()),
            "masters": state.last_extraction_time.get(&crate::types::DataType::Masters).map(|t| t.elapsed().as_secs_f64()),
            "releases": state.last_extraction_time.get(&crate::types::DataType::Releases).map(|t| t.elapsed().as_secs_f64()),
        },
        "timestamp": Utc::now().to_rfc3339(),
    });

    (StatusCode::OK, Json(health))
}

async fn metrics_handler(State((state, _)): State<AppState>) -> (StatusCode, Json<serde_json::Value>) {
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

async fn ready_handler(State((state, _)): State<AppState>) -> StatusCode {
    let state = state.read().await;

    // Service is ready if it has initialized (has connections or has completed files)
    if !state.active_connections.is_empty() || !state.completed_files.is_empty() {
        StatusCode::OK
    } else {
        StatusCode::SERVICE_UNAVAILABLE
    }
}

pub async fn trigger_handler(
    State((state, trigger)): State<AppState>,
    body: Option<Json<TriggerRequest>>,
) -> (StatusCode, Json<serde_json::Value>) {
    let state = state.read().await;
    if state.extraction_status == ExtractionStatus::Running {
        return (StatusCode::CONFLICT, Json(json!({"status": "already_running"})));
    }
    drop(state);

    let force_reprocess = body.map(|b| b.force_reprocess).unwrap_or(false);

    {
        let mut t = trigger.lock().unwrap();
        *t = Some(force_reprocess);
    }
    info!("🔄 Extraction triggered via API (force_reprocess={})", force_reprocess);

    (StatusCode::ACCEPTED, Json(json!({"status": "started", "force_reprocess": force_reprocess})))
}

#[cfg(test)]
#[path = "tests/health_tests.rs"]
mod tests;
