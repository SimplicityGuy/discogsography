//! Broker integration tests for in-place publish retry (discogsography-5ow5).
//!
//! These run against a real RabbitMQ and are `#[ignore]`d so a plain `cargo test` never needs
//! one. `just extractor-test-broker` starts the scratch broker in `tests/broker/` (rabbitmq
//! 4.4.0 with the homelab config), runs them, and tears it down. To run them by hand:
//!
//! ```sh
//! docker compose -f extractor/tests/broker/compose.yaml up -d --wait
//! EXTRACTOR_IT_AMQP_URL=amqp://extractor-it:extractor-it@127.0.0.1:35672/%2F \
//! EXTRACTOR_IT_MGMT_URL=http://127.0.0.1:45672 \
//!   cargo test --manifest-path extractor/Cargo.toml --test broker_backpressure_test -- --ignored --test-threads=1
//! docker compose -f extractor/tests/broker/compose.yaml down -v
//! ```
//!
//! Each test declares the consumer queue shape brainzgraphinator uses — a fanout exchange, a
//! quorum queue with `x-dead-letter-exchange` and `x-delivery-limit: 20`, and a classic DLQ —
//! and caps it with a small `overflow: reject-publish` policy, so a full queue nacks.

use extractor::message_queue::{MessagePublisher, MessageQueue, PublishBackpressure, PublishError};
use extractor::types::{DataMessage, DataType, Message};
use futures::StreamExt;
use lapin::options::{
    BasicAckOptions, BasicConsumeOptions, BasicQosOptions, ExchangeDeclareOptions, ExchangeDeleteOptions, QueueBindOptions, QueueDeclareOptions,
    QueueDeleteOptions,
};
use lapin::types::{AMQPValue, FieldTable};
use lapin::{Channel, Connection, ConnectionProperties, ExchangeKind};
use std::collections::BTreeMap;
use std::sync::Arc;
use std::time::Duration;

/// Small cap so the queue fills after a few dozen ~4 KiB messages.
const CAP_BYTES: u64 = 128 * 1024;
const RECORD_COUNT: usize = 200;
const BATCH_SIZE: usize = 25;

struct Broker {
    amqp_url: String,
    mgmt_url: String,
}

fn broker() -> Broker {
    let amqp_url = std::env::var("EXTRACTOR_IT_AMQP_URL").expect("set EXTRACTOR_IT_AMQP_URL (see the module docs)");
    let mgmt_url = std::env::var("EXTRACTOR_IT_MGMT_URL").expect("set EXTRACTOR_IT_MGMT_URL (see the module docs)");
    Broker { amqp_url, mgmt_url }
}

/// Names for one test's exchange, queue, DLX and DLQ, unique per run.
struct Topology {
    prefix: String,
    exchange: String,
    queue: String,
    dlx: String,
    dlq: String,
    policy: String,
}

impl Topology {
    fn new(test: &str) -> Self {
        let nonce = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos();
        let prefix = format!("it5ow5-{test}-{nonce}");
        Self {
            exchange: format!("{prefix}-{}", DataType::Artists),
            queue: format!("{prefix}-consumer-artists"),
            dlx: format!("{prefix}-consumer-artists.dlx"),
            dlq: format!("{prefix}-consumer-artists.dlq"),
            policy: format!("{prefix}-cap"),
            prefix,
        }
    }
}

async fn admin_channel(broker: &Broker) -> (Connection, Channel) {
    let conn = Connection::connect(&broker.amqp_url, ConnectionProperties::default()).await.expect("connect to the test broker");
    let channel = conn.create_channel().await.unwrap();
    (conn, channel)
}

/// Apply a reject-publish cap to the test queue, at a higher priority than the broker-wide
/// homelab-quorum-cap so it wins (RabbitMQ applies only the highest-priority matching policy).
async fn put_cap_policy(broker: &Broker, topology: &Topology) {
    let body = serde_json::json!({
        "pattern": format!("^{}$", regex::escape(&topology.queue)),
        "apply-to": "quorum_queues",
        "priority": 10,
        "definition": {"max-length-bytes": CAP_BYTES, "overflow": "reject-publish"},
    });
    let response = reqwest::Client::new()
        .put(format!("{}/api/policies/%2F/{}", broker.mgmt_url, topology.policy))
        .basic_auth("extractor-it", Some("extractor-it"))
        .json(&body)
        .send()
        .await
        .expect("management API reachable");
    assert!(response.status().is_success(), "policy PUT failed: {}", response.status());
}

