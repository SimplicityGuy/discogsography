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
    marker.download_phase.status = PhaseStatus::Failed;
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
    // MusicBrainz JSONL filenames — normalized to plural to match DataType::as_str()
    assert_eq!(extract_data_type("artist.jsonl.xz"), Some("artists".to_string()));
    assert_eq!(extract_data_type("label.jsonl.xz"), Some("labels".to_string()));
    assert_eq!(extract_data_type("release.jsonl.xz"), Some("releases".to_string()));
    assert_eq!(extract_data_type("release-group.jsonl.xz"), Some("release-groups".to_string()));
    // Non-matching filenames
    assert_eq!(extract_data_type("invalid.xml.gz"), None);
}

#[test]
fn test_file_path_generation() {
    let path = StateMarker::file_path(Path::new("/discogs-data"), "20260101");
    assert_eq!(path, PathBuf::from("/discogs-data/.extraction_status_20260101.json"));
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

#[tokio::test]
async fn test_load_missing_file() {
    let path = Path::new("/tmp/nonexistent_state_marker.json");
    let result = StateMarker::load(path).await.unwrap();
    assert!(result.is_none());
}

#[tokio::test]
async fn test_load_corrupt_file() {
    use std::io::Write;
    use tempfile::NamedTempFile;

    // Create a temporary file with corrupt JSON
    let mut temp_file = NamedTempFile::new().unwrap();
    temp_file.write_all(b"{ corrupt json }").unwrap();
    let path = temp_file.path();

    // Should return None instead of failing
    let result = StateMarker::load(path).await.unwrap();
    assert!(result.is_none());
}

#[tokio::test]
async fn test_load_and_save_roundtrip() {
    use tempfile::NamedTempFile;

    let temp_file = NamedTempFile::new().unwrap();
    let path = temp_file.path();

    // Create and save a marker
    let mut marker = StateMarker::new("20260101".to_string());
    marker.start_download(4);
    marker.file_downloaded("discogs_20260101_artists.xml.gz", 1000);
    marker.save(path).await.unwrap();

    // Load it back
    let loaded = StateMarker::load(path).await.unwrap();
    assert!(loaded.is_some());
    let loaded = loaded.unwrap();

    assert_eq!(loaded.current_version, "20260101");
    assert_eq!(loaded.download_phase.files_downloaded, 1);
    assert_eq!(loaded.download_phase.bytes_downloaded, 1000);
}

#[tokio::test]
async fn test_atomic_save_no_temp_file_remains() {
    use tempfile::TempDir;

    let temp_dir = TempDir::new().unwrap();
    let marker_path = temp_dir.path().join("test_marker.json");

    let mut marker = StateMarker::new("20260101".to_string());
    marker.start_download(2);
    marker.file_downloaded("discogs_20260101_artists.xml.gz", 1000);

    // Save to a path with .json extension
    marker.save(&marker_path).await.unwrap();

    // Verify the .json file exists
    assert!(marker_path.exists(), "State marker .json file should exist after save");

    // Verify no .json.tmp file remains (atomic rename should have removed it)
    let tmp_path = marker_path.with_extension("json.tmp");
    assert!(!tmp_path.exists(), "Temp file .json.tmp should not remain after atomic save");

    // Verify the saved file can be loaded back
    let loaded = StateMarker::load(&marker_path).await.unwrap();
    assert!(loaded.is_some(), "Should be able to load saved state marker");
    let loaded = loaded.unwrap();
    assert_eq!(loaded.current_version, "20260101");
    assert_eq!(loaded.download_phase.files_downloaded, 1);
    assert_eq!(loaded.download_phase.bytes_downloaded, 1000);
}

#[test]
fn test_complete_file_processing_syncs_messages_with_records() {
    let mut marker = StateMarker::new("20260101".to_string());

    // Start file processing
    marker.start_file_processing("discogs_20260101_artists.xml.gz");

    // Simulate periodic updates with different record/message counts
    marker.update_file_progress("discogs_20260101_artists.xml.gz", 1000, 950, 10);

    // Complete file processing with final record count
    let final_records = 1250;
    marker.complete_file_processing("discogs_20260101_artists.xml.gz", final_records);

    // Verify records are set to the final count, but messages_published
    // preserves the batcher-tracked value (950) since it was already non-zero
    let status = marker.processing_phase.progress_by_file.get("discogs_20260101_artists.xml.gz").unwrap();
    assert_eq!(status.records_extracted, final_records);
    assert_eq!(status.messages_published, 950, "messages_published should preserve the batcher-tracked value when non-zero");
}

#[test]
fn test_file_downloaded_tracks_bytes() {
    let mut marker = StateMarker::new("20260101".to_string());

    // Start download phase
    marker.start_download(2);

    // Download files with actual byte counts
    marker.start_file_download("discogs_20260101_artists.xml.gz");
    marker.file_downloaded("discogs_20260101_artists.xml.gz", 480351382);

    marker.start_file_download("discogs_20260101_labels.xml.gz");
    marker.file_downloaded("discogs_20260101_labels.xml.gz", 86848860);

    // Verify individual file byte counts
    let artists_status = marker.download_phase.downloads_by_file.get("discogs_20260101_artists.xml.gz").unwrap();
    assert_eq!(artists_status.bytes_downloaded, 480351382, "artists file should track actual bytes downloaded");

    let labels_status = marker.download_phase.downloads_by_file.get("discogs_20260101_labels.xml.gz").unwrap();
    assert_eq!(labels_status.bytes_downloaded, 86848860, "labels file should track actual bytes downloaded");

    // Verify total bytes downloaded
    let expected_total = 480351382 + 86848860;
    assert_eq!(marker.download_phase.bytes_downloaded, expected_total, "total bytes_downloaded should sum individual file downloads");
}

#[test]
fn test_file_downloaded_without_prior_tracking() {
    let mut marker = StateMarker::new("20260101".to_string());
    marker.start_download(1);

    // Call file_downloaded without calling start_file_download first
    marker.file_downloaded("discogs_20260101_artists.xml.gz", 5000);

    let status = marker.download_phase.downloads_by_file.get("discogs_20260101_artists.xml.gz").unwrap();
    assert_eq!(status.status, PhaseStatus::Completed);
    assert_eq!(status.bytes_downloaded, 5000);
    assert!(status.started_at.is_some());
    assert!(status.completed_at.is_some());
    assert_eq!(marker.download_phase.files_downloaded, 1);
    assert_eq!(marker.download_phase.bytes_downloaded, 5000);
}

#[test]
fn test_should_process_failed_processing() {
    let mut marker = StateMarker::new("20260101".to_string());

    // Set processing phase to Failed
    marker.processing_phase.status = PhaseStatus::Failed;
    assert_eq!(marker.should_process(), ProcessingDecision::Continue);
}

#[test]
fn test_sync_phase_totals_multiple_files() {
    let mut marker = StateMarker::new("20260101".to_string());
    marker.start_processing(3);

    // Start and update three files
    marker.start_file_processing("discogs_20260101_artists.xml.gz");
    marker.update_file_progress("discogs_20260101_artists.xml.gz", 200, 200, 4);

    marker.start_file_processing("discogs_20260101_labels.xml.gz");
    marker.update_file_progress("discogs_20260101_labels.xml.gz", 300, 300, 6);

    marker.start_file_processing("discogs_20260101_releases.xml.gz");
    marker.update_file_progress("discogs_20260101_releases.xml.gz", 500, 500, 10);

    // Verify aggregated totals
    assert_eq!(marker.processing_phase.records_extracted, 1000);
    assert_eq!(marker.publishing_phase.messages_published, 1000);
    assert_eq!(marker.publishing_phase.batches_sent, 20);
}

#[test]
fn test_should_process_reprocesses_interrupted_download() {
    let mut marker = StateMarker::new("test_version".to_string());
    marker.start_download(4);
    // download_phase.status is now InProgress
    assert_eq!(marker.should_process(), ProcessingDecision::Reprocess);
}

#[test]
fn test_complete_extraction_without_download_start() {
    let mut marker = StateMarker::new("20260101".to_string());

    // Never start download, so download_phase.started_at is None
    // Start and complete processing directly
    marker.start_processing(1);
    marker.start_file_processing("discogs_20260101_artists.xml.gz");
    marker.complete_file_processing("discogs_20260101_artists.xml.gz", 100);
    marker.complete_processing();
    marker.complete_extraction();

    // total_duration_seconds should be None because download_phase.started_at is None
    assert!(marker.summary.total_duration_seconds.is_none());
    assert_eq!(marker.summary.overall_status, PhaseStatus::Completed);
}
