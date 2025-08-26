use anyhow::{Context, Result};
use flate2::read::GzDecoder;
use quick_xml::events::Event;
use quick_xml::Reader;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
// use std::collections::HashMap; // Not currently needed
use std::fs::File;
use std::io::BufReader;
use std::path::Path;
use tokio::sync::mpsc;
use tracing::{debug, error, warn};

use crate::types::{DataMessage, DataType};

pub struct XmlParser {
    data_type: DataType,
    sender: mpsc::Sender<DataMessage>,
}

impl XmlParser {
    pub fn new(data_type: DataType, sender: mpsc::Sender<DataMessage>) -> Self {
        Self { data_type, sender }
    }

    pub async fn parse_file(&self, file_path: &Path) -> Result<u64> {
        let file =
            File::open(file_path).context(format!("Failed to open file: {:?}", file_path))?;

        let decoder = GzDecoder::new(file);
        let buf_reader = BufReader::new(decoder);

        let mut reader = Reader::from_reader(buf_reader);
        // Note: trim_text and expand_empty_elements are configured differently in newer quick-xml versions
        // The default behavior should work for our use case

        let mut buf = Vec::new();
        let mut current_element = String::new();
        let mut current_record: Option<Value> = None;
        let mut text_content = String::new();
        let mut record_count = 0u64;
        let mut in_target_element = false;
        let mut element_stack = Vec::new();

        // Determine the target element based on data type
        let target_element = match self.data_type {
            DataType::Artists => "artist",
            DataType::Labels => "label",
            DataType::Masters => "master",
            DataType::Releases => "release",
        };

        let container_element = format!("{}s", target_element);

        loop {
            match reader.read_event_into(&mut buf) {
                Ok(Event::Start(e)) => {
                    let name = String::from_utf8_lossy(e.name().as_ref()).to_string();
                    element_stack.push(name.clone());

                    if name == target_element && element_stack.len() == 2 {
                        // Start of a new record
                        in_target_element = true;
                        current_record = Some(json!({}));

                        // Parse attributes
                        for attr in e.attributes() {
                            if let Ok(attr) = attr {
                                let key = String::from_utf8_lossy(attr.key.as_ref()).to_string();
                                let value = String::from_utf8_lossy(&attr.value).to_string();

                                if key == "id" {
                                    if let Some(ref mut record) = current_record {
                                        record["id"] = json!(value);
                                    }
                                }
                            }
                        }
                    }

                    current_element = name;
                    text_content.clear();
                }

                Ok(Event::End(e)) => {
                    let name = String::from_utf8_lossy(e.name().as_ref()).to_string();

                    if in_target_element && !text_content.is_empty() {
                        // Process the collected text content
                        let trimmed = text_content.trim();
                        if !trimmed.is_empty() {
                            if let Some(ref mut record) = current_record {
                                self.add_field_to_record(record, &current_element, trimmed);
                            }
                        }
                    }

                    if name == target_element && element_stack.len() == 2 {
                        // End of record, send it
                        if let Some(mut record) = current_record.take() {
                            record_count += 1;

                            // Calculate SHA256 hash
                            let sha256 = calculate_record_hash(&record);

                            // Extract ID
                            let id = record["id"].as_str().unwrap_or("unknown").to_string();

                            // Create message
                            let message = DataMessage {
                                id: id.clone(),
                                sha256,
                                data: record,
                            };

                            // Send message
                            if self.sender.send(message).await.is_err() {
                                warn!("⚠️ Receiver dropped, stopping parsing");
                                break;
                            }

                            // Log progress periodically
                            if record_count % 1000 == 0 {
                                debug!("📊 Parsed {} {} records", record_count, self.data_type);
                            }
                        }
                        in_target_element = false;
                    }

                    element_stack.pop();
                    text_content.clear();
                }

                Ok(Event::Text(e)) => {
                    if in_target_element {
                        text_content.push_str(&e.unescape().unwrap_or_default());
                    }
                }

                Ok(Event::CData(e)) => {
                    if in_target_element {
                        text_content.push_str(&String::from_utf8_lossy(&e));
                    }
                }

                Ok(Event::Eof) => break,

                Err(e) => {
                    error!(
                        "❌ Error parsing XML at position {}: {}",
                        reader.buffer_position(),
                        e
                    );
                    return Err(e.into());
                }

                _ => {} // Ignore other events
            }

            buf.clear();
        }

        debug!(
            "✅ Finished parsing {} records from {:?}",
            record_count, file_path
        );
        Ok(record_count)
    }

