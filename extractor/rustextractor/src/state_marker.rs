use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use tokio::fs;
use tracing::{debug, info, warn};


/// Phase status for tracking progress
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PhaseStatus {
    Pending,
    InProgress,
    Completed,
    Failed,
}

/// Per-file download tracking
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FileDownloadStatus {
    pub status: PhaseStatus,
    pub bytes_downloaded: u64,
    pub started_at: Option<DateTime<Utc>>,
    pub completed_at: Option<DateTime<Utc>>,
}

impl Default for FileDownloadStatus {
    fn default() -> Self {
        Self {
            status: PhaseStatus::Pending,
            bytes_downloaded: 0,
            started_at: None,
            completed_at: None,
        }
    }
}

/// Download phase tracking
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DownloadPhase {
    pub status: PhaseStatus,
    pub started_at: Option<DateTime<Utc>>,
    pub completed_at: Option<DateTime<Utc>>,
    pub files_downloaded: usize,
    pub files_total: usize,
    pub bytes_downloaded: u64,
    pub downloads_by_file: HashMap<String, FileDownloadStatus>,
    pub errors: Vec<String>,
}

impl Default for DownloadPhase {
    fn default() -> Self {
        Self {
            status: PhaseStatus::Pending,
            started_at: None,
            completed_at: None,
            files_downloaded: 0,
            files_total: 0,
            bytes_downloaded: 0,
            downloads_by_file: HashMap::new(),
            errors: Vec::new(),
        }
    }
}

/// File processing status
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FileProcessingStatus {
    pub status: PhaseStatus,
    pub records_extracted: u64,
    pub messages_published: u64,
    pub batches_sent: u64,
    pub started_at: Option<DateTime<Utc>>,
    pub completed_at: Option<DateTime<Utc>>,
}

impl Default for FileProcessingStatus {
    fn default() -> Self {
        Self {
            status: PhaseStatus::Pending,
            records_extracted: 0,
            messages_published: 0,
            batches_sent: 0,
            started_at: None,
            completed_at: None,
        }
    }
}

/// Processing phase tracking
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProcessingPhase {
    pub status: PhaseStatus,
    pub started_at: Option<DateTime<Utc>>,
    pub completed_at: Option<DateTime<Utc>>,
    pub files_processed: usize,
    pub files_total: usize,
    pub records_extracted: u64,
    pub current_file: Option<String>,
    pub progress_by_file: HashMap<String, FileProcessingStatus>,
    pub errors: Vec<String>,
}

impl Default for ProcessingPhase {
    fn default() -> Self {
        Self {
            status: PhaseStatus::Pending,
            started_at: None,
            completed_at: None,
            files_processed: 0,
            files_total: 0,
            records_extracted: 0,
            current_file: None,
            progress_by_file: HashMap::new(),
            errors: Vec::new(),
        }
    }
}

/// Publishing phase tracking
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PublishingPhase {
    pub status: PhaseStatus,
    pub messages_published: u64,
    pub batches_sent: u64,
    pub errors: Vec<String>,
    pub last_amqp_heartbeat: Option<DateTime<Utc>>,
}

impl Default for PublishingPhase {
    fn default() -> Self {
        Self {
            status: PhaseStatus::Pending,
            messages_published: 0,
            batches_sent: 0,
            errors: Vec::new(),
            last_amqp_heartbeat: None,
        }
    }
}

/// Overall extraction status summary
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExtractionSummary {
    pub overall_status: PhaseStatus,
    pub total_duration_seconds: Option<f64>,
    pub files_by_type: HashMap<String, PhaseStatus>,
}

impl Default for ExtractionSummary {
    fn default() -> Self {
        Self {
            overall_status: PhaseStatus::Pending,
            total_duration_seconds: None,
            files_by_type: HashMap::new(),
        }
    }
}

