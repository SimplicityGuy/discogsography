use anyhow::{Context, Result};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::LazyLock;
use tokio::fs;
use tokio::io::AsyncWriteExt;
use tracing::{debug, error, info, warn};

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
                if name_str.contains(keyword) && !(data_type == &DataType::Releases && name_str.contains("release-group")) && (name_str.ends_with(".jsonl.xz") || name_str.ends_with(".jsonl")) {
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
}

#[allow(dead_code)]
impl MbDownloader {
    pub fn new(output_directory: PathBuf, base_url: String) -> Self {
        Self { output_directory, base_url }
    }

    /// Discover the latest MusicBrainz dump version and download it if not already present.
    pub async fn download_latest(&self) -> Result<MbDownloadResult> {
        // Step 1: Scrape index page for version directories
        info!("🌐 Fetching MusicBrainz dump index from {}...", self.base_url);
        let response = reqwest::get(&self.base_url) // nosemgrep: rust.actix.ssrf.reqwest-taint.reqwest-taint
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
        let version_dir = self.output_directory.join(version); // nosemgrep: rust.actix.path-traversal.tainted-path.tainted-path
        if self.is_version_complete(&version_dir) {
            info!("✅ MusicBrainz dump {} already downloaded", version);
            return Ok(MbDownloadResult::AlreadyCurrent(version.clone()));
        }

        // Step 3: Download SHA256SUMS
        let sha_url = format!("{}{}/SHA256SUMS", self.base_url, version);
        info!("⬇️ Fetching SHA256SUMS from {}...", sha_url);
        let sha_response = reqwest::get(&sha_url) // nosemgrep: rust.actix.ssrf.reqwest-taint.reqwest-taint
            .await
            .context("Failed to fetch SHA256SUMS")?;
        let sha_content = sha_response.text().await.context("Failed to read SHA256SUMS")?;
        let checksums = parse_sha256sums(&sha_content);

        // Step 4: Create version directory
        fs::create_dir_all(&version_dir).await.with_context(|| format!("Failed to create directory: {:?}", version_dir))?;

        // Step 5: Download, verify, and extract each entity
        for entity in MB_ENTITIES {
            let tarball_name = format!("{}.tar.xz", entity);
            let expected_hash = checksums
                .get(&tarball_name)
                .ok_or_else(|| anyhow::anyhow!("No SHA256 checksum found for {} in SHA256SUMS", tarball_name))?;

            let download_url = format!("{}{}/{}", self.base_url, version, tarball_name);
            let tmp_path = version_dir.join(format!("{}.tmp", tarball_name)); // nosemgrep: rust.actix.path-traversal.tainted-path.tainted-path
            let out_path = version_dir.join(format!("{}.jsonl", entity)); // nosemgrep: rust.actix.path-traversal.tainted-path.tainted-path

            // Download with retry
            self.download_file(&download_url, &tmp_path, expected_hash, entity).await?;

            // Extract on blocking thread
            let extract_tmp = tmp_path.clone();
            let extract_entity = entity.to_string();
            let extract_out = out_path.clone();
            tokio::task::spawn_blocking(move || extract_entity_from_tarball(&extract_tmp, &extract_entity, &extract_out))
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
    /// Recognizes both uncompressed `.jsonl` and compressed `.jsonl.xz` variants.
    pub(crate) fn is_version_complete(&self, version_dir: &Path) -> bool {
        if !version_dir.is_dir() {
            return false;
        }
        MB_ENTITIES.iter().all(|entity| {
            version_dir.join(format!("{}.jsonl", entity)).exists() || version_dir.join(format!("{}.jsonl.xz", entity)).exists()
        })
    }

    /// Download a file with retry logic and SHA256 verification.
    async fn download_file(&self, url: &str, dest: &Path, expected_sha256: &str, entity: &str) -> Result<()> {
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
                // nosemgrep: rust.actix.ssrf.reqwest-taint.reqwest-taint
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

            let mut file = fs::File::create(dest) // nosemgrep: rust.actix.path-traversal.tainted-path.tainted-path
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
            let actual_hash = hex::encode(hasher.finalize());
            if actual_hash != expected_sha256 {
                let msg = format!("SHA256 mismatch for {}: expected {}, got {}", entity, expected_sha256, actual_hash);
                warn!("⚠️ {}", msg);
                last_error = Some(anyhow::anyhow!(msg));
                let _ = fs::remove_file(dest).await;
                continue;
            }

            info!("✅ Downloaded {} ({:.2} MB, SHA256 verified)", entity, downloaded as f64 / 1_048_576.0);
            return Ok(());
        }

        error!("❌ Download failed after {} attempts for {}", MB_MAX_DOWNLOAD_RETRIES, entity);
        Err(last_error.unwrap_or_else(|| anyhow::anyhow!("Download failed after {} attempts", MB_MAX_DOWNLOAD_RETRIES)))
    }
}

/// Parse version directory names (YYYYMMDD-HHMMSS) from an HTML index page.
/// Returns them sorted descending (most recent first).
#[allow(dead_code)]
pub fn parse_version_directories(html: &str) -> Vec<String> {
    static VERSION_PATTERN: LazyLock<regex::Regex> = LazyLock::new(|| {
        regex::Regex::new(r#"href="(\d{8}-\d{6})/?"#).expect("hardcoded regex is valid")
    });
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

/// Log compression progress for large files.
pub fn log_compression_progress(filename: &std::ffi::OsStr, total_read: u64, input_size: u64, elapsed_secs: f64) {
    let speed = if elapsed_secs > 0.0 { (total_read as f64 / 1_048_576.0) / elapsed_secs } else { 0.0 };
    let pct = if input_size > 0 { (total_read as f64 / input_size as f64) * 100.0 } else { 0.0 };
    info!(
        "🧹 Compressing {:?} — {:.1}% ({:.1} MB read, {:.1} MB/s)",
        filename,
        pct,
        total_read as f64 / 1_048_576.0,
        speed,
    );
}

/// Compress a `.jsonl` file to `.jsonl.xz` and delete the original.
///
/// Uses XZ compression (level 6) to match the original MusicBrainz dump format.
/// Returns the path of the compressed file on success.
/// Logs progress every 10 seconds for large files.
pub fn compress_jsonl_to_xz(jsonl_path: &Path) -> Result<PathBuf> {
    use xz2::write::XzEncoder;

    let xz_path = jsonl_path.with_extension("jsonl.xz");

    // `jsonl_path` and `xz_path` come from operator-controlled config, not HTTP input.
    let input = std::fs::File::open(jsonl_path) // nosemgrep: rust.actix.path-traversal.tainted-path.tainted-path
        .with_context(|| format!("Failed to open file for compression: {:?}", jsonl_path))?;
    let input_size = input.metadata().map(|m| m.len()).unwrap_or(0);
    let mut reader = std::io::BufReader::new(input);

    let output = std::fs::File::create(&xz_path) // nosemgrep: rust.actix.path-traversal.tainted-path.tainted-path
        .with_context(|| format!("Failed to create compressed file: {:?}", xz_path))?;
    let mut encoder = XzEncoder::new(output, 6);

    let mut buf = [0u8; 256 * 1024]; // 256 KB buffer
    let mut total_read: u64 = 0;
    let compress_start = std::time::Instant::now();
    let mut last_progress_log = compress_start;
    let filename = jsonl_path.file_name().unwrap_or_default().to_owned();

    let compress_result = (|| -> Result<()> {
        loop {
            let n = reader.read(&mut buf).context("Failed to read during compression")?;
            if n == 0 {
                break;
            }
            encoder.write_all(&buf[..n]).context("Failed to write compressed data")?;
            total_read += n as u64;

            let now = std::time::Instant::now();
            if now.duration_since(last_progress_log).as_secs() >= 10 {
                log_compression_progress(&filename, total_read, input_size, compress_start.elapsed().as_secs_f64());
                last_progress_log = now;
            }
        }
        encoder.finish().context("Failed to finalize XZ compression")?;
        Ok(())
    })();

    // Clean up partial .xz file on any failure to prevent poisoning restarts
    if let Err(e) = compress_result {
        let _ = std::fs::remove_file(&xz_path);
        return Err(e);
    }

    let compressed_size = std::fs::metadata(&xz_path).map(|m| m.len()).unwrap_or(0);
    let ratio = if total_read > 0 { (compressed_size as f64 / total_read as f64) * 100.0 } else { 0.0 };

    // Remove the original uncompressed file
    std::fs::remove_file(jsonl_path) // nosemgrep: rust.actix.path-traversal.tainted-path.tainted-path
        .with_context(|| format!("Failed to remove original file: {:?}", jsonl_path))?;

    info!(
        "🧹 Compressed {:?} → {:?} ({:.1} MB → {:.1} MB, {:.1}% of original)",
        jsonl_path.file_name().unwrap_or_default(),
        xz_path.file_name().unwrap_or_default(),
        total_read as f64 / 1_048_576.0,
        compressed_size as f64 / 1_048_576.0,
        ratio,
    );

    Ok(xz_path)
}

/// Extract the `mbdump/<entity>` file from a `.tar.xz` archive.
///
/// Only the target entry is extracted; all other entries are skipped.
/// Returns an error if the target entry is not found.
#[allow(dead_code)]
pub fn extract_entity_from_tarball(tar_path: &Path, entity: &str, out_path: &Path) -> Result<()> {
    // `tar_path` and `out_path` come from operator-controlled config (CLI/env var), not HTTP input.
    let file = std::fs::File::open(tar_path) // nosemgrep: rust.actix.path-traversal.tainted-path.tainted-path
        .with_context(|| format!("Failed to open tarball: {:?}", tar_path))?;
    let xz = xz2::read::XzDecoder::new(file);
    let mut archive = tar::Archive::new(xz);

    let target_suffix = format!("mbdump/{}", entity);

    for entry_result in archive.entries().context("Failed to read tar entries")? {
        let mut entry = entry_result.context("Failed to read tar entry")?;
        let path = entry.path().context("Failed to read entry path")?;

        if path.ends_with(&target_suffix) {
            let mut out_file = std::fs::File::create(out_path) // nosemgrep: rust.actix.path-traversal.tainted-path.tainted-path
                .with_context(|| format!("Failed to create output file: {:?}", out_path))?;

            // Copy with progress logging — xz decompression of large files can take 30+ minutes
            let mut buf = [0u8; 256 * 1024]; // 256 KB buffer
            let mut total_written: u64 = 0;
            let extract_start = std::time::Instant::now();
            let mut last_progress_log = extract_start;

            loop {
                let n = entry.read(&mut buf).with_context(|| format!("Failed to read {} from tarball", entity))?;
                if n == 0 {
                    break;
                }
                out_file.write_all(&buf[..n]).with_context(|| format!("Failed to write {} to {:?}", entity, out_path))?;
                total_written += n as u64;

                let now = std::time::Instant::now();
                if now.duration_since(last_progress_log).as_secs() >= 10 {
                    let elapsed = extract_start.elapsed().as_secs_f64();
                    let speed = if elapsed > 0.0 { (total_written as f64 / 1_048_576.0) / elapsed } else { 0.0 };
                    info!(
                        "📦 {} — extracting: {:.1} MB written ({:.1} MB/s)",
                        entity,
                        total_written as f64 / 1_048_576.0,
                        speed,
                    );
                    last_progress_log = now;
                }
            }

            out_file.flush().context("Failed to flush extracted file")?;
            out_file.sync_data().context("Failed to sync extracted file")?;
            info!("📋 Extracted {} from {} ({} bytes)", entity, tar_path.display(), total_written);
            return Ok(());
        }
    }

    Err(anyhow::anyhow!("Entry '{}' not found in {:?}", target_suffix, tar_path))
}

#[cfg(test)]
#[path = "tests/musicbrainz_downloader_tests.rs"]
mod tests;
