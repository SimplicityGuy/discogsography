use super::*;
use std::collections::HashMap;
use tempfile::TempDir;
use tokio::fs;
use tokio::io::AsyncWriteExt;

#[test]
fn test_extract_month() {
    assert_eq!(extract_month_from_filename("discogs_20241201_artists.xml.gz"), "202412");
    assert_eq!(extract_month_from_filename("discogs_20240115_labels.xml.gz"), "202401");
}

#[test]
fn test_extract_month_invalid_filename() {
    // Test with invalid filename formats - should return current month (YYYYMM)
    let result = extract_month_from_filename("invalid_format.xml");
    assert_eq!(result.len(), 6); // Should be YYYYMM format

    // Test with short date part - takes what's available or returns current month
    let result = extract_month_from_filename("discogs_2024_artists.xml.gz");
    // This should return current month since 2024 is not 6 chars
    assert_eq!(result.len(), 6);
}

#[test]
fn test_extract_month_edge_cases() {
    // Test with short date part - should return current month
    let result = extract_month_from_filename("discogs_2024_test.xml.gz");
    assert_eq!(result.len(), 6);

    // Test with no underscores - should return current month
    let result = extract_month_from_filename("nounderscores.xml.gz");
    assert_eq!(result.len(), 6);
}

#[tokio::test]
async fn test_load_metadata_nonexistent() {
    let temp_dir = TempDir::new().unwrap();
    let metadata = load_metadata(temp_dir.path()).unwrap();
    assert!(metadata.is_empty());
}

#[tokio::test]
async fn test_load_metadata_valid() {
    let temp_dir = TempDir::new().unwrap();
    let metadata_path = temp_dir.path().join(".discogs_metadata.json");

    let mut test_metadata = HashMap::new();
    test_metadata.insert(
        "test.xml.gz".to_string(),
        LocalFileInfo { path: "/tmp/test.xml.gz".to_string(), checksum: "abc123".to_string(), version: "202412".to_string(), size: 1024 },
    );

    let json = serde_json::to_string_pretty(&test_metadata).unwrap();
    std::fs::write(&metadata_path, json).unwrap();

    let loaded = load_metadata(temp_dir.path()).unwrap();
    assert_eq!(loaded.len(), 1);
    assert_eq!(loaded.get("test.xml.gz").unwrap().checksum, "abc123");
}

#[tokio::test]
async fn test_load_metadata_invalid_json() {
    let temp_dir = TempDir::new().unwrap();
    let metadata_path = temp_dir.path().join(".discogs_metadata.json");

    std::fs::write(&metadata_path, "invalid json").unwrap();

    // A corrupt metadata cache is recoverable (bead discogsography-fsmp): it is
    // quarantined and loading falls back to an empty map instead of wedging startup.
    let loaded = load_metadata(temp_dir.path()).expect("corrupt metadata must not be fatal");
    assert!(loaded.is_empty());
    assert!(!metadata_path.exists());
    assert!(temp_dir.path().join(".discogs_metadata.json.corrupt").exists());
}

#[tokio::test]
async fn test_calculate_file_checksum() {
    let temp_dir = TempDir::new().unwrap();
    let test_file = temp_dir.path().join("test.txt");

    let mut file = fs::File::create(&test_file).await.unwrap();
    file.write_all(b"test content").await.unwrap();
    file.sync_all().await.unwrap();
    drop(file);

    let checksum = calculate_file_checksum(&test_file).await.unwrap();
    assert!(!checksum.is_empty());
    assert_eq!(checksum.len(), 64); // SHA256 hex string length
}

#[tokio::test]
async fn test_calculate_file_checksum_empty_file() {
    let temp_dir = TempDir::new().unwrap();
    let test_file = temp_dir.path().join("empty.txt");

    fs::File::create(&test_file).await.unwrap();

    let checksum = calculate_file_checksum(&test_file).await.unwrap();
    assert!(!checksum.is_empty());
    assert_eq!(checksum.len(), 64);
}

#[tokio::test]
async fn test_calculate_file_checksum_nonexistent() {
    let temp_dir = TempDir::new().unwrap();
    let test_file = temp_dir.path().join("nonexistent.txt");

    let result = calculate_file_checksum(&test_file).await;
    assert!(result.is_err());
}

#[tokio::test]
async fn test_downloader_new() {
    let temp_dir = TempDir::new().unwrap();

    // Create a new downloader (no AWS connection needed anymore)
    let result = Downloader::new(temp_dir.path().to_path_buf()).await;

    // We expect this to succeed since it's just initialization
    assert!(result.is_ok());

    let downloader = result.unwrap();
    assert_eq!(downloader.output_directory, temp_dir.path());
    assert!(downloader.metadata.is_empty());
}

#[tokio::test]
async fn test_downloader_save_metadata() {
    let temp_dir = TempDir::new().unwrap();
    let mut downloader = Downloader::new(temp_dir.path().to_path_buf()).await.unwrap();

    downloader.metadata.insert(
        "test.xml.gz".to_string(),
        LocalFileInfo { path: "/tmp/test.xml.gz".to_string(), checksum: "abc123".to_string(), version: "202412".to_string(), size: 1024 },
    );

    let result = downloader.save_metadata();
    assert!(result.is_ok());

    let metadata_file = temp_dir.path().join(".discogs_metadata.json");
    assert!(metadata_file.exists());

    let loaded = load_metadata(temp_dir.path()).unwrap();
    assert_eq!(loaded.len(), 1);
}

#[tokio::test]
async fn test_should_download_file_not_exists() {
    let temp_dir = TempDir::new().unwrap();
    let downloader = Downloader::new(temp_dir.path().to_path_buf()).await.unwrap();

    let file_info = S3FileInfo { name: "discogs_20241201_artists.xml.gz".to_string(), size: 1024 };

    let should_download = downloader.should_download(&file_info).await.unwrap();
    assert!(should_download);
}

#[tokio::test]
async fn test_should_download_size_changed() {
    let temp_dir = TempDir::new().unwrap();
    let mut downloader = Downloader::new(temp_dir.path().to_path_buf()).await.unwrap();

    // Create a local file
    let filename = "discogs_20241201_artists.xml.gz";
    let local_path = temp_dir.path().join(filename);
    fs::write(&local_path, b"test content").await.unwrap();

    // Add metadata with different size
    downloader.metadata.insert(
        filename.to_string(),
        LocalFileInfo { path: local_path.to_string_lossy().to_string(), checksum: "abc123".to_string(), version: "202412".to_string(), size: 1024 },
    );

    let file_info = S3FileInfo {
        name: filename.to_string(),
        size: 2048, // Different size
    };

    let should_download = downloader.should_download(&file_info).await.unwrap();
    assert!(should_download);
}

#[tokio::test]
async fn test_should_download_checksum_mismatch() {
    let temp_dir = TempDir::new().unwrap();
    let mut downloader = Downloader::new(temp_dir.path().to_path_buf()).await.unwrap();

    // Create a local file
    let filename = "discogs_20241201_artists.xml.gz";
    let local_path = temp_dir.path().join(filename);
    let content = b"test content";
    fs::write(&local_path, content).await.unwrap();

    // Add metadata with wrong checksum (intentionally not using actual checksum)
    downloader.metadata.insert(
        filename.to_string(),
        LocalFileInfo {
            path: local_path.to_string_lossy().to_string(),
            checksum: "wrong_checksum".to_string(),
            version: "202412".to_string(),
            size: content.len() as u64,
        },
    );

    let file_info = S3FileInfo { name: filename.to_string(), size: content.len() as u64 };

    let should_download = downloader.should_download(&file_info).await.unwrap();
    assert!(should_download);
}

