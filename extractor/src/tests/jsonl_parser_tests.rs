use super::*;

// ─── extract_discogs_id ───────────────────────────────────────────────────────

#[test]
fn test_extract_discogs_id_from_artist_url() {
    assert_eq!(extract_discogs_id("https://www.discogs.com/artist/108713", "artist"), Some(108713));
}

#[test]
fn test_extract_discogs_id_from_label_url() {
    assert_eq!(extract_discogs_id("https://www.discogs.com/label/1000", "label"), Some(1000));
}

#[test]
fn test_extract_discogs_id_no_match() {
    assert_eq!(extract_discogs_id("https://en.wikipedia.org/wiki/The_Beatles", "artist"), None);
}

#[test]
fn test_extract_discogs_id_malformed() {
    assert_eq!(extract_discogs_id("https://www.discogs.com/artist/notanumber", "artist"), None);
}

#[test]
fn test_extract_discogs_id_with_slug() {
    // Slug after hyphen should be ignored; leading numeric segment is the ID.
    assert_eq!(extract_discogs_id("https://www.discogs.com/artist/108713-The-Beatles", "artist"), Some(108713));
}

#[test]
fn test_extract_discogs_id_wrong_entity_type() {
    // URL is for "artist" but we request "label" — prefix won't match.
    assert_eq!(extract_discogs_id("https://www.discogs.com/artist/108713", "label"), None);
}

// ─── extract_external_links ──────────────────────────────────────────────────

#[test]
fn test_extract_external_links_filters_discogs() {
    let url_rels = serde_json::json!([
        {"type": "discogs", "url": {"resource": "https://www.discogs.com/artist/108713"}},
        {"type": "wikipedia", "url": {"resource": "https://en.wikipedia.org/wiki/The_Beatles"}}
    ]);
    let links = extract_external_links(url_rels.as_array().unwrap());
    assert_eq!(links.len(), 1);
    assert_eq!(links[0]["service"], "wikipedia");
    assert_eq!(links[0]["url"], "https://en.wikipedia.org/wiki/The_Beatles");
}

#[test]
fn test_extract_external_links_empty() {
    let links = extract_external_links(&[]);
    assert!(links.is_empty());
}

#[test]
fn test_extract_external_links_all_discogs() {
    let url_rels = serde_json::json!([
        {"type": "discogs", "url": {"resource": "https://www.discogs.com/artist/1"}}
    ]);
    let links = extract_external_links(url_rels.as_array().unwrap());
    assert!(links.is_empty());
}

// ─── parse_mb_artist_line ────────────────────────────────────────────────────

#[test]
fn test_parse_mb_artist_line_with_discogs() {
    let line = r#"{"id":"b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d","name":"The Beatles","sort-name":"Beatles, The","type":"Group","gender":null,"life-span":{"begin":"1960","end":"1970","ended":true},"area":{"name":"London"},"begin-area":{"name":"Liverpool"},"end-area":null,"disambiguation":"the band","aliases":[],"tags":[],"relations":[],"url-rels":[{"type":"discogs","url":{"resource":"https://www.discogs.com/artist/108713"}},{"type":"wikipedia","url":{"resource":"https://en.wikipedia.org/wiki/The_Beatles"}}]}"#;
    let msg = parse_mb_artist_line(line).unwrap();
    assert_eq!(msg.id, "b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d");
    assert_eq!(msg.data["discogs_artist_id"], 108713);
    assert_eq!(msg.data["mb_type"], "Group");
    assert_eq!(msg.data["name"], "The Beatles");
    assert_eq!(msg.data["area"], "London");
    assert_eq!(msg.data["begin_area"], "Liverpool");
    // sha256 should be non-empty
    assert!(!msg.sha256.is_empty());
    // Check external links include wikipedia but not discogs
    let links = msg.data["external_links"].as_array().unwrap();
    assert_eq!(links.len(), 1);
    assert_eq!(links[0]["service"], "wikipedia");
}

