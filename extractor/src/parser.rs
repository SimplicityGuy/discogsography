use anyhow::{Context, Result};
use flate2::read::GzDecoder;
use quick_xml::Reader;
use quick_xml::events::Event;
use serde_json::{Map, Value};
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
        Self { attributes: Map::new(), children: Map::new(), text_content: String::new() }
    }

    /// Create a new element context, parsing attributes from an XML element
    fn with_attributes(e: &quick_xml::events::BytesStart<'_>) -> Self {
        let mut ctx = Self::new();
        for attr in e.attributes().flatten() {
            let key = String::from_utf8_lossy(attr.key.as_ref()).to_string();
            let value = String::from_utf8_lossy(&attr.value).to_string();
            ctx.attributes.insert(key, Value::String(value));
        }
        ctx
    }

    /// Convert this element to a JSON value, combining attributes, text, and children
    fn into_value(self) -> Value {
        let mut result = Map::new();

        // Add attributes with @ prefix (matching xmltodict behavior exactly)
        for (key, value) in self.attributes {
            result.insert(format!("@{}", key), value);
        }

        // Preserve text content as-is (matching xmltodict which does not trim whitespace)
        let text = &self.text_content;
        let has_text = !text.trim().is_empty();

        if self.children.is_empty() {
            if result.is_empty() && has_text {
                // Just text content, return as string
                return Value::String(text.to_string());
            } else if has_text {
                // Has attributes and text, use #text for the text content
                result.insert("#text".to_string(), Value::String(text.to_string()));
            }
        } else if has_text {
            // Has children AND text (mixed content) — preserve text as #text
            // (matching xmltodict behavior)
            result.insert("#text".to_string(), Value::String(text.to_string()));
        }

        // Add children
        for (key, value) in self.children {
            result.insert(key, value);
        }

        if result.is_empty() && has_text {
            Value::String(text.to_string())
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
    capture_raw_xml: bool,
}

impl XmlParser {
    pub fn new(data_type: DataType, sender: mpsc::Sender<DataMessage>) -> Self {
        Self { data_type, sender, capture_raw_xml: false }
    }

    #[allow(dead_code)]
    pub fn with_options(data_type: DataType, sender: mpsc::Sender<DataMessage>, capture_raw_xml: bool) -> Self {
        Self { data_type, sender, capture_raw_xml }
    }

    pub async fn parse_file(&self, file_path: &Path) -> Result<u64> {
        // `file_path` comes from operator-controlled config (CLI/config file), not HTTP input.
        let file = File::open(file_path).context(format!("Failed to open file: {:?}", file_path))?; // nosemgrep: rust.actix.path-traversal.tainted-path.tainted-path

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
            DataType::ReleaseGroups => unreachable!("ReleaseGroups is MusicBrainz-only, not used in Discogs XML parser"),
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
                        element_stack.push(ElementContext::with_attributes(&e));
                    }
                }

                Ok(Event::Empty(e)) => {
                    // Self-closing element like <artist id="123" />
                    let name = String::from_utf8_lossy(e.name().as_ref()).to_string();
                    depth += 1;

                    if name == target_element && depth == 2 {
                        // Self-closing target element (unlikely but handle it)
                        element_stack.clear();

                        // Send immediately since it's self-closing
                        let record = ElementContext::with_attributes(&e).into_value();
                        if let Value::Object(ref obj) = record {
                            let id = obj.get("@id").or_else(|| obj.get("id")).and_then(|v| v.as_str()).unwrap_or("unknown").to_string();
                            let sha256 = calculate_record_hash(&record);
                            let raw_xml = if self.capture_raw_xml {
                                Some(reconstruct_xml(target_element, &record))
                            } else {
                                None
                            };
                            let message = DataMessage { id, sha256, data: record.clone(), raw_xml };

                            if self.sender.send(message).await.is_err() {
                                warn!("⚠️ Receiver dropped, stopping parsing");
                                break;
                            }
                            record_count += 1;
                        }

                        in_target_element = false;
                    } else if in_target_element {
                        // Self-closing child element
                        let child_value = ElementContext::with_attributes(&e).into_value();

                        // Add to parent if we have one
                        if let Some(parent) = element_stack.last_mut() {
                            parent.add_child(name, child_value);
                        }
                    }

                    depth = depth.saturating_sub(1);
                }

                Ok(Event::End(e)) => {
                    let name = String::from_utf8_lossy(e.name().as_ref()).to_string();

                    if in_target_element && let Some(context) = element_stack.pop() {
                        let element_value = context.into_value();

                        if name == target_element && depth == 2 {
                            // End of record, send it
                            if let Value::Object(obj) = element_value {
                                // Get ID - try @id first (attribute), then id (child element)
                                let id = obj.get("@id").or_else(|| obj.get("id")).and_then(|v| v.as_str()).unwrap_or("unknown").to_string();

                                // For releases and masters, pyextractor adds a plain 'id' field
                                // in addition to @id (see pyextractor.py line 536)
                                let mut final_obj = obj;
                                if matches!(self.data_type, DataType::Releases | DataType::Masters)
                                    && final_obj.get("@id").is_some()
                                    && final_obj.get("id").is_none()
                                {
                                    final_obj.insert("id".to_string(), Value::String(id.clone()));
                                }

                                let final_value = Value::Object(final_obj);
                                let sha256 = calculate_record_hash(&final_value);
                                let raw_xml = if self.capture_raw_xml {
                                    Some(reconstruct_xml(target_element, &final_value))
                                } else {
                                    None
                                };
                                let message = DataMessage { id: id.clone(), sha256, data: final_value, raw_xml };

                                if self.sender.send(message).await.is_err() {
                                    warn!("⚠️ Receiver dropped, stopping parsing");
                                    break;
                                }

                                record_count += 1;
                                if record_count.is_multiple_of(1000) {
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

                    depth = depth.saturating_sub(1);
                }

                Ok(Event::Text(e)) => {
                    if in_target_element
                        && let Some(context) = element_stack.last_mut()
                        && let Ok(text) = e.decode()
                    {
                        context.text_content.push_str(&text);
                    }
                }

                // In quick-xml 0.39+, entity references (&amp; &lt; etc.) are emitted as
                // separate GeneralRef events rather than being included in Event::Text bytes.
                Ok(Event::GeneralRef(e)) => {
                    if in_target_element && let Some(context) = element_stack.last_mut() {
                        if e.is_char_ref() {
                            if let Ok(Some(ch)) = e.resolve_char_ref() {
                                context.text_content.push(ch);
                            }
                        } else if let Ok(name) = e.decode() {
                            match name.as_ref() {
                                "amp" => context.text_content.push('&'),
                                "lt" => context.text_content.push('<'),
                                "gt" => context.text_content.push('>'),
                                "apos" => context.text_content.push('\''),
                                "quot" => context.text_content.push('"'),
                                _ => context.text_content.push_str(&format!("&{};", name)),
                            }
                        }
                    }
                }

                Ok(Event::CData(e)) => {
                    if in_target_element && let Some(context) = element_stack.last_mut() {
                        context.text_content.push_str(&String::from_utf8_lossy(&e));
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

/// Reconstruct an XML fragment from a parsed JSON Value using quick-xml::Writer.
fn reconstruct_xml(element_name: &str, value: &Value) -> Vec<u8> {
    use quick_xml::Writer;
    use std::io::Cursor;
    let mut writer = Writer::new(Cursor::new(Vec::new()));
    write_element(&mut writer, element_name, value);
    writer.into_inner().into_inner()
}

fn write_element<W: std::io::Write>(writer: &mut quick_xml::Writer<W>, name: &str, value: &Value) {
    use quick_xml::events::{BytesEnd, BytesStart, BytesText};

    match value {
        Value::Object(map) => {
            let mut start = BytesStart::new(name);
            for (key, val) in map {
                if let Some(attr_name) = key.strip_prefix('@')
                    && let Value::String(s) = val
                {
                    start.push_attribute((attr_name, s.as_str()));
                }
            }
            writer.write_event(Event::Start(start)).unwrap();

            if let Some(Value::String(text)) = map.get("#text") {
                writer.write_event(Event::Text(BytesText::new(text))).unwrap();
            }

            let has_at_id = map.contains_key("@id");
            for (key, val) in map {
                if key.starts_with('@') || key == "#text" {
                    continue;
                }
                if key == "id" && has_at_id {
                    continue;
                }
                match val {
                    Value::Array(arr) => {
                        for item in arr {
                            write_element(writer, key, item);
                        }
                    }
                    _ => write_element(writer, key, val),
                }
            }
            writer.write_event(Event::End(BytesEnd::new(name))).unwrap();
        }
        Value::String(s) => {
            writer.write_event(Event::Start(BytesStart::new(name))).unwrap();
            writer.write_event(Event::Text(BytesText::new(s))).unwrap();
            writer.write_event(Event::End(BytesEnd::new(name))).unwrap();
        }
        Value::Number(n) => {
            let s = n.to_string();
            writer.write_event(Event::Start(BytesStart::new(name))).unwrap();
            writer.write_event(Event::Text(BytesText::new(&s))).unwrap();
            writer.write_event(Event::End(BytesEnd::new(name))).unwrap();
        }
        Value::Null => {
            writer.write_event(Event::Empty(BytesStart::new(name))).unwrap();
        }
        _ => {}
    }
}

fn calculate_record_hash(record: &Value) -> String {
    let json_str = serde_json::to_string(record).unwrap_or_default();
    let mut hasher = Sha256::new();
    hasher.update(json_str.as_bytes());
    hex::encode(hasher.finalize())
}

#[cfg(test)]
#[path = "tests/parser_tests.rs"]
mod tests;