#[tokio::test]
async fn test_should_download_up_to_date() {
    let temp_dir = TempDir::new().unwrap();
    let mut downloader = Downloader::new(temp_dir.path().to_path_buf()).await.unwrap();

    // Create a local file
    let filename = "discogs_20241201_artists.xml.gz";
    let local_path = temp_dir.path().join(filename);
    let content = b"test content";
    fs::write(&local_path, content).await.unwrap();

    let actual_checksum = calculate_file_checksum(&local_path).await.unwrap();

    // Add metadata with correct checksum and size
    downloader.metadata.insert(
        filename.to_string(),
        LocalFileInfo {
            path: local_path.to_string_lossy().to_string(),
            checksum: actual_checksum,
            version: "202412".to_string(),
            size: content.len() as u64,
        },
    );

    let file_info = S3FileInfo { name: filename.to_string(), size: content.len() as u64 };

    let should_download = downloader.should_download(&file_info).await.unwrap();
    assert!(!should_download);
}

#[test]
fn test_get_latest_monthly_files_no_complete_set() {
    let temp_dir = TempDir::new().unwrap();
    let downloader = tokio::runtime::Runtime::new().unwrap().block_on(Downloader::new(temp_dir.path().to_path_buf())).unwrap();

    // Only 3 files instead of required 4 data files + 1 checksum
    let files = vec![
        S3FileInfo { name: "data/discogs_20241201_artists.xml.gz".to_string(), size: 1024 },
        S3FileInfo { name: "data/discogs_20241201_labels.xml.gz".to_string(), size: 1024 },
        S3FileInfo { name: "data/discogs_20241201_CHECKSUM.txt".to_string(), size: 100 },
    ];

    let result = downloader.get_latest_monthly_files(&files).unwrap();
    assert!(result.is_empty());
}

#[test]
fn test_get_latest_monthly_files_complete_set() {
    let temp_dir = TempDir::new().unwrap();
    let downloader = tokio::runtime::Runtime::new().unwrap().block_on(Downloader::new(temp_dir.path().to_path_buf())).unwrap();

    // Complete set: 4 data files + 1 checksum
    let files = vec![
        S3FileInfo { name: "data/discogs_20241201_artists.xml.gz".to_string(), size: 1024 },
        S3FileInfo { name: "data/discogs_20241201_labels.xml.gz".to_string(), size: 1024 },
        S3FileInfo { name: "data/discogs_20241201_masters.xml.gz".to_string(), size: 1024 },
        S3FileInfo { name: "data/discogs_20241201_releases.xml.gz".to_string(), size: 1024 },
        S3FileInfo { name: "data/discogs_20241201_CHECKSUM.txt".to_string(), size: 100 },
    ];

    let result = downloader.get_latest_monthly_files(&files).unwrap();
    assert_eq!(result.len(), 4); // Should return 4 data files

    // Verify filenames retain the full S3 key (consumers use Path::file_name() for bare names)
    assert!(result.iter().all(|f| f.name.contains("discogs_20241201_")));
}

#[tokio::test]
async fn test_with_state_marker() {
    use crate::state_marker::StateMarker;

    let temp_dir = TempDir::new().unwrap();
    let marker = StateMarker::new("20260101".to_string());
    let marker_path = temp_dir.path().join(".extraction_status_20260101.json");

    let downloader = Downloader::new(temp_dir.path().to_path_buf()).await.unwrap().with_state_marker(marker, marker_path.clone());

    assert!(downloader.state_marker.is_some());
    assert!(downloader.marker_path.is_some());
    assert_eq!(downloader.state_marker.as_ref().unwrap().current_version, "20260101");
    assert_eq!(downloader.marker_path.as_ref().unwrap(), &marker_path);
}

#[tokio::test]
async fn test_save_state_marker_with_marker() {
    use crate::state_marker::StateMarker;

    let temp_dir = TempDir::new().unwrap();
    let marker = StateMarker::new("20260101".to_string());
    let marker_path = temp_dir.path().join(".extraction_status_20260101.json");

    let mut downloader = Downloader::new(temp_dir.path().to_path_buf()).await.unwrap().with_state_marker(marker, marker_path.clone());

    downloader.save_state_marker().await;

    // Verify the file was written
    assert!(marker_path.exists());
    let contents = fs::read_to_string(&marker_path).await.unwrap();
    let parsed: serde_json::Value = serde_json::from_str(&contents).unwrap();
    assert_eq!(parsed["current_version"], "20260101");
}

#[tokio::test]
async fn test_save_state_marker_without_marker() {
    let temp_dir = TempDir::new().unwrap();
    let mut downloader = Downloader::new(temp_dir.path().to_path_buf()).await.unwrap();

    // Should be a no-op, no error
    downloader.save_state_marker().await;

    assert!(downloader.state_marker.is_none());
    assert!(downloader.marker_path.is_none());
}

#[tokio::test]
async fn test_new_with_base_url() {
    let temp_dir = TempDir::new().unwrap();
    let custom_url = "https://custom.example.com/".to_string();
    let downloader = Downloader::new_with_base_url(temp_dir.path().to_path_buf(), custom_url).await.unwrap();

    // base_url is private, but we can verify the downloader was created successfully
    assert_eq!(downloader.output_directory, temp_dir.path());
    assert!(downloader.metadata.is_empty());
}

#[tokio::test]
async fn test_should_download_no_metadata_file_exists() {
    let temp_dir = TempDir::new().unwrap();
    let downloader = Downloader::new(temp_dir.path().to_path_buf()).await.unwrap();

    // Create a local file but do NOT add any metadata entry
    let filename = "discogs_20241201_artists.xml.gz";
    let local_path = temp_dir.path().join(filename);
    fs::write(&local_path, b"some data").await.unwrap();

    let file_info = S3FileInfo { name: filename.to_string(), size: 1024 };

    // File exists locally but no metadata entry — should return true (download to be safe)
    let should_download = downloader.should_download(&file_info).await.unwrap();
    assert!(should_download);
}

#[test]
fn test_get_latest_monthly_files_empty_input() {
    let temp_dir = TempDir::new().unwrap();
    let downloader = tokio::runtime::Runtime::new().unwrap().block_on(Downloader::new(temp_dir.path().to_path_buf())).unwrap();

    let files: Vec<S3FileInfo> = vec![];
    let result = downloader.get_latest_monthly_files(&files).unwrap();
    assert!(result.is_empty());
}

