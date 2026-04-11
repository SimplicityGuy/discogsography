use serde_json::Value;

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

/// Public entry point: normalize a record based on its data type.
pub fn normalize_record(data_type: &str, record: &mut Value) {
    match data_type {
        _ => {
            // Suppress unused variable warnings until type-specific normalizers are added
            let _ = (data_type, record);
        }
    }
}

#[cfg(test)]
#[path = "tests/normalize_tests.rs"]
mod tests;
