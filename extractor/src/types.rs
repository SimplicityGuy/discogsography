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
    #[allow(dead_code)]
    pub fn is_processed(&self, file: &str) -> bool {
        self.files.get(file).copied().unwrap_or(false)
    }

    #[allow(dead_code)]
    pub fn mark_processed(&mut self, file: &str) {
        self.files.insert(file.to_string(), true);
    }

    #[allow(dead_code)]
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
        assert_eq!(DataType::from_str("artists"), Ok(DataType::Artists));
        assert_eq!(DataType::from_str("LABELS"), Ok(DataType::Labels));
        assert!(DataType::from_str("unknown").is_err());
        assert_eq!(DataType::Artists.as_str(), "artists");
    }

    #[test]
    fn test_data_type_all_types() {
        assert_eq!(DataType::from_str("artists"), Ok(DataType::Artists));
        assert_eq!(DataType::from_str("labels"), Ok(DataType::Labels));
        assert_eq!(DataType::from_str("masters"), Ok(DataType::Masters));
        assert_eq!(DataType::from_str("releases"), Ok(DataType::Releases));
    }

    #[test]
    fn test_data_type_case_insensitive() {
        assert_eq!(DataType::from_str("ARTISTS"), Ok(DataType::Artists));
        assert_eq!(DataType::from_str("Artists"), Ok(DataType::Artists));
        assert_eq!(DataType::from_str("aRtIsTs"), Ok(DataType::Artists));
    }

    #[test]
    fn test_data_type_invalid() {
        assert!(DataType::from_str("invalid").is_err());
        assert!(DataType::from_str("").is_err());
        assert!(DataType::from_str("artist").is_err()); // singular
    }

    #[test]
    fn test_data_type_as_str() {
        assert_eq!(DataType::Artists.as_str(), "artists");
        assert_eq!(DataType::Labels.as_str(), "labels");
        assert_eq!(DataType::Masters.as_str(), "masters");
        assert_eq!(DataType::Releases.as_str(), "releases");
    }

    #[test]
    fn test_data_type_routing_key() {
        assert_eq!(DataType::Artists.routing_key(), "artists");
        assert_eq!(DataType::Labels.routing_key(), "labels");
        assert_eq!(DataType::Masters.routing_key(), "masters");
        assert_eq!(DataType::Releases.routing_key(), "releases");
    }

    #[test]
    fn test_data_type_display() {
        assert_eq!(format!("{}", DataType::Artists), "artists");
        assert_eq!(format!("{}", DataType::Labels), "labels");
        assert_eq!(format!("{}", DataType::Masters), "masters");
        assert_eq!(format!("{}", DataType::Releases), "releases");
    }

    #[test]
    fn test_data_type_all() {
        let all = DataType::all();
        assert_eq!(all.len(), 4);
        assert!(all.contains(&DataType::Artists));
        assert!(all.contains(&DataType::Labels));
        assert!(all.contains(&DataType::Masters));
        assert!(all.contains(&DataType::Releases));
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
    fn test_extraction_progress_all_types() {
        let mut progress = ExtractionProgress::default();
        progress.increment(DataType::Artists);
        progress.increment(DataType::Labels);
        progress.increment(DataType::Masters);
        progress.increment(DataType::Releases);

        assert_eq!(progress.get(DataType::Artists), 1);
        assert_eq!(progress.get(DataType::Labels), 1);
        assert_eq!(progress.get(DataType::Masters), 1);
        assert_eq!(progress.get(DataType::Releases), 1);
        assert_eq!(progress.total(), 4);
    }

    #[test]
    fn test_extraction_progress_default() {
        let progress = ExtractionProgress::default();
        assert_eq!(progress.artists, 0);
        assert_eq!(progress.labels, 0);
        assert_eq!(progress.masters, 0);
        assert_eq!(progress.releases, 0);
        assert_eq!(progress.total(), 0);
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

    #[test]
    fn test_processing_state_multiple_files() {
        let mut state = ProcessingState::default();
        state.mark_processed("file1.xml");
        state.mark_processed("file2.xml");
        state.mark_processed("file3.xml");

        assert!(state.is_processed("file1.xml"));
        assert!(state.is_processed("file2.xml"));
        assert!(state.is_processed("file3.xml"));
        assert!(!state.is_processed("file4.xml"));
        assert_eq!(state.files.len(), 3);
    }

    #[test]
    fn test_processing_state_default() {
        let state = ProcessingState::default();
        assert!(state.files.is_empty());
    }

    #[test]
    fn test_message_serialization() {
        let data_msg = DataMessage { id: "123".to_string(), sha256: "abc".to_string(), data: serde_json::json!({"test": "value"}) };

        let serialized = serde_json::to_string(&data_msg).unwrap();
        let deserialized: DataMessage = serde_json::from_str(&serialized).unwrap();

        assert_eq!(deserialized.id, "123");
        assert_eq!(deserialized.sha256, "abc");
    }

    #[test]
    fn test_file_complete_message() {
        let msg =
            FileCompleteMessage { data_type: "artists".to_string(), timestamp: Utc::now(), total_processed: 1000, file: "test.xml".to_string() };

        assert_eq!(msg.data_type, "artists");
        assert_eq!(msg.total_processed, 1000);
        assert_eq!(msg.file, "test.xml");
    }

    #[test]
    fn test_message_enum_data() {
        let data_msg = DataMessage { id: "1".to_string(), sha256: "hash".to_string(), data: serde_json::json!({}) };

        let message = Message::Data(data_msg);
        match message {
            Message::Data(msg) => assert_eq!(msg.id, "1"),
            _ => panic!("Expected Data variant"),
        }
    }

    #[test]
    fn test_message_enum_file_complete() {
        let file_msg =
            FileCompleteMessage { data_type: "labels".to_string(), timestamp: Utc::now(), total_processed: 500, file: "test.xml".to_string() };

        let message = Message::FileComplete(file_msg);
        match message {
            Message::FileComplete(msg) => assert_eq!(msg.total_processed, 500),
            _ => panic!("Expected FileComplete variant"),
        }
    }
}
