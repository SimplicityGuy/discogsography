use anyhow::{Context, Result};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::LazyLock;
use tokio::fs;
use tracing::{debug, error, info, warn};

use crate::polite_http::{PoliteClient, PoliteConfig};
use crate::types::DataType;

/// Known file name patterns for MusicBrainz JSONL dump files.
/// Each entry maps a DataType to a list of candidate file-name patterns.
const MB_FILE_PATTERNS: &[(DataType, &[&str])] = &[
    (DataType::Artists, &["artist.jsonl.xz", "mbdump-artist.jsonl.xz", "artist.jsonl"]),
    (DataType::Labels, &["label.jsonl.xz", "mbdump-label.jsonl.xz", "label.jsonl"]),
    (DataType::ReleaseGroups, &["release-group.jsonl.xz", "mbdump-release-group.jsonl.xz", "release-group.jsonl"]),
    (DataType::Releases, &["release.jsonl.xz", "mbdump-release.jsonl.xz", "release.jsonl"]),
];

/// Entity name used for fuzzy matching when none of the exact patterns hit.
fn entity_keyword(dt: DataType) -> &'static str {
    match dt {
        DataType::Artists => "artist",
        DataType::Labels => "label",
        DataType::ReleaseGroups => "release-group",
        DataType::Releases => "release",
        DataType::Masters => "master",
    }
}

/// Discover available MusicBrainz JSONL dump files in the given directory.
/// Returns a map of DataType -> file path for each found dump file.
pub fn discover_mb_dump_files(root: &Path) -> Result<HashMap<DataType, PathBuf>> {
    let mut found: HashMap<DataType, PathBuf> = HashMap::new();

    // `root` comes from operator-controlled config (CLI/env var), not HTTP input.
    let entries: Vec<_> = match std::fs::read_dir(root) {
        // nosemgrep: rust.actix.path-traversal.tainted-path.tainted-path
        Ok(rd) => rd.filter_map(|e| e.ok()).filter(|e| e.file_type().map(|ft| ft.is_file()).unwrap_or(false)).collect(),
        Err(e) => {
            warn!("⚠️ Cannot read MusicBrainz dump directory {:?}: {}", root, e);
            return Ok(found);
        }
    };

    for (data_type, patterns) in MB_FILE_PATTERNS {
        // Try exact pattern matches first
        for pattern in *patterns {
            let candidate = root.join(pattern); // nosemgrep: rust.actix.path-traversal.tainted-path.tainted-path
            if candidate.exists() {
                info!("📋 Found MusicBrainz {} dump: {:?}", data_type, candidate);
                found.insert(*data_type, candidate);
                break;
            }
        }

        // If no exact match, try fuzzy: any file containing the entity name and ending in .jsonl.xz
        if !found.contains_key(data_type) {
            let keyword = entity_keyword(*data_type);
            for entry in &entries {
                let name = entry.file_name();
                let name_str = name.to_string_lossy();
                if name_str.contains(keyword)
                    && !(data_type == &DataType::Releases && name_str.contains("release-group"))
                    && (name_str.ends_with(".jsonl.xz") || name_str.ends_with(".jsonl"))
                {
                    let path = entry.path();
                    info!("📋 Found MusicBrainz {} dump (fuzzy match): {:?}", data_type, path);
                    found.insert(*data_type, path);
                    break;
                }
            }
        }
    }

    if found.is_empty() {
        warn!("⚠️ No MusicBrainz dump files found in {:?}", root);
    } else {
        info!("📋 Discovered {} MusicBrainz dump file(s) in {:?}", found.len(), root);
        for (dt, path) in &found {
            debug!("📋   {} -> {:?}", dt, path);
        }
    }

    Ok(found)
}

/// Detect the version (date) of the dump from directory name or current date.
///
/// Tries to extract a YYYYMMDD date from the last component of the directory
/// path (e.g., `/data/20260322/` -> `"20260322"`).  Falls back to the current
/// date formatted as `YYYYMMDD`.
#[allow(dead_code)]
pub fn detect_mb_dump_version(root: &Path) -> String {
    if let Some(dir_name) = root.file_name().and_then(|n| n.to_str()) {
        // Check if the directory name looks like a YYYYMMDD date
        if dir_name.len() == 8 && dir_name.chars().all(|c| c.is_ascii_digit()) {
            info!("📋 Detected MusicBrainz dump version from directory name: {}", dir_name);
            return dir_name.to_string();
        }

        // Also try extracting a date from a longer name (e.g., "mbdump-20260322")
        for segment in dir_name.split(&['-', '_', '.'][..]) {
            if segment.len() == 8 && segment.chars().all(|c| c.is_ascii_digit()) {
                info!("📋 Detected MusicBrainz dump version from directory name segment: {}", segment);
                return segment.to_string();
            }
        }
    }

    let fallback = chrono::Utc::now().format("%Y%m%d").to_string();
    info!("📋 Using current date as MusicBrainz dump version: {}", fallback);
    fallback
}

