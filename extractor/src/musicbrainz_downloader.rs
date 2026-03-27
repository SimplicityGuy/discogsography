use anyhow::{Context, Result};
use std::collections::HashMap;
use std::io;
use std::path::{Path, PathBuf};
use tracing::{debug, info, warn};

use crate::types::DataType;

/// Known file name patterns for MusicBrainz JSONL dump files.
/// Each entry maps a DataType to a list of candidate file-name patterns.
const MB_FILE_PATTERNS: &[(DataType, &[&str])] = &[
    (DataType::Artists, &["artist.jsonl.xz", "mbdump-artist.jsonl.xz", "artist.jsonl"]),
    (DataType::Labels, &["label.jsonl.xz", "mbdump-label.jsonl.xz", "label.jsonl"]),
    (DataType::Releases, &["release.jsonl.xz", "mbdump-release.jsonl.xz", "release.jsonl"]),
];

/// Entity name used for fuzzy matching when none of the exact patterns hit.
fn entity_keyword(dt: DataType) -> &'static str {
    match dt {
        DataType::Artists => "artist",
        DataType::Labels => "label",
        DataType::Releases => "release",
        DataType::Masters => "master",
    }
}

/// Discover available MusicBrainz JSONL dump files in the given directory.
/// Returns a map of DataType -> file path for each found dump file.
pub fn discover_mb_dump_files(root: &Path) -> Result<HashMap<DataType, PathBuf>> {
    let mut found: HashMap<DataType, PathBuf> = HashMap::new();

    // `root` comes from operator-controlled config (CLI/env var), not HTTP input.
    let entries: Vec<_> = match std::fs::read_dir(root) { // nosemgrep: rust.actix.path-traversal.tainted-path.tainted-path
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
                if name_str.contains(keyword) && (name_str.ends_with(".jsonl.xz") || name_str.ends_with(".jsonl")) {
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
const MB_ENTITIES: &[&str] = &["artist", "label", "release"];

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

/// Parse version directory names (YYYYMMDD-HHMMSS) from an HTML index page.
/// Returns them sorted descending (most recent first).
#[allow(dead_code)]
pub fn parse_version_directories(html: &str) -> Vec<String> {
    let pattern = regex::Regex::new(r#"href="(\d{8}-\d{6})/?"#).unwrap();
    let mut versions: Vec<String> = pattern
        .captures_iter(html)
        .filter_map(|cap| cap.get(1).map(|m| m.as_str().to_string()))
        .collect();
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
            io::copy(&mut entry, &mut out_file)
                .with_context(|| format!("Failed to extract {} to {:?}", entity, out_path))?;
            let size = out_file.metadata().map(|m| m.len()).unwrap_or(0);
            info!("📋 Extracted {} from {:?} ({} bytes)", entity, tar_path, size);
            return Ok(());
        }
    }

    Err(anyhow::anyhow!("Entry '{}' not found in {:?}", target_suffix, tar_path))
}

#[cfg(test)]
#[path = "tests/musicbrainz_downloader_tests.rs"]
mod tests;