#[tokio::test]
async fn test_download_discogs_data_with_state_marker() {
    use crate::state_marker::StateMarker;

    let temp_dir = TempDir::new().unwrap();

    // Set up mockito server
    let mut server = mockito::Server::new_async().await;
    let base_url = format!("{}/", server.url());

    // Main page listing year directories
    let main_page_html = r#"<html><body>
        <a href="?prefix=data%2F2026%2F">2026/</a>
    </body></html>"#;

    let _main_mock = server.mock("GET", "/").with_status(200).with_body(main_page_html).create_async().await;

    // Year page listing files (5 files = 4 data + 1 checksum for a complete set)
    let year_page_html = r#"<html><body>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_artists.xml.gz">artists</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_labels.xml.gz">labels</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_masters.xml.gz">masters</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_releases.xml.gz">releases</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_CHECKSUM.txt">checksum</a>
    </body></html>"#
        .to_string();

    let _year_mock = server.mock("GET", "/?prefix=data%2F2026%2F").with_status(200).with_body(&year_page_html).create_async().await;

    // Mock download endpoints for each file
    let file_types = ["artists", "labels", "masters", "releases"];
    let mut _download_mocks = Vec::new();
    for file_type in &file_types {
        let download_path = format!("/?download=data%2F2026%2Fdiscogs_20260101_{}.xml.gz", file_type);
        let mock = server
            .mock("GET", download_path.as_str())
            .with_status(200)
            .with_body(format!("fake {} data", file_type))
            .create_async()
            .await;
        _download_mocks.push(mock);
    }

    // Create downloader with state marker
    let marker = StateMarker::new("20260101".to_string());
    let marker_path = temp_dir.path().join(".extraction_status_20260101.json");

    let mut downloader = Downloader::new_with_base_url(temp_dir.path().to_path_buf(), base_url)
        .await
        .unwrap()
        .with_state_marker(marker, marker_path.clone());

    let result = downloader.download_discogs_data().await.unwrap();

    // Should have downloaded 4 data files
    assert_eq!(result.len(), 4);

    // State marker should have been saved and track downloads
    assert!(marker_path.exists());
    let marker = downloader.state_marker.as_ref().unwrap();
    assert_eq!(marker.download_phase.files_downloaded, 4);
    assert!(marker.download_phase.bytes_downloaded > 0);
    assert_eq!(marker.download_phase.status, crate::state_marker::PhaseStatus::Completed);
}

/// SHA-256 of the literal bodies the mockito download mocks below serve
/// (`"fake {type} data"`), computed once and hardcoded so tests don't
/// depend on `sha2` at the call site for the published-CHECKSUM fixture.
fn fake_data_checksums_txt() -> String {
    "2d89e4146a50731264b28056ed61c904a99de6bfe1af8c82d139bd8cbee850f6  discogs_20260101_artists.xml.gz\n\
     246d842084dfd15b2da652a5a19da2287ae7cc2235f0d71aa7ab3ee64140a813  discogs_20260101_labels.xml.gz\n\
     613e7e23d0ce2d0c60dd2da6216457bbd8de38c940696c11d3fc57a352cb1851  discogs_20260101_masters.xml.gz\n\
     bd804e5e894bd322addead6469d641f07fe36650cd2ae637a5912e28f28c5ee8  discogs_20260101_releases.xml.gz\n"
        .to_string()
}

#[tokio::test]
async fn test_download_discogs_data_verifies_against_published_checksum() {
    // discogsography-cu2.106 regression: a genuine download whose bytes match the
    // Discogs-published CHECKSUM must succeed as before.
    let temp_dir = TempDir::new().unwrap();
    let mut server = mockito::Server::new_async().await;
    let base_url = format!("{}/", server.url());

    let main_page_html = r#"<html><body>
        <a href="?prefix=data%2F2026%2F">2026/</a>
    </body></html>"#;
    let _main_mock = server.mock("GET", "/").with_status(200).with_body(main_page_html).create_async().await;

    let year_page_html = r#"<html><body>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_artists.xml.gz">artists</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_labels.xml.gz">labels</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_masters.xml.gz">masters</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_releases.xml.gz">releases</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_CHECKSUM.txt">checksum</a>
    </body></html>"#;
    let _year_mock = server.mock("GET", "/?prefix=data%2F2026%2F").with_status(200).with_body(year_page_html).create_async().await;

    let _checksum_mock = server
        .mock("GET", "/?download=data%2F2026%2Fdiscogs_20260101_CHECKSUM.txt")
        .with_status(200)
        .with_body(fake_data_checksums_txt())
        .create_async()
        .await;

    let file_types = ["artists", "labels", "masters", "releases"];
    let mut _download_mocks = Vec::new();
    for file_type in &file_types {
        let download_path = format!("/?download=data%2F2026%2Fdiscogs_20260101_{}.xml.gz", file_type);
        let mock = server
            .mock("GET", download_path.as_str())
            .with_status(200)
            .with_body(format!("fake {} data", file_type))
            .create_async()
            .await;
        _download_mocks.push(mock);
    }

    let mut downloader = Downloader::new_with_base_url(temp_dir.path().to_path_buf(), base_url).await.unwrap();

    let result = downloader.download_discogs_data().await.unwrap();

    assert_eq!(result.len(), 4);
    for file_type in &file_types {
        let filename = format!("discogs_20260101_{}.xml.gz", file_type);
        assert!(downloader.metadata.contains_key(&filename), "expected metadata for {}", filename);
    }
}

#[tokio::test]
async fn test_download_discogs_data_checksum_mismatch_deletes_corrupt_file() {
    // discogsography-cu2.106 regression: a 200-response whose body isn't the real dump
    // (a bad-but-complete download) must NOT be permanently trusted. On a
    // published-CHECKSUM mismatch, the corrupt local file and its metadata entry must be
    // removed and the run must fail loudly instead of silently succeeding.
    let temp_dir = TempDir::new().unwrap();
    let mut server = mockito::Server::new_async().await;
    let base_url = format!("{}/", server.url());

    let main_page_html = r#"<html><body>
        <a href="?prefix=data%2F2026%2F">2026/</a>
    </body></html>"#;
    let _main_mock = server.mock("GET", "/").with_status(200).with_body(main_page_html).create_async().await;

    let year_page_html = r#"<html><body>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_artists.xml.gz">artists</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_labels.xml.gz">labels</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_masters.xml.gz">masters</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_releases.xml.gz">releases</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_CHECKSUM.txt">checksum</a>
    </body></html>"#;
    let _year_mock = server.mock("GET", "/?prefix=data%2F2026%2F").with_status(200).with_body(year_page_html).create_async().await;

    // Published CHECKSUM disagrees with what the mocked artists download actually
    // serves below (an interstitial error page, standing in for a bad 200 body).
    let bogus_checksum = format!("{}  discogs_20260101_artists.xml.gz\n", "0".repeat(64));
    let _checksum_mock = server
        .mock("GET", "/?download=data%2F2026%2Fdiscogs_20260101_CHECKSUM.txt")
        .with_status(200)
        .with_body(bogus_checksum)
        .create_async()
        .await;

    let _artists_mock = server
        .mock("GET", "/?download=data%2F2026%2Fdiscogs_20260101_artists.xml.gz")
        .with_status(200)
        .with_body("<html>upstream interstitial error page</html>")
        .create_async()
        .await;

    let mut downloader = Downloader::new_with_base_url(temp_dir.path().to_path_buf(), base_url).await.unwrap();

    let result = downloader.download_discogs_data().await;

    assert!(result.is_err(), "a published-CHECKSUM mismatch must fail the run, not silently succeed");

    let corrupt_path = temp_dir.path().join("discogs_20260101_artists.xml.gz");
    assert!(!corrupt_path.exists(), "the corrupt file must be deleted on checksum mismatch");
    assert!(!downloader.metadata.contains_key("discogs_20260101_artists.xml.gz"), "the corrupt metadata entry must be removed");
}

