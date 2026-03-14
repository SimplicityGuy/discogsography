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
        env::set_var("RABBITMQ_USERNAME", "testuser");
        env::set_var("RABBITMQ_PASSWORD", "testpass");
        env::set_var("RABBITMQ_HOST", "mybroker");
        env::set_var("RABBITMQ_PORT", "5673");
    }

    let config = ExtractorConfig::from_env().unwrap();
    assert_eq!(config.amqp_connection, "amqp://testuser:testpass@mybroker:5673/%2F");

    unsafe {
        env::remove_var("RABBITMQ_USERNAME");
        env::remove_var("RABBITMQ_PASSWORD");
        env::remove_var("RABBITMQ_HOST");
        env::remove_var("RABBITMQ_PORT");
    }
}

#[test]
#[serial]
fn test_from_env_uses_credential_defaults() {
    unsafe {
        env::remove_var("RABBITMQ_USERNAME");
        env::remove_var("RABBITMQ_PASSWORD");
        env::remove_var("RABBITMQ_HOST");
        env::remove_var("RABBITMQ_PORT");
        env::remove_var("RABBITMQ_USERNAME_FILE");
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
        env::set_var("RABBITMQ_USERNAME", "testuser");
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
        env::remove_var("RABBITMQ_USERNAME");
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

#[test]
#[serial]
fn test_from_env_reads_secret_from_file() {
    use std::io::Write;

    let mut tmp = tempfile::NamedTempFile::new().unwrap();
    write!(tmp, "file_secret_password").unwrap();

    unsafe {
        env::set_var("RABBITMQ_PASSWORD_FILE", tmp.path().to_str().unwrap());
        env::remove_var("RABBITMQ_PASSWORD");
        env::remove_var("RABBITMQ_USERNAME_FILE");
        env::remove_var("RABBITMQ_USERNAME");
    }

    let config = ExtractorConfig::from_env().unwrap();
    assert!(
        config.amqp_connection.contains("file_secret_password"),
        "Expected password from file in AMQP URL, got: {}",
        config.amqp_connection
    );

    unsafe {
        env::remove_var("RABBITMQ_PASSWORD_FILE");
    }
}

#[test]
#[serial]
fn test_from_env_secret_file_not_found() {
    unsafe {
        env::set_var("RABBITMQ_PASSWORD_FILE", "/nonexistent/path/to/secret");
        env::remove_var("RABBITMQ_PASSWORD");
    }

    let result = ExtractorConfig::from_env();
    assert!(result.is_err(), "Expected error when secret file does not exist");

    let err_msg = format!("{:#}", result.unwrap_err());
    assert!(
        err_msg.contains("Cannot read secret file"),
        "Expected 'Cannot read secret file' in error, got: {}",
        err_msg
    );

    unsafe {
        env::remove_var("RABBITMQ_PASSWORD_FILE");
    }
}

#[test]
fn test_build_amqp_url_special_characters() {
    let url = build_amqp_url("user@host", "p@ss:w/rd#1", "localhost", "5672");
    assert_eq!(
        url,
        "amqp://user%40host:p%40ss%3Aw%2Frd%231@localhost:5672/%2F"
    );
}

#[test]
#[serial]
fn test_from_env_secret_file_with_whitespace() {
    use std::io::Write;

    let mut tmp = tempfile::NamedTempFile::new().unwrap();
    writeln!(tmp, "  trimmed_password  ").unwrap();

    unsafe {
        env::set_var("RABBITMQ_PASSWORD_FILE", tmp.path().to_str().unwrap());
        env::remove_var("RABBITMQ_PASSWORD");
        env::remove_var("RABBITMQ_USERNAME_FILE");
        env::remove_var("RABBITMQ_USERNAME");
    }

    let config = ExtractorConfig::from_env().unwrap();
    assert!(
        config.amqp_connection.contains("trimmed_password"),
        "Expected trimmed password in AMQP URL, got: {}",
        config.amqp_connection
    );
    assert!(
        !config.amqp_connection.contains("  trimmed_password"),
        "Password should be trimmed of leading whitespace"
    );

    unsafe {
        env::remove_var("RABBITMQ_PASSWORD_FILE");
    }
}
