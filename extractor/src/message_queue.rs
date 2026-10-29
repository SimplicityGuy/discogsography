use anyhow::{Context, Result};
use lapin::{BasicProperties, Channel, Confirmation, Connection, ConnectionProperties, ExchangeKind, options::*, types::FieldTable};
use std::collections::HashMap;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;
use tokio::sync::RwLock;
use tokio::time::{Instant, sleep};
use tokio_util::sync::CancellationToken;
use tracing::{debug, error, info, warn};
use url::Url;

use async_trait::async_trait;

use crate::types::{DataMessage, DataType, ExtractionCompleteMessage, FileCompleteMessage, Message};

#[cfg(test)]
const DEFAULT_EXCHANGE_PREFIX: &str = crate::generated::catalog_contract::DEFAULT_DISCOGS_EXCHANGE_PREFIX;
const AMQP_EXCHANGE_TYPE: ExchangeKind = ExchangeKind::Fanout;

/// Deadline for a publisher-confirm to come back from the broker.
///
/// Publisher confirms are enabled (`confirm_select`), and awaiting the confirm
/// future had no timeout. When RabbitMQ trips a memory or `disk_free` alarm it
/// stops acking publishes while leaving the connection TCP-connected, so
/// `get_channel`'s reconnect path — which only fires on a DISCONNECTED channel —
/// never triggers. The publisher task then parks forever, the bounded
/// batch channel fills, the batcher blocks on `send().await`, and the whole
/// per-file pipeline wedges. The shutdown flag is only polled BETWEEN files, so
/// SIGTERM cannot break it and the container is SIGKILLed
/// (discogsography-rehd).
const PUBLISH_CONFIRM_TIMEOUT: Duration = Duration::from_secs(30);

/// Delay before the first retry of a publish the broker pushed back on.
pub const PUBLISH_RETRY_INITIAL_BACKOFF: Duration = Duration::from_millis(500);

/// Ceiling for the delay between retries of a publish the broker pushed back on.
pub const PUBLISH_RETRY_MAX_BACKOFF: Duration = Duration::from_secs(30);

/// Delay before retry number `retry` (1-based) of a pushed-back publish: 0.5s doubling to a
/// 30s cap (0.5, 1, 2, 4, 8, 16, 30, 30, ...).
pub fn publish_retry_backoff(retry: u32) -> Duration {
    let exponent = retry.saturating_sub(1).min(16); // guard against shl overflow
    PUBLISH_RETRY_INITIAL_BACKOFF.saturating_mul(1u32 << exponent).min(PUBLISH_RETRY_MAX_BACKOFF)
}

/// Why a single publish attempt did not deliver its message.
///
/// The split that matters is backpressure versus failure. A full `reject-publish` quorum
/// queue nacks, a broker under a resource alarm withholds the confirm, and a restarting
/// broker drops the channel: in all three the message can still be delivered later, so the
/// publish is retried in place and the bounded pipeline channels stall the parser behind it.
/// An unroutable message (`basic.return`) means no consumer queue is bound at all, which no
/// amount of waiting fixes, so it still fails the file (discogsography-5ow5).
#[derive(Debug, thiserror::Error)]
pub enum PublishError {
    #[error("Message to exchange '{exchange}' was returned as unroutable ({reply_code} {reply_text}) — no consumer queue is bound")]
    Unroutable { exchange: String, reply_code: u16, reply_text: String },
    #[error("Message to exchange '{exchange}' was not acknowledged by broker (nack)")]
    Nacked { exchange: String },
    #[error("Timed out after {0:?} waiting for publisher confirm")]
    ConfirmTimeout(Duration),
    #[error("AMQP transport error: {0:#}")]
    Transport(anyhow::Error),
    #[error("Shutdown requested while the publish to '{exchange}' was blocked on the broker ({retries} retries)")]
    ShutdownWhileBlocked { exchange: String, retries: u32 },
}

impl PublishError {
    /// The backpressure reason for an error worth retrying in place, or `None` when the
    /// error must fail the publish.
    pub fn backpressure_reason(&self) -> Option<&'static str> {
        match self {
            PublishError::Nacked { .. } => Some("nack"),
            PublishError::ConfirmTimeout(_) => Some("confirm_timeout"),
            PublishError::Transport(_) => Some("transport"),
            PublishError::Unroutable { .. } | PublishError::ShutdownWhileBlocked { .. } => None,
        }
    }
}

