use super::*;
use hex;
use std::io::{Read, Write};
use tempfile::TempDir;

#[tokio::test]
async fn test_download_latest_already_current() {
    let dir = TempDir::new().unwrap();

    let mut server = mockito::Server::new_async().await;
    let base_url = format!("{}/", server.url());

    let index_html = r#"<html><body>
        <a href="20260325-001001/">20260325-001001/</a>
    </body></html>"#;

    let _index_mock = server.mock("GET", "/").with_status(200).with_body(index_html).create_async().await;

    // Create existing version directory with all entity files
    let version_dir = dir.path().join("20260325-001001");
    std::fs::create_dir(&version_dir).unwrap();
    std::fs::write(version_dir.join("artist.jsonl"), b"data").unwrap();
    std::fs::write(version_dir.join("label.jsonl"), b"data").unwrap();
    std::fs::write(version_dir.join("release-group.jsonl"), b"data").unwrap();
    std::fs::write(version_dir.join("release.jsonl"), b"data").unwrap();

    let downloader = MbDownloader::new(dir.path().to_path_buf(), base_url);
    let result = downloader.download_latest().await.unwrap();

    assert!(matches!(result, MbDownloadResult::AlreadyCurrent(v) if v == "20260325-001001"));
}

#[tokio::test]
async fn test_download_latest_new_version() {
    let dir = TempDir::new().unwrap();

    let mut server = mockito::Server::new_async().await;
    let base_url = format!("{}/", server.url());

    let index_html = r#"<html><body>
        <a href="20260325-001001/">20260325-001001/</a>
    </body></html>"#;
    let _index_mock = server.mock("GET", "/").with_status(200).with_body(index_html).create_async().await;

    // Build a tiny tar.xz for each entity
    let mut tar_bodies: std::collections::HashMap<String, Vec<u8>> = std::collections::HashMap::new();
    let mut sha256_lines = String::new();

    for entity in &["artist", "label", "release-group", "release"] {
        let content = format!("{{\"id\":\"test-{}\"}}\n", entity);
        let mut tar_data = Vec::new();
        {
            let mut builder = tar::Builder::new(&mut tar_data);
            let bytes = content.as_bytes();
            let mut header = tar::Header::new_gnu();
            header.set_path(format!("{}/mbdump/{}", entity, entity)).unwrap();
            header.set_size(bytes.len() as u64);
            header.set_mode(0o644);
            header.set_cksum();
            builder.append(&header, bytes).unwrap();
            builder.finish().unwrap();
        }
        let mut encoder = xz2::write::XzEncoder::new(Vec::new(), 1);
        encoder.write_all(&tar_data).unwrap();
        let compressed = encoder.finish().unwrap();

        let hash = hex::encode(sha2::Sha256::digest(&compressed));
        sha256_lines.push_str(&format!("{} *{}.tar.xz\n", hash, entity));
        tar_bodies.insert(entity.to_string(), compressed);
    }

    let _sha_mock = server.mock("GET", "/20260325-001001/SHA256SUMS").with_status(200).with_body(&sha256_lines).create_async().await;

    let _artist_mock = server
        .mock("GET", "/20260325-001001/artist.tar.xz")
        .with_status(200)
        .with_body(tar_bodies.get("artist").unwrap().clone())
        .create_async()
        .await;
    let _label_mock = server
        .mock("GET", "/20260325-001001/label.tar.xz")
        .with_status(200)
        .with_body(tar_bodies.get("label").unwrap().clone())
        .create_async()
        .await;
    let _release_group_mock = server
        .mock("GET", "/20260325-001001/release-group.tar.xz")
        .with_status(200)
        .with_body(tar_bodies.get("release-group").unwrap().clone())
        .create_async()
        .await;
    let _release_mock = server
        .mock("GET", "/20260325-001001/release.tar.xz")
        .with_status(200)
        .with_body(tar_bodies.get("release").unwrap().clone())
        .create_async()
        .await;

    let downloader = MbDownloader::new(dir.path().to_path_buf(), base_url);
    let result = downloader.download_latest().await.unwrap();

    assert!(matches!(result, MbDownloadResult::Downloaded(v) if v == "20260325-001001"));

    let version_dir = dir.path().join("20260325-001001");
    assert!(version_dir.join("artist.jsonl.xz").exists());
    assert!(version_dir.join("label.jsonl.xz").exists());
    assert!(version_dir.join("release-group.jsonl.xz").exists());
    assert!(version_dir.join("release.jsonl.xz").exists());

    // Verify temp files and source tarballs are cleaned up after extraction
    assert!(!version_dir.join("artist.tar.xz.tmp").exists());
    assert!(!version_dir.join("artist.tar.xz").exists());
    assert!(!version_dir.join("label.tar.xz").exists());
    assert!(!version_dir.join("release-group.tar.xz").exists());
    assert!(!version_dir.join("release.tar.xz").exists());

    // Verify content via decompression round-trip
    let file = std::fs::File::open(version_dir.join("artist.jsonl.xz")).unwrap();
    let mut decoder = xz2::read::XzDecoder::new(file);
    let mut artist_content = String::new();
    decoder.read_to_string(&mut artist_content).unwrap();
    assert!(artist_content.contains("test-artist"));
}

