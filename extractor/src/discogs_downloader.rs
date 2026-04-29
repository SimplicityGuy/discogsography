use anyhow::{Context, Result};
use chrono::Utc;
use indicatif::{ProgressBar, ProgressStyle};
use regex::Regex;
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use tokio::fs::{self, File};
use tokio::io::AsyncWriteExt;
use tracing::{debug, error, info, warn};

use async_trait::async_trait;

use crate::polite_http::{PoliteClient, PoliteConfig};
use crate::state_marker::StateMarker;
use crate::types::{LocalFileInfo, S3FileInfo};

// S3 file names already contain the full key (e.g., "data/2026/discogs_...xml.gz")
// so no prefix stripping or re-prepending is needed.
const DISCOGS_DATA_URL: &str = "https://data.discogs.com/";
// Discogs has been observed returning Retry-After ~36 minutes; with 5 attempts
// we give ourselves enough headroom to ride out a single bad cooldown without
// the docker restart loop sliding the limiter window forward.
const MAX_DOWNLOAD_RETRIES: u32 = 5;

#[cfg(not(test))]
const RETRY_BASE_DELAY_MS: u64 = 30_000;
#[cfg(test)]
const RETRY_BASE_DELAY_MS: u64 = 10;

pub struct Downloader {
    pub output_directory: PathBuf,
    pub metadata: HashMap<String, LocalFileInfo>,
    base_url: String,
    pub state_marker: Option<StateMarker>,
    pub marker_path: Option<PathBuf>,
    cached_files: Option<Vec<S3FileInfo>>,
    client: PoliteClient,
}

#[cfg_attr(feature = "test-support", mockall::automock)]
#[async_trait]
pub trait DataSource: Send + Sync {
    async fn list_s3_files(&mut self) -> Result<Vec<S3FileInfo>>;
    fn get_latest_monthly_files(&self, files: &[S3FileInfo]) -> Result<Vec<S3FileInfo>>;
    async fn download_discogs_data(&mut self) -> Result<Vec<String>>;
    fn set_state_marker(&mut self, state_marker: StateMarker, marker_path: PathBuf);
    fn take_state_marker(&mut self) -> Option<StateMarker>;
}

impl Downloader {
    pub async fn new(output_directory: PathBuf) -> Result<Self> {
        Self::new_with_base_url(output_directory, DISCOGS_DATA_URL.to_string()).await
    }

    /// Create a new downloader with a custom base URL (primarily for testing)
    #[doc(hidden)]
    pub async fn new_with_base_url(output_directory: PathBuf, base_url: String) -> Result<Self> {
        let metadata = load_metadata(&output_directory)?;
        let client = PoliteClient::new(Self::polite_config())?;

        Ok(Self { output_directory, metadata, base_url, state_marker: None, marker_path: None, cached_files: None, client })
    }

    /// Polite-client tuning for `data.discogs.com`. Tests override `min_gap`
    /// to keep them fast; production uses the upstream-friendly defaults.
    fn polite_config() -> PoliteConfig {
        let mut cfg = PoliteConfig::discogs();
        if cfg!(test) {
            cfg.min_gap = std::time::Duration::from_millis(10);
        }
        cfg
    }

    /// Set the state marker for tracking download progress (builder pattern, used by integration tests)
    #[allow(dead_code)]
    pub fn with_state_marker(mut self, state_marker: StateMarker, marker_path: PathBuf) -> Self {
        self.state_marker = Some(state_marker);
        self.marker_path = Some(marker_path);
        self
    }

    /// Save state marker to disk if present
    async fn save_state_marker(&mut self) {
        if let (Some(marker), Some(path)) = (&mut self.state_marker, &self.marker_path)
            && let Err(e) = marker.save(path).await
        {
            warn!("⚠️ Failed to save state marker: {}", e);
        }
    }

    pub async fn download_discogs_data(&mut self) -> Result<Vec<String>> {
        info!("📥 Starting download of Discogs data dumps...");

        // Create output directory if it doesn't exist
        fs::create_dir_all(&self.output_directory).await.context("Failed to create output directory")?;

        // List available files from S3
        let available_files = self.list_s3_files().await?;

        // Get latest monthly dump
        let latest_files = self.get_latest_monthly_files(&available_files)?;

        if latest_files.is_empty() {
            warn!("⚠️ No monthly data files found");
            return Ok(Vec::new());
        }

        let month = extract_month_from_filename(&latest_files[0].name);
        info!("📅 Latest available month: {}", month);

        // Start download phase tracking if state marker is available
        if let Some(ref mut marker) = self.state_marker {
            marker.start_download(latest_files.len());
        }
        self.save_state_marker().await;

        let mut downloaded_files = Vec::new();

        for file_info in &latest_files {
            let filename = std::path::Path::new(&file_info.name).file_name().and_then(|name| name.to_str()).unwrap_or("unknown_file");

            if self.should_download(file_info).await? {
                // Start tracking file download
                if let Some(ref mut marker) = self.state_marker {
                    marker.start_file_download(filename);
                }
                self.save_state_marker().await;

                match self.download_file(file_info).await {
                    Ok(downloaded_size) => {
                        info!("✅ Successfully downloaded: {}", filename);

                        // Track file download in state marker with actual downloaded size
                        if let Some(ref mut marker) = self.state_marker {
                            marker.file_downloaded(filename, downloaded_size);
                        }
                        self.save_state_marker().await;

                        downloaded_files.push(filename.to_string());
                    }
                    Err(e) => {
                        error!("❌ Failed to download {}: {}", filename, e);
                        return Err(e).context(format!("Failed to download {}", filename));
                    }
                }
            } else {
                info!("✅ Already have latest version of: {}", filename);

                // Track existing file in state marker with actual file size
                if let Some(ref mut marker) = self.state_marker {
                    let local_path = self.output_directory.join(filename);
                    let file_size = tokio::fs::metadata(&local_path).await.map(|m| m.len()).unwrap_or(0);
                    marker.file_downloaded(filename, file_size);
                }
                self.save_state_marker().await;

                downloaded_files.push(filename.to_string());
            }
        }

        // Complete download phase tracking if state marker is available
        if let Some(ref mut marker) = self.state_marker {
            marker.complete_download();
        }
        self.save_state_marker().await;

        // Save updated metadata
        self.save_metadata()?;

        Ok(downloaded_files)
    }

