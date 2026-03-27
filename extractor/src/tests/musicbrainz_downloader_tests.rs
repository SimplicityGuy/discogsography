use super::*;
use tempfile::TempDir;

#[test]
fn test_discover_mb_dump_files_exact_patterns() {
    let dir = TempDir::new().unwrap();
    std::fs::write(dir.path().join("artist.jsonl.xz"), b"fake").unwrap();
    std::fs::write(dir.path().join("label.jsonl.xz"), b"fake").unwrap();
    std::fs::write(dir.path().join("release.jsonl.xz"), b"fake").unwrap();

    let found = discover_mb_dump_files(dir.path()).unwrap();

    assert_eq!(found.len(), 3);
    assert!(found.contains_key(&DataType::Artists));
    assert!(found.contains_key(&DataType::Labels));
    assert!(found.contains_key(&DataType::Releases));
}

#[test]
fn test_discover_mb_dump_files_mbdump_prefix() {
    let dir = TempDir::new().unwrap();
    std::fs::write(dir.path().join("mbdump-artist.jsonl.xz"), b"fake").unwrap();
    std::fs::write(dir.path().join("mbdump-label.jsonl.xz"), b"fake").unwrap();

    let found = discover_mb_dump_files(dir.path()).unwrap();

    assert_eq!(found.len(), 2);
    assert!(found.contains_key(&DataType::Artists));
    assert!(found.contains_key(&DataType::Labels));
}

#[test]
fn test_discover_mb_dump_files_fuzzy_match() {
    let dir = TempDir::new().unwrap();
    // Non-standard name containing "artist" and ending in .jsonl.xz
    std::fs::write(dir.path().join("my-custom-artist-dump.jsonl.xz"), b"fake").unwrap();

    let found = discover_mb_dump_files(dir.path()).unwrap();

    assert_eq!(found.len(), 1);
    assert!(found.contains_key(&DataType::Artists));
}

#[test]
fn test_discover_mb_dump_files_empty_dir() {
    let dir = TempDir::new().unwrap();

    let found = discover_mb_dump_files(dir.path()).unwrap();

    assert!(found.is_empty());
}

#[test]
fn test_discover_mb_dump_files_nonexistent_dir() {
    let found = discover_mb_dump_files(Path::new("/nonexistent/path/to/mb/dumps")).unwrap();

    assert!(found.is_empty());
}

#[test]
fn test_discover_mb_dump_files_ignores_non_jsonl_xz() {
    let dir = TempDir::new().unwrap();
    std::fs::write(dir.path().join("artist.json"), b"fake").unwrap();
    std::fs::write(dir.path().join("artist.xml.gz"), b"fake").unwrap();

    let found = discover_mb_dump_files(dir.path()).unwrap();

    assert!(found.is_empty());
}

#[test]
fn test_discover_mb_dump_files_bare_jsonl() {
    let dir = TempDir::new().unwrap();
    std::fs::write(dir.path().join("artist.jsonl"), b"fake").unwrap();
    std::fs::write(dir.path().join("label.jsonl"), b"fake").unwrap();
    std::fs::write(dir.path().join("release.jsonl"), b"fake").unwrap();

    let found = discover_mb_dump_files(dir.path()).unwrap();

    assert_eq!(found.len(), 3);
    assert!(found.contains_key(&DataType::Artists));
    assert!(found.contains_key(&DataType::Labels));
    assert!(found.contains_key(&DataType::Releases));
}

#[test]
fn test_detect_mb_dump_version_from_date_dir() {
    let version = detect_mb_dump_version(Path::new("/data/20260322"));
    assert_eq!(version, "20260322");
}

#[test]
fn test_detect_mb_dump_version_from_prefixed_dir() {
    let version = detect_mb_dump_version(Path::new("/data/mbdump-20260315"));
    assert_eq!(version, "20260315");
}

#[test]
fn test_detect_mb_dump_version_fallback_to_current_date() {
    let version = detect_mb_dump_version(Path::new("/data/musicbrainz"));
    // Should be today's date in YYYYMMDD format
    let today = chrono::Utc::now().format("%Y%m%d").to_string();
    assert_eq!(version, today);
}

#[test]
fn test_detect_mb_dump_version_root_path() {
    // Edge case: root path "/"
    let version = detect_mb_dump_version(Path::new("/"));
    let today = chrono::Utc::now().format("%Y%m%d").to_string();
    assert_eq!(version, today);
}

#[test]
fn test_discover_mb_dump_files_exact_preferred_over_fuzzy() {
    let dir = TempDir::new().unwrap();
    // Both exact and fuzzy match exist; exact should win
    std::fs::write(dir.path().join("artist.jsonl.xz"), b"exact").unwrap();
    std::fs::write(dir.path().join("custom-artist-v2.jsonl.xz"), b"fuzzy").unwrap();

    let found = discover_mb_dump_files(dir.path()).unwrap();

    assert_eq!(found.len(), 1);
    let artist_path = found.get(&DataType::Artists).unwrap();
    assert!(artist_path.ends_with("artist.jsonl.xz"));
}

#[test]
fn test_find_latest_mb_directory_single() {
    let dir = TempDir::new().unwrap();
    std::fs::create_dir(dir.path().join("20260325-001001")).unwrap();

    let result = find_latest_mb_directory(dir.path());
    assert_eq!(result, Some(dir.path().join("20260325-001001")));
}

#[test]
fn test_find_latest_mb_directory_multiple() {
    let dir = TempDir::new().unwrap();
    std::fs::create_dir(dir.path().join("20260321-001002")).unwrap();
    std::fs::create_dir(dir.path().join("20260325-001001")).unwrap();

    let result = find_latest_mb_directory(dir.path());
    assert_eq!(result, Some(dir.path().join("20260325-001001")));
}

#[test]
fn test_find_latest_mb_directory_empty() {
    let dir = TempDir::new().unwrap();

    let result = find_latest_mb_directory(dir.path());
    assert_eq!(result, None);
}

#[test]
fn test_find_latest_mb_directory_ignores_non_version_dirs() {
    let dir = TempDir::new().unwrap();
    std::fs::create_dir(dir.path().join("some-random-dir")).unwrap();
    std::fs::create_dir(dir.path().join("20260325-001001")).unwrap();

    let result = find_latest_mb_directory(dir.path());
    assert_eq!(result, Some(dir.path().join("20260325-001001")));
}