/// Main state marker tracking all extraction phases
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StateMarker {
    /// Version identifier (e.g., "1.0")
    pub metadata_version: String,

    /// Last update timestamp
    pub last_updated: DateTime<Utc>,

    /// Discogs data version (e.g., "20260101")
    pub current_version: String,

    /// Download phase tracking
    pub download_phase: DownloadPhase,

    /// Processing phase tracking
    pub processing_phase: ProcessingPhase,

    /// Publishing phase tracking
    pub publishing_phase: PublishingPhase,

    /// Overall summary
    pub summary: ExtractionSummary,
}

impl StateMarker {
    /// Create a new state marker for a version
    pub fn new(version: String) -> Self {
        Self {
            metadata_version: "1.0".to_string(),
            last_updated: Utc::now(),
            current_version: version,
            download_phase: DownloadPhase::default(),
            processing_phase: ProcessingPhase::default(),
            publishing_phase: PublishingPhase::default(),
            summary: ExtractionSummary::default(),
        }
    }

    /// Load state marker from file
    pub async fn load(path: &Path) -> Result<Option<Self>> {
        if !path.exists() {
            debug!("📋 No state marker found at: {}", path.display());
            return Ok(None);
        }

        let contents = fs::read_to_string(path)
            .await
            .context("Failed to read state marker file")?;

        let marker: StateMarker = serde_json::from_str(&contents)
            .context("Failed to parse state marker JSON")?;

        info!("📋 Loaded state marker for version: {}", marker.current_version);
        Ok(Some(marker))
    }

    /// Save state marker to file
    pub async fn save(&mut self, path: &Path) -> Result<()> {
        self.last_updated = Utc::now();

        let json = serde_json::to_string_pretty(self)
            .context("Failed to serialize state marker")?;

        fs::write(path, json)
            .await
            .context("Failed to write state marker file")?;

        debug!("💾 Saved state marker to: {}", path.display());
        Ok(())
    }

    /// Get the file path for this version's state marker
    pub fn file_path(discogs_root: &Path, version: &str) -> PathBuf {
        discogs_root.join(format!(".extraction_status_{}.json", version))
    }

    /// Check if we should re-process, continue, or skip
    pub fn should_process(&self) -> ProcessingDecision {
        // If download failed, need to re-download
        if self.download_phase.status == PhaseStatus::Failed {
            warn!("⚠️ Download phase failed, will re-download");
            return ProcessingDecision::Reprocess;
        }

        // If processing failed, can resume
        if self.processing_phase.status == PhaseStatus::Failed {
            warn!("⚠️ Processing phase failed, will resume");
            return ProcessingDecision::Continue;
        }

        // If processing in progress, resume
        if self.processing_phase.status == PhaseStatus::InProgress {
            info!("🔄 Processing in progress, will resume");
            return ProcessingDecision::Continue;
        }

        // If everything completed successfully, skip
        if self.summary.overall_status == PhaseStatus::Completed {
            info!("✅ Version {} already fully processed", self.current_version);
            return ProcessingDecision::Skip;
        }

        // Otherwise, continue processing
        ProcessingDecision::Continue
    }

    /// Mark download phase as started
    pub fn start_download(&mut self, files_total: usize) {
        self.download_phase.status = PhaseStatus::InProgress;
        self.download_phase.started_at = Some(Utc::now());
        self.download_phase.files_total = files_total;
        self.download_phase.files_downloaded = 0;
        self.download_phase.bytes_downloaded = 0;
    }

    /// Mark a file download as started
    pub fn start_file_download(&mut self, filename: &str) {
        let status = FileDownloadStatus {
            status: PhaseStatus::InProgress,
            started_at: Some(Utc::now()),
            ..Default::default()
        };
        self.download_phase.downloads_by_file.insert(filename.to_string(), status);
    }