#[test]
fn test_parse_mb_artist_line_no_discogs() {
    let line = r#"{"id":"some-mbid","name":"Unknown","sort-name":"Unknown","type":"Person","gender":"Male","life-span":{"begin":"1990","end":null,"ended":false},"area":null,"begin-area":null,"end-area":null,"disambiguation":"","aliases":[],"tags":[],"relations":[],"url-rels":[]}"#;
    let msg = parse_mb_artist_line(line).unwrap();
    assert!(msg.data["discogs_artist_id"].is_null());
    assert_eq!(msg.data["gender"], "Male");
    assert_eq!(msg.data["mb_type"], "Person");
}

#[test]
fn test_parse_mb_artist_line_invalid_json() {
    let result = parse_mb_artist_line("not valid json{{{");
    assert!(result.is_err());
}

#[test]
fn test_parse_mb_artist_line_life_span_fields() {
    let line = r#"{"id":"test-id","name":"Solo Artist","sort-name":"Artist, Solo","type":"Person","gender":"Female","life-span":{"begin":"1985","end":null,"ended":false},"area":{"name":"New York"},"begin-area":null,"end-area":null,"disambiguation":"","aliases":[],"tags":[],"relations":[],"url-rels":[]}"#;
    let msg = parse_mb_artist_line(line).unwrap();
    assert_eq!(msg.data["life_span"]["begin"], "1985");
    assert!(msg.data["life_span"]["end"].is_null());
    assert_eq!(msg.data["life_span"]["ended"], false);
}

// ─── parse_mb_label_line ─────────────────────────────────────────────────────

#[test]
fn test_parse_mb_label_line_with_discogs() {
    let line = r#"{"id":"4cccc72a-0bd0-433a-905e-dad87871397d","name":"EMI","type":"Original Production","label-code":542,"life-span":{"begin":"1931","end":"2012","ended":true},"area":{"name":"United Kingdom"},"disambiguation":"","relations":[],"url-rels":[{"type":"discogs","url":{"resource":"https://www.discogs.com/label/542"}},{"type":"allmusic","url":{"resource":"https://www.allmusic.com/artist/emi-mn0000929870"}}]}"#;
    let msg = parse_mb_label_line(line).unwrap();
    assert_eq!(msg.id, "4cccc72a-0bd0-433a-905e-dad87871397d");
    assert_eq!(msg.data["discogs_label_id"], 542);
    assert_eq!(msg.data["name"], "EMI");
    assert_eq!(msg.data["mb_type"], "Original Production");
    assert_eq!(msg.data["label_code"], 542);
    assert_eq!(msg.data["area"], "United Kingdom");
    let links = msg.data["external_links"].as_array().unwrap();
    assert_eq!(links.len(), 1);
    assert_eq!(links[0]["service"], "allmusic");
}

#[test]
fn test_parse_mb_label_line_no_discogs() {
    let line = r#"{"id":"label-mbid","name":"Indie Label","type":"Imprint","label-code":null,"life-span":{"begin":"2000","end":null,"ended":false},"area":null,"disambiguation":"small indie","relations":[],"url-rels":[]}"#;
    let msg = parse_mb_label_line(line).unwrap();
    assert!(msg.data["discogs_label_id"].is_null());
    assert_eq!(msg.data["name"], "Indie Label");
    assert!(msg.data["area"].is_null());
}

#[test]
fn test_parse_mb_label_line_invalid_json() {
    let result = parse_mb_label_line("{bad json");
    assert!(result.is_err());
}

// ─── parse_mb_release_line ───────────────────────────────────────────────────

