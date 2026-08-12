use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use tokio::fs;
use tokio::io::AsyncWriteExt;
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
    /// SHA-256 of the bytes currently on disk for this file, once verified.
    ///
    /// This is what links the two otherwise-independent phase machines: a processing
    /// status is only valid for the byte-image it was computed from, and that image is
    /// identified here. Defaulted so markers written before this field existed still load.
    #[serde(default)]
    pub checksum: Option<String>,
}

impl Default for FileDownloadStatus {
    fn default() -> Self {
        Self { status: PhaseStatus::Pending, bytes_downloaded: 0, started_at: None, completed_at: None, checksum: None }
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
    /// Checksum of the downloaded byte-image this processing status was computed from.
    ///
    /// `None` means the provenance is unknown (a marker written before this field existed),
    /// in which case the status is left alone rather than speculatively invalidated.
    #[serde(default)]
    pub source_checksum: Option<String>,
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
            source_checksum: None,
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
        Self { status: PhaseStatus::Pending, messages_published: 0, batches_sent: 0, errors: Vec::new(), last_amqp_heartbeat: None }
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
        Self { overall_status: PhaseStatus::Pending, total_duration_seconds: None, files_by_type: HashMap::new() }
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

    /// Load state marker from file. Callers only ever pass paths built by `file_path()` /
    /// `musicbrainz_file_path()` below, which embed `version` as a substring of a fixed
    /// `.extraction_status_<version>.json` filename under an operator-controlled root — `version`
    /// itself is always a slash-free basename fragment (see extractor.rs), so this can never
    /// escape the configured root directory.
    pub async fn load(path: &Path) -> Result<Option<Self>> {
        if !path.exists() {
            debug!("📋 No state marker found at: {}", path.display());
            return Ok(None);
        }

        // Try to read and parse the file, but return None if it fails
        // This allows the extractor to start fresh if the state file is corrupt
        let read_result = fs::read_to_string(path).await; // nosemgrep: rust.actix.path-traversal.tainted-path.tainted-path
        let contents = match read_result {
            Ok(contents) => contents,
            Err(e) => {
                warn!("⚠️ Failed to read state marker file, will start fresh: {}", e);
                return Ok(None);
            }
        };

        match serde_json::from_str::<StateMarker>(&contents) {
            Ok(marker) => {
                info!("📋 Loaded state marker for version: {}", marker.current_version);
                Ok(Some(marker))
            }
            Err(e) => {
                warn!("⚠️ Failed to parse state marker JSON, will start fresh: {}", e);
                Ok(None)
            }
        }
    }

    /// Save state marker to file.
    ///
    /// Durability, not just atomicity. `write(tmp)` + `rename` alone guarantees that a
    /// READER never observes a torn file, but says nothing about what survives a power
    /// loss or kernel panic: `tokio::fs::write` is open+write+close with no fsync, and
    /// `rename` issues no directory fsync, so POSIX allows the rename's directory entry
    /// to reach stable storage while the file's data blocks are still in the page cache
    /// (dirty writeback runs every ~5-30s). The marker then comes back zero-length or
    /// truncated, `load` treats any parse failure as "start fresh", and the extractor
    /// re-downloads and re-publishes a whole multi-GB dump — exactly what the
    /// tmp+rename design was meant to prevent (discogsography-mm27).
    ///
    /// So: fsync the temp file's contents BEFORE the rename, then fsync the parent
    /// directory AFTER it so the rename itself is durable. The downloader already does
    /// the equivalent for the dump files it writes (`discogs_downloader.rs`'s
    /// `sync_data`).
    pub async fn save(&mut self, path: &Path) -> Result<()> {
        self.last_updated = Utc::now();

        let json = serde_json::to_string_pretty(self).context("Failed to serialize state marker")?;

        // Write to temp file then atomic rename to prevent corruption on crash
        let tmp_path = path.with_extension("json.tmp");
        {
            let mut tmp_file = fs::File::create(&tmp_path).await.context("Failed to create state marker temp file")?;
            tmp_file.write_all(json.as_bytes()).await.context("Failed to write state marker temp file")?;
            // Data blocks + metadata on stable storage before anything points at them.
            tmp_file.sync_all().await.context("Failed to fsync state marker temp file")?;
        }
        fs::rename(&tmp_path, path).await.context("Failed to rename state marker temp file")?;

        // Persist the directory entry created by the rename. Without this the file
        // contents are durable but the name pointing at them may not be.
        if let Some(parent) = path.parent() {
            match fs::File::open(parent).await {
                // Best effort: some filesystems reject fsync on a directory handle, and
                // a marker that is merely un-fsynced is still far better than failing
                // the extraction over it.
                Ok(dir) => {
                    if let Err(e) = dir.sync_all().await {
                        debug!("⚠️ Could not fsync state marker directory {}: {}", parent.display(), e);
                    }
                }
                Err(e) => debug!("⚠️ Could not open state marker directory {} for fsync: {}", parent.display(), e),
            }
        }

        debug!("💾 Saved state marker to: {}", path.display());
        Ok(())
    }

    /// Get the file path for a Discogs version's state marker.
    ///
    /// For MusicBrainz markers, use [`musicbrainz_file_path`] instead — MusicBrainz
    /// markers live in a versioned subdirectory with a different filename prefix.
    pub fn file_path(discogs_root: &Path, version: &str) -> PathBuf {
        discogs_root.join(format!(".extraction_status_{}.json", version))
    }

    /// Get the file path for a MusicBrainz version's state marker.
    ///
    /// MusicBrainz markers are stored inside `musicbrainz_root/<version>/`
    /// (the versioned subdirectory), not at the root level.
    pub fn musicbrainz_file_path(musicbrainz_root: &Path, version: &str) -> PathBuf {
        musicbrainz_root.join(version).join(format!(".mb_extraction_status_{}.json", version))
    }

    /// Number of files that have finished processing.
    pub fn completed_file_count(&self) -> usize {
        self.processing_phase.progress_by_file.values().filter(|s| s.status == PhaseStatus::Completed).count()
    }

    /// Check if we should re-process, continue, or skip
    pub fn should_process(&self) -> ProcessingDecision {
        // A failed or interrupted download phase normally means "start over". That is
        // only safe while nothing has been processed yet: the download layer is
        // idempotent and self-healing (checksums re-download exactly what is missing or
        // corrupt), whereas processing progress costs hours of parsing and tens of
        // millions of republished messages to rebuild. A resumed run re-enters the
        // download phase on every cycle just to re-verify already-present dumps, so a
        // crash inside that window must not demote completed files.
        let download_incomplete = self.download_phase.status == PhaseStatus::Failed || self.download_phase.status == PhaseStatus::InProgress;

        if download_incomplete {
            let completed = self.completed_file_count();
            if completed > 0 {
                warn!(
                    "⚠️ Download phase {:?} but {} file(s) already processed, will resume (downloads self-heal via checksums)",
                    self.download_phase.status, completed
                );
                return ProcessingDecision::Continue;
            }

            if self.download_phase.status == PhaseStatus::Failed {
                warn!("⚠️ Download phase failed, will re-download");
            } else {
                warn!("⚠️ Download phase interrupted, will re-download");
            }
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
        self.download_phase.downloads_by_file.clear();
    }

    /// Mark a file download as started
    pub fn start_file_download(&mut self, filename: &str) {
        let status = FileDownloadStatus { status: PhaseStatus::InProgress, started_at: Some(Utc::now()), ..Default::default() };
        self.download_phase.downloads_by_file.insert(filename.to_string(), status);
    }

    /// Mark a file as downloaded
    pub fn file_downloaded(&mut self, filename: &str, bytes: u64) {
        // Only increment files_downloaded if this file was not already completed
        // (avoids double-counting on retry/resume)
        let already_completed = self.download_phase.downloads_by_file.get(filename).is_some_and(|s| s.status == PhaseStatus::Completed);

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
                    checksum: None,
                },
            );
        }

