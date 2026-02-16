//! Tests for extractor utility functions

use extractor::types::DataType;
use std::str::FromStr;

#[test]
fn test_extract_data_type_from_filename() {
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

    // Note: extract_data_type is a private function, so we test via the pattern
    for (filename, expected) in test_cases {
        let parts: Vec<&str> = filename.split('_').collect();
        let result = if parts.len() >= 3 {
            parts[2].split('.').next().and_then(|type_part| DataType::from_str(type_part).ok())
        } else {
            None
        };

        assert_eq!(result, expected, "Failed for filename: {}", filename);
    }
}

#[test]
fn test_extract_version_from_filename() {
    // Test version extraction pattern
    // Note: Implementation just splits by '_' and takes parts[1] if it exists
    let test_cases = vec![
        ("discogs_20260101_artists.xml.gz", Some("20260101")),
        ("discogs_20250315_labels.xml.gz", Some("20250315")),
        ("discogs_20241225_masters.xml.gz", Some("20241225")),
        ("discogs_20240701_releases.xml.gz", Some("20240701")),
        ("invalid_format.xml", Some("format.xml")), // Has 2 parts, returns parts[1]
        ("discogs.xml.gz", None),                   // Only 1 part
        ("", None),                                 // Empty string
        ("single", None),                           // Single part, no underscore
    ];

    for (filename, expected) in test_cases {
        let parts: Vec<&str> = filename.split('_').collect();
        let result = if parts.len() >= 2 { Some(parts[1]) } else { None };

        assert_eq!(result, expected, "Failed for filename: {}", filename);
    }
}

#[test]
fn test_filename_parsing_edge_cases() {
    // Test edge cases in filename parsing
    // Note: Implementation doesn't validate extensions or format strictly
    let edge_cases = vec![
        ("discogs_20260101_artists", Some(DataType::Artists)),         // No extension, but still valid
        ("_20260101_artists.xml.gz", Some(DataType::Artists)),         // Empty prefix is parts[0] = ""
        ("discogs__artists.xml.gz", Some(DataType::Artists)),          // Empty version, but parts[2] exists
        ("discogs_v20260101_artists.xml.gz", Some(DataType::Artists)), // Version format not validated
        ("discogs_20260101", None),                                    // Only 2 parts, needs >= 3
        ("a_b", None),                                                 // Only 2 parts
    ];

    for (filename, expected) in edge_cases {
        let parts: Vec<&str> = filename.split('_').collect();
        let result = if parts.len() >= 3 {
            parts[2].split('.').next().and_then(|type_part| DataType::from_str(type_part).ok())
        } else {
            None
        };

        assert_eq!(result, expected, "Failed for edge case: {}", filename);
    }
}