#[test]
fn test_parse_mb_release_line_with_discogs() {
    let line = r#"{"id":"c7b9bcd3-a23e-476b-be7f-f8e96c54b6a2","title":"Abbey Road","barcode":"077774644228","status":"Official","release-group":{"id":"1dc4c347-a1db-32aa-b14f-bc9cc507b843"},"relations":[],"url-rels":[{"type":"discogs","url":{"resource":"https://www.discogs.com/release/5027187"}},{"type":"youtube","url":{"resource":"https://www.youtube.com/watch?v=abc"}}]}"#;
    let msg = parse_mb_release_line(line).unwrap();
    assert_eq!(msg.id, "c7b9bcd3-a23e-476b-be7f-f8e96c54b6a2");
    assert_eq!(msg.data["discogs_release_id"], 5_027_187);
    assert_eq!(msg.data["name"], "Abbey Road");
    assert_eq!(msg.data["barcode"], "077774644228");
    assert_eq!(msg.data["status"], "Official");
    assert_eq!(msg.data["release_group_mbid"], "1dc4c347-a1db-32aa-b14f-bc9cc507b843");
    let links = msg.data["external_links"].as_array().unwrap();
    assert_eq!(links.len(), 1);
    assert_eq!(links[0]["service"], "youtube");
}

#[test]
fn test_parse_mb_release_line_no_discogs() {
    let line = r#"{"id":"release-mbid","title":"Unknown Release","barcode":null,"status":"Bootleg","release-group":{"id":"group-mbid"},"relations":[],"url-rels":[]}"#;
    let msg = parse_mb_release_line(line).unwrap();
    assert!(msg.data["discogs_release_id"].is_null());
    assert_eq!(msg.data["name"], "Unknown Release");
    assert_eq!(msg.data["status"], "Bootleg");
}

#[test]
fn test_parse_mb_release_line_invalid_json() {
    let result = parse_mb_release_line("[]");
    // An array is valid JSON but will produce "unknown" id — it should succeed but produce null fields
    // Actually this won't error because serde_json::from_str succeeds on arrays.
    // The function returns Ok with "unknown" id.
    assert!(result.is_ok());
}

#[test]
fn test_parse_mb_release_line_true_invalid_json() {
    let result = parse_mb_release_line("definitely not json");
    assert!(result.is_err());
}

// ─── parse_mb_jsonl_file (integration via in-memory xz) ─────────────────────

#[test]
fn test_parse_mb_jsonl_file_artists() {
    use std::io::Write;
    use tempfile::NamedTempFile;
    use tokio::sync::mpsc;
    use xz2::write::XzEncoder;

    let line1 = r#"{"id":"mbid-1","name":"Artist One","sort-name":"One, Artist","type":"Person","gender":"Male","life-span":{"begin":"1970","end":null,"ended":false},"area":null,"begin-area":null,"end-area":null,"disambiguation":"","aliases":[],"tags":[],"relations":[],"url-rels":[]}"#;
    let line2 = r#"{"id":"mbid-2","name":"Artist Two","sort-name":"Two, Artist","type":"Group","gender":null,"life-span":{"begin":"1990","end":"2000","ended":true},"area":{"name":"Berlin"},"begin-area":null,"end-area":null,"disambiguation":"","aliases":[],"tags":[],"relations":[],"url-rels":[]}"#;
    let content = format!("{}\n{}\n", line1, line2);

    let mut temp_file = NamedTempFile::new().unwrap();
    let mut encoder = XzEncoder::new(Vec::new(), 1);
    encoder.write_all(content.as_bytes()).unwrap();
    let compressed = encoder.finish().unwrap();
    temp_file.write_all(&compressed).unwrap();
    temp_file.flush().unwrap();

    let rt = tokio::runtime::Builder::new_current_thread().enable_all().build().unwrap();
    let (sender, mut receiver) = mpsc::channel(10);
    let count = parse_mb_jsonl_file(temp_file.path(), DataType::Artists, sender, None).unwrap();
    assert_eq!(count, 2);

    let msg1 = rt.block_on(receiver.recv()).unwrap();
    assert_eq!(msg1.id, "mbid-1");

    let msg2 = rt.block_on(receiver.recv()).unwrap();
    assert_eq!(msg2.id, "mbid-2");
    assert_eq!(msg2.data["area"], "Berlin");
}