#[tokio::test]
async fn test_download_latest_sha256_mismatch() {
    let dir = TempDir::new().unwrap();

    let mut server = mockito::Server::new_async().await;
    let base_url = format!("{}/", server.url());

    let index_html = r#"<html><body>
        <a href="20260325-001001/">20260325-001001/</a>
    </body></html>"#;
    let _index_mock = server.mock("GET", "/").with_status(200).with_body(index_html).create_async().await;

    let _sha_mock = server
        .mock("GET", "/20260325-001001/SHA256SUMS")
        .with_status(200)
        .with_body("0000000000000000000000000000000000000000000000000000000000000000 *artist.tar.xz\n")
        .create_async()
        .await;

    // Serve some data that won't match the wrong hash
    let tar_data = vec![0u8; 10];
    let _artist_mock = server
        .mock("GET", "/20260325-001001/artist.tar.xz")
        .with_status(200)
        .with_body(tar_data)
        .expect_at_least(1)
        .create_async()
        .await;

    let downloader = MbDownloader::new(dir.path().to_path_buf(), base_url);
    let result = downloader.download_latest().await;

    assert!(result.is_err());
    let err_msg = format!("{}", result.unwrap_err());
    // With streaming, invalid data fails at the xz/tar decoder or at SHA256 verification.
    assert!(
        err_msg.contains("SHA256") || err_msg.contains("checksum") || err_msg.contains("mismatch") || err_msg.contains("tar") || err_msg.contains("failed"),
        "Error should indicate corrupt data or checksum mismatch: {}",
        err_msg,
    );
}

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
    let out_path = dir.path().join("label.jsonl.xz");

    let original_content = "{\"id\":\"abc-123\",\"name\":\"Test Label\"}\n{\"id\":\"def-456\",\"name\":\"Another Label\"}\n";

    // Build tar archive in memory
    let mut tar_data = Vec::new();
    {
        let mut builder = tar::Builder::new(&mut tar_data);
        let content = original_content.as_bytes();
        let mut header = tar::Header::new_gnu();
        header.set_path("label/mbdump/label").unwrap();
        header.set_size(content.len() as u64);
        header.set_mode(0o644);
        header.set_cksum();
        builder.append(&header, content).unwrap();

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
    assert!(tar_path.exists()); // original tarball preserved

    // Decompress the output and verify round-trip integrity
    let file = std::fs::File::open(&out_path).unwrap();
    let mut decoder = xz2::read::XzDecoder::new(file);
    let mut decompressed = String::new();
    decoder.read_to_string(&mut decompressed).unwrap();
    assert_eq!(decompressed, original_content);
}

