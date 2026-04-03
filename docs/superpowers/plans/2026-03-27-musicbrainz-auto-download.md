# MusicBrainz Auto-Download Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically download MusicBrainz JSON dump files from MetaBrainz, extract them, and integrate with the existing extraction pipeline including periodic version checking.

**Architecture:** Add `MbDownloader` to `musicbrainz_downloader.rs` that scrapes the MetaBrainz directory index for version-stamped directories, downloads `.tar.xz` archives, verifies SHA256 checksums, and extracts the JSONL data files. The extraction pipeline is updated to download before discovery, and `main.rs` wraps the MusicBrainz path in a periodic loop matching the Discogs pattern.

**Tech Stack:** Rust, reqwest (HTTP streaming), tar + xz2 (archive extraction), sha2 (checksum verification), mockito (test HTTP mocking)

______________________________________________________________________

### Task 1: Add `tar` dependency to Cargo.toml

`xz2` is already present. Only `tar` needs to be added.

**Files:**

- Modify: `extractor/Cargo.toml:25-26`

- [ ] **Step 1: Add `tar` crate to dependencies**

In `extractor/Cargo.toml`, add `tar` after `flate2` in the compression section:

```toml
# Compression handling
flate2 = "1.1"
xz2 = "0.1"
tar = "0.4"
```

- [ ] **Step 2: Verify it compiles**

Run: `cd /Users/Robert/Code/public/discogsography/extractor && cargo check`
Expected: Compiles successfully with no errors.

- [ ] **Step 3: Commit**

```bash
git add extractor/Cargo.toml extractor/Cargo.lock
git commit -m "feat: add tar dependency for MusicBrainz archive extraction"
```

______________________________________________________________________

### Task 2: Add `musicbrainz_dump_url` to ExtractorConfig

**Files:**

- Modify: `extractor/src/config.rs:8` (struct definition)

- Modify: `extractor/src/config.rs:24` (Default impl)

- Modify: `extractor/src/config.rs:63` (from_env)

- Test: `extractor/src/tests/config_tests.rs`

- [ ] **Step 1: Write test for new config field**

Add to `extractor/src/tests/config_tests.rs`:

```rust
#[test]
fn test_musicbrainz_dump_url_default() {
    // Clear env to ensure defaults
    std::env::remove_var("MUSICBRAINZ_DUMP_URL");
    let config = ExtractorConfig::default();
    assert_eq!(config.musicbrainz_dump_url, "https://data.metabrainz.org/pub/musicbrainz/data/json-dumps/");
}

#[test]
fn test_musicbrainz_dump_url_from_env() {
    std::env::set_var("MUSICBRAINZ_DUMP_URL", "http://localhost:9999/dumps/");
    let config = ExtractorConfig::from_env().unwrap();
    assert_eq!(config.musicbrainz_dump_url, "http://localhost:9999/dumps/");
    std::env::remove_var("MUSICBRAINZ_DUMP_URL");
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/Robert/Code/public/discogsography/extractor && cargo test --features test-support config_tests -- --nocapture`
Expected: FAIL — `musicbrainz_dump_url` field does not exist.

- [ ] **Step 3: Add field to ExtractorConfig struct**

In `extractor/src/config.rs`, add to the `ExtractorConfig` struct after `musicbrainz_root`:

```rust
pub musicbrainz_dump_url: String,
```

- [ ] **Step 4: Add default value**

In `extractor/src/config.rs` `Default` impl, add after `musicbrainz_root`:

```rust
musicbrainz_dump_url: "https://data.metabrainz.org/pub/musicbrainz/data/json-dumps/".to_string(),
```

- [ ] **Step 5: Add env var loading in from_env()**

In `extractor/src/config.rs` `from_env()`, add after the `musicbrainz_root` line:

```rust
let musicbrainz_dump_url = std::env::var("MUSICBRAINZ_DUMP_URL")
    .unwrap_or_else(|_| "https://data.metabrainz.org/pub/musicbrainz/data/json-dumps/".to_string());
```

And add `musicbrainz_dump_url,` to the `Ok(Self { ... })` return struct.

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /Users/Robert/Code/public/discogsography/extractor && cargo test --features test-support config_tests -- --nocapture`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add extractor/src/config.rs extractor/src/tests/config_tests.rs
git commit -m "feat: add musicbrainz_dump_url config field"
```

______________________________________________________________________

### Task 3: Add `find_latest_mb_directory` function

Scans the local filesystem for version-stamped subdirectories (YYYYMMDD-HHMMSS pattern) and returns the path to the latest one.

**Files:**

- Modify: `extractor/src/musicbrainz_downloader.rs`

- Test: `extractor/src/tests/musicbrainz_downloader_tests.rs`

- [ ] **Step 1: Write tests for find_latest_mb_directory**

Add to `extractor/src/tests/musicbrainz_downloader_tests.rs`:

```rust
#[test]
fn test_find_latest_mb_directory_single() {
    let dir = TempDir::new().unwrap();
    std::fs::create_dir(dir.path().join("20260325-001001")).unwrap();

    let result = find_latest_mb_directory(dir.path());
    assert_eq!(result, Some(dir.path().join("20260325-001001")));
}

#[test]
fn test_find_latest_mb_directory_multiple() {
    let dir = TempDir::new().unwrap();
    std::fs::create_dir(dir.path().join("20260321-001002")).unwrap();
    std::fs::create_dir(dir.path().join("20260325-001001")).unwrap();

    let result = find_latest_mb_directory(dir.path());
    assert_eq!(result, Some(dir.path().join("20260325-001001")));
}

#[test]
fn test_find_latest_mb_directory_empty() {
    let dir = TempDir::new().unwrap();

    let result = find_latest_mb_directory(dir.path());
    assert_eq!(result, None);
}

#[test]
fn test_find_latest_mb_directory_ignores_non_version_dirs() {
    let dir = TempDir::new().unwrap();
    std::fs::create_dir(dir.path().join("some-random-dir")).unwrap();
    std::fs::create_dir(dir.path().join("20260325-001001")).unwrap();

    let result = find_latest_mb_directory(dir.path());
    assert_eq!(result, Some(dir.path().join("20260325-001001")));
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/Robert/Code/public/discogsography/extractor && cargo test --features test-support musicbrainz_downloader_tests -- --nocapture`
Expected: FAIL — `find_latest_mb_directory` not found.

