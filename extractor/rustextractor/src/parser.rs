use anyhow::{Context, Result};
use flate2::read::GzDecoder;
use quick_xml::Reader;
use quick_xml::events::Event;
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use std::fs::File;
use std::io::BufReader;
use std::path::Path;
use tokio::sync::mpsc;
use tracing::{debug, error, warn};

use crate::types::{DataMessage, DataType};

/// Represents an element being parsed with its attributes and children
#[derive(Debug)]
struct ElementContext {
    attributes: Map<String, Value>,
    children: Map<String, Value>,
    text_content: String,
}

impl ElementContext {
    fn new() -> Self {
        Self {
            attributes: Map::new(),
            children: Map::new(),
            text_content: String::new(),
        }
    }

    /// Convert this element to a JSON value, combining attributes, text, and children
    fn to_value(self) -> Value {
        let mut result = Map::new();

        // Add attributes with @ prefix (matching xmltodict behavior exactly)
        for (key, value) in self.attributes {
            result.insert(format!("@{}", key), value);
        }

        // If there's only text content and no children, return just the text or combine with attributes
        let trimmed_text = self.text_content.trim();
        if self.children.is_empty() {
            if result.is_empty() && !trimmed_text.is_empty() {
                // Just text content, return as string
                return Value::String(trimmed_text.to_string());
            } else if !trimmed_text.is_empty() {
                // Has attributes and text, use #text for the text content
                result.insert("#text".to_string(), Value::String(trimmed_text.to_string()));
            }
        }

        // Add children
        for (key, value) in self.children {
            result.insert(key, value);
        }

        if result.is_empty() && !trimmed_text.is_empty() {
            Value::String(trimmed_text.to_string())
        } else if result.is_empty() {
            Value::Null
        } else {
            Value::Object(result)
        }
    }

    /// Add a child element, handling the case where multiple children have the same name
    fn add_child(&mut self, child_name: String, child_value: Value) {
        if let Some(existing) = self.children.get_mut(&child_name) {
            // Already have a child with this name, convert to or append to array
            match existing {
                Value::Array(arr) => {
                    arr.push(child_value);
                }
                _ => {
                    // Convert single value to array
                    let old_value = existing.take();
                    *existing = Value::Array(vec![old_value, child_value]);
                }
            }
        } else {
            // First child with this name
            self.children.insert(child_name, child_value);
        }
    }
}

pub struct XmlParser {
    data_type: DataType,
    sender: mpsc::Sender<DataMessage>,
}

impl XmlParser {
    pub fn new(data_type: DataType, sender: mpsc::Sender<DataMessage>) -> Self {
        Self { data_type, sender }
    }