/// Decide whether a publisher confirm actually proves delivery.
///
/// A broker ack only proves the message was RECEIVED, not that it was ROUTED: a fanout
/// exchange with zero bound queues acks and drops. Publishing with `mandatory` makes the
/// broker return such a message, and `returned` carries that `basic.return` — which must
/// be treated as a failure so the file stays pending instead of being durably marked
/// Completed while every record was discarded.
///
/// Scope limit: `mandatory` only detects total unroutability. If one consumer has
/// declared and bound its queue but another has not, the message is routable and this
/// check passes — partial-consumer loss is out of scope here.
fn check_confirmation(exchange_name: &str, acked: bool, returned: Option<(u16, String)>) -> Result<(), PublishError> {
    if let Some((reply_code, reply_text)) = returned {
        return Err(PublishError::Unroutable { exchange: exchange_name.to_string(), reply_code, reply_text });
    }

    if !acked {
        return Err(PublishError::Nacked { exchange: exchange_name.to_string() });
    }

    Ok(())
}

/// One publish that is currently being retried against broker backpressure.
#[derive(Debug, Clone)]
struct BlockedPublish {
    data_type: DataType,
    since: Instant,
    retries: u32,
    last_reason: &'static str,
}

/// Per-data-type view of the publishes blocked on the broker right now.
#[derive(Debug, Clone, PartialEq)]
pub struct BlockedTypeSnapshot {
    pub data_type: DataType,
    pub blocked_for: Duration,
    pub retries: u32,
    pub last_reason: &'static str,
}

/// Point-in-time copy of the broker backpressure counters for `/health` and `/metrics`.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct BackpressureSnapshot {
    pub publish_nacks: u64,
    pub publish_confirm_timeouts: u64,
    pub publish_transport_errors: u64,
    pub publish_retries: u64,
    pub blocked: Vec<BlockedTypeSnapshot>,
}

impl BackpressureSnapshot {
    pub fn is_blocked(&self) -> bool {
        !self.blocked.is_empty()
    }
}

/// Process-wide broker backpressure state shared by every `MessageQueue`.
///
/// Holds the counters and the set of in-flight blocked publishes that `/health` reports, and
/// the shutdown token that ends a retry loop: without it a publish retried against a full
/// queue would keep SIGTERM waiting until Docker's SIGKILL (discogsography-5ow5).
#[derive(Debug, Default)]
pub struct PublishBackpressure {
    shutdown: CancellationToken,
    nacks: AtomicU64,
    confirm_timeouts: AtomicU64,
    transport_errors: AtomicU64,
    retries: AtomicU64,
    next_id: AtomicU64,
    blocked: parking_lot::Mutex<HashMap<u64, BlockedPublish>>,
}

impl PublishBackpressure {
    /// Stop retrying blocked publishes: every retry loop returns
    /// [`PublishError::ShutdownWhileBlocked`] promptly, so the file is left not Completed.
    pub fn request_shutdown(&self) {
        self.shutdown.cancel();
    }

    pub fn shutdown_requested(&self) -> bool {
        self.shutdown.is_cancelled()
    }

    pub fn snapshot(&self) -> BackpressureSnapshot {
        let mut by_type: HashMap<DataType, BlockedTypeSnapshot> = HashMap::new();
        for publish in self.blocked.lock().values() {
            let entry = BlockedTypeSnapshot {
                data_type: publish.data_type,
                blocked_for: publish.since.elapsed(),
                retries: publish.retries,
                last_reason: publish.last_reason,
            };
            // Two publishers blocked on one type: report the one blocked longest.
            match by_type.get(&publish.data_type) {
                Some(existing) if existing.blocked_for >= entry.blocked_for => {}
                _ => {
                    by_type.insert(publish.data_type, entry);
                }
            }
        }
        let mut blocked: Vec<BlockedTypeSnapshot> = by_type.into_values().collect();
        blocked.sort_by_key(|b| b.data_type.as_str());

        BackpressureSnapshot {
            publish_nacks: self.nacks.load(Ordering::Relaxed),
            publish_confirm_timeouts: self.confirm_timeouts.load(Ordering::Relaxed),
            publish_transport_errors: self.transport_errors.load(Ordering::Relaxed),
            publish_retries: self.retries.load(Ordering::Relaxed),
            blocked,
        }
    }

