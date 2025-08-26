use axum::{extract::State, http::StatusCode, response::Json, routing::get, Router};
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

async fn health_handler(
    State(state): State<Arc<RwLock<ExtractorState>>>,
) -> (StatusCode, Json<serde_json::Value>) {
    let state = state.read().await;

    let health = json!({
        "status": "healthy",
        "service": "distiller",
        "current_task": state.current_task.as_ref().map(|t| t.as_str()),
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

async fn metrics_handler(
    State(state): State<Arc<RwLock<ExtractorState>>>,
) -> (StatusCode, Json<serde_json::Value>) {
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
}
