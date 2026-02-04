"""Tests for state marker module."""

from pathlib import Path

from common.state_marker import (
    DownloadPhase,
    ExtractionSummary,
    FileProcessingStatus,
    PhaseStatus,
    ProcessingDecision,
    ProcessingPhase,
    PublishingPhase,
    StateMarker,
    _extract_data_type,
)


class TestPhaseStatus:
    """Test phase status enum."""

    def test_phase_status_values(self):
        """Test phase status enum values."""
        assert PhaseStatus.PENDING == "pending"
        assert PhaseStatus.IN_PROGRESS == "in_progress"
        assert PhaseStatus.COMPLETED == "completed"
        assert PhaseStatus.FAILED == "failed"


class TestDownloadPhase:
    """Test download phase tracking."""

    def test_download_phase_default(self):
        """Test download phase default values."""
        phase = DownloadPhase()
        assert phase.status == PhaseStatus.PENDING
        assert phase.started_at is None
        assert phase.completed_at is None
        assert phase.files_downloaded == 0
        assert phase.files_total == 0
        assert phase.bytes_downloaded == 0
        assert phase.errors == []


class TestFileProcessingStatus:
    """Test file processing status."""

    def test_file_processing_status_default(self):
        """Test file processing status default values."""
        status = FileProcessingStatus()
        assert status.status == PhaseStatus.PENDING
        assert status.records_extracted == 0
        assert status.messages_published == 0
        assert status.started_at is None
        assert status.completed_at is None


class TestProcessingPhase:
    """Test processing phase tracking."""

    def test_processing_phase_default(self):
        """Test processing phase default values."""
        phase = ProcessingPhase()
        assert phase.status == PhaseStatus.PENDING
        assert phase.started_at is None
        assert phase.completed_at is None
        assert phase.files_processed == 0
        assert phase.files_total == 0
        assert phase.records_extracted == 0
        assert phase.current_file is None
        assert phase.progress_by_file == {}
        assert phase.errors == []


class TestPublishingPhase:
    """Test publishing phase tracking."""

    def test_publishing_phase_default(self):
        """Test publishing phase default values."""
        phase = PublishingPhase()
        assert phase.status == PhaseStatus.PENDING
        assert phase.messages_published == 0
        assert phase.batches_sent == 0
        assert phase.errors == []
        assert phase.last_amqp_heartbeat is None


class TestExtractionSummary:
    """Test extraction summary."""

    def test_extraction_summary_default(self):
        """Test extraction summary default values."""
        summary = ExtractionSummary()
        assert summary.overall_status == PhaseStatus.PENDING
        assert summary.total_duration_seconds is None
        assert summary.files_by_type == {}


