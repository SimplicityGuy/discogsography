use serde_json::{Map, Value};

/// Remove `@` prefixes from all keys in an object and rename `#text` to `name`.
pub fn strip_at_prefixes(value: &mut Value) {
    let Some(map) = value.as_object_mut() else {
        return;
    };

    let keys: Vec<String> = map.keys().cloned().collect();
    let mut renames: Vec<(String, String)> = Vec::new();

    for key in &keys {
        if let Some(stripped) = key.strip_prefix('@') {
            renames.push((key.clone(), stripped.to_string()));
        } else if key == "#text" && !keys.contains(&"name".to_string()) {
            // Only rename #text -> name if "name" doesn't already exist
            renames.push((key.clone(), "name".to_string()));
        }
    }

    for (old, new) in renames {
        if let Some(val) = map.remove(&old) {
            map.insert(new, val);
        }
    }
}

/// Unwrap a container value into an array.
///
/// - null -> empty array
/// - already array -> clone
/// - object with `key` -> ensure_list of that value
/// - object without `key` -> empty array
/// - other -> wrap in single-item array
pub fn unwrap_container(value: &Value, key: &str) -> Value {
    match value {
        Value::Null => Value::Array(vec![]),
        Value::Array(_) => value.clone(),
        Value::Object(map) => {
            if let Some(inner) = map.get(key) {
                ensure_list(inner)
            } else {
                Value::Array(vec![])
            }
        }
        _ => Value::Array(vec![value.clone()]),
    }
}

/// Ensure a value is an array.
///
/// - array -> clone
/// - null -> empty array
/// - other -> wrap in single-item array
pub fn ensure_list(value: &Value) -> Value {
    match value {
        Value::Array(_) => value.clone(),
        Value::Null => Value::Array(vec![]),
        _ => Value::Array(vec![value.clone()]),
    }
}

/// Insert `value` into `map` under `key` only if it is a non-empty array.
fn insert_if_nonempty(map: &mut Map<String, Value>, key: &str, value: Value) {
    if let Some(arr) = value.as_array()
        && !arr.is_empty()
    {
        map.insert(key.to_string(), value);
    }
}

/// Normalize a list of items from a container.
///
/// Uses `unwrap_container` to extract items, then for each:
/// - objects get `strip_at_prefixes` applied
/// - strings get wrapped as `{"id": value}`
fn normalize_item_list(value: &Value, container_key: &str) -> Value {
    let items = unwrap_container(value, container_key);
    let Some(arr) = items.as_array() else {
        return Value::Array(vec![]);
    };

    let result: Vec<Value> = arr
        .iter()
        .map(|item| match item {
            Value::Object(_) => {
                let mut cloned = item.clone();
                strip_at_prefixes(&mut cloned);
                cloned
            }
            Value::String(_) => {
                serde_json::json!({"id": item})
            }
            _ => item.clone(),
        })
        .collect();

    Value::Array(result)
}

/// Normalize an artist record.
fn normalize_artist(record: &mut Value) {
    let Some(map) = record.as_object_mut() else {
        return;
    };

    for field in &["members", "groups", "aliases"] {
        if let Some(val) = map.remove(*field) {
            let normalized = normalize_item_list(&val, "name");
            insert_if_nonempty(map, field, normalized);
        }
    }
}

/// Normalize a label record.
fn normalize_label(record: &mut Value) {
    let Some(map) = record.as_object_mut() else {
        return;
    };

    // parentLabel: if present and object, strip_at_prefixes
    if let Some(parent) = map.get_mut("parentLabel")
        && parent.is_object()
    {
        strip_at_prefixes(parent);
    }

    // sublabels: normalize_item_list with key "label"
    if let Some(val) = map.remove("sublabels") {
        let normalized = normalize_item_list(&val, "label");
        insert_if_nonempty(map, "sublabels", normalized);
    }
}

/// Public entry point: normalize a record based on its data type.
pub fn normalize_record(data_type: &str, record: &mut Value) {
    match data_type {
        "artists" => normalize_artist(record),
        "labels" => normalize_label(record),
        _ => {}
    }
}

#[cfg(test)]
#[path = "tests/normalize_tests.rs"]
mod tests;
