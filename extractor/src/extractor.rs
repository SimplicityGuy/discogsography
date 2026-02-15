use anyhow::{Context, Result};
// use chrono::{DateTime, Utc}; // Not directly used in this module
use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
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
use crate::state_marker::{PhaseStatus, ProcessingDecision, StateMarker};
use crate::types::{DataMessage, DataType, ExtractionProgress};

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

    // Create downloader
    let mut downloader = Downloader::new(config.discogs_root.clone()).await?;

    // Get file list to determine version
    let available_files = downloader.list_s3_files().await.context("Failed to list S3 files")?;
    let latest_files = downloader.get_latest_monthly_files(&available_files)?;

    if latest_files.is_empty() {
        warn!("⚠️ No data files found");
        return Ok(true);
    }

    // Extract version from first filename
    let first_filename = Path::new(&latest_files[0].name)
        .file_name()
        .and_then(|n| n.to_str())
        .ok_or_else(|| anyhow::anyhow!("Invalid filename"))?;
    let version = extract_version_from_filename(first_filename).ok_or_else(|| anyhow::anyhow!("Could not extract version from filename"))?;

    info!("📋 Detected Discogs data version: {}", version);

    // Load or create state marker
    let marker_path = StateMarker::file_path(&config.discogs_root, &version);
    let mut state_marker = if force_reprocess {
        info!("🔄 Force reprocess requested, creating new state marker");
        StateMarker::new(version.clone())
    } else {
        StateMarker::load(&marker_path).await?.unwrap_or_else(|| StateMarker::new(version.clone()))
    };

    // Check what to do based on state marker
    let decision = state_marker.should_process();

    match decision {
        ProcessingDecision::Skip => {
            info!("✅ Version {} already processed, skipping", version);
            return Ok(true);
        }
        ProcessingDecision::Reprocess => {
            warn!("⚠️ Will re-download and re-process version {}", version);
            state_marker = StateMarker::new(version.clone());
        }
        ProcessingDecision::Continue => {
            info!("🔄 Will continue processing version {}", version);
        }
    }

    // Pass state marker to downloader for tracking download progress
    downloader = downloader.with_state_marker(state_marker, marker_path.clone());

    // Download latest data (this will now track timestamps properly)
    let data_files = downloader.download_discogs_data().await.context("Failed to download Discogs data")?;

    // Get state marker back from downloader
    let mut state_marker = downloader.state_marker.take().unwrap();

    // Filter out checksum files
    let data_files: Vec<_> = data_files.into_iter().filter(|f| !f.contains("CHECKSUM")).collect();

    if data_files.is_empty() {
        warn!("⚠️ No data files to process");
        return Ok(true);
    }

    // Start processing phase
    if state_marker.processing_phase.status != PhaseStatus::Completed {
        state_marker.start_processing(data_files.len());
        state_marker.save(&marker_path).await?;
        info!("🚀 Starting processing phase: {} total files", data_files.len());
    }

    // Get list of files that still need processing
    let pending_files = state_marker.pending_files(&data_files);

    if pending_files.is_empty() {
        info!("✅ All files already processed");
        state_marker.complete_processing();
        state_marker.complete_extraction();
        state_marker.save(&marker_path).await?;
        return Ok(true);
    }

    info!("📋 Files to process: total={}, pending={}, completed={}", data_files.len(), pending_files.len(), data_files.len() - pending_files.len());

    debug!("📋 Pending files list: {:?}", pending_files);

    // Process files concurrently
    let semaphore = Arc::new(tokio::sync::Semaphore::new(3)); // Limit concurrent files
    let mut tasks = Vec::new();
    let state_marker_arc = Arc::new(tokio::sync::Mutex::new(state_marker));

    for (idx, file) in pending_files.iter().enumerate() {
        debug!("📋 Spawning task {} for file: {}", idx, file);
        let file = file.clone(); // Clone the filename string
        let config = config.clone();
        let state = state.clone();
        let shutdown = shutdown.clone();
        let semaphore = semaphore.clone();
        let marker_path = marker_path.clone();
        let state_marker_arc = state_marker_arc.clone();

        let task: tokio::task::JoinHandle<Result<()>> = tokio::spawn(async move {
            let _permit = semaphore.acquire().await?;

            // Check for shutdown - skip if notified
            // For now, we'll skip the shutdown check here since tokio::sync::Notify
            // doesn't have a non-consuming check method

            process_single_file(&file, config, state, shutdown, state_marker_arc.clone(), marker_path.clone()).await?;

            info!("✅ Completed processing: {}", file);
            Ok(())
        });

        tasks.push(task);
    }

    info!("📋 Spawned {} tasks for processing", tasks.len());

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

    // Mark processing as complete
    let mut state_marker = state_marker_arc.lock().await;
    state_marker.complete_processing();
    state_marker.complete_extraction();
    state_marker.save(&marker_path).await?;
    info!("✅ Processing phase completed: version {}", state_marker.current_version);

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
    state_marker: Arc<tokio::sync::Mutex<StateMarker>>,
    marker_path: PathBuf,
) -> Result<()> {
    // Extract data type from filename
    let data_type = extract_data_type(file_name).ok_or_else(|| anyhow::anyhow!("Invalid file format: {}", file_name))?;

    info!("🚀 Starting extraction of {} from {}", data_type, file_name);

    // Mark file processing as started in state marker
    {
        let mut marker = state_marker.lock().await;
        marker.start_file_processing(file_name);
        marker.save(&marker_path).await?;
        info!("📋 Started file processing in state marker: {}", file_name);
    }

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
        let batcher_config = BatcherConfig {
            batch_size: config.batch_size,
            data_type,
            state: state.clone(),
            state_marker: state_marker.clone(),
            marker_path: marker_path.clone(),
            file_name: file_name.to_string(),
            state_save_interval: config.state_save_interval,
        };
        async move { message_batcher(parse_receiver, batch_sender, batcher_config).await }
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

    // Mark file as completed in state marker FIRST (consistent with Python)
    {
        let mut marker = state_marker.lock().await;
        marker.complete_file_processing(file_name, total_count);
        marker.save(&marker_path).await?;
        info!("✅ Completed file processing in state marker: {} ({} records)", file_name, total_count);
    }

    // Update state
    {
        let mut s = state.write().await;
        s.completed_files.insert(file_name.to_string());
        s.active_connections.remove(&data_type);
    }

    // THEN send file completion message (consistent with Python)
    mq.send_file_complete(data_type, file_name, total_count).await?;

    // Clean up
    mq.close().await?;

    info!("✅ Completed processing {} with {} records", file_name, total_count);
    Ok(())
}

