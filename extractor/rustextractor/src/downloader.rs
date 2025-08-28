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
                        info!("✅ Successfully downloaded: {}", file_info.name);
                        downloaded_files.push(file_info.name.clone());
                    }
                    Err(e) => {
                        error!("❌ Failed to download {}: {}", file_info.name, e);
                    }
                }
            } else {
                info!("✅ Already have latest version of: {}", file_info.name);
                downloaded_files.push(file_info.name.clone());
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
                    // Strip data/ prefix to get filename only (matching Python behavior)
                    let name = key.strip_prefix(S3_PREFIX).unwrap_or(key).to_string();
                    debug!("Including file: {} (size: {})", name, size);
                    Some(S3FileInfo { name, size })
                } else {
                    None
                }
            })
            .collect();

        info!("Found {} relevant files in S3 bucket after filtering", files.len());
        Ok(files)
    }

    fn get_latest_monthly_files(&self, files: &[S3FileInfo]) -> Result<Vec<S3FileInfo>> {
        // Filter for monthly dumps (format: discogs_YYYYMMDD_datatype.xml.gz)
        let mut monthly_files: Vec<_> = files
            .iter()
            .filter(|f| f.name.starts_with("discogs_") && f.name.contains('_') && !f.name.contains("CHECKSUM"))
            .cloned()
            .collect();

        if monthly_files.is_empty() {
            return Ok(Vec::new());
        }

        // Sort by date (embedded in filename)
        monthly_files.sort_by(|a, b| b.name.cmp(&a.name));

        // Get the latest month
        let latest_month = extract_month_from_filename(&monthly_files[0].name);

        // Filter for all files from the latest month
        let latest_files: Vec<_> = monthly_files.into_iter().filter(|f| extract_month_from_filename(&f.name) == latest_month).collect();

        Ok(latest_files)
    }

    async fn should_download(&self, file_info: &S3FileInfo) -> Result<bool> {
        let local_path = self.output_directory.join(&file_info.name);

        // Check if file exists locally
        if !local_path.exists() {
            return Ok(true);
        }

        // Check metadata
        if let Some(local_info) = self.metadata.get(&file_info.name) {
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
        let s3_key = format!("{}{}", S3_PREFIX, file_info.name);
        let local_path = self.output_directory.join(&file_info.name);

        info!("⬇️ Downloading {} ({:.2} MB)...", file_info.name, file_info.size as f64 / 1_048_576.0);

        // Create progress bar
        let pb = ProgressBar::new(file_info.size);
        pb.set_style(
            ProgressStyle::default_bar()
                .template("{spinner:.green} [{elapsed_precise}] [{bar:40.cyan/blue}] {bytes}/{total_bytes} ({eta})")
                .unwrap()
                .progress_chars("=>-"),
        );

        // Download using AWS SDK (equivalent to boto3 download_fileobj)
        let response = self.s3_client.get_object().bucket(S3_BUCKET).key(&s3_key).send().await.context("Failed to start S3 download")?;

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
            file_info.name.clone(),
            LocalFileInfo {
                path: local_path.to_string_lossy().to_string(),
                checksum,
                version: extract_month_from_filename(&file_info.name),
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
