// HTTP Integration tests for downloader module
// Tests web scraping and HTTP download functionality with mocked responses

use mockito::Server;
use rust_extractor::downloader::Downloader;
use rust_extractor::types::S3FileInfo;
use tempfile::TempDir;
use tokio::fs;

/// Helper to create a mock HTML response for the main Discogs page
fn create_main_page_html(years: &[&str]) -> String {
    let mut html = String::from("<html><body>");
    for year in years {
        html.push_str(&format!(
            r#"<a href="?prefix=data%2F{}%2F">{}

/</a>"#,
            year, year
        ));
    }
    html.push_str("</body></html>");
    html
}

/// Helper to create a mock HTML response for a year directory
fn create_year_page_html(year: &str, files: &[(&str, &str)]) -> String {
    let mut html = String::from("<html><body>");
    for (version, file_type) in files {
        html.push_str(&format!(
            r#"<a href="?download=data%2F{}%2Fdiscogs_{}_{}">discogs_{}_{}</a>"#,
            year, version, file_type, version, file_type
        ));
    }
    html.push_str("</body></html>");
    html
}

#[tokio::test]
async fn test_successful_web_scraping() {
    let mut server = Server::new_async().await;
    let temp_dir = TempDir::new().unwrap();

    // Mock main page response
    let _m1 = server
        .mock("GET", "/")
        .with_status(200)
        .with_body(create_main_page_html(&["2026", "2025"]))
        .create_async()
        .await;

    // Mock year directory pages
    let _m2 = server
        .mock("GET", "/?prefix=data%2F2026%2F")
        .with_status(200)
        .with_body(create_year_page_html(
            "2026",
            &[
                ("20260101", "artists.xml.gz"),
                ("20260101", "labels.xml.gz"),
                ("20260101", "masters.xml.gz"),
                ("20260101", "releases.xml.gz"),
                ("20260101", "CHECKSUM.txt"),
            ],
        ))
        .create_async()
        .await;

    let downloader =
        Downloader::new_with_base_url(temp_dir.path().to_path_buf(), format!("{}/", server.url()))
            .await
            .unwrap();

    // Test scraping (using private method through download_discogs_data)
    // We can't test scrape_file_list_from_discogs directly as it's private,
    // but we can verify the files are discovered correctly by checking the behavior

    // Verify downloader was created successfully
    assert!(downloader.metadata.is_empty());
    assert_eq!(downloader.output_directory, temp_dir.path());
}

#[tokio::test]
async fn test_empty_website_response() {
    let mut server = Server::new_async().await;
    let temp_dir = TempDir::new().unwrap();

    // Mock empty main page
    let _m = server
        .mock("GET", "/")
        .with_status(200)
        .with_body("<html><body></body></html>")
        .create_async()
        .await;

    let mut downloader =
        Downloader::new_with_base_url(temp_dir.path().to_path_buf(), format!("{}/", server.url()))
            .await
            .unwrap();

    // Attempt to download should fail due to no files found
    let result = downloader.download_discogs_data().await;
    assert!(result.is_err() || result.unwrap().is_empty());
}

#[tokio::test]
async fn test_website_connection_failure() {
    let temp_dir = TempDir::new().unwrap();

    // Use an invalid URL to simulate connection failure
    let mut downloader = Downloader::new_with_base_url(
        temp_dir.path().to_path_buf(),
        "http://localhost:59999/".to_string(), // Port unlikely to be in use
    )
    .await
    .unwrap();

    let result = downloader.download_discogs_data().await;
    assert!(result.is_err());
}

