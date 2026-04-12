# Normalizer-to-Extractor Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move JSON normalization from Python consumers into the Rust extractor so it runs once at extraction time instead of redundantly in every consumer.

**Architecture:** A new `normalize.rs` module in the extractor transforms XML-shaped JSON (with `@` prefixes, nested containers, `#text` wrappers) into flat, consumer-ready JSON. Called in the validator pipeline after `apply_filters()` and before `calculate_content_hash()`. The Python `data_normalizer.py` is then gutted to only keep `_parse_year_int()` and a thin `normalize_record()` wrapper.

**Tech Stack:** Rust (serde_json), Python 3.13+

---

### Task 1: Create `normalize.rs` — Generic Helpers

**Files:**
- Create: `extractor/src/normalize.rs`
- Create: `extractor/src/tests/normalize_tests.rs`
- Modify: `extractor/src/lib.rs:11` (add module declaration)

- [ ] **Step 1: Write failing tests for generic helpers**

Create `extractor/src/tests/normalize_tests.rs`:

```rust
use serde_json::{json, Value};

use crate::normalize::{ensure_list, strip_at_prefixes, unwrap_container};

#[test]
fn test_strip_at_prefixes_flat() {
    let mut obj = json!({"@id": "123", "@name": "Test", "title": "Hello"});
    strip_at_prefixes(&mut obj);
    assert_eq!(obj, json!({"id": "123", "name": "Test", "title": "Hello"}));
}

#[test]
fn test_strip_at_prefixes_no_at_keys() {
    let mut obj = json!({"id": "123", "name": "Test"});
    strip_at_prefixes(&mut obj);
    assert_eq!(obj, json!({"id": "123", "name": "Test"}));
}

#[test]
fn test_strip_at_prefixes_extracts_text() {
    let mut obj = json!({"@id": "123", "#text": "The Beatles"});
    strip_at_prefixes(&mut obj);
    assert_eq!(obj, json!({"id": "123", "name": "The Beatles"}));
}

#[test]
fn test_strip_at_prefixes_no_text_key_without_hash_text() {
    let mut obj = json!({"@id": "123", "name": "Already Named"});
    strip_at_prefixes(&mut obj);
    assert_eq!(obj, json!({"id": "123", "name": "Already Named"}));
}

#[test]
fn test_unwrap_container_dict_with_key() {
    let input = json!({"genre": ["Rock", "Pop"]});
    let result = unwrap_container(&input, "genre");
    assert_eq!(result, json!(["Rock", "Pop"]));
}

#[test]
fn test_unwrap_container_dict_single_item() {
    let input = json!({"genre": "Rock"});
    let result = unwrap_container(&input, "genre");
    assert_eq!(result, json!(["Rock"]));
}

#[test]
fn test_unwrap_container_already_list() {
    let input = json!(["Rock", "Pop"]);
    let result = unwrap_container(&input, "genre");
    assert_eq!(result, json!(["Rock", "Pop"]));
}

#[test]
fn test_unwrap_container_null() {
    let result = unwrap_container(&Value::Null, "genre");
    assert_eq!(result, json!([]));
}

#[test]
fn test_ensure_list_already_array() {
    let input = json!(["a", "b"]);
    assert_eq!(ensure_list(&input), json!(["a", "b"]));
}

#[test]
fn test_ensure_list_single_value() {
    let input = json!("a");
    assert_eq!(ensure_list(&input), json!(["a"]));
}

#[test]
fn test_ensure_list_null() {
    assert_eq!(ensure_list(&Value::Null), json!([]));
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/Robert/Code/public/discogsography/.claude/worktrees/290-normalizer && cargo test -p extractor normalize_tests -- --test-threads=1 2>&1 | head -20`
Expected: compilation error — `normalize` module not found

- [ ] **Step 3: Write the generic helpers**

Create `extractor/src/normalize.rs`:

```rust
use serde_json::{Map, Value};

/// Strip `@` prefix from all keys in a JSON object (top-level only).
/// Also renames `#text` to `name` (the convention for text content in item dicts).
pub fn strip_at_prefixes(value: &mut Value) {
    let Value::Object(map) = value else { return };

    let keys: Vec<String> = map.keys().cloned().collect();
    let mut renamed: Map<String, Value> = Map::new();

    for key in &keys {
        let val = map.remove(key).unwrap();
        if key == "#text" {
            renamed.insert("name".to_string(), val);
        } else if let Some(stripped) = key.strip_prefix('@') {
            renamed.insert(stripped.to_string(), val);
        } else {
            renamed.insert(key.clone(), val);
        }
    }

    *map = renamed;
}

/// Unwrap a nested container like `{"genre": ["Rock", "Pop"]}` into `["Rock", "Pop"]`.
/// If the input is already a list, return it. If null/missing, return empty array.
/// Single values are wrapped in a list.
pub fn unwrap_container(value: &Value, key: &str) -> Value {
    match value {
        Value::Null => Value::Array(vec![]),
        Value::Array(_) => value.clone(),
        Value::Object(map) => match map.get(key) {
            Some(inner) => ensure_list(inner),
            None => Value::Array(vec![]),
        },
        _ => Value::Array(vec![value.clone()]),
    }
}

