use super::*;

#[test]
fn test_data_type_conversion() {
    assert_eq!(DataType::from_str("artists"), Ok(DataType::Artists));
    assert_eq!(DataType::from_str("LABELS"), Ok(DataType::Labels));
    assert!(DataType::from_str("unknown").is_err());
    assert_eq!(DataType::Artists.as_str(), "artists");
}

#[test]
fn test_data_type_all_types() {
    assert_eq!(DataType::from_str("artists"), Ok(DataType::Artists));
    assert_eq!(DataType::from_str("labels"), Ok(DataType::Labels));
    assert_eq!(DataType::from_str("masters"), Ok(DataType::Masters));
    assert_eq!(DataType::from_str("releases"), Ok(DataType::Releases));
}

#[test]
fn test_data_type_case_insensitive() {
    assert_eq!(DataType::from_str("ARTISTS"), Ok(DataType::Artists));
    assert_eq!(DataType::from_str("Artists"), Ok(DataType::Artists));
    assert_eq!(DataType::from_str("aRtIsTs"), Ok(DataType::Artists));
}

#[test]
fn test_data_type_invalid() {
    assert!(DataType::from_str("invalid").is_err());
    assert!(DataType::from_str("").is_err());
    assert!(DataType::from_str("artist").is_err()); // singular
}

#[test]
fn test_data_type_as_str() {
    assert_eq!(DataType::Artists.as_str(), "artists");
    assert_eq!(DataType::Labels.as_str(), "labels");
    assert_eq!(DataType::Masters.as_str(), "masters");
    assert_eq!(DataType::ReleaseGroups.as_str(), "release-groups");
    assert_eq!(DataType::Releases.as_str(), "releases");
}

#[test]
fn test_data_type_display() {
    assert_eq!(format!("{}", DataType::Artists), "artists");
    assert_eq!(format!("{}", DataType::Labels), "labels");
    assert_eq!(format!("{}", DataType::Masters), "masters");
    assert_eq!(format!("{}", DataType::ReleaseGroups), "release-groups");
    assert_eq!(format!("{}", DataType::Releases), "releases");
}

#[test]
fn test_data_type_all() {
    let all = DataType::all();
    assert_eq!(all.len(), 5);
    assert!(all.contains(&DataType::Artists));
    assert!(all.contains(&DataType::Labels));
    assert!(all.contains(&DataType::Masters));
    assert!(all.contains(&DataType::ReleaseGroups));
    assert!(all.contains(&DataType::Releases));
}

#[test]
fn test_extraction_progress() {
    let mut progress = ExtractionProgress::default();
    progress.increment(DataType::Artists);
    progress.increment(DataType::Artists);
    progress.increment(DataType::Labels);

    assert_eq!(progress.get(DataType::Artists), 2);
    assert_eq!(progress.get(DataType::Labels), 1);
    assert_eq!(progress.total(), 3);
}

#[test]
fn test_extraction_progress_all_types() {
    let mut progress = ExtractionProgress::default();
    progress.increment(DataType::Artists);
    progress.increment(DataType::Labels);
    progress.increment(DataType::Masters);
    progress.increment(DataType::ReleaseGroups);
    progress.increment(DataType::Releases);

    assert_eq!(progress.get(DataType::Artists), 1);
    assert_eq!(progress.get(DataType::Labels), 1);
    assert_eq!(progress.get(DataType::Masters), 1);
    assert_eq!(progress.get(DataType::ReleaseGroups), 1);
    assert_eq!(progress.get(DataType::Releases), 1);
    assert_eq!(progress.total(), 5);
}

#[test]
fn test_extraction_progress_default() {
    let progress = ExtractionProgress::default();
    assert_eq!(progress.artists, 0);
    assert_eq!(progress.labels, 0);
    assert_eq!(progress.masters, 0);
    assert_eq!(progress.release_groups, 0);
    assert_eq!(progress.releases, 0);
    assert_eq!(progress.total(), 0);
}

#[test]
fn test_message_serialization() {
    let data_msg = DataMessage { id: "123".to_string(), sha256: "abc".to_string(), data: serde_json::json!({"test": "value"}), raw_xml: None };

    let serialized = serde_json::to_string(&data_msg).unwrap();
    let deserialized: DataMessage = serde_json::from_str(&serialized).unwrap();

    assert_eq!(deserialized.id, "123");
    assert_eq!(deserialized.sha256, "abc");
}

#[test]
fn test_file_complete_message() {
    let msg = FileCompleteMessage { data_type: "artists".to_string(), timestamp: Utc::now(), total_processed: 1000, file: "test.xml".to_string() };

    assert_eq!(msg.data_type, "artists");
    assert_eq!(msg.total_processed, 1000);
    assert_eq!(msg.file, "test.xml");
}

