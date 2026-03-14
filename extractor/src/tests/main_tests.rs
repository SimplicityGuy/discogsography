use super::*;

#[test]
fn test_build_tracing_filter_debug() {
    let filter = build_tracing_filter("debug");
    assert_eq!(filter, "extractor=debug,lapin=info");
}

#[test]
fn test_build_tracing_filter_info() {
    let filter = build_tracing_filter("info");
    assert_eq!(filter, "extractor=info,lapin=warn");
}

#[test]
fn test_build_tracing_filter_warn() {
    let filter = build_tracing_filter("warn");
    assert_eq!(filter, "extractor=warn,lapin=warn");
}

#[test]
fn test_build_tracing_filter_error() {
    let filter = build_tracing_filter("error");
    assert_eq!(filter, "extractor=error,lapin=warn");
}

#[test]
fn test_build_tracing_filter_python_levels() {
    assert_eq!(build_tracing_filter("DEBUG"), "extractor=debug,lapin=info");
    assert_eq!(build_tracing_filter("INFO"), "extractor=info,lapin=warn");
    assert_eq!(build_tracing_filter("WARNING"), "extractor=warn,lapin=warn");
    assert_eq!(build_tracing_filter("CRITICAL"), "extractor=error,lapin=warn");
    assert_eq!(build_tracing_filter("INVALID"), "extractor=info,lapin=warn");
    assert_eq!(build_tracing_filter(""), "extractor=info,lapin=warn");
}

#[tokio::test]
async fn test_setup_shutdown_handler() {
    let shutdown = setup_shutdown_handler();
    // Just verify it creates a valid Notify instance
    assert!(Arc::strong_count(&shutdown) >= 1);
}

#[test]
fn test_ascii_art_display() {
    // Just verify the function doesn't panic
    print_ascii_art();
}
