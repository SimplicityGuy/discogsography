use anyhow::Result;
use clap::Parser;
use std::path::PathBuf;
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
mod types;

use config::DistillerConfig;
use health::HealthServer;

/// High-performance Discogs data extractor written in Rust
#[derive(Parser, Debug)]
#[clap(author, version, about, long_about = None)]
struct Args {
    /// Path to the configuration file
    #[clap(short, long, env = "RUST_EXTRACTOR_CONFIG", default_value = "config.toml")]
    config: PathBuf,

    /// Force reprocess all files
    #[clap(short, long, env = "FORCE_REPROCESS")]
    force_reprocess: bool,

    /// Enable verbose logging
    #[clap(short, long)]
    verbose: bool,
}

#[tokio::main]
async fn main() -> Result<()> {
    let args = Args::parse();

    // Initialize tracing
    let filter = if args.verbose {
        "rust_extractor=debug,lapin=info"
    } else {
        "rust_extractor=info,lapin=warn"
    };

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
    let config = match DistillerConfig::from_env() {
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