#[tokio::test]
async fn test_download_discogs_data_redownloads_when_locally_trusted_checksum_disagrees_with_published() {
    // discogsography-cu2.106 regression: a file that was previously downloaded and
    // self-checksummed (should_download() would normally skip it as "up to date") must
    // be forced to re-download when the published CHECKSUM disagrees — closing the
    // "permanently trusted" hole for files that were already corrupted before this fix
    // shipped.
    use sha2::{Digest, Sha256};

    let temp_dir = TempDir::new().unwrap();
    let mut server = mockito::Server::new_async().await;
    let base_url = format!("{}/", server.url());

    let main_page_html = r#"<html><body>
        <a href="?prefix=data%2F2026%2F">2026/</a>
    </body></html>"#;
    let _main_mock = server.mock("GET", "/").with_status(200).with_body(main_page_html).create_async().await;

    let year_page_html = r#"<html><body>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_artists.xml.gz">artists</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_labels.xml.gz">labels</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_masters.xml.gz">masters</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_releases.xml.gz">releases</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_CHECKSUM.txt">checksum</a>
    </body></html>"#;
    let _year_mock = server.mock("GET", "/?prefix=data%2F2026%2F").with_status(200).with_body(year_page_html).create_async().await;

    let _checksum_mock = server
        .mock("GET", "/?download=data%2F2026%2Fdiscogs_20260101_CHECKSUM.txt")
        .with_status(200)
        .with_body(fake_data_checksums_txt())
        .create_async()
        .await;

    // Pre-create all 4 local files with a self-consistent (but WRONG, i.e. not matching
    // the published CHECKSUM) checksum in metadata — as if a bad download was trusted
    // under the pre-fix behavior.
    let file_types = ["artists", "labels", "masters", "releases"];
    let mut downloader = Downloader::new_with_base_url(temp_dir.path().to_path_buf(), base_url).await.unwrap();
    for file_type in &file_types {
        let filename = format!("discogs_20260101_{}.xml.gz", file_type);
        let content = format!("previously trusted bad {} data", file_type);
        let local_path = temp_dir.path().join(&filename);
        fs::write(&local_path, content.as_bytes()).await.unwrap();

        let mut hasher = Sha256::new();
        hasher.update(content.as_bytes());
        let checksum = hex::encode(hasher.finalize());

        downloader.metadata.insert(
            filename,
            LocalFileInfo { path: local_path.to_string_lossy().to_string(), checksum, version: "202601".to_string(), size: content.len() as u64 },
        );
    }

    // Re-download mocks serving content that DOES match the published CHECKSUM.
    let mut _download_mocks = Vec::new();
    for file_type in &file_types {
        let download_path = format!("/?download=data%2F2026%2Fdiscogs_20260101_{}.xml.gz", file_type);
        let mock = server
            .mock("GET", download_path.as_str())
            .with_status(200)
            .with_body(format!("fake {} data", file_type))
            .create_async()
            .await;
        _download_mocks.push(mock);
    }

    let result = downloader.download_discogs_data().await.unwrap();

    assert_eq!(result.len(), 4);
    for file_type in &file_types {
        let filename = format!("discogs_20260101_{}.xml.gz", file_type);
        let content = std::fs::read_to_string(temp_dir.path().join(&filename)).unwrap();
        assert_eq!(content, format!("fake {} data", file_type), "{} must have been re-downloaded with fresh, verified content", filename);
    }
}

#[tokio::test]
async fn test_download_discogs_data_skips_already_downloaded() {
    use sha2::{Digest, Sha256};

    let temp_dir = TempDir::new().unwrap();

    // Set up mockito server
    let mut server = mockito::Server::new_async().await;
    let base_url = format!("{}/", server.url());

    // Main page listing year directories
    let main_page_html = r#"<html><body>
        <a href="?prefix=data%2F2026%2F">2026/</a>
    </body></html>"#;

    let _main_mock = server.mock("GET", "/").with_status(200).with_body(main_page_html).create_async().await;

    // Year page with complete 5-file set
    let year_page_html = r#"<html><body>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_artists.xml.gz">artists</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_labels.xml.gz">labels</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_masters.xml.gz">masters</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_releases.xml.gz">releases</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_CHECKSUM.txt">checksum</a>
    </body></html>"#;

    let _year_mock = server.mock("GET", "/?prefix=data%2F2026%2F").with_status(200).with_body(year_page_html).create_async().await;

    // Pre-create all 4 data files locally with known content and matching checksums
    let file_types = ["artists", "labels", "masters", "releases"];
    let mut downloader = Downloader::new_with_base_url(temp_dir.path().to_path_buf(), base_url).await.unwrap();

    for file_type in &file_types {
        let filename = format!("discogs_20260101_{}.xml.gz", file_type);
        let content = format!("existing {} data", file_type);
        let local_path = temp_dir.path().join(&filename);
        fs::write(&local_path, content.as_bytes()).await.unwrap();

        // Compute actual SHA256 checksum
        let mut hasher = Sha256::new();
        hasher.update(content.as_bytes());
        let checksum = hex::encode(hasher.finalize());

        // Pre-populate metadata with correct checksum
        downloader.metadata.insert(
            filename,
            LocalFileInfo { path: local_path.to_string_lossy().to_string(), checksum, version: "202601".to_string(), size: content.len() as u64 },
        );
    }

    // No download mocks are set up — if it tries to download, mockito will return
    // an unexpected request error. The test succeeds only if downloads are skipped.

    let result = downloader.download_discogs_data().await.unwrap();

    // All 4 files should be returned (skipped but still tracked)
    assert_eq!(result.len(), 4);
    for file_type in &file_types {
        let filename = format!("discogs_20260101_{}.xml.gz", file_type);
        assert!(result.contains(&filename), "Expected {} in result", filename);
    }
}

#[tokio::test]
async fn test_list_s3_files_uses_cache() {
    let temp_dir = TempDir::new().unwrap();

    let mut server = mockito::Server::new_async().await;
    let base_url = format!("{}/", server.url());

    let main_page_html = r#"<html><body>
        <a href="?prefix=data%2F2026%2F">2026/</a>
    </body></html>"#;

    // Expect the main page to be called exactly once
    let _main_mock = server.mock("GET", "/").with_status(200).with_body(main_page_html).expect(1).create_async().await;

    let year_page_html = r#"<html><body>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_artists.xml.gz">artists</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_labels.xml.gz">labels</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_masters.xml.gz">masters</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_releases.xml.gz">releases</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_CHECKSUM.txt">checksum</a>
    </body></html>"#;

    let _year_mock = server.mock("GET", "/?prefix=data%2F2026%2F").with_status(200).with_body(year_page_html).expect(1).create_async().await;

    let mut downloader = Downloader::new_with_base_url(temp_dir.path().to_path_buf(), base_url).await.unwrap();

    // First call — fetches from server
    let first_result = downloader.list_s3_files().await.unwrap();
    assert_eq!(first_result.len(), 5); // 4 data + 1 checksum

    // Second call — should use cache, no additional HTTP requests
    let second_result = downloader.list_s3_files().await.unwrap();
    assert_eq!(second_result.len(), 5);
    assert_eq!(first_result.len(), second_result.len());

    // mockito expect(1) will panic on drop if mocks were hit more than once
}

