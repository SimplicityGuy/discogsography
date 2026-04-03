use super::*;
use crate::rules::{CompiledRulesConfig, RulesConfig};

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
        let message =
            DataMessage { sha256: format!("sha{}", i), data: serde_json::json!({ "test": format!("test{}", i) }), id: i.to_string(), raw_xml: None };
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
        let message =
            DataMessage { sha256: format!("sha{}", i), data: serde_json::json!({ "test": format!("test{}", i) }), id: i.to_string(), raw_xml: None };
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
        let message =
            DataMessage { sha256: format!("sha{}", i), data: serde_json::json!({ "test": format!("test{}", i) }), id: i.to_string(), raw_xml: None };
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
        s.last_extraction_time.insert(DataType::Artists, Instant::now());
        s.last_extraction_time.insert(DataType::Labels, Instant::now());
    }

    let s = state.read().await;
    assert!(s.last_extraction_time.contains_key(&DataType::Artists));
    assert!(s.last_extraction_time.contains_key(&DataType::Labels));
}

#[tokio::test(start_paused = true)]
async fn test_progress_reporter_immediate_shutdown() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let shutdown = Arc::new(tokio::sync::Notify::new());
    let shutdown_clone = shutdown.clone();

    let handle = tokio::spawn(async move {
        progress_reporter(state, shutdown_clone).await;
    });

    // Yield to allow the spawned task to enter the select!
    tokio::task::yield_now().await;

    // Signal shutdown before any timer fires
    shutdown.notify_waiters();
    tokio::task::yield_now().await;

    assert!(handle.is_finished());
    handle.await.unwrap();
}

#[tokio::test(start_paused = true)]
async fn test_progress_reporter_logs_on_timer_fire() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    {
        let mut s = state.write().await;
        s.extraction_progress.increment(DataType::Artists);
        s.extraction_progress.increment(DataType::Labels);
        s.completed_files.insert("discogs_20260101_artists.xml.gz".to_string());
        s.active_connections.insert(DataType::Labels, "discogs_20260101_labels.xml.gz".to_string());
    }

    let shutdown = Arc::new(tokio::sync::Notify::new());
    let shutdown_clone = shutdown.clone();
    let state_clone = state.clone();

    let handle = tokio::spawn(async move {
        progress_reporter(state_clone, shutdown_clone).await;
    });

    tokio::task::yield_now().await;

    // Advance past first 10-second report interval
    tokio::time::advance(Duration::from_secs(11)).await;
    // Allow the reporter to run through the logging code
    tokio::task::yield_now().await;
    tokio::task::yield_now().await;

    // Reporter should still be running (waiting for next interval)
    assert!(!handle.is_finished());

    shutdown.notify_waiters();
    tokio::task::yield_now().await;

    assert!(handle.is_finished());
    handle.await.unwrap();
}

#[tokio::test(start_paused = true)]
async fn test_progress_reporter_interval_increases_after_three_reports() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let shutdown = Arc::new(tokio::sync::Notify::new());
    let shutdown_clone = shutdown.clone();
    let state_clone = state.clone();

    let handle = tokio::spawn(async move {
        progress_reporter(state_clone, shutdown_clone).await;
    });

    tokio::task::yield_now().await;

    // Fire first 3 short intervals (10s each)
    for _ in 0..3 {
        tokio::time::advance(Duration::from_secs(11)).await;
        tokio::task::yield_now().await;
        tokio::task::yield_now().await;
    }

    // Now on the 4th iteration the interval is 30s; 11s is not enough to fire
    tokio::time::advance(Duration::from_secs(11)).await;
    tokio::task::yield_now().await;

    // Should still be running (30s interval, only 11s elapsed)
    assert!(!handle.is_finished());

    shutdown.notify_waiters();
    tokio::task::yield_now().await;
    handle.await.unwrap();
}

