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

// ── normalize_record: releases ──────────────────────────────────────

#[test]
fn test_release_basic() {
    let mut record = json!({"@id": "999", "title": "Single", "released": "2024", "country": "US"});
    normalize_record("releases", &mut record);
    assert_eq!(record["id"], json!("999"));
    assert_eq!(record["title"], json!("Single"));
    assert_eq!(record["released"], json!("2024"));
    assert_eq!(record["country"], json!("US"));
    assert!(record.get("@id").is_none());
}

#[test]
fn test_release_artists() {
    let mut record = json!({
        "@id": "999",
        "artists": {"artist": [{"@id": "1", "#text": "A"}]}
    });
    normalize_record("releases", &mut record);
    assert_eq!(record["artists"], json!([{"id": "1", "name": "A"}]));
}

#[test]
fn test_release_labels() {
    let mut record = json!({
        "@id": "999",
        "labels": {"label": [{"@id": "10", "@name": "Lab", "@catno": "CAT01"}]}
    });
    normalize_record("releases", &mut record);
    assert_eq!(
        record["labels"],
        json!([{"id": "10", "name": "Lab", "catno": "CAT01"}])
    );
}

#[test]
fn test_release_master_id_dict() {
    let mut record = json!({
        "@id": "999",
        "master_id": {"#text": "5000", "@is_main_release": "true"}
    });
    normalize_record("releases", &mut record);
    assert_eq!(record["master_id"], json!("5000"));
}

#[test]
fn test_release_master_id_string() {
    let mut record = json!({"@id": "999", "master_id": "5000"});
    normalize_record("releases", &mut record);
    assert_eq!(record["master_id"], json!("5000"));
}

#[test]
fn test_release_genres_styles() {
    let mut record = json!({
        "@id": "999",
        "genres": {"genre": ["Rock", "Pop"]},
        "styles": {"style": "Indie"}
    });
    normalize_record("releases", &mut record);
    assert_eq!(record["genres"], json!(["Rock", "Pop"]));
    assert_eq!(record["styles"], json!(["Indie"]));
}

#[test]
fn test_release_extraartists() {
    let mut record = json!({
        "@id": "999",
        "extraartists": {"artist": [{"@id": "5", "#text": "Producer"}]}
    });
    normalize_record("releases", &mut record);
    assert_eq!(
        record["extraartists"],
        json!([{"id": "5", "name": "Producer"}])
    );
}

#[test]
fn test_release_formats() {
    let mut record = json!({
        "@id": "999",
        "formats": {"format": [{"@name": "Vinyl", "@qty": "1"}]}
    });
    normalize_record("releases", &mut record);
    assert_eq!(record["formats"], json!([{"name": "Vinyl", "qty": "1"}]));
}

#[test]
fn test_release_single_format() {
    let mut record = json!({
        "@id": "999",
        "formats": {"format": {"@name": "CD", "@qty": "1"}}
    });
    normalize_record("releases", &mut record);
    assert_eq!(record["formats"], json!([{"name": "CD", "qty": "1"}]));
}

#[test]
fn test_release_format_with_descriptions() {
    let mut record = json!({
        "@id": "999",
        "formats": {"format": {"@name": "Vinyl", "@qty": "1", "descriptions": {"description": ["LP", "Album"]}}}
    });
    normalize_record("releases", &mut record);
    let fmt = &record["formats"][0];
    assert_eq!(fmt["name"], json!("Vinyl"));
    assert_eq!(fmt["qty"], json!("1"));
    // descriptions stay as-is (child object); strip_at_prefixes only touches top-level keys
    assert!(fmt.get("descriptions").is_some());
}

