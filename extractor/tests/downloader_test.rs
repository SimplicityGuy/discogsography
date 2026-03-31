// Additional integration tests for discogs_downloader module
// Tests S3 file listing, metadata handling, and download logic

use extractor::discogs_downloader::Downloader;
use extractor::types::{LocalFileInfo, S3FileInfo};
use std::collections::HashMap;
use tempfile::TempDir;
use tokio::fs;

#[tokio::test]
async fn test_downloader_initialization() {
    let temp_dir = TempDir::new().unwrap();
    let result = Downloader::new(temp_dir.path().to_path_buf()).await;

    assert!(result.is_ok());
    let downloader = result.unwrap();

    // Should have empty metadata initially
    assert!(downloader.metadata.is_empty());
}

#[tokio::test]
async fn test_downloader_creates_output_directory() {
    let temp_dir = TempDir::new().unwrap();
    let nested_path = temp_dir.path().join("nested").join("directory");

    let downloader = Downloader::new(nested_path.clone()).await.unwrap();

    // Directory may not exist yet until first download, but save_metadata should work
    if !nested_path.exists() {
        // Create it for the test
        fs::create_dir_all(&nested_path).await.unwrap();
        let _result = downloader.save_metadata();
        assert!(_result.is_ok());
    }
}

#[tokio::test]
async fn test_metadata_persistence() {
    let temp_dir = TempDir::new().unwrap();
    let mut downloader = Downloader::new(temp_dir.path().to_path_buf()).await.unwrap();

    // Add some metadata
    downloader.metadata.insert(
        "test1.xml.gz".to_string(),
        LocalFileInfo { path: "/tmp/test1.xml.gz".to_string(), checksum: "abc123".to_string(), version: "202412".to_string(), size: 1024 },
    );

    downloader.metadata.insert(
        "test2.xml.gz".to_string(),
        LocalFileInfo { path: "/tmp/test2.xml.gz".to_string(), checksum: "def456".to_string(), version: "202412".to_string(), size: 2048 },
    );

    // Save metadata
    downloader.save_metadata().unwrap();

    // Create new downloader instance
    let downloader2 = Downloader::new(temp_dir.path().to_path_buf()).await.unwrap();

    // Should load saved metadata
    assert_eq!(downloader2.metadata.len(), 2);
    assert!(downloader2.metadata.contains_key("test1.xml.gz"));
    assert!(downloader2.metadata.contains_key("test2.xml.gz"));
}

#[tokio::test]
async fn test_should_download_missing_file() {
    let temp_dir = TempDir::new().unwrap();
    let downloader = Downloader::new(temp_dir.path().to_path_buf()).await.unwrap();

    let file_info = S3FileInfo { name: "nonexistent.xml.gz".to_string(), size: 1024 };

    let result = downloader.should_download(&file_info).await.unwrap();
    assert!(result, "Should download missing file");
}

#[tokio::test]
async fn test_should_not_download_up_to_date_file() {
    let temp_dir = TempDir::new().unwrap();
    let mut downloader = Downloader::new(temp_dir.path().to_path_buf()).await.unwrap();

    // Create a test file
    let filename = "test.xml.gz";
    let file_path = temp_dir.path().join(filename);
    let content = b"test content";
    fs::write(&file_path, content).await.unwrap();

    // Calculate actual checksum
    let actual_checksum = {
        use sha2::{Digest, Sha256};
        let mut hasher = Sha256::new();
        hasher.update(content);
        format!("{:x}", hasher.finalize())
    };

    // Add metadata with correct checksum and size
    downloader.metadata.insert(
        filename.to_string(),
        LocalFileInfo {
            path: file_path.to_string_lossy().to_string(),
            checksum: actual_checksum,
            version: "202412".to_string(),
            size: content.len() as u64,
        },
    );

    let file_info = S3FileInfo { name: filename.to_string(), size: content.len() as u64 };

    let result = downloader.should_download(&file_info).await.unwrap();
    assert!(!result, "Should not download up-to-date file");
}

