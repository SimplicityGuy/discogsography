
// Unit tests for normalize_amqp_url function
#[test]
fn test_normalize_amqp_url_with_trailing_slash() {
    use extractor::message_queue::MessageQueue;

    // Test that trailing slash is removed for default vhost
    let url = "amqp://localhost:5672/";
    let normalized = MessageQueue::normalize_amqp_url(url).unwrap();
    assert_eq!(normalized, "amqp://localhost:5672");
}

#[test]
fn test_normalize_amqp_url_without_trailing_slash() {
    use extractor::message_queue::MessageQueue;

    // Test that URL without trailing slash remains unchanged
    let url = "amqp://localhost:5672";
    let normalized = MessageQueue::normalize_amqp_url(url).unwrap();
    assert_eq!(normalized, "amqp://localhost:5672");
}

#[test]
fn test_normalize_amqp_url_with_custom_vhost() {
    use extractor::message_queue::MessageQueue;

    // Test that custom vhost is preserved
    let url = "amqp://localhost:5672/discogsography";
    let normalized = MessageQueue::normalize_amqp_url(url).unwrap();
    assert_eq!(normalized, "amqp://localhost:5672/discogsography");
}

#[test]
fn test_normalize_amqp_url_with_credentials() {
    use extractor::message_queue::MessageQueue;

    // Test that credentials are preserved
    let url = "amqp://user:pass@localhost:5672/";
    let normalized = MessageQueue::normalize_amqp_url(url).unwrap();
    assert_eq!(normalized, "amqp://user:pass@localhost:5672");
}

#[test]
fn test_normalize_amqp_url_with_credentials_and_vhost() {
    use extractor::message_queue::MessageQueue;

    // Test that credentials and custom vhost are preserved
    let url = "amqp://user:pass@localhost:5672/custom_vhost";
    let normalized = MessageQueue::normalize_amqp_url(url).unwrap();
    assert_eq!(normalized, "amqp://user:pass@localhost:5672/custom_vhost");
}

#[test]
fn test_normalize_amqp_url_invalid() {
    use extractor::message_queue::MessageQueue;

    // Test that invalid URL returns error
    let url = "not a valid url";
    let result = MessageQueue::normalize_amqp_url(url);
    assert!(result.is_err());
}

#[test]
fn test_normalize_amqp_url_empty() {
    use extractor::message_queue::MessageQueue;

    // Test that empty URL returns error
    let url = "";
    let result = MessageQueue::normalize_amqp_url(url);
    assert!(result.is_err());
}

#[test]
fn test_normalize_amqp_url_with_port() {
    use extractor::message_queue::MessageQueue;

    // Test that port is preserved
    let url = "amqp://localhost:15672/";
    let normalized = MessageQueue::normalize_amqp_url(url).unwrap();
    assert_eq!(normalized, "amqp://localhost:15672");
}

#[test]
fn test_normalize_amqp_url_complex() {
    use extractor::message_queue::MessageQueue;

    // Test complex URL with all components
    let url = "amqp://admin:secret@rabbitmq.example.com:5672/production";
    let normalized = MessageQueue::normalize_amqp_url(url).unwrap();
    assert_eq!(normalized, "amqp://admin:secret@rabbitmq.example.com:5672/production");
}

#[test]
fn test_normalize_amqp_url_amqps() {
    use extractor::message_queue::MessageQueue;

    // Test that amqps scheme is preserved
    let url = "amqps://localhost:5671/";
    let normalized = MessageQueue::normalize_amqp_url(url).unwrap();
    assert_eq!(normalized, "amqps://localhost:5671");
}