#[test]
fn test_release_full_pipeline() {
    let mut record = json!({
        "@id": "12345",
        "title": "Full Album",
        "released": "2024-01-01",
        "country": "UK",
        "artists": {"artist": [{"@id": "1", "#text": "Band"}, {"@id": "2", "#text": "Featured"}]},
        "labels": {"label": [{"@id": "10", "@name": "BigLabel", "@catno": "BIG001"}]},
        "master_id": {"#text": "5000", "@is_main_release": "true"},
        "genres": {"genre": ["Electronic", "Rock"]},
        "styles": {"style": "Synth-pop"},
        "extraartists": {"artist": {"@id": "99", "#text": "Mixer"}},
        "formats": {"format": [{"@name": "CD", "@qty": "1"}, {"@name": "Vinyl", "@qty": "2"}]}
    });
    normalize_record("releases", &mut record);

    assert_eq!(record["id"], json!("12345"));
    assert!(record.get("@id").is_none());
    assert_eq!(record["title"], json!("Full Album"));
    assert_eq!(record["released"], json!("2024-01-01"));
    assert_eq!(record["country"], json!("UK"));
    assert_eq!(
        record["artists"],
        json!([{"id": "1", "name": "Band"}, {"id": "2", "name": "Featured"}])
    );
    assert_eq!(
        record["labels"],
        json!([{"id": "10", "name": "BigLabel", "catno": "BIG001"}])
    );
    assert_eq!(record["master_id"], json!("5000"));
    assert_eq!(record["genres"], json!(["Electronic", "Rock"]));
    assert_eq!(record["styles"], json!(["Synth-pop"]));
    assert_eq!(
        record["extraartists"],
        json!([{"id": "99", "name": "Mixer"}])
    );
    assert_eq!(
        record["formats"],
        json!([{"name": "CD", "qty": "1"}, {"name": "Vinyl", "qty": "2"}])
    );
}

// ── edge cases from code review ─────────────────────────────────────

#[test]
fn test_normalize_artist_empty_members_container() {
    let mut record = json!({
        "id": "1",
        "name": "Solo",
        "members": {"name": []}
    });
    normalize_record("artists", &mut record);
    assert!(record.get("members").is_none(), "empty members should be removed");
}

#[test]
fn test_normalize_release_master_id_null() {
    let mut record = json!({
        "@id": "1",
        "title": "Test",
        "master_id": null
    });
    normalize_record("releases", &mut record);
    // null master_id stays as-is (not an object, no extraction)
    assert_eq!(record["master_id"], json!(null));
}

#[test]
fn test_normalize_release_master_id_integer() {
    let mut record = json!({
        "@id": "1",
        "title": "Test",
        "master_id": 5000
    });
    normalize_record("releases", &mut record);
    assert_eq!(record["master_id"], json!(5000));
}

// ── coverage: defensive branches ────────────────────────────────────

#[test]
fn test_unwrap_container_bare_string() {
    // Line 48: non-null/non-array/non-object value wraps in array
    let input = json!("hello");
    let result = unwrap_container(&input, "key");
    assert_eq!(result, json!(["hello"]));
}

#[test]
fn test_normalize_item_list_with_string_items() {
    // Line 94: string items become {"id": value}
    let input = json!({"name": ["123", "456"]});
    let result = crate::normalize::normalize_item_list(&input, "name");
    assert_eq!(result, json!([{"id": "123"}, {"id": "456"}]));
}

#[test]
fn test_normalize_item_list_with_number_items() {
    // Line 96: non-object/non-string items pass through
    let input = json!({"name": [42, true]});
    let result = crate::normalize::normalize_item_list(&input, "name");
    assert_eq!(result, json!([42, true]));
}

#[test]
fn test_normalize_artist_non_object() {
    // Line 106: non-object record is a no-op
    let mut record = json!("not an object");
    normalize_record("artists", &mut record);
    assert_eq!(record, json!("not an object"));
}

#[test]
fn test_normalize_label_non_object() {
    // Line 120: non-object record is a no-op
    let mut record = json!(null);
    normalize_record("labels", &mut record);
    assert_eq!(record, json!(null));
}

#[test]
fn test_normalize_master_non_object() {
    // Line 147: non-object record (after strip_at_prefixes) is a no-op
    let mut record = json!(42);
    normalize_record("masters", &mut record);
    assert_eq!(record, json!(42));
}

#[test]
fn test_normalize_release_non_object() {
    // Line 167: non-object record is a no-op
    let mut record = json!([1, 2, 3]);
    normalize_record("releases", &mut record);
    assert_eq!(record, json!([1, 2, 3]));
}

#[test]
fn test_normalize_release_format_non_object_item() {
    // Line 219: non-object format items pass through
    let mut record = json!({
        "@id": "1",
        "title": "Test",
        "formats": {"format": ["StringFormat", 42]}
    });
    normalize_record("releases", &mut record);
    let formats = record["formats"].as_array().unwrap();
    assert_eq!(formats.len(), 2);
    assert_eq!(formats[0], json!("StringFormat"));
    assert_eq!(formats[1], json!(42));
}

// ── unknown data type -> no-op ──────────────────────────────────────

#[test]
fn test_unknown_type_noop() {
    let mut record = json!({"@id": "1", "name": "Test"});
    let original = record.clone();
    normalize_record("unknown", &mut record);
    assert_eq!(record, original);
}
