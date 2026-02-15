// Comprehensive unit tests for message_queue module
// These tests are kept separate from integration tests to allow more focused unit testing

#[cfg(test)]
mod message_queue_unit_tests {
    use crate::types::{DataMessage, DataType, FileCompleteMessage, Message};
    use serde_json::json;

    // Helper to create test messages
    fn create_test_data_message(id: &str) -> DataMessage {
        DataMessage { id: id.to_string(), sha256: format!("sha_{}", id), data: json!({"name": format!("Test {}", id)}) }
    }

    fn create_test_file_complete() -> FileCompleteMessage {
        FileCompleteMessage { data_type: "artists".to_string(), timestamp: chrono::Utc::now(), total_processed: 100, file: "test.xml.gz".to_string() }
    }

    #[test]
    fn test_message_serialization_data() {
        let msg = create_test_data_message("123");
        let message = Message::Data(msg);

        let serialized = serde_json::to_string(&message).unwrap();
        assert!(serialized.contains("\"type\":\"data\""));
        assert!(serialized.contains("\"id\":\"123\""));
    }

    #[test]
    fn test_message_serialization_file_complete() {
        let msg = create_test_file_complete();
        let message = Message::FileComplete(msg);

        let serialized = serde_json::to_string(&message).unwrap();
        assert!(serialized.contains("\"type\":\"file_complete\""));
        assert!(serialized.contains("\"total_processed\":100"));
    }

    // Note: normalize_amqp_url is private and already tested in the message_queue module
    // We test it indirectly through the public API

    #[test]
    fn test_data_type_display() {
        assert_eq!(DataType::Artists.to_string(), "artists");
        assert_eq!(DataType::Labels.to_string(), "labels");
        assert_eq!(DataType::Masters.to_string(), "masters");
        assert_eq!(DataType::Releases.to_string(), "releases");
    }

    #[test]
    fn test_data_type_routing_keys() {
        assert_eq!(DataType::Artists.routing_key(), "artists");
        assert_eq!(DataType::Labels.routing_key(), "labels");
        assert_eq!(DataType::Masters.routing_key(), "masters");
        assert_eq!(DataType::Releases.routing_key(), "releases");
    }

    #[test]
    fn test_message_data_variant_round_trip() {
        let original = create_test_data_message("test-id");
        let message = Message::Data(original.clone());

        let serialized = serde_json::to_string(&message).unwrap();
        let deserialized: Message = serde_json::from_str(&serialized).unwrap();

        match deserialized {
            Message::Data(dm) => {
                assert_eq!(dm.id, original.id);
                assert_eq!(dm.sha256, original.sha256);
            }
            _ => panic!("Expected Data variant"),
        }
    }

    #[test]
    fn test_message_file_complete_variant_round_trip() {
        let original = create_test_file_complete();
        let message = Message::FileComplete(original.clone());

        let serialized = serde_json::to_string(&message).unwrap();
        let deserialized: Message = serde_json::from_str(&serialized).unwrap();

        match deserialized {
            Message::FileComplete(fc) => {
                assert_eq!(fc.data_type, original.data_type);
                assert_eq!(fc.total_processed, original.total_processed);
                assert_eq!(fc.file, original.file);
            }
            _ => panic!("Expected FileComplete variant"),
        }
    }

    #[test]
    fn test_data_message_with_empty_data() {
        let msg = DataMessage { id: "empty".to_string(), sha256: "hash".to_string(), data: json!({}) };

        let serialized = serde_json::to_string(&msg).unwrap();
        assert!(serialized.contains("\"id\":\"empty\""));
    }

    #[test]
    fn test_data_message_with_nested_data() {
        let msg = DataMessage {
            id: "nested".to_string(),
            sha256: "hash".to_string(),
            data: json!({
                "name": "Test",
                "nested": {
                    "field": "value"
                }
            }),
        };

        let serialized = serde_json::to_string(&msg).unwrap();
        let deserialized: DataMessage = serde_json::from_str(&serialized).unwrap();

        assert!(deserialized.data.get("nested").is_some());
        assert_eq!(deserialized.data["nested"]["field"], "value");
    }

    #[test]
    fn test_file_complete_message_fields() {
        let msg = FileCompleteMessage {
            data_type: "labels".to_string(),
            timestamp: chrono::Utc::now(),
            total_processed: 12345,
            file: "discogs_20241201_labels.xml.gz".to_string(),
        };

        assert_eq!(msg.data_type, "labels");
        assert_eq!(msg.total_processed, 12345);
        assert!(msg.file.contains("labels"));
    }

    #[test]
    fn test_message_json_structure() {
        let msg = create_test_data_message("1");
        let message = Message::Data(msg);

        let json_value = serde_json::to_value(&message).unwrap();

        // Check JSON structure
        assert!(json_value.is_object());
        assert_eq!(json_value["type"], "data");
        assert!(json_value.get("id").is_some());
        assert!(json_value.get("sha256").is_some());
    }

    #[test]
    fn test_data_type_from_string_all_variants() {
        use std::str::FromStr;

        assert!(matches!(DataType::from_str("artists"), Ok(DataType::Artists)));
        assert!(matches!(DataType::from_str("labels"), Ok(DataType::Labels)));
        assert!(matches!(DataType::from_str("masters"), Ok(DataType::Masters)));
        assert!(matches!(DataType::from_str("releases"), Ok(DataType::Releases)));
        assert!(DataType::from_str("invalid").is_err());
        assert!(DataType::from_str("").is_err());
    }

    #[test]
    fn test_message_size_estimation() {
        // Test that messages can be serialized to reasonable sizes
        let msg = create_test_data_message("1");
        let message = Message::Data(msg);

        let serialized = serde_json::to_vec(&message).unwrap();
        assert!(!serialized.is_empty());
        assert!(serialized.len() < 1000); // Should be reasonable size
    }

    #[test]
    fn test_large_data_message() {
        let large_data = json!({
            "field1": "value".repeat(1000),
            "field2": vec![1; 1000],
            "field3": {
                "nested": "data".repeat(500)
            }
        });

        let msg = DataMessage { id: "large".to_string(), sha256: "hash".to_string(), data: large_data };

        let serialized = serde_json::to_string(&msg).unwrap();
        assert!(serialized.len() > 5000); // Should be large

        // Should still be deserializable
        let deserialized: DataMessage = serde_json::from_str(&serialized).unwrap();
        assert_eq!(deserialized.id, "large");
    }
}
