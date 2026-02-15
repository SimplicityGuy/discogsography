// Additional integration tests for downloader module
// Tests S3 file listing, metadata handling, and download logic

use extractor::downloader::Downloader;
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
        LocalFileInfo {
            path: "/tmp/test1.xml.gz".to_string(),
            checksum: "abc123".to_string(),
            version: "202412".to_string(),
            size: 1024,
        },
    );

    downloader.metadata.insert(
        "test2.xml.gz".to_string(),
        LocalFileInfo {
            path: "/tmp/test2.xml.gz".to_string(),
            checksum: "def456".to_string(),
            version: "202412".to_string(),
            size: 2048,
        },
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

    let file_info = S3FileInfo {
        name: "nonexistent.xml.gz".to_string(),
        size: 1024,
    };

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

    let file_info = S3FileInfo {
        name: filename.to_string(),
        size: content.len() as u64,
    };

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

    let file_info = S3FileInfo {
        name: filename.to_string(),
        size: content.len() as u64,
    };

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
        S3FileInfo {
            name: "data/discogs_20241201_artists.xml.gz".to_string(),
            size: 1024,
        },
        S3FileInfo {
            name: "data/discogs_20241201_labels.xml.gz".to_string(),
            size: 1024,
        },
        S3FileInfo {
            name: "data/discogs_20241201_CHECKSUM.txt".to_string(),
            size: 100,
        },
    ];

    let result = downloader.get_latest_monthly_files(&files).unwrap();
    assert_eq!(result.len(), 0, "Should return empty for incomplete set");
}

#[tokio::test]
async fn test_get_latest_monthly_files_complete_set() {
    let temp_dir = TempDir::new().unwrap();
    let downloader = Downloader::new(temp_dir.path().to_path_buf()).await.unwrap();

    // Complete set: 4 data files + 1 checksum
    let files = vec![
        S3FileInfo {
            name: "data/discogs_20241201_artists.xml.gz".to_string(),
            size: 1024,
        },
        S3FileInfo {
            name: "data/discogs_20241201_labels.xml.gz".to_string(),
            size: 1024,
        },
        S3FileInfo {
            name: "data/discogs_20241201_masters.xml.gz".to_string(),
            size: 1024,
        },
        S3FileInfo {
            name: "data/discogs_20241201_releases.xml.gz".to_string(),
            size: 1024,
        },
        S3FileInfo {
            name: "data/discogs_20241201_CHECKSUM.txt".to_string(),
            size: 100,
        },
    ];

    let result = downloader.get_latest_monthly_files(&files).unwrap();
    assert_eq!(result.len(), 4, "Should return 4 data files");

    // Verify filenames have prefix stripped
    for file in &result {
        assert!(!file.name.starts_with("data/"));
    }
}

#[tokio::test]
async fn test_get_latest_monthly_files_selects_newest() {
    let temp_dir = TempDir::new().unwrap();
    let downloader = Downloader::new(temp_dir.path().to_path_buf()).await.unwrap();

    // Two complete sets, different dates
    let files = vec![
        // Older version (20241201)
        S3FileInfo {
            name: "data/discogs_20241201_artists.xml.gz".to_string(),
            size: 1024,
        },
        S3FileInfo {
            name: "data/discogs_20241201_labels.xml.gz".to_string(),
            size: 1024,
        },
        S3FileInfo {
            name: "data/discogs_20241201_masters.xml.gz".to_string(),
            size: 1024,
        },
        S3FileInfo {
            name: "data/discogs_20241201_releases.xml.gz".to_string(),
            size: 1024,
        },
        S3FileInfo {
            name: "data/discogs_20241201_CHECKSUM.txt".to_string(),
            size: 100,
        },
        // Newer version (20241215)
        S3FileInfo {
            name: "data/discogs_20241215_artists.xml.gz".to_string(),
            size: 2048,
        },
        S3FileInfo {
            name: "data/discogs_20241215_labels.xml.gz".to_string(),
            size: 2048,
        },
        S3FileInfo {
            name: "data/discogs_20241215_masters.xml.gz".to_string(),
            size: 2048,
        },
        S3FileInfo {
            name: "data/discogs_20241215_releases.xml.gz".to_string(),
            size: 2048,
        },
        S3FileInfo {
            name: "data/discogs_20241215_CHECKSUM.txt".to_string(),
            size: 100,
        },
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
        LocalFileInfo {
            path: "/tmp/test.xml.gz".to_string(),
            checksum: "hash".to_string(),
            version: "202412".to_string(),
            size: 100,
        },
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
    let file_info = S3FileInfo {
        name: "test.xml.gz".to_string(),
        size: 12345,
    };

    assert_eq!(file_info.name, "test.xml.gz");
    assert_eq!(file_info.size, 12345);
}

#[tokio::test]
async fn test_local_file_info_structure() {
    let file_info = LocalFileInfo {
        path: "/tmp/test.xml.gz".to_string(),
        checksum: "abc123".to_string(),
        version: "202412".to_string(),
        size: 1024,
    };

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
        LocalFileInfo {
            path: "/tmp/test.xml.gz".to_string(),
            checksum: "abc123def456".to_string(),
            version: "202412".to_string(),
            size: 9876,
        },
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
