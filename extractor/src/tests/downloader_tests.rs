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

    let result = load_metadata(temp_dir.path());
    assert!(result.is_err());
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
        LocalFileInfo {
            path: local_path.to_string_lossy().to_string(),
            checksum: "abc123".to_string(),
            version: "202412".to_string(),
            size: 1024,
        },
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

    // Verify filenames have prefix stripped
    assert!(result.iter().all(|f| !f.name.starts_with("data/")));
}

#[tokio::test]
async fn test_with_state_marker() {
    use crate::state_marker::StateMarker;

    let temp_dir = TempDir::new().unwrap();
    let marker = StateMarker::new("20260101".to_string());
    let marker_path = temp_dir.path().join(".extraction_status_20260101.json");

    let downloader = Downloader::new(temp_dir.path().to_path_buf())
        .await
        .unwrap()
        .with_state_marker(marker, marker_path.clone());

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

    let mut downloader = Downloader::new(temp_dir.path().to_path_buf())
        .await
        .unwrap()
        .with_state_marker(marker, marker_path.clone());

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

    let _main_mock = server
        .mock("GET", "/")
        .with_status(200)
        .with_body(main_page_html)
        .create_async()
        .await;

    // Year page listing files (5 files = 4 data + 1 checksum for a complete set)
    let year_page_html = r#"<html><body>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_artists.xml.gz">artists</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_labels.xml.gz">labels</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_masters.xml.gz">masters</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_releases.xml.gz">releases</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_CHECKSUM.txt">checksum</a>
    </body></html>"#.to_string();

    let _year_mock = server
        .mock("GET", "/?prefix=data%2F2026%2F")
        .with_status(200)
        .with_body(&year_page_html)
        .create_async()
        .await;

    // Mock download endpoints for each file
    let file_types = ["artists", "labels", "masters", "releases"];
    let mut _download_mocks = Vec::new();
    for file_type in &file_types {
        let download_path = format!(
            "/?download=data%2F2026%2Fdiscogs_20260101_{}.xml.gz",
            file_type
        );
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

    let _main_mock = server
        .mock("GET", "/")
        .with_status(200)
        .with_body(main_page_html)
        .create_async()
        .await;

    // Year page with complete 5-file set
    let year_page_html = r#"<html><body>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_artists.xml.gz">artists</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_labels.xml.gz">labels</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_masters.xml.gz">masters</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_releases.xml.gz">releases</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_CHECKSUM.txt">checksum</a>
    </body></html>"#;

    let _year_mock = server
        .mock("GET", "/?prefix=data%2F2026%2F")
        .with_status(200)
        .with_body(year_page_html)
        .create_async()
        .await;

    // Pre-create all 4 data files locally with known content and matching checksums
    let file_types = ["artists", "labels", "masters", "releases"];
    let mut downloader = Downloader::new_with_base_url(temp_dir.path().to_path_buf(), base_url)
        .await
        .unwrap();

    for file_type in &file_types {
        let filename = format!("discogs_20260101_{}.xml.gz", file_type);
        let content = format!("existing {} data", file_type);
        let local_path = temp_dir.path().join(&filename);
        fs::write(&local_path, content.as_bytes()).await.unwrap();

        // Compute actual SHA256 checksum
        let mut hasher = Sha256::new();
        hasher.update(content.as_bytes());
        let checksum = format!("{:x}", hasher.finalize());

        // Pre-populate metadata with correct checksum
        downloader.metadata.insert(
            filename,
            LocalFileInfo {
                path: local_path.to_string_lossy().to_string(),
                checksum,
                version: "202601".to_string(),
                size: content.len() as u64,
            },
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
    let _main_mock = server
        .mock("GET", "/")
        .with_status(200)
        .with_body(main_page_html)
        .expect(1)
        .create_async()
        .await;

    let year_page_html = r#"<html><body>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_artists.xml.gz">artists</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_labels.xml.gz">labels</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_masters.xml.gz">masters</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_releases.xml.gz">releases</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_CHECKSUM.txt">checksum</a>
    </body></html>"#;

    let _year_mock = server
        .mock("GET", "/?prefix=data%2F2026%2F")
        .with_status(200)
        .with_body(year_page_html)
        .expect(1)
        .create_async()
        .await;

    let mut downloader = Downloader::new_with_base_url(temp_dir.path().to_path_buf(), base_url)
        .await
        .unwrap();

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

    let _main_mock = server
        .mock("GET", "/")
        .with_status(200)
        .with_body(main_page_html)
        .create_async()
        .await;

    let year_page_html = r#"<html><body>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_artists.xml.gz">artists</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_labels.xml.gz">labels</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_masters.xml.gz">masters</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_releases.xml.gz">releases</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_CHECKSUM.txt">checksum</a>
    </body></html>"#;

    let _year_mock = server
        .mock("GET", "/?prefix=data%2F2026%2F")
        .with_status(200)
        .with_body(year_page_html)
        .create_async()
        .await;

    // Pre-create all 4 data files with matching checksums
    let file_types = ["artists", "labels", "masters", "releases"];
    let mut downloader = Downloader::new_with_base_url(temp_dir.path().to_path_buf(), base_url)
        .await
        .unwrap();

    let mut expected_sizes: HashMap<String, u64> = HashMap::new();

    for file_type in &file_types {
        let filename = format!("discogs_20260101_{}.xml.gz", file_type);
        let content = format!("state marker {} data", file_type);
        let local_path = temp_dir.path().join(&filename);
        fs::write(&local_path, content.as_bytes()).await.unwrap();

        let mut hasher = Sha256::new();
        hasher.update(content.as_bytes());
        let checksum = format!("{:x}", hasher.finalize());

        expected_sizes.insert(filename.clone(), content.len() as u64);

        downloader.metadata.insert(
            filename,
            LocalFileInfo {
                path: local_path.to_string_lossy().to_string(),
                checksum,
                version: "202601".to_string(),
                size: content.len() as u64,
            },
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
    let mut downloader: Box<dyn DataSource> = Box::new(
        Downloader::new_with_base_url(temp_dir.path().to_path_buf(), "http://unused".to_string())
            .await
            .unwrap(),
    );

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
    let _year_mock = server
        .mock("GET", "/?prefix=data%2F2026%2F")
        .with_status(200)
        .with_body(year_page_html)
        .create_async()
        .await;

    let mut downloader: Box<dyn DataSource> = Box::new(
        Downloader::new_with_base_url(temp_dir.path().to_path_buf(), base_url)
            .await
            .unwrap(),
    );

    // Call through the DataSource trait
    let files = downloader.list_s3_files().await.unwrap();
    assert_eq!(files.len(), 5);
}

#[tokio::test]
async fn test_datasource_get_latest_monthly_files_via_trait() {
    let temp_dir = TempDir::new().unwrap();
    let downloader: Box<dyn DataSource> = Box::new(
        Downloader::new_with_base_url(temp_dir.path().to_path_buf(), "http://unused".to_string())
            .await
            .unwrap(),
    );

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

    let mut downloader = Downloader::new(temp_dir.path().to_path_buf())
        .await
        .unwrap()
        .with_state_marker(marker, bad_path.clone());

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
    let _year_mock = server
        .mock("GET", "/?prefix=data%2F2026%2F")
        .with_status(200)
        .with_body(year_page_html)
        .create_async()
        .await;

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

    let mut downloader: Box<dyn DataSource> = Box::new(
        Downloader::new_with_base_url(temp_dir.path().to_path_buf(), base_url)
            .await
            .unwrap(),
    );
    downloader.set_state_marker(marker, marker_path);

    // Call download_discogs_data through the DataSource trait
    let result = downloader.download_discogs_data().await.unwrap();
    assert_eq!(result.len(), 4);
}