    fn count(&self, reason: &'static str) {
        let counter = match reason {
            "nack" => &self.nacks,
            "confirm_timeout" => &self.confirm_timeouts,
            _ => &self.transport_errors,
        };
        counter.fetch_add(1, Ordering::Relaxed);
    }

    fn mark_blocked(&self, data_type: DataType) -> BlockedGuard<'_> {
        let id = self.next_id.fetch_add(1, Ordering::Relaxed);
        self.blocked.lock().insert(id, BlockedPublish { data_type, since: Instant::now(), retries: 0, last_reason: "" });
        BlockedGuard { backpressure: self, id }
    }
}

/// Removes a blocked-publish entry when its retry loop ends by any path — success, failure,
/// shutdown, or the future being dropped — so `/health` never reports a stale block.
struct BlockedGuard<'a> {
    backpressure: &'a PublishBackpressure,
    id: u64,
}

impl BlockedGuard<'_> {
    fn update(&self, retries: u32, reason: &'static str) {
        if let Some(publish) = self.backpressure.blocked.lock().get_mut(&self.id) {
            publish.retries = retries;
            publish.last_reason = reason;
        }
    }
}

impl Drop for BlockedGuard<'_> {
    fn drop(&mut self) {
        self.backpressure.blocked.lock().remove(&self.id);
    }
}

/// Run one publish to completion, retrying it in place while the broker pushes back.
///
/// `attempt` publishes the same message once and reports how the broker answered. A nack, a
/// confirm timeout, or a transport error is backpressure: it is counted, the publish is marked
/// blocked for `/health`, and the same message is retried after [`publish_retry_backoff`]
/// for as long as shutdown is not requested. The caller does not return in the meantime, so
/// the bounded pipeline channels stall the batcher and parser behind it. A `basic.return`
/// fails immediately.
///
/// A shutdown ends the loop promptly with [`PublishError::ShutdownWhileBlocked`]: it is
/// checked after every pushed-back attempt, and it interrupts both the backoff sleep and any
/// retry attempt in flight. The first attempt is not interrupted, so files still publishing
/// normally when SIGTERM arrives keep running to completion (cu2.44).
pub async fn publish_with_retry<F, Fut>(
    backpressure: &PublishBackpressure,
    data_type: DataType,
    exchange: &str,
    mut attempt: F,
) -> Result<(), PublishError>
where
    F: FnMut() -> Fut,
    Fut: std::future::Future<Output = Result<(), PublishError>>,
{
    let shutdown = &backpressure.shutdown;
    let shutdown_error = |retries| PublishError::ShutdownWhileBlocked { exchange: exchange.to_string(), retries };
    let mut retries: u32 = 0;
    let mut blocked: Option<BlockedGuard<'_>> = None;

    loop {
        let result = if retries == 0 {
            attempt().await
        } else {
            tokio::select! {
                result = attempt() => result,
                _ = shutdown.cancelled() => return Err(shutdown_error(retries)),
            }
        };

        let err = match result {
            Ok(()) => {
                if retries > 0 {
                    info!("✅ Broker accepted publish to '{}' after {} retries — no longer blocked on broker", exchange, retries);
                }
                return Ok(());
            }
            Err(err) => err,
        };

        let Some(reason) = err.backpressure_reason() else {
            return Err(err);
        };
        backpressure.count(reason);

        if backpressure.shutdown_requested() {
            warn!("🛑 Shutdown requested while publish to '{}' is blocked on broker ({}) — abandoning file for rerun", exchange, err);
            return Err(shutdown_error(retries));
        }

        retries = retries.saturating_add(1);
        backpressure.retries.fetch_add(1, Ordering::Relaxed);
        blocked.get_or_insert_with(|| backpressure.mark_blocked(data_type)).update(retries, reason);

        let delay = publish_retry_backoff(retries);
        warn!("⏸️ Blocked on broker publishing {} to '{}' ({}): {} — retry {} in {:?}", data_type, exchange, reason, err, retries, delay);

        tokio::select! {
            _ = sleep(delay) => {}
            _ = shutdown.cancelled() => return Err(shutdown_error(retries)),
        }
    }
}