- [ ] **Step 3: Implement find_latest_mb_directory**

Add to `extractor/src/musicbrainz_downloader.rs`, before the `#[cfg(test)]` block:

```rust
/// Scan `root` for subdirectories matching the MusicBrainz version pattern
/// (YYYYMMDD-HHMMSS) and return the path to the most recent one.
pub fn find_latest_mb_directory(root: &Path) -> Option<PathBuf> {
    let version_pattern = regex::Regex::new(r"^\d{8}-\d{6}$").ok()?;

    let mut versions: Vec<String> = match std::fs::read_dir(root) {
        Ok(rd) => rd
            .filter_map(|e| e.ok())
            .filter(|e| e.file_type().map(|ft| ft.is_dir()).unwrap_or(false))
            .filter_map(|e| {
                let name = e.file_name().to_string_lossy().to_string();
                if version_pattern.is_match(&name) { Some(name) } else { None }
            })
            .collect(),
        Err(_) => return None,
    };

    versions.sort_by(|a, b| b.cmp(a));
    versions.first().map(|v| root.join(v))
}
```

Add `use regex::Regex;` is not needed since regex is used inline. The `regex` crate is already a dependency of the extractor.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/Robert/Code/public/discogsography/extractor && cargo test --features test-support musicbrainz_downloader_tests -- --nocapture`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add extractor/src/musicbrainz_downloader.rs extractor/src/tests/musicbrainz_downloader_tests.rs
git commit -m "feat: add find_latest_mb_directory for version directory scanning"
```

______________________________________________________________________

### Task 4: Update `discover_mb_dump_files` to match bare `.jsonl` files

The extracted files are `artist.jsonl`, not `artist.jsonl.xz`. Discovery needs to find them.

**Files:**

- Modify: `extractor/src/musicbrainz_downloader.rs:10-14` (MB_FILE_PATTERNS)

- Test: `extractor/src/tests/musicbrainz_downloader_tests.rs`

- [ ] **Step 1: Write test for bare .jsonl discovery**

Add to `extractor/src/tests/musicbrainz_downloader_tests.rs`:

```rust
#[test]
fn test_discover_mb_dump_files_bare_jsonl() {
    let dir = TempDir::new().unwrap();
    std::fs::write(dir.path().join("artist.jsonl"), b"fake").unwrap();
    std::fs::write(dir.path().join("label.jsonl"), b"fake").unwrap();
    std::fs::write(dir.path().join("release.jsonl"), b"fake").unwrap();

    let found = discover_mb_dump_files(dir.path()).unwrap();

    assert_eq!(found.len(), 3);
    assert!(found.contains_key(&DataType::Artists));
    assert!(found.contains_key(&DataType::Labels));
    assert!(found.contains_key(&DataType::Releases));
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/Robert/Code/public/discogsography/extractor && cargo test --features test-support test_discover_mb_dump_files_bare_jsonl -- --nocapture`
Expected: FAIL — bare `.jsonl` files not matched by current patterns.

- [ ] **Step 3: Update MB_FILE_PATTERNS to include bare .jsonl**

In `extractor/src/musicbrainz_downloader.rs`, update the `MB_FILE_PATTERNS` constant:

```rust
const MB_FILE_PATTERNS: &[(DataType, &[&str])] = &[
    (DataType::Artists, &["artist.jsonl.xz", "mbdump-artist.jsonl.xz", "artist.jsonl"]),
    (DataType::Labels, &["label.jsonl.xz", "mbdump-label.jsonl.xz", "label.jsonl"]),
    (DataType::Releases, &["release.jsonl.xz", "mbdump-release.jsonl.xz", "release.jsonl"]),
];
```

Also update the fuzzy match in `discover_mb_dump_files` to also match files ending in just `.jsonl` (not only `.jsonl.xz`). Change the fuzzy match condition from:

```rust
if name_str.contains(keyword) && name_str.ends_with(".jsonl.xz") {
```

to:

```rust
if name_str.contains(keyword) && (name_str.ends_with(".jsonl.xz") || name_str.ends_with(".jsonl")) {
```

- [ ] **Step 4: Run all discovery tests to verify they pass**

Run: `cd /Users/Robert/Code/public/discogsography/extractor && cargo test --features test-support musicbrainz_downloader_tests -- --nocapture`
Expected: All tests PASS (existing + new).

- [ ] **Step 5: Commit**

```bash
git add extractor/src/musicbrainz_downloader.rs extractor/src/tests/musicbrainz_downloader_tests.rs
git commit -m "feat: support bare .jsonl files in MusicBrainz dump discovery"
```

______________________________________________________________________

### Task 5: Implement `MbDownloader` core — version scraping and SHA256 parsing

**Files:**

- Modify: `extractor/src/musicbrainz_downloader.rs`

- Test: `extractor/src/tests/musicbrainz_downloader_tests.rs`

- [ ] **Step 1: Write tests for version scraping and SHA256 parsing**

Add to `extractor/src/tests/musicbrainz_downloader_tests.rs`:

```rust
#[test]
fn test_parse_version_directories_from_html() {
    let html = r#"<html><body>
        <a href="20260321-001002/">20260321-001002/</a>
        <a href="20260325-001001/">20260325-001001/</a>
        <a href="LATEST">LATEST</a>
        <a href="latest-is-20260325-001001">latest-is-20260325-001001</a>
        <a href="../">../</a>
    </body></html>"#;

    let versions = parse_version_directories(html);
    assert_eq!(versions, vec!["20260325-001001".to_string(), "20260321-001002".to_string()]);
}

#[test]
fn test_parse_version_directories_empty() {
    let html = r#"<html><body><a href="../">../</a></body></html>"#;
    let versions = parse_version_directories(html);
    assert!(versions.is_empty());
}

#[test]
fn test_parse_sha256sums() {
    let content = "dacfc4327ad44074d043c4184b77bebbcb4b41e926cc8f57742e6b2572d33624 *artist.tar.xz\n\
                   92952108bdae756d9c75cad1c82a2c1dfdc50fcd60d5405f622b93a7a7793007 *label.tar.xz\n\
                   48aec88150f56a51f685f585854c92e56711a4bd867a6ada48a93f60f5a73682 *release.tar.xz\n";

    let checksums = parse_sha256sums(content);
    assert_eq!(checksums.len(), 3);
    assert_eq!(checksums.get("artist.tar.xz").unwrap(), "dacfc4327ad44074d043c4184b77bebbcb4b41e926cc8f57742e6b2572d33624");
    assert_eq!(checksums.get("label.tar.xz").unwrap(), "92952108bdae756d9c75cad1c82a2c1dfdc50fcd60d5405f622b93a7a7793007");
    assert_eq!(checksums.get("release.tar.xz").unwrap(), "48aec88150f56a51f685f585854c92e56711a4bd867a6ada48a93f60f5a73682");
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/Robert/Code/public/discogsography/extractor && cargo test --features test-support test_parse_version_directories -- --nocapture`
Expected: FAIL — functions not defined.

