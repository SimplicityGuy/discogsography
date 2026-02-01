# State Marker System

The state marker system tracks extraction progress across all phases, allowing the extractor to intelligently decide whether to re-process, continue, or skip processing when restarted.

## Overview

Each Discogs data version (e.g., `20260101`) has its own state marker file (`.extraction_status_20260101.json`) that tracks:

1. **Download Phase** - File downloads and checksums
2. **Processing Phase** - Which files are being/have been processed
3. **Publishing Phase** - Messages sent to RabbitMQ
4. **Overall Status** - Decision logic for restart behavior

## File Structure

```json
{
  "metadata_version": "1.0",
  "last_updated": "2026-01-31T12:34:56.789Z",
  "current_version": "20260101",

  "download_phase": {
    "status": "completed",
    "started_at": "2026-01-31T12:00:00.000Z",
    "completed_at": "2026-01-31T12:15:00.000Z",
    "files_downloaded": 4,
    "files_total": 4,
    "bytes_downloaded": 5234567890,
    "errors": []
  },

  "processing_phase": {
    "status": "in_progress",
    "started_at": "2026-01-31T12:15:00.000Z",
    "completed_at": null,
    "files_processed": 2,
    "files_total": 4,
    "records_extracted": 1234567,
    "current_file": "discogs_20260101_releases.xml.gz",
    "progress_by_file": {
      "discogs_20260101_artists.xml.gz": {
        "status": "completed",
        "records_extracted": 500000,
        "messages_published": 5000,
        "started_at": "2026-01-31T12:15:00.000Z",
        "completed_at": "2026-01-31T12:20:00.000Z"
      },
      "discogs_20260101_labels.xml.gz": {
        "status": "completed",
        "records_extracted": 250000,
        "messages_published": 2500,
        "started_at": "2026-01-31T12:20:00.000Z",
        "completed_at": "2026-01-31T12:25:00.000Z"
      },
      "discogs_20260101_masters.xml.gz": {
        "status": "in_progress",
        "records_extracted": 150000,
        "messages_published": 1500,
        "started_at": "2026-01-31T12:25:00.000Z",
        "completed_at": null
      }
    },
    "errors": []
  },

  "publishing_phase": {
    "status": "in_progress",
    "messages_published": 1234567,
    "batches_sent": 12345,
    "errors": [],
    "last_amqp_heartbeat": "2026-01-31T12:34:50.000Z"
  },

  "summary": {
    "overall_status": "in_progress",
    "total_duration_seconds": null,
    "files_by_type": {
      "artists": "completed",
      "labels": "completed",
      "masters": "in_progress",
      "releases": "pending"
    }
  }
}
```

## Phase Status Values

- `pending` - Not started yet
- `in_progress` - Currently running
- `completed` - Successfully finished
- `failed` - Encountered an error

## Processing Decisions

When the extractor restarts, it checks the state marker and makes one of three decisions:

### 1. Reprocess (Start Over)

**Triggered when:**
- Download phase failed
- State marker is corrupted
- Force reprocess flag is set

**Action:**
- Delete old files
- Re-download all data
- Re-process from scratch

### 2. Continue (Resume)

**Triggered when:**
- Processing phase is `in_progress`
- Processing phase `failed` but can recover

**Action:**
- Skip completed files
- Resume processing unfinished files
- Continue from last checkpoint

### 3. Skip (Already Complete)

**Triggered when:**
- Overall status is `completed`
- All files successfully processed
- No new version available

**Action:**
- Log "already processed" message
- Wait for next periodic check
- No processing occurs

## Usage in Rust Extractor

