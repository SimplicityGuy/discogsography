use super::*;
use flate2::Compression;
use flate2::write::GzEncoder;
use serde_json::json;
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

#[test]
fn test_element_context_new() {
    let context = ElementContext::new();
    assert!(context.attributes.is_empty());
    assert!(context.children.is_empty());
    assert!(context.text_content.is_empty());
}

#[test]
fn test_element_context_to_value_empty() {
    let context = ElementContext::new();
    let value = context.into_value();
    assert_eq!(value, Value::Null);
}

#[test]
fn test_element_context_to_value_text_only() {
    let mut context = ElementContext::new();
    context.text_content = "  Test text  ".to_string();
    let value = context.into_value();
    // Whitespace is preserved to match xmltodict behavior
    assert_eq!(value, Value::String("  Test text  ".to_string()));
}

#[test]
fn test_element_context_to_value_attributes_only() {
    let mut context = ElementContext::new();
    context.attributes.insert("id".to_string(), Value::String("123".to_string()));
    let value = context.into_value();
    assert!(value.is_object());
    let obj = value.as_object().unwrap();
    assert_eq!(obj.get("@id"), Some(&Value::String("123".to_string())));
}

#[test]
fn test_element_context_to_value_attributes_and_text() {
    let mut context = ElementContext::new();
    context.attributes.insert("id".to_string(), Value::String("123".to_string()));
    context.text_content = "Text content".to_string();
    let value = context.into_value();
    assert!(value.is_object());
    let obj = value.as_object().unwrap();
    assert_eq!(obj.get("@id"), Some(&Value::String("123".to_string())));
    assert_eq!(obj.get("#text"), Some(&Value::String("Text content".to_string())));
}

#[test]
fn test_element_context_to_value_mixed_content() {
    // Element with both text and children (mixed content)
    // xmltodict preserves the text as #text alongside children
    let mut context = ElementContext::new();
    context.text_content = "Some text".to_string();
    context.add_child("child".to_string(), Value::String("child value".to_string()));
    let value = context.into_value();
    assert!(value.is_object());
    let obj = value.as_object().unwrap();
    assert_eq!(obj.get("#text"), Some(&Value::String("Some text".to_string())));
    assert_eq!(obj.get("child"), Some(&Value::String("child value".to_string())));
}

#[test]
fn test_element_context_to_value_whitespace_preserved() {
    // Whitespace should be preserved to match xmltodict behavior
    let mut context = ElementContext::new();
    context.attributes.insert("id".to_string(), Value::String("1".to_string()));
    context.text_content = "  spaced text  ".to_string();
    let value = context.into_value();
    let obj = value.as_object().unwrap();
    assert_eq!(obj.get("#text"), Some(&Value::String("  spaced text  ".to_string())));
}

#[test]
fn test_element_context_add_child_single() {
    let mut context = ElementContext::new();
    context.add_child("name".to_string(), Value::String("Test".to_string()));
    assert_eq!(context.children.get("name"), Some(&Value::String("Test".to_string())));
}

#[test]
fn test_element_context_add_child_multiple() {
    let mut context = ElementContext::new();
    context.add_child("name".to_string(), Value::String("First".to_string()));
    context.add_child("name".to_string(), Value::String("Second".to_string()));

    let value = context.children.get("name").unwrap();
    assert!(value.is_array());
    let arr = value.as_array().unwrap();
    assert_eq!(arr.len(), 2);
    assert_eq!(arr[0], Value::String("First".to_string()));
    assert_eq!(arr[1], Value::String("Second".to_string()));
}

