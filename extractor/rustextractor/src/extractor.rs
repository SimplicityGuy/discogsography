use anyhow::{Context, Result};
// use chrono::{DateTime, Utc}; // Not directly used in this module
use std::collections::{HashMap, HashSet};
use std::path::PathBuf;
use std::str::FromStr;
use std::sync::Arc;
use std::time::Instant;
use tokio::sync::{RwLock, mpsc};
use tokio::time::{Duration, sleep};
// use tokio::select; // Not needed with current implementation
use tracing::{debug, error, info, warn};

use crate::config::ExtractorConfig;
use crate::downloader::Downloader;
use crate::message_queue::MessageQueue;
use crate::parser::XmlParser;
use crate::types::{DataMessage, DataType, ExtractionProgress, ProcessingState};

/// State shared across the extractor
#[derive(Debug, Default)]
pub struct ExtractorState {
    pub current_task: Option<String>,
    pub current_progress: f64,
    pub extraction_progress: ExtractionProgress,
    pub last_extraction_time: HashMap<DataType, f64>,
    pub completed_files: HashSet<String>,
    pub active_connections: HashMap<DataType, String>,
    pub error_count: u64,
}

/// Process Discogs data files
pub async fn process_discogs_data(
    config: Arc<ExtractorConfig>,
    state: Arc<RwLock<ExtractorState>>,
    shutdown: Arc<tokio::sync::Notify>,
    force_reprocess: bool,
) -> Result<bool> {
    // Reset progress for new run
    {
        let mut s = state.write().await;
        s.extraction_progress = ExtractionProgress::default();
        s.last_extraction_time.clear();
        s.completed_files.clear();
        s.active_connections.clear();
        s.error_count = 0;
    }

    // Download latest data
    let mut downloader = Downloader::new(config.discogs_root.clone()).await?;
    let data_files = downloader.download_discogs_data().await.context("Failed to download Discogs data")?;

    // Filter out checksum files
    let data_files: Vec<_> = data_files.into_iter().filter(|f| !f.contains("CHECKSUM")).collect();

    if data_files.is_empty() {
        warn!("⚠️ No data files to process");
        return Ok(true);
    }

    // Check processing state
    let processing_state_path = config.discogs_root.join(".processing_state.json");
    let processing_state = load_processing_state(&processing_state_path).await?;

    let mut files_to_process = Vec::new();
    for file in &data_files {
        if force_reprocess || !processing_state.is_processed(file) {
            files_to_process.push(file.clone());
            info!("📋 Will process: {}", file);
        } else {
            info!("✅ Already processed: {}", file);
        }
    }

    if files_to_process.is_empty() && !force_reprocess {
        info!("✅ All files have been processed previously");
        return Ok(true);
    }

    // Process files concurrently
    let semaphore = Arc::new(tokio::sync::Semaphore::new(3)); // Limit concurrent files
    let mut tasks = Vec::new();

    for file in files_to_process {
        let config = config.clone();
        let state = state.clone();
        let shutdown = shutdown.clone();
        let semaphore = semaphore.clone();
        let processing_state_path = processing_state_path.clone();

        let task: tokio::task::JoinHandle<Result<()>> = tokio::spawn(async move {
            let _permit = semaphore.acquire().await?;

            // Check for shutdown - skip if notified
            // For now, we'll skip the shutdown check here since tokio::sync::Notify
            // doesn't have a non-consuming check method

            process_single_file(&file, config, state, shutdown).await?;

            // Mark as processed
            let mut ps = load_processing_state(&processing_state_path).await?;
            ps.mark_processed(&file);
            save_processing_state(&processing_state_path, &ps).await?;

            info!("✅ Marked {} as processed", file);
            Ok(())
        });

        tasks.push(task);
    }

    // Start progress reporter
    let reporter_state = state.clone();
    let reporter_shutdown = shutdown.clone();
    let reporter = tokio::spawn(async move {
        progress_reporter(reporter_state, reporter_shutdown).await;
    });

    // Wait for all tasks
    let mut success = true;
    for (i, task) in tasks.into_iter().enumerate() {
        match task.await {
            Ok(Ok(_)) => {}
            Ok(Err(e)) => {
                error!("❌ File processing failed: {}", e);
                success = false;
            }
            Err(e) => {
                error!("❌ Task {} panicked: {}", i, e);
                success = false;
            }
        }
    }

    reporter.abort();

    // Log completion
    let s = state.read().await;
    if !s.completed_files.is_empty() {
        info!("🎉 All processing complete! Finished files: {:?}", s.completed_files);
        info!("📊 Final statistics: {} total records extracted", s.extraction_progress.total());
    }

    Ok(success)
}