#[tokio::test]
async fn test_message_batcher_triggers_state_save() {
    use crate::state_marker::StateMarker;
    use tempfile::TempDir;

    let (parse_sender, parse_receiver) = mpsc::channel::<DataMessage>(100);
    let (batch_sender, mut batch_receiver) = mpsc::channel::<Vec<DataMessage>>(100);
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    let temp_dir = TempDir::new().unwrap();
    let marker_path = temp_dir.path().join(".extraction_status_test.json");
    let mut marker = StateMarker::new("20260101".to_string());
    marker.start_file_processing("test_file.xml.gz");
    let state_marker = Arc::new(tokio::sync::Mutex::new(marker));

    // state_save_interval = 5, send exactly 5 messages to trigger a save
    let save_interval = 5usize;
    for i in 0..save_interval {
        let message = DataMessage { id: i.to_string(), sha256: format!("hash{i}"), data: serde_json::json!({}), raw_xml: None };
        parse_sender.send(message).await.unwrap();
    }
    drop(parse_sender);

    let batcher_config = BatcherConfig {
        batch_size: 100,
        data_type: DataType::Artists,
        state: state.clone(),
        state_marker: state_marker.clone(),
        marker_path: marker_path.clone(),
        file_name: "test_file.xml.gz".to_string(),
        state_save_interval: save_interval,
    };

    tokio::spawn(async move {
        message_batcher(parse_receiver, batch_sender, batcher_config).await.ok();
    });

    let mut total = 0;
    while let Some(batch) = batch_receiver.recv().await {
        total += batch.len();
    }
    assert_eq!(total, save_interval);

    // State marker file should have been created by the periodic save
    assert!(marker_path.exists(), "State marker file should be written on periodic save");
}

#[test]
fn test_extract_version_from_filename() {
    assert_eq!(extract_version_from_filename("discogs_20260101_artists.xml.gz"), Some("20260101".to_string()));
    assert_eq!(extract_version_from_filename("discogs_20241201_labels.xml.gz"), Some("20241201".to_string()));
    assert_eq!(extract_version_from_filename("discogs_20230615_masters.xml.gz"), Some("20230615".to_string()));
}

#[test]
fn test_extract_version_from_filename_invalid() {
    // No underscores
    assert_eq!(extract_version_from_filename("nounderscore"), None);
    // Single part with no underscore
    assert_eq!(extract_version_from_filename("singlepart"), None);
    // Empty string
    assert_eq!(extract_version_from_filename(""), None);
    // Single underscore should still work (parts.len() == 2)
    assert_eq!(extract_version_from_filename("discogs_20260101"), Some("20260101".to_string()));
}

#[test]
fn test_extract_data_type_with_path_prefix() {
    // Filenames with path components - the split on '_' still works because
    // the path prefix becomes part of parts[0]
    assert_eq!(extract_data_type("2026/discogs_20260101_artists.xml.gz"), Some(DataType::Artists));
    assert_eq!(extract_data_type("data/discogs_20260101_releases.xml.gz"), Some(DataType::Releases));
    assert_eq!(extract_data_type("some/deep/path/discogs_20260101_masters.xml.gz"), Some(DataType::Masters));
}

#[test]
fn test_extract_data_type_empty_string() {
    assert_eq!(extract_data_type(""), None);
}

#[tokio::test(start_paused = true)]
async fn test_progress_reporter_stall_detection() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    // Set up state: Artists has a last_extraction_time but is NOT in completed_files
    {
        let mut s = state.write().await;
        s.last_extraction_time.insert(DataType::Artists, Instant::now());
        s.extraction_progress.increment(DataType::Artists);
    }

    let shutdown = Arc::new(tokio::sync::Notify::new());
    let shutdown_clone = shutdown.clone();
    let state_clone = state.clone();

    let handle = tokio::spawn(async move {
        progress_reporter(state_clone, shutdown_clone).await;
    });

    tokio::task::yield_now().await;

    // Advance past the first 10s reporting interval
    tokio::time::advance(Duration::from_secs(11)).await;
    tokio::task::yield_now().await;
    tokio::task::yield_now().await;

    // At this point, elapsed time for Artists is ~11s which is < 120s, no stall yet.
    // Advance well past 120s total to trigger stall detection
    tokio::time::advance(Duration::from_secs(120)).await;
    tokio::task::yield_now().await;
    tokio::task::yield_now().await;

    // The reporter should have detected the stall (elapsed > 120s, file not completed).
    // We can't easily capture log output, but the code path is exercised.
    // Reporter should still be running.
    assert!(!handle.is_finished());

    shutdown.notify_waiters();
    tokio::task::yield_now().await;

    assert!(handle.is_finished());
    handle.await.unwrap();
}

