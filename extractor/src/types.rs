use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fmt;
use std::str::FromStr;

/// Supported data types from Discogs
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum DataType {
    Artists,
    Labels,
    Masters,
    ReleaseGroups,
    Releases,
}

impl DataType {
    /// Get all data types
    #[allow(dead_code)]
    pub fn all() -> Vec<DataType> {
        vec![DataType::Artists, DataType::Labels, DataType::Masters, DataType::ReleaseGroups, DataType::Releases]
    }

    /// Get data types for Discogs extraction (no ReleaseGroups)
    pub fn discogs() -> Vec<DataType> {
        vec![DataType::Artists, DataType::Labels, DataType::Masters, DataType::Releases]
    }

    /// Get data types for MusicBrainz extraction (no Masters)
    pub fn musicbrainz() -> Vec<DataType> {
        vec![DataType::Artists, DataType::Labels, DataType::ReleaseGroups, DataType::Releases]
    }

    /// Get the string representation for file names
    pub fn as_str(&self) -> &'static str {
        match self {
            DataType::Artists => "artists",
            DataType::Labels => "labels",
            DataType::Masters => "masters",
            DataType::ReleaseGroups => "release-groups",
            DataType::Releases => "releases",
        }
    }
}

impl fmt::Display for DataType {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.as_str())
    }
}

impl FromStr for DataType {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.to_lowercase().as_str() {
            "artists" => Ok(DataType::Artists),
            "labels" => Ok(DataType::Labels),
            "masters" => Ok(DataType::Masters),
            "release-groups" => Ok(DataType::ReleaseGroups),
            "releases" => Ok(DataType::Releases),
            _ => Err(format!("Unknown data type: {}", s)),
        }
    }
}

/// Data source for extraction
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Source {
    Discogs,
    MusicBrainz,
}

impl fmt::Display for Source {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Source::Discogs => write!(f, "discogs"),
            Source::MusicBrainz => write!(f, "musicbrainz"),
        }
    }
}

impl FromStr for Source {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.to_lowercase().as_str() {
            "discogs" => Ok(Source::Discogs),
            "musicbrainz" => Ok(Source::MusicBrainz),
            _ => Err(format!("Unknown source: {}", s)),
        }
    }
}

/// Progress tracking for extraction
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ExtractionProgress {
    pub artists: u64,
    pub labels: u64,
    pub masters: u64,
    pub release_groups: u64,
    pub releases: u64,
}

impl ExtractionProgress {
    pub fn increment(&mut self, data_type: DataType) {
        match data_type {
            DataType::Artists => self.artists += 1,
            DataType::Labels => self.labels += 1,
            DataType::Masters => self.masters += 1,
            DataType::ReleaseGroups => self.release_groups += 1,
            DataType::Releases => self.releases += 1,
        }
    }

    #[allow(dead_code)]
    pub fn get(&self, data_type: DataType) -> u64 {
        match data_type {
            DataType::Artists => self.artists,
            DataType::Labels => self.labels,
            DataType::Masters => self.masters,
            DataType::ReleaseGroups => self.release_groups,
            DataType::Releases => self.releases,
        }
    }

    pub fn total(&self) -> u64 {
        self.artists + self.labels + self.masters + self.release_groups + self.releases
    }
}

/// Message types for AMQP
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type")]
pub enum Message {
    #[serde(rename = "data")]
    Data(DataMessage),
    #[serde(rename = "file_complete")]
    FileComplete(FileCompleteMessage),
    #[serde(rename = "extraction_complete")]
    ExtractionComplete(ExtractionCompleteMessage),
}

/// Compute SHA-256 hash of a JSON value's serialized form.
///
/// Used to produce a content hash from the post-filter data so that
/// consumers can detect when the *consumer-facing* payload has changed,
/// even if the upstream source (XML/JSONL) is identical.
pub fn calculate_content_hash(data: &serde_json::Value) -> String {
    let json_str = serde_json::to_string(data).unwrap_or_default();
    let mut hasher = Sha256::new();
    hasher.update(json_str.as_bytes());
    hex::encode(hasher.finalize())
}

/// Data message containing a parsed record
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DataMessage {
    pub id: String,
    pub sha256: String,
    #[serde(flatten)]
    pub data: serde_json::Value,
    /// Raw XML fragment for data quality inspection; never serialized to AMQP
    #[serde(skip)]
    #[allow(dead_code)]
    pub raw_xml: Option<Vec<u8>>,
}

/// File completion message
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FileCompleteMessage {
    pub data_type: String,
    pub timestamp: DateTime<Utc>,
    pub total_processed: u64,
    pub file: String,
}

/// Extraction complete message — sent once after all files finish processing
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExtractionCompleteMessage {
    pub version: String,
    pub timestamp: DateTime<Utc>,
    pub started_at: DateTime<Utc>,
    pub record_counts: std::collections::HashMap<String, u64>,
}

/// File information from S3
#[derive(Debug, Clone)]
pub struct S3FileInfo {
    pub name: String,
    pub size: u64,
}

/// Local file information with metadata
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LocalFileInfo {
    pub path: String,
    pub checksum: String,
    pub version: String,
    pub size: u64,
}

#[cfg(test)]
#[path = "tests/types_tests.rs"]
mod tests;
