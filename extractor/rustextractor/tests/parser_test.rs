// Additional integration tests for parser module
// Tests edge cases, error handling, and complex XML structures

use rust_extractor::parser::XmlParser;
use rust_extractor::types::DataType;
use flate2::Compression;
use flate2::write::GzEncoder;
use serde_json::json;
use std::io::Write;
use tempfile::NamedTempFile;
use tokio::sync::mpsc;

#[tokio::test]
async fn test_parse_empty_xml() {
    let xml_content = r#"<?xml version="1.0" encoding="UTF-8"?>
<artists>
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

    assert_eq!(count, 0);

    // Should not receive any messages
    let result = tokio::time::timeout(
        tokio::time::Duration::from_millis(100),
        receiver.recv()
    ).await;
    assert!(result.is_err()); // Timeout, no message received
}

#[tokio::test]
async fn test_parse_multiple_records() {
    let xml_content = r#"<?xml version="1.0" encoding="UTF-8"?>
<artists>
    <artist id="1"><name>Artist 1</name></artist>
    <artist id="2"><name>Artist 2</name></artist>
    <artist id="3"><name>Artist 3</name></artist>
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

    assert_eq!(count, 3);

    // Collect all messages
    let mut messages = Vec::new();
    while let Ok(msg) = tokio::time::timeout(
        tokio::time::Duration::from_millis(100),
        receiver.recv()
    ).await {
        if let Some(m) = msg {
            messages.push(m);
        }
    }

    assert_eq!(messages.len(), 3);
    assert_eq!(messages[0].id, "1");
    assert_eq!(messages[1].id, "2");
    assert_eq!(messages[2].id, "3");
}

#[tokio::test]
async fn test_parse_with_special_characters() {
    let xml_content = r#"<?xml version="1.0" encoding="UTF-8"?>
<artists>
    <artist id="1">
        <name>Artist &amp; Co.</name>
        <profile>They say "hello" &lt;world&gt;</profile>
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
    assert_eq!(message.data["name"], json!("Artist & Co."));
    // XML entities should be unescaped
    assert!(message.data["profile"].as_str().unwrap().contains("\"hello\""));
}

#[tokio::test]
async fn test_parse_with_cdata() {
    let xml_content = r#"<?xml version="1.0" encoding="UTF-8"?>
<artists>
    <artist id="1">
        <name>Test Artist</name>
        <profile><![CDATA[<b>Bold</b> text & special chars]]></profile>
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
    // CDATA content should be preserved as-is
    assert!(message.data["profile"].as_str().unwrap().contains("<b>Bold</b>"));
}

#[tokio::test]
async fn test_parse_deeply_nested_structure() {
    let xml_content = r#"<?xml version="1.0" encoding="UTF-8"?>
<releases>
    <release id="1">
        <title>Album</title>
        <artists>
            <artist>
                <id>100</id>
                <name>Main Artist</name>
                <anv>Alias</anv>
            </artist>
        </artists>
        <tracklist>
            <track>
                <position>A1</position>
                <title>Track 1</title>
                <artists>
                    <artist>
                        <id>100</id>
                        <name>Main Artist</name>
                    </artist>
                </artists>
            </track>
        </tracklist>
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
    assert_eq!(message.id, "1");

    // Verify nested structure
    let artists = &message.data["artists"];
    assert!(artists.is_object());

    let tracklist = &message.data["tracklist"];
    assert!(tracklist.is_object());
}

#[tokio::test]
async fn test_parse_labels_data_type() {
    let xml_content = r#"<?xml version="1.0" encoding="UTF-8"?>
<labels>
    <label>
        <id>1</id>
        <name>Test Label</name>
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
    assert_eq!(message.data["name"], json!("Test Label"));
}

#[tokio::test]
async fn test_parse_masters_data_type() {
    let xml_content = r#"<?xml version="1.0" encoding="UTF-8"?>
<masters>
    <master id="1">
        <title>Master Release</title>
        <year>2024</year>
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
    assert_eq!(message.id, "1");
    assert_eq!(message.data["title"], json!("Master Release"));
    assert_eq!(message.data["year"], json!("2024"));
}

#[tokio::test]
async fn test_parse_with_empty_elements() {
    let xml_content = r#"<?xml version="1.0" encoding="UTF-8"?>
<artists>
    <artist id="1">
        <name>Artist</name>
        <profile></profile>
        <notes/>
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
    assert_eq!(message.data["name"], json!("Artist"));
    // Empty elements should still be present in the structure
}

