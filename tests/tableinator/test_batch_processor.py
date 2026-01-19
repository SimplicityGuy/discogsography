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

        # Should log error and nack
        mock_logger.error.assert_called()
        nack.assert_called_once()

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
    async def test_flush_queue_nack_callback_error(self) -> None:
        """Test handling errors in nack callback."""
        # Setup connection pool that raises error when getting connection
        mock_connection_cm = AsyncMock()
        mock_connection_cm.__aenter__ = AsyncMock(side_effect=Exception("Connection failed"))
        mock_connection_cm.__aexit__ = AsyncMock(return_value=None)

        mock_connection_pool = MagicMock()
        mock_connection_pool.connection = MagicMock(return_value=mock_connection_cm)

        processor = PostgreSQLBatchProcessor(mock_connection_pool)

        # Add message with failing nack callback
        failing_nack = AsyncMock(side_effect=Exception("Nack failed"))
        processor.queues["artists"].append(
            PendingMessage(
                data_type="artists",
                data_id="1",
                data={"id": "1"},
                sha256="abc",
                ack_callback=AsyncMock(),
                nack_callback=failing_nack,
            )
        )

        with patch("tableinator.batch_processor.logger") as mock_logger:
            await processor._flush_queue("artists")

        # Should log warning about nack failure
        assert any("nack" in str(call).lower() for call in mock_logger.warning.call_args_list)

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

        # Mock _flush_queue
        processor._flush_queue = AsyncMock()  # type: ignore[method-assign]

        await processor.flush_all()

        # Should flush all data types
        assert processor._flush_queue.call_count == 4
        expected_calls = [
            call("artists"),
            call("labels"),
            call("masters"),
            call("releases"),
        ]
        processor._flush_queue.assert_has_calls(expected_calls, any_order=True)

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
