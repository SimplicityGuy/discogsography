#[tokio::test]
async fn test_config_from_env() {
    // Test that configuration loads from environment variables
    std::env::set_var("AMQP_CONNECTION", "amqp://localhost:5672");

    // This should not panic
    let _config = distiller::config::DistillerConfig::from_env();

    // Clean up
    std::env::remove_var("AMQP_CONNECTION");
}

#[tokio::test]
async fn test_data_type_conversion() {
    use distiller::types::DataType;

    assert_eq!(DataType::from_str("artists"), Some(DataType::Artists));
    assert_eq!(DataType::from_str("labels"), Some(DataType::Labels));
    assert_eq!(DataType::from_str("masters"), Some(DataType::Masters));
    assert_eq!(DataType::from_str("releases"), Some(DataType::Releases));
    assert_eq!(DataType::from_str("invalid"), None);
}

#[tokio::test]
async fn test_extraction_progress() {
    use distiller::types::{DataType, ExtractionProgress};

    let mut progress = ExtractionProgress::default();
    assert_eq!(progress.total(), 0);

    progress.increment(DataType::Artists);
    assert_eq!(progress.artists, 1);
    assert_eq!(progress.total(), 1);

    progress.increment(DataType::Labels);
    assert_eq!(progress.labels, 1);
    assert_eq!(progress.total(), 2);
}
