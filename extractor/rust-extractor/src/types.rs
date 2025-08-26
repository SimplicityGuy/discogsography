use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
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
    pub fn all() -> Vec<DataType> {
        vec![
            DataType::Artists,
            DataType::Labels,
            DataType::Masters,
            DataType::Releases,
        ]
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

    /// Get the AMQP routing key
    pub fn routing_key(&self) -> &'static str {
        self.as_str()
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

/// Processing state for tracking which files have been processed
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ProcessingState {
    pub files: HashMap<String, bool>,
}

impl ProcessingState {
    pub fn is_processed(&self, file: &str) -> bool {
        self.files.get(file).copied().unwrap_or(false)
    }

    pub fn mark_processed(&mut self, file: &str) {
        self.files.insert(file.to_string(), true);
    }

    pub fn clear(&mut self) {
        self.files.clear();
    }
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
mod tests {
    use super::*;

    #[test]
    fn test_data_type_conversion() {
        assert_eq!(DataType::from_str("artists"), Some(DataType::Artists));
        assert_eq!(DataType::from_str("LABELS"), Some(DataType::Labels));
        assert_eq!(DataType::from_str("unknown"), None);
        assert_eq!(DataType::Artists.as_str(), "artists");
    }

    #[test]
    fn test_extraction_progress() {
        let mut progress = ExtractionProgress::default();
        progress.increment(DataType::Artists);
        progress.increment(DataType::Artists);
        progress.increment(DataType::Labels);

        assert_eq!(progress.get(DataType::Artists), 2);
        assert_eq!(progress.get(DataType::Labels), 1);
        assert_eq!(progress.total(), 3);
    }

    #[test]
    fn test_processing_state() {
        let mut state = ProcessingState::default();
        assert!(!state.is_processed("file1.xml"));

        state.mark_processed("file1.xml");
        assert!(state.is_processed("file1.xml"));

        state.clear();
        assert!(!state.is_processed("file1.xml"));
    }
}
