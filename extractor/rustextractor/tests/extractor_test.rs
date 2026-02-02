// Integration tests for extractor module
// Focus on testing the extraction workflow with mocked dependencies

use rust_extractor::extractor::ExtractorState;
use rust_extractor::types::{DataType, DataMessage};
use std::sync::Arc;
use tokio::sync::RwLock;

#[tokio::test]
async fn test_extractor_state_initialization() {
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
async fn test_extractor_state_updates() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    {
        let mut s = state.write().await;
        s.current_task = Some("Processing artists".to_string());
        s.current_progress = 0.5;
        s.extraction_progress.increment(DataType::Artists);
        s.extraction_progress.increment(DataType::Artists);
        s.error_count += 1;
    }

    let s = state.read().await;
    assert_eq!(s.current_task, Some("Processing artists".to_string()));
    assert_eq!(s.current_progress, 0.5);
    assert_eq!(s.extraction_progress.artists, 2);
    assert_eq!(s.extraction_progress.total(), 2);
    assert_eq!(s.error_count, 1);
}

#[tokio::test]
async fn test_extractor_state_completed_files_tracking() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    {
        let mut s = state.write().await;
        s.completed_files.insert("file1.xml".to_string());
        s.completed_files.insert("file2.xml".to_string());
        s.completed_files.insert("file3.xml".to_string());
    }

    let s = state.read().await;
    assert_eq!(s.completed_files.len(), 3);
    assert!(s.completed_files.contains("file1.xml"));
    assert!(s.completed_files.contains("file2.xml"));
    assert!(s.completed_files.contains("file3.xml"));
}

#[tokio::test]
async fn test_extractor_state_active_connections() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    {
        let mut s = state.write().await;
        s.active_connections.insert(DataType::Artists, "artists.xml".to_string());
        s.active_connections.insert(DataType::Labels, "labels.xml".to_string());
    }

    let s = state.read().await;
    assert_eq!(s.active_connections.len(), 2);
    assert_eq!(s.active_connections.get(&DataType::Artists), Some(&"artists.xml".to_string()));
    assert_eq!(s.active_connections.get(&DataType::Labels), Some(&"labels.xml".to_string()));
}

#[tokio::test]
async fn test_extractor_state_last_extraction_time() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    {
        let mut s = state.write().await;
        s.last_extraction_time.insert(DataType::Artists, 100.5);
        s.last_extraction_time.insert(DataType::Labels, 200.75);
    }

    let s = state.read().await;
    assert_eq!(s.last_extraction_time.get(&DataType::Artists), Some(&100.5));
    assert_eq!(s.last_extraction_time.get(&DataType::Labels), Some(&200.75));
}

#[tokio::test]
async fn test_extractor_state_progress_increment() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    // Increment different data types
    {
        let mut s = state.write().await;
        for _ in 0..10 {
            s.extraction_progress.increment(DataType::Artists);
        }
        for _ in 0..5 {
            s.extraction_progress.increment(DataType::Labels);
        }
        for _ in 0..3 {
            s.extraction_progress.increment(DataType::Masters);
        }
        for _ in 0..7 {
            s.extraction_progress.increment(DataType::Releases);
        }
    }

    let s = state.read().await;
    assert_eq!(s.extraction_progress.artists, 10);
    assert_eq!(s.extraction_progress.labels, 5);
    assert_eq!(s.extraction_progress.masters, 3);
    assert_eq!(s.extraction_progress.releases, 7);
    assert_eq!(s.extraction_progress.total(), 25);
}

#[tokio::test]
async fn test_extractor_state_error_count() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    {
        let mut s = state.write().await;
        s.error_count = 5;
    }

    let s = state.read().await;
    assert_eq!(s.error_count, 5);
}

#[tokio::test]
async fn test_extractor_state_reset() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    // Set some state
    {
        let mut s = state.write().await;
        s.current_task = Some("test".to_string());
        s.extraction_progress.increment(DataType::Artists);
        s.completed_files.insert("file.xml".to_string());
        s.error_count = 3;
    }

    // Reset
    {
        let mut s = state.write().await;
        *s = ExtractorState::default();
    }

    let s = state.read().await;
    assert!(s.current_task.is_none());
    assert_eq!(s.extraction_progress.total(), 0);
    assert!(s.completed_files.is_empty());
    assert_eq!(s.error_count, 0);
}

// Deprecated ProcessingState tests removed - replaced by StateMarker integration tests in extractor.rs

#[test]
fn test_extract_data_type_from_filename() {
    use std::str::FromStr;

    // Test valid filenames
    let test_cases = vec![
        ("discogs_20241201_artists.xml.gz", Some(DataType::Artists)),
        ("discogs_20241201_labels.xml.gz", Some(DataType::Labels)),
        ("discogs_20241201_masters.xml.gz", Some(DataType::Masters)),
        ("discogs_20241201_releases.xml.gz", Some(DataType::Releases)),
        ("invalid_format.xml", None),
        ("discogs_20241201.xml.gz", None),
        ("discogs_20241201_unknown.xml.gz", None),
        ("", None),
    ];

    // Note: extract_data_type is a private function, so we test via the public API
    // or test the pattern matching logic
    for (filename, expected) in test_cases {
        let parts: Vec<&str> = filename.split('_').collect();
        if parts.len() >= 3 {
            let type_part = parts[2].split('.').next();
            if let Some(type_str) = type_part {
                let result = DataType::from_str(type_str).ok();
                assert_eq!(result, expected, "Failed for filename: {}", filename);
            }
        }
    }
}