- [ ] **Step 3: Implement MbDownloader struct and helper functions**

Add to `extractor/src/musicbrainz_downloader.rs`, after the existing imports, add new imports:

```rust
use regex::Regex;
use sha2::{Digest, Sha256};
use std::io;
use tokio::fs;
use tokio::io::AsyncWriteExt;
use tracing::{error, info, warn};
```

Note: `info` and `warn` are already imported; `debug` too. Add only the missing ones (`error`, `Regex`, `Sha256`, `Digest`, `io`, `fs`, `AsyncWriteExt`).

Then add the struct and helper functions:

```rust
/// MusicBrainz entity names for download (singular, matching tarball names)
const MB_ENTITIES: &[&str] = &["artist", "label", "release"];

const MB_MAX_DOWNLOAD_RETRIES: u32 = 3;

#[cfg(not(test))]
const MB_RETRY_BASE_DELAY_MS: u64 = 2_000;
#[cfg(test)]
const MB_RETRY_BASE_DELAY_MS: u64 = 10;

/// Result of a MusicBrainz download attempt
#[derive(Debug)]
pub enum MbDownloadResult {
    /// Files already present and up-to-date for this version
    AlreadyCurrent(String),
    /// New version downloaded and extracted
    Downloaded(String),
}

impl MbDownloadResult {
    /// Get the version string regardless of variant
    pub fn version(&self) -> &str {
        match self {
            MbDownloadResult::AlreadyCurrent(v) | MbDownloadResult::Downloaded(v) => v,
        }
    }
}

pub struct MbDownloader {
    output_directory: PathBuf,
    base_url: String,
}

/// Parse version directory names (YYYYMMDD-HHMMSS) from an HTML index page.
/// Returns them sorted descending (most recent first).
pub fn parse_version_directories(html: &str) -> Vec<String> {
    let pattern = Regex::new(r#"href="(\d{8}-\d{6})/?"#).unwrap();
    let mut versions: Vec<String> = pattern
        .captures_iter(html)
        .filter_map(|cap| cap.get(1).map(|m| m.as_str().to_string()))
        .collect();
    versions.sort_by(|a, b| b.cmp(a));
    versions.dedup();
    versions
}

/// Parse a SHA256SUMS file into a map of filename -> hex hash.
pub fn parse_sha256sums(content: &str) -> HashMap<String, String> {
    content
        .lines()
        .filter_map(|line| {
            let line = line.trim();
            if line.is_empty() { return None; }
            let mut parts = line.splitn(2, char::is_whitespace);
            let hash = parts.next()?.trim().to_string();
            let filename = parts.next()?.trim().trim_start_matches('*').to_string();
            Some((filename, hash))
        })
        .collect()
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/Robert/Code/public/discogsography/extractor && cargo test --features test-support test_parse_version_directories test_parse_sha256sums -- --nocapture`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add extractor/src/musicbrainz_downloader.rs extractor/src/tests/musicbrainz_downloader_tests.rs
git commit -m "feat: add MbDownloader struct with version scraping and SHA256 parsing"
```

______________________________________________________________________

### Task 6: Implement tar extraction helper

**Files:**

- Modify: `extractor/src/musicbrainz_downloader.rs`

- Test: `extractor/src/tests/musicbrainz_downloader_tests.rs`

- [ ] **Step 1: Write test for tar extraction**

Add to `extractor/src/tests/musicbrainz_downloader_tests.rs`:

```rust
#[test]
fn test_extract_entity_from_tarball() {
    use std::io::Write;

    let dir = TempDir::new().unwrap();

    // Create a .tar.xz file with the expected structure: label/mbdump/label
    let tar_path = dir.path().join("label.tar.xz");
    let out_path = dir.path().join("label.jsonl");

    // Build tar archive in memory
    let mut tar_data = Vec::new();
    {
        let mut builder = tar::Builder::new(&mut tar_data);

        // Add label/mbdump/label with some JSONL content
        let content = b"{\"id\":\"abc-123\",\"name\":\"Test Label\"}\n{\"id\":\"def-456\",\"name\":\"Another Label\"}\n";
        let mut header = tar::Header::new_gnu();
        header.set_path("label/mbdump/label").unwrap();
        header.set_size(content.len() as u64);
        header.set_mode(0o644);
        header.set_cksum();
        builder.append(&header, &content[..]).unwrap();

        // Add a decoy file that should be ignored
        let decoy = b"This is the README";
        let mut decoy_header = tar::Header::new_gnu();
        decoy_header.set_path("label/README").unwrap();
        decoy_header.set_size(decoy.len() as u64);
        decoy_header.set_mode(0o644);
        decoy_header.set_cksum();
        builder.append(&decoy_header, &decoy[..]).unwrap();

        builder.finish().unwrap();
    }

    // XZ-compress the tar data
    let mut xz_file = std::fs::File::create(&tar_path).unwrap();
    let mut encoder = xz2::write::XzEncoder::new(Vec::new(), 1);
    encoder.write_all(&tar_data).unwrap();
    let compressed = encoder.finish().unwrap();
    xz_file.write_all(&compressed).unwrap();
    drop(xz_file);

    // Extract
    extract_entity_from_tarball(&tar_path, "label", &out_path).unwrap();

    // Verify
    assert!(out_path.exists());
    let extracted = std::fs::read_to_string(&out_path).unwrap();
    assert!(extracted.contains("Test Label"));
    assert!(extracted.contains("Another Label"));

    // Verify tar was NOT deleted (caller handles cleanup)
    assert!(tar_path.exists());
}

