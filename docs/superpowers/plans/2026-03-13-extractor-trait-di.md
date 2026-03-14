# Extractor Trait-Based Dependency Injection Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the Rust extractor to use trait-based dependency injection so orchestration functions (`process_discogs_data`, `process_single_file`) can be unit tested with mocks, raising coverage from ~87% to ~95%.

**Architecture:** Extract `MessagePublisher` and `DataSource` traits from `MessageQueue` and `Downloader` concrete types. Add a `MessageQueueFactory` trait for constructing publishers. Inject these traits into orchestration functions via parameters instead of constructing concrete types internally. Use `mockall` for auto-generated mocks in tests. Mocks are gated behind a `test-support` Cargo feature flag (not `cfg(test)`) so they are available in both unit tests and integration tests.

**Tech Stack:** Rust 2024 (native `async fn` in traits — no `async-trait` crate needed), `mockall`, `tokio`, `lapin` (AMQP)

**Issue:** [#97](https://github.com/SimplicityGuy/discogsography/issues/97)

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `extractor/Cargo.toml` | Add `mockall` behind `test-support` feature flag |
| Modify | `extractor/src/message_queue.rs` | Extract `MessagePublisher` trait from `MessageQueue` |
| Modify | `extractor/src/downloader.rs` | Extract `DataSource` trait from `Downloader` |
| Modify | `extractor/src/extractor.rs` | Accept trait objects in orchestration fns; add `MessageQueueFactory` trait; make `message_publisher` public |
| Modify | `extractor/src/main.rs` | Extract `run()` fn; wire concrete types to new trait-based signatures |
| Modify | `extractor/src/lib.rs` | No changes expected (modules already re-exported) |
| Modify | `extractor/tests/mock_helpers.rs` | Add `MockMqFactory` for integration tests |
| Create | `extractor/tests/extractor_di_test.rs` | Mock-based tests for orchestration functions |

---

## Important Design Decisions

### Why a feature flag instead of `cfg(test)`?

The `#[cfg_attr(test, mockall::automock)]` pattern only generates mock structs when the **library crate itself** is compiled in test mode. Integration tests (in `tests/`) compile the library in **normal mode**, so `MockMessagePublisher` and `MockDataSource` would not exist. Using a feature flag (`test-support`) solves this:

```toml
[features]
test-support = ["mockall"]

[dev-dependencies]
extractor = { path = ".", features = ["test-support"] }
```

Traits use `#[cfg_attr(feature = "test-support", mockall::automock)]` instead of `#[cfg_attr(test, ...)]`.

### Why no `async-trait` crate?

This project uses Rust edition 2024 (rustc 1.94). Native `async fn` in traits is fully supported. The `mockall` crate (0.13+) is compatible with native async trait methods. No polyfill needed.

### `mq_factory` parameter type: `Arc<dyn MessageQueueFactory>`

The `process_discogs_data` function spawns tasks via `tokio::spawn`, which requires `'static` bounds. A borrowed `&dyn MessageQueueFactory` cannot cross this boundary. Therefore `mq_factory` uses `Arc<dyn MessageQueueFactory>` throughout — in `process_discogs_data`, `run_extraction_loop`, and `main.rs`.

---

## Chunk 1: Dependencies and `MessagePublisher` Trait

### Task 1: Add `mockall` with feature flag

**Files:**
- Modify: `extractor/Cargo.toml`

- [ ] **Step 1: Add feature flag and mockall dependency**

Add a `[features]` section and update `[dev-dependencies]`:

```toml
# After [package] section, before [dependencies]:
[features]
test-support = ["mockall"]

# In [dependencies] section, after the "# Utilities" group:
# Mock generation for trait-based testing (behind feature flag)
mockall = { version = "0.13", optional = true }

# In [dev-dependencies] section, add self-dependency with feature:
extractor = { path = ".", features = ["test-support"] }
```

- [ ] **Step 2: Verify it compiles**

Run: `cd extractor && cargo check`
Expected: Success, no errors

- [ ] **Step 3: Commit**

```bash
git add extractor/Cargo.toml
git commit -m "chore(extractor): add mockall with test-support feature flag for DI refactor (#97)"
```

---

### Task 2: Extract `MessagePublisher` trait

**Files:**
- Modify: `extractor/src/message_queue.rs`

This is the core enabler. We define a trait with all public methods that orchestration code calls, then implement it for `MessageQueue`. No logic changes — just mechanical extraction.

- [ ] **Step 1: Write the trait definition**

Add this **above** the `impl MessageQueue` block (after the struct definition, around line 21):

```rust
use std::collections::HashMap;

#[cfg_attr(feature = "test-support", mockall::automock)]
pub trait MessagePublisher: Send + Sync {
    async fn setup_exchange(&self, data_type: DataType) -> Result<()>;
    async fn publish(&self, message: Message, data_type: DataType) -> Result<()>;
    async fn publish_batch(&self, messages: Vec<DataMessage>, data_type: DataType) -> Result<()>;
    async fn send_file_complete(
        &self,
        data_type: DataType,
        file_name: &str,
        total_processed: u64,
    ) -> Result<()>;
    async fn send_extraction_complete(
        &self,
        version: &str,
        started_at: chrono::DateTime<chrono::Utc>,
        record_counts: HashMap<String, u64>,
    ) -> Result<()>;
    async fn close(&self) -> Result<()>;
}
```

Note: No `#[async_trait]` needed — Rust 2024 edition supports `async fn` in traits natively.

- [ ] **Step 2: Implement the trait for `MessageQueue`**

Split the existing `impl MessageQueue` into two blocks:

1. A private `impl MessageQueue` block containing only internal methods that are NOT part of the trait: `new`, `normalize_amqp_url`, `exchange_name`, `connect`, `try_connect`, `message_properties`, `get_channel`.

2. An `impl MessagePublisher for MessageQueue` block containing: `setup_exchange`, `publish`, `publish_batch`, `send_file_complete`, `send_extraction_complete`, `close`.

Move each method body unchanged — only the `impl` header changes. Internal methods stay on `impl MessageQueue` because they are implementation details that use `&self` access to private fields.

The trait methods call internal helpers. Since `self` inside the trait impl is `&MessageQueue`, calls like `self.get_channel().await?` and `Self::exchange_name(data_type)` continue to work because Rust resolves inherent methods on the concrete type.

- [ ] **Step 3: Verify it compiles**

Run: `cd extractor && cargo check`
Expected: Success

- [ ] **Step 4: Run all existing tests**

Run: `cd extractor && cargo test`
Expected: All tests pass (no behavior change)

- [ ] **Step 5: Commit**

```bash
git add extractor/src/message_queue.rs
git commit -m "refactor(extractor): extract MessagePublisher trait from MessageQueue (#97)"
```

---

## Chunk 2: `DataSource` Trait and `MessageQueueFactory`

### Task 3: Extract `DataSource` trait from `Downloader`

**Files:**
- Modify: `extractor/src/downloader.rs`

- [ ] **Step 1: Write the trait definition**

Add this above the `impl Downloader` block (after the struct definition, around line 32):

```rust
#[cfg_attr(feature = "test-support", mockall::automock)]
pub trait DataSource: Send + Sync {
    async fn list_s3_files(&mut self) -> Result<Vec<S3FileInfo>>;
    fn get_latest_monthly_files(&self, files: &[S3FileInfo]) -> Result<Vec<S3FileInfo>>;
    async fn download_discogs_data(&mut self) -> Result<Vec<String>>;
    fn set_state_marker(&mut self, state_marker: StateMarker, marker_path: PathBuf);
    fn take_state_marker(&mut self) -> Option<StateMarker>;
}
```

**Design note:** The existing `with_state_marker(self, ...) -> Self` builder pattern is incompatible with `dyn DataSource` because trait objects cannot return `Self where Self: Sized`. The replacement `set_state_marker(&mut self, ...)` achieves the same effect without consuming self.

- [ ] **Step 2: Implement the trait for `Downloader`**

Add a new `impl DataSource for Downloader` block. Move `list_s3_files`, `get_latest_monthly_files`, and `download_discogs_data` method bodies from the inherent impl into the trait impl.

Add two new method implementations:

```rust
fn set_state_marker(&mut self, state_marker: StateMarker, marker_path: PathBuf) {
    self.state_marker = Some(state_marker);
    self.marker_path = Some(marker_path);
}

fn take_state_marker(&mut self) -> Option<StateMarker> {
    self.state_marker.take()
}
```

Keep the following on the inherent `impl Downloader` (NOT in the trait): `new`, `new_with_base_url`, `with_state_marker` (keep for backwards compat — internally calls `set_state_marker`), `save_state_marker`, `should_download`, `download_file`, `save_metadata`.

- [ ] **Step 3: Verify it compiles**

Run: `cd extractor && cargo check`
Expected: Success

- [ ] **Step 4: Run all existing tests**

Run: `cd extractor && cargo test`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add extractor/src/downloader.rs
git commit -m "refactor(extractor): extract DataSource trait from Downloader (#97)"
```

---

### Task 4: Add `MessageQueueFactory` trait

**Files:**
- Modify: `extractor/src/extractor.rs`

The factory pattern lets tests inject mock publishers without needing a live AMQP connection. `process_discogs_data` creates `MessageQueue` instances in two places — the factory abstracts this.

- [ ] **Step 1: Add the factory trait and default implementation**

Add at the top of `extractor.rs` (after imports):

```rust
use crate::message_queue::{MessagePublisher, MessageQueue};
use crate::downloader::DataSource;

/// Factory for creating MessagePublisher instances (enables DI for testing)
#[cfg_attr(feature = "test-support", mockall::automock)]
pub trait MessageQueueFactory: Send + Sync {
    async fn create(&self, url: &str) -> Result<Arc<dyn MessagePublisher>>;
}

/// Default factory that creates real MessageQueue connections
pub struct DefaultMessageQueueFactory;

impl MessageQueueFactory for DefaultMessageQueueFactory {
    async fn create(&self, url: &str) -> Result<Arc<dyn MessagePublisher>> {
        Ok(Arc::new(MessageQueue::new(url, 3).await?))
    }
}
```

- [ ] **Step 2: Verify it compiles**

Run: `cd extractor && cargo check`
Expected: Success

- [ ] **Step 3: Commit**

```bash
git add extractor/src/extractor.rs
git commit -m "feat(extractor): add MessageQueueFactory trait for dependency injection (#97)"
```

---

## Chunk 3: Inject Traits into Orchestration Functions

> **Note:** Tasks 5-8 form an atomic unit. The code will not compile until Task 8 is complete. Do NOT attempt to run tests between tasks 5-7. Run `cargo check` only at Task 8 Step 5.

### Task 5: Refactor `process_single_file` to accept `Arc<dyn MessagePublisher>`

**Files:**
- Modify: `extractor/src/extractor.rs:255-347`

This is the simpler of the two orchestration functions. It currently creates `MessageQueue::new()` on line 276. We change it to accept a pre-built publisher.

- [ ] **Step 1: Change function signature and remove internal MQ construction**

Change from:

```rust
async fn process_single_file(
    file_name: &str,
    config: Arc<ExtractorConfig>,
    state: Arc<RwLock<ExtractorState>>,
    state_marker: Arc<tokio::sync::Mutex<StateMarker>>,
    marker_path: PathBuf,
) -> Result<()> {
```

To:

```rust
pub async fn process_single_file(
    file_name: &str,
    config: Arc<ExtractorConfig>,
    state: Arc<RwLock<ExtractorState>>,
    state_marker: Arc<tokio::sync::Mutex<StateMarker>>,
    marker_path: PathBuf,
    mq: Arc<dyn MessagePublisher>,
) -> Result<()> {
```

Also made `pub` so tests can call it directly.

- [ ] **Step 2: Remove internal MessageQueue construction**

Delete the `MessageQueue::new(...)` line (around line 276):

```rust
// DELETE this line:
let mq = Arc::new(MessageQueue::new(&config.amqp_connection, 3).await.context("Failed to connect to message queue")?);
```

The `mq` parameter now provides the publisher. All remaining uses of `mq` (`mq.setup_exchange(...)`, `mq.send_file_complete(...)`, `mq.close()`) work unchanged because `Arc<dyn MessagePublisher>` exposes the same methods.

---

### Task 6: Refactor `message_publisher` to accept `Arc<dyn MessagePublisher>`

**Files:**
- Modify: `extractor/src/extractor.rs:436-457`

- [ ] **Step 1: Change signature and visibility**

Change from:

```rust
async fn message_publisher(
    mut receiver: mpsc::Receiver<Vec<DataMessage>>,
    mq: Arc<MessageQueue>,
    data_type: DataType,
    state: Arc<RwLock<ExtractorState>>,
) -> Result<()> {
```

To:

```rust
pub async fn message_publisher(
    mut receiver: mpsc::Receiver<Vec<DataMessage>>,
    mq: Arc<dyn MessagePublisher>,
    data_type: DataType,
    state: Arc<RwLock<ExtractorState>>,
) -> Result<()> {
```

The function body is unchanged — it only calls `mq.publish_batch(batch, data_type)` which is on the trait.

---

### Task 7: Refactor `process_discogs_data` to accept trait objects

**Files:**
- Modify: `extractor/src/extractor.rs:29-252`

This is the most involved change. The function currently constructs both a `Downloader` and `MessageQueue` internally.

- [ ] **Step 1: Change function signature**

Change from:

```rust
pub async fn process_discogs_data(
    config: Arc<ExtractorConfig>,
    state: Arc<RwLock<ExtractorState>>,
    shutdown: Arc<tokio::sync::Notify>,
    force_reprocess: bool,
) -> Result<bool> {
```

To:

```rust
pub async fn process_discogs_data(
    config: Arc<ExtractorConfig>,
    state: Arc<RwLock<ExtractorState>>,
    shutdown: Arc<tokio::sync::Notify>,
    force_reprocess: bool,
    downloader: &mut dyn DataSource,
    mq_factory: Arc<dyn MessageQueueFactory>,
) -> Result<bool> {
```

Note: `mq_factory` is `Arc<dyn MessageQueueFactory>` (not `&dyn`) because it must be cloneable into `tokio::spawn` tasks which require `'static`.

- [ ] **Step 2: Replace `Downloader::new()` usage**

Delete line 49:

```rust
// DELETE:
let mut downloader = Downloader::new(config.discogs_root.clone()).await?;
```

The `downloader` parameter now provides this.

- [ ] **Step 3: Replace `downloader.with_state_marker()` with `set_state_marker()`**

Change line 96 from:

```rust
downloader = downloader.with_state_marker(state_marker, marker_path.clone());
```

To:

```rust
downloader.set_state_marker(state_marker, marker_path.clone());
```

- [ ] **Step 4: Replace `downloader.state_marker.take()` with trait method**

Change line 102 from:

```rust
let mut state_marker = downloader.state_marker.take().unwrap();
```

To:

```rust
let mut state_marker = downloader.take_state_marker()
    .ok_or_else(|| anyhow::anyhow!("State marker missing after download"))?;
```

- [ ] **Step 5: Replace both `MessageQueue::new()` calls with `mq_factory.create()`**

There are two places where `MessageQueue::new()` is called directly:

**Location 1: "all pending files already processed" early return (around lines 130-143):**

Change `MessageQueue::new(&config.amqp_connection, 3).await` to `mq_factory.create(&config.amqp_connection).await`. Keep the same match arm structure.

**Location 2: Final extraction_complete block (around lines 233-248):**

Same replacement — `MessageQueue::new(...)` becomes `mq_factory.create(...)`.

- [ ] **Step 6: Update the spawned task loop to use `mq_factory`**

Change the task spawn loop (around lines 157-176) so each spawned task creates its own publisher via the factory:

```rust
let mq_factory = mq_factory.clone();

let task: tokio::task::JoinHandle<Result<()>> = tokio::spawn(async move {
    let _permit = semaphore.acquire().await?;
    let mq = mq_factory.create(&config.amqp_connection).await
        .context("Failed to connect to message queue")?;
    process_single_file(&file, config, state, state_marker_arc.clone(), marker_path.clone(), mq).await?;
    info!("✅ Completed processing: {}", file);
    Ok(())
});
```

Note: `config` is already cloned into the task (line 160), so `config.amqp_connection` is available. The `mq_factory.clone()` clones the `Arc`, which is cheap.

---

### Task 8: Update `run_extraction_loop` and `main.rs` to wire dependencies

**Files:**
- Modify: `extractor/src/extractor.rs:528-576` (`run_extraction_loop`)
- Modify: `extractor/src/main.rs`

- [ ] **Step 1: Update `run_extraction_loop` signature**

Change from:

```rust
pub async fn run_extraction_loop(
    config: Arc<ExtractorConfig>,
    state: Arc<RwLock<ExtractorState>>,
    shutdown: Arc<tokio::sync::Notify>,
    force_reprocess: bool,
) -> Result<()> {
```

To:

```rust
pub async fn run_extraction_loop(
    config: Arc<ExtractorConfig>,
    state: Arc<RwLock<ExtractorState>>,
    shutdown: Arc<tokio::sync::Notify>,
    force_reprocess: bool,
    mq_factory: Arc<dyn MessageQueueFactory>,
) -> Result<()> {
```

- [ ] **Step 2: Create downloader inside `run_extraction_loop` and pass to `process_discogs_data`**

For the initial call (line 537), create a `Downloader` and pass it:

```rust
let mut downloader = Downloader::new(config.discogs_root.clone()).await?;
let success = process_discogs_data(
    config.clone(), state.clone(), shutdown.clone(), force_reprocess,
    &mut downloader, mq_factory.clone(),
).await?;
```

For the periodic loop call (line 556), create a fresh downloader each iteration:

```rust
let mut downloader = match Downloader::new(config.discogs_root.clone()).await {
    Ok(dl) => dl,
    Err(e) => {
        error!("❌ Failed to create downloader for periodic check: {}", e);
        continue;
    }
};
match process_discogs_data(config.clone(), state.clone(), shutdown.clone(), false, &mut downloader, mq_factory.clone()).await {
    // ... existing match arms ...
}
```

- [ ] **Step 3: Extract `run()` function from `main()` and wire `DefaultMessageQueueFactory`**

Move the core logic from `main()` into a testable function:

```rust
async fn run(args: Args) -> Result<()> {
    // Load configuration
    let config = Arc::new(ExtractorConfig::from_env()?);

    // Initialize shared state
    let state = Arc::new(RwLock::new(extractor::ExtractorState::default()));

    // Start health server
    let health_server = HealthServer::new(config.health_port, state.clone());
    let health_handle = tokio::spawn(async move {
        if let Err(e) = health_server.run().await {
            error!("❌ Health server error: {}", e);
        }
    });

    // Set up signal handlers
    let shutdown = setup_shutdown_handler();

    // Create factory for message queue connections
    let mq_factory: Arc<dyn extractor::MessageQueueFactory> =
        Arc::new(extractor::DefaultMessageQueueFactory);

    // Run the main extraction loop
    let extraction_result = extractor::run_extraction_loop(
        config.clone(), state.clone(), shutdown.clone(),
        args.force_reprocess, mq_factory,
    ).await;

    // Cleanup
    info!("🛑 Shutting down rust-extractor...");
    health_handle.abort();

    extraction_result
}

#[tokio::main]
async fn main() -> Result<()> {
    let args = Args::parse();

    // Initialize tracing
    let log_level = std::env::var("LOG_LEVEL").unwrap_or_else(|_| "INFO".to_string());
    let filter = build_tracing_filter(&log_level);
    tracing_subscriber::fmt()
        .with_env_filter(filter)
        .with_target(false)
        .with_thread_ids(false)
        .with_line_number(true)
        .json()
        .init();

    print_ascii_art();
    info!("🚀 Starting Rust-based Discogs data extractor with high performance");

    match run(args).await {
        Ok(_) => {
            info!("✅ Rust-extractor service shutdown complete");
            Ok(())
        }
        Err(e) => {
            error!("❌ Rust-extractor failed: {}", e);
            std::process::exit(1);
        }
    }
}
```

- [ ] **Step 4: Verify full compilation**

Run: `cd extractor && cargo check`
Expected: Success — all callers now pass the required trait objects

- [ ] **Step 5: Run all existing tests**

Run: `cd extractor && cargo test`
Expected: All existing tests pass

- [ ] **Step 6: Commit**

```bash
git add extractor/src/extractor.rs extractor/src/main.rs
git commit -m "refactor(extractor): inject trait objects into orchestration functions (#97)"
```

---

## Chunk 4: Mock-Based Tests

### Task 9: Update `mock_helpers.rs`

**Files:**
- Modify: `extractor/tests/mock_helpers.rs`

The existing hand-rolled `MockMessageQueue` and `MockDownloader` don't implement our new traits. The `mockall`-generated `MockMessagePublisher` and `MockDataSource` replace them for trait-based testing. Keep the old mocks if other test files reference them; otherwise they can be removed later.

- [ ] **Step 1: Add `MockMqFactory` implementation**

Add to `mock_helpers.rs`:

```rust
use std::sync::Arc;
use extractor::message_queue::MessagePublisher;
use extractor::extractor::MessageQueueFactory;

/// Mock factory that returns a pre-configured mock publisher.
/// Each call to `create()` returns a clone of the same Arc<dyn MessagePublisher>.
pub struct MockMqFactory {
    pub publisher: Arc<dyn MessagePublisher>,
}

impl MessageQueueFactory for MockMqFactory {
    async fn create(&self, _url: &str) -> anyhow::Result<Arc<dyn MessagePublisher>> {
        Ok(self.publisher.clone())
    }
}
```

- [ ] **Step 2: Run tests**

Run: `cd extractor && cargo test`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add extractor/tests/mock_helpers.rs
git commit -m "refactor(extractor): add MockMqFactory for trait-based DI tests (#97)"
```

---

### Task 10: Write mock-based tests for `process_single_file` and `message_publisher`

**Files:**
- Create: `extractor/tests/extractor_di_test.rs`

- [ ] **Step 1: Write test file with helper and imports**

```rust
use std::sync::Arc;
use tokio::sync::{Mutex, RwLock};
use tempfile::TempDir;
use extractor::extractor::{process_single_file, message_publisher, ExtractorState};
use extractor::config::ExtractorConfig;
use extractor::state_marker::StateMarker;
use extractor::message_queue::MockMessagePublisher;
use extractor::types::{DataType, DataMessage};

mod mock_helpers;
use mock_helpers::MockMqFactory;

/// Helper to create a test config with all required fields.
/// ExtractorConfig has 9 fields — all must be provided.
fn test_config(root: &std::path::Path) -> ExtractorConfig {
    ExtractorConfig {
        amqp_connection: "amqp://localhost:5672/%2F".to_string(),
        discogs_root: root.to_path_buf(),
        periodic_check_days: 1,
        health_port: 0,
        max_workers: 2,
        batch_size: 100,
        queue_size: 100,
        progress_log_interval: 1000,
        state_save_interval: 1000,
    }
}
```

- [ ] **Step 2: Write test for `process_single_file` MQ setup**

```rust
#[tokio::test]
async fn test_process_single_file_mq_setup_called() {
    // Verifies that process_single_file calls setup_exchange on the provided publisher.
    // The test will fail at parsing (file doesn't exist on disk) — that's expected.
    // We're testing that MQ setup happens before parsing starts.

    let temp_dir = TempDir::new().unwrap();
    let config = Arc::new(test_config(temp_dir.path()));
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let state_marker = Arc::new(Mutex::new(StateMarker::new("20260101".to_string())));
    let marker_path = temp_dir.path().join("marker.json");

    let mut mock_mq = MockMessagePublisher::new();
    mock_mq.expect_setup_exchange()
        .withf(|dt| *dt == DataType::Artists)
        .times(1)
        .returning(|_| Ok(()));
    // These may or may not be called depending on how far execution gets
    mock_mq.expect_close().times(..).returning(|| Ok(()));
    mock_mq.expect_publish_batch().returning(|_, _| Ok(()));
    mock_mq.expect_send_file_complete().returning(|_, _, _| Ok(()));

    let mq: Arc<dyn extractor::message_queue::MessagePublisher> = Arc::new(mock_mq);

    let result = process_single_file(
        "discogs_20260101_artists.xml.gz",
        config, state, state_marker, marker_path, mq,
    ).await;

    // Error expected — file doesn't exist on disk
    assert!(result.is_err());
    // setup_exchange mock expectation (times(1)) is verified on drop
}
```

- [ ] **Step 3: Write tests for `message_publisher` error handling and success path**

```rust
#[tokio::test]
async fn test_message_publisher_increments_error_count_on_failure() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    let mut mock_mq = MockMessagePublisher::new();
    mock_mq.expect_publish_batch()
        .times(1)
        .returning(|_, _| Err(anyhow::anyhow!("AMQP connection lost")));

    let mq: Arc<dyn extractor::message_queue::MessagePublisher> = Arc::new(mock_mq);
    let (sender, receiver) = tokio::sync::mpsc::channel::<Vec<DataMessage>>(10);

    // Send one batch then drop sender to close channel
    sender.send(vec![]).await.unwrap();
    drop(sender);

    let result = message_publisher(receiver, mq, DataType::Artists, state.clone()).await;

    assert!(result.is_err());
    let s = state.read().await;
    assert_eq!(s.error_count, 1);
}

#[tokio::test]
async fn test_message_publisher_success_path() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));

    let mut mock_mq = MockMessagePublisher::new();
    mock_mq.expect_publish_batch()
        .times(3)
        .returning(|_, _| Ok(()));

    let mq: Arc<dyn extractor::message_queue::MessagePublisher> = Arc::new(mock_mq);
    let (sender, receiver) = tokio::sync::mpsc::channel::<Vec<DataMessage>>(10);

    for _ in 0..3 {
        sender.send(vec![]).await.unwrap();
    }
    drop(sender);

    let result = message_publisher(receiver, mq, DataType::Artists, state.clone()).await;

    assert!(result.is_ok());
    let s = state.read().await;
    assert_eq!(s.error_count, 0);
}
```

- [ ] **Step 4: Run tests**

Run: `cd extractor && cargo test extractor_di_test -- --nocapture`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add extractor/tests/extractor_di_test.rs
git commit -m "test(extractor): add mock-based tests for process_single_file and message_publisher (#97)"
```

---

### Task 11: Write mock-based tests for `process_discogs_data`

**Files:**
- Modify: `extractor/tests/extractor_di_test.rs`

- [ ] **Step 1: Write test for empty files early return**

This tests the path where `get_latest_monthly_files` returns an empty list — `process_discogs_data` returns `Ok(true)` immediately without touching AMQP.

```rust
use extractor::downloader::{MockDataSource, S3FileInfo};

#[tokio::test]
async fn test_process_discogs_data_empty_files() {
    let temp_dir = TempDir::new().unwrap();
    let config = Arc::new(test_config(temp_dir.path()));
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let shutdown = Arc::new(tokio::sync::Notify::new());

    let mut mock_dl = MockDataSource::new();
    mock_dl.expect_list_s3_files()
        .times(1)
        .returning(|| Ok(vec![]));
    mock_dl.expect_get_latest_monthly_files()
        .times(1)
        .returning(|_| Ok(vec![]));

    // MQ factory — should NOT be called since we exit before AMQP
    let mock_mq = MockMessagePublisher::new();
    let factory = Arc::new(MockMqFactory { publisher: Arc::new(mock_mq) });

    let result = extractor::extractor::process_discogs_data(
        config, state, shutdown, false,
        &mut mock_dl, factory,
    ).await;

    assert!(result.is_ok());
    assert!(result.unwrap()); // Returns true (no files = success)
}
```

- [ ] **Step 2: Write test for the "all pending files already complete" path**

This tests the code path where a state marker exists with `ProcessingDecision::Continue` but all individual files are already marked complete in the state marker (i.e., `pending_files` is empty). This is the path at lines 122-146 that sends `extraction_complete` via AMQP.

**Important:** This is different from the `ProcessingDecision::Skip` path (lines 82-84) which returns `Ok(true)` immediately without touching AMQP. The `Skip` path fires when `complete_extraction()` was already called; this path fires when processing was started but all files were individually completed.

```rust
#[tokio::test]
async fn test_process_discogs_data_pending_files_empty_sends_extraction_complete() {
    let temp_dir = TempDir::new().unwrap();
    let config = Arc::new(test_config(temp_dir.path()));
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let shutdown = Arc::new(tokio::sync::Notify::new());

    // Create a state marker that has started processing and completed all files,
    // but has NOT called complete_extraction() — so should_process() returns Continue
    let mut marker = StateMarker::new("20260101".to_string());
    marker.start_processing(4);
    // Mark all 4 files as individually completed
    marker.start_file_processing("discogs_20260101_artists.xml.gz");
    marker.complete_file_processing("discogs_20260101_artists.xml.gz", 1000);
    marker.start_file_processing("discogs_20260101_labels.xml.gz");
    marker.complete_file_processing("discogs_20260101_labels.xml.gz", 500);
    marker.start_file_processing("discogs_20260101_masters.xml.gz");
    marker.complete_file_processing("discogs_20260101_masters.xml.gz", 300);
    marker.start_file_processing("discogs_20260101_releases.xml.gz");
    marker.complete_file_processing("discogs_20260101_releases.xml.gz", 2000);
    let marker_path = StateMarker::file_path(temp_dir.path(), "20260101");
    marker.save(&marker_path).await.unwrap();

    let mut mock_dl = MockDataSource::new();
    mock_dl.expect_list_s3_files()
        .returning(|| Ok(vec![
            S3FileInfo { name: "data/discogs_20260101_artists.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_labels.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_masters.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_releases.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_CHECKSUM.txt".to_string(), size: 100 },
        ]));
    mock_dl.expect_get_latest_monthly_files()
        .returning(|_| Ok(vec![
            S3FileInfo { name: "discogs_20260101_artists.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "discogs_20260101_labels.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "discogs_20260101_masters.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "discogs_20260101_releases.xml.gz".to_string(), size: 1000 },
        ]));
    mock_dl.expect_set_state_marker()
        .times(1)
        .returning(|_, _| ());
    mock_dl.expect_download_discogs_data()
        .times(1)
        .returning(|| Ok(vec![
            "discogs_20260101_artists.xml.gz".to_string(),
            "discogs_20260101_labels.xml.gz".to_string(),
            "discogs_20260101_masters.xml.gz".to_string(),
            "discogs_20260101_releases.xml.gz".to_string(),
        ]));
    mock_dl.expect_take_state_marker()
        .times(1)
        .returning(|| {
            let mut m = StateMarker::new("20260101".to_string());
            m.start_processing(4);
            m.start_file_processing("discogs_20260101_artists.xml.gz");
            m.complete_file_processing("discogs_20260101_artists.xml.gz", 1000);
            m.start_file_processing("discogs_20260101_labels.xml.gz");
            m.complete_file_processing("discogs_20260101_labels.xml.gz", 500);
            m.start_file_processing("discogs_20260101_masters.xml.gz");
            m.complete_file_processing("discogs_20260101_masters.xml.gz", 300);
            m.start_file_processing("discogs_20260101_releases.xml.gz");
            m.complete_file_processing("discogs_20260101_releases.xml.gz", 2000);
            Some(m)
        });

    // Mock MQ — extraction_complete should be called via the factory
    let mut mock_mq = MockMessagePublisher::new();
    mock_mq.expect_send_extraction_complete()
        .times(1)
        .returning(|_, _, _| Ok(()));
    mock_mq.expect_close()
        .returning(|| Ok(()));

    let factory = Arc::new(MockMqFactory { publisher: Arc::new(mock_mq) });

    let result = extractor::extractor::process_discogs_data(
        config, state, shutdown, false,
        &mut mock_dl, factory,
    ).await;

    assert!(result.is_ok());
    assert!(result.unwrap()); // Returns true
}
```

- [ ] **Step 3: Write test for `ProcessingDecision::Skip` path**

This tests the path where extraction was already fully completed — returns `Ok(true)` without touching AMQP at all.

```rust
#[tokio::test]
async fn test_process_discogs_data_skip_when_already_complete() {
    let temp_dir = TempDir::new().unwrap();
    let config = Arc::new(test_config(temp_dir.path()));
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let shutdown = Arc::new(tokio::sync::Notify::new());

    // Create a fully completed state marker (both processing and extraction done)
    let mut marker = StateMarker::new("20260101".to_string());
    marker.complete_processing();
    marker.complete_extraction();
    let marker_path = StateMarker::file_path(temp_dir.path(), "20260101");
    marker.save(&marker_path).await.unwrap();

    let mut mock_dl = MockDataSource::new();
    mock_dl.expect_list_s3_files()
        .returning(|| Ok(vec![
            S3FileInfo { name: "data/discogs_20260101_artists.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_labels.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_masters.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_releases.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_CHECKSUM.txt".to_string(), size: 100 },
        ]));
    mock_dl.expect_get_latest_monthly_files()
        .returning(|_| Ok(vec![
            S3FileInfo { name: "discogs_20260101_artists.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "discogs_20260101_labels.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "discogs_20260101_masters.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "discogs_20260101_releases.xml.gz".to_string(), size: 1000 },
        ]));
    // download_discogs_data should NOT be called — Skip exits early
    // set_state_marker should NOT be called either

    // MQ not needed — Skip path doesn't touch AMQP
    let mock_mq = MockMessagePublisher::new();
    let factory = Arc::new(MockMqFactory { publisher: Arc::new(mock_mq) });

    let result = extractor::extractor::process_discogs_data(
        config, state, shutdown, false,
        &mut mock_dl, factory,
    ).await;

    assert!(result.is_ok());
    assert!(result.unwrap()); // Returns true (skipped)
    // Mock expectations verify download_discogs_data was NOT called
}
```

- [ ] **Step 4: Write test for force reprocess path**

```rust
#[tokio::test]
async fn test_process_discogs_data_force_reprocess_bypasses_skip() {
    let temp_dir = TempDir::new().unwrap();
    let config = Arc::new(test_config(temp_dir.path()));
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let shutdown = Arc::new(tokio::sync::Notify::new());

    // Create a fully completed state marker — force_reprocess should ignore it
    let mut marker = StateMarker::new("20260101".to_string());
    marker.complete_processing();
    marker.complete_extraction();
    let marker_path = StateMarker::file_path(temp_dir.path(), "20260101");
    marker.save(&marker_path).await.unwrap();

    let mut mock_dl = MockDataSource::new();
    mock_dl.expect_list_s3_files()
        .returning(|| Ok(vec![
            S3FileInfo { name: "data/discogs_20260101_artists.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_labels.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_masters.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_releases.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_CHECKSUM.txt".to_string(), size: 100 },
        ]));
    mock_dl.expect_get_latest_monthly_files()
        .returning(|_| Ok(vec![
            S3FileInfo { name: "discogs_20260101_artists.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "discogs_20260101_labels.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "discogs_20260101_masters.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "discogs_20260101_releases.xml.gz".to_string(), size: 1000 },
        ]));
    // force_reprocess=true should call set_state_marker and download
    mock_dl.expect_set_state_marker()
        .times(1)
        .returning(|_, _| ());
    mock_dl.expect_download_discogs_data()
        .times(1)
        .returning(|| Ok(vec![
            "discogs_20260101_artists.xml.gz".to_string(),
            "discogs_20260101_labels.xml.gz".to_string(),
            "discogs_20260101_masters.xml.gz".to_string(),
            "discogs_20260101_releases.xml.gz".to_string(),
        ]));
    mock_dl.expect_take_state_marker()
        .times(1)
        .returning(|| Some(StateMarker::new("20260101".to_string())));

    // MQ factory — tasks will try to process files but they don't exist on disk
    let mut mock_mq = MockMessagePublisher::new();
    mock_mq.expect_setup_exchange().returning(|_| Ok(()));
    mock_mq.expect_publish_batch().returning(|_, _| Ok(()));
    mock_mq.expect_send_file_complete().returning(|_, _, _| Ok(()));
    mock_mq.expect_send_extraction_complete().returning(|_, _, _| Ok(()));
    mock_mq.expect_close().returning(|| Ok(()));

    let factory = Arc::new(MockMqFactory { publisher: Arc::new(mock_mq) });

    let result = extractor::extractor::process_discogs_data(
        config, state, shutdown, true, // force_reprocess = true
        &mut mock_dl, factory,
    ).await;

    // Result may be Ok(false) or Err because data files don't exist on disk for parsing.
    // The key assertion: download_discogs_data was called (verified by mock times(1)).
    // force_reprocess successfully bypassed the Skip decision.
}
```

- [ ] **Step 5: Run all new tests**

Run: `cd extractor && cargo test extractor_di_test -- --nocapture`
Expected: All pass

- [ ] **Step 6: Run full test suite**

Run: `cd extractor && cargo test`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add extractor/tests/extractor_di_test.rs
git commit -m "test(extractor): add mock-based tests for process_discogs_data (#97)"
```

---

## Chunk 5: Cleanup and Verification

### Task 12: Run full test suite and coverage

**Files:** None (verification only)

- [ ] **Step 1: Run full test suite**

Run: `cd extractor && cargo test`
Expected: All tests pass

- [ ] **Step 2: Run clippy**

Run: `cd extractor && cargo clippy -- -D warnings`
Expected: No warnings

- [ ] **Step 3: Run coverage**

Run: `cd extractor && cargo llvm-cov test --verbose --lcov --output-path lcov.info`
Expected: Coverage report generated

- [ ] **Step 4: Check coverage numbers**

Run: `cd extractor && cargo llvm-cov test --text 2>&1 | grep -E "(extractor|message_queue|main|downloader)\.rs"`

Expected: `extractor.rs`, `message_queue.rs`, and `main.rs` should all show improved coverage. Target is ~95% overall.

- [ ] **Step 5: Final commit if any cleanup needed**

If clippy or tests revealed issues, fix and commit:

```bash
git add -A
git commit -m "fix(extractor): address clippy/test issues from DI refactor (#97)"
```

---

## Implementation Notes

### What NOT to change

- **Parser (`parser.rs`)**: Already at high coverage, not involved in DI
- **State marker (`state_marker.rs`)**: Already at high coverage
- **Config (`config.rs`)**: Already at high coverage
- **Health (`health.rs`)**: Already at high coverage
- **Types (`types.rs`)**: Already at high coverage

### Known edge cases

1. **`mockall` with native async traits**: The `#[cfg_attr(feature = "test-support", mockall::automock)]` attribute must come BEFORE any other trait macros. Order matters.

2. **`Arc<dyn MessagePublisher>` in spawned tasks**: The `tokio::spawn` boundary requires `'static`, so trait objects must be wrapped in `Arc` (not borrowed references).

3. **`DataSource` mock and `S3FileInfo`**: The `S3FileInfo` struct needs to derive `Clone` (it already does based on usage in production code). Verify before writing mocks.

4. **Line numbers are approximate**: Tasks 5-7 reference line numbers from the current codebase. If earlier tasks add or remove lines, these will shift. Use the code patterns (function names, variable names) as the primary locator.

5. **`MockMqFactory` returns the same `Arc` on every `create()` call**: This means all spawned tasks in `process_discogs_data` share a single mock publisher. This is fine for tests that don't run parallel file processing (because files don't exist on disk), but would need a per-call factory for more advanced integration tests.

### Inherently untestable lines (~5%)

These lines will remain uncovered and that's expected:
- `MessageQueue::connect()` / `try_connect()` — calls `lapin::Connection::connect()` with a real broker
- `MessageQueue::get_channel()` — reconnection logic needs live AMQP
- `main()` — tracing init + `process::exit`
- `setup_shutdown_handler()` — signal handling (partially tested already)