/// Scan `root` for subdirectories matching the MusicBrainz version pattern
/// (YYYYMMDD-HHMMSS) and return the path to the most recent one.
#[allow(dead_code)]
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
    // `root` comes from operator-controlled config (CLI/env var), not HTTP input.
    versions.first().map(|v| root.join(v)) // nosemgrep: rust.actix.path-traversal.tainted-path.tainted-path
}

/// MusicBrainz entity names for download (singular, matching tarball names)
#[allow(dead_code)]
const MB_ENTITIES: &[&str] = &["artist", "label", "release-group", "release"];

#[allow(dead_code)]
const MB_MAX_DOWNLOAD_RETRIES: u32 = 3;

// Post-connect transport-error retry — see the equivalent comment in
// `discogs_downloader.rs`. Rate-limit handling lives in `polite_http`.
#[cfg(not(test))]
#[allow(dead_code)]
const MB_RETRY_BASE_DELAY_MS: u64 = 2_000;
#[cfg(test)]
#[allow(dead_code)]
const MB_RETRY_BASE_DELAY_MS: u64 = 10;

/// Result of a MusicBrainz download attempt
#[allow(dead_code)]
#[derive(Debug)]
pub enum MbDownloadResult {
    AlreadyCurrent(String),
    Downloaded(String),
}

#[allow(dead_code)]
impl MbDownloadResult {
    pub fn version(&self) -> &str {
        match self {
            MbDownloadResult::AlreadyCurrent(v) | MbDownloadResult::Downloaded(v) => v,
        }
    }
}

#[allow(dead_code)]
pub struct MbDownloader {
    output_directory: PathBuf,
    base_url: String,
    client: PoliteClient,
}

#[allow(dead_code)]
impl MbDownloader {
    pub fn new(output_directory: PathBuf, base_url: String) -> Self {
        let mut cfg = PoliteConfig::musicbrainz();
        if cfg!(test) {
            cfg.min_gap = std::time::Duration::from_millis(10);
        }
        // Constructing PoliteClient with the default user-agent should not fail under
        // normal conditions; if it does (e.g., reqwest TLS init failure on a misconfigured
        // host), we'd rather surface the error on first use than panic at startup, but
        // the existing API is non-fallible here, so we fall back to a best-effort default.
        let client = PoliteClient::new(cfg).expect("polite HTTP client init failed — TLS or system config broken");
        Self { output_directory, base_url, client }
    }

    /// Discover the latest MusicBrainz dump version and download it if not already present.
    pub async fn download_latest(&self) -> Result<MbDownloadResult> {
        // Step 1: Scrape index page for version directories
        info!("🌐 Fetching MusicBrainz dump index from {}...", self.base_url);
        let response = self.client.get(&self.base_url).await.context("Failed to fetch MusicBrainz dump index")?;
        if !response.status().is_success() {
            return Err(anyhow::anyhow!("MusicBrainz index returned HTTP {} for {}", response.status(), self.base_url));
        }
        let html = response.text().await.context("Failed to read index HTML")?;

        let versions = parse_version_directories(&html);
        if versions.is_empty() {
            return Err(anyhow::anyhow!("No version directories found at {}", self.base_url));
        }

        let version = &versions[0];
        info!("📋 Latest MusicBrainz dump version: {}", version);

        // Step 2: Check if already downloaded
        let version_dir = self.output_directory.join(version); // nosemgrep: rust.actix.path-traversal.tainted-path.tainted-path
        if self.is_version_complete(&version_dir) {
            info!("✅ MusicBrainz dump {} already downloaded", version);
            return Ok(MbDownloadResult::AlreadyCurrent(version.clone()));
        }

        // Step 3: Download SHA256SUMS
        let sha_url = format!("{}{}/SHA256SUMS", self.base_url, version);
        info!("⬇️ Fetching SHA256SUMS from {}...", sha_url);
        let sha_response = self.client.get(&sha_url).await.context("Failed to fetch SHA256SUMS")?;
        if !sha_response.status().is_success() {
            return Err(anyhow::anyhow!("MusicBrainz SHA256SUMS returned HTTP {} for {}", sha_response.status(), sha_url));
        }
        let sha_content = sha_response.text().await.context("Failed to read SHA256SUMS")?;
        let checksums = parse_sha256sums(&sha_content);

        // Step 4: Create version directory
        fs::create_dir_all(&version_dir).await.with_context(|| format!("Failed to create directory: {:?}", version_dir))?;

        // Step 5: Download, verify, and extract each entity — streamed end-to-end.
        // The .tar.xz bytes flow directly from the network through the xz decoder,
        // tar extractor, and xz encoder, landing on disk only as {entity}.jsonl.xz.
        // SHA256 is computed on the raw compressed bytes as they flow past.
        for entity in MB_ENTITIES {
            let tarball_name = format!("{}.tar.xz", entity);
            let expected_hash = checksums
                .get(&tarball_name)
                .ok_or_else(|| anyhow::anyhow!("No SHA256 checksum found for {} in SHA256SUMS", tarball_name))?;

            let download_url = format!("{}{}/{}", self.base_url, version, tarball_name);
            let out_path = version_dir.join(format!("{}.jsonl.xz", entity)); // nosemgrep: rust.actix.path-traversal.tainted-path.tainted-path

            self.stream_download_verify_extract(&download_url, entity, expected_hash, &out_path).await?;

            info!("✅ Successfully streamed MusicBrainz {} dump to jsonl.xz", entity);
        }

        info!("✅ MusicBrainz dump {} download complete", version);
        Ok(MbDownloadResult::Downloaded(version.clone()))
    }

