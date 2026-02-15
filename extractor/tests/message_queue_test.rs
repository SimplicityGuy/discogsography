// Integration tests for message queue module

use extractor::types::{DataMessage, DataType, FileCompleteMessage, Message};
use serde_json::json;

#[test]
fn test_data_message_serialization() {
    let message = DataMessage {
        id: "123".to_string(),
        sha256: "abc123".to_string(),
        data: json!({"name": "Test Artist"}),
    };

    let serialized = serde_json::to_string(&message).unwrap();
    assert!(serialized.contains("\"id\":\"123\""));
    assert!(serialized.contains("\"sha256\":\"abc123\""));
}

#[test]
fn test_data_message_deserialization() {
    let json_str = r#"{"id":"123","sha256":"abc123","name":"Test Artist"}"#;
    let message: DataMessage = serde_json::from_str(json_str).unwrap();

    assert_eq!(message.id, "123");
    assert_eq!(message.sha256, "abc123");
    assert!(message.data.get("name").is_some());
}

#[test]
fn test_file_complete_message_serialization() {
    let message = FileCompleteMessage {
        data_type: "artists".to_string(),
        timestamp: chrono::Utc::now(),
        total_processed: 100,
        file: "test.xml.gz".to_string(),
    };

    let serialized = serde_json::to_string(&message).unwrap();
    assert!(serialized.contains("\"data_type\":\"artists\""));
    assert!(serialized.contains("\"total_processed\":100"));
    assert!(serialized.contains("\"file\":\"test.xml.gz\""));
}

#[test]
fn test_message_enum_data_variant() {
    let data_msg = DataMessage {
        id: "123".to_string(),
        sha256: "abc".to_string(),
        data: json!({"test": "value"}),
    };

    let message = Message::Data(data_msg);
    let serialized = serde_json::to_string(&message).unwrap();

    assert!(serialized.contains("\"type\":\"data\""));
}

#[test]
fn test_message_enum_file_complete_variant() {
    let fc_msg = FileCompleteMessage {
        data_type: "artists".to_string(),
        timestamp: chrono::Utc::now(),
        total_processed: 50,
        file: "test.xml".to_string(),
    };

    let message = Message::FileComplete(fc_msg);
    let serialized = serde_json::to_string(&message).unwrap();

    assert!(serialized.contains("\"type\":\"file_complete\""));
}

#[test]
fn test_data_type_routing_key() {
    assert_eq!(DataType::Artists.routing_key(), "artists");
    assert_eq!(DataType::Labels.routing_key(), "labels");
    assert_eq!(DataType::Masters.routing_key(), "masters");
    assert_eq!(DataType::Releases.routing_key(), "releases");
}

#[test]
fn test_message_serialization_round_trip() {
    let data_msg = DataMessage {
        id: "test-id".to_string(),
        sha256: "test-sha".to_string(),
        data: json!({"field": "value"}),
    };

    let message = Message::Data(data_msg);
    let serialized = serde_json::to_string(&message).unwrap();
    let deserialized: Message = serde_json::from_str(&serialized).unwrap();

    match deserialized {
        Message::Data(dm) => {
            assert_eq!(dm.id, "test-id");
            assert_eq!(dm.sha256, "test-sha");
        }
        _ => panic!("Wrong message type"),
    }
}

#[test]
fn test_data_message_with_complex_data() {
    let complex_data = json!({
        "name": "Test",
        "nested": {
            "field1": "value1",
            "field2": 123
        },
        "array": [1, 2, 3]
    });

    let message = DataMessage {
        id: "complex".to_string(),
        sha256: "hash".to_string(),
        data: complex_data,
    };

    let serialized = serde_json::to_string(&message).unwrap();
    let deserialized: DataMessage = serde_json::from_str(&serialized).unwrap();

    assert_eq!(deserialized.id, "complex");
    assert!(deserialized.data.get("nested").is_some());
    assert!(deserialized.data.get("array").is_some());
}

