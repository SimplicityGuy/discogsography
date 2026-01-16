"""Tests for batch_processor module."""

import asyncio
import contextlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from graphinator.batch_processor import (
    BatchConfig,
    Neo4jBatchProcessor,
    PendingMessage,
)


class TestBatchConfig:
    """Test BatchConfig dataclass."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        config = BatchConfig()
        assert config.batch_size == 100
        assert config.flush_interval == 5.0
        assert config.max_pending == 1000

    def test_custom_config(self) -> None:
        """Test custom configuration values."""
        config = BatchConfig(batch_size=50, flush_interval=10.0, max_pending=500)
        assert config.batch_size == 50
        assert config.flush_interval == 10.0
        assert config.max_pending == 500


class TestPendingMessage:
    """Test PendingMessage dataclass."""

    def test_pending_message_creation(self) -> None:
        """Test creating a pending message."""
        ack_callback = MagicMock()
        nack_callback = MagicMock()
        data = {"id": "123", "name": "Test"}

        msg = PendingMessage(data_type="artists", data=data, ack_callback=ack_callback, nack_callback=nack_callback)

        assert msg.data_type == "artists"
        assert msg.data == data
        assert msg.ack_callback == ack_callback
        assert msg.nack_callback == nack_callback
        assert msg.received_at > 0


class TestNeo4jBatchProcessorInit:
    """Test Neo4jBatchProcessor initialization."""

    def test_initialization_with_defaults(self) -> None:
        """Test batch processor with default config."""
        mock_driver = MagicMock()
        processor = Neo4jBatchProcessor(mock_driver)

        assert processor.driver == mock_driver
        assert processor.config.batch_size == 100
        assert processor.config.flush_interval == 5.0
        assert len(processor.queues) == 4
        assert "artists" in processor.queues
        assert "labels" in processor.queues
        assert "masters" in processor.queues
        assert "releases" in processor.queues

    def test_initialization_with_custom_config(self) -> None:
        """Test batch processor with custom config."""
        mock_driver = MagicMock()
        config = BatchConfig(batch_size=50, flush_interval=2.0)
        processor = Neo4jBatchProcessor(mock_driver, config)

        assert processor.config.batch_size == 50
        assert processor.config.flush_interval == 2.0

    def test_initialization_with_env_batch_size(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test batch processor reads batch size from environment."""
        monkeypatch.setenv("NEO4J_BATCH_SIZE", "200")
        mock_driver = MagicMock()

        processor = Neo4jBatchProcessor(mock_driver)

        assert processor.config.batch_size == 200

    def test_initialization_with_invalid_env_batch_size(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test batch processor handles invalid env batch size."""
        monkeypatch.setenv("NEO4J_BATCH_SIZE", "invalid")
        mock_driver = MagicMock()

        processor = Neo4jBatchProcessor(mock_driver)

        # Should use default
        assert processor.config.batch_size == 100


class TestAddMessage:
    """Test add_message functionality."""

    @pytest.mark.asyncio
    async def test_add_message_to_queue(self) -> None:
        """Test adding a message to queue."""
        mock_driver = MagicMock()
        config = BatchConfig(batch_size=10)
        processor = Neo4jBatchProcessor(mock_driver, config)

        ack_callback = AsyncMock()
        nack_callback = AsyncMock()
        data = {"id": "123", "name": "Test Artist", "sha256": "hash123"}

        with patch("graphinator.batch_processor.normalize_record", return_value=data):
            await processor.add_message("artists", data, ack_callback, nack_callback)

        assert len(processor.queues["artists"]) == 1

    @pytest.mark.asyncio
    async def test_add_message_unknown_data_type(self) -> None:
        """Test adding message with unknown data type."""
        mock_driver = MagicMock()
        processor = Neo4jBatchProcessor(mock_driver)

        ack_callback = AsyncMock()
        nack_callback = AsyncMock()
        data = {"id": "123"}

        await processor.add_message("unknown", data, ack_callback, nack_callback)

        # Should nack the message
        nack_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_message_normalization_error(self) -> None:
        """Test handling normalization errors."""
        mock_driver = MagicMock()
        processor = Neo4jBatchProcessor(mock_driver)

        ack_callback = AsyncMock()
        nack_callback = AsyncMock()
        data = {"id": "123"}

        with patch("graphinator.batch_processor.normalize_record", side_effect=ValueError("Invalid data")):
            await processor.add_message("artists", data, ack_callback, nack_callback)

        # Should nack the message
        nack_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_message_triggers_flush_on_batch_size(self) -> None:
        """Test that adding messages triggers flush when batch size reached."""
        mock_driver = MagicMock()
        config = BatchConfig(batch_size=2)
        processor = Neo4jBatchProcessor(mock_driver, config)

        # Mock the flush method
        processor._flush_queue = AsyncMock()  # type: ignore[method-assign]

        ack_callback = AsyncMock()
        nack_callback = AsyncMock()
        data = {"id": "123", "name": "Test", "sha256": "hash"}

        with patch("graphinator.batch_processor.normalize_record", return_value=data):
            # Add first message - shouldn't flush
            await processor.add_message("artists", data, ack_callback, nack_callback)
            assert processor._flush_queue.call_count == 0

            # Add second message - should flush
            await processor.add_message("artists", data, ack_callback, nack_callback)
            processor._flush_queue.assert_called_once_with("artists")

    @pytest.mark.asyncio
    async def test_add_message_triggers_flush_on_interval(self) -> None:
        """Test that messages trigger flush after interval."""
        mock_driver = MagicMock()
        config = BatchConfig(batch_size=100, flush_interval=0.1)
        processor = Neo4jBatchProcessor(mock_driver, config)

        # Mock the flush method
        processor._flush_queue = AsyncMock()  # type: ignore[method-assign]

        # Set last flush time to past
        processor.last_flush["artists"] = 0.0

        ack_callback = AsyncMock()
        nack_callback = AsyncMock()
        data = {"id": "123", "name": "Test", "sha256": "hash"}

        with patch("graphinator.batch_processor.normalize_record", return_value=data):
            await processor.add_message("artists", data, ack_callback, nack_callback)

        # Should trigger flush due to interval
        processor._flush_queue.assert_called_once_with("artists")


class TestFlushQueue:
    """Test _flush_queue functionality."""

    @pytest.mark.asyncio
    async def test_flush_empty_queue(self) -> None:
        """Test flushing an empty queue."""
        mock_driver = MagicMock()
        processor = Neo4jBatchProcessor(mock_driver)

        # Should return early without error
        await processor._flush_queue("artists")

    @pytest.mark.asyncio
    async def test_flush_artists_batch_success(self) -> None:
        """Test successfully flushing artists batch."""
        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_driver.session.return_value.__enter__.return_value = mock_session

        processor = Neo4jBatchProcessor(mock_driver)

        # Add messages to queue
        ack1 = AsyncMock()
        ack2 = AsyncMock()
        nack1 = AsyncMock()
        nack2 = AsyncMock()

        msg1 = PendingMessage("artists", {"id": "1", "name": "Artist 1", "sha256": "hash1"}, ack1, nack1)
        msg2 = PendingMessage("artists", {"id": "2", "name": "Artist 2", "sha256": "hash2"}, ack2, nack2)

        processor.queues["artists"].append(msg1)
        processor.queues["artists"].append(msg2)

        await processor._flush_queue("artists")

        # Should acknowledge both messages
        ack1.assert_called_once()
        ack2.assert_called_once()

        # Should have updated stats
        assert processor.processed_counts["artists"] == 2
        assert processor.batch_counts["artists"] == 1

    @pytest.mark.asyncio
    async def test_flush_labels_batch_success(self) -> None:
        """Test successfully flushing labels batch."""
        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_driver.session.return_value.__enter__.return_value = mock_session

        processor = Neo4jBatchProcessor(mock_driver)

        ack = AsyncMock()
        nack = AsyncMock()
        msg = PendingMessage("labels", {"id": "1", "name": "Label 1", "sha256": "hash1"}, ack, nack)
        processor.queues["labels"].append(msg)

        await processor._flush_queue("labels")

        ack.assert_called_once()
        assert processor.processed_counts["labels"] == 1

    @pytest.mark.asyncio
    async def test_flush_masters_batch_success(self) -> None:
        """Test successfully flushing masters batch."""
        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_driver.session.return_value.__enter__.return_value = mock_session

        processor = Neo4jBatchProcessor(mock_driver)

        ack = AsyncMock()
        nack = AsyncMock()
        msg = PendingMessage("masters", {"id": "1", "title": "Master 1", "year": 2023, "sha256": "hash1"}, ack, nack)
        processor.queues["masters"].append(msg)

        await processor._flush_queue("masters")

        ack.assert_called_once()
        assert processor.processed_counts["masters"] == 1

    @pytest.mark.asyncio
    async def test_flush_releases_batch_success(self) -> None:
        """Test successfully flushing releases batch."""
        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_driver.session.return_value.__enter__.return_value = mock_session

        processor = Neo4jBatchProcessor(mock_driver)

        ack = AsyncMock()
        nack = AsyncMock()
        msg = PendingMessage("releases", {"id": "1", "title": "Release 1", "sha256": "hash1"}, ack, nack)
        processor.queues["releases"].append(msg)

        await processor._flush_queue("releases")

        ack.assert_called_once()
        assert processor.processed_counts["releases"] == 1

    @pytest.mark.asyncio
    async def test_flush_handles_neo4j_unavailable(self) -> None:
        """Test handling Neo4j unavailable during flush."""
        from neo4j.exceptions import ServiceUnavailable

        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_session.execute_write.side_effect = ServiceUnavailable("Neo4j down")
        mock_driver.session.return_value.__enter__.return_value = mock_session

        processor = Neo4jBatchProcessor(mock_driver)

        ack = AsyncMock()
        nack = AsyncMock()
        msg = PendingMessage("artists", {"id": "1", "name": "Artist 1", "sha256": "hash1"}, ack, nack)
        processor.queues["artists"].append(msg)

        await processor._flush_queue("artists")

        # Message should be back in queue for retry
        assert len(processor.queues["artists"]) == 1
        # Should not have acknowledged
        ack.assert_not_called()

    @pytest.mark.asyncio
    async def test_flush_handles_general_error(self) -> None:
        """Test handling general errors during flush."""
        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_session.execute_write.side_effect = RuntimeError("Database error")
        mock_driver.session.return_value.__enter__.return_value = mock_session

        processor = Neo4jBatchProcessor(mock_driver)

        ack = AsyncMock()
        nack = AsyncMock()
        msg = PendingMessage("artists", {"id": "1", "name": "Artist 1", "sha256": "hash1"}, ack, nack)
        processor.queues["artists"].append(msg)

        await processor._flush_queue("artists")

        # Should nack the message
        nack.assert_called_once()

    @pytest.mark.asyncio
    async def test_flush_handles_ack_failure(self) -> None:
        """Test handling ack callback failures."""
        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_driver.session.return_value.__enter__.return_value = mock_session

        processor = Neo4jBatchProcessor(mock_driver)

        ack = AsyncMock(side_effect=Exception("Ack failed"))
        nack = AsyncMock()
        msg = PendingMessage("artists", {"id": "1", "name": "Artist 1", "sha256": "hash1"}, ack, nack)
        processor.queues["artists"].append(msg)

        # Should not raise exception
        await processor._flush_queue("artists")

    @pytest.mark.asyncio
    async def test_flush_handles_nack_failure(self) -> None:
        """Test handling nack callback failures."""
        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_session.execute_write.side_effect = RuntimeError("Error")
        mock_driver.session.return_value.__enter__.return_value = mock_session

        processor = Neo4jBatchProcessor(mock_driver)

        ack = AsyncMock()
        nack = AsyncMock(side_effect=Exception("Nack failed"))
        msg = PendingMessage("artists", {"id": "1", "name": "Artist 1", "sha256": "hash1"}, ack, nack)
        processor.queues["artists"].append(msg)

        # Should not raise exception
        await processor._flush_queue("artists")

    @pytest.mark.asyncio
    async def test_flush_respects_batch_size_limit(self) -> None:
        """Test that flush respects batch size limit."""
        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_driver.session.return_value.__enter__.return_value = mock_session

        config = BatchConfig(batch_size=2)
        processor = Neo4jBatchProcessor(mock_driver, config)

        # Add 5 messages
        for i in range(5):
            msg = PendingMessage("artists", {"id": str(i), "name": f"Artist {i}", "sha256": f"hash{i}"}, AsyncMock(), AsyncMock())
            processor.queues["artists"].append(msg)

        await processor._flush_queue("artists")

        # Should only process 2 messages (batch_size limit)
        assert len(processor.queues["artists"]) == 3
        assert processor.processed_counts["artists"] == 2


class TestProcessArtistsBatch:
    """Test _process_artists_batch functionality."""

    @pytest.mark.asyncio
    async def test_process_artists_with_no_updates_needed(self) -> None:
        """Test skipping artists that are already up to date."""
        mock_driver = MagicMock()
        mock_session = MagicMock()

        # Mock hash check to return matching hashes
        mock_result = MagicMock()
        mock_result.__iter__ = lambda _: iter([{"id": "1", "hash": "hash1"}])
        mock_session.run.return_value = mock_result

        mock_driver.session.return_value.__enter__.return_value = mock_session

        processor = Neo4jBatchProcessor(mock_driver)

        messages = [PendingMessage("artists", {"id": "1", "name": "Artist 1", "sha256": "hash1"}, AsyncMock(), AsyncMock())]

        await processor._process_artists_batch(messages)

        # Should only run hash check query, not updates
        assert mock_session.run.call_count == 1

    @pytest.mark.asyncio
    async def test_process_artists_with_updates(self) -> None:
        """Test processing artists that need updates."""
        mock_driver = MagicMock()
        mock_session = MagicMock()

        # Mock hash check to return no existing hash
        mock_result = MagicMock()
        mock_result.__iter__ = lambda _: iter([{"id": "1", "hash": None}])
        mock_session.run.return_value = mock_result

        mock_driver.session.return_value.__enter__.return_value = mock_session

        processor = Neo4jBatchProcessor(mock_driver)

        messages = [
            PendingMessage(
                "artists",
                {"id": "1", "name": "Artist 1", "sha256": "hash1", "members": [], "groups": [], "aliases": []},
                AsyncMock(),
                AsyncMock(),
            )
        ]

        await processor._process_artists_batch(messages)

        # Should have called execute_write
        mock_session.execute_write.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_artists_with_relationships(self) -> None:
        """Test processing artists with members, groups, and aliases."""
        mock_driver = MagicMock()
        mock_session = MagicMock()

        # Mock hash check
        mock_result = MagicMock()
        mock_result.__iter__ = lambda _: iter([{"id": "1", "hash": None}])
        mock_session.run.return_value = mock_result

        mock_driver.session.return_value.__enter__.return_value = mock_session

        processor = Neo4jBatchProcessor(mock_driver)

        messages = [
            PendingMessage(
                "artists",
                {
                    "id": "1",
                    "name": "Artist 1",
                    "sha256": "hash1",
                    "members": [{"id": "2"}, {"id": "3"}],
                    "groups": [{"id": "4"}],
                    "aliases": [{"id": "5"}],
                },
                AsyncMock(),
                AsyncMock(),
            )
        ]

        await processor._process_artists_batch(messages)

        mock_session.execute_write.assert_called_once()


class TestProcessLabelsBatch:
    """Test _process_labels_batch functionality."""

    @pytest.mark.asyncio
    async def test_process_labels_with_parent_and_sublabels(self) -> None:
        """Test processing labels with parent and sublabel relationships."""
        mock_driver = MagicMock()
        mock_session = MagicMock()

        # Mock hash check
        mock_result = MagicMock()
        mock_result.__iter__ = lambda _: iter([{"id": "1", "hash": None}])
        mock_session.run.return_value = mock_result

        mock_driver.session.return_value.__enter__.return_value = mock_session

        processor = Neo4jBatchProcessor(mock_driver)

        messages = [
            PendingMessage(
                "labels",
                {
                    "id": "1",
                    "name": "Label 1",
                    "sha256": "hash1",
                    "parentLabel": {"id": "2"},
                    "sublabels": [{"id": "3"}, {"id": "4"}],
                },
                AsyncMock(),
                AsyncMock(),
            )
        ]

        await processor._process_labels_batch(messages)

        mock_session.execute_write.assert_called_once()


class TestProcessMastersBatch:
    """Test _process_masters_batch functionality."""

    @pytest.mark.asyncio
    async def test_process_masters_with_genres_and_styles(self) -> None:
        """Test processing masters with genres and styles."""
        mock_driver = MagicMock()
        mock_session = MagicMock()

        # Mock hash check
        mock_result = MagicMock()
        mock_result.__iter__ = lambda _: iter([{"id": "1", "hash": None}])
        mock_session.run.return_value = mock_result

        mock_driver.session.return_value.__enter__.return_value = mock_session

        processor = Neo4jBatchProcessor(mock_driver)

        messages = [
            PendingMessage(
                "masters",
                {
                    "id": "1",
                    "title": "Master 1",
                    "year": 2023,
                    "sha256": "hash1",
                    "artists": [{"id": "A1"}],
                    "genres": ["Rock", "Pop"],
                    "styles": ["Alternative", "Indie"],
                },
                AsyncMock(),
                AsyncMock(),
            )
        ]

        await processor._process_masters_batch(messages)

        mock_session.execute_write.assert_called_once()


class TestProcessReleasesBatch:
    """Test _process_releases_batch functionality."""

    @pytest.mark.asyncio
    async def test_process_releases_with_all_relationships(self) -> None:
        """Test processing releases with all relationship types."""
        mock_driver = MagicMock()
        mock_session = MagicMock()

        # Mock hash check
        mock_result = MagicMock()
        mock_result.__iter__ = lambda _: iter([{"id": "1", "hash": None}])
        mock_session.run.return_value = mock_result

        mock_driver.session.return_value.__enter__.return_value = mock_session

        processor = Neo4jBatchProcessor(mock_driver)

        messages = [
            PendingMessage(
                "releases",
                {
                    "id": "1",
                    "title": "Release 1",
                    "sha256": "hash1",
                    "artists": [{"id": "A1"}],
                    "labels": [{"id": "L1"}],
                    "master_id": "M1",
                    "genres": ["Rock"],
                    "styles": ["Alternative"],
                },
                AsyncMock(),
                AsyncMock(),
            )
        ]

        await processor._process_releases_batch(messages)

        mock_session.execute_write.assert_called_once()


class TestFlushAll:
    """Test flush_all functionality."""

    @pytest.mark.asyncio
    async def test_flush_all_queues(self) -> None:
        """Test flushing all queues."""
        mock_driver = MagicMock()
        processor = Neo4jBatchProcessor(mock_driver)

        # Mock the _flush_queue method
        processor._flush_queue = AsyncMock()  # type: ignore[method-assign]

        await processor.flush_all()

        # Should flush all 4 data types
        assert processor._flush_queue.call_count == 4


class TestPeriodicFlush:
    """Test periodic_flush functionality."""

    @pytest.mark.asyncio
    async def test_periodic_flush_runs_until_shutdown(self) -> None:
        """Test periodic flush runs and stops on shutdown."""
        import time

        mock_driver = MagicMock()
        config = BatchConfig(flush_interval=0.1)
        processor = Neo4jBatchProcessor(mock_driver, config)

        # Mock the _flush_queue method
        processor._flush_queue = AsyncMock()  # type: ignore[method-assign]

        # Set last flush time to past so flush will be triggered
        for data_type in processor.queues:
            processor.last_flush[data_type] = time.time() - 1.0

        # Add a message to trigger flush
        processor.queues["artists"].append(PendingMessage("artists", {"id": "1"}, AsyncMock(), AsyncMock()))

        # Start periodic flush
        flush_task = asyncio.create_task(processor.periodic_flush())

        # Let it run for a bit
        await asyncio.sleep(0.25)

        # Shutdown
        processor.shutdown()

        # Wait for task to complete
        await asyncio.sleep(0.15)

        # Cancel task
        flush_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await flush_task

        # Should have called flush at least once
        assert processor._flush_queue.call_count > 0

    @pytest.mark.asyncio
    async def test_periodic_flush_only_flushes_after_interval(self) -> None:
        """Test periodic flush only flushes queues after interval."""
        mock_driver = MagicMock()
        config = BatchConfig(flush_interval=10.0)  # Long interval
        processor = Neo4jBatchProcessor(mock_driver, config)

        # Mock the _flush_queue method
        processor._flush_queue = AsyncMock()  # type: ignore[method-assign]

        # Set last flush to recent
        import time

        for data_type in processor.queues:
            processor.last_flush[data_type] = time.time()

        # Start periodic flush
        flush_task = asyncio.create_task(processor.periodic_flush())

        # Wait a short time (less than interval)
        await asyncio.sleep(0.2)

        # Shutdown
        processor.shutdown()
        await asyncio.sleep(0.1)

        # Cancel task
        flush_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await flush_task

        # Should not have flushed since interval not passed
        assert processor._flush_queue.call_count == 0


class TestShutdown:
    """Test shutdown functionality."""

    def test_shutdown_sets_flag(self) -> None:
        """Test shutdown sets internal flag."""
        mock_driver = MagicMock()
        processor = Neo4jBatchProcessor(mock_driver)

        assert processor._shutdown is False

        processor.shutdown()

        assert processor._shutdown is True


class TestGetStats:
    """Test get_stats functionality."""

    def test_get_stats_returns_current_state(self) -> None:
        """Test getting processor statistics."""
        mock_driver = MagicMock()
        processor = Neo4jBatchProcessor(mock_driver)

        # Add some test data
        processor.processed_counts["artists"] = 100
        processor.batch_counts["artists"] = 5
        processor.queues["artists"].append(PendingMessage("artists", {"id": "1"}, AsyncMock(), AsyncMock()))

        stats = processor.get_stats()

        assert stats["processed"]["artists"] == 100
        assert stats["batches"]["artists"] == 5
        assert stats["pending"]["artists"] == 1
        assert stats["pending"]["labels"] == 0


class TestBatchTransactionLogic:
    """Test batch transaction logic for all data types."""

    @pytest.mark.asyncio
    async def test_artists_batch_transaction_creates_all_relationships(self) -> None:
        """Test artist batch transaction creates all relationship types."""
        mock_driver = MagicMock()
        mock_session = MagicMock()

        # Track cypher queries executed
        executed_queries: list[str] = []

        def track_query(query: str, **_params: Any) -> None:
            executed_queries.append(query)

        mock_tx = MagicMock()
        mock_tx.run.side_effect = track_query

        def execute_write_mock(tx_func: Any) -> None:
            return tx_func(mock_tx)

        mock_session.execute_write.side_effect = execute_write_mock

        # Mock hash check to return no hashes
        mock_result = MagicMock()
        mock_result.__iter__ = lambda _: iter([{"id": "1", "hash": None}])
        mock_session.run.return_value = mock_result

        mock_driver.session.return_value.__enter__.return_value = mock_session

        processor = Neo4jBatchProcessor(mock_driver)

        messages = [
            PendingMessage(
                "artists",
                {
                    "id": "1",
                    "name": "Artist 1",
                    "sha256": "hash1",
                    "members": [{"id": "M1"}],
                    "groups": [{"id": "G1"}],
                    "aliases": [{"id": "A1"}],
                },
                AsyncMock(),
                AsyncMock(),
            )
        ]

        await processor._process_artists_batch(messages)

        # Should have created artist node and all relationships
        assert len(executed_queries) >= 4  # Artist node + members + groups + aliases