#[tokio::test(start_paused = true)]
async fn test_progress_reporter_with_completed_files_and_active_connections() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    // Set up state with extraction progress, completed files, and active connections
    {
        let mut s = state.write().await;
        s.extraction_progress.artists = 1000;
        s.extraction_progress.labels = 500;
        s.extraction_progress.masters = 200;
        s.extraction_progress.releases = 300;
        s.completed_files.insert("discogs_20260101_artists.xml.gz".to_string());
        s.active_connections.insert(DataType::Labels, "discogs_20260101_labels.xml.gz".to_string());
    }

    let shutdown = Arc::new(tokio::sync::Notify::new());
    let shutdown_clone = shutdown.clone();
    let state_clone = state.clone();

    let handle = tokio::spawn(async move {
        progress_reporter(state_clone, shutdown_clone).await;
    });

    tokio::task::yield_now().await;

    // Advance past the first 10s reporting interval to fire the timer
    tokio::time::advance(Duration::from_secs(11)).await;
    tokio::task::yield_now().await;
    tokio::task::yield_now().await;

    // Reporter should still be running
    assert!(!handle.is_finished());

    // Shutdown
    shutdown.notify_waiters();
    tokio::task::yield_now().await;

    assert!(handle.is_finished());
    handle.await.unwrap();
}

#[tokio::test]
async fn test_message_batcher_multiple_batch_sizes() {
    use crate::state_marker::StateMarker;
    use tempfile::TempDir;

    let (parse_sender, parse_receiver) = mpsc::channel::<DataMessage>(100);
    let (batch_sender, mut batch_receiver) = mpsc::channel::<Vec<DataMessage>>(100);
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    let temp_dir = TempDir::new().unwrap();
    let marker_path = temp_dir.path().join(".extraction_status_test.json");
    let state_marker = Arc::new(tokio::sync::Mutex::new(StateMarker::new("20260101".to_string())));

    // Send 25 messages with batch_size=10 => expect 3 batches (10, 10, 5)
    for i in 0..25 {
        let message =
            DataMessage { id: i.to_string(), sha256: format!("sha{}", i), data: serde_json::json!({ "test": format!("test{}", i) }), raw_xml: None };
        parse_sender.send(message).await.unwrap();
    }
    drop(parse_sender);

    let batcher_config = BatcherConfig {
        batch_size: 10,
        data_type: DataType::Releases,
        state: state.clone(),
        state_marker,
        marker_path,
        file_name: "test_file.xml.gz".to_string(),
        state_save_interval: 50000,
    };

    tokio::spawn(async move {
        message_batcher(parse_receiver, batch_sender, batcher_config).await.ok();
    });

    // Collect all batches
    let mut batches = Vec::new();
    while let Some(batch) = batch_receiver.recv().await {
        batches.push(batch.len());
    }

    assert_eq!(batches.len(), 3, "Expected 3 batches, got {}: {:?}", batches.len(), batches);
    assert_eq!(batches[0], 10);
    assert_eq!(batches[1], 10);
    assert_eq!(batches[2], 5);
}

#[test]
fn test_extract_data_type_checksum_file() {
    // CHECKSUM is not a valid DataType, so extract_data_type should return None
    assert_eq!(extract_data_type("discogs_20260101_CHECKSUM.txt"), None);
}

#[tokio::test]
async fn test_message_batcher_empty_input() {
    use crate::state_marker::StateMarker;
    use tempfile::TempDir;

    let (parse_sender, parse_receiver) = mpsc::channel::<DataMessage>(10);
    let (batch_sender, mut batch_receiver) = mpsc::channel::<Vec<DataMessage>>(10);
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    let temp_dir = TempDir::new().unwrap();
    let marker_path = temp_dir.path().join(".extraction_status_test.json");
    let state_marker = Arc::new(tokio::sync::Mutex::new(StateMarker::new("20260101".to_string())));

    // Drop sender immediately - zero messages
    drop(parse_sender);

    let batcher_config = BatcherConfig {
        batch_size: 10,
        data_type: DataType::Artists,
        state: state.clone(),
        state_marker,
        marker_path,
        file_name: "test_file.xml.gz".to_string(),
        state_save_interval: 5000,
    };

    let handle = tokio::spawn(async move { message_batcher(parse_receiver, batch_sender, batcher_config).await });

    // Should receive no batches
    let result = batch_receiver.recv().await;
    assert!(result.is_none(), "Should receive no batches for empty input");

    // Batcher should exit cleanly
    let batcher_result = handle.await.unwrap();
    assert!(batcher_result.is_ok(), "Batcher should exit cleanly with no input");
}