#[test]
fn test_file_complete_message_timestamp() {
    use chrono::Utc;

    let now = Utc::now();
    let message = FileCompleteMessage {
        data_type: "test".to_string(),
        timestamp: now,
        total_processed: 42,
        file: "file.xml".to_string(),
    };

    let serialized = serde_json::to_string(&message).unwrap();
    let deserialized: FileCompleteMessage = serde_json::from_str(&serialized).unwrap();

    // Timestamps should be roughly equal (within a second)
    let diff = (deserialized.timestamp - now).num_seconds().abs();
    assert!(diff < 1);
}

#[test]
fn test_message_type_tag() {
    let data_msg = DataMessage {
        id: "1".to_string(),
        sha256: "hash".to_string(),
        data: json!({}),
    };

    let message = Message::Data(data_msg);
    let json_value = serde_json::to_value(&message).unwrap();

    assert_eq!(json_value["type"], "data");
}

#[test]
fn test_data_message_flattened_data() {
    // The data field is flattened, so it should be at the same level as id and sha256
    let message = DataMessage {
        id: "123".to_string(),
        sha256: "abc".to_string(),
        data: json!({"custom_field": "custom_value"}),
    };

    let json_value = serde_json::to_value(&message).unwrap();

    // These fields should all be at the root level
    assert!(json_value.get("id").is_some());
    assert!(json_value.get("sha256").is_some());
    assert!(json_value.get("custom_field").is_some());
    // There should NOT be a nested "data" field
    assert!(json_value.get("data").is_none());
}

// Additional tests for DataType

#[test]
fn test_data_type_display() {
    assert_eq!(DataType::Artists.to_string(), "artists");
    assert_eq!(DataType::Labels.to_string(), "labels");
    assert_eq!(DataType::Masters.to_string(), "masters");
    assert_eq!(DataType::Releases.to_string(), "releases");
}

#[test]
fn test_data_type_as_str() {
    assert_eq!(DataType::Artists.as_str(), "artists");
    assert_eq!(DataType::Labels.as_str(), "labels");
    assert_eq!(DataType::Masters.as_str(), "masters");
    assert_eq!(DataType::Releases.as_str(), "releases");
}

#[test]
fn test_data_type_from_str() {
    use std::str::FromStr;

    assert_eq!(DataType::from_str("artists").unwrap(), DataType::Artists);
    assert_eq!(DataType::from_str("labels").unwrap(), DataType::Labels);
    assert_eq!(DataType::from_str("masters").unwrap(), DataType::Masters);
    assert_eq!(DataType::from_str("releases").unwrap(), DataType::Releases);

    // Test invalid data type
    assert!(DataType::from_str("invalid").is_err());
    assert!(DataType::from_str("").is_err());
}

#[test]
fn test_message_enum_tagged() {
    // Test that Message enum uses tagged format
    let data_msg = DataMessage {
        id: "123".to_string(),
        sha256: "abc".to_string(),
        data: json!({}),
    };
    let message = Message::Data(data_msg);
    let json_str = serde_json::to_string(&message).unwrap();
    assert!(json_str.contains("\"type\":\"data\""));

    let fc_msg = FileCompleteMessage {
        data_type: "test".to_string(),
        timestamp: chrono::Utc::now(),
        total_processed: 1,
        file: "test.xml".to_string(),
    };
    let message = Message::FileComplete(fc_msg);
    let json_str = serde_json::to_string(&message).unwrap();
    assert!(json_str.contains("\"type\":\"file_complete\""));
}

#[test]
fn test_data_message_with_empty_data() {
    let message = DataMessage {
        id: "123".to_string(),
        sha256: "abc".to_string(),
        data: json!({}),
    };

    let serialized = serde_json::to_string(&message).unwrap();
    let deserialized: DataMessage = serde_json::from_str(&serialized).unwrap();

    assert_eq!(deserialized.id, "123");
    assert_eq!(deserialized.sha256, "abc");
    assert!(deserialized.data.is_object());
}