#[tokio::test]
async fn test_download_discogs_data_with_state_marker_skips() {
    use crate::state_marker::StateMarker;
    use sha2::{Digest, Sha256};

    let temp_dir = TempDir::new().unwrap();

    let mut server = mockito::Server::new_async().await;
    let base_url = format!("{}/", server.url());

    let main_page_html = r#"<html><body>
        <a href="?prefix=data%2F2026%2F">2026/</a>
    </body></html>"#;

    let _main_mock = server.mock("GET", "/").with_status(200).with_body(main_page_html).create_async().await;

    let year_page_html = r#"<html><body>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_artists.xml.gz">artists</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_labels.xml.gz">labels</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_masters.xml.gz">masters</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_releases.xml.gz">releases</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_CHECKSUM.txt">checksum</a>
    </body></html>"#;

    let _year_mock = server.mock("GET", "/?prefix=data%2F2026%2F").with_status(200).with_body(year_page_html).create_async().await;

    // Pre-create all 4 data files with matching checksums
    let file_types = ["artists", "labels", "masters", "releases"];
    let mut downloader = Downloader::new_with_base_url(temp_dir.path().to_path_buf(), base_url).await.unwrap();

    let mut expected_sizes: HashMap<String, u64> = HashMap::new();

    for file_type in &file_types {
        let filename = format!("discogs_20260101_{}.xml.gz", file_type);
        let content = format!("state marker {} data", file_type);
        let local_path = temp_dir.path().join(&filename);
        fs::write(&local_path, content.as_bytes()).await.unwrap();

        let mut hasher = Sha256::new();
        hasher.update(content.as_bytes());
        let checksum = hex::encode(hasher.finalize());

        expected_sizes.insert(filename.clone(), content.len() as u64);

        downloader.metadata.insert(
            filename,
            LocalFileInfo { path: local_path.to_string_lossy().to_string(), checksum, version: "202601".to_string(), size: content.len() as u64 },
        );
    }

    // Attach a state marker
    let marker = StateMarker::new("20260101".to_string());
    let marker_path = temp_dir.path().join(".extraction_status_20260101.json");
    downloader.state_marker = Some(marker);
    downloader.marker_path = Some(marker_path.clone());

    let result = downloader.download_discogs_data().await.unwrap();
    assert_eq!(result.len(), 4);

    // State marker should track all files as downloaded with correct byte sizes
    let marker = downloader.state_marker.as_ref().unwrap();
    assert_eq!(marker.download_phase.files_downloaded, 4);
    assert_eq!(marker.download_phase.status, crate::state_marker::PhaseStatus::Completed);
    assert!(marker.download_phase.bytes_downloaded > 0);

    // Verify each file is tracked in the state marker with correct size
    for file_type in &file_types {
        let filename = format!("discogs_20260101_{}.xml.gz", file_type);
        let file_status = marker.download_phase.downloads_by_file.get(&filename);
        assert!(file_status.is_some(), "File {} should be tracked in state marker", filename);
        let status = file_status.unwrap();
        assert_eq!(status.status, crate::state_marker::PhaseStatus::Completed);
        assert_eq!(status.bytes_downloaded, *expected_sizes.get(&filename).unwrap());
    }

    // Verify marker was persisted to disk
    assert!(marker_path.exists());
}

// ──── DataSource trait impl tests ────

#[tokio::test]
async fn test_datasource_set_and_take_state_marker() {
    use crate::state_marker::StateMarker;

    let temp_dir = TempDir::new().unwrap();
    let mut downloader: Box<dyn DataSource> =
        Box::new(Downloader::new_with_base_url(temp_dir.path().to_path_buf(), "http://unused".to_string()).await.unwrap());

    // Initially no state marker
    assert!(downloader.take_state_marker().is_none());

    // Set a state marker via the trait
    let marker = StateMarker::new("20260101".to_string());
    let marker_path = temp_dir.path().join("marker.json");
    downloader.set_state_marker(marker, marker_path);

    // Take it back
    let taken = downloader.take_state_marker();
    assert!(taken.is_some());
    assert_eq!(taken.unwrap().current_version, "20260101");

    // Should be None after take
    assert!(downloader.take_state_marker().is_none());
}

#[tokio::test]
async fn test_datasource_list_s3_files_via_trait() {
    let temp_dir = TempDir::new().unwrap();
    let mut server = mockito::Server::new_async().await;
    let base_url = format!("{}/", server.url());

    let main_page_html = r#"<html><body>
        <a href="?prefix=data%2F2026%2F">2026/</a>
    </body></html>"#;
    let _main_mock = server.mock("GET", "/").with_status(200).with_body(main_page_html).create_async().await;

    let year_page_html = r#"<html><body>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_artists.xml.gz">artists</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_labels.xml.gz">labels</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_masters.xml.gz">masters</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_releases.xml.gz">releases</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_CHECKSUM.txt">checksum</a>
    </body></html>"#;
    let _year_mock = server.mock("GET", "/?prefix=data%2F2026%2F").with_status(200).with_body(year_page_html).create_async().await;

    let mut downloader: Box<dyn DataSource> = Box::new(Downloader::new_with_base_url(temp_dir.path().to_path_buf(), base_url).await.unwrap());

    // Call through the DataSource trait
    let files = downloader.list_s3_files().await.unwrap();
    assert_eq!(files.len(), 5);
}

#[tokio::test]
async fn test_datasource_get_latest_monthly_files_via_trait() {
    let temp_dir = TempDir::new().unwrap();
    let downloader: Box<dyn DataSource> =
        Box::new(Downloader::new_with_base_url(temp_dir.path().to_path_buf(), "http://unused".to_string()).await.unwrap());

    let files = vec![
        S3FileInfo { name: "data/discogs_20260101_artists.xml.gz".to_string(), size: 1000 },
        S3FileInfo { name: "data/discogs_20260101_labels.xml.gz".to_string(), size: 1000 },
        S3FileInfo { name: "data/discogs_20260101_masters.xml.gz".to_string(), size: 1000 },
        S3FileInfo { name: "data/discogs_20260101_releases.xml.gz".to_string(), size: 1000 },
        S3FileInfo { name: "data/discogs_20260101_CHECKSUM.txt".to_string(), size: 100 },
    ];

    let result = downloader.get_latest_monthly_files(&files).unwrap();
    assert_eq!(result.len(), 4);
    assert!(result.iter().all(|f| !f.name.contains("CHECKSUM")));
}

