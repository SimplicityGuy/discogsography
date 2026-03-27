use anyhow::{Context, Result};
use lapin::{BasicProperties, Channel, Connection, ConnectionProperties, ExchangeKind, options::*, types::FieldTable};
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::RwLock;
use tokio::time::sleep;
use tracing::{debug, error, info, warn};
use url::Url;

use async_trait::async_trait;

use crate::types::{DataMessage, DataType, ExtractionCompleteMessage, FileCompleteMessage, Message};

#[allow(dead_code)]
const DEFAULT_EXCHANGE_PREFIX: &str = "discogsography";
const AMQP_EXCHANGE_TYPE: ExchangeKind = ExchangeKind::Fanout;

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
    ) -> Result<()>;
    async fn close(&self) -> Result<()>;
}

pub struct MessageQueue {
    connection: Arc<RwLock<Option<Connection>>>,
    channel: Arc<RwLock<Option<Channel>>>,
    url: String,
    max_retries: u32,
    exchange_prefix: String,
}

impl MessageQueue {
    /// Build the fanout exchange name for a given data type (e.g. "discogsography-artists")
    fn exchange_name(&self, data_type: DataType) -> String {
        format!("{}-{}", self.exchange_prefix, data_type)
    }

    pub async fn new(url: &str, max_retries: u32, exchange_prefix: &str) -> Result<Self> {
        // Normalize the AMQP URL to handle trailing slash consistently with Python extractor
        let normalized_url = Self::normalize_amqp_url(url)?;

        let mq = Self {
            connection: Arc::new(RwLock::new(None)),
            channel: Arc::new(RwLock::new(None)),
            url: normalized_url,
            max_retries,
            exchange_prefix: exchange_prefix.to_string(),
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
        let channel = self.get_channel().await?;
        let exchange_name = self.exchange_name(data_type);
        let payload = serde_json::to_vec(&message).context("Failed to serialize message")?;

        let confirm = channel
            .basic_publish(exchange_name.as_str().into(), "".into(), BasicPublishOptions::default(), &payload, Self::message_properties())
            .await
            .context("Failed to publish message")?
            .await
            .context("Failed to confirm message delivery")?;

        if !confirm.is_ack() {
            return Err(anyhow::anyhow!("Message was not acknowledged by broker"));
        }

        Ok(())
    }

    async fn publish_batch(&self, messages: Vec<DataMessage>, data_type: DataType) -> Result<()> {
        let channel = self.get_channel().await?;
        let exchange_name = self.exchange_name(data_type);

        for message in messages {
            let payload = serde_json::to_vec(&Message::Data(message)).context("Failed to serialize message")?;

            let confirm = channel
                .basic_publish(exchange_name.as_str().into(), "".into(), BasicPublishOptions::default(), &payload, Self::message_properties())
                .await
                .context("Failed to publish message")?
                .await
                .context("Failed to confirm message delivery")?;

            if !confirm.is_ack() {
                return Err(anyhow::anyhow!("Message was not acknowledged by broker"));
            }
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
    ) -> Result<()> {
        let message = ExtractionCompleteMessage { version: version.to_string(), timestamp: chrono::Utc::now(), started_at, record_counts };

        // Publish to all data type exchanges so every consumer queue receives it
        // Attempt all exchanges before returning, so a single failure doesn't prevent
        // other consumers from receiving the signal
        let mut errors = Vec::new();
        for data_type in DataType::all() {
            if let Err(e) = self.publish(Message::ExtractionComplete(message.clone()), data_type).await {
                error!("❌ Failed to send extraction_complete to {}: {}", data_type, e);
                errors.push(format!("{}: {}", data_type, e));
            }
        }

        if errors.is_empty() {
            info!("🏁 Extraction complete message sent to all {} exchanges (version: {})", DataType::all().len(), version,);
        } else {
            let succeeded = DataType::all().len() - errors.len();
            warn!("⚠️ Extraction complete sent to {}/{} exchanges (version: {})", succeeded, DataType::all().len(), version,);
            return Err(anyhow::anyhow!("Failed to send extraction_complete to {} exchange(s): {}", errors.len(), errors.join("; ")));
        }

        Ok(())
    }

    async fn close(&self) -> Result<()> {
        if let Some(channel) = self.channel.write().await.take() {
            channel.close(200, "Normal shutdown".into()).await?;
        }

        if let Some(conn) = self.connection.write().await.take() {
            conn.close(200, "Normal shutdown".into()).await?;
        }

        info!("🔌 AMQP connection closed");
        Ok(())
    }
}

#[cfg(test)]
#[path = "tests/message_queue_tests.rs"]
mod tests;