async fn delete_cap_policy(broker: &Broker, topology: &Topology) {
    let _ = reqwest::Client::new()
        .delete(format!("{}/api/policies/%2F/{}", broker.mgmt_url, topology.policy))
        .basic_auth("extractor-it", Some("extractor-it"))
        .send()
        .await;
}

/// Declare the brainzgraphinator queue shape and bind it to the extractor's exchange.
async fn declare_consumer_queue(channel: &Channel, topology: &Topology) {
    let durable_exchange = ExchangeDeclareOptions { durable: true, ..Default::default() };
    channel
        .exchange_declare(topology.exchange.as_str().into(), ExchangeKind::Fanout, durable_exchange, FieldTable::default())
        .await
        .unwrap();
    channel
        .exchange_declare(topology.dlx.as_str().into(), ExchangeKind::Fanout, durable_exchange, FieldTable::default())
        .await
        .unwrap();

    let mut dlq_args = FieldTable::default();
    dlq_args.insert("x-queue-type".into(), AMQPValue::LongString("classic".into()));
    channel
        .queue_declare(topology.dlq.as_str().into(), QueueDeclareOptions { durable: true, ..Default::default() }, dlq_args)
        .await
        .unwrap();
    channel
        .queue_bind(topology.dlq.as_str().into(), topology.dlx.as_str().into(), "".into(), QueueBindOptions::default(), FieldTable::default())
        .await
        .unwrap();

    let mut args = FieldTable::default();
    args.insert("x-queue-type".into(), AMQPValue::LongString("quorum".into()));
    args.insert("x-dead-letter-exchange".into(), AMQPValue::LongString(topology.dlx.as_str().into()));
    args.insert("x-delivery-limit".into(), AMQPValue::LongInt(20));
    channel
        .queue_declare(topology.queue.as_str().into(), QueueDeclareOptions { durable: true, ..Default::default() }, args)
        .await
        .unwrap();
    channel
        .queue_bind(topology.queue.as_str().into(), topology.exchange.as_str().into(), "".into(), QueueBindOptions::default(), FieldTable::default())
        .await
        .unwrap();
}

async fn teardown(broker: &Broker, channel: &Channel, topology: &Topology) {
    for queue in [&topology.queue, &topology.dlq] {
        let _ = channel.queue_delete(queue.as_str().into(), QueueDeleteOptions::default()).await;
    }
    for exchange in [&topology.exchange, &topology.dlx] {
        let _ = channel.exchange_delete(exchange.as_str().into(), ExchangeDeleteOptions::default()).await;
    }
    delete_cap_policy(broker, topology).await;
}

async fn message_count(channel: &Channel, queue: &str) -> u32 {
    let passive = QueueDeclareOptions { passive: true, ..Default::default() };
    channel.queue_declare(queue.into(), passive, FieldTable::default()).await.unwrap().message_count()
}

fn record(id: usize) -> DataMessage {
    // ~4 KiB per message so the 128 KiB cap is reached after about 30 messages.
    DataMessage {
        id: id.to_string(),
        sha256: format!("sha-{id}"),
        data: serde_json::json!({"name": format!("Artist {id}"), "profile": "x".repeat(4096)}),
        raw_xml: None,
    }
}

async fn wait_until(what: &str, timeout: Duration, mut condition: impl FnMut() -> bool) {
    tokio::time::timeout(timeout, async {
        while !condition() {
            tokio::time::sleep(Duration::from_millis(50)).await;
        }
    })
    .await
    .unwrap_or_else(|_| panic!("timed out waiting for {what}"));
}