    /// Check whether a version directory contains all expected entity JSONL files.
    /// Recognizes both uncompressed `.jsonl` and compressed `.jsonl.xz` variants.
    pub(crate) fn is_version_complete(&self, version_dir: &Path) -> bool {
        if !version_dir.is_dir() {
            return false;
        }
        MB_ENTITIES
            .iter()
            .all(|entity| version_dir.join(format!("{}.jsonl", entity)).exists() || version_dir.join(format!("{}.jsonl.xz", entity)).exists())
    }

    /// Stream a `.tar.xz` from `url` straight through xz decompression, tar extraction, and
    /// xz re-compression into `{entity}.jsonl.xz` without ever writing the source tarball to disk.
    ///
    /// The raw compressed bytes flow through a [`HashingReader`] so SHA256 is verified against
    /// the published checksum. Because the tar iterator may stop reading after the target entry,
    /// the caller drains the remainder of the stream post-extraction to ensure every byte is
    /// hashed. On any failure (network, checksum, extraction) the partial output file is removed
    /// and the attempt is retried up to [`MB_MAX_DOWNLOAD_RETRIES`] times with exponential backoff.
    async fn stream_download_verify_extract(&self, url: &str, entity: &str, expected_sha256: &str, out_path: &Path) -> Result<()> {
        use futures::TryStreamExt;
        use tokio_util::io::{StreamReader, SyncIoBridge};

        let mut last_error: Option<anyhow::Error> = None;

        for attempt in 1..=MB_MAX_DOWNLOAD_RETRIES {
            if attempt > 1 {
                if out_path.exists() {
                    let _ = fs::remove_file(out_path).await;
                }
                let delay_ms = MB_RETRY_BASE_DELAY_MS * (1u64 << (attempt - 2));
                warn!("🔄 Retry {}/{} for {} (waiting {}ms)...", attempt - 1, MB_MAX_DOWNLOAD_RETRIES - 1, entity, delay_ms);
                tokio::time::sleep(tokio::time::Duration::from_millis(delay_ms)).await;
            }

            info!("⬇️ Streaming {} (attempt {}/{})...", entity, attempt, MB_MAX_DOWNLOAD_RETRIES);

            let response = match self.client.get(url).await {
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

            // Bridge the async reqwest byte stream to a blocking Read and tee SHA256 on the way past.
            let byte_stream = response.bytes_stream().map_err(std::io::Error::other);
            let async_read = StreamReader::new(byte_stream);
            let sync_read = SyncIoBridge::new(async_read);
            let hashing_reader = HashingReader::new(sync_read);

            let entity_owned = entity.to_string();
            let expected_hash_owned = expected_sha256.to_string();
            let out_path_owned = out_path.to_path_buf();
            let attempt_start = std::time::Instant::now();

            let extract_result = tokio::task::spawn_blocking(move || -> Result<(u64, u64)> {
                // Core extraction — reads bytes from the network through xz → tar → xz encoder.
                // Returns the recovered reader so we can drain remaining bytes through the hasher.
                let mut recovered = extract_entity_from_reader(hashing_reader, &entity_owned, &out_path_owned)?;

                // The tar iterator may stop as soon as the target entry is written, leaving some
                // compressed bytes unread. Drain them so SHA256 sees every byte before finalize().
                let mut discard = [0u8; 64 * 1024];
                loop {
                    match recovered.read(&mut discard) {
                        Ok(0) => break,
                        Ok(_) => continue,
                        Err(e) => return Err(anyhow::anyhow!("Failed to drain compressed stream: {}", e)),
                    }
                }

                let (actual_hash, total_bytes) = recovered.finalize();
                if actual_hash != expected_hash_owned {
                    let _ = std::fs::remove_file(&out_path_owned);
                    return Err(anyhow::anyhow!("SHA256 mismatch for {}: expected {}, got {}", entity_owned, expected_hash_owned, actual_hash));
                }
                let compressed_out = std::fs::metadata(&out_path_owned).map(|m| m.len()).unwrap_or(0);
                Ok((total_bytes, compressed_out))
            })
            .await
            .context("Streaming extraction task panicked")?;

            match extract_result {
                Ok((total_bytes, compressed_out)) => {
                    let elapsed = attempt_start.elapsed().as_secs_f64();
                    let speed = if elapsed > 0.0 { (total_bytes as f64 / 1_048_576.0) / elapsed } else { 0.0 };
                    info!(
                        "✅ Streamed {} ({:.1} MB in {:.1} MB .tar.xz → {:.1} MB .jsonl.xz in {:.1}s, {:.1} MB/s, SHA256 verified)",
                        entity,
                        total_bytes as f64 / 1_048_576.0,
                        total_bytes as f64 / 1_048_576.0,
                        compressed_out as f64 / 1_048_576.0,
                        elapsed,
                        speed
                    );
                    return Ok(());
                }
                Err(e) => {
                    warn!("⚠️ Attempt {}/{} failed for {}: {}", attempt, MB_MAX_DOWNLOAD_RETRIES, entity, e);
                    last_error = Some(e);
                    if out_path.exists() {
                        let _ = fs::remove_file(out_path).await;
                    }
                    continue;
                }
            }
        }

        error!("❌ Download failed after {} attempts for {}", MB_MAX_DOWNLOAD_RETRIES, entity);
        Err(last_error.unwrap_or_else(|| anyhow::anyhow!("Download failed after {} attempts", MB_MAX_DOWNLOAD_RETRIES)))
    }
}

/// `Read` adapter that tees every byte through a SHA256 hasher while counting total bytes read.
/// The hash is available via [`HashingReader::finalize`] once all reads are complete.
struct HashingReader<R: Read> {
    inner: R,
    hasher: Sha256,
    bytes: u64,
}

impl<R: Read> HashingReader<R> {
    fn new(inner: R) -> Self {
        Self { inner, hasher: Sha256::new(), bytes: 0 }
    }

