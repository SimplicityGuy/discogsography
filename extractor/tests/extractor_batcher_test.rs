//! Tests for message batching functionality

use extractor::extractor::{BatcherConfig, ExtractorState, message_batcher};
use extractor::state_marker::StateMarker;
use extractor::types::{DataMessage, DataType};
use serde_json::json;
use std::path::PathBuf;
use std::sync::Arc;
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
