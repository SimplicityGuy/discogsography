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
    fn normalize_amqp_url(url: &str) -> Result<String> {
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

        let graphinator_queue = format!("{}-{}", AMQP_QUEUE_PREFIX_GRAPHINATOR, data_type);
        let tableinator_queue = format!("{}-{}", AMQP_QUEUE_PREFIX_TABLEINATOR, data_type);

        // Declare and bind graphinator queue
        channel
            .queue_declare(&graphinator_queue, QueueDeclareOptions { durable: true, auto_delete: false, ..Default::default() }, FieldTable::default())
            .await
            .context("Failed to declare graphinator queue")?;

        channel
            .queue_bind(&graphinator_queue, AMQP_EXCHANGE, data_type.routing_key(), QueueBindOptions::default(), FieldTable::default())
            .await
            .context("Failed to bind graphinator queue")?;

        // Declare and bind tableinator queue
        channel
            .queue_declare(&tableinator_queue, QueueDeclareOptions { durable: true, auto_delete: false, ..Default::default() }, FieldTable::default())
            .await
            .context("Failed to declare tableinator queue")?;

        channel
            .queue_bind(&tableinator_queue, AMQP_EXCHANGE, data_type.routing_key(), QueueBindOptions::default(), FieldTable::default())
            .await
            .context("Failed to bind tableinator queue")?;

        debug!("✅ Set up AMQP queues for {} (exchange: {}, type: {:?})", data_type, AMQP_EXCHANGE, AMQP_EXCHANGE_TYPE);

        Ok(())
    }

    pub async fn publish(&self, message: Message, data_type: DataType) -> Result<()> {
        let channel = self.get_channel().await?;
        let payload = serde_json::to_vec(&message).context("Failed to serialize message")?;

        let properties = BasicProperties::default()
            .with_content_type("application/json".into())
            .with_content_encoding("application/json".into())
            .with_delivery_mode(2); // Persistent

        let confirm = channel
            .basic_publish(
                AMQP_EXCHANGE,
                data_type.routing_key(),
                BasicPublishOptions { mandatory: true, ..Default::default() },
                &payload,
                properties,
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

        let properties = BasicProperties::default()
            .with_content_type("application/json".into())
            .with_content_encoding("application/json".into())
            .with_delivery_mode(2); // Persistent

        for message in messages {
            let payload = serde_json::to_vec(&Message::Data(message)).context("Failed to serialize message")?;

            let confirm = channel
                .basic_publish(
                    AMQP_EXCHANGE,
                    data_type.routing_key(),
                    BasicPublishOptions { mandatory: true, ..Default::default() },
                    &payload,
                    properties.clone(),
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
}
