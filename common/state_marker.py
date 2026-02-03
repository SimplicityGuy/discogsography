"""State marker module for tracking extraction progress across phases.

This module provides state tracking for Discogs data extraction, allowing
the extractor to resume, re-process, or skip processing based on previous state.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, StrEnum
import json
from pathlib import Path
from typing import Any

import structlog


logger = structlog.get_logger(__name__)


class PhaseStatus(StrEnum):
    """Phase status for tracking progress."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class DownloadPhase:
    """Download phase tracking."""

    status: PhaseStatus = PhaseStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None
    files_downloaded: int = 0
    files_total: int = 0
    bytes_downloaded: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class FileProcessingStatus:
    """File processing status."""

    status: PhaseStatus = PhaseStatus.PENDING
    records_extracted: int = 0
    messages_published: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass
class ProcessingPhase:
    """Processing phase tracking."""

    status: PhaseStatus = PhaseStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None
    files_processed: int = 0
    files_total: int = 0
    records_extracted: int = 0
    current_file: str | None = None
    progress_by_file: dict[str, FileProcessingStatus] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


@dataclass
class PublishingPhase:
    """Publishing phase tracking."""

    status: PhaseStatus = PhaseStatus.PENDING
    messages_published: int = 0
    batches_sent: int = 0
    errors: list[str] = field(default_factory=list)
    last_amqp_heartbeat: datetime | None = None


@dataclass
class ExtractionSummary:
    """Overall extraction status summary."""

    overall_status: PhaseStatus = PhaseStatus.PENDING
    total_duration_seconds: float | None = None
    files_by_type: dict[str, PhaseStatus] = field(default_factory=dict)


class ProcessingDecision(StrEnum):
    """Decision on how to handle processing."""

    REPROCESS = "reprocess"  # Re-download and re-process everything
    CONTINUE = "continue"  # Continue processing unfinished files
    SKIP = "skip"  # Skip processing, already complete