// ── message_validator tests ─────────────────────────────────────────

fn compile_test_rules(yaml: &str) -> Arc<CompiledRulesConfig> {
    let config: RulesConfig = serde_yaml_ng::from_str(yaml).unwrap();
    Arc::new(CompiledRulesConfig::compile(config).unwrap())
}

#[tokio::test]
async fn test_message_validator_no_violations() {
    use tempfile::TempDir;

    let rules = compile_test_rules(
        r#"
rules:
  artists:
    - name: name_required
      field: name
      condition: {type: required}
      severity: error
"#,
    );

    let temp_dir = TempDir::new().unwrap();
    let (parse_sender, parse_receiver) = mpsc::channel::<DataMessage>(10);
    let (validated_sender, mut validated_receiver) = mpsc::channel::<DataMessage>(10);

    // Send a valid message (has name field)
    let msg = DataMessage { id: "1".to_string(), sha256: "abc".to_string(), data: serde_json::json!({"name": "Aphex Twin"}), raw_xml: None };
    parse_sender.send(msg).await.unwrap();
    drop(parse_sender);

    let report = message_validator(parse_receiver, validated_sender, rules, "artists", temp_dir.path(), "20260301").await.unwrap();

    // Message should be forwarded downstream
    let received = validated_receiver.recv().await.unwrap();
    assert_eq!(received.id, "1");

    // No more messages
    assert!(validated_receiver.recv().await.is_none());

    // Report should have no violations
    assert!(!report.has_violations());
    assert_eq!(report.total_records["artists"], 1);
}

#[tokio::test]
async fn test_message_validator_with_violations() {
    use tempfile::TempDir;

    let rules = compile_test_rules(
        r#"
rules:
  artists:
    - name: name_required
      field: name
      condition: {type: required}
      severity: error
"#,
    );

    let temp_dir = TempDir::new().unwrap();
    let (parse_sender, parse_receiver) = mpsc::channel::<DataMessage>(10);
    let (validated_sender, mut validated_receiver) = mpsc::channel::<DataMessage>(10);

    // Send a message missing the required name field
    let msg = DataMessage { id: "42".to_string(), sha256: "def".to_string(), data: serde_json::json!({"profile": "test"}), raw_xml: None };
    parse_sender.send(msg).await.unwrap();
    drop(parse_sender);

    let report = message_validator(parse_receiver, validated_sender, rules, "artists", temp_dir.path(), "20260301").await.unwrap();

    // Message should STILL be forwarded (validator doesn't filter)
    let received = validated_receiver.recv().await.unwrap();
    assert_eq!(received.id, "42");
    assert!(validated_receiver.recv().await.is_none());

    // Report should show violation
    assert!(report.has_violations());
    assert_eq!(report.total_records["artists"], 1);
    let rule_counts = &report.counts["artists"]["name_required"];
    assert_eq!(rule_counts.errors, 1);
}