    fn finalize(self) -> (String, u64) {
        (hex::encode(self.hasher.finalize()), self.bytes)
    }
}

impl<R: Read> Read for HashingReader<R> {
    fn read(&mut self, buf: &mut [u8]) -> std::io::Result<usize> {
        let n = self.inner.read(buf)?;
        if n > 0 {
            self.hasher.update(&buf[..n]);
            self.bytes += n as u64;
        }
        Ok(n)
    }
}

/// Parse version directory names (YYYYMMDD-HHMMSS) from an HTML index page.
/// Returns them sorted descending (most recent first).
#[allow(dead_code)]
pub fn parse_version_directories(html: &str) -> Vec<String> {
    static VERSION_PATTERN: LazyLock<regex::Regex> =
        LazyLock::new(|| regex::Regex::new(r#"href="(\d{8}-\d{6})/?"#).expect("hardcoded regex is valid"));
    let pattern = &*VERSION_PATTERN;
    let mut versions: Vec<String> = pattern.captures_iter(html).filter_map(|cap| cap.get(1).map(|m| m.as_str().to_string())).collect();
    versions.sort_by(|a, b| b.cmp(a));
    versions.dedup();
    versions
}

/// Parse a SHA256SUMS file into a map of filename -> hex hash.
#[allow(dead_code)]
pub fn parse_sha256sums(content: &str) -> HashMap<String, String> {
    content
        .lines()
        .filter_map(|line| {
            let line = line.trim();
            if line.is_empty() {
                return None;
            }
            let mut parts = line.splitn(2, char::is_whitespace);
            let hash = parts.next()?.trim().to_string();
            let filename = parts.next()?.trim().trim_start_matches('*').to_string();
            Some((filename, hash))
        })
        .collect()
}

/// Extract `mbdump/<entity>` from a `.tar.xz` file on disk into a compressed `.jsonl.xz`
/// output file. Thin wrapper around [`extract_entity_from_reader`] — kept as a stable public
/// entry point so existing disk-based tests and any standalone callers keep working.
#[allow(dead_code)]
pub fn extract_entity_from_tarball(tar_path: &Path, entity: &str, out_path: &Path) -> Result<()> {
    // `tar_path` and `out_path` come from operator-controlled config (CLI/env var), not HTTP input.
    let file = std::fs::File::open(tar_path) // nosemgrep: rust.actix.path-traversal.tainted-path.tainted-path
        .with_context(|| format!("Failed to open tarball: {:?}", tar_path))?;
    extract_entity_from_reader(file, entity, out_path).map(|_| ())
}

/// Core extraction: pull a `.tar.xz` byte stream through an XZ decoder, locate
/// `mbdump/<entity>` inside the tar archive, and re-encode it as `.jsonl.xz` at the given path.
///
/// Generic over any blocking `Read`, so the same code path handles both on-disk tarballs
/// (`File`) and live network streams (via `SyncIoBridge<StreamReader<…>>`). On success,
/// returns the inner reader so callers can drain any unread trailing bytes — necessary
/// when SHA256 is being computed on the way in, because the tar iterator typically stops
/// as soon as the target entry is written.
///
/// On failure, the partial output file is removed so a retry can start from a clean slate.
fn extract_entity_from_reader<R: Read>(reader: R, entity: &str, out_path: &Path) -> Result<R> {
    use xz2::write::XzEncoder;

    let xz = xz2::read::XzDecoder::new(reader);
    let mut archive = tar::Archive::new(xz);
    let target_suffix = format!("mbdump/{}", entity);

    let mut found_total_bytes: Option<u64> = None;

    for entry_result in archive.entries().context("Failed to read tar entries")? {
        let mut entry = entry_result.context("Failed to read tar entry")?;
        let is_target = {
            let path = entry.path().context("Failed to read entry path")?;
            path.ends_with(&target_suffix)
        };

        if !is_target {
            continue;
        }

        let out_file = std::fs::File::create(out_path) // nosemgrep: rust.actix.path-traversal.tainted-path.tainted-path
            .with_context(|| format!("Failed to create output file: {:?}", out_path))?;
        let mut encoder = XzEncoder::new(out_file, 6);

        // Stream with progress logging — xz decompression of large files can take 30+ minutes.
        let mut buf = [0u8; 256 * 1024]; // 256 KB buffer
        let mut total_read: u64 = 0;
        let extract_start = std::time::Instant::now();
        let mut last_progress_log = extract_start;

        let extract_result = (|| -> Result<()> {
            loop {
                let n = entry.read(&mut buf).with_context(|| format!("Failed to read {} from tarball", entity))?;
                if n == 0 {
                    break;
                }
                encoder.write_all(&buf[..n]).with_context(|| format!("Failed to write compressed {} to {:?}", entity, out_path))?;
                total_read += n as u64;

                let now = std::time::Instant::now();
                if now.duration_since(last_progress_log).as_secs() >= 10 {
                    let elapsed = extract_start.elapsed().as_secs_f64();
                    let speed = if elapsed > 0.0 { (total_read as f64 / 1_048_576.0) / elapsed } else { 0.0 };
                    info!("📦 {} — streaming+compressing: {:.1} MB processed ({:.1} MB/s)", entity, total_read as f64 / 1_048_576.0, speed);
                    last_progress_log = now;
                }
            }
            encoder.finish().context("Failed to finalize XZ compression")?;
            Ok(())
        })();

        if let Err(e) = extract_result {
            let _ = std::fs::remove_file(out_path);
            return Err(e);
        }

        let compressed_size = std::fs::metadata(out_path).map(|m| m.len()).unwrap_or(0);
        info!(
            "📋 Extracted+compressed {} ({:.1} MB uncompressed → {:.1} MB XZ)",
            entity,
            total_read as f64 / 1_048_576.0,
            compressed_size as f64 / 1_048_576.0,
        );
        found_total_bytes = Some(total_read);
        break;
    }

    if found_total_bytes.is_none() {
        let _ = std::fs::remove_file(out_path);
        return Err(anyhow::anyhow!("Entry '{}' not found in archive", target_suffix));
    }

    // Recover the underlying reader so the caller can continue consuming it (drain for hashing).
    Ok(archive.into_inner().into_inner())
}

#[cfg(test)]
#[path = "tests/musicbrainz_downloader_tests.rs"]
mod tests;