#[cfg_attr(feature = "test-support", mockall::automock)]
#[async_trait]
pub trait MessagePublisher: Send + Sync {
    async fn setup_exchange(&self, data_type: DataType) -> Result<()>;
    async fn publish(&self, message: Message, data_type: DataType) -> Result<()>;
    async fn publish_batch(&self, messages: Vec<DataMessage>, data_type: DataType) -> Result<()>;
    async fn send_file_complete(&self, data_type: DataType, file_name: &str, total_processed: u64) -> Result<()>;
    async fn send_extraction_complete(
        &self,
        version: &str,
        started_at: chrono::DateTime<chrono::Utc>,
        record_counts: std::collections::HashMap<String, u64>,
        data_types: &[DataType],
    ) -> Result<()>;
    async fn close(&self) -> Result<()>;
}

pub struct MessageQueue {
    connection: Arc<RwLock<Option<Connection>>>,
    channel: Arc<RwLock<Option<Channel>>>,
    reconnect_mutex: tokio::sync::Mutex<()>,
    url: String,
    max_retries: u32,
    exchange_prefix: String,
    backpressure: Arc<PublishBackpressure>,
}

impl MessageQueue {
    /// Build the fanout exchange name for a given data type (e.g. "discogsography-discogs-artists")
    fn exchange_name(&self, data_type: DataType) -> String {
        format!("{}-{}", self.exchange_prefix, data_type)
    }

    /// Connect. Publishes report backpressure into, and take shutdown from, the shared
    /// `backpressure` state that `/health` reads.
    pub async fn new(url: &str, max_retries: u32, exchange_prefix: &str, backpressure: Arc<PublishBackpressure>) -> Result<Self> {
        // Normalize the AMQP URL to handle trailing slash consistently with Python extractor
        let normalized_url = Self::normalize_amqp_url(url)?;

        let mq = Self {
            connection: Arc::new(RwLock::new(None)),
            channel: Arc::new(RwLock::new(None)),
            reconnect_mutex: tokio::sync::Mutex::new(()),
            url: normalized_url,
            max_retries,
            exchange_prefix: exchange_prefix.to_string(),
            backpressure,
        };

        mq.connect().await?;
        Ok(mq)
    }

    /// Normalize AMQP URL to ensure compatibility with Python extractor
    ///
    /// Handles the case where a trailing slash in the URL (e.g., amqp://host:5672/)
    /// should be interpreted as the default vhost "/" rather than an empty vhost.
    /// This matches the behavior of Python's aio-pika library.
    pub(crate) fn normalize_amqp_url(url: &str) -> Result<String> {
        let mut parsed_url = Url::parse(url).context("Failed to parse AMQP URL")?;

        // Get the path (which represents the vhost)
        let path = parsed_url.path();

        // If path is "/" (trailing slash with no vhost), it means default vhost
        // lapin interprets this as empty vhost, so we need to remove the trailing slash
        // to make it connect to the default vhost "/"
        if path == "/" {
            parsed_url.set_path("");
        }
        // If path is empty, lapin correctly uses default vhost
        // If path is something else (e.g., "/discogsography"), lapin uses that vhost

        Ok(parsed_url.to_string())
    }

    async fn connect(&self) -> Result<()> {
        let mut retry_count = 0;
        let mut backoff = Duration::from_secs(1);

        loop {
            match self.try_connect().await {
                Ok(_) => {
                    info!("✅ Successfully connected to AMQP broker");
                    return Ok(());
                }
                Err(e) => {
                    retry_count += 1;
                    if retry_count >= self.max_retries {
                        return Err(e).context("Failed to connect to AMQP broker after retries");
                    }
                    warn!("⚠️ Failed to connect to AMQP (attempt {}/{}): {}", retry_count, self.max_retries, e);
                    sleep(backoff).await;
                    backoff = (backoff * 2).min(Duration::from_secs(30));
                }
            }
        }
    }

    async fn try_connect(&self) -> Result<()> {
        let conn = Connection::connect(&self.url, ConnectionProperties::default()).await.context("Failed to establish AMQP connection")?;

        let channel = conn.create_channel().await.context("Failed to create AMQP channel")?;

        // Enable publisher confirms
        channel.confirm_select(ConfirmSelectOptions::default()).await.context("Failed to enable publisher confirms")?;

        *self.connection.write().await = Some(conn);
        *self.channel.write().await = Some(channel);

        Ok(())
    }

    fn message_properties() -> BasicProperties {
        BasicProperties::default()
            .with_content_type("application/json".into())
            .with_content_encoding("UTF-8".into())
            .with_delivery_mode(2) // Persistent
    }