/// Ensure a value is an array. Wraps single values, returns null as empty array.
pub fn ensure_list(value: &Value) -> Value {
    match value {
        Value::Array(_) => value.clone(),
        Value::Null => Value::Array(vec![]),
        _ => Value::Array(vec![value.clone()]),
    }
}
```

- [ ] **Step 4: Add module declaration to `lib.rs`**

In `extractor/src/lib.rs`, add after the `pub mod parser;` line:

```rust
pub mod normalize;
```

And add the test module reference at the bottom of `normalize.rs`:

```rust
#[cfg(test)]
#[path = "tests/normalize_tests.rs"]
mod tests;
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/Robert/Code/public/discogsography/.claude/worktrees/290-normalizer && cargo test -p extractor normalize_tests -- --test-threads=1`
Expected: all 12 tests pass

- [ ] **Step 6: Commit**

```bash
git add extractor/src/normalize.rs extractor/src/tests/normalize_tests.rs extractor/src/lib.rs
git commit -m "feat(extractor): add normalize.rs with generic helpers (strip_at_prefixes, unwrap_container, ensure_list)"
```

---

### Task 2: Add Artist Normalization to `normalize.rs`

**Files:**
- Modify: `extractor/src/normalize.rs`
- Modify: `extractor/src/tests/normalize_tests.rs`

- [ ] **Step 1: Write failing tests for artist normalization**

Append to `extractor/src/tests/normalize_tests.rs`:

```rust
use crate::normalize::normalize_record;

#[test]
fn test_normalize_artist_basic() {
    let mut record = json!({
        "id": "123",
        "name": "The Beatles",
        "sha256": "abc123",
        "realname": "The Beatles",
        "profile": "English rock band"
    });
    normalize_record("artists", &mut record);
    assert_eq!(record["id"], "123");
    assert_eq!(record["name"], "The Beatles");
    assert_eq!(record["sha256"], "abc123");
}

#[test]
fn test_normalize_artist_members() {
    let mut record = json!({
        "id": "123",
        "name": "The Beatles",
        "members": {
            "name": [
                {"id": "10", "#text": "John Lennon"},
                {"id": "20", "#text": "Paul McCartney"}
            ]
        }
    });
    normalize_record("artists", &mut record);
    let members = record["members"].as_array().unwrap();
    assert_eq!(members.len(), 2);
    assert_eq!(members[0], json!({"id": "10", "name": "John Lennon"}));
    assert_eq!(members[1], json!({"id": "20", "name": "Paul McCartney"}));
}

#[test]
fn test_normalize_artist_groups() {
    let mut record = json!({
        "id": "10",
        "name": "John Lennon",
        "groups": {
            "name": [
                {"id": "123", "#text": "The Beatles"}
            ]
        }
    });
    normalize_record("artists", &mut record);
    let groups = record["groups"].as_array().unwrap();
    assert_eq!(groups.len(), 1);
    assert_eq!(groups[0], json!({"id": "123", "name": "The Beatles"}));
}

#[test]
fn test_normalize_artist_aliases() {
    let mut record = json!({
        "id": "10",
        "name": "John Lennon",
        "aliases": {
            "name": [
                {"id": "999", "#text": "Dr. Winston O'Boogie"}
            ]
        }
    });
    normalize_record("artists", &mut record);
    let aliases = record["aliases"].as_array().unwrap();
    assert_eq!(aliases.len(), 1);
    assert_eq!(aliases[0], json!({"id": "999", "name": "Dr. Winston O'Boogie"}));
}

#[test]
fn test_normalize_artist_single_member() {
    let mut record = json!({
        "id": "123",
        "name": "Duo",
        "members": {
            "name": {"id": "10", "#text": "Solo Member"}
        }
    });
    normalize_record("artists", &mut record);
    let members = record["members"].as_array().unwrap();
    assert_eq!(members.len(), 1);
    assert_eq!(members[0], json!({"id": "10", "name": "Solo Member"}));
}