    pub async fn parse_file(&self, file_path: &Path) -> Result<u64> {
        let file = File::open(file_path).context(format!("Failed to open file: {:?}", file_path))?;

        let decoder = GzDecoder::new(file);
        let buf_reader = BufReader::new(decoder);

        let mut reader = Reader::from_reader(buf_reader);

        let mut buf = Vec::new();
        let mut record_count = 0u64;
        let mut in_target_element = false;

        // Stack of element contexts for building nested structure
        let mut element_stack: Vec<ElementContext> = Vec::new();
        // Track depth in the overall document
        let mut depth = 0usize;

        // Determine the target element based on data type
        let target_element = match self.data_type {
            DataType::Artists => "artist",
            DataType::Labels => "label",
            DataType::Masters => "master",
            DataType::Releases => "release",
        };

        loop {
            match reader.read_event_into(&mut buf) {
                Ok(Event::Start(e)) => {
                    let name = String::from_utf8_lossy(e.name().as_ref()).to_string();
                    depth += 1;

                    if name == target_element && depth == 2 {
                        // Start of a new record at depth 2 (inside container like <artists>)
                        in_target_element = true;
                        element_stack.clear();
                    }

                    if in_target_element {
                        // Create new element context
                        let mut context = ElementContext::new();

                        // Parse all attributes
                        for attr in e.attributes().flatten() {
                            let key = String::from_utf8_lossy(attr.key.as_ref()).to_string();
                            let value = String::from_utf8_lossy(&attr.value).to_string();
                            context.attributes.insert(key, Value::String(value));
                        }

                        element_stack.push(context);
                    }
                }

                Ok(Event::Empty(e)) => {
                    // Self-closing element like <artist id="123" />
                    let name = String::from_utf8_lossy(e.name().as_ref()).to_string();
                    depth += 1;

                    if name == target_element && depth == 2 {
                        // Self-closing target element (unlikely but handle it)
                        element_stack.clear();

                        let mut context = ElementContext::new();
                        for attr in e.attributes().flatten() {
                            let key = String::from_utf8_lossy(attr.key.as_ref()).to_string();
                            let value = String::from_utf8_lossy(&attr.value).to_string();
                            context.attributes.insert(key, Value::String(value));
                        }

                        // Send immediately since it's self-closing
                        let record = context.to_value();
                        if let Value::Object(ref obj) = record {
                            let id = obj.get("id")
                                .and_then(|v| v.as_str())
                                .unwrap_or("unknown")
                                .to_string();
                            let sha256 = calculate_record_hash(&record);
                            let message = DataMessage { id, sha256, data: record.clone() };

                            if self.sender.send(message).await.is_err() {
                                warn!("⚠️ Receiver dropped, stopping parsing");
                                break;
                            }
                            record_count += 1;
                        }

                        in_target_element = false;
                    } else if in_target_element {
                        // Self-closing child element
                        let mut context = ElementContext::new();
                        for attr in e.attributes().flatten() {
                            let key = String::from_utf8_lossy(attr.key.as_ref()).to_string();
                            let value = String::from_utf8_lossy(&attr.value).to_string();
                            context.attributes.insert(key, Value::String(value));
                        }

                        let child_value = context.to_value();

                        // Add to parent if we have one
                        if let Some(parent) = element_stack.last_mut() {
                            parent.add_child(name, child_value);
                        }
                    }

                    depth -= 1;
                }

                Ok(Event::End(e)) => {
                    let name = String::from_utf8_lossy(e.name().as_ref()).to_string();

                    if in_target_element {
                        if let Some(context) = element_stack.pop() {
                            let element_value = context.to_value();

                            if name == target_element && depth == 2 {
                                // End of record, send it
                                if let Value::Object(obj) = element_value {
                                    // Get ID - try @id first (attribute), then id (child element)
                                    let id = obj.get("@id")
                                        .or_else(|| obj.get("id"))
                                        .and_then(|v| v.as_str())
                                        .unwrap_or("unknown")
                                        .to_string();

                                    // For releases and masters, pyextractor adds a plain 'id' field
                                    // in addition to @id (see pyextractor.py line 536)
                                    let mut final_obj = obj;
                                    if matches!(self.data_type, DataType::Releases | DataType::Masters) {
                                        if final_obj.get("@id").is_some() && final_obj.get("id").is_none() {
                                            final_obj.insert("id".to_string(), Value::String(id.clone()));
                                        }
                                    }

                                    let final_value = Value::Object(final_obj);
                                    let sha256 = calculate_record_hash(&final_value);
                                    let message = DataMessage {
                                        id: id.clone(),
                                        sha256,
                                        data: final_value,
                                    };

                                    if self.sender.send(message).await.is_err() {
                                        warn!("⚠️ Receiver dropped, stopping parsing");
                                        break;
                                    }

                                    record_count += 1;
                                    if record_count % 1000 == 0 {
                                        debug!("📊 Parsed {} {} records", record_count, self.data_type);
                                    }
                                }

                                in_target_element = false;
                            } else {
                                // End of child element, add to parent
                                if let Some(parent) = element_stack.last_mut() {
                                    parent.add_child(name, element_value);
                                }
                            }
                        }
                    }

                    depth -= 1;
                }

                Ok(Event::Text(e)) => {
                    if in_target_element {
                        if let Some(context) = element_stack.last_mut() {
                            context.text_content.push_str(&e.unescape().unwrap_or_default());
                        }
                    }
                }

                Ok(Event::CData(e)) => {
                    if in_target_element {
                        if let Some(context) = element_stack.last_mut() {
                            context.text_content.push_str(&String::from_utf8_lossy(&e));
                        }
                    }
                }

                Ok(Event::Eof) => break,

                Err(e) => {
                    error!("❌ Error parsing XML at position {}: {}", reader.buffer_position(), e);
                    return Err(e.into());
                }

                _ => {} // Ignore other events (comments, declarations, etc.)
            }

            buf.clear();
        }

        debug!("✅ Finished parsing {} records from {:?}", record_count, file_path);
        Ok(record_count)
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
    use flate2::Compression;
    use flate2::write::GzEncoder;
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

        let mut temp_file = NamedTempFile::new().unwrap();
        let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
        encoder.write_all(xml_content.as_bytes()).unwrap();
        let compressed = encoder.finish().unwrap();
        temp_file.write_all(&compressed).unwrap();
        temp_file.flush().unwrap();

        let (sender, mut receiver) = mpsc::channel(10);
        let parser = XmlParser::new(DataType::Artists, sender);
        let count = parser.parse_file(temp_file.path()).await.unwrap();

        assert_eq!(count, 1);

        let message = receiver.recv().await.unwrap();
        assert_eq!(message.id, "1");
        assert_eq!(message.data["name"], json!("Test Artist"));
        assert_eq!(message.data["profile"], json!("Test profile"));
    }

