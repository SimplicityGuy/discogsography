use anyhow::{Context, Result};
use flate2::read::GzDecoder;
use quick_xml::encoding::Decoder;
use quick_xml::events::Event;
use quick_xml::{Reader, XmlVersion};
use serde_json::{Map, Value};
use std::fs::File;
use std::io::BufReader;
use std::path::Path;
use tokio::sync::mpsc;
use tracing::{debug, error, warn};

use crate::types::{DataMessage, DataType};

/// Maximum number of malformed XML records tolerated (skipped) per dump file.
///
/// A handful of poison records in a multi-GB monthly dump must not abort the whole
/// file — that would leave the file permanently un-completable and re-published from
/// record 0 on every restart. A large number of errors, on the other hand, means the
/// file is genuinely unusable (wrong file, truncated download), so parsing aborts.
const MAX_MALFORMED_RECORDS_PER_FILE: u64 = 100;

/// Maximum number of per-chunk UTF-8 decode warnings emitted while parsing one file.
///
/// The crate is built without quick-xml's `encoding` feature, so `decode()` is exactly
/// `str::from_utf8` and a dump that is not actually UTF-8 would fail on *every* text
/// chunk. Warn about the first few (enough for an operator to notice and diagnose) and
/// summarize the rest once at end-of-file instead of flooding the log.
const MAX_DECODE_WARNINGS_PER_FILE: u64 = 10;

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

    /// Create a new element context, parsing attributes from an XML element.
    ///
    /// Attribute values are decoded and entity-unescaped through quick-xml's
    /// unescape API so `&amp;`, `&lt;`, numeric char refs, etc. resolve the
    /// same way they do for element text (see the `Event::GeneralRef`
    /// handling in `parse_file`). Falls back to a raw, non-unescaped decode
    /// if the escape sequence is malformed, so a single bad attribute cannot
    /// abort parsing of an otherwise-valid record.
    fn with_attributes(e: &quick_xml::events::BytesStart<'_>, decoder: Decoder) -> Self {
        let mut ctx = Self::new();
        for attr in e.attributes().flatten() {
            let key = String::from_utf8_lossy(attr.key.as_ref()).to_string();
            let value = attr.decoded_and_normalized_value(XmlVersion::Implicit1_0, decoder).map(|c| c.into_owned()).unwrap_or_else(|err| {
                warn!("⚠️ Failed to unescape XML attribute '{}': {}", key, err);
                String::from_utf8_lossy(&attr.value).into_owned()
            });
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

        // Discogs dumps are known to ship records containing a bare `&` that does not
        // start an entity reference (e.g. `<title>Tom & Jerry</title>`). quick-xml < 0.39
        // emitted those bytes as text; 0.39+ returns `IllFormed(UnclosedReference)` unless
        // `allow_dangling_amp` is set. Restore the tolerant behaviour so a single legacy
        // escaping defect does not abort a multi-GB dump.
        reader.config_mut().allow_dangling_amp = true;

        let mut buf = Vec::new();
        let mut record_count = 0u64;
        let mut in_target_element = false;

        // Stack of element contexts for building nested structure
        let mut element_stack: Vec<ElementContext> = Vec::new();
        // Track depth in the overall document
        let mut depth = 0usize;

        // Per-record fault isolation state: a malformed record is dropped and the parser
        // resynchronizes on the next `<target_element>` start instead of aborting the file.
        let mut malformed_records = 0u64;
        let mut resyncing = false;
        let mut last_error_position = u64::MAX;

        // Count of text/entity chunks that failed a strict UTF-8 decode and were preserved
        // lossily instead of being dropped.
        let mut decode_failures = 0u64;

        // Determine the target element based on data type
        let target_element = match self.data_type {
            DataType::Artists => "artist",
            DataType::Labels => "label",
            DataType::Masters => "master",
            DataType::ReleaseGroups => unreachable!("ReleaseGroups is MusicBrainz-only, not used in Discogs XML parser"),
            DataType::Releases => "release",
        };

        loop {
            let event = match reader.read_event_into(&mut buf) {
                Ok(event) => event,
                Err(e) => {
                    let position = reader.buffer_position();
                    malformed_records += 1;

                    // A repeated error at the same byte offset means the reader made no
                    // forward progress and cannot recover — abort rather than spin forever.
                    if position == last_error_position {
                        error!("❌ Unrecoverable XML error at position {} (no forward progress): {}", position, e);
                        return Err(e).context(format!("Unrecoverable XML parse error at position {position}"));
                    }
                    if malformed_records > MAX_MALFORMED_RECORDS_PER_FILE {
                        error!(
                            "❌ Aborting {:?}: more than {} malformed XML records (last at position {}): {}",
                            file_path, MAX_MALFORMED_RECORDS_PER_FILE, position, e
                        );
                        return Err(e).context(format!("Exceeded malformed-record budget of {MAX_MALFORMED_RECORDS_PER_FILE} in {file_path:?}"));
                    }

                    warn!(
                        "⚠️ Skipping malformed XML record at position {} ({}/{} tolerated), resyncing on next <{}>: {}",
                        position, malformed_records, MAX_MALFORMED_RECORDS_PER_FILE, target_element, e
                    );
                    last_error_position = position;

                    // Discard the partially-built record and resynchronize.
                    element_stack.clear();
                    in_target_element = false;
                    resyncing = true;

                    buf.clear();
                    continue;
                }
            };

            // While resyncing, ignore everything until the next record start; document
            // depth is unreliable after an error, so it is re-anchored here.
            if resyncing {
                match &event {
                    Event::Start(e) | Event::Empty(e) if e.name().as_ref() == target_element.as_bytes() => {
                        debug!("🔄 Resynchronized on <{}> at position {}", target_element, reader.buffer_position());
                        resyncing = false;
                        depth = 1;
                    }
                    Event::Eof => break,
                    _ => {
                        buf.clear();
                        continue;
                    }
                }
            }

            match event {
                Event::Start(e) => {
                    let name = String::from_utf8_lossy(e.name().as_ref()).to_string();
                    depth += 1;

                    if name == target_element && depth == 2 {
                        // Start of a new record at depth 2 (inside container like <artists>)
                        in_target_element = true;
                        element_stack.clear();
                    }

                    if in_target_element {
                        element_stack.push(ElementContext::with_attributes(&e, reader.decoder()));
                    }
                }

                Event::Empty(e) => {
                    // Self-closing element like <artist id="123" />
                    let name = String::from_utf8_lossy(e.name().as_ref()).to_string();
                    depth += 1;

                    if name == target_element && depth == 2 {
                        // Self-closing target element (unlikely but handle it)
                        element_stack.clear();

                        // Send immediately since it's self-closing
                        let record = ElementContext::with_attributes(&e, reader.decoder()).into_value();
                        if let Value::Object(ref obj) = record {
                            let id = obj.get("@id").or_else(|| obj.get("id")).and_then(|v| v.as_str()).unwrap_or("unknown").to_string();
                            let raw_xml = if self.capture_raw_xml {
                                Some(reconstruct_xml(target_element, &record))
                            } else {
                                None
                            };
                            let message = DataMessage { id, sha256: String::new(), data: record.clone(), raw_xml };

                            if self.sender.send(message).await.is_err() {
                                warn!("⚠️ Receiver dropped, stopping parsing");
                                break;
                            }
                            record_count += 1;
                        }

                        in_target_element = false;
                    } else if in_target_element {
                        // Self-closing child element
                        let child_value = ElementContext::with_attributes(&e, reader.decoder()).into_value();

                        // Add to parent if we have one
                        if let Some(parent) = element_stack.last_mut() {
                            parent.add_child(name, child_value);
                        }
                    }

                    depth = depth.saturating_sub(1);
                }

                Event::End(e) => {
                    let name = String::from_utf8_lossy(e.name().as_ref()).to_string();

                    if in_target_element && let Some(context) = element_stack.pop() {
                        let element_value = context.into_value();

                        if name == target_element && depth == 2 {
                            // End of record, send it
                            if let Value::Object(obj) = element_value {
                                // Get ID - try @id first (attribute), then id (child element)
                                let id = obj.get("@id").or_else(|| obj.get("id")).and_then(|v| v.as_str()).unwrap_or("unknown").to_string();

                                // For releases/masters with @id attribute, the old pyextractor
                                // added a synthetic "id" field alongside @id. We skip that now
                                // because DataMessage.id carries the record ID, and
                                // #[serde(flatten)] would produce duplicate "id" JSON keys.
                                // For artists/labels that use <id> child elements (no @id),
                                // "id" is real data from the XML and must be preserved.
                                let mut final_obj = obj;
                                if final_obj.contains_key("@id") {
                                    final_obj.remove("id");
                                }

                                let final_value = Value::Object(final_obj);
                                let raw_xml = if self.capture_raw_xml {
                                    Some(reconstruct_xml(target_element, &final_value))
                                } else {
                                    None
                                };
                                let message = DataMessage { id: id.clone(), sha256: String::new(), data: final_value, raw_xml };

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

                Event::Text(e) => {
                    if in_target_element && let Some(context) = element_stack.last_mut() {
                        match e.decode() {
                            Ok(text) => context.text_content.push_str(&text),
                            Err(err) => {
                                // Degrade lossily rather than dropping the chunk: a silent drop
                                // publishes the record with the field's text missing, and the
                                // sha256 computed over that corrupted shape becomes the canonical
                                // value downstream, so the loss is never re-detected.
                                let position = reader.buffer_position();
                                decode_failures += 1;
                                if decode_failures <= MAX_DECODE_WARNINGS_PER_FILE {
                                    warn!(
                                        "⚠️ Failed to decode XML text at position {} ({}), preserving it lossily: {}",
                                        position, self.data_type, err
                                    );
                                }
                                context.text_content.push_str(&String::from_utf8_lossy(e.as_ref()));
                            }
                        }
                    }
                }

                // In quick-xml 0.39+, entity references (&amp; &lt; etc.) are emitted as
                // separate GeneralRef events rather than being included in Event::Text bytes.
                Event::GeneralRef(e) => {
                    if in_target_element && let Some(context) = element_stack.last_mut() {
                        if e.is_char_ref() {
                            match e.resolve_char_ref() {
                                Ok(Some(ch)) => context.text_content.push(ch),
                                Ok(None) => {
                                    warn!("⚠️ Unresolvable character reference in XML, dropping");
                                    context.text_content.push('\u{FFFD}');
                                }
                                Err(err) => {
                                    warn!("⚠️ Malformed character reference in XML: {}", err);
                                    context.text_content.push('\u{FFFD}');
                                }
                            }
                        } else {
                            // Same lossy-degradation contract as Event::Text: an undecodable
                            // entity name is preserved verbatim rather than dropped silently.
                            let name = e.decode().map(|n| n.into_owned()).unwrap_or_else(|err| {
                                let position = reader.buffer_position();
                                decode_failures += 1;
                                if decode_failures <= MAX_DECODE_WARNINGS_PER_FILE {
                                    warn!(
                                        "⚠️ Failed to decode XML entity reference at position {} ({}), preserving it lossily: {}",
                                        position, self.data_type, err
                                    );
                                }
                                String::from_utf8_lossy(e.as_ref()).into_owned()
                            });
                            match name.as_str() {
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

                Event::CData(e) => {
                    if in_target_element && let Some(context) = element_stack.last_mut() {
                        context.text_content.push_str(&String::from_utf8_lossy(&e));
                    }
                }

                Event::Eof => break,

                _ => {} // Ignore other events (comments, declarations, etc.)
            }

            buf.clear();
        }

        if malformed_records > 0 {
            warn!("⚠️ Skipped {} malformed XML record(s) while parsing {:?} ({} records parsed)", malformed_records, file_path, record_count);
        }

        if decode_failures > 0 {
            warn!(
                "⚠️ Recovered {} non-UTF-8 text chunk(s) lossily while parsing {:?} — the source dump is not valid UTF-8 and affected fields contain replacement characters",
                decode_failures, file_path
            );
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
    if let Err(e) = write_element(&mut writer, element_name, value) {
        tracing::warn!("Failed to reconstruct XML for violation report: {e}");
        return Vec::new();
    }
    writer.into_inner().into_inner()
}

fn write_element<W: std::io::Write>(writer: &mut quick_xml::Writer<W>, name: &str, value: &Value) -> std::io::Result<()> {
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
            writer.write_event(Event::Start(start))?;

            if let Some(Value::String(text)) = map.get("#text") {
                writer.write_event(Event::Text(BytesText::new(text)))?;
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
                            write_element(writer, key, item)?;
                        }
                    }
                    _ => write_element(writer, key, val)?,
                }
            }
            writer.write_event(Event::End(BytesEnd::new(name)))?;
        }
        Value::String(s) => {
            writer.write_event(Event::Start(BytesStart::new(name)))?;
            writer.write_event(Event::Text(BytesText::new(s)))?;
            writer.write_event(Event::End(BytesEnd::new(name)))?;
        }
        Value::Number(n) => {
            let s = n.to_string();
            writer.write_event(Event::Start(BytesStart::new(name)))?;
            writer.write_event(Event::Text(BytesText::new(&s)))?;
            writer.write_event(Event::End(BytesEnd::new(name)))?;
        }
        Value::Null => {
            writer.write_event(Event::Empty(BytesStart::new(name)))?;
        }
        _ => {}
    }
    Ok(())
}

#[cfg(test)]
#[path = "tests/parser_tests.rs"]
mod tests;