/// Process a single file
async fn process_single_file(
    file_name: &str,
    config: Arc<ExtractorConfig>,
    state: Arc<RwLock<ExtractorState>>,
    _shutdown: Arc<tokio::sync::Notify>,
) -> Result<()> {
    // Extract data type from filename
    let data_type = extract_data_type(file_name).ok_or_else(|| anyhow::anyhow!("Invalid file format: {}", file_name))?;

    info!("🚀 Starting extraction of {} from {}", data_type, file_name);

    // Connect to message queue
    let mq = Arc::new(MessageQueue::new(&config.amqp_connection, 3).await.context("Failed to connect to message queue")?);

    // Setup queues for this data type
    mq.setup_queues(data_type).await?;

    // Track active connection
    {
        let mut s = state.write().await;
        s.active_connections.insert(data_type, file_name.to_string());
    }

    // Create channels for processing pipeline
    let (parse_sender, parse_receiver) = mpsc::channel::<DataMessage>(config.queue_size);
    let (batch_sender, batch_receiver) = mpsc::channel::<Vec<DataMessage>>(100);

    // Start workers
    let parser_handle = tokio::spawn({
        let file_path = config.discogs_root.join(file_name);
        async move {
            let parser = XmlParser::new(data_type, parse_sender);
            parser.parse_file(&file_path).await
        }
    });

    let batcher_handle = tokio::spawn({
        let batch_size = config.batch_size;
        let state = state.clone();
        async move { message_batcher(parse_receiver, batch_sender, batch_size, data_type, state).await }
    });

    let publisher_handle = tokio::spawn({
        let mq = mq.clone();
        let state = state.clone();
        async move { message_publisher(batch_receiver, mq, data_type, state).await }
    });

    // Wait for all workers to complete
    let total_count = parser_handle.await??;
    batcher_handle.await??;
    publisher_handle.await??;

    // Send file completion message
    mq.send_file_complete(data_type, file_name, total_count).await?;

    // Clean up
    mq.close().await?;

    // Update state
    {
        let mut s = state.write().await;
        s.completed_files.insert(file_name.to_string());
        s.active_connections.remove(&data_type);
    }

    info!("✅ Completed processing {} with {} records", file_name, total_count);
    Ok(())
}

/// Batch messages for efficient publishing
async fn message_batcher(
    mut receiver: mpsc::Receiver<DataMessage>,
    sender: mpsc::Sender<Vec<DataMessage>>,
    batch_size: usize,
    data_type: DataType,
    state: Arc<RwLock<ExtractorState>>,
) -> Result<()> {
    let mut batch = Vec::with_capacity(batch_size);
    let mut last_flush = Instant::now();

    loop {
        // Try to receive with timeout
        match tokio::time::timeout(Duration::from_millis(100), receiver.recv()).await {
            Ok(Some(message)) => {
                batch.push(message);

                // Update progress
                {
                    let mut s = state.write().await;
                    s.extraction_progress.increment(data_type);
                    s.last_extraction_time.insert(data_type, Instant::now().elapsed().as_secs_f64());
                }

                // Send batch if full
                if batch.len() >= batch_size {
                    let messages = std::mem::replace(&mut batch, Vec::with_capacity(batch_size));
                    sender.send(messages).await?;
                    last_flush = Instant::now();
                }
            }
            Ok(None) => {
                // Channel closed, send remaining messages
                if !batch.is_empty() {
                    sender.send(batch).await?;
                }
                break;
            }
            Err(_) => {
                // Timeout, check if we should flush
                if !batch.is_empty() && last_flush.elapsed() > Duration::from_secs(1) {
                    let messages = std::mem::replace(&mut batch, Vec::with_capacity(batch_size));
                    sender.send(messages).await?;
                    last_flush = Instant::now();
                }
            }
        }
    }

    Ok(())
}

/// Publish batched messages to AMQP
async fn message_publisher(
    mut receiver: mpsc::Receiver<Vec<DataMessage>>,
    mq: Arc<MessageQueue>,
    data_type: DataType,
    state: Arc<RwLock<ExtractorState>>,
) -> Result<()> {
    while let Some(batch) = receiver.recv().await {
        match mq.publish_batch(batch, data_type).await {
            Ok(_) => {
                debug!("✅ Published batch to AMQP");
            }
            Err(e) => {
                error!("❌ Failed to publish batch: {}", e);
                let mut s = state.write().await;
                s.error_count += 1;
            }
        }
    }

    Ok(())
}

