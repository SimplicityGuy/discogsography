use anyhow::{Context, Result};
use serde_json::Value;
use std::collections::HashMap;
use std::fs::File;
use std::io::{BufRead, BufReader, Read};
use std::path::Path;
use tokio::sync::mpsc;
use tracing::{debug, info, warn};
use xz2::read::XzDecoder;

use crate::types::{DataMessage, DataType};

/// Open a file for line-by-line reading, automatically handling both plain `.jsonl` and
/// XZ-compressed files based on the file extension.
///
/// - Files ending in `.jsonl` are read as plain text.
/// - All other files (including `.jsonl.xz`, no extension, etc.) are opened with XzDecoder.
fn open_jsonl_reader(path: &Path) -> Result<BufReader<Box<dyn Read + Send>>> {
    // `path` comes from operator-controlled config (CLI/config file), not HTTP input.
    let file = File::open(path).context(format!("Failed to open file: {:?}", path))?; // nosemgrep: rust.actix.path-traversal.tainted-path.tainted-path
    let reader: Box<dyn Read + Send> = match path.extension().and_then(|e| e.to_str()) {
        Some("jsonl") => Box::new(file),
        _ => Box::new(XzDecoder::new(file)),
    };
    Ok(BufReader::new(reader))
}

/// Extract a Discogs numeric ID from a Discogs URL of the form:
/// `https://www.discogs.com/{entity_type}/{id}` or
/// `https://www.discogs.com/{entity_type}/{id}-Some-Slug`
///
/// Returns `None` for non-Discogs URLs or when the ID segment is not a valid integer.
pub fn extract_discogs_id(url: &str, entity_type: &str) -> Option<i64> {
    let prefix = format!("https://www.discogs.com/{entity_type}/");
    let id_segment = url.strip_prefix(&prefix)?;
    // The segment may be just a number or `{id}-{slug}`
    let id_str = id_segment.split('-').next()?;
    id_str.parse::<i64>().ok()
}

/// Extract URL-type relationships from the unified `relations` array.
///
/// MusicBrainz JSON dumps store all relationships (artist-to-artist, artist-to-url, etc.)
/// in a single `relations` array. URL relationships are identified by `"target-type": "url"`.
/// This function filters for those entries only.
fn extract_url_rels(relations: &[Value]) -> Vec<Value> {
    relations.iter().filter(|rel| rel["target-type"].as_str() == Some("url")).cloned().collect()
}

/// Extract entity-to-entity relationships from the unified `relations` array,
/// normalizing to a flat format with `target_mbid` and `target_type` fields.
///
/// URL-type relations are excluded (they're captured separately via
/// [`extract_url_rels`] → [`extract_external_links`]).
///
/// The MusicBrainz dump stores the target entity under a key matching
/// `target-type` (e.g., `rel["artist"]["id"]` for `target-type: "artist"`).
/// This function normalizes that to `target_mbid` for downstream consumers.
fn extract_entity_rels(relations: &[Value]) -> Vec<Value> {
    relations
        .iter()
        .filter_map(|rel| {
            let target_type = rel["target-type"].as_str()?;
            if target_type == "url" {
                return None;
            }
            let target_mbid = rel[target_type]["id"].as_str().unwrap_or("");
            Some(serde_json::json!({
                "type": rel["type"],
                "target_type": target_type,
                "target_mbid": target_mbid,
                "direction": rel["direction"],
                "attributes": rel["attributes"],
                "begin_date": rel["begin"],
                "end_date": rel["end"],
                "ended": rel["ended"]
            }))
        })
        .collect()
}

/// Filter URL-rel entries, returning non-Discogs ones as `{"service": ..., "url": ...}` objects.
pub fn extract_external_links(url_rels: &[Value]) -> Vec<Value> {
    url_rels
        .iter()
        .filter_map(|rel| {
            let rel_type = rel["type"].as_str()?;
            if rel_type == "discogs" {
                return None;
            }
            let resource = rel["url"]["resource"].as_str()?;
            Some(serde_json::json!({
                "service": rel_type,
                "url": resource
            }))
        })
        .collect()
}

