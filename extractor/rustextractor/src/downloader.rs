use anyhow::{Context, Result};
use aws_config::BehaviorVersion;
use aws_sdk_s3::Client as S3Client;
use chrono::Utc;
use indicatif::{ProgressBar, ProgressStyle};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use tokio::fs::{self, File};
use tokio::io::AsyncWriteExt;
use tracing::{debug, error, info, warn};

use crate::types::{LocalFileInfo, S3FileInfo};

const S3_BUCKET: &str = "discogs-data-dumps";
const S3_PREFIX: &str = "data/";

pub struct Downloader {
    s3_client: S3Client,
    pub output_directory: PathBuf,
    pub metadata: HashMap<String, LocalFileInfo>,
}

impl Downloader {
    pub async fn new(output_directory: PathBuf) -> Result<Self> {
        // Initialize AWS SDK with default configuration (similar to boto3 default)
        let config = aws_config::defaults(BehaviorVersion::latest())
            .region("us-west-2")
            .no_credentials() // Public bucket, no credentials needed
            .load()
            .await;

        let s3_client = S3Client::new(&config);

        let metadata = load_metadata(&output_directory)?;

        Ok(Self { s3_client, output_directory, metadata })
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

        let mut downloaded_files = Vec::new();

        for file_info in &latest_files {
            if self.should_download(file_info).await? {
                match self.download_file(file_info).await {
                    Ok(_) => {
                        let filename = std::path::Path::new(&file_info.name).file_name().and_then(|name| name.to_str()).unwrap_or("unknown_file");
                        info!("✅ Successfully downloaded: {}", filename);
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
                downloaded_files.push(filename.to_string());
            }
        }

        // Save updated metadata
        self.save_metadata()?;

        Ok(downloaded_files)
    }

    async fn list_s3_files(&self) -> Result<Vec<S3FileInfo>> {
        info!("🔍 Listing available files from S3...");

        // Use AWS SDK list_objects_v2 (equivalent to Python's boto3 list_objects_v2)
        let response = self.s3_client.list_objects_v2().bucket(S3_BUCKET).prefix(S3_PREFIX).send().await.context("Failed to list S3 objects")?;

        let objects = response.contents();

        let files: Vec<S3FileInfo> = objects
            .iter()
            .filter_map(|obj| {
                let key = obj.key()?;
                let size = obj.size()? as u64;

                // Filter for XML files and CHECKSUM files (matching Python logic)
                if key.ends_with(".xml.gz") || key.contains("CHECKSUM") {
                    // Store full key like Python does - this is crucial for version grouping
                    Some(S3FileInfo { name: key.to_string(), size })
                } else {
                    None
                }
            })
            .collect();

        info!("Found {} relevant files in S3 bucket after filtering", files.len());
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
            // Compare sizes
            if local_info.size != file_info.size {
                info!("📊 File size changed for {}: {} -> {}", file_info.name, local_info.size, file_info.size);
                return Ok(true);
            }

            // Validate checksum if file exists
            if local_path.exists() {
                let checksum = calculate_file_checksum(&local_path).await?;
                if checksum != local_info.checksum {
                    warn!("⚠️ Checksum mismatch for {}", file_info.name);
                    return Ok(true);
                }
            }

            // File is up to date
            return Ok(false);
        }

        // No metadata, download to be safe
        Ok(true)
    }

    async fn download_file(&mut self, file_info: &S3FileInfo) -> Result<()> {
        // Reconstruct the full S3 key by prepending the prefix
        let s3_key = format!("{}{}", S3_PREFIX, &file_info.name);
        // Extract just the base filename for local storage (remove path components)
        let filename = std::path::Path::new(&file_info.name).file_name().and_then(|name| name.to_str()).unwrap_or("unknown_file");
        let local_path = self.output_directory.join(filename);

        info!("⬇️ Downloading {} ({:.2} MB)...", filename, file_info.size as f64 / 1_048_576.0);

        // Create progress bar
        let pb = ProgressBar::new(file_info.size);
        pb.set_style(
            ProgressStyle::default_bar()
                .template("{spinner:.green} [{elapsed_precise}] [{bar:40.cyan/blue}] {bytes}/{total_bytes} ({eta})")
                .unwrap()
                .progress_chars("=>-"),
        );

        // Download using AWS SDK (equivalent to boto3 download_fileobj)
        let response = self
            .s3_client
            .get_object()
            .bucket(S3_BUCKET)
            .key(&s3_key)
            .send()
            .await
            .with_context(|| format!("Failed to start S3 download for key: {}", s3_key))?;

        let body = response.body.collect().await.context("Failed to read S3 response")?;
        let data = body.into_bytes();

        let mut file = File::create(&local_path).await.context("Failed to create local file")?;

        let mut hasher = Sha256::new();
        hasher.update(&data);

        file.write_all(&data).await.context("Failed to write file")?;

        pb.set_position(data.len() as u64);

        pb.finish_with_message("Download complete");

        // Calculate checksum
        let checksum = format!("{:x}", hasher.finalize());

        // Update metadata
        self.metadata.insert(
            filename.to_string(),
            LocalFileInfo {
                path: local_path.to_string_lossy().to_string(),
                checksum,
                version: extract_month_from_filename(filename),
                size: file_info.size,
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

        // This will attempt to connect to AWS (in no-credentials mode for public bucket)
        // It should succeed in creating the downloader
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

        let actual_checksum = calculate_file_checksum(&local_path).await.unwrap();

        // Add metadata with wrong checksum
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
