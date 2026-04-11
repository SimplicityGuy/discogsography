use serde_json::json;

use crate::normalize::{ensure_list, normalize_record, strip_at_prefixes, unwrap_container};

// ── strip_at_prefixes ───────────────────────────────────────────────

#[test]
fn test_strip_at_prefixes_flat_object() {
    let mut val = json!({"@id": "123", "@name": "Test"});
    strip_at_prefixes(&mut val);
    assert_eq!(val, json!({"id": "123", "name": "Test"}));
}

#[test]
fn test_strip_at_prefixes_no_at_keys() {
    let mut val = json!({"id": "123", "name": "Test"});
    strip_at_prefixes(&mut val);
    assert_eq!(val, json!({"id": "123", "name": "Test"}));
}

#[test]
fn test_strip_at_prefixes_hash_text_to_name() {
    let mut val = json!({"@id": "123", "#text": "Some Name"});
    strip_at_prefixes(&mut val);
    assert_eq!(val, json!({"id": "123", "name": "Some Name"}));
}

#[test]
fn test_strip_at_prefixes_no_op_when_name_exists() {
    let mut val = json!({"name": "Existing", "#text": "Ignored"});
    strip_at_prefixes(&mut val);
    // #text should NOT be renamed because name already exists
    assert_eq!(val, json!({"name": "Existing", "#text": "Ignored"}));
}

#[test]
fn test_strip_at_prefixes_non_object() {
    let mut val = json!("just a string");
    strip_at_prefixes(&mut val);
    assert_eq!(val, json!("just a string"));
}

// ── unwrap_container ────────────────────────────────────────────────

#[test]
fn test_unwrap_container_dict_with_key() {
    let val = json!({"name": [{"@id": "1"}, {"@id": "2"}]});
    let result = unwrap_container(&val, "name");
    assert_eq!(result, json!([{"@id": "1"}, {"@id": "2"}]));
}

#[test]
fn test_unwrap_container_single_item() {
    let val = json!({"name": {"@id": "1"}});
    let result = unwrap_container(&val, "name");
    assert_eq!(result, json!([{"@id": "1"}]));
}

#[test]
fn test_unwrap_container_already_list() {
    let val = json!([1, 2, 3]);
    let result = unwrap_container(&val, "name");
    assert_eq!(result, json!([1, 2, 3]));
}

#[test]
fn test_unwrap_container_null() {
    let val = json!(null);
    let result = unwrap_container(&val, "name");
    assert_eq!(result, json!([]));
}

#[test]
fn test_unwrap_container_dict_without_key() {
    let val = json!({"other": "value"});
    let result = unwrap_container(&val, "name");
    assert_eq!(result, json!([]));
}

// ── ensure_list ─────────────────────────────────────────────────────

#[test]
fn test_ensure_list_array() {
    let val = json!([1, 2, 3]);
    assert_eq!(ensure_list(&val), json!([1, 2, 3]));
}

#[test]
fn test_ensure_list_single_value() {
    let val = json!("hello");
    assert_eq!(ensure_list(&val), json!(["hello"]));
}

#[test]
fn test_ensure_list_null() {
    let val = json!(null);
    assert_eq!(ensure_list(&val), json!([]));
}

// ── normalize_record: artists ───────────────────────────────────────

#[test]
fn test_artist_basic() {
    let mut record = json!({"id": "123", "name": "Artist", "sha256": "abc"});
    normalize_record("artists", &mut record);
    assert_eq!(record["id"], json!("123"));
    assert_eq!(record["name"], json!("Artist"));
    assert_eq!(record["sha256"], json!("abc"));
}

#[test]
fn test_artist_with_members() {
    let mut record = json!({
        "id": "123",
        "name": "Band",
        "members": {"name": [{"@id": "10", "#text": "John"}, {"@id": "20", "#text": "Jane"}]}
    });
    normalize_record("artists", &mut record);
    assert_eq!(
        record["members"],
        json!([{"id": "10", "name": "John"}, {"id": "20", "name": "Jane"}])
    );
}

#[test]
fn test_artist_with_groups() {
    let mut record = json!({
        "id": "10",
        "name": "John",
        "groups": {"name": [{"@id": "123", "#text": "Band"}]}
    });
    normalize_record("artists", &mut record);
    assert_eq!(record["groups"], json!([{"id": "123", "name": "Band"}]));
}