/// The extractor's publisher, held by a full reject-publish quorum queue with no consumer,
/// delivers every message exactly once — including `file_complete` — once a consumer drains
/// the queue, and nothing is dead-lettered.
#[tokio::test]
#[ignore = "needs a RabbitMQ broker: just extractor-test-broker"]
async fn test_full_reject_publish_queue_is_backpressure_and_every_message_arrives_once() {
    let broker = broker();
    let topology = Topology::new("drain");
    let (_admin_conn, admin) = admin_channel(&broker).await;
    put_cap_policy(&broker, &topology).await;
    declare_consumer_queue(&admin, &topology).await;

    let backpressure = Arc::new(PublishBackpressure::default());
    let mq = Arc::new(MessageQueue::new(&broker.amqp_url, 3, &topology.prefix, backpressure.clone()).await.unwrap());
    mq.setup_exchange(DataType::Artists).await.unwrap();

    // Publish the "file" the way message_publisher does: batches, then file_complete.
    let publisher = tokio::spawn({
        let mq = mq.clone();
        async move {
            let records: Vec<DataMessage> = (0..RECORD_COUNT).map(record).collect();
            for batch in records.chunks(BATCH_SIZE) {
                mq.publish_batch(batch.to_vec(), DataType::Artists).await?;
            }
            mq.send_file_complete(DataType::Artists, "discogs_20260101_artists.xml.gz", RECORD_COUNT as u64).await
        }
    });

    // No consumer yet: the queue fills to the cap and the broker starts nacking.
    wait_until("the publisher to be blocked on broker", Duration::from_secs(60), || {
        let snapshot = backpressure.snapshot();
        snapshot.is_blocked() && snapshot.publish_nacks >= 3
    })
    .await;
    assert!(!publisher.is_finished(), "a full queue must hold the publisher, not fail it");
    let held = message_count(&admin, &topology.queue).await;
    assert!(held > 0 && (held as usize) < RECORD_COUNT, "queue should be capped part-way, holds {held}");
    assert_eq!(message_count(&admin, &topology.dlq).await, 0, "reject-publish must not dead-letter");

    // A consumer appears and drains the queue.
    let consumer_conn = Connection::connect(&broker.amqp_url, ConnectionProperties::default()).await.unwrap();
    let consumer_channel = consumer_conn.create_channel().await.unwrap();
    consumer_channel.basic_qos(50, BasicQosOptions::default()).await.unwrap();
    let mut consumer = consumer_channel
        .basic_consume(topology.queue.as_str().into(), "it5ow5".into(), BasicConsumeOptions::default(), FieldTable::default())
        .await
        .unwrap();

    let mut data_ids: BTreeMap<String, u32> = BTreeMap::new();
    let mut file_completes = 0;
    let drain = tokio::time::timeout(Duration::from_secs(120), async {
        while data_ids.len() < RECORD_COUNT || file_completes == 0 {
            let delivery = consumer.next().await.expect("consumer stream ended").expect("delivery error");
            match serde_json::from_slice::<Message>(&delivery.data).expect("extractor message JSON") {
                Message::Data(message) => *data_ids.entry(message.id).or_default() += 1,
                Message::FileComplete(_) => file_completes += 1,
                Message::ExtractionComplete(_) => panic!("unexpected extraction_complete"),
            }
            delivery.acker.ack(BasicAckOptions::default()).await.unwrap();
        }
    })
    .await;
    assert!(drain.is_ok(), "timed out draining: {} of {RECORD_COUNT} records, {file_completes} file_complete", data_ids.len());

    let published = tokio::time::timeout(Duration::from_secs(60), publisher).await.expect("publisher should finish once drained").unwrap();
    assert!(published.is_ok(), "the file must complete once the broker accepts again: {:?}", published.err());

    // Anything still in flight (a duplicate would arrive now) — give it a moment, then count.
    while let Ok(Some(Ok(delivery))) = tokio::time::timeout(Duration::from_secs(2), consumer.next()).await {
        match serde_json::from_slice::<Message>(&delivery.data).unwrap() {
            Message::Data(message) => *data_ids.entry(message.id).or_default() += 1,
            Message::FileComplete(_) => file_completes += 1,
            Message::ExtractionComplete(_) => panic!("unexpected extraction_complete"),
        }
        delivery.acker.ack(BasicAckOptions::default()).await.unwrap();
    }

    let missing: Vec<usize> = (0..RECORD_COUNT).filter(|id| !data_ids.contains_key(&id.to_string())).collect();
    let duplicated: Vec<(&String, &u32)> = data_ids.iter().filter(|(_, n)| **n > 1).collect();
    assert!(missing.is_empty(), "missing records: {missing:?}");
    assert!(duplicated.is_empty(), "duplicated records: {duplicated:?}");
    assert_eq!(file_completes, 1, "file_complete must arrive exactly once");
    assert_eq!(message_count(&admin, &topology.dlq).await, 0, "nothing may be dead-lettered");

    let snapshot = backpressure.snapshot();
    assert!(snapshot.publish_nacks >= 3, "the broker should have nacked: {snapshot:?}");
    assert_eq!(snapshot.publish_retries, snapshot.publish_nacks + snapshot.publish_confirm_timeouts + snapshot.publish_transport_errors);
    assert!(!snapshot.is_blocked(), "the block clears once the broker accepts");
    eprintln!(
        "drained {RECORD_COUNT} records + file_complete exactly once; queue held {held} at the cap; {} nacks, {} retries, 0 dead-lettered",
        snapshot.publish_nacks, snapshot.publish_retries
    );

    let _ = mq.close().await;
    let _ = consumer_conn.close(200, "done".into()).await;
    teardown(&broker, &admin, &topology).await;
}

