use anyhow::{Context, Result};
// use futures::StreamExt; // Not needed for current implementation
use lapin::{BasicProperties, Channel, Connection, ConnectionProperties, ExchangeKind, options::*, types::FieldTable};
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::RwLock;
use tokio::time::sleep;
use tracing::{debug, info, warn};
use url::Url;

use crate::types::{DataMessage, DataType, FileCompleteMessage, Message};

const AMQP_EXCHANGE: &str = "discogsography-exchange";
const AMQP_EXCHANGE_TYPE: ExchangeKind = ExchangeKind::Topic;
const AMQP_QUEUE_PREFIX_GRAPHINATOR: &str = "discogsography-graphinator";
const AMQP_QUEUE_PREFIX_TABLEINATOR: &str = "discogsography-tableinator";

pub struct MessageQueue {
    connection: Arc<RwLock<Option<Connection>>>,
    channel: Arc<RwLock<Option<Channel>>>,
    url: String,
    max_retries: u32,
}

impl MessageQueue {
    pub async fn new(url: &str, max_retries: u32) -> Result<Self> {
        // Normalize the AMQP URL to handle trailing slash consistently with Python extractor
        let normalized_url = Self::normalize_amqp_url(url)?;

        let mq = Self { connection: Arc::new(RwLock::new(None)), channel: Arc::new(RwLock::new(None)), url: normalized_url, max_retries };

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
        let conn = Connection::connect(
            &self.url,
            ConnectionProperties::default().with_connection_name("rust-extractor".into()),
            // Note: heartbeat is configured differently in newer lapin versions
        )
        .await
        .context("Failed to establish AMQP connection")?;

        let channel = conn.create_channel().await.context("Failed to create AMQP channel")?;

        // Enable publisher confirms
        channel.confirm_select(ConfirmSelectOptions::default()).await.context("Failed to enable publisher confirms")?;

        // Set QoS
        channel.basic_qos(100, BasicQosOptions::default()).await.context("Failed to set QoS")?;

        // Declare exchange
        channel
            .exchange_declare(
                AMQP_EXCHANGE,
                AMQP_EXCHANGE_TYPE,
                ExchangeDeclareOptions { durable: true, auto_delete: false, ..Default::default() },
                FieldTable::default(),
            )
            .await
            .context("Failed to declare exchange")?;

        *self.connection.write().await = Some(conn);
        *self.channel.write().await = Some(channel);

        Ok(())
    }

    pub async fn setup_queues(&self, data_type: DataType) -> Result<()> {
        let channel = self.get_channel().await?;

        // Declare dead-letter exchange for poison messages
        let dlx_exchange = format!("{}.dlx", AMQP_EXCHANGE);
        channel
            .exchange_declare(
                &dlx_exchange,
                AMQP_EXCHANGE_TYPE,
                ExchangeDeclareOptions { durable: true, auto_delete: false, ..Default::default() },
                FieldTable::default(),
            )
            .await
            .context("Failed to declare dead-letter exchange")?;

        // Queue arguments for quorum queues with DLX
        let mut queue_args = FieldTable::default();
        queue_args.insert("x-queue-type".into(), lapin::types::AMQPValue::LongString("quorum".into()));
        queue_args.insert("x-dead-letter-exchange".into(), lapin::types::AMQPValue::LongString(dlx_exchange.clone().into()));
        queue_args.insert("x-delivery-limit".into(), lapin::types::AMQPValue::LongInt(20));

        // DLQ arguments (classic queues)
        let mut dlq_args = FieldTable::default();
        dlq_args.insert("x-queue-type".into(), lapin::types::AMQPValue::LongString("classic".into()));

        for prefix in [AMQP_QUEUE_PREFIX_GRAPHINATOR, AMQP_QUEUE_PREFIX_TABLEINATOR] {
            let queue_name = format!("{}-{}", prefix, data_type);
            let dlq_name = format!("{}.dlq", queue_name);

            // Declare and bind DLQ
            channel
                .queue_declare(&dlq_name, QueueDeclareOptions { durable: true, auto_delete: false, ..Default::default() }, dlq_args.clone())
                .await
                .context(format!("Failed to declare {} DLQ", prefix))?;

            channel
                .queue_bind(&dlq_name, &dlx_exchange, data_type.routing_key(), QueueBindOptions::default(), FieldTable::default())
                .await
                .context(format!("Failed to bind {} DLQ", prefix))?;

            // Declare and bind main queue (quorum)
            channel
                .queue_declare(&queue_name, QueueDeclareOptions { durable: true, auto_delete: false, ..Default::default() }, queue_args.clone())
                .await
                .context(format!("Failed to declare {} queue", prefix))?;

            channel
                .queue_bind(&queue_name, AMQP_EXCHANGE, data_type.routing_key(), QueueBindOptions::default(), FieldTable::default())
                .await
                .context(format!("Failed to bind {} queue", prefix))?;
        }

        debug!("✅ Set up AMQP queues for {} (exchange: {}, type: quorum with DLX)", data_type, AMQP_EXCHANGE);

        Ok(())
    }