```rust
use crate::state_marker::{StateMarker, ProcessingDecision};

// Load existing state or create new
let marker_path = StateMarker::file_path(&config.discogs_root, &version);
let mut marker = StateMarker::load(&marker_path)
    .await?
    .unwrap_or_else(|| StateMarker::new(version.clone()));

// Check what to do
match marker.should_process() {
    ProcessingDecision::Skip => {
        info!("✅ Version {} already processed, skipping", version);
        return Ok(true);
    }
    ProcessingDecision::Reprocess => {
        warn!("⚠️ Will re-download and re-process");
        marker = StateMarker::new(version.clone());
    }
    ProcessingDecision::Continue => {
        info!("🔄 Will continue processing");
    }
}

// Track download phase
marker.start_download(files.len());
for file in &files {
    download_file(&file).await?;
    marker.file_downloaded(file.size);
    marker.save(&marker_path).await?;
}
marker.complete_download();
marker.save(&marker_path).await?;

// Track processing phase
marker.start_processing(files.len());
marker.save(&marker_path).await?;

for file in &files {
    // Skip if already completed
    if marker.processing_phase.progress_by_file
        .get(file)
        .map(|s| s.status == PhaseStatus::Completed)
        .unwrap_or(false)
    {
        info!("✅ Skipping already processed file: {}", file);
        continue;
    }

    marker.start_file_processing(&file);
    marker.save(&marker_path).await?;

    // Process file...
    let records = process_file(&file).await?;

    marker.complete_file_processing(&file, records);
    marker.save(&marker_path).await?;
}

marker.complete_processing();
marker.complete_extraction();
marker.save(&marker_path).await?;
```

## Usage in Python Extractor

```python
from pathlib import Path
from common import StateMarker, ProcessingDecision, PhaseStatus

# Load existing state or create new
marker_path = StateMarker.file_path(Path(config.discogs_root), version)
marker = StateMarker.load(marker_path) or StateMarker(current_version=version)

# Check what to do
decision = marker.should_process()
if decision == ProcessingDecision.SKIP:
    logger.info("✅ Version already processed, skipping", version=version)
    return True
elif decision == ProcessingDecision.REPROCESS:
    logger.warning("⚠️ Will re-download and re-process")
    marker = StateMarker(current_version=version)
elif decision == ProcessingDecision.CONTINUE:
    logger.info("🔄 Will continue processing")

# Track download phase
marker.start_download(len(files))
for file in files:
    download_file(file)
    marker.file_downloaded(file.size)
    marker.save(marker_path)

marker.complete_download()
marker.save(marker_path)

# Track processing phase
marker.start_processing(len(files))
marker.save(marker_path)

for file in files:
    # Skip if already completed
    file_status = marker.processing_phase.progress_by_file.get(file)
    if file_status and file_status.status == PhaseStatus.COMPLETED:
        logger.info("✅ Skipping already processed file", file=file)
        continue

    marker.start_file_processing(file)
    marker.save(marker_path)

    # Process file...
    records = process_file(file)

    marker.complete_file_processing(file, records)
    marker.save(marker_path)

marker.complete_processing()
marker.complete_extraction()
marker.save(marker_path)
```

## Benefits

1. **Resilience** - Survive restarts without losing progress
2. **Efficiency** - Don't re-process already completed files
3. **Observability** - Clear view of extraction status
4. **Debugging** - Detailed error tracking per phase
5. **Idempotency** - Safe to restart at any time

## File Locations

State markers are stored in the Discogs root directory:

```
/discogs-data/
├── discogs_20260101_artists.xml.gz
├── discogs_20260101_labels.xml.gz
├── discogs_20260101_masters.xml.gz
├── discogs_20260101_releases.xml.gz
├── .discogs_metadata.json              # Download checksums (existing)
├── .processing_state.json              # Simple boolean flags (deprecated)
└── .extraction_status_20260101.json    # State marker (new)
```

## Version-Specific Tracking

Each Discogs version gets its own state marker:

- `.extraction_status_20260101.json` - January 2026 data
- `.extraction_status_20251201.json` - December 2025 data
- `.extraction_status_20251101.json` - November 2025 data

This allows:
- Multiple versions to coexist
- Easy cleanup of old versions
- Clear version history

## Migration Path

The new state marker system works alongside existing tracking:

1. `.discogs_metadata.json` - Still used for download checksums
2. `.processing_state.json` - Deprecated, replaced by state marker
3. `.extraction_status_*.json` - New comprehensive tracking

## Error Handling

If a state marker file is corrupted:

1. Log warning
2. Return `None` from load
3. Create new marker
4. Continue processing

This ensures the system is always resilient to state corruption.

## Testing

Both Rust and Python implementations have comprehensive tests:

**Rust:**
```bash
cd extractor/rustextractor
cargo test state_marker
```

**Python:**
```bash
uv run pytest tests/common/test_state_marker.py -v
```

## Future Enhancements

Potential improvements:

1. **Checkpoints** - Save progress every N records
2. **Metrics** - Track processing speed over time
3. **Alerts** - Notify on phase failures
4. **Cleanup** - Auto-remove old state markers
5. **Compression** - Gzip state markers for large extractions
