use anyhow::Result;
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use tracing::{debug, info, warn};

use crate::types::DataType;

/// Known file name patterns for MusicBrainz JSONL dump files.
/// Each entry maps a DataType to a list of candidate file-name patterns.
const MB_FILE_PATTERNS: &[(DataType, &[&str])] = &[
    (DataType::Artists, &["artist.jsonl.xz", "mbdump-artist.jsonl.xz"]),
    (DataType::Labels, &["label.jsonl.xz", "mbdump-label.jsonl.xz"]),
    (DataType::Releases, &["release.jsonl.xz", "mbdump-release.jsonl.xz"]),
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
                if name_str.contains(keyword) && name_str.ends_with(".jsonl.xz") {
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

#[cfg(test)]
#[path = "tests/musicbrainz_downloader_tests.rs"]
mod tests;