    fn add_field_to_record(&self, record: &mut Value, field_name: &str, value: &str) {
        // Handle special fields based on data type
        match self.data_type {
            DataType::Artists => {
                match field_name {
                    "name" | "realname" | "profile" | "data_quality" => {
                        record[field_name] = json!(value);
                    }
                    "namevariations" | "aliases" | "groups" | "members" => {
                        // These are typically arrays in the original data
                        if !record[field_name].is_array() {
                            record[field_name] = json!([]);
                        }
                        if let Some(arr) = record[field_name].as_array_mut() {
                            arr.push(json!(value));
                        }
                    }
                    "urls" => {
                        if !record["urls"].is_array() {
                            record["urls"] = json!([]);
                        }
                        if let Some(arr) = record["urls"].as_array_mut() {
                            arr.push(json!(value));
                        }
                    }
                    _ => {
                        record[field_name] = json!(value);
                    }
                }
            }
            DataType::Labels => match field_name {
                "name" | "profile" | "contactinfo" | "data_quality" => {
                    record[field_name] = json!(value);
                }
                "sublabels" | "urls" => {
                    if !record[field_name].is_array() {
                        record[field_name] = json!([]);
                    }
                    if let Some(arr) = record[field_name].as_array_mut() {
                        arr.push(json!(value));
                    }
                }
                _ => {
                    record[field_name] = json!(value);
                }
            },
            DataType::Masters => match field_name {
                "title" | "main_release" | "year" | "notes" | "data_quality" => {
                    record[field_name] = json!(value);
                }
                "artists" | "genres" | "styles" | "videos" => {
                    if !record[field_name].is_array() {
                        record[field_name] = json!([]);
                    }
                    if let Some(arr) = record[field_name].as_array_mut() {
                        arr.push(json!(value));
                    }
                }
                _ => {
                    record[field_name] = json!(value);
                }
            },
            DataType::Releases => match field_name {
                "title" | "released" | "country" | "notes" | "data_quality" | "master_id" => {
                    record[field_name] = json!(value);
                }
                "artists" | "labels" | "formats" | "genres" | "styles" | "tracklist"
                | "identifiers" | "videos" | "companies" => {
                    if !record[field_name].is_array() {
                        record[field_name] = json!([]);
                    }
                    if let Some(arr) = record[field_name].as_array_mut() {
                        arr.push(json!(value));
                    }
                }
                _ => {
                    record[field_name] = json!(value);
                }
            },
        }
    }
}

fn calculate_record_hash(record: &Value) -> String {
    let json_str = serde_json::to_string(record).unwrap_or_default();
    let mut hasher = Sha256::new();
    hasher.update(json_str.as_bytes());
    format!("{:x}", hasher.finalize())
}

#[cfg(test)]
mod tests {
    use super::*;
    use flate2::write::GzEncoder;
    use flate2::Compression;
    use std::io::Write;
    use tempfile::NamedTempFile;

    #[tokio::test]
    async fn test_parse_simple_xml() {
        let xml_content = r#"<?xml version="1.0" encoding="UTF-8"?>
<artists>
    <artist id="1">
        <name>Test Artist</name>
        <profile>Test profile</profile>
    </artist>
</artists>"#;

        // Create a temporary gzipped file
        let mut temp_file = NamedTempFile::new().unwrap();
        let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
        encoder.write_all(xml_content.as_bytes()).unwrap();
        let compressed = encoder.finish().unwrap();
        temp_file.write_all(&compressed).unwrap();
        temp_file.flush().unwrap();

        // Create channel for receiving parsed records
        let (sender, mut receiver) = mpsc::channel(10);

        // Parse the file
        let parser = XmlParser::new(DataType::Artists, sender);
        let count = parser.parse_file(temp_file.path()).await.unwrap();

        assert_eq!(count, 1);

        // Check the parsed record
        let message = receiver.recv().await.unwrap();
        assert_eq!(message.id, "1");
        assert_eq!(message.data["name"], json!("Test Artist"));
        assert_eq!(message.data["profile"], json!("Test profile"));
    }
}
