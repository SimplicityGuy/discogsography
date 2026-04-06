# MusicBrainz Auto-Download Design

## Problem

The MusicBrainz extractor requires pre-downloaded JSONL dump files in the `MUSICBRAINZ_ROOT` directory. When files are missing, it logs a warning and exits. Unlike the Discogs extractor, which automatically downloads data from `data.discogs.com`, the MusicBrainz path has no download capability.

## Solution

Add automatic downloading of MusicBrainz JSON dump files from `https://data.metabrainz.org/pub/musicbrainz/data/json-dumps/`, with version checking and a periodic loop to detect new dumps.

## Download Source

- **Base URL**: `https://data.metabrainz.org/pub/musicbrainz/data/json-dumps/`
- **Structure**: Root index contains version-stamped directories (e.g., `20260325-001001/`)
- **Version format**: `YYYYMMDD-HHMMSS`
- **Per-version contents**: `.tar.xz` archives per entity, `SHA256SUMS` for integrity
- **Relevant archives**: `artist.tar.xz` (~2GB), `label.tar.xz` (~159MB), `release.tar.xz` (~20GB)
- **Tarball structure**: Each `.tar.xz` contains `<entity>/mbdump/<entity>` — a raw JSONL file (not xz-compressed internally)

## Architecture

### MbDownloader struct

New `MbDownloader` in `musicbrainz_downloader.rs`, parallel to the Discogs `Downloader`:

```
MbDownloader {
    output_directory: PathBuf,   // MUSICBRAINZ_ROOT
    base_url: String,            // MUSICBRAINZ_DUMP_URL
}
```

### download_latest() flow

```
pub async fn download_latest() -> Result<MbDownloadResult>

1. GET <base_url>/ -> scrape HTML for directory links matching YYYYMMDD-HHMMSS pattern
   -> sort descending, pick the latest version string
2. Check if <output_dir>/<version>/ exists with all 3 entity files (artist.jsonl, label.jsonl, release.jsonl)
   -> if yes, return MbDownloadResult::AlreadyCurrent(version)
3. Download <base_url>/<version>/SHA256SUMS -> parse into HashMap<filename, hash>
4. For each entity (artist, label, release):
   a. Download <base_url>/<version>/<entity>.tar.xz to <output_dir>/<version>/<entity>.tar.xz.tmp
      - Streaming download with reqwest bytes_stream
      - Compute SHA256 on the fly during download
      - Verify against SHA256SUMS after download completes
      - Retry logic: 3 attempts, exponential backoff (same constants as Discogs downloader)
      - Progress logging every 10 seconds
   b. Rename .tar.xz.tmp to .tar.xz (preserve original tarball)
   c. Extract+compress mbdump/<entity> from tarball in a single streaming pass using spawn_blocking
      -> stream: tar.xz → XZ decoder → XZ encoder (level 6) → <output_dir>/<version>/<entity>.jsonl.xz
      -> no intermediate uncompressed file on disk
5. Return MbDownloadResult::Downloaded(version)
```

### Extracted file layout

```
/musicbrainz-data/
  20260325-001001/
    artist.tar.xz       <- original tarball (preserved)
    artist.jsonl.xz      <- streaming extract+compress from artist.tar.xz
    label.tar.xz
    label.jsonl.xz
    release.tar.xz
    release.jsonl.xz
```

### Streaming extract+compress

Uses `tar` and `xz2` crates (synchronous, run via `spawn_blocking`). Streams the tar entry
directly through an XZ encoder to produce `.jsonl.xz` on disk — no intermediate uncompressed file:

```rust
let file = File::open(&tarball_path)?;
let xz = xz2::read::XzDecoder::new(file);
let mut archive = tar::Archive::new(xz);

for entry in archive.entries()? {
    let mut entry = entry?;
    let path = entry.path()?;
    if path.ends_with(format!("mbdump/{}", entity)) {
        let out_file = File::create(&out_path)?;  // .jsonl.xz
        let mut encoder = XzEncoder::new(out_file, 6);
        io::copy(&mut entry, &mut encoder)?;
        encoder.finish()?;
        break;
    }
}
// Original .tar.xz is preserved for re-extraction if needed
```

