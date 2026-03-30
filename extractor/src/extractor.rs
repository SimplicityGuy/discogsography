use anyhow::{Context, Result};
use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::str::FromStr;
use std::sync::Arc;
use std::time::Instant;
use tokio::sync::{RwLock, mpsc};
use tokio::time::{Duration, sleep};
use tracing::{debug, error, info, warn};

use async_trait::async_trait;

use crate::config::ExtractorConfig;
use crate::discogs_downloader::{DataSource, Downloader};
use crate::message_queue::{MessagePublisher, MessageQueue};
use crate::parser::XmlParser;
use crate::rules::{CompiledRulesConfig, FlaggedRecordWriter, QualityReport, Severity, evaluate_rules};
use crate::state_marker::{PhaseStatus, ProcessingDecision, StateMarker};
use crate::types::{DataMessage, DataType, ExtractionProgress};

/// Factory for creating MessagePublisher instances (enables DI for testing)
#[cfg_attr(feature = "test-support", mockall::automock)]
#[async_trait]
pub trait MessageQueueFactory: Send + Sync {
    async fn create(&self, url: &str, exchange_prefix: &str) -> Result<Arc<dyn MessagePublisher>>;
}

/// Default factory that creates real MessageQueue connections
pub struct DefaultMessageQueueFactory;

#[async_trait]
impl MessageQueueFactory for DefaultMessageQueueFactory {
    async fn create(&self, url: &str, exchange_prefix: &str) -> Result<Arc<dyn MessagePublisher>> {
        Ok(Arc::new(MessageQueue::new(url, 3, exchange_prefix).await?))
    }
}

/// State shared across the extractor
#[derive(Debug, Default)]
pub struct ExtractorState {
    pub extraction_progress: ExtractionProgress,
    pub last_extraction_time: HashMap<DataType, Instant>,
    pub completed_files: HashSet<String>,
    pub active_connections: HashMap<DataType, String>,
    pub error_count: u64,
    pub extraction_status: ExtractionStatus,
}

/// Lifecycle status of the extraction process
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum ExtractionStatus {
    #[default]
    Idle,
    Running,
    Completed,
    Failed,
}

impl ExtractionStatus {
    pub fn as_str(&self) -> &'static str {
        match self {
            ExtractionStatus::Idle => "idle",
            ExtractionStatus::Running => "running",
            ExtractionStatus::Completed => "completed",
            ExtractionStatus::Failed => "failed",
        }
    }
}

