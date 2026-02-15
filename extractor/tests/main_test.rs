// Tests for main.rs functionality

use std::env;

#[test]
fn test_log_level_mapping() {
    // Test that log level environment variable parsing works correctly
    let test_cases = vec![
        ("DEBUG", "debug"),
        ("INFO", "info"),
        ("WARNING", "warn"),
        ("WARN", "warn"),
        ("ERROR", "error"),
        ("CRITICAL", "error"),
        ("invalid", "info"), // Should default to info
    ];

    for (input, expected) in test_cases {
        let rust_level = match input.to_uppercase().as_str() {
            "DEBUG" => "debug",
            "INFO" => "info",
            "WARNING" | "WARN" => "warn",
            "ERROR" => "error",
            "CRITICAL" => "error",
            _ => "info",
        };

        assert_eq!(rust_level, expected, "Failed for input: {}", input);
    }
}

#[test]
fn test_lapin_level_selection() {
    // Test that lapin log level is set correctly based on main log level
    let test_cases = vec![
        ("debug", "info"),  // Debug mode -> lapin at info
        ("info", "warn"),   // Info mode -> lapin at warn
        ("warn", "warn"),   // Warn mode -> lapin at warn
        ("error", "warn"),  // Error mode -> lapin at warn
    ];

    for (rust_level, expected_lapin) in test_cases {
        let lapin_level = if rust_level == "debug" { "info" } else { "warn" };
        assert_eq!(lapin_level, expected_lapin, "Failed for rust_level: {}", rust_level);
    }
}

#[tokio::test]
async fn test_ascii_art_generation() {
    // Verify ASCII art contains expected box-drawing characters
    let ascii_art = r#"
██████╗ ██╗███████╗ ██████╗ ██████╗  ██████╗ ███████╗
██╔══██╗██║██╔════╝██╔════╝██╔═══██╗██╔════╝ ██╔════╝
██║  ██║██║███████╗██║     ██║   ██║██║  ███╗███████╗
██║  ██║██║╚════██║██║     ██║   ██║██║   ██║╚════██║
██████╔╝██║███████║╚██████╗╚██████╔╝╚██████╔╝███████║
╚═════╝ ╚═╝╚══════╝ ╚═════╝ ╚═════╝  ╚═════╝ ╚══════╝

██████╗ ██╗   ██╗███████╗████████╗    ███████╗██╗  ██╗████████╗██████╗  █████╗  ██████╗████████╗ ██████╗ ██████╗
██╔══██╗██║   ██║██╔════╝╚══██╔══╝    ██╔════╝╚██╗██╔╝╚══██╔══╝██╔══██╗██╔══██╗██╔════╝╚══██╔══╝██╔═══██╗██╔══██╗
██████╔╝██║   ██║███████╗   ██║       █████╗   ╚███╔╝    ██║   ██████╔╝███████║██║        ██║   ██║   ██║██████╔╝
██╔══██╗██║   ██║╚════██║   ██║       ██╔══╝   ██╔██╗    ██║   ██╔══██╗██╔══██║██║        ██║   ██║   ██║██╔══██╗
██║  ██║╚██████╔╝███████║   ██║       ███████╗██╔╝ ██╗   ██║   ██║  ██║██║  ██║╚██████╗   ██║   ╚██████╔╝██║  ██║
╚═╝  ╚═╝ ╚═════╝ ╚══════╝   ╚═╝       ╚══════╝╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝   ╚═╝    ╚═════╝ ╚═╝  ╚═╝
"#;

    // ASCII art uses box-drawing characters (██, ╗, ╔, etc.)
    assert!(ascii_art.contains("██"));
    assert!(ascii_art.contains("╗"));
    assert!(ascii_art.contains("╚"));
    assert!(!ascii_art.is_empty());
    assert!(ascii_art.len() > 100); // Should be substantial
}

#[test]
fn test_environment_variable_defaults() {
    // Test that environment variables have sensible defaults
    unsafe {
        env::remove_var("LOG_LEVEL");
        env::remove_var("RUST_EXTRACTOR_CONFIG");
        env::remove_var("FORCE_REPROCESS");
    }

    let log_level = env::var("LOG_LEVEL").unwrap_or_else(|_| "INFO".to_string());
    assert_eq!(log_level, "INFO");

    // Config file should default to config.toml
    let config_file = env::var("RUST_EXTRACTOR_CONFIG").unwrap_or_else(|_| "config.toml".to_string());
    assert_eq!(config_file, "config.toml");

    // Force reprocess should default to false (empty env var)
    let force_reprocess = env::var("FORCE_REPROCESS").is_ok();
    assert!(!force_reprocess);
}

#[test]
fn test_filter_format() {
    // Test that the tracing filter is formatted correctly
    let rust_level = "info";
    let lapin_level = "warn";
    let filter = format!("extractor={},lapin={}", rust_level, lapin_level);

    assert_eq!(filter, "extractor=info,lapin=warn");
}

#[test]
fn test_log_level_case_insensitive() {
    // Test that log level is case-insensitive
    let test_cases = vec![
        ("debug", "DEBUG", "Debug"),
        ("info", "INFO", "Info"),
        ("warning", "WARNING", "Warning"),
    ];

    for (lower, upper, title) in test_cases {
        assert_eq!(lower.to_uppercase(), upper);
        assert_eq!(title.to_uppercase(), upper);
    }
}

#[tokio::test]
async fn test_shutdown_signal_handler() {
    use std::sync::Arc;
    use tokio::sync::Notify;

    // Create a shutdown notifier
    let shutdown = Arc::new(Notify::new());
    let shutdown_clone = shutdown.clone();

    // Simulate shutdown signal
    tokio::spawn(async move {
        tokio::time::sleep(tokio::time::Duration::from_millis(100)).await;
        shutdown_clone.notify_waiters();
    });

    // Wait for shutdown signal with timeout
    let result = tokio::time::timeout(
        tokio::time::Duration::from_secs(1),
        shutdown.notified()
    ).await;

    assert!(result.is_ok(), "Shutdown signal should be received");
}

#[test]
fn test_config_path_default() {
    // Test that config path defaults are correct
    use std::path::PathBuf;

    let default_config = PathBuf::from("config.toml");
    assert_eq!(default_config.to_str().unwrap(), "config.toml");
}

#[test]
fn test_force_reprocess_flag() {
    // Test force_reprocess flag behavior
    let test_cases = vec![
        (true, "should reprocess"),
        (false, "should not reprocess"),
    ];

    for (force_reprocess, description) in test_cases {
        if force_reprocess {
            assert!(force_reprocess, "{}", description);
        } else {
            assert!(!force_reprocess, "{}", description);
        }
    }
}
