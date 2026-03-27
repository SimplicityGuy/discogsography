use extractor::config::ExtractorConfig;
use extractor::discogs_downloader::MockDataSource;
use extractor::extractor::DefaultMessageQueueFactory;
use extractor::extractor::{ExtractionStatus, ExtractorState, message_publisher, process_musicbrainz_data, process_single_file};
use extractor::message_queue::MockMessagePublisher;
use extractor::state_marker::StateMarker;
use extractor::types::S3FileInfo;
use extractor::types::{DataMessage, DataType, Source};
use std::sync::Arc;
use tempfile::TempDir;
use tokio::sync::{Mutex, RwLock};

mod mock_helpers;
use mock_helpers::MockMqFactory;

/// Helper to create a test config with all required fields.
fn test_config(root: &std::path::Path) -> ExtractorConfig {
    ExtractorConfig {
        amqp_connection: "amqp://localhost:5672/%2F".to_string(),
        discogs_root: root.to_path_buf(),
        periodic_check_days: 1,
        health_port: 0,
        max_workers: 2,
        batch_size: 100,
        queue_size: 100,
        progress_log_interval: 1000,
        state_save_interval: 1000,
        data_quality_rules: None,
        source: Source::Discogs,
        musicbrainz_root: std::path::PathBuf::from("/musicbrainz-data"),
        amqp_exchange_prefix: "discogsography".to_string(),
    }
}

#[tokio::test]
async fn test_process_single_file_mq_setup_called() {
    let temp_dir = TempDir::new().unwrap();
    let config = Arc::new(test_config(temp_dir.path()));
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let state_marker = Arc::new(Mutex::new(StateMarker::new("20260101".to_string())));
    let marker_path = temp_dir.path().join("marker.json");

    let mut mock_mq = MockMessagePublisher::new();
    mock_mq.expect_setup_exchange().withf(|dt| *dt == DataType::Artists).times(1).returning(|_| Ok(()));
    mock_mq.expect_close().times(..).returning(|| Ok(()));
    mock_mq.expect_publish_batch().returning(|_, _| Ok(()));
    mock_mq.expect_send_file_complete().returning(|_, _, _| Ok(()));

    let mq: Arc<dyn extractor::message_queue::MessagePublisher> = Arc::new(mock_mq);

    let result = process_single_file("discogs_20260101_artists.xml.gz", config, state, state_marker, marker_path, mq, None).await;

    // Error expected — file doesn't exist on disk
    assert!(result.is_err());
}

#[tokio::test]
async fn test_message_publisher_increments_error_count_on_failure() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    let mut mock_mq = MockMessagePublisher::new();
    mock_mq.expect_publish_batch().times(1).returning(|_, _| Err(anyhow::anyhow!("AMQP connection lost")));

    let mq: Arc<dyn extractor::message_queue::MessagePublisher> = Arc::new(mock_mq);
    let (sender, receiver) = tokio::sync::mpsc::channel::<Vec<DataMessage>>(10);

    sender.send(vec![]).await.unwrap();
    drop(sender);

    let result = message_publisher(receiver, mq, DataType::Artists, state.clone()).await;

    assert!(result.is_err());
    let s = state.read().await;
    assert_eq!(s.error_count, 1);
}

#[tokio::test]
async fn test_message_publisher_success_path() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    let mut mock_mq = MockMessagePublisher::new();
    mock_mq.expect_publish_batch().times(3).returning(|_, _| Ok(()));

    let mq: Arc<dyn extractor::message_queue::MessagePublisher> = Arc::new(mock_mq);
    let (sender, receiver) = tokio::sync::mpsc::channel::<Vec<DataMessage>>(10);

    for _ in 0..3 {
        sender.send(vec![]).await.unwrap();
    }
    drop(sender);

    let result = message_publisher(receiver, mq, DataType::Artists, state.clone()).await;

    assert!(result.is_ok());
    let s = state.read().await;
    assert_eq!(s.error_count, 0);
}