#[test]
fn test_extract_entity_from_tarball_missing_entity() {
    let dir = TempDir::new().unwrap();
    let tar_path = dir.path().join("artist.tar.xz");
    let out_path = dir.path().join("artist.jsonl.xz");

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
    assert!(!out_path.exists()); // partial file cleaned up on failure
}

#[tokio::test]
async fn test_download_latest_retry_on_failure() {
    use std::io::Write;

    let dir = TempDir::new().unwrap();

    let mut server = mockito::Server::new_async().await;
    let base_url = format!("{}/", server.url());

    let index_html = r#"<html><body>
        <a href="20260325-001001/">20260325-001001/</a>
    </body></html>"#;
    let _index_mock = server.mock("GET", "/").with_status(200).with_body(index_html).create_async().await;

    // Build valid tar.xz for all entities
    let mut tar_bodies: std::collections::HashMap<String, Vec<u8>> = std::collections::HashMap::new();
    let mut sha256_lines = String::new();

    for entity in &["artist", "label", "release-group", "release"] {
        let content = format!("{{\"id\":\"{}\"}}\n", entity);
        let mut tar_data = Vec::new();
        {
            let mut builder = tar::Builder::new(&mut tar_data);
            let bytes = content.as_bytes();
            let mut header = tar::Header::new_gnu();
            header.set_path(format!("{}/mbdump/{}", entity, entity)).unwrap();
            header.set_size(bytes.len() as u64);
            header.set_mode(0o644);
            header.set_cksum();
            builder.append(&header, bytes).unwrap();
            builder.finish().unwrap();
        }
        let mut encoder = xz2::write::XzEncoder::new(Vec::new(), 1);
        encoder.write_all(&tar_data).unwrap();
        let compressed = encoder.finish().unwrap();
        let hash = hex::encode(sha2::Sha256::digest(&compressed));
        sha256_lines.push_str(&format!("{} *{}.tar.xz\n", hash, entity));
        tar_bodies.insert(entity.to_string(), compressed);
    }

    let _sha_mock = server.mock("GET", "/20260325-001001/SHA256SUMS").with_status(200).with_body(&sha256_lines).create_async().await;

    // artist: first request fails (500), second succeeds
    let _artist_fail = server
        .mock("GET", "/20260325-001001/artist.tar.xz")
        .with_status(500)
        .with_body("Internal Server Error")
        .expect(1)
        .create_async()
        .await;
    let _artist_ok = server
        .mock("GET", "/20260325-001001/artist.tar.xz")
        .with_status(200)
        .with_body(tar_bodies.get("artist").unwrap().clone())
        .expect(1)
        .create_async()
        .await;

    // label, release-group, and release succeed immediately
    let _label_mock = server
        .mock("GET", "/20260325-001001/label.tar.xz")
        .with_status(200)
        .with_body(tar_bodies.get("label").unwrap().clone())
        .create_async()
        .await;
    let _release_group_mock = server
        .mock("GET", "/20260325-001001/release-group.tar.xz")
        .with_status(200)
        .with_body(tar_bodies.get("release-group").unwrap().clone())
        .create_async()
        .await;
    let _release_mock = server
        .mock("GET", "/20260325-001001/release.tar.xz")
        .with_status(200)
        .with_body(tar_bodies.get("release").unwrap().clone())
        .create_async()
        .await;

    let downloader = MbDownloader::new(dir.path().to_path_buf(), base_url);
    let result = downloader.download_latest().await.unwrap();

    assert!(matches!(result, MbDownloadResult::Downloaded(_)));
    assert!(dir.path().join("20260325-001001/artist.jsonl.xz").exists());
    // Source tarball is deleted after successful extraction to reclaim disk space
    assert!(!dir.path().join("20260325-001001/artist.tar.xz").exists());
}

