#[tokio::test]
async fn test_config_from_env() {
    // Test that configuration loads from environment variables
    unsafe {
        std::env::set_var("AMQP_CONNECTION", "amqp://localhost:5672");
    }

    // This should not panic
    let _config = extractor::config::ExtractorConfig::from_env();

    // Clean up
    unsafe {
        std::env::remove_var("AMQP_CONNECTION");
    }
}

#[tokio::test]
async fn test_data_type_conversion() {
    use extractor::types::DataType;
    use std::str::FromStr;

    assert_eq!(DataType::from_str("artists"), Ok(DataType::Artists));
    assert_eq!(DataType::from_str("labels"), Ok(DataType::Labels));
    assert_eq!(DataType::from_str("masters"), Ok(DataType::Masters));
    assert_eq!(DataType::from_str("releases"), Ok(DataType::Releases));
    assert!(DataType::from_str("invalid").is_err());
}

#[tokio::test]
async fn test_extraction_progress() {
    use extractor::types::{DataType, ExtractionProgress};

    let mut progress = ExtractionProgress::default();
    assert_eq!(progress.total(), 0);

    progress.increment(DataType::Artists);
    assert_eq!(progress.artists, 1);
    assert_eq!(progress.total(), 1);

    progress.increment(DataType::Labels);
    assert_eq!(progress.labels, 1);
    assert_eq!(progress.total(), 2);
}
