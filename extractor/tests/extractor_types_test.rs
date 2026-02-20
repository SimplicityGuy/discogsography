//! Tests for DataType and ExtractionProgress

use extractor::types::DataType;
use std::str::FromStr;

#[test]
fn test_data_type_all_variants() {
    let types = [DataType::Artists, DataType::Labels, DataType::Masters, DataType::Releases];

    assert_eq!(types.len(), 4);

    for data_type in types {
        // Verify each variant has a valid string representation
        assert!(!data_type.as_str().is_empty());
        assert!(!data_type.to_string().is_empty());
        assert!(!data_type.routing_key().is_empty());
    }
}

#[test]
fn test_data_type_all_conversions() {
    let conversions = [
        ("artists", DataType::Artists),
        ("labels", DataType::Labels),
        ("masters", DataType::Masters),
        ("releases", DataType::Releases),
    ];

    for (string_val, expected_type) in conversions {
        // Test from_str
        let parsed = DataType::from_str(string_val).unwrap();
        assert_eq!(parsed, expected_type);

        // Test to_string roundtrip
        assert_eq!(parsed.to_string(), string_val);

        // Test as_str roundtrip
        assert_eq!(parsed.as_str(), string_val);

        // Test routing_key matches
        assert_eq!(parsed.routing_key(), string_val);
    }
}

#[test]
fn test_extraction_progress_default() {
    use extractor::types::ExtractionProgress;

    let progress = ExtractionProgress::default();

    assert_eq!(progress.artists, 0);
    assert_eq!(progress.labels, 0);
    assert_eq!(progress.masters, 0);
    assert_eq!(progress.releases, 0);
    assert_eq!(progress.total(), 0);
}

#[test]
fn test_extraction_progress_increment_all_types() {
    use extractor::types::ExtractionProgress;

    let mut progress = ExtractionProgress { artists: 100, labels: 200, masters: 300, releases: 400 };

    assert_eq!(progress.total(), 1000);

    // Increment
    progress.artists += 50;
    progress.labels += 100;
    progress.masters += 150;
    progress.releases += 200;

    assert_eq!(progress.total(), 1500);
}

#[test]
fn test_data_type_from_str_invalid() {
    let result = DataType::from_str("invalid_type");
    assert!(result.is_err());

    let result = DataType::from_str("");
    assert!(result.is_err());

    // Note: Case doesn't matter due to to_lowercase() in implementation
    let result = DataType::from_str("not_a_real_type");
    assert!(result.is_err());
}

#[test]
fn test_data_type_display_formatting() {
    assert_eq!(format!("{}", DataType::Artists), "artists");
    assert_eq!(format!("{}", DataType::Labels), "labels");
    assert_eq!(format!("{}", DataType::Masters), "masters");
    assert_eq!(format!("{}", DataType::Releases), "releases");
}

#[test]
fn test_data_type_case_insensitive_parsing() {
    // Verify from_str is case-insensitive
    assert_eq!(DataType::from_str("ARTISTS").unwrap(), DataType::Artists);
    assert_eq!(DataType::from_str("Artists").unwrap(), DataType::Artists);
    assert_eq!(DataType::from_str("aRtIsTs").unwrap(), DataType::Artists);

    assert_eq!(DataType::from_str("LABELS").unwrap(), DataType::Labels);
    assert_eq!(DataType::from_str("MASTERS").unwrap(), DataType::Masters);
    assert_eq!(DataType::from_str("RELEASES").unwrap(), DataType::Releases);
}

#[test]
fn test_extraction_progress_large_numbers() {
    use extractor::types::ExtractionProgress;

    let progress = ExtractionProgress { artists: 1_000_000, labels: 500_000, masters: 750_000, releases: 2_000_000 };

    assert_eq!(progress.total(), 4_250_000);
}