#[tokio::test]
async fn test_message_validator_multiple_messages() {
    use tempfile::TempDir;

    let rules = compile_test_rules(
        r#"
rules:
  releases:
    - name: title_required
      field: title
      condition: {type: required}
      severity: error
    - name: year_range
      field: year
      condition: {type: range, min: 1900, max: 2100}
      severity: warning
"#,
    );

    let temp_dir = TempDir::new().unwrap();
    let (parse_sender, parse_receiver) = mpsc::channel::<DataMessage>(10);
    let (validated_sender, mut validated_receiver) = mpsc::channel::<DataMessage>(10);

    // Message 1: valid
    let msg1 =
        DataMessage { id: "1".to_string(), sha256: "a".to_string(), data: serde_json::json!({"title": "Good Album", "year": "2000"}), raw_xml: None };
    // Message 2: missing title (error) + year out of range (warning)
    let msg2 = DataMessage { id: "2".to_string(), sha256: "b".to_string(), data: serde_json::json!({"year": "1800"}), raw_xml: None };
    // Message 3: has title, year ok
    let msg3 = DataMessage {
        id: "3".to_string(),
        sha256: "c".to_string(),
        data: serde_json::json!({"title": "Another Album", "year": "1999"}),
        raw_xml: None,
    };

    parse_sender.send(msg1).await.unwrap();
    parse_sender.send(msg2).await.unwrap();
    parse_sender.send(msg3).await.unwrap();
    drop(parse_sender);

    let report = message_validator(parse_receiver, validated_sender, rules, "releases", temp_dir.path(), "20260301").await.unwrap();

    // All 3 messages forwarded
    let mut count = 0;
    while validated_receiver.recv().await.is_some() {
        count += 1;
    }
    assert_eq!(count, 3);

    // Check report
    assert_eq!(report.total_records["releases"], 3);
    assert!(report.has_violations());
    assert_eq!(report.counts["releases"]["title_required"].errors, 1);
    assert_eq!(report.counts["releases"]["year_range"].warnings, 1);
}

#[tokio::test]
async fn test_message_validator_writes_flagged_files() {
    use tempfile::TempDir;

    let rules = compile_test_rules(
        r#"
rules:
  artists:
    - name: name_required
      field: name
      condition: {type: required}
      severity: error
"#,
    );

    let temp_dir = TempDir::new().unwrap();
    let (parse_sender, parse_receiver) = mpsc::channel::<DataMessage>(10);
    let (validated_sender, mut validated_receiver) = mpsc::channel::<DataMessage>(10);

    let raw_xml = b"<artist><profile>test</profile></artist>".to_vec();
    let msg = DataMessage { id: "77".to_string(), sha256: "xyz".to_string(), data: serde_json::json!({"profile": "test"}), raw_xml: Some(raw_xml) };
    parse_sender.send(msg).await.unwrap();
    drop(parse_sender);

    let report = message_validator(parse_receiver, validated_sender, rules, "artists", temp_dir.path(), "20260301").await.unwrap();

    // Consume forwarded messages
    while validated_receiver.recv().await.is_some() {}

    assert!(report.has_violations());

    // Check flagged files were written
    let flagged_dir = temp_dir.path().join("flagged").join("20260301").join("artists");
    assert!(flagged_dir.join("77.xml").exists(), "Flagged XML should be written");
    assert!(flagged_dir.join("77.json").exists(), "Flagged JSON should be written");
    assert!(flagged_dir.join("violations.jsonl").exists(), "Violations JSONL should be written");

    // Check report file
    let report_path = temp_dir.path().join("flagged").join("20260301").join("report.txt");
    assert!(report_path.exists(), "Report file should be written");
}

#[tokio::test]
async fn test_message_validator_downstream_dropped() {
    use tempfile::TempDir;

    let rules = compile_test_rules(
        r#"
rules:
  artists:
    - name: name_required
      field: name
      condition: {type: required}
      severity: error
"#,
    );

    let temp_dir = TempDir::new().unwrap();
    let (parse_sender, parse_receiver) = mpsc::channel::<DataMessage>(10);
    let (validated_sender, validated_receiver) = mpsc::channel::<DataMessage>(1);

    // Drop receiver before sending messages
    drop(validated_receiver);

    // Send multiple messages — validator should detect dropped receiver and break
    for i in 0..5 {
        let msg = DataMessage {
            id: i.to_string(),
            sha256: format!("hash{}", i),
            data: serde_json::json!({"name": format!("Artist {}", i)}),
            raw_xml: None,
        };
        parse_sender.send(msg).await.unwrap();
    }
    drop(parse_sender);

    let report = message_validator(parse_receiver, validated_sender, rules, "artists", temp_dir.path(), "20260301").await.unwrap();

    // Should have processed at least 1 but potentially not all (downstream dropped)
    assert!(*report.total_records.get("artists").unwrap_or(&0) >= 1);
}