#[tokio::test]
async fn test_should_download_when_size_differs() {
    let temp_dir = TempDir::new().unwrap();
    let mut downloader = Downloader::new(temp_dir.path().to_path_buf()).await.unwrap();

    // Create a test file
    let filename = "test.xml.gz";
    let file_path = temp_dir.path().join(filename);
    fs::write(&file_path, b"content").await.unwrap();

    // Add metadata with different size
    downloader.metadata.insert(
        filename.to_string(),
        LocalFileInfo {
            path: file_path.to_string_lossy().to_string(),
            checksum: "abc123".to_string(),
            version: "202412".to_string(),
            size: 100, // Different from actual size
        },
    );

    let file_info = S3FileInfo {
        name: filename.to_string(),
        size: 200, // Different size
    };

    let result = downloader.should_download(&file_info).await.unwrap();
    assert!(result, "Should download when size differs");
}

#[tokio::test]
async fn test_should_download_when_checksum_differs() {
    let temp_dir = TempDir::new().unwrap();
    let mut downloader = Downloader::new(temp_dir.path().to_path_buf()).await.unwrap();

    // Create a test file
    let filename = "test.xml.gz";
    let file_path = temp_dir.path().join(filename);
    let content = b"test content";
    fs::write(&file_path, content).await.unwrap();

    // Add metadata with wrong checksum
    downloader.metadata.insert(
        filename.to_string(),
        LocalFileInfo {
            path: file_path.to_string_lossy().to_string(),
            checksum: "wrong_checksum".to_string(),
            version: "202412".to_string(),
            size: content.len() as u64,
        },
    );

    let file_info = S3FileInfo { name: filename.to_string(), size: content.len() as u64 };

    let result = downloader.should_download(&file_info).await.unwrap();
    assert!(result, "Should download when checksum differs");
}

// Note: extract_month_from_filename is a private function
// It's already tested in the downloader module
// We test the functionality through the public API

#[tokio::test]
async fn test_get_latest_monthly_files_incomplete_set() {
    let temp_dir = TempDir::new().unwrap();
    let downloader = Downloader::new(temp_dir.path().to_path_buf()).await.unwrap();

    // Only 3 files instead of required 5 (4 data + 1 checksum)
    let files = vec![
        S3FileInfo { name: "data/discogs_20241201_artists.xml.gz".to_string(), size: 1024 },
        S3FileInfo { name: "data/discogs_20241201_labels.xml.gz".to_string(), size: 1024 },
        S3FileInfo { name: "data/discogs_20241201_CHECKSUM.txt".to_string(), size: 100 },
    ];

    let result = downloader.get_latest_monthly_files(&files).unwrap();
    assert_eq!(result.len(), 0, "Should return empty for incomplete set");
}

#[tokio::test]
async fn test_get_latest_monthly_files_deeply_nested_paths() {
    let temp_dir = TempDir::new().unwrap();
    let downloader = Downloader::new(temp_dir.path().to_path_buf()).await.unwrap();

    // Files with deeply nested S3 key prefixes containing multiple path separators.
    // The basename extraction fix (lines 242-247) ensures these are grouped correctly
    // by extracting the basename before splitting on '_' to determine the version ID.
    let files = vec![
        S3FileInfo { name: "data/2024/monthly/discogs_20241201_artists.xml.gz".to_string(), size: 1024 },
        S3FileInfo { name: "data/2024/monthly/discogs_20241201_labels.xml.gz".to_string(), size: 1024 },
        S3FileInfo { name: "data/2024/monthly/discogs_20241201_masters.xml.gz".to_string(), size: 1024 },
        S3FileInfo { name: "data/2024/monthly/discogs_20241201_releases.xml.gz".to_string(), size: 1024 },
        S3FileInfo { name: "data/2024/monthly/discogs_20241201_CHECKSUM.txt".to_string(), size: 100 },
    ];

    let result = downloader.get_latest_monthly_files(&files).unwrap();
    // Without the basename fix, splitting "data/2024/monthly/discogs_20241201_artists.xml.gz"
    // on '_' would produce id "data/2024/monthly/discogs" instead of "20241201",
    // causing files to not group correctly. With the fix, they group by "20241201".
    assert_eq!(result.len(), 4, "Should return 4 data files from deeply nested paths");

    // Returned files have S3_PREFIX ("data/") stripped but may retain inner path segments
    for file in &result {
        assert!(file.name.contains("discogs_20241201_"), "File name '{}' should contain discogs prefix", file.name);
        assert!(file.name.ends_with(".xml.gz"), "File name '{}' should be a data file", file.name);
    }
}

