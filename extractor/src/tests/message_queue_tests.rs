use super::*;

#[test]
fn test_exchange_names_default_prefix() {
    let mq = MessageQueue {
        connection: Arc::new(RwLock::new(None)),
        channel: Arc::new(RwLock::new(None)),
        reconnect_mutex: tokio::sync::Mutex::new(()),
        url: String::new(),
        max_retries: 1,
        exchange_prefix: DEFAULT_EXCHANGE_PREFIX.to_string(),
        backpressure: Arc::default(),
    };
    assert_eq!(mq.exchange_name(DataType::Artists), "discogsography-discogs-artists");
    assert_eq!(mq.exchange_name(DataType::Labels), "discogsography-discogs-labels");
    assert_eq!(mq.exchange_name(DataType::Masters), "discogsography-discogs-masters");
    assert_eq!(mq.exchange_name(DataType::Releases), "discogsography-discogs-releases");
}

#[test]
fn test_exchange_names_custom_prefix() {
    let mq = MessageQueue {
        connection: Arc::new(RwLock::new(None)),
        channel: Arc::new(RwLock::new(None)),
        reconnect_mutex: tokio::sync::Mutex::new(()),
        url: String::new(),
        max_retries: 1,
        exchange_prefix: "discogsography-musicbrainz".to_string(),
        backpressure: Arc::default(),
    };
    assert_eq!(mq.exchange_name(DataType::Artists), "discogsography-musicbrainz-artists");
    assert_eq!(mq.exchange_name(DataType::Labels), "discogsography-musicbrainz-labels");
    assert_eq!(mq.exchange_name(DataType::Releases), "discogsography-musicbrainz-releases");
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
    let data_msg = DataMessage { id: "123".to_string(), sha256: "abc".to_string(), data: serde_json::json!({"key": "value"}), raw_xml: None };

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
    let file_complete_msg =
        FileCompleteMessage { data_type: "artists".to_string(), timestamp: chrono::Utc::now(), total_processed: 100, file: "test.xml".to_string() };

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
    assert_eq!(DEFAULT_EXCHANGE_PREFIX, "discogsography-discogs");
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
    let result = MessageQueue::new("amqp://localhost:59999", 1, DEFAULT_EXCHANGE_PREFIX, Arc::default()).await;
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
    let data_msg =
        DataMessage { id: "456".to_string(), sha256: "deadbeef".to_string(), data: serde_json::json!({"name": "Test Artist"}), raw_xml: None };

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
async fn test_get_channel_with_no_channel_triggers_reconnect() {
    // When channel is None, get_channel should attempt to reconnect.
    // With an invalid URL, reconnection fails — exercising the slow path
    // including the reconnect_mutex lock and double-check pattern.
    let mq = MessageQueue {
        connection: Arc::new(RwLock::new(None)),
        channel: Arc::new(RwLock::new(None)),
        reconnect_mutex: tokio::sync::Mutex::new(()),
        url: "amqp://localhost:59999".to_string(),
        max_retries: 1,
        exchange_prefix: DEFAULT_EXCHANGE_PREFIX.to_string(),
        backpressure: Arc::default(),
    };

    let result = mq.get_channel().await;
    assert!(result.is_err(), "Expected error when channel is None and reconnect fails");
    let err_msg = format!("{}", result.err().unwrap());
    assert!(err_msg.contains("Failed to connect") || err_msg.contains("Failed to get channel"), "Unexpected error: {}", err_msg);
}

#[tokio::test]
async fn test_close_with_no_channel_or_connection_is_ok() {
    // discogsography-cu2.108 regression: close() must be a best-effort no-op
    // (never early-return via `?`) when there's nothing to close — the
    // happy-path baseline for the "always attempt both closes" contract.
    let mq = MessageQueue {
        connection: Arc::new(RwLock::new(None)),
        channel: Arc::new(RwLock::new(None)),
        reconnect_mutex: tokio::sync::Mutex::new(()),
        url: String::new(),
        max_retries: 1,
        exchange_prefix: DEFAULT_EXCHANGE_PREFIX.to_string(),
        backpressure: Arc::default(),
    };

    let result = mq.close().await;
    assert!(result.is_ok(), "close() with no channel/connection must succeed: {:?}", result.err());
    // Both slots must remain drained (taken) after close().
    assert!(mq.channel.read().await.is_none());
    assert!(mq.connection.read().await.is_none());
}

#[tokio::test]
async fn test_new_connection_failure_with_retries() {
    // Use 2 retries to exercise the retry backoff loop (lines 72-75):
    // - First attempt: try_connect fails, retry_count=1 < 2, warn + sleep(1s) + backoff doubled
    // - Second attempt: try_connect fails, retry_count=2 >= 2, return error
    let result = MessageQueue::new("amqp://localhost:59999", 2, DEFAULT_EXCHANGE_PREFIX, Arc::default()).await;
    assert!(result.is_err());
    let err_msg = format!("{}", result.err().unwrap());
    assert!(err_msg.contains("Failed to connect to AMQP broker after retries"), "Unexpected error: {}", err_msg);
}

// ── Publisher-confirm timeout (discogsography-rehd) ────────────────────────────

#[tokio::test]
async fn test_await_confirm_accepts_ack() {
    let result = MessageQueue::await_confirm(async { Ok(Confirmation::Ack(None)) }).await;
    assert!(result.is_ok(), "an acked publish must succeed");
}

#[tokio::test]
async fn test_await_confirm_passes_nack_through() {
    // Nack rejection itself lives in check_confirmation (discogsography-i3h2);
    // await_confirm's contract is to surface the confirmation for that check.
    let confirm = MessageQueue::await_confirm(async { Ok(Confirmation::Nack(None)) }).await.expect("a resolved confirm must not error");
    assert!(!confirm.is_ack(), "a nack must surface to the caller for check_confirmation");
}

#[tokio::test(start_paused = true)]
async fn test_await_confirm_times_out_on_stall() {
    // A broker under a memory / disk_free alarm keeps the connection up while
    // withholding acks, so the confirm future never resolves. Without a
    // deadline the publisher task parks forever, the bounded batch channel
    // fills, the batcher blocks, and the whole per-file pipeline wedges —
    // SIGTERM cannot break it because the shutdown flag is only polled between
    // files.
    let stalled = std::future::pending::<lapin::Result<Confirmation>>();

    let result = MessageQueue::await_confirm(stalled).await;

    let err = result.expect_err("a stalled confirm must time out, not hang");
    assert!(err.to_string().contains("Timed out"), "unexpected error: {}", err);
}

#[test]
fn test_publish_confirm_timeout_is_bounded() {
    assert!(PUBLISH_CONFIRM_TIMEOUT > Duration::ZERO);
    assert!(PUBLISH_CONFIRM_TIMEOUT <= Duration::from_secs(60));
}

/// Regression for discogsography-i3h2: publishes must be mandatory, otherwise the broker
/// acks and silently drops messages that route to zero queues.
#[test]
fn test_publish_options_are_mandatory() {
    let options = MessageQueue::publish_options();
    assert!(options.mandatory, "publishes must be mandatory so unroutable messages are returned, not dropped");
    assert!(!options.immediate, "immediate is deprecated by RabbitMQ and must stay off");
}

#[test]
fn test_confirmation_ack_without_return() {
    // The healthy case: acked and routed.
    assert!(check_confirmation("discogsography-discogs-artists", true, None).is_ok());
}

#[test]
fn test_confirmation_returned_is_failure() {
    // RabbitMQ answers a mandatory publish that matched no queue with basic.return
    // FOLLOWED BY basic.ack — the ack alone must not be read as delivery.
    let err = check_confirmation("discogsography-discogs-artists", true, Some((312, "NO_ROUTE".to_string())))
        .expect_err("an unroutable message must fail the publish");
    let message = err.to_string();
    assert!(message.contains("discogsography-discogs-artists"), "error should name the exchange: {message}");
    assert!(message.contains("NO_ROUTE") && message.contains("312"), "error should carry the broker's reason: {message}");
}

#[test]
fn test_confirmation_nack_is_failure() {
    let err = check_confirmation("discogsography-discogs-artists", false, None).expect_err("a nack must fail the publish");
    assert!(err.to_string().contains("not acknowledged"), "unexpected error: {err}");
}

#[test]
fn test_confirmation_nack_with_return() {
    // A nack that also carries a returned message reports the routing failure.
    let err = check_confirmation("discogsography-discogs-releases", false, Some((312, "NO_ROUTE".to_string()))).expect_err("must fail");
    assert!(err.to_string().contains("unroutable"), "unexpected error: {err}");
}

// ── In-place publish retry under broker backpressure (discogsography-5ow5) ─────

/// A scripted publish attempt: pops the next outcome per call and counts calls.
fn scripted_attempts(
    outcomes: Vec<Result<(), PublishError>>,
) -> (Arc<std::sync::atomic::AtomicU32>, impl FnMut() -> std::future::Ready<Result<(), PublishError>>) {
    let calls = Arc::new(std::sync::atomic::AtomicU32::new(0));
    let counter = calls.clone();
    let mut outcomes = std::collections::VecDeque::from(outcomes);
    let attempt = move || {
        counter.fetch_add(1, Ordering::SeqCst);
        std::future::ready(outcomes.pop_front().expect("publish attempted more often than scripted"))
    };
    (calls, attempt)
}

fn nack() -> Result<(), PublishError> {
    Err(PublishError::Nacked { exchange: "ex".to_string() })
}

#[test]
fn test_publish_retry_backoff_schedule() {
    // 0.5s doubling to a 30s cap.
    let schedule: Vec<Duration> = (1..=9).map(publish_retry_backoff).collect();
    let expected_ms = [500, 1_000, 2_000, 4_000, 8_000, 16_000, 30_000, 30_000, 30_000];
    assert_eq!(schedule, expected_ms.iter().map(|ms| Duration::from_millis(*ms)).collect::<Vec<_>>());
    assert_eq!(PUBLISH_RETRY_INITIAL_BACKOFF, Duration::from_millis(500));
    assert_eq!(PUBLISH_RETRY_MAX_BACKOFF, Duration::from_secs(30));
    // Degenerate and huge retry numbers stay in range instead of overflowing.
    assert_eq!(publish_retry_backoff(0), PUBLISH_RETRY_INITIAL_BACKOFF);
    assert_eq!(publish_retry_backoff(1_000), PUBLISH_RETRY_MAX_BACKOFF);
    assert_eq!(publish_retry_backoff(u32::MAX), PUBLISH_RETRY_MAX_BACKOFF);
}

#[test]
fn test_publish_error_classification() {
    // Backpressure: retried in place.
    assert_eq!(PublishError::Nacked { exchange: "ex".into() }.backpressure_reason(), Some("nack"));
    assert_eq!(PublishError::ConfirmTimeout(PUBLISH_CONFIRM_TIMEOUT).backpressure_reason(), Some("confirm_timeout"));
    assert_eq!(PublishError::Transport(anyhow::anyhow!("connection reset")).backpressure_reason(), Some("transport"));
    // Failures: a missing consumer queue is not a full one, and shutdown ends the loop.
    let unroutable = PublishError::Unroutable { exchange: "ex".into(), reply_code: 312, reply_text: "NO_ROUTE".into() };
    assert_eq!(unroutable.backpressure_reason(), None);
    assert_eq!(PublishError::ShutdownWhileBlocked { exchange: "ex".into(), retries: 3 }.backpressure_reason(), None);
}

#[tokio::test(start_paused = true)]
async fn test_publish_with_retry_ack_publishes_once() {
    let backpressure = PublishBackpressure::default();
    let (calls, attempt) = scripted_attempts(vec![Ok(())]);
    let start = tokio::time::Instant::now();

    let result = publish_with_retry(&backpressure, DataType::Artists, "ex", attempt).await;

    assert!(result.is_ok());
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert_eq!(start.elapsed(), Duration::ZERO, "an acked publish must not wait");
    assert_eq!(backpressure.snapshot(), BackpressureSnapshot::default(), "an acked publish is not backpressure");
}

#[tokio::test(start_paused = true)]
async fn test_publish_with_retry_nack_then_ack_retries_same_message_with_backoff() {
    let backpressure = PublishBackpressure::default();
    let (calls, attempt) = scripted_attempts(vec![nack(), nack(), nack(), Ok(())]);
    let start = tokio::time::Instant::now();

    let result = publish_with_retry(&backpressure, DataType::Artists, "ex", attempt).await;

    assert!(result.is_ok(), "a nack is backpressure, not a failure: {:?}", result.err());
    assert_eq!(calls.load(Ordering::SeqCst), 4, "the same message is retried until the broker acks it");
    assert_eq!(start.elapsed(), Duration::from_millis(500 + 1_000 + 2_000), "retries follow the backoff schedule");
    let snapshot = backpressure.snapshot();
    assert_eq!(snapshot.publish_nacks, 3);
    assert_eq!(snapshot.publish_retries, 3);
    assert_eq!(snapshot.publish_confirm_timeouts, 0);
    assert!(!snapshot.is_blocked(), "an acked retry clears the blocked state");
}

#[tokio::test(start_paused = true)]
async fn test_publish_with_retry_confirm_timeout_then_ack() {
    // Drive the real confirm path: the first confirm never resolves (broker under a resource
    // alarm), so await_confirm times out; the retry is acked.
    let backpressure = PublishBackpressure::default();
    let calls = std::sync::atomic::AtomicU32::new(0);
    let attempt = || {
        let call = calls.fetch_add(1, Ordering::SeqCst);
        async move {
            if call == 0 {
                MessageQueue::confirm_outcome("ex", std::future::pending::<lapin::Result<Confirmation>>()).await
            } else {
                MessageQueue::confirm_outcome("ex", async { Ok(Confirmation::Ack(None)) }).await
            }
        }
    };
    let start = tokio::time::Instant::now();

    let result = publish_with_retry(&backpressure, DataType::Labels, "ex", attempt).await;

    assert!(result.is_ok(), "a confirm timeout is backpressure, not a failure: {:?}", result.err());
    assert_eq!(calls.load(Ordering::SeqCst), 2);
    assert_eq!(start.elapsed(), PUBLISH_CONFIRM_TIMEOUT + PUBLISH_RETRY_INITIAL_BACKOFF);
    let snapshot = backpressure.snapshot();
    assert_eq!(snapshot.publish_confirm_timeouts, 1);
    assert_eq!(snapshot.publish_nacks, 0);
    assert_eq!(snapshot.publish_retries, 1);
    assert!(!snapshot.is_blocked());
}

#[tokio::test(start_paused = true)]
async fn test_publish_with_retry_nack_confirmation_is_retried() {
    // A real Nack confirmation (not just a scripted error) is classified as backpressure.
    let backpressure = PublishBackpressure::default();
    let calls = std::sync::atomic::AtomicU32::new(0);
    let attempt = || {
        let call = calls.fetch_add(1, Ordering::SeqCst);
        async move {
            let confirmation = if call == 0 { Confirmation::Nack(None) } else { Confirmation::Ack(None) };
            MessageQueue::confirm_outcome("ex", async move { Ok(confirmation) }).await
        }
    };

    let result = publish_with_retry(&backpressure, DataType::Masters, "ex", attempt).await;

    assert!(result.is_ok());
    assert_eq!(calls.load(Ordering::SeqCst), 2);
    assert_eq!(backpressure.snapshot().publish_nacks, 1);
}

#[tokio::test(start_paused = true)]
async fn test_publish_with_retry_transport_error_is_retried() {
    // A broker restart drops the channel; the retry reconnects and publishes the same message.
    let backpressure = PublishBackpressure::default();
    let (calls, attempt) = scripted_attempts(vec![Err(PublishError::Transport(anyhow::anyhow!("channel closed"))), Ok(())]);

    let result = publish_with_retry(&backpressure, DataType::Releases, "ex", attempt).await;

    assert!(result.is_ok());
    assert_eq!(calls.load(Ordering::SeqCst), 2);
    assert_eq!(backpressure.snapshot().publish_transport_errors, 1);
}

#[tokio::test(start_paused = true)]
async fn test_publish_with_retry_return_fails_without_retry() {
    // basic.return means no consumer queue is bound: waiting cannot fix it, so the file fails.
    let backpressure = PublishBackpressure::default();
    let unroutable = || Err(PublishError::Unroutable { exchange: "ex".into(), reply_code: 312, reply_text: "NO_ROUTE".into() });
    let (calls, attempt) = scripted_attempts(vec![unroutable()]);

    let result = publish_with_retry(&backpressure, DataType::Artists, "ex", attempt).await;

    assert!(matches!(result, Err(PublishError::Unroutable { reply_code: 312, .. })), "unexpected: {result:?}");
    assert_eq!(calls.load(Ordering::SeqCst), 1, "an unroutable publish must not be retried");
    assert_eq!(backpressure.snapshot(), BackpressureSnapshot::default());

    // The same holds after some backpressure: the return still fails, and the block clears.
    let (calls, attempt) = scripted_attempts(vec![nack(), unroutable()]);
    let result = publish_with_retry(&backpressure, DataType::Artists, "ex", attempt).await;
    assert!(matches!(result, Err(PublishError::Unroutable { .. })), "unexpected: {result:?}");
    assert_eq!(calls.load(Ordering::SeqCst), 2);
    assert!(!backpressure.snapshot().is_blocked());
}

#[tokio::test(start_paused = true)]
async fn test_publish_with_retry_reports_blocked_and_shutdown_mid_retry_exits_promptly() {
    let backpressure = Arc::new(PublishBackpressure::default());
    let calls = Arc::new(std::sync::atomic::AtomicU32::new(0));

    let task = tokio::spawn({
        let backpressure = backpressure.clone();
        let calls = calls.clone();
        async move {
            publish_with_retry(&backpressure, DataType::ReleaseGroups, "ex", || {
                calls.fetch_add(1, Ordering::SeqCst);
                std::future::ready(nack())
            })
            .await
        }
    });

    // Let the broker nack long enough to reach the 30s backoff cap.
    tokio::time::sleep(Duration::from_secs(120)).await;
    let snapshot = backpressure.snapshot();
    assert!(snapshot.is_blocked(), "a publish being retried must show as blocked on broker");
    assert_eq!(snapshot.blocked.len(), 1);
    let blocked = &snapshot.blocked[0];
    assert_eq!(blocked.data_type, DataType::ReleaseGroups);
    assert_eq!(blocked.last_reason, "nack");
    assert!(blocked.retries >= 7, "expected the backoff to have ramped to the cap, got {} retries", blocked.retries);
    assert!(blocked.blocked_for >= Duration::from_secs(60));
    assert!(!task.is_finished(), "the publish keeps retrying while shutdown is not requested");

    // Shutdown lands in the middle of a 30s backoff sleep and must cut it short.
    let attempts_before = calls.load(Ordering::SeqCst);
    let shutdown_at = tokio::time::Instant::now();
    backpressure.request_shutdown();
    let result = task.await.unwrap();

    assert_eq!(shutdown_at.elapsed(), Duration::ZERO, "shutdown must not wait out the backoff");
    assert!(matches!(result, Err(PublishError::ShutdownWhileBlocked { .. })), "unexpected: {result:?}");
    assert_eq!(calls.load(Ordering::SeqCst), attempts_before, "no further attempt after shutdown");
    assert!(!backpressure.snapshot().is_blocked(), "the blocked entry is cleared when the loop exits");
}

#[tokio::test(start_paused = true)]
async fn test_publish_with_retry_shutdown_interrupts_a_hung_retry_attempt() {
    // The retry attempt itself can hang (broker blocking the connection); shutdown must not
    // wait for it either.
    let backpressure = Arc::new(PublishBackpressure::default());
    let calls = Arc::new(std::sync::atomic::AtomicU32::new(0));

    let task = tokio::spawn({
        let backpressure = backpressure.clone();
        let calls = calls.clone();
        async move {
            publish_with_retry(&backpressure, DataType::Artists, "ex", || {
                let call = calls.fetch_add(1, Ordering::SeqCst);
                async move {
                    if call == 0 {
                        nack()
                    } else {
                        std::future::pending::<Result<(), PublishError>>().await
                    }
                }
            })
            .await
        }
    });

    // Past the first 0.5s backoff, inside the hung second attempt.
    tokio::time::sleep(Duration::from_secs(5)).await;
    assert_eq!(calls.load(Ordering::SeqCst), 2);
    backpressure.request_shutdown();

    let result = task.await.unwrap();
    assert!(matches!(result, Err(PublishError::ShutdownWhileBlocked { retries: 1, .. })), "unexpected: {result:?}");
    assert!(!backpressure.snapshot().is_blocked());
}

#[tokio::test(start_paused = true)]
async fn test_publish_with_retry_after_shutdown_first_attempt_still_runs() {
    // Files already publishing when SIGTERM arrives run to completion (cu2.44): an acked
    // first attempt still succeeds after shutdown...
    let backpressure = PublishBackpressure::default();
    backpressure.request_shutdown();
    let (calls, attempt) = scripted_attempts(vec![Ok(())]);
    assert!(publish_with_retry(&backpressure, DataType::Artists, "ex", attempt).await.is_ok());
    assert_eq!(calls.load(Ordering::SeqCst), 1);

    // ...but a pushed-back one stops at once instead of entering the retry loop.
    let (calls, attempt) = scripted_attempts(vec![nack()]);
    let start = tokio::time::Instant::now();
    let result = publish_with_retry(&backpressure, DataType::Artists, "ex", attempt).await;
    assert!(matches!(result, Err(PublishError::ShutdownWhileBlocked { retries: 0, .. })), "unexpected: {result:?}");
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert_eq!(start.elapsed(), Duration::ZERO);
    assert_eq!(backpressure.snapshot().publish_nacks, 1, "the nack is still counted");
}

#[tokio::test(start_paused = true)]
async fn test_publish_with_retry_dropped_future_clears_blocked_state() {
    // If the publisher task is aborted mid-retry, /health must not keep reporting the block.
    let backpressure = Arc::new(PublishBackpressure::default());
    let task = tokio::spawn({
        let backpressure = backpressure.clone();
        async move { publish_with_retry(&backpressure, DataType::Labels, "ex", || std::future::ready(nack())).await }
    });
    tokio::time::sleep(Duration::from_secs(2)).await;
    assert!(backpressure.snapshot().is_blocked());

    task.abort();
    let _ = task.await;
    assert!(!backpressure.snapshot().is_blocked());
}