#[tokio::test]
async fn test_message_validator_no_rules_for_data_type() {
    use tempfile::TempDir;

    // Rules only for "releases", but we validate "artists"
    let rules = compile_test_rules(
        r#"
rules:
  releases:
    - name: title_required
      field: title
      condition: {type: required}
      severity: error
"#,
    );

    let temp_dir = TempDir::new().unwrap();
    let (parse_sender, parse_receiver) = mpsc::channel::<DataMessage>(10);
    let (validated_sender, mut validated_receiver) = mpsc::channel::<DataMessage>(10);

    let msg = DataMessage { id: "1".to_string(), sha256: "a".to_string(), data: serde_json::json!({}), raw_xml: None };
    parse_sender.send(msg).await.unwrap();
    drop(parse_sender);

    let report = message_validator(parse_receiver, validated_sender, rules, "artists", temp_dir.path(), "20260301").await.unwrap();

    // Message forwarded
    assert!(validated_receiver.recv().await.is_some());
    assert!(validated_receiver.recv().await.is_none());

    // No violations (no rules for artists)
    assert!(!report.has_violations());
    assert_eq!(report.total_records["artists"], 1);
}

// ── wait_for_trigger tests ──────────────────────────────────────────

#[tokio::test(start_paused = true)]
async fn test_wait_for_trigger_returns_when_triggered() {
    let trigger = Arc::new(tokio::sync::Mutex::new(None::<bool>));
    let trigger_clone = trigger.clone();

    let handle = tokio::spawn(async move { wait_for_trigger(&trigger_clone).await });

    // Advance past a few polling intervals — should NOT return yet
    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;
    assert!(!handle.is_finished(), "should still be waiting");

    // Set the trigger with force_reprocess = true
    {
        let mut t = trigger.lock().await;
        *t = Some(true);
    }

    // Advance past one polling interval (500ms) and yield
    tokio::time::advance(Duration::from_millis(600)).await;
    tokio::task::yield_now().await;

    // Should have returned with the force_reprocess value
    let result = handle.await.unwrap();
    assert!(result, "should return true (force_reprocess)");
}

#[tokio::test(start_paused = true)]
async fn test_wait_for_trigger_clears_flag() {
    let trigger = Arc::new(tokio::sync::Mutex::new(Some(false)));

    let result = wait_for_trigger(&trigger).await;

    // Should return false (the force_reprocess value)
    assert!(!result, "should return false (force_reprocess)");

    // Mutex should be None after taking
    assert_eq!(*trigger.lock().await, None);
}

#[tokio::test(start_paused = true)]
async fn test_wait_for_trigger_only_fires_once() {
    let trigger = Arc::new(tokio::sync::Mutex::new(Some(false)));

    // First call should return immediately (trigger is already set)
    let result = wait_for_trigger(&trigger).await;
    assert!(!result, "first call should return false");
    assert_eq!(*trigger.lock().await, None);

    // Second call should block — spawn it and verify it doesn't complete
    let trigger_clone = trigger.clone();
    let handle = tokio::spawn(async move { wait_for_trigger(&trigger_clone).await });

    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;
    assert!(!handle.is_finished(), "second wait should block until re-triggered");

    // Re-trigger with force_reprocess = true
    {
        let mut t = trigger.lock().await;
        *t = Some(true);
    }
    tokio::time::advance(Duration::from_millis(600)).await;
    tokio::task::yield_now().await;
    let result = handle.await.unwrap();
    assert!(result, "second call should return true");
}

// ── extraction_status field in ExtractorState ────────────────────────

#[test]
fn test_extractor_state_default_extraction_status() {
    let state = ExtractorState::default();
    assert_eq!(state.extraction_status, ExtractionStatus::Idle);
}

#[tokio::test]
async fn test_extraction_status_set_to_running() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    // Simulate what process_discogs_data does at startup
    {
        let mut s = state.write().await;
        s.extraction_progress = ExtractionProgress::default();
        s.last_extraction_time.clear();
        s.completed_files.clear();
        s.active_connections.clear();
        s.error_count = 0;
        s.extraction_status = ExtractionStatus::Running;
    }

    let s = state.read().await;
    assert_eq!(s.extraction_status, ExtractionStatus::Running);
}

#[tokio::test]
async fn test_extraction_status_set_completed_on_success() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    // Simulate what process_discogs_data does on success
    {
        let mut s = state.write().await;
        s.extraction_status = ExtractionStatus::Running;
    }
    {
        let mut s = state.write().await;
        let success = true;
        s.extraction_status = if success { ExtractionStatus::Completed } else { ExtractionStatus::Failed };
    }

    let s = state.read().await;
    assert_eq!(s.extraction_status, ExtractionStatus::Completed);
}