    /// Await a publisher-confirm under a bounded deadline.
    ///
    /// A stalled broker (resource alarm / flow control) keeps the connection up
    /// while withholding acks, so an unbounded await never resolves. Timing out
    /// turns the wedge into an error the caller can count and retry, instead of
    /// parking the whole pipeline (discogsography-rehd); `publish_with_retry`
    /// retries it as backpressure (discogsography-5ow5).
    async fn await_confirm<F>(confirm_future: F) -> Result<Confirmation, PublishError>
    where
        F: std::future::Future<Output = lapin::Result<Confirmation>>,
    {
        match tokio::time::timeout(PUBLISH_CONFIRM_TIMEOUT, confirm_future).await {
            Ok(result) => result.map_err(|e| PublishError::Transport(anyhow::Error::new(e).context("Failed to confirm message delivery"))),
            Err(_) => {
                warn!("⚠️ Publisher confirm timed out after {:?} — broker may be under a resource alarm", PUBLISH_CONFIRM_TIMEOUT);
                Err(PublishError::ConfirmTimeout(PUBLISH_CONFIRM_TIMEOUT))
            }
        }
    }

    /// Turn a publisher confirm into a publish outcome: ack and routed, nacked, timed out,
    /// or returned as unroutable.
    async fn confirm_outcome<F>(exchange_name: &str, confirm_future: F) -> Result<(), PublishError>
    where
        F: std::future::Future<Output = lapin::Result<Confirmation>>,
    {
        let confirm = Self::await_confirm(confirm_future).await?;

        let acked = confirm.is_ack();
        let returned = confirm.take_message().map(|returned| (returned.reply_code, returned.reply_text.to_string()));

        check_confirmation(exchange_name, acked, returned)
    }

    /// Publish options for every extractor publish.
    ///
    /// `mandatory` is required for correctness, not politeness: a publisher confirm on a
    /// fanout exchange with zero bound queues still returns `basic.ack`, so without this
    /// flag the broker silently drops the message and the extractor records the file as
    /// Completed. With `mandatory` set, an unroutable message comes back as a
    /// `basic.return` attached to the confirmation and is treated as a delivery failure.
    fn publish_options() -> BasicPublishOptions {
        BasicPublishOptions { mandatory: true, ..Default::default() }
    }

    /// Publish one already-serialized payload and require both a broker ack and proof
    /// that the message was routable, retrying the same payload in place while the broker
    /// pushes back (see [`publish_with_retry`]).
    async fn publish_payload(&self, data_type: DataType, exchange_name: &str, payload: &[u8]) -> Result<()> {
        publish_with_retry(&self.backpressure, data_type, exchange_name, || self.publish_once(exchange_name, payload)).await?;
        Ok(())
    }

    /// A single publish attempt. The channel is fetched per attempt so a retry after a broker
    /// restart reconnects instead of reusing the dead channel. `basic_publish` shares the
    /// confirm deadline: a connection blocked by a resource alarm can stall the write itself.
    async fn publish_once(&self, exchange_name: &str, payload: &[u8]) -> Result<(), PublishError> {
        let channel = self.get_channel().await.map_err(PublishError::Transport)?;

        let publish = tokio::time::timeout(
            PUBLISH_CONFIRM_TIMEOUT,
            channel.basic_publish(exchange_name.into(), "".into(), Self::publish_options(), payload, Self::message_properties()),
        )
        .await
        .map_err(|_| PublishError::ConfirmTimeout(PUBLISH_CONFIRM_TIMEOUT))?
        .map_err(|e| PublishError::Transport(anyhow::Error::new(e).context("Failed to publish message")))?;

        Self::confirm_outcome(exchange_name, publish).await
    }

    async fn get_channel(&self) -> Result<Channel> {
        // Fast path: check if channel is connected under read lock
        {
            let channel_guard = self.channel.read().await;
            if let Some(channel) = &*channel_guard
                && channel.status().connected()
            {
                return Ok(channel.clone());
            }
        }

        // Slow path: serialize reconnection attempts to prevent multiple
        // concurrent callers from racing to create separate connections.
        let _reconnect_guard = self.reconnect_mutex.lock().await;

        // Re-check after acquiring the mutex — another caller may have
        // already reconnected while we were waiting.
        {
            let channel_guard = self.channel.read().await;
            if let Some(channel) = &*channel_guard
                && channel.status().connected()
            {
                return Ok(channel.clone());
            }
        }

        warn!("⚠️ AMQP channel lost, attempting to reconnect...");
        self.connect().await?;

        self.channel.read().await.as_ref().cloned().ok_or_else(|| anyhow::anyhow!("Failed to get channel after reconnection"))
    }
}

