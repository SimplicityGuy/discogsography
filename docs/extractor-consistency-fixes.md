# Extractor Consistency Fixes

## Summary

This document describes the changes made to ensure both `pyextractor` and `rustextractor` operate identically with respect to state marker tracking.

## Issues Fixed

### 1. State Marker Tracking Improvements

#### Problem: Incorrect Metrics in State Marker

The state marker JSON was showing incorrect values:
- `bytes_downloaded`: 0 (should show actual bytes)
- `messages_published`: 0 in publishing_phase (should aggregate from files)
- `batches_sent`: 0 (should show actual batch count)

#### Root Causes

1. **Per-file tracking missing**: Download phase only tracked aggregate bytes, not per-file
2. **Publishing metrics not aggregated**: Publishing phase metrics were tracked separately instead of being calculated from file progress
3. **Batch tracking incomplete**: Batches weren't being counted properly

#### Solution

**Enhanced State Marker Structure:**

1. **Added `FileDownloadStatus`** to track downloads per file:
   ```python
   @dataclass
   class FileDownloadStatus:
       status: PhaseStatus
       bytes_downloaded: int
       started_at: datetime | None
       completed_at: datetime | None
   ```

2. **Added `downloads_by_file`** to `DownloadPhase`:
   - Tracks each file's download status and size
   - `bytes_downloaded` is now calculated as sum of all files

3. **Added `batches_sent`** to `FileProcessingStatus`:
   - Tracks batches sent per file
   - Publishing phase aggregates from all files

4. **Auto-calculation in `update_file_progress()`**:
   ```python
   def update_file_progress(self, filename: str, records: int, messages: int, batches: int = 0):
       # Update file-specific progress
       # ...

       # Auto-calculate publishing phase from all files
       self.publishing_phase.messages_published = sum(
           status.messages_published for status in self.processing_phase.progress_by_file.values()
       )
       self.publishing_phase.batches_sent = sum(
           status.batches_sent for status in self.processing_phase.progress_by_file.values()
       )
   ```

### 2. Extractor Behavioral Consistency

#### Problems Found

1. **Missing `start_file_download()` in Python**
   - Rust: Called before each download
   - Python: Not called at all
   - **Impact**: Missing download start timestamps in Python

2. **Different cached file tracking timing**
   - Python: Tracked cached files BEFORE `start_download()`
   - Rust: Tracked cached files AFTER `start_download()`
   - **Impact**: Timeline ordering inconsistency

3. **Reversed completion order**
   - Python: State marker → Completion message
   - Rust: Completion message → State marker
   - **Impact**: Race condition risk on process crash

#### Solutions Applied

**Python (`discogs.py`):**

1. **Added `start_file_download()` before download** (line 406-407):
   ```python
   # Start tracking file download in state marker
   state_marker.start_file_download(filename)
   state_marker.save(marker_path)
   ```

2. **Moved cached file tracking after `start_download()`** (lines 392-398):
   ```python
   # Start download phase tracking
   state_marker.start_download(total_files)
   state_marker.save(marker_path)

   # Track cached files (those with valid checksums that were skipped)
   for filename, checksum in checksums.items():
       file_path = output_path / filename
       if file_path.exists():
           file_size = file_path.stat().st_size
           state_marker.file_downloaded(filename, file_size)
   ```

3. **Already correct**: State marker updated before completion message

**Python (`extractor.py`):**

1. **Added `batches_sent` counter** (line 120):
   ```python
   self.batches_sent: int = 0
   ```

2. **Increment after batch flush** (line 804):
   ```python
   # Increment batches sent counter
   self.batches_sent += 1
   ```

3. **Pass to `update_file_progress()`** (line 702):
   ```python
   self.state_marker.update_file_progress(
       self.input_file,
       self.total_count,      # records
       self.total_count,      # messages (one per record)
       self.batches_sent,     # batches
   )
   ```

**Rust (`downloader.rs`):**

1. **Added `start_file_download()` before download** (lines 88-92):
   ```rust
   // Start tracking file download
   if let Some(ref mut marker) = self.state_marker {
       marker.start_file_download(filename);
       marker.save(marker_path).await.ok();
   }
   ```

2. **Already correct**: Cached files tracked after `start_download()`

**Rust (`extractor.rs`):**

1. **Added batch tracking** (lines 339, 373, 383, 388):
   ```rust
   let mut total_batches = 0u64;
   // ...
   total_batches += 1;
   ```

2. **Pass to `update_file_progress()`** (line 359):
   ```rust
   marker.update_file_progress(&file_name, total_records, total_records, total_batches);
   ```

