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
    output_directory: PathBuf,
    metadata: HashMap<String, LocalFileInfo>,
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
                        let filename = std::path::Path::new(&file_info.name).file_name()
                            .and_then(|name| name.to_str())
                            .unwrap_or("unknown_file");
                        info!("✅ Successfully downloaded: {}", filename);
                        downloaded_files.push(filename.to_string());
                    }
                    Err(e) => {
                        let filename = std::path::Path::new(&file_info.name).file_name()
                            .and_then(|name| name.to_str())
                            .unwrap_or("unknown_file");
                        error!("❌ Failed to download {}: {}", filename, e);
                    }
                }
            } else {
                let filename = std::path::Path::new(&file_info.name).file_name()
                    .and_then(|name| name.to_str())
                    .unwrap_or("unknown_file");
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

        debug!("Found {} total objects in S3 bucket", objects.len());

        // Debug: Log sample S3 object keys (similar to Python logging)
        for (i, obj) in objects.iter().enumerate() {
            if (i < 5 || i >= objects.len() - 5)
                && let (Some(key), Some(size)) = (obj.key(), obj.size())
            {
                debug!("  Object {}: Key: {}, Size: {}", i, key, size);
            }
        }

        let files: Vec<S3FileInfo> = objects
            .iter()
            .filter_map(|obj| {
                let key = obj.key()?;
                let size = obj.size()? as u64;

                // Filter for XML files and CHECKSUM files (matching Python logic)
                if key.ends_with(".xml.gz") || key.contains("CHECKSUM") {
                    // Store full key like Python does - this is crucial for version grouping
                    debug!("Including file: {} (size: {})", key, size);
                    Some(S3FileInfo { name: key.to_string(), size })
                } else {
                    None
                }
            })
            .collect();

        info!("Found {} relevant files in S3 bucket after filtering", files.len());
        Ok(files)
    }

    fn get_latest_monthly_files(&self, files: &[S3FileInfo]) -> Result<Vec<S3FileInfo>> {
        // Group files by their ID (date part like "20250801") - matching Python logic
        let mut ids: std::collections::HashMap<String, Vec<S3FileInfo>> = std::collections::HashMap::new();

        for file in files {
            debug!("Processing file: {}", file.name);
            // Split the full S3 key exactly like Python does
            let parts: Vec<&str> = file.name.split('_').collect();
            debug!("Split parts: {:?}", parts);
            if parts.len() >= 2 {
                let id = parts[1].to_string();
                debug!("Found version ID: {}", id);
                ids.entry(id).or_default().push(file.clone());
            } else {
                debug!("Skipping file (invalid format): {}", file.name);
            }
        }

        info!("Found {} unique version IDs", ids.len());
        for (id, files) in &ids {
            info!("  Version {}: {} files", id, files.len());
            for file in files {
                info!("    - {}", file.name);
            }
        }

        // Get the most recent version (sorted in reverse order)
        let mut sorted_ids: Vec<_> = ids.keys().collect();
        sorted_ids.sort_by(|a, b| b.cmp(a));

        for id in sorted_ids {
            let files_for_id = ids.get(id).unwrap();
            info!("Checking version {}: {} files", id, files_for_id.len());

            // Check if we have a complete set - exactly like Python logic
            // Python requires exactly 5 files total (1 CHECKSUM + 4 data files)
            info!("Version {} has {} total files", id, files_for_id.len());

            if files_for_id.len() != 5 {
                info!("Skipping version {} - has {} files, need exactly 5", id, files_for_id.len());
                continue;
            }

            // Only return data files (not CHECKSUM) for processing, with filename only
            let data_files: Vec<_> = files_for_id
                .iter()
                .filter(|f| f.name.ends_with(".xml.gz"))
                .map(|f| {
                    let filename = f.name.strip_prefix(S3_PREFIX).unwrap_or(&f.name);
                    S3FileInfo {
                        name: filename.to_string(),
                        size: f.size,
                    }
                })
                .collect();

            debug!("Version {} has {} data files", id, data_files.len());

            if data_files.len() == 4 {  // We expect exactly 4 data files
                info!("📅 Using version {} with {} data files", id, data_files.len());
                return Ok(data_files);
            }
        }

        warn!("No complete version found with all expected data files");
        Ok(Vec::new())
    }

    async fn should_download(&self, file_info: &S3FileInfo) -> Result<bool> {
        // Extract just the base filename for local checks
        let filename = std::path::Path::new(&file_info.name).file_name()
            .and_then(|name| name.to_str())
            .unwrap_or("unknown_file");
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
        let s3_key = &file_info.name;  // file_info.name is already the full S3 key
        // Extract just the base filename for local storage (remove path components)
        let filename = std::path::Path::new(&file_info.name).file_name()
            .and_then(|name| name.to_str())
            .unwrap_or("unknown_file");
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
        debug!("Attempting to download S3 object: bucket={}, key={}", S3_BUCKET, s3_key);
        let response = self.s3_client.get_object().bucket(S3_BUCKET).key(s3_key).send().await
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

    fn save_metadata(&self) -> Result<()> {
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

    #[test]
    fn test_extract_month() {
        assert_eq!(extract_month_from_filename("discogs_20241201_artists.xml.gz"), "202412");
        assert_eq!(extract_month_from_filename("discogs_20240115_labels.xml.gz"), "202401");
    }
}