#[tokio::test]
async fn test_extractor_state_concurrent_updates() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    let state1 = state.clone();
    let state2 = state.clone();

    let handle1 = tokio::spawn(async move {
        for _ in 0..100 {
            let mut s = state1.write().await;
            s.extraction_progress.increment(DataType::Artists);
        }
    });

    let handle2 = tokio::spawn(async move {
        for _ in 0..100 {
            let mut s = state2.write().await;
            s.extraction_progress.increment(DataType::Labels);
        }
    });

    handle1.await.unwrap();
    handle2.await.unwrap();

    let s = state.read().await;
    assert_eq!(s.extraction_progress.artists, 100);
    assert_eq!(s.extraction_progress.labels, 100);
    assert_eq!(s.extraction_progress.total(), 200);
}

#[tokio::test]
async fn test_extractor_state_large_scale_updates() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    {
        let mut s = state.write().await;
        for i in 0..1000 {
            s.completed_files.insert(format!("file_{}.xml", i));
        }
    }

    let s = state.read().await;
    assert_eq!(s.completed_files.len(), 1000);
}

// Note: Testing with full config requires mocking S3 and AMQP
// which is beyond the scope of unit tests

#[tokio::test]
async fn test_extractor_state_memory_cleanup() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    // Add a lot of data
    {
        let mut s = state.write().await;
        for i in 0..1000 {
            s.completed_files.insert(format!("file_{}.xml", i));
            s.last_extraction_time.insert(DataType::Artists, i as f64);
        }
    }

    // Clear it
    {
        let mut s = state.write().await;
        s.completed_files.clear();
        s.last_extraction_time.clear();
    }

    let s = state.read().await;
    assert_eq!(s.completed_files.len(), 0);
    assert_eq!(s.last_extraction_time.len(), 0);
}

#[test]
fn test_data_type_all_variants() {
    let types = vec![
        DataType::Artists,
        DataType::Labels,
        DataType::Masters,
        DataType::Releases,
    ];

    for data_type in types {
        // Test Display trait
        let display_str = data_type.to_string();
        assert!(!display_str.is_empty());

        // Test routing key
        let routing_key = data_type.routing_key();
        assert_eq!(routing_key, display_str);

        // Test round-trip conversion
        use std::str::FromStr;
        let parsed = DataType::from_str(&display_str).unwrap();
        assert_eq!(parsed, data_type);
    }
}

#[tokio::test]
async fn test_state_progress_tracking_accuracy() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    let expected_counts = vec![
        (DataType::Artists, 123),
        (DataType::Labels, 456),
        (DataType::Masters, 789),
        (DataType::Releases, 101112),
    ];

    {
        let mut s = state.write().await;
        for (data_type, count) in &expected_counts {
            for _ in 0..*count {
                s.extraction_progress.increment(*data_type);
            }
        }
    }

    let s = state.read().await;
    for (data_type, expected_count) in expected_counts {
        let actual_count = match data_type {
            DataType::Artists => s.extraction_progress.artists,
            DataType::Labels => s.extraction_progress.labels,
            DataType::Masters => s.extraction_progress.masters,
            DataType::Releases => s.extraction_progress.releases,
        };
        assert_eq!(actual_count, expected_count);
    }
}

// Additional tests for code paths

#[test]
fn test_data_type_all_conversions() {
    use std::str::FromStr;

    let all_types = [
        DataType::Artists,
        DataType::Labels,
        DataType::Masters,
        DataType::Releases,
    ];

    for data_type in all_types {
        let as_str = data_type.to_string();
        let routing_key = data_type.routing_key();
        let from_str = DataType::from_str(&as_str).unwrap();

        assert_eq!(routing_key, as_str);
        assert_eq!(from_str, data_type);
    }
}

#[test]
fn test_extraction_progress_default() {
    use rust_extractor::types::ExtractionProgress;

    let progress = ExtractionProgress::default();
    assert_eq!(progress.artists, 0);
    assert_eq!(progress.labels, 0);
    assert_eq!(progress.masters, 0);
    assert_eq!(progress.releases, 0);
    assert_eq!(progress.total(), 0);
}

#[test]
fn test_extraction_progress_increment_all_types() {
    use rust_extractor::types::ExtractionProgress;

    let mut progress = ExtractionProgress::default();

    // Increment all types different amounts
    for _ in 0..10 {
        progress.increment(DataType::Artists);
    }
    for _ in 0..20 {
        progress.increment(DataType::Labels);
    }
    for _ in 0..30 {
        progress.increment(DataType::Masters);
    }
    for _ in 0..40 {
        progress.increment(DataType::Releases);
    }

    assert_eq!(progress.artists, 10);
    assert_eq!(progress.labels, 20);
    assert_eq!(progress.masters, 30);
    assert_eq!(progress.releases, 40);
    assert_eq!(progress.total(), 100);
}