class TestStateMarker:
    """Test state marker."""

    def test_new_state_marker(self):
        """Test creating new state marker."""
        marker = StateMarker(current_version="20260101")
        assert marker.current_version == "20260101"
        assert marker.metadata_version == "1.0"
        assert marker.download_phase.status == PhaseStatus.PENDING
        assert marker.processing_phase.status == PhaseStatus.PENDING
        assert marker.publishing_phase.status == PhaseStatus.PENDING
        assert marker.summary.overall_status == PhaseStatus.PENDING

    def test_download_lifecycle(self):
        """Test download phase lifecycle."""
        marker = StateMarker(current_version="20260101")

        # Start download
        marker.start_download(4)
        assert marker.download_phase.status == PhaseStatus.IN_PROGRESS
        assert marker.download_phase.files_total == 4
        assert marker.download_phase.started_at is not None

        # Download files
        marker.file_downloaded("discogs_20260101_artists.xml.gz", 1000)
        marker.file_downloaded("discogs_20260101_labels.xml.gz", 2000)
        assert marker.download_phase.files_downloaded == 2
        assert marker.download_phase.bytes_downloaded == 3000
        assert len(marker.download_phase.downloads_by_file) == 2

        # Complete download
        marker.complete_download()
        assert marker.download_phase.status == PhaseStatus.COMPLETED
        assert marker.download_phase.completed_at is not None

    def test_processing_lifecycle(self):
        """Test processing phase lifecycle."""
        marker = StateMarker(current_version="20260101")

        # Start processing - should also set summary status to IN_PROGRESS
        marker.start_processing(4)
        assert marker.processing_phase.status == PhaseStatus.IN_PROGRESS
        assert marker.processing_phase.files_total == 4
        assert marker.summary.overall_status == PhaseStatus.IN_PROGRESS

        # Process file
        marker.start_file_processing("discogs_20260101_artists.xml.gz")
        assert marker.processing_phase.current_file == "discogs_20260101_artists.xml.gz"

        # Update progress - should update phase totals
        marker.update_file_progress("discogs_20260101_artists.xml.gz", 100, 10)
        assert marker.processing_phase.records_extracted == 100  # Should sum from progress_by_file
        assert marker.processing_phase.files_processed == 0  # No files completed yet

        # Start another file
        marker.start_file_processing("discogs_20260101_labels.xml.gz")
        marker.update_file_progress("discogs_20260101_labels.xml.gz", 50, 5)
        assert marker.processing_phase.records_extracted == 150  # 100 + 50
        assert marker.processing_phase.files_processed == 0  # Still no files completed

        # Complete first file - this increments files_processed
        marker.complete_file_processing("discogs_20260101_artists.xml.gz", 100)
        assert marker.processing_phase.files_processed == 1  # Now 1 file completed
        assert marker.processing_phase.records_extracted == 150  # Still 150 total (complete doesn't add, it's already counted)

        # Complete processing
        marker.complete_processing()
        assert marker.processing_phase.status == PhaseStatus.COMPLETED
        assert marker.processing_phase.completed_at is not None
        assert marker.processing_phase.current_file is None

    def test_should_process_decisions(self):
        """Test processing decision logic."""
        marker = StateMarker(current_version="20260101")

        # New marker should continue
        assert marker.should_process() == ProcessingDecision.CONTINUE

        # Failed download should reprocess
        marker.fail_download("Test error")
        assert marker.should_process() == ProcessingDecision.REPROCESS

        # Reset and test in-progress processing
        marker = StateMarker(current_version="20260101")
        marker.start_processing(4)
        assert marker.should_process() == ProcessingDecision.CONTINUE

        # Completed should skip
        marker.complete_processing()
        marker.complete_extraction()
        assert marker.should_process() == ProcessingDecision.SKIP

    def test_pending_files(self):
        """Test pending files calculation."""
        marker = StateMarker(current_version="20260101")

        all_files = [
            "discogs_20260101_artists.xml.gz",
            "discogs_20260101_labels.xml.gz",
            "discogs_20260101_masters.xml.gz",
        ]

        # All pending initially
        pending = marker.pending_files(all_files)
        assert len(pending) == 3

        # Mark one as completed
        marker.start_file_processing("discogs_20260101_artists.xml.gz")
        marker.complete_file_processing("discogs_20260101_artists.xml.gz", 100)

        pending = marker.pending_files(all_files)
        assert len(pending) == 2
        assert "discogs_20260101_artists.xml.gz" not in pending

    def test_save_and_load(self, tmp_path: Path):
        """Test saving and loading state marker."""
        marker = StateMarker(current_version="20260101")
        marker.start_download(4)
        marker.file_downloaded("discogs_20260101_artists.xml.gz", 1000)

        # Save
        path = tmp_path / ".extraction_status_20260101.json"
        marker.save(path)
        assert path.exists()

        # Load
        loaded = StateMarker.load(path)
        assert loaded is not None
        assert loaded.current_version == "20260101"
        assert loaded.download_phase.files_downloaded == 1
        assert loaded.download_phase.bytes_downloaded == 1000
        assert len(loaded.download_phase.downloads_by_file) == 1

    def test_load_nonexistent_file(self, tmp_path: Path):
        """Test loading from nonexistent file."""
        path = tmp_path / ".extraction_status_20260101.json"
        loaded = StateMarker.load(path)
        assert loaded is None

    def test_file_path_generation(self, tmp_path: Path):
        """Test file path generation."""
        path = StateMarker.file_path(tmp_path, "20260101")
        assert path == tmp_path / ".extraction_status_20260101.json"

    def test_publishing_updates(self):
        """Test publishing updates."""
        marker = StateMarker(current_version="20260101")

        marker.update_publishing(100, 1)
        assert marker.publishing_phase.status == PhaseStatus.IN_PROGRESS
        assert marker.publishing_phase.messages_published == 100
        assert marker.publishing_phase.batches_sent == 1
        assert marker.publishing_phase.last_amqp_heartbeat is not None

        marker.update_publishing(200, 2)
        assert marker.publishing_phase.messages_published == 300
        assert marker.publishing_phase.batches_sent == 3

    def test_complete_extraction(self):
        """Test complete extraction."""
        marker = StateMarker(current_version="20260101")

        marker.start_download(4)
        marker.complete_download()
        marker.start_processing(4)
        marker.complete_processing()
        marker.complete_extraction()

        assert marker.summary.overall_status == PhaseStatus.COMPLETED
        assert marker.publishing_phase.status == PhaseStatus.COMPLETED
        assert marker.summary.total_duration_seconds is not None

    def test_error_tracking(self):
        """Test error tracking."""
        marker = StateMarker(current_version="20260101")

        marker.fail_download("Download failed")
        assert marker.download_phase.status == PhaseStatus.FAILED
        assert len(marker.download_phase.errors) == 1
        assert marker.summary.overall_status == PhaseStatus.FAILED

        marker = StateMarker(current_version="20260101")
        marker.fail_processing("Processing failed")
        assert marker.processing_phase.status == PhaseStatus.FAILED
        assert len(marker.processing_phase.errors) == 1
        assert marker.summary.overall_status == PhaseStatus.FAILED

        marker = StateMarker(current_version="20260101")
        marker.fail_publishing("Publishing failed")
        assert marker.publishing_phase.status == PhaseStatus.FAILED
        assert len(marker.publishing_phase.errors) == 1

    def test_serialization_roundtrip(self, tmp_path: Path):
        """Test full serialization roundtrip."""
        marker = StateMarker(current_version="20260101")

        # Set up complete state
        marker.start_download(4)
        marker.file_downloaded("discogs_20260101_artists.xml.gz", 1000)
        marker.complete_download()

        marker.start_processing(4)
        marker.start_file_processing("discogs_20260101_artists.xml.gz")
        marker.update_file_progress("discogs_20260101_artists.xml.gz", 100, 100, 2)
        marker.complete_file_processing("discogs_20260101_artists.xml.gz", 100)
        marker.complete_processing()

        marker.complete_extraction()

        # Save and load
        path = tmp_path / ".extraction_status_20260101.json"
        marker.save(path)

        loaded = StateMarker.load(path)
        assert loaded is not None

        # Verify all fields
        assert loaded.current_version == "20260101"
        assert loaded.download_phase.status == PhaseStatus.COMPLETED
        assert loaded.download_phase.files_downloaded == 1
        assert loaded.download_phase.bytes_downloaded == 1000

        assert loaded.processing_phase.status == PhaseStatus.COMPLETED
        assert loaded.processing_phase.files_processed == 1
        assert loaded.processing_phase.records_extracted == 100

        assert loaded.publishing_phase.status == PhaseStatus.COMPLETED
        assert loaded.publishing_phase.messages_published == 100
        assert loaded.publishing_phase.batches_sent == 2  # From update_file_progress call

        assert loaded.summary.overall_status == PhaseStatus.COMPLETED
        assert loaded.summary.total_duration_seconds is not None

    def test_load_invalid_json(self, tmp_path: Path):
        """Test loading invalid JSON."""
        path = tmp_path / ".extraction_status_20260101.json"
        path.write_text("invalid json")

        loaded = StateMarker.load(path)
        assert loaded is None


class TestExtractDataType:
    """Test data type extraction."""

    def test_extract_data_type(self):
        """Test extracting data type from filename."""
        assert _extract_data_type("discogs_20260101_artists.xml.gz") == "artists"
        assert _extract_data_type("discogs_20260101_labels.xml.gz") == "labels"
        assert _extract_data_type("discogs_20260101_masters.xml.gz") == "masters"
        assert _extract_data_type("discogs_20260101_releases.xml.gz") == "releases"

    def test_extract_data_type_invalid(self):
        """Test extracting data type from invalid filename."""
        assert _extract_data_type("invalid.xml.gz") is None
        assert _extract_data_type("") is None


class TestProcessingDecision:
    """Test processing decision enum."""

    def test_processing_decision_values(self):
        """Test processing decision enum values."""
        assert ProcessingDecision.REPROCESS == "reprocess"
        assert ProcessingDecision.CONTINUE == "continue"
        assert ProcessingDecision.SKIP == "skip"