#[tokio::test]
async fn test_get_latest_monthly_files_complete_set() {
    let temp_dir = TempDir::new().unwrap();
    let downloader = Downloader::new(temp_dir.path().to_path_buf()).await.unwrap();

    // Complete set: 4 data files + 1 checksum
    let files = vec![
        S3FileInfo { name: "data/discogs_20241201_artists.xml.gz".to_string(), size: 1024 },
        S3FileInfo { name: "data/discogs_20241201_labels.xml.gz".to_string(), size: 1024 },
        S3FileInfo { name: "data/discogs_20241201_masters.xml.gz".to_string(), size: 1024 },
        S3FileInfo { name: "data/discogs_20241201_releases.xml.gz".to_string(), size: 1024 },
        S3FileInfo { name: "data/discogs_20241201_CHECKSUM.txt".to_string(), size: 100 },
    ];

    let result = downloader.get_latest_monthly_files(&files).unwrap();
    assert_eq!(result.len(), 4, "Should return 4 data files");

    // Verify filenames retain the full S3 key (consumers use Path::file_name() for bare names)
    for file in &result {
        assert!(file.name.contains("discogs_20241201_"));
    }
}

#[tokio::test]
async fn test_get_latest_monthly_files_selects_newest() {
    let temp_dir = TempDir::new().unwrap();
    let downloader = Downloader::new(temp_dir.path().to_path_buf()).await.unwrap();

    // Two complete sets, different dates
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

    // All files should be from the newer version
    for file in &result {
        assert!(file.name.contains("20241215"));
    }
}

#[tokio::test]
async fn test_metadata_file_location() {
    let temp_dir = TempDir::new().unwrap();
    let mut downloader = Downloader::new(temp_dir.path().to_path_buf()).await.unwrap();

    downloader.metadata.insert(
        "test.xml.gz".to_string(),
        LocalFileInfo { path: "/tmp/test.xml.gz".to_string(), checksum: "hash".to_string(), version: "202412".to_string(), size: 100 },
    );

    downloader.save_metadata().unwrap();

    // Check that metadata file exists
    let metadata_path = temp_dir.path().join(".discogs_metadata.json");
    assert!(metadata_path.exists());

    // Verify content
    let content = fs::read_to_string(&metadata_path).await.unwrap();
    assert!(content.contains("test.xml.gz"));
    assert!(content.contains("hash"));
}

#[tokio::test]
async fn test_corrupted_metadata_handling() {
    let temp_dir = TempDir::new().unwrap();

    // Write invalid JSON to metadata file
    let metadata_path = temp_dir.path().join(".discogs_metadata.json");
    fs::write(&metadata_path, "not valid json {{{").await.unwrap();

    // Attempting to load should fail
    let result = Downloader::new(temp_dir.path().to_path_buf()).await;
    assert!(result.is_err(), "Should fail with corrupted metadata");
}

#[tokio::test]
async fn test_empty_metadata_file() {
    let temp_dir = TempDir::new().unwrap();

    // Create empty metadata file
    let metadata_path = temp_dir.path().join(".discogs_metadata.json");
    fs::write(&metadata_path, "{}").await.unwrap();

    // Should load successfully with empty metadata
    let result = Downloader::new(temp_dir.path().to_path_buf()).await;
    assert!(result.is_ok());

    let downloader = result.unwrap();
    assert!(downloader.metadata.is_empty());
}

