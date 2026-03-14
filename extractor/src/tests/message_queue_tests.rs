use super::*;

#[test]
fn test_exchange_names() {
    assert_eq!(MessageQueue::exchange_name(DataType::Artists), "discogsography-artists");
    assert_eq!(MessageQueue::exchange_name(DataType::Labels), "discogsography-labels");
    assert_eq!(MessageQueue::exchange_name(DataType::Masters), "discogsography-masters");
    assert_eq!(MessageQueue::exchange_name(DataType::Releases), "discogsography-releases");
}

#[test]
fn test_normalize_amqp_url_with_trailing_slash() {
    // Trailing slash should be removed to use default vhost
    let url = "amqp://user:pass@host:5672/";
    let normalized = MessageQueue::normalize_amqp_url(url).unwrap();
    assert_eq!(normalized, "amqp://user:pass@host:5672");
}

#[test]
fn test_normalize_amqp_url_without_trailing_slash() {
    // No trailing slash should remain unchanged
    let url = "amqp://user:pass@host:5672";
    let normalized = MessageQueue::normalize_amqp_url(url).unwrap();
    assert_eq!(normalized, "amqp://user:pass@host:5672");
}

#[test]
fn test_normalize_amqp_url_with_explicit_vhost() {
    // Explicit vhost should be preserved
    let url = "amqp://user:pass@host:5672/discogsography";
    let normalized = MessageQueue::normalize_amqp_url(url).unwrap();
    assert_eq!(normalized, "amqp://user:pass@host:5672/discogsography");
}

#[test]
fn test_normalize_amqp_url_with_encoded_default_vhost() {
    // URL-encoded default vhost %2F should be preserved
    let url = "amqp://user:pass@host:5672/%2F";
    let normalized = MessageQueue::normalize_amqp_url(url).unwrap();
    assert_eq!(normalized, "amqp://user:pass@host:5672/%2F");
}

#[test]
fn test_normalize_amqp_url_minimal() {
    // Minimal URL without credentials
    let url = "amqp://localhost:5672/";
    let normalized = MessageQueue::normalize_amqp_url(url).unwrap();
    assert_eq!(normalized, "amqp://localhost:5672");
}

#[test]
fn test_normalize_amqp_url_invalid() {
    // Invalid URL should return error
    let url = "not-a-valid-url";
    let result = MessageQueue::normalize_amqp_url(url);
    assert!(result.is_err());
}

#[test]
fn test_normalize_amqp_url_empty() {
    let result = MessageQueue::normalize_amqp_url("");
    assert!(result.is_err());
}

#[test]
fn test_normalize_amqp_url_different_ports() {
    let url1 = "amqp://host:5672/";
    let url2 = "amqp://host:15672/";

    let normalized1 = MessageQueue::normalize_amqp_url(url1).unwrap();
    let normalized2 = MessageQueue::normalize_amqp_url(url2).unwrap();

    assert_eq!(normalized1, "amqp://host:5672");
    assert_eq!(normalized2, "amqp://host:15672");
}

#[test]
fn test_normalize_amqp_url_with_query_params() {
    let url = "amqp://host:5672/?heartbeat=30";
    let normalized = MessageQueue::normalize_amqp_url(url).unwrap();
    // Query params should be preserved
    assert!(normalized.contains("heartbeat=30"));
}

#[test]
fn test_message_serialization_data() {
    let data_msg = DataMessage { id: "123".to_string(), sha256: "abc".to_string(), data: serde_json::json!({"key": "value"}) };

    let message = Message::Data(data_msg);
    let serialized = serde_json::to_vec(&message).unwrap();
    let deserialized: Message = serde_json::from_slice(&serialized).unwrap();

    match deserialized {
        Message::Data(msg) => {
            assert_eq!(msg.id, "123");
            assert_eq!(msg.sha256, "abc");
        }
        _ => panic!("Expected Data message"),
    }
}

#[test]
fn test_message_serialization_file_complete() {
    let file_complete_msg = FileCompleteMessage {
        data_type: "artists".to_string(),
        timestamp: chrono::Utc::now(),
        total_processed: 100,
        file: "test.xml".to_string(),
    };

    let message = Message::FileComplete(file_complete_msg.clone());
    let serialized = serde_json::to_vec(&message).unwrap();
    let deserialized: Message = serde_json::from_slice(&serialized).unwrap();

    match deserialized {
        Message::FileComplete(msg) => {
            assert_eq!(msg.data_type, "artists");
            assert_eq!(msg.total_processed, 100);
            assert_eq!(msg.file, "test.xml");
        }
        _ => panic!("Expected FileComplete message"),
    }
}

#[test]
fn test_constants() {
    assert_eq!(AMQP_EXCHANGE_PREFIX, "discogsography");
    assert_eq!(AMQP_EXCHANGE_TYPE, ExchangeKind::Fanout);
}

#[test]
fn test_message_properties_persistent_delivery() {
    let props = MessageQueue::message_properties();
    // delivery_mode 2 = persistent (messages survive broker restart)
    assert_eq!(props.delivery_mode(), &Some(2));
    assert!(props.content_type().is_some());
    let encoding = props.content_encoding().as_ref().expect("content_encoding should be set");
    assert_eq!(encoding.as_str(), "UTF-8", "content_encoding should be UTF-8");
}