    /// Mark a file as downloaded
    pub fn file_downloaded(&mut self, filename: &str, bytes: u64) {
        if let Some(status) = self.download_phase.downloads_by_file.get_mut(filename) {
            status.status = PhaseStatus::Completed;
            status.bytes_downloaded = bytes;
            status.completed_at = Some(Utc::now());
        } else {
            // If not tracked, create entry
            self.download_phase.downloads_by_file.insert(
                filename.to_string(),
                FileDownloadStatus {
                    status: PhaseStatus::Completed,
                    bytes_downloaded: bytes,
                    started_at: Some(Utc::now()),
                    completed_at: Some(Utc::now()),
                },
            );
        }

        self.download_phase.files_downloaded += 1;
        // Recalculate total bytes from all files
        self.download_phase.bytes_downloaded = self
            .download_phase
            .downloads_by_file
            .values()
            .map(|s| s.bytes_downloaded)
            .sum();
    }

    /// Mark download phase as completed
    pub fn complete_download(&mut self) {
        self.download_phase.status = PhaseStatus::Completed;
        self.download_phase.completed_at = Some(Utc::now());
        info!("✅ Download phase completed: {} files, {} bytes",
              self.download_phase.files_downloaded,
              self.download_phase.bytes_downloaded);
    }

    /// Mark download phase as failed
    pub fn fail_download(&mut self, error: String) {
        self.download_phase.status = PhaseStatus::Failed;
        self.download_phase.errors.push(error);
        self.summary.overall_status = PhaseStatus::Failed;
    }

    /// Mark processing phase as started
    pub fn start_processing(&mut self, files_total: usize) {
        self.processing_phase.status = PhaseStatus::InProgress;
        self.processing_phase.started_at = Some(Utc::now());
        self.processing_phase.files_total = files_total;
        self.processing_phase.files_processed = 0;
        self.processing_phase.records_extracted = 0;
        // Update summary status when processing starts
        self.summary.overall_status = PhaseStatus::InProgress;
    }

    /// Mark a file processing as started
    pub fn start_file_processing(&mut self, filename: &str) {
        self.processing_phase.current_file = Some(filename.to_string());

        let status = FileProcessingStatus {
            status: PhaseStatus::InProgress,
            started_at: Some(Utc::now()),
            ..Default::default()
        };

        self.processing_phase.progress_by_file.insert(filename.to_string(), status);

        // Update summary files_by_type to track in-progress files
        if let Some(data_type) = extract_data_type(filename) {
            self.summary.files_by_type.insert(data_type, PhaseStatus::InProgress);
        }
    }

    /// Update file processing progress
    pub fn update_file_progress(&mut self, filename: &str, records: u64, messages: u64, batches: u64) {
        if let Some(status) = self.processing_phase.progress_by_file.get_mut(filename) {
            status.records_extracted = records;
            status.messages_published = messages;
            status.batches_sent = batches;
        }

        // Update processing phase totals by summing all file progress
        self.processing_phase.records_extracted = self
            .processing_phase
            .progress_by_file
            .values()
            .map(|s| s.records_extracted)
            .sum();

        // Update publishing phase totals by summing from all files
        self.publishing_phase.messages_published = self
            .processing_phase
            .progress_by_file
            .values()
            .map(|s| s.messages_published)
            .sum();
        self.publishing_phase.batches_sent = self
            .processing_phase
            .progress_by_file
            .values()
            .map(|s| s.batches_sent)
            .sum();

        // Update publishing phase status if any messages have been published
        if self.publishing_phase.messages_published > 0 {
            self.publishing_phase.status = PhaseStatus::InProgress;
            self.publishing_phase.last_amqp_heartbeat = Some(Utc::now());
        }

        // files_processed is only incremented when files complete, not during progress updates
        // This is handled by complete_file_processing()
    }

    /// Mark a file processing as completed
    pub fn complete_file_processing(&mut self, filename: &str, records: u64) {
        if let Some(status) = self.processing_phase.progress_by_file.get_mut(filename) {
            status.status = PhaseStatus::Completed;
            status.completed_at = Some(Utc::now());
            status.records_extracted = records;
        }

        self.processing_phase.files_processed += 1;

        // Update total records by summing from all files (same as update_file_progress)
        // This ensures we don't double-count since we're already tracking in progress_by_file
        self.processing_phase.records_extracted = self
            .processing_phase
            .progress_by_file
            .values()
            .map(|s| s.records_extracted)
            .sum();

        // Update publishing phase totals by summing from all files
        self.publishing_phase.messages_published = self
            .processing_phase
            .progress_by_file
            .values()
            .map(|s| s.messages_published)
            .sum();
        self.publishing_phase.batches_sent = self
            .processing_phase
            .progress_by_file
            .values()
            .map(|s| s.batches_sent)
            .sum();

        // Update summary
        if let Some(data_type) = extract_data_type(filename) {
            self.summary.files_by_type.insert(data_type, PhaseStatus::Completed);
        }
    }

