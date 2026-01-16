// Integration tests for message queue module

use rust_extractor::types::{DataMessage, DataType, FileCompleteMessage, Message};
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
