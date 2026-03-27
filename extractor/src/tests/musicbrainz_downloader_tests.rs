use super::*;
use std::io::Write;
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

#[test]
fn test_parse_version_directories_from_html() {
    let html = r#"<html><body>
        <a href="20260321-001002/">20260321-001002/</a>
        <a href="20260325-001001/">20260325-001001/</a>
        <a href="LATEST">LATEST</a>
        <a href="latest-is-20260325-001001">latest-is-20260325-001001</a>
        <a href="../">../</a>
    </body></html>"#;

    let versions = parse_version_directories(html);
    assert_eq!(versions, vec!["20260325-001001".to_string(), "20260321-001002".to_string()]);
}

#[test]
fn test_parse_version_directories_empty() {
    let html = r#"<html><body><a href="../">../</a></body></html>"#;
    let versions = parse_version_directories(html);
    assert!(versions.is_empty());
}

#[test]
fn test_parse_sha256sums() {
    let content = "dacfc4327ad44074d043c4184b77bebbcb4b41e926cc8f57742e6b2572d33624 *artist.tar.xz\n\
                   92952108bdae756d9c75cad1c82a2c1dfdc50fcd60d5405f622b93a7a7793007 *label.tar.xz\n\
                   48aec88150f56a51f685f585854c92e56711a4bd867a6ada48a93f60f5a73682 *release.tar.xz\n";

    let checksums = parse_sha256sums(content);
    assert_eq!(checksums.len(), 3);
    assert_eq!(checksums.get("artist.tar.xz").unwrap(), "dacfc4327ad44074d043c4184b77bebbcb4b41e926cc8f57742e6b2572d33624");
    assert_eq!(checksums.get("label.tar.xz").unwrap(), "92952108bdae756d9c75cad1c82a2c1dfdc50fcd60d5405f622b93a7a7793007");
    assert_eq!(checksums.get("release.tar.xz").unwrap(), "48aec88150f56a51f685f585854c92e56711a4bd867a6ada48a93f60f5a73682");
}

#[test]
fn test_extract_entity_from_tarball() {
    let dir = TempDir::new().unwrap();
    let tar_path = dir.path().join("label.tar.xz");
    let out_path = dir.path().join("label.jsonl");

    // Build tar archive in memory
    let mut tar_data = Vec::new();
    {
        let mut builder = tar::Builder::new(&mut tar_data);
        let content = b"{\"id\":\"abc-123\",\"name\":\"Test Label\"}\n{\"id\":\"def-456\",\"name\":\"Another Label\"}\n";
        let mut header = tar::Header::new_gnu();
        header.set_path("label/mbdump/label").unwrap();
        header.set_size(content.len() as u64);
        header.set_mode(0o644);
        header.set_cksum();
        builder.append(&header, &content[..]).unwrap();

        // Add a decoy file that should be ignored
        let decoy = b"This is the README";
        let mut decoy_header = tar::Header::new_gnu();
        decoy_header.set_path("label/README").unwrap();
        decoy_header.set_size(decoy.len() as u64);
        decoy_header.set_mode(0o644);
        decoy_header.set_cksum();
        builder.append(&decoy_header, &decoy[..]).unwrap();

        builder.finish().unwrap();
    }

    // XZ-compress the tar data
    let mut xz_file = std::fs::File::create(&tar_path).unwrap();
    let mut encoder = xz2::write::XzEncoder::new(Vec::new(), 1);
    encoder.write_all(&tar_data).unwrap();
    let compressed = encoder.finish().unwrap();
    xz_file.write_all(&compressed).unwrap();
    drop(xz_file);

    extract_entity_from_tarball(&tar_path, "label", &out_path).unwrap();

    assert!(out_path.exists());
    let extracted = std::fs::read_to_string(&out_path).unwrap();
    assert!(extracted.contains("Test Label"));
    assert!(extracted.contains("Another Label"));
    assert!(tar_path.exists()); // caller handles cleanup
}

#[test]
fn test_extract_entity_from_tarball_missing_entity() {
    let dir = TempDir::new().unwrap();
    let tar_path = dir.path().join("artist.tar.xz");
    let out_path = dir.path().join("artist.jsonl");

    let mut tar_data = Vec::new();
    {
        let mut builder = tar::Builder::new(&mut tar_data);
        let content = b"readme content";
        let mut header = tar::Header::new_gnu();
        header.set_path("artist/README").unwrap();
        header.set_size(content.len() as u64);
        header.set_mode(0o644);
        header.set_cksum();
        builder.append(&header, &content[..]).unwrap();
        builder.finish().unwrap();
    }

    let mut xz_file = std::fs::File::create(&tar_path).unwrap();
    let mut encoder = xz2::write::XzEncoder::new(Vec::new(), 1);
    encoder.write_all(&tar_data).unwrap();
    let compressed = encoder.finish().unwrap();
    xz_file.write_all(&compressed).unwrap();
    drop(xz_file);

    let result = extract_entity_from_tarball(&tar_path, "artist", &out_path);
    assert!(result.is_err());
    assert!(!out_path.exists());
}
