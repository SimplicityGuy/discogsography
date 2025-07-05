"""Tests for graphinator module."""

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aio_pika.abc import AbstractIncomingMessage

from graphinator.graphinator import (
    get_existing_hash,
    main,
    on_artist_message,
    on_label_message,
    on_master_message,
    on_release_message,
    safe_execute_query,
)


class TestGetExistingHash:
    """Test get_existing_hash function."""

    def test_get_existing_hash_found(self) -> None:
        """Test getting hash when node exists."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.single.return_value = {"hash": "abc123"}
        mock_session.run.return_value = mock_result

        result = get_existing_hash(mock_session, "Artist", "123")

        assert result == "abc123"
        mock_session.run.assert_called_once()

    def test_get_existing_hash_not_found(self) -> None:
        """Test getting hash when node doesn't exist."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.single.return_value = None
        mock_session.run.return_value = mock_result

        result = get_existing_hash(mock_session, "Artist", "123")

        assert result is None

    def test_get_existing_hash_error(self) -> None:
        """Test handling errors when getting hash."""
        mock_session = MagicMock()
        mock_session.run.side_effect = Exception("Database error")

        with patch("graphinator.graphinator.logger") as mock_logger:
            result = get_existing_hash(mock_session, "Artist", "123")

            assert result is None
            mock_logger.warning.assert_called_once()


class TestSafeExecuteQuery:
    """Test safe_execute_query function."""

    def test_successful_execution(self) -> None:
        """Test successful query execution."""
        mock_session = MagicMock()

        result = safe_execute_query(mock_session, "MATCH (n) RETURN n", {"id": "123"})

        assert result is True
        mock_session.run.assert_called_once_with("MATCH (n) RETURN n", {"id": "123"})

    def test_neo4j_error(self) -> None:
        """Test handling Neo4j errors."""
        mock_session = MagicMock()
        mock_session.run.side_effect = Exception("Neo4j error")

        with patch("graphinator.graphinator.logger") as mock_logger:
            result = safe_execute_query(mock_session, "MATCH (n) RETURN n", {})

            assert result is False
            mock_logger.error.assert_called()


class TestOnArtistMessage:
    """Test on_artist_message handler."""

    @pytest.mark.asyncio
    async def test_process_new_artist(
        self, sample_artist_data: dict[str, Any], mock_neo4j_driver: MagicMock
    ) -> None:
        """Test processing a new artist message."""
        # Create mock message
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(sample_artist_data).encode()

        # Setup Neo4j mock
        mock_session = MagicMock()
        mock_tx = MagicMock()
        mock_neo4j_driver.session.return_value.__enter__.return_value = mock_session
        mock_session.execute_write.return_value = True

        # Mock transaction to indicate new artist
        def mock_tx_func(func: Any) -> Any:
            mock_tx.run.return_value.single.return_value = None  # No existing artist
            return func(mock_tx)

        mock_session.execute_write.side_effect = mock_tx_func

        with patch("graphinator.graphinator.graph", mock_neo4j_driver):
            await on_artist_message(mock_message)

        # Verify message was acknowledged
        mock_message.ack.assert_called_once()

        # Verify session was used
        mock_session.execute_write.assert_called_once()

    @pytest.mark.asyncio
    async def test_skip_unchanged_artist(
        self, sample_artist_data: dict[str, Any], mock_neo4j_driver: MagicMock
    ) -> None:
        """Test skipping artist with unchanged hash."""
        # Create mock message
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(sample_artist_data).encode()

        # Setup Neo4j mock to return existing hash
        mock_session = MagicMock()
        mock_neo4j_driver.session.return_value.__enter__.return_value = mock_session

        def mock_tx_func(func: Any) -> Any:
            mock_tx = MagicMock()
            # Return existing artist with same hash
            mock_tx.run.return_value.single.return_value = {"hash": sample_artist_data["sha256"]}
            return func(mock_tx)

        mock_session.execute_write.side_effect = mock_tx_func

        with patch("graphinator.graphinator.graph", mock_neo4j_driver):
            await on_artist_message(mock_message)

        # Verify message was acknowledged
        mock_message.ack.assert_called_once()

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.shutdown_requested", True)
    async def test_reject_on_shutdown(self) -> None:
        """Test message rejection during shutdown."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)

        await on_artist_message(mock_message)

        mock_message.nack.assert_called_once_with(requeue=True)
        mock_message.ack.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_processing_error(self, sample_artist_data: dict[str, Any]) -> None:
        """Test error handling during processing."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(sample_artist_data).encode()

        with patch("graphinator.graphinator.graph") as mock_graph:
            # Make session raise exception
            mock_graph.session.side_effect = Exception("Database connection failed")

            await on_artist_message(mock_message)

        # Should nack with requeue
        mock_message.nack.assert_called_once_with(requeue=True)