    async fn scrape_file_list_from_discogs(&self) -> Result<HashMap<String, Vec<S3FileInfo>>> {
        info!("🌐 Fetching file list from Discogs website...");

        // Step 1: Fetch the main page to get available years
        let response = self.client.get(&self.base_url).await.context("Failed to fetch Discogs website")?;
        if !response.status().is_success() {
            return Err(anyhow::anyhow!("Discogs website returned HTTP {} for {}", response.status(), self.base_url));
        }
        let html = response.text().await.context("Failed to read HTML response")?;

        // Extract year directories (e.g., 2026/, 2025/, etc.)
        let year_pattern = Regex::new(r#"href="\?prefix=data%2F(\d{4})%2F""#).context("Failed to compile year regex")?;

        let mut years: Vec<String> = year_pattern.captures_iter(&html).filter_map(|cap| cap.get(1).map(|m| m.as_str().to_string())).collect();

        if years.is_empty() {
            return Err(anyhow::anyhow!("No year directories found on Discogs website"));
        }

        // Sort years in descending order (most recent first)
        years.sort_by(|a, b| b.cmp(a));
        info!("📅 Found {} year directories, checking recent years...", years.len());

        // Step 2: Fetch files from recent years (check last 2 years)
        let mut ids: HashMap<String, Vec<S3FileInfo>> = HashMap::new();

        // Compile regex once outside the loop
        // Pattern matches: ?download=data%2F2026%2Fdiscogs_20260101_artists.xml.gz
        let file_pattern = Regex::new(r#"\?download=data%2F\d{4}%2F(discogs_(\d{8})_[^"]+)"#).context("Failed to compile file regex")?;

        for year in years.iter().take(2) {
            let year_url = format!("{}?prefix=data%2F{}%2F", self.base_url, year);

            match self.client.get(&year_url).await {
                Ok(year_response) if year_response.status().is_success() => {
                    if let Ok(year_html) = year_response.text().await {
                        let mut file_count = 0;
                        for cap in file_pattern.captures_iter(&year_html) {
                            if let (Some(filename_match), Some(version_match)) = (cap.get(1), cap.get(2)) {
                                let filename = filename_match.as_str();
                                let version_id = version_match.as_str();

                                // URL decode the filename
                                let decoded_filename = urlencoding::decode(filename).context("Failed to URL decode filename")?.to_string();

                                // Construct full S3 key
                                let s3_key = format!("data/{}/{}", year, decoded_filename);

                                ids.entry(version_id.to_string()).or_default().push(S3FileInfo { name: s3_key, size: 0 });

                                file_count += 1;
                            }
                        }

                        if file_count > 0 {
                            info!("📋 Found {} files in year {} directory", file_count, year);
                        }
                    }
                }
                Ok(year_response) => {
                    warn!("⚠️ Discogs returned HTTP {} for year {} directory", year_response.status(), year);
                    continue;
                }
                Err(e) => {
                    warn!("⚠️ Failed to fetch year {} directory: {}", year, e);
                    continue;
                }
            }
        }

        if ids.is_empty() {
            return Err(anyhow::anyhow!("No files found on Discogs website"));
        }

        info!("📊 Found {} unique versions from website", ids.len());

        Ok(ids)
    }

    pub async fn list_s3_files(&mut self) -> Result<Vec<S3FileInfo>> {
        if let Some(ref cached) = self.cached_files {
            debug!("📋 Using cached file list ({} files)", cached.len());
            return Ok(cached.clone());
        }

        info!("🔍 Listing available files from Discogs website...");

        // Scrape file list from Discogs website instead of S3 listing
        // This avoids the AccessDenied error from S3's ListBucket restriction
        let ids_map = self.scrape_file_list_from_discogs().await?;

        // Flatten the map into a single list of files for compatibility
        let files: Vec<S3FileInfo> = ids_map.into_values().flat_map(|files| files.into_iter()).collect();

        info!("Found {} relevant files from website", files.len());
        self.cached_files = Some(files.clone());
        Ok(files)
    }

    pub fn get_latest_monthly_files(&self, files: &[S3FileInfo]) -> Result<Vec<S3FileInfo>> {
        // Group files by their ID (date part like "20250801") - matching Python logic
        let mut ids: std::collections::HashMap<String, Vec<S3FileInfo>> = std::collections::HashMap::new();

        for file in files {
            // Extract basename before splitting — the full S3 key may contain path separators
            let basename = std::path::Path::new(&file.name).file_name().and_then(|f| f.to_str()).unwrap_or(&file.name);
            let parts: Vec<&str> = basename.split('_').collect();
            if parts.len() >= 2 {
                let id = parts[1].to_string();
                ids.entry(id).or_default().push(file.clone());
            }
        }

        info!("Found {} unique version IDs", ids.len());

        // Get the most recent version (sorted in reverse order)
        let mut sorted_ids: Vec<_> = ids.keys().collect();
        sorted_ids.sort_by(|a, b| b.cmp(a));

        for id in sorted_ids {
            let files_for_id = ids.get(id).unwrap();
            // Check if we have a complete set - exactly like Python logic
            // Python requires exactly 5 files total (1 CHECKSUM + 4 data files)
            if files_for_id.len() != 5 {
                warn!("⚠️ Skipping version {} — expected 5 files, found {}", id, files_for_id.len());
                continue;
            }

            // Only return data files (not CHECKSUM) for processing, with filename only
            let data_files: Vec<_> = files_for_id
                .iter()
                .filter(|f| f.name.ends_with(".xml.gz"))
                .map(|f| S3FileInfo { name: f.name.clone(), size: f.size })
                .collect();

            debug!("Version {} has {} data files", id, data_files.len());

            if data_files.len() == 4 {
                // We expect exactly 4 data files
                info!("📅 Using version {} with {} data files", id, data_files.len());
                return Ok(data_files);
            }
        }

        warn!("No complete version found with all expected data files");
        Ok(Vec::new())
    }

    pub async fn should_download(&self, file_info: &S3FileInfo) -> Result<bool> {
        // Extract just the base filename for local checks
        let filename = std::path::Path::new(&file_info.name).file_name().and_then(|name| name.to_str()).unwrap_or("unknown_file");
        let local_path = self.output_directory.join(filename);

        // Check if file exists locally
        if !local_path.exists() {
            return Ok(true);
        }

        // Check metadata
        if let Some(local_info) = self.metadata.get(filename) {
            // Note: file_info.size is 0 from scraping, so we can't compare sizes
            // File exists (checked above), validate checksum
            let checksum = calculate_file_checksum(&local_path).await?;
            if checksum != local_info.checksum {
                warn!("⚠️ Checksum mismatch for {}", file_info.name);
                return Ok(true);
            }

            // File exists with correct checksum
            return Ok(false);
        }

        // No metadata, download to be safe
        Ok(true)
    }

    /// Download a single file (exposed for testing)
    /// Returns the number of bytes downloaded
    #[doc(hidden)]
    pub async fn download_file(&mut self, file_info: &S3FileInfo) -> Result<u64> {
        use futures::StreamExt;

        // Use the full S3 key directly (name already contains the full path)
        let s3_key = &file_info.name;
        // Extract just the base filename for local storage (remove path components)
        let filename = std::path::Path::new(&file_info.name).file_name().and_then(|name| name.to_str()).unwrap_or("unknown_file");
        let local_path = self.output_directory.join(filename);

        info!("⬇️ Downloading {}...", filename);

        // Construct Discogs download URL (URL encode the S3 key)
        let download_url = format!("{}?download={}", self.base_url, urlencoding::encode(s3_key));

        let mut last_error: Option<anyhow::Error> = None;

        for attempt in 1..=MAX_DOWNLOAD_RETRIES {
            if attempt > 1 {
                // Remove any partial file left by the previous attempt
                if local_path.exists()
                    && let Err(e) = fs::remove_file(&local_path).await
                {
                    warn!("⚠️ Failed to remove partial file before retry: {}", e);
                }
                let delay_ms = RETRY_BASE_DELAY_MS * (1u64 << (attempt - 2));
                warn!("🔄 Retry {}/{} for {} (waiting {}ms)...", attempt - 1, MAX_DOWNLOAD_RETRIES - 1, filename, delay_ms);
                tokio::time::sleep(tokio::time::Duration::from_millis(delay_ms)).await;
            }

            // Create progress bar (unknown size from scraping)
            let pb = ProgressBar::new_spinner();
            pb.set_style(ProgressStyle::default_spinner().template("{spinner:.green} [{elapsed_precise}] {bytes} ({bytes_per_sec})").unwrap());

            // Download via the polite client — gates the request on min_gap and
            // server-driven Retry-After so a 429 doesn't burn a retry slot here.
            let response = match self.client.get(&download_url).await {
                Ok(r) => r,
                Err(e) => {
                    let msg = format!("Failed to start HTTP download from {}: {}", download_url, e);
                    warn!("⚠️ Attempt {}/{}: {}", attempt, MAX_DOWNLOAD_RETRIES, msg);
                    last_error = Some(anyhow::anyhow!(msg));
                    continue;
                }
            };

            if !response.status().is_success() {
                let msg = format!("HTTP error: {}", response.status());
                warn!("⚠️ Attempt {}/{}: {}", attempt, MAX_DOWNLOAD_RETRIES, msg);
                last_error = Some(anyhow::anyhow!(msg));
                continue;
            }

            let mut file = File::create(&local_path).await.context("Failed to create local file")?;
            let mut hasher = Sha256::new();
            let mut downloaded: u64 = 0;
            let download_start = std::time::Instant::now();
            let mut last_progress_log = download_start;

            // Stream the response body
            let mut stream = response.bytes_stream();
            let mut stream_error: Option<anyhow::Error> = None;

            while let Some(chunk_result) = stream.next().await {
                match chunk_result {
                    Ok(chunk) => {
                        hasher.update(&chunk);
                        if let Err(e) = file.write_all(&chunk).await {
                            stream_error = Some(anyhow::anyhow!("Failed to write chunk to file: {}", e));
                            break;
                        }
                        downloaded += chunk.len() as u64;
                        pb.set_position(downloaded);

                        // Log progress every 10 seconds for syslog visibility
                        let now = std::time::Instant::now();
                        if now.duration_since(last_progress_log).as_secs() >= 10 {
                            let elapsed_secs = download_start.elapsed().as_secs_f64();
                            let speed = if elapsed_secs > 0.0 {
                                (downloaded as f64 / 1_048_576.0) / elapsed_secs
                            } else {
                                0.0
                            };
                            info!("📥 {} — {:.1} MB received ({:.1} MB/s)", filename, downloaded as f64 / 1_048_576.0, speed);
                            last_progress_log = now;
                        }
                    }
                    Err(e) => {
                        stream_error = Some(anyhow::anyhow!("Failed to read HTTP response chunk: {}", e));
                        break;
                    }
                }
            }

            if let Some(err) = stream_error {
                warn!("⚠️ Attempt {}/{} failed for {}: {}", attempt, MAX_DOWNLOAD_RETRIES, filename, err);
                last_error = Some(err);
                continue;
            }

            if let Err(e) = file.flush().await {
                warn!("⚠️ Attempt {}/{} failed to flush {}: {}", attempt, MAX_DOWNLOAD_RETRIES, filename, e);
                last_error = Some(anyhow::anyhow!("Failed to flush file: {}", e));
                continue;
            }
            if let Err(e) = file.sync_data().await {
                warn!("⚠️ Attempt {}/{} failed to sync {}: {}", attempt, MAX_DOWNLOAD_RETRIES, filename, e);
                last_error = Some(anyhow::anyhow!("Failed to sync file: {}", e));
                continue;
            }

            pb.finish_with_message("Download complete");

            info!("✅ Downloaded {} ({:.2} MB)", filename, downloaded as f64 / 1_048_576.0);

            // Calculate checksum
            let checksum = hex::encode(hasher.finalize());

            // Update metadata with actual downloaded size
            self.metadata.insert(
                filename.to_string(),
                LocalFileInfo {
                    path: local_path.to_string_lossy().to_string(),
                    checksum,
                    version: extract_month_from_filename(filename),
                    size: downloaded,
                },
            );

            return Ok(downloaded);
        }

        // Clean up partial file left by the final failed attempt
        if local_path.exists()
            && let Err(e) = fs::remove_file(&local_path).await
        {
            warn!("⚠️ Failed to remove partial file after all retries: {}", e);
        }

        Err(last_error.unwrap_or_else(|| anyhow::anyhow!("Download failed after {} attempts", MAX_DOWNLOAD_RETRIES)))
    }

    pub fn save_metadata(&self) -> Result<()> {
        let metadata_file = self.output_directory.join(".discogs_metadata.json");
        let json = serde_json::to_string_pretty(&self.metadata).context("Failed to serialize metadata")?;

        std::fs::write(metadata_file, json).context("Failed to save metadata")?;

        Ok(())
    }
}

fn load_metadata(output_directory: &Path) -> Result<HashMap<String, LocalFileInfo>> {
    let metadata_file = output_directory.join(".discogs_metadata.json");

    if !metadata_file.exists() {
        return Ok(HashMap::new());
    }

    let json = std::fs::read_to_string(metadata_file).context("Failed to read metadata file")?;

    serde_json::from_str(&json).context("Failed to parse metadata")
}

async fn calculate_file_checksum(path: &Path) -> Result<String> {
    let mut file = File::open(path).await.context("Failed to open file for checksum")?;

    let mut hasher = Sha256::new();
    let mut buffer = vec![0; 8192];

    loop {
        let n = tokio::io::AsyncReadExt::read(&mut file, &mut buffer).await.context("Failed to read file for checksum")?;

        if n == 0 {
            break;
        }

        hasher.update(&buffer[..n]);
    }

    Ok(hex::encode(hasher.finalize()))
}

fn extract_month_from_filename(filename: &str) -> String {
    // Extract YYYYMMDD from filename like discogs_20241201_artists.xml.gz
    if let Some(date_part) = filename.split('_').nth(1)
        && date_part.len() >= 6
    {
        return date_part[0..6].to_string(); // YYYYMM
    }
    Utc::now().format("%Y%m").to_string()
}

#[async_trait]
impl DataSource for Downloader {
    async fn list_s3_files(&mut self) -> Result<Vec<S3FileInfo>> {
        Downloader::list_s3_files(self).await
    }

    fn get_latest_monthly_files(&self, files: &[S3FileInfo]) -> Result<Vec<S3FileInfo>> {
        Downloader::get_latest_monthly_files(self, files)
    }

    async fn download_discogs_data(&mut self) -> Result<Vec<String>> {
        Downloader::download_discogs_data(self).await
    }

    fn set_state_marker(&mut self, state_marker: StateMarker, marker_path: PathBuf) {
        self.state_marker = Some(state_marker);
        self.marker_path = Some(marker_path);
    }

    fn take_state_marker(&mut self) -> Option<StateMarker> {
        self.state_marker.take()
    }
}

#[cfg(test)]
#[path = "tests/downloader_tests.rs"]
mod tests;

// Keep remainder as a placeholder to handle removal of test block body
#[cfg(any())]
mod _remove_old_tests {
    use super::*;
    use std::collections::HashMap;
    use tempfile::TempDir;
    use tokio::fs;
    use tokio::io::AsyncWriteExt;

    #[test]
    fn test_extract_month() {
        assert_eq!(extract_month_from_filename("discogs_20241201_artists.xml.gz"), "202412");
        assert_eq!(extract_month_from_filename("discogs_20240115_labels.xml.gz"), "202401");
    }

    #[test]
    fn test_extract_month_invalid_filename() {
        // Test with invalid filename formats - should return current month (YYYYMM)
        let result = extract_month_from_filename("invalid_format.xml");
        assert_eq!(result.len(), 6); // Should be YYYYMM format

        // Test with short date part - takes what's available or returns current month
        let result = extract_month_from_filename("discogs_2024_artists.xml.gz");
        // This should return current month since 2024 is not 6 chars
        assert_eq!(result.len(), 6);
    }

    #[test]
    fn test_extract_month_edge_cases() {
        // Test with short date part - should return current month
        let result = extract_month_from_filename("discogs_2024_test.xml.gz");
        assert_eq!(result.len(), 6);

        // Test with no underscores - should return current month
        let result = extract_month_from_filename("nounderscores.xml.gz");
        assert_eq!(result.len(), 6);
    }

    #[tokio::test]
    async fn test_load_metadata_nonexistent() {
        let temp_dir = TempDir::new().unwrap();
        let metadata = load_metadata(temp_dir.path()).unwrap();
        assert!(metadata.is_empty());
    }

    #[tokio::test]
    async fn test_load_metadata_valid() {
        let temp_dir = TempDir::new().unwrap();
        let metadata_path = temp_dir.path().join(".discogs_metadata.json");

        let mut test_metadata = HashMap::new();
        test_metadata.insert(
            "test.xml.gz".to_string(),
            LocalFileInfo { path: "/tmp/test.xml.gz".to_string(), checksum: "abc123".to_string(), version: "202412".to_string(), size: 1024 },
        );

        let json = serde_json::to_string_pretty(&test_metadata).unwrap();
        std::fs::write(&metadata_path, json).unwrap();

        let loaded = load_metadata(temp_dir.path()).unwrap();
        assert_eq!(loaded.len(), 1);
        assert_eq!(loaded.get("test.xml.gz").unwrap().checksum, "abc123");
    }

    #[tokio::test]
    async fn test_load_metadata_invalid_json() {
        let temp_dir = TempDir::new().unwrap();
        let metadata_path = temp_dir.path().join(".discogs_metadata.json");

        std::fs::write(&metadata_path, "invalid json").unwrap();

        let result = load_metadata(temp_dir.path());
        assert!(result.is_err());
    }

    #[tokio::test]
    async fn test_calculate_file_checksum() {
        let temp_dir = TempDir::new().unwrap();
        let test_file = temp_dir.path().join("test.txt");

        let mut file = fs::File::create(&test_file).await.unwrap();
        file.write_all(b"test content").await.unwrap();
        file.sync_all().await.unwrap();
        drop(file);

        let checksum = calculate_file_checksum(&test_file).await.unwrap();
        assert!(!checksum.is_empty());
        assert_eq!(checksum.len(), 64); // SHA256 hex string length
    }

    #[tokio::test]
    async fn test_calculate_file_checksum_empty_file() {
        let temp_dir = TempDir::new().unwrap();
        let test_file = temp_dir.path().join("empty.txt");

        fs::File::create(&test_file).await.unwrap();

        let checksum = calculate_file_checksum(&test_file).await.unwrap();
        assert!(!checksum.is_empty());
        assert_eq!(checksum.len(), 64);
    }

    #[tokio::test]
    async fn test_calculate_file_checksum_nonexistent() {
        let temp_dir = TempDir::new().unwrap();
        let test_file = temp_dir.path().join("nonexistent.txt");

        let result = calculate_file_checksum(&test_file).await;
        assert!(result.is_err());
    }

    #[tokio::test]
    async fn test_downloader_new() {
        let temp_dir = TempDir::new().unwrap();

        // Create a new downloader (no AWS connection needed anymore)
        let result = Downloader::new(temp_dir.path().to_path_buf()).await;

        // We expect this to succeed since it's just initialization
        assert!(result.is_ok());

        let downloader = result.unwrap();
        assert_eq!(downloader.output_directory, temp_dir.path());
        assert!(downloader.metadata.is_empty());
    }

    #[tokio::test]
    async fn test_downloader_save_metadata() {
        let temp_dir = TempDir::new().unwrap();
        let mut downloader = Downloader::new(temp_dir.path().to_path_buf()).await.unwrap();

        downloader.metadata.insert(
            "test.xml.gz".to_string(),
            LocalFileInfo { path: "/tmp/test.xml.gz".to_string(), checksum: "abc123".to_string(), version: "202412".to_string(), size: 1024 },
        );

        let result = downloader.save_metadata();
        assert!(result.is_ok());

        let metadata_file = temp_dir.path().join(".discogs_metadata.json");
        assert!(metadata_file.exists());

        let loaded = load_metadata(temp_dir.path()).unwrap();
        assert_eq!(loaded.len(), 1);
    }

    #[tokio::test]
    async fn test_should_download_file_not_exists() {
        let temp_dir = TempDir::new().unwrap();
        let downloader = Downloader::new(temp_dir.path().to_path_buf()).await.unwrap();

        let file_info = S3FileInfo { name: "discogs_20241201_artists.xml.gz".to_string(), size: 1024 };

        let should_download = downloader.should_download(&file_info).await.unwrap();
        assert!(should_download);
    }

    #[tokio::test]
    async fn test_should_download_size_changed() {
        let temp_dir = TempDir::new().unwrap();
        let mut downloader = Downloader::new(temp_dir.path().to_path_buf()).await.unwrap();

        // Create a local file
        let filename = "discogs_20241201_artists.xml.gz";
        let local_path = temp_dir.path().join(filename);
        fs::write(&local_path, b"test content").await.unwrap();

        // Add metadata with different size
        downloader.metadata.insert(
            filename.to_string(),
            LocalFileInfo {
                path: local_path.to_string_lossy().to_string(),
                checksum: "abc123".to_string(),
                version: "202412".to_string(),
                size: 1024,
            },
        );

        let file_info = S3FileInfo {
            name: filename.to_string(),
            size: 2048, // Different size
        };

        let should_download = downloader.should_download(&file_info).await.unwrap();
        assert!(should_download);
    }

    #[tokio::test]
    async fn test_should_download_checksum_mismatch() {
        let temp_dir = TempDir::new().unwrap();
        let mut downloader = Downloader::new(temp_dir.path().to_path_buf()).await.unwrap();

        // Create a local file
        let filename = "discogs_20241201_artists.xml.gz";
        let local_path = temp_dir.path().join(filename);
        let content = b"test content";
        fs::write(&local_path, content).await.unwrap();

        // Add metadata with wrong checksum (intentionally not using actual checksum)
        downloader.metadata.insert(
            filename.to_string(),
            LocalFileInfo {
                path: local_path.to_string_lossy().to_string(),
                checksum: "wrong_checksum".to_string(),
                version: "202412".to_string(),
                size: content.len() as u64,
            },
        );

        let file_info = S3FileInfo { name: filename.to_string(), size: content.len() as u64 };

        let should_download = downloader.should_download(&file_info).await.unwrap();
        assert!(should_download);
    }

    #[tokio::test]
    async fn test_should_download_up_to_date() {
        let temp_dir = TempDir::new().unwrap();
        let mut downloader = Downloader::new(temp_dir.path().to_path_buf()).await.unwrap();

        // Create a local file
        let filename = "discogs_20241201_artists.xml.gz";
        let local_path = temp_dir.path().join(filename);
        let content = b"test content";
        fs::write(&local_path, content).await.unwrap();

        let actual_checksum = calculate_file_checksum(&local_path).await.unwrap();

        // Add metadata with correct checksum and size
        downloader.metadata.insert(
            filename.to_string(),
            LocalFileInfo {
                path: local_path.to_string_lossy().to_string(),
                checksum: actual_checksum,
                version: "202412".to_string(),
                size: content.len() as u64,
            },
        );

        let file_info = S3FileInfo { name: filename.to_string(), size: content.len() as u64 };

        let should_download = downloader.should_download(&file_info).await.unwrap();
        assert!(!should_download);
    }

    #[test]
    fn test_get_latest_monthly_files_no_complete_set() {
        let temp_dir = TempDir::new().unwrap();
        let downloader = tokio::runtime::Runtime::new().unwrap().block_on(Downloader::new(temp_dir.path().to_path_buf())).unwrap();

        // Only 3 files instead of required 4 data files + 1 checksum
        let files = vec![
            S3FileInfo { name: "data/discogs_20241201_artists.xml.gz".to_string(), size: 1024 },
            S3FileInfo { name: "data/discogs_20241201_labels.xml.gz".to_string(), size: 1024 },
            S3FileInfo { name: "data/discogs_20241201_CHECKSUM.txt".to_string(), size: 100 },
        ];

        let result = downloader.get_latest_monthly_files(&files).unwrap();
        assert!(result.is_empty());
    }

    #[test]
    fn test_get_latest_monthly_files_complete_set() {
        let temp_dir = TempDir::new().unwrap();
        let downloader = tokio::runtime::Runtime::new().unwrap().block_on(Downloader::new(temp_dir.path().to_path_buf())).unwrap();

        // Complete set: 4 data files + 1 checksum
        let files = vec![
            S3FileInfo { name: "data/discogs_20241201_artists.xml.gz".to_string(), size: 1024 },
            S3FileInfo { name: "data/discogs_20241201_labels.xml.gz".to_string(), size: 1024 },
            S3FileInfo { name: "data/discogs_20241201_masters.xml.gz".to_string(), size: 1024 },
            S3FileInfo { name: "data/discogs_20241201_releases.xml.gz".to_string(), size: 1024 },
            S3FileInfo { name: "data/discogs_20241201_CHECKSUM.txt".to_string(), size: 100 },
        ];

        let result = downloader.get_latest_monthly_files(&files).unwrap();
        assert_eq!(result.len(), 4); // Should return 4 data files

        // Verify filenames have prefix stripped
        assert!(result.iter().all(|f| !f.name.starts_with("data/")));
    }

    #[tokio::test]
    async fn test_with_state_marker() {
        use crate::state_marker::StateMarker;

        let temp_dir = TempDir::new().unwrap();
        let marker = StateMarker::new("20260101".to_string());
        let marker_path = temp_dir.path().join(".extraction_status_20260101.json");

        let downloader = Downloader::new(temp_dir.path().to_path_buf()).await.unwrap().with_state_marker(marker, marker_path.clone());

        assert!(downloader.state_marker.is_some());
        assert!(downloader.marker_path.is_some());
        assert_eq!(downloader.state_marker.as_ref().unwrap().current_version, "20260101");
        assert_eq!(downloader.marker_path.as_ref().unwrap(), &marker_path);
    }

    #[tokio::test]
    async fn test_save_state_marker_with_marker() {
        use crate::state_marker::StateMarker;

        let temp_dir = TempDir::new().unwrap();
        let marker = StateMarker::new("20260101".to_string());
        let marker_path = temp_dir.path().join(".extraction_status_20260101.json");

        let mut downloader = Downloader::new(temp_dir.path().to_path_buf()).await.unwrap().with_state_marker(marker, marker_path.clone());

        downloader.save_state_marker().await;

        // Verify the file was written
        assert!(marker_path.exists());
        let contents = fs::read_to_string(&marker_path).await.unwrap();
        let parsed: serde_json::Value = serde_json::from_str(&contents).unwrap();
        assert_eq!(parsed["current_version"], "20260101");
    }

    #[tokio::test]
    async fn test_save_state_marker_without_marker() {
        let temp_dir = TempDir::new().unwrap();
        let mut downloader = Downloader::new(temp_dir.path().to_path_buf()).await.unwrap();

        // Should be a no-op, no error
        downloader.save_state_marker().await;

        assert!(downloader.state_marker.is_none());
        assert!(downloader.marker_path.is_none());
    }

    #[tokio::test]
    async fn test_new_with_base_url() {
        let temp_dir = TempDir::new().unwrap();
        let custom_url = "https://custom.example.com/".to_string();
        let downloader = Downloader::new_with_base_url(temp_dir.path().to_path_buf(), custom_url).await.unwrap();

        // base_url is private, but we can verify the downloader was created successfully
        assert_eq!(downloader.output_directory, temp_dir.path());
        assert!(downloader.metadata.is_empty());
    }

    #[tokio::test]
    async fn test_should_download_no_metadata_file_exists() {
        let temp_dir = TempDir::new().unwrap();
        let downloader = Downloader::new(temp_dir.path().to_path_buf()).await.unwrap();

        // Create a local file but do NOT add any metadata entry
        let filename = "discogs_20241201_artists.xml.gz";
        let local_path = temp_dir.path().join(filename);
        fs::write(&local_path, b"some data").await.unwrap();

        let file_info = S3FileInfo { name: filename.to_string(), size: 1024 };

        // File exists locally but no metadata entry — should return true (download to be safe)
        let should_download = downloader.should_download(&file_info).await.unwrap();
        assert!(should_download);
    }

    #[test]
    fn test_get_latest_monthly_files_empty_input() {
        let temp_dir = TempDir::new().unwrap();
        let downloader = tokio::runtime::Runtime::new().unwrap().block_on(Downloader::new(temp_dir.path().to_path_buf())).unwrap();

        let files: Vec<S3FileInfo> = vec![];
        let result = downloader.get_latest_monthly_files(&files).unwrap();
        assert!(result.is_empty());
    }

    #[tokio::test]
    async fn test_download_discogs_data_with_state_marker() {
        use crate::state_marker::StateMarker;

        let temp_dir = TempDir::new().unwrap();

        // Set up mockito server
        let mut server = mockito::Server::new_async().await;
        let base_url = format!("{}/", server.url());

        // Main page listing year directories
        let main_page_html = r#"<html><body>
            <a href="?prefix=data%2F2026%2F">2026/</a>
        </body></html>"#;

        let _main_mock = server.mock("GET", "/").with_status(200).with_body(main_page_html).create_async().await;

        // Year page listing files (5 files = 4 data + 1 checksum for a complete set)
        let year_page_html = r#"<html><body>
            <a href="?download=data%2F2026%2Fdiscogs_20260101_artists.xml.gz">artists</a>
            <a href="?download=data%2F2026%2Fdiscogs_20260101_labels.xml.gz">labels</a>
            <a href="?download=data%2F2026%2Fdiscogs_20260101_masters.xml.gz">masters</a>
            <a href="?download=data%2F2026%2Fdiscogs_20260101_releases.xml.gz">releases</a>
            <a href="?download=data%2F2026%2Fdiscogs_20260101_CHECKSUM.txt">checksum</a>
        </body></html>"#
            .to_string();

        let _year_mock = server.mock("GET", "/?prefix=data%2F2026%2F").with_status(200).with_body(&year_page_html).create_async().await;

        // Mock download endpoints for each file
        let file_types = ["artists", "labels", "masters", "releases"];
        let mut _download_mocks = Vec::new();
        for file_type in &file_types {
            let download_path = format!("/?download=data%2F2026%2Fdiscogs_20260101_{}.xml.gz", file_type);
            let mock = server
                .mock("GET", download_path.as_str())
                .with_status(200)
                .with_body(format!("fake {} data", file_type))
                .create_async()
                .await;
            _download_mocks.push(mock);
        }

        // Create downloader with state marker
        let marker = StateMarker::new("20260101".to_string());
        let marker_path = temp_dir.path().join(".extraction_status_20260101.json");

        let mut downloader = Downloader::new_with_base_url(temp_dir.path().to_path_buf(), base_url)
            .await
            .unwrap()
            .with_state_marker(marker, marker_path.clone());

        let result = downloader.download_discogs_data().await.unwrap();

        // Should have downloaded 4 data files
        assert_eq!(result.len(), 4);

        // State marker should have been saved and track downloads
        assert!(marker_path.exists());
        let marker = downloader.state_marker.as_ref().unwrap();
        assert_eq!(marker.download_phase.files_downloaded, 4);
        assert!(marker.download_phase.bytes_downloaded > 0);
        assert_eq!(marker.download_phase.status, crate::state_marker::PhaseStatus::Completed);
    }

    #[tokio::test]
    async fn test_download_discogs_data_skips_already_downloaded() {
        use sha2::{Digest, Sha256};

        let temp_dir = TempDir::new().unwrap();

        // Set up mockito server
        let mut server = mockito::Server::new_async().await;
        let base_url = format!("{}/", server.url());

        // Main page listing year directories
        let main_page_html = r#"<html><body>
            <a href="?prefix=data%2F2026%2F">2026/</a>
        </body></html>"#;

        let _main_mock = server.mock("GET", "/").with_status(200).with_body(main_page_html).create_async().await;

        // Year page with complete 5-file set
        let year_page_html = r#"<html><body>
            <a href="?download=data%2F2026%2Fdiscogs_20260101_artists.xml.gz">artists</a>
            <a href="?download=data%2F2026%2Fdiscogs_20260101_labels.xml.gz">labels</a>
            <a href="?download=data%2F2026%2Fdiscogs_20260101_masters.xml.gz">masters</a>
            <a href="?download=data%2F2026%2Fdiscogs_20260101_releases.xml.gz">releases</a>
            <a href="?download=data%2F2026%2Fdiscogs_20260101_CHECKSUM.txt">checksum</a>
        </body></html>"#;

        let _year_mock = server.mock("GET", "/?prefix=data%2F2026%2F").with_status(200).with_body(year_page_html).create_async().await;

        // Pre-create all 4 data files locally with known content and matching checksums
        let file_types = ["artists", "labels", "masters", "releases"];
        let mut downloader = Downloader::new_with_base_url(temp_dir.path().to_path_buf(), base_url).await.unwrap();

        for file_type in &file_types {
            let filename = format!("discogs_20260101_{}.xml.gz", file_type);
            let content = format!("existing {} data", file_type);
            let local_path = temp_dir.path().join(&filename);
            fs::write(&local_path, content.as_bytes()).await.unwrap();

            // Compute actual SHA256 checksum
            let mut hasher = Sha256::new();
            hasher.update(content.as_bytes());
            let checksum = hex::encode(hasher.finalize());

            // Pre-populate metadata with correct checksum
            downloader.metadata.insert(
                filename,
                LocalFileInfo { path: local_path.to_string_lossy().to_string(), checksum, version: "202601".to_string(), size: content.len() as u64 },
            );
        }

        // No download mocks are set up — if it tries to download, mockito will return
        // an unexpected request error. The test succeeds only if downloads are skipped.

        let result = downloader.download_discogs_data().await.unwrap();

        // All 4 files should be returned (skipped but still tracked)
        assert_eq!(result.len(), 4);
        for file_type in &file_types {
            let filename = format!("discogs_20260101_{}.xml.gz", file_type);
            assert!(result.contains(&filename), "Expected {} in result", filename);
        }
    }

    #[tokio::test]
    async fn test_list_s3_files_uses_cache() {
        let temp_dir = TempDir::new().unwrap();

        let mut server = mockito::Server::new_async().await;
        let base_url = format!("{}/", server.url());

        let main_page_html = r#"<html><body>
            <a href="?prefix=data%2F2026%2F">2026/</a>
        </body></html>"#;

        // Expect the main page to be called exactly once
        let _main_mock = server.mock("GET", "/").with_status(200).with_body(main_page_html).expect(1).create_async().await;

        let year_page_html = r#"<html><body>
            <a href="?download=data%2F2026%2Fdiscogs_20260101_artists.xml.gz">artists</a>
            <a href="?download=data%2F2026%2Fdiscogs_20260101_labels.xml.gz">labels</a>
            <a href="?download=data%2F2026%2Fdiscogs_20260101_masters.xml.gz">masters</a>
            <a href="?download=data%2F2026%2Fdiscogs_20260101_releases.xml.gz">releases</a>
            <a href="?download=data%2F2026%2Fdiscogs_20260101_CHECKSUM.txt">checksum</a>
        </body></html>"#;

        let _year_mock = server.mock("GET", "/?prefix=data%2F2026%2F").with_status(200).with_body(year_page_html).expect(1).create_async().await;

        let mut downloader = Downloader::new_with_base_url(temp_dir.path().to_path_buf(), base_url).await.unwrap();

        // First call — fetches from server
        let first_result = downloader.list_s3_files().await.unwrap();
        assert_eq!(first_result.len(), 5); // 4 data + 1 checksum

        // Second call — should use cache, no additional HTTP requests
        let second_result = downloader.list_s3_files().await.unwrap();
        assert_eq!(second_result.len(), 5);
        assert_eq!(first_result.len(), second_result.len());

        // mockito expect(1) will panic on drop if mocks were hit more than once
    }

    #[tokio::test]
    async fn test_download_discogs_data_with_state_marker_skips() {
        use crate::state_marker::StateMarker;
        use sha2::{Digest, Sha256};

        let temp_dir = TempDir::new().unwrap();

        let mut server = mockito::Server::new_async().await;
        let base_url = format!("{}/", server.url());

        let main_page_html = r#"<html><body>
            <a href="?prefix=data%2F2026%2F">2026/</a>
        </body></html>"#;

        let _main_mock = server.mock("GET", "/").with_status(200).with_body(main_page_html).create_async().await;

        let year_page_html = r#"<html><body>
            <a href="?download=data%2F2026%2Fdiscogs_20260101_artists.xml.gz">artists</a>
            <a href="?download=data%2F2026%2Fdiscogs_20260101_labels.xml.gz">labels</a>
            <a href="?download=data%2F2026%2Fdiscogs_20260101_masters.xml.gz">masters</a>
            <a href="?download=data%2F2026%2Fdiscogs_20260101_releases.xml.gz">releases</a>
            <a href="?download=data%2F2026%2Fdiscogs_20260101_CHECKSUM.txt">checksum</a>
        </body></html>"#;

        let _year_mock = server.mock("GET", "/?prefix=data%2F2026%2F").with_status(200).with_body(year_page_html).create_async().await;

        // Pre-create all 4 data files with matching checksums
        let file_types = ["artists", "labels", "masters", "releases"];
        let mut downloader = Downloader::new_with_base_url(temp_dir.path().to_path_buf(), base_url).await.unwrap();

        let mut expected_sizes: HashMap<String, u64> = HashMap::new();

        for file_type in &file_types {
            let filename = format!("discogs_20260101_{}.xml.gz", file_type);
            let content = format!("state marker {} data", file_type);
            let local_path = temp_dir.path().join(&filename);
            fs::write(&local_path, content.as_bytes()).await.unwrap();

            let mut hasher = Sha256::new();
            hasher.update(content.as_bytes());
            let checksum = hex::encode(hasher.finalize());

            expected_sizes.insert(filename.clone(), content.len() as u64);

            downloader.metadata.insert(
                filename,
                LocalFileInfo { path: local_path.to_string_lossy().to_string(), checksum, version: "202601".to_string(), size: content.len() as u64 },
            );
        }

        // Attach a state marker
        let marker = StateMarker::new("20260101".to_string());
        let marker_path = temp_dir.path().join(".extraction_status_20260101.json");
        downloader.state_marker = Some(marker);
        downloader.marker_path = Some(marker_path.clone());

        let result = downloader.download_discogs_data().await.unwrap();
        assert_eq!(result.len(), 4);

        // State marker should track all files as downloaded with correct byte sizes
        let marker = downloader.state_marker.as_ref().unwrap();
        assert_eq!(marker.download_phase.files_downloaded, 4);
        assert_eq!(marker.download_phase.status, crate::state_marker::PhaseStatus::Completed);
        assert!(marker.download_phase.bytes_downloaded > 0);

        // Verify each file is tracked in the state marker with correct size
        for file_type in &file_types {
            let filename = format!("discogs_20260101_{}.xml.gz", file_type);
            let file_status = marker.download_phase.downloads_by_file.get(&filename);
            assert!(file_status.is_some(), "File {} should be tracked in state marker", filename);
            let status = file_status.unwrap();
            assert_eq!(status.status, crate::state_marker::PhaseStatus::Completed);
            assert_eq!(status.bytes_downloaded, *expected_sizes.get(&filename).unwrap());
        }

        // Verify marker was persisted to disk
        assert!(marker_path.exists());
    }

    // ──── DataSource trait impl tests ────

    #[tokio::test]
    async fn test_datasource_set_and_take_state_marker() {
        use crate::state_marker::StateMarker;

        let temp_dir = TempDir::new().unwrap();
        let mut downloader: Box<dyn DataSource> =
            Box::new(Downloader::new_with_base_url(temp_dir.path().to_path_buf(), "http://unused".to_string()).await.unwrap());

        // Initially no state marker
        assert!(downloader.take_state_marker().is_none());

        // Set a state marker via the trait
        let marker = StateMarker::new("20260101".to_string());
        let marker_path = temp_dir.path().join("marker.json");
        downloader.set_state_marker(marker, marker_path);

        // Take it back
        let taken = downloader.take_state_marker();
        assert!(taken.is_some());
        assert_eq!(taken.unwrap().current_version, "20260101");

        // Should be None after take
        assert!(downloader.take_state_marker().is_none());
    }

    #[tokio::test]
    async fn test_datasource_list_s3_files_via_trait() {
        let temp_dir = TempDir::new().unwrap();
        let mut server = mockito::Server::new_async().await;
        let base_url = format!("{}/", server.url());

        let main_page_html = r#"<html><body>
            <a href="?prefix=data%2F2026%2F">2026/</a>
        </body></html>"#;
        let _main_mock = server.mock("GET", "/").with_status(200).with_body(main_page_html).create_async().await;

        let year_page_html = r#"<html><body>
            <a href="?download=data%2F2026%2Fdiscogs_20260101_artists.xml.gz">artists</a>
            <a href="?download=data%2F2026%2Fdiscogs_20260101_labels.xml.gz">labels</a>
            <a href="?download=data%2F2026%2Fdiscogs_20260101_masters.xml.gz">masters</a>
            <a href="?download=data%2F2026%2Fdiscogs_20260101_releases.xml.gz">releases</a>
            <a href="?download=data%2F2026%2Fdiscogs_20260101_CHECKSUM.txt">checksum</a>
        </body></html>"#;
        let _year_mock = server.mock("GET", "/?prefix=data%2F2026%2F").with_status(200).with_body(year_page_html).create_async().await;

        let mut downloader: Box<dyn DataSource> = Box::new(Downloader::new_with_base_url(temp_dir.path().to_path_buf(), base_url).await.unwrap());

        // Call through the DataSource trait
        let files = downloader.list_s3_files().await.unwrap();
        assert_eq!(files.len(), 5);
    }

    #[tokio::test]
    async fn test_datasource_get_latest_monthly_files_via_trait() {
        let temp_dir = TempDir::new().unwrap();
        let downloader: Box<dyn DataSource> =
            Box::new(Downloader::new_with_base_url(temp_dir.path().to_path_buf(), "http://unused".to_string()).await.unwrap());

        let files = vec![
            S3FileInfo { name: "data/discogs_20260101_artists.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_labels.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_masters.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_releases.xml.gz".to_string(), size: 1000 },
            S3FileInfo { name: "data/discogs_20260101_CHECKSUM.txt".to_string(), size: 100 },
        ];

        let result = downloader.get_latest_monthly_files(&files).unwrap();
        assert_eq!(result.len(), 4);
        assert!(result.iter().all(|f| !f.name.contains("CHECKSUM")));
    }

    #[test]
    fn test_get_latest_monthly_files_multiple_versions() {
        let temp_dir = TempDir::new().unwrap();
        let downloader = tokio::runtime::Runtime::new().unwrap().block_on(Downloader::new(temp_dir.path().to_path_buf())).unwrap();

        // Multiple versions - should pick the latest (20241215)
        let files = vec![
            // Older version (20241201)
            S3FileInfo { name: "data/discogs_20241201_artists.xml.gz".to_string(), size: 1024 },
            S3FileInfo { name: "data/discogs_20241201_labels.xml.gz".to_string(), size: 1024 },
            S3FileInfo { name: "data/discogs_20241201_masters.xml.gz".to_string(), size: 1024 },
            S3FileInfo { name: "data/discogs_20241201_releases.xml.gz".to_string(), size: 1024 },
            S3FileInfo { name: "data/discogs_20241201_CHECKSUM.txt".to_string(), size: 100 },
            // Newer version (20241215)
            S3FileInfo { name: "data/discogs_20241215_artists.xml.gz".to_string(), size: 2048 },
            S3FileInfo { name: "data/discogs_20241215_labels.xml.gz".to_string(), size: 2048 },
            S3FileInfo { name: "data/discogs_20241215_masters.xml.gz".to_string(), size: 2048 },
            S3FileInfo { name: "data/discogs_20241215_releases.xml.gz".to_string(), size: 2048 },
            S3FileInfo { name: "data/discogs_20241215_CHECKSUM.txt".to_string(), size: 100 },
        ];

        let result = downloader.get_latest_monthly_files(&files).unwrap();
        assert_eq!(result.len(), 4);

        // Verify all files are from the latest version
        assert!(result.iter().all(|f| f.name.contains("20241215")));
    }

    #[tokio::test]
    async fn test_save_state_marker_failure_warns() {
        // Exercises the warn! path in save_state_marker (line 57)
        // by pointing the marker path to a non-existent parent directory.
        use crate::state_marker::StateMarker;

        let temp_dir = TempDir::new().unwrap();
        let marker = StateMarker::new("20260101".to_string());
        // Path with non-existent parent directory so save() fails
        let bad_path = PathBuf::from("/nonexistent/dir/marker.json");

        let mut downloader = Downloader::new(temp_dir.path().to_path_buf()).await.unwrap().with_state_marker(marker, bad_path.clone());

        // Should not panic — just warns internally
        downloader.save_state_marker().await;

        // Marker file should NOT exist (save failed)
        assert!(!bad_path.exists());
    }
}