/// Configuration for message batcher
pub struct BatcherConfig {
    pub batch_size: usize,
    pub data_type: DataType,
    pub state: Arc<RwLock<ExtractorState>>,
    pub state_marker: Arc<tokio::sync::Mutex<StateMarker>>,
    pub marker_path: PathBuf,
    pub file_name: String,
    pub state_save_interval: usize,
}

/// Batch messages for efficient publishing
pub async fn message_batcher(mut receiver: mpsc::Receiver<DataMessage>, sender: mpsc::Sender<Vec<DataMessage>>, config: BatcherConfig) -> Result<()> {
    let BatcherConfig { batch_size, data_type, state, state_marker, marker_path, file_name, state_save_interval } = config;
    let mut batch = Vec::with_capacity(batch_size);
    let mut last_flush = Instant::now();
    let mut total_records = 0u64;
    let mut total_batches = 0u64;
    let mut last_state_save = 0u64;

    loop {
        // Try to receive with timeout
        match tokio::time::timeout(Duration::from_millis(100), receiver.recv()).await {
            Ok(Some(message)) => {
                batch.push(message);
                total_records += 1;

                // Update progress
                {
                    let mut s = state.write().await;
                    s.extraction_progress.increment(data_type);
                    s.last_extraction_time.insert(data_type, Instant::now().elapsed().as_secs_f64());
                }

                // Save state marker periodically
                if total_records.is_multiple_of(state_save_interval as u64) && total_records != last_state_save {
                    last_state_save = total_records;
                    let mut marker = state_marker.lock().await;
                    marker.update_file_progress(&file_name, total_records, total_records, total_batches);
                    if let Err(e) = marker.save(&marker_path).await {
                        warn!("⚠️ Failed to save state marker progress: {}", e);
                    } else {
                        debug!("💾 Saved state marker progress: {} records, {} batches for {}", total_records, total_batches, file_name);
                    }
                }

                // Send batch if full
                if batch.len() >= batch_size {
                    let messages = std::mem::replace(&mut batch, Vec::with_capacity(batch_size));
                    sender.send(messages).await?;
                    total_batches += 1;
                    last_flush = Instant::now();
                }
            }
            Ok(None) => {
                // Channel closed, send remaining messages
                if !batch.is_empty() {
                    sender.send(batch).await?;
                    // Note: total_batches is not incremented here as it's not used after loop exit
                }
                break;
            }
            Err(_) => {
                // Timeout, check if we should flush
                if !batch.is_empty() && last_flush.elapsed() > Duration::from_secs(1) {
                    let messages = std::mem::replace(&mut batch, Vec::with_capacity(batch_size));
                    sender.send(messages).await?;
                    total_batches += 1;
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

/// Extract version from filename (e.g., "discogs_20260101_artists.xml.gz" -> "20260101")
fn extract_version_from_filename(filename: &str) -> Option<String> {
    let parts: Vec<&str> = filename.split('_').collect();
    if parts.len() >= 2 { Some(parts[1].to_string()) } else { None }
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

    #[test]
    fn test_extract_data_type_all_types() {
        assert_eq!(extract_data_type("discogs_20241201_artists.xml.gz"), Some(DataType::Artists));
        assert_eq!(extract_data_type("discogs_20241201_labels.xml.gz"), Some(DataType::Labels));
        assert_eq!(extract_data_type("discogs_20241201_masters.xml.gz"), Some(DataType::Masters));
        assert_eq!(extract_data_type("discogs_20241201_releases.xml.gz"), Some(DataType::Releases));
    }

    #[test]
    fn test_extract_data_type_invalid_formats() {
        assert_eq!(extract_data_type("invalid_format.xml"), None);
        assert_eq!(extract_data_type("no_underscores.xml.gz"), None);
        assert_eq!(extract_data_type("discogs_20241201.xml.gz"), None);
        assert_eq!(extract_data_type("discogs_20241201_unknown.xml.gz"), None);
    }

    // Deprecated ProcessingState tests removed - replaced by StateMarker integration tests below

    #[tokio::test]
    async fn test_state_marker_file_tracking() {
        use crate::state_marker::{PhaseStatus, StateMarker};
        use tempfile::TempDir;

        let _temp_dir = TempDir::new().unwrap();
        let mut marker = StateMarker::new("20230101".to_string());

        // Test file start tracking
        marker.start_file_processing("discogs_20230101_artists.xml.gz");
        assert_eq!(marker.processing_phase.current_file, Some("discogs_20230101_artists.xml.gz".to_string()));

        // Test file completion
        marker.complete_file_processing("discogs_20230101_artists.xml.gz", 1000);
        let file_progress = marker.processing_phase.progress_by_file.get("discogs_20230101_artists.xml.gz");
        assert!(file_progress.is_some());
        let progress = file_progress.unwrap();
        assert_eq!(progress.status, PhaseStatus::Completed);
        assert_eq!(progress.records_extracted, 1000);
    }

    #[tokio::test]
    async fn test_state_marker_periodic_updates() {
        use crate::state_marker::StateMarker;

        let mut marker = StateMarker::new("20230101".to_string());
        marker.start_file_processing("discogs_20230101_artists.xml.gz");

        // Simulate periodic record updates (records, messages, batches)
        for i in 1..=3 {
            marker.update_file_progress("discogs_20230101_artists.xml.gz", i * 1000, i * 1000, i * 10);
        }

        let file_progress = marker.processing_phase.progress_by_file.get("discogs_20230101_artists.xml.gz");
        assert!(file_progress.is_some());
        assert_eq!(file_progress.unwrap().records_extracted, 3000);
    }

    #[tokio::test]
    async fn test_state_marker_save_load() {
        use crate::state_marker::StateMarker;
        use tempfile::TempDir;

        let temp_dir = TempDir::new().unwrap();
        let marker_path = temp_dir.path().join(".extraction_status_20230101.json");

        // Create and save marker
        let mut marker = StateMarker::new("20230101".to_string());
        marker.start_file_processing("discogs_20230101_artists.xml.gz");
        marker.complete_file_processing("discogs_20230101_artists.xml.gz", 1500);
        marker.save(&marker_path).await.expect("Failed to save marker");

        // Load marker
        let loaded = StateMarker::load(&marker_path).await.expect("Failed to load marker");
        assert!(loaded.is_some());
        let loaded = loaded.unwrap();
        assert_eq!(loaded.current_version, "20230101");
        let file_progress = loaded.processing_phase.progress_by_file.get("discogs_20230101_artists.xml.gz");
        assert!(file_progress.is_some());
        assert_eq!(file_progress.unwrap().records_extracted, 1500);
    }

    #[test]
    fn test_extractor_state_default() {
        let state = ExtractorState::default();

        assert!(state.current_task.is_none());
        assert_eq!(state.current_progress, 0.0);
        assert_eq!(state.extraction_progress.total(), 0);
        assert!(state.last_extraction_time.is_empty());
        assert!(state.completed_files.is_empty());
        assert!(state.active_connections.is_empty());
        assert_eq!(state.error_count, 0);
    }

    #[tokio::test]
    async fn test_message_batcher_basic() {
        use crate::state_marker::StateMarker;
        use tempfile::TempDir;

        let (parse_sender, parse_receiver) = mpsc::channel::<DataMessage>(10);
        let (batch_sender, mut batch_receiver) = mpsc::channel::<Vec<DataMessage>>(10);
        let state = Arc::new(RwLock::new(ExtractorState::default()));

        let temp_dir = TempDir::new().unwrap();
        let marker_path = temp_dir.path().join(".extraction_status_20230101.json");
        let state_marker = Arc::new(tokio::sync::Mutex::new(StateMarker::new("20230101".to_string())));

        // Send some test messages
        for i in 0..5 {
            let message = DataMessage { sha256: format!("sha{}", i), data: serde_json::json!({ "test": format!("test{}", i) }), id: i.to_string() };
            parse_sender.send(message).await.unwrap();
        }
        drop(parse_sender);

        // Run batcher
        let batcher_config = BatcherConfig {
            batch_size: 3,
            data_type: DataType::Artists,
            state: state.clone(),
            state_marker,
            marker_path,
            file_name: "test_file.xml.gz".to_string(),
            state_save_interval: 5000,
        };
        let batcher = message_batcher(parse_receiver, batch_sender, batcher_config);

        // Spawn batcher task
        tokio::spawn(batcher);

        // Collect batches
        let mut total_messages = 0;
        while let Some(batch) = batch_receiver.recv().await {
            total_messages += batch.len();
        }

        assert_eq!(total_messages, 5);

        // Verify state was updated
        let s = state.read().await;
        assert_eq!(s.extraction_progress.artists, 5);
    }

    #[tokio::test]
    async fn test_message_batcher_respects_batch_size() {
        use crate::state_marker::StateMarker;
        use tempfile::TempDir;

        let (parse_sender, parse_receiver) = mpsc::channel::<DataMessage>(100);
        let (batch_sender, mut batch_receiver) = mpsc::channel::<Vec<DataMessage>>(10);
        let state = Arc::new(RwLock::new(ExtractorState::default()));

        let temp_dir = TempDir::new().unwrap();
        let marker_path = temp_dir.path().join(".extraction_status_20230101.json");
        let state_marker = Arc::new(tokio::sync::Mutex::new(StateMarker::new("20230101".to_string())));

        // Send exactly batch_size messages
        let batch_size = 10;
        for i in 0..batch_size {
            let message = DataMessage { sha256: format!("sha{}", i), data: serde_json::json!({ "test": format!("test{}", i) }), id: i.to_string() };
            parse_sender.send(message).await.unwrap();
        }
        drop(parse_sender);

        // Run batcher
        let batcher_config = BatcherConfig {
            batch_size,
            data_type: DataType::Labels,
            state: state.clone(),
            state_marker,
            marker_path,
            file_name: "test_file.xml.gz".to_string(),
            state_save_interval: 5000,
        };
        let batcher = message_batcher(parse_receiver, batch_sender, batcher_config);
        tokio::spawn(batcher);

        // Get first batch
        if let Some(batch) = batch_receiver.recv().await {
            assert_eq!(batch.len(), batch_size);
        }
    }

    #[tokio::test]
    async fn test_message_batcher_timeout_flush() {
        use crate::state_marker::StateMarker;
        use tempfile::TempDir;

        let (parse_sender, parse_receiver) = mpsc::channel::<DataMessage>(10);
        let (batch_sender, mut batch_receiver) = mpsc::channel::<Vec<DataMessage>>(10);
        let state = Arc::new(RwLock::new(ExtractorState::default()));

        let temp_dir = TempDir::new().unwrap();
        let marker_path = temp_dir.path().join(".extraction_status_20230101.json");
        let state_marker = Arc::new(tokio::sync::Mutex::new(StateMarker::new("20230101".to_string())));

        // Send fewer messages than batch size
        for i in 0..3 {
            let message = DataMessage { sha256: format!("sha{}", i), data: serde_json::json!({ "test": format!("test{}", i) }), id: i.to_string() };
            parse_sender.send(message).await.unwrap();
        }

        // Run batcher with large batch size
        let batcher_config = BatcherConfig {
            batch_size: 100,
            data_type: DataType::Masters,
            state: state.clone(),
            state_marker,
            marker_path,
            file_name: "test_file.xml.gz".to_string(),
            state_save_interval: 5000,
        };
        let batcher = message_batcher(parse_receiver, batch_sender, batcher_config);
        let batcher_handle = tokio::spawn(batcher);

        // Wait a bit for timeout flush
        tokio::time::sleep(Duration::from_millis(1200)).await;

        drop(parse_sender);

        // Should eventually flush despite not reaching batch size
        let batch = tokio::time::timeout(Duration::from_secs(5), batch_receiver.recv())
            .await
            .expect("Timeout waiting for batch")
            .expect("Channel closed without receiving batch");

        assert_eq!(batch.len(), 3);

        batcher_handle.await.unwrap().unwrap();
    }

    #[tokio::test]
    async fn test_extractor_state_tracks_progress() {
        let state = Arc::new(RwLock::new(ExtractorState::default()));

        {
            let mut s = state.write().await;
            s.extraction_progress.increment(DataType::Artists);
            s.extraction_progress.increment(DataType::Artists);
            s.extraction_progress.increment(DataType::Labels);
        }

        let s = state.read().await;
        assert_eq!(s.extraction_progress.artists, 2);
        assert_eq!(s.extraction_progress.labels, 1);
        assert_eq!(s.extraction_progress.total(), 3);
    }

    #[tokio::test]
    async fn test_extractor_state_tracks_completed_files() {
        let state = Arc::new(RwLock::new(ExtractorState::default()));

        {
            let mut s = state.write().await;
            s.completed_files.insert("file1.xml".to_string());
            s.completed_files.insert("file2.xml".to_string());
        }

        let s = state.read().await;
        assert_eq!(s.completed_files.len(), 2);
        assert!(s.completed_files.contains("file1.xml"));
    }

    #[tokio::test]
    async fn test_extractor_state_tracks_active_connections() {
        let state = Arc::new(RwLock::new(ExtractorState::default()));

        {
            let mut s = state.write().await;
            s.active_connections.insert(DataType::Artists, "processing_artists.xml".to_string());
            s.active_connections.insert(DataType::Labels, "processing_labels.xml".to_string());
        }

        let s = state.read().await;
        assert_eq!(s.active_connections.len(), 2);
        assert_eq!(s.active_connections.get(&DataType::Artists), Some(&"processing_artists.xml".to_string()));
    }

    #[tokio::test]
    async fn test_extractor_state_tracks_errors() {
        let state = Arc::new(RwLock::new(ExtractorState::default()));

        {
            let mut s = state.write().await;
            s.error_count += 1;
            s.error_count += 1;
        }

        let s = state.read().await;
        assert_eq!(s.error_count, 2);
    }

    #[tokio::test]
    async fn test_extractor_state_last_extraction_time() {
        let state = Arc::new(RwLock::new(ExtractorState::default()));

        {
            let mut s = state.write().await;
            s.last_extraction_time.insert(DataType::Artists, 123.45);
            s.last_extraction_time.insert(DataType::Labels, 678.90);
        }

        let s = state.read().await;
        assert_eq!(s.last_extraction_time.get(&DataType::Artists), Some(&123.45));
        assert_eq!(s.last_extraction_time.get(&DataType::Labels), Some(&678.90));
    }
}