#[test]
fn test_parse_mb_jsonl_file_skips_malformed_lines() {
    use std::io::Write;
    use tempfile::NamedTempFile;
    use tokio::sync::mpsc;
    use xz2::write::XzEncoder;

    let good = r#"{"id":"ok-id","name":"Good Artist","sort-name":"Artist, Good","type":"Person","gender":null,"life-span":{"begin":null,"end":null,"ended":false},"area":null,"begin-area":null,"end-area":null,"disambiguation":"","aliases":[],"tags":[],"relations":[],"url-rels":[]}"#;
    let content = format!("not json at all\n{}\n{{broken}}\n", good);

    let mut temp_file = NamedTempFile::new().unwrap();
    let mut encoder = XzEncoder::new(Vec::new(), 1);
    encoder.write_all(content.as_bytes()).unwrap();
    let compressed = encoder.finish().unwrap();
    temp_file.write_all(&compressed).unwrap();
    temp_file.flush().unwrap();

    let rt = tokio::runtime::Builder::new_current_thread().enable_all().build().unwrap();
    let (sender, mut receiver) = mpsc::channel(10);
    let count = parse_mb_jsonl_file(temp_file.path(), DataType::Artists, sender, None).unwrap();
    // Only the good line should be counted
    assert_eq!(count, 1);
    let msg = rt.block_on(receiver.recv()).unwrap();
    assert_eq!(msg.id, "ok-id");
}

#[test]
fn test_parse_mb_jsonl_file_masters_returns_zero() {
    use std::io::Write;
    use tempfile::NamedTempFile;
    use tokio::sync::mpsc;
    use xz2::write::XzEncoder;

    let mut temp_file = NamedTempFile::new().unwrap();
    let mut encoder = XzEncoder::new(Vec::new(), 1);
    encoder.write_all(b"some content\n").unwrap();
    let compressed = encoder.finish().unwrap();
    temp_file.write_all(&compressed).unwrap();
    temp_file.flush().unwrap();

    let (sender, _receiver) = mpsc::channel(10);
    let count = parse_mb_jsonl_file(temp_file.path(), DataType::Masters, sender, None).unwrap();
    assert_eq!(count, 0);
}

// ─── build_mbid_discogs_map_from_file ─────────────────────────────────────────

#[test]
fn test_build_mbid_discogs_map() {
    use std::io::Write;
    use tempfile::NamedTempFile;
    use xz2::write::XzEncoder;

    // Line 1: has a Discogs url-rel → should appear in map
    let line_with_discogs = r#"{"id":"artist-mbid-1","name":"Artist With Discogs","sort-name":"With Discogs, Artist","type":"Person","gender":null,"life-span":{"begin":null,"end":null,"ended":false},"area":null,"begin-area":null,"end-area":null,"disambiguation":"","aliases":[],"tags":[],"relations":[],"url-rels":[{"type":"discogs","url":{"resource":"https://www.discogs.com/artist/12345"}}]}"#;
    // Line 2: no Discogs url-rel → should NOT appear in map
    let line_without_discogs = r#"{"id":"artist-mbid-2","name":"Artist Without Discogs","sort-name":"Without Discogs, Artist","type":"Person","gender":null,"life-span":{"begin":null,"end":null,"ended":false},"area":null,"begin-area":null,"end-area":null,"disambiguation":"","aliases":[],"tags":[],"relations":[],"url-rels":[{"type":"wikipedia","url":{"resource":"https://en.wikipedia.org/wiki/Some_Artist"}}]}"#;
    let content = format!("{}\n{}\n", line_with_discogs, line_without_discogs);

    let mut temp_file = NamedTempFile::new().unwrap();
    let mut encoder = XzEncoder::new(Vec::new(), 1);
    encoder.write_all(content.as_bytes()).unwrap();
    let compressed = encoder.finish().unwrap();
    temp_file.write_all(&compressed).unwrap();
    temp_file.flush().unwrap();

    let map = build_mbid_discogs_map_from_file(temp_file.path(), "artist").unwrap();
    assert_eq!(map.len(), 1);
    assert_eq!(map.get("artist-mbid-1"), Some(&12345i64));
    assert!(!map.contains_key("artist-mbid-2"));
}

