//! Tests for ExtractorState functionality

use extractor::extractor::ExtractorState;
use extractor::types::DataType;
use std::sync::Arc;
use tokio::sync::RwLock;

#[tokio::test]
async fn test_extractor_state_initialization() {
    let state = ExtractorState::default();

    assert_eq!(state.current_task, None);
    assert_eq!(state.current_progress, 0.0);
    assert_eq!(state.extraction_progress.artists, 0);
    assert_eq!(state.extraction_progress.labels, 0);
    assert_eq!(state.extraction_progress.masters, 0);
    assert_eq!(state.extraction_progress.releases, 0);
    assert_eq!(state.error_count, 0);
    assert!(state.completed_files.is_empty());
    assert!(state.active_connections.is_empty());
    assert!(state.last_extraction_time.is_empty());
}

#[tokio::test]
async fn test_extractor_state_updates() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    {
        let mut s = state.write().await;
        s.current_task = Some("Processing artists".to_string());
        s.current_progress = 0.5;
        s.extraction_progress.artists = 100;
    }

    let s = state.read().await;
    assert_eq!(s.current_task, Some("Processing artists".to_string()));
    assert_eq!(s.current_progress, 0.5);
    assert_eq!(s.extraction_progress.artists, 100);
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
        s.last_extraction_time.insert(DataType::Artists, 1.5);
        s.last_extraction_time.insert(DataType::Labels, 2.3);
    }

    let s = state.read().await;
    assert_eq!(s.last_extraction_time.get(&DataType::Artists), Some(&1.5));
    assert_eq!(s.last_extraction_time.get(&DataType::Labels), Some(&2.3));
}

#[tokio::test]
async fn test_extractor_state_progress_increment() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    {
        let mut s = state.write().await;
        s.extraction_progress.artists = 100;
        s.extraction_progress.labels = 50;
        s.extraction_progress.masters = 75;
        s.extraction_progress.releases = 200;
    }

    let s = state.read().await;
    assert_eq!(s.extraction_progress.total(), 425);
}

#[tokio::test]
async fn test_extractor_state_error_count() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    {
        let mut s = state.write().await;
        s.error_count = 0;
        s.error_count += 1;
        s.error_count += 1;
    }

    let s = state.read().await;
    assert_eq!(s.error_count, 2);
}

#[tokio::test]
async fn test_extractor_state_reset() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    // Populate state
    {
        let mut s = state.write().await;
        s.current_task = Some("Task".to_string());
        s.current_progress = 0.5;
        s.extraction_progress.artists = 100;
        s.error_count = 5;
        s.completed_files.insert("file.xml".to_string());
        s.active_connections.insert(DataType::Artists, "processing.xml".to_string());
        s.last_extraction_time.insert(DataType::Artists, 1.5);
    }

    // Reset by creating new default
    {
        let mut s = state.write().await;
        *s = ExtractorState::default();
    }

    // Verify reset
    let s = state.read().await;
    assert_eq!(s.current_task, None);
    assert_eq!(s.current_progress, 0.0);
    assert_eq!(s.extraction_progress.total(), 0);
    assert_eq!(s.error_count, 0);
    assert!(s.completed_files.is_empty());
    assert!(s.active_connections.is_empty());
    assert!(s.last_extraction_time.is_empty());
}

#[tokio::test]
async fn test_extractor_state_concurrent_updates() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    // Simulate concurrent updates from multiple tasks
    let handles: Vec<_> = (0..10)
        .map(|i| {
            let state_clone = state.clone();
            tokio::spawn(async move {
                let mut s = state_clone.write().await;
                s.extraction_progress.artists += 1;
                s.completed_files.insert(format!("file{}.xml", i));
            })
        })
        .collect();

    // Wait for all tasks
    for handle in handles {
        handle.await.unwrap();
    }

    let s = state.read().await;
    assert_eq!(s.extraction_progress.artists, 10);
    assert_eq!(s.completed_files.len(), 10);
}

#[tokio::test]
async fn test_extractor_state_large_scale_updates() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    {
        let mut s = state.write().await;
        // Simulate processing large datasets
        s.extraction_progress.artists = 1_000_000;
        s.extraction_progress.labels = 500_000;
        s.extraction_progress.masters = 750_000;
        s.extraction_progress.releases = 2_000_000;
    }

    let s = state.read().await;
    assert_eq!(s.extraction_progress.total(), 4_250_000);
}

#[tokio::test]
async fn test_extractor_state_memory_cleanup() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    // Add many files
    {
        let mut s = state.write().await;
        for i in 0..100 {
            s.completed_files.insert(format!("file{}.xml", i));
        }
    }

    // Clear completed files
    {
        let mut s = state.write().await;
        s.completed_files.clear();
    }

    let s = state.read().await;
    assert_eq!(s.completed_files.len(), 0);
}

#[tokio::test]
async fn test_state_progress_tracking_accuracy() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    {
        let mut s = state.write().await;
        s.extraction_progress.artists = 1234;
        s.extraction_progress.labels = 5678;
        s.extraction_progress.masters = 9012;
        s.extraction_progress.releases = 3456;
    }

    let s = state.read().await;
    let expected_total = 1234 + 5678 + 9012 + 3456;
    assert_eq!(s.extraction_progress.total(), expected_total);
}

#[tokio::test]
async fn test_extractor_state_concurrent_file_tracking() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    let files = vec!["artists.xml", "labels.xml", "masters.xml", "releases.xml"];
    let handles: Vec<_> = files
        .into_iter()
        .map(|file| {
            let state_clone = state.clone();
            let file_owned = file.to_string();
            tokio::spawn(async move {
                let mut s = state_clone.write().await;
                s.completed_files.insert(file_owned);
            })
        })
        .collect();

    for handle in handles {
        handle.await.unwrap();
    }

    let s = state.read().await;
    assert_eq!(s.completed_files.len(), 4);
}

#[tokio::test]
async fn test_extractor_state_error_tracking() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    // Simulate errors from concurrent operations
    let handles: Vec<_> = (0..5)
        .map(|_| {
            let state_clone = state.clone();
            tokio::spawn(async move {
                let mut s = state_clone.write().await;
                s.error_count += 1;
            })
        })
        .collect();

    for handle in handles {
        handle.await.unwrap();
    }

    let s = state.read().await;
    assert_eq!(s.error_count, 5);
}