Security: Only the expected `mbdump/<entity>` entry is extracted. All other tar entries are skipped. Paths are validated to prevent path traversal. Partial output files are cleaned up on failure.

## Integration with Extraction Pipeline

### process_musicbrainz_data changes

Before (current):

1. `discover_mb_dump_files(musicbrainz_root)` — if empty, warn and exit
1. Detect version, process files

After:

1. `MbDownloader::new(musicbrainz_root, dump_url).download_latest()` — returns version
1. Set working root to `<musicbrainz_root>/<version>/`
1. `discover_mb_dump_files(versioned_root)` — should always find files now
1. `detect_mb_dump_version` naturally extracts YYYYMMDD from directory name
1. State marker check — if already processed and not `force_reprocess`, skip
1. Otherwise proceed with existing processing pipeline (unchanged)

### Periodic loop in main.rs

New `run_musicbrainz_loop` function (mirrors `run_extraction_loop`):

```rust
pub async fn run_musicbrainz_loop(...) -> Result<()> {
    // Initial download + process
    process_musicbrainz_data(...).await?;

    // Periodic check loop
    loop {
        tokio::select! {
            _ = sleep(check_interval) => {
                // Re-run process_musicbrainz_data
                // download_latest() will check for newer version
                // State marker prevents re-processing same version
            }
            trigger = wait_for_trigger(&trigger) => { ... }
            _ = shutdown.notified() => break;
        }
    }
}
```

The `main.rs` MusicBrainz branch calls `run_musicbrainz_loop` instead of one-shot `process_musicbrainz_data`.

### Discovery updates

- `discover_mb_dump_files` updated to also match bare `.jsonl` files (not just `.jsonl.xz`)
- New `find_latest_mb_directory(root)` scans subdirectories for YYYYMMDD-HHMMSS pattern, returns latest

## Configuration

- **New field**: `ExtractorConfig.musicbrainz_dump_url: String`
- **Env var**: `MUSICBRAINZ_DUMP_URL` (default: `https://data.metabrainz.org/pub/musicbrainz/data/json-dumps/`)
- **Existing**: `PERIODIC_CHECK_DAYS` reused for the MusicBrainz periodic loop (already set to 7 in docker-compose)

## Rust Dependencies

New in `Cargo.toml`:

- `tar` — read tar archives
- `xz2` — xz decompression (wraps liblzma)

Both are synchronous and used inside `spawn_blocking`.

## Files Changed

1. **`extractor/src/musicbrainz_downloader.rs`** — add `MbDownloader`, `download_latest`, `find_latest_mb_directory`, update `discover_mb_dump_files` for bare `.jsonl` matching
1. **`extractor/src/config.rs`** — add `musicbrainz_dump_url` field and env var loading
1. **`extractor/src/extractor.rs`** — update `process_musicbrainz_data` to download first, add `run_musicbrainz_loop`
1. **`extractor/src/main.rs`** — call `run_musicbrainz_loop` for MusicBrainz source
1. **`extractor/Cargo.toml`** — add `tar`, `xz2` dependencies
1. **`extractor/src/tests/musicbrainz_downloader_tests.rs`** — new download/extraction tests
1. **`docker-compose.yml`** — optionally add `MUSICBRAINZ_DUMP_URL` env var

## Tests

- `test_scrape_version_directories` — parse HTML index, extract YYYYMMDD-HHMMSS patterns, pick latest
- `test_download_latest_already_current` — version dir exists with all 3 files -> returns AlreadyCurrent
- `test_download_latest_new_version` — mock server serves tar.xz files -> downloads, extracts, verifies SHA256
- `test_download_retry_on_failure` — first attempt fails, second succeeds
- `test_sha256_mismatch_fails` — corrupted download detected
- `test_tar_extraction_correct_file` — extracts only mbdump/<entity>, ignores COPYING/README/etc.
- `test_find_latest_mb_directory` — scans filesystem for version-stamped subdirectories
- `test_discover_finds_bare_jsonl` — discovery matches artist.jsonl (no .xz extension)

Existing discovery tests remain unchanged.