// ─── enrich_relations ─────────────────────────────────────────────────────────

#[test]
fn test_enrich_relations_with_map() {
    use std::collections::HashMap;

    let mut map = HashMap::new();
    map.insert("target-mbid-1".to_string(), 200i64);

    let relations = vec![
        serde_json::json!({
            "type": "collaboration",
            "target": {"id": "target-mbid-1", "name": "Artist B"}
        }),
        serde_json::json!({
            "type": "tribute",
            "target": {"id": "target-mbid-2", "name": "Artist C"}
        }),
    ];

    let enriched = enrich_relations(relations, &map);
    assert_eq!(enriched.len(), 2);
    assert_eq!(enriched[0]["target_discogs_artist_id"], 200);
    assert!(enriched[1]["target_discogs_artist_id"].is_null());
    // Original fields preserved
    assert_eq!(enriched[0]["type"], "collaboration");
    assert_eq!(enriched[1]["type"], "tribute");
}

#[test]
fn test_enrich_relations_empty() {
    use std::collections::HashMap;
    let map: HashMap<String, i64> = HashMap::new();
    let enriched = enrich_relations(vec![], &map);
    assert!(enriched.is_empty());
}

#[test]
fn test_enrich_relations_no_target_id() {
    use std::collections::HashMap;
    let mut map = HashMap::new();
    map.insert("some-mbid".to_string(), 999i64);

    // Relation with no "target" field at all — should get null
    let relations = vec![serde_json::json!({"type": "misc"})];
    let enriched = enrich_relations(relations, &map);
    assert_eq!(enriched.len(), 1);
    assert!(enriched[0]["target_discogs_artist_id"].is_null());
}

// ─── parse_mb_jsonl_file with discogs_map ─────────────────────────────────────

#[test]
fn test_parse_mb_jsonl_file_with_discogs_map_enriches_relations() {
    use std::collections::HashMap;
    use std::io::Write;
    use tempfile::NamedTempFile;
    use tokio::sync::mpsc;
    use xz2::write::XzEncoder;

    let line = r#"{"id":"mbid-artist","name":"Test Artist","sort-name":"Artist, Test","type":"Person","gender":null,"life-span":{"begin":null,"end":null,"ended":false},"area":null,"begin-area":null,"end-area":null,"disambiguation":"","aliases":[],"tags":[],"relations":[{"type":"collaboration","target":{"id":"target-mbid-A","name":"Collab Artist"}}],"url-rels":[]}"#;
    let content = format!("{}\n", line);

    let mut temp_file = NamedTempFile::new().unwrap();
    let mut encoder = XzEncoder::new(Vec::new(), 1);
    encoder.write_all(content.as_bytes()).unwrap();
    let compressed = encoder.finish().unwrap();
    temp_file.write_all(&compressed).unwrap();
    temp_file.flush().unwrap();

    let mut map = HashMap::new();
    map.insert("target-mbid-A".to_string(), 777i64);

    let rt = tokio::runtime::Builder::new_current_thread().enable_all().build().unwrap();
    let (sender, mut receiver) = mpsc::channel(10);
    let count = parse_mb_jsonl_file(temp_file.path(), DataType::Artists, sender, Some(&map)).unwrap();
    assert_eq!(count, 1);

    let msg = rt.block_on(receiver.recv()).unwrap();
    let relations = msg.data["relations"].as_array().unwrap();
    assert_eq!(relations.len(), 1);
    assert_eq!(relations[0]["target_discogs_artist_id"], 777);
}

// ─── find_discogs_id edge case: discogs type but no url resource ─────────────

#[test]
fn test_find_discogs_id_discogs_type_but_no_url() {
    let url_rels = vec![serde_json::json!({"type": "discogs", "url": {}})];
    let result = find_discogs_id(&url_rels, "artist");
    assert!(result.is_null());
}