/// Progress reporter task
async fn progress_reporter(state: Arc<RwLock<ExtractorState>>, shutdown: Arc<tokio::sync::Notify>) {
    let mut report_count = 0;

    loop {
        // Check for shutdown will be handled by select! below

        // Sleep interval
        let interval = if report_count < 3 { Duration::from_secs(10) } else { Duration::from_secs(30) };

        tokio::select! {
            _ = sleep(interval) => {},
            _ = shutdown.notified() => break,
        }

        report_count += 1;

        let s = state.read().await;
        let total = s.extraction_progress.total();

        // Check for stalled extractors
        let current_time = Instant::now().elapsed().as_secs_f64();
        let mut stalled = Vec::new();

        for (data_type, last_time) in &s.last_extraction_time {
            if !s.completed_files.contains(&format!("discogs_*_{}.xml.gz", data_type)) && *last_time > 0.0 && (current_time - last_time) > 120.0 {
                stalled.push(data_type.to_string());
            }
        }

        if !stalled.is_empty() {
            warn!("⚠️ Stalled extractors detected: {:?}", stalled);
        }

        // Log progress
        info!(
            "📊 Extraction Progress: {} total records (Artists: {}, Labels: {}, Masters: {}, Releases: {})",
            total, s.extraction_progress.artists, s.extraction_progress.labels, s.extraction_progress.masters, s.extraction_progress.releases
        );

        if !s.completed_files.is_empty() {
            info!("🎉 Completed files: {:?}", s.completed_files);
        }

        if !s.active_connections.is_empty() {
            info!("🔗 Active connections: {:?}", s.active_connections.keys().collect::<Vec<_>>());
        }
    }
}

/// Extract data type from filename
fn extract_data_type(filename: &str) -> Option<DataType> {
    // Format: discogs_YYYYMMDD_datatype.xml.gz
    let parts: Vec<&str> = filename.split('_').collect();
    if parts.len() >= 3 {
        let type_part = parts[2].split('.').next()?;
        DataType::from_str(type_part).ok()
    } else {
        None
    }
}

/// Load processing state from file
async fn load_processing_state(path: &PathBuf) -> Result<ProcessingState> {
    if !path.exists() {
        return Ok(ProcessingState::default());
    }

    let json = tokio::fs::read_to_string(path).await?;
    Ok(serde_json::from_str(&json)?)
}

/// Save processing state to file
async fn save_processing_state(path: &PathBuf, state: &ProcessingState) -> Result<()> {
    let json = serde_json::to_string_pretty(state)?;
    tokio::fs::write(path, json).await?;
    Ok(())
}

/// Main extraction loop with periodic checks
pub async fn run_extraction_loop(
    config: Arc<ExtractorConfig>,
    state: Arc<RwLock<ExtractorState>>,
    shutdown: Arc<tokio::sync::Notify>,
    force_reprocess: bool,
) -> Result<()> {
    info!("📥 Starting initial data processing...");

    // Process initial data
    let success = process_discogs_data(config.clone(), state.clone(), shutdown.clone(), force_reprocess).await?;

    if !success {
        error!("❌ Initial data processing failed");
        return Err(anyhow::anyhow!("Initial data processing failed"));
    }

    info!("✅ Initial data processing completed successfully");

    // Start periodic check loop
    loop {
        let check_interval = Duration::from_secs(config.periodic_check_days * 24 * 60 * 60);
        info!("⏰ Waiting {} days before next check...", config.periodic_check_days);

        tokio::select! {
            _ = sleep(check_interval) => {
                info!("🔄 Starting periodic check for new or updated Discogs files...");
                let start = Instant::now();

                match process_discogs_data(config.clone(), state.clone(), shutdown.clone(), false).await {
                    Ok(true) => {
                        info!("✅ Periodic check completed successfully in {:?}", start.elapsed());
                    }
                    Ok(false) => {
                        error!("❌ Periodic check completed with errors");
                    }
                    Err(e) => {
                        error!("❌ Periodic check failed: {}", e);
                    }
                }
            }
            _ = shutdown.notified() => {
                info!("🛑 Shutdown requested, stopping periodic checks");
                break;
            }
        }
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_extract_data_type() {
        assert_eq!(extract_data_type("discogs_20241201_artists.xml.gz"), Some(DataType::Artists));
        assert_eq!(extract_data_type("discogs_20241201_labels.xml.gz"), Some(DataType::Labels));
        assert_eq!(extract_data_type("invalid_format.xml"), None);
    }
}