#[test]
fn test_message_enum_data() {
    let data_msg = DataMessage { id: "1".to_string(), sha256: "hash".to_string(), data: serde_json::json!({}), raw_xml: None };

    let message = Message::Data(data_msg);
    match message {
        Message::Data(msg) => assert_eq!(msg.id, "1"),
        _ => panic!("Expected Data variant"),
    }
}

#[test]
fn test_message_enum_file_complete() {
    let file_msg = FileCompleteMessage { data_type: "labels".to_string(), timestamp: Utc::now(), total_processed: 500, file: "test.xml".to_string() };

    let message = Message::FileComplete(file_msg);
    match message {
        Message::FileComplete(msg) => assert_eq!(msg.total_processed, 500),
        _ => panic!("Expected FileComplete variant"),
    }
}

#[test]
fn test_message_enum_extraction_complete() {
    let mut record_counts = std::collections::HashMap::new();
    record_counts.insert("artists".to_string(), 9957079);
    record_counts.insert("labels".to_string(), 2349729);

    let msg = ExtractionCompleteMessage { version: "20260101".to_string(), timestamp: Utc::now(), started_at: Utc::now(), record_counts };

    let message = Message::ExtractionComplete(msg);
    match message {
        Message::ExtractionComplete(m) => {
            assert_eq!(m.version, "20260101");
            assert_eq!(m.record_counts["artists"], 9957079);
            assert_eq!(m.record_counts["labels"], 2349729);
        }
        _ => panic!("Expected ExtractionComplete variant"),
    }
}

#[test]
fn test_extraction_complete_serialization_format() {
    let mut record_counts = std::collections::HashMap::new();
    record_counts.insert("artists".to_string(), 100);

    let msg = ExtractionCompleteMessage { version: "20260101".to_string(), timestamp: Utc::now(), started_at: Utc::now(), record_counts };

    let message = Message::ExtractionComplete(msg);
    let json_str = serde_json::to_string(&message).unwrap();

    assert!(json_str.contains(r#""type":"extraction_complete""#), "Expected type tag, got: {}", json_str);
    assert!(json_str.contains(r#""version":"20260101""#), "Expected version field, got: {}", json_str);
    assert!(json_str.contains(r#""started_at""#), "Expected started_at field, got: {}", json_str);
    assert!(json_str.contains(r#""record_counts""#), "Expected record_counts field, got: {}", json_str);
}

#[test]
fn test_source_display() {
    assert_eq!(format!("{}", Source::Discogs), "discogs");
    assert_eq!(format!("{}", Source::MusicBrainz), "musicbrainz");
}

#[test]
fn test_source_from_str() {
    assert_eq!(Source::from_str("discogs"), Ok(Source::Discogs));
    assert_eq!(Source::from_str("musicbrainz"), Ok(Source::MusicBrainz));
    assert_eq!(Source::from_str("DISCOGS"), Ok(Source::Discogs));
    assert_eq!(Source::from_str("MUSICBRAINZ"), Ok(Source::MusicBrainz));
    assert_eq!(Source::from_str("Discogs"), Ok(Source::Discogs));
    assert_eq!(Source::from_str("MusicBrainz"), Ok(Source::MusicBrainz));
}

#[test]
fn test_source_from_str_invalid() {
    assert!(Source::from_str("invalid").is_err());
    assert!(Source::from_str("").is_err());
    assert!(Source::from_str("spotify").is_err());
}

#[test]
fn test_source_serialize_deserialize() {
    let discogs = Source::Discogs;
    let json = serde_json::to_string(&discogs).unwrap();
    assert_eq!(json, r#""Discogs""#);
    let deserialized: Source = serde_json::from_str(&json).unwrap();
    assert_eq!(deserialized, Source::Discogs);

    let mb = Source::MusicBrainz;
    let json = serde_json::to_string(&mb).unwrap();
    assert_eq!(json, r#""MusicBrainz""#);
    let deserialized: Source = serde_json::from_str(&json).unwrap();
    assert_eq!(deserialized, Source::MusicBrainz);
}

#[test]
fn test_discogs_types() {
    let discogs = DataType::discogs();
    assert_eq!(discogs.len(), 4);
    assert!(discogs.contains(&DataType::Artists));
    assert!(discogs.contains(&DataType::Labels));
    assert!(discogs.contains(&DataType::Masters));
    assert!(discogs.contains(&DataType::Releases));
    // Discogs does not have ReleaseGroups
    assert!(!discogs.contains(&DataType::ReleaseGroups));
}

#[test]
fn test_musicbrainz_types() {
    let mb_types = DataType::musicbrainz();
    assert_eq!(mb_types.len(), 4);
    assert!(mb_types.contains(&DataType::Artists));
    assert!(mb_types.contains(&DataType::Labels));
    assert!(mb_types.contains(&DataType::ReleaseGroups));
    assert!(mb_types.contains(&DataType::Releases));
    // MusicBrainz does not have Masters
    assert!(!mb_types.contains(&DataType::Masters));
}