#[test]
fn test_find_discogs_id_discogs_type_but_empty_resource() {
    let url_rels = vec![serde_json::json!({"type": "discogs", "url": {"resource": ""}})];
    let result = find_discogs_id(&url_rels, "artist");
    assert!(result.is_null());
}

// ─── parse_mb_jsonl_file: Labels and Releases branches ──────────────────────

#[test]
fn test_parse_mb_jsonl_file_labels() {
    use std::io::Write;
    use tempfile::NamedTempFile;
    use tokio::sync::mpsc;
    use xz2::write::XzEncoder;

    let line = r#"{"id":"label-mbid-1","name":"Test Label","type":"Original Production","label-code":100,"life-span":{"begin":"1950","end":null,"ended":false},"area":{"name":"Germany"},"disambiguation":"","relations":[],"url-rels":[{"type":"discogs","url":{"resource":"https://www.discogs.com/label/9999"}}]}"#;
    let content = format!("{}\n", line);

    let mut temp_file = NamedTempFile::new().unwrap();
    let mut encoder = XzEncoder::new(Vec::new(), 1);
    encoder.write_all(content.as_bytes()).unwrap();
    let compressed = encoder.finish().unwrap();
    temp_file.write_all(&compressed).unwrap();
    temp_file.flush().unwrap();

    let rt = tokio::runtime::Builder::new_current_thread().enable_all().build().unwrap();
    let (sender, mut receiver) = mpsc::channel(10);
    let count = parse_mb_jsonl_file(temp_file.path(), DataType::Labels, sender, None).unwrap();
    assert_eq!(count, 1);

    let msg = rt.block_on(receiver.recv()).unwrap();
    assert_eq!(msg.id, "label-mbid-1");
    assert_eq!(msg.data["discogs_label_id"], 9999);
    assert_eq!(msg.data["name"], "Test Label");
}

#[test]
fn test_parse_mb_jsonl_file_releases() {
    use std::io::Write;
    use tempfile::NamedTempFile;
    use tokio::sync::mpsc;
    use xz2::write::XzEncoder;

    let line = r#"{"id":"release-mbid-1","title":"Test Album","barcode":"1234567890","status":"Official","release-group":{"id":"rg-mbid-1"},"relations":[],"url-rels":[{"type":"discogs","url":{"resource":"https://www.discogs.com/release/55555"}}]}"#;
    let content = format!("{}\n", line);

    let mut temp_file = NamedTempFile::new().unwrap();
    let mut encoder = XzEncoder::new(Vec::new(), 1);
    encoder.write_all(content.as_bytes()).unwrap();
    let compressed = encoder.finish().unwrap();
    temp_file.write_all(&compressed).unwrap();
    temp_file.flush().unwrap();

    let rt = tokio::runtime::Builder::new_current_thread().enable_all().build().unwrap();
    let (sender, mut receiver) = mpsc::channel(10);
    let count = parse_mb_jsonl_file(temp_file.path(), DataType::Releases, sender, None).unwrap();
    assert_eq!(count, 1);

    let msg = rt.block_on(receiver.recv()).unwrap();
    assert_eq!(msg.id, "release-mbid-1");
    assert_eq!(msg.data["discogs_release_id"], 55555);
    assert_eq!(msg.data["name"], "Test Album");
}

// ─── parse_mb_jsonl_file: empty lines mixed with valid data ─────────────────