// ── is_version_complete ─────────────────────────────────────────────────

#[test]
fn test_is_version_complete_true() {
    let dir = TempDir::new().unwrap();
    let version_dir = dir.path().join("20260325-001001");
    std::fs::create_dir(&version_dir).unwrap();
    std::fs::write(version_dir.join("artist.jsonl"), b"data").unwrap();
    std::fs::write(version_dir.join("label.jsonl"), b"data").unwrap();
    std::fs::write(version_dir.join("release-group.jsonl"), b"data").unwrap();
    std::fs::write(version_dir.join("release.jsonl"), b"data").unwrap();

    let downloader = MbDownloader::new(dir.path().to_path_buf(), "http://unused".to_string());
    assert!(downloader.is_version_complete(&version_dir));
}

#[test]
fn test_is_version_complete_missing_one_file() {
    let dir = TempDir::new().unwrap();
    let version_dir = dir.path().join("20260325-001001");
    std::fs::create_dir(&version_dir).unwrap();
    std::fs::write(version_dir.join("artist.jsonl"), b"data").unwrap();
    std::fs::write(version_dir.join("label.jsonl"), b"data").unwrap();
    // release.jsonl is missing

    let downloader = MbDownloader::new(dir.path().to_path_buf(), "http://unused".to_string());
    assert!(!downloader.is_version_complete(&version_dir));
}

#[test]
fn test_is_version_complete_nonexistent_dir() {
    let dir = TempDir::new().unwrap();
    let version_dir = dir.path().join("nonexistent");

    let downloader = MbDownloader::new(dir.path().to_path_buf(), "http://unused".to_string());
    assert!(!downloader.is_version_complete(&version_dir));
}

// ── MbDownloadResult::version ───────────────────────────────────────────

#[test]
fn test_mb_download_result_version_already_current() {
    let result = MbDownloadResult::AlreadyCurrent("20260325-001001".to_string());
    assert_eq!(result.version(), "20260325-001001");
}

#[test]
fn test_mb_download_result_version_downloaded() {
    let result = MbDownloadResult::Downloaded("20260325-001001".to_string());
    assert_eq!(result.version(), "20260325-001001");
}

// ── download_latest error paths ─────────────────────────────────────────

#[tokio::test]
async fn test_download_latest_no_versions_found() {
    let dir = TempDir::new().unwrap();

    let mut server = mockito::Server::new_async().await;
    let base_url = format!("{}/", server.url());

    // Empty HTML with no version directories
    let index_html = r#"<html><body><a href="../">Parent</a></body></html>"#;
    let _index_mock = server.mock("GET", "/").with_status(200).with_body(index_html).create_async().await;

    let downloader = MbDownloader::new(dir.path().to_path_buf(), base_url);
    let result = downloader.download_latest().await;

    assert!(result.is_err());
    let err_msg = format!("{}", result.unwrap_err());
    assert!(err_msg.contains("No version directories found"), "Unexpected error: {}", err_msg);
}

#[tokio::test]
async fn test_download_latest_sha256sums_missing_entry() {
    let dir = TempDir::new().unwrap();

    let mut server = mockito::Server::new_async().await;
    let base_url = format!("{}/", server.url());

    let index_html = r#"<html><body>
        <a href="20260325-001001/">20260325-001001/</a>
    </body></html>"#;
    let _index_mock = server.mock("GET", "/").with_status(200).with_body(index_html).create_async().await;

    // SHA256SUMS missing the artist entry
    let _sha_mock = server
        .mock("GET", "/20260325-001001/SHA256SUMS")
        .with_status(200)
        .with_body("abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234 *label.tar.xz\n")
        .create_async()
        .await;

    let downloader = MbDownloader::new(dir.path().to_path_buf(), base_url);
    let result = downloader.download_latest().await;

    assert!(result.is_err());
    let err_msg = format!("{}", result.unwrap_err());
    assert!(err_msg.contains("No SHA256 checksum found for artist.tar.xz"), "Unexpected error: {}", err_msg);
}