    fn message_properties() -> BasicProperties {
        BasicProperties::default()
            .with_content_type("application/json".into())
            .with_content_encoding("application/json".into())
            .with_delivery_mode(2) // Persistent
    }

    pub async fn publish(&self, message: Message, data_type: DataType) -> Result<()> {
        let channel = self.get_channel().await?;
        let payload = serde_json::to_vec(&message).context("Failed to serialize message")?;

        let confirm = channel
            .basic_publish(
                AMQP_EXCHANGE,
                data_type.routing_key(),
                BasicPublishOptions { mandatory: true, ..Default::default() },
                &payload,
                Self::message_properties(),
            )
            .await
            .context("Failed to publish message")?
            .await
            .context("Failed to confirm message delivery")?;

        if !confirm.is_ack() {
            return Err(anyhow::anyhow!("Message was not acknowledged by broker"));
        }

        Ok(())
    }

    pub async fn publish_batch(&self, messages: Vec<DataMessage>, data_type: DataType) -> Result<()> {
        let channel = self.get_channel().await?;

        for message in messages {
            let payload = serde_json::to_vec(&Message::Data(message)).context("Failed to serialize message")?;

            let confirm = channel
                .basic_publish(
                    AMQP_EXCHANGE,
                    data_type.routing_key(),
                    BasicPublishOptions { mandatory: true, ..Default::default() },
                    &payload,
                    Self::message_properties(),
                )
                .await
                .context("Failed to publish message")?
                .await
                .context("Failed to confirm message delivery")?;

            if !confirm.is_ack() {
                warn!("⚠️ Message was not acknowledged by broker");
            }
        }

        Ok(())
    }

    pub async fn send_file_complete(&self, data_type: DataType, file_name: &str, total_processed: u64) -> Result<()> {
        let message =
            FileCompleteMessage { data_type: data_type.to_string(), timestamp: chrono::Utc::now(), total_processed, file: file_name.to_string() };

        self.publish(Message::FileComplete(message), data_type).await?;

        info!("🎉 File processing complete for {}! Total records processed: {}", data_type, total_processed);

        Ok(())
    }

    async fn get_channel(&self) -> Result<Channel> {
        let channel_guard = self.channel.read().await;

        if let Some(channel) = &*channel_guard
            && channel.status().connected()
        {
            return Ok(channel.clone());
        }

        drop(channel_guard);

        // Channel is not connected, try to reconnect
        warn!("⚠️ AMQP channel lost, attempting to reconnect...");
        self.connect().await?;

        self.channel.read().await.as_ref().cloned().ok_or_else(|| anyhow::anyhow!("Failed to get channel after reconnection"))
    }

    pub async fn close(&self) -> Result<()> {
        if let Some(channel) = self.channel.write().await.take() {
            channel.close(200, "Normal shutdown").await?;
        }

        if let Some(conn) = self.connection.write().await.take() {
            conn.close(200, "Normal shutdown").await?;
        }

        info!("🔌 AMQP connection closed");
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_queue_names() {
        let data_type = DataType::Artists;
        let graphinator = format!("{}-{}", AMQP_QUEUE_PREFIX_GRAPHINATOR, data_type);
        let tableinator = format!("{}-{}", AMQP_QUEUE_PREFIX_TABLEINATOR, data_type);

        assert_eq!(graphinator, "discogsography-graphinator-artists");
        assert_eq!(tableinator, "discogsography-tableinator-artists");
    }

    #[test]
    fn test_queue_names_all_types() {
        for data_type in [DataType::Artists, DataType::Labels, DataType::Masters, DataType::Releases] {
            let graphinator = format!("{}-{}", AMQP_QUEUE_PREFIX_GRAPHINATOR, data_type);
            let tableinator = format!("{}-{}", AMQP_QUEUE_PREFIX_TABLEINATOR, data_type);

            assert!(graphinator.starts_with("discogsography-graphinator-"));
            assert!(tableinator.starts_with("discogsography-tableinator-"));
            assert!(graphinator.ends_with(data_type.as_str()));
            assert!(tableinator.ends_with(data_type.as_str()));
        }
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
    fn test_routing_key_generation() {
        assert_eq!(DataType::Artists.routing_key(), "artists");
        assert_eq!(DataType::Labels.routing_key(), "labels");
        assert_eq!(DataType::Masters.routing_key(), "masters");
        assert_eq!(DataType::Releases.routing_key(), "releases");
    }

    #[test]
    fn test_constants() {
        assert_eq!(AMQP_EXCHANGE, "discogsography-exchange");
        assert_eq!(AMQP_EXCHANGE_TYPE, ExchangeKind::Topic);
        assert_eq!(AMQP_QUEUE_PREFIX_GRAPHINATOR, "discogsography-graphinator");
        assert_eq!(AMQP_QUEUE_PREFIX_TABLEINATOR, "discogsography-tableinator");
    }
}
