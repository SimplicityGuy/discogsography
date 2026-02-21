use anyhow::Result;
use clap::Parser;
use std::sync::Arc;
use tokio::signal;
use tokio::sync::RwLock;
use tracing::{error, info};

mod config;
mod downloader;
mod extractor;
mod health;
mod message_queue;
mod parser;
mod state_marker;
mod types;

use config::ExtractorConfig;
use health::HealthServer;

/// High-performance Discogs data extractor written in Rust
#[derive(Parser, Debug)]
#[clap(author, version, about, long_about = None)]
struct Args {
    /// Force reprocess all files
    #[clap(short, long, env = "FORCE_REPROCESS")]
    force_reprocess: bool,
}

#[tokio::main]
async fn main() -> Result<()> {
    let args = Args::parse();

    // Initialize tracing with LOG_LEVEL environment variable
    // Supports: DEBUG, INFO, WARNING, ERROR, CRITICAL (maps to Rust's trace, debug, info, warn, error)
    let log_level = std::env::var("LOG_LEVEL").unwrap_or_else(|_| "INFO".to_string());
    let filter = build_tracing_filter(&log_level);

    tracing_subscriber::fmt()
        .with_env_filter(filter)
        .with_target(false)
        .with_thread_ids(false)
        .with_line_number(true)
        .json()
        .init();

    // Display ASCII art
    print_ascii_art();

    info!("🚀 Starting Rust-based Discogs data extractor with high performance");

    // Load configuration from environment (drop-in replacement for extractor)
    let config = match ExtractorConfig::from_env() {
        Ok(c) => Arc::new(c),
        Err(e) => {
            error!("❌ Configuration error: {}", e);
            std::process::exit(1);
        }
    };

    // Initialize shared state
    let state = Arc::new(RwLock::new(extractor::ExtractorState::default()));

    // Start health server
    let health_server = HealthServer::new(config.health_port, state.clone());
    let health_handle = tokio::spawn(async move {
        if let Err(e) = health_server.run().await {
            error!("❌ Health server error: {}", e);
        }
    });

    // Set up signal handlers
    let shutdown = setup_shutdown_handler();

    // Run the main extraction loop
    let extraction_result = extractor::run_extraction_loop(config.clone(), state.clone(), shutdown.clone(), args.force_reprocess).await;

    // Cleanup
    info!("🛑 Shutting down rust-extractor...");
    health_handle.abort();

    match extraction_result {
        Ok(_) => {
            info!("✅ Rust-extractor service shutdown complete");
            Ok(())
        }
        Err(e) => {
            error!("❌ Rust-extractor failed: {}", e);
            std::process::exit(1);
        }
    }
}

fn print_ascii_art() {
    println!(
        r#"
██████╗ ██╗███████╗ ██████╗ ██████╗  ██████╗ ███████╗
██╔══██╗██║██╔════╝██╔════╝██╔═══██╗██╔════╝ ██╔════╝
██║  ██║██║███████╗██║     ██║   ██║██║  ███╗███████╗
██║  ██║██║╚════██║██║     ██║   ██║██║   ██║╚════██║
██████╔╝██║███████║╚██████╗╚██████╔╝╚██████╔╝███████║
╚═════╝ ╚═╝╚══════╝ ╚═════╝ ╚═════╝  ╚═════╝ ╚══════╝

██████╗ ██╗   ██╗███████╗████████╗    ███████╗██╗  ██╗████████╗██████╗  █████╗  ██████╗████████╗ ██████╗ ██████╗
██╔══██╗██║   ██║██╔════╝╚══██╔══╝    ██╔════╝╚██╗██╔╝╚══██╔══╝██╔══██╗██╔══██╗██╔════╝╚══██╔══╝██╔═══██╗██╔══██╗
██████╔╝██║   ██║███████╗   ██║       █████╗   ╚███╔╝    ██║   ██████╔╝███████║██║        ██║   ██║   ██║██████╔╝
██╔══██╗██║   ██║╚════██║   ██║       ██╔══╝   ██╔██╗    ██║   ██╔══██╗██╔══██║██║        ██║   ██║   ██║██╔══██╗
██║  ██║╚██████╔╝███████║   ██║       ███████╗██╔╝ ██╗   ██║   ██║  ██║██║  ██║╚██████╗   ██║   ╚██████╔╝██║  ██║
╚═╝  ╚═╝ ╚═════╝ ╚══════╝   ╚═╝       ╚══════╝╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝   ╚═╝    ╚═════╝ ╚═╝  ╚═╝
"#
    );
    println!();
}

fn setup_shutdown_handler() -> Arc<tokio::sync::Notify> {
    let shutdown = Arc::new(tokio::sync::Notify::new());
    let shutdown_clone = shutdown.clone();

    tokio::spawn(async move {
        let _ = signal::ctrl_c().await;
        info!("🛑 Received shutdown signal");
        shutdown_clone.notify_waiters();
    });

    shutdown
}

/// Build tracing filter string from Python-style log level
fn build_tracing_filter(log_level: &str) -> String {
    let rust_level = match log_level.to_uppercase().as_str() {
        "DEBUG" => "debug",
        "INFO" => "info",
        "WARNING" | "WARN" => "warn",
        "ERROR" => "error",
        "CRITICAL" => "error",
        _ => "info",
    };
    let lapin_level = if rust_level == "debug" { "info" } else { "warn" };
    format!("extractor={},lapin={}", rust_level, lapin_level)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_build_tracing_filter_debug() {
        let filter = build_tracing_filter("debug");
        assert_eq!(filter, "extractor=debug,lapin=info");
    }

    #[test]
    fn test_build_tracing_filter_info() {
        let filter = build_tracing_filter("info");
        assert_eq!(filter, "extractor=info,lapin=warn");
    }

    #[test]
    fn test_build_tracing_filter_warn() {
        let filter = build_tracing_filter("warn");
        assert_eq!(filter, "extractor=warn,lapin=warn");
    }

    #[test]
    fn test_build_tracing_filter_error() {
        let filter = build_tracing_filter("error");
        assert_eq!(filter, "extractor=error,lapin=warn");
    }

    #[test]
    fn test_build_tracing_filter_python_levels() {
        assert_eq!(build_tracing_filter("DEBUG"), "extractor=debug,lapin=info");
        assert_eq!(build_tracing_filter("INFO"), "extractor=info,lapin=warn");
        assert_eq!(build_tracing_filter("WARNING"), "extractor=warn,lapin=warn");
        assert_eq!(build_tracing_filter("CRITICAL"), "extractor=error,lapin=warn");
        assert_eq!(build_tracing_filter("INVALID"), "extractor=info,lapin=warn");
        assert_eq!(build_tracing_filter(""), "extractor=info,lapin=warn");
    }

    #[tokio::test]
    async fn test_setup_shutdown_handler() {
        let shutdown = setup_shutdown_handler();
        // Just verify it creates a valid Notify instance
        assert!(Arc::strong_count(&shutdown) >= 1);
    }

    #[test]
    fn test_ascii_art_display() {
        // Just verify the function doesn't panic
        print_ascii_art();
    }
}