@dataclass
class StateMarker:
    """Main state marker tracking all extraction phases."""

    metadata_version: str = "1.0"
    last_updated: datetime = field(default_factory=lambda: datetime.now(UTC))
    current_version: str = ""
    download_phase: DownloadPhase = field(default_factory=DownloadPhase)
    processing_phase: ProcessingPhase = field(default_factory=ProcessingPhase)
    publishing_phase: PublishingPhase = field(default_factory=PublishingPhase)
    summary: ExtractionSummary = field(default_factory=ExtractionSummary)

    @classmethod
    def load(cls, path: Path) -> "StateMarker | None":
        """Load state marker from file."""
        if not path.exists():
            logger.debug("📋 No state marker found", path=str(path))
            return None

        try:
            with path.open() as f:
                data = json.load(f)

            # Convert datetime strings back to datetime objects
            marker = cls._from_dict(data)
            logger.info("📋 Loaded state marker for version", version=marker.current_version)
            return marker

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("⚠️ Failed to load state marker", path=str(path), error=str(e))
            return None

    def save(self, path: Path) -> None:
        """Save state marker to file."""
        self.last_updated = datetime.now(UTC)

        # Convert to dict and handle datetime serialization
        data = self._to_dict()

        with path.open("w") as f:
            json.dump(data, f, indent=2, default=str)

        logger.debug("💾 Saved state marker", path=str(path))

    @staticmethod
    def file_path(discogs_root: Path, version: str) -> Path:
        """Get the file path for this version's state marker."""
        return discogs_root / f".extraction_status_{version}.json"

    def should_process(self) -> ProcessingDecision:
        """Check if we should re-process, continue, or skip."""
        # If download failed, need to re-download
        if self.download_phase.status == PhaseStatus.FAILED:
            logger.warning("⚠️ Download phase failed, will re-download")
            return ProcessingDecision.REPROCESS

        # If processing failed, can resume
        if self.processing_phase.status == PhaseStatus.FAILED:
            logger.warning("⚠️ Processing phase failed, will resume")
            return ProcessingDecision.CONTINUE

        # If processing in progress, resume
        if self.processing_phase.status == PhaseStatus.IN_PROGRESS:
            logger.info("🔄 Processing in progress, will resume")
            return ProcessingDecision.CONTINUE

        # If everything completed successfully, skip
        if self.summary.overall_status == PhaseStatus.COMPLETED:
            logger.info("✅ Version already fully processed", version=self.current_version)
            return ProcessingDecision.SKIP

        # Otherwise, continue processing
        return ProcessingDecision.CONTINUE

    def start_download(self, files_total: int) -> None:
        """Mark download phase as started."""
        self.download_phase.status = PhaseStatus.IN_PROGRESS
        self.download_phase.started_at = datetime.now(UTC)
        self.download_phase.files_total = files_total
        self.download_phase.files_downloaded = 0
        self.download_phase.bytes_downloaded = 0

    def file_downloaded(self, bytes_count: int) -> None:
        """Mark a file as downloaded."""
        self.download_phase.files_downloaded += 1
        self.download_phase.bytes_downloaded += bytes_count

    def complete_download(self) -> None:
        """Mark download phase as completed."""
        self.download_phase.status = PhaseStatus.COMPLETED
        self.download_phase.completed_at = datetime.now(UTC)
        logger.info(
            "✅ Download phase completed",
            files=self.download_phase.files_downloaded,
            bytes=self.download_phase.bytes_downloaded,
        )

    def fail_download(self, error: str) -> None:
        """Mark download phase as failed."""
        self.download_phase.status = PhaseStatus.FAILED
        self.download_phase.errors.append(error)
        self.summary.overall_status = PhaseStatus.FAILED

    def start_processing(self, files_total: int) -> None:
        """Mark processing phase as started."""
        self.processing_phase.status = PhaseStatus.IN_PROGRESS
        self.processing_phase.started_at = datetime.now(UTC)
        self.processing_phase.files_total = files_total
        self.processing_phase.files_processed = 0
        self.processing_phase.records_extracted = 0
        # Update summary status when processing starts
        self.summary.overall_status = PhaseStatus.IN_PROGRESS

    def start_file_processing(self, filename: str) -> None:
        """Mark a file processing as started."""
        self.processing_phase.current_file = filename
        self.processing_phase.progress_by_file[filename] = FileProcessingStatus(
            status=PhaseStatus.IN_PROGRESS,
            started_at=datetime.now(UTC),
        )

    def update_file_progress(self, filename: str, records: int, messages: int) -> None:
        """Update file processing progress."""
        if filename in self.processing_phase.progress_by_file:
            status = self.processing_phase.progress_by_file[filename]
            status.records_extracted = records
            status.messages_published = messages

        # Update processing phase totals by summing all file progress
        self.processing_phase.records_extracted = sum(status.records_extracted for status in self.processing_phase.progress_by_file.values())

        # files_processed is only incremented when files complete, not during progress updates
        # This is handled by complete_file_processing()

    def complete_file_processing(self, filename: str, records: int) -> None:
        """Mark a file processing as completed."""
        if filename in self.processing_phase.progress_by_file:
            status = self.processing_phase.progress_by_file[filename]
            status.status = PhaseStatus.COMPLETED
            status.completed_at = datetime.now(UTC)
            status.records_extracted = records

        self.processing_phase.files_processed += 1

        # Update total records by summing from all files (same as update_file_progress)
        # This ensures we don't double-count since we're already tracking in progress_by_file
        self.processing_phase.records_extracted = sum(status.records_extracted for status in self.processing_phase.progress_by_file.values())

        # Update summary
        data_type = _extract_data_type(filename)
        if data_type:
            self.summary.files_by_type[data_type] = PhaseStatus.COMPLETED

    def complete_processing(self) -> None:
        """Mark processing phase as completed."""
        self.processing_phase.status = PhaseStatus.COMPLETED
        self.processing_phase.completed_at = datetime.now(UTC)
        self.processing_phase.current_file = None
        logger.info(
            "✅ Processing phase completed",
            files=self.processing_phase.files_processed,
            records=self.processing_phase.records_extracted,
        )

    def fail_processing(self, error: str) -> None:
        """Mark processing phase as failed."""
        self.processing_phase.status = PhaseStatus.FAILED
        self.processing_phase.errors.append(error)
        self.summary.overall_status = PhaseStatus.FAILED

    def update_publishing(self, messages: int, batches: int) -> None:
        """Update publishing metrics."""
        self.publishing_phase.status = PhaseStatus.IN_PROGRESS
        self.publishing_phase.messages_published += messages
        self.publishing_phase.batches_sent += batches
        self.publishing_phase.last_amqp_heartbeat = datetime.now(UTC)

    def fail_publishing(self, error: str) -> None:
        """Mark publishing as failed."""
        self.publishing_phase.status = PhaseStatus.FAILED
        self.publishing_phase.errors.append(error)

    def complete_extraction(self) -> None:
        """Mark entire extraction as completed."""
        self.publishing_phase.status = PhaseStatus.COMPLETED
        self.summary.overall_status = PhaseStatus.COMPLETED

        # Calculate total duration
        if self.download_phase.started_at and self.processing_phase.completed_at:
            duration = self.processing_phase.completed_at - self.download_phase.started_at
            self.summary.total_duration_seconds = duration.total_seconds()

        logger.info("🎉 Extraction completed for version", version=self.current_version)

    def pending_files(self, all_files: list[str]) -> list[str]:
        """Get list of files that still need processing."""
        return [
            f
            for f in all_files
            if f not in self.processing_phase.progress_by_file or self.processing_phase.progress_by_file[f].status != PhaseStatus.COMPLETED
        ]

    def _to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""

        def convert_value(value: Any) -> Any:
            if isinstance(value, datetime):
                return value.isoformat()
            if isinstance(value, Enum):
                return value.value
            if isinstance(value, dict):
                return {k: convert_value(v) for k, v in value.items()}
            if isinstance(value, list):
                return [convert_value(v) for v in value]
            if hasattr(value, "__dict__"):
                return {k: convert_value(v) for k, v in value.__dict__.items()}
            return value

        return {k: convert_value(v) for k, v in self.__dict__.items()}

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> "StateMarker":
        """Create from dictionary loaded from JSON."""

        def parse_datetime(value: str | None) -> datetime | None:
            if value is None:
                return None
            return datetime.fromisoformat(value)

        def parse_phase_status(value: str) -> PhaseStatus:
            return PhaseStatus(value)

        # Parse download phase
        download_data = data.get("download_phase", {})
        download_phase = DownloadPhase(
            status=parse_phase_status(download_data.get("status", "pending")),
            started_at=parse_datetime(download_data.get("started_at")),
            completed_at=parse_datetime(download_data.get("completed_at")),
            files_downloaded=download_data.get("files_downloaded", 0),
            files_total=download_data.get("files_total", 0),
            bytes_downloaded=download_data.get("bytes_downloaded", 0),
            errors=download_data.get("errors", []),
        )

        # Parse processing phase
        processing_data = data.get("processing_phase", {})
        progress_by_file = {}
        for filename, status_data in processing_data.get("progress_by_file", {}).items():
            progress_by_file[filename] = FileProcessingStatus(
                status=parse_phase_status(status_data.get("status", "pending")),
                records_extracted=status_data.get("records_extracted", 0),
                messages_published=status_data.get("messages_published", 0),
                started_at=parse_datetime(status_data.get("started_at")),
                completed_at=parse_datetime(status_data.get("completed_at")),
            )

        processing_phase = ProcessingPhase(
            status=parse_phase_status(processing_data.get("status", "pending")),
            started_at=parse_datetime(processing_data.get("started_at")),
            completed_at=parse_datetime(processing_data.get("completed_at")),
            files_processed=processing_data.get("files_processed", 0),
            files_total=processing_data.get("files_total", 0),
            records_extracted=processing_data.get("records_extracted", 0),
            current_file=processing_data.get("current_file"),
            progress_by_file=progress_by_file,
            errors=processing_data.get("errors", []),
        )

        # Parse publishing phase
        publishing_data = data.get("publishing_phase", {})
        publishing_phase = PublishingPhase(
            status=parse_phase_status(publishing_data.get("status", "pending")),
            messages_published=publishing_data.get("messages_published", 0),
            batches_sent=publishing_data.get("batches_sent", 0),
            errors=publishing_data.get("errors", []),
            last_amqp_heartbeat=parse_datetime(publishing_data.get("last_amqp_heartbeat")),
        )

        # Parse summary
        summary_data = data.get("summary", {})
        files_by_type = {k: parse_phase_status(v) for k, v in summary_data.get("files_by_type", {}).items()}

        summary = ExtractionSummary(
            overall_status=parse_phase_status(summary_data.get("overall_status", "pending")),
            total_duration_seconds=summary_data.get("total_duration_seconds"),
            files_by_type=files_by_type,
        )

        return cls(
            metadata_version=data.get("metadata_version", "1.0"),
            last_updated=parse_datetime(data.get("last_updated")) or datetime.now(UTC),
            current_version=data.get("current_version", ""),
            download_phase=download_phase,
            processing_phase=processing_phase,
            publishing_phase=publishing_phase,
            summary=summary,
        )


def _extract_data_type(filename: str) -> str | None:
    """Extract data type from filename (e.g., 'discogs_20260101_artists.xml.gz' -> 'artists')."""
    try:
        return filename.split("_")[2].split(".")[0]
    except (IndexError, AttributeError):
        return None