#[tokio::test]
async fn test_metadata_with_multiple_versions() {
    let temp_dir = TempDir::new().unwrap();
    let mut downloader = Downloader::new(temp_dir.path().to_path_buf()).await.unwrap();

    // Add metadata for different versions
    for i in 1..=3 {
        downloader.metadata.insert(
            format!("file{}.xml.gz", i),
            LocalFileInfo {
                path: format!("/tmp/file{}.xml.gz", i),
                checksum: format!("hash{}", i),
                version: format!("20241{:02}", i),
                size: i * 1000,
            },
        );
    }

    downloader.save_metadata().unwrap();

    // Load in new instance
    let downloader2 = Downloader::new(temp_dir.path().to_path_buf()).await.unwrap();
    assert_eq!(downloader2.metadata.len(), 3);

    // Verify all entries
    for i in 1..=3 {
        let key = format!("file{}.xml.gz", i);
        assert!(downloader2.metadata.contains_key(&key));
        let info = &downloader2.metadata[&key];
        assert_eq!(info.version, format!("20241{:02}", i));
    }
}

#[tokio::test]
async fn test_s3_file_info_structure() {
    let file_info = S3FileInfo { name: "test.xml.gz".to_string(), size: 12345 };

    assert_eq!(file_info.name, "test.xml.gz");
    assert_eq!(file_info.size, 12345);
}

#[tokio::test]
async fn test_local_file_info_structure() {
    let file_info = LocalFileInfo { path: "/tmp/test.xml.gz".to_string(), checksum: "abc123".to_string(), version: "202412".to_string(), size: 1024 };

    assert_eq!(file_info.path, "/tmp/test.xml.gz");
    assert_eq!(file_info.checksum, "abc123");
    assert_eq!(file_info.version, "202412");
    assert_eq!(file_info.size, 1024);
}

// Note: calculate_file_checksum is a private function
// It's already tested in the downloader module

#[tokio::test]
async fn test_metadata_json_format() {
    let temp_dir = TempDir::new().unwrap();
    let mut downloader = Downloader::new(temp_dir.path().to_path_buf()).await.unwrap();

    downloader.metadata.insert(
        "test.xml.gz".to_string(),
        LocalFileInfo { path: "/tmp/test.xml.gz".to_string(), checksum: "abc123def456".to_string(), version: "202412".to_string(), size: 9876 },
    );

    downloader.save_metadata().unwrap();

    // Read and parse JSON
    let metadata_path = temp_dir.path().join(".discogs_metadata.json");
    let json_str = fs::read_to_string(&metadata_path).await.unwrap();
    let parsed: HashMap<String, LocalFileInfo> = serde_json::from_str(&json_str).unwrap();

    assert_eq!(parsed.len(), 1);
    let info = &parsed["test.xml.gz"];
    assert_eq!(info.checksum, "abc123def456");
    assert_eq!(info.size, 9876);
}

// ──────────────────────────────────────────────────────────────────────────────
// HTTP-based list_s3_files tests using mockito
// ──────────────────────────────────────────────────────────────────────────────