    #[tokio::test]
    async fn test_parse_release_with_artists() {
        // Test that nested artist elements are properly parsed with IDs
        let xml_content = r#"<?xml version="1.0" encoding="UTF-8"?>
<releases>
    <release id="123">
        <title>Test Release</title>
        <artists>
            <artist>
                <id>456</id>
                <name>The Beatles</name>
            </artist>
            <artist>
                <id>789</id>
                <name>George Martin</name>
            </artist>
        </artists>
        <labels>
            <label id="100" name="EMI" catno="PCS 7067"/>
        </labels>
        <genres>
            <genre>Rock</genre>
        </genres>
        <styles>
            <style>Pop Rock</style>
        </styles>
    </release>
</releases>"#;

        let mut temp_file = NamedTempFile::new().unwrap();
        let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
        encoder.write_all(xml_content.as_bytes()).unwrap();
        let compressed = encoder.finish().unwrap();
        temp_file.write_all(&compressed).unwrap();
        temp_file.flush().unwrap();

        let (sender, mut receiver) = mpsc::channel(10);
        let parser = XmlParser::new(DataType::Releases, sender);
        let count = parser.parse_file(temp_file.path()).await.unwrap();

        assert_eq!(count, 1);

        let message = receiver.recv().await.unwrap();
        assert_eq!(message.id, "123");
        assert_eq!(message.data["title"], json!("Test Release"));

        // Verify nested artists structure
        let artists = &message.data["artists"];
        assert!(artists.is_object(), "artists should be an object");

        let artist_list = &artists["artist"];
        assert!(artist_list.is_array(), "artists.artist should be an array");

        let artists_arr = artist_list.as_array().unwrap();
        assert_eq!(artists_arr.len(), 2);

        // First artist
        assert_eq!(artists_arr[0]["id"], json!("456"));
        assert_eq!(artists_arr[0]["name"], json!("The Beatles"));

        // Second artist
        assert_eq!(artists_arr[1]["id"], json!("789"));
        assert_eq!(artists_arr[1]["name"], json!("George Martin"));

        // Verify labels with attributes (all use @ prefix like xmltodict)
        let labels = &message.data["labels"];
        let label = &labels["label"];
        assert_eq!(label["@id"], json!("100"));
        assert_eq!(label["@name"], json!("EMI"));
        assert_eq!(label["@catno"], json!("PCS 7067"));

        // Verify genres and styles
        let genres = &message.data["genres"];
        assert_eq!(genres["genre"], json!("Rock"));

        let styles = &message.data["styles"];
        assert_eq!(styles["style"], json!("Pop Rock"));
    }

    #[tokio::test]
    async fn test_parse_artist_with_members() {
        // Test that artist members/groups are properly parsed
        // Note: In Discogs XML, artist id is a child element, not an attribute
        let xml_content = r#"<?xml version="1.0" encoding="UTF-8"?>
<artists>
    <artist>
        <id>1</id>
        <name>The Beatles</name>
        <members>
            <name id="10">John Lennon</name>
            <name id="20">Paul McCartney</name>
        </members>
        <aliases>
            <name id="100">Beatles, The</name>
        </aliases>
    </artist>
</artists>"#;

        let mut temp_file = NamedTempFile::new().unwrap();
        let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
        encoder.write_all(xml_content.as_bytes()).unwrap();
        let compressed = encoder.finish().unwrap();
        temp_file.write_all(&compressed).unwrap();
        temp_file.flush().unwrap();

        let (sender, mut receiver) = mpsc::channel(10);
        let parser = XmlParser::new(DataType::Artists, sender);
        let count = parser.parse_file(temp_file.path()).await.unwrap();

        assert_eq!(count, 1);

        let message = receiver.recv().await.unwrap();
        assert_eq!(message.id, "1");
        assert_eq!(message.data["name"], json!("The Beatles"));

        // Verify members structure
        let members = &message.data["members"];
        assert!(members.is_object(), "members should be an object");

        let member_list = &members["name"];
        assert!(member_list.is_array(), "members.name should be an array");

        let members_arr = member_list.as_array().unwrap();
        assert_eq!(members_arr.len(), 2);

        // Check that members have IDs and text content (id is attribute, uses @)
        assert_eq!(members_arr[0]["@id"], json!("10"));
        assert_eq!(members_arr[0]["#text"], json!("John Lennon"));

        assert_eq!(members_arr[1]["@id"], json!("20"));
        assert_eq!(members_arr[1]["#text"], json!("Paul McCartney"));

        // Verify aliases
        let aliases = &message.data["aliases"];
        let alias = &aliases["name"];
        assert_eq!(alias["@id"], json!("100"));
        assert_eq!(alias["#text"], json!("Beatles, The"));
    }