#[tokio::test]
async fn test_download_latest_connection_error_exhausts_retries() {
    let dir = TempDir::new().unwrap();

    let mut server = mockito::Server::new_async().await;
    let base_url = format!("{}/", server.url());

    let index_html = r#"<html><body>
        <a href="20260325-001001/">20260325-001001/</a>
    </body></html>"#;
    let _index_mock = server.mock("GET", "/").with_status(200).with_body(index_html).create_async().await;

    let sha_content = "abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234 *artist.tar.xz\n\
                        abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234 *label.tar.xz\n\
                        abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234 *release-group.tar.xz\n\
                        abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234 *release.tar.xz\n";
    let _sha_mock = server.mock("GET", "/20260325-001001/SHA256SUMS").with_status(200).with_body(sha_content).create_async().await;

    // All attempts return 500 — exhausts retries on the first entity
    let _artist_mock = server
        .mock("GET", "/20260325-001001/artist.tar.xz")
        .with_status(500)
        .with_body("Server Error")
        .expect_at_least(1)
        .create_async()
        .await;

    let downloader = MbDownloader::new(dir.path().to_path_buf(), base_url);
    let result = downloader.download_latest().await;

    assert!(result.is_err());
    let err_msg = format!("{}", result.unwrap_err());
    assert!(err_msg.contains("HTTP error") || err_msg.contains("failed"), "Unexpected error: {}", err_msg);
}

// ── find_latest_mb_directory edge cases ─────────────────────────────────

#[test]
fn test_find_latest_mb_directory_nonexistent_root() {
    let result = find_latest_mb_directory(Path::new("/nonexistent/root/path"));
    assert_eq!(result, None);
}

#[test]
fn test_find_latest_mb_directory_files_only_no_dirs() {
    let dir = TempDir::new().unwrap();
    // Create files with version-like names (not directories)
    std::fs::write(dir.path().join("20260325-001001"), b"file").unwrap();

    let result = find_latest_mb_directory(dir.path());
    assert_eq!(result, None);
}

// ── parse_sha256sums edge cases ─────────────────────────────────────────

#[test]
fn test_parse_sha256sums_empty() {
    let checksums = parse_sha256sums("");
    assert!(checksums.is_empty());
}

#[test]
fn test_parse_sha256sums_blank_lines() {
    let content = "\n  \nabcd1234 *file.tar.xz\n\n";
    let checksums = parse_sha256sums(content);
    assert_eq!(checksums.len(), 1);
    assert_eq!(checksums.get("file.tar.xz").unwrap(), "abcd1234");
}

// ── entity_keyword coverage ─────────────────────────────────────────────

#[test]
fn test_entity_keyword_masters() {
    // entity_keyword handles DataType::Masters
    assert_eq!(entity_keyword(DataType::Masters), "master");
}

#[test]
fn test_entity_keyword_release_groups() {
    assert_eq!(entity_keyword(DataType::ReleaseGroups), "release-group");
}

// ── discover_mb_dump_files: fuzzy .jsonl (no .xz) ───────────────────────

#[test]
fn test_discover_mb_dump_files_fuzzy_match_bare_jsonl() {
    let dir = TempDir::new().unwrap();
    // Non-standard name containing "release" and ending in .jsonl (not .xz)
    std::fs::write(dir.path().join("custom-release-v3.jsonl"), b"fake").unwrap();

    let found = discover_mb_dump_files(dir.path()).unwrap();

    assert_eq!(found.len(), 1);
    assert!(found.contains_key(&DataType::Releases));
}

