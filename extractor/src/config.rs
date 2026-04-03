use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

use crate::types::Source;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExtractorConfig {
    pub amqp_connection: String,
    pub discogs_root: PathBuf,
    pub periodic_check_days: u64,
    pub health_port: u16,
    pub max_workers: usize,
    pub batch_size: usize,
    pub queue_size: usize,
    pub progress_log_interval: usize,
    pub state_save_interval: usize,
    pub data_quality_rules: Option<PathBuf>,
    pub source: Source,
    pub musicbrainz_root: PathBuf,
    pub discogs_exchange_prefix: String,
    pub musicbrainz_exchange_prefix: String,
    pub musicbrainz_dump_url: String,
}

impl Default for ExtractorConfig {
    fn default() -> Self {
        Self {
            amqp_connection: build_amqp_url("discogsography", "discogsography", "localhost", "5672"),
            discogs_root: PathBuf::from("/discogs-data"),
            periodic_check_days: 15,
            health_port: 8000,
            max_workers: num_cpus::get(),
            batch_size: 100,
            queue_size: 5000,
            progress_log_interval: 1000,
            state_save_interval: 5000,
            data_quality_rules: None,
            source: Source::Discogs,
            musicbrainz_root: PathBuf::from("/musicbrainz-data"),
            discogs_exchange_prefix: "discogsography-discogs".to_string(),
            musicbrainz_exchange_prefix: "discogsography-musicbrainz".to_string(),
            musicbrainz_dump_url: "https://data.metabrainz.org/pub/musicbrainz/data/json-dumps/".to_string(),
        }
    }
}

/// Read a secret value from a `<VAR>_FILE` path if set, else fall back to the plain `<VAR>`
/// environment variable, then to the provided default.
fn read_secret(env_var: &str, default: &str) -> Result<String> {
    let file_var = format!("{}_FILE", env_var);
    if let Ok(file_path) = std::env::var(&file_var) {
        return std::fs::read_to_string(&file_path)
            .map(|s| s.trim().to_string())
            .with_context(|| format!("Cannot read secret file for {}: {:?}", env_var, file_path));
    }
    Ok(std::env::var(env_var).unwrap_or_else(|_| default.to_string()))
}

/// Build an AMQP connection URL from its component parts, percent-encoding credentials.
fn build_amqp_url(user: &str, password: &str, host: &str, port: &str) -> String {
    let encoded_user = urlencoding::encode(user);
    let encoded_password = urlencoding::encode(password);
    format!("amqp://{}:{}@{}:{}/%2F", encoded_user, encoded_password, host, port)
}

impl ExtractorConfig {
    /// Load configuration from environment variables.
    pub fn from_env() -> Result<Self> {
        let user = read_secret("RABBITMQ_USERNAME", "discogsography")?;
        let password = read_secret("RABBITMQ_PASSWORD", "discogsography")?;
        let host = std::env::var("RABBITMQ_HOST").unwrap_or_else(|_| "rabbitmq".to_string());
        let port = std::env::var("RABBITMQ_PORT").unwrap_or_else(|_| "5672".to_string());
        let amqp_connection = build_amqp_url(&user, &password, &host, &port);

        let discogs_root = PathBuf::from(std::env::var("DISCOGS_ROOT").unwrap_or_else(|_| "/discogs-data".to_string()));

        let periodic_check_days = std::env::var("PERIODIC_CHECK_DAYS").unwrap_or_else(|_| "15".to_string()).parse::<u64>().unwrap_or(15).max(1);

        let max_workers = std::env::var("MAX_WORKERS")
            .unwrap_or_else(|_| num_cpus::get().to_string())
            .parse::<usize>()
            .unwrap_or_else(|_| num_cpus::get())
            .max(1);

        let batch_size = std::env::var("BATCH_SIZE").unwrap_or_else(|_| "100".to_string()).parse::<usize>().unwrap_or(100).max(1);

        let data_quality_rules = std::env::var("DATA_QUALITY_RULES").ok().map(PathBuf::from);

        let source = std::env::var("EXTRACTOR_SOURCE").unwrap_or_else(|_| "discogs".to_string()).parse::<Source>().unwrap_or(Source::Discogs);

        let musicbrainz_root = PathBuf::from(std::env::var("MUSICBRAINZ_ROOT").unwrap_or_else(|_| "/musicbrainz-data".to_string()));

        let discogs_exchange_prefix = std::env::var("DISCOGS_EXCHANGE_PREFIX").unwrap_or_else(|_| "discogsography-discogs".to_string());
        let musicbrainz_exchange_prefix = std::env::var("MUSICBRAINZ_EXCHANGE_PREFIX").unwrap_or_else(|_| "discogsography-musicbrainz".to_string());

        let musicbrainz_dump_url =
            std::env::var("MUSICBRAINZ_DUMP_URL").unwrap_or_else(|_| "https://data.metabrainz.org/pub/musicbrainz/data/json-dumps/".to_string());

        let health_port = std::env::var("HEALTH_PORT").unwrap_or_else(|_| "8000".to_string()).parse::<u16>().unwrap_or(8000);
        let queue_size = std::env::var("QUEUE_SIZE").unwrap_or_else(|_| "5000".to_string()).parse::<usize>().unwrap_or(5000).max(1);
        let progress_log_interval =
            std::env::var("PROGRESS_LOG_INTERVAL").unwrap_or_else(|_| "1000".to_string()).parse::<usize>().unwrap_or(1000).max(1);
        let state_save_interval =
            std::env::var("STATE_SAVE_INTERVAL").unwrap_or_else(|_| "5000".to_string()).parse::<usize>().unwrap_or(5000).max(1);

        Ok(Self {
            amqp_connection,
            discogs_root,
            periodic_check_days,
            health_port,
            max_workers,
            batch_size,
            queue_size,
            progress_log_interval,
            state_save_interval,
            data_quality_rules,
            source,
            musicbrainz_root,
            discogs_exchange_prefix,
            musicbrainz_exchange_prefix,
            musicbrainz_dump_url,
        })
    }
}

#[cfg(test)]
#[path = "tests/config_tests.rs"]
mod tests;
