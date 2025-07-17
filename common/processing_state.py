"""Processing state tracker for incremental updates."""

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import orjson
import psycopg
from psycopg.rows import dict_row


logger = logging.getLogger(__name__)


@dataclass
class ProcessingState:
    """Represents the processing state for a data type."""

    data_type: str
    last_processed_at: datetime | None = None
    last_file_url: str | None = None
    last_file_checksum: str | None = None
    last_file_size: int | None = None
    total_records_processed: int = 0
    processing_status: str = "idle"
    error_message: str | None = None


@dataclass
class RecordChange:
    """Represents a change to a record."""

    data_type: str
    record_id: str
    change_type: str  # 'created', 'updated', 'deleted'
    old_hash: str | None = None
    new_hash: str | None = None
    changed_fields: dict[str, Any] = field(default_factory=dict)
    processing_run_id: UUID | None = None


class ProcessingStateTracker:
    """Tracks processing state for incremental updates."""

    def __init__(self, db_connection_string: str):
        """Initialize the tracker with a database connection."""
        self.db_connection_string = db_connection_string
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Ensure the database schema exists."""
        # Schema creation is handled by migrations
        pass

    def get_processing_state(self, data_type: str) -> ProcessingState | None:
        """Get the current processing state for a data type."""
        with (
            psycopg.connect(self.db_connection_string) as conn,
            conn.cursor(row_factory=dict_row) as cursor,
        ):
            cursor.execute(
                """
                    SELECT * FROM processing_state WHERE data_type = %s
                    """,
                (data_type,),
            )
            row = cursor.fetchone()
            if row:
                return ProcessingState(
                    data_type=row["data_type"],
                    last_processed_at=row["last_processed_at"],
                    last_file_url=row["last_file_url"],
                    last_file_checksum=row["last_file_checksum"],
                    last_file_size=row["last_file_size"],
                    total_records_processed=row["total_records_processed"],
                    processing_status=row["processing_status"],
                    error_message=row["error_message"],
                )
            return None

    def update_processing_state(self, state: ProcessingState) -> None:
        """Update the processing state for a data type."""
        with (
            psycopg.connect(self.db_connection_string) as conn,
            conn.cursor() as cursor,
        ):
            cursor.execute(
                """
                    INSERT INTO processing_state (
                        data_type, last_processed_at, last_file_url,
                        last_file_checksum, last_file_size, total_records_processed,
                        processing_status, error_message
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (data_type) DO UPDATE SET
                        last_processed_at = EXCLUDED.last_processed_at,
                        last_file_url = EXCLUDED.last_file_url,
                        last_file_checksum = EXCLUDED.last_file_checksum,
                        last_file_size = EXCLUDED.last_file_size,
                        total_records_processed = EXCLUDED.total_records_processed,
                        processing_status = EXCLUDED.processing_status,
                        error_message = EXCLUDED.error_message,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                (
                    state.data_type,
                    state.last_processed_at,
                    state.last_file_url,
                    state.last_file_checksum,
                    state.last_file_size,
                    state.total_records_processed,
                    state.processing_status,
                    state.error_message,
                ),
            )
            conn.commit()

    def start_processing_run(self, data_type: str, metadata: dict[str, Any] | None = None) -> UUID:
        """Start a new processing run and return its ID."""
        run_id = uuid4()
        with (
            psycopg.connect(self.db_connection_string) as conn,
            conn.cursor() as cursor,
        ):
            cursor.execute(
                """
                    INSERT INTO processing_runs (id, data_type, metadata)
                    VALUES (%s, %s, %s)
                    """,
                (str(run_id), data_type, orjson.dumps(metadata).decode() if metadata else None),
            )
            conn.commit()
        logger.info(f"🚀 Started processing run {run_id} for {data_type}")
        return run_id

    def complete_processing_run(
        self,
        run_id: UUID,
        records_processed: int,
        records_created: int,
        records_updated: int,
        records_deleted: int,
        error_message: str | None = None,
    ) -> None:
        """Complete a processing run."""
        status = "failed" if error_message else "completed"
        with (
            psycopg.connect(self.db_connection_string) as conn,
            conn.cursor() as cursor,
        ):
            cursor.execute(
                """
                    UPDATE processing_runs SET
                        completed_at = CURRENT_TIMESTAMP,
                        status = %s,
                        records_processed = %s,
                        records_created = %s,
                        records_updated = %s,
                        records_deleted = %s,
                        error_message = %s
                    WHERE id = %s
                    """,
                (
                    status,
                    records_processed,
                    records_created,
                    records_updated,
                    records_deleted,
                    error_message,
                    str(run_id),
                ),
            )
            conn.commit()
        logger.info(f"✅ Completed processing run {run_id} - Status: {status}")

    def get_record_hash(self, data_type: str, record_id: str) -> str | None:
        """Get the stored hash for a record."""
        with (
            psycopg.connect(self.db_connection_string) as conn,
            conn.cursor() as cursor,
        ):
            cursor.execute(
                """
                    SELECT record_hash FROM record_processing_state
                    WHERE data_type = %s AND record_id = %s
                    """,
                (data_type, record_id),
            )
            result = cursor.fetchone()
            return result[0] if result else None

    def update_record_state(
        self, data_type: str, record_id: str, record_hash: str, run_id: UUID
    ) -> RecordChange | None:
        """Update record state and return change if detected."""
        old_hash = self.get_record_hash(data_type, record_id)
        change_type = None
        change = None

        with (
            psycopg.connect(self.db_connection_string) as conn,
            conn.cursor() as cursor,
        ):
            if old_hash is None:
                # New record
                change_type = "created"
                cursor.execute(
                    """
                        INSERT INTO record_processing_state
                        (data_type, record_id, record_hash, last_modified_at)
                        VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                        """,
                    (data_type, record_id, record_hash),
                )
            elif old_hash != record_hash:
                # Updated record
                change_type = "updated"
                cursor.execute(
                    """
                        UPDATE record_processing_state SET
                            record_hash = %s,
                            last_seen_at = CURRENT_TIMESTAMP,
                            last_modified_at = CURRENT_TIMESTAMP,
                            processing_version = processing_version + 1
                        WHERE data_type = %s AND record_id = %s
                        """,
                    (record_hash, data_type, record_id),
                )
            else:
                # No change, just update last_seen_at
                cursor.execute(
                    """
                        UPDATE record_processing_state SET
                            last_seen_at = CURRENT_TIMESTAMP
                        WHERE data_type = %s AND record_id = %s
                        """,
                    (data_type, record_id),
                )

            # Record change if detected
            if change_type:
                change = RecordChange(
                    data_type=data_type,
                    record_id=record_id,
                    change_type=change_type,
                    old_hash=old_hash,
                    new_hash=record_hash,
                    processing_run_id=run_id,
                )
                cursor.execute(
                    """
                        INSERT INTO data_changelog
                        (data_type, record_id, change_type, old_hash, new_hash, processing_run_id)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                    (
                        data_type,
                        record_id,
                        change_type,
                        old_hash,
                        record_hash,
                        str(run_id),
                    ),
                )

            conn.commit()

        return change

    def detect_deleted_records(
        self, data_type: str, run_id: UUID, current_record_ids: set[str]
    ) -> int:
        """Detect and mark deleted records."""
        deleted_count = 0
        with (
            psycopg.connect(self.db_connection_string) as conn,
            conn.cursor() as cursor,
        ):
            # Find records not seen in current run
            cursor.execute(
                """
                    SELECT record_id, record_hash FROM record_processing_state
                    WHERE data_type = %s
                    AND record_id NOT IN %s
                    AND last_seen_at < (SELECT started_at FROM processing_runs WHERE id = %s)
                    """,
                (
                    data_type,
                    tuple(current_record_ids) if current_record_ids else ("",),
                    str(run_id),
                ),
            )

            deleted_records = cursor.fetchall()
            for record_id, record_hash in deleted_records:
                cursor.execute(
                    """
                        INSERT INTO data_changelog
                        (data_type, record_id, change_type, old_hash, processing_run_id)
                        VALUES (%s, %s, 'deleted', %s, %s)
                        """,
                    (data_type, record_id, record_hash, str(run_id)),
                )
                deleted_count += 1

            conn.commit()

        if deleted_count > 0:
            logger.info(f"🗑️ Detected {deleted_count} deleted {data_type} records")

        return deleted_count

    def get_unprocessed_changes(
        self, data_type: str | None = None, limit: int = 1000
    ) -> list[RecordChange]:
        """Get unprocessed changes from the changelog."""
        changes = []
        with (
            psycopg.connect(self.db_connection_string) as conn,
            conn.cursor(row_factory=dict_row) as cursor,
        ):
            query = """
                    SELECT * FROM data_changelog
                    WHERE processed = FALSE
                """
            params: list[Any] = []

            if data_type:
                query += " AND data_type = %s"
                params.append(data_type)

            query += " ORDER BY change_detected_at LIMIT %s"
            params.append(limit)

            cursor.execute(query, params)

            for row in cursor:
                changes.append(
                    RecordChange(
                        data_type=row["data_type"],
                        record_id=row["record_id"],
                        change_type=row["change_type"],
                        old_hash=row["old_hash"],
                        new_hash=row["new_hash"],
                        changed_fields=row["changed_fields"] or {},
                        processing_run_id=UUID(row["processing_run_id"])
                        if row["processing_run_id"]
                        else None,
                    )
                )
        return changes

    def mark_changes_processed(self, change_ids: list[int]) -> None:
        """Mark changes as processed."""
        if not change_ids:
            return

        with (
            psycopg.connect(self.db_connection_string) as conn,
            conn.cursor() as cursor,
        ):
            cursor.execute(
                """
                    UPDATE data_changelog SET
                        processed = TRUE,
                        processed_at = CURRENT_TIMESTAMP
                    WHERE id = ANY(%s)
                    """,
                (change_ids,),
            )
            conn.commit()

    def compute_record_hash(self, record_data: dict[str, Any]) -> str:
        """Compute a hash for a record."""
        # Sort keys for consistent hashing
        sorted_data = orjson.dumps(record_data, option=orjson.OPT_SORT_KEYS)
        return hashlib.sha256(sorted_data).hexdigest()