#[tokio::test]
async fn test_download_latest_retry_cleans_up_dest_file() {
    // When a download attempt fails (e.g., checksum mismatch), the next retry
    // should clean up any leftover dest file from the previous attempt (line 264).
    use std::io::Write;

    let dir = TempDir::new().unwrap();

    let mut server = mockito::Server::new_async().await;
    let base_url = format!("{}/", server.url());

    let index_html = r#"<html><body>
        <a href="20260325-001001/">20260325-001001/</a>
    </body></html>"#;
    let _index_mock = server.mock("GET", "/").with_status(200).with_body(index_html).create_async().await;

    // Build a valid tar.xz for all entities
    let mut tar_bodies: std::collections::HashMap<String, Vec<u8>> = std::collections::HashMap::new();
    let mut sha256_lines = String::new();

    for entity in &["artist", "label", "release-group", "release"] {
        let content = format!("{{\"id\":\"{}\"}}\n", entity);
        let mut tar_data = Vec::new();
        {
            let mut builder = tar::Builder::new(&mut tar_data);
            let bytes = content.as_bytes();
            let mut header = tar::Header::new_gnu();
            header.set_path(format!("{}/mbdump/{}", entity, entity)).unwrap();
            header.set_size(bytes.len() as u64);
            header.set_mode(0o644);
            header.set_cksum();
            builder.append(&header, bytes).unwrap();
            builder.finish().unwrap();
        }
        let mut encoder = xz2::write::XzEncoder::new(Vec::new(), 1);
        encoder.write_all(&tar_data).unwrap();
        let compressed = encoder.finish().unwrap();
        let hash = hex::encode(sha2::Sha256::digest(&compressed));
        sha256_lines.push_str(&format!("{} *{}.tar.xz\n", hash, entity));
        tar_bodies.insert(entity.to_string(), compressed);
    }

    let _sha_mock = server.mock("GET", "/20260325-001001/SHA256SUMS").with_status(200).with_body(&sha256_lines).create_async().await;

    // artist: first request returns wrong data (checksum mismatch triggers retry with dest cleanup),
    // second request returns correct data
    let _artist_fail = server
        .mock("GET", "/20260325-001001/artist.tar.xz")
        .with_status(200)
        .with_body("this is wrong data that will fail checksum")
        .expect(1)
        .create_async()
        .await;
    let _artist_ok = server
        .mock("GET", "/20260325-001001/artist.tar.xz")
        .with_status(200)
        .with_body(tar_bodies.get("artist").unwrap().clone())
        .expect(1)
        .create_async()
        .await;

    // label, release-group, and release succeed immediately
    let _label_mock = server
        .mock("GET", "/20260325-001001/label.tar.xz")
        .with_status(200)
        .with_body(tar_bodies.get("label").unwrap().clone())
        .create_async()
        .await;
    let _release_group_mock = server
        .mock("GET", "/20260325-001001/release-group.tar.xz")
        .with_status(200)
        .with_body(tar_bodies.get("release-group").unwrap().clone())
        .create_async()
        .await;
    let _release_mock = server
        .mock("GET", "/20260325-001001/release.tar.xz")
        .with_status(200)
        .with_body(tar_bodies.get("release").unwrap().clone())
        .create_async()
        .await;

    let downloader = MbDownloader::new(dir.path().to_path_buf(), base_url);
    let result = downloader.download_latest().await.unwrap();

    assert!(matches!(result, MbDownloadResult::Downloaded(_)));
    // Verify the files exist and the dest file was cleaned up between retries
    assert!(dir.path().join("20260325-001001/artist.jsonl.xz").exists());
    assert!(dir.path().join("20260325-001001/label.jsonl.xz").exists());
    assert!(dir.path().join("20260325-001001/release.jsonl.xz").exists());
}

