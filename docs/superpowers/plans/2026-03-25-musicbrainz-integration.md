# MusicBrainz Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate MusicBrainz JSONL database dumps into the Discogsography platform via the existing extractor/consumer architecture, enriching the Neo4j knowledge graph and storing MB data in PostgreSQL.

**Architecture:** The Rust extractor gains a `--source musicbrainz` mode that parses MB JSONL dumps and publishes to three `musicbrainz-*` fanout exchanges. Two new Python consumer services — brainzgraphinator (Neo4j enrichment) and brainztableinator (PostgreSQL storage) — consume these messages. A new API router exposes enriched data.

**Tech Stack:** Rust (extractor: serde_json, xz2, clap), Python 3.13+ (consumers: aio-pika, neo4j-rust-ext, psycopg, structlog), FastAPI (API endpoints), PostgreSQL (`musicbrainz` schema), Neo4j (node enrichment + new edge types)

**Spec:** `docs/superpowers/specs/2026-03-25-musicbrainz-integration-design.md`

---

## Phase 1: Extractor — MusicBrainz JSONL Support

### Task 1: Add Source enum and CLI argument

**Files:**
- Modify: `extractor/src/types.rs`
- Modify: `extractor/src/main.rs`
- Modify: `extractor/Cargo.toml`

- [ ] **Step 1: Add xz2 dependency to Cargo.toml**

In `extractor/Cargo.toml`, add to `[dependencies]`:

```toml
xz2 = "0.1"
```

- [ ] **Step 2: Add Source enum to types.rs**

At the top of `extractor/src/types.rs`, after the existing `DataType` enum, add:

```rust
/// Data source for extraction — Discogs XML or MusicBrainz JSONL.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Source {
    Discogs,
    MusicBrainz,
}

impl std::fmt::Display for Source {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Source::Discogs => write!(f, "discogs"),
            Source::MusicBrainz => write!(f, "musicbrainz"),
        }
    }
}

impl std::str::FromStr for Source {
    type Err = String;
    fn from_str(s: &str) -> std::result::Result<Self, Self::Err> {
        match s.to_lowercase().as_str() {
            "discogs" => Ok(Source::Discogs),
            "musicbrainz" => Ok(Source::MusicBrainz),
            _ => Err(format!("Unknown source: {s}. Expected 'discogs' or 'musicbrainz'")),
        }
    }
}
```

Also add `MusicBrainz`-specific `DataType` variants or a separate MB data type enum. Since MB doesn't have "masters", add a helper:

```rust
impl DataType {
    /// Data types applicable to MusicBrainz source.
    pub fn musicbrainz_types() -> Vec<DataType> {
        vec![DataType::Artists, DataType::Labels, DataType::Releases]
    }
}
```

- [ ] **Step 3: Add --source CLI argument to main.rs**

In `extractor/src/main.rs`, modify the `Args` struct:

```rust
#[derive(Parser, Debug)]
#[command(name = "extractor", about = "Discogs/MusicBrainz data extractor")]
struct Args {
    /// Force reprocess all files
    #[arg(long, env = "FORCE_REPROCESS", default_value = "false")]
    force_reprocess: bool,

    /// Path to data quality rules YAML file
    #[arg(long, env = "DATA_QUALITY_RULES")]
    data_quality_rules: Option<PathBuf>,

    /// Data source: discogs or musicbrainz
    #[arg(long, env = "EXTRACTOR_SOURCE", default_value = "discogs")]
    source: Source,
}
```

- [ ] **Step 4: Pass source through to config**

In `extractor/src/config.rs`, add `source` field to `ExtractorConfig`:

```rust
pub struct ExtractorConfig {
    // ... existing fields ...
    pub source: Source,
    pub musicbrainz_root: PathBuf,
    pub amqp_exchange_prefix: String,
}
```

Add to `from_env()`:

```rust
let musicbrainz_root = PathBuf::from(
    std::env::var("MUSICBRAINZ_ROOT").unwrap_or_else(|_| "/musicbrainz-data".to_string())
);
let amqp_exchange_prefix = std::env::var("AMQP_EXCHANGE_PREFIX")
    .unwrap_or_else(|_| "discogsography".to_string());
```

- [ ] **Step 5: Route to correct pipeline in main.rs**

In `main()`, after config loading, branch based on source:

```rust
let success = match config.source {
    Source::Discogs => {
        extractor::process_discogs_data(&config, state.clone(), &mq_factory, args.force_reprocess).await?
    }
    Source::MusicBrainz => {
        extractor::process_musicbrainz_data(&config, state.clone(), &mq_factory, args.force_reprocess).await?
    }
};
```

- [ ] **Step 6: Build to verify compilation**

Run: `cd extractor && cargo build 2>&1 | head -20`
Expected: Compiles (process_musicbrainz_data doesn't exist yet — that's fine, add a stub)

- [ ] **Step 7: Commit**

```bash
git add extractor/src/types.rs extractor/src/main.rs extractor/src/config.rs extractor/Cargo.toml
git commit -m "feat(extractor): add --source CLI argument and Source enum (#168)"
```

---

### Task 2: MusicBrainz JSONL parser

**Files:**
- Create: `extractor/src/jsonl_parser.rs`
- Modify: `extractor/src/lib.rs`

- [ ] **Step 1: Write parser tests first**

