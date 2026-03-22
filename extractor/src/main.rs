use anyhow::Result;
use clap::Parser;
use std::sync::Arc;
use tokio::signal;
use tokio::sync::RwLock;
use tracing::{error, info};

use rules::RulesConfig;

mod config;
mod downloader;
mod extractor;
mod health;
mod message_queue;
mod parser;
mod rules;
mod state_marker;
mod types;

use config::ExtractorConfig;
use health::HealthServer;

/// High-performance Discogs data extractor written in Rust
#[derive(Parser, Debug)]
#[clap(author, version, about, long_about = None)]
struct Args {
    /// Force reprocess all files
    #[clap(short, long, env = "FORCE_REPROCESS", value_parser = clap::builder::BoolishValueParser::new(), default_value_t = false)]
    force_reprocess: bool,

    /// Path to data quality rules YAML file
    #[clap(long, env = "DATA_QUALITY_RULES")]
    data_quality_rules: Option<std::path::PathBuf>,
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
    let mut config = match ExtractorConfig::from_env() {
        Ok(c) => c,
        Err(e) => {
            error!("❌ Configuration error: {}", e);
            std::process::exit(1);
        }
    };

    // CLI arg takes precedence over env var for rules path
    if args.data_quality_rules.is_some() {
        config.data_quality_rules = args.data_quality_rules;
    }

    // Load and compile data quality rules if configured
    let compiled_rules = if let Some(ref rules_path) = config.data_quality_rules {
        info!("📋 Loading data quality rules from {:?}", rules_path);
        match RulesConfig::load(rules_path) { // nosemgrep: rust.actix.path-traversal.tainted-path.tainted-path
            Ok(rules_config) => match rules::CompiledRulesConfig::compile(rules_config) {
                Ok(compiled) => {
                    info!("✅ Data quality rules loaded and compiled successfully");
                    Some(Arc::new(compiled))
                }
                Err(e) => {
                    error!("❌ Failed to compile data quality rules: {}", e);
                    std::process::exit(1);
                }
            },
            Err(e) => {
                error!("❌ Failed to load data quality rules: {}", e);
                std::process::exit(1);
            }
        }
    } else {
        None
    };

    let config = Arc::new(config);

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

    // Create factory for message queue connections
    let mq_factory: Arc<dyn extractor::MessageQueueFactory> = Arc::new(extractor::DefaultMessageQueueFactory);

    // Run the main extraction loop
    let extraction_result = extractor::run_extraction_loop(config.clone(), state.clone(), shutdown.clone(), args.force_reprocess, mq_factory, compiled_rules).await;

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

███████╗██╗  ██╗████████╗██████╗  █████╗  ██████╗████████╗ ██████╗ ██████╗
██╔════╝╚██╗██╔╝╚══██╔══╝██╔══██╗██╔══██╗██╔════╝╚══██╔══╝██╔═══██╗██╔══██╗
█████╗   ╚███╔╝    ██║   ██████╔╝███████║██║        ██║   ██║   ██║██████╔╝
██╔══╝   ██╔██╗    ██║   ██╔══██╗██╔══██║██║        ██║   ██║   ██║██╔══██╗
███████╗██╔╝ ██╗   ██║   ██║  ██║██║  ██║╚██████╗   ██║   ╚██████╔╝██║  ██║
╚══════╝╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝   ╚═╝    ╚═════╝ ╚═╝  ╚═╝
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
#[path = "tests/main_tests.rs"]
mod tests;
