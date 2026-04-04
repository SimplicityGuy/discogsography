# Extractor Mutual Exclusion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent MusicBrainz extractor from running while Discogs extractor is actively extracting, by polling the Discogs health endpoint.

**Architecture:** Add a `wait_for_discogs_idle()` function that polls `http://extractor-discogs:8000/health` and checks `extraction_status`. Called in `run_musicbrainz_loop()` before each `process_musicbrainz_data()` invocation. Configurable via `DISCOGS_HEALTH_URL` env var.

**Tech Stack:** Rust, reqwest (already a dependency), tokio, serde_json

**Spec:** `docs/superpowers/specs/2026-04-03-extractor-mutual-exclusion-design.md`

---

### File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `extractor/src/config.rs` | Modify | Add `discogs_health_url` field |
| `extractor/src/extractor.rs` | Modify | Add `wait_for_discogs_idle()`, call it from `run_musicbrainz_loop()` |
| `extractor/src/tests/config_tests.rs` | Modify | Test new config field |
| `extractor/src/tests/extractor_tests.rs` | Modify | Tests for `wait_for_discogs_idle()` |

---

### Task 1: Add `discogs_health_url` to config

**Files:**
- Modify: `extractor/src/config.rs:7-23` (struct definition)
- Modify: `extractor/src/config.rs:25-44` (Default impl)
- Modify: `extractor/src/config.rs:66-124` (from_env)
- Test: `extractor/src/tests/config_tests.rs`

- [ ] **Step 1: Write the failing test**

In `extractor/src/tests/config_tests.rs`, add:

```rust
#[test]
fn test_discogs_health_url_default() {
    let config = ExtractorConfig::default();
    assert_eq!(config.discogs_health_url, "http://extractor-discogs:8000/health");
}

#[test]
fn test_discogs_health_url_from_env() {
    std::env::set_var("DISCOGS_HEALTH_URL", "http://custom-host:9999/health");
    // Need to also set required vars so from_env doesn't fail on missing secrets
    let config = ExtractorConfig::from_env().unwrap();
    assert_eq!(config.discogs_health_url, "http://custom-host:9999/health");
    std::env::remove_var("DISCOGS_HEALTH_URL");
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd extractor && cargo test test_discogs_health_url -- --nocapture 2>&1`
Expected: compilation error — `discogs_health_url` field doesn't exist

- [ ] **Step 3: Add the config field**

In `extractor/src/config.rs`, add to the `ExtractorConfig` struct (after `musicbrainz_dump_url`):

```rust
pub discogs_health_url: String,
```

In the `Default` impl, add (after `musicbrainz_dump_url`):

```rust
discogs_health_url: "http://extractor-discogs:8000/health".to_string(),
```

In `from_env()`, add (after the `musicbrainz_dump_url` line, before `let health_port`):

```rust
let discogs_health_url =
    std::env::var("DISCOGS_HEALTH_URL").unwrap_or_else(|_| "http://extractor-discogs:8000/health".to_string());
```

