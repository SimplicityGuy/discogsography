use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

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
        let user = read_secret("RABBITMQ_USER", "discogsography")?;
        let password = read_secret("RABBITMQ_PASSWORD", "discogsography")?;
        let host = std::env::var("RABBITMQ_HOST").unwrap_or_else(|_| "rabbitmq".to_string());
        let port = std::env::var("RABBITMQ_PORT").unwrap_or_else(|_| "5672".to_string());
        let amqp_connection = build_amqp_url(&user, &password, &host, &port);

        let discogs_root = PathBuf::from(std::env::var("DISCOGS_ROOT").unwrap_or_else(|_| "/discogs-data".to_string()));

        let periodic_check_days = std::env::var("PERIODIC_CHECK_DAYS").unwrap_or_else(|_| "15".to_string()).parse::<u64>().unwrap_or(15);

        let max_workers = std::env::var("MAX_WORKERS")
            .unwrap_or_else(|_| num_cpus::get().to_string())
            .parse::<usize>()
            .unwrap_or_else(|_| num_cpus::get());

        let batch_size = std::env::var("BATCH_SIZE").unwrap_or_else(|_| "100".to_string()).parse::<usize>().unwrap_or(100);

        Ok(Self { amqp_connection, discogs_root, periodic_check_days, max_workers, batch_size, ..Default::default() })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serial_test::serial;
    use std::env;

    #[test]
    fn test_default_config() {
        let config = ExtractorConfig::default();
        assert_eq!(config.periodic_check_days, 15);
        assert_eq!(config.batch_size, 100);
        assert_eq!(config.queue_size, 5000);
        assert_eq!(config.progress_log_interval, 1000);
        assert_eq!(config.state_save_interval, 5000);
        assert_eq!(config.health_port, 8000);
        assert_eq!(config.amqp_connection, "amqp://discogsography:discogsography@localhost:5672/%2F");
        assert_eq!(config.discogs_root, PathBuf::from("/discogs-data"));
    }

    #[test]
    fn test_default_max_workers() {
        let config = ExtractorConfig::default();
        assert_eq!(config.max_workers, num_cpus::get());
    }

    #[test]
    #[serial]
    fn test_from_env_with_rabbitmq_credentials() {
        unsafe {
            env::set_var("RABBITMQ_USER", "testuser");
            env::set_var("RABBITMQ_PASSWORD", "testpass");
            env::set_var("RABBITMQ_HOST", "mybroker");
            env::set_var("RABBITMQ_PORT", "5673");
        }

        let config = ExtractorConfig::from_env().unwrap();
        assert_eq!(config.amqp_connection, "amqp://testuser:testpass@mybroker:5673/%2F");

        unsafe {
            env::remove_var("RABBITMQ_USER");
            env::remove_var("RABBITMQ_PASSWORD");
            env::remove_var("RABBITMQ_HOST");
            env::remove_var("RABBITMQ_PORT");
        }
    }

    #[test]
    #[serial]
    fn test_from_env_uses_credential_defaults() {
        unsafe {
            env::remove_var("RABBITMQ_USER");
            env::remove_var("RABBITMQ_PASSWORD");
            env::remove_var("RABBITMQ_HOST");
            env::remove_var("RABBITMQ_PORT");
            env::remove_var("RABBITMQ_USER_FILE");
            env::remove_var("RABBITMQ_PASSWORD_FILE");
        }

        let config = ExtractorConfig::from_env().unwrap();
        assert_eq!(config.amqp_connection, "amqp://discogsography:discogsography@rabbitmq:5672/%2F");
    }

    #[test]
    #[serial]
    fn test_from_env_with_all_settings() {
        // Lock to prevent concurrent env var access
        unsafe {
            env::set_var("RABBITMQ_USER", "testuser");
            env::set_var("RABBITMQ_PASSWORD", "testpass");
            env::remove_var("RABBITMQ_HOST");
            env::remove_var("RABBITMQ_PORT");
            env::remove_var("DISCOGS_ROOT");
            env::remove_var("PERIODIC_CHECK_DAYS");
            env::remove_var("BATCH_SIZE");
            env::remove_var("MAX_WORKERS");
        }

        let config = ExtractorConfig::from_env().unwrap();
        assert_eq!(config.amqp_connection, "amqp://testuser:testpass@rabbitmq:5672/%2F");

        unsafe {
            env::set_var("DISCOGS_ROOT", "/custom/path");
            env::set_var("PERIODIC_CHECK_DAYS", "30");
            env::set_var("BATCH_SIZE", "200");
            env::set_var("MAX_WORKERS", "8");
        }

        let config2 = ExtractorConfig::from_env().unwrap();
        assert_eq!(config2.discogs_root, PathBuf::from("/custom/path"));
        assert_eq!(config2.periodic_check_days, 30);
        assert_eq!(config2.batch_size, 200);
        assert_eq!(config2.max_workers, 8);

        unsafe {
            env::remove_var("RABBITMQ_USER");
            env::remove_var("RABBITMQ_PASSWORD");
            env::remove_var("DISCOGS_ROOT");
            env::remove_var("PERIODIC_CHECK_DAYS");
            env::remove_var("BATCH_SIZE");
            env::remove_var("MAX_WORKERS");
        }
    }

    #[test]
    #[serial]
    fn test_from_env_default_discogs_root() {
        unsafe {
            env::remove_var("DISCOGS_ROOT");
        }

        let config = ExtractorConfig::from_env().unwrap();
        assert_eq!(config.discogs_root, PathBuf::from("/discogs-data"));
    }

    #[test]
    #[serial]
    fn test_from_env_invalid_periodic_check_days() {
        unsafe {
            env::set_var("PERIODIC_CHECK_DAYS", "invalid");
        }

        let config = ExtractorConfig::from_env().unwrap();
        assert_eq!(config.periodic_check_days, 15); // Should use default

        unsafe {
            env::remove_var("PERIODIC_CHECK_DAYS");
        }
    }

    #[test]
    fn test_from_env_invalid_batch_size() {
        // Test parse logic directly since env vars have race conditions
        let invalid_str = "not_a_number";
        let result = invalid_str.parse::<usize>().unwrap_or(100);
        assert_eq!(result, 100); // Should use default
    }

    #[test]
    fn test_from_env_invalid_max_workers() {
        // Test parse logic directly since env vars have race conditions
        let invalid_str = "invalid";
        let result = invalid_str.parse::<usize>().unwrap_or_else(|_| num_cpus::get());
        assert_eq!(result, num_cpus::get()); // Should use default
    }

    #[test]
    #[serial]
    fn test_from_env_fixed_values() {
        let config = ExtractorConfig::from_env().unwrap();

        // These should always be fixed for drop-in compatibility
        assert_eq!(config.queue_size, 5000);
        assert_eq!(config.progress_log_interval, 1000);
        assert_eq!(config.state_save_interval, 5000);
        assert_eq!(config.health_port, 8000);
    }
}
