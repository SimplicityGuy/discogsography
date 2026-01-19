// Advanced tests for extractor module

use rust_extractor::types::{DataType, ExtractionProgress};
use std::str::FromStr;

#[test]
fn test_extraction_progress_increment() {
    let mut progress = ExtractionProgress::default();

    assert_eq!(progress.total(), 0);

    progress.increment(DataType::Artists);
    progress.increment(DataType::Artists);
    progress.increment(DataType::Labels);

    assert_eq!(progress.artists, 2);
    assert_eq!(progress.labels, 1);
    assert_eq!(progress.total(), 3);
}

#[test]
fn test_extraction_progress_all_types() {
    let mut progress = ExtractionProgress::default();

    progress.increment(DataType::Artists);
    progress.increment(DataType::Labels);
    progress.increment(DataType::Masters);
    progress.increment(DataType::Releases);

    assert_eq!(progress.artists, 1);
    assert_eq!(progress.labels, 1);
    assert_eq!(progress.masters, 1);
    assert_eq!(progress.releases, 1);
    assert_eq!(progress.total(), 4);
}

#[test]
fn test_data_type_conversion() {
    let artists = DataType::from_str("artists").unwrap();
    assert_eq!(artists, DataType::Artists);
    assert_eq!(artists.as_str(), "artists");
    assert_eq!(artists.routing_key(), "artists");
}

#[test]
fn test_data_type_display() {
    assert_eq!(format!("{}", DataType::Artists), "artists");
    assert_eq!(format!("{}", DataType::Labels), "labels");
    assert_eq!(format!("{}", DataType::Masters), "masters");
    assert_eq!(format!("{}", DataType::Releases), "releases");
}

#[test]
fn test_extraction_progress_large_numbers() {
    let mut progress = ExtractionProgress::default();

    // Increment many times
    for _ in 0..1000 {
        progress.increment(DataType::Artists);
    }
    for _ in 0..500 {
        progress.increment(DataType::Labels);
    }

    assert_eq!(progress.artists, 1000);
    assert_eq!(progress.labels, 500);
    assert_eq!(progress.total(), 1500);
}

#[test]
fn test_data_type_all_variants_unique() {
    let types = vec![
        DataType::Artists,
        DataType::Labels,
        DataType::Masters,
        DataType::Releases,
    ];

    // All routing keys should be different
    let keys: Vec<_> = types.iter().map(|t| t.routing_key()).collect();
    assert_eq!(keys.len(), 4);

    // Check all are unique
    for i in 0..keys.len() {
        for j in (i + 1)..keys.len() {
            assert_ne!(keys[i], keys[j]);
        }
    }
}
