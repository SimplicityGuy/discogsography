//! Tests for message batching functionality

use extractor::extractor::{BatcherConfig, ExtractorState, message_batcher};
use extractor::state_marker::StateMarker;
use extractor::types::{DataMessage, DataType};
use serde_json::json;
use std::path::PathBuf;
use std::sync::Arc;
use tempfile::TempDir;
use tokio::sync::{RwLock, mpsc};

#[tokio::test]
async fn test_message_batcher_empty_batch() {
    let (tx, rx) = mpsc::channel(10);
    let (batch_tx, mut batch_rx) = mpsc::channel::<Vec<DataMessage>>(10);

    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let state_marker = Arc::new(tokio::sync::Mutex::new(StateMarker::new("20260101".to_string())));

    let config = BatcherConfig {
        batch_size: 5,
        data_type: DataType::Artists,
        state: state.clone(),
        state_marker: state_marker.clone(),
        marker_path: PathBuf::from("/tmp/test_marker.json"),
        file_name: "test.xml".to_string(),
        state_save_interval: 100,
    };

    // Close sender immediately
    drop(tx);

    // Start batcher
    let batcher_handle = tokio::spawn(async move { message_batcher(rx, batch_tx, config).await });

    // Should receive no batches
    assert!(batch_rx.recv().await.is_none());

    // Batcher should finish without error
    assert!(batcher_handle.await.is_ok());
}

#[tokio::test]
async fn test_message_batcher_single_message() {
    let (tx, rx) = mpsc::channel(10);
    let (batch_tx, mut batch_rx) = mpsc::channel::<Vec<DataMessage>>(10);

    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let state_marker = Arc::new(tokio::sync::Mutex::new(StateMarker::new("20260101".to_string())));

    let config = BatcherConfig {
        batch_size: 5,
        data_type: DataType::Artists,
        state: state.clone(),
        state_marker: state_marker.clone(),
        marker_path: PathBuf::from("/tmp/test_marker.json"),
        file_name: "test.xml".to_string(),
        state_save_interval: 100,
    };

    // Send one message
    let message = DataMessage { id: "1".to_string(), sha256: "hash1".to_string(), data: json!({"name": "Test Artist"}) };
    tx.send(message).await.unwrap();
    drop(tx);

    // Start batcher
    tokio::spawn(async move {
        message_batcher(rx, batch_tx, config).await.ok();
    });

    // Should receive one batch with one message
    if let Some(batch) = batch_rx.recv().await {
        assert_eq!(batch.len(), 1);
        assert_eq!(batch[0].id, "1");
    }
}

#[tokio::test]
async fn test_message_batcher_multiple_batches() {
    let (tx, rx) = mpsc::channel(20);
    let (batch_tx, mut batch_rx) = mpsc::channel::<Vec<DataMessage>>(10);

    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let state_marker = Arc::new(tokio::sync::Mutex::new(StateMarker::new("20260101".to_string())));

    let config = BatcherConfig {
        batch_size: 3,
        data_type: DataType::Artists,
        state: state.clone(),
        state_marker: state_marker.clone(),
        marker_path: PathBuf::from("/tmp/test_marker.json"),
        file_name: "test.xml".to_string(),
        state_save_interval: 100,
    };

    // Send 7 messages (should create 2 full batches + 1 partial)
    for i in 1..=7 {
        let message = DataMessage { id: i.to_string(), sha256: format!("hash{}", i), data: json!({"name": format!("Artist {}", i)}) };
        tx.send(message).await.unwrap();
    }
    drop(tx);

    // Start batcher
    tokio::spawn(async move {
        message_batcher(rx, batch_tx, config).await.ok();
    });

    // Collect batches
    let mut total_messages = 0;
    while let Some(batch) = batch_rx.recv().await {
        total_messages += batch.len();
    }

    assert_eq!(total_messages, 7);
}

#[tokio::test]
async fn test_message_batcher_saves_final_state_marker() {
    let temp_dir = TempDir::new().unwrap();
    let marker_path = temp_dir.path().join("test_final_marker.json");

    let (tx, rx) = mpsc::channel(20);
    let (batch_tx, mut batch_rx) = mpsc::channel::<Vec<DataMessage>>(10);

    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let mut marker = StateMarker::new("20260101".to_string());
    marker.start_file_processing("discogs_20260101_artists.xml.gz");
    let state_marker = Arc::new(tokio::sync::Mutex::new(marker));

    let config = BatcherConfig {
        batch_size: 3,
        data_type: DataType::Artists,
        state: state.clone(),
        state_marker: state_marker.clone(),
        marker_path: marker_path.clone(),
        file_name: "discogs_20260101_artists.xml.gz".to_string(),
        state_save_interval: 10000, // High interval so periodic save won't trigger
    };

    // Send 5 messages
    for i in 1..=5 {
        let message = DataMessage { id: i.to_string(), sha256: format!("hash{}", i), data: json!({"name": format!("Artist {}", i)}) };
        tx.send(message).await.unwrap();
    }
    drop(tx);

    // Start batcher
    let batcher_handle = tokio::spawn(async move { message_batcher(rx, batch_tx, config).await });

    // Drain batches so batcher can complete
    while batch_rx.recv().await.is_some() {}

    // Wait for batcher to finish
    batcher_handle.await.unwrap().unwrap();

    // Verify the final state marker was saved to disk
    assert!(marker_path.exists(), "State marker file should exist after batcher completes");

    // Load and verify the state marker contents
    let loaded = StateMarker::load(&marker_path).await.unwrap();
    assert!(loaded.is_some(), "Should be able to load the saved state marker");
    let loaded = loaded.unwrap();

    let file_progress = loaded
        .processing_phase
        .progress_by_file
        .get("discogs_20260101_artists.xml.gz");
    assert!(file_progress.is_some(), "State marker should have progress for the file");
    let progress = file_progress.unwrap();
    assert_eq!(progress.records_extracted, 5, "Should track all 5 records");
    assert_eq!(progress.messages_published, 5, "messages_published should match records");
}