        if !already_completed {
            self.download_phase.files_downloaded += 1;
        }
        // Recalculate total bytes from all files
        self.download_phase.bytes_downloaded = self.download_phase.downloads_by_file.values().map(|s| s.bytes_downloaded).sum();
    }

    /// Record the checksum of the bytes now on disk for `filename` and, if a completed
    /// processing status was derived from *different* bytes, invalidate it so the file is
    /// processed again.
    ///
    /// The download and processing phases are otherwise independent state machines keyed by
    /// the same filename, with no invariant linking them. That let a file whose bytes had
    /// just been declared untrustworthy — and re-downloaded to replace them — keep a
    /// `Completed` processing status computed from the old, bad bytes: `pending_files()`
    /// filters purely on processing status, so the corrected file was never re-parsed and
    /// the run still finalized as Completed, permanently for that version.
    ///
    /// Invalidation is deliberately narrow. It fires only when both checksums are known and
    /// they differ, so the common case of an operator deleting a processed `.xml.gz` to
    /// reclaim disk (re-downloaded → identical bytes) does not force a needless reparse, and
    /// markers predating the checksum field are left untouched.
    ///
    /// Returns `true` when a completed processing status was invalidated.
    pub fn file_bytes_verified(&mut self, filename: &str, checksum: &str) -> bool {
        let previous_checksum = match self.processing_phase.progress_by_file.get(filename) {
            Some(status) if status.status == PhaseStatus::Completed => status.source_checksum.clone(),
            _ => None,
        };

        if let Some(status) = self.download_phase.downloads_by_file.get_mut(filename) {
            status.checksum = Some(checksum.to_string());
        }

        let stale = previous_checksum.is_some_and(|previous| previous != checksum);
        if !stale {
            return false;
        }

        warn!("⚠️ {} was re-downloaded with different bytes than the ones already processed — re-queuing it for processing", filename);

        self.processing_phase.progress_by_file.remove(filename);
        self.processing_phase.files_processed = self.processing_phase.files_processed.saturating_sub(1);
        if let Some(data_type) = extract_data_type(filename) {
            self.summary.files_by_type.insert(data_type, PhaseStatus::Pending);
        }
        // Drop the stale record/message counts too — they feed /health totals and the
        // extraction_complete record_counts broadcast.
        self.sync_phase_totals();

        // The version is no longer fully processed, so it must not be skipped on a later cycle.
        if self.summary.overall_status == PhaseStatus::Completed {
            self.summary.overall_status = PhaseStatus::InProgress;
        }
        if self.processing_phase.status == PhaseStatus::Completed {
            self.processing_phase.status = PhaseStatus::InProgress;
            self.processing_phase.completed_at = None;
        }

        true
    }

    /// Mark download phase as completed
    pub fn complete_download(&mut self) {
        self.download_phase.status = PhaseStatus::Completed;
        self.download_phase.completed_at = Some(Utc::now());
        info!("✅ Download phase completed: {} files, {} bytes", self.download_phase.files_downloaded, self.download_phase.bytes_downloaded);
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

        // Bind this processing attempt to the byte-image it is about to read, so a later
        // re-download of different bytes can tell that the resulting status is stale.
        let source_checksum = self.download_phase.downloads_by_file.get(filename).and_then(|s| s.checksum.clone());

        let status = FileProcessingStatus { status: PhaseStatus::InProgress, started_at: Some(Utc::now()), source_checksum, ..Default::default() };

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

        self.sync_phase_totals();

        // Update publishing phase status if any messages have been published
        if self.publishing_phase.messages_published > 0 {
            self.publishing_phase.status = PhaseStatus::InProgress;
            self.publishing_phase.last_amqp_heartbeat = Some(Utc::now());
        }
    }

    /// Mark a file processing as completed
    pub fn complete_file_processing(&mut self, filename: &str, records: u64) {
        if let Some(status) = self.processing_phase.progress_by_file.get_mut(filename) {
            status.status = PhaseStatus::Completed;
            status.completed_at = Some(Utc::now());
            status.records_extracted = records;
            // Only set messages_published if it was not tracked independently
            if status.messages_published == 0 {
                status.messages_published = records;
            }
        }

        self.processing_phase.files_processed += 1;
        self.sync_phase_totals();

        // Update summary
        if let Some(data_type) = extract_data_type(filename) {
            self.summary.files_by_type.insert(data_type, PhaseStatus::Completed);
        }
    }

    /// Sync processing and publishing phase totals from per-file progress
    fn sync_phase_totals(&mut self) {
        self.processing_phase.records_extracted = self.processing_phase.progress_by_file.values().map(|s| s.records_extracted).sum();
        self.publishing_phase.messages_published = self.processing_phase.progress_by_file.values().map(|s| s.messages_published).sum();
        self.publishing_phase.batches_sent = self.processing_phase.progress_by_file.values().map(|s| s.batches_sent).sum();
    }

    /// Mark processing phase as completed
    pub fn complete_processing(&mut self) {
        self.processing_phase.status = PhaseStatus::Completed;
        self.processing_phase.completed_at = Some(Utc::now());
        self.processing_phase.current_file = None;

        info!("✅ Processing phase completed: {} files, {} records", self.processing_phase.files_processed, self.processing_phase.records_extracted);
    }

    /// Mark entire extraction as completed
    pub fn complete_extraction(&mut self) {
        self.publishing_phase.status = PhaseStatus::Completed;
        self.summary.overall_status = PhaseStatus::Completed;

        // Calculate total duration
        if let (Some(start), Some(end)) = (self.download_phase.started_at, self.processing_phase.completed_at) {
            self.summary.total_duration_seconds = Some((end - start).num_seconds() as f64);
        }

        info!("🎉 Extraction completed for version {}", self.current_version);
    }

    /// Get list of files that still need processing
    pub fn pending_files(&self, all_files: &[String]) -> Vec<String> {
        all_files
            .iter()
            .filter(|f| self.processing_phase.progress_by_file.get(*f).map(|status| status.status != PhaseStatus::Completed).unwrap_or(true))
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

/// Extract data type from filename.
///
/// Handles both Discogs filenames (e.g., "discogs_20260101_artists.xml.gz" -> "artists")
/// and MusicBrainz filenames (e.g., "artist.jsonl.xz" -> "artists").
///
/// MusicBrainz filenames use singular forms (artist, label, release, release-group)
/// which are normalized to plural to match `DataType::as_str()`.
fn extract_data_type(filename: &str) -> Option<String> {
    // Try Discogs format first: third underscore-delimited segment
    if let Some(data_type) = filename.split('_').nth(2).and_then(|s| s.split('.').next()) {
        return Some(data_type.to_string());
    }
    // MusicBrainz format: no underscores, contains ".jsonl"
    // Normalize singular to plural to match DataType::as_str()
    if !filename.contains('_') && filename.contains(".jsonl") {
        return filename.split('.').next().filter(|s| !s.is_empty()).map(|s| {
            // Strip optional "mbdump-" prefix before matching singular to plural
            let base = s.strip_prefix("mbdump-").unwrap_or(s);
            match base {
                "artist" => "artists".to_string(),
                "label" => "labels".to_string(),
                "release" => "releases".to_string(),
                "release-group" => "release-groups".to_string(),
                other => other.to_string(),
            }
        });
    }
    None
}

#[cfg(test)]
#[path = "tests/state_marker_tests.rs"]
mod tests;