#[tokio::test]
async fn test_download_latest_empty_response_stream_error() {
    // When the server closes the connection after sending a response with content-length
    // but no body (or truncated body), the stream may yield an error.
    // Here we test with a 200 response that has empty body — download succeeds but
    // checksum mismatch triggers retry and cleanup logic.
    let dir = TempDir::new().unwrap();

    let mut server = mockito::Server::new_async().await;
    let base_url = format!("{}/", server.url());

    let index_html = r#"<html><body>
        <a href="20260325-001001/">20260325-001001/</a>
    </body></html>"#;
    let _index_mock = server.mock("GET", "/").with_status(200).with_body(index_html).create_async().await;

    let sha_content = "abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234 *artist.tar.xz\n\
                        abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234 *label.tar.xz\n\
                        abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234 *release-group.tar.xz\n\
                        abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234 *release.tar.xz\n";
    let _sha_mock = server.mock("GET", "/20260325-001001/SHA256SUMS").with_status(200).with_body(sha_content).create_async().await;

    // Return empty body — checksum will never match, exhausting all retries
    let _artist_mock = server
        .mock("GET", "/20260325-001001/artist.tar.xz")
        .with_status(200)
        .with_body(Vec::<u8>::new())
        .expect_at_least(1)
        .create_async()
        .await;

    let downloader = MbDownloader::new(dir.path().to_path_buf(), base_url);
    let result = downloader.download_latest().await;

    assert!(result.is_err());
    let err_msg = format!("{}", result.unwrap_err());
    // With streaming, empty body fails at the xz/tar decoder or at SHA256 verification.
    assert!(
        err_msg.contains("SHA256") || err_msg.contains("mismatch") || err_msg.contains("tar") || err_msg.contains("failed"),
        "Expected corrupt data or checksum error, got: {}",
        err_msg,
    );
}

#[test]
fn test_discover_finds_compressed_files() {
    let dir = TempDir::new().unwrap();

    // Create .jsonl.xz files (as if previously compressed)
    for name in &["artist.jsonl.xz", "label.jsonl.xz", "release.jsonl.xz", "release-group.jsonl.xz"] {
        let path = dir.path().join(name);
        // Write a minimal valid XZ file
        let mut encoder = xz2::write::XzEncoder::new(Vec::new(), 6);
        encoder.write_all(b"{}\n").unwrap();
        let compressed = encoder.finish().unwrap();
        std::fs::write(&path, compressed).unwrap();
    }

    let found = discover_mb_dump_files(dir.path()).unwrap();
    assert_eq!(found.len(), 4, "Should discover all 4 entity types from .xz files");
    assert!(found.contains_key(&DataType::Artists));
    assert!(found.contains_key(&DataType::Labels));
    assert!(found.contains_key(&DataType::Releases));
    assert!(found.contains_key(&DataType::ReleaseGroups));
}

#[test]
fn test_extract_entity_from_tarball_multiline_round_trip() {
    let dir = TempDir::new().unwrap();
    let tar_path = dir.path().join("release.tar.xz");
    let out_path = dir.path().join("release.jsonl.xz");

    // Build many lines to exercise the read/write loop more thoroughly
    let mut content = String::new();
    for i in 0..1000 {
        content.push_str(&format!("{{\"id\":\"{}\",\"name\":\"Release {}\",\"relations\":[]}}\n", i, i));
    }

    // Build tar archive
    let mut tar_data = Vec::new();
    {
        let mut builder = tar::Builder::new(&mut tar_data);
        let bytes = content.as_bytes();
        let mut header = tar::Header::new_gnu();
        header.set_path("release/mbdump/release").unwrap();
        header.set_size(bytes.len() as u64);
        header.set_mode(0o644);
        header.set_cksum();
        builder.append(&header, bytes).unwrap();
        builder.finish().unwrap();
    }

    let mut xz_file = std::fs::File::create(&tar_path).unwrap();
    let mut encoder = xz2::write::XzEncoder::new(Vec::new(), 1);
    encoder.write_all(&tar_data).unwrap();
    let compressed = encoder.finish().unwrap();
    xz_file.write_all(&compressed).unwrap();
    drop(xz_file);

    extract_entity_from_tarball(&tar_path, "release", &out_path).unwrap();

    // Verify round-trip decompression
    let file = std::fs::File::open(&out_path).unwrap();
    let mut decoder = xz2::read::XzDecoder::new(file);
    let mut decompressed = String::new();
    decoder.read_to_string(&mut decompressed).unwrap();
    assert_eq!(decompressed, content);

    // Output should be smaller than uncompressed content
    let compressed_size = std::fs::metadata(&out_path).unwrap().len();
    assert!(compressed_size < content.len() as u64, "Compressed output should be smaller than original");
}