3. **Fixed completion order** (lines 299-319):
   ```rust
   // Mark file as completed in state marker FIRST (consistent with Python)
   {
       let mut marker = state_marker.lock().await;
       marker.complete_file_processing(file_name, total_count);
       marker.save(&marker_path).await?;
   }

   // Update state
   // ...

   // THEN send file completion message (consistent with Python)
   mq.send_file_complete(data_type, file_name, total_count).await?;
   ```

## Verification

### Test Results

**Python Tests:**
```bash
uv run pytest tests/common/test_state_marker.py -v
# Result: 22 passed in 1.89s
```

**Rust Tests:**
```bash
cd extractor/rustextractor && cargo test --lib state_marker
# Result: 14 passed; 0 failed
```

### Expected State Marker Output

With these fixes, the state marker JSON now correctly shows:

```json
{
  "download_phase": {
    "status": "completed",
    "bytes_downloaded": 12052065551,  // ✅ Correct total
    "downloads_by_file": {
      "discogs_20260201_artists.xml.gz": {
        "status": "completed",
        "bytes_downloaded": 480351382,
        "started_at": "2026-02-04T00:02:54Z",
        "completed_at": "2026-02-04T00:03:45Z"
      },
      "discogs_20260201_labels.xml.gz": {
        "status": "completed",
        "bytes_downloaded": 86848860,
        "started_at": "2026-02-04T00:03:45Z",
        "completed_at": "2026-02-04T00:04:01Z"
      }
      // ... other files ...
    }
  },
  "processing_phase": {
    "status": "in_progress",
    "records_extracted": 525000,
    "progress_by_file": {
      "discogs_20260201_artists.xml.gz": {
        "status": "in_progress",
        "records_extracted": 175000,
        "messages_published": 175000,
        "batches_sent": 1750  // ✅ Now tracked
      },
      "discogs_20260201_labels.xml.gz": {
        "status": "in_progress",
        "records_extracted": 180000,
        "messages_published": 180000,
        "batches_sent": 1800  // ✅ Now tracked
      }
      // ... other files ...
    }
  },
  "publishing_phase": {
    "status": "in_progress",
    "messages_published": 525000,  // ✅ Aggregated from files
    "batches_sent": 5250,          // ✅ Aggregated from files
    "last_amqp_heartbeat": "2026-02-04T00:23:18Z"
  }
}
```

## Operational Consistency

Both extractors now:

1. **Download Phase:**
   - Call `start_download(total_files)` before any downloads
   - Call `start_file_download(filename)` before each file download
   - Call `file_downloaded(filename, bytes)` after each download (or for cached files)
   - Track per-file download status with timestamps
   - Calculate aggregate `bytes_downloaded` from all files

2. **Processing Phase:**
   - Call `start_processing(total_files)` before processing
   - Call `start_file_processing(filename)` when starting each file
   - Call `update_file_progress(filename, records, messages, batches)` periodically (every 5000 records)
   - Track batch counts per file
   - Auto-calculate publishing phase metrics from file progress
   - Call `complete_file_processing(filename, total_records)` when done

3. **Completion Order:**
   - Update state marker first
   - Send AMQP completion message second
   - Prevents state loss on crash between operations

4. **Publishing Metrics:**
   - No direct calls to `update_publishing()` needed
   - Metrics automatically calculated from `progress_by_file`
   - Publishing phase status updated when any messages are published

## Benefits

1. **Accurate Tracking**: All metrics now reflect actual progress
2. **Consistent Behavior**: Both implementations operate identically
3. **Better Observability**: Per-file tracking provides detailed insights
4. **Safer Operations**: Consistent completion order reduces race condition risk
5. **Easier Debugging**: State marker provides complete audit trail
6. **Resume Capability**: Per-file status enables fine-grained resume logic

## Migration Notes

No breaking changes for users. The enhanced state marker is backward-compatible:
- Old state markers without `downloads_by_file` will be handled gracefully
- Old state markers without `batches_sent` will default to 0
- Publishing phase metrics will be recalculated on next update

## Files Modified

### Common
- `common/state_marker.py` - Enhanced data structures and methods
- `extractor/rustextractor/src/state_marker.rs` - Enhanced data structures and methods

### Python Extractor
- `extractor/pyextractor/discogs.py` - Download tracking fixes
- `extractor/pyextractor/extractor.py` - Batch counting and progress updates

### Rust Extractor
- `extractor/rustextractor/src/downloader.rs` - Download tracking enhancements
- `extractor/rustextractor/src/extractor.rs` - Batch counting and completion order fix

### Tests
- `tests/common/test_state_marker.py` - Updated for new method signatures
- `extractor/rustextractor/src/state_marker.rs` (tests module) - Updated for new method signatures
- `extractor/rustextractor/src/extractor.rs` (tests module) - Updated for new method signatures

All tests pass in both implementations.