/// Find and return the Discogs numeric ID from a slice of url-rel objects.
///
/// Scans `url_rels` for an entry with `"type": "discogs"` and extracts the
/// numeric ID from the `url.resource` field using [`extract_discogs_id`].
/// Returns `Value::Null` when no matching rel is found.
fn find_discogs_id(url_rels: &[Value], entity_type: &str) -> Value {
    url_rels
        .iter()
        .find_map(|rel| {
            if rel["type"].as_str() == Some("discogs") {
                extract_discogs_id(rel["url"]["resource"].as_str()?, entity_type)
            } else {
                None
            }
        })
        .map(Value::from)
        .unwrap_or(Value::Null)
}

/// Parse a single MusicBrainz JSONL artist line into a [`DataMessage`].
pub fn parse_mb_artist_line(line: &str) -> Result<DataMessage> {
    let v: Value = serde_json::from_str(line).context("Failed to parse artist JSONL line")?;

    let mbid = v["id"].as_str().unwrap_or("unknown").to_string();
    let sha256 = String::new();

    let all_rels = v["relations"].as_array().map(|a| a.as_slice()).unwrap_or(&[]);
    let url_rels = extract_url_rels(all_rels);
    let entity_rels = extract_entity_rels(all_rels);
    let discogs_artist_id = find_discogs_id(&url_rels, "artist");
    let external_links = extract_external_links(&url_rels);

    let life_span = &v["life-span"];
    let area_name = v["area"]["name"].as_str().map(|s| Value::String(s.to_string())).unwrap_or(Value::Null);
    let begin_area_name = v["begin-area"]["name"].as_str().map(|s| Value::String(s.to_string())).unwrap_or(Value::Null);
    let end_area_name = v["end-area"]["name"].as_str().map(|s| Value::String(s.to_string())).unwrap_or(Value::Null);

    let data = serde_json::json!({
        "discogs_artist_id": discogs_artist_id,
        "name": v["name"],
        "sort_name": v["sort-name"],
        "mb_type": v["type"],
        "gender": v["gender"],
        "life_span": {
            "begin": life_span["begin"],
            "end": life_span["end"],
            "ended": life_span["ended"]
        },
        "area": area_name,
        "begin_area": begin_area_name,
        "end_area": end_area_name,
        "disambiguation": v["disambiguation"],
        "aliases": v["aliases"],
        "tags": v["tags"],
        "relations": entity_rels,
        "external_links": external_links
    });

    Ok(DataMessage { id: mbid, sha256, data, raw_xml: None })
}

/// Parse a single MusicBrainz JSONL label line into a [`DataMessage`].
pub fn parse_mb_label_line(line: &str) -> Result<DataMessage> {
    let v: Value = serde_json::from_str(line).context("Failed to parse label JSONL line")?;

    let mbid = v["id"].as_str().unwrap_or("unknown").to_string();
    let sha256 = String::new();

    let all_rels = v["relations"].as_array().map(|a| a.as_slice()).unwrap_or(&[]);
    let url_rels = extract_url_rels(all_rels);
    let entity_rels = extract_entity_rels(all_rels);
    let discogs_label_id = find_discogs_id(&url_rels, "label");
    let external_links = extract_external_links(&url_rels);

    let life_span = &v["life-span"];
    let area_name = v["area"]["name"].as_str().map(|s| Value::String(s.to_string())).unwrap_or(Value::Null);

    let data = serde_json::json!({
        "discogs_label_id": discogs_label_id,
        "name": v["name"],
        "mb_type": v["type"],
        "label_code": v["label-code"],
        "life_span": {
            "begin": life_span["begin"],
            "end": life_span["end"],
            "ended": life_span["ended"]
        },
        "area": area_name,
        "disambiguation": v["disambiguation"],
        "relations": entity_rels,
        "external_links": external_links
    });

    Ok(DataMessage { id: mbid, sha256, data, raw_xml: None })
}