#[tokio::test]
async fn test_new_connection_failure() {
    // Use an invalid port so the connection will fail, with only 1 retry to keep the test fast
    let result = MessageQueue::new("amqp://localhost:59999", 1).await;
    assert!(result.is_err());
    let err_msg = format!("{}", result.err().unwrap());
    assert!(err_msg.contains("Failed to connect to AMQP broker after retries"), "Unexpected error: {}", err_msg);
}

#[test]
fn test_extraction_complete_message_roundtrip() {
    let mut record_counts = std::collections::HashMap::new();
    record_counts.insert("artists".to_string(), 9957079);
    record_counts.insert("releases".to_string(), 18952204);

    let msg = ExtractionCompleteMessage {
        version: "20260101".to_string(),
        timestamp: chrono::Utc::now(),
        started_at: chrono::Utc::now(),
        record_counts: record_counts.clone(),
    };

    let message = Message::ExtractionComplete(msg);
    let serialized = serde_json::to_vec(&message).unwrap();
    let deserialized: Message = serde_json::from_slice(&serialized).unwrap();

    match deserialized {
        Message::ExtractionComplete(m) => {
            assert_eq!(m.version, "20260101");
            assert_eq!(m.record_counts["artists"], 9957079);
            assert_eq!(m.record_counts["releases"], 18952204);
        }
        _ => panic!("Expected ExtractionComplete message"),
    }
}

#[test]
fn test_normalize_amqp_url_with_credentials_special_chars() {
    // URL with percent-encoded special characters in credentials
    let url = "amqp://user%40domain:p%40ss@host:5672/%2F";
    let normalized = MessageQueue::normalize_amqp_url(url).unwrap();
    // Credentials with special chars and explicit %2F vhost should be preserved
    assert!(normalized.contains("user%40domain"));
    assert!(normalized.contains("p%40ss"));
    assert!(normalized.contains("/%2F"));
}

#[test]
fn test_normalize_amqp_url_amqps_scheme() {
    // TLS scheme should be preserved
    let url = "amqps://user:pass@host:5671/";
    let normalized = MessageQueue::normalize_amqp_url(url).unwrap();
    assert!(normalized.starts_with("amqps://"), "Expected amqps:// scheme, got: {}", normalized);
    assert_eq!(normalized, "amqps://user:pass@host:5671");
}

#[test]
fn test_file_complete_message_serialization_format() {
    let file_complete_msg = FileCompleteMessage {
        data_type: "artists".to_string(),
        timestamp: chrono::Utc::now(),
        total_processed: 42,
        file: "discogs_20250101_artists.xml.gz".to_string(),
    };

    let message = Message::FileComplete(file_complete_msg);
    let json_str = serde_json::to_string(&message).unwrap();

    // Verify the tagged enum produces "type": "file_complete"
    assert!(json_str.contains(r#""type":"file_complete""#), "Expected type tag, got: {}", json_str);
    assert!(json_str.contains(r#""data_type":"artists""#), "Expected data_type field, got: {}", json_str);
    assert!(json_str.contains(r#""total_processed":42"#), "Expected total_processed field, got: {}", json_str);
    assert!(json_str.contains(r#""file":"discogs_20250101_artists.xml.gz""#), "Expected file field, got: {}", json_str);
    assert!(json_str.contains(r#""timestamp""#), "Expected timestamp field, got: {}", json_str);
}

#[test]
fn test_data_message_serialization_format() {
    let data_msg = DataMessage {
        id: "456".to_string(),
        sha256: "deadbeef".to_string(),
        data: serde_json::json!({"name": "Test Artist"}),
    };

    let message = Message::Data(data_msg);
    let json_str = serde_json::to_string(&message).unwrap();

    // Verify the tagged enum produces "type": "data"
    assert!(json_str.contains(r#""type":"data""#), "Expected type tag, got: {}", json_str);
    assert!(json_str.contains(r#""id":"456""#), "Expected id field, got: {}", json_str);
    assert!(json_str.contains(r#""sha256":"deadbeef""#), "Expected sha256 field, got: {}", json_str);
    // DataMessage uses #[serde(flatten)] on data, so fields appear at top level
    assert!(json_str.contains(r#""name":"Test Artist""#), "Expected flattened data field, got: {}", json_str);
}

#[test]
fn test_message_properties_content_type() {
    let props = MessageQueue::message_properties();
    let content_type = props.content_type().as_ref().expect("content_type should be set");
    assert_eq!(content_type.as_str(), "application/json");
}

#[tokio::test]
async fn test_new_connection_failure_with_retries() {
    // Use 2 retries to exercise the retry backoff loop (lines 72-75):
    // - First attempt: try_connect fails, retry_count=1 < 2, warn + sleep(1s) + backoff doubled
    // - Second attempt: try_connect fails, retry_count=2 >= 2, return error
    let result = MessageQueue::new("amqp://localhost:59999", 2).await;
    assert!(result.is_err());
    let err_msg = format!("{}", result.err().unwrap());
    assert!(err_msg.contains("Failed to connect to AMQP broker after retries"), "Unexpected error: {}", err_msg);
}
