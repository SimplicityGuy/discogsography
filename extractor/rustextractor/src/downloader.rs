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

use crate::state_marker::StateMarker;
use crate::types::{LocalFileInfo, S3FileInfo};

const S3_PREFIX: &str = "data/";
const DISCOGS_DATA_URL: &str = "https://data.discogs.com/";

pub struct Downloader {
    pub output_directory: PathBuf,
    pub metadata: HashMap<String, LocalFileInfo>,
    base_url: String,
    pub state_marker: Option<StateMarker>,
    pub marker_path: Option<PathBuf>,
}

impl Downloader {
    pub async fn new(output_directory: PathBuf) -> Result<Self> {
        Self::new_with_base_url(output_directory, DISCOGS_DATA_URL.to_string()).await
    }

    /// Create a new downloader with a custom base URL (primarily for testing)
    #[doc(hidden)]
    pub async fn new_with_base_url(output_directory: PathBuf, base_url: String) -> Result<Self> {
        let metadata = load_metadata(&output_directory)?;

        Ok(Self {
            output_directory,
            metadata,
            base_url,
            state_marker: None,
            marker_path: None,
        })
    }

    /// Set the state marker for tracking download progress
    pub fn with_state_marker(mut self, state_marker: StateMarker, marker_path: PathBuf) -> Self {
        self.state_marker = Some(state_marker);
        self.marker_path = Some(marker_path);
        self
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
            if let Some(ref marker_path) = self.marker_path {
                marker.save(marker_path).await.ok();
            }
        }

        let mut downloaded_files = Vec::new();

        for file_info in &latest_files {
            if self.should_download(file_info).await? {
                match self.download_file(file_info).await {
                    Ok(_) => {
                        let filename = std::path::Path::new(&file_info.name).file_name().and_then(|name| name.to_str()).unwrap_or("unknown_file");
                        info!("✅ Successfully downloaded: {}", filename);

                        // Track file download in state marker
                        if let Some(ref mut marker) = self.state_marker {
                            marker.file_downloaded(file_info.size);
                            if let Some(ref marker_path) = self.marker_path {
                                marker.save(marker_path).await.ok();
                            }
                        }

                        downloaded_files.push(filename.to_string());
                    }
                    Err(e) => {
                        let filename = std::path::Path::new(&file_info.name).file_name().and_then(|name| name.to_str()).unwrap_or("unknown_file");
                        error!("❌ Failed to download {}: {}", filename, e);
                    }
                }
            } else {
                let filename = std::path::Path::new(&file_info.name).file_name().and_then(|name| name.to_str()).unwrap_or("unknown_file");
                info!("✅ Already have latest version of: {}", filename);

                // Track existing file in state marker
                if let Some(ref mut marker) = self.state_marker {
                    marker.file_downloaded(file_info.size);
                    if let Some(ref marker_path) = self.marker_path {
                        marker.save(marker_path).await.ok();
                    }
                }

                downloaded_files.push(filename.to_string());
            }
        }

        // Complete download phase tracking if state marker is available
        if let Some(ref mut marker) = self.state_marker {
            marker.complete_download();
            if let Some(ref marker_path) = self.marker_path {
                marker.save(marker_path).await.ok();
            }
        }

        // Save updated metadata
        self.save_metadata()?;