/// Process Discogs data files
pub async fn process_discogs_data(
    config: Arc<ExtractorConfig>,
    state: Arc<RwLock<ExtractorState>>,
    shutdown: Arc<tokio::sync::Notify>,
    force_reprocess: bool,
    downloader: &mut dyn DataSource,
    mq_factory: Arc<dyn MessageQueueFactory>,
    compiled_rules: Option<Arc<CompiledRulesConfig>>,
) -> Result<bool> {
    // Record extraction start time for consumer cleanup coordination
    let extraction_started_at = chrono::Utc::now();

    // Reset progress for new run
    {
        let mut s = state.write().await;
        s.extraction_progress = ExtractionProgress::default();
        s.last_extraction_time.clear();
        s.completed_files.clear();
        s.active_connections.clear();
        s.error_count = 0;
        s.extraction_status = ExtractionStatus::Running;
    }

    // Get file list to determine version
    let available_files = downloader.list_s3_files().await.context("Failed to list S3 files")?;
    let latest_files = downloader.get_latest_monthly_files(&available_files)?;

    if latest_files.is_empty() {
        warn!("⚠️ No data files found");
        return Ok(true);
    }

    // Extract version from first filename
    // `latest_files[0].name` is an S3 object key from the Discogs public bucket — operator-controlled, not user input.
    let first_filename = Path::new(&latest_files[0].name) // nosemgrep: rust.actix.path-traversal.tainted-path.tainted-path
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
    downloader.set_state_marker(state_marker, marker_path.clone());

    // Download latest data (this will now track timestamps properly)
    let data_files = downloader.download_discogs_data().await.context("Failed to download Discogs data")?;

    // Get state marker back from downloader
    let mut state_marker = downloader.take_state_marker().ok_or_else(|| anyhow::anyhow!("State marker missing after download"))?;

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

        // Send extraction_complete with actual record counts from state marker
        let mut record_counts = HashMap::new();
        for (file_name, file_state) in &state_marker.processing_phase.progress_by_file {
            record_counts.insert(file_name.clone(), file_state.records_extracted);
        }
        match mq_factory.create(&config.amqp_connection, &config.amqp_exchange_prefix).await {
            Ok(mq) => {
                if let Err(e) = mq.send_extraction_complete(&version, extraction_started_at, record_counts, &DataType::discogs()).await {
                    error!("❌ Failed to send extraction_complete message: {}", e);
                }
                let _ = mq.close().await;
            }
            Err(e) => {
                error!("❌ Failed to connect to AMQP for extraction_complete: {}", e);
            }
        }

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
        let semaphore = semaphore.clone();
        let marker_path = marker_path.clone();
        let state_marker_arc = state_marker_arc.clone();
        let mq_factory = mq_factory.clone();
        let compiled_rules = compiled_rules.clone();

        let task: tokio::task::JoinHandle<Result<()>> = tokio::spawn(async move {
            let _permit = semaphore.acquire().await?;
            let mq = mq_factory
                .create(&config.amqp_connection, &config.amqp_exchange_prefix)
                .await
                .context("Failed to connect to message queue")?;

            process_single_file(&file, config, state, state_marker_arc.clone(), marker_path.clone(), mq, compiled_rules).await?;

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

    // Only mark processing as complete if all tasks succeeded
    let mut state_marker = state_marker_arc.lock().await;
    if success {
        state_marker.complete_processing();
        state_marker.complete_extraction();
        state_marker.save(&marker_path).await?;
        info!("✅ Processing phase completed: version {}", state_marker.current_version);
    } else {
        // Save current progress without marking complete — allows restart to resume
        state_marker.save(&marker_path).await?;
        error!("❌ Processing phase finished with errors — not marking complete");
    }

    // Log completion and send extraction_complete to all consumers
    {
        let s = state.read().await;
        info!("🎉 All processing complete! Finished files: {:?}", s.completed_files);
        info!("📊 Final statistics: {} total records extracted", s.extraction_progress.total());

        // Build per-type record counts from extraction progress
        let mut record_counts = HashMap::new();
        record_counts.insert("artists".to_string(), s.extraction_progress.artists);
        record_counts.insert("labels".to_string(), s.extraction_progress.labels);
        record_counts.insert("masters".to_string(), s.extraction_progress.masters);
        record_counts.insert("releases".to_string(), s.extraction_progress.releases);

        // Send extraction_complete to all consumer queues
        drop(s); // Release read lock before async MQ operations
        match mq_factory.create(&config.amqp_connection, &config.amqp_exchange_prefix).await {
            Ok(mq) => {
                if let Err(e) = mq.send_extraction_complete(&version, extraction_started_at, record_counts, &DataType::discogs()).await {
                    error!("❌ Failed to send extraction_complete message: {}", e);
                    success = false;
                }
                let _ = mq.close().await;
            }
            Err(e) => {
                error!("❌ Failed to connect to AMQP for extraction_complete: {}", e);
                success = false;
            }
        }
    }

    // Update extraction status based on result
    {
        let mut s = state.write().await;
        s.extraction_status = if success { ExtractionStatus::Completed } else { ExtractionStatus::Failed };
    }

    Ok(success)
}

/// Process a single file
pub async fn process_single_file(
    file_name: &str,
    config: Arc<ExtractorConfig>,
    state: Arc<RwLock<ExtractorState>>,
    state_marker: Arc<tokio::sync::Mutex<StateMarker>>,
    marker_path: PathBuf,
    mq: Arc<dyn MessagePublisher>,
    compiled_rules: Option<Arc<CompiledRulesConfig>>,
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

    // Declare fanout exchange for this data type
    mq.setup_exchange(data_type).await?;

    // Track active connection
    {
        let mut s = state.write().await;
        s.active_connections.insert(data_type, file_name.to_string());
    }

    // Create channels for processing pipeline
    let (parse_sender, parse_receiver) = mpsc::channel::<DataMessage>(config.queue_size);
    let (batch_sender, batch_receiver) = mpsc::channel::<Vec<DataMessage>>(100);

    // Start workers — with optional validator stage between parser and batcher
    let file_base_name = Path::new(file_name).file_name().and_then(|n| n.to_str()).unwrap_or(file_name); // nosemgrep: rust.actix.path-traversal.tainted-path.tainted-path
    let version = extract_version_from_filename(file_base_name).unwrap_or_else(|| "unknown".to_string());

    let validator_handle = if let Some(rules) = compiled_rules {
        let (validated_sender, validated_receiver) = mpsc::channel::<DataMessage>(config.queue_size);
        let rules = rules.clone();
        let discogs_root = config.discogs_root.clone();
        let version_clone = version.clone();
        let data_type_str = data_type.as_str().to_string();

        let handle =
            tokio::spawn(
                async move { message_validator(parse_receiver, validated_sender, rules, &data_type_str, &discogs_root, &version_clone).await },
            );

        let batcher_config = BatcherConfig {
            batch_size: config.batch_size,
            data_type,
            state: state.clone(),
            state_marker: state_marker.clone(),
            marker_path: marker_path.clone(),
            file_name: file_name.to_string(),
            state_save_interval: config.state_save_interval,
        };
        let batcher_handle = tokio::spawn(async move { message_batcher(validated_receiver, batch_sender, batcher_config).await });

        let parser_handle = tokio::spawn({
            let file_path = config.discogs_root.join(file_name); // nosemgrep: rust.actix.path-traversal.tainted-path.tainted-path
            async move {
                let parser = XmlParser::with_options(data_type, parse_sender, true);
                parser.parse_file(&file_path).await
            }
        });

        let publisher_handle = tokio::spawn({
            let mq = mq.clone();
            let state = state.clone();
            async move { message_publisher(batch_receiver, mq, data_type, state).await }
        });

        let total_count = parser_handle.await??;
        let report: QualityReport = handle.await??;
        batcher_handle.await??;
        publisher_handle.await??;

        if report.has_violations() {
            // file_name comes from S3 file listing (operator-controlled, not user input)
            let version_for_report = extract_version_from_filename(
                Path::new(file_name).file_name().and_then(|n| n.to_str()).unwrap_or(""), // nosemgrep: rust.actix.path-traversal.tainted-path.tainted-path
            )
            .unwrap_or_default();
            info!("{}", report.format_summary(&version_for_report));
        }

        Some(total_count)
    } else {
        let parser_handle = tokio::spawn({
            let file_path = config.discogs_root.join(file_name);
            async move {
                let parser = XmlParser::new(data_type, parse_sender);
                parser.parse_file(&file_path).await
            }
        });

        let batcher_config = BatcherConfig {
            batch_size: config.batch_size,
            data_type,
            state: state.clone(),
            state_marker: state_marker.clone(),
            marker_path: marker_path.clone(),
            file_name: file_name.to_string(),
            state_save_interval: config.state_save_interval,
        };
        let batcher_handle = tokio::spawn(async move { message_batcher(parse_receiver, batch_sender, batcher_config).await });

        let publisher_handle = tokio::spawn({
            let mq = mq.clone();
            let state = state.clone();
            async move { message_publisher(batch_receiver, mq, data_type, state).await }
        });

        let total_count = parser_handle.await??;
        batcher_handle.await??;
        publisher_handle.await??;

        Some(total_count)
    };

    let total_count = validator_handle.unwrap_or(0);

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
                    s.last_extraction_time.insert(data_type, Instant::now());
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
                    total_batches += 1;
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

    // Save final state marker with accurate batch count
    {
        let mut marker = state_marker.lock().await;
        marker.update_file_progress(&file_name, total_records, total_records, total_batches);
        if let Err(e) = marker.save(&marker_path).await {
            warn!("⚠️ Failed to save final state marker progress: {}", e);
        }
    }

    Ok(())
}

/// Validate messages against data quality rules.
/// All messages are forwarded downstream regardless of violations.
pub async fn message_validator(
    mut receiver: mpsc::Receiver<DataMessage>,
    sender: mpsc::Sender<DataMessage>,
    rules: Arc<CompiledRulesConfig>,
    data_type: &str,
    discogs_root: &Path,
    version: &str,
) -> Result<QualityReport> {
    let mut report = QualityReport::new();
    let mut writer = FlaggedRecordWriter::new(discogs_root, version);

    while let Some(message) = receiver.recv().await {
        report.increment_total(data_type);
        let violations = evaluate_rules(&rules, data_type, &message.data);
        for violation in &violations {
            report.record_violation(data_type, &violation.rule_name, &violation.severity);
            let capture_files = matches!(violation.severity, Severity::Error | Severity::Warning);
            writer.write_violation(data_type, &message.id, violation, message.raw_xml.as_deref(), &message.data, capture_files);
        }
        if sender.send(message).await.is_err() {
            warn!("⚠️ Validator: downstream receiver dropped");
            break;
        }
    }

    writer.flush();
    writer.write_report(&report, version);
    Ok(report)
}

/// Publish batched messages to AMQP
pub async fn message_publisher(
    mut receiver: mpsc::Receiver<Vec<DataMessage>>,
    mq: Arc<dyn MessagePublisher>,
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
                return Err(e).context("Failed to publish batch to AMQP");
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
        let mut stalled = Vec::new();

        for (data_type, last_time) in &s.last_extraction_time {
            let is_completed = s.completed_files.iter().any(|f| f.contains(data_type.as_str()));
            if !is_completed && last_time.elapsed() > Duration::from_secs(120) {
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

/// Wait for the trigger to be set, then take the value and return the force_reprocess flag
async fn wait_for_trigger(trigger: &Arc<std::sync::Mutex<Option<bool>>>) -> bool {
    loop {
        {
            let mut t = trigger.lock().unwrap();
            if let Some(force_reprocess) = t.take() {
                return force_reprocess;
            }
        }
        tokio::time::sleep(Duration::from_millis(500)).await;
    }
}

/// Main extraction loop with periodic checks
pub async fn run_extraction_loop(
    config: Arc<ExtractorConfig>,
    state: Arc<RwLock<ExtractorState>>,
    shutdown: Arc<tokio::sync::Notify>,
    force_reprocess: bool,
    mq_factory: Arc<dyn MessageQueueFactory>,
    trigger: Arc<std::sync::Mutex<Option<bool>>>,
    compiled_rules: Option<Arc<CompiledRulesConfig>>,
) -> Result<()> {
    info!("📥 Starting initial data processing...");

    // Process initial data
    let mut downloader = Downloader::new(config.discogs_root.clone()).await?;
    let success = process_discogs_data(
        config.clone(),
        state.clone(),
        shutdown.clone(),
        force_reprocess,
        &mut downloader,
        mq_factory.clone(),
        compiled_rules.clone(),
    )
    .await?;

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

                let mut downloader = match Downloader::new(config.discogs_root.clone()).await {
                    Ok(dl) => dl,
                    Err(e) => {
                        error!("❌ Failed to create downloader for periodic check: {}", e);
                        continue;
                    }
                };
                match process_discogs_data(config.clone(), state.clone(), shutdown.clone(), false, &mut downloader, mq_factory.clone(), compiled_rules.clone()).await {
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
            trigger_force_reprocess = wait_for_trigger(&trigger) => {
                info!("🔄 Extraction triggered via API (force_reprocess={})...", trigger_force_reprocess);
                let start = Instant::now();
                let mut downloader = match Downloader::new(config.discogs_root.clone()).await {
                    Ok(dl) => dl,
                    Err(e) => {
                        error!("❌ Failed to create downloader for triggered extraction: {}", e);
                        continue;
                    }
                };
                match process_discogs_data(config.clone(), state.clone(), shutdown.clone(), trigger_force_reprocess, &mut downloader, mq_factory.clone(), compiled_rules.clone()).await {
                    Ok(true) => info!("✅ Triggered extraction completed successfully in {:?}", start.elapsed()),
                    Ok(false) => error!("❌ Triggered extraction completed with errors"),
                    Err(e) => error!("❌ Triggered extraction failed: {}", e),
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

/// Main MusicBrainz extraction loop with periodic checks for new dumps.
pub async fn run_musicbrainz_loop(
    config: Arc<ExtractorConfig>,
    state: Arc<RwLock<ExtractorState>>,
    shutdown: Arc<tokio::sync::Notify>,
    force_reprocess: bool,
    mq_factory: Arc<dyn MessageQueueFactory>,
    trigger: Arc<std::sync::Mutex<Option<bool>>>,
    compiled_rules: Option<Arc<CompiledRulesConfig>>,
) -> Result<()> {
    info!("🎵 Starting MusicBrainz extraction...");

    let success =
        process_musicbrainz_data(config.clone(), state.clone(), shutdown.clone(), force_reprocess, mq_factory.clone(), compiled_rules.clone())
            .await?;

    if !success {
        error!("❌ Initial MusicBrainz processing failed");
        return Err(anyhow::anyhow!("Initial MusicBrainz processing failed"));
    }

    info!("✅ Initial MusicBrainz processing completed successfully");

    // Periodic check loop
    loop {
        let check_interval = Duration::from_secs(config.periodic_check_days * 24 * 60 * 60);
        info!("⏰ Waiting {} days before next MusicBrainz check...", config.periodic_check_days);

        tokio::select! {
            _ = sleep(check_interval) => {
                info!("🔄 Starting periodic check for new MusicBrainz dumps...");
                let start = Instant::now();
                match process_musicbrainz_data(config.clone(), state.clone(), shutdown.clone(), false, mq_factory.clone(), compiled_rules.clone()).await {
                    Ok(true) => {
                        info!("✅ Periodic MusicBrainz check completed successfully in {:?}", start.elapsed());
                    }
                    Ok(false) => {
                        error!("❌ Periodic MusicBrainz check completed with errors");
                    }
                    Err(e) => {
                        error!("❌ Periodic MusicBrainz check failed: {}", e);
                    }
                }
            }
            trigger_force_reprocess = wait_for_trigger(&trigger) => {
                info!("🔄 MusicBrainz extraction triggered via API (force_reprocess={})...", trigger_force_reprocess);
                let start = Instant::now();
                match process_musicbrainz_data(config.clone(), state.clone(), shutdown.clone(), trigger_force_reprocess, mq_factory.clone(), compiled_rules.clone()).await {
                    Ok(true) => info!("✅ Triggered MusicBrainz extraction completed in {:?}", start.elapsed()),
                    Ok(false) => error!("❌ Triggered MusicBrainz extraction completed with errors"),
                    Err(e) => error!("❌ Triggered MusicBrainz extraction failed: {}", e),
                }
            }
            _ = shutdown.notified() => {
                info!("🛑 Shutdown requested, stopping MusicBrainz periodic checks");
                break;
            }
        }
    }

    Ok(())
}

/// Process MusicBrainz JSONL dump files and publish records to AMQP.
///
/// Pipeline per file: blocking JSONL parser -> async batcher -> async publisher
pub async fn process_musicbrainz_data(
    config: Arc<ExtractorConfig>,
    state: Arc<RwLock<ExtractorState>>,
    _shutdown: Arc<tokio::sync::Notify>,
    force_reprocess: bool,
    mq_factory: Arc<dyn MessageQueueFactory>,
    _compiled_rules: Option<Arc<CompiledRulesConfig>>,
) -> Result<bool> {
    use crate::jsonl_parser::{build_mbid_discogs_map_from_file, parse_mb_jsonl_file};
    use crate::musicbrainz_downloader::{MbDownloader, discover_mb_dump_files};

    let extraction_started_at = chrono::Utc::now();

    // Reset progress for new run
    {
        let mut s = state.write().await;
        s.extraction_progress = ExtractionProgress::default();
        s.last_extraction_time.clear();
        s.completed_files.clear();
        s.active_connections.clear();
        s.error_count = 0;
        s.extraction_status = ExtractionStatus::Running;
    }

    // Download latest MusicBrainz dump if needed
    let downloader = MbDownloader::new(config.musicbrainz_root.clone(), config.musicbrainz_dump_url.clone());
    let download_result = downloader.download_latest().await?;
    let version = download_result.version().to_string();
    let versioned_root = config.musicbrainz_root.join(&version);
    info!("📋 Using MusicBrainz dump version: {} from {:?}", version, versioned_root);

    // Discover dump files in the versioned directory
    let dump_files = discover_mb_dump_files(&versioned_root)?;

    if dump_files.is_empty() {
        warn!("⚠️ No MusicBrainz dump files found after download");
        let mut s = state.write().await;
        s.extraction_status = ExtractionStatus::Completed;
        return Ok(true);
    }

    // Check state marker — skip if already completed and not force_reprocess
    let marker_path = versioned_root.join(format!(".mb_extraction_status_{}.json", version));
    let mut state_marker = if force_reprocess {
        info!("🔄 Force reprocess requested, creating new state marker");
        StateMarker::new(version.clone())
    } else {
        StateMarker::load(&marker_path).await?.unwrap_or_else(|| StateMarker::new(version.clone()))
    };

    let decision = state_marker.should_process();
    match decision {
        ProcessingDecision::Skip => {
            info!("✅ MusicBrainz version {} already processed, skipping", version);
            let mut s = state.write().await;
            s.extraction_status = ExtractionStatus::Completed;
            return Ok(true);
        }
        ProcessingDecision::Reprocess => {
            warn!("⚠️ Will re-process MusicBrainz version {}", version);
            state_marker = StateMarker::new(version.clone());
        }
        ProcessingDecision::Continue => {
            info!("🔄 Will continue processing MusicBrainz version {}", version);
        }
    }

    // Create message queue connection with MusicBrainz exchange prefix
    let mq = mq_factory
        .create(&config.amqp_connection, &config.amqp_exchange_prefix)
        .await
        .context("Failed to connect to message queue for MusicBrainz")?;

    // Declare exchanges for MusicBrainz data types
    for data_type in DataType::musicbrainz() {
        mq.setup_exchange(data_type).await?;
    }

    // Start processing phase
    let file_count = dump_files.len();
    state_marker.start_processing(file_count);
    state_marker.save(&marker_path).await?;
    info!("🚀 Starting MusicBrainz processing phase: {} dump file(s)", file_count);

    // First pass: build MBID→Discogs ID map for artist relationship target resolution
    let artist_discogs_map = if let Some(artist_path) = dump_files.get(&DataType::Artists) {
        info!("🔍 First pass: building MBID→Discogs ID map for artists...");
        let path = artist_path.clone();
        tokio::task::spawn_blocking(move || build_mbid_discogs_map_from_file(&path, "artist")).await??
    } else {
        HashMap::new()
    };
    info!("📊 Built MBID→Discogs map: {} entries", artist_discogs_map.len());

    let mut record_counts: HashMap<String, u64> = HashMap::new();
    let mut success = true;

    for (data_type, file_path) in &dump_files {
        let file_name = file_path.file_name().and_then(|n| n.to_str()).unwrap_or("unknown");

        // Skip files already completed in state marker
        if let Some(status) = state_marker.processing_phase.progress_by_file.get(file_name)
            && status.status == PhaseStatus::Completed
        {
            info!("✅ Skipping already-completed file: {}", file_name);
            continue;
        }

        info!("🚀 Starting MusicBrainz extraction of {} from {:?}", data_type, file_path);
        state_marker.start_file_processing(file_name);
        state_marker.save(&marker_path).await?;

        // Track active connection
        {
            let mut s = state.write().await;
            s.active_connections.insert(*data_type, file_name.to_string());
        }

        // Create channel for parser -> batcher -> publisher pipeline
        let (parse_sender, parse_receiver) = mpsc::channel::<DataMessage>(config.queue_size);
        let (batch_sender, batch_receiver) = mpsc::channel::<Vec<DataMessage>>(100);

        // Spawn parser on blocking thread — pass MBID→Discogs map for artist relationship enrichment
        let parser_path = file_path.clone();
        let parser_dt = *data_type;
        let parser_map = if parser_dt == DataType::Artists {
            Some(artist_discogs_map.clone())
        } else {
            None
        };
        let parser_handle = tokio::task::spawn_blocking(move || parse_mb_jsonl_file(&parser_path, parser_dt, parse_sender, parser_map.as_ref()));

        // Spawn batcher
        let batcher_state_marker = Arc::new(tokio::sync::Mutex::new(state_marker.clone()));
        let batcher_config = BatcherConfig {
            batch_size: config.batch_size,
            data_type: *data_type,
            state: state.clone(),
            state_marker: batcher_state_marker.clone(),
            marker_path: marker_path.clone(),
            file_name: file_name.to_string(),
            state_save_interval: config.state_save_interval,
        };
        let batcher_handle = tokio::spawn(async move { message_batcher(parse_receiver, batch_sender, batcher_config).await });

        // Spawn publisher
        let pub_mq = mq.clone();
        let pub_dt = *data_type;
        let pub_state = state.clone();
        let publisher_handle = tokio::spawn(async move { message_publisher(batch_receiver, pub_mq, pub_dt, pub_state).await });

        // Wait for all stages — use per-file success flag to avoid cross-file bleed
        let mut file_success = true;
        let total_count = match parser_handle.await {
            Ok(Ok(count)) => count,
            Ok(Err(e)) => {
                error!("❌ MusicBrainz parser failed for {}: {}", data_type, e);
                file_success = false;
                0
            }
            Err(e) => {
                error!("❌ MusicBrainz parser task panicked for {}: {}", data_type, e);
                file_success = false;
                0
            }
        };

        if let Err(e) = batcher_handle.await {
            error!("❌ MusicBrainz batcher task failed for {}: {}", data_type, e);
            file_success = false;
        }

        if let Err(e) = publisher_handle.await {
            error!("❌ MusicBrainz publisher task failed for {}: {}", data_type, e);
            file_success = false;
        }

        if !file_success {
            success = false;
        }

        // Update state marker with results from batcher
        state_marker = batcher_state_marker.lock().await.clone();

        // Mark file complete only on success; on failure, save current state without marking complete
        if file_success {
            state_marker.complete_file_processing(file_name, total_count);
        }
        state_marker.save(&marker_path).await?;

        // Update shared state
        {
            let mut s = state.write().await;
            s.completed_files.insert(file_name.to_string());
            s.active_connections.remove(data_type);
        }

        // Send file_complete message only on success to avoid misleading consumers
        if file_success {
            if let Err(e) = mq.send_file_complete(*data_type, file_name, total_count).await {
                error!("❌ Failed to send file_complete for {}: {}", data_type, e);
                success = false;
            }
        }

        record_counts.insert(data_type.to_string(), total_count);
        info!("✅ Completed MusicBrainz {} extraction: {} records", data_type, total_count);
    }

    // Send extraction_complete to MusicBrainz exchanges only (no masters)
    let mb_types = DataType::musicbrainz();
    if let Err(e) = mq.send_extraction_complete(&version, extraction_started_at, record_counts, &mb_types).await {
        error!("❌ Failed to send extraction_complete: {}", e);
        success = false;
    }
    let _ = mq.close().await;

    // Finalize state marker
    if success {
        state_marker.complete_processing();
        state_marker.complete_extraction();
        state_marker.save(&marker_path).await?;
        info!("✅ MusicBrainz processing completed: version {}", version);
    } else {
        state_marker.save(&marker_path).await?;
        error!("❌ MusicBrainz processing finished with errors — not marking complete");
    }

    // Update extraction status
    {
        let mut s = state.write().await;
        s.extraction_status = if success { ExtractionStatus::Completed } else { ExtractionStatus::Failed };
    }

    Ok(success)
}

#[cfg(test)]
#[path = "tests/extractor_tests.rs"]
mod tests;