#[test]
fn test_element_context_add_child_to_existing_array() {
    let mut context = ElementContext::new();
    context.add_child("name".to_string(), Value::String("First".to_string()));
    context.add_child("name".to_string(), Value::String("Second".to_string()));
    context.add_child("name".to_string(), Value::String("Third".to_string()));

    let value = context.children.get("name").unwrap();
    let arr = value.as_array().unwrap();
    assert_eq!(arr.len(), 3);
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

#[tokio::test]
async fn test_parse_self_closing_target_element() {
    let xml_content = r#"<?xml version="1.0" encoding="UTF-8"?>
<artists>
    <artist id="1" />
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
    assert_eq!(message.id, "1", "self-closing element ID should use @id attribute");
    assert_eq!(message.data["@id"], json!("1"));
}

#[tokio::test]
async fn test_parse_with_entity_references() {
    let xml_content = r#"<?xml version="1.0" encoding="UTF-8"?>
<artists>
    <artist id="1">
        <name>Tom &amp; Jerry</name>
        <profile>&lt;b&gt;Bold &amp; &apos;Quoted&apos; &quot;Text&quot;&lt;/b&gt;</profile>
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
    assert_eq!(message.data["name"], json!("Tom & Jerry"));
    assert_eq!(message.data["profile"], json!("<b>Bold & 'Quoted' \"Text\"</b>"));
}

#[tokio::test]
async fn test_parse_with_numeric_character_references() {
    // Test that numeric character references (&#x...;) are resolved correctly.
    // This exercises the Ok(Some(ch)) branch of resolve_char_ref().
    let xml_content = r#"<?xml version="1.0" encoding="UTF-8"?>
<artists>
    <artist id="1">
        <name>&#x41;rtist &#x42;</name>
        <profile>Note &#x266A; Music</profile>
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
    // &#x41; = 'A', &#x42; = 'B', &#x266A; = '♪'
    assert_eq!(message.data["name"], json!("Artist B"));
    assert_eq!(message.data["profile"], json!("Note ♪ Music"));
}

#[tokio::test]
async fn test_parse_with_unknown_entity_reference() {
    // Test that unknown named entity references are preserved as &name;
    // This exercises the _ => fallback branch in the GeneralRef handler.
    let xml_content = r#"<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE artists [
    <!ENTITY custom "custom value">
]>
<artists>
    <artist id="1">
        <name>Test &custom; Artist</name>
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
    // Custom entity should be preserved as &custom; since parser doesn't expand DTD entities
    assert_eq!(message.data["name"], json!("Test &custom; Artist"));
}

#[tokio::test]
async fn test_parse_file_not_found() {
    let (sender, _receiver) = mpsc::channel(10);
    let parser = XmlParser::new(DataType::Artists, sender);
    let result = parser.parse_file(Path::new("/nonexistent/path/file.xml.gz")).await;

    assert!(result.is_err());
}

#[tokio::test]
async fn test_parse_self_closing_child_element() {
    let xml_content = r#"<?xml version="1.0" encoding="UTF-8"?>
<artists>
    <artist id="1">
        <name>Test Artist</name>
        <image height="100" width="100" />
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
    assert_eq!(message.data["name"], json!("Test Artist"));
    let image = &message.data["image"];
    assert_eq!(image["@height"], json!("100"));
    assert_eq!(image["@width"], json!("100"));
}