And add `discogs_health_url,` to the `Ok(Self { ... })` return struct (after `musicbrainz_dump_url,`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd extractor && cargo test test_discogs_health_url -- --nocapture 2>&1`
Expected: both tests PASS

- [ ] **Step 5: Commit**

```bash
git add extractor/src/config.rs extractor/src/tests/config_tests.rs
git commit -m "feat(extractor): add discogs_health_url config field"
```

---

### Task 2: Implement `wait_for_discogs_idle()`

**Files:**
- Modify: `extractor/src/extractor.rs` — add the new function
- Test: `extractor/src/tests/extractor_tests.rs`

- [ ] **Step 1: Write the failing tests**

In `extractor/src/tests/extractor_tests.rs`, add these tests. They use `mockito` for HTTP mocking (check if it's already in `Cargo.toml` dev-dependencies; if not, add `mockito = "1"` to `[dev-dependencies]`):

```rust
mod wait_for_discogs_idle_tests {
    use crate::extractor::wait_for_discogs_idle;
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::Arc;

    #[tokio::test]
    async fn test_proceeds_when_idle() {
        let mut server = mockito::Server::new_async().await;
        let mock = server
            .mock("GET", "/health")
            .with_status(200)
            .with_header("content-type", "application/json")
            .with_body(r#"{"extraction_status": "idle"}"#)
            .create_async()
            .await;

        let shutdown = Arc::new(AtomicBool::new(false));
        let result = wait_for_discogs_idle(&server.url().replace("127.0.0.1", "localhost"), &shutdown).await;

        assert!(result.is_ok());
        mock.assert_async().await;
    }

    #[tokio::test]
    async fn test_proceeds_when_completed() {
        let mut server = mockito::Server::new_async().await;
        let mock = server
            .mock("GET", "/health")
            .with_status(200)
            .with_header("content-type", "application/json")
            .with_body(r#"{"extraction_status": "completed"}"#)
            .create_async()
            .await;

        let shutdown = Arc::new(AtomicBool::new(false));
        let result = wait_for_discogs_idle(&server.url().replace("127.0.0.1", "localhost"), &shutdown).await;

        assert!(result.is_ok());
        mock.assert_async().await;
    }

    #[tokio::test]
    async fn test_proceeds_when_failed() {
        let mut server = mockito::Server::new_async().await;
        let mock = server
            .mock("GET", "/health")
            .with_status(200)
            .with_header("content-type", "application/json")
            .with_body(r#"{"extraction_status": "failed"}"#)
            .create_async()
            .await;

        let shutdown = Arc::new(AtomicBool::new(false));
        let result = wait_for_discogs_idle(&server.url().replace("127.0.0.1", "localhost"), &shutdown).await;

        assert!(result.is_ok());
        mock.assert_async().await;
    }

    #[tokio::test]
    async fn test_waits_then_proceeds_when_running_then_idle() {
        let mut server = mockito::Server::new_async().await;

        // First call returns "running", second returns "idle"
        let mock_running = server
            .mock("GET", "/health")
            .with_status(200)
            .with_header("content-type", "application/json")
            .with_body(r#"{"extraction_status": "running"}"#)
            .expect(1)
            .create_async()
            .await;

        let mock_idle = server
            .mock("GET", "/health")
            .with_status(200)
            .with_header("content-type", "application/json")
            .with_body(r#"{"extraction_status": "idle"}"#)
            .expect(1)
            .create_async()
            .await;

        let shutdown = Arc::new(AtomicBool::new(false));
        // Use 0 poll interval for tests
        let result = wait_for_discogs_idle_with_interval(
            &server.url().replace("127.0.0.1", "localhost"),
            &shutdown,
            std::time::Duration::from_millis(10),
        )
        .await;

        assert!(result.is_ok());
        mock_running.assert_async().await;
        mock_idle.assert_async().await;
    }

    #[tokio::test]
    async fn test_proceeds_after_max_unreachable_retries() {
        // No server listening — connection refused
        let shutdown = Arc::new(AtomicBool::new(false));
        let result = wait_for_discogs_idle_with_interval(
            "http://localhost:19999/health",
            &shutdown,
            std::time::Duration::from_millis(10),
        )
        .await;

        // Should still succeed (fallback after 10 retries)
        assert!(result.is_ok());
    }

    #[tokio::test]
    async fn test_respects_shutdown_signal() {
        let shutdown = Arc::new(AtomicBool::new(false));
        let shutdown_clone = shutdown.clone();

        // Set shutdown immediately so the loop exits on first check
        shutdown_clone.store(true, Ordering::SeqCst);

        let result = wait_for_discogs_idle_with_interval(
            "http://localhost:19999/health",
            &shutdown,
            std::time::Duration::from_millis(10),
        )
        .await;

        assert!(result.is_ok());
    }
}
```

- [ ] **Step 2: Add mockito dev-dependency if needed**

Check `extractor/Cargo.toml` for `mockito`. If not present, add to `[dev-dependencies]`:

```toml
mockito = "1"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd extractor && cargo test wait_for_discogs_idle -- --nocapture 2>&1`
Expected: compilation error — `wait_for_discogs_idle` and `wait_for_discogs_idle_with_interval` don't exist

- [ ] **Step 4: Implement `wait_for_discogs_idle()`**

In `extractor/src/extractor.rs`, add these two functions (before `run_musicbrainz_loop`):

```rust
const DISCOGS_POLL_INTERVAL: Duration = Duration::from_secs(60);
const DISCOGS_HEALTH_TIMEOUT: Duration = Duration::from_secs(5);
const DISCOGS_MAX_UNREACHABLE_RETRIES: u32 = 10;

/// Wait until the Discogs extractor is not actively extracting.
/// Polls the Discogs health endpoint and blocks while `extraction_status` is "running".
/// Falls back to proceeding after `DISCOGS_MAX_UNREACHABLE_RETRIES` consecutive connection failures.
pub async fn wait_for_discogs_idle(url: &str, shutdown_flag: &AtomicBool) -> Result<()> {
    wait_for_discogs_idle_with_interval(url, shutdown_flag, DISCOGS_POLL_INTERVAL).await
}

/// Internal implementation with configurable poll interval (for testing).
pub async fn wait_for_discogs_idle_with_interval(
    url: &str,
    shutdown_flag: &AtomicBool,
    poll_interval: Duration,
) -> Result<()> {
    let client = reqwest::Client::builder()
        .timeout(DISCOGS_HEALTH_TIMEOUT)
        .build()?;

    let mut unreachable_count: u32 = 0;

    loop {
        if shutdown_flag.load(Ordering::SeqCst) {
            info!("🛑 Shutdown requested, stopping Discogs health check wait");
            return Ok(());
        }

        match client.get(url).send().await {
            Ok(response) => {
                unreachable_count = 0; // Reset on any successful connection

                match response.json::<serde_json::Value>().await {
                    Ok(body) => {
                        let status = body
                            .get("extraction_status")
                            .and_then(|v| v.as_str())
                            .unwrap_or("unknown");

                        if status == "running" {
                            info!("⏳ Discogs extraction in progress, waiting before starting MusicBrainz extraction...");
                        } else {
                            info!("✅ Discogs extractor idle (status: {}), proceeding with MusicBrainz extraction", status);
                            return Ok(());
                        }
                    }
                    Err(e) => {
                        warn!("⚠️ Failed to parse Discogs health response: {}, proceeding", e);
                        return Ok(());
                    }
                }
            }
            Err(_) => {
                unreachable_count += 1;
                if unreachable_count >= DISCOGS_MAX_UNREACHABLE_RETRIES {
                    warn!(
                        "⚠️ Discogs health endpoint unreachable after {} attempts, proceeding with MusicBrainz extraction",
                        DISCOGS_MAX_UNREACHABLE_RETRIES
                    );
                    return Ok(());
                }
                warn!(
                    "⚠️ Discogs health endpoint unreachable (attempt {}/{}), retrying in {:?}...",
                    unreachable_count, DISCOGS_MAX_UNREACHABLE_RETRIES, poll_interval
                );
            }
        }

        tokio::time::sleep(poll_interval).await;
    }
}
```

Add `use std::sync::atomic::Ordering;` at the top of the file if not already present (it likely is, since `run_musicbrainz_loop` already uses it).

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd extractor && cargo test wait_for_discogs_idle -- --nocapture 2>&1`
Expected: all 6 tests PASS

Note: `test_proceeds_after_max_unreachable_retries` will take a moment since it retries 10 times with 10ms intervals.

- [ ] **Step 6: Commit**

```bash
git add extractor/src/extractor.rs extractor/src/tests/extractor_tests.rs extractor/Cargo.toml extractor/Cargo.lock
git commit -m "feat(extractor): add wait_for_discogs_idle() with health polling"
```

---

### Task 3: Integrate into `run_musicbrainz_loop()`

**Files:**
- Modify: `extractor/src/extractor.rs:800-879` — add calls before each `process_musicbrainz_data()`

- [ ] **Step 1: Add wait call before initial extraction**

In `run_musicbrainz_loop()` in `extractor/src/extractor.rs`, add the wait call after the shutdown flag setup and the `"Starting MusicBrainz extraction"` log line (line ~822), but before the `process_musicbrainz_data` call (line ~824):

```rust
    info!("🎵 Starting MusicBrainz extraction...");

    // Wait for Discogs extractor to finish before starting MusicBrainz
    wait_for_discogs_idle(&config.discogs_health_url, &shutdown_flag).await?;

    let success =
        process_musicbrainz_data(config.clone(), state.clone(), shutdown_flag.clone(), force_reprocess, mq_factory.clone(), compiled_rules.clone())
            .await?;
```

- [ ] **Step 2: Add wait call before periodic extraction**

In the periodic check loop's `sleep` arm (around line ~848), add the wait before `process_musicbrainz_data`:

```rust
            _ = sleep(check_interval) => {
                info!("🔄 Starting periodic check for new MusicBrainz dumps...");
                // Wait for Discogs extractor to finish before starting MusicBrainz
                if let Err(e) = wait_for_discogs_idle(&config.discogs_health_url, &shutdown_flag).await {
                    error!("❌ Failed to check Discogs health: {}", e);
                }
                let start = Instant::now();
                match process_musicbrainz_data(...).await {
```

- [ ] **Step 3: Add wait call before triggered extraction**

In the trigger arm (around line ~862), add the same wait:

```rust
            trigger_force_reprocess = wait_for_trigger(&trigger) => {
                info!("🔄 MusicBrainz extraction triggered via API (force_reprocess={})...", trigger_force_reprocess);
                // Wait for Discogs extractor to finish before starting MusicBrainz
                if let Err(e) = wait_for_discogs_idle(&config.discogs_health_url, &shutdown_flag).await {
                    error!("❌ Failed to check Discogs health: {}", e);
                }
                let start = Instant::now();
                match process_musicbrainz_data(...).await {
```

- [ ] **Step 4: Run the full extractor test suite**

Run: `cd extractor && cargo test 2>&1`
Expected: all tests pass (existing + new)

- [ ] **Step 5: Run clippy**

Run: `cd extractor && cargo clippy -- -D warnings 2>&1`
Expected: no warnings

- [ ] **Step 6: Commit**

```bash
git add extractor/src/extractor.rs
git commit -m "feat(extractor): integrate Discogs health check into MusicBrainz loop"
```

---

### Task 4: Final verification

- [ ] **Step 1: Run the full test suite**

Run: `just test-extractor 2>&1`
Expected: all tests pass

- [ ] **Step 2: Run formatting check**

Run: `just extractor-fmt-check 2>&1`
Expected: no formatting issues

- [ ] **Step 3: Run linting**

Run: `just extractor-lint 2>&1`
Expected: no warnings/errors

- [ ] **Step 4: Commit any formatting fixes if needed**

```bash
just extractor-fmt
git add -A
git commit -m "style(extractor): format code"
```