    /// Mark processing phase as completed
    pub fn complete_processing(&mut self) {
        self.processing_phase.status = PhaseStatus::Completed;
        self.processing_phase.completed_at = Some(Utc::now());
        self.processing_phase.current_file = None;

        info!("✅ Processing phase completed: {} files, {} records",
              self.processing_phase.files_processed,
              self.processing_phase.records_extracted);
    }

    /// Mark processing phase as failed
    pub fn fail_processing(&mut self, error: String) {
        self.processing_phase.status = PhaseStatus::Failed;
        self.processing_phase.errors.push(error);
        self.summary.overall_status = PhaseStatus::Failed;
    }

    /// Update publishing metrics
    pub fn update_publishing(&mut self, messages: u64, batches: u64) {
        self.publishing_phase.status = PhaseStatus::InProgress;
        self.publishing_phase.messages_published += messages;
        self.publishing_phase.batches_sent += batches;
        self.publishing_phase.last_amqp_heartbeat = Some(Utc::now());
    }

    /// Mark publishing as failed
    pub fn fail_publishing(&mut self, error: String) {
        self.publishing_phase.status = PhaseStatus::Failed;
        self.publishing_phase.errors.push(error);
    }

    /// Mark entire extraction as completed
    pub fn complete_extraction(&mut self) {
        self.publishing_phase.status = PhaseStatus::Completed;
        self.summary.overall_status = PhaseStatus::Completed;

        // Calculate total duration
        if let (Some(start), Some(end)) = (
            self.download_phase.started_at,
            self.processing_phase.completed_at,
        ) {
            self.summary.total_duration_seconds = Some((end - start).num_seconds() as f64);
        }

        info!("🎉 Extraction completed for version {}", self.current_version);
    }

    /// Get list of files that still need processing
    pub fn pending_files(&self, all_files: &[String]) -> Vec<String> {
        all_files
            .iter()
            .filter(|f| {
                self.processing_phase
                    .progress_by_file
                    .get(*f)
                    .map(|status| status.status != PhaseStatus::Completed)
                    .unwrap_or(true)
            })
            .cloned()
            .collect()
    }
}

/// Decision on how to handle processing
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ProcessingDecision {
    /// Re-download and re-process everything
    Reprocess,
    /// Continue processing unfinished files
    Continue,
    /// Skip processing, already complete
    Skip,
}

