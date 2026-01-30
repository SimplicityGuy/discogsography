# S3 Listing Fix for Discogs Data Downloads

## Problem

The Discogs S3 bucket (`discogs-data-dumps`) is configured to allow public downloads of specific files (using `s3:GetObject`), but it **does not** allow public listing of the bucket contents (using `s3:ListBucket`).

When pyextractor and rustextractor attempted to use `list_objects_v2` to discover available data files, they would receive an `AccessDenied` error because the bucket policy explicitly denies the `ListBucket` action for anonymous users.

## Solution

Instead of trying to list and access the S3 bucket directly, both extractors now:
1. **Scrape the file list** from the Discogs website at https://data.discogs.com/
2. **Download files through the Discogs website proxy** instead of direct S3 access

### How It Works

1. **Fetch Main Page**: Get the list of available year directories (e.g., 2026/, 2025/, etc.)
2. **Fetch Recent Years**: Check the last 2 years for available data files
3. **Parse File Information**: Extract file names and version IDs from the HTML
4. **Download via Proxy**: Use the Discogs website download URLs (e.g., `https://data.discogs.com/?download=data%2F2026%2Fdiscogs_20260101_artists.xml.gz`)

### Benefits

- ✅ Avoids `AccessDenied` errors from S3 listing and GetObject attempts
- ✅ Uses only publicly available information from the Discogs website
- ✅ Downloads through Discogs' official website proxy (same as browser downloads)
- ✅ No AWS credentials or S3 client needed
- ✅ Simpler, more reliable approach

## Changes Made

### Python Extractor (`extractor/pyextractor/discogs.py`)

1. **Removed S3 dependencies**: Removed `boto3` from imports and dependencies
2. **Added HTTP downloads**: Created `_download_file_from_discogs()` function to download files via Discogs website proxy
3. **Added web scraping**: Created `_scrape_file_list_from_discogs()` function to fetch file list from website
4. **Updated download logic**: Modified `download_discogs_data()` to use HTTP downloads instead of S3
5. **Updated dependencies**: Added `requests>=2.31.0`, removed `boto3>=1.34.0` from `pyproject.toml`

### Rust Extractor (`extractor/rustextractor/src/downloader.rs`)

1. **Removed S3 dependencies**: Removed `aws-config` and `aws-sdk-s3` from Cargo.toml
2. **Removed S3 client**: Removed `S3Client` from `Downloader` struct
3. **Added HTTP downloads**: Updated `download_file()` method to download files via Discogs website proxy using reqwest
4. **Added web scraping**: Created `scrape_file_list_from_discogs()` method to fetch file list from website
5. **Updated file listing**: Modified `list_s3_files()` to use the scraper instead of S3 listing
6. **Updated dependencies**: Added `regex` and `urlencoding`, removed AWS SDK dependencies from `Cargo.toml`
7. **Updated tests**: Fixed test comments and warnings, all 18 tests passing

## Testing

The Python implementation was tested and successfully retrieves the file list:

```
✅ Successfully scraped file list!
📊 Found 13 unique versions

📅 Latest versions:
  - 20260101: 5 files (4 data + 1 checksum)
  - 20251201: 5 files (4 data + 1 checksum)
  - 20251101: 5 files (4 data + 1 checksum)
```

## Technical Details

### HTML Structure

The Discogs data page uses a simple HTML structure:

- **Main page**: Lists year directories as `?prefix=data%2F{YEAR}%2F`
- **Year page**: Lists files as `?download=data%2F{YEAR}%2Fdiscogs_{YYYYMMDD}_{type}.xml.gz`

### File Naming Pattern

Files follow a predictable pattern:
- `discogs_{YYYYMMDD}_artists.xml.gz`
- `discogs_{YYYYMMDD}_labels.xml.gz`
- `discogs_{YYYYMMDD}_masters.xml.gz`
- `discogs_{YYYYMMDD}_releases.xml.gz`
- `discogs_{YYYYMMDD}_CHECKSUM.txt`

A complete monthly dump consists of exactly 5 files (4 data files + 1 checksum).

### Download URLs

Files are downloaded using the Discogs website proxy:
- **Format**: `https://data.discogs.com/?download={url_encoded_s3_key}`
- **Example**: `https://data.discogs.com/?download=data%2F2026%2Fdiscogs_20260101_artists.xml.gz`

This approach:
- Works exactly like browser downloads
- Requires no authentication
- Is officially supported by Discogs
- Handles rate limiting and CDN caching

## Future Considerations

### Website Structure Changes

If Discogs changes their website structure, the scraping logic may need to be updated. However, since this is a static HTML page with a simple structure, it's unlikely to change frequently.

### Alternative Approaches

1. **If Discogs enables public S3 access**: Could revert to S3 API for better performance
2. **If Discogs provides an API**: Could use official API endpoints instead of scraping
3. **If download proxy changes**: May need to update URL construction logic

### Performance Optimization

The current implementation:
- Checks only the last 2 years for efficiency
- Uses streaming downloads for large files
- Maintains checksum validation for data integrity

Future optimizations could include:
- Parallel downloads for multiple files
- Resume capability for interrupted downloads
- Better progress reporting with actual file sizes