#[tokio::test]
async fn test_parse_with_whitespace() {
    let xml_content = r#"<?xml version="1.0" encoding="UTF-8"?>
<artists>
    <artist id="1">
        <name>  Artist Name  </name>
        <profile>
            Text with
            whitespace
        </profile>
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
    // Whitespace should be trimmed
    assert_eq!(message.data["name"], json!("Artist Name"));
}

#[tokio::test]
async fn test_parse_hash_calculation() {
    let xml_content = r#"<?xml version="1.0" encoding="UTF-8"?>
<artists>
    <artist id="1"><name>Artist 1</name></artist>
    <artist id="2"><name>Artist 2</name></artist>
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

    assert_eq!(count, 2);

    // Collect messages
    let msg1 = receiver.recv().await.unwrap();
    let msg2 = receiver.recv().await.unwrap();

    // Hashes should be different for different content
    assert_ne!(msg1.sha256, msg2.sha256);

    // Hashes should be non-empty and valid hex
    assert_eq!(msg1.sha256.len(), 64); // SHA256 produces 64 hex chars
    assert_eq!(msg2.sha256.len(), 64);
    assert!(msg1.sha256.chars().all(|c| c.is_ascii_hexdigit()));
    assert!(msg2.sha256.chars().all(|c| c.is_ascii_hexdigit()));
}

#[tokio::test]
async fn test_parse_with_array_elements() {
    let xml_content = r#"<?xml version="1.0" encoding="UTF-8"?>
<artists>
    <artist id="1">
        <name>Artist</name>
        <members>
            <name>Member 1</name>
            <name>Member 2</name>
            <name>Member 3</name>
        </members>
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

    // Multiple elements with same name should become array
    let members = &message.data["members"]["name"];
    assert!(members.is_array(), "Multiple 'name' elements should be array");
    let members_arr = members.as_array().unwrap();
    assert_eq!(members_arr.len(), 3);
}

#[tokio::test]
async fn test_parse_release_with_id_field() {
    // Releases should have both @id (attribute) and id (plain field)
    let xml_content = r#"<?xml version="1.0" encoding="UTF-8"?>
<releases>
    <release id="123">
        <title>Test</title>
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

    // Should have both @id and id
    assert_eq!(message.data["@id"], json!("123"));
    assert_eq!(message.data["id"], json!("123"));
}

#[tokio::test]
async fn test_parse_master_with_id_field() {
    // Masters should also have both @id and id
    let xml_content = r#"<?xml version="1.0" encoding="UTF-8"?>
<masters>
    <master id="456">
        <title>Test Master</title>
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

    // Should have both @id and id
    assert_eq!(message.data["@id"], json!("456"));
    assert_eq!(message.data["id"], json!("456"));
}

#[tokio::test]
async fn test_parse_channel_closed_gracefully() {
    let xml_content = r#"<?xml version="1.0" encoding="UTF-8"?>
<artists>
    <artist id="1"><name>Artist 1</name></artist>
    <artist id="2"><name>Artist 2</name></artist>
</artists>"#;

    let mut temp_file = NamedTempFile::new().unwrap();
    let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
    encoder.write_all(xml_content.as_bytes()).unwrap();
    let compressed = encoder.finish().unwrap();
    temp_file.write_all(&compressed).unwrap();
    temp_file.flush().unwrap();

    let (sender, receiver) = mpsc::channel(1); // Small buffer
    let parser = XmlParser::new(DataType::Artists, sender);

    // Drop receiver immediately to close channel
    drop(receiver);

    // Parser should handle closed channel gracefully
    let result = parser.parse_file(temp_file.path()).await;
    assert!(result.is_ok());
}

#[tokio::test]
async fn test_parse_large_batch() {
    // Generate XML with many records
    let mut xml_content = String::from(r#"<?xml version="1.0" encoding="UTF-8"?>
<artists>"#);

    for i in 1..=100 {
        xml_content.push_str(&format!(
            r#"<artist id="{}"><name>Artist {}</name></artist>"#,
            i, i
        ));
    }

    xml_content.push_str("</artists>");

    let mut temp_file = NamedTempFile::new().unwrap();
    let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
    encoder.write_all(xml_content.as_bytes()).unwrap();
    let compressed = encoder.finish().unwrap();
    temp_file.write_all(&compressed).unwrap();
    temp_file.flush().unwrap();

    let (sender, mut receiver) = mpsc::channel(200);
    let parser = XmlParser::new(DataType::Artists, sender);
    let count = parser.parse_file(temp_file.path()).await.unwrap();

    assert_eq!(count, 100);

    // Verify we can receive all messages
    let mut received_count = 0;
    while let Ok(Some(_)) = tokio::time::timeout(
        tokio::time::Duration::from_millis(100),
        receiver.recv()
    ).await {
        received_count += 1;
    }

    assert_eq!(received_count, 100);
}