/// Extract data type from filename (e.g., "discogs_20260101_artists.xml.gz" -> "artists")
fn extract_data_type(filename: &str) -> Option<String> {
    filename
        .split('_')
        .nth(2)
        .and_then(|s| s.split('.').next())
        .map(|s| s.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_new_state_marker() {
        let marker = StateMarker::new("20260101".to_string());
        assert_eq!(marker.current_version, "20260101");
        assert_eq!(marker.metadata_version, "1.0");
        assert_eq!(marker.download_phase.status, PhaseStatus::Pending);
        assert_eq!(marker.processing_phase.status, PhaseStatus::Pending);
        assert_eq!(marker.publishing_phase.status, PhaseStatus::Pending);
        assert_eq!(marker.summary.overall_status, PhaseStatus::Pending);
    }

    #[test]
    fn test_download_phase_lifecycle() {
        let mut marker = StateMarker::new("20260101".to_string());

        // Start download
        marker.start_download(4);
        assert_eq!(marker.download_phase.status, PhaseStatus::InProgress);
        assert_eq!(marker.download_phase.files_total, 4);
        assert!(marker.download_phase.started_at.is_some());

        // Download files
        marker.file_downloaded("discogs_20260101_artists.xml.gz", 1000);
        marker.file_downloaded("discogs_20260101_labels.xml.gz", 2000);
        assert_eq!(marker.download_phase.files_downloaded, 2);
        assert_eq!(marker.download_phase.bytes_downloaded, 3000);
        assert_eq!(marker.download_phase.downloads_by_file.len(), 2);

        // Complete download
        marker.complete_download();
        assert_eq!(marker.download_phase.status, PhaseStatus::Completed);
        assert!(marker.download_phase.completed_at.is_some());
    }

    #[test]
    fn test_processing_phase_lifecycle() {
        let mut marker = StateMarker::new("20260101".to_string());

        // Start processing - should also set summary status to InProgress
        marker.start_processing(4);
        assert_eq!(marker.processing_phase.status, PhaseStatus::InProgress);
        assert_eq!(marker.processing_phase.files_total, 4);
        assert_eq!(marker.summary.overall_status, PhaseStatus::InProgress);

        // Process file
        marker.start_file_processing("discogs_20260101_artists.xml.gz");
        assert_eq!(marker.processing_phase.current_file, Some("discogs_20260101_artists.xml.gz".to_string()));

        // Update progress - should update phase totals and publishing metrics
        marker.update_file_progress("discogs_20260101_artists.xml.gz", 100, 100, 2);
        assert_eq!(marker.processing_phase.records_extracted, 100); // Should sum from progress_by_file
        assert_eq!(marker.processing_phase.files_processed, 0); // No files completed yet
        assert_eq!(marker.publishing_phase.messages_published, 100); // Should aggregate from files
        assert_eq!(marker.publishing_phase.batches_sent, 2); // Should aggregate from files

        // Start another file
        marker.start_file_processing("discogs_20260101_labels.xml.gz");
        marker.update_file_progress("discogs_20260101_labels.xml.gz", 50, 50, 1);
        assert_eq!(marker.processing_phase.records_extracted, 150); // 100 + 50
        assert_eq!(marker.processing_phase.files_processed, 0); // Still no files completed
        assert_eq!(marker.publishing_phase.messages_published, 150); // 100 + 50
        assert_eq!(marker.publishing_phase.batches_sent, 3); // 2 + 1

        // Complete first file - this increments files_processed
        marker.complete_file_processing("discogs_20260101_artists.xml.gz", 100);
        assert_eq!(marker.processing_phase.files_processed, 1); // Now 1 file completed
        assert_eq!(marker.processing_phase.records_extracted, 150); // Still 150 total (complete doesn't add, it's already counted)

        // Complete processing
        marker.complete_processing();
        assert_eq!(marker.processing_phase.status, PhaseStatus::Completed);
        assert!(marker.processing_phase.completed_at.is_some());
        assert_eq!(marker.processing_phase.current_file, None);
    }

    #[test]
    fn test_should_process_decisions() {
        let mut marker = StateMarker::new("20260101".to_string());

        // New marker should continue
        assert_eq!(marker.should_process(), ProcessingDecision::Continue);

        // Failed download should reprocess
        marker.fail_download("Test error".to_string());
        assert_eq!(marker.should_process(), ProcessingDecision::Reprocess);

        // Reset and test in-progress processing
        marker = StateMarker::new("20260101".to_string());
        marker.start_processing(4);
        assert_eq!(marker.should_process(), ProcessingDecision::Continue);

        // Completed should skip
        marker.complete_processing();
        marker.complete_extraction();
        assert_eq!(marker.should_process(), ProcessingDecision::Skip);
    }

    #[test]
    fn test_pending_files() {
        let mut marker = StateMarker::new("20260101".to_string());

        let all_files = vec![
            "discogs_20260101_artists.xml.gz".to_string(),
            "discogs_20260101_labels.xml.gz".to_string(),
            "discogs_20260101_masters.xml.gz".to_string(),
        ];

        // All pending initially
        let pending = marker.pending_files(&all_files);
        assert_eq!(pending.len(), 3);

        // Mark one as completed
        marker.start_file_processing("discogs_20260101_artists.xml.gz");
        marker.complete_file_processing("discogs_20260101_artists.xml.gz", 100);

        let pending = marker.pending_files(&all_files);
        assert_eq!(pending.len(), 2);
        assert!(!pending.contains(&"discogs_20260101_artists.xml.gz".to_string()));
    }

    #[test]
    fn test_extract_data_type() {
        assert_eq!(extract_data_type("discogs_20260101_artists.xml.gz"), Some("artists".to_string()));
        assert_eq!(extract_data_type("discogs_20260101_labels.xml.gz"), Some("labels".to_string()));
        assert_eq!(extract_data_type("discogs_20260101_masters.xml.gz"), Some("masters".to_string()));
        assert_eq!(extract_data_type("discogs_20260101_releases.xml.gz"), Some("releases".to_string()));
        assert_eq!(extract_data_type("invalid.xml.gz"), None);
    }

    #[test]
    fn test_file_path_generation() {
        let path = StateMarker::file_path(Path::new("/discogs-data"), "20260101");
        assert_eq!(path, PathBuf::from("/discogs-data/.extraction_status_20260101.json"));
    }

    #[test]
    fn test_publishing_updates() {
        let mut marker = StateMarker::new("20260101".to_string());

        marker.update_publishing(100, 1);
        assert_eq!(marker.publishing_phase.status, PhaseStatus::InProgress);
        assert_eq!(marker.publishing_phase.messages_published, 100);
        assert_eq!(marker.publishing_phase.batches_sent, 1);
        assert!(marker.publishing_phase.last_amqp_heartbeat.is_some());

        marker.update_publishing(200, 2);
        assert_eq!(marker.publishing_phase.messages_published, 300);
        assert_eq!(marker.publishing_phase.batches_sent, 3);
    }

    #[test]
    fn test_complete_extraction() {
        let mut marker = StateMarker::new("20260101".to_string());

        marker.start_download(4);
        marker.complete_download();
        marker.start_processing(4);
        marker.complete_processing();
        marker.complete_extraction();

        assert_eq!(marker.summary.overall_status, PhaseStatus::Completed);
        assert_eq!(marker.publishing_phase.status, PhaseStatus::Completed);
        assert!(marker.summary.total_duration_seconds.is_some());
    }

    #[test]
    fn test_error_tracking() {
        let mut marker = StateMarker::new("20260101".to_string());

        marker.fail_download("Download failed".to_string());
        assert_eq!(marker.download_phase.status, PhaseStatus::Failed);
        assert_eq!(marker.download_phase.errors.len(), 1);
        assert_eq!(marker.summary.overall_status, PhaseStatus::Failed);

        marker = StateMarker::new("20260101".to_string());
        marker.fail_processing("Processing failed".to_string());
        assert_eq!(marker.processing_phase.status, PhaseStatus::Failed);
        assert_eq!(marker.processing_phase.errors.len(), 1);
        assert_eq!(marker.summary.overall_status, PhaseStatus::Failed);

        marker = StateMarker::new("20260101".to_string());
        marker.fail_publishing("Publishing failed".to_string());
        assert_eq!(marker.publishing_phase.status, PhaseStatus::Failed);
        assert_eq!(marker.publishing_phase.errors.len(), 1);
    }

    #[tokio::test]
    async fn test_serialization() {
        let mut marker = StateMarker::new("20260101".to_string());
        marker.start_download(4);
        marker.file_downloaded("discogs_20260101_artists.xml.gz", 1000);

        let json = serde_json::to_string_pretty(&marker).unwrap();
        let deserialized: StateMarker = serde_json::from_str(&json).unwrap();

        assert_eq!(deserialized.current_version, "20260101");
        assert_eq!(deserialized.download_phase.files_downloaded, 1);
        assert_eq!(deserialized.download_phase.bytes_downloaded, 1000);
        assert_eq!(deserialized.download_phase.downloads_by_file.len(), 1);
    }
}