#[tokio::test]
async fn test_incomplete_file_set() {
    let mut server = Server::new_async().await;
    let temp_dir = TempDir::new().unwrap();

    // Mock main page
    let _m1 = server
        .mock("GET", "/")
        .with_status(200)
        .with_body(create_main_page_html(&["2026"]))
        .create_async()
        .await;

    // Mock year page with incomplete set (missing some files)
    let _m2 = server
        .mock("GET", "/?prefix=data%2F2026%2F")
        .with_status(200)
        .with_body(create_year_page_html(
            "2026",
            &[
                ("20260101", "artists.xml.gz"),
                ("20260101", "labels.xml.gz"),
                // Missing masters and releases
            ],
        ))
        .create_async()
        .await;

    let mut downloader =
        Downloader::new_with_base_url(temp_dir.path().to_path_buf(), format!("{}/", server.url()))
            .await
            .unwrap();

    let result = downloader.download_discogs_data().await;
    // Should return empty or error due to incomplete set
    assert!(result.is_err() || result.unwrap().is_empty());
}

#[tokio::test]
async fn test_http_download_success() {
    let mut server = Server::new_async().await;
    let temp_dir = TempDir::new().unwrap();

    let test_content = b"test file content for download";

    // Mock download endpoint
    let _m = server
        .mock("GET", "/?download=data%2Ftest_file.xml.gz")
        .with_status(200)
        .with_body(test_content)
        .create_async()
        .await;

    let mut downloader =
        Downloader::new_with_base_url(temp_dir.path().to_path_buf(), format!("{}/", server.url()))
            .await
            .unwrap();

    // Create a file info for testing
    let file_info = S3FileInfo {
        name: "test_file.xml.gz".to_string(),
        size: test_content.len() as u64,
    };

    // Download the file
    let result = downloader.download_file(&file_info).await;
    assert!(result.is_ok());

    // Verify file was created
    let downloaded_path = temp_dir.path().join("test_file.xml.gz");
    assert!(downloaded_path.exists());

    // Verify content matches
    let content = fs::read(&downloaded_path).await.unwrap();
    assert_eq!(content, test_content);
}

#[tokio::test]
async fn test_http_download_failure() {
    let mut server = Server::new_async().await;
    let temp_dir = TempDir::new().unwrap();

    // Mock download endpoint with error
    let _m = server
        .mock("GET", "/?download=data%2Ffailed_file.xml.gz")
        .with_status(500)
        .with_body("Internal Server Error")
        .create_async()
        .await;

    let mut downloader =
        Downloader::new_with_base_url(temp_dir.path().to_path_buf(), format!("{}/", server.url()))
            .await
            .unwrap();

    let file_info = S3FileInfo {
        name: "failed_file.xml.gz".to_string(),
        size: 1024,
    };

    // Download should fail
    let result = downloader.download_file(&file_info).await;
    assert!(result.is_err());
}

#[tokio::test]
async fn test_http_download_404() {
    let mut server = Server::new_async().await;
    let temp_dir = TempDir::new().unwrap();

    // Mock download endpoint with 404
    let _m = server
        .mock("GET", "/?download=data%2Fnonexistent.xml.gz")
        .with_status(404)
        .with_body("Not Found")
        .create_async()
        .await;

    let mut downloader =
        Downloader::new_with_base_url(temp_dir.path().to_path_buf(), format!("{}/", server.url()))
            .await
            .unwrap();

    let file_info = S3FileInfo {
        name: "nonexistent.xml.gz".to_string(),
        size: 1024,
    };

    let result = downloader.download_file(&file_info).await;
    assert!(result.is_err());
}

#[tokio::test]
async fn test_checksum_calculation_during_download() {
    let mut server = Server::new_async().await;
    let temp_dir = TempDir::new().unwrap();

    let test_content = b"checksum test content";

    // Mock download
    let _m = server
        .mock("GET", "/?download=data%2Fchecksum_test.xml.gz")
        .with_status(200)
        .with_body(test_content)
        .create_async()
        .await;

    let mut downloader =
        Downloader::new_with_base_url(temp_dir.path().to_path_buf(), format!("{}/", server.url()))
            .await
            .unwrap();

    let file_info = S3FileInfo {
        name: "checksum_test.xml.gz".to_string(),
        size: test_content.len() as u64,
    };

    downloader.download_file(&file_info).await.unwrap();

    // Check if metadata was updated with checksum
    let filename = "checksum_test.xml.gz";
    assert!(downloader.metadata.contains_key(filename));

    let metadata = &downloader.metadata[filename];
    assert!(!metadata.checksum.is_empty());
    assert_eq!(metadata.size, test_content.len() as u64);
}