#[test]
fn test_get_latest_monthly_files_multiple_versions() {
    let temp_dir = TempDir::new().unwrap();
    let downloader = tokio::runtime::Runtime::new().unwrap().block_on(Downloader::new(temp_dir.path().to_path_buf())).unwrap();

    // Multiple versions - should pick the latest (20241215)
    let files = vec![
        // Older version (20241201)
        S3FileInfo { name: "data/discogs_20241201_artists.xml.gz".to_string(), size: 1024 },
        S3FileInfo { name: "data/discogs_20241201_labels.xml.gz".to_string(), size: 1024 },
        S3FileInfo { name: "data/discogs_20241201_masters.xml.gz".to_string(), size: 1024 },
        S3FileInfo { name: "data/discogs_20241201_releases.xml.gz".to_string(), size: 1024 },
        S3FileInfo { name: "data/discogs_20241201_CHECKSUM.txt".to_string(), size: 100 },
        // Newer version (20241215)
        S3FileInfo { name: "data/discogs_20241215_artists.xml.gz".to_string(), size: 2048 },
        S3FileInfo { name: "data/discogs_20241215_labels.xml.gz".to_string(), size: 2048 },
        S3FileInfo { name: "data/discogs_20241215_masters.xml.gz".to_string(), size: 2048 },
        S3FileInfo { name: "data/discogs_20241215_releases.xml.gz".to_string(), size: 2048 },
        S3FileInfo { name: "data/discogs_20241215_CHECKSUM.txt".to_string(), size: 100 },
    ];

    let result = downloader.get_latest_monthly_files(&files).unwrap();
    assert_eq!(result.len(), 4);

    // Verify all files are from the latest version
    assert!(result.iter().all(|f| f.name.contains("20241215")));
}

#[tokio::test]
async fn test_save_state_marker_failure_warns() {
    // Exercises the warn! path in save_state_marker (line 57)
    // by pointing the marker path to a non-existent parent directory.
    use crate::state_marker::StateMarker;

    let temp_dir = TempDir::new().unwrap();
    let marker = StateMarker::new("20260101".to_string());
    // Path with non-existent parent directory so save() fails
    let bad_path = PathBuf::from("/nonexistent/dir/marker.json");

    let mut downloader = Downloader::new(temp_dir.path().to_path_buf()).await.unwrap().with_state_marker(marker, bad_path.clone());

    // Should not panic — just warns internally
    downloader.save_state_marker().await;

    // Marker file should NOT exist (save failed)
    assert!(!bad_path.exists());
}

#[tokio::test]
async fn test_datasource_download_discogs_data_via_trait() {
    use crate::state_marker::StateMarker;

    let temp_dir = TempDir::new().unwrap();
    let mut server = mockito::Server::new_async().await;
    let base_url = format!("{}/", server.url());

    // Main page listing year directories
    let main_page_html = r#"<html><body>
        <a href="?prefix=data%2F2026%2F">2026/</a>
    </body></html>"#;
    let _main_mock = server.mock("GET", "/").with_status(200).with_body(main_page_html).create_async().await;

    let year_page_html = r#"<html><body>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_artists.xml.gz">artists</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_labels.xml.gz">labels</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_masters.xml.gz">masters</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_releases.xml.gz">releases</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_CHECKSUM.txt">checksum</a>
    </body></html>"#;
    let _year_mock = server.mock("GET", "/?prefix=data%2F2026%2F").with_status(200).with_body(year_page_html).create_async().await;

    // Mock download endpoints
    let file_types = ["artists", "labels", "masters", "releases"];
    let mut _download_mocks = Vec::new();
    for file_type in &file_types {
        let download_path = format!("/?download=data%2F2026%2Fdiscogs_20260101_{}.xml.gz", file_type);
        let mock = server
            .mock("GET", download_path.as_str())
            .with_status(200)
            .with_body(format!("fake {} data", file_type))
            .create_async()
            .await;
        _download_mocks.push(mock);
    }

    let marker = StateMarker::new("20260101".to_string());
    let marker_path = temp_dir.path().join(".extraction_status_20260101.json");

    let mut downloader: Box<dyn DataSource> = Box::new(Downloader::new_with_base_url(temp_dir.path().to_path_buf(), base_url).await.unwrap());
    downloader.set_state_marker(marker, marker_path);

    // Call download_discogs_data through the DataSource trait
    let result = downloader.download_discogs_data().await.unwrap();
    assert_eq!(result.len(), 4);
}

// ── HTTP-error branches added by polite-client wiring ─────────────────

#[tokio::test]
async fn test_scrape_main_page_non_success_returns_error() {
    // Discogs returning 500 on the main listing should propagate as an error,
    // not silently succeed with an empty file list — otherwise the periodic
    // check would no-op forever after a server hiccup.
    let temp_dir = TempDir::new().unwrap();
    let mut server = mockito::Server::new_async().await;
    let base_url = format!("{}/", server.url());

    let _m = server.mock("GET", "/").with_status(500).with_body("upstream broke").create_async().await;

    let mut downloader = Downloader::new_with_base_url(temp_dir.path().to_path_buf(), base_url.clone()).await.unwrap();
    let result = downloader.download_discogs_data().await;

    let err = result.expect_err("expected error from 500 response");
    let msg = format!("{:#}", err);
    assert!(msg.contains("HTTP 500") || msg.contains("Discogs website returned"), "unexpected error: {}", msg);
}

#[tokio::test]
async fn test_year_directory_non_success_skipped_other_years_succeed() {
    // The year-fetch loop walks the two most recent years. If one of them
    // returns a 500 we should warn-and-continue rather than fail the whole
    // listing — the other year still gives us a usable file list.
    let temp_dir = TempDir::new().unwrap();
    let mut server = mockito::Server::new_async().await;
    let base_url = format!("{}/", server.url());

    // Main page advertises two years. The newer year errors; the older one works.
    let main_page_html = r#"<html><body>
        <a href="?prefix=data%2F2026%2F">2026/</a>
        <a href="?prefix=data%2F2025%2F">2025/</a>
    </body></html>"#;
    let _main = server.mock("GET", "/").with_status(200).with_body(main_page_html).create_async().await;

    let _bad_year = server.mock("GET", "/?prefix=data%2F2026%2F").with_status(500).with_body("oops").create_async().await;

    let good_year_html = r#"<html><body>
        <a href="?download=data%2F2025%2Fdiscogs_20251201_artists.xml.gz">a</a>
        <a href="?download=data%2F2025%2Fdiscogs_20251201_labels.xml.gz">l</a>
        <a href="?download=data%2F2025%2Fdiscogs_20251201_masters.xml.gz">m</a>
        <a href="?download=data%2F2025%2Fdiscogs_20251201_releases.xml.gz">r</a>
    </body></html>"#;
    let _good_year = server.mock("GET", "/?prefix=data%2F2025%2F").with_status(200).with_body(good_year_html).create_async().await;

    let mut downloader = Downloader::new_with_base_url(temp_dir.path().to_path_buf(), base_url).await.unwrap();
    let files = downloader.list_s3_files().await.expect("should still succeed despite one bad year");

    // We should only see files from the working year — and we should see them all.
    assert!(!files.is_empty(), "expected files from the working year");
    assert!(files.iter().all(|f| f.name.contains("2025")), "should not have any 2026 files; got {:?}", files);
}