#[tokio::test]
async fn test_process_discogs_data_empty_files() {
    let temp_dir = TempDir::new().unwrap();
    let config = Arc::new(test_config(temp_dir.path()));
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let shutdown = Arc::new(tokio::sync::Notify::new());

    let mut mock_dl = MockDataSource::new();
    mock_dl.expect_list_s3_files().times(1).returning(|| Ok(vec![]));
    mock_dl.expect_get_latest_monthly_files().times(1).returning(|_| Ok(vec![]));

    let mock_mq = MockMessagePublisher::new();
    let factory = Arc::new(MockMqFactory { publisher: Arc::new(mock_mq) });

    let result = extractor::extractor::process_discogs_data(config, state, shutdown, false, &mut mock_dl, factory, None).await;

    assert!(result.is_ok());
    assert!(result.unwrap());
}

#[tokio::test]
async fn test_process_discogs_data_skip_when_already_complete() {
    let temp_dir = TempDir::new().unwrap();
    let config = Arc::new(test_config(temp_dir.path()));
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let shutdown = Arc::new(tokio::sync::Notify::new());

    // Create a fully completed state marker
    let mut marker = StateMarker::new("20260101".to_string());
    marker.complete_processing();
    marker.complete_extraction();
    let marker_path = StateMarker::file_path(temp_dir.path(), "20260101");
    marker.save(&marker_path).await.unwrap();

    let mut mock_dl = MockDataSource::new();
    mock_dl.expect_list_s3_files().returning(|| {
        Ok(vec![
            S3FileInfo { name: "data/discogs_20260101_artists.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_labels.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_masters.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_releases.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_CHECKSUM.txt".to_string(), size: 100 },
        ])
    });
    mock_dl.expect_get_latest_monthly_files().returning(|_| {
        Ok(vec![
            S3FileInfo { name: "discogs_20260101_artists.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "discogs_20260101_labels.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "discogs_20260101_masters.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "discogs_20260101_releases.xml.gz".to_string(), size: 1000 },
        ])
    });

    let mock_mq = MockMessagePublisher::new();
    let factory = Arc::new(MockMqFactory { publisher: Arc::new(mock_mq) });

    let result = extractor::extractor::process_discogs_data(config, state, shutdown, false, &mut mock_dl, factory, None).await;

    assert!(result.is_ok());
    assert!(result.unwrap());
}

#[tokio::test]
async fn test_process_discogs_data_force_reprocess_bypasses_skip() {
    let temp_dir = TempDir::new().unwrap();
    let config = Arc::new(test_config(temp_dir.path()));
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let shutdown = Arc::new(tokio::sync::Notify::new());

    // Create a fully completed state marker — force_reprocess should ignore it
    let mut marker = StateMarker::new("20260101".to_string());
    marker.complete_processing();
    marker.complete_extraction();
    let marker_path = StateMarker::file_path(temp_dir.path(), "20260101");
    marker.save(&marker_path).await.unwrap();

    let mut mock_dl = MockDataSource::new();
    mock_dl.expect_list_s3_files().returning(|| {
        Ok(vec![
            S3FileInfo { name: "data/discogs_20260101_artists.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_labels.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_masters.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_releases.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_CHECKSUM.txt".to_string(), size: 100 },
        ])
    });
    mock_dl.expect_get_latest_monthly_files().returning(|_| {
        Ok(vec![
            S3FileInfo { name: "discogs_20260101_artists.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "discogs_20260101_labels.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "discogs_20260101_masters.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "discogs_20260101_releases.xml.gz".to_string(), size: 1000 },
        ])
    });
    mock_dl.expect_set_state_marker().times(1).returning(|_, _| ());
    mock_dl.expect_download_discogs_data().times(1).returning(|| {
        Ok(vec![
            "discogs_20260101_artists.xml.gz".to_string(),
            "discogs_20260101_labels.xml.gz".to_string(),
            "discogs_20260101_masters.xml.gz".to_string(),
            "discogs_20260101_releases.xml.gz".to_string(),
        ])
    });
    mock_dl.expect_take_state_marker().times(1).returning(|| Some(StateMarker::new("20260101".to_string())));

    let mut mock_mq = MockMessagePublisher::new();
    mock_mq.expect_setup_exchange().returning(|_| Ok(()));
    mock_mq.expect_publish_batch().returning(|_, _| Ok(()));
    mock_mq.expect_send_file_complete().returning(|_, _, _| Ok(()));
    mock_mq.expect_send_extraction_complete().returning(|_, _, _| Ok(()));
    mock_mq.expect_close().returning(|| Ok(()));

    let factory = Arc::new(MockMqFactory { publisher: Arc::new(mock_mq) });

    let result = extractor::extractor::process_discogs_data(config, state, shutdown, true, &mut mock_dl, factory, None).await;

    // Result may be Ok or Err — key assertion is download_discogs_data was called (verified by mock times(1))
    let _ = result;
}

#[tokio::test]
async fn test_default_mq_factory_create_fails_without_broker() {
    use extractor::extractor::MessageQueueFactory;

    let factory = DefaultMessageQueueFactory;
    // Invalid port so connection fails fast
    let result: anyhow::Result<Arc<dyn extractor::message_queue::MessagePublisher>> =
        factory.create("amqp://localhost:59999", "discogsography").await;
    assert!(result.is_err());
}

#[tokio::test]
async fn test_process_discogs_data_take_state_marker_none() {
    let temp_dir = TempDir::new().unwrap();
    let config = Arc::new(test_config(temp_dir.path()));
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let shutdown = Arc::new(tokio::sync::Notify::new());

    let mut mock_dl = MockDataSource::new();
    mock_dl.expect_list_s3_files().returning(|| {
        Ok(vec![
            S3FileInfo { name: "data/discogs_20260101_artists.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_labels.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_masters.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_releases.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_CHECKSUM.txt".to_string(), size: 100 },
        ])
    });
    mock_dl.expect_get_latest_monthly_files().returning(|_| {
        Ok(vec![
            S3FileInfo { name: "discogs_20260101_artists.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "discogs_20260101_labels.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "discogs_20260101_masters.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "discogs_20260101_releases.xml.gz".to_string(), size: 1000 },
        ])
    });
    mock_dl.expect_set_state_marker().times(1).returning(|_, _| ());
    mock_dl.expect_download_discogs_data().times(1).returning(|| Ok(vec!["discogs_20260101_artists.xml.gz".to_string()]));
    // Return None to trigger the "State marker missing after download" error
    mock_dl.expect_take_state_marker().times(1).returning(|| None);

    let mock_mq = MockMessagePublisher::new();
    let factory = Arc::new(MockMqFactory { publisher: Arc::new(mock_mq) });

    let result = extractor::extractor::process_discogs_data(config, state, shutdown, true, &mut mock_dl, factory, None).await;

    assert!(result.is_err());
    let err_msg = format!("{}", result.err().unwrap());
    assert!(err_msg.contains("State marker missing after download"), "Unexpected error: {}", err_msg);
}

#[tokio::test]
async fn test_process_discogs_data_no_data_files() {
    let temp_dir = TempDir::new().unwrap();
    let config = Arc::new(test_config(temp_dir.path()));
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let shutdown = Arc::new(tokio::sync::Notify::new());

    let mut mock_dl = MockDataSource::new();
    mock_dl.expect_list_s3_files().returning(|| {
        Ok(vec![
            S3FileInfo { name: "data/discogs_20260101_artists.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_labels.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_masters.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_releases.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_CHECKSUM.txt".to_string(), size: 100 },
        ])
    });
    mock_dl.expect_get_latest_monthly_files().returning(|_| {
        Ok(vec![
            S3FileInfo { name: "discogs_20260101_artists.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "discogs_20260101_labels.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "discogs_20260101_masters.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "discogs_20260101_releases.xml.gz".to_string(), size: 1000 },
        ])
    });
    mock_dl.expect_set_state_marker().times(1).returning(|_, _| ());
    // Return only CHECKSUM — all get filtered out
    mock_dl.expect_download_discogs_data().times(1).returning(|| Ok(vec!["discogs_20260101_CHECKSUM.txt".to_string()]));
    mock_dl.expect_take_state_marker().times(1).returning(|| Some(StateMarker::new("20260101".to_string())));

    let mock_mq = MockMessagePublisher::new();
    let factory = Arc::new(MockMqFactory { publisher: Arc::new(mock_mq) });

    let result = extractor::extractor::process_discogs_data(config, state, shutdown, true, &mut mock_dl, factory, None).await;

    // Should return Ok(true) — "No data files to process"
    assert!(result.is_ok());
    assert!(result.unwrap());
}

#[tokio::test]
async fn test_process_discogs_data_all_files_already_processed() {
    let temp_dir = TempDir::new().unwrap();
    let config = Arc::new(test_config(temp_dir.path()));
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let shutdown = Arc::new(tokio::sync::Notify::new());

    // Create a state marker where processing is started but all files are complete
    let mut marker = StateMarker::new("20260101".to_string());
    marker.start_processing(1);
    marker.start_file_processing("discogs_20260101_artists.xml.gz");
    marker.complete_file_processing("discogs_20260101_artists.xml.gz", 1000);

    let mut mock_dl = MockDataSource::new();
    mock_dl.expect_list_s3_files().returning(|| {
        Ok(vec![
            S3FileInfo { name: "data/discogs_20260101_artists.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_labels.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_masters.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_releases.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_CHECKSUM.txt".to_string(), size: 100 },
        ])
    });
    mock_dl.expect_get_latest_monthly_files().returning(|_| {
        Ok(vec![
            S3FileInfo { name: "discogs_20260101_artists.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "discogs_20260101_labels.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "discogs_20260101_masters.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "discogs_20260101_releases.xml.gz".to_string(), size: 1000 },
        ])
    });
    mock_dl.expect_set_state_marker().times(1).returning(|_, _| ());
    mock_dl.expect_download_discogs_data().times(1).returning(|| Ok(vec!["discogs_20260101_artists.xml.gz".to_string()]));
    mock_dl.expect_take_state_marker().times(1).returning(move || Some(marker.clone()));

    let mut mock_mq = MockMessagePublisher::new();
    mock_mq.expect_send_extraction_complete().returning(|_, _, _| Ok(()));
    mock_mq.expect_close().returning(|| Ok(()));

    let factory = Arc::new(MockMqFactory { publisher: Arc::new(mock_mq) });

    let result = extractor::extractor::process_discogs_data(config, state, shutdown, true, &mut mock_dl, factory, None).await;

    assert!(result.is_ok());
    assert!(result.unwrap());
}

#[tokio::test]
async fn test_process_discogs_data_mq_factory_create_fails_on_all_processed() {
    let temp_dir = TempDir::new().unwrap();
    let config = Arc::new(test_config(temp_dir.path()));
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let shutdown = Arc::new(tokio::sync::Notify::new());

    let mut marker = StateMarker::new("20260101".to_string());
    marker.start_processing(1);
    marker.start_file_processing("discogs_20260101_artists.xml.gz");
    marker.complete_file_processing("discogs_20260101_artists.xml.gz", 1000);

    let mut mock_dl = MockDataSource::new();
    mock_dl.expect_list_s3_files().returning(|| {
        Ok(vec![
            S3FileInfo { name: "data/discogs_20260101_artists.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_labels.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_masters.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_releases.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_CHECKSUM.txt".to_string(), size: 100 },
        ])
    });
    mock_dl.expect_get_latest_monthly_files().returning(|_| {
        Ok(vec![
            S3FileInfo { name: "discogs_20260101_artists.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "discogs_20260101_labels.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "discogs_20260101_masters.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "discogs_20260101_releases.xml.gz".to_string(), size: 1000 },
        ])
    });
    mock_dl.expect_set_state_marker().times(1).returning(|_, _| ());
    mock_dl.expect_download_discogs_data().times(1).returning(|| Ok(vec!["discogs_20260101_artists.xml.gz".to_string()]));
    mock_dl.expect_take_state_marker().times(1).returning(move || Some(marker.clone()));

    // Factory that fails to create MQ connection — exercises the error path
    use extractor::extractor::MessageQueueFactory;
    struct FailingMqFactory;
    #[async_trait::async_trait]
    impl MessageQueueFactory for FailingMqFactory {
        async fn create(&self, _url: &str, _exchange_prefix: &str) -> anyhow::Result<Arc<dyn extractor::message_queue::MessagePublisher>> {
            Err(anyhow::anyhow!("AMQP connection refused"))
        }
    }
    let factory = Arc::new(FailingMqFactory);

    let result = extractor::extractor::process_discogs_data(config, state, shutdown, true, &mut mock_dl, factory, None).await;

    // Should still succeed (extraction_complete failure is logged, not fatal)
    assert!(result.is_ok());
    assert!(result.unwrap());
}

// ──────────────────────────────────────────────────────────────────────────────
// MusicBrainz pipeline tests
// ──────────────────────────────────────────────────────────────────────────────

/// Helper to create a test config pointing musicbrainz_root at a temp dir.
fn mb_test_config(mb_root: &std::path::Path) -> ExtractorConfig {
    ExtractorConfig {
        amqp_connection: "amqp://localhost:5672/%2F".to_string(),
        discogs_root: std::path::PathBuf::from("/discogs-data"),
        periodic_check_days: 1,
        health_port: 0,
        max_workers: 2,
        batch_size: 100,
        queue_size: 100,
        progress_log_interval: 1000,
        state_save_interval: 1000,
        data_quality_rules: None,
        source: Source::MusicBrainz,
        musicbrainz_root: mb_root.to_path_buf(),
        amqp_exchange_prefix: "discogsography-mb".to_string(),
    }
}

#[tokio::test]
async fn test_process_musicbrainz_data_empty_dump_dir() {
    // Empty directory — no dump files found
    let temp_dir = TempDir::new().unwrap();
    let config = Arc::new(mb_test_config(temp_dir.path()));
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let shutdown = Arc::new(tokio::sync::Notify::new());

    let mock_mq = MockMessagePublisher::new();
    let factory = Arc::new(MockMqFactory { publisher: Arc::new(mock_mq) });

    let result = process_musicbrainz_data(config, state.clone(), shutdown, false, factory, None).await;

    assert!(result.is_ok());
    assert!(result.unwrap()); // Returns true — "no dump files"

    let s = state.read().await;
    assert_eq!(s.extraction_status, ExtractionStatus::Completed);
}

#[tokio::test]
async fn test_process_musicbrainz_data_skip_when_already_complete() {
    // Create a temp dir with a dump file so discover_mb_dump_files finds something
    let temp_dir = TempDir::new().unwrap();
    let mb_root = temp_dir.path().join("20260322");
    std::fs::create_dir_all(&mb_root).unwrap();
    std::fs::write(mb_root.join("artist.jsonl.xz"), EMPTY_XZ).unwrap();

    let config = Arc::new(mb_test_config(&mb_root));
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let shutdown = Arc::new(tokio::sync::Notify::new());

    // Create a fully completed state marker at the expected path
    let mut marker = StateMarker::new("20260322".to_string());
    marker.complete_processing();
    marker.complete_extraction();
    let marker_path = mb_root.join(".mb_extraction_status_20260322.json");
    marker.save(&marker_path).await.unwrap();

    let mock_mq = MockMessagePublisher::new();
    let factory = Arc::new(MockMqFactory { publisher: Arc::new(mock_mq) });

    let result = process_musicbrainz_data(config, state.clone(), shutdown, false, factory, None).await;

    assert!(result.is_ok());
    assert!(result.unwrap()); // Returns true — skipped

    let s = state.read().await;
    assert_eq!(s.extraction_status, ExtractionStatus::Completed);
}

/// A valid xz-compressed empty file (32 bytes) for testing.
/// Created from: `echo -n '' | xz`
const EMPTY_XZ: &[u8] = &[
    0xfd, 0x37, 0x7a, 0x58, 0x5a, 0x00, 0x00, 0x04, 0xe6, 0xd6, 0xb4, 0x46, 0x00, 0x00, 0x00, 0x00, 0x1c, 0xdf, 0x44, 0x21, 0x1f, 0xb6, 0xf3, 0x7d,
    0x01, 0x00, 0x00, 0x00, 0x00, 0x04, 0x59, 0x5a,
];

#[tokio::test]
async fn test_process_musicbrainz_data_force_reprocess_bypasses_skip() {
    // Create a temp dir with a valid empty xz dump file
    let temp_dir = TempDir::new().unwrap();
    let mb_root = temp_dir.path().join("20260322");
    std::fs::create_dir_all(&mb_root).unwrap();
    std::fs::write(mb_root.join("artist.jsonl.xz"), EMPTY_XZ).unwrap();

    let config = Arc::new(mb_test_config(&mb_root));
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let shutdown = Arc::new(tokio::sync::Notify::new());

    // Create a fully completed state marker
    let mut marker = StateMarker::new("20260322".to_string());
    marker.complete_processing();
    marker.complete_extraction();
    let marker_path = mb_root.join(".mb_extraction_status_20260322.json");
    marker.save(&marker_path).await.unwrap();

    // With force_reprocess=true, it should NOT skip — it proceeds to MQ creation
    let mut mock_mq = MockMessagePublisher::new();
    mock_mq.expect_setup_exchange().returning(|_| Ok(()));
    mock_mq.expect_publish_batch().returning(|_, _| Ok(()));
    mock_mq.expect_send_file_complete().returning(|_, _, _| Ok(()));
    mock_mq.expect_send_extraction_complete().returning(|_, _, _| Ok(()));
    mock_mq.expect_close().returning(|| Ok(()));

    let factory = Arc::new(MockMqFactory { publisher: Arc::new(mock_mq) });

    let result = process_musicbrainz_data(config, state.clone(), shutdown, true, factory, None).await;

    // force_reprocess bypasses skip — it should succeed with 0 records (empty file)
    assert!(result.is_ok());
    assert!(result.unwrap());

    let s = state.read().await;
    assert_eq!(s.extraction_status, ExtractionStatus::Completed);
}

#[tokio::test]
async fn test_process_musicbrainz_data_mq_connection_failure() {
    // Create a temp dir with a dump file so it gets past discovery
    let temp_dir = TempDir::new().unwrap();
    let mb_root = temp_dir.path().join("20260322");
    std::fs::create_dir_all(&mb_root).unwrap();
    std::fs::write(mb_root.join("artist.jsonl.xz"), EMPTY_XZ).unwrap();

    let config = Arc::new(mb_test_config(&mb_root));
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let shutdown = Arc::new(tokio::sync::Notify::new());

    // Factory that fails to create MQ connection
    use extractor::extractor::MessageQueueFactory;
    struct FailingMqFactory;
    #[async_trait::async_trait]
    impl MessageQueueFactory for FailingMqFactory {
        async fn create(&self, _url: &str, _exchange_prefix: &str) -> anyhow::Result<Arc<dyn extractor::message_queue::MessagePublisher>> {
            Err(anyhow::anyhow!("AMQP connection refused"))
        }
    }
    let factory = Arc::new(FailingMqFactory);

    let result = process_musicbrainz_data(config, state, shutdown, false, factory, None).await;

    // Should return an error because MQ connection failed
    assert!(result.is_err());
    let err_msg = format!("{}", result.err().unwrap());
    assert!(err_msg.contains("message queue"), "Expected MQ error, got: {}", err_msg);
}

#[tokio::test]
async fn test_process_musicbrainz_data_nonexistent_dir() {
    // Point at a directory that doesn't exist — discover_mb_dump_files returns empty
    let config = Arc::new(mb_test_config(std::path::Path::new("/tmp/nonexistent-mb-dir-12345")));
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let shutdown = Arc::new(tokio::sync::Notify::new());

    let mock_mq = MockMessagePublisher::new();
    let factory = Arc::new(MockMqFactory { publisher: Arc::new(mock_mq) });

    let result = process_musicbrainz_data(config, state.clone(), shutdown, false, factory, None).await;

    assert!(result.is_ok());
    assert!(result.unwrap()); // Returns true — no dump files
}

#[tokio::test]
async fn test_process_musicbrainz_data_reprocess_decision() {
    // Create a temp dir with a valid empty xz dump file
    let temp_dir = TempDir::new().unwrap();
    let mb_root = temp_dir.path().join("20260322");
    std::fs::create_dir_all(&mb_root).unwrap();
    std::fs::write(mb_root.join("artist.jsonl.xz"), EMPTY_XZ).unwrap();

    let config = Arc::new(mb_test_config(&mb_root));
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let shutdown = Arc::new(tokio::sync::Notify::new());

    // Create a state marker with a failed download phase — triggers Reprocess
    let mut marker = StateMarker::new("20260322".to_string());
    marker.download_phase.status = extractor::state_marker::PhaseStatus::Failed;
    let marker_path = mb_root.join(".mb_extraction_status_20260322.json");
    marker.save(&marker_path).await.unwrap();

    let mut mock_mq = MockMessagePublisher::new();
    mock_mq.expect_setup_exchange().returning(|_| Ok(()));
    mock_mq.expect_publish_batch().returning(|_, _| Ok(()));
    mock_mq.expect_send_file_complete().returning(|_, _, _| Ok(()));
    mock_mq.expect_send_extraction_complete().returning(|_, _, _| Ok(()));
    mock_mq.expect_close().returning(|| Ok(()));

    let factory = Arc::new(MockMqFactory { publisher: Arc::new(mock_mq) });

    let result = process_musicbrainz_data(config, state.clone(), shutdown, false, factory, None).await;

    // Should succeed — Reprocess creates a new marker and proceeds
    assert!(result.is_ok());
    assert!(result.unwrap());

    let s = state.read().await;
    assert_eq!(s.extraction_status, ExtractionStatus::Completed);
}

#[tokio::test]
async fn test_process_musicbrainz_data_skips_completed_files() {
    // Create a temp dir with two dump files
    let temp_dir = TempDir::new().unwrap();
    let mb_root = temp_dir.path().join("20260322");
    std::fs::create_dir_all(&mb_root).unwrap();

    // Write valid xz files for artist and label
    std::fs::write(mb_root.join("artist.jsonl.xz"), EMPTY_XZ).unwrap();
    std::fs::write(mb_root.join("label.jsonl.xz"), EMPTY_XZ).unwrap();

    let config = Arc::new(mb_test_config(&mb_root));
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let shutdown = Arc::new(tokio::sync::Notify::new());

    // Create a state marker where artist is already completed but label is not
    let mut marker = StateMarker::new("20260322".to_string());
    marker.start_processing(2);
    marker.start_file_processing("artist.jsonl.xz");
    marker.complete_file_processing("artist.jsonl.xz", 1000);
    let marker_path = mb_root.join(".mb_extraction_status_20260322.json");
    marker.save(&marker_path).await.unwrap();

    let mut mock_mq = MockMessagePublisher::new();
    mock_mq.expect_setup_exchange().returning(|_| Ok(()));
    mock_mq.expect_publish_batch().returning(|_, _| Ok(()));
    // send_file_complete should only be called for label (artist is skipped)
    mock_mq.expect_send_file_complete().returning(|_, _, _| Ok(()));
    mock_mq.expect_send_extraction_complete().returning(|_, _, _| Ok(()));
    mock_mq.expect_close().returning(|| Ok(()));

    let factory = Arc::new(MockMqFactory { publisher: Arc::new(mock_mq) });

    let result = process_musicbrainz_data(config, state.clone(), shutdown, false, factory, None).await;

    assert!(result.is_ok());
    assert!(result.unwrap());
}

#[tokio::test]
async fn test_process_musicbrainz_data_only_labels_no_artist_dump() {
    // Only label dump file exists — no artist dump means empty HashMap for MBID map
    let temp_dir = TempDir::new().unwrap();
    let mb_root = temp_dir.path().join("20260322");
    std::fs::create_dir_all(&mb_root).unwrap();
    std::fs::write(mb_root.join("label.jsonl.xz"), EMPTY_XZ).unwrap();

    let config = Arc::new(mb_test_config(&mb_root));
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let shutdown = Arc::new(tokio::sync::Notify::new());

    let mut mock_mq = MockMessagePublisher::new();
    mock_mq.expect_setup_exchange().returning(|_| Ok(()));
    mock_mq.expect_publish_batch().returning(|_, _| Ok(()));
    mock_mq.expect_send_file_complete().returning(|_, _, _| Ok(()));
    mock_mq.expect_send_extraction_complete().returning(|_, _, _| Ok(()));
    mock_mq.expect_close().returning(|| Ok(()));

    let factory = Arc::new(MockMqFactory { publisher: Arc::new(mock_mq) });

    let result = process_musicbrainz_data(config, state.clone(), shutdown, false, factory, None).await;

    assert!(result.is_ok());
    assert!(result.unwrap());

    let s = state.read().await;
    assert_eq!(s.extraction_status, ExtractionStatus::Completed);
}