#[tokio::test]
async fn test_message_batcher_final_batch_increments_total_batches() {
    // Verifies that when the channel closes with a partial batch,
    // total_batches is incremented (line 407) and reflected in the state marker.
    let temp_dir = TempDir::new().unwrap();
    let marker_path = temp_dir.path().join("test_batch_count.json");

    let (tx, rx) = mpsc::channel(20);
    let (batch_tx, mut batch_rx) = mpsc::channel::<Vec<DataMessage>>(10);

    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let mut marker = StateMarker::new("20260101".to_string());
    marker.start_file_processing("discogs_20260101_artists.xml.gz");
    let state_marker = Arc::new(tokio::sync::Mutex::new(marker));

    let config = BatcherConfig {
        batch_size: 10, // Batch size larger than message count so final batch is partial
        data_type: DataType::Artists,
        state: state.clone(),
        state_marker: state_marker.clone(),
        marker_path: marker_path.clone(),
        file_name: "discogs_20260101_artists.xml.gz".to_string(),
        state_save_interval: 10000,
    };

    // Send 3 messages (less than batch_size=10, so only a final partial batch)
    for i in 1..=3 {
        let message = DataMessage { id: i.to_string(), sha256: format!("hash{}", i), data: json!({"name": format!("Artist {}", i)}) };
        tx.send(message).await.unwrap();
    }
    drop(tx);

    let batcher_handle = tokio::spawn(async move { message_batcher(rx, batch_tx, config).await });

    // Drain batches
    let mut batch_count = 0;
    while let Some(_batch) = batch_rx.recv().await {
        batch_count += 1;
    }

    batcher_handle.await.unwrap().unwrap();

    assert_eq!(batch_count, 1, "Should have exactly 1 partial batch");

    // Verify the state marker records the correct batch count
    let loaded = StateMarker::load(&marker_path).await.unwrap().unwrap();
    let progress = loaded
        .processing_phase
        .progress_by_file
        .get("discogs_20260101_artists.xml.gz")
        .unwrap();
    assert_eq!(progress.batches_sent, 1, "State marker should reflect 1 batch from final flush");
}

#[tokio::test]
async fn test_message_batcher_saves_marker_on_read_only_path_warns() {
    // Verifies that a failed final state marker save (line 427-428) doesn't
    // cause the batcher to error — it just warns.
    let (tx, rx) = mpsc::channel(10);
    let (batch_tx, mut batch_rx) = mpsc::channel::<Vec<DataMessage>>(10);

    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let state_marker = Arc::new(tokio::sync::Mutex::new(StateMarker::new("20260101".to_string())));

    // Use a path that will fail to write (nonexistent parent directory)
    let config = BatcherConfig {
        batch_size: 5,
        data_type: DataType::Artists,
        state: state.clone(),
        state_marker: state_marker.clone(),
        marker_path: PathBuf::from("/nonexistent/dir/marker.json"),
        file_name: "test.xml".to_string(),
        state_save_interval: 10000,
    };

    // Send one message so the batcher has work to do
    let message = DataMessage { id: "1".to_string(), sha256: "hash1".to_string(), data: json!({"name": "Test"}) };
    tx.send(message).await.unwrap();
    drop(tx);

    let batcher_handle = tokio::spawn(async move { message_batcher(rx, batch_tx, config).await });

    // Drain batches
    while batch_rx.recv().await.is_some() {}

    // Batcher should succeed even though state marker save fails
    let result = batcher_handle.await.unwrap();
    assert!(result.is_ok(), "Batcher should not error on failed state marker save");
}

#[tokio::test]
async fn test_message_batcher_periodic_state_save() {
    // Verifies periodic state marker save at state_save_interval (lines 384-392)
    let temp_dir = TempDir::new().unwrap();
    let marker_path = temp_dir.path().join("periodic_save.json");

    let (tx, rx) = mpsc::channel(50);
    let (batch_tx, mut batch_rx) = mpsc::channel::<Vec<DataMessage>>(50);

    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let mut marker = StateMarker::new("20260101".to_string());
    marker.start_file_processing("test.xml.gz");
    let state_marker = Arc::new(tokio::sync::Mutex::new(marker));

    let config = BatcherConfig {
        batch_size: 5,
        data_type: DataType::Artists,
        state: state.clone(),
        state_marker: state_marker.clone(),
        marker_path: marker_path.clone(),
        file_name: "test.xml.gz".to_string(),
        state_save_interval: 10, // Save every 10 records
    };

    // Send 15 messages — should trigger periodic save at record 10
    for i in 1..=15 {
        let message = DataMessage { id: i.to_string(), sha256: format!("hash{}", i), data: json!({"name": format!("Artist {}", i)}) };
        tx.send(message).await.unwrap();
    }
    drop(tx);

    let batcher_handle = tokio::spawn(async move { message_batcher(rx, batch_tx, config).await });
    while batch_rx.recv().await.is_some() {}
    batcher_handle.await.unwrap().unwrap();

    // Final state marker should exist with all 15 records
    let loaded = StateMarker::load(&marker_path).await.unwrap().unwrap();
    let progress = loaded.processing_phase.progress_by_file.get("test.xml.gz").unwrap();
    assert_eq!(progress.records_extracted, 15);
}