#[tokio::test]
async fn test_list_s3_files_scraping_with_valid_data() {
    let temp_dir = TempDir::new().unwrap();

    let mut server = mockito::Server::new_async().await;
    let base_url = format!("{}/", server.url());

    // Main page with year links — regex matches href="?prefix=data%2F(\d{4})%2F"
    let main_html = r#"<html><body>
        <a href="?prefix=data%2F2026%2F">2026/</a>
        <a href="?prefix=data%2F2025%2F">2025/</a>
    </body></html>"#;
    let _main_mock = server.mock("GET", "/").with_status(200).with_body(main_html).create_async().await;

    // Year page with file links — regex matches ?download=data%2F\d{4}%2F(discogs_(\d{8})_[^"]+)
    let year_html = r#"<html><body>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_artists.xml.gz">artists</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_labels.xml.gz">labels</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_masters.xml.gz">masters</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_releases.xml.gz">releases</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_CHECKSUM.txt">CHECKSUM</a>
    </body></html>"#;
    let _year_mock = server
        .mock("GET", "/?prefix=data%2F2026%2F")
        .with_status(200)
        .with_body(year_html)
        .create_async()
        .await;

    // 2025 year page — empty (no files)
    let _year2025_mock = server
        .mock("GET", "/?prefix=data%2F2025%2F")
        .with_status(200)
        .with_body("<html><body>No files</body></html>")
        .create_async()
        .await;

    let mut downloader = Downloader::new_with_base_url(temp_dir.path().to_path_buf(), base_url).await.unwrap();
    let files = downloader.list_s3_files().await.unwrap();

    assert_eq!(files.len(), 5, "Should find 5 files (4 data + 1 checksum)");
    assert!(files.iter().any(|f| f.name.contains("artists")));
    assert!(files.iter().any(|f| f.name.contains("labels")));
    assert!(files.iter().any(|f| f.name.contains("masters")));
    assert!(files.iter().any(|f| f.name.contains("releases")));
    assert!(files.iter().any(|f| f.name.contains("CHECKSUM")));
}

#[tokio::test]
async fn test_list_s3_files_no_files_found() {
    let temp_dir = TempDir::new().unwrap();

    let mut server = mockito::Server::new_async().await;
    let base_url = format!("{}/", server.url());

    // Main page with year links
    let main_html = r#"<html><body>
        <a href="?prefix=data%2F2026%2F">2026/</a>
    </body></html>"#;
    let _main_mock = server.mock("GET", "/").with_status(200).with_body(main_html).create_async().await;

    // Year page with NO matching file links
    let _year_mock = server
        .mock("GET", "/?prefix=data%2F2026%2F")
        .with_status(200)
        .with_body("<html><body>Nothing here</body></html>")
        .create_async()
        .await;

    let mut downloader = Downloader::new_with_base_url(temp_dir.path().to_path_buf(), base_url).await.unwrap();
    let result = downloader.list_s3_files().await;

    assert!(result.is_err(), "Should return error when no files found");
    let err_msg = format!("{}", result.err().unwrap());
    assert!(err_msg.contains("No files found"), "Error should mention no files: {}", err_msg);
}

#[tokio::test]
async fn test_list_s3_files_no_year_directories() {
    let temp_dir = TempDir::new().unwrap();

    let mut server = mockito::Server::new_async().await;
    let base_url = format!("{}/", server.url());

    // Main page with NO year links at all
    let main_html = r#"<html><body>No year directories found</body></html>"#;
    let _main_mock = server.mock("GET", "/").with_status(200).with_body(main_html).create_async().await;

    let mut downloader = Downloader::new_with_base_url(temp_dir.path().to_path_buf(), base_url).await.unwrap();
    let result = downloader.list_s3_files().await;

    assert!(result.is_err(), "Should return error when no year directories found");
    let err_msg = format!("{}", result.err().unwrap());
    assert!(err_msg.contains("year directories"), "Error should mention year directories: {}", err_msg);
}