#[test]
fn test_extract_entity_from_tarball_cleans_up_on_failure() {
    let dir = TempDir::new().unwrap();
    let tar_path = dir.path().join("artist.tar.xz");

    // Build a valid tar.xz
    let mut tar_data = Vec::new();
    {
        let mut builder = tar::Builder::new(&mut tar_data);
        let content = b"{\"id\":\"1\"}\n";
        let mut header = tar::Header::new_gnu();
        header.set_path("artist/mbdump/artist").unwrap();
        header.set_size(content.len() as u64);
        header.set_mode(0o644);
        header.set_cksum();
        builder.append(&header, &content[..]).unwrap();
        builder.finish().unwrap();
    }

    let mut xz_file = std::fs::File::create(&tar_path).unwrap();
    let mut encoder = xz2::write::XzEncoder::new(Vec::new(), 1);
    encoder.write_all(&tar_data).unwrap();
    std::fs::File::write_all(&mut xz_file, &encoder.finish().unwrap()).unwrap();
    drop(xz_file);

    // Create a subdirectory where the output file should go — prevents File::create from succeeding
    let out_path = dir.path().join("subdir").join("artist.jsonl.xz");
    // subdir doesn't exist, so File::create should fail
    let result = extract_entity_from_tarball(&tar_path, "artist", &out_path);
    assert!(result.is_err(), "Should fail when output directory doesn't exist");
    assert!(!out_path.exists(), "No partial file should remain on failure");
}

#[test]
fn test_is_version_complete_with_xz_files() {
    let dir = TempDir::new().unwrap();

    // Create only .xz files (no .jsonl)
    for name in &["artist", "label", "release-group", "release"] {
        let xz_path = dir.path().join(format!("{}.jsonl.xz", name));
        std::fs::write(&xz_path, b"compressed content").unwrap();
    }

    // is_version_complete should recognize .xz files
    let downloader = MbDownloader::new(dir.path().to_path_buf(), "https://example.com".to_string());
    assert!(downloader.is_version_complete(dir.path()), "Should be complete with all .xz files");
}

#[test]
fn test_is_version_complete_with_mixed_files() {
    let dir = TempDir::new().unwrap();

    // Mix of .jsonl and .jsonl.xz files
    std::fs::write(dir.path().join("artist.jsonl"), b"").unwrap();
    std::fs::write(dir.path().join("label.jsonl.xz"), b"").unwrap();
    std::fs::write(dir.path().join("release-group.jsonl"), b"").unwrap();
    std::fs::write(dir.path().join("release.jsonl.xz"), b"").unwrap();

    let downloader = MbDownloader::new(dir.path().to_path_buf(), "https://example.com".to_string());
    assert!(downloader.is_version_complete(dir.path()), "Should be complete with mixed .jsonl and .xz files");
}

#[test]
fn test_is_version_complete_missing_entity() {
    let dir = TempDir::new().unwrap();

    // Missing release-group (neither .jsonl nor .xz)
    std::fs::write(dir.path().join("artist.jsonl"), b"").unwrap();
    std::fs::write(dir.path().join("label.jsonl.xz"), b"").unwrap();
    std::fs::write(dir.path().join("release.jsonl"), b"").unwrap();

    let downloader = MbDownloader::new(dir.path().to_path_buf(), "https://example.com".to_string());
    assert!(!downloader.is_version_complete(dir.path()), "Should be incomplete with missing entity");
}
