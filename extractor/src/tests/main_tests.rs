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
fn test_ascii_art_display_discogs() {
    // Just verify the function doesn't panic
    print_ascii_art(Some(&Source::Discogs));
}

#[test]
fn test_ascii_art_display_musicbrainz() {
    // Just verify the function doesn't panic
    print_ascii_art(Some(&Source::MusicBrainz));
}

#[test]
fn test_ascii_art_display_none() {
    // Just verify the function doesn't panic with no source
    print_ascii_art(None);
}

// ── failure-cooldown parser ───────────────────────────────────────────

#[test]
fn test_parse_failure_cooldown_default_when_missing() {
    assert_eq!(parse_failure_cooldown(None), DEFAULT_FAILURE_COOLDOWN_SECS);
}

#[test]
fn test_parse_failure_cooldown_default_when_garbage() {
    assert_eq!(parse_failure_cooldown(Some("not-a-number")), DEFAULT_FAILURE_COOLDOWN_SECS);
    assert_eq!(parse_failure_cooldown(Some("")), DEFAULT_FAILURE_COOLDOWN_SECS);
    assert_eq!(parse_failure_cooldown(Some("-1")), DEFAULT_FAILURE_COOLDOWN_SECS);
}

#[test]
fn test_parse_failure_cooldown_explicit_value() {
    assert_eq!(parse_failure_cooldown(Some("0")), 0);
    assert_eq!(parse_failure_cooldown(Some("1")), 1);
    assert_eq!(parse_failure_cooldown(Some("3600")), 3600);
}

#[tokio::test(start_paused = true)]
async fn test_apply_failure_cooldown_zero_returns_immediately() {
    // FAILURE_COOLDOWN_SECS=0 must not sleep at all — under start_paused this
    // would otherwise hang forever waiting on virtual time to advance.
    let start = tokio::time::Instant::now();
    apply_failure_cooldown(Some("0")).await;
    assert!(start.elapsed() < std::time::Duration::from_millis(5));
}

#[tokio::test(start_paused = true)]
async fn test_apply_failure_cooldown_advances_virtual_clock() {
    // Verify a non-zero value actually requests a sleep of that duration.
    let start = tokio::time::Instant::now();
    apply_failure_cooldown(Some("60")).await;
    let elapsed = start.elapsed();
    assert!(elapsed >= std::time::Duration::from_secs(60), "expected ≥60s virtual sleep, got {:?}", elapsed);
}
