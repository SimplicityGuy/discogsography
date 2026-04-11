use serde_json::json;

use crate::normalize::{ensure_list, strip_at_prefixes, unwrap_container};

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
