"""Tests for batch_processor module."""

import asyncio
import contextlib
import time
from unittest.mock import AsyncMock, MagicMock, call, patch

from psycopg.errors import InterfaceError, OperationalError
import pytest

from tableinator.batch_processor import (
    BatchConfig,
    PendingMessage,
    PostgreSQLBatchProcessor,
)


class TestBatchConfig:
    """Test BatchConfig dataclass."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = BatchConfig()

        assert config.batch_size == 100
        assert config.flush_interval == 5.0
        assert config.max_pending == 1000

    def test_custom_values(self) -> None:
        """Test custom configuration values."""
        config = BatchConfig(
            batch_size=50,
            flush_interval=2.5,
            max_pending=500,
        )

        assert config.batch_size == 50
        assert config.flush_interval == 2.5
        assert config.max_pending == 500


class TestPendingMessage:
    """Test PendingMessage dataclass."""

    def test_creation_with_default_timestamp(self) -> None:
        """Test message creation with default timestamp."""
        before = time.time()
        msg = PendingMessage(
            data_type="artists",
            data_id="123",
            data={"id": "123"},
            sha256="abc123",
            ack_callback=lambda: None,
            nack_callback=lambda: None,
        )
        after = time.time()

        assert msg.data_type == "artists"
        assert msg.data_id == "123"
        assert before <= msg.received_at <= after

    def test_creation_with_custom_timestamp(self) -> None:
        """Test message creation with custom timestamp."""
        custom_time = 1234567890.0
        msg = PendingMessage(
            data_type="artists",
            data_id="123",
            data={"id": "123"},
            sha256="abc123",
            ack_callback=lambda: None,
            nack_callback=lambda: None,
            received_at=custom_time,
        )

        assert msg.received_at == custom_time


class TestPostgreSQLBatchProcessor:
    """Test PostgreSQLBatchProcessor class."""

    def test_initialization_with_defaults(self) -> None:
        """Test processor initialization with default config."""
        mock_connection_pool = MagicMock()
        processor = PostgreSQLBatchProcessor(mock_connection_pool)

        assert processor.connection_pool == mock_connection_pool
        assert processor.config.batch_size == 100
        assert processor.config.flush_interval == 5.0
        assert len(processor.queues) == 4
        assert all(data_type in processor.queues for data_type in ["artists", "labels", "masters", "releases"])

    def test_initialization_with_custom_config(self) -> None:
        """Test processor initialization with custom config."""
        mock_connection_pool = MagicMock()
        config = BatchConfig(batch_size=50, flush_interval=2.5)
        processor = PostgreSQLBatchProcessor(mock_connection_pool, config)

        assert processor.config.batch_size == 50
        assert processor.config.flush_interval == 2.5

    def test_initialization_reads_env_batch_size(self) -> None:
        """Test that processor reads POSTGRES_BATCH_SIZE from environment."""
        mock_connection_pool = MagicMock()

        with patch.dict("os.environ", {"POSTGRES_BATCH_SIZE": "75"}):
            processor = PostgreSQLBatchProcessor(mock_connection_pool)

        assert processor.config.batch_size == 75

    def test_initialization_handles_invalid_env_batch_size(self) -> None:
        """Test handling of invalid POSTGRES_BATCH_SIZE."""
        mock_connection_pool = MagicMock()

        with (
            patch.dict("os.environ", {"POSTGRES_BATCH_SIZE": "invalid"}),
            patch("tableinator.batch_processor.logger") as mock_logger,
        ):
            processor = PostgreSQLBatchProcessor(mock_connection_pool)

        # Should use default and log warning
        assert processor.config.batch_size == 100
        mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_message_success(self) -> None:
        """Test adding a message to the queue."""
        mock_connection_pool = MagicMock()
        processor = PostgreSQLBatchProcessor(mock_connection_pool, BatchConfig(batch_size=10))

        ack_callback = AsyncMock()
        nack_callback = AsyncMock()

        data = {
            "id": "123",
            "name": "Test Artist",
            "sha256": "abc123",
        }

        with patch("tableinator.batch_processor.normalize_record", return_value=data) as mock_normalize:
            await processor.add_message(
                data_type="artists",
                data=data,
                ack_callback=ack_callback,
                nack_callback=nack_callback,
            )

        # Verify normalization was called
        mock_normalize.assert_called_once_with("artists", data)

        # Verify message was added to queue
        assert len(processor.queues["artists"]) == 1
        pending = processor.queues["artists"][0]
        assert pending.data_id == "123"
        assert pending.sha256 == "abc123"

    @pytest.mark.asyncio
    async def test_add_message_unknown_data_type(self) -> None:
        """Test adding message with unknown data type."""
        mock_connection_pool = MagicMock()
        processor = PostgreSQLBatchProcessor(mock_connection_pool)

        ack_callback = AsyncMock()
        nack_callback = AsyncMock()

        with patch("tableinator.batch_processor.logger") as mock_logger:
            await processor.add_message(
                data_type="unknown",
                data={"id": "123"},
                ack_callback=ack_callback,
                nack_callback=nack_callback,
            )

        # Should log error and nack
        mock_logger.error.assert_called_once()
        nack_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_message_missing_id(self) -> None:
        """Test adding message without id field."""
        mock_connection_pool = MagicMock()
        processor = PostgreSQLBatchProcessor(mock_connection_pool)

        ack_callback = AsyncMock()
        nack_callback = AsyncMock()

        with patch("tableinator.batch_processor.logger") as mock_logger:
            await processor.add_message(
                data_type="artists",
                data={"name": "Test Artist"},  # Missing 'id'
                ack_callback=ack_callback,
                nack_callback=nack_callback,
            )

        # Should log error and nack
        mock_logger.error.assert_called_once()
        nack_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_message_normalization_error(self) -> None:
        """Test handling of normalization errors."""
        mock_connection_pool = MagicMock()
        processor = PostgreSQLBatchProcessor(mock_connection_pool)

        ack_callback = AsyncMock()
        nack_callback = AsyncMock()

        data = {"id": "123", "name": "Test"}

        with (
            patch(
                "tableinator.batch_processor.normalize_record",
                side_effect=Exception("Normalization failed"),
            ),
            patch("tableinator.batch_processor.logger") as mock_logger,
        ):
            await processor.add_message(
                data_type="artists",
                data=data,
                ack_callback=ack_callback,
                nack_callback=nack_callback,
            )

        # Should log error and nack
        mock_logger.error.assert_called_once()
        nack_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_message_triggers_flush_on_batch_size(self) -> None:
        """Test that adding messages triggers flush at batch size."""
        mock_connection_pool = MagicMock()
        processor = PostgreSQLBatchProcessor(mock_connection_pool, BatchConfig(batch_size=2))

        # Mock _flush_queue
        processor._flush_queue = AsyncMock()  # type: ignore[method-assign]

        # Add first message
        with patch("tableinator.batch_processor.normalize_record", return_value={"id": "1"}):
            await processor.add_message(
                data_type="artists",
                data={"id": "1", "sha256": "abc"},
                ack_callback=AsyncMock(),
                nack_callback=AsyncMock(),
            )

        # Should not flush yet
        processor._flush_queue.assert_not_called()

        # Add second message
        with patch("tableinator.batch_processor.normalize_record", return_value={"id": "2"}):
            await processor.add_message(
                data_type="artists",
                data={"id": "2", "sha256": "def"},
                ack_callback=AsyncMock(),
                nack_callback=AsyncMock(),
            )

        # Should trigger flush
        processor._flush_queue.assert_called_once_with("artists")

    @pytest.mark.asyncio
    async def test_add_message_triggers_flush_on_time_interval(self) -> None:
        """Test that messages are flushed after time interval."""
        mock_connection_pool = MagicMock()
        processor = PostgreSQLBatchProcessor(mock_connection_pool, BatchConfig(batch_size=100, flush_interval=0.1))

        # Set last flush to past
        processor.last_flush["artists"] = time.time() - 1.0

        # Mock _flush_queue
        processor._flush_queue = AsyncMock()  # type: ignore[method-assign]

        # Add message
        with patch("tableinator.batch_processor.normalize_record", return_value={"id": "1"}):
            await processor.add_message(
                data_type="artists",
                data={"id": "1", "sha256": "abc"},
                ack_callback=AsyncMock(),
                nack_callback=AsyncMock(),
            )

        # Should trigger flush due to time interval
        processor._flush_queue.assert_called_once_with("artists")

    @pytest.mark.asyncio
    async def test_flush_queue_empty(self) -> None:
        """Test flushing an empty queue."""
        mock_connection_pool = MagicMock()
        processor = PostgreSQLBatchProcessor(mock_connection_pool)

        # Should complete without error
        await processor._flush_queue("artists")

        # Nothing should happen - connection pool should not be accessed
        mock_connection_pool.connection.assert_not_called()

    @pytest.mark.asyncio
    async def test_flush_queue_success(self) -> None:
        """Test successful queue flush."""
        mock_connection = MagicMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[("1", "abc")])  # ID 1 unchanged

        # Setup async cursor context manager
        mock_cursor_cm = AsyncMock()
        mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_cm.__aexit__ = AsyncMock(return_value=None)
        mock_connection.cursor = MagicMock(return_value=mock_cursor_cm)

        # Setup async connection context manager
        mock_connection_cm = AsyncMock()
        mock_connection_cm.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_connection_cm.__aexit__ = AsyncMock(return_value=None)

        mock_connection_pool = MagicMock()
        mock_connection_pool.connection = MagicMock(return_value=mock_connection_cm)

        processor = PostgreSQLBatchProcessor(mock_connection_pool)

        # Add messages to queue
        ack1 = AsyncMock()
        ack2 = AsyncMock()
        processor.queues["artists"].append(
            PendingMessage(
                data_type="artists",
                data_id="1",
                data={"id": "1"},
                sha256="abc",
                ack_callback=ack1,
                nack_callback=AsyncMock(),
            )
        )
        processor.queues["artists"].append(
            PendingMessage(
                data_type="artists",
                data_id="2",
                data={"id": "2"},
                sha256="def",
                ack_callback=ack2,
                nack_callback=AsyncMock(),
            )
        )

        with patch("tableinator.batch_processor.logger"):
            await processor._flush_queue("artists")

        # Verify both messages were acked
        ack1.assert_called_once()
        ack2.assert_called_once()

        # Verify stats were updated
        assert processor.processed_counts["artists"] == 2
        assert processor.batch_counts["artists"] == 1

    @pytest.mark.asyncio
    async def test_flush_queue_connection_error(self) -> None:
        """Test handling connection errors during flush."""
        # Setup connection pool that raises error when getting connection
        mock_connection_cm = AsyncMock()
        mock_connection_cm.__aenter__ = AsyncMock(side_effect=InterfaceError("Connection lost"))
        mock_connection_cm.__aexit__ = AsyncMock(return_value=None)

        mock_connection_pool = MagicMock()
        mock_connection_pool.connection = MagicMock(return_value=mock_connection_cm)

        processor = PostgreSQLBatchProcessor(mock_connection_pool)

        # Add messages to queue
        nack1 = AsyncMock()
        nack2 = AsyncMock()
        processor.queues["artists"].append(
            PendingMessage(
                data_type="artists",
                data_id="1",
                data={"id": "1"},
                sha256="abc",
                ack_callback=AsyncMock(),
                nack_callback=nack1,
            )
        )
        processor.queues["artists"].append(
            PendingMessage(
                data_type="artists",
                data_id="2",
                data={"id": "2"},
                sha256="def",
                ack_callback=AsyncMock(),
                nack_callback=nack2,
            )
        )

        with patch("tableinator.batch_processor.logger") as mock_logger:
            await processor._flush_queue("artists")

        # Should log error
        mock_logger.error.assert_called()

        # Messages should be back in queue for retry
        assert len(processor.queues["artists"]) == 2

    @pytest.mark.asyncio
    async def test_flush_queue_operational_error(self) -> None:
        """Test handling operational errors during flush."""
        # Setup connection that raises OperationalError on entry
        mock_connection_cm = AsyncMock()
        mock_connection_cm.__aenter__ = AsyncMock(side_effect=OperationalError("Database unavailable"))
        mock_connection_cm.__aexit__ = AsyncMock(return_value=None)

        mock_connection_pool = MagicMock()
        mock_connection_pool.connection = MagicMock(return_value=mock_connection_cm)

        processor = PostgreSQLBatchProcessor(mock_connection_pool)

        # Add message
        processor.queues["artists"].append(
            PendingMessage(
                data_type="artists",
                data_id="1",
                data={"id": "1"},
                sha256="abc",
                ack_callback=AsyncMock(),
                nack_callback=AsyncMock(),
            )
        )

        with patch("tableinator.batch_processor.logger") as mock_logger:
            await processor._flush_queue("artists")

        # Should log error
        mock_logger.error.assert_called()

        # Message should be back in queue
        assert len(processor.queues["artists"]) == 1

    @pytest.mark.asyncio
    async def test_flush_queue_general_exception(self) -> None:
        """Test handling general exceptions during flush."""
        mock_connection = MagicMock()
        mock_cursor = AsyncMock()
        mock_cursor.execute = AsyncMock(side_effect=Exception("Unexpected error"))

        # Setup async cursor context manager
        mock_cursor_cm = AsyncMock()
        mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_cm.__aexit__ = AsyncMock(return_value=None)
        mock_connection.cursor = MagicMock(return_value=mock_cursor_cm)

        # Setup async connection context manager
        mock_connection_cm = AsyncMock()
        mock_connection_cm.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_connection_cm.__aexit__ = AsyncMock(return_value=None)

        mock_connection_pool = MagicMock()
        mock_connection_pool.connection = MagicMock(return_value=mock_connection_cm)

        processor = PostgreSQLBatchProcessor(mock_connection_pool)

        # Add message
        nack = AsyncMock()
        processor.queues["artists"].append(
            PendingMessage(
                data_type="artists",
                data_id="1",
                data={"id": "1"},
                sha256="abc",
                ack_callback=AsyncMock(),
                nack_callback=nack,
            )
        )

        with patch("tableinator.batch_processor.logger") as mock_logger:
            await processor._flush_queue("artists")

        # Should log error and re-enqueue for local retry — not nack
        mock_logger.error.assert_called()
        nack.assert_not_called()
        assert len(processor.queues["artists"]) == 1

    @pytest.mark.asyncio
    async def test_flush_queue_ack_callback_error(self) -> None:
        """Test handling errors in ack callback."""
        mock_connection = MagicMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])

        # Setup async cursor context manager
        mock_cursor_cm = AsyncMock()
        mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_cm.__aexit__ = AsyncMock(return_value=None)
        mock_connection.cursor = MagicMock(return_value=mock_cursor_cm)

        # Setup async connection context manager
        mock_connection_cm = AsyncMock()
        mock_connection_cm.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_connection_cm.__aexit__ = AsyncMock(return_value=None)

        mock_connection_pool = MagicMock()
        mock_connection_pool.connection = MagicMock(return_value=mock_connection_cm)

        processor = PostgreSQLBatchProcessor(mock_connection_pool)

        # Add message with failing ack callback
        failing_ack = AsyncMock(side_effect=Exception("Ack failed"))
        processor.queues["artists"].append(
            PendingMessage(
                data_type="artists",
                data_id="1",
                data={"id": "1"},
                sha256="abc",
                ack_callback=failing_ack,
                nack_callback=AsyncMock(),
            )
        )

        with patch("tableinator.batch_processor.logger") as mock_logger:
            await processor._flush_queue("artists")

        # Should log warning about ack failure
        mock_logger.warning.assert_called()

        # Processing should still succeed
        assert processor.processed_counts["artists"] == 1

    @pytest.mark.asyncio
    async def test_flush_queue_general_error_requeues(self) -> None:
        """Test that general errors re-enqueue messages for local retry."""
        # Setup connection pool that raises error when getting connection
        mock_connection_cm = AsyncMock()
        mock_connection_cm.__aenter__ = AsyncMock(side_effect=Exception("Connection failed"))
        mock_connection_cm.__aexit__ = AsyncMock(return_value=None)

        mock_connection_pool = MagicMock()
        mock_connection_pool.connection = MagicMock(return_value=mock_connection_cm)

        processor = PostgreSQLBatchProcessor(mock_connection_pool)

        nack = AsyncMock()
        processor.queues["artists"].append(
            PendingMessage(
                data_type="artists",
                data_id="1",
                data={"id": "1"},
                sha256="abc",
                ack_callback=AsyncMock(),
                nack_callback=nack,
            )
        )

        with patch("tableinator.batch_processor.logger") as mock_logger:
            await processor._flush_queue("artists")

        # Messages re-enqueued for local retry — nack not called
        mock_logger.error.assert_called()
        nack.assert_not_called()
        assert len(processor.queues["artists"]) == 1

    @pytest.mark.asyncio
    async def test_process_batch_with_unchanged_records(self) -> None:
        """Test batch processing skips unchanged records."""
        mock_connection = MagicMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[("1", "abc"), ("2", "def")])

        # Setup async cursor context manager
        mock_cursor_cm = AsyncMock()
        mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_cm.__aexit__ = AsyncMock(return_value=None)
        mock_connection.cursor = MagicMock(return_value=mock_cursor_cm)

        # Setup async connection context manager
        mock_connection_cm = AsyncMock()
        mock_connection_cm.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_connection_cm.__aexit__ = AsyncMock(return_value=None)

        mock_connection_pool = MagicMock()
        mock_connection_pool.connection = MagicMock(return_value=mock_connection_cm)

        processor = PostgreSQLBatchProcessor(mock_connection_pool)

        messages = [
            PendingMessage(
                data_type="artists",
                data_id="1",
                data={"id": "1"},
                sha256="abc",
                ack_callback=AsyncMock(),
                nack_callback=AsyncMock(),
            ),
            PendingMessage(
                data_type="artists",
                data_id="2",
                data={"id": "2"},
                sha256="def",
                ack_callback=AsyncMock(),
                nack_callback=AsyncMock(),
            ),
        ]

        with patch("tableinator.batch_processor.logger") as mock_logger:
            await processor._process_batch("artists", messages)

        # Should log that records were skipped
        mock_logger.debug.assert_called()

        # executemany should not be called if all records unchanged
        assert mock_cursor.executemany.call_count == 0

    @pytest.mark.asyncio
    async def test_process_batch_with_mixed_records(self) -> None:
        """Test batch processing with mix of changed and unchanged records."""
        mock_connection = MagicMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[("1", "abc"), ("2", "def_old")])

        # Setup async cursor context manager
        mock_cursor_cm = AsyncMock()
        mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_cm.__aexit__ = AsyncMock(return_value=None)
        mock_connection.cursor = MagicMock(return_value=mock_cursor_cm)

        # Setup async connection context manager
        mock_connection_cm = AsyncMock()
        mock_connection_cm.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_connection_cm.__aexit__ = AsyncMock(return_value=None)

        mock_connection_pool = MagicMock()
        mock_connection_pool.connection = MagicMock(return_value=mock_connection_cm)

        processor = PostgreSQLBatchProcessor(mock_connection_pool)

        messages = [
            PendingMessage(
                data_type="artists",
                data_id="1",
                data={"id": "1"},
                sha256="abc",
                ack_callback=AsyncMock(),
                nack_callback=AsyncMock(),
            ),
            PendingMessage(
                data_type="artists",
                data_id="2",
                data={"id": "2"},
                sha256="def_new",  # Changed hash
                ack_callback=AsyncMock(),
                nack_callback=AsyncMock(),
            ),
        ]

        with patch("tableinator.batch_processor.logger"):
            await processor._process_batch("artists", messages)

        # executemany should be called with only the changed record
        assert mock_cursor.executemany.call_count == 1
        call_args = mock_cursor.executemany.call_args[0]
        assert len(call_args[1]) == 1  # Only one record to upsert

    @pytest.mark.asyncio
    async def test_flush_all(self) -> None:
        """Test flushing all queues."""
        mock_connection_pool = MagicMock()
        processor = PostgreSQLBatchProcessor(mock_connection_pool)

        # Mock flush_queue (flush_all delegates to flush_queue per data type)
        processor.flush_queue = AsyncMock()  # type: ignore[method-assign]

        await processor.flush_all()

        # Should flush all data types
        assert processor.flush_queue.call_count == 4
        expected_calls = [
            call("artists"),
            call("labels"),
            call("masters"),
            call("releases"),
        ]
        processor.flush_queue.assert_has_calls(expected_calls, any_order=True)

    @pytest.mark.asyncio
    async def test_periodic_flush(self) -> None:
        """Test periodic flush background task."""
        mock_connection_pool = MagicMock()
        processor = PostgreSQLBatchProcessor(mock_connection_pool, BatchConfig(flush_interval=0.1))

        # Set last flush to past for one queue
        processor.last_flush["artists"] = time.time() - 1.0

        # Add a message to that queue
        processor.queues["artists"].append(
            PendingMessage(
                data_type="artists",
                data_id="1",
                data={"id": "1"},
                sha256="abc",
                ack_callback=AsyncMock(),
                nack_callback=AsyncMock(),
            )
        )

        # Mock _flush_queue
        processor._flush_queue = AsyncMock()  # type: ignore[method-assign]

        # Start periodic flush task
        task = asyncio.create_task(processor.periodic_flush())

        # Wait for at least one flush cycle
        await asyncio.sleep(0.15)

        # Stop the task
        processor.shutdown()
        await asyncio.sleep(0.05)

        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        # Should have flushed at least once
        assert processor._flush_queue.call_count >= 1

    @pytest.mark.asyncio
    async def test_periodic_flush_respects_shutdown(self) -> None:
        """Test that periodic flush stops on shutdown."""
        mock_connection_pool = MagicMock()
        processor = PostgreSQLBatchProcessor(mock_connection_pool, BatchConfig(flush_interval=0.1))

        # Start periodic flush task
        task = asyncio.create_task(processor.periodic_flush())

        # Immediately shutdown
        processor.shutdown()
        await asyncio.sleep(0.05)

        # Task should complete quickly
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        assert processor._shutdown is True

    def test_shutdown(self) -> None:
        """Test shutdown flag is set."""
        mock_connection_pool = MagicMock()
        processor = PostgreSQLBatchProcessor(mock_connection_pool)

        assert processor._shutdown is False

        processor.shutdown()

        assert processor._shutdown is True

    def test_get_stats(self) -> None:
        """Test getting processing statistics."""
        mock_connection_pool = MagicMock()
        processor = PostgreSQLBatchProcessor(mock_connection_pool)

        # Set some stats
        processor.processed_counts["artists"] = 100
        processor.batch_counts["labels"] = 5

        # Add some pending messages
        processor.queues["artists"].append(
            PendingMessage(
                data_type="artists",
                data_id="1",
                data={"id": "1"},
                sha256="abc",
                ack_callback=AsyncMock(),
                nack_callback=AsyncMock(),
            )
        )

        stats = processor.get_stats()

        assert stats["processed"]["artists"] == 100
        assert stats["batches"]["labels"] == 5
        assert stats["pending"]["artists"] == 1
        assert stats["pending"]["labels"] == 0

    @pytest.mark.asyncio
    async def test_batch_respects_max_size(self) -> None:
        """Test that flush only processes up to batch_size messages."""
        mock_connection = MagicMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])

        # Setup async cursor context manager
        mock_cursor_cm = AsyncMock()
        mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_cm.__aexit__ = AsyncMock(return_value=None)
        mock_connection.cursor = MagicMock(return_value=mock_cursor_cm)

        # Setup async connection context manager
        mock_connection_cm = AsyncMock()
        mock_connection_cm.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_connection_cm.__aexit__ = AsyncMock(return_value=None)

        mock_connection_pool = MagicMock()
        mock_connection_pool.connection = MagicMock(return_value=mock_connection_cm)

        processor = PostgreSQLBatchProcessor(mock_connection_pool, BatchConfig(batch_size=2))

        # Add 4 messages to queue
        for i in range(4):
            processor.queues["artists"].append(
                PendingMessage(
                    data_type="artists",
                    data_id=str(i),
                    data={"id": str(i)},
                    sha256=f"hash{i}",
                    ack_callback=AsyncMock(),
                    nack_callback=AsyncMock(),
                )
            )

        with patch("tableinator.batch_processor.logger"):
            await processor._flush_queue("artists")

        # Should only process 2 messages (batch_size)
        assert len(processor.queues["artists"]) == 2

        # Should have processed 2
        assert processor.processed_counts["artists"] == 2


class TestBackoffPeriodSkip:
    """Test that _flush_queue returns early during backoff."""

    @pytest.mark.asyncio
    async def test_flush_queue_skips_during_backoff(self) -> None:
        """When backoff_until is in the future, _flush_queue should return without processing."""
        mock_connection_pool = MagicMock()
        processor = PostgreSQLBatchProcessor(mock_connection_pool)

        # Add a message to the queue
        processor.queues["artists"].append(
            PendingMessage(
                data_type="artists",
                data_id="1",
                data={"id": "1"},
                sha256="abc",
                ack_callback=AsyncMock(),
                nack_callback=AsyncMock(),
            )
        )

        # Set backoff to far in the future
        processor._backoff_until["artists"] = time.time() + 9999

        await processor._flush_queue("artists")

        # Message should still be in queue (not processed)
        assert len(processor.queues["artists"]) == 1
        # Connection pool should not have been touched
        mock_connection_pool.connection.assert_not_called()

    @pytest.mark.asyncio
    async def test_flush_queue_proceeds_after_backoff_expires(self) -> None:
        """When backoff_until is in the past, _flush_queue should process normally."""
        mock_connection = MagicMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])

        mock_cursor_cm = AsyncMock()
        mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_cm.__aexit__ = AsyncMock(return_value=None)
        mock_connection.cursor = MagicMock(return_value=mock_cursor_cm)

        mock_connection_cm = AsyncMock()
        mock_connection_cm.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_connection_cm.__aexit__ = AsyncMock(return_value=None)

        mock_connection_pool = MagicMock()
        mock_connection_pool.connection = MagicMock(return_value=mock_connection_cm)

        processor = PostgreSQLBatchProcessor(mock_connection_pool)

        processor.queues["artists"].append(
            PendingMessage(
                data_type="artists",
                data_id="1",
                data={"id": "1"},
                sha256="abc",
                ack_callback=AsyncMock(),
                nack_callback=AsyncMock(),
            )
        )

        # Set backoff to the past
        processor._backoff_until["artists"] = time.time() - 1

        with patch("tableinator.batch_processor.logger"):
            await processor._flush_queue("artists")

        # Message should have been processed
        assert len(processor.queues["artists"]) == 0
        assert processor.processed_counts["artists"] == 1


class TestInterfaceAndOperationalErrorHandling:
    """Test InterfaceError/OperationalError handling in _flush_queue."""

    @pytest.mark.asyncio
    async def test_messages_returned_to_queue_on_interface_error(self) -> None:
        """Messages should be put back in queue on InterfaceError."""
        mock_connection_cm = AsyncMock()
        mock_connection_cm.__aenter__ = AsyncMock(side_effect=InterfaceError("Connection lost"))
        mock_connection_cm.__aexit__ = AsyncMock(return_value=None)

        mock_connection_pool = MagicMock()
        mock_connection_pool.connection = MagicMock(return_value=mock_connection_cm)

        processor = PostgreSQLBatchProcessor(mock_connection_pool)

        processor.queues["artists"].append(
            PendingMessage(
                data_type="artists",
                data_id="1",
                data={"id": "1"},
                sha256="abc",
                ack_callback=AsyncMock(),
                nack_callback=AsyncMock(),
            )
        )

        with patch("tableinator.batch_processor.logger"):
            await processor._flush_queue("artists")

        assert len(processor.queues["artists"]) == 1

    @pytest.mark.asyncio
    async def test_consecutive_failures_increments_on_operational_error(self) -> None:
        """_consecutive_failures should increment on OperationalError."""
        mock_connection_cm = AsyncMock()
        mock_connection_cm.__aenter__ = AsyncMock(side_effect=OperationalError("DB down"))
        mock_connection_cm.__aexit__ = AsyncMock(return_value=None)

        mock_connection_pool = MagicMock()
        mock_connection_pool.connection = MagicMock(return_value=mock_connection_cm)

        processor = PostgreSQLBatchProcessor(mock_connection_pool)
        assert processor._consecutive_failures["artists"] == 0

        processor.queues["artists"].append(
            PendingMessage(
                data_type="artists",
                data_id="1",
                data={"id": "1"},
                sha256="abc",
                ack_callback=AsyncMock(),
                nack_callback=AsyncMock(),
            )
        )

        with patch("tableinator.batch_processor.logger"):
            await processor._flush_queue("artists")

        assert processor._consecutive_failures["artists"] == 1

    @pytest.mark.asyncio
    async def test_backoff_until_set_on_interface_error(self) -> None:
        """_backoff_until should be set to a future time on InterfaceError."""
        mock_connection_cm = AsyncMock()
        mock_connection_cm.__aenter__ = AsyncMock(side_effect=InterfaceError("Connection lost"))
        mock_connection_cm.__aexit__ = AsyncMock(return_value=None)

        mock_connection_pool = MagicMock()
        mock_connection_pool.connection = MagicMock(return_value=mock_connection_cm)

        processor = PostgreSQLBatchProcessor(mock_connection_pool)
        assert processor._backoff_until["artists"] == 0.0

        processor.queues["artists"].append(
            PendingMessage(
                data_type="artists",
                data_id="1",
                data={"id": "1"},
                sha256="abc",
                ack_callback=AsyncMock(),
                nack_callback=AsyncMock(),
            )
        )

        before = time.time()
        with patch("tableinator.batch_processor.logger"):
            await processor._flush_queue("artists")

        assert processor._backoff_until["artists"] > before

    @pytest.mark.asyncio
    async def test_effective_batch_size_halves_on_error(self) -> None:
        """_effective_batch_size should halve on InterfaceError."""
        mock_connection_cm = AsyncMock()
        mock_connection_cm.__aenter__ = AsyncMock(side_effect=InterfaceError("Connection lost"))
        mock_connection_cm.__aexit__ = AsyncMock(return_value=None)

        mock_connection_pool = MagicMock()
        mock_connection_pool.connection = MagicMock(return_value=mock_connection_cm)

        config = BatchConfig(batch_size=100, min_batch_size=10)
        processor = PostgreSQLBatchProcessor(mock_connection_pool, config)
        assert processor._effective_batch_size["artists"] == 100

        processor.queues["artists"].append(
            PendingMessage(
                data_type="artists",
                data_id="1",
                data={"id": "1"},
                sha256="abc",
                ack_callback=AsyncMock(),
                nack_callback=AsyncMock(),
            )
        )

        with patch("tableinator.batch_processor.logger"):
            await processor._flush_queue("artists")

        assert processor._effective_batch_size["artists"] == 50

    @pytest.mark.asyncio
    async def test_effective_batch_size_floors_at_min(self) -> None:
        """_effective_batch_size should not go below min_batch_size."""
        mock_connection_cm = AsyncMock()
        mock_connection_cm.__aenter__ = AsyncMock(side_effect=InterfaceError("Connection lost"))
        mock_connection_cm.__aexit__ = AsyncMock(return_value=None)

        mock_connection_pool = MagicMock()
        mock_connection_pool.connection = MagicMock(return_value=mock_connection_cm)

        config = BatchConfig(batch_size=100, min_batch_size=10)
        processor = PostgreSQLBatchProcessor(mock_connection_pool, config)

        # Set effective batch size to min already
        processor._effective_batch_size["artists"] = 10

        processor.queues["artists"].append(
            PendingMessage(
                data_type="artists",
                data_id="1",
                data={"id": "1"},
                sha256="abc",
                ack_callback=AsyncMock(),
                nack_callback=AsyncMock(),
            )
        )

        with patch("tableinator.batch_processor.logger") as mock_logger:
            await processor._flush_queue("artists")

        # Should stay at min
        assert processor._effective_batch_size["artists"] == 10

        # Should log "Backing off" instead of "Reduced batch size"
        warning_calls = [str(c) for c in mock_logger.warning.call_args_list]
        assert any("Backing off" in c for c in warning_calls)
        assert not any("Reduced batch size" in c for c in warning_calls)


class TestGeneralExceptionBackoff:
    """Test non-transient error backoff in _flush_queue."""

    @pytest.mark.asyncio
    async def test_general_exception_increments_failures(self) -> None:
        """Non-transient errors should increment _consecutive_failures."""
        mock_connection = MagicMock()
        mock_cursor = AsyncMock()
        mock_cursor.execute = AsyncMock(side_effect=Exception("Unexpected"))

        mock_cursor_cm = AsyncMock()
        mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_cm.__aexit__ = AsyncMock(return_value=None)
        mock_connection.cursor = MagicMock(return_value=mock_cursor_cm)

        mock_connection_cm = AsyncMock()
        mock_connection_cm.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_connection_cm.__aexit__ = AsyncMock(return_value=None)

        mock_connection_pool = MagicMock()
        mock_connection_pool.connection = MagicMock(return_value=mock_connection_cm)

        processor = PostgreSQLBatchProcessor(mock_connection_pool)

        processor.queues["artists"].append(
            PendingMessage(
                data_type="artists",
                data_id="1",
                data={"id": "1"},
                sha256="abc",
                ack_callback=AsyncMock(),
                nack_callback=AsyncMock(),
            )
        )

        with patch("tableinator.batch_processor.logger"):
            await processor._flush_queue("artists")

        assert processor._consecutive_failures["artists"] == 1

    @pytest.mark.asyncio
    async def test_general_exception_sets_backoff(self) -> None:
        """Non-transient errors should set _backoff_until to a future time."""
        mock_connection = MagicMock()
        mock_cursor = AsyncMock()
        mock_cursor.execute = AsyncMock(side_effect=Exception("Unexpected"))

        mock_cursor_cm = AsyncMock()
        mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_cm.__aexit__ = AsyncMock(return_value=None)
        mock_connection.cursor = MagicMock(return_value=mock_cursor_cm)

        mock_connection_cm = AsyncMock()
        mock_connection_cm.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_connection_cm.__aexit__ = AsyncMock(return_value=None)

        mock_connection_pool = MagicMock()
        mock_connection_pool.connection = MagicMock(return_value=mock_connection_cm)

        processor = PostgreSQLBatchProcessor(mock_connection_pool)

        processor.queues["artists"].append(
            PendingMessage(
                data_type="artists",
                data_id="1",
                data={"id": "1"},
                sha256="abc",
                ack_callback=AsyncMock(),
                nack_callback=AsyncMock(),
            )
        )

        before = time.time()
        with patch("tableinator.batch_processor.logger"):
            await processor._flush_queue("artists")

        assert processor._backoff_until["artists"] > before

    @pytest.mark.asyncio
    async def test_general_exception_nacks_messages(self) -> None:
        """Non-transient errors should re-enqueue messages for local retry."""
        mock_connection = MagicMock()
        mock_cursor = AsyncMock()
        mock_cursor.execute = AsyncMock(side_effect=Exception("Unexpected"))

        mock_cursor_cm = AsyncMock()
        mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_cm.__aexit__ = AsyncMock(return_value=None)
        mock_connection.cursor = MagicMock(return_value=mock_cursor_cm)

        mock_connection_cm = AsyncMock()
        mock_connection_cm.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_connection_cm.__aexit__ = AsyncMock(return_value=None)

        mock_connection_pool = MagicMock()
        mock_connection_pool.connection = MagicMock(return_value=mock_connection_cm)

        processor = PostgreSQLBatchProcessor(mock_connection_pool)

        nack = AsyncMock()
        processor.queues["artists"].append(
            PendingMessage(
                data_type="artists",
                data_id="1",
                data={"id": "1"},
                sha256="abc",
                ack_callback=AsyncMock(),
                nack_callback=nack,
            )
        )

        with patch("tableinator.batch_processor.logger"):
            await processor._flush_queue("artists")

        # Messages re-enqueued for local retry — nack not called
        nack.assert_not_called()
        assert len(processor.queues["artists"]) == 1


class TestSuccessRecovery:
    """Test adaptive batch size recovery after failures."""

    @pytest.mark.asyncio
    async def test_consecutive_failures_resets_on_success(self) -> None:
        """After a successful flush, _consecutive_failures should reset to 0."""
        mock_connection = MagicMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])

        mock_cursor_cm = AsyncMock()
        mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_cm.__aexit__ = AsyncMock(return_value=None)
        mock_connection.cursor = MagicMock(return_value=mock_cursor_cm)

        mock_connection_cm = AsyncMock()
        mock_connection_cm.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_connection_cm.__aexit__ = AsyncMock(return_value=None)

        mock_connection_pool = MagicMock()
        mock_connection_pool.connection = MagicMock(return_value=mock_connection_cm)

        config = BatchConfig(batch_size=100, min_batch_size=10)
        processor = PostgreSQLBatchProcessor(mock_connection_pool, config)

        # Simulate prior failures
        processor._consecutive_failures["artists"] = 3
        processor._effective_batch_size["artists"] = 25

        processor.queues["artists"].append(
            PendingMessage(
                data_type="artists",
                data_id="1",
                data={"id": "1"},
                sha256="abc",
                ack_callback=AsyncMock(),
                nack_callback=AsyncMock(),
            )
        )

        with patch("tableinator.batch_processor.logger"):
            await processor._flush_queue("artists")

        assert processor._consecutive_failures["artists"] == 0

    @pytest.mark.asyncio
    async def test_effective_batch_size_increases_on_success(self) -> None:
        """After success, _effective_batch_size should gradually increase toward configured size."""
        mock_connection = MagicMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])

        mock_cursor_cm = AsyncMock()
        mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_cm.__aexit__ = AsyncMock(return_value=None)
        mock_connection.cursor = MagicMock(return_value=mock_cursor_cm)

        mock_connection_cm = AsyncMock()
        mock_connection_cm.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_connection_cm.__aexit__ = AsyncMock(return_value=None)

        mock_connection_pool = MagicMock()
        mock_connection_pool.connection = MagicMock(return_value=mock_connection_cm)

        config = BatchConfig(batch_size=100, min_batch_size=10)
        processor = PostgreSQLBatchProcessor(mock_connection_pool, config)

        # Simulate reduced batch size from prior failure
        processor._effective_batch_size["artists"] = 25

        processor.queues["artists"].append(
            PendingMessage(
                data_type="artists",
                data_id="1",
                data={"id": "1"},
                sha256="abc",
                ack_callback=AsyncMock(),
                nack_callback=AsyncMock(),
            )
        )

        with patch("tableinator.batch_processor.logger") as mock_logger:
            await processor._flush_queue("artists")

        # Should increase: min(100, 25 + max(10, 100 // 10)) = min(100, 35) = 35
        assert processor._effective_batch_size["artists"] == 35

        # Should log the increase
        info_calls = [str(c) for c in mock_logger.info.call_args_list]
        assert any("Increased batch size" in c for c in info_calls)

    @pytest.mark.asyncio
    async def test_effective_batch_size_caps_at_configured(self) -> None:
        """_effective_batch_size should not exceed the configured batch_size."""
        mock_connection = MagicMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])

        mock_cursor_cm = AsyncMock()
        mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_cm.__aexit__ = AsyncMock(return_value=None)
        mock_connection.cursor = MagicMock(return_value=mock_cursor_cm)

        mock_connection_cm = AsyncMock()
        mock_connection_cm.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_connection_cm.__aexit__ = AsyncMock(return_value=None)

        mock_connection_pool = MagicMock()
        mock_connection_pool.connection = MagicMock(return_value=mock_connection_cm)

        config = BatchConfig(batch_size=100, min_batch_size=10)
        processor = PostgreSQLBatchProcessor(mock_connection_pool, config)

        # Set effective close to max
        processor._effective_batch_size["artists"] = 95

        processor.queues["artists"].append(
            PendingMessage(
                data_type="artists",
                data_id="1",
                data={"id": "1"},
                sha256="abc",
                ack_callback=AsyncMock(),
                nack_callback=AsyncMock(),
            )
        )

        with patch("tableinator.batch_processor.logger"):
            await processor._flush_queue("artists")

        # min(100, 95 + 10) = 100
        assert processor._effective_batch_size["artists"] == 100


class TestFlushQueuePublicMethod:
    """Test the public flush_queue method that drains completely."""

    @pytest.mark.asyncio
    async def test_flush_queue_drains_completely(self) -> None:
        """flush_queue should call _flush_queue repeatedly until queue is empty."""
        mock_connection_pool = MagicMock()
        processor = PostgreSQLBatchProcessor(mock_connection_pool, BatchConfig(batch_size=1))

        # Add 3 messages
        for i in range(3):
            processor.queues["artists"].append(
                PendingMessage(
                    data_type="artists",
                    data_id=str(i),
                    data={"id": str(i)},
                    sha256=f"hash{i}",
                    ack_callback=AsyncMock(),
                    nack_callback=AsyncMock(),
                )
            )

        call_count = 0
        original_queue = processor.queues["artists"]

        async def mock_flush(_data_type: str) -> None:
            nonlocal call_count
            call_count += 1
            # Simulate processing one message per call
            if original_queue:
                original_queue.popleft()

        processor._flush_queue = AsyncMock(side_effect=mock_flush)  # type: ignore[method-assign]

        await processor.flush_queue("artists")

        assert call_count == 3
        assert len(processor.queues["artists"]) == 0

    @pytest.mark.asyncio
    async def test_flush_queue_waits_during_backoff(self) -> None:
        """flush_queue should sleep during backoff periods."""
        mock_connection_pool = MagicMock()
        processor = PostgreSQLBatchProcessor(mock_connection_pool, BatchConfig(batch_size=1))

        processor.queues["artists"].append(
            PendingMessage(
                data_type="artists",
                data_id="1",
                data={"id": "1"},
                sha256="abc",
                ack_callback=AsyncMock(),
                nack_callback=AsyncMock(),
            )
        )

        # Set a small backoff
        processor._backoff_until["artists"] = time.time() + 0.05

        async def mock_flush(_data_type: str) -> None:
            # Clear queue and backoff on call
            processor.queues["artists"].clear()
            processor._backoff_until["artists"] = 0.0

        processor._flush_queue = AsyncMock(side_effect=mock_flush)  # type: ignore[method-assign]

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await processor.flush_queue("artists")

            # Should have called asyncio.sleep with a positive wait time
            mock_sleep.assert_called_once()
            wait_arg = mock_sleep.call_args[0][0]
            assert wait_arg > 0
