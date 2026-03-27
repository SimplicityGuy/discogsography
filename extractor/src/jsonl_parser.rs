use anyhow::{Context, Result};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::Path;
use tokio::sync::mpsc;
use tracing::{debug, info, warn};
use xz2::read::XzDecoder;

use crate::types::{DataMessage, DataType};

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

/// Compute SHA-256 of the raw line string.
fn hash_line(line: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(line.as_bytes());
    format!("{:x}", hasher.finalize())
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
    let sha256 = hash_line(line);

    let url_rels = v["url-rels"].as_array().map(|a| a.as_slice()).unwrap_or(&[]);
    let discogs_artist_id = find_discogs_id(url_rels, "artist");
    let external_links = extract_external_links(url_rels);

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
        "relations": v["relations"],
        "external_links": external_links
    });

    Ok(DataMessage { id: mbid, sha256, data, raw_xml: None })
}

/// Parse a single MusicBrainz JSONL label line into a [`DataMessage`].
pub fn parse_mb_label_line(line: &str) -> Result<DataMessage> {
    let v: Value = serde_json::from_str(line).context("Failed to parse label JSONL line")?;

    let mbid = v["id"].as_str().unwrap_or("unknown").to_string();
    let sha256 = hash_line(line);

    let url_rels = v["url-rels"].as_array().map(|a| a.as_slice()).unwrap_or(&[]);
    let discogs_label_id = find_discogs_id(url_rels, "label");
    let external_links = extract_external_links(url_rels);

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
        "relations": v["relations"],
        "external_links": external_links
    });

    Ok(DataMessage { id: mbid, sha256, data, raw_xml: None })
}

/// Parse a single MusicBrainz JSONL release line into a [`DataMessage`].
pub fn parse_mb_release_line(line: &str) -> Result<DataMessage> {
    let v: Value = serde_json::from_str(line).context("Failed to parse release JSONL line")?;

    let mbid = v["id"].as_str().unwrap_or("unknown").to_string();
    let sha256 = hash_line(line);

    let url_rels = v["url-rels"].as_array().map(|a| a.as_slice()).unwrap_or(&[]);
    let discogs_release_id = find_discogs_id(url_rels, "release");
    let external_links = extract_external_links(url_rels);

    let release_group_mbid = v["release-group"]["id"].as_str().map(|s| Value::String(s.to_string())).unwrap_or(Value::Null);

    let data = serde_json::json!({
        "discogs_release_id": discogs_release_id,
        "name": v["title"],
        "barcode": v["barcode"],
        "status": v["status"],
        "release_group_mbid": release_group_mbid,
        "relations": v["relations"],
        "external_links": external_links
    });

    Ok(DataMessage { id: mbid, sha256, data, raw_xml: None })
}

/// First pass: build a map of MBID → Discogs ID by scanning all url-rels in an xz-compressed JSONL file.
///
/// **Blocking:** This function performs synchronous I/O and must be run on a
/// blocking thread via `tokio::task::spawn_blocking`.
///
/// Only lines that contain a Discogs url-rel are added to the map.
/// Malformed lines are silently skipped.
pub fn build_mbid_discogs_map_from_file(path: &Path, entity_type: &str) -> Result<HashMap<String, i64>> {
    // `path` comes from operator-controlled config (CLI/config file), not HTTP input.
    let file = File::open(path).context(format!("Failed to open file for MBID map: {:?}", path))?; // nosemgrep: rust.actix.path-traversal.tainted-path.tainted-path
    let decoder = XzDecoder::new(file);
    let reader = BufReader::new(decoder);

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
        let url_rels = v["url-rels"].as_array().map(|a| a.as_slice()).unwrap_or(&[]);
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

/// Enrich relationship target entries with Discogs IDs from a lookup map.
///
/// For each relation, looks up the target's MBID in `discogs_map`. If found,
/// adds `"target_discogs_artist_id": <id>` to the relation object. If not
/// found, adds `"target_discogs_artist_id": null`.
pub fn enrich_relations(relations: Vec<Value>, discogs_map: &HashMap<String, i64>) -> Vec<Value> {
    relations
        .into_iter()
        .map(|mut rel| {
            let target_mbid = rel["target"]["id"].as_str().map(|s| s.to_string());
            let target_discogs_id: Value =
                target_mbid.as_deref().and_then(|mbid| discogs_map.get(mbid)).copied().map(Value::from).unwrap_or(Value::Null);
            if let Some(obj) = rel.as_object_mut() {
                obj.insert("target_discogs_artist_id".to_string(), target_discogs_id);
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
    // `path` comes from operator-controlled config (CLI/config file), not HTTP input.
    let file = File::open(path).context(format!("Failed to open file: {:?}", path))?; // nosemgrep: rust.actix.path-traversal.tainted-path.tainted-path
    let decoder = XzDecoder::new(file);
    let reader = BufReader::new(decoder);

    let parse_fn: fn(&str) -> Result<DataMessage> = match data_type {
        DataType::Artists => parse_mb_artist_line,
        DataType::Labels => parse_mb_label_line,
        DataType::Releases => parse_mb_release_line,
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
                    let enriched = enrich_relations(relations, map);
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