        Ok(downloaded_files)
    }

    async fn scrape_file_list_from_discogs(&self) -> Result<HashMap<String, Vec<S3FileInfo>>> {
        info!("🌐 Fetching file list from Discogs website...");

        // Step 1: Fetch the main page to get available years
        let response = reqwest::get(&self.base_url)
            .await
            .context("Failed to fetch Discogs website")?;

        let html = response.text().await.context("Failed to read HTML response")?;

        // Extract year directories (e.g., 2026/, 2025/, etc.)
        let year_pattern = Regex::new(r#"href="\?prefix=data%2F(\d{4})%2F""#)
            .context("Failed to compile year regex")?;

        let mut years: Vec<String> = year_pattern
            .captures_iter(&html)
            .filter_map(|cap| cap.get(1).map(|m| m.as_str().to_string()))
            .collect();

        if years.is_empty() {
            return Err(anyhow::anyhow!("No year directories found on Discogs website"));
        }

        // Sort years in descending order (most recent first)
        years.sort_by(|a, b| b.cmp(a));
        info!("📅 Found {} year directories, checking recent years...", years.len());

        // Step 2: Fetch files from recent years (check last 2 years)
        let mut ids: HashMap<String, Vec<S3FileInfo>> = HashMap::new();

        for year in years.iter().take(2) {
            let year_url = format!("{}?prefix=data%2F{}%2F", self.base_url, year);

            match reqwest::get(&year_url).await {
                Ok(year_response) => {
                    if let Ok(year_html) = year_response.text().await {
                        // Extract file links from year directory
                        // Pattern matches: ?download=data%2F2026%2Fdiscogs_20260101_artists.xml.gz
                        let file_pattern = Regex::new(r#"\?download=data%2F\d{4}%2F(discogs_(\d{8})_[^"]+)"#)
                            .context("Failed to compile file regex")?;

                        let mut file_count = 0;
                        for cap in file_pattern.captures_iter(&year_html) {
                            if let (Some(filename_match), Some(version_match)) = (cap.get(1), cap.get(2)) {
                                let filename = filename_match.as_str();
                                let version_id = version_match.as_str();

                                // URL decode the filename
                                let decoded_filename = urlencoding::decode(filename)
                                    .context("Failed to URL decode filename")?
                                    .to_string();

                                // Construct full S3 key
                                let s3_key = format!("data/{}/{}", year, decoded_filename);

                                ids.entry(version_id.to_string())
                                    .or_default()
                                    .push(S3FileInfo { name: s3_key, size: 0 });

                                file_count += 1;
                            }
                        }

                        if file_count > 0 {
                            info!("📋 Found {} files in year {} directory", file_count, year);
                        }
                    }
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

    pub async fn list_s3_files(&self) -> Result<Vec<S3FileInfo>> {
        info!("🔍 Listing available files from Discogs website...");

        // Scrape file list from Discogs website instead of S3 listing
        // This avoids the AccessDenied error from S3's ListBucket restriction
        let ids_map = self.scrape_file_list_from_discogs().await?;

        // Flatten the map into a single list of files for compatibility
        let files: Vec<S3FileInfo> = ids_map
            .into_values()
            .flat_map(|files| files.into_iter())
            .collect();

        info!("Found {} relevant files from website", files.len());
        Ok(files)
    }

    pub fn get_latest_monthly_files(&self, files: &[S3FileInfo]) -> Result<Vec<S3FileInfo>> {
        // Group files by their ID (date part like "20250801") - matching Python logic
        let mut ids: std::collections::HashMap<String, Vec<S3FileInfo>> = std::collections::HashMap::new();

        for file in files {
            // Split the full S3 key exactly like Python does
            let parts: Vec<&str> = file.name.split('_').collect();
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
                continue;
            }

            // Only return data files (not CHECKSUM) for processing, with filename only
            let data_files: Vec<_> = files_for_id
                .iter()
                .filter(|f| f.name.ends_with(".xml.gz"))
                .map(|f| {
                    let filename = f.name.strip_prefix(S3_PREFIX).unwrap_or(&f.name);
                    S3FileInfo { name: filename.to_string(), size: f.size }
                })
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
            // Instead, just validate checksum if file exists
            if local_path.exists() {
                let checksum = calculate_file_checksum(&local_path).await?;
                if checksum != local_info.checksum {
                    warn!("⚠️ Checksum mismatch for {}", file_info.name);
                    return Ok(true);
                }
            }

            // File exists with correct checksum
            return Ok(false);
        }

        // No metadata, download to be safe
        Ok(true)
    }

    /// Download a single file (exposed for testing)
    #[doc(hidden)]
    pub async fn download_file(&mut self, file_info: &S3FileInfo) -> Result<()> {
        use futures::StreamExt;

        // Reconstruct the full S3 key by prepending the prefix
        let s3_key = format!("{}{}", S3_PREFIX, &file_info.name);
        // Extract just the base filename for local storage (remove path components)
        let filename = std::path::Path::new(&file_info.name).file_name().and_then(|name| name.to_str()).unwrap_or("unknown_file");
        let local_path = self.output_directory.join(filename);

        info!("⬇️ Downloading {}...", filename);

        // Construct Discogs download URL (URL encode the S3 key)
        let download_url = format!("{}?download={}", self.base_url, urlencoding::encode(&s3_key));

        // Create progress bar (unknown size from scraping)
        let pb = ProgressBar::new_spinner();
        pb.set_style(
            ProgressStyle::default_spinner()
                .template("{spinner:.green} [{elapsed_precise}] {bytes} ({bytes_per_sec})")
                .unwrap(),
        );

        // Download using reqwest with streaming
        let response = reqwest::get(&download_url)
            .await
            .with_context(|| format!("Failed to start HTTP download from: {}", download_url))?;

        if !response.status().is_success() {
            return Err(anyhow::anyhow!("HTTP error: {}", response.status()));
        }

        let mut file = File::create(&local_path).await.context("Failed to create local file")?;
        let mut hasher = Sha256::new();
        let mut downloaded: u64 = 0;

        // Stream the response body
        let mut stream = response.bytes_stream();

        while let Some(chunk_result) = stream.next().await {
            let chunk = chunk_result.context("Failed to read HTTP response chunk")?;

            hasher.update(&chunk);
            file.write_all(&chunk).await.context("Failed to write chunk to file")?;

            downloaded += chunk.len() as u64;
            pb.set_position(downloaded);
        }

        pb.finish_with_message("Download complete");

        info!("✅ Downloaded {} ({:.2} MB)", filename, downloaded as f64 / 1_048_576.0);

        // Calculate checksum
        let checksum = format!("{:x}", hasher.finalize());

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

        Ok(())
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

    Ok(format!("{:x}", hasher.finalize()))
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

#[cfg(test)]
mod tests {
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
            LocalFileInfo {
                path: "/tmp/test.xml.gz".to_string(),
                checksum: "abc123".to_string(),
                version: "202412".to_string(),
                size: 1024,
            },
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
            LocalFileInfo {
                path: "/tmp/test.xml.gz".to_string(),
                checksum: "abc123".to_string(),
                version: "202412".to_string(),
                size: 1024,
            },
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

        let file_info = S3FileInfo {
            name: "discogs_20241201_artists.xml.gz".to_string(),
            size: 1024,
        };

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

        let file_info = S3FileInfo {
            name: filename.to_string(),
            size: content.len() as u64,
        };

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

        let file_info = S3FileInfo {
            name: filename.to_string(),
            size: content.len() as u64,
        };

        let should_download = downloader.should_download(&file_info).await.unwrap();
        assert!(!should_download);
    }

    #[test]
    fn test_get_latest_monthly_files_no_complete_set() {
        let temp_dir = TempDir::new().unwrap();
        let downloader = tokio::runtime::Runtime::new()
            .unwrap()
            .block_on(Downloader::new(temp_dir.path().to_path_buf()))
            .unwrap();

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
        let downloader = tokio::runtime::Runtime::new()
            .unwrap()
            .block_on(Downloader::new(temp_dir.path().to_path_buf()))
            .unwrap();

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

    #[test]
    fn test_get_latest_monthly_files_multiple_versions() {
        let temp_dir = TempDir::new().unwrap();
        let downloader = tokio::runtime::Runtime::new()
            .unwrap()
            .block_on(Downloader::new(temp_dir.path().to_path_buf()))
            .unwrap();

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
}