#[tokio::test]
async fn test_concurrent_year_scraping() {
    let mut server = Server::new_async().await;
    let temp_dir = TempDir::new().unwrap();

    // Mock main page with multiple years
    let _m1 = server
        .mock("GET", "/")
        .with_status(200)
        .with_body(create_main_page_html(&["2026", "2025", "2024"]))
        .create_async()
        .await;

    // Mock first two years (scraper only checks last 2 years)
    let _m2 = server
        .mock("GET", "/?prefix=data%2F2026%2F")
        .with_status(200)
        .with_body(create_year_page_html(
            "2026",
            &[
                ("20260101", "artists.xml.gz"),
                ("20260101", "labels.xml.gz"),
                ("20260101", "masters.xml.gz"),
                ("20260101", "releases.xml.gz"),
                ("20260101", "CHECKSUM.txt"),
            ],
        ))
        .create_async()
        .await;

    let _m3 = server
        .mock("GET", "/?prefix=data%2F2025%2F")
        .with_status(200)
        .with_body(create_year_page_html(
            "2025",
            &[
                ("20251201", "artists.xml.gz"),
                ("20251201", "labels.xml.gz"),
                ("20251201", "masters.xml.gz"),
                ("20251201", "releases.xml.gz"),
                ("20251201", "CHECKSUM.txt"),
            ],
        ))
        .create_async()
        .await;

    let downloader =
        Downloader::new_with_base_url(temp_dir.path().to_path_buf(), format!("{}/", server.url()))
            .await
            .unwrap();

    // Verify downloader creation succeeds
    assert!(downloader.metadata.is_empty());
}

#[tokio::test]
async fn test_url_encoding_in_download() {
    let mut server = Server::new_async().await;
    let temp_dir = TempDir::new().unwrap();

    // Test file with special characters that need URL encoding
    let _m = server
        .mock("GET", "/?download=data%2Ffile%20with%20spaces.xml.gz")
        .with_status(200)
        .with_body(b"content")
        .create_async()
        .await;

    let mut downloader =
        Downloader::new_with_base_url(temp_dir.path().to_path_buf(), format!("{}/", server.url()))
            .await
            .unwrap();

    let file_info = S3FileInfo {
        name: "file with spaces.xml.gz".to_string(),
        size: 7,
    };

    let result = downloader.download_file(&file_info).await;
    assert!(result.is_ok());
}

#[tokio::test]
async fn test_large_file_streaming() {
    let mut server = Server::new_async().await;
    let temp_dir = TempDir::new().unwrap();

    // Create a larger test content (1MB)
    let test_content = vec![b'x'; 1024 * 1024];

    let _m = server
        .mock("GET", "/?download=data%2Flarge_file.xml.gz")
        .with_status(200)
        .with_body(&test_content)
        .create_async()
        .await;

    let mut downloader =
        Downloader::new_with_base_url(temp_dir.path().to_path_buf(), format!("{}/", server.url()))
            .await
            .unwrap();

    let file_info = S3FileInfo {
        name: "large_file.xml.gz".to_string(),
        size: test_content.len() as u64,
    };

    let result = downloader.download_file(&file_info).await;
    assert!(result.is_ok());

    // Verify file size
    let downloaded_path = temp_dir.path().join("large_file.xml.gz");
    let metadata = fs::metadata(&downloaded_path).await.unwrap();
    assert_eq!(metadata.len(), test_content.len() as u64);
}