    #[tokio::test]
    async fn test_parse_label_with_sublabels() {
        // Note: In Discogs XML, label id is a child element, not an attribute
        let xml_content = r#"<?xml version="1.0" encoding="UTF-8"?>
<labels>
    <label>
        <id>1</id>
        <name>EMI</name>
        <parentLabel id="500">EMI Group</parentLabel>
        <sublabels>
            <label id="10">Parlophone</label>
            <label id="20">Columbia</label>
        </sublabels>
    </label>
</labels>"#;

        let mut temp_file = NamedTempFile::new().unwrap();
        let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
        encoder.write_all(xml_content.as_bytes()).unwrap();
        let compressed = encoder.finish().unwrap();
        temp_file.write_all(&compressed).unwrap();
        temp_file.flush().unwrap();

        let (sender, mut receiver) = mpsc::channel(10);
        let parser = XmlParser::new(DataType::Labels, sender);
        let count = parser.parse_file(temp_file.path()).await.unwrap();

        assert_eq!(count, 1);

        let message = receiver.recv().await.unwrap();
        assert_eq!(message.id, "1");
        assert_eq!(message.data["name"], json!("EMI"));

        // Verify parentLabel (id is attribute, uses @)
        let parent = &message.data["parentLabel"];
        assert_eq!(parent["@id"], json!("500"));
        assert_eq!(parent["#text"], json!("EMI Group"));

        // Verify sublabels
        let sublabels = &message.data["sublabels"];
        let label_list = &sublabels["label"];
        assert!(label_list.is_array());

        let labels_arr = label_list.as_array().unwrap();
        assert_eq!(labels_arr.len(), 2);

        assert_eq!(labels_arr[0]["@id"], json!("10"));
        assert_eq!(labels_arr[0]["#text"], json!("Parlophone"));

        assert_eq!(labels_arr[1]["@id"], json!("20"));
        assert_eq!(labels_arr[1]["#text"], json!("Columbia"));
    }

    #[tokio::test]
    async fn test_parse_master_with_artists() {
        let xml_content = r#"<?xml version="1.0" encoding="UTF-8"?>
<masters>
    <master id="1000">
        <title>Abbey Road</title>
        <year>1969</year>
        <artists>
            <artist>
                <id>456</id>
                <name>The Beatles</name>
            </artist>
        </artists>
        <genres>
            <genre>Rock</genre>
            <genre>Pop</genre>
        </genres>
        <styles>
            <style>Pop Rock</style>
        </styles>
    </master>
</masters>"#;

        let mut temp_file = NamedTempFile::new().unwrap();
        let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
        encoder.write_all(xml_content.as_bytes()).unwrap();
        let compressed = encoder.finish().unwrap();
        temp_file.write_all(&compressed).unwrap();
        temp_file.flush().unwrap();

        let (sender, mut receiver) = mpsc::channel(10);
        let parser = XmlParser::new(DataType::Masters, sender);
        let count = parser.parse_file(temp_file.path()).await.unwrap();

        assert_eq!(count, 1);

        let message = receiver.recv().await.unwrap();
        assert_eq!(message.id, "1000");
        assert_eq!(message.data["title"], json!("Abbey Road"));
        assert_eq!(message.data["year"], json!("1969"));

        // Verify artists
        let artists = &message.data["artists"];
        let artist = &artists["artist"];
        assert_eq!(artist["id"], json!("456"));
        assert_eq!(artist["name"], json!("The Beatles"));

        // Verify multiple genres
        let genres = &message.data["genres"];
        let genre_list = &genres["genre"];
        assert!(genre_list.is_array());
        let genres_arr = genre_list.as_array().unwrap();
        assert_eq!(genres_arr.len(), 2);
        assert_eq!(genres_arr[0], json!("Rock"));
        assert_eq!(genres_arr[1], json!("Pop"));
    }
}