#[tokio::test]
async fn test_parse_receiver_dropped() {
    // Create XML with multiple records
    let mut xml_content = String::from(r#"<?xml version="1.0" encoding="UTF-8"?><artists>"#);
    for i in 0..100 {
        xml_content.push_str(&format!(r#"<artist id="{}"><name>Artist {}</name></artist>"#, i, i));
    }
    xml_content.push_str("</artists>");

    let mut temp_file = NamedTempFile::new().unwrap();
    let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
    encoder.write_all(xml_content.as_bytes()).unwrap();
    let compressed = encoder.finish().unwrap();
    temp_file.write_all(&compressed).unwrap();
    temp_file.flush().unwrap();

    // Use a channel with buffer size 1, then drop the receiver immediately
    let (sender, receiver) = mpsc::channel(1);
    drop(receiver);

    let parser = XmlParser::new(DataType::Artists, sender);
    let result = parser.parse_file(temp_file.path()).await;

    // Should return Ok (breaks early) with a partial count
    assert!(result.is_ok());
    let count = result.unwrap();
    assert!(count < 100, "Should have stopped early due to dropped receiver, got {}", count);
}

#[tokio::test]
async fn test_raw_xml_capture() {
    let xml_content = r#"<?xml version="1.0" encoding="UTF-8"?>
<artists>
    <artist id="1">
        <name>Test Artist</name>
    </artist>
</artists>"#;

    let mut temp_file = NamedTempFile::new().unwrap();
    let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
    encoder.write_all(xml_content.as_bytes()).unwrap();
    let compressed = encoder.finish().unwrap();
    temp_file.write_all(&compressed).unwrap();
    temp_file.flush().unwrap();

    let (sender, mut receiver) = mpsc::channel(10);
    let parser = XmlParser::with_options(DataType::Artists, sender, true);
    let count = parser.parse_file(temp_file.path()).await.unwrap();

    assert_eq!(count, 1);
    let msg = receiver.recv().await.unwrap();
    assert!(msg.raw_xml.is_some(), "raw_xml should be populated when capture is enabled");
    let xml_str = String::from_utf8_lossy(msg.raw_xml.as_ref().unwrap());
    assert!(xml_str.contains("Test Artist"), "reconstructed XML should contain the artist name");
    assert!(xml_str.contains("artist"), "reconstructed XML should contain the element name");
}

#[tokio::test]
async fn test_raw_xml_not_captured_by_default() {
    let xml_content = r#"<?xml version="1.0" encoding="UTF-8"?>
<artists>
    <artist id="1">
        <name>Test Artist</name>
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
    let msg = receiver.recv().await.unwrap();
    assert!(msg.raw_xml.is_none(), "raw_xml should be None when capture is disabled");
}

// ── reconstruct_xml / write_element coverage ────────────────────────

/// Helper: parse XML, capture raw_xml, return it as a UTF-8 string.
async fn capture_raw_xml(xml_content: &str, data_type: DataType) -> String {
    let mut temp_file = NamedTempFile::new().unwrap();
    let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
    encoder.write_all(xml_content.as_bytes()).unwrap();
    let compressed = encoder.finish().unwrap();
    temp_file.write_all(&compressed).unwrap();
    temp_file.flush().unwrap();

    let (sender, mut receiver) = mpsc::channel(10);
    let parser = XmlParser::with_options(data_type, sender, true);
    parser.parse_file(temp_file.path()).await.unwrap();
    let msg = receiver.recv().await.unwrap();
    String::from_utf8(msg.raw_xml.unwrap()).unwrap()
}

#[tokio::test]
async fn test_reconstruct_xml_with_null_value() {
    // An element with no content or attributes → Value::Null → self-closing tag
    let xml_content = r#"<?xml version="1.0" encoding="UTF-8"?>
<artists>
    <artist id="1">
        <name>Test Artist</name>
        <profile/>
    </artist>
</artists>"#;

    let raw = capture_raw_xml(xml_content, DataType::Artists).await;
    // profile element is null → should be written as self-closing <profile/>
    assert!(raw.contains("profile"), "reconstructed XML should include empty profile element");
    assert!(raw.contains("Test Artist"), "reconstructed XML should include name text");
}

#[tokio::test]
async fn test_reconstruct_xml_with_array_children() {
    // Multiple genre elements → stored as Value::Array → each emitted as separate element
    let xml_content = r#"<?xml version="1.0" encoding="UTF-8"?>
<masters>
    <master id="999">
        <title>Multi-Genre Album</title>
        <genres>
            <genre>Rock</genre>
            <genre>Jazz</genre>
            <genre>Blues</genre>
        </genres>
    </master>
</masters>"#;

    let raw = capture_raw_xml(xml_content, DataType::Masters).await;
    // All three genres should appear in the reconstructed XML
    assert!(raw.contains("Rock"), "reconstructed XML should contain first genre");
    assert!(raw.contains("Jazz"), "reconstructed XML should contain second genre");
    assert!(raw.contains("Blues"), "reconstructed XML should contain third genre");
    // The genre tag should appear three times
    let genre_count = raw.matches("<genre>").count();
    assert_eq!(genre_count, 3, "should have 3 <genre> elements, got {}", genre_count);
}

#[tokio::test]
async fn test_reconstruct_xml_with_text_and_attributes() {
    // Element with both @id attribute and #text content
    let xml_content = r#"<?xml version="1.0" encoding="UTF-8"?>
<artists>
    <artist>
        <id>42</id>
        <name>Mixed Content Artist</name>
        <aliases>
            <name id="99">An Alias Name</name>
        </aliases>
    </artist>
</artists>"#;

    let raw = capture_raw_xml(xml_content, DataType::Artists).await;
    // The alias element has @id attribute and #text — both must appear in output
    assert!(raw.contains("An Alias Name"), "reconstructed XML should contain alias text");
    assert!(raw.contains("id=\"99\""), "reconstructed XML should contain alias id attribute");
}

#[tokio::test]
async fn test_reconstruct_xml_id_dedup_for_releases() {
    // Releases get a plain `id` field added alongside @id.
    // write_element should skip the plain `id` child when @id is present to avoid duplication.
    let xml_content = r#"<?xml version="1.0" encoding="UTF-8"?>
<releases>
    <release id="555">
        <title>Dedup Test Release</title>
        <genres>
            <genre>Electronic</genre>
        </genres>
    </release>
</releases>"#;

    let raw = capture_raw_xml(xml_content, DataType::Releases).await;
    // The reconstructed XML should have the id attribute but not a standalone <id> child element,
    // because write_element skips `id` when `@id` is present.
    assert!(raw.contains("id=\"555\""), "reconstructed XML should contain id attribute");
    // Should NOT contain <id>555</id> — that would be the deduplicated plain id child
    assert!(!raw.contains("<id>"), "reconstructed XML should not contain a standalone <id> element");
    assert!(raw.contains("Dedup Test Release"), "reconstructed XML should contain title");
}

#[tokio::test]
async fn test_reconstruct_xml_with_numeric_values() {
    // A master with numeric year field — tests the Value::Number branch of write_element
    let xml_content = r#"<?xml version="1.0" encoding="UTF-8"?>
<masters>
    <master id="500">
        <title>Numeric Test</title>
        <year>2025</year>
    </master>
</masters>"#;

    let raw = capture_raw_xml(xml_content, DataType::Masters).await;
    assert!(raw.contains("2025"), "reconstructed XML should contain numeric year value");
    assert!(raw.contains("<year>"), "reconstructed XML should have year element");
    assert!(raw.contains("Numeric Test"), "reconstructed XML should contain title");
}

#[tokio::test]
async fn test_reconstruct_xml_self_closing_target() {
    // Self-closing target element with capture_raw_xml enabled
    let xml_content = r#"<?xml version="1.0" encoding="UTF-8"?>
<artists>
    <artist id="999" />
</artists>"#;

    let mut temp_file = NamedTempFile::new().unwrap();
    let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
    encoder.write_all(xml_content.as_bytes()).unwrap();
    let compressed = encoder.finish().unwrap();
    temp_file.write_all(&compressed).unwrap();
    temp_file.flush().unwrap();

    let (sender, mut receiver) = mpsc::channel(10);
    let parser = XmlParser::with_options(DataType::Artists, sender, true);
    let count = parser.parse_file(temp_file.path()).await.unwrap();

    assert_eq!(count, 1);
    let msg = receiver.recv().await.unwrap();
    assert!(msg.raw_xml.is_some(), "raw_xml should be populated for self-closing target");
    let xml_str = String::from_utf8_lossy(msg.raw_xml.as_ref().unwrap());
    assert!(xml_str.contains("artist"), "reconstructed XML should contain element name");
    assert!(xml_str.contains("999"), "reconstructed XML should contain id attribute value");
}

#[tokio::test]
async fn test_reconstruct_xml_id_without_at_id_is_kept() {
    // Artists/Labels use child <id> elements (not @id attributes).
    // write_element must NOT skip the `id` child when no @id attribute is present.
    let xml_content = r#"<?xml version="1.0" encoding="UTF-8"?>
<artists>
    <artist>
        <id>77</id>
        <name>Artist With Child ID</name>
    </artist>
</artists>"#;

    let raw = capture_raw_xml(xml_content, DataType::Artists).await;
    // The plain `id` element should be present because there is no @id on this artist
    assert!(raw.contains("<id>"), "reconstructed XML should retain <id> child when no @id attribute");
    assert!(raw.contains("77"), "reconstructed XML should contain the id value");
}