#[tokio::test]
async fn test_download_metadata_persisted_incrementally_on_mid_batch_failure() {
    // Regression for discogsography-cu2.65: metadata was persisted only after
    // ALL files succeeded, so a failure on a later file discarded the checksums
    // of the files that already completed — forcing full multi-GB re-downloads
    // on restart. Each successful download must now persist metadata immediately.
    let temp_dir = TempDir::new().unwrap();

    let mut server = mockito::Server::new_async().await;
    let base_url = format!("{}/", server.url());

    let main_page_html = r#"<html><body>
        <a href="?prefix=data%2F2026%2F">2026/</a>
    </body></html>"#;
    let _main_mock = server.mock("GET", "/").with_status(200).with_body(main_page_html).create_async().await;

    let year_page_html = r#"<html><body>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_artists.xml.gz">artists</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_labels.xml.gz">labels</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_masters.xml.gz">masters</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_releases.xml.gz">releases</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_CHECKSUM.txt">checksum</a>
    </body></html>"#;
    let _year_mock = server.mock("GET", "/?prefix=data%2F2026%2F").with_status(200).with_body(year_page_html).create_async().await;

    // The three earlier files download successfully...
    let mut _ok_mocks = Vec::new();
    for file_type in ["artists", "labels", "masters"] {
        let download_path = format!("/?download=data%2F2026%2Fdiscogs_20260101_{}.xml.gz", file_type);
        let mock = server
            .mock("GET", download_path.as_str())
            .with_status(200)
            .with_body(format!("fake {} data", file_type))
            .create_async()
            .await;
        _ok_mocks.push(mock);
    }
    // ...but the last file (releases) fails on every attempt, aborting the batch.
    let _fail_mock = server
        .mock("GET", "/?download=data%2F2026%2Fdiscogs_20260101_releases.xml.gz")
        .with_status(500)
        .with_body("boom")
        .create_async()
        .await;

    let mut downloader = Downloader::new_with_base_url(temp_dir.path().to_path_buf(), base_url).await.unwrap();
    let result = downloader.download_discogs_data().await;

    // The batch fails on the releases download.
    assert!(result.is_err(), "expected the batch to fail on the releases download");

    // A fresh Downloader loads the durable metadata written during the failed run.
    // Before the fix this file was written only after full success, so it would be
    // empty and every completed file would be re-downloaded.
    let reloaded = Downloader::new_with_base_url(temp_dir.path().to_path_buf(), "http://unused".to_string()).await.unwrap();
    assert!(!reloaded.metadata.is_empty(), "completed files' checksums must be persisted after a mid-batch failure");
    assert!(
        reloaded.metadata.contains_key("discogs_20260101_artists.xml.gz"),
        "the first completed file's checksum must survive; got {:?}",
        reloaded.metadata.keys().collect::<Vec<_>>()
    );
    // The failed file left no persisted metadata entry.
    assert!(!reloaded.metadata.contains_key("discogs_20260101_releases.xml.gz"), "the failed file must not be recorded as complete");

    // The persisted checksum means the completed file is not re-downloaded next run.
    let completed = S3FileInfo { name: "discogs_20260101_artists.xml.gz".to_string(), size: "fake artists data".len() as u64 };
    assert!(!reloaded.should_download(&completed).await.unwrap(), "a completed, persisted file must not be re-downloaded");
}

/// Collects formatted log output so a test can assert that a failure was actually reported.
#[derive(Clone, Default)]
struct LogCapture(std::sync::Arc<std::sync::Mutex<Vec<u8>>>);

impl LogCapture {
    fn contents(&self) -> String {
        String::from_utf8_lossy(&self.0.lock().unwrap()).to_string()
    }
}

impl std::io::Write for LogCapture {
    fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
        self.0.lock().unwrap().extend_from_slice(buf);
        Ok(buf.len())
    }

    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

impl<'a> tracing_subscriber::fmt::MakeWriter<'a> for LogCapture {
    type Writer = LogCapture;

    fn make_writer(&'a self) -> Self::Writer {
        self.clone()
    }
}

#[tokio::test]
async fn test_year_body_read_failure_is_logged() {
    // discogsography-xgyb regression: the year-page body read was the one traceless failure
    // arm in scrape_file_list_from_discogs — `if let Ok(year_html)` with no else. A body that
    // fails post-headers (proxy reset / truncation) dropped the whole year's listing, so the
    // newest dump became invisible while the run still reported success with nothing logged.
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use tokio::net::TcpListener;

    let capture = LogCapture::default();
    let subscriber = tracing_subscriber::fmt().with_max_level(tracing::Level::WARN).with_writer(capture.clone()).finish();
    let _log_guard = tracing::subscriber::set_default(subscriber);

    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();

    let _server = tokio::spawn(async move {
        loop {
            let Ok((mut sock, _)) = listener.accept().await else {
                return;
            };
            tokio::spawn(async move {
                loop {
                    let mut buf = vec![0u8; 4096];
                    let n = match sock.read(&mut buf).await {
                        Ok(0) | Err(_) => return,
                        Ok(n) => n,
                    };
                    let request = String::from_utf8_lossy(&buf[..n]).to_string();

                    if request.contains("prefix=data%2F2026%2F") {
                        // Headers promise a full body; send a fragment and close the socket —
                        // reqwest surfaces this as an Err from .text(), not from .get().
                        let _ = sock.write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 4096\r\n\r\n<html><body>").await;
                        let _ = sock.flush().await;
                        return;
                    }

                    let body = if request.contains("prefix=data%2F2025%2F") {
                        r#"<html><body>
                        <a href="?download=data%2F2025%2Fdiscogs_20251201_artists.xml.gz">a</a>
                        <a href="?download=data%2F2025%2Fdiscogs_20251201_labels.xml.gz">l</a>
                        <a href="?download=data%2F2025%2Fdiscogs_20251201_masters.xml.gz">m</a>
                        <a href="?download=data%2F2025%2Fdiscogs_20251201_releases.xml.gz">r</a>
                        </body></html>"#
                    } else {
                        r#"<html><body>
                        <a href="?prefix=data%2F2026%2F">2026/</a>
                        <a href="?prefix=data%2F2025%2F">2025/</a>
                        </body></html>"#
                    };
                    let response = format!("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: {}\r\n\r\n{}", body.len(), body);
                    if sock.write_all(response.as_bytes()).await.is_err() {
                        return;
                    }
                    let _ = sock.flush().await;
                }
            });
        }
    });

    let temp_dir = TempDir::new().unwrap();
    let base_url = format!("http://{}/", addr);
    let mut downloader = Downloader::new_with_base_url(temp_dir.path().to_path_buf(), base_url).await.unwrap();

    let files = downloader.list_s3_files().await.expect("a lost year must not fail the whole listing");
    assert!(files.iter().all(|f| f.name.contains("2025")), "only the readable year can contribute files; got {:?}", files);

    let logs = capture.contents();
    assert!(logs.contains("Failed to read year 2026 directory body"), "the lost year must be logged, not silently dropped; logs were:\n{logs}");
}