#[test]
fn test_normalize_artist_no_members() {
    let mut record = json!({
        "id": "123",
        "name": "Solo Artist"
    });
    normalize_record("artists", &mut record);
    assert!(record.get("members").is_none());
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/Robert/Code/public/discogsography/.claude/worktrees/290-normalizer && cargo test -p extractor normalize_tests -- --test-threads=1 2>&1 | head -20`
Expected: compilation error — `normalize_record` not found

- [ ] **Step 3: Implement artist normalization**

Add to `extractor/src/normalize.rs`:

```rust
/// Normalize a list of items that have IDs (members, groups, aliases, sublabels, artists, labels).
/// Each item gets `@` prefixes stripped and `#text` converted to `name`.
fn normalize_item_list(value: &Value, container_key: &str) -> Value {
    let items = unwrap_container(value, container_key);
    let Value::Array(arr) = items else {
        return Value::Array(vec![]);
    };

    let result: Vec<Value> = arr
        .into_iter()
        .filter_map(|mut item| {
            if item.is_object() {
                strip_at_prefixes(&mut item);
                Some(item)
            } else {
                // String items (just an ID) become {"id": "value"}
                Some(json!({"id": item}))
            }
        })
        .collect();

    Value::Array(result)
}

fn normalize_artist(record: &mut Value) {
    let Value::Object(map) = record else { return };

    // Normalize members, groups, aliases — all use "name" as container key
    for field in &["members", "groups", "aliases"] {
        if let Some(val) = map.remove(*field) {
            let normalized = normalize_item_list(&val, "name");
            if let Value::Array(ref arr) = normalized {
                if !arr.is_empty() {
                    map.insert(field.to_string(), normalized);
                }
            }
        }
    }
}

/// Normalize a parsed record in-place based on its data type.
/// Transforms XML-shaped JSON into flat, consumer-ready JSON.
pub fn normalize_record(data_type: &str, record: &mut Value) {
    match data_type {
        "artists" => normalize_artist(record),
        _ => {} // Other types will be added in subsequent tasks
    }
}
```

Add `use serde_json::json;` to the imports at the top of `normalize.rs` (it's needed by `normalize_item_list`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/Robert/Code/public/discogsography/.claude/worktrees/290-normalizer && cargo test -p extractor normalize_tests -- --test-threads=1`
Expected: all tests pass (12 generic + 6 artist = 18 total)

- [ ] **Step 5: Commit**

```bash
git add extractor/src/normalize.rs extractor/src/tests/normalize_tests.rs
git commit -m "feat(extractor): add artist normalization to normalize.rs"
```

---

### Task 3: Add Label Normalization to `normalize.rs`

**Files:**
- Modify: `extractor/src/normalize.rs`
- Modify: `extractor/src/tests/normalize_tests.rs`

- [ ] **Step 1: Write failing tests for label normalization**

Append to `extractor/src/tests/normalize_tests.rs`:

```rust
#[test]
fn test_normalize_label_basic() {
    let mut record = json!({
        "id": "456",
        "name": "EMI Records",
        "sha256": "def456",
        "profile": "Major label"
    });
    normalize_record("labels", &mut record);
    assert_eq!(record["id"], "456");
    assert_eq!(record["name"], "EMI Records");
}

#[test]
fn test_normalize_label_parent_label() {
    let mut record = json!({
        "id": "456",
        "name": "EMI Records",
        "parentLabel": {"@id": "100", "#text": "Universal Music"}
    });
    normalize_record("labels", &mut record);
    assert_eq!(record["parentLabel"], json!({"id": "100", "name": "Universal Music"}));
}

#[test]
fn test_normalize_label_sublabels() {
    let mut record = json!({
        "id": "100",
        "name": "Universal Music",
        "sublabels": {
            "label": [
                {"@id": "456", "#text": "EMI Records"},
                {"@id": "789", "#text": "Polydor"}
            ]
        }
    });
    normalize_record("labels", &mut record);
    let sublabels = record["sublabels"].as_array().unwrap();
    assert_eq!(sublabels.len(), 2);
    assert_eq!(sublabels[0], json!({"id": "456", "name": "EMI Records"}));
    assert_eq!(sublabels[1], json!({"id": "789", "name": "Polydor"}));
}

#[test]
fn test_normalize_label_single_sublabel() {
    let mut record = json!({
        "id": "100",
        "name": "Universal Music",
        "sublabels": {
            "label": {"@id": "456", "#text": "EMI Records"}
        }
    });
    normalize_record("labels", &mut record);
    let sublabels = record["sublabels"].as_array().unwrap();
    assert_eq!(sublabels.len(), 1);
    assert_eq!(sublabels[0], json!({"id": "456", "name": "EMI Records"}));
}

#[test]
fn test_normalize_label_no_parent() {
    let mut record = json!({
        "id": "456",
        "name": "Indie Label"
    });
    normalize_record("labels", &mut record);
    assert!(record.get("parentLabel").is_none());
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/Robert/Code/public/discogsography/.claude/worktrees/290-normalizer && cargo test -p extractor normalize_tests::test_normalize_label -- --test-threads=1 2>&1 | head -10`
Expected: FAIL — label normalization not yet implemented (data unchanged)

- [ ] **Step 3: Implement label normalization**

Add to `extractor/src/normalize.rs`:

```rust
fn normalize_label(record: &mut Value) {
    let Value::Object(map) = record else { return };

    // Normalize parentLabel — strip @ prefixes and extract #text
    if let Some(mut parent) = map.remove("parentLabel") {
        if parent.is_object() {
            strip_at_prefixes(&mut parent);
            map.insert("parentLabel".to_string(), parent);
        }
    }

    // Normalize sublabels — unwrap container and strip @ prefixes
    if let Some(val) = map.remove("sublabels") {
        let normalized = normalize_item_list(&val, "label");
        if let Value::Array(ref arr) = normalized {
            if !arr.is_empty() {
                map.insert("sublabels".to_string(), normalized);
            }
        }
    }
}
```

Update `normalize_record` to add the labels arm:

```rust
pub fn normalize_record(data_type: &str, record: &mut Value) {
    match data_type {
        "artists" => normalize_artist(record),
        "labels" => normalize_label(record),
        _ => {}
    }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/Robert/Code/public/discogsography/.claude/worktrees/290-normalizer && cargo test -p extractor normalize_tests -- --test-threads=1`
Expected: all tests pass (18 + 5 = 23 total)

- [ ] **Step 5: Commit**

```bash
git add extractor/src/normalize.rs extractor/src/tests/normalize_tests.rs
git commit -m "feat(extractor): add label normalization to normalize.rs"
```

---

### Task 4: Add Master Normalization to `normalize.rs`

**Files:**
- Modify: `extractor/src/normalize.rs`
- Modify: `extractor/src/tests/normalize_tests.rs`

- [ ] **Step 1: Write failing tests for master normalization**

Append to `extractor/src/tests/normalize_tests.rs`:

```rust
#[test]
fn test_normalize_master_basic() {
    let mut record = json!({
        "@id": "789",
        "title": "Abbey Road",
        "year": "1969",
        "sha256": "ghi789"
    });
    normalize_record("masters", &mut record);
    // @id should be renamed to id
    assert_eq!(record["id"], "789");
    assert!(record.get("@id").is_none());
    assert_eq!(record["title"], "Abbey Road");
}

#[test]
fn test_normalize_master_artists() {
    let mut record = json!({
        "@id": "789",
        "title": "Abbey Road",
        "artists": {
            "artist": [
                {"id": "123", "name": "The Beatles"}
            ]
        }
    });
    normalize_record("masters", &mut record);
    let artists = record["artists"].as_array().unwrap();
    assert_eq!(artists.len(), 1);
    assert_eq!(artists[0], json!({"id": "123", "name": "The Beatles"}));
}

#[test]
fn test_normalize_master_genres() {
    let mut record = json!({
        "@id": "789",
        "title": "Abbey Road",
        "genres": {
            "genre": ["Rock", "Pop"]
        }
    });
    normalize_record("masters", &mut record);
    assert_eq!(record["genres"], json!(["Rock", "Pop"]));
}

#[test]
fn test_normalize_master_styles() {
    let mut record = json!({
        "@id": "789",
        "title": "Abbey Road",
        "styles": {
            "style": "Classic Rock"
        }
    });
    normalize_record("masters", &mut record);
    assert_eq!(record["styles"], json!(["Classic Rock"]));
}

#[test]
fn test_normalize_master_single_artist() {
    let mut record = json!({
        "@id": "789",
        "title": "Abbey Road",
        "artists": {
            "artist": {"id": "123", "name": "Solo Artist", "anv": "Alias"}
        }
    });
    normalize_record("masters", &mut record);
    let artists = record["artists"].as_array().unwrap();
    assert_eq!(artists.len(), 1);
    assert_eq!(artists[0]["id"], "123");
    assert_eq!(artists[0]["name"], "Solo Artist");
    assert_eq!(artists[0]["anv"], "Alias");
}

#[test]
fn test_normalize_master_no_genres() {
    let mut record = json!({
        "@id": "789",
        "title": "No Genres"
    });
    normalize_record("masters", &mut record);
    assert!(record.get("genres").is_none());
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/Robert/Code/public/discogsography/.claude/worktrees/290-normalizer && cargo test -p extractor normalize_tests::test_normalize_master -- --test-threads=1 2>&1 | head -10`
Expected: FAIL

- [ ] **Step 3: Implement master normalization**

Add to `extractor/src/normalize.rs`:

```rust
/// Unwrap a string list container like `{"genre": ["Rock", "Pop"]}` into `["Rock", "Pop"]`.
/// Unlike `normalize_item_list`, this is for simple string arrays (genres, styles).
fn normalize_string_list(value: &Value, container_key: &str) -> Value {
    unwrap_container(value, container_key)
}

fn normalize_master(record: &mut Value) {
    let Value::Object(map) = record else { return };

    // Strip @ prefix from top-level keys (@id -> id)
    strip_at_prefixes(record);
    let Value::Object(map) = record else { return };

    // Normalize artists
    if let Some(val) = map.remove("artists") {
        let normalized = normalize_item_list(&val, "artist");
        if let Value::Array(ref arr) = normalized {
            if !arr.is_empty() {
                map.insert("artists".to_string(), normalized);
            }
        }
    }

    // Normalize genres and styles (simple string lists)
    for field in &["genres", "styles"] {
        let container_key = &field[..field.len() - 1]; // "genres" -> "genre", "styles" -> "style"
        if let Some(val) = map.remove(*field) {
            let normalized = normalize_string_list(&val, container_key);
            if let Value::Array(ref arr) = normalized {
                if !arr.is_empty() {
                    map.insert(field.to_string(), normalized);
                }
            }
        }
    }
}
```

Update `normalize_record`:

```rust
pub fn normalize_record(data_type: &str, record: &mut Value) {
    match data_type {
        "artists" => normalize_artist(record),
        "labels" => normalize_label(record),
        "masters" => normalize_master(record),
        _ => {}
    }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/Robert/Code/public/discogsography/.claude/worktrees/290-normalizer && cargo test -p extractor normalize_tests -- --test-threads=1`
Expected: all tests pass (23 + 6 = 29 total)

- [ ] **Step 5: Commit**

```bash
git add extractor/src/normalize.rs extractor/src/tests/normalize_tests.rs
git commit -m "feat(extractor): add master normalization to normalize.rs"
```

---

### Task 5: Add Release Normalization to `normalize.rs`

**Files:**
- Modify: `extractor/src/normalize.rs`
- Modify: `extractor/src/tests/normalize_tests.rs`

- [ ] **Step 1: Write failing tests for release normalization**

Append to `extractor/src/tests/normalize_tests.rs`:

```rust
#[test]
fn test_normalize_release_basic() {
    let mut record = json!({
        "@id": "12345",
        "title": "Abbey Road",
        "released": "1969-09-26",
        "sha256": "abc123"
    });
    normalize_record("releases", &mut record);
    assert_eq!(record["id"], "12345");
    assert!(record.get("@id").is_none());
    assert_eq!(record["title"], "Abbey Road");
}

#[test]
fn test_normalize_release_artists() {
    let mut record = json!({
        "@id": "12345",
        "title": "Abbey Road",
        "artists": {
            "artist": [
                {"id": "123", "name": "The Beatles"}
            ]
        }
    });
    normalize_record("releases", &mut record);
    let artists = record["artists"].as_array().unwrap();
    assert_eq!(artists.len(), 1);
    assert_eq!(artists[0], json!({"id": "123", "name": "The Beatles"}));
}

#[test]
fn test_normalize_release_labels() {
    let mut record = json!({
        "@id": "12345",
        "title": "Abbey Road",
        "labels": {
            "label": {"@id": "100", "@name": "EMI", "@catno": "PCS 7067"}
        }
    });
    normalize_record("releases", &mut record);
    let labels = record["labels"].as_array().unwrap();
    assert_eq!(labels.len(), 1);
    assert_eq!(labels[0]["id"], "100");
    assert_eq!(labels[0]["name"], "EMI");
    assert_eq!(labels[0]["catno"], "PCS 7067");
}

#[test]
fn test_normalize_release_master_id_dict() {
    let mut record = json!({
        "@id": "12345",
        "title": "Abbey Road",
        "master_id": {"#text": "789", "@is_main_release": "true"}
    });
    normalize_record("releases", &mut record);
    assert_eq!(record["master_id"], "789");
}

#[test]
fn test_normalize_release_master_id_string() {
    let mut record = json!({
        "@id": "12345",
        "title": "Abbey Road",
        "master_id": "789"
    });
    normalize_record("releases", &mut record);
    assert_eq!(record["master_id"], "789");
}

#[test]
fn test_normalize_release_genres_styles() {
    let mut record = json!({
        "@id": "12345",
        "title": "Abbey Road",
        "genres": {"genre": ["Rock", "Pop"]},
        "styles": {"style": "Classic Rock"}
    });
    normalize_record("releases", &mut record);
    assert_eq!(record["genres"], json!(["Rock", "Pop"]));
    assert_eq!(record["styles"], json!(["Classic Rock"]));
}

#[test]
fn test_normalize_release_extraartists() {
    let mut record = json!({
        "@id": "12345",
        "title": "Abbey Road",
        "extraartists": {
            "artist": [
                {"id": "500", "name": "Bob Ludwig", "role": "Mastered By"},
                {"id": "501", "name": "Flood", "role": "Producer"}
            ]
        }
    });
    normalize_record("releases", &mut record);
    let credits = record["extraartists"].as_array().unwrap();
    assert_eq!(credits.len(), 2);
    assert_eq!(credits[0]["name"], "Bob Ludwig");
    assert_eq!(credits[0]["role"], "Mastered By");
    assert_eq!(credits[1]["id"], "501");
}

#[test]
fn test_normalize_release_formats() {
    let mut record = json!({
        "@id": "12345",
        "title": "Abbey Road",
        "formats": {
            "format": [
                {"@name": "Vinyl", "@qty": "1", "descriptions": {"description": "LP"}},
                {"@name": "CD", "@qty": "2"}
            ]
        }
    });
    normalize_record("releases", &mut record);
    let formats = record["formats"].as_array().unwrap();
    assert_eq!(formats.len(), 2);
    assert_eq!(formats[0]["name"], "Vinyl");
    assert_eq!(formats[0]["qty"], "1");
    assert!(formats[0].get("@name").is_none());
    assert_eq!(formats[1]["name"], "CD");
}

#[test]
fn test_normalize_release_single_format() {
    let mut record = json!({
        "@id": "12345",
        "title": "Test",
        "formats": {
            "format": {"@name": "Cassette", "@qty": "1"}
        }
    });
    normalize_record("releases", &mut record);
    let formats = record["formats"].as_array().unwrap();
    assert_eq!(formats.len(), 1);
    assert_eq!(formats[0]["name"], "Cassette");
}

#[test]
fn test_normalize_release_preserves_other_fields() {
    let mut record = json!({
        "@id": "12345",
        "title": "Abbey Road",
        "released": "1969-09-26",
        "country": "UK",
        "notes": "Some notes",
        "data_quality": "Correct"
    });
    normalize_record("releases", &mut record);
    assert_eq!(record["released"], "1969-09-26");
    assert_eq!(record["country"], "UK");
    assert_eq!(record["notes"], "Some notes");
    assert_eq!(record["data_quality"], "Correct");
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/Robert/Code/public/discogsography/.claude/worktrees/290-normalizer && cargo test -p extractor normalize_tests::test_normalize_release -- --test-threads=1 2>&1 | head -10`
Expected: FAIL

- [ ] **Step 3: Implement release normalization**

Add to `extractor/src/normalize.rs`:

```rust
fn normalize_release(record: &mut Value) {
    let Value::Object(map) = record else { return };

    // Strip @ prefix from top-level keys (@id -> id)
    strip_at_prefixes(record);
    let Value::Object(map) = record else { return };

    // Normalize artists
    if let Some(val) = map.remove("artists") {
        let normalized = normalize_item_list(&val, "artist");
        if let Value::Array(ref arr) = normalized {
            if !arr.is_empty() {
                map.insert("artists".to_string(), normalized);
            }
        }
    }

    // Normalize labels (have @id, @name, @catno attributes)
    if let Some(val) = map.remove("labels") {
        let normalized = normalize_item_list(&val, "label");
        if let Value::Array(ref arr) = normalized {
            if !arr.is_empty() {
                map.insert("labels".to_string(), normalized);
            }
        }
    }

    // Normalize master_id — extract string from dict wrapper
    if let Some(val) = map.remove("master_id") {
        match &val {
            Value::Object(m) => {
                // {"#text": "789", "@is_main_release": "true"} -> "789"
                if let Some(text) = m.get("#text") {
                    map.insert("master_id".to_string(), text.clone());
                } else if let Some(id) = m.get("id") {
                    map.insert("master_id".to_string(), id.clone());
                }
            }
            Value::String(_) | Value::Number(_) => {
                map.insert("master_id".to_string(), val);
            }
            _ => {}
        }
    }

    // Normalize genres and styles
    for field in &["genres", "styles"] {
        let container_key = &field[..field.len() - 1];
        if let Some(val) = map.remove(*field) {
            let normalized = normalize_string_list(&val, container_key);
            if let Value::Array(ref arr) = normalized {
                if !arr.is_empty() {
                    map.insert(field.to_string(), normalized);
                }
            }
        }
    }

    // Normalize extraartists
    if let Some(val) = map.remove("extraartists") {
        let normalized = normalize_item_list(&val, "artist");
        if let Value::Array(ref arr) = normalized {
            if !arr.is_empty() {
                map.insert("extraartists".to_string(), normalized);
            }
        }
    }

    // Normalize formats — unwrap container and strip @ prefixes from each format
    if let Some(val) = map.remove("formats") {
        let items = unwrap_container(&val, "format");
        if let Value::Array(arr) = items {
            let normalized: Vec<Value> = arr
                .into_iter()
                .map(|mut item| {
                    if item.is_object() {
                        strip_at_prefixes(&mut item);
                    }
                    item
                })
                .collect();
            if !normalized.is_empty() {
                map.insert("formats".to_string(), Value::Array(normalized));
            }
        }
    }
}
```

Update `normalize_record`:

```rust
pub fn normalize_record(data_type: &str, record: &mut Value) {
    match data_type {
        "artists" => normalize_artist(record),
        "labels" => normalize_label(record),
        "masters" => normalize_master(record),
        "releases" => normalize_release(record),
        _ => {}
    }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/Robert/Code/public/discogsography/.claude/worktrees/290-normalizer && cargo test -p extractor normalize_tests -- --test-threads=1`
Expected: all tests pass (29 + 11 = 40 total)

- [ ] **Step 5: Commit**

```bash
git add extractor/src/normalize.rs extractor/src/tests/normalize_tests.rs
git commit -m "feat(extractor): add release normalization to normalize.rs"
```

---

### Task 6: Wire Normalization into Extractor Pipeline

**Files:**
- Modify: `extractor/src/extractor.rs:18-20` (add import)
- Modify: `extractor/src/extractor.rs:607-611` (add normalize call)

- [ ] **Step 1: Write a failing integration test**

Append to `extractor/src/tests/normalize_tests.rs`:

```rust
/// Integration test: simulate the full validator flow for a release record.
/// Verifies that normalization produces the shape consumers expect.
#[test]
fn test_normalize_full_release_pipeline() {
    // This is what the parser produces for a release
    let mut record = json!({
        "@id": "12345",
        "title": "Abbey Road",
        "released": "1969-09-26",
        "sha256": "abc123",
        "artists": {
            "artist": {"id": "123", "name": "The Beatles"}
        },
        "labels": {
            "label": {"@id": "100", "@name": "EMI", "@catno": "PCS 7067"}
        },
        "master_id": {"#text": "789", "@is_main_release": "true"},
        "genres": {"genre": ["Rock", "Pop"]},
        "styles": {"style": "Classic Rock"},
        "extraartists": {
            "artist": [
                {"id": "500", "name": "Bob Ludwig", "role": "Mastered By"}
            ]
        },
        "formats": {
            "format": {"@name": "Vinyl", "@qty": "1"}
        },
        "country": "UK",
        "data_quality": "Correct"
    });

    normalize_record("releases", &mut record);

    // Verify the consumer-ready shape
    assert_eq!(record["id"], "12345");
    assert!(record.get("@id").is_none());
    assert_eq!(record["title"], "Abbey Road");
    assert_eq!(record["released"], "1969-09-26");
    assert_eq!(record["country"], "UK");
    assert_eq!(record["artists"], json!([{"id": "123", "name": "The Beatles"}]));
    assert_eq!(record["labels"], json!([{"id": "100", "name": "EMI", "catno": "PCS 7067"}]));
    assert_eq!(record["master_id"], "789");
    assert_eq!(record["genres"], json!(["Rock", "Pop"]));
    assert_eq!(record["styles"], json!(["Classic Rock"]));
    assert_eq!(record["extraartists"], json!([{"id": "500", "name": "Bob Ludwig", "role": "Mastered By"}]));
    assert_eq!(record["formats"], json!([{"name": "Vinyl", "qty": "1"}]));
}
```

- [ ] **Step 2: Run tests to verify the integration test passes**

Run: `cd /Users/Robert/Code/public/discogsography/.claude/worktrees/290-normalizer && cargo test -p extractor normalize_tests::test_normalize_full_release_pipeline -- --test-threads=1`
Expected: PASS (normalization logic already implemented; this validates end-to-end)

- [ ] **Step 3: Wire normalization into the validator pipeline**

In `extractor/src/extractor.rs`, add to the imports (around line 18):

```rust
use crate::normalize::normalize_record;
```

In the `message_validator` function, add the normalize call after filters and before hash calculation. Replace lines 607-611:

```rust
        // Compute content hash from post-filter data so consumers detect
        // changes caused by filter updates, not just upstream XML/JSONL changes.
        message.sha256 = calculate_content_hash(&message.data);
```

With:

```rust
        // Normalize XML-shaped JSON into flat, consumer-ready format.
        // Runs after filters (which operate on XML shape) and before hash
        // calculation (so hash reflects the normalized shape consumers see).
        normalize_record(data_type, &mut message.data);

        // Compute content hash from post-normalization data so consumers detect
        // changes caused by filter or normalization updates.
        message.sha256 = calculate_content_hash(&message.data);
```

- [ ] **Step 4: Run all extractor tests**

Run: `cd /Users/Robert/Code/public/discogsography/.claude/worktrees/290-normalizer && cargo test -p extractor -- --test-threads=1`
Expected: all tests pass

- [ ] **Step 5: Run clippy**

Run: `cd /Users/Robert/Code/public/discogsography/.claude/worktrees/290-normalizer && cargo clippy -p extractor -- -D warnings`
Expected: no warnings

- [ ] **Step 6: Commit**

```bash
git add extractor/src/extractor.rs extractor/src/tests/normalize_tests.rs
git commit -m "feat(extractor): wire normalize_record into validator pipeline"
```

---

### Task 7: Simplify Python `data_normalizer.py`

**Files:**
- Modify: `common/data_normalizer.py` (gut and simplify)
- Modify: `common/__init__.py:25-34,135-142` (remove deleted exports)

- [ ] **Step 1: Rewrite `data_normalizer.py`**

Replace the entire contents of `common/data_normalizer.py` with:

```python
"""Data normalization utilities for Discogs data.

The Rust extractor now handles structural normalization (flattening nested
containers, stripping @ prefixes, unwrapping #text).  This module retains
only consumer-side concerns: year parsing and the normalize_record() entry
point that consumers call.
"""

from typing import Any

import structlog


logger = structlog.get_logger(__name__)


def _parse_year_int(value: Any) -> int | None:
    """Parse a Discogs year value into an integer.

    Handles both plain year strings ("1969", as used in Master.<year>) and
    full/partial date strings ("1969-09-26", "1969-00-00", as used in
    Release.<released>).  Returns None when no valid year is found.

    Note: The extractor's ``nullify_when`` filter now converts sentinel years
    (year < 1860, including 0) to null before messages reach consumers.  The
    ``year == 0`` check below is a defensive fallback for extractions run
    without the updated rules config.
    """
    if value is None:
        return None
    if isinstance(value, int):
        return value if value != 0 else None
    s = str(value).strip()
    if not s:
        return None
    try:
        year = int(s[:4])
        return year if year != 0 else None
    except ValueError:
        return None


def normalize_record(data_type: str, data: dict[str, Any]) -> dict[str, Any]:
    """Normalize a record based on its data type.

    The Rust extractor now handles structural normalization. This function
    performs only consumer-side transforms:
    - Parse year fields from date strings

    Args:
        data_type: The type of record ("artists", "labels", "masters", "releases")
        data: The record data (already structurally normalized by the extractor)

    Returns:
        Record data with consumer-side transforms applied
    """
    if data_type == "masters":
        data["year"] = _parse_year_int(data.get("year"))
    elif data_type == "releases":
        data["year"] = _parse_year_int(data.get("released"))

    return data
```

- [ ] **Step 2: Update `common/__init__.py` to remove deleted exports**

In `common/__init__.py`, replace the data_normalizer import block (lines 25-34):

```python
from common.data_normalizer import (
    normalize_artist,
    normalize_id,
    normalize_item_with_id,
    normalize_label,
    normalize_master,
    normalize_nested_list,
    normalize_record,
    normalize_release,
)
```

With:

```python
from common.data_normalizer import (
    normalize_record,
)
```

And remove the deleted names from `__all__` (lines 135-142). Remove these entries:
- `"normalize_artist",`
- `"normalize_id",`
- `"normalize_item_with_id",`
- `"normalize_label",`
- `"normalize_master",`
- `"normalize_nested_list",`
- `"normalize_release",`

Keep only `"normalize_record",` in the `__all__` list.

- [ ] **Step 3: Run Python linting**

Run: `cd /Users/Robert/Code/public/discogsography/.claude/worktrees/290-normalizer && uv run ruff check common/data_normalizer.py common/__init__.py && uv run mypy common/data_normalizer.py common/__init__.py`
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add common/data_normalizer.py common/__init__.py
git commit -m "refactor: simplify data_normalizer.py — structural normalization moved to Rust extractor"
```

---

### Task 8: Update Graphinator to Use New Flat Format

**Files:**
- Modify: `graphinator/graphinator.py:23-25,911` (remove extract_format_names)
- Modify: `graphinator/batch_processor.py:14-16,833` (remove extract_format_names)

- [ ] **Step 1: Update graphinator.py**

In `graphinator/graphinator.py`, remove the `extract_format_names` import (line 25):

```python
from common.data_normalizer import extract_format_names
```

Replace the `extract_format_names` call at line 911:

```python
    formats = extract_format_names(record.get("formats"))
```

With:

```python
    formats = [f["name"] for f in record.get("formats", []) if isinstance(f, dict) and "name" in f]
```

- [ ] **Step 2: Update batch_processor.py**

In `graphinator/batch_processor.py`, remove the `extract_format_names` import (line 16):

```python
from common.data_normalizer import extract_format_names
```

Replace the `extract_format_names` call at lines 833-835:

```python
                    release_data["format_names"] = extract_format_names(
                        msg.data.get("formats")
                    )
```

With:

```python
                    release_data["format_names"] = [
                        f["name"] for f in msg.data.get("formats", []) if isinstance(f, dict) and "name" in f
                    ]
```

- [ ] **Step 3: Run linting**

Run: `cd /Users/Robert/Code/public/discogsography/.claude/worktrees/290-normalizer && uv run ruff check graphinator/ && uv run mypy graphinator/`
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add graphinator/graphinator.py graphinator/batch_processor.py
git commit -m "refactor(graphinator): replace extract_format_names with inline list comprehension"
```

---

### Task 9: Rewrite Python Tests for Simplified Normalizer

**Files:**
- Modify: `tests/common/test_data_normalizer.py` (rewrite)

- [ ] **Step 1: Rewrite `test_data_normalizer.py`**

Replace the entire contents of `tests/common/test_data_normalizer.py` with:

```python
from common.data_normalizer import (
    _parse_year_int,
    normalize_record,
)


class TestParseYearInt:
    """Test _parse_year_int function."""

    def test_none_returns_none(self) -> None:
        assert _parse_year_int(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert _parse_year_int("") is None

    def test_zero_returns_none(self) -> None:
        assert _parse_year_int(0) is None

    def test_zero_string_returns_none(self) -> None:
        assert _parse_year_int("0") is None

    def test_valid_year_int(self) -> None:
        assert _parse_year_int(1969) == 1969

    def test_valid_year_string(self) -> None:
        assert _parse_year_int("1969") == 1969

    def test_date_string(self) -> None:
        assert _parse_year_int("1969-09-26") == 1969

    def test_partial_date_string(self) -> None:
        assert _parse_year_int("1969-00-00") == 1969

    def test_invalid_string(self) -> None:
        assert _parse_year_int("Unknown") is None

    def test_whitespace_string(self) -> None:
        assert _parse_year_int("   ") is None


class TestNormalizeRecord:
    """Test normalize_record function."""

    def test_artists_passthrough(self) -> None:
        """Artists don't need year parsing — data passes through."""
        data = {"id": "1", "name": "Test", "sha256": "abc"}
        result = normalize_record("artists", data)
        assert result["id"] == "1"
        assert result["name"] == "Test"

    def test_labels_passthrough(self) -> None:
        """Labels don't need year parsing — data passes through."""
        data = {"id": "1", "name": "Test Label", "sha256": "abc"}
        result = normalize_record("labels", data)
        assert result["id"] == "1"

    def test_masters_year_parsing(self) -> None:
        """Masters parse year from the 'year' field."""
        data = {"id": "1", "title": "Test", "year": "1969", "sha256": "abc"}
        result = normalize_record("masters", data)
        assert result["year"] == 1969

    def test_masters_year_none(self) -> None:
        """Masters with no year field get year=None."""
        data = {"id": "1", "title": "Test", "sha256": "abc"}
        result = normalize_record("masters", data)
        assert result["year"] is None

    def test_releases_year_from_released(self) -> None:
        """Releases parse year from the 'released' field."""
        data = {"id": "1", "title": "Test", "released": "1969-09-26", "sha256": "abc"}
        result = normalize_record("releases", data)
        assert result["year"] == 1969

    def test_releases_no_released_field(self) -> None:
        """Releases with no released field get year=None."""
        data = {"id": "1", "title": "Test", "sha256": "abc"}
        result = normalize_record("releases", data)
        assert result["year"] is None

    def test_unknown_type_passthrough(self) -> None:
        """Unknown types pass through unchanged."""
        data = {"id": "1", "custom": "field"}
        result = normalize_record("unknown", data)
        assert result == {"id": "1", "custom": "field"}
```

- [ ] **Step 2: Run tests**

Run: `cd /Users/Robert/Code/public/discogsography/.claude/worktrees/290-normalizer && uv run pytest tests/common/test_data_normalizer.py -v`
Expected: all tests pass

- [ ] **Step 3: Commit**

```bash
git add tests/common/test_data_normalizer.py
git commit -m "test: rewrite data_normalizer tests for simplified normalizer"
```

---

### Task 10: Update Consumer Test Fixtures

**Files:**
- Modify: `tests/graphinator/test_batch_processor.py`
- Modify: `tests/tableinator/test_batch_processor.py`

- [ ] **Step 1: Update graphinator batch processor tests**

In `tests/graphinator/test_batch_processor.py`, the test fixtures use `normalize_record` as a mock. The mock return values need to use the new flat format (no `@` prefixes, no nested containers). The mocks already return flat data like `{"id": "123", "name": "Test Artist", "sha256": "hash123"}` — these are already correct since they mock the function's return value.

Verify by checking that all `patch("graphinator.batch_processor.normalize_record", return_value=data)` calls use flat data. If any use XML-shaped data, update them.

Also check that any test data for releases includes `formats` in the new flat format:
- Old: `"formats": {"format": [{"@name": "CD"}]}`
- New: `"formats": [{"name": "CD"}]`

- [ ] **Step 2: Update tableinator batch processor tests**

Same check for `tests/tableinator/test_batch_processor.py` — verify mock data uses flat format.

- [ ] **Step 3: Run all consumer tests**

Run: `cd /Users/Robert/Code/public/discogsography/.claude/worktrees/290-normalizer && uv run pytest tests/graphinator/ tests/tableinator/ -v`
Expected: all tests pass

- [ ] **Step 4: Commit**

```bash
git add tests/graphinator/test_batch_processor.py tests/tableinator/test_batch_processor.py
git commit -m "test: update consumer test fixtures for flat extractor output format"
```

---

### Task 11: Run Full Test Suite and Fix Any Remaining Issues

**Files:**
- Potentially any files from previous tasks

- [ ] **Step 1: Run full Rust test suite**

Run: `cd /Users/Robert/Code/public/discogsography/.claude/worktrees/290-normalizer && cargo test -p extractor -- --test-threads=1`
Expected: all tests pass

- [ ] **Step 2: Run full Python test suite**

Run: `cd /Users/Robert/Code/public/discogsography/.claude/worktrees/290-normalizer && just test`
Expected: all tests pass

- [ ] **Step 3: Run linting and type checking**

Run: `cd /Users/Robert/Code/public/discogsography/.claude/worktrees/290-normalizer && just lint`
Expected: all checks pass

- [ ] **Step 4: Run Rust clippy and format check**

Run: `cd /Users/Robert/Code/public/discogsography/.claude/worktrees/290-normalizer && just extractor-lint && just extractor-fmt-check`
Expected: no warnings, no format issues

- [ ] **Step 5: Fix any issues found in steps 1-4**

Address any test failures, lint errors, or type errors. Common issues:
- Other test files importing removed functions from `common.data_normalizer`
- Other code importing `extract_format_names` or `normalize_id` etc.
- Type annotation mismatches in the simplified normalizer

Grep for all remaining references to deleted functions:

```bash
cd /Users/Robert/Code/public/discogsography/.claude/worktrees/290-normalizer
grep -rn "normalize_id\|normalize_text\|normalize_item_with_id\|normalize_nested_list\|ensure_list\|normalize_artist\|normalize_label\|normalize_master\|normalize_release\|extract_format_names" --include="*.py" .
```

Any remaining references must be updated or removed.

- [ ] **Step 6: Commit any fixes**

```bash
git add -A
git commit -m "fix: resolve remaining references to deleted normalizer functions"
```