/// Partition a flat `relations` array into URL-type relations (those with `"target-type": "url"`).
/// Parse a single MusicBrainz JSONL release line into a [`DataMessage`].
pub fn parse_mb_release_line(line: &str) -> Result<DataMessage> {
    let v: Value = serde_json::from_str(line).context("Failed to parse release JSONL line")?;

    let mbid = v["id"].as_str().unwrap_or("unknown").to_string();
    let sha256 = String::new();

    let all_rels = v["relations"].as_array().map(|a| a.as_slice()).unwrap_or(&[]);
    let url_rels = extract_url_rels(all_rels);
    let entity_rels = extract_entity_rels(all_rels);
    let discogs_release_id = find_discogs_id(&url_rels, "release");
    let external_links = extract_external_links(&url_rels);

    let release_group_mbid = v["release-group"]["id"].as_str().map(|s| Value::String(s.to_string())).unwrap_or(Value::Null);

    let data = serde_json::json!({
        "discogs_release_id": discogs_release_id,
        "name": v["title"],
        "disambiguation": v["disambiguation"],
        "barcode": v["barcode"],
        "status": v["status"],
        "release_group_mbid": release_group_mbid,
        "aliases": v["aliases"],
        "tags": v["tags"],
        "relations": entity_rels,
        "external_links": external_links
    });

    Ok(DataMessage { id: mbid, sha256, data, raw_xml: None })
}

/// Parse a single MusicBrainz JSONL release-group line into a [`DataMessage`].
pub fn parse_mb_release_group_line(line: &str) -> Result<DataMessage> {
    let v: Value = serde_json::from_str(line).context("Failed to parse release-group JSONL line")?;

    let mbid = v["id"].as_str().unwrap_or("unknown").to_string();
    let sha256 = String::new();

    let all_rels = v["relations"].as_array().map(|a| a.as_slice()).unwrap_or(&[]);
    let url_rels = extract_url_rels(all_rels);
    let entity_rels = extract_entity_rels(all_rels);
    let discogs_master_id = find_discogs_id(&url_rels, "master");
    let external_links = extract_external_links(&url_rels);

    let data = serde_json::json!({
        "discogs_master_id": discogs_master_id,
        "name": v["title"],
        "mb_type": v["primary-type"],
        "secondary_types": v["secondary-types"],
        "first_release_date": v["first-release-date"],
        "disambiguation": v["disambiguation"],
        "relations": entity_rels,
        "external_links": external_links
    });

    Ok(DataMessage { id: mbid, sha256, data, raw_xml: None })
}

/// First pass: build a map of MBID → Discogs ID by scanning URL relations in a JSONL file.
///
/// **Blocking:** This function performs synchronous I/O and must be run on a
/// blocking thread via `tokio::task::spawn_blocking`.
///
/// Scans the `relations` array for entries with `target-type: "url"` and `type: "discogs"`.
/// Only lines that contain a Discogs URL relation are added to the map.
/// Malformed lines are silently skipped.
pub fn build_mbid_discogs_map_from_file(path: &Path, entity_type: &str) -> Result<HashMap<String, i64>> {
    let reader = open_jsonl_reader(path).context(format!("Failed to open file for MBID map: {:?}", path))?;

    let mut map = HashMap::new();

    for line_result in reader.lines() {
        let line = match line_result {
            Ok(l) => l,
            Err(e) => {
                debug!("⚠️ Failed to read line during MBID map build: {e}");
                continue;
            }
        };
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        let v: Value = match serde_json::from_str(trimmed) {
            Ok(v) => v,
            Err(_) => continue,
        };
        let mbid = match v["id"].as_str() {
            Some(id) => id.to_string(),
            None => continue,
        };
        let all_rels = v["relations"].as_array().map(|a| a.as_slice()).unwrap_or(&[]);
        let url_rels = extract_url_rels(all_rels);
        if let Some(discogs_id) = url_rels.iter().find_map(|rel| {
            if rel["type"].as_str() == Some("discogs") {
                extract_discogs_id(rel["url"]["resource"].as_str()?, entity_type)
            } else {
                None
            }
        }) {
            map.insert(mbid, discogs_id);
        }
    }

    info!("📊 Built MBID→Discogs map: {} entries from {:?}", map.len(), path);
    Ok(map)
}