#[tokio::test]
async fn test_extraction_status_set_failed_on_error() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    // Simulate what process_discogs_data does on failure
    {
        let mut s = state.write().await;
        s.extraction_status = ExtractionStatus::Running;
    }
    {
        let mut s = state.write().await;
        let success = false;
        s.extraction_status = if success { ExtractionStatus::Completed } else { ExtractionStatus::Failed };
    }

    let s = state.read().await;
    assert_eq!(s.extraction_status, ExtractionStatus::Failed);
}

mod wait_for_discogs_idle_tests {
    use crate::extractor::{wait_for_discogs_idle, wait_for_discogs_idle_with_interval};
    use std::sync::atomic::AtomicBool;
    use tokio::time::Duration;

    #[tokio::test]
    async fn test_proceeds_when_idle() {
        let mut server = mockito::Server::new_async().await;
        let mock = server
            .mock("GET", "/health")
            .with_status(200)
            .with_header("content-type", "application/json")
            .with_body(r#"{"extraction_status": "idle"}"#)
            .create_async()
            .await;

        let shutdown = AtomicBool::new(false);
        let url = format!("{}/health", server.url());
        let result = wait_for_discogs_idle(&url, &shutdown).await;

        assert!(result.is_ok());
        mock.assert_async().await;
    }

    #[tokio::test]
    async fn test_proceeds_when_completed() {
        let mut server = mockito::Server::new_async().await;
        let mock = server
            .mock("GET", "/health")
            .with_status(200)
            .with_header("content-type", "application/json")
            .with_body(r#"{"extraction_status": "completed"}"#)
            .create_async()
            .await;

        let shutdown = AtomicBool::new(false);
        let url = format!("{}/health", server.url());
        let result = wait_for_discogs_idle(&url, &shutdown).await;

        assert!(result.is_ok());
        mock.assert_async().await;
    }

    #[tokio::test]
    async fn test_proceeds_when_failed() {
        let mut server = mockito::Server::new_async().await;
        let mock = server
            .mock("GET", "/health")
            .with_status(200)
            .with_header("content-type", "application/json")
            .with_body(r#"{"extraction_status": "failed"}"#)
            .create_async()
            .await;

        let shutdown = AtomicBool::new(false);
        let url = format!("{}/health", server.url());
        let result = wait_for_discogs_idle(&url, &shutdown).await;

        assert!(result.is_ok());
        mock.assert_async().await;
    }

    #[tokio::test]
    async fn test_waits_then_proceeds_when_running_then_idle() {
        let mut server = mockito::Server::new_async().await;
        let _mock_running = server
            .mock("GET", "/health")
            .with_status(200)
            .with_header("content-type", "application/json")
            .with_body(r#"{"extraction_status": "running"}"#)
            .expect(1)
            .create_async()
            .await;
        let _mock_idle = server
            .mock("GET", "/health")
            .with_status(200)
            .with_header("content-type", "application/json")
            .with_body(r#"{"extraction_status": "idle"}"#)
            .expect(1)
            .create_async()
            .await;

        let shutdown = AtomicBool::new(false);
        let url = format!("{}/health", server.url());
        let result =
            wait_for_discogs_idle_with_interval(&url, &shutdown, Duration::from_millis(10)).await;

        assert!(result.is_ok());
    }

    #[tokio::test]
    async fn test_proceeds_after_max_unreachable_retries() {
        // Use a port that nothing listens on
        let url = "http://127.0.0.1:19999/health";
        let shutdown = AtomicBool::new(false);
        let result =
            wait_for_discogs_idle_with_interval(url, &shutdown, Duration::from_millis(10)).await;

        assert!(result.is_ok());
    }

    #[tokio::test]
    async fn test_respects_shutdown_signal() {
        let shutdown = AtomicBool::new(true);
        // Use unreachable port — should return immediately due to shutdown flag
        let url = "http://127.0.0.1:19999/health";
        let result =
            wait_for_discogs_idle_with_interval(url, &shutdown, Duration::from_millis(10)).await;

        assert!(result.is_ok());
    }
}
