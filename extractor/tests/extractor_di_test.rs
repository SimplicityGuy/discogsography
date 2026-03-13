use std::sync::Arc;
use tokio::sync::{Mutex, RwLock};
use tempfile::TempDir;
use extractor::extractor::{process_single_file, message_publisher, ExtractorState};
use extractor::config::ExtractorConfig;
use extractor::state_marker::StateMarker;
use extractor::message_queue::MockMessagePublisher;
use extractor::downloader::MockDataSource;
use extractor::types::S3FileInfo;
use extractor::types::{DataType, DataMessage};

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
    mock_mq.expect_setup_exchange()
        .withf(|dt| *dt == DataType::Artists)
        .times(1)
        .returning(|_| Ok(()));
    mock_mq.expect_close().times(..).returning(|| Ok(()));
    mock_mq.expect_publish_batch().returning(|_, _| Ok(()));
    mock_mq.expect_send_file_complete().returning(|_, _, _| Ok(()));

    let mq: Arc<dyn extractor::message_queue::MessagePublisher> = Arc::new(mock_mq);

    let result = process_single_file(
        "discogs_20260101_artists.xml.gz",
        config, state, state_marker, marker_path, mq,
    ).await;

    // Error expected — file doesn't exist on disk
    assert!(result.is_err());
}

#[tokio::test]
async fn test_message_publisher_increments_error_count_on_failure() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    let mut mock_mq = MockMessagePublisher::new();
    mock_mq.expect_publish_batch()
        .times(1)
        .returning(|_, _| Err(anyhow::anyhow!("AMQP connection lost")));

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
    mock_mq.expect_publish_batch()
        .times(3)
        .returning(|_, _| Ok(()));

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
    mock_dl.expect_list_s3_files()
        .times(1)
        .returning(|| Ok(vec![]));
    mock_dl.expect_get_latest_monthly_files()
        .times(1)
        .returning(|_| Ok(vec![]));

    let mock_mq = MockMessagePublisher::new();
    let factory = Arc::new(MockMqFactory { publisher: Arc::new(mock_mq) });

    let result = extractor::extractor::process_discogs_data(
        config, state, shutdown, false,
        &mut mock_dl, factory,
    ).await;

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
    mock_dl.expect_list_s3_files()
        .returning(|| Ok(vec![
            S3FileInfo { name: "data/discogs_20260101_artists.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_labels.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_masters.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_releases.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_CHECKSUM.txt".to_string(), size: 100 },
        ]));
    mock_dl.expect_get_latest_monthly_files()
        .returning(|_| Ok(vec![
            S3FileInfo { name: "discogs_20260101_artists.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "discogs_20260101_labels.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "discogs_20260101_masters.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "discogs_20260101_releases.xml.gz".to_string(), size: 1000 },
        ]));

    let mock_mq = MockMessagePublisher::new();
    let factory = Arc::new(MockMqFactory { publisher: Arc::new(mock_mq) });

    let result = extractor::extractor::process_discogs_data(
        config, state, shutdown, false,
        &mut mock_dl, factory,
    ).await;

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
    mock_dl.expect_list_s3_files()
        .returning(|| Ok(vec![
            S3FileInfo { name: "data/discogs_20260101_artists.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_labels.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_masters.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_releases.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_CHECKSUM.txt".to_string(), size: 100 },
        ]));
    mock_dl.expect_get_latest_monthly_files()
        .returning(|_| Ok(vec![
            S3FileInfo { name: "discogs_20260101_artists.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "discogs_20260101_labels.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "discogs_20260101_masters.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "discogs_20260101_releases.xml.gz".to_string(), size: 1000 },
        ]));
    mock_dl.expect_set_state_marker()
        .times(1)
        .returning(|_, _| ());
    mock_dl.expect_download_discogs_data()
        .times(1)
        .returning(|| Ok(vec![
            "discogs_20260101_artists.xml.gz".to_string(),
            "discogs_20260101_labels.xml.gz".to_string(),
            "discogs_20260101_masters.xml.gz".to_string(),
            "discogs_20260101_releases.xml.gz".to_string(),
        ]));
    mock_dl.expect_take_state_marker()
        .times(1)
        .returning(|| Some(StateMarker::new("20260101".to_string())));

    let mut mock_mq = MockMessagePublisher::new();
    mock_mq.expect_setup_exchange().returning(|_| Ok(()));
    mock_mq.expect_publish_batch().returning(|_, _| Ok(()));
    mock_mq.expect_send_file_complete().returning(|_, _, _| Ok(()));
    mock_mq.expect_send_extraction_complete().returning(|_, _, _| Ok(()));
    mock_mq.expect_close().returning(|| Ok(()));

    let factory = Arc::new(MockMqFactory { publisher: Arc::new(mock_mq) });

    let result = extractor::extractor::process_discogs_data(
        config, state, shutdown, true,
        &mut mock_dl, factory,
    ).await;

    // Result may be Ok or Err — key assertion is download_discogs_data was called (verified by mock times(1))
    let _ = result;
}