#[test]
fn test_extract_entity_from_tarball_missing_entity() {
    use std::io::Write;

    let dir = TempDir::new().unwrap();
    let tar_path = dir.path().join("artist.tar.xz");
    let out_path = dir.path().join("artist.jsonl");

    // Build tar with only a README, no mbdump/artist
    let mut tar_data = Vec::new();
    {
        let mut builder = tar::Builder::new(&mut tar_data);
        let content = b"readme content";
        let mut header = tar::Header::new_gnu();
        header.set_path("artist/README").unwrap();
        header.set_size(content.len() as u64);
        header.set_mode(0o644);
        header.set_cksum();
        builder.append(&header, &content[..]).unwrap();
        builder.finish().unwrap();
    }

    let mut xz_file = std::fs::File::create(&tar_path).unwrap();
    let mut encoder = xz2::write::XzEncoder::new(Vec::new(), 1);
    encoder.write_all(&tar_data).unwrap();
    let compressed = encoder.finish().unwrap();
    xz_file.write_all(&compressed).unwrap();
    drop(xz_file);

    let result = extract_entity_from_tarball(&tar_path, "artist", &out_path);
    assert!(result.is_err());
    assert!(!out_path.exists());
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/Robert/Code/public/discogsography/extractor && cargo test --features test-support test_extract_entity_from_tarball -- --nocapture`
Expected: FAIL — `extract_entity_from_tarball` not found.

- [ ] **Step 3: Implement extract_entity_from_tarball**

Add to `extractor/src/musicbrainz_downloader.rs`:

```rust
/// Extract the `mbdump/<entity>` file from a `.tar.xz` archive.
///
/// Only the target entry is extracted; all other entries are skipped.
/// Returns an error if the target entry is not found.
pub fn extract_entity_from_tarball(tar_path: &Path, entity: &str, out_path: &Path) -> Result<()> {
    let file = std::fs::File::open(tar_path)
        .with_context(|| format!("Failed to open tarball: {:?}", tar_path))?;
    let xz = xz2::read::XzDecoder::new(file);
    let mut archive = tar::Archive::new(xz);

    let target_suffix = format!("mbdump/{}", entity);

    for entry_result in archive.entries().context("Failed to read tar entries")? {
        let mut entry = entry_result.context("Failed to read tar entry")?;
        let path = entry.path().context("Failed to read entry path")?;

        if path.ends_with(&target_suffix) {
            let mut out_file = std::fs::File::create(out_path)
                .with_context(|| format!("Failed to create output file: {:?}", out_path))?;
            io::copy(&mut entry, &mut out_file)
                .with_context(|| format!("Failed to extract {} to {:?}", entity, out_path))?;
            info!("📋 Extracted {} from {:?} ({} bytes)", entity, tar_path, out_file.metadata()?.len());
            return Ok(());
        }
    }

    Err(anyhow::anyhow!("Entry '{}' not found in {:?}", target_suffix, tar_path))
}
```

Add `use anyhow::Context;` to the imports at the top of the file.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/Robert/Code/public/discogsography/extractor && cargo test --features test-support test_extract_entity_from_tarball -- --nocapture`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add extractor/src/musicbrainz_downloader.rs extractor/src/tests/musicbrainz_downloader_tests.rs
git commit -m "feat: add tar.xz extraction helper for MusicBrainz dumps"
```

______________________________________________________________________

### Task 7: Implement `MbDownloader::download_latest`

This is the main download orchestration method: scrape versions, check for existing files, download + verify + extract.

**Files:**

- Modify: `extractor/src/musicbrainz_downloader.rs`

- Test: `extractor/src/tests/musicbrainz_downloader_tests.rs`

- [ ] **Step 1: Write test for already-current scenario**

Add to `extractor/src/tests/musicbrainz_downloader_tests.rs`:

```rust
#[tokio::test]
async fn test_download_latest_already_current() {
    let dir = TempDir::new().unwrap();

    // Set up mock server
    let mut server = mockito::Server::new_async().await;
    let base_url = format!("{}/", server.url());

    let index_html = r#"<html><body>
        <a href="20260325-001001/">20260325-001001/</a>
    </body></html>"#;

    let _index_mock = server.mock("GET", "/")
        .with_status(200)
        .with_body(index_html)
        .create_async().await;

    // Create existing version directory with all 3 entity files
    let version_dir = dir.path().join("20260325-001001");
    std::fs::create_dir(&version_dir).unwrap();
    std::fs::write(version_dir.join("artist.jsonl"), b"data").unwrap();
    std::fs::write(version_dir.join("label.jsonl"), b"data").unwrap();
    std::fs::write(version_dir.join("release.jsonl"), b"data").unwrap();

    let downloader = MbDownloader::new(dir.path().to_path_buf(), base_url);
    let result = downloader.download_latest().await.unwrap();

    assert!(matches!(result, MbDownloadResult::AlreadyCurrent(v) if v == "20260325-001001"));
}
```

- [ ] **Step 2: Write test for new version download**

Add to `extractor/src/tests/musicbrainz_downloader_tests.rs`:

```rust
#[tokio::test]
async fn test_download_latest_new_version() {
    use std::io::Write;

    let dir = TempDir::new().unwrap();

    let mut server = mockito::Server::new_async().await;
    let base_url = format!("{}/", server.url());

    // Index page with one version
    let index_html = r#"<html><body>
        <a href="20260325-001001/">20260325-001001/</a>
    </body></html>"#;
    let _index_mock = server.mock("GET", "/")
        .with_status(200)
        .with_body(index_html)
        .create_async().await;

    // Build a tiny tar.xz for each entity
    let mut tar_bodies: HashMap<String, Vec<u8>> = HashMap::new();
    let mut sha256_lines = String::new();

    for entity in &["artist", "label", "release"] {
        let content = format!("{{\"id\":\"test-{}\"}}\n", entity);
        let mut tar_data = Vec::new();
        {
            let mut builder = tar::Builder::new(&mut tar_data);
            let bytes = content.as_bytes();
            let mut header = tar::Header::new_gnu();
            header.set_path(format!("{}/mbdump/{}", entity, entity)).unwrap();
            header.set_size(bytes.len() as u64);
            header.set_mode(0o644);
            header.set_cksum();
            builder.append(&header, bytes).unwrap();
            builder.finish().unwrap();
        }
        let mut encoder = xz2::write::XzEncoder::new(Vec::new(), 1);
        encoder.write_all(&tar_data).unwrap();
        let compressed = encoder.finish().unwrap();

        // Compute SHA256
        let hash = format!("{:x}", sha2::Sha256::digest(&compressed));
        sha256_lines.push_str(&format!("{} *{}.tar.xz\n", hash, entity));
        tar_bodies.insert(entity.to_string(), compressed);
    }

    // SHA256SUMS mock
    let _sha_mock = server.mock("GET", "/20260325-001001/SHA256SUMS")
        .with_status(200)
        .with_body(&sha256_lines)
        .create_async().await;

    // Tar file mocks
    let _artist_mock = server.mock("GET", "/20260325-001001/artist.tar.xz")
        .with_status(200)
        .with_body(tar_bodies.get("artist").unwrap().clone())
        .create_async().await;
    let _label_mock = server.mock("GET", "/20260325-001001/label.tar.xz")
        .with_status(200)
        .with_body(tar_bodies.get("label").unwrap().clone())
        .create_async().await;
    let _release_mock = server.mock("GET", "/20260325-001001/release.tar.xz")
        .with_status(200)
        .with_body(tar_bodies.get("release").unwrap().clone())
        .create_async().await;

    let downloader = MbDownloader::new(dir.path().to_path_buf(), base_url);
    let result = downloader.download_latest().await.unwrap();

    assert!(matches!(result, MbDownloadResult::Downloaded(v) if v == "20260325-001001"));

    // Verify extracted files exist
    let version_dir = dir.path().join("20260325-001001");
    assert!(version_dir.join("artist.jsonl").exists());
    assert!(version_dir.join("label.jsonl").exists());
    assert!(version_dir.join("release.jsonl").exists());

    // Verify temp files cleaned up
    assert!(!version_dir.join("artist.tar.xz.tmp").exists());
    assert!(!version_dir.join("label.tar.xz.tmp").exists());
    assert!(!version_dir.join("release.tar.xz.tmp").exists());

    // Verify content
    let artist_content = std::fs::read_to_string(version_dir.join("artist.jsonl")).unwrap();
    assert!(artist_content.contains("test-artist"));
}
```

- [ ] **Step 3: Write test for SHA256 mismatch**

Add to `extractor/src/tests/musicbrainz_downloader_tests.rs`:

```rust
#[tokio::test]
async fn test_download_latest_sha256_mismatch() {
    let dir = TempDir::new().unwrap();

    let mut server = mockito::Server::new_async().await;
    let base_url = format!("{}/", server.url());

    let index_html = r#"<html><body>
        <a href="20260325-001001/">20260325-001001/</a>
    </body></html>"#;
    let _index_mock = server.mock("GET", "/")
        .with_status(200)
        .with_body(index_html)
        .create_async().await;

    // SHA256SUMS with wrong hashes
    let _sha_mock = server.mock("GET", "/20260325-001001/SHA256SUMS")
        .with_status(200)
        .with_body("0000000000000000000000000000000000000000000000000000000000000000 *artist.tar.xz\n")
        .create_async().await;

    // Serve a valid tar.xz but with a hash that won't match
    let tar_data = vec![0u8; 10]; // Garbage data — will fail SHA256 check before tar parsing
    let _artist_mock = server.mock("GET", "/20260325-001001/artist.tar.xz")
        .with_status(200)
        .with_body(tar_data)
        .expect_at_least(1)
        .create_async().await;

    let downloader = MbDownloader::new(dir.path().to_path_buf(), base_url);
    let result = downloader.download_latest().await;

    assert!(result.is_err());
    let err_msg = format!("{}", result.unwrap_err());
    assert!(err_msg.contains("SHA256") || err_msg.contains("checksum"), "Error should mention checksum: {}", err_msg);
}
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd /Users/Robert/Code/public/discogsography/extractor && cargo test --features test-support test_download_latest -- --nocapture`
Expected: FAIL — `MbDownloader::new` and `download_latest` not implemented.

- [ ] **Step 5: Implement MbDownloader::new and download_latest**

Add to `extractor/src/musicbrainz_downloader.rs`, in the `impl MbDownloader` block:

```rust
impl MbDownloader {
    pub fn new(output_directory: PathBuf, base_url: String) -> Self {
        Self { output_directory, base_url }
    }

    /// Discover the latest MusicBrainz dump version and download it if not already present.
    pub async fn download_latest(&self) -> Result<MbDownloadResult> {
        // Step 1: Scrape index page for version directories
        info!("🌐 Fetching MusicBrainz dump index from {}...", self.base_url);
        let response = reqwest::get(&self.base_url)
            .await
            .context("Failed to fetch MusicBrainz dump index")?;
        let html = response.text().await.context("Failed to read index HTML")?;

        let versions = parse_version_directories(&html);
        if versions.is_empty() {
            return Err(anyhow::anyhow!("No version directories found at {}", self.base_url));
        }

        let version = &versions[0];
        info!("📋 Latest MusicBrainz dump version: {}", version);

        // Step 2: Check if already downloaded
        let version_dir = self.output_directory.join(version);
        if self.is_version_complete(&version_dir) {
            info!("✅ MusicBrainz dump {} already downloaded", version);
            return Ok(MbDownloadResult::AlreadyCurrent(version.clone()));
        }

        // Step 3: Download SHA256SUMS
        let sha_url = format!("{}{}/SHA256SUMS", self.base_url, version);
        info!("⬇️ Fetching SHA256SUMS from {}...", sha_url);
        let sha_response = reqwest::get(&sha_url)
            .await
            .context("Failed to fetch SHA256SUMS")?;
        let sha_content = sha_response.text().await.context("Failed to read SHA256SUMS")?;
        let checksums = parse_sha256sums(&sha_content);

        // Step 4: Create version directory
        fs::create_dir_all(&version_dir)
            .await
            .with_context(|| format!("Failed to create directory: {:?}", version_dir))?;

        // Step 5: Download, verify, and extract each entity
        for entity in MB_ENTITIES {
            let tarball_name = format!("{}.tar.xz", entity);
            let expected_hash = checksums.get(&tarball_name).ok_or_else(|| {
                anyhow::anyhow!("No SHA256 checksum found for {} in SHA256SUMS", tarball_name)
            })?;

            let download_url = format!("{}{}/{}", self.base_url, version, tarball_name);
            let tmp_path = version_dir.join(format!("{}.tmp", tarball_name));
            let out_path = version_dir.join(format!("{}.jsonl", entity));

            // Download with retry
            self.download_file(&download_url, &tmp_path, expected_hash, entity).await?;

            // Extract on blocking thread
            let extract_tmp = tmp_path.clone();
            let extract_entity = entity.to_string();
            let extract_out = out_path.clone();
            tokio::task::spawn_blocking(move || {
                extract_entity_from_tarball(&extract_tmp, &extract_entity, &extract_out)
            })
            .await
            .context("Extraction task panicked")??;

            // Clean up temp tarball
            if let Err(e) = fs::remove_file(&tmp_path).await {
                warn!("⚠️ Failed to remove temp tarball {:?}: {}", tmp_path, e);
            }

            info!("✅ Successfully downloaded and extracted MusicBrainz {} dump", entity);
        }

        info!("✅ MusicBrainz dump {} download complete", version);
        Ok(MbDownloadResult::Downloaded(version.clone()))
    }

    /// Check whether a version directory contains all expected entity JSONL files.
    fn is_version_complete(&self, version_dir: &Path) -> bool {
        if !version_dir.is_dir() {
            return false;
        }
        MB_ENTITIES.iter().all(|entity| version_dir.join(format!("{}.jsonl", entity)).exists())
    }

    /// Download a file with retry logic and SHA256 verification.
    async fn download_file(
        &self,
        url: &str,
        dest: &Path,
        expected_sha256: &str,
        entity: &str,
    ) -> Result<()> {
        use futures::StreamExt;

        let mut last_error: Option<anyhow::Error> = None;

        for attempt in 1..=MB_MAX_DOWNLOAD_RETRIES {
            if attempt > 1 {
                if dest.exists() {
                    let _ = fs::remove_file(dest).await;
                }
                let delay_ms = MB_RETRY_BASE_DELAY_MS * (1u64 << (attempt - 2));
                warn!("🔄 Retry {}/{} for {} (waiting {}ms)...", attempt - 1, MB_MAX_DOWNLOAD_RETRIES - 1, entity, delay_ms);
                tokio::time::sleep(tokio::time::Duration::from_millis(delay_ms)).await;
            }

            info!("⬇️ Downloading {} (attempt {}/{})...", entity, attempt, MB_MAX_DOWNLOAD_RETRIES);

            let response = match reqwest::get(url).await {
                Ok(r) => r,
                Err(e) => {
                    let msg = format!("Failed to start download for {}: {}", entity, e);
                    warn!("⚠️ {}", msg);
                    last_error = Some(anyhow::anyhow!(msg));
                    continue;
                }
            };

            if !response.status().is_success() {
                let msg = format!("HTTP error downloading {}: {}", entity, response.status());
                warn!("⚠️ {}", msg);
                last_error = Some(anyhow::anyhow!(msg));
                continue;
            }

            let mut file = fs::File::create(dest)
                .await
                .context("Failed to create download file")?;
            let mut hasher = Sha256::new();
            let mut downloaded: u64 = 0;
            let download_start = std::time::Instant::now();
            let mut last_progress_log = download_start;

            let mut stream = response.bytes_stream();
            let mut stream_error: Option<anyhow::Error> = None;

            while let Some(chunk_result) = stream.next().await {
                match chunk_result {
                    Ok(chunk) => {
                        hasher.update(&chunk);
                        if let Err(e) = file.write_all(&chunk).await {
                            stream_error = Some(anyhow::anyhow!("Write failed: {}", e));
                            break;
                        }
                        downloaded += chunk.len() as u64;

                        let now = std::time::Instant::now();
                        if now.duration_since(last_progress_log).as_secs() >= 10 {
                            let elapsed = download_start.elapsed().as_secs_f64();
                            let speed = if elapsed > 0.0 { (downloaded as f64 / 1_048_576.0) / elapsed } else { 0.0 };
                            info!("⬇️ {} — {:.1} MB received ({:.1} MB/s)", entity, downloaded as f64 / 1_048_576.0, speed);
                            last_progress_log = now;
                        }
                    }
                    Err(e) => {
                        stream_error = Some(anyhow::anyhow!("Stream error: {}", e));
                        break;
                    }
                }
            }

            if let Some(err) = stream_error {
                warn!("⚠️ Attempt {}/{} failed for {}: {}", attempt, MB_MAX_DOWNLOAD_RETRIES, entity, err);
                last_error = Some(err);
                continue;
            }

            if let Err(e) = file.flush().await {
                last_error = Some(anyhow::anyhow!("Flush failed: {}", e));
                continue;
            }
            if let Err(e) = file.sync_data().await {
                last_error = Some(anyhow::anyhow!("Sync failed: {}", e));
                continue;
            }

            // Verify SHA256
            let actual_hash = format!("{:x}", hasher.finalize());
            if actual_hash != expected_sha256 {
                let msg = format!(
                    "SHA256 mismatch for {}: expected {}, got {}",
                    entity, expected_sha256, actual_hash
                );
                warn!("⚠️ {}", msg);
                last_error = Some(anyhow::anyhow!(msg));
                let _ = fs::remove_file(dest).await;
                continue;
            }

            info!("✅ Downloaded {} ({:.2} MB, SHA256 verified)", entity, downloaded as f64 / 1_048_576.0);
            return Ok(());
        }

        Err(last_error.unwrap_or_else(|| anyhow::anyhow!("Download failed after {} attempts", MB_MAX_DOWNLOAD_RETRIES)))
    }
}
```

- [ ] **Step 6: Run all download tests to verify they pass**

Run: `cd /Users/Robert/Code/public/discogsography/extractor && cargo test --features test-support test_download_latest -- --nocapture`
Expected: PASS

- [ ] **Step 7: Run all musicbrainz_downloader tests**

Run: `cd /Users/Robert/Code/public/discogsography/extractor && cargo test --features test-support musicbrainz_downloader_tests -- --nocapture`
Expected: All tests PASS.

- [ ] **Step 8: Commit**

```bash
git add extractor/src/musicbrainz_downloader.rs extractor/src/tests/musicbrainz_downloader_tests.rs
git commit -m "feat: implement MbDownloader with streaming download, SHA256 verification, and retry"
```

______________________________________________________________________

### Task 8: Integrate download into `process_musicbrainz_data`

Update the extraction pipeline to download before discovery and use the versioned subdirectory.

**Files:**

- Modify: `extractor/src/extractor.rs:766-801`

- [ ] **Step 1: Update process_musicbrainz_data to download first**

In `extractor/src/extractor.rs`, modify `process_musicbrainz_data`. Replace the current discovery block (lines 777-804) with:

```rust
    use crate::musicbrainz_downloader::{MbDownloader, discover_mb_dump_files};
    use crate::jsonl_parser::{build_mbid_discogs_map_from_file, parse_mb_jsonl_file};

    let extraction_started_at = chrono::Utc::now();

    // Reset progress for new run
    {
        let mut s = state.write().await;
        s.extraction_progress = ExtractionProgress::default();
        s.last_extraction_time.clear();
        s.completed_files.clear();
        s.active_connections.clear();
        s.error_count = 0;
        s.extraction_status = ExtractionStatus::Running;
    }

    // Download latest MusicBrainz dump if needed
    let downloader = MbDownloader::new(
        config.musicbrainz_root.clone(),
        config.musicbrainz_dump_url.clone(),
    );
    let download_result = downloader.download_latest().await?;
    let version = download_result.version().to_string();
    let versioned_root = config.musicbrainz_root.join(&version);
    info!("📋 Using MusicBrainz dump version: {} from {:?}", version, versioned_root);

    // Discover dump files in the versioned directory
    let dump_files = discover_mb_dump_files(&versioned_root)?;

    if dump_files.is_empty() {
        warn!("⚠️ No MusicBrainz dump files found after download");
        let mut s = state.write().await;
        s.extraction_status = ExtractionStatus::Completed;
        return Ok(true);
    }
```

Remove the old `detect_mb_dump_version` call since `version` now comes from the download result. The rest of the function (state marker check onward) stays the same but uses this `version` and `versioned_root`.

Update the state marker path to use `versioned_root`:

```rust
    let marker_path = versioned_root.join(format!(".mb_extraction_status_{}.json", version));
```

- [ ] **Step 2: Verify it compiles**

Run: `cd /Users/Robert/Code/public/discogsography/extractor && cargo check`
Expected: Compiles successfully.

- [ ] **Step 3: Run existing extractor tests**

Run: `cd /Users/Robert/Code/public/discogsography/extractor && cargo test --features test-support extractor_tests -- --nocapture`
Expected: PASS (existing tests may need minor adjustment if they mock `process_musicbrainz_data`).

- [ ] **Step 4: Commit**

```bash
git add extractor/src/extractor.rs
git commit -m "feat: integrate MusicBrainz download into extraction pipeline"
```

______________________________________________________________________

### Task 9: Add `run_musicbrainz_loop` with periodic checking

**Files:**

- Modify: `extractor/src/extractor.rs` (add new function after `run_extraction_loop`)

- Modify: `extractor/src/main.rs:130-148` (call the loop instead of one-shot)

- [ ] **Step 1: Add run_musicbrainz_loop to extractor.rs**

Add after the `run_extraction_loop` function (around line 764), before `process_musicbrainz_data`:

```rust
/// Main MusicBrainz extraction loop with periodic checks for new dumps.
pub async fn run_musicbrainz_loop(
    config: Arc<ExtractorConfig>,
    state: Arc<RwLock<ExtractorState>>,
    shutdown: Arc<tokio::sync::Notify>,
    force_reprocess: bool,
    mq_factory: Arc<dyn MessageQueueFactory>,
    trigger: Arc<std::sync::Mutex<Option<bool>>>,
    compiled_rules: Option<Arc<CompiledRulesConfig>>,
) -> Result<()> {
    info!("🎵 Starting MusicBrainz extraction...");

    // Initial download + process
    let success = process_musicbrainz_data(
        config.clone(),
        state.clone(),
        shutdown.clone(),
        force_reprocess,
        mq_factory.clone(),
        compiled_rules.clone(),
    )
    .await?;

    if !success {
        error!("❌ Initial MusicBrainz processing failed");
        return Err(anyhow::anyhow!("Initial MusicBrainz processing failed"));
    }

    info!("✅ Initial MusicBrainz processing completed successfully");

    // Periodic check loop
    loop {
        let check_interval = Duration::from_secs(config.periodic_check_days * 24 * 60 * 60);
        info!("⏰ Waiting {} days before next MusicBrainz check...", config.periodic_check_days);

        tokio::select! {
            _ = sleep(check_interval) => {
                info!("🔄 Starting periodic check for new MusicBrainz dumps...");
                let start = Instant::now();
                match process_musicbrainz_data(config.clone(), state.clone(), shutdown.clone(), false, mq_factory.clone(), compiled_rules.clone()).await {
                    Ok(true) => {
                        info!("✅ Periodic MusicBrainz check completed successfully in {:?}", start.elapsed());
                    }
                    Ok(false) => {
                        error!("❌ Periodic MusicBrainz check completed with errors");
                    }
                    Err(e) => {
                        error!("❌ Periodic MusicBrainz check failed: {}", e);
                    }
                }
            }
            trigger_force_reprocess = wait_for_trigger(&trigger) => {
                info!("🔄 MusicBrainz extraction triggered via API (force_reprocess={})...", trigger_force_reprocess);
                let start = Instant::now();
                match process_musicbrainz_data(config.clone(), state.clone(), shutdown.clone(), trigger_force_reprocess, mq_factory.clone(), compiled_rules.clone()).await {
                    Ok(true) => info!("✅ Triggered MusicBrainz extraction completed in {:?}", start.elapsed()),
                    Ok(false) => error!("❌ Triggered MusicBrainz extraction completed with errors"),
                    Err(e) => error!("❌ Triggered MusicBrainz extraction failed: {}", e),
                }
            }
            _ = shutdown.notified() => {
                info!("🛑 Shutdown requested, stopping MusicBrainz periodic checks");
                break;
            }
        }
    }

    Ok(())
}
```

- [ ] **Step 2: Update main.rs to call run_musicbrainz_loop**

In `extractor/src/main.rs`, replace the `Source::MusicBrainz` match arm (lines 143-148):

```rust
        Source::MusicBrainz => {
            extractor::run_musicbrainz_loop(
                config.clone(),
                state.clone(),
                shutdown.clone(),
                args.force_reprocess,
                mq_factory,
                trigger.clone(),
                compiled_rules,
            )
            .await
        }
```

- [ ] **Step 3: Verify it compiles**

Run: `cd /Users/Robert/Code/public/discogsography/extractor && cargo check`
Expected: Compiles successfully.

- [ ] **Step 4: Run all tests**

Run: `cd /Users/Robert/Code/public/discogsography/extractor && cargo test --features test-support -- --nocapture`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add extractor/src/extractor.rs extractor/src/main.rs
git commit -m "feat: add run_musicbrainz_loop with periodic version checking"
```

______________________________________________________________________

### Task 10: Add retry test

**Files:**

- Test: `extractor/src/tests/musicbrainz_downloader_tests.rs`

- [ ] **Step 1: Write retry test**

Add to `extractor/src/tests/musicbrainz_downloader_tests.rs`:

```rust
#[tokio::test]
async fn test_download_latest_retry_on_failure() {
    use std::io::Write;

    let dir = TempDir::new().unwrap();

    let mut server = mockito::Server::new_async().await;
    let base_url = format!("{}/", server.url());

    let index_html = r#"<html><body>
        <a href="20260325-001001/">20260325-001001/</a>
    </body></html>"#;
    let _index_mock = server.mock("GET", "/")
        .with_status(200)
        .with_body(index_html)
        .create_async().await;

    // Build a valid tar.xz for all 3 entities
    let mut tar_bodies: HashMap<String, Vec<u8>> = HashMap::new();
    let mut sha256_lines = String::new();

    for entity in &["artist", "label", "release"] {
        let content = format!("{{\"id\":\"{}\"}}\n", entity);
        let mut tar_data = Vec::new();
        {
            let mut builder = tar::Builder::new(&mut tar_data);
            let bytes = content.as_bytes();
            let mut header = tar::Header::new_gnu();
            header.set_path(format!("{}/mbdump/{}", entity, entity)).unwrap();
            header.set_size(bytes.len() as u64);
            header.set_mode(0o644);
            header.set_cksum();
            builder.append(&header, bytes).unwrap();
            builder.finish().unwrap();
        }
        let mut encoder = xz2::write::XzEncoder::new(Vec::new(), 1);
        encoder.write_all(&tar_data).unwrap();
        let compressed = encoder.finish().unwrap();
        let hash = format!("{:x}", sha2::Sha256::digest(&compressed));
        sha256_lines.push_str(&format!("{} *{}.tar.xz\n", hash, entity));
        tar_bodies.insert(entity.to_string(), compressed);
    }

    let _sha_mock = server.mock("GET", "/20260325-001001/SHA256SUMS")
        .with_status(200)
        .with_body(&sha256_lines)
        .create_async().await;

    // artist: first request fails (500), second succeeds
    let _artist_fail = server.mock("GET", "/20260325-001001/artist.tar.xz")
        .with_status(500)
        .with_body("Internal Server Error")
        .expect(1)
        .create_async().await;
    let _artist_ok = server.mock("GET", "/20260325-001001/artist.tar.xz")
        .with_status(200)
        .with_body(tar_bodies.get("artist").unwrap().clone())
        .expect(1)
        .create_async().await;

    // label and release succeed immediately
    let _label_mock = server.mock("GET", "/20260325-001001/label.tar.xz")
        .with_status(200)
        .with_body(tar_bodies.get("label").unwrap().clone())
        .create_async().await;
    let _release_mock = server.mock("GET", "/20260325-001001/release.tar.xz")
        .with_status(200)
        .with_body(tar_bodies.get("release").unwrap().clone())
        .create_async().await;

    let downloader = MbDownloader::new(dir.path().to_path_buf(), base_url);
    let result = downloader.download_latest().await.unwrap();

    assert!(matches!(result, MbDownloadResult::Downloaded(_)));
    assert!(dir.path().join("20260325-001001/artist.jsonl").exists());
}
```

- [ ] **Step 2: Run the retry test**

Run: `cd /Users/Robert/Code/public/discogsography/extractor && cargo test --features test-support test_download_latest_retry_on_failure -- --nocapture`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add extractor/src/tests/musicbrainz_downloader_tests.rs
git commit -m "test: add retry test for MusicBrainz download"
```

______________________________________________________________________

### Task 11: Run full test suite, lint, and format

**Files:** None — verification only.

- [ ] **Step 1: Format code**

Run: `cd /Users/Robert/Code/public/discogsography && just extractor-fmt`
Expected: Code formatted.

- [ ] **Step 2: Run clippy**

Run: `cd /Users/Robert/Code/public/discogsography && just extractor-lint`
Expected: No warnings (warnings are errors in this project).

- [ ] **Step 3: Run all Rust tests**

Run: `cd /Users/Robert/Code/public/discogsography && just test-extractor`
Expected: All tests PASS.

- [ ] **Step 4: Run full Python test suite**

Run: `cd /Users/Robert/Code/public/discogsography && just test`
Expected: All tests PASS (no Python changes, but verify nothing is broken).

- [ ] **Step 5: Fix any issues found**

Address lint warnings, test failures, or formatting issues.

- [ ] **Step 6: Commit any fixes**

```bash
git add -A
git commit -m "fix: address lint and formatting issues from MusicBrainz download feature"
```

______________________________________________________________________

### Task 12: Update docker-compose.yml (optional env var)

**Files:**

- Modify: `docker-compose.yml:335-337`

- [ ] **Step 1: Add MUSICBRAINZ_DUMP_URL to extractor-musicbrainz service**

In `docker-compose.yml`, add to the `extractor-musicbrainz` environment section, after `MUSICBRAINZ_ROOT`:

```yaml
      MUSICBRAINZ_DUMP_URL: "https://data.metabrainz.org/pub/musicbrainz/data/json-dumps/"
```

This is optional (the default is the same value) but makes the configuration explicit and discoverable.

- [ ] **Step 2: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: add MUSICBRAINZ_DUMP_URL to docker-compose config"
```
