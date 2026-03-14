use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::fmt;
use std::str::FromStr;

/// Supported data types from Discogs
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum DataType {
    Artists,
    Labels,
    Masters,
    Releases,
}

impl DataType {
    /// Get all data types
    #[allow(dead_code)]
    pub fn all() -> Vec<DataType> {
        vec![DataType::Artists, DataType::Labels, DataType::Masters, DataType::Releases]
    }

    /// Get the string representation for file names
    pub fn as_str(&self) -> &'static str {
        match self {
            DataType::Artists => "artists",
            DataType::Labels => "labels",
            DataType::Masters => "masters",
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
            "releases" => Ok(DataType::Releases),
            _ => Err(format!("Unknown data type: {}", s)),
        }
    }
}

/// Progress tracking for extraction
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ExtractionProgress {
    pub artists: u64,
    pub labels: u64,
    pub masters: u64,
    pub releases: u64,
}

impl ExtractionProgress {
    pub fn increment(&mut self, data_type: DataType) {
        match data_type {
            DataType::Artists => self.artists += 1,
            DataType::Labels => self.labels += 1,
            DataType::Masters => self.masters += 1,
            DataType::Releases => self.releases += 1,
        }
    }

    #[allow(dead_code)]
    pub fn get(&self, data_type: DataType) -> u64 {
        match data_type {
            DataType::Artists => self.artists,
            DataType::Labels => self.labels,
            DataType::Masters => self.masters,
            DataType::Releases => self.releases,
        }
    }

    pub fn total(&self) -> u64 {
        self.artists + self.labels + self.masters + self.releases
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

/// Data message containing a parsed record
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DataMessage {
    pub id: String,
    pub sha256: String,
    #[serde(flatten)]
    pub data: serde_json::Value,
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
