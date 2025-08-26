use anyhow::{Context, Result};
use config::{Config, File};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DistillerConfig {
    pub amqp_connection: String,
    pub discogs_root: PathBuf,
    pub max_temp_size: u64,
    pub periodic_check_days: u64,
    pub health_port: u16,
    pub max_workers: usize,
    pub batch_size: usize,
    pub queue_size: usize,
    pub progress_log_interval: usize,
    pub s3_bucket: String,
    pub s3_region: String,
}

impl Default for DistillerConfig {
    fn default() -> Self {
        Self {
            amqp_connection: "amqp://localhost:5672".to_string(),
            discogs_root: PathBuf::from("/discogs-data"),
            max_temp_size: 1_000_000_000, // 1GB
            periodic_check_days: 15,
            health_port: 8000,
            max_workers: num_cpus::get(),
            batch_size: 100,
            queue_size: 5000,
            progress_log_interval: 1000,
            s3_bucket: "discogs-data-dumps".to_string(),
            s3_region: "us-west-2".to_string(),
        }
    }
}

impl DistillerConfig {
    /// Load configuration from file
    #[allow(dead_code)]
    pub fn from_file(path: &Path) -> Result<Self> {
        let config = Config::builder()
            .add_source(File::from(path).required(false))
            .add_source(config::Environment::with_prefix("DISTILLER"))
            .build()
            .context("Failed to build configuration")?;

        config.try_deserialize().context("Failed to deserialize configuration")
    }

    /// Load configuration from environment variables (drop-in replacement for extractor)
    pub fn from_env() -> Result<Self> {
        // Use same environment variables as Python extractor for drop-in compatibility
        let amqp_connection = std::env::var("AMQP_CONNECTION").context("AMQP_CONNECTION environment variable is required")?;

        let discogs_root = PathBuf::from(std::env::var("DISCOGS_ROOT").unwrap_or_else(|_| "/discogs-data".to_string()));

        let periodic_check_days = std::env::var("PERIODIC_CHECK_DAYS").unwrap_or_else(|_| "15".to_string()).parse::<u64>().unwrap_or(15);

        // Internal settings - use defaults for drop-in compatibility
        let max_workers = std::env::var("MAX_WORKERS")
            .unwrap_or_else(|_| num_cpus::get().to_string())
            .parse::<usize>()
            .unwrap_or_else(|_| num_cpus::get());

        let batch_size = std::env::var("BATCH_SIZE").unwrap_or_else(|_| "100".to_string()).parse::<usize>().unwrap_or(100);
        let queue_size = 5000; // Fixed for compatibility
        let progress_log_interval = 1000; // Fixed for compatibility
        let health_port = 8000; // Fixed port for drop-in replacement

        let s3_bucket = "discogs-data-dumps".to_string();
        let s3_region = "us-west-2".to_string();

        Ok(Self {
            amqp_connection,
            discogs_root,
            max_temp_size: 1_000_000_000,
            periodic_check_days,
            health_port,
            max_workers,
            batch_size,
            queue_size,
            progress_log_interval,
            s3_bucket,
            s3_region,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::env;

    #[test]
    fn test_default_config() {
        let config = DistillerConfig::default();
        assert_eq!(config.periodic_check_days, 15);
        assert_eq!(config.batch_size, 100);
        assert_eq!(config.queue_size, 5000);
    }

    #[test]
    fn test_from_env() {
        unsafe {
            env::set_var("AMQP_CONNECTION", "amqp://test:5672");
            env::set_var("PERIODIC_CHECK_DAYS", "30");
            env::set_var("BATCH_SIZE", "200");
        }

        let config = DistillerConfig::from_env().unwrap();
        assert_eq!(config.amqp_connection, "amqp://test:5672");
        assert_eq!(config.periodic_check_days, 30);
        assert_eq!(config.batch_size, 200);

        // Cleanup
        unsafe {
            env::remove_var("AMQP_CONNECTION");
            env::remove_var("PERIODIC_CHECK_DAYS");
            env::remove_var("BATCH_SIZE");
        }
    }
}