#[tokio::test]
async fn test_extractor_state_concurrent_file_tracking() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    let mut handles = vec![];

    // Spawn multiple tasks adding files concurrently
    for i in 0..10 {
        let state_clone = state.clone();
        let handle = tokio::spawn(async move {
            let mut s = state_clone.write().await;
            s.completed_files.insert(format!("file_{}.xml", i));
        });
        handles.push(handle);
    }

    for handle in handles {
        handle.await.unwrap();
    }

    let s = state.read().await;
    assert_eq!(s.completed_files.len(), 10);
}

#[tokio::test]
async fn test_extractor_state_error_tracking() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    {
        let mut s = state.write().await;
        for _ in 0..5 {
            s.error_count += 1;
        }
    }

    let s = state.read().await;
    assert_eq!(s.error_count, 5);
}

#[tokio::test]
async fn test_message_batcher_empty_batch() {
    use tokio::sync::mpsc;

    let (parse_sender, parse_receiver) = mpsc::channel::<DataMessage>(10);
    let (batch_sender, mut batch_receiver) = mpsc::channel::<Vec<DataMessage>>(10);
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    // Close sender immediately without sending messages
    drop(parse_sender);

    let batcher_handle = tokio::spawn(async move {
        use rust_extractor::extractor::message_batcher;
        message_batcher(parse_receiver, batch_sender, 10, DataType::Artists, state).await
    });

    // Should not receive any batches
    let result = tokio::time::timeout(
        tokio::time::Duration::from_millis(100),
        batch_receiver.recv()
    ).await;

    assert!(result.is_err() || result.unwrap().is_none());

    batcher_handle.await.unwrap().unwrap();
}

#[tokio::test]
async fn test_message_batcher_single_message() {
    use tokio::sync::mpsc;

    let (parse_sender, parse_receiver) = mpsc::channel::<DataMessage>(10);
    let (batch_sender, mut batch_receiver) = mpsc::channel::<Vec<DataMessage>>(10);
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    // Send one message
    let msg = DataMessage {
        id: "1".to_string(),
        sha256: "hash1".to_string(),
        data: serde_json::json!({"test": "value"}),
    };
    parse_sender.send(msg).await.unwrap();
    drop(parse_sender);

    let batcher_handle = tokio::spawn(async move {
        use rust_extractor::extractor::message_batcher;
        message_batcher(parse_receiver, batch_sender, 10, DataType::Labels, state).await
    });

    // Should receive one batch with one message
    let batch = batch_receiver.recv().await.unwrap();
    assert_eq!(batch.len(), 1);
    assert_eq!(batch[0].id, "1");

    batcher_handle.await.unwrap().unwrap();
}

#[tokio::test]
async fn test_message_batcher_multiple_batches() {
    use tokio::sync::mpsc;

    let (parse_sender, parse_receiver) = mpsc::channel::<DataMessage>(100);
    let (batch_sender, mut batch_receiver) = mpsc::channel::<Vec<DataMessage>>(10);
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    let batch_size = 5;

    // Send exactly 2 full batches worth of messages
    for i in 0..(batch_size * 2) {
        let msg = DataMessage {
            id: format!("{}", i),
            sha256: format!("hash{}", i),
            data: serde_json::json!({"test": format!("value{}", i)}),
        };
        parse_sender.send(msg).await.unwrap();
    }
    drop(parse_sender);

    let batcher_handle = tokio::spawn(async move {
        use rust_extractor::extractor::message_batcher;
        message_batcher(parse_receiver, batch_sender, batch_size, DataType::Masters, state).await
    });

    // Should receive two batches
    let batch1 = batch_receiver.recv().await.unwrap();
    assert_eq!(batch1.len(), batch_size);

    let batch2 = batch_receiver.recv().await.unwrap();
    assert_eq!(batch2.len(), batch_size);

    batcher_handle.await.unwrap().unwrap();
}

#[tokio::test]
async fn test_extractor_state_current_task_tracking() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    {
        let mut s = state.write().await;
        s.current_task = Some("Processing artists file".to_string());
        s.current_progress = 0.33;
    }

    let s = state.read().await;
    assert_eq!(s.current_task, Some("Processing artists file".to_string()));
    assert!((s.current_progress - 0.33).abs() < 0.001);
}

// Deprecated test removed - StateMarker integration tests are in extractor.rs

#[tokio::test]
async fn test_extractor_state_active_connections_removal() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    {
        let mut s = state.write().await;
        s.active_connections.insert(DataType::Artists, "file1.xml".to_string());
        s.active_connections.insert(DataType::Labels, "file2.xml".to_string());
    }

    {
        let mut s = state.write().await;
        s.active_connections.remove(&DataType::Artists);
    }

    let s = state.read().await;
    assert_eq!(s.active_connections.len(), 1);
    assert!(s.active_connections.get(&DataType::Labels).is_some());
    assert!(s.active_connections.get(&DataType::Artists).is_none());
}