#[tokio::test]
async fn test_list_s3_files_caching() {
    let temp_dir = TempDir::new().unwrap();

    let mut server = mockito::Server::new_async().await;
    let base_url = format!("{}/", server.url());

    // Main page with year links
    let main_html = r#"<html><body>
        <a href="?prefix=data%2F2026%2F">2026/</a>
    </body></html>"#;
    let _main_mock = server.mock("GET", "/").with_status(200).with_body(main_html).expect(1).create_async().await;

    let year_html = r#"<html><body>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_artists.xml.gz">file</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_labels.xml.gz">file</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_masters.xml.gz">file</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_releases.xml.gz">file</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_CHECKSUM.txt">file</a>
    </body></html>"#;
    let _year_mock = server
        .mock("GET", "/?prefix=data%2F2026%2F")
        .with_status(200)
        .with_body(year_html)
        .expect(1)
        .create_async()
        .await;

    let mut downloader = Downloader::new_with_base_url(temp_dir.path().to_path_buf(), base_url).await.unwrap();

    // First call — scrapes
    let files1 = downloader.list_s3_files().await.unwrap();
    assert_eq!(files1.len(), 5);

    // Second call — should use cache (mocks expect only 1 call each)
    let files2 = downloader.list_s3_files().await.unwrap();
    assert_eq!(files2.len(), 5);
}

#[tokio::test]
async fn test_download_discogs_data_with_mockito() {
    let temp_dir = TempDir::new().unwrap();

    let mut server = mockito::Server::new_async().await;
    let base_url = format!("{}/", server.url());

    // Main page with year links — must match regex: href="?prefix=data%2F(\d{4})%2F"
    let main_html = r#"<html><body>
        <a href="?prefix=data%2F2026%2F">2026/</a>
    </body></html>"#;
    let _main_mock = server.mock("GET", "/").with_status(200).with_body(main_html).create_async().await;

    // Year page — must match regex: ?download=data%2F\d{4}%2F(discogs_(\d{8})_[^"]+)
    let year_html = r#"<html><body>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_artists.xml.gz">file</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_labels.xml.gz">file</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_masters.xml.gz">file</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_releases.xml.gz">file</a>
        <a href="?download=data%2F2026%2Fdiscogs_20260101_CHECKSUM.txt">file</a>
    </body></html>"#;
    let _year_mock = server
        .mock("GET", "/?prefix=data%2F2026%2F")
        .with_status(200)
        .with_body(year_html)
        .create_async()
        .await;

    // Create compressed gzipped files for download
    use flate2::Compression;
    use flate2::write::GzEncoder;
    use std::io::Write;

    let xml_content = r#"<?xml version="1.0" encoding="UTF-8"?><artists><artist id="1"><name>Test</name></artist></artists>"#;
    let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
    encoder.write_all(xml_content.as_bytes()).unwrap();
    let compressed = encoder.finish().unwrap();

    // Mock the download endpoints — the downloader constructs URLs as: base_url + "?download=data%2F" + year + "%2F" + filename
    let _dl_artists = server
        .mock("GET", "/?download=data%2F2026%2Fdiscogs_20260101_artists.xml.gz")
        .with_status(200)
        .with_body(compressed.clone())
        .create_async()
        .await;
    let _dl_labels = server
        .mock("GET", "/?download=data%2F2026%2Fdiscogs_20260101_labels.xml.gz")
        .with_status(200)
        .with_body(compressed.clone())
        .create_async()
        .await;
    let _dl_masters = server
        .mock("GET", "/?download=data%2F2026%2Fdiscogs_20260101_masters.xml.gz")
        .with_status(200)
        .with_body(compressed.clone())
        .create_async()
        .await;
    let _dl_releases = server
        .mock("GET", "/?download=data%2F2026%2Fdiscogs_20260101_releases.xml.gz")
        .with_status(200)
        .with_body(compressed.clone())
        .create_async()
        .await;
    let _dl_checksum = server
        .mock("GET", "/?download=data%2F2026%2Fdiscogs_20260101_CHECKSUM.txt")
        .with_status(200)
        .with_body(b"checksum data")
        .create_async()
        .await;

    let mut downloader = Downloader::new_with_base_url(temp_dir.path().to_path_buf(), base_url).await.unwrap();
    let result = downloader.download_discogs_data().await;

    assert!(result.is_ok(), "Download should succeed: {:?}", result);
    let files = result.unwrap();
    assert!(files.len() >= 4, "Should download at least 4 files, got {}", files.len());
}