/// Enrich relationship entries with Discogs IDs from a lookup map.
///
/// For each relation, looks up `target_mbid` in `discogs_map` only when
/// the relation's `target_type` matches the entity type being processed.
/// Non-matching relations are passed through unchanged since the map only
/// contains IDs for one entity type.
///
/// The inserted field name is derived from the entity type — e.g.,
/// `"target_discogs_artist_id"` for artists, `"target_discogs_label_id"` for
/// labels. Currently only called for artists; if extended to other entity
/// types, ensure downstream consumers (brainzgraphinator) handle the
/// corresponding field name.
///
/// `entity_type` uses plural form from `DataType::as_str()` (e.g., "artists").
/// Relation `target_type` uses singular MusicBrainz form (e.g., "artist").
///
/// Expects relations already normalized by [`extract_entity_rels`] with
/// `target_mbid` and `target_type` fields.
pub fn enrich_relations(relations: Vec<Value>, discogs_map: &HashMap<String, i64>, entity_type: &str) -> Vec<Value> {
    // entity_type is plural ("artists"), target_type in relations is singular ("artist")
    let singular = match entity_type {
        "artists" => "artist",
        "labels" => "label",
        "releases" => "release",
        "release-groups" => "release-group",
        other => other.strip_suffix('s').unwrap_or(other),
    };
    let field_name = format!("target_discogs_{}_id", singular.replace('-', "_"));
    relations
        .into_iter()
        .map(|mut rel| {
            // Only enrich relations whose target matches the entity type
            let target_type = rel["target_type"].as_str().unwrap_or("");
            if target_type != singular {
                return rel;
            }
            let target_mbid = rel["target_mbid"].as_str().map(|s| s.to_string());
            let target_discogs_id: Value =
                target_mbid.as_deref().and_then(|mbid| discogs_map.get(mbid)).copied().map(Value::from).unwrap_or(Value::Null);
            if let Some(obj) = rel.as_object_mut() {
                obj.insert(field_name.clone(), target_discogs_id);
            }
            rel
        })
        .collect()
}

/// Parse an xz-compressed MusicBrainz JSONL file line by line.
///
/// **Blocking:** This function performs synchronous I/O and must be run on a
/// blocking thread via `tokio::task::spawn_blocking`. Calling it directly from
/// an async context will panic.
///
/// When `discogs_map` is `Some`, artist relation targets are enriched with
/// `target_discogs_artist_id` using the provided MBID→Discogs ID lookup map.
///
/// Sends each successfully parsed [`DataMessage`] through `sender`.
/// Malformed lines are skipped with a debug log.
/// Returns the total count of records successfully parsed and sent.
pub fn parse_mb_jsonl_file(
    path: &Path,
    data_type: DataType,
    sender: mpsc::Sender<DataMessage>,
    discogs_map: Option<&HashMap<String, i64>>,
) -> Result<u64> {
    let reader = open_jsonl_reader(path).context(format!("Failed to open JSONL file: {:?}", path))?;

    let parse_fn: fn(&str) -> Result<DataMessage> = match data_type {
        DataType::Artists => parse_mb_artist_line,
        DataType::Labels => parse_mb_label_line,
        DataType::Releases => parse_mb_release_line,
        DataType::ReleaseGroups => parse_mb_release_group_line,
        DataType::Masters => {
            warn!("⚠️ MusicBrainz does not have a Masters data type; skipping file {:?}", path);
            return Ok(0);
        }
    };

    let mut count = 0u64;
    for line_result in reader.lines() {
        let line = match line_result {
            Ok(l) => l,
            Err(e) => {
                debug!("⚠️ Failed to read line: {e}");
                continue;
            }
        };
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        match parse_fn(trimmed) {
            Ok(mut msg) => {
                // Enrich relations with target Discogs IDs when a map is provided
                if let Some(map) = discogs_map
                    && let Some(relations) = msg.data.get("relations").and_then(|r| r.as_array()).cloned()
                {
                    let enriched = enrich_relations(relations, map, data_type.as_str());
                    if let Some(obj) = msg.data.as_object_mut() {
                        obj.insert("relations".to_string(), Value::Array(enriched));
                    }
                }
                if sender.blocking_send(msg).is_err() {
                    warn!("⚠️ Receiver dropped, stopping JSONL parsing");
                    break;
                }
                count += 1;
                if count.is_multiple_of(100_000) {
                    info!("🔄 Parsed {} {} MusicBrainz records", count, data_type);
                }
            }
            Err(e) => {
                debug!("⚠️ Skipping malformed JSONL line: {e}");
            }
        }
    }

    info!("✅ Finished parsing {} {} MusicBrainz records from {:?}", count, data_type, path);
    Ok(count)
}

#[cfg(test)]
#[path = "tests/jsonl_parser_tests.rs"]
mod tests;
