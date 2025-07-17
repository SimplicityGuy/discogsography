"""Tests for incremental processing functionality."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from common.processing_state import ProcessingState, ProcessingStateTracker, RecordChange


class MockConnection:
    """Mock database connection for testing."""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.closed = False

    def __enter__(self) -> "MockConnection":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass

    def cursor(self, row_factory: Any = None) -> "MockCursor":
        return MockCursor(self.data, row_factory=row_factory)

    def commit(self) -> None:
        pass


class MockCursor:
    """Mock database cursor for testing."""

    def __init__(self, data: dict[str, Any], row_factory: Any = None) -> None:
        self.data = data
        self.row_factory = row_factory
        self.last_query: str | None = None
        self.last_params: tuple[Any, ...] | None = None
        self._results: list[Any] = []
        self._current = 0

    def __enter__(self) -> "MockCursor":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass

    def __iter__(self) -> "MockCursor":
        return self

    def __next__(self) -> Any:
        if self._current >= len(self._results):
            raise StopIteration
        result = self._results[self._current]
        self._current += 1
        return result

    def execute(self, query: str, params: tuple[Any, ...] | None = None) -> None:
        self.last_query = query
        self.last_params = params
        self._results = []  # Reset results
        self._current = 0

        # Handle data_changelog queries for get_unprocessed_changes
        if "data_changelog" in query and "SELECT" in query:
            self._results = []  # Empty list for our mock

    def fetchone(self) -> tuple[Any, ...] | dict[str, Any] | None:
        # Simulate different queries - order matters!
        if (
            self.last_query
            and "record_processing_state" in self.last_query
            and "record_hash" in self.last_query
            and "SELECT" in self.last_query
        ):
            # Return existing hash for record "123"
            if self.last_params and len(self.last_params) > 1 and self.last_params[1] == "123":
                # Return a tuple with just the hash value (since SELECT record_hash only selects the hash column)
                return ("old_hash_123",)
            # For other record IDs, return None (not found)
            return None
        elif (
            self.last_query
            and "processing_state" in self.last_query
            and "SELECT" in self.last_query
        ):
            if self.last_params and "artists" in self.last_params:
                # When row_factory is dict_row, return dict
                if self.row_factory:
                    return {
                        "data_type": "artists",
                        "last_processed_at": datetime.now(UTC),
                        "last_file_url": "s3://test/file.xml.gz",
                        "last_file_checksum": "abc123",
                        "last_file_size": 1000000,
                        "total_records_processed": 100,
                        "processing_status": "idle",
                        "error_message": None,
                    }
                else:
                    # Return tuple for regular cursor
                    return (
                        "artists",
                        datetime.now(UTC),
                        "s3://test/file.xml.gz",
                        "abc123",
                        1000000,
                        100,
                        "idle",
                        None,
                    )
        elif (
            self.last_query and "processing_runs" in self.last_query and "INSERT" in self.last_query
        ):
            # For insert queries, don't return anything
            return None
        elif self.last_query and (
            (
                "processing_state" in self.last_query
                and ("INSERT" in self.last_query or "UPDATE" in self.last_query)
            )
            or (
                "record_processing_state" in self.last_query
                and ("INSERT" in self.last_query or "UPDATE" in self.last_query)
            )
        ):
            # For insert/update queries, don't return anything
            return None
        elif (
            self.last_query and "data_changelog" in self.last_query and "INSERT" in self.last_query
        ):
            # For insert queries, don't return anything
            return None
        return None

    def fetchall(self) -> list[tuple[Any, ...]]:
        # For deleted records detection
        if (
            self.last_query
            and "record_processing_state" in self.last_query
            and "NOT IN" in self.last_query
        ):
            return [("456", "hash_456"), ("789", "hash_789")]
        return []


class TestProcessingStateTracker:
    """Test the ProcessingStateTracker class."""

    @pytest.fixture
    def mock_psycopg(self, monkeypatch: Any) -> None:
        """Mock psycopg connection."""

        def mock_connect(connection_string: str) -> MockConnection:  # noqa: ARG001
            return MockConnection()

        monkeypatch.setattr("psycopg.connect", mock_connect)

    @pytest.fixture
    def tracker(self, mock_psycopg: Any) -> ProcessingStateTracker:  # noqa: ARG002
        """Create a ProcessingStateTracker instance."""
        return ProcessingStateTracker("postgresql://test:test@localhost/test")

    def test_get_processing_state(self, tracker: ProcessingStateTracker) -> None:
        """Test retrieving processing state."""
        state = tracker.get_processing_state("artists")

        assert state is not None
        assert state.data_type == "artists"
        assert state.last_file_checksum == "abc123"
        assert state.total_records_processed == 100

    def test_get_processing_state_not_found(self, tracker: ProcessingStateTracker) -> None:
        """Test retrieving non-existent processing state."""
        state = tracker.get_processing_state("nonexistent")
        assert state is None

    def test_update_processing_state(self, tracker):
        """Test updating processing state."""
        state = ProcessingState(
            data_type="releases",
            last_processed_at=datetime.now(UTC),
            last_file_url="s3://test/releases.xml.gz",
            last_file_checksum="def456",
            last_file_size=2000000,
            total_records_processed=200,
            processing_status="processing",
        )

        # Should not raise any exceptions
        tracker.update_processing_state(state)

    def test_start_processing_run(self, tracker):
        """Test starting a processing run."""
        metadata = {"file": "test.xml.gz", "size": 1000000}
        run_id = tracker.start_processing_run("artists", metadata)

        assert isinstance(run_id, UUID)

    def test_complete_processing_run(self, tracker):
        """Test completing a processing run."""
        run_id = uuid4()

        # Should not raise any exceptions
        tracker.complete_processing_run(
            run_id,
            records_processed=1000,
            records_created=100,
            records_updated=50,
            records_deleted=10,
        )

    def test_get_record_hash(self, tracker):
        """Test getting existing record hash."""
        # Record "123" exists with hash "old_hash_123"
        hash_value = tracker.get_record_hash("artists", "123")
        assert hash_value == "old_hash_123"

        # Record "999" doesn't exist
        hash_value = tracker.get_record_hash("artists", "999")
        assert hash_value is None

    def test_update_record_state_created(self, tracker):
        """Test updating record state for a new record."""
        run_id = uuid4()

        # New record (no existing hash)
        change = tracker.update_record_state("artists", "999", "new_hash_999", run_id)

        assert change is not None
        assert change.change_type == "created"
        assert change.old_hash is None
        assert change.new_hash == "new_hash_999"

    def test_update_record_state_updated(self, tracker):
        """Test updating record state for an existing record."""
        run_id = uuid4()

        # Existing record "123" with different hash
        change = tracker.update_record_state("artists", "123", "new_hash_123", run_id)

        assert change is not None
        assert change.change_type == "updated"
        assert change.old_hash == "old_hash_123"
        assert change.new_hash == "new_hash_123"

    def test_update_record_state_unchanged(self, tracker):
        """Test updating record state for unchanged record."""
        run_id = uuid4()

        # Existing record "123" with same hash
        change = tracker.update_record_state("artists", "123", "old_hash_123", run_id)

        assert change is None  # No change detected

    def test_detect_deleted_records(self, tracker):
        """Test detecting deleted records."""
        run_id = uuid4()
        current_ids = {"123", "124", "125"}  # Records 456 and 789 are missing

        deleted_count = tracker.detect_deleted_records("artists", run_id, current_ids)

        assert deleted_count == 2  # Two records deleted

    def test_compute_record_hash(self, tracker):
        """Test computing record hash."""
        record_data = {
            "id": "123",
            "name": "Test Artist",
            "profile": "Test profile",
        }

        hash1 = tracker.compute_record_hash(record_data)
        hash2 = tracker.compute_record_hash(record_data)

        # Same data should produce same hash
        assert hash1 == hash2

        # Different data should produce different hash
        record_data["name"] = "Different Name"
        hash3 = tracker.compute_record_hash(record_data)
        assert hash1 != hash3

    def test_get_unprocessed_changes(self, tracker):
        """Test retrieving unprocessed changes."""
        changes = tracker.get_unprocessed_changes(limit=10)

        # With our mock, this returns empty list
        assert changes == []

    def test_mark_changes_processed(self, tracker):
        """Test marking changes as processed."""
        change_ids = [1, 2, 3]

        # Should not raise any exceptions
        tracker.mark_changes_processed(change_ids)

        # Empty list should also work
        tracker.mark_changes_processed([])


class TestProcessingState:
    """Test the ProcessingState dataclass."""

    def test_creation_with_defaults(self):
        """Test creating ProcessingState with default values."""
        state = ProcessingState(data_type="artists")

        assert state.data_type == "artists"
        assert state.last_processed_at is None
        assert state.last_file_url is None
        assert state.last_file_checksum is None
        assert state.last_file_size is None
        assert state.total_records_processed == 0
        assert state.processing_status == "idle"
        assert state.error_message is None

    def test_creation_with_values(self):
        """Test creating ProcessingState with all values."""
        now = datetime.now(UTC)
        state = ProcessingState(
            data_type="releases",
            last_processed_at=now,
            last_file_url="s3://test/file.xml.gz",
            last_file_checksum="abc123",
            last_file_size=1000000,
            total_records_processed=500,
            processing_status="processing",
            error_message="Test error",
        )

        assert state.data_type == "releases"
        assert state.last_processed_at == now
        assert state.last_file_url == "s3://test/file.xml.gz"
        assert state.last_file_checksum == "abc123"
        assert state.last_file_size == 1000000
        assert state.total_records_processed == 500
        assert state.processing_status == "processing"
        assert state.error_message == "Test error"


class TestRecordChange:
    """Test the RecordChange dataclass."""

    def test_creation(self):
        """Test creating RecordChange."""
        run_id = uuid4()
        change = RecordChange(
            data_type="artists",
            record_id="123",
            change_type="updated",
            old_hash="old_hash",
            new_hash="new_hash",
            changed_fields={"name": "New Name"},
            processing_run_id=run_id,
        )

        assert change.data_type == "artists"
        assert change.record_id == "123"
        assert change.change_type == "updated"
        assert change.old_hash == "old_hash"
        assert change.new_hash == "new_hash"
        assert change.changed_fields == {"name": "New Name"}
        assert change.processing_run_id == run_id