#[async_trait]
impl MessagePublisher for MessageQueue {
    async fn setup_exchange(&self, data_type: DataType) -> Result<()> {
        let channel = self.get_channel().await?;
        let exchange_name = self.exchange_name(data_type);

        channel
            .exchange_declare(
                exchange_name.as_str().into(),
                AMQP_EXCHANGE_TYPE,
                ExchangeDeclareOptions { durable: true, auto_delete: false, ..Default::default() },
                FieldTable::default(),
            )
            .await
            .context(format!("Failed to declare fanout exchange for {}", data_type))?;

        debug!("✅ Declared fanout exchange: {}", exchange_name);

        Ok(())
    }

    async fn publish(&self, message: Message, data_type: DataType) -> Result<()> {
        let exchange_name = self.exchange_name(data_type);
        let payload = serde_json::to_vec(&message).context("Failed to serialize message")?;

        self.publish_payload(data_type, &exchange_name, &payload).await
    }

    async fn publish_batch(&self, messages: Vec<DataMessage>, data_type: DataType) -> Result<()> {
        let exchange_name = self.exchange_name(data_type);

        for message in messages {
            let payload = serde_json::to_vec(&Message::Data(message)).context("Failed to serialize message")?;

            self.publish_payload(data_type, &exchange_name, &payload).await?;
        }

        Ok(())
    }

    async fn send_file_complete(&self, data_type: DataType, file_name: &str, total_processed: u64) -> Result<()> {
        let message =
            FileCompleteMessage { data_type: data_type.to_string(), timestamp: chrono::Utc::now(), total_processed, file: file_name.to_string() };

        self.publish(Message::FileComplete(message), data_type).await?;

        info!("🎉 File processing complete for {}! Total records processed: {}", data_type, total_processed);

        Ok(())
    }

    async fn send_extraction_complete(
        &self,
        version: &str,
        started_at: chrono::DateTime<chrono::Utc>,
        record_counts: std::collections::HashMap<String, u64>,
        data_types: &[DataType],
    ) -> Result<()> {
        let message = ExtractionCompleteMessage { version: version.to_string(), timestamp: chrono::Utc::now(), started_at, record_counts };

        // Publish to specified data type exchanges so every consumer queue receives it
        // Attempt all exchanges before returning, so a single failure doesn't prevent
        // other consumers from receiving the signal
        let mut errors = Vec::new();
        for data_type in data_types {
            if let Err(e) = self.publish(Message::ExtractionComplete(message.clone()), *data_type).await {
                error!("❌ Failed to send extraction_complete to {}: {}", data_type, e);
                errors.push(format!("{}: {}", data_type, e));
            }
        }

        if errors.is_empty() {
            info!("🏁 Extraction complete message sent to all {} exchanges (version: {})", data_types.len(), version,);
        } else {
            let succeeded = data_types.len() - errors.len();
            warn!("⚠️ Extraction complete sent to {}/{} exchanges (version: {})", succeeded, data_types.len(), version,);
            return Err(anyhow::anyhow!("Failed to send extraction_complete to {} exchange(s): {}", errors.len(), errors.join("; ")));
        }

        Ok(())
    }

    async fn close(&self) -> Result<()> {
        // Best-effort on both halves: a channel-close error (typical when the
        // broker already dropped the connection) must not skip the connection
        // close. Every call site except one already treats close() as
        // best-effort (`let _ = mq.close().await;`); make the implementation
        // match that contract instead of early-returning via `?` and leaving
        // the connection open.
        if let Some(channel) = self.channel.write().await.take()
            && let Err(e) = channel.close(200, "Normal shutdown".into()).await
        {
            warn!("⚠️ Failed to close AMQP channel cleanly: {}", e);
        }

        if let Some(conn) = self.connection.write().await.take()
            && let Err(e) = conn.close(200, "Normal shutdown".into()).await
        {
            warn!("⚠️ Failed to close AMQP connection cleanly: {}", e);
        }

        info!("🔌 AMQP connection closed");
        Ok(())
    }
}

#[cfg(test)]
#[path = "tests/message_queue_tests.rs"]
mod tests;