#[tokio::test]
async fn test_forced_redownload_requeues_processed_file() {
    // discogsography-qhel regression: cu2.106 revokes trust in bad bytes on the download
    // side, but the processing status computed from those bytes used to survive — so
    // pending_files() skipped the corrected file, the run finalized Completed, and the
    // corrected data was never parsed or published for the whole monthly version.
    use sha2::{Digest, Sha256};

    let temp_dir = TempDir::new().unwrap();
    let mut server = mockito::Server::new_async().await;
    let base_url = format!("{}/", server.url());

    let main_page_html = r#"<html><body>
        <a href="?prefix=data%2F2026%2F">2026/</a>
    </body></html>"#;
    let _main_mock = server.mock("GET", "/").with_status(200).with_body(main_page_html).create_async().await;

    let year_page_html = r#"<html><body>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_artists.xml.gz">artists</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_labels.xml.gz">labels</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_masters.xml.gz">masters</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_releases.xml.gz">releases</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_CHECKSUM.txt">checksum</a>
    </body></html>"#;
    let _year_mock = server.mock("GET", "/?prefix=data%2F2026%2F").with_status(200).with_body(year_page_html).create_async().await;

    let _checksum_mock = server
        .mock("GET", "/?download=data%2F2026%2Fdiscogs_20260101_CHECKSUM.txt")
        .with_status(200)
        .with_body(fake_data_checksums_txt())
        .create_async()
        .await;

    let file_types = ["artists", "labels", "masters", "releases"];
    let mut downloader = Downloader::new_with_base_url(temp_dir.path().to_path_buf(), base_url).await.unwrap();

    // Session 1's world: locally trusted bytes that do NOT match the published CHECKSUM.
    let mut trusted_checksums = std::collections::HashMap::new();
    for file_type in &file_types {
        let filename = format!("discogs_20260101_{}.xml.gz", file_type);
        let content = format!("previously trusted bad {} data", file_type);
        let local_path = temp_dir.path().join(&filename);
        fs::write(&local_path, content.as_bytes()).await.unwrap();

        let mut hasher = Sha256::new();
        hasher.update(content.as_bytes());
        let checksum = hex::encode(hasher.finalize());
        trusted_checksums.insert(filename.clone(), checksum.clone());

        downloader.metadata.insert(
            filename,
            LocalFileInfo { path: local_path.to_string_lossy().to_string(), checksum, version: "202601".to_string(), size: content.len() as u64 },
        );
    }

    // Session 1's marker: artists was parsed from the bad bytes and marked Completed.
    let artists = "discogs_20260101_artists.xml.gz".to_string();
    let mut marker = StateMarker::new("20260101".to_string());
    marker.start_download(4);
    marker.start_file_download(&artists);
    marker.file_downloaded(&artists, 42);
    marker.file_bytes_verified(&artists, &trusted_checksums[&artists]);
    marker.complete_download();
    marker.start_processing(4);
    marker.start_file_processing(&artists);
    marker.complete_file_processing(&artists, 500);

    let all_files: Vec<String> = file_types.iter().map(|t| format!("discogs_20260101_{}.xml.gz", t)).collect();
    assert!(!marker.pending_files(&all_files).contains(&artists), "precondition: artists starts out completed");

    downloader.set_state_marker(marker, temp_dir.path().join("marker.json"));

    let mut _download_mocks = Vec::new();
    for file_type in &file_types {
        let download_path = format!("/?download=data%2F2026%2Fdiscogs_20260101_{}.xml.gz", file_type);
        let mock = server
            .mock("GET", download_path.as_str())
            .with_status(200)
            .with_body(format!("fake {} data", file_type))
            .create_async()
            .await;
        _download_mocks.push(mock);
    }

    downloader.download_discogs_data().await.unwrap();

    let marker = downloader.take_state_marker().expect("marker returns from the downloader");
    assert!(
        marker.pending_files(&all_files).contains(&artists),
        "a file re-downloaded with different bytes must be re-queued, not skipped as already processed"
    );
    assert_eq!(marker.processing_phase.files_processed, 0, "the stale completion must not still be counted");
}

#[tokio::test]
async fn test_unchanged_redownload_keeps_file_processed() {
    // The counterpart: an operator deleting a processed .xml.gz to reclaim disk gets the
    // same bytes back, which must not force a needless multi-GB reparse.
    use sha2::{Digest, Sha256};

    let temp_dir = TempDir::new().unwrap();
    let mut server = mockito::Server::new_async().await;
    let base_url = format!("{}/", server.url());

    let main_page_html = r#"<html><body>
        <a href="?prefix=data%2F2026%2F">2026/</a>
    </body></html>"#;
    let _main_mock = server.mock("GET", "/").with_status(200).with_body(main_page_html).create_async().await;

    let year_page_html = r#"<html><body>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_artists.xml.gz">artists</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_labels.xml.gz">labels</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_masters.xml.gz">masters</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_releases.xml.gz">releases</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_CHECKSUM.txt">checksum</a>
    </body></html>"#;
    let _year_mock = server.mock("GET", "/?prefix=data%2F2026%2F").with_status(200).with_body(year_page_html).create_async().await;

    let _checksum_mock = server
        .mock("GET", "/?download=data%2F2026%2Fdiscogs_20260101_CHECKSUM.txt")
        .with_status(200)
        .with_body(fake_data_checksums_txt())
        .create_async()
        .await;

    let file_types = ["artists", "labels", "masters", "releases"];
    let mut downloader = Downloader::new_with_base_url(temp_dir.path().to_path_buf(), base_url).await.unwrap();

    // The good bytes the server will serve, hashed exactly as download_file would.
    let artists = "discogs_20260101_artists.xml.gz".to_string();
    let mut hasher = Sha256::new();
    hasher.update(b"fake artists data");
    let good_checksum = hex::encode(hasher.finalize());

    // artists is absent from disk (deleted to reclaim disk) but already processed.
    for file_type in &file_types {
        if *file_type == "artists" {
            continue;
        }
        let filename = format!("discogs_20260101_{}.xml.gz", file_type);
        let content = format!("fake {} data", file_type);
        let local_path = temp_dir.path().join(&filename);
        fs::write(&local_path, content.as_bytes()).await.unwrap();

        let mut hasher = Sha256::new();
        hasher.update(content.as_bytes());
        downloader.metadata.insert(
            filename,
            LocalFileInfo {
                path: local_path.to_string_lossy().to_string(),
                checksum: hex::encode(hasher.finalize()),
                version: "202601".to_string(),
                size: content.len() as u64,
            },
        );
    }

    let mut marker = StateMarker::new("20260101".to_string());
    marker.start_download(4);
    marker.start_file_download(&artists);
    marker.file_downloaded(&artists, 17);
    marker.file_bytes_verified(&artists, &good_checksum);
    marker.complete_download();
    marker.start_processing(4);
    marker.start_file_processing(&artists);
    marker.complete_file_processing(&artists, 500);
    downloader.set_state_marker(marker, temp_dir.path().join("marker.json"));

    let mut _download_mocks = Vec::new();
    for file_type in &file_types {
        let download_path = format!("/?download=data%2F2026%2Fdiscogs_20260101_{}.xml.gz", file_type);
        let mock = server
            .mock("GET", download_path.as_str())
            .with_status(200)
            .with_body(format!("fake {} data", file_type))
            .create_async()
            .await;
        _download_mocks.push(mock);
    }

    downloader.download_discogs_data().await.unwrap();

    let marker = downloader.take_state_marker().unwrap();
    let all_files: Vec<String> = file_types.iter().map(|t| format!("discogs_20260101_{}.xml.gz", t)).collect();
    assert!(!marker.pending_files(&all_files).contains(&artists), "identical bytes must not force a reparse of an already-processed file");
    assert_eq!(marker.processing_phase.records_extracted, 500);
}