/// SIGTERM while the publisher is blocked on a full queue ends the retry loop promptly.
#[tokio::test]
#[ignore = "needs a RabbitMQ broker: just extractor-test-broker"]
async fn test_shutdown_while_blocked_on_full_queue_exits_promptly() {
    let broker = broker();
    let topology = Topology::new("shutdown");
    let (_admin_conn, admin) = admin_channel(&broker).await;
    put_cap_policy(&broker, &topology).await;
    declare_consumer_queue(&admin, &topology).await;

    let backpressure = Arc::new(PublishBackpressure::default());
    let mq = Arc::new(MessageQueue::new(&broker.amqp_url, 3, &topology.prefix, backpressure.clone()).await.unwrap());
    mq.setup_exchange(DataType::Artists).await.unwrap();

    let publisher = tokio::spawn({
        let mq = mq.clone();
        async move { mq.publish_batch((0..RECORD_COUNT).map(record).collect(), DataType::Artists).await }
    });
    wait_until("the publisher to be blocked on broker", Duration::from_secs(60), || backpressure.snapshot().is_blocked()).await;
    // Let the backoff ramp up so shutdown lands inside a multi-second sleep.
    tokio::time::sleep(Duration::from_secs(4)).await;

    let started = std::time::Instant::now();
    backpressure.request_shutdown();
    let result = tokio::time::timeout(Duration::from_secs(2), publisher)
        .await
        .expect("shutdown must end the retry loop promptly")
        .unwrap();

    let err = result.expect_err("an interrupted publish must not report success");
    assert!(matches!(err.downcast_ref::<PublishError>(), Some(PublishError::ShutdownWhileBlocked { .. })), "unexpected error: {err:#}");
    assert!(started.elapsed() < Duration::from_secs(1), "took {:?}", started.elapsed());
    assert!(!backpressure.snapshot().is_blocked());
    assert_eq!(message_count(&admin, &topology.dlq).await, 0);

    let _ = mq.close().await;
    teardown(&broker, &admin, &topology).await;
}

/// An unroutable publish (no consumer queue bound) still fails at once instead of retrying.
#[tokio::test]
#[ignore = "needs a RabbitMQ broker: just extractor-test-broker"]
async fn test_unroutable_publish_fails_without_retry() {
    let broker = broker();
    let topology = Topology::new("unroutable");
    let (_admin_conn, admin) = admin_channel(&broker).await;

    let backpressure = Arc::new(PublishBackpressure::default());
    let mq = MessageQueue::new(&broker.amqp_url, 3, &topology.prefix, backpressure.clone()).await.unwrap();
    mq.setup_exchange(DataType::Artists).await.unwrap(); // exchange with no queue bound

    let result = tokio::time::timeout(Duration::from_secs(10), mq.publish_batch(vec![record(1)], DataType::Artists))
        .await
        .expect("must not retry");

    let err = result.expect_err("an unroutable message must fail the publish");
    assert!(matches!(err.downcast_ref::<PublishError>(), Some(PublishError::Unroutable { reply_code: 312, .. })), "unexpected error: {err:#}");
    assert_eq!(backpressure.snapshot().publish_retries, 0);

    let _ = mq.close().await;
    teardown(&broker, &admin, &topology).await;
}