class TestOnLabelMessage:
    """Test on_label_message handler."""

    @pytest.mark.asyncio
    async def test_process_label_with_parent(
        self, sample_label_data: dict[str, Any], mock_neo4j_driver: MagicMock
    ) -> None:
        """Test processing label with parent relationship."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(sample_label_data).encode()

        mock_session = MagicMock()
        mock_neo4j_driver.session.return_value.__enter__.return_value = mock_session
        mock_session.execute_write.return_value = True

        with patch("graphinator.graphinator.graph", mock_neo4j_driver):
            await on_label_message(mock_message)

        mock_message.ack.assert_called_once()
        mock_session.execute_write.assert_called_once()


class TestOnMasterMessage:
    """Test on_master_message handler."""

    @pytest.mark.asyncio
    async def test_process_master_with_genres_styles(
        self, sample_master_data: dict[str, Any], mock_neo4j_driver: MagicMock
    ) -> None:
        """Test processing master with genres and styles."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(sample_master_data).encode()

        mock_session = MagicMock()
        mock_neo4j_driver.session.return_value.__enter__.return_value = mock_session
        mock_session.execute_write.return_value = True

        with patch("graphinator.graphinator.graph", mock_neo4j_driver):
            await on_master_message(mock_message)

        mock_message.ack.assert_called_once()
        mock_session.execute_write.assert_called_once()


class TestOnReleaseMessage:
    """Test on_release_message handler."""

    @pytest.mark.asyncio
    async def test_process_release_with_all_relationships(
        self, sample_release_data: dict[str, Any], mock_neo4j_driver: MagicMock
    ) -> None:
        """Test processing release with all relationships."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(sample_release_data).encode()

        mock_session = MagicMock()
        mock_neo4j_driver.session.return_value.__enter__.return_value = mock_session
        mock_session.execute_write.return_value = True

        with patch("graphinator.graphinator.graph", mock_neo4j_driver):
            await on_release_message(mock_message)

        mock_message.ack.assert_called_once()
        mock_session.execute_write.assert_called_once()


class TestMain:
    """Test main function."""

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.connect")
    @patch("graphinator.graphinator.GraphDatabase")
    async def test_main_execution(self, mock_graph_db: MagicMock, mock_connect: AsyncMock) -> None:
        """Test successful main execution."""
        # Setup mocks
        mock_amqp = AsyncMock()
        mock_connect.return_value = mock_amqp
        mock_channel = AsyncMock()
        mock_amqp.channel.return_value = mock_channel

        # Mock queue setup
        mock_queue = AsyncMock()
        mock_channel.declare_queue.return_value = mock_queue

        # Mock Neo4j driver and connectivity test
        mock_driver = MagicMock()
        mock_graph_db.driver.return_value = mock_driver
        mock_session = MagicMock()
        mock_driver.session.return_value.__enter__.return_value = mock_session
        mock_session.run.return_value.single.return_value = {"test": 1}

        # Simulate shutdown by setting shutdown_requested
        with patch("graphinator.graphinator.shutdown_requested", False):
            # Create a mock task that can be properly awaited
            async def mock_coro() -> None:
                pass

            mock_task = asyncio.create_task(mock_coro())
            mock_task.cancel()  # Pre-cancel it

            with patch("asyncio.create_task", return_value=mock_task):
                # Make the main loop exit after setup
                async def mock_wait_for(coro: Any, timeout: float) -> None:  # noqa: ARG001
                    # First call times out, second call sets shutdown_requested
                    import graphinator.graphinator

                    graphinator.graphinator.shutdown_requested = True
                    raise TimeoutError()

                with patch("asyncio.wait_for", mock_wait_for):
                    await main()

        # Verify setup was performed
        mock_connect.assert_called_once()
        mock_channel.declare_exchange.assert_called_once()
        assert mock_channel.declare_queue.call_count == 4  # 4 data types

        # Verify driver was closed
        mock_driver.close.assert_called_once()

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.graph")
    async def test_main_neo4j_connection_failure(self, mock_graph: MagicMock) -> None:
        """Test main when Neo4j connection fails."""
        # Make Neo4j connection fail
        mock_graph.session.side_effect = Exception("Cannot connect to Neo4j")

        # Should complete without raising
        await main()

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.connect")
    @patch("graphinator.graphinator.graph")
    async def test_main_amqp_connection_failure(
        self, mock_graph: MagicMock, mock_connect: AsyncMock
    ) -> None:
        """Test main when AMQP connection fails."""
        # Setup Neo4j success
        mock_session = MagicMock()
        mock_graph.session.return_value.__enter__.return_value = mock_session
        mock_session.run.return_value.single.return_value = {"test": 1}

        # Make AMQP connection fail
        mock_connect.side_effect = Exception("Cannot connect to AMQP")

        # Should complete without raising
        await main()