#[test]
fn test_file_complete_message_serialization_fields() {
    let msg = FileCompleteMessage {
        data_type: "artists".to_string(),
        timestamp: chrono::Utc::now(),
        total_processed: 999,
        file: "test_file.xml.gz".to_string(),
    };

    let json_value = serde_json::to_value(&msg).unwrap();

    assert_eq!(json_value["data_type"], "artists");
    assert_eq!(json_value["total_processed"], 999);
    assert_eq!(json_value["file"], "test_file.xml.gz");
    assert!(json_value.get("timestamp").is_some());
}

#[test]
fn test_data_message_large_data() {
    // Test with large nested JSON data
    let large_data = json!({
        "artists": (0..100).map(|i| format!("artist_{}", i)).collect::<Vec<_>>(),
        "labels": (0..100).map(|i| format!("label_{}", i)).collect::<Vec<_>>(),
        "nested": {
            "deep": {
                "values": (0..100).collect::<Vec<_>>()
            }
        }
    });

    let message = DataMessage {
        id: "large_test".to_string(),
        sha256: "hash123".to_string(),
        data: large_data.clone(),
    };

    let serialized = serde_json::to_string(&message).unwrap();
    let deserialized: DataMessage = serde_json::from_str(&serialized).unwrap();

    assert_eq!(deserialized.id, "large_test");
    assert!(deserialized.data.get("artists").is_some());
    assert!(deserialized.data.get("labels").is_some());
    assert!(deserialized.data.get("nested").is_some());
}

// Note: normalize_amqp_url tests are in the module unit tests (src/message_queue.rs)
// since it's a private function

#[test]
fn test_message_batch_serialization() {
    let messages = vec![
        DataMessage {
            id: "1".to_string(),
            sha256: "hash1".to_string(),
            data: json!({"field": "value1"}),
        },
        DataMessage {
            id: "2".to_string(),
            sha256: "hash2".to_string(),
            data: json!({"field": "value2"}),
        },
        DataMessage {
            id: "3".to_string(),
            sha256: "hash3".to_string(),
            data: json!({"field": "value3"}),
        },
    ];

    // Serialize batch
    let serialized: Vec<String> = messages
        .iter()
        .map(|m| serde_json::to_string(&Message::Data(m.clone())).unwrap())
        .collect();

    assert_eq!(serialized.len(), 3);
    for json_str in &serialized {
        assert!(json_str.contains("\"type\":\"data\""));
    }
}

#[test]
fn test_data_type_equality() {
    assert_eq!(DataType::Artists, DataType::Artists);
    assert_ne!(DataType::Artists, DataType::Labels);
    assert_ne!(DataType::Masters, DataType::Releases);
}

#[test]
fn test_data_type_clone() {
    let dt1 = DataType::Artists;
    let dt2 = dt1;
    assert_eq!(dt1, dt2);
}

#[test]
fn test_message_size_estimation() {
    let message = DataMessage {
        id: "test_id".to_string(),
        sha256: "a".repeat(64),
        data: json!({
            "name": "Test Artist",
            "members": vec!["member1", "member2", "member3"],
        }),
    };

    let serialized = serde_json::to_vec(&Message::Data(message)).unwrap();
    // Verify reasonable message size (not too large)
    assert!(serialized.len() < 1024); // Less than 1KB for typical message
}

#[test]
fn test_file_complete_message_with_zero_processed() {
    let msg = FileCompleteMessage {
        data_type: "artists".to_string(),
        timestamp: chrono::Utc::now(),
        total_processed: 0,
        file: "empty.xml".to_string(),
    };

    let serialized = serde_json::to_string(&msg).unwrap();
    let deserialized: FileCompleteMessage = serde_json::from_str(&serialized).unwrap();

    assert_eq!(deserialized.total_processed, 0);
}

#[test]
fn test_file_complete_message_with_large_count() {
    let msg = FileCompleteMessage {
        data_type: "releases".to_string(),
        timestamp: chrono::Utc::now(),
        total_processed: 1_000_000_000, // 1 billion
        file: "large.xml.gz".to_string(),
    };

    let serialized = serde_json::to_string(&msg).unwrap();
    let deserialized: FileCompleteMessage = serde_json::from_str(&serialized).unwrap();

    assert_eq!(deserialized.total_processed, 1_000_000_000);
}