#[test]
fn test_parse_mb_jsonl_file_with_empty_lines() {
    use std::io::Write;
    use tempfile::NamedTempFile;
    use tokio::sync::mpsc;
    use xz2::write::XzEncoder;

    let good = r#"{"id":"ok-id","name":"Good Artist","sort-name":"Artist, Good","type":"Person","gender":null,"life-span":{"begin":null,"end":null,"ended":false},"area":null,"begin-area":null,"end-area":null,"disambiguation":"","aliases":[],"tags":[],"relations":[],"url-rels":[]}"#;
    // Mix empty lines, whitespace-only lines, and valid data
    let content = format!("\n\n{}\n   \n\n", good);

    let mut temp_file = NamedTempFile::new().unwrap();
    let mut encoder = XzEncoder::new(Vec::new(), 1);
    encoder.write_all(content.as_bytes()).unwrap();
    let compressed = encoder.finish().unwrap();
    temp_file.write_all(&compressed).unwrap();
    temp_file.flush().unwrap();

    let rt = tokio::runtime::Builder::new_current_thread().enable_all().build().unwrap();
    let (sender, mut receiver) = mpsc::channel(10);
    let count = parse_mb_jsonl_file(temp_file.path(), DataType::Artists, sender, None).unwrap();
    assert_eq!(count, 1);

    let msg = rt.block_on(receiver.recv()).unwrap();
    assert_eq!(msg.id, "ok-id");
}

// ─── build_mbid_discogs_map_from_file: malformed lines ──────────────────────

#[test]
fn test_build_mbid_discogs_map_with_malformed_lines() {
    use std::io::Write;
    use tempfile::NamedTempFile;
    use xz2::write::XzEncoder;

    let valid_line = r#"{"id":"mbid-good","url-rels":[{"type":"discogs","url":{"resource":"https://www.discogs.com/artist/42"}}]}"#;
    let no_id_line = r#"{"name":"no id field","url-rels":[{"type":"discogs","url":{"resource":"https://www.discogs.com/artist/99"}}]}"#;
    let invalid_json = "not json at all";
    // Mix: valid, invalid JSON, empty line, line with no id, valid again
    let content = format!("{}\n{}\n\n{}\n{}\n", valid_line, invalid_json, no_id_line, valid_line);

    let mut temp_file = NamedTempFile::new().unwrap();
    let mut encoder = XzEncoder::new(Vec::new(), 1);
    encoder.write_all(content.as_bytes()).unwrap();
    let compressed = encoder.finish().unwrap();
    temp_file.write_all(&compressed).unwrap();
    temp_file.flush().unwrap();

    let map = build_mbid_discogs_map_from_file(temp_file.path(), "artist").unwrap();
    // Only the valid line with id should appear (duplicated = 1 entry)
    assert_eq!(map.len(), 1);
    assert_eq!(map.get("mbid-good"), Some(&42i64));
}

#[test]
fn test_build_mbid_discogs_map_nonexistent_file() {
    let result = build_mbid_discogs_map_from_file(std::path::Path::new("/tmp/nonexistent-file.jsonl.xz"), "artist");
    assert!(result.is_err());
}

// ─── parse_mb_jsonl_file: receiver dropped ──────────────────────────────────

#[test]
fn test_parse_mb_jsonl_file_receiver_dropped() {
    use std::io::Write;
    use tempfile::NamedTempFile;
    use tokio::sync::mpsc;
    use xz2::write::XzEncoder;

    // Create a file with multiple valid lines
    let line = r#"{"id":"mbid-1","name":"Artist","sort-name":"Artist","type":"Person","gender":null,"life-span":{"begin":null,"end":null,"ended":false},"area":null,"begin-area":null,"end-area":null,"disambiguation":"","aliases":[],"tags":[],"relations":[],"url-rels":[]}"#;
    let content = format!("{}\n{}\n{}\n{}\n{}\n", line, line, line, line, line);

    let mut temp_file = NamedTempFile::new().unwrap();
    let mut encoder = XzEncoder::new(Vec::new(), 1);
    encoder.write_all(content.as_bytes()).unwrap();
    let compressed = encoder.finish().unwrap();
    temp_file.write_all(&compressed).unwrap();
    temp_file.flush().unwrap();

    // Create channel and immediately drop receiver
    let (sender, receiver) = mpsc::channel(1);
    drop(receiver);

    // Should stop gracefully without error — returns count of records sent before drop
    let count = parse_mb_jsonl_file(temp_file.path(), DataType::Artists, sender, None).unwrap();
    // Count should be 0 since the very first blocking_send should fail (receiver dropped)
    assert_eq!(count, 0);
}