Create `extractor/tests/jsonl_parser_test.rs` (or add to existing test module). Key test cases:

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use tokio::sync::mpsc;

    #[test]
    fn test_extract_discogs_id_from_artist_url() {
        let url = "https://www.discogs.com/artist/108713";
        assert_eq!(extract_discogs_id(url, "artist"), Some(108713));
    }

    #[test]
    fn test_extract_discogs_id_from_label_url() {
        let url = "https://www.discogs.com/label/1000";
        assert_eq!(extract_discogs_id(url, "label"), Some(1000));
    }

    #[test]
    fn test_extract_discogs_id_no_match() {
        let url = "https://en.wikipedia.org/wiki/The_Beatles";
        assert_eq!(extract_discogs_id(url, "artist"), None);
    }

    #[test]
    fn test_extract_discogs_id_malformed_url() {
        let url = "https://www.discogs.com/artist/notanumber";
        assert_eq!(extract_discogs_id(url, "artist"), None);
    }

    #[test]
    fn test_parse_jsonl_line_artist_with_discogs() {
        let line = r#"{"id":"b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d","name":"The Beatles","type":"Group","life-span":{"begin":"1960","end":"1970","ended":true},"relations":[],"url-rels":[{"type":"discogs","url":{"resource":"https://www.discogs.com/artist/108713"}}]}"#;
        let msg = parse_mb_artist_line(line).unwrap();
        assert_eq!(msg.id, "b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d");
        assert_eq!(msg.data["discogs_artist_id"], 108713);
        assert_eq!(msg.data["mb_type"], "Group");
    }

    #[test]
    fn test_parse_jsonl_line_artist_no_discogs() {
        let line = r#"{"id":"some-mbid","name":"Unknown","type":"Person","life-span":{"begin":"1990"},"relations":[],"url-rels":[]}"#;
        let msg = parse_mb_artist_line(line).unwrap();
        assert!(msg.data.get("discogs_artist_id").unwrap().is_null());
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd extractor && cargo test jsonl_parser 2>&1 | tail -5`
Expected: FAIL — module doesn't exist yet

- [ ] **Step 3: Create jsonl_parser.rs**

Create `extractor/src/jsonl_parser.rs`:

```rust
use anyhow::Result;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::io::{BufRead, BufReader};
use std::path::Path;
use tokio::sync::mpsc;
use tracing::{debug, info, warn};
use xz2::read::XzDecoder;

use crate::types::{DataMessage, DataType};

/// Extract a Discogs numeric ID from a URL like "https://www.discogs.com/artist/108713".
pub fn extract_discogs_id(url: &str, entity_type: &str) -> Option<i64> {
    let prefix = format!("https://www.discogs.com/{}/", entity_type);
    if let Some(id_str) = url.strip_prefix(&prefix) {
        // Handle URLs with trailing path segments (e.g., /artist/108713-The-Beatles)
        let numeric_part = id_str.split(['-', '/']).next().unwrap_or(id_str);
        numeric_part.parse::<i64>().ok()
    } else {
        None
    }
}

/// Extract external links (non-Discogs) from url-rels.
fn extract_external_links(url_rels: &[Value]) -> Vec<Value> {
    url_rels
        .iter()
        .filter(|rel| {
            rel.get("type")
                .and_then(|t| t.as_str())
                .map_or(false, |t| t != "discogs")
        })
        .filter_map(|rel| {
            let service = rel.get("type")?.as_str()?;
            let url = rel.get("url")?.get("resource")?.as_str()?;
            Some(serde_json::json!({"service": service, "url": url}))
        })
        .collect()
}

/// Parse a single JSONL line for an MB artist into a DataMessage.
pub fn parse_mb_artist_line(line: &str) -> Result<DataMessage> {
    let raw: Value = serde_json::from_str(line)?;
    let mbid = raw["id"].as_str().unwrap_or_default().to_string();

    // Extract Discogs ID from url-rels
    let url_rels = raw["url-rels"].as_array().cloned().unwrap_or_default();
    let discogs_id: Value = url_rels
        .iter()
        .find(|r| r["type"].as_str() == Some("discogs"))
        .and_then(|r| r["url"]["resource"].as_str())
        .and_then(|url| extract_discogs_id(url, "artist"))
        .map(Value::from)
        .unwrap_or(Value::Null);

    let external_links = extract_external_links(&url_rels);
    let life_span = &raw["life-span"];

    let mut data = serde_json::json!({
        "discogs_artist_id": discogs_id,
        "name": raw["name"],
        "sort_name": raw["sort-name"],
        "mb_type": raw["type"],
        "gender": raw["gender"],
        "life_span": {
            "begin": life_span["begin"],
            "end": life_span["end"],
            "ended": life_span["ended"],
        },
        "area": raw["area"]["name"],
        "begin_area": raw["begin-area"]["name"],
        "end_area": raw["end-area"]["name"],
        "disambiguation": raw["disambiguation"],
        "aliases": raw["aliases"],
        "tags": raw["tags"],
        "relations": raw["relations"],
        "external_links": external_links,
    });

    let sha256 = calculate_hash(line);

    Ok(DataMessage {
        id: mbid,
        sha256,
        data,
        raw_xml: None,
    })
}

/// Parse a single JSONL line for an MB label into a DataMessage.
pub fn parse_mb_label_line(line: &str) -> Result<DataMessage> {
    let raw: Value = serde_json::from_str(line)?;
    let mbid = raw["id"].as_str().unwrap_or_default().to_string();

    let url_rels = raw["url-rels"].as_array().cloned().unwrap_or_default();
    let discogs_id: Value = url_rels
        .iter()
        .find(|r| r["type"].as_str() == Some("discogs"))
        .and_then(|r| r["url"]["resource"].as_str())
        .and_then(|url| extract_discogs_id(url, "label"))
        .map(Value::from)
        .unwrap_or(Value::Null);

    let external_links = extract_external_links(&url_rels);
    let life_span = &raw["life-span"];

    let data = serde_json::json!({
        "discogs_label_id": discogs_id,
        "name": raw["name"],
        "mb_type": raw["type"],
        "label_code": raw["label-code"],
        "life_span": {
            "begin": life_span["begin"],
            "end": life_span["end"],
            "ended": life_span["ended"],
        },
        "area": raw["area"]["name"],
        "disambiguation": raw["disambiguation"],
        "relations": raw["relations"],
        "external_links": external_links,
    });

    let sha256 = calculate_hash(line);

    Ok(DataMessage {
        id: mbid,
        sha256,
        data,
        raw_xml: None,
    })
}

/// Parse a single JSONL line for an MB release into a DataMessage.
pub fn parse_mb_release_line(line: &str) -> Result<DataMessage> {
    let raw: Value = serde_json::from_str(line)?;
    let mbid = raw["id"].as_str().unwrap_or_default().to_string();

    let url_rels = raw["url-rels"].as_array().cloned().unwrap_or_default();
    let discogs_id: Value = url_rels
        .iter()
        .find(|r| r["type"].as_str() == Some("discogs"))
        .and_then(|r| r["url"]["resource"].as_str())
        .and_then(|url| extract_discogs_id(url, "release"))
        .map(Value::from)
        .unwrap_or(Value::Null);

    let external_links = extract_external_links(&url_rels);

    let data = serde_json::json!({
        "discogs_release_id": discogs_id,
        "name": raw["title"],
        "barcode": raw["barcode"],
        "status": raw["status"],
        "release_group_mbid": raw["release-group"].as_ref().and_then(|rg| rg["id"].as_str()),
        "relations": raw["relations"],
        "external_links": external_links,
    });

    let sha256 = calculate_hash(line);

    Ok(DataMessage {
        id: mbid,
        sha256,
        data,
        raw_xml: None,
    })
}

/// Stream-parse an xz-compressed JSONL file, sending DataMessages to the channel.
pub async fn parse_mb_jsonl_file(
    path: &Path,
    data_type: DataType,
    sender: mpsc::Sender<DataMessage>,
) -> Result<u64> {
    let file = std::fs::File::open(path)?;
    let decoder = XzDecoder::new(file);
    let reader = BufReader::new(decoder);

    let parse_fn = match data_type {
        DataType::Artists => parse_mb_artist_line,
        DataType::Labels => parse_mb_label_line,
        DataType::Releases => parse_mb_release_line,
        DataType::Masters => {
            anyhow::bail!("MusicBrainz does not have a masters entity type");
        }
    };

    let mut count: u64 = 0;
    for line_result in reader.lines() {
        let line = line_result?;
        if line.trim().is_empty() {
            continue;
        }
        match parse_fn(&line) {
            Ok(msg) => {
                if sender.send(msg).await.is_err() {
                    warn!("⚠️ Channel closed, stopping parse");
                    break;
                }
                count += 1;
                if count % 100_000 == 0 {
                    info!("📊 Parsed {} {} records", count, data_type);
                }
            }
            Err(e) => {
                debug!("⚠️ Skipping malformed JSONL line: {}", e);
            }
        }
    }

    info!("✅ Finished parsing {} {} records from {:?}", count, data_type, path);
    Ok(count)
}

fn calculate_hash(input: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(input.as_bytes());
    format!("{:x}", hasher.finalize())
}
```

- [ ] **Step 4: Register module in lib.rs**

Add to `extractor/src/lib.rs`:

```rust
pub mod jsonl_parser;
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd extractor && cargo test jsonl_parser 2>&1 | tail -10`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add extractor/src/jsonl_parser.rs extractor/src/lib.rs
git commit -m "feat(extractor): add MusicBrainz JSONL parser with Discogs ID extraction (#168)"
```

---

### Task 3: MusicBrainz download and extraction pipeline

**Files:**
- Create: `extractor/src/mb_downloader.rs`
- Modify: `extractor/src/extractor.rs`
- Modify: `extractor/src/message_queue.rs`

- [ ] **Step 1: Write mb_downloader.rs**

The MB downloader fetches JSONL dumps from the MusicBrainz website. MB publishes dumps at a known URL pattern. For the initial implementation, we support pointing at a local directory of pre-downloaded dumps (the download-from-web feature can be added later).

Create `extractor/src/mb_downloader.rs`:

```rust
use anyhow::{Context, Result};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use tracing::{info, warn};

use crate::types::DataType;

/// Expected JSONL dump file patterns per data type.
const MB_FILE_PATTERNS: &[(&str, &str)] = &[
    ("artist", "artist.jsonl.xz"),
    ("label", "label.jsonl.xz"),
    ("release", "release.jsonl.xz"),
];

/// Discover available MusicBrainz JSONL dump files in the given directory.
/// Returns a map of DataType -> file path for each found dump file.
pub fn discover_mb_dump_files(root: &Path) -> Result<HashMap<DataType, PathBuf>> {
    let mut found = HashMap::new();

    for (entity, pattern) in MB_FILE_PATTERNS {
        // Check for exact filename or glob for versioned files
        let exact_path = root.join(pattern);
        if exact_path.exists() {
            let data_type = match *entity {
                "artist" => DataType::Artists,
                "label" => DataType::Labels,
                "release" => DataType::Releases,
                _ => continue,
            };
            info!("📁 Found MB dump: {:?}", exact_path);
            found.insert(data_type, exact_path);
            continue;
        }

        // Try common alternative patterns (e.g., mbdump-artist.jsonl.xz)
        for entry in std::fs::read_dir(root).with_context(|| format!("Cannot read directory: {:?}", root))? {
            let entry = entry?;
            let name = entry.file_name().to_string_lossy().to_string();
            if name.contains(entity) && name.ends_with(".jsonl.xz") {
                let data_type = match *entity {
                    "artist" => DataType::Artists,
                    "label" => DataType::Labels,
                    "release" => DataType::Releases,
                    _ => continue,
                };
                info!("📁 Found MB dump: {:?}", entry.path());
                found.insert(data_type, entry.path());
                break;
            }
        }
    }

    if found.is_empty() {
        warn!("⚠️ No MusicBrainz JSONL dump files found in {:?}", root);
    } else {
        info!("📊 Discovered {} MB dump files", found.len());
    }

    Ok(found)
}

/// Detect the version (date) of the dump from the directory name or file metadata.
/// Falls back to current date if detection fails.
pub fn detect_mb_dump_version(root: &Path) -> String {
    // Try to extract a date from the directory name (e.g., /musicbrainz-data/2026-03-22/)
    if let Some(dir_name) = root.file_name().and_then(|n| n.to_str()) {
        let date_part = dir_name.replace('-', "");
        if date_part.len() == 8 && date_part.chars().all(|c| c.is_ascii_digit()) {
            return date_part;
        }
    }
    // Fall back to file modification time or current date
    chrono::Utc::now().format("%Y%m%d").to_string()
}
```

- [ ] **Step 2: Update AMQP exchange prefix to be configurable**

In `extractor/src/message_queue.rs`, change the hardcoded prefix to accept a parameter. Modify `MessageQueue::new()` to accept an exchange prefix:

```rust
pub struct MessageQueue {
    connection: Arc<RwLock<Option<Connection>>>,
    channel: Arc<RwLock<Option<Channel>>>,
    url: String,
    max_retries: u32,
    exchange_prefix: String,
}

impl MessageQueue {
    pub async fn new(url: &str, max_retries: u32, exchange_prefix: &str) -> Result<Self> {
        let mq = Self {
            connection: Arc::new(RwLock::new(None)),
            channel: Arc::new(RwLock::new(None)),
            url: url.to_string(),
            max_retries,
            exchange_prefix: exchange_prefix.to_string(),
        };
        mq.connect().await?;
        Ok(mq)
    }

    fn exchange_name(&self, data_type: DataType) -> String {
        format!("{}-{}", self.exchange_prefix, data_type)
    }
}
```

Update `MessageQueueFactory` and its implementation to pass the prefix through:

```rust
pub trait MessageQueueFactory: Send + Sync {
    async fn create(&self, url: &str, exchange_prefix: &str) -> Result<Arc<dyn MessagePublisher>>;
}
```

- [ ] **Step 3: Add process_musicbrainz_data to extractor.rs**

In `extractor/src/extractor.rs`, add the MB processing pipeline:

```rust
use crate::jsonl_parser::parse_mb_jsonl_file;
use crate::mb_downloader::{detect_mb_dump_version, discover_mb_dump_files};

/// Main entry point for MusicBrainz data processing.
pub async fn process_musicbrainz_data(
    config: &ExtractorConfig,
    state: Arc<RwLock<ExtractorState>>,
    mq_factory: &dyn MessageQueueFactory,
    force_reprocess: bool,
) -> Result<bool> {
    let root = &config.musicbrainz_root;
    info!("🧠 Starting MusicBrainz extraction from {:?}", root);

    let version = detect_mb_dump_version(root);
    let marker_path = root.join(format!(".mb_extraction_status_{}.json", version));

    // Check state marker for resume logic
    if !force_reprocess && marker_path.exists() {
        let marker = StateMarker::load(&marker_path)?;
        if marker.is_completed() {
            info!("✅ MB extraction already completed for version {}, skipping", version);
            return Ok(true);
        }
    }

    let dump_files = discover_mb_dump_files(root)?;
    if dump_files.is_empty() {
        warn!("⚠️ No MB dump files found, nothing to process");
        return Ok(false);
    }

    let started_at = chrono::Utc::now();
    let mq = mq_factory.create(&config.amqp_connection, &config.amqp_exchange_prefix).await?;

    // Declare exchanges for MB data types
    for data_type in DataType::musicbrainz_types() {
        mq.setup_exchange(data_type).await?;
    }

    let mut record_counts: HashMap<String, u64> = HashMap::new();

    // Process each dump file
    for (data_type, file_path) in &dump_files {
        info!("📦 Processing MB {} from {:?}", data_type, file_path);

        let (sender, mut receiver) = tokio::sync::mpsc::channel::<DataMessage>(config.queue_size);

        // Spawn parser task
        let path = file_path.clone();
        let dt = *data_type;
        let parse_task = tokio::spawn(async move {
            parse_mb_jsonl_file(&path, dt, sender).await
        });

        // Spawn publisher task
        let mq_clone = mq.clone();
        let dt_pub = *data_type;
        let batch_size = config.batch_size;
        let publish_task = tokio::spawn(async move {
            let mut batch = Vec::with_capacity(batch_size);
            let mut total: u64 = 0;
            while let Some(msg) = receiver.recv().await {
                batch.push(msg);
                if batch.len() >= batch_size {
                    mq_clone.publish_batch(std::mem::take(&mut batch), dt_pub).await?;
                    total += batch_size as u64;
                }
            }
            if !batch.is_empty() {
                let remaining = batch.len() as u64;
                mq_clone.publish_batch(batch, dt_pub).await?;
                total += remaining;
            }
            Ok::<u64, anyhow::Error>(total)
        });

        let parsed = parse_task.await??;
        let published = publish_task.await??;

        info!("✅ MB {}: parsed={}, published={}", data_type, parsed, published);
        record_counts.insert(data_type.to_string(), published);

        // Send file_complete
        mq.send_file_complete(
            *data_type,
            &file_path.file_name().unwrap_or_default().to_string_lossy(),
            published,
        ).await?;
    }

    // Send extraction_complete to all MB exchanges
    mq.send_extraction_complete(&version, started_at, record_counts).await?;

    // Save state marker
    let mut marker = StateMarker::new(&version);
    marker.mark_completed();
    marker.save(&marker_path)?;

    info!("✅ MusicBrainz extraction complete for version {}", version);
    Ok(true)
}
```

- [ ] **Step 4: Register mb_downloader module in lib.rs**

Add to `extractor/src/lib.rs`:

```rust
pub mod mb_downloader;
```

- [ ] **Step 5: Build to verify compilation**

Run: `cd extractor && cargo build 2>&1 | tail -10`
Expected: Compiles successfully

- [ ] **Step 6: Commit**

```bash
git add extractor/src/mb_downloader.rs extractor/src/extractor.rs extractor/src/message_queue.rs extractor/src/lib.rs
git commit -m "feat(extractor): add MusicBrainz download, pipeline, and configurable exchange prefix (#168)"
```

---

### Task 4: Discogs ID resolution for relationship targets (two-pass)

**Files:**
- Modify: `extractor/src/jsonl_parser.rs`

- [ ] **Step 1: Write test for two-pass ID resolution**

```rust
#[test]
fn test_build_mbid_to_discogs_map() {
    let lines = vec![
        r#"{"id":"mbid-1","name":"Artist A","url-rels":[{"type":"discogs","url":{"resource":"https://www.discogs.com/artist/100"}}]}"#,
        r#"{"id":"mbid-2","name":"Artist B","url-rels":[{"type":"discogs","url":{"resource":"https://www.discogs.com/artist/200"}}]}"#,
        r#"{"id":"mbid-3","name":"Artist C","url-rels":[]}"#,
    ];
    let map = build_mbid_discogs_map(&lines, "artist");
    assert_eq!(map.get("mbid-1"), Some(&100i64));
    assert_eq!(map.get("mbid-2"), Some(&200i64));
    assert!(!map.contains_key("mbid-3"));
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd extractor && cargo test test_build_mbid_to_discogs_map 2>&1`
Expected: FAIL

- [ ] **Step 3: Implement build_mbid_discogs_map**

In `extractor/src/jsonl_parser.rs`, add a first-pass function:

```rust
use std::collections::HashMap;

/// First pass: build a map of MBID -> Discogs ID from JSONL lines.
/// Used to resolve relationship target Discogs IDs.
pub fn build_mbid_discogs_map_from_file(
    path: &Path,
    entity_type: &str,
) -> Result<HashMap<String, i64>> {
    let file = std::fs::File::open(path)?;
    let decoder = XzDecoder::new(file);
    let reader = BufReader::new(decoder);
    let mut map = HashMap::new();

    for line_result in reader.lines() {
        let line = line_result?;
        if line.trim().is_empty() {
            continue;
        }
        if let Ok(raw) = serde_json::from_str::<Value>(&line) {
            let mbid = raw["id"].as_str().unwrap_or_default();
            if mbid.is_empty() {
                continue;
            }
            let url_rels = raw["url-rels"].as_array();
            if let Some(rels) = url_rels {
                for rel in rels {
                    if rel["type"].as_str() == Some("discogs") {
                        if let Some(url) = rel["url"]["resource"].as_str() {
                            if let Some(id) = extract_discogs_id(url, entity_type) {
                                map.insert(mbid.to_string(), id);
                                break;
                            }
                        }
                    }
                }
            }
        }
    }

    info!("📊 Built MBID->Discogs map: {} entries for {}", map.len(), entity_type);
    Ok(map)
}
```

- [ ] **Step 4: Enrich relationship targets with Discogs IDs during second pass**

Update `parse_mb_artist_line` to accept an optional lookup map:

```rust
pub fn parse_mb_artist_line_with_map(
    line: &str,
    discogs_map: &HashMap<String, i64>,
) -> Result<DataMessage> {
    let raw: Value = serde_json::from_str(line)?;
    let mbid = raw["id"].as_str().unwrap_or_default().to_string();

    // ... same as parse_mb_artist_line but enrich relations:
    let relations = raw["relations"].as_array().cloned().unwrap_or_default();
    let enriched_relations: Vec<Value> = relations
        .into_iter()
        .map(|mut rel| {
            if let Some(target_mbid) = rel["target"]["id"].as_str() {
                if let Some(&target_discogs_id) = discogs_map.get(target_mbid) {
                    rel["target_discogs_artist_id"] = Value::from(target_discogs_id);
                } else {
                    rel["target_discogs_artist_id"] = Value::Null;
                }
            }
            rel
        })
        .collect();

    // ... rest of message construction, using enriched_relations instead of raw["relations"]
}
```

- [ ] **Step 5: Update parse_mb_jsonl_file to use two-pass for artists**

```rust
pub async fn parse_mb_jsonl_file(
    path: &Path,
    data_type: DataType,
    sender: mpsc::Sender<DataMessage>,
    discogs_map: Option<&HashMap<String, i64>>,
) -> Result<u64> {
    // ... same as before but use parse_mb_artist_line_with_map when map is provided
}
```

Update `process_musicbrainz_data` in `extractor.rs` to do the first pass for artists:

```rust
// First pass: build MBID->Discogs ID map for relationship target resolution
let artist_discogs_map = if let Some(artist_path) = dump_files.get(&DataType::Artists) {
    info!("🔍 First pass: building MBID→Discogs ID map for artists...");
    build_mbid_discogs_map_from_file(artist_path, "artist")?
} else {
    HashMap::new()
};
```

- [ ] **Step 6: Run tests**

Run: `cd extractor && cargo test 2>&1 | tail -10`
Expected: All tests pass

- [ ] **Step 7: Commit**

```bash
git add extractor/src/jsonl_parser.rs extractor/src/extractor.rs
git commit -m "feat(extractor): add two-pass Discogs ID resolution for relationship targets (#168)"
```

---

### Task 5: MB state markers

**Files:**
- Modify: `extractor/src/state_marker.rs`

- [ ] **Step 1: Add MB-specific state marker support**

The existing `StateMarker` struct is generic enough. The only change needed is ensuring MB uses a different file pattern (`.mb_extraction_status_{version}.json`). This is already handled in `process_musicbrainz_data` by constructing the path with the `mb_` prefix.

Verify the `StateMarker` API supports the operations we need:
- `StateMarker::new(version)` — create new marker
- `StateMarker::load(path)` — load from disk
- `marker.is_completed()` — check if complete
- `marker.mark_completed()` — mark as complete
- `marker.save(path)` — persist to disk

If any of these don't exist, add them. The key is that MB and Discogs markers are completely independent files.

- [ ] **Step 2: Commit if any changes were needed**

```bash
git add extractor/src/state_marker.rs
git commit -m "feat(extractor): ensure state markers support MB extraction tracking (#168)"
```

---

### Task 6: Docker configuration for second extractor

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add extractor-musicbrainz service to docker-compose.yml**

Add after the existing `extractor` service definition:

```yaml
  extractor-musicbrainz:
    build:
      context: .
      dockerfile: extractor/Dockerfile
      args:
        RUST_VERSION: ${RUST_VERSION:-1.94}
        UID: ${UID:-1000}
        GID: ${GID:-1000}
    image: discogsography/extractor:latest
    container_name: discogsography-extractor-musicbrainz
    hostname: extractor-musicbrainz
    command: ["--source", "musicbrainz"]
    user: "${UID:-1000}:${GID:-1000}"
    environment:
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
      MUSICBRAINZ_ROOT: /musicbrainz-data
      AMQP_EXCHANGE_PREFIX: musicbrainz
      RABBITMQ_HOST: rabbitmq
      RABBITMQ_USERNAME: ${RABBITMQ_USERNAME:-discogsography}
      RABBITMQ_PASSWORD: ${RABBITMQ_PASSWORD:-discogsography}
      PERIODIC_CHECK_DAYS: "7"
    depends_on:
      rabbitmq:
        condition: service_healthy
    networks:
      - discogsography
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s
    restart: on-failure
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    read_only: true
    tmpfs:
      - /tmp
    volumes:
      - musicbrainz_data:/musicbrainz-data
      - extractor_mb_logs:/logs
```

Add volumes at the bottom of the `volumes:` section:

```yaml
  musicbrainz_data:
  extractor_mb_logs:
```

- [ ] **Step 2: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(docker): add extractor-musicbrainz service container (#168)"
```

---

### Task 7: Extractor Rust tests

**Files:**
- Create or modify: `extractor/tests/` test files

- [ ] **Step 1: Write integration tests for MB pipeline**

Create test fixtures — small JSONL test files. Add integration tests that verify:
- JSONL parsing produces correct DataMessage fields
- Discogs ID extraction handles all URL formats
- Two-pass map building works end-to-end
- Exchange prefix is configurable
- State marker files are created correctly

- [ ] **Step 2: Run full test suite**

Run: `cd extractor && cargo test 2>&1 | tail -20`
Expected: All tests pass

- [ ] **Step 3: Run clippy**

Run: `cd extractor && cargo clippy -- -D warnings 2>&1 | tail -10`
Expected: No warnings

- [ ] **Step 4: Run fmt check**

Run: `cd extractor && cargo fmt --check 2>&1`
Expected: No formatting issues

- [ ] **Step 5: Commit**

```bash
git add extractor/tests/
git commit -m "test(extractor): add MusicBrainz JSONL parser and pipeline tests (#168)"
```

---

## Phase 2: Schema + Brainztableinator

### Task 8: PostgreSQL musicbrainz schema in schema-init

**Files:**
- Modify: `schema-init/postgres_schema.py`

- [ ] **Step 1: Write test for new schema statements**

Create `tests/schema-init/test_musicbrainz_schema.py`:

```python
"""Tests for MusicBrainz PostgreSQL schema definitions."""

from schema_init.postgres_schema import _MUSICBRAINZ_TABLES, _MUSICBRAINZ_INDEXES


def test_musicbrainz_tables_defined():
    """All expected MB tables are declared."""
    table_names = [name for name, _ in _MUSICBRAINZ_TABLES]
    assert "musicbrainz_schema" in table_names
    assert "musicbrainz_artists" in table_names
    assert "musicbrainz_labels" in table_names
    assert "musicbrainz_releases" in table_names
    assert "musicbrainz_relationships" in table_names
    assert "musicbrainz_external_links" in table_names


def test_musicbrainz_tables_use_if_not_exists():
    """All MB table statements use IF NOT EXISTS for idempotency."""
    for name, sql in _MUSICBRAINZ_TABLES:
        assert "IF NOT EXISTS" in sql, f"{name} missing IF NOT EXISTS"


def test_musicbrainz_indexes_defined():
    """Cross-reference and lookup indexes are declared."""
    index_names = [name for name, _ in _MUSICBRAINZ_INDEXES]
    assert "idx_mb_artists_discogs_id" in index_names
    assert "idx_mb_labels_discogs_id" in index_names
    assert "idx_mb_releases_discogs_id" in index_names
    assert "idx_mb_rels_source" in index_names
    assert "idx_mb_links_mbid" in index_names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/schema-init/test_musicbrainz_schema.py -v 2>&1 | tail -10`
Expected: FAIL — `_MUSICBRAINZ_TABLES` not defined

- [ ] **Step 3: Add musicbrainz schema to postgres_schema.py**

In `schema-init/postgres_schema.py`, add after existing table definitions:

```python
_MUSICBRAINZ_TABLES: list[tuple[str, str]] = [
    (
        "musicbrainz_schema",
        "CREATE SCHEMA IF NOT EXISTS musicbrainz",
    ),
    (
        "musicbrainz_artists",
        """CREATE TABLE IF NOT EXISTS musicbrainz.artists (
            mbid UUID PRIMARY KEY,
            name TEXT NOT NULL,
            sort_name TEXT,
            type TEXT,
            gender TEXT,
            begin_date TEXT,
            end_date TEXT,
            ended BOOLEAN DEFAULT FALSE,
            area TEXT,
            begin_area TEXT,
            end_area TEXT,
            disambiguation TEXT,
            discogs_artist_id INTEGER,
            aliases JSONB,
            tags JSONB,
            data JSONB,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )""",
    ),
    (
        "musicbrainz_labels",
        """CREATE TABLE IF NOT EXISTS musicbrainz.labels (
            mbid UUID PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT,
            label_code INTEGER,
            begin_date TEXT,
            end_date TEXT,
            ended BOOLEAN DEFAULT FALSE,
            area TEXT,
            disambiguation TEXT,
            discogs_label_id INTEGER,
            data JSONB,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )""",
    ),
    (
        "musicbrainz_releases",
        """CREATE TABLE IF NOT EXISTS musicbrainz.releases (
            mbid UUID PRIMARY KEY,
            name TEXT NOT NULL,
            barcode TEXT,
            status TEXT,
            release_group_mbid UUID,
            discogs_release_id INTEGER,
            data JSONB,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )""",
    ),
    (
        "musicbrainz_relationships",
        """CREATE TABLE IF NOT EXISTS musicbrainz.relationships (
            id SERIAL PRIMARY KEY,
            source_mbid UUID NOT NULL,
            target_mbid UUID NOT NULL,
            source_entity_type TEXT NOT NULL,
            target_entity_type TEXT NOT NULL,
            relationship_type TEXT NOT NULL,
            begin_date TEXT,
            end_date TEXT,
            ended BOOLEAN DEFAULT FALSE,
            attributes JSONB,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (source_mbid, target_mbid, relationship_type)
        )""",
    ),
    (
        "musicbrainz_external_links",
        """CREATE TABLE IF NOT EXISTS musicbrainz.external_links (
            id SERIAL PRIMARY KEY,
            mbid UUID NOT NULL,
            entity_type TEXT NOT NULL,
            service_name TEXT NOT NULL,
            url TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (mbid, entity_type, service_name)
        )""",
    ),
]

_MUSICBRAINZ_INDEXES: list[tuple[str, str]] = [
    ("idx_mb_artists_discogs_id", "CREATE INDEX IF NOT EXISTS idx_mb_artists_discogs_id ON musicbrainz.artists (discogs_artist_id) WHERE discogs_artist_id IS NOT NULL"),
    ("idx_mb_labels_discogs_id", "CREATE INDEX IF NOT EXISTS idx_mb_labels_discogs_id ON musicbrainz.labels (discogs_label_id) WHERE discogs_label_id IS NOT NULL"),
    ("idx_mb_releases_discogs_id", "CREATE INDEX IF NOT EXISTS idx_mb_releases_discogs_id ON musicbrainz.releases (discogs_release_id) WHERE discogs_release_id IS NOT NULL"),
    ("idx_mb_artists_name", "CREATE INDEX IF NOT EXISTS idx_mb_artists_name ON musicbrainz.artists (name)"),
    ("idx_mb_labels_name", "CREATE INDEX IF NOT EXISTS idx_mb_labels_name ON musicbrainz.labels (name)"),
    ("idx_mb_rels_source", "CREATE INDEX IF NOT EXISTS idx_mb_rels_source ON musicbrainz.relationships (source_mbid)"),
    ("idx_mb_rels_target", "CREATE INDEX IF NOT EXISTS idx_mb_rels_target ON musicbrainz.relationships (target_mbid)"),
    ("idx_mb_rels_type", "CREATE INDEX IF NOT EXISTS idx_mb_rels_type ON musicbrainz.relationships (relationship_type)"),
    ("idx_mb_links_mbid", "CREATE INDEX IF NOT EXISTS idx_mb_links_mbid ON musicbrainz.external_links (mbid)"),
    ("idx_mb_links_service", "CREATE INDEX IF NOT EXISTS idx_mb_links_service ON musicbrainz.external_links (service_name)"),
]
```

Include these in the `create_postgres_schema()` function by appending to the statement list:

```python
all_statements = (
    _ENTITY_TABLES_STATEMENTS
    + _SPECIFIC_INDEXES
    + _USER_TABLES
    + _INSIGHTS_TABLES
    + _MUSICBRAINZ_TABLES
    + _MUSICBRAINZ_INDEXES
)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/schema-init/test_musicbrainz_schema.py -v 2>&1 | tail -10`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add schema-init/postgres_schema.py tests/schema-init/test_musicbrainz_schema.py
git commit -m "feat(schema-init): add MusicBrainz PostgreSQL schema and indexes (#168)"
```

---

### Task 9: Brainztableinator service scaffold

**Files:**
- Create: `brainztableinator/__init__.py`
- Create: `brainztableinator/pyproject.toml`
- Create: `brainztableinator/brainztableinator.py`
- Modify: `common/config.py`
- Modify: `common/__init__.py`
- Modify: `pyproject.toml` (root)

- [ ] **Step 1: Add BrainztableinatorConfig to common/config.py**

After the existing `TableinatorConfig`, add:

```python
@dataclass(frozen=True)
class BrainztableinatorConfig:
    """Configuration for the brainztableinator service."""

    amqp_connection: str
    postgres_host: str
    postgres_username: str
    postgres_password: str
    postgres_database: str

    @classmethod
    def from_env(cls) -> "BrainztableinatorConfig":
        """Create configuration from environment variables."""
        missing = []
        postgres_host = os.environ.get("POSTGRES_HOST")
        if not postgres_host:
            missing.append("POSTGRES_HOST")
        postgres_username = os.environ.get("POSTGRES_USERNAME")
        if not postgres_username:
            missing.append("POSTGRES_USERNAME")
        postgres_password = get_secret("POSTGRES_PASSWORD")
        if not postgres_password:
            missing.append("POSTGRES_PASSWORD")
        postgres_database = os.environ.get("POSTGRES_DATABASE", "discogsography")
        if missing:
            msg = f"Missing required environment variables: {', '.join(missing)}"
            raise ValueError(msg)
        return cls(
            amqp_connection=_build_amqp_url(),
            postgres_host=postgres_host,  # type: ignore[arg-type]
            postgres_username=postgres_username,  # type: ignore[arg-type]
            postgres_password=postgres_password,
            postgres_database=postgres_database,
        )
```

- [ ] **Step 2: Add AMQP constants for musicbrainz exchanges**

In `common/config.py`, after existing AMQP constants:

```python
MUSICBRAINZ_EXCHANGE_PREFIX = "musicbrainz"
AMQP_QUEUE_PREFIX_BRAINZGRAPHINATOR = "musicbrainz-brainzgraphinator"
AMQP_QUEUE_PREFIX_BRAINZTABLEINATOR = "musicbrainz-brainztableinator"
MUSICBRAINZ_DATA_TYPES = ["artists", "labels", "releases"]
```

Export these from `common/__init__.py`:

```python
from common.config import (
    # ... existing exports ...
    BrainztableinatorConfig,
    MUSICBRAINZ_EXCHANGE_PREFIX,
    AMQP_QUEUE_PREFIX_BRAINZGRAPHINATOR,
    AMQP_QUEUE_PREFIX_BRAINZTABLEINATOR,
    MUSICBRAINZ_DATA_TYPES,
)
```

- [ ] **Step 3: Create brainztableinator/pyproject.toml**

```toml
[project]
name = "discogsography-brainztableinator"
version = "0.1.0"
description = "MusicBrainz data consumer — writes to PostgreSQL"
requires-python = ">=3.13"
dependencies = [
    "aio-pika>=9.0.0",
    "orjson>=3.0.0",
    "psycopg[binary]>=3.1.0",
    "structlog>=24.0.0",
]

[tool.pytest.ini_options]
testpaths = ["../tests/brainztableinator"]
```

- [ ] **Step 4: Create brainztableinator/__init__.py**

```python
"""Brainztableinator — MusicBrainz data consumer for PostgreSQL."""
```

- [ ] **Step 5: Create brainztableinator/brainztableinator.py**

Follow the tableinator pattern exactly. Key structure:

```python
"""Brainztableinator service — consumes MusicBrainz messages and writes to PostgreSQL."""

from __future__ import annotations

import asyncio
import os
import signal
import time
from asyncio import run
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from aio_pika.abc import AbstractIncomingMessage
from orjson import loads
from psycopg import sql
from psycopg.errors import InterfaceError, OperationalError
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from common import (
    AMQP_QUEUE_PREFIX_BRAINZTABLEINATOR,
    MUSICBRAINZ_DATA_TYPES,
    MUSICBRAINZ_EXCHANGE_PREFIX,
    AsyncPostgreSQLPool,
    AsyncResilientRabbitMQ,
    BrainztableinatorConfig,
    HealthServer,
    setup_logging,
)

logger = structlog.get_logger(__name__)

# Module-level state (same pattern as tableinator)
config: BrainztableinatorConfig | None = None
message_counts: dict[str, int] = {dt: 0 for dt in MUSICBRAINZ_DATA_TYPES}
last_message_time: dict[str, float] = {}
completed_files: set[str] = set()
consumer_tags: dict[str, str] = {}
queues: dict[str, Any] = {}
connection_pool: AsyncPostgreSQLPool | None = None
shutdown_requested: bool = False

CONSUMER_CANCEL_DELAY = int(os.environ.get("CONSUMER_CANCEL_DELAY", "300"))
QUEUE_CHECK_INTERVAL = int(os.environ.get("QUEUE_CHECK_INTERVAL", "3600"))
BATCH_MODE = os.environ.get("POSTGRES_BATCH_MODE", "false").lower() == "true"


def get_health_data() -> dict[str, Any]:
    """Return health status for the health endpoint."""
    return {
        "status": "healthy" if connection_pool else "starting",
        "service": "brainztableinator",
        "message_counts": dict(message_counts),
        "last_message_time": {k: str(v) for k, v in last_message_time.items()},
        "active_consumers": list(consumer_tags.keys()),
        "completed_files": list(completed_files),
        "timestamp": datetime.now(UTC).isoformat(),
    }


def signal_handler(signum: int, _frame: Any) -> None:
    """Handle shutdown signals."""
    global shutdown_requested
    shutdown_requested = True
    logger.info("🛑 Shutdown requested", signal=signum)


async def process_artist(conn: Any, record: dict[str, Any]) -> None:
    """Insert or update a MusicBrainz artist record."""
    mbid = record.get("id", "")
    data = record.get("data", record)
    discogs_id = data.get("discogs_artist_id")

    async with conn.cursor() as cur:
        await cur.execute(
            """INSERT INTO musicbrainz.artists
               (mbid, name, sort_name, type, gender, begin_date, end_date, ended,
                area, begin_area, end_area, disambiguation, discogs_artist_id,
                aliases, tags, data)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (mbid) DO UPDATE SET
                name = EXCLUDED.name, sort_name = EXCLUDED.sort_name,
                type = EXCLUDED.type, gender = EXCLUDED.gender,
                begin_date = EXCLUDED.begin_date, end_date = EXCLUDED.end_date,
                ended = EXCLUDED.ended, area = EXCLUDED.area,
                begin_area = EXCLUDED.begin_area, end_area = EXCLUDED.end_area,
                disambiguation = EXCLUDED.disambiguation,
                discogs_artist_id = EXCLUDED.discogs_artist_id,
                aliases = EXCLUDED.aliases, tags = EXCLUDED.tags,
                data = EXCLUDED.data, updated_at = NOW()""",
            (
                mbid,
                data.get("name"),
                data.get("sort_name"),
                data.get("mb_type"),
                data.get("gender"),
                data.get("life_span", {}).get("begin"),
                data.get("life_span", {}).get("end"),
                data.get("life_span", {}).get("ended", False),
                data.get("area"),
                data.get("begin_area"),
                data.get("end_area"),
                data.get("disambiguation"),
                discogs_id,
                Jsonb(data.get("aliases", [])),
                Jsonb(data.get("tags", [])),
                Jsonb(data),
            ),
        )

    # Insert relationships
    for rel in data.get("relations", []):
        await _insert_relationship(conn, mbid, "artist", rel)

    # Insert external links
    for link in data.get("external_links", []):
        await _insert_external_link(conn, mbid, "artist", link)


async def process_label(conn: Any, record: dict[str, Any]) -> None:
    """Insert or update a MusicBrainz label record."""
    mbid = record.get("id", "")
    data = record.get("data", record)
    discogs_id = data.get("discogs_label_id")

    async with conn.cursor() as cur:
        await cur.execute(
            """INSERT INTO musicbrainz.labels
               (mbid, name, type, label_code, begin_date, end_date, ended,
                area, disambiguation, discogs_label_id, data)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (mbid) DO UPDATE SET
                name = EXCLUDED.name, type = EXCLUDED.type,
                label_code = EXCLUDED.label_code,
                begin_date = EXCLUDED.begin_date, end_date = EXCLUDED.end_date,
                ended = EXCLUDED.ended, area = EXCLUDED.area,
                disambiguation = EXCLUDED.disambiguation,
                discogs_label_id = EXCLUDED.discogs_label_id,
                data = EXCLUDED.data, updated_at = NOW()""",
            (
                mbid,
                data.get("name"),
                data.get("mb_type"),
                data.get("label_code"),
                data.get("life_span", {}).get("begin"),
                data.get("life_span", {}).get("end"),
                data.get("life_span", {}).get("ended", False),
                data.get("area"),
                data.get("disambiguation"),
                discogs_id,
                Jsonb(data),
            ),
        )

    for rel in data.get("relations", []):
        await _insert_relationship(conn, mbid, "label", rel)
    for link in data.get("external_links", []):
        await _insert_external_link(conn, mbid, "label", link)


async def process_release(conn: Any, record: dict[str, Any]) -> None:
    """Insert or update a MusicBrainz release record."""
    mbid = record.get("id", "")
    data = record.get("data", record)
    discogs_id = data.get("discogs_release_id")

    async with conn.cursor() as cur:
        await cur.execute(
            """INSERT INTO musicbrainz.releases
               (mbid, name, barcode, status, release_group_mbid, discogs_release_id, data)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (mbid) DO UPDATE SET
                name = EXCLUDED.name, barcode = EXCLUDED.barcode,
                status = EXCLUDED.status,
                release_group_mbid = EXCLUDED.release_group_mbid,
                discogs_release_id = EXCLUDED.discogs_release_id,
                data = EXCLUDED.data, updated_at = NOW()""",
            (
                mbid,
                data.get("name"),
                data.get("barcode"),
                data.get("status"),
                data.get("release_group_mbid"),
                discogs_id,
                Jsonb(data),
            ),
        )

    for rel in data.get("relations", []):
        await _insert_relationship(conn, mbid, "release", rel)
    for link in data.get("external_links", []):
        await _insert_external_link(conn, mbid, "release", link)


async def _insert_relationship(conn: Any, source_mbid: str, source_type: str, rel: dict[str, Any]) -> None:
    """Insert a relationship record (idempotent via source+target+type check)."""
    target_mbid = rel.get("target", {}).get("id", "")
    if not target_mbid:
        return
    rel_type = rel.get("type", "unknown")
    target_type = rel.get("target-type", source_type)

    async with conn.cursor() as cur:
        await cur.execute(
            """INSERT INTO musicbrainz.relationships
               (source_mbid, target_mbid, source_entity_type, target_entity_type,
                relationship_type, begin_date, end_date, ended, attributes)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT DO NOTHING""",
            (
                source_mbid,
                target_mbid,
                source_type,
                target_type,
                rel_type,
                rel.get("begin"),
                rel.get("end"),
                rel.get("ended", False),
                Jsonb(rel.get("attributes", [])),
            ),
        )


async def _insert_external_link(conn: Any, mbid: str, entity_type: str, link: dict[str, Any]) -> None:
    """Insert an external link record."""
    service = link.get("service", "")
    url = link.get("url", "")
    if not service or not url:
        return

    async with conn.cursor() as cur:
        await cur.execute(
            """INSERT INTO musicbrainz.external_links (mbid, entity_type, service_name, url)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT DO NOTHING""",
            (mbid, entity_type, service, url),
        )


def make_message_handler(data_type: str, process_fn: Any) -> Any:
    """Create an async message handler for the given data type."""

    async def handler(message: AbstractIncomingMessage) -> None:
        global shutdown_requested
        if shutdown_requested:
            await message.nack(requeue=True)
            return

        try:
            body = loads(message.body)
        except Exception:
            logger.error("❌ Failed to parse message body", data_type=data_type)
            await message.ack()
            return

        # Check for file_complete/extraction_complete control messages
        msg_type = body.get("type")
        if msg_type in ("file_complete", "extraction_complete"):
            if msg_type == "file_complete":
                completed_files.add(data_type)
                logger.info("✅ File complete", data_type=data_type)
            await message.ack()
            return

        try:
            async with connection_pool.connection() as conn:
                await process_fn(conn, body)
                await conn.commit()
            message_counts[data_type] += 1
            last_message_time[data_type] = time.time()
            await message.ack()
        except (InterfaceError, OperationalError) as e:
            logger.warning("⚠️ Database error, requeueing", error=str(e), data_type=data_type)
            await message.nack(requeue=True)
        except Exception as e:
            logger.error("❌ Processing error", error=str(e), data_type=data_type)
            await message.nack(requeue=True)

    return handler


HANDLERS: dict[str, Any] = {
    "artists": make_message_handler("artists", process_artist),
    "labels": make_message_handler("labels", process_label),
    "releases": make_message_handler("releases", process_release),
}


async def main() -> None:
    """Main entry point for brainztableinator."""
    global config, connection_pool, shutdown_requested

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    setup_logging("brainztableinator", log_file=Path("/logs/brainztableinator.log"))
    logger.info("🧠 Starting brainztableinator service")

    # Startup delay
    startup_delay = int(os.environ.get("STARTUP_DELAY", "0"))
    if startup_delay > 0:
        logger.info(f"⏳ Waiting {startup_delay}s before starting...")
        await asyncio.sleep(startup_delay)

    health_server = HealthServer(8010, get_health_data)
    health_server.start_background()

    try:
        config = BrainztableinatorConfig.from_env()
    except ValueError as e:
        logger.error("❌ Configuration error", error=str(e))
        return

    # Initialize PostgreSQL connection pool
    host_parts = config.postgres_host.split(":")
    pg_host = host_parts[0]
    pg_port = int(host_parts[1]) if len(host_parts) > 1 else 5432

    connection_pool = AsyncPostgreSQLPool(
        connection_params={
            "host": pg_host,
            "port": pg_port,
            "dbname": config.postgres_database,
            "user": config.postgres_username,
            "password": config.postgres_password,
        },
        max_connections=10,
        min_connections=2,
        max_retries=5,
        health_check_interval=30,
    )
    await connection_pool.initialize()

    # ASCII art
    print(r"""
    ____             _            _        _     _      _             _
   | __ ) _ __ __ _ (_)_ __  ____| |_ __ _| |__ | | ___(_)_ __   __ _| |_ ___  _ __
   |  _ \| '__/ _` || | '_ \|_  / __/ _` | '_ \| |/ _ \ | '_ \ / _` | __/ _ \| '__|
   | |_) | | | (_| || | | | |/ /| || (_| | |_) | |  __/ | | | | (_| | || (_) | |
   |____/|_|  \__,_||_|_| |_/___|\__\__,_|_.__/|_|\___|_|_| |_|\__,_|\__\___/|_|
    """)

    # RabbitMQ connection
    rabbitmq_manager = AsyncResilientRabbitMQ(
        url=config.amqp_connection, max_retries=10, heartbeat=600,
    )

    max_connect_attempts = 5
    amqp_connection = None
    for attempt in range(1, max_connect_attempts + 1):
        try:
            amqp_connection = await rabbitmq_manager.connect()
            break
        except Exception as e:
            if attempt == max_connect_attempts:
                logger.error("❌ Failed to connect to RabbitMQ", error=str(e))
                return
            delay = min(5 * attempt, 30)
            logger.warning(f"⚠️ RabbitMQ connection attempt {attempt} failed, retrying in {delay}s")
            await asyncio.sleep(delay)

    async with amqp_connection:
        channel = await amqp_connection.channel()
        await channel.set_qos(prefetch_count=50)

        # Declare exchanges, DLX/DLQ, and queues per data type
        for data_type in MUSICBRAINZ_DATA_TYPES:
            exchange_name = f"{MUSICBRAINZ_EXCHANGE_PREFIX}-{data_type}"
            queue_name = f"{AMQP_QUEUE_PREFIX_BRAINZTABLEINATOR}-{data_type}"

            exchange = await channel.declare_exchange(exchange_name, "fanout", durable=True)
            dlx = await channel.declare_exchange(f"{queue_name}.dlx", "fanout", durable=True)
            dlq = await channel.declare_queue(f"{queue_name}.dlq", durable=True, arguments={"x-queue-type": "classic"})
            await dlq.bind(dlx)

            queue = await channel.declare_queue(
                queue_name, durable=True,
                arguments={"x-queue-type": "quorum", "x-dead-letter-exchange": f"{queue_name}.dlx", "x-delivery-limit": 20},
            )
            await queue.bind(exchange)
            queues[data_type] = queue

            handler = HANDLERS[data_type]
            tag = await queue.consume(handler, consumer_tag=f"brainztableinator-{data_type}")
            consumer_tags[data_type] = tag
            logger.info(f"📡 Consuming {exchange_name} → {queue_name}")

        # Main loop
        while not shutdown_requested:
            await asyncio.sleep(1)

        logger.info("🛑 Shutting down brainztableinator")

    if connection_pool:
        await connection_pool.close()
    health_server.stop()
    logger.info("✅ Brainztableinator service shutdown complete")


if __name__ == "__main__":
    try:
        run(main())
    except KeyboardInterrupt:
        logger.warning("⚠️ Application interrupted")
    except Exception as e:
        logger.error("❌ Application error", error=str(e))
    finally:
        logger.info("✅ Brainztableinator service shutdown complete")
```

- [ ] **Step 6: Update root pyproject.toml**

Add `brainztableinator` to workspace members and optional dependencies:

```toml
[tool.uv.workspace]
members = ["api", "common", "dashboard", "explore", "graphinator", "insights", "mcp-server", "schema-init", "tableinator", "brainztableinator"]

[project.optional-dependencies]
brainztableinator = ["psycopg[binary]>=3.1.0"]
```

Add to `[tool.coverage.run]` source list:

```toml
source = ["api", "common", "dashboard", "explore", "graphinator", "insights", "mcp-server", "schema-init", "tableinator", "brainztableinator"]
```

- [ ] **Step 7: Run lint and type check**

Run: `uv run ruff check brainztableinator/ && uv run mypy brainztableinator/ 2>&1 | tail -10`
Expected: No errors

- [ ] **Step 8: Commit**

```bash
git add brainztableinator/ common/config.py common/__init__.py pyproject.toml
git commit -m "feat: add brainztableinator service scaffold for MusicBrainz PostgreSQL storage (#168)"
```

---

### Task 10: Brainztableinator tests, CI, Docker, coverage

**Files:**
- Create: `tests/brainztableinator/conftest.py`
- Create: `tests/brainztableinator/test_brainztableinator.py`
- Create: `.coveragerc.brainztableinator`
- Create: `brainztableinator/Dockerfile`
- Modify: `docker-compose.yml`
- Modify: `justfile`
- Modify: `.github/workflows/test.yml`

- [ ] **Step 1: Create test conftest.py**

Create `tests/brainztableinator/conftest.py`:

```python
"""Test fixtures for brainztableinator tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def disable_batch_mode():
    """Disable batch mode for all brainztableinator tests."""
    with patch("brainztableinator.brainztableinator.BATCH_MODE", False):
        yield


@pytest.fixture
def mock_async_pool():
    """Create a mock AsyncPostgreSQLPool."""

    def create_pool(mock_connection=None):
        pool = MagicMock()
        conn = mock_connection or AsyncMock()
        conn_ctx = AsyncMock()
        conn_ctx.__aenter__ = AsyncMock(return_value=conn)
        conn_ctx.__aexit__ = AsyncMock(return_value=False)
        pool.connection = MagicMock(return_value=conn_ctx)
        pool.initialize = AsyncMock()
        pool.close = AsyncMock()
        return pool

    return create_pool
```

- [ ] **Step 2: Create test file**

Create `tests/brainztableinator/test_brainztableinator.py`:

```python
"""Tests for brainztableinator service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from brainztableinator.brainztableinator import (
    _insert_external_link,
    _insert_relationship,
    get_health_data,
    process_artist,
    process_label,
    process_release,
)


class TestHealthData:
    def test_health_data_starting(self):
        with patch("brainztableinator.brainztableinator.connection_pool", None):
            data = get_health_data()
            assert data["status"] == "starting"
            assert data["service"] == "brainztableinator"

    def test_health_data_healthy(self):
        with patch("brainztableinator.brainztableinator.connection_pool", MagicMock()):
            data = get_health_data()
            assert data["status"] == "healthy"


class TestProcessArtist:
    @pytest.mark.asyncio
    async def test_process_artist_basic(self, mock_async_pool):
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_cursor), __aexit__=AsyncMock(return_value=False)))

        record = {
            "id": "mbid-123",
            "data": {
                "discogs_artist_id": 108713,
                "name": "The Beatles",
                "sort_name": "Beatles, The",
                "mb_type": "Group",
                "gender": None,
                "life_span": {"begin": "1960", "end": "1970", "ended": True},
                "area": "London",
                "begin_area": "Liverpool",
                "end_area": None,
                "disambiguation": "the band",
                "aliases": [],
                "tags": [{"name": "rock", "count": 42}],
                "relations": [],
                "external_links": [],
            },
        }

        await process_artist(mock_conn, record)
        mock_cursor.execute.assert_called_once()
        call_args = mock_cursor.execute.call_args
        assert "INSERT INTO musicbrainz.artists" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_process_artist_with_relationships(self, mock_async_pool):
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_cursor), __aexit__=AsyncMock(return_value=False)))

        record = {
            "id": "mbid-123",
            "data": {
                "discogs_artist_id": 100,
                "name": "Test",
                "relations": [
                    {"type": "collaboration", "target": {"id": "mbid-456"}, "begin": "2020"},
                ],
                "external_links": [
                    {"service": "wikipedia", "url": "https://en.wikipedia.org/wiki/Test"},
                ],
            },
        }

        await process_artist(mock_conn, record)
        # Should have: 1 artist insert + 1 relationship insert + 1 external link insert = 3 execute calls
        assert mock_cursor.execute.call_count == 3


class TestProcessLabel:
    @pytest.mark.asyncio
    async def test_process_label_basic(self, mock_async_pool):
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_cursor), __aexit__=AsyncMock(return_value=False)))

        record = {
            "id": "label-mbid",
            "data": {
                "discogs_label_id": 1000,
                "name": "Test Label",
                "mb_type": "Original Production",
                "relations": [],
                "external_links": [],
            },
        }

        await process_label(mock_conn, record)
        call_args = mock_cursor.execute.call_args
        assert "INSERT INTO musicbrainz.labels" in call_args[0][0]


class TestProcessRelease:
    @pytest.mark.asyncio
    async def test_process_release_basic(self, mock_async_pool):
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_cursor), __aexit__=AsyncMock(return_value=False)))

        record = {
            "id": "release-mbid",
            "data": {
                "discogs_release_id": 5000,
                "name": "Test Album",
                "barcode": "1234567890",
                "status": "Official",
                "release_group_mbid": "rg-mbid",
                "relations": [],
                "external_links": [],
            },
        }

        await process_release(mock_conn, record)
        call_args = mock_cursor.execute.call_args
        assert "INSERT INTO musicbrainz.releases" in call_args[0][0]
```

- [ ] **Step 3: Create coverage config**

Create `.coveragerc.brainztableinator`:

```ini
[run]
include =
    brainztableinator/**

omit =
    */tests/*
    */__init__.py
```

- [ ] **Step 4: Create Dockerfile**

Create `brainztableinator/Dockerfile` following the existing pattern:

```dockerfile
ARG PYTHON_VERSION=3.13
ARG UID=1000
ARG GID=1000

# Build stage
FROM python:${PYTHON_VERSION}-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.11.1 /uv /bin/uv
ENV UV_SYSTEM_PYTHON=1 UV_CACHE_DIR=/tmp/.cache/uv UV_LINK_MODE=copy
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY common/pyproject.toml ./common/
COPY brainztableinator/pyproject.toml ./brainztableinator/

RUN --mount=type=cache,target=/tmp/.cache/uv \
    uv sync --frozen --no-dev --extra brainztableinator && \
    find /app/.venv -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; \
    find /app/.venv -name "*.pyc" -delete 2>/dev/null; \
    find /app/.venv -name "*.pyo" -delete 2>/dev/null; \
    true

COPY common/ ./common/
COPY brainztableinator/ ./brainztableinator/

# Runtime stage
FROM python:${PYTHON_VERSION}-slim
ARG UID=1000
ARG GID=1000

RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

RUN groupadd -r -g ${GID} discogsography && \
    useradd -r -l -u ${UID} -g discogsography -m -s /bin/bash discogsography && \
    mkdir -p /logs && chown discogsography:discogsography /logs

COPY --from=builder --chown=discogsography:discogsography /app/.venv /app/.venv
COPY --from=builder --chown=discogsography:discogsography /app/common /app/common
COPY --from=builder --chown=discogsography:discogsography /app/brainztableinator /app/brainztableinator

RUN printf '#!/bin/sh\nset -e\nsleep "${STARTUP_DELAY:-0}"\nexec /app/.venv/bin/python -m brainztableinator.brainztableinator "$@"\n' \
    > /app/start.sh && chmod +x /app/start.sh

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8010/health || exit 1

USER discogsography:discogsography
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
VOLUME ["/logs"]
CMD ["/app/start.sh"]
```

- [ ] **Step 5: Add brainztableinator to docker-compose.yml**

```yaml
  brainztableinator:
    build:
      context: .
      dockerfile: brainztableinator/Dockerfile
      args:
        PYTHON_VERSION: ${PYTHON_VERSION:-3.13}
        UID: ${UID:-1000}
        GID: ${GID:-1000}
    image: discogsography/brainztableinator:latest
    container_name: discogsography-brainztableinator
    hostname: brainztableinator
    user: "${UID:-1000}:${GID:-1000}"
    environment:
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
      POSTGRES_HOST: postgres
      POSTGRES_USERNAME: ${POSTGRES_USERNAME:-discogsography}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-discogsography}
      POSTGRES_DATABASE: ${POSTGRES_DATABASE:-discogsography}
      RABBITMQ_HOST: rabbitmq
      RABBITMQ_USERNAME: ${RABBITMQ_USERNAME:-discogsography}
      RABBITMQ_PASSWORD: ${RABBITMQ_PASSWORD:-discogsography}
      POSTGRES_BATCH_MODE: "true"
      POSTGRES_BATCH_SIZE: "500"
      POSTGRES_BATCH_FLUSH_INTERVAL: "2.0"
      CONSUMER_CANCEL_DELAY: "300"
      QUEUE_CHECK_INTERVAL: "3600"
      STARTUP_DELAY: "25"
    depends_on:
      schema-init:
        condition: service_completed_successfully
      rabbitmq:
        condition: service_healthy
      postgres:
        condition: service_healthy
    networks:
      - discogsography
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:8010/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s
    restart: on-failure
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    read_only: true
    tmpfs:
      - /tmp
    volumes:
      - brainztableinator_logs:/logs
```

Add `brainztableinator_logs:` to the volumes section.

- [ ] **Step 6: Add justfile commands**

```just
[group('test')]
test-brainztableinator:
    uv run pytest tests/brainztableinator/ -v \
        --cov --cov-config=.coveragerc.brainztableinator \
        --cov-report=xml --cov-report=json --cov-report=term
```

- [ ] **Step 7: Add CI job to test.yml**

Add a new job following the existing pattern:

```yaml
  test-brainztableinator:
    name: "🧠 Brainztableinator Tests"
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - uses: extractions/setup-just@v2
      - run: just install
      - run: just test-brainztableinator
      - uses: codecov/codecov-action@v5
        with:
          files: coverage.xml
          flags: brainztableinator
          token: ${{ secrets.CODECOV_TOKEN }}
```

- [ ] **Step 8: Run tests**

Run: `uv run pytest tests/brainztableinator/ -v 2>&1 | tail -20`
Expected: All PASS

- [ ] **Step 9: Commit**

```bash
git add tests/brainztableinator/ .coveragerc.brainztableinator brainztableinator/Dockerfile docker-compose.yml justfile .github/workflows/test.yml
git commit -m "feat: add brainztableinator tests, Docker, CI, and coverage (#168)"
```

---

## Phase 3: Brainzgraphinator — Metadata Enrichment

### Task 11: Neo4j MBID indexes in schema-init

**Files:**
- Modify: `schema-init/neo4j_schema.py`

- [ ] **Step 1: Write test**

```python
def test_mbid_indexes_defined():
    """MBID indexes exist for Artist, Label, Release."""
    from schema_init.neo4j_schema import SCHEMA_STATEMENTS
    names = [name for name, _ in SCHEMA_STATEMENTS]
    assert "artist_mbid" in names
    assert "label_mbid" in names
    assert "release_mbid" in names
```

- [ ] **Step 2: Add indexes to neo4j_schema.py**

Append to `SCHEMA_STATEMENTS`:

```python
    ("artist_mbid", "CREATE INDEX artist_mbid IF NOT EXISTS FOR (a:Artist) ON (a.mbid)"),
    ("label_mbid", "CREATE INDEX label_mbid IF NOT EXISTS FOR (l:Label) ON (l.mbid)"),
    ("release_mbid", "CREATE INDEX release_mbid IF NOT EXISTS FOR (r:Release) ON (r.mbid)"),
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/schema-init/ -v 2>&1 | tail -10`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add schema-init/neo4j_schema.py tests/schema-init/
git commit -m "feat(schema-init): add Neo4j MBID indexes for MusicBrainz enrichment (#168)"
```

---

### Task 12: Brainzgraphinator service scaffold

**Files:**
- Create: `brainzgraphinator/__init__.py`
- Create: `brainzgraphinator/pyproject.toml`
- Create: `brainzgraphinator/brainzgraphinator.py`
- Modify: `common/config.py`
- Modify: `common/__init__.py`
- Modify: `pyproject.toml` (root)

- [ ] **Step 1: Add BrainzgraphinatorConfig to common/config.py**

After `BrainztableinatorConfig`:

```python
@dataclass(frozen=True)
class BrainzgraphinatorConfig:
    """Configuration for the brainzgraphinator service."""

    amqp_connection: str
    neo4j_host: str
    neo4j_username: str
    neo4j_password: str

    @classmethod
    def from_env(cls) -> "BrainzgraphinatorConfig":
        """Create configuration from environment variables."""
        missing = []
        neo4j_host = os.environ.get("NEO4J_HOST")
        if not neo4j_host:
            missing.append("NEO4J_HOST")
        neo4j_username = os.environ.get("NEO4J_USERNAME")
        if not neo4j_username:
            missing.append("NEO4J_USERNAME")
        neo4j_password = get_secret("NEO4J_PASSWORD")
        if not neo4j_password:
            missing.append("NEO4J_PASSWORD")
        if missing:
            msg = f"Missing required environment variables: {', '.join(missing)}"
            raise ValueError(msg)
        return cls(
            amqp_connection=_build_amqp_url(),
            neo4j_host=neo4j_host,  # type: ignore[arg-type]
            neo4j_username=neo4j_username,  # type: ignore[arg-type]
            neo4j_password=neo4j_password,
        )
```

Export from `common/__init__.py`.

- [ ] **Step 2: Create brainzgraphinator service files**

Create `brainzgraphinator/__init__.py`, `brainzgraphinator/pyproject.toml` (same pattern as brainztableinator but with `neo4j-rust-ext` dependency).

- [ ] **Step 3: Create brainzgraphinator/brainzgraphinator.py**

Follow graphinator pattern. Key differences from brainztableinator:

```python
"""Brainzgraphinator service — enriches Neo4j nodes with MusicBrainz metadata."""

# ... imports similar to graphinator ...
from common import (
    AMQP_QUEUE_PREFIX_BRAINZGRAPHINATOR,
    MUSICBRAINZ_DATA_TYPES,
    MUSICBRAINZ_EXCHANGE_PREFIX,
    AsyncResilientNeo4jDriver,
    AsyncResilientRabbitMQ,
    BrainzgraphinatorConfig,
    HealthServer,
    setup_logging,
)

# Enrichment stats for health endpoint
enrichment_stats = {
    "entities_enriched": 0,
    "entities_skipped_no_discogs_match": 0,
    "relationships_created": 0,
    "relationships_skipped_missing_side": 0,
}


def enrich_artist(tx: Any, record: dict[str, Any]) -> bool:
    """Enrich existing Artist node with MusicBrainz metadata."""
    data = record.get("data", record)
    discogs_id = data.get("discogs_artist_id")

    if discogs_id is None:
        enrichment_stats["entities_skipped_no_discogs_match"] += 1
        return True  # Skip but ack

    life_span = data.get("life_span", {})

    result = tx.run(
        """MATCH (a:Artist {id: $discogs_id})
           SET a.mbid = $mbid,
               a.mb_type = $mb_type,
               a.mb_gender = $gender,
               a.mb_begin_date = $begin_date,
               a.mb_end_date = $end_date,
               a.mb_area = $area,
               a.mb_begin_area = $begin_area,
               a.mb_end_area = $end_area,
               a.mb_disambiguation = $disambiguation,
               a.mb_updated_at = datetime()
           RETURN a.id AS id""",
        discogs_id=discogs_id,
        mbid=record.get("id"),
        mb_type=data.get("mb_type"),
        gender=data.get("gender"),
        begin_date=life_span.get("begin"),
        end_date=life_span.get("end"),
        area=data.get("area"),
        begin_area=data.get("begin_area"),
        end_area=data.get("end_area"),
        disambiguation=data.get("disambiguation"),
    )

    if result.single():
        enrichment_stats["entities_enriched"] += 1
    else:
        enrichment_stats["entities_skipped_no_discogs_match"] += 1

    return True


def enrich_label(tx: Any, record: dict[str, Any]) -> bool:
    """Enrich existing Label node with MusicBrainz metadata."""
    data = record.get("data", record)
    discogs_id = data.get("discogs_label_id")

    if discogs_id is None:
        enrichment_stats["entities_skipped_no_discogs_match"] += 1
        return True

    life_span = data.get("life_span", {})

    result = tx.run(
        """MATCH (l:Label {id: $discogs_id})
           SET l.mbid = $mbid,
               l.mb_type = $mb_type,
               l.mb_label_code = $label_code,
               l.mb_begin_date = $begin_date,
               l.mb_end_date = $end_date,
               l.mb_area = $area,
               l.mb_updated_at = datetime()
           RETURN l.id AS id""",
        discogs_id=discogs_id,
        mbid=record.get("id"),
        mb_type=data.get("mb_type"),
        label_code=data.get("label_code"),
        begin_date=life_span.get("begin"),
        end_date=life_span.get("end"),
        area=data.get("area"),
    )

    if result.single():
        enrichment_stats["entities_enriched"] += 1
    else:
        enrichment_stats["entities_skipped_no_discogs_match"] += 1

    return True


def enrich_release(tx: Any, record: dict[str, Any]) -> bool:
    """Enrich existing Release node with MusicBrainz metadata."""
    data = record.get("data", record)
    discogs_id = data.get("discogs_release_id")

    if discogs_id is None:
        enrichment_stats["entities_skipped_no_discogs_match"] += 1
        return True

    result = tx.run(
        """MATCH (r:Release {id: $discogs_id})
           SET r.mbid = $mbid,
               r.mb_barcode = $barcode,
               r.mb_status = $status,
               r.mb_updated_at = datetime()
           RETURN r.id AS id""",
        discogs_id=discogs_id,
        mbid=record.get("id"),
        barcode=data.get("barcode"),
        status=data.get("status"),
    )

    if result.single():
        enrichment_stats["entities_enriched"] += 1
    else:
        enrichment_stats["entities_skipped_no_discogs_match"] += 1

    return True
```

The `main()` function follows graphinator's pattern — health on port 8011, queue prefix `musicbrainz-brainzgraphinator`, consuming from 3 exchanges.

- [ ] **Step 4: Update root pyproject.toml**

Add `brainzgraphinator` to workspace members, optional deps, and coverage source.

- [ ] **Step 5: Run lint and type check**

Run: `uv run ruff check brainzgraphinator/ && uv run mypy brainzgraphinator/`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add brainzgraphinator/ common/config.py common/__init__.py pyproject.toml
git commit -m "feat: add brainzgraphinator service scaffold for Neo4j metadata enrichment (#168)"
```

---

### Task 13: Brainzgraphinator tests, CI, Docker, coverage

**Files:** Same pattern as Task 10 but for brainzgraphinator.

- [ ] **Step 1: Create tests/brainzgraphinator/conftest.py**

```python
"""Test fixtures for brainzgraphinator tests."""

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def disable_batch_mode():
    """Disable batch mode for all brainzgraphinator tests."""
    with patch("brainzgraphinator.brainzgraphinator.BATCH_MODE", False):
        yield
```

- [ ] **Step 2: Create tests/brainzgraphinator/test_brainzgraphinator.py**

```python
"""Tests for brainzgraphinator service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from brainzgraphinator.brainzgraphinator import (
    enrich_artist,
    enrich_label,
    enrich_release,
    enrichment_stats,
    get_health_data,
)


class TestHealthData:
    def test_health_data_starting(self):
        with patch("brainzgraphinator.brainzgraphinator.graph", None):
            data = get_health_data()
            assert data["status"] == "starting"
            assert data["service"] == "brainzgraphinator"


class TestEnrichArtist:
    def test_enrich_artist_with_discogs_match(self):
        tx = MagicMock()
        tx.run.return_value.single.return_value = {"id": 108713}

        record = {
            "id": "mbid-123",
            "data": {
                "discogs_artist_id": 108713,
                "name": "The Beatles",
                "mb_type": "Group",
                "gender": None,
                "life_span": {"begin": "1960", "end": "1970"},
                "area": "London",
                "begin_area": "Liverpool",
                "end_area": None,
                "disambiguation": "the band",
            },
        }

        result = enrich_artist(tx, record)
        assert result is True
        tx.run.assert_called_once()
        cypher = tx.run.call_args[0][0]
        assert "MATCH (a:Artist {id: $discogs_id})" in cypher
        assert "SET a.mbid = $mbid" in cypher

    def test_enrich_artist_no_discogs_id_skips(self):
        tx = MagicMock()

        record = {
            "id": "mbid-456",
            "data": {
                "discogs_artist_id": None,
                "name": "Unknown MB Artist",
            },
        }

        result = enrich_artist(tx, record)
        assert result is True
        tx.run.assert_not_called()

    def test_enrich_artist_no_neo4j_match_skips(self):
        tx = MagicMock()
        tx.run.return_value.single.return_value = None

        record = {
            "id": "mbid-789",
            "data": {
                "discogs_artist_id": 99999999,
                "name": "Not In Graph",
                "mb_type": "Person",
                "life_span": {},
            },
        }

        result = enrich_artist(tx, record)
        assert result is True


class TestEnrichLabel:
    def test_enrich_label_with_match(self):
        tx = MagicMock()
        tx.run.return_value.single.return_value = {"id": 1000}

        record = {
            "id": "label-mbid",
            "data": {
                "discogs_label_id": 1000,
                "name": "Test Label",
                "mb_type": "Original Production",
                "label_code": 123,
                "life_span": {"begin": "1990"},
                "area": "UK",
            },
        }

        result = enrich_label(tx, record)
        assert result is True
        assert "MATCH (l:Label {id: $discogs_id})" in tx.run.call_args[0][0]


class TestEnrichRelease:
    def test_enrich_release_with_match(self):
        tx = MagicMock()
        tx.run.return_value.single.return_value = {"id": 5000}

        record = {
            "id": "release-mbid",
            "data": {
                "discogs_release_id": 5000,
                "name": "Test Album",
                "barcode": "1234567890",
                "status": "Official",
            },
        }

        result = enrich_release(tx, record)
        assert result is True
        assert "MATCH (r:Release {id: $discogs_id})" in tx.run.call_args[0][0]
```

- [ ] **Step 3: Create .coveragerc.brainzgraphinator, Dockerfile, Docker compose, justfile, CI**

Follow exact same pattern as Task 10, substituting:
- Port: 8011
- Service name: brainzgraphinator
- Database: Neo4j (NEO4J_HOST, NEO4J_USERNAME, NEO4J_PASSWORD)
- Depends on: schema-init, rabbitmq, neo4j

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/brainzgraphinator/ -v 2>&1 | tail -20`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add tests/brainzgraphinator/ .coveragerc.brainzgraphinator brainzgraphinator/Dockerfile docker-compose.yml justfile .github/workflows/test.yml
git commit -m "feat: add brainzgraphinator tests, Docker, CI, and coverage (#168)"
```

---

## Phase 4: Brainzgraphinator — Relationship Enrichment

### Task 14: Relationship edge creation logic

**Files:**
- Modify: `brainzgraphinator/brainzgraphinator.py`

- [ ] **Step 1: Write tests for relationship creation**

In `tests/brainzgraphinator/test_brainzgraphinator.py`, add:

```python
from brainzgraphinator.brainzgraphinator import create_relationship_edges, MB_RELATIONSHIP_MAP


class TestRelationshipEdges:
    def test_relationship_map_defined(self):
        """All expected MB relationship types are mapped."""
        assert "member of band" in MB_RELATIONSHIP_MAP
        assert "collaboration" in MB_RELATIONSHIP_MAP
        assert "teacher" in MB_RELATIONSHIP_MAP
        assert "tribute" in MB_RELATIONSHIP_MAP
        assert "founder" in MB_RELATIONSHIP_MAP
        assert "supporting musician" in MB_RELATIONSHIP_MAP
        assert "subgroup" in MB_RELATIONSHIP_MAP
        assert "artist rename" in MB_RELATIONSHIP_MAP

    def test_create_edge_both_sides_matched(self):
        tx = MagicMock()
        tx.run.return_value.single.return_value = {"created": True}

        rel = {
            "type": "collaboration",
            "target": {"id": "target-mbid"},
            "target_discogs_artist_id": 200,
            "begin": "2020",
            "end": None,
            "attributes": [],
        }

        created = create_relationship_edges(tx, 100, [rel])
        assert created == 1
        cypher = tx.run.call_args[0][0]
        assert "COLLABORATED_WITH" in cypher
        assert "source: 'musicbrainz'" in cypher

    def test_create_edge_target_no_discogs_id_skips(self):
        tx = MagicMock()

        rel = {
            "type": "collaboration",
            "target": {"id": "target-mbid"},
            "target_discogs_artist_id": None,
        }

        created = create_relationship_edges(tx, 100, [rel])
        assert created == 0
        tx.run.assert_not_called()

    def test_create_edge_unknown_type_skips(self):
        tx = MagicMock()

        rel = {
            "type": "some_unknown_relationship",
            "target": {"id": "target-mbid"},
            "target_discogs_artist_id": 200,
        }

        created = create_relationship_edges(tx, 100, [rel])
        assert created == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/brainzgraphinator/test_brainzgraphinator.py::TestRelationshipEdges -v`
Expected: FAIL

- [ ] **Step 3: Implement relationship edge creation**

In `brainzgraphinator/brainzgraphinator.py`, add:

```python
# Mapping from MusicBrainz relationship type names to Neo4j edge types
MB_RELATIONSHIP_MAP: dict[str, str] = {
    "member of band": "MEMBER_OF",
    "collaboration": "COLLABORATED_WITH",
    "teacher": "TAUGHT",
    "tribute": "TRIBUTE_TO",
    "founder": "FOUNDED",
    "supporting musician": "SUPPORTED",
    "subgroup": "SUBGROUP_OF",
    "artist rename": "RENAMED_TO",
}


def create_relationship_edges(tx: Any, source_discogs_id: int, relations: list[dict[str, Any]]) -> int:
    """Create Neo4j relationship edges from MB relations.

    Only creates edges when both source and target have Discogs IDs.
    This is a deliberate scope decision — we enrich the existing Discogs graph,
    not build a parallel MusicBrainz graph. See design spec "Known Limitations"
    for full rationale.

    Returns the number of edges created.
    """
    created = 0

    for rel in relations:
        rel_type = rel.get("type", "")
        neo4j_edge = MB_RELATIONSHIP_MAP.get(rel_type)
        if neo4j_edge is None:
            continue  # Unknown relationship type, skip

        target_discogs_id = rel.get("target_discogs_artist_id")
        if target_discogs_id is None:
            enrichment_stats["relationships_skipped_missing_side"] += 1
            continue

        begin_date = rel.get("begin")
        end_date = rel.get("end")
        attributes = rel.get("attributes", [])

        # Use MERGE to be idempotent — safe for re-imports
        # Note: Cypher doesn't support parameterized relationship types,
        # so we use string formatting for the edge type (safe — comes from our map, not user input)
        cypher = f"""
            MATCH (a1:Artist {{id: $source_id}})
            MATCH (a2:Artist {{id: $target_id}})
            MERGE (a1)-[r:{neo4j_edge}]->(a2)
            SET r.begin_date = $begin_date,
                r.end_date = $end_date,
                r.attributes = $attributes,
                r.source = 'musicbrainz'
            RETURN true AS created
        """

        result = tx.run(
            cypher,
            source_id=source_discogs_id,
            target_id=target_discogs_id,
            begin_date=begin_date,
            end_date=end_date,
            attributes=attributes,
        )

        if result.single():
            created += 1
            enrichment_stats["relationships_created"] += 1
        else:
            enrichment_stats["relationships_skipped_missing_side"] += 1

    return created
```

- [ ] **Step 4: Integrate into enrich_artist**

Update `enrich_artist` to call `create_relationship_edges` after metadata enrichment:

```python
def enrich_artist(tx: Any, record: dict[str, Any]) -> bool:
    # ... existing metadata enrichment ...

    # Create relationship edges (Phase 4)
    relations = data.get("relations", [])
    if relations and discogs_id is not None:
        create_relationship_edges(tx, discogs_id, relations)

    return True
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/brainzgraphinator/ -v 2>&1 | tail -20`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add brainzgraphinator/brainzgraphinator.py tests/brainzgraphinator/test_brainzgraphinator.py
git commit -m "feat(brainzgraphinator): add relationship edge creation with skip-if-unmapped logic (#168)"
```

---

## Phase 5: API Endpoints

### Task 15: MusicBrainz API router

**Files:**
- Create: `api/routers/musicbrainz.py`
- Create: `api/queries/musicbrainz_queries.py`
- Modify: `api/api.py`

- [ ] **Step 1: Write tests first**

Create `tests/api/test_musicbrainz_endpoints.py`:

```python
"""Tests for MusicBrainz API endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def mock_neo4j_session():
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


@pytest.fixture
def mock_neo4j(mock_neo4j_session):
    driver = MagicMock()
    driver.session = MagicMock(return_value=mock_neo4j_session)
    return driver


class TestMusicBrainzMetadata:
    def test_get_artist_musicbrainz_found(self, test_client, mock_neo4j, mock_neo4j_session):
        mock_result = AsyncMock()
        mock_result.data = AsyncMock(return_value=[{
            "mbid": "b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d",
            "mb_type": "Group",
            "mb_gender": None,
            "mb_begin_date": "1960",
            "mb_end_date": "1970",
            "mb_area": "London",
            "mb_begin_area": "Liverpool",
            "mb_disambiguation": "the Beatles",
        }])
        mock_neo4j_session.run = AsyncMock(return_value=mock_result)

        with patch("api.routers.musicbrainz._neo4j_driver", mock_neo4j):
            response = test_client.get("/api/artist/108713/musicbrainz")

        assert response.status_code == 200
        data = response.json()
        assert data["mbid"] == "b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d"
        assert data["type"] == "Group"

    def test_get_artist_musicbrainz_not_found(self, test_client, mock_neo4j, mock_neo4j_session):
        mock_result = AsyncMock()
        mock_result.data = AsyncMock(return_value=[])
        mock_neo4j_session.run = AsyncMock(return_value=mock_result)

        with patch("api.routers.musicbrainz._neo4j_driver", mock_neo4j):
            response = test_client.get("/api/artist/999999/musicbrainz")

        assert response.status_code == 404


class TestArtistRelationships:
    def test_get_artist_relationships(self, test_client, mock_neo4j, mock_neo4j_session):
        mock_result = AsyncMock()
        mock_result.data = AsyncMock(return_value=[
            {
                "type": "COLLABORATED_WITH",
                "target_id": 200,
                "target_name": "Artist B",
                "direction": "outgoing",
                "begin_date": "2020",
                "end_date": None,
                "attributes": [],
            },
        ])
        mock_neo4j_session.run = AsyncMock(return_value=mock_result)

        with patch("api.routers.musicbrainz._neo4j_driver", mock_neo4j):
            response = test_client.get("/api/artist/108713/relationships")

        assert response.status_code == 200
        data = response.json()
        assert len(data["relationships"]) == 1
        assert data["relationships"][0]["type"] == "COLLABORATED_WITH"


class TestExternalLinks:
    def test_get_external_links(self, test_client, mock_pool):
        # Mock PostgreSQL query result
        with patch("api.routers.musicbrainz._pool", mock_pool):
            response = test_client.get("/api/artist/108713/external-links")

        assert response.status_code == 200


class TestEnrichmentStatus:
    def test_get_enrichment_status(self, test_client, mock_pool, mock_neo4j, mock_neo4j_session):
        with patch("api.routers.musicbrainz._pool", mock_pool), \
             patch("api.routers.musicbrainz._neo4j_driver", mock_neo4j):
            response = test_client.get("/api/enrichment/status")

        assert response.status_code == 200
```

- [ ] **Step 2: Create api/queries/musicbrainz_queries.py**

```python
"""Query functions for MusicBrainz enrichment data."""

from typing import Any

from psycopg.rows import dict_row

from common.query_debug import execute_sql


async def get_artist_musicbrainz(neo4j_driver: Any, discogs_id: int) -> dict[str, Any] | None:
    """Fetch MusicBrainz metadata for a Discogs artist from Neo4j."""
    async with neo4j_driver.session() as session:
        result = await session.run(
            """MATCH (a:Artist {id: $discogs_id})
               WHERE a.mbid IS NOT NULL
               RETURN a.mbid AS mbid, a.mb_type AS type, a.mb_gender AS gender,
                      a.mb_begin_date AS begin_date, a.mb_end_date AS end_date,
                      a.mb_area AS area, a.mb_begin_area AS begin_area,
                      a.mb_disambiguation AS disambiguation""",
            discogs_id=discogs_id,
        )
        records = await result.data()
        if not records:
            return None
        row = records[0]
        return {
            "discogs_id": discogs_id,
            "mbid": row["mbid"],
            "type": row["type"],
            "gender": row["gender"],
            "begin_date": row["begin_date"],
            "end_date": row["end_date"],
            "area": row["area"],
            "begin_area": row["begin_area"],
            "disambiguation": row["disambiguation"],
        }


async def get_artist_mb_relationships(neo4j_driver: Any, discogs_id: int) -> list[dict[str, Any]]:
    """Fetch MusicBrainz-sourced relationships for a Discogs artist from Neo4j."""
    async with neo4j_driver.session() as session:
        result = await session.run(
            """MATCH (a:Artist {id: $discogs_id})-[r]->(target:Artist)
               WHERE r.source = 'musicbrainz'
               RETURN type(r) AS type, target.id AS target_id, target.name AS target_name,
                      'outgoing' AS direction, r.begin_date AS begin_date,
                      r.end_date AS end_date, r.attributes AS attributes
               UNION
               MATCH (a:Artist {id: $discogs_id})<-[r]-(source:Artist)
               WHERE r.source = 'musicbrainz'
               RETURN type(r) AS type, source.id AS target_id, source.name AS target_name,
                      'incoming' AS direction, r.begin_date AS begin_date,
                      r.end_date AS end_date, r.attributes AS attributes""",
            discogs_id=discogs_id,
        )
        return await result.data()


async def get_artist_external_links(pool: Any, discogs_id: int) -> list[dict[str, Any]]:
    """Fetch external links for a Discogs artist from PostgreSQL."""
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(
            cur,
            """SELECT el.service_name AS service, el.url
               FROM musicbrainz.external_links el
               JOIN musicbrainz.artists a ON a.mbid = el.mbid
               WHERE a.discogs_artist_id = %s AND el.entity_type = 'artist'
               ORDER BY el.service_name""",
            (discogs_id,),
        )
        return await cur.fetchall()


async def get_enrichment_status(pool: Any, neo4j_driver: Any) -> dict[str, Any]:
    """Fetch enrichment coverage statistics from both databases."""
    stats: dict[str, Any] = {"musicbrainz": {}}

    # PostgreSQL counts
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        for entity in ["artists", "labels", "releases"]:
            discogs_col = f"discogs_{entity[:-1]}_id"  # artists -> discogs_artist_id
            await execute_sql(cur, f"SELECT COUNT(*) AS total FROM musicbrainz.{entity}")
            total = (await cur.fetchone())["total"]
            await execute_sql(cur, f"SELECT COUNT(*) AS matched FROM musicbrainz.{entity} WHERE {discogs_col} IS NOT NULL")
            matched = (await cur.fetchone())["matched"]
            stats["musicbrainz"][entity] = {"total_mb": total, "matched_to_discogs": matched}

        await execute_sql(cur, "SELECT COUNT(*) AS total FROM musicbrainz.relationships")
        rel_total = (await cur.fetchone())["total"]
        stats["musicbrainz"]["relationships"] = {"total_in_mb": rel_total}

    # Neo4j enrichment count
    async with neo4j_driver.session() as session:
        for entity, label in [("artists", "Artist"), ("labels", "Label"), ("releases", "Release")]:
            result = await session.run(f"MATCH (n:{label}) WHERE n.mbid IS NOT NULL RETURN COUNT(n) AS count")
            records = await result.data()
            stats["musicbrainz"][entity]["enriched_in_neo4j"] = records[0]["count"] if records else 0

        result = await session.run(
            "MATCH ()-[r]->() WHERE r.source = 'musicbrainz' RETURN COUNT(r) AS count"
        )
        records = await result.data()
        stats["musicbrainz"]["relationships"]["created_in_neo4j"] = records[0]["count"] if records else 0

    return stats
```

- [ ] **Step 3: Create api/routers/musicbrainz.py**

```python
"""MusicBrainz enrichment API endpoints."""

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

from api.limiter import limiter
from api.queries.musicbrainz_queries import (
    get_artist_external_links,
    get_artist_mb_relationships,
    get_artist_musicbrainz,
    get_enrichment_status,
)

logger = structlog.get_logger(__name__)
router = APIRouter()

_pool: Any = None
_neo4j_driver: Any = None


def configure(pool: Any, neo4j_driver: Any) -> None:
    """Configure router dependencies."""
    global _pool, _neo4j_driver
    _pool = pool
    _neo4j_driver = neo4j_driver


@router.get("/api/artist/{artist_id}/musicbrainz", status_code=status.HTTP_200_OK)
@limiter.limit("30/minute")
async def artist_musicbrainz(request: Request, artist_id: int) -> JSONResponse:
    """Get MusicBrainz metadata for a Discogs artist."""
    if _neo4j_driver is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")

    data = await get_artist_musicbrainz(_neo4j_driver, artist_id)
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No MusicBrainz data for this artist")

    return JSONResponse(content=data)


@router.get("/api/artist/{artist_id}/relationships", status_code=status.HTTP_200_OK)
@limiter.limit("30/minute")
async def artist_relationships(request: Request, artist_id: int) -> JSONResponse:
    """Get MusicBrainz-sourced relationships for a Discogs artist."""
    if _neo4j_driver is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")

    relationships = await get_artist_mb_relationships(_neo4j_driver, artist_id)
    return JSONResponse(content={"discogs_id": artist_id, "relationships": relationships})


@router.get("/api/artist/{artist_id}/external-links", status_code=status.HTTP_200_OK)
@limiter.limit("30/minute")
async def artist_external_links(request: Request, artist_id: int) -> JSONResponse:
    """Get external links (Wikipedia, Wikidata, etc.) for a Discogs artist."""
    if _pool is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")

    links = await get_artist_external_links(_pool, artist_id)
    return JSONResponse(content={"discogs_id": artist_id, "links": links})


@router.get("/api/enrichment/status", status_code=status.HTTP_200_OK)
@limiter.limit("10/minute")
async def enrichment_status_endpoint(request: Request) -> JSONResponse:
    """Get MusicBrainz enrichment coverage statistics."""
    if _pool is None or _neo4j_driver is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")

    stats = await get_enrichment_status(_pool, _neo4j_driver)
    return JSONResponse(content=stats)
```

- [ ] **Step 4: Register router in api/api.py**

In the imports section:

```python
from api.routers import musicbrainz as _musicbrainz_router
```

In the `lifespan()` context manager, after other router configurations:

```python
_musicbrainz_router.configure(_pool, _neo4j)
```

After the existing `app.include_router()` calls:

```python
app.include_router(_musicbrainz_router.router)
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/api/test_musicbrainz_endpoints.py -v 2>&1 | tail -20`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add api/routers/musicbrainz.py api/queries/musicbrainz_queries.py api/api.py tests/api/test_musicbrainz_endpoints.py
git commit -m "feat(api): add MusicBrainz metadata, relationships, and enrichment status endpoints (#168)"
```

---

## Phase 6: Incremental Sync

### Task 16: Document incremental sync strategy

**Files:**
- Modify: `docs/superpowers/specs/2026-03-25-musicbrainz-integration-design.md`

- [ ] **Step 1: Verify idempotent writes**

The incremental sync strategy relies on idempotent writes. Verify:
- brainztableinator uses `ON CONFLICT (mbid) DO UPDATE` — re-importing is safe
- brainzgraphinator uses `MATCH ... SET` (updates in place) and `MERGE` for edges — re-importing is safe
- State markers use version-specific files — new dump = new version = full reprocess

No code changes needed — the idempotent design already supports re-importing full dumps.

- [ ] **Step 2: Document the operational process**

Update the design spec's Phase 6 section with the operational process:

```markdown
### Operational Process

1. Download latest MB JSONL dumps to the `musicbrainz_data` Docker volume
2. Restart the `extractor-musicbrainz` container (or trigger via `/trigger` endpoint)
3. State marker detects new version → triggers full reprocess
4. brainzgraphinator and brainztableinator process all messages idempotently
5. Previous data is updated in place, new data is inserted

This can be automated via cron or a scheduled CI job that:
- Checks for new MB dumps (published Wednesdays and Saturdays)
- Downloads to the volume
- Triggers extraction
```

- [ ] **Step 3: Commit**

```bash
git add docs/
git commit -m "docs: document MusicBrainz incremental sync operational process (#168)"
```

---

### Task 17: Final documentation and cleanup

**Files:**
- Modify: `docs/architecture.md` (if it exists)
- Create: `brainzgraphinator/README.md`
- Create: `brainztableinator/README.md`

- [ ] **Step 1: Create service READMEs**

Create `brainzgraphinator/README.md`:

```markdown
# Brainzgraphinator

Enriches existing Neo4j knowledge graph nodes with MusicBrainz metadata and relationships.

## What it does

- Consumes messages from `musicbrainz-artists`, `musicbrainz-labels`, `musicbrainz-releases` fanout exchanges
- For entities with a Discogs ID match: adds MBID, type, gender, dates, area, and other metadata as `mb_`-prefixed properties
- Creates new relationship edges (COLLABORATED_WITH, TAUGHT, TRIBUTE_TO, etc.) between matched entities
- Skips entities and relationships without Discogs matches (see design spec for rationale)
- All writes are idempotent — safe for re-import

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `NEO4J_HOST` | — | Neo4j hostname |
| `NEO4J_USERNAME` | — | Neo4j username |
| `NEO4J_PASSWORD` | — | Neo4j password |
| `RABBITMQ_HOST` | rabbitmq | RabbitMQ hostname |
| `NEO4J_BATCH_MODE` | false | Enable batch processing |
| `STARTUP_DELAY` | 0 | Seconds to wait before starting |

## Health

Port 8011: `GET /health`
```

Create `brainztableinator/README.md` with equivalent content for PostgreSQL.

- [ ] **Step 2: Update architecture docs if they exist**

Add the new services to any architecture diagrams or service tables.

- [ ] **Step 3: Run full test suite**

Run: `just test 2>&1 | tail -20`
Expected: All tests pass including new services

- [ ] **Step 4: Run lint on all changed files**

Run: `just lint 2>&1 | tail -20`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add brainzgraphinator/README.md brainztableinator/README.md docs/
git commit -m "docs: add brainzgraphinator and brainztableinator READMEs and update architecture (#168)"
```