/// A broker restart while the publisher is blocked on a full queue is retried through as
/// backpressure: the publisher reconnects, keeps retrying, and completes once a consumer drains
/// the queue, with nothing lost or dead-lettered. Needs `EXTRACTOR_IT_BROKER_RESTART_CMD` (a
/// shell command that restarts the test broker); `just extractor-test-broker` sets it.
#[tokio::test]
#[ignore = "needs a RabbitMQ broker: just extractor-test-broker"]
async fn test_broker_restart_while_blocked_is_retried_through() {
    let Ok(restart_cmd) = std::env::var("EXTRACTOR_IT_BROKER_RESTART_CMD") else {
        eprintln!("skipping: EXTRACTOR_IT_BROKER_RESTART_CMD is not set");
        return;
    };
    let broker = broker();
    let topology = Topology::new("restart");
    let (admin_conn, admin) = admin_channel(&broker).await;
    put_cap_policy(&broker, &topology).await;
    declare_consumer_queue(&admin, &topology).await;
    drop(admin);
    drop(admin_conn);

    let backpressure = Arc::new(PublishBackpressure::default());
    let mq = Arc::new(MessageQueue::new(&broker.amqp_url, 3, &topology.prefix, backpressure.clone()).await.unwrap());
    mq.setup_exchange(DataType::Artists).await.unwrap();

    let publisher = tokio::spawn({
        let mq = mq.clone();
        async move {
            let records: Vec<DataMessage> = (0..RECORD_COUNT).map(record).collect();
            for batch in records.chunks(BATCH_SIZE) {
                mq.publish_batch(batch.to_vec(), DataType::Artists).await?;
            }
            mq.send_file_complete(DataType::Artists, "discogs_20260101_artists.xml.gz", RECORD_COUNT as u64).await
        }
    });
    wait_until("the publisher to be blocked on broker", Duration::from_secs(60), || backpressure.snapshot().is_blocked()).await;

    let status = tokio::process::Command::new("sh").arg("-c").arg(&restart_cmd).status().await.expect("run the restart command");
    assert!(status.success(), "broker restart command failed: {status}");

    // The publisher rides out the restart (transport errors), then is nacked again by the
    // still-full queue: it never fails the file.
    let restarted_nacks = backpressure.snapshot().publish_nacks;
    wait_until("the publisher to reconnect and be nacked again", Duration::from_secs(120), || {
        let snapshot = backpressure.snapshot();
        snapshot.publish_transport_errors > 0 && snapshot.publish_nacks > restarted_nacks
    })
    .await;
    assert!(!publisher.is_finished(), "a broker restart must not fail the file");

    let (_admin_conn, admin) = admin_channel(&broker).await;
    let consumer_conn = Connection::connect(&broker.amqp_url, ConnectionProperties::default()).await.unwrap();
    let consumer_channel = consumer_conn.create_channel().await.unwrap();
    consumer_channel.basic_qos(50, BasicQosOptions::default()).await.unwrap();
    let mut consumer = consumer_channel
        .basic_consume(topology.queue.as_str().into(), "it5ow5".into(), BasicConsumeOptions::default(), FieldTable::default())
        .await
        .unwrap();

    let mut data_ids: BTreeMap<String, u32> = BTreeMap::new();
    let mut file_completes = 0;
    let published = tokio::time::timeout(Duration::from_secs(180), async {
        let mut publisher = publisher;
        loop {
            tokio::select! {
                delivery = consumer.next() => {
                    let delivery = delivery.expect("consumer stream ended").expect("delivery error");
                    match serde_json::from_slice::<Message>(&delivery.data).unwrap() {
                        Message::Data(message) => *data_ids.entry(message.id).or_default() += 1,
                        Message::FileComplete(_) => file_completes += 1,
                        Message::ExtractionComplete(_) => panic!("unexpected extraction_complete"),
                    }
                    delivery.acker.ack(BasicAckOptions::default()).await.unwrap();
                }
                result = &mut publisher => break result.unwrap(),
            }
        }
    })
    .await
    .expect("publisher should finish once drained");
    assert!(published.is_ok(), "the file must complete after the restart: {:?}", published.err());

    while let Ok(Some(Ok(delivery))) = tokio::time::timeout(Duration::from_secs(2), consumer.next()).await {
        match serde_json::from_slice::<Message>(&delivery.data).unwrap() {
            Message::Data(message) => *data_ids.entry(message.id).or_default() += 1,
            Message::FileComplete(_) => file_completes += 1,
            Message::ExtractionComplete(_) => panic!("unexpected extraction_complete"),
        }
        delivery.acker.ack(BasicAckOptions::default()).await.unwrap();
    }

    let missing: Vec<usize> = (0..RECORD_COUNT).filter(|id| !data_ids.contains_key(&id.to_string())).collect();
    assert!(missing.is_empty(), "missing records: {missing:?}");
    assert!(file_completes >= 1, "file_complete must arrive");
    assert_eq!(message_count(&admin, &topology.dlq).await, 0, "nothing may be dead-lettered");
    // A publish in flight when the connection dropped may have been enqueued without its ack
    // reaching us; retrying it is at-least-once, which the consumers' sha256 upserts absorb.
    let duplicates: u32 = data_ids.values().map(|n| n - 1).sum::<u32>() + (file_completes - 1);
    let snapshot = backpressure.snapshot();
    eprintln!(
        "after restart: {RECORD_COUNT} records delivered, {duplicates} duplicate(s); {} nacks, {} transport errors, {} retries, 0 dead-lettered",
        snapshot.publish_nacks, snapshot.publish_transport_errors, snapshot.publish_retries
    );
    assert!(duplicates <= 1, "at most the one in-flight message may be redelivered, got {duplicates}");

    let _ = mq.close().await;
    let _ = consumer_conn.close(200, "done".into()).await;
    teardown(&broker, &admin, &topology).await;
}