#[test]
fn test_artist_with_aliases() {
    let mut record = json!({
        "id": "10",
        "name": "DJ X",
        "aliases": {"name": [{"@id": "20", "#text": "DJ Y"}]}
    });
    normalize_record("artists", &mut record);
    assert_eq!(record["aliases"], json!([{"id": "20", "name": "DJ Y"}]));
}

#[test]
fn test_artist_single_member() {
    let mut record = json!({
        "id": "123",
        "name": "Band",
        "members": {"name": {"@id": "10", "#text": "John"}}
    });
    normalize_record("artists", &mut record);
    assert_eq!(record["members"], json!([{"id": "10", "name": "John"}]));
}

#[test]
fn test_artist_no_members() {
    let mut record = json!({"id": "123", "name": "Artist"});
    normalize_record("artists", &mut record);
    assert!(record.get("members").is_none());
}

// ── normalize_record: labels ────────────────────────────────────────

#[test]
fn test_label_basic() {
    let mut record = json!({"id": "1", "name": "Warp Records"});
    normalize_record("labels", &mut record);
    assert_eq!(record["id"], json!("1"));
    assert_eq!(record["name"], json!("Warp Records"));
}

#[test]
fn test_label_parent_label() {
    let mut record = json!({
        "id": "1",
        "name": "Sub Label",
        "parentLabel": {"@id": "100", "#text": "Parent"}
    });
    normalize_record("labels", &mut record);
    assert_eq!(record["parentLabel"], json!({"id": "100", "name": "Parent"}));
}

#[test]
fn test_label_sublabels_container() {
    let mut record = json!({
        "id": "1",
        "name": "Parent",
        "sublabels": {"label": [{"@id": "10", "#text": "Sub A"}, {"@id": "20", "#text": "Sub B"}]}
    });
    normalize_record("labels", &mut record);
    assert_eq!(
        record["sublabels"],
        json!([{"id": "10", "name": "Sub A"}, {"id": "20", "name": "Sub B"}])
    );
}

#[test]
fn test_label_single_sublabel() {
    let mut record = json!({
        "id": "1",
        "name": "Parent",
        "sublabels": {"label": {"@id": "10", "#text": "Sub A"}}
    });
    normalize_record("labels", &mut record);
    assert_eq!(record["sublabels"], json!([{"id": "10", "name": "Sub A"}]));
}

#[test]
fn test_label_no_parent() {
    let mut record = json!({"id": "1", "name": "Label"});
    normalize_record("labels", &mut record);
    assert!(record.get("parentLabel").is_none());
}

// ── normalize_record: masters ───────────────────────────────────────

#[test]
fn test_master_basic() {
    let mut record = json!({"@id": "5000", "title": "Album"});
    normalize_record("masters", &mut record);
    assert_eq!(record["id"], json!("5000"));
    assert_eq!(record["title"], json!("Album"));
    assert!(record.get("@id").is_none());
}

#[test]
fn test_master_artists_container() {
    let mut record = json!({
        "@id": "5000",
        "title": "Album",
        "artists": {"artist": [{"@id": "1", "#text": "Artist A"}]}
    });
    normalize_record("masters", &mut record);
    assert_eq!(record["artists"], json!([{"id": "1", "name": "Artist A"}]));
}

#[test]
fn test_master_genres_container() {
    let mut record = json!({
        "@id": "5000",
        "title": "Album",
        "genres": {"genre": ["Rock", "Pop"]}
    });
    normalize_record("masters", &mut record);
    assert_eq!(record["genres"], json!(["Rock", "Pop"]));
}

#[test]
fn test_master_styles_single() {
    let mut record = json!({
        "@id": "5000",
        "title": "Album",
        "styles": {"style": "Ambient"}
    });
    normalize_record("masters", &mut record);
    assert_eq!(record["styles"], json!(["Ambient"]));
}

#[test]
fn test_master_single_artist() {
    let mut record = json!({
        "@id": "5000",
        "title": "Album",
        "artists": {"artist": {"@id": "1", "#text": "Solo"}}
    });
    normalize_record("masters", &mut record);
    assert_eq!(record["artists"], json!([{"id": "1", "name": "Solo"}]));
}

#[test]
fn test_master_no_genres() {
    let mut record = json!({"@id": "5000", "title": "Album"});
    normalize_record("masters", &mut record);
    assert!(record.get("genres").is_none());
}
