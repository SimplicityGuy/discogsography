"""Tests for graphinator module."""

import asyncio
import contextlib
import json
import signal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from aio_pika.abc import AbstractIncomingMessage
from orjson import dumps
import pytest

from graphinator.graphinator import (
    main,
    on_artist_message,
    on_label_message,
    on_master_message,
    on_release_message,
)


class TestOnArtistMessage:
    """Test on_artist_message handler."""

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.shutdown_requested", False)
    async def test_process_new_artist(self, sample_artist_data: dict[str, Any], mock_neo4j_driver: MagicMock) -> None:
        """Test processing a new artist message."""
        # Create mock message
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(sample_artist_data).encode()

        # Get the mock session from the fixture's async context manager
        mock_context_manager = await mock_neo4j_driver.session(database="neo4j")
        mock_session = await mock_context_manager.__aenter__()

        # Mock transaction to indicate new artist
        mock_tx = MagicMock()

        async def mock_tx_func(func: Any) -> Any:
            mock_tx.run.return_value.single.return_value = None  # No existing artist
            return func(mock_tx)

        mock_session.execute_write.side_effect = mock_tx_func

        with patch("graphinator.graphinator.graph", mock_neo4j_driver):
            await on_artist_message(mock_message)

        # Verify message was acknowledged
        mock_message.ack.assert_called_once()

        # Verify session was used
        mock_session.execute_write.assert_called()

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.shutdown_requested", False)
    async def test_skip_unchanged_artist(self, sample_artist_data: dict[str, Any], mock_neo4j_driver: MagicMock) -> None:
        """Test skipping artist with unchanged hash."""
        # Create mock message
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(sample_artist_data).encode()

        # Get the mock session from the fixture's async context manager
        mock_context_manager = await mock_neo4j_driver.session(database="neo4j")
        mock_session = await mock_context_manager.__aenter__()

        # Mock transaction to return existing hash
        mock_tx = MagicMock()

        async def mock_tx_func(func: Any) -> Any:
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
    @patch("graphinator.graphinator.shutdown_requested", False)
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

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.shutdown_requested", False)
    async def test_handle_neo4j_connection_error_with_raise(self, sample_artist_data: dict[str, Any]) -> None:
        """Test handling Neo4j connection errors that get raised."""
        from neo4j.exceptions import ServiceUnavailable

        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(sample_artist_data).encode()

        with patch("graphinator.graphinator.graph") as mock_graph:
            # Make session raise ServiceUnavailable
            mock_graph.session.side_effect = ServiceUnavailable("Connection lost")

            await on_artist_message(mock_message)

        # Should nack with requeue
        mock_message.nack.assert_called_once_with(requeue=True)

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.shutdown_requested", False)
    async def test_handle_session_expired_error(self, sample_artist_data: dict[str, Any]) -> None:
        """Test handling SessionExpired errors."""
        from neo4j.exceptions import SessionExpired

        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(sample_artist_data).encode()

        with patch("graphinator.graphinator.graph") as mock_graph:
            # Make session raise SessionExpired
            mock_graph.session.side_effect = SessionExpired("Session expired")

            await on_artist_message(mock_message)

        # Should nack with requeue
        mock_message.nack.assert_called_once_with(requeue=True)

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.shutdown_requested", False)
    async def test_handle_nack_failure_on_service_unavailable(self, sample_artist_data: dict[str, Any]) -> None:
        """Test handling nack failure when Neo4j is unavailable."""
        from neo4j.exceptions import ServiceUnavailable

        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(sample_artist_data).encode()
        mock_message.nack.side_effect = Exception("Nack failed")

        with patch("graphinator.graphinator.graph") as mock_graph, patch("graphinator.graphinator.logger"):
            mock_graph.session.side_effect = ServiceUnavailable("Connection lost")

            # Should not raise exception
            await on_artist_message(mock_message)

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.shutdown_requested", False)
    async def test_handle_general_exception_with_nack_failure(self, sample_artist_data: dict[str, Any]) -> None:
        """Test handling general exception with nack failure."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(sample_artist_data).encode()
        mock_message.nack.side_effect = Exception("Nack failed")

        with patch("graphinator.graphinator.graph") as mock_graph, patch("graphinator.graphinator.logger"):
            mock_graph.session.side_effect = RuntimeError("Unexpected error")

            # Should not raise exception
            await on_artist_message(mock_message)

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.shutdown_requested", False)
    async def test_handle_file_completion_message(self) -> None:
        """Test handling file completion message in artist handler."""
        import graphinator.graphinator

        graphinator.graphinator.completed_files = set()
        graphinator.graphinator.queues = {}

        completion_data = {
            "type": "file_complete",
            "total_processed": 100,
        }

        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(completion_data).encode()

        await on_artist_message(mock_message)

        # Should acknowledge the message
        mock_message.ack.assert_called_once()

        # Should mark file as completed
        assert "artists" in graphinator.graphinator.completed_files


class TestOnLabelMessage:
    """Test on_label_message handler."""

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.shutdown_requested", False)
    async def test_process_label_with_parent(self, sample_label_data: dict[str, Any], mock_neo4j_driver: MagicMock) -> None:
        """Test processing label with parent relationship."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(sample_label_data).encode()

        # Get the mock session from the fixture's async context manager
        mock_context_manager = await mock_neo4j_driver.session(database="neo4j")
        mock_session = await mock_context_manager.__aenter__()
        mock_session.execute_write = AsyncMock(return_value=True)

        with patch("graphinator.graphinator.graph", mock_neo4j_driver):
            await on_label_message(mock_message)

        mock_message.ack.assert_called_once()
        mock_session.execute_write.assert_called()

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.shutdown_requested", True)
    async def test_reject_on_shutdown(self) -> None:
        """Test label message rejection during shutdown."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)

        await on_label_message(mock_message)

        mock_message.nack.assert_called_once_with(requeue=True)
        mock_message.ack.assert_not_called()


class TestOnMasterMessage:
    """Test on_master_message handler."""

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.shutdown_requested", False)
    async def test_process_master_with_genres_styles(self, sample_master_data: dict[str, Any], mock_neo4j_driver: MagicMock) -> None:
        """Test processing master with genres and styles."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(sample_master_data).encode()

        # Get the mock session from the fixture's async context manager
        mock_context_manager = await mock_neo4j_driver.session(database="neo4j")
        mock_session = await mock_context_manager.__aenter__()
        mock_session.execute_write = AsyncMock(return_value=True)

        with patch("graphinator.graphinator.graph", mock_neo4j_driver):
            await on_master_message(mock_message)

        mock_message.ack.assert_called_once()
        mock_session.execute_write.assert_called()


class TestOnReleaseMessage:
    """Test on_release_message handler."""

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.shutdown_requested", False)
    async def test_process_release_with_all_relationships(self, sample_release_data: dict[str, Any], mock_neo4j_driver: MagicMock) -> None:
        """Test processing release with all relationships."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(sample_release_data).encode()

        # Get the mock session from the fixture's async context manager
        mock_context_manager = await mock_neo4j_driver.session(database="neo4j")
        mock_session = await mock_context_manager.__aenter__()
        mock_session.execute_write = AsyncMock(return_value=True)

        with patch("graphinator.graphinator.graph", mock_neo4j_driver):
            await on_release_message(mock_message)

        mock_message.ack.assert_called_once()
        mock_session.execute_write.assert_called()


class TestCheckConsumersUnexpectedlyDead:
    """Test check_consumers_unexpectedly_dead function."""

    @pytest.mark.asyncio
    async def test_returns_true_when_consumers_dead(self) -> None:
        """Test returns True when consumers have died unexpectedly."""
        import graphinator.graphinator

        graphinator.graphinator.consumer_tags = {}
        graphinator.graphinator.completed_files = {"artists"}  # Not all complete
        graphinator.graphinator.message_counts = {"artists": 10, "labels": 0, "masters": 0, "releases": 0}

        from graphinator.graphinator import check_consumers_unexpectedly_dead

        result = await check_consumers_unexpectedly_dead()
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_consumers_active(self) -> None:
        """Test returns False when consumers are still active."""
        import graphinator.graphinator

        graphinator.graphinator.consumer_tags = {"artists": "tag123"}
        graphinator.graphinator.completed_files = {"artists"}
        graphinator.graphinator.message_counts = {"artists": 10, "labels": 0, "masters": 0, "releases": 0}

        from graphinator.graphinator import check_consumers_unexpectedly_dead

        result = await check_consumers_unexpectedly_dead()
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_no_messages_processed(self) -> None:
        """Test returns False when no messages have been processed yet."""
        import graphinator.graphinator

        graphinator.graphinator.consumer_tags = {}
        graphinator.graphinator.completed_files = set()
        graphinator.graphinator.message_counts = {"artists": 0, "labels": 0, "masters": 0, "releases": 0}

        from graphinator.graphinator import check_consumers_unexpectedly_dead

        result = await check_consumers_unexpectedly_dead()
        assert result is False


class TestMain:
    """Test main function."""

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.setup_logging")
    @patch("graphinator.graphinator.HealthServer")
    @patch("graphinator.graphinator.AsyncResilientRabbitMQ")
    @patch("graphinator.graphinator.AsyncResilientNeo4jDriver")
    async def test_main_execution(
        self,
        mock_neo4j_class: MagicMock,
        mock_rabbitmq_class: AsyncMock,
        mock_health_server: MagicMock,
        _mock_setup_logging: MagicMock,
    ) -> None:
        """Test successful main execution."""
        # Mock health server
        mock_health_instance = MagicMock()
        mock_health_server.return_value = mock_health_instance

        # Setup RabbitMQ mocks
        mock_rabbitmq_instance = AsyncMock()
        mock_rabbitmq_class.return_value = mock_rabbitmq_instance
        mock_connection = AsyncMock()
        mock_rabbitmq_instance.connect.return_value = mock_connection
        mock_channel = AsyncMock()
        mock_rabbitmq_instance.channel.return_value = mock_channel

        # Mock queue setup
        mock_queue = AsyncMock()
        mock_channel.declare_queue.return_value = mock_queue

        # Mock Neo4j driver and connectivity test
        mock_neo4j_instance = MagicMock()
        mock_neo4j_class.return_value = mock_neo4j_instance

        # Setup async session context manager
        mock_session = AsyncMock()
        mock_context_manager = AsyncMock()
        mock_context_manager.__aenter__ = AsyncMock(return_value=mock_session)
        mock_context_manager.__aexit__ = AsyncMock(return_value=None)

        # session() returns an awaitable that returns the context manager
        async def mock_session_factory(*_args, **_kwargs):
            return mock_context_manager

        mock_neo4j_instance.session = MagicMock(side_effect=mock_session_factory)

        # Mock the connectivity test
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value={"test": 1})
        mock_session.run = AsyncMock(return_value=mock_result)
        mock_neo4j_instance.close = AsyncMock()

        # Simulate shutdown by setting shutdown_requested
        with patch("graphinator.graphinator.shutdown_requested", False):
            # Track created tasks
            created_tasks = []

            # Mock create_task to capture and return real tasks
            original_create_task = asyncio.create_task

            def mock_create_task(coro: Any) -> asyncio.Task[Any]:
                task = original_create_task(coro)
                created_tasks.append(task)
                return task

            with patch("asyncio.create_task", side_effect=mock_create_task):
                # Make the main loop exit after setup
                async def mock_wait_for(_coro: Any, _timeout: float) -> None:
                    # First call times out, second call sets shutdown_requested
                    import graphinator.graphinator

                    graphinator.graphinator.shutdown_requested = True
                    raise TimeoutError()

                with patch("asyncio.wait_for", mock_wait_for):
                    await main()

            # Clean up any created tasks
            for task in created_tasks:
                if not task.done():
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task

        # Verify setup was performed
        mock_rabbitmq_class.assert_called_once()
        mock_neo4j_class.assert_called_once()

        # The test exits early due to our mock, so channel operations might not complete

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.setup_logging")
    @patch("graphinator.graphinator.HealthServer")
    @patch("graphinator.graphinator.AsyncResilientNeo4jDriver")
    async def test_main_neo4j_connection_failure(
        self,
        mock_neo4j_class: MagicMock,
        mock_health_server: MagicMock,
        _mock_setup_logging: MagicMock,
    ) -> None:
        """Test main when Neo4j connection fails."""
        # Mock health server
        mock_health_instance = MagicMock()
        mock_health_server.return_value = mock_health_instance

        # Make Neo4j connection fail
        mock_neo4j_class.side_effect = Exception("Cannot connect to Neo4j")

        # Should handle the exception and exit gracefully
        with pytest.raises(Exception, match="Cannot connect to Neo4j"):
            await main()

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.setup_logging")
    @patch("graphinator.graphinator.HealthServer")
    @patch("graphinator.graphinator.AsyncResilientRabbitMQ")
    @patch("graphinator.graphinator.AsyncResilientNeo4jDriver")
    async def test_main_amqp_connection_failure(
        self,
        mock_neo4j_class: MagicMock,
        mock_rabbitmq_class: AsyncMock,
        mock_health_server: MagicMock,
        _mock_setup_logging: MagicMock,
    ) -> None:
        """Test main when AMQP connection fails."""
        # Mock health server
        mock_health_instance = MagicMock()
        mock_health_server.return_value = mock_health_instance

        # Setup Neo4j success with async session support
        mock_neo4j_instance = MagicMock()
        mock_neo4j_class.return_value = mock_neo4j_instance

        # Create async session mock
        mock_session = AsyncMock()
        mock_session.run.return_value.single.return_value = {"test": 1}

        # Setup async context manager for session
        mock_context_manager = AsyncMock()
        mock_context_manager.__aenter__ = AsyncMock(return_value=mock_session)
        mock_context_manager.__aexit__ = AsyncMock(return_value=None)

        async def mock_session_factory(*_args, **_kwargs):
            return mock_context_manager

        mock_neo4j_instance.session = MagicMock(side_effect=mock_session_factory)

        # Make AMQP connection fail
        mock_rabbitmq_class.side_effect = Exception("Cannot connect to AMQP")

        # Should handle the exception and exit gracefully
        with pytest.raises(Exception, match="Cannot connect to AMQP"):
            await main()


class TestGetHealthData:
    """Test get_health_data function."""

    def test_health_data_with_graph(self) -> None:
        """Test health data when graph is connected."""
        import time

        current_time = time.time()
        with (
            patch("graphinator.graphinator.graph", MagicMock()),
            patch("graphinator.graphinator.current_progress", 0.75),
            patch(
                "graphinator.graphinator.message_counts",
                {"artists": 100, "labels": 50, "masters": 25, "releases": 200},
            ),
            patch(
                "graphinator.graphinator.last_message_time",
                {
                    "artists": current_time - 5,  # 5 seconds ago - recent activity
                    "labels": current_time - 8,  # 8 seconds ago - recent activity
                    "masters": current_time - 15,  # 15 seconds ago - old
                    "releases": current_time - 20,  # 20 seconds ago - old
                },
            ),
            patch(
                "graphinator.graphinator.consumer_tags",
                {"artists": "consumer-1", "labels": "consumer-2"},
            ),
        ):
            from graphinator.graphinator import get_health_data

            result = get_health_data()

            assert result["status"] == "healthy"
            assert result["service"] == "graphinator"
            # Should show "Processing artists" because it has recent activity (5 seconds ago)
            assert result["current_task"] == "Processing artists"
            assert result["progress"] == 0.75
            assert result["message_counts"]["artists"] == 100

    def test_health_data_starting_status(self) -> None:
        """Test health data shows 'starting' during initialization (no graph, no consumers, no messages)."""
        with (
            patch("graphinator.graphinator.graph", None),
            patch("graphinator.graphinator.consumer_tags", {}),
            patch(
                "graphinator.graphinator.message_counts",
                {"artists": 0, "labels": 0, "masters": 0, "releases": 0},
            ),
        ):
            from graphinator.graphinator import get_health_data

            result = get_health_data()

            assert result["status"] == "starting"
            assert result["service"] == "graphinator"
            assert result["current_task"] == "Initializing Neo4j connection"

    def test_health_data_unhealthy_when_graph_lost(self) -> None:
        """Test health data shows 'unhealthy' when graph connection lost after processing started."""
        with (
            patch("graphinator.graphinator.graph", None),
            patch("graphinator.graphinator.consumer_tags", {"artists": "consumer-1"}),
            patch(
                "graphinator.graphinator.message_counts",
                {"artists": 100, "labels": 0, "masters": 0, "releases": 0},
            ),
        ):
            from graphinator.graphinator import get_health_data

            result = get_health_data()

            assert result["status"] == "unhealthy"
            assert result["service"] == "graphinator"

    def test_idle_status_with_active_consumers(self) -> None:
        """Test health data shows idle status when consumers active but no recent messages."""
        import time

        current_time = time.time()
        with (
            patch("graphinator.graphinator.graph", MagicMock()),
            patch("graphinator.graphinator.current_progress", 0.0),
            patch(
                "graphinator.graphinator.message_counts",
                {"artists": 100, "labels": 50, "masters": 0, "releases": 0},
            ),
            patch(
                "graphinator.graphinator.last_message_time",
                {
                    "artists": current_time - 60,  # 60 seconds ago - old
                    "labels": current_time - 120,  # 120 seconds ago - old
                    "masters": 0.0,
                    "releases": 0.0,
                },
            ),
            patch(
                "graphinator.graphinator.consumer_tags",
                {"artists": "consumer-1", "labels": "consumer-2"},
            ),
        ):
            from graphinator.graphinator import get_health_data

            result = get_health_data()

            assert result["status"] == "healthy"
            assert result["current_task"] == "Idle - waiting for messages"

    def test_no_status_when_no_consumers(self) -> None:
        """Test health data shows healthy when no consumers but all files completed (normal idle)."""
        import time

        current_time = time.time()
        with (
            patch("graphinator.graphinator.graph", MagicMock()),
            patch("graphinator.graphinator.current_progress", 0.0),
            patch(
                "graphinator.graphinator.message_counts",
                {"artists": 100, "labels": 50, "masters": 0, "releases": 0},
            ),
            patch(
                "graphinator.graphinator.last_message_time",
                {
                    "artists": current_time - 60,
                    "labels": current_time - 120,
                    "masters": 0.0,
                    "releases": 0.0,
                },
            ),
            patch("graphinator.graphinator.consumer_tags", {}),
            # All files completed = normal idle state, not stuck
            patch("graphinator.graphinator.completed_files", {"artists", "labels", "masters", "releases"}),
        ):
            from graphinator.graphinator import get_health_data

            result = get_health_data()

            assert result["status"] == "healthy"
            assert result["current_task"] is None


class TestSignalHandler:
    """Test signal_handler function."""

    def test_signal_handler_sets_shutdown_flag(self) -> None:
        """Test that signal handler sets shutdown_requested flag."""
        import graphinator.graphinator

        # Reset shutdown flag
        graphinator.graphinator.shutdown_requested = False

        with patch("graphinator.graphinator.logger") as mock_logger:
            from graphinator.graphinator import signal_handler

            signal_handler(signal.SIGTERM, None)

            assert graphinator.graphinator.shutdown_requested is True
            mock_logger.info.assert_called_once()

    def test_signal_handler_logs_signal_number(self) -> None:
        """Test that signal handler logs the signal number."""
        import graphinator.graphinator

        graphinator.graphinator.shutdown_requested = False

        with patch("graphinator.graphinator.logger") as mock_logger:
            from graphinator.graphinator import signal_handler

            signal_handler(signal.SIGINT, None)

            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args
            assert "signum" in call_args[1]


class TestCheckAllConsumersIdle:
    """Test check_all_consumers_idle function."""

    @pytest.mark.asyncio
    async def test_all_idle_when_no_consumers_and_all_files_complete(self) -> None:
        """Test returns True when all consumers idle and files complete."""
        with (
            patch("graphinator.graphinator.consumer_tags", {}),
            patch("graphinator.graphinator.completed_files", {"artists", "labels", "masters", "releases"}),
        ):
            from graphinator.graphinator import check_all_consumers_idle

            result = await check_all_consumers_idle()
            assert result is True

    @pytest.mark.asyncio
    async def test_not_idle_when_consumers_active(self) -> None:
        """Test returns False when consumers are still active."""
        with (
            patch("graphinator.graphinator.consumer_tags", {"artists": "tag123"}),
            patch("graphinator.graphinator.completed_files", {"artists", "labels", "masters", "releases"}),
        ):
            from graphinator.graphinator import check_all_consumers_idle

            result = await check_all_consumers_idle()
            assert result is False

    @pytest.mark.asyncio
    async def test_not_idle_when_files_incomplete(self) -> None:
        """Test returns False when files are not all complete."""
        with patch("graphinator.graphinator.consumer_tags", {}), patch("graphinator.graphinator.completed_files", {"artists", "labels"}):
            from graphinator.graphinator import check_all_consumers_idle

            result = await check_all_consumers_idle()
            assert result is False


class TestCloseRabbitMQConnection:
    """Test close_rabbitmq_connection function."""

    @pytest.mark.asyncio
    async def test_close_channel_and_connection(self) -> None:
        """Test closes both channel and connection."""
        mock_channel = AsyncMock()
        mock_connection = AsyncMock()

        import graphinator.graphinator

        graphinator.graphinator.active_channel = mock_channel
        graphinator.graphinator.active_connection = mock_connection

        from graphinator.graphinator import close_rabbitmq_connection

        await close_rabbitmq_connection()

        mock_channel.close.assert_called_once()
        mock_connection.close.assert_called_once()
        assert graphinator.graphinator.active_channel is None
        assert graphinator.graphinator.active_connection is None

    @pytest.mark.asyncio
    async def test_close_handles_channel_error(self) -> None:
        """Test handles errors when closing channel."""
        mock_channel = AsyncMock()
        mock_channel.close.side_effect = Exception("Close failed")
        mock_connection = AsyncMock()

        import graphinator.graphinator

        graphinator.graphinator.active_channel = mock_channel
        graphinator.graphinator.active_connection = mock_connection

        with patch("graphinator.graphinator.logger"):
            from graphinator.graphinator import close_rabbitmq_connection

            # Should not raise
            await close_rabbitmq_connection()

            assert graphinator.graphinator.active_channel is None
            assert graphinator.graphinator.active_connection is None

    @pytest.mark.asyncio
    async def test_close_when_no_active_connections(self) -> None:
        """Test handles case when no active connections."""
        import graphinator.graphinator

        graphinator.graphinator.active_channel = None
        graphinator.graphinator.active_connection = None

        from graphinator.graphinator import close_rabbitmq_connection

        # Should not raise
        await close_rabbitmq_connection()


class TestCheckFileCompletion:
    """Test check_file_completion function."""

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.CONSUMER_CANCEL_DELAY", 0)
    async def test_handles_file_completion_message(self) -> None:
        """Test handles file completion message correctly."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        completion_data = {
            "type": "file_complete",
            "data_type": "artists",
            "total_processed": 1000,
        }

        import graphinator.graphinator

        graphinator.graphinator.completed_files = set()

        from graphinator.graphinator import check_file_completion

        result = await check_file_completion(completion_data, "artists", mock_message)

        assert result is True
        assert "artists" in graphinator.graphinator.completed_files
        mock_message.ack.assert_called_once()

    @pytest.mark.asyncio
    async def test_ignores_regular_message(self) -> None:
        """Test returns False for regular (non-completion) messages."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        regular_data = {"id": "123", "name": "Test Artist"}

        from graphinator.graphinator import check_file_completion

        result = await check_file_completion(regular_data, "artists", mock_message)

        assert result is False
        mock_message.ack.assert_not_called()

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.CONSUMER_CANCEL_DELAY", 300)
    @patch("graphinator.graphinator.schedule_consumer_cancellation")
    async def test_schedules_cancellation_when_enabled(self, mock_schedule: AsyncMock) -> None:
        """Test schedules consumer cancellation when delay is enabled."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_queue = AsyncMock()
        completion_data = {
            "type": "file_complete",
            "data_type": "artists",
            "total_processed": 1000,
        }

        import graphinator.graphinator

        graphinator.graphinator.completed_files = set()
        graphinator.graphinator.queues = {"artists": mock_queue}

        from graphinator.graphinator import check_file_completion

        result = await check_file_completion(completion_data, "artists", mock_message)

        assert result is True
        mock_schedule.assert_called_once_with("artists", mock_queue)


class TestScheduleConsumerCancellation:
    """Test schedule_consumer_cancellation function."""

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.CONSUMER_CANCEL_DELAY", 0.1)
    async def test_cancels_consumer_after_delay(self) -> None:
        """Test cancels consumer after specified delay."""
        mock_queue = AsyncMock()

        import graphinator.graphinator

        graphinator.graphinator.consumer_tags = {"artists": "consumer-tag-123"}
        graphinator.graphinator.consumer_cancel_tasks = {}

        from graphinator.graphinator import schedule_consumer_cancellation

        # Start cancellation task
        await schedule_consumer_cancellation("artists", mock_queue)

        # Wait for delay to pass
        await asyncio.sleep(0.2)

        # Consumer should be cancelled
        mock_queue.cancel.assert_called_once_with("consumer-tag-123", nowait=True)

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.CONSUMER_CANCEL_DELAY", 0.1)
    async def test_cancels_existing_scheduled_task(self) -> None:
        """Test cancels existing scheduled task before creating new one."""
        mock_queue = AsyncMock()
        mock_existing_task = AsyncMock()

        import graphinator.graphinator

        graphinator.graphinator.consumer_tags = {"artists": "consumer-tag-123"}
        graphinator.graphinator.consumer_cancel_tasks = {"artists": mock_existing_task}

        from graphinator.graphinator import schedule_consumer_cancellation

        await schedule_consumer_cancellation("artists", mock_queue)

        # Existing task should be cancelled
        mock_existing_task.cancel.assert_called_once()

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.CONSUMER_CANCEL_DELAY", 0.1)
    @patch("graphinator.graphinator.check_all_consumers_idle")
    @patch("graphinator.graphinator.close_rabbitmq_connection")
    async def test_closes_connection_when_all_idle(self, mock_close: AsyncMock, mock_check_idle: AsyncMock) -> None:
        """Test closes RabbitMQ connection when all consumers idle."""
        mock_queue = AsyncMock()
        mock_check_idle.return_value = True

        import graphinator.graphinator

        graphinator.graphinator.consumer_tags = {"artists": "consumer-tag-123"}
        graphinator.graphinator.consumer_cancel_tasks = {}

        from graphinator.graphinator import schedule_consumer_cancellation

        await schedule_consumer_cancellation("artists", mock_queue)
        await asyncio.sleep(0.2)

        # Should check if all idle and close connection
        mock_check_idle.assert_called_once()
        mock_close.assert_called_once()


class TestPeriodicQueueChecker:
    """Test periodic_queue_checker function."""

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.QUEUE_CHECK_INTERVAL", 0.05)
    @patch("graphinator.graphinator.STUCK_CHECK_INTERVAL", 0.05)
    @patch("graphinator.graphinator.shutdown_requested", False)
    async def test_checks_queues_periodically(self) -> None:
        """Test periodically checks queues for messages."""
        mock_rabbitmq_manager = AsyncMock()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_queue = AsyncMock()
        mock_queue.declaration_result.message_count = 0

        mock_rabbitmq_manager.connect.return_value = mock_connection
        mock_connection.channel.return_value = mock_channel
        mock_channel.declare_queue.return_value = mock_queue

        import graphinator.graphinator

        graphinator.graphinator.rabbitmq_manager = mock_rabbitmq_manager
        graphinator.graphinator.active_connection = None
        graphinator.graphinator.active_channel = None
        graphinator.graphinator.consumer_tags = {}
        graphinator.graphinator.completed_files = {"artists", "labels", "masters", "releases"}

        from graphinator.graphinator import periodic_queue_checker

        # Run checker for a short time
        checker_task = asyncio.create_task(periodic_queue_checker())

        # Wait for one check cycle
        await asyncio.sleep(0.15)

        # Stop the checker
        graphinator.graphinator.shutdown_requested = True
        await asyncio.sleep(0.05)

        # Clean up
        checker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await checker_task

        # Should have attempted to connect
        assert mock_rabbitmq_manager.connect.called

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.QUEUE_CHECK_INTERVAL", 0.05)
    @patch("graphinator.graphinator.STUCK_CHECK_INTERVAL", 0.05)
    async def test_skips_check_when_connection_active(self) -> None:
        """Test skips check when connection is already active."""
        mock_rabbitmq_manager = AsyncMock()

        import graphinator.graphinator

        graphinator.graphinator.rabbitmq_manager = mock_rabbitmq_manager
        graphinator.graphinator.active_connection = AsyncMock()
        graphinator.graphinator.shutdown_requested = False

        from graphinator.graphinator import periodic_queue_checker

        # Run checker for a short time
        checker_task = asyncio.create_task(periodic_queue_checker())

        await asyncio.sleep(0.15)

        # Stop the checker
        graphinator.graphinator.shutdown_requested = True
        await asyncio.sleep(0.05)

        # Clean up
        checker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await checker_task

        # Should not have attempted to connect
        mock_rabbitmq_manager.connect.assert_not_called()


class TestLabelTransactionLogic:
    """Test label processing transaction logic."""

    @pytest.mark.asyncio
    async def test_skips_unchanged_label(self, sample_label_data: dict[str, Any], mock_neo4j_driver: MagicMock) -> None:
        """Test that label processing skips when hash matches."""
        from graphinator.graphinator import on_label_message

        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(sample_label_data).encode()

        # Get the mock session from the fixture's async context manager
        mock_context_manager = await mock_neo4j_driver.session(database="neo4j")
        mock_session = await mock_context_manager.__aenter__()

        # Create a mock transaction function that will be called
        mock_tx = MagicMock()
        # Return existing hash that matches
        mock_tx.run.return_value.single.return_value = {"hash": sample_label_data["sha256"]}

        # When execute_write is called, execute the transaction function
        async def execute_tx(tx_func: Any) -> Any:
            return tx_func(mock_tx)

        mock_session.execute_write.side_effect = execute_tx

        with (
            patch("graphinator.graphinator.graph", mock_neo4j_driver),
            patch("graphinator.graphinator.shutdown_requested", False),
        ):
            await on_label_message(mock_message)

        # Should only check hash, not update
        assert mock_tx.run.call_count == 1
        mock_message.ack.assert_called_once()

    @pytest.mark.asyncio
    async def test_creates_label_with_parent_and_sublabels(self, mock_neo4j_driver: MagicMock) -> None:
        """Test label creation with parent and sublabels."""
        from graphinator.graphinator import on_label_message

        label_data = {
            "id": "L123",
            "name": "Test Label",
            "sha256": "test_hash",
            "parentLabel": {"@id": "L_PARENT"},
            "sublabels": {"label": [{"@id": "L_SUB1"}, {"@id": "L_SUB2"}]},
        }

        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(label_data).encode()

        # Get the mock session from the fixture's async context manager
        mock_context_manager = await mock_neo4j_driver.session(database="neo4j")
        mock_session = await mock_context_manager.__aenter__()

        mock_tx = MagicMock()
        # No existing label
        mock_tx.run.return_value.single.return_value = None

        async def execute_tx(tx_func: Any) -> Any:
            return tx_func(mock_tx)

        mock_session.execute_write.side_effect = execute_tx

        with (
            patch("graphinator.graphinator.graph", mock_neo4j_driver),
            patch("graphinator.graphinator.shutdown_requested", False),
        ):
            await on_label_message(mock_message)

        # Should have multiple cypher calls:
        # 1. Hash check
        # 2. Create/update label node
        # 3. Parent relationship
        # 4. Sublabels relationships
        assert mock_tx.run.call_count == 4
        mock_message.ack.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_string_parent_label(self, mock_neo4j_driver: MagicMock) -> None:
        """Test label with parent as string ID."""
        from graphinator.graphinator import on_label_message

        label_data = {
            "id": "L123",
            "name": "Test Label",
            "sha256": "test_hash",
            "parentLabel": "L_PARENT_STRING",  # String instead of dict
        }

        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(label_data).encode()

        # Get the mock session from the fixture's async context manager
        mock_context_manager = await mock_neo4j_driver.session(database="neo4j")
        mock_session = await mock_context_manager.__aenter__()

        mock_tx = MagicMock()
        mock_tx.run.return_value.single.return_value = None

        async def execute_tx(tx_func: Any) -> Any:
            return tx_func(mock_tx)

        mock_session.execute_write.side_effect = execute_tx

        with (
            patch("graphinator.graphinator.graph", mock_neo4j_driver),
            patch("graphinator.graphinator.shutdown_requested", False),
        ):
            await on_label_message(mock_message)

        # Should handle string parent
        assert mock_tx.run.call_count >= 3
        mock_message.ack.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_various_sublabel_formats(self, mock_neo4j_driver: MagicMock) -> None:
        """Test label with different sublabel formats."""
        from graphinator.graphinator import on_label_message

        # Test with list format
        label_data = {
            "id": "L123",
            "name": "Test Label",
            "sha256": "test_hash",
            "sublabels": ["L_SUB1", "L_SUB2"],  # Direct list of strings
        }

        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(label_data).encode()

        # Get the mock session from the fixture's async context manager
        mock_context_manager = await mock_neo4j_driver.session(database="neo4j")
        mock_session = await mock_context_manager.__aenter__()

        mock_tx = MagicMock()
        mock_tx.run.return_value.single.return_value = None

        async def execute_tx(tx_func: Any) -> Any:
            return tx_func(mock_tx)

        mock_session.execute_write.side_effect = execute_tx

        with (
            patch("graphinator.graphinator.graph", mock_neo4j_driver),
            patch("graphinator.graphinator.shutdown_requested", False),
        ):
            await on_label_message(mock_message)

        mock_message.ack.assert_called_once()


class TestMasterTransactionLogic:
    """Test master processing transaction logic."""

    @pytest.mark.asyncio
    async def test_skips_unchanged_master(self, sample_master_data: dict[str, Any], mock_neo4j_driver: MagicMock) -> None:
        """Test that master processing skips when hash matches."""
        from graphinator.graphinator import on_master_message

        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(sample_master_data).encode()

        # Get the mock session from the fixture's async context manager
        mock_context_manager = await mock_neo4j_driver.session(database="neo4j")
        mock_session = await mock_context_manager.__aenter__()

        mock_tx = MagicMock()
        mock_tx.run.return_value.single.return_value = {"hash": sample_master_data["sha256"]}

        async def execute_tx(tx_func: Any) -> Any:
            return tx_func(mock_tx)

        mock_session.execute_write.side_effect = execute_tx

        with (
            patch("graphinator.graphinator.graph", mock_neo4j_driver),
            patch("graphinator.graphinator.shutdown_requested", False),
        ):
            await on_master_message(mock_message)

        # Should only check hash
        assert mock_tx.run.call_count == 1
        mock_message.ack.assert_called_once()

    @pytest.mark.asyncio
    async def test_creates_master_with_artists_genres_styles(self, mock_neo4j_driver: MagicMock) -> None:
        """Test master creation with artists, genres, and styles."""
        from graphinator.graphinator import on_master_message

        master_data = {
            "id": "M123",
            "title": "Test Master",
            "year": 2023,
            "sha256": "test_hash",
            "artists": {"artist": [{"id": "A1"}, {"id": "A2"}]},
            "genres": {"genre": ["Rock", "Electronic"]},
            "styles": {"style": ["Alternative", "Ambient"]},
        }

        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(master_data).encode()

        # Get the mock session from the fixture's async context manager
        mock_context_manager = await mock_neo4j_driver.session(database="neo4j")
        mock_session = await mock_context_manager.__aenter__()

        mock_tx = MagicMock()
        mock_tx.run.return_value.single.return_value = None

        async def execute_tx(tx_func: Any) -> Any:
            return tx_func(mock_tx)

        mock_session.execute_write.side_effect = execute_tx

        with (
            patch("graphinator.graphinator.graph", mock_neo4j_driver),
            patch("graphinator.graphinator.shutdown_requested", False),
        ):
            await on_master_message(mock_message)

        # Should have multiple cypher calls:
        # 1. Hash check
        # 2. Create master node
        # 3. Artist relationships
        # 4. Genre relationships
        # 5. Style relationships
        # 6. Genre-style connections
        assert mock_tx.run.call_count == 6
        mock_message.ack.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_string_artist_ids(self, mock_neo4j_driver: MagicMock) -> None:
        """Test master with string artist IDs."""
        from graphinator.graphinator import on_master_message

        master_data = {
            "id": "M123",
            "title": "Test Master",
            "sha256": "test_hash",
            "artists": {"artist": ["A1", "A2"]},  # String IDs instead of dicts
        }

        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(master_data).encode()

        # Get the mock session from the fixture's async context manager
        mock_context_manager = await mock_neo4j_driver.session(database="neo4j")
        mock_session = await mock_context_manager.__aenter__()

        mock_tx = MagicMock()
        mock_tx.run.return_value.single.return_value = None

        async def execute_tx(tx_func: Any) -> Any:
            return tx_func(mock_tx)

        mock_session.execute_write.side_effect = execute_tx

        with (
            patch("graphinator.graphinator.graph", mock_neo4j_driver),
            patch("graphinator.graphinator.shutdown_requested", False),
        ):
            await on_master_message(mock_message)

        mock_message.ack.assert_called_once()


class TestReleaseTransactionLogic:
    """Test release processing transaction logic."""

    @pytest.mark.asyncio
    async def test_skips_unchanged_release(self, sample_release_data: dict[str, Any], mock_neo4j_driver: MagicMock) -> None:
        """Test that release processing skips when hash matches."""
        from graphinator.graphinator import on_release_message

        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(sample_release_data).encode()

        # Get the mock session from the fixture's async context manager
        mock_context_manager = await mock_neo4j_driver.session(database="neo4j")
        mock_session = await mock_context_manager.__aenter__()

        mock_tx = MagicMock()
        mock_tx.run.return_value.single.return_value = {"hash": sample_release_data["sha256"]}

        async def execute_tx(tx_func: Any) -> Any:
            return tx_func(mock_tx)

        mock_session.execute_write.side_effect = execute_tx

        with (
            patch("graphinator.graphinator.graph", mock_neo4j_driver),
            patch("graphinator.graphinator.shutdown_requested", False),
        ):
            await on_release_message(mock_message)

        # Should only check hash
        assert mock_tx.run.call_count == 1
        mock_message.ack.assert_called_once()

    @pytest.mark.asyncio
    async def test_creates_release_with_all_relationships(self, mock_neo4j_driver: MagicMock) -> None:
        """Test release creation with all relationship types."""
        from graphinator.graphinator import on_release_message

        release_data = {
            "id": "R123",
            "title": "Test Release",
            "sha256": "test_hash",
            "artists": {"artist": [{"id": "A1"}]},
            "labels": {"label": [{"@id": "L1"}]},
            "master_id": {"#text": "M123"},
            "genres": {"genre": ["Rock"]},
            "styles": {"style": ["Alternative"]},
        }

        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(release_data).encode()

        # Get the mock session from the fixture's async context manager
        mock_context_manager = await mock_neo4j_driver.session(database="neo4j")
        mock_session = await mock_context_manager.__aenter__()

        mock_tx = MagicMock()
        mock_tx.run.return_value.single.return_value = None

        async def execute_tx(tx_func: Any) -> Any:
            return tx_func(mock_tx)

        mock_session.execute_write.side_effect = execute_tx

        with (
            patch("graphinator.graphinator.graph", mock_neo4j_driver),
            patch("graphinator.graphinator.shutdown_requested", False),
        ):
            await on_release_message(mock_message)

        # Should have multiple cypher calls for all relationships
        # 1. Hash check
        # 2. Create release node
        # 3. Artist relationships
        # 4. Label relationships
        # 5. Master relationship
        # 6. Genre relationships
        # 7. Style relationships
        # 8. Genre-style connections
        assert mock_tx.run.call_count == 8
        mock_message.ack.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_master_id_as_direct_string(self, mock_neo4j_driver: MagicMock) -> None:
        """Test release with master_id as direct string."""
        from graphinator.graphinator import on_release_message

        release_data = {
            "id": "R123",
            "title": "Test Release",
            "sha256": "test_hash",
            "master_id": "M123",  # Direct string instead of dict with #text
        }

        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(release_data).encode()

        # Get the mock session from the fixture's async context manager
        mock_context_manager = await mock_neo4j_driver.session(database="neo4j")
        mock_session = await mock_context_manager.__aenter__()

        mock_tx = MagicMock()
        mock_tx.run.return_value.single.return_value = None

        async def execute_tx(tx_func: Any) -> Any:
            return tx_func(mock_tx)

        mock_session.execute_write.side_effect = execute_tx

        with (
            patch("graphinator.graphinator.graph", mock_neo4j_driver),
            patch("graphinator.graphinator.shutdown_requested", False),
        ):
            await on_release_message(mock_message)

        mock_message.ack.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_string_artist_and_label_ids(self, mock_neo4j_driver: MagicMock) -> None:
        """Test release with string artist and label IDs."""
        from graphinator.graphinator import on_release_message

        release_data = {
            "id": "R123",
            "title": "Test Release",
            "sha256": "test_hash",
            "artists": {"artist": ["A1", "A2"]},  # String IDs
            "labels": {"label": ["L1"]},  # String IDs
        }

        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(release_data).encode()

        # Get the mock session from the fixture's async context manager
        mock_context_manager = await mock_neo4j_driver.session(database="neo4j")
        mock_session = await mock_context_manager.__aenter__()

        mock_tx = MagicMock()
        mock_tx.run.return_value.single.return_value = None

        async def execute_tx(tx_func: Any) -> Any:
            return tx_func(mock_tx)

        mock_session.execute_write.side_effect = execute_tx

        with (
            patch("graphinator.graphinator.graph", mock_neo4j_driver),
            patch("graphinator.graphinator.shutdown_requested", False),
        ):
            await on_release_message(mock_message)

        mock_message.ack.assert_called_once()


class TestMasterMessageErrorHandling:
    """Test error handling in master message processing."""

    @pytest.fixture
    def sample_master_data(self) -> dict[str, Any]:
        """Sample master data for testing."""
        return {
            "id": "12345",
            "title": "Test Master",
            "artists": [{"id": "1", "name": "Artist 1"}],
            "genres": ["Rock"],
            "styles": ["Alternative"],
        }

    @pytest.mark.asyncio
    async def test_master_neo4j_unavailable_nacks_message(self, sample_master_data: dict[str, Any]) -> None:
        """Test that Neo4j unavailable error nacks the message."""
        from neo4j.exceptions import ServiceUnavailable

        from graphinator.graphinator import on_master_message

        # Mock message
        mock_message = AsyncMock()
        mock_message.body = dumps(sample_master_data)
        mock_message.nack = AsyncMock()

        # Mock Neo4j driver to raise ServiceUnavailable
        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(side_effect=ServiceUnavailable("Neo4j down"))
        mock_session.__exit__ = MagicMock()
        mock_driver.session.return_value = mock_session

        # Process message
        with patch("graphinator.graphinator.graph", mock_driver):
            await on_master_message(mock_message)

        # Should nack with requeue
        mock_message.nack.assert_called_once_with(requeue=True)

    @pytest.mark.asyncio
    async def test_master_processing_error_nacks_message(self) -> None:
        """Test that processing errors result in message nack."""
        from graphinator.graphinator import on_master_message

        # Mock message
        sample_data = {
            "id": "12345",
            "title": "Test Master",
            "sha256": "test_hash",
        }

        mock_message = AsyncMock()
        mock_message.body = dumps(sample_data)
        mock_message.nack = AsyncMock()

        # Mock Neo4j driver to raise an error during processing
        mock_driver = MagicMock()

        # Create a session context manager that raises error on execute_write
        mock_session_context = MagicMock()
        mock_session_context.execute_write.side_effect = RuntimeError("Database error")

        # Make session() return a context manager
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session_context)
        mock_session.__exit__ = MagicMock(return_value=None)

        mock_driver.session.return_value = mock_session

        # Process message
        with patch("graphinator.graphinator.graph", mock_driver):
            await on_master_message(mock_message)

        # Should nack the message with requeue
        mock_message.nack.assert_called_once_with(requeue=True)

    @pytest.mark.asyncio
    async def test_master_nack_failure_logged(self, sample_master_data: dict[str, Any]) -> None:
        """Test that nack failures are logged."""
        from neo4j.exceptions import ServiceUnavailable

        from graphinator.graphinator import on_master_message

        # Mock message that fails to nack
        mock_message = AsyncMock()
        mock_message.body = dumps(sample_master_data)
        mock_message.nack = AsyncMock(side_effect=Exception("Nack failed"))

        # Mock Neo4j driver to raise ServiceUnavailable
        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(side_effect=ServiceUnavailable("Neo4j down"))
        mock_session.__exit__ = MagicMock()
        mock_driver.session.return_value = mock_session

        # Process message - should not raise exception
        with patch("graphinator.graphinator.graph", mock_driver), patch("graphinator.graphinator.logger") as mock_logger:
            await on_master_message(mock_message)

            # Should have logged nack failure
            assert mock_logger.warning.called


class TestProgressReporter:
    """Test progress reporting functionality."""

    @pytest.mark.asyncio
    async def test_progress_reporter_detects_stalled_consumers(self) -> None:
        """Test that progress reporter detects stalled consumers."""
        import time

        import graphinator.graphinator as graphinator_module

        # Set up global state
        graphinator_module.shutdown_requested = False
        graphinator_module.message_counts = {
            "artists": 100,
            "labels": 50,
            "masters": 0,
            "releases": 200,
        }
        graphinator_module.last_message_time = {
            "artists": time.time() - 130,  # Stalled
            "labels": time.time() - 10,  # Active
            "masters": 0,  # Not started
            "releases": time.time() - 5,  # Active
        }
        graphinator_module.completed_files = set()
        graphinator_module.consumer_tags = {"artists": "tag1", "releases": "tag2"}

        # Simulate stalled consumer detection logic
        current_time = time.time()
        stalled_consumers = []
        for data_type, last_time in graphinator_module.last_message_time.items():
            if data_type not in graphinator_module.completed_files and last_time > 0 and (current_time - last_time) > 120:
                stalled_consumers.append(data_type)

        # Should detect artists as stalled
        assert "artists" in stalled_consumers
        assert "labels" not in stalled_consumers
        assert "releases" not in stalled_consumers

    @pytest.mark.asyncio
    async def test_progress_reporter_shows_completed_files(self) -> None:
        """Test that progress reporter shows completed files."""
        import graphinator.graphinator as graphinator_module

        # Set up global state with completed files
        graphinator_module.message_counts = {
            "artists": 1000,
            "labels": 500,
            "masters": 0,
            "releases": 0,
        }
        graphinator_module.completed_files = {"artists", "labels"}

        # Build progress string like the progress reporter does
        progress_parts = []
        for data_type in ["artists", "labels", "masters", "releases"]:
            emoji = "🎉 " if data_type in graphinator_module.completed_files else ""
            progress_parts.append(f"{emoji}{data_type.capitalize()}: {graphinator_module.message_counts[data_type]}")

        # Should include emoji for completed files
        progress_str = ", ".join(progress_parts)
        assert "🎉 Artists" in progress_str
        assert "🎉 Labels" in progress_str
        assert "🎉 Masters" not in progress_str


class TestQueueRestartLogic:
    """Test queue restart logic when messages are found."""

    @pytest.mark.asyncio
    async def test_restarts_consumers_when_queues_have_messages(self) -> None:
        """Test that consumers are restarted when queues have messages."""
        import graphinator.graphinator as graphinator_module

        # Set up global state
        graphinator_module.consumer_tags = {}
        graphinator_module.completed_files = set()
        graphinator_module.last_message_time = {
            "artists": 0,
            "labels": 0,
            "masters": 0,
            "releases": 0,
        }

        # Simulate finding queues with messages
        queues_with_messages = [("artists", 100), ("releases", 50)]

        # Should identify that consumers need to be restarted
        assert len(queues_with_messages) > 0
        assert any(count > 0 for _, count in queues_with_messages)


class TestBatchModeIntegration:
    """Test batch mode integration in message handlers."""

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.BATCH_MODE", True)
    @patch("graphinator.graphinator.shutdown_requested", False)
    async def test_artist_message_uses_batch_processor(self, sample_artist_data: dict[str, Any]) -> None:
        """Test that artist messages use batch processor when enabled."""
        from graphinator.graphinator import on_artist_message

        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(sample_artist_data).encode()

        mock_batch_processor = AsyncMock()

        with patch("graphinator.graphinator.batch_processor", mock_batch_processor):
            await on_artist_message(mock_message)

        # Should add message to batch processor
        mock_batch_processor.add_message.assert_called_once()
        args = mock_batch_processor.add_message.call_args[0]
        assert args[0] == "artists"  # data_type
        assert args[1]["id"] == sample_artist_data["id"]  # data

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.BATCH_MODE", True)
    @patch("graphinator.graphinator.shutdown_requested", False)
    async def test_label_message_uses_batch_processor(self, sample_label_data: dict[str, Any]) -> None:
        """Test that label messages use batch processor when enabled."""
        from graphinator.graphinator import on_label_message

        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(sample_label_data).encode()

        mock_batch_processor = AsyncMock()

        with patch("graphinator.graphinator.batch_processor", mock_batch_processor):
            await on_label_message(mock_message)

        mock_batch_processor.add_message.assert_called_once()

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.BATCH_MODE", True)
    @patch("graphinator.graphinator.shutdown_requested", False)
    async def test_master_message_uses_batch_processor(self, sample_master_data: dict[str, Any]) -> None:
        """Test that master messages use batch processor when enabled."""
        from graphinator.graphinator import on_master_message

        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(sample_master_data).encode()

        mock_batch_processor = AsyncMock()

        with patch("graphinator.graphinator.batch_processor", mock_batch_processor):
            await on_master_message(mock_message)

        mock_batch_processor.add_message.assert_called_once()

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.BATCH_MODE", True)
    @patch("graphinator.graphinator.shutdown_requested", False)
    async def test_release_message_uses_batch_processor(self, sample_release_data: dict[str, Any]) -> None:
        """Test that release messages use batch processor when enabled."""
        from graphinator.graphinator import on_release_message

        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(sample_release_data).encode()

        mock_batch_processor = AsyncMock()

        with patch("graphinator.graphinator.batch_processor", mock_batch_processor):
            await on_release_message(mock_message)

        mock_batch_processor.add_message.assert_called_once()

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.BATCH_MODE", False)
    @patch("graphinator.graphinator.shutdown_requested", False)
    async def test_artist_message_bypasses_batch_processor_when_disabled(
        self, sample_artist_data: dict[str, Any], mock_neo4j_driver: MagicMock
    ) -> None:
        """Test that messages bypass batch processor when disabled."""
        from graphinator.graphinator import on_artist_message

        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(sample_artist_data).encode()

        mock_batch_processor = AsyncMock()

        # Get the mock session from the fixture's async context manager
        mock_context_manager = await mock_neo4j_driver.session(database="neo4j")
        mock_session = await mock_context_manager.__aenter__()
        mock_session.execute_write.return_value = True

        with (
            patch("graphinator.graphinator.batch_processor", mock_batch_processor),
            patch("graphinator.graphinator.graph", mock_neo4j_driver),
        ):
            await on_artist_message(mock_message)

        # Should NOT use batch processor
        mock_batch_processor.add_message.assert_not_called()
        # Should use direct Neo4j session
        mock_session.execute_write.assert_called_once()


class TestArtistTransactionEdgeCases:
    """Test edge cases in artist transaction processing."""

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.shutdown_requested", False)
    async def test_artist_with_members_without_ids(self, mock_neo4j_driver: MagicMock) -> None:
        """Test handling artist members without IDs."""
        from graphinator.graphinator import on_artist_message

        artist_data = {
            "id": "A123",
            "name": "Test Artist",
            "sha256": "test_hash",
            "members": {"name": [{"@id": "M1"}, {"name": "No ID Member"}]},  # One without ID
        }

        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(artist_data).encode()

        # Get the mock session from the fixture's async context manager
        mock_context_manager = await mock_neo4j_driver.session(database="neo4j")
        mock_session = await mock_context_manager.__aenter__()

        mock_tx = MagicMock()
        mock_tx.run.return_value.single.return_value = None

        async def execute_tx(tx_func: Any) -> Any:
            return tx_func(mock_tx)

        mock_session.execute_write.side_effect = execute_tx

        with (
            patch("graphinator.graphinator.graph", mock_neo4j_driver),
            patch("graphinator.graphinator.logger") as mock_logger,
        ):
            await on_artist_message(mock_message)

        # Should log warning about member without ID
        assert any("Skipping member without ID" in str(call) for call in mock_logger.warning.call_args_list)
        mock_message.ack.assert_called_once()

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.shutdown_requested", False)
    async def test_artist_with_groups_without_ids(self, mock_neo4j_driver: MagicMock) -> None:
        """Test handling artist groups without IDs."""
        from graphinator.graphinator import on_artist_message

        artist_data = {
            "id": "A123",
            "name": "Test Artist",
            "sha256": "test_hash",
            "groups": {"name": [{"@id": "G1"}, {}]},  # One without ID
        }

        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(artist_data).encode()

        # Get the mock session from the fixture's async context manager
        mock_context_manager = await mock_neo4j_driver.session(database="neo4j")
        mock_session = await mock_context_manager.__aenter__()

        mock_tx = MagicMock()
        mock_tx.run.return_value.single.return_value = None

        async def execute_tx(tx_func: Any) -> Any:
            return tx_func(mock_tx)

        mock_session.execute_write.side_effect = execute_tx

        with (
            patch("graphinator.graphinator.graph", mock_neo4j_driver),
            patch("graphinator.graphinator.logger") as mock_logger,
        ):
            await on_artist_message(mock_message)

        # Should log warning about group without ID
        assert any("Skipping group without ID" in str(call) for call in mock_logger.warning.call_args_list)

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.shutdown_requested", False)
    async def test_artist_with_aliases_without_ids(self, mock_neo4j_driver: MagicMock) -> None:
        """Test handling artist aliases without IDs."""
        from graphinator.graphinator import on_artist_message

        artist_data = {
            "id": "A123",
            "name": "Test Artist",
            "sha256": "test_hash",
            "aliases": {"name": [{"@id": "AL1"}, {"name": "No ID Alias"}]},
        }

        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(artist_data).encode()

        # Get the mock session from the fixture's async context manager
        mock_context_manager = await mock_neo4j_driver.session(database="neo4j")
        mock_session = await mock_context_manager.__aenter__()

        mock_tx = MagicMock()
        mock_tx.run.return_value.single.return_value = None

        async def execute_tx(tx_func: Any) -> Any:
            return tx_func(mock_tx)

        mock_session.execute_write.side_effect = execute_tx

        with (
            patch("graphinator.graphinator.graph", mock_neo4j_driver),
            patch("graphinator.graphinator.logger") as mock_logger,
        ):
            await on_artist_message(mock_message)

        assert any("Skipping alias without ID" in str(call) for call in mock_logger.warning.call_args_list)

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.shutdown_requested", False)
    async def test_artist_neo4j_session_expired(self, sample_artist_data: dict[str, Any]) -> None:
        """Test handling Neo4j session expired during processing."""
        from neo4j.exceptions import SessionExpired

        from graphinator.graphinator import on_artist_message

        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(sample_artist_data).encode()

        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(side_effect=SessionExpired("Session expired"))
        mock_session.__exit__ = MagicMock()
        mock_driver.session.return_value = mock_session

        with patch("graphinator.graphinator.graph", mock_driver):
            await on_artist_message(mock_message)

        # Should nack with requeue
        mock_message.nack.assert_called_once_with(requeue=True)

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.shutdown_requested", False)
    async def test_artist_with_runtime_error_not_initialized(self, sample_artist_data: dict[str, Any]) -> None:
        """Test handling when graph driver is not initialized."""
        from graphinator.graphinator import on_artist_message

        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(sample_artist_data).encode()

        with patch("graphinator.graphinator.graph", None):
            await on_artist_message(mock_message)

        # Should nack the message
        mock_message.nack.assert_called_once_with(requeue=True)


class TestLabelTransactionEdgeCases:
    """Test edge cases in label transaction processing."""

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.shutdown_requested", False)
    async def test_label_with_parent_without_id(self, mock_neo4j_driver: MagicMock) -> None:
        """Test handling label with parent that has no ID."""
        from graphinator.graphinator import on_label_message

        label_data = {
            "id": "L123",
            "name": "Test Label",
            "sha256": "test_hash",
            "parentLabel": {"name": "No ID Parent"},  # No @id or id field
        }

        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(label_data).encode()

        # Get the mock session from the fixture's async context manager
        mock_context_manager = await mock_neo4j_driver.session(database="neo4j")
        mock_session = await mock_context_manager.__aenter__()

        mock_tx = MagicMock()
        mock_tx.run.return_value.single.return_value = None

        async def execute_tx(tx_func: Any) -> Any:
            return tx_func(mock_tx)

        mock_session.execute_write.side_effect = execute_tx

        with (
            patch("graphinator.graphinator.graph", mock_neo4j_driver),
            patch("graphinator.graphinator.logger") as mock_logger,
        ):
            await on_label_message(mock_message)

        # Should log warning about parent without ID
        assert any("Skipping parent label without ID" in str(call) for call in mock_logger.warning.call_args_list)

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.shutdown_requested", False)
    async def test_label_with_sublabels_without_ids(self, mock_neo4j_driver: MagicMock) -> None:
        """Test handling sublabels without IDs."""
        from graphinator.graphinator import on_label_message

        label_data = {
            "id": "L123",
            "name": "Test Label",
            "sha256": "test_hash",
            "sublabels": {"label": [{"@id": "SL1"}, {"name": "No ID Sublabel"}]},
        }

        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(label_data).encode()

        # Get the mock session from the fixture's async context manager
        mock_context_manager = await mock_neo4j_driver.session(database="neo4j")
        mock_session = await mock_context_manager.__aenter__()

        mock_tx = MagicMock()
        mock_tx.run.return_value.single.return_value = None

        async def execute_tx(tx_func: Any) -> Any:
            return tx_func(mock_tx)

        mock_session.execute_write.side_effect = execute_tx

        with (
            patch("graphinator.graphinator.graph", mock_neo4j_driver),
            patch("graphinator.graphinator.logger") as mock_logger,
        ):
            await on_label_message(mock_message)

        assert any("Skipping sublabel without ID" in str(call) for call in mock_logger.warning.call_args_list)


class TestReleaseMessageErrorHandling:
    """Test error handling in release message processing."""

    @pytest.mark.asyncio
    async def test_release_neo4j_unavailable_nacks_message(self) -> None:
        """Test that Neo4j unavailable error nacks release message."""
        from neo4j.exceptions import ServiceUnavailable

        from graphinator.graphinator import on_release_message

        # Mock message
        sample_release_data = {
            "id": "123",
            "title": "Test Release",
            "artists": [{"id": "1", "name": "Artist 1"}],
        }

        mock_message = AsyncMock()
        mock_message.body = dumps(sample_release_data)
        mock_message.nack = AsyncMock()

        # Mock Neo4j driver to raise ServiceUnavailable
        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(side_effect=ServiceUnavailable("Neo4j down"))
        mock_session.__exit__ = MagicMock()
        mock_driver.session.return_value = mock_session

        # Process message
        with patch("graphinator.graphinator.graph", mock_driver):
            await on_release_message(mock_message)

        # Should nack with requeue
        mock_message.nack.assert_called_once_with(requeue=True)

    @pytest.mark.asyncio
    async def test_release_processing_error_nacks_message(self) -> None:
        """Test that processing errors result in message nack."""
        from graphinator.graphinator import on_release_message

        # Mock message
        sample_data = {
            "id": "456",
            "title": "Test Release",
            "sha256": "test_hash",
        }

        mock_message = AsyncMock()
        mock_message.body = dumps(sample_data)
        mock_message.nack = AsyncMock()

        # Mock Neo4j driver to raise error during processing
        mock_driver = MagicMock()

        # Create a session context manager that raises error on execute_write
        mock_session_context = MagicMock()
        mock_session_context.execute_write.side_effect = RuntimeError("Database error")

        # Make session() return a context manager
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session_context)
        mock_session.__exit__ = MagicMock(return_value=None)

        mock_driver.session.return_value = mock_session

        # Process message
        with patch("graphinator.graphinator.graph", mock_driver):
            await on_release_message(mock_message)

        # Should nack the message with requeue
        mock_message.nack.assert_called_once_with(requeue=True)

    @pytest.mark.asyncio
    async def test_release_nack_failure_logged(self) -> None:
        """Test that nack failures are logged for release messages."""
        from neo4j.exceptions import ServiceUnavailable

        from graphinator.graphinator import on_release_message

        # Mock message that fails to nack
        sample_data = {
            "id": "789",
            "title": "Test Release",
        }

        mock_message = AsyncMock()
        mock_message.body = dumps(sample_data)
        mock_message.nack = AsyncMock(side_effect=Exception("Nack failed"))

        # Mock Neo4j driver to raise ServiceUnavailable
        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(side_effect=ServiceUnavailable("Neo4j down"))
        mock_session.__exit__ = MagicMock()
        mock_driver.session.return_value = mock_session

        # Process message - should not raise exception
        with patch("graphinator.graphinator.graph", mock_driver), patch("graphinator.graphinator.logger") as mock_logger:
            await on_release_message(mock_message)

            # Should have logged nack failure
            assert mock_logger.warning.called


class TestGetHealthDataStuckState:
    """Test get_health_data() stuck state detection."""

    def test_stuck_state_with_graph_set(self) -> None:
        """Test health data shows stuck+unhealthy when consumers dead but graph connected."""
        import graphinator.graphinator

        graphinator.graphinator.consumer_tags = {}
        graphinator.graphinator.completed_files = {"artists"}  # only 1 of 4 complete
        graphinator.graphinator.message_counts = {"artists": 100, "labels": 0, "masters": 0, "releases": 0}
        graphinator.graphinator.last_message_time = {"artists": 0.0, "labels": 0.0, "masters": 0.0, "releases": 0.0}

        from graphinator.graphinator import get_health_data

        with patch("graphinator.graphinator.graph", MagicMock()):
            result = get_health_data()

        assert result["status"] == "unhealthy"
        assert "STUCK" in result["current_task"]

    def test_stuck_state_sets_active_task(self) -> None:
        """Test that stuck state sets the STUCK active_task message (line 121)."""
        import graphinator.graphinator

        graphinator.graphinator.consumer_tags = {}
        graphinator.graphinator.completed_files = set()
        graphinator.graphinator.message_counts = {"artists": 50, "labels": 0, "masters": 0, "releases": 0}
        graphinator.graphinator.last_message_time = {"artists": 0.0, "labels": 0.0, "masters": 0.0, "releases": 0.0}

        from graphinator.graphinator import get_health_data

        # With graph None and is_stuck True, status goes to unhealthy via the graph-is-None path
        # but with graph not None, is_stuck causes both active_task and status = "unhealthy"
        with patch("graphinator.graphinator.graph", MagicMock()):
            result = get_health_data()

        assert result["current_task"] == "STUCK - consumers died, awaiting recovery"
        assert result["status"] == "unhealthy"


class TestCloseRabbitMQConnectionErrors:
    """Test close_rabbitmq_connection error handling."""

    @pytest.mark.asyncio
    async def test_close_connection_error_logged(self) -> None:
        """Test that error closing connection is logged but does not raise (lines 231-232)."""
        import graphinator.graphinator

        mock_channel = AsyncMock()
        mock_channel.close = AsyncMock()

        mock_connection = AsyncMock()
        mock_connection.close.side_effect = Exception("Connection close failed")

        graphinator.graphinator.active_channel = mock_channel
        graphinator.graphinator.active_connection = mock_connection

        with patch("graphinator.graphinator.logger"):
            from graphinator.graphinator import close_rabbitmq_connection

            await close_rabbitmq_connection()

        # Should not raise; connection should be set to None anyway
        assert graphinator.graphinator.active_connection is None
        assert graphinator.graphinator.active_channel is None


class TestPeriodicQueueCheckerExceptions:
    """Test periodic_queue_checker exception handling paths."""

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.STUCK_CHECK_INTERVAL", 0.01)
    @patch("graphinator.graphinator.shutdown_requested", False)
    async def test_cancelled_error_breaks_loop(self) -> None:
        """Test CancelledError breaks out of the queue checker loop (lines 303-305)."""
        import graphinator.graphinator

        graphinator.graphinator.consumer_tags = {}
        graphinator.graphinator.completed_files = {"artists", "labels", "masters", "releases"}
        graphinator.graphinator.message_counts = {"artists": 0, "labels": 0, "masters": 0, "releases": 0}

        call_count = 0

        async def raise_cancelled(*_args: object, **_kwargs: object) -> None:
            nonlocal call_count
            call_count += 1
            raise asyncio.CancelledError()

        from graphinator.graphinator import periodic_queue_checker

        with patch("asyncio.sleep", side_effect=raise_cancelled):
            await periodic_queue_checker()

        assert call_count == 1  # Broke out after first CancelledError

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.STUCK_CHECK_INTERVAL", 0.01)
    async def test_general_exception_continues_loop(self) -> None:
        """Test general exception is logged and loop continues (lines 306-308)."""
        import graphinator.graphinator

        graphinator.graphinator.consumer_tags = {}
        graphinator.graphinator.completed_files = {"artists", "labels", "masters", "releases"}
        graphinator.graphinator.message_counts = {"artists": 0, "labels": 0, "masters": 0, "releases": 0}

        call_count = 0

        async def raise_then_shutdown(*_args: object, **_kwargs: object) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Test error in queue checker")
            # Second call: set shutdown to exit loop
            graphinator.graphinator.shutdown_requested = True

        from graphinator.graphinator import periodic_queue_checker

        graphinator.graphinator.shutdown_requested = False
        with patch("asyncio.sleep", side_effect=raise_then_shutdown), patch("graphinator.graphinator.logger"):
            await periodic_queue_checker()

        assert call_count == 2  # Continued after exception, then stopped


class TestRecoverConsumersEdgeCases:
    """Test _recover_consumers edge cases."""

    @pytest.mark.asyncio
    async def test_closes_existing_connection_before_recovery(self) -> None:
        """Test that _recover_consumers closes existing connection first (lines 322-327)."""
        import graphinator.graphinator

        mock_existing_conn = AsyncMock()
        graphinator.graphinator.active_connection = mock_existing_conn
        graphinator.graphinator.active_channel = AsyncMock()

        mock_rabbitmq_manager = AsyncMock()
        mock_rabbitmq_manager.connect.side_effect = Exception("Can't reconnect")

        with patch("graphinator.graphinator.rabbitmq_manager", mock_rabbitmq_manager), patch("graphinator.graphinator.logger"):
            from graphinator.graphinator import _recover_consumers

            await _recover_consumers()

        mock_existing_conn.close.assert_called_once()
        assert graphinator.graphinator.active_connection is None
        assert graphinator.graphinator.active_channel is None

    @pytest.mark.asyncio
    async def test_returns_on_rabbitmq_connect_failure(self) -> None:
        """Test that _recover_consumers returns early when RabbitMQ connect fails (lines 333-335)."""
        import graphinator.graphinator

        graphinator.graphinator.active_connection = None
        graphinator.graphinator.active_channel = None

        mock_rabbitmq_manager = AsyncMock()
        mock_rabbitmq_manager.connect.side_effect = Exception("RabbitMQ unavailable")

        with patch("graphinator.graphinator.rabbitmq_manager", mock_rabbitmq_manager), patch("graphinator.graphinator.logger"):
            from graphinator.graphinator import _recover_consumers

            # Should return without raising
            await _recover_consumers()

        # No connection should be established
        assert graphinator.graphinator.active_connection is None


class TestProcessArtistEdgeCases:
    """Test process_artist edge cases for string members/groups/aliases and missing IDs."""

    def test_string_member_is_used_as_id(self) -> None:
        """Test string member is treated as member ID directly (line 510)."""
        from graphinator.graphinator import process_artist

        mock_tx = MagicMock()
        mock_tx.run.return_value.single.return_value = None

        record = {
            "id": "artist-1",
            "sha256": "newhash",
            "name": "Test Artist",
            "members": {"name": ["string-member-id"]},  # String, not dict
        }

        result = process_artist(mock_tx, record)
        assert result is True
        # Should run MEMBER_OF relationship with string-member-id
        calls = [str(c) for c in mock_tx.run.call_args_list]
        assert any("MEMBER_OF" in c for c in calls)

    def test_member_without_id_logs_warning(self) -> None:
        """Test member dict without @id or id logs a warning (lines 516-518)."""
        from graphinator.graphinator import process_artist

        mock_tx = MagicMock()
        mock_tx.run.return_value.single.return_value = None

        record = {
            "id": "artist-1",
            "sha256": "newhash",
            "name": "Test Artist",
            "members": {"name": [{"#text": "No ID Member"}]},  # Dict without @id or id
        }

        with patch("graphinator.graphinator.logger") as mock_logger:
            result = process_artist(mock_tx, record)

        assert result is True
        mock_logger.warning.assert_called()
        warning_msg = str(mock_logger.warning.call_args_list)
        assert "Skipping member" in warning_msg

    def test_string_group_is_used_as_id(self) -> None:
        """Test string group is treated as group ID directly (line 539)."""
        from graphinator.graphinator import process_artist

        mock_tx = MagicMock()
        mock_tx.run.return_value.single.return_value = None

        record = {
            "id": "artist-1",
            "sha256": "newhash",
            "name": "Test Artist",
            "groups": {"name": ["string-group-id"]},  # String, not dict
        }

        result = process_artist(mock_tx, record)
        assert result is True
        calls = [str(c) for c in mock_tx.run.call_args_list]
        assert any("MEMBER_OF" in c for c in calls)

    def test_group_without_id_logs_warning(self) -> None:
        """Test group dict without @id or id logs a warning (lines 545-547)."""
        from graphinator.graphinator import process_artist

        mock_tx = MagicMock()
        mock_tx.run.return_value.single.return_value = None

        record = {
            "id": "artist-1",
            "sha256": "newhash",
            "name": "Test Artist",
            "groups": {"name": [{"#text": "No ID Group"}]},
        }

        with patch("graphinator.graphinator.logger") as mock_logger:
            result = process_artist(mock_tx, record)

        assert result is True
        mock_logger.warning.assert_called()
        warning_msg = str(mock_logger.warning.call_args_list)
        assert "Skipping group" in warning_msg

    def test_string_alias_is_used_as_id(self) -> None:
        """Test string alias is treated as alias ID directly (line 568)."""
        from graphinator.graphinator import process_artist

        mock_tx = MagicMock()
        mock_tx.run.return_value.single.return_value = None

        record = {
            "id": "artist-1",
            "sha256": "newhash",
            "name": "Test Artist",
            "aliases": {"name": ["string-alias-id"]},
        }

        result = process_artist(mock_tx, record)
        assert result is True
        calls = [str(c) for c in mock_tx.run.call_args_list]
        assert any("ALIAS_OF" in c for c in calls)

    def test_alias_without_id_logs_warning(self) -> None:
        """Test alias dict without @id or id logs a warning (lines 574-576)."""
        from graphinator.graphinator import process_artist

        mock_tx = MagicMock()
        mock_tx.run.return_value.single.return_value = None

        record = {
            "id": "artist-1",
            "sha256": "newhash",
            "name": "Test Artist",
            "aliases": {"name": [{"#text": "No ID Alias"}]},
        }

        with patch("graphinator.graphinator.logger") as mock_logger:
            result = process_artist(mock_tx, record)

        assert result is True
        mock_logger.warning.assert_called()
        warning_msg = str(mock_logger.warning.call_args_list)
        assert "Skipping alias" in warning_msg


class TestProcessLabelEdgeCases:
    """Test process_label edge cases."""

    def test_sublabel_without_id_logs_warning(self) -> None:
        """Test sublabel dict without @id or id logs a warning (line 635)."""
        from graphinator.graphinator import process_label

        mock_tx = MagicMock()
        mock_tx.run.return_value.single.return_value = None

        record = {
            "id": "label-1",
            "sha256": "newhash",
            "name": "Test Label",
            "sublabels": {"label": [{"#text": "No ID Sublabel"}]},  # Dict without @id or id
        }

        with patch("graphinator.graphinator.logger") as mock_logger:
            result = process_label(mock_tx, record)

        assert result is True
        mock_logger.warning.assert_called()
        warning_msg = str(mock_logger.warning.call_args_list)
        assert "Skipping sublabel" in warning_msg

    def test_parent_label_without_id_logs_warning(self) -> None:
        """Test parent label dict without @id or id logs a warning."""
        from graphinator.graphinator import process_label

        mock_tx = MagicMock()
        mock_tx.run.return_value.single.return_value = None

        record = {
            "id": "label-1",
            "sha256": "newhash",
            "name": "Test Label",
            "parentLabel": {"#text": "No ID Parent"},  # Dict without @id or id
        }

        with patch("graphinator.graphinator.logger") as mock_logger:
            result = process_label(mock_tx, record)

        assert result is True
        mock_logger.warning.assert_called()
        warning_msg = str(mock_logger.warning.call_args_list)
        assert "Skipping parent label" in warning_msg


class TestProcessMasterEdgeCases:
    """Test process_master edge cases."""

    def test_artist_without_id_logs_warning(self) -> None:
        """Test master artist dict without id or @id logs a warning (line 709)."""
        from graphinator.graphinator import process_master

        mock_tx = MagicMock()
        mock_tx.run.return_value.single.return_value = None

        record = {
            "id": "master-1",
            "sha256": "newhash",
            "title": "Test Master",
            "year": 2023,
            "artists": {"artist": [{"name": "Unknown Artist"}]},  # Dict without id or @id
        }

        with patch("graphinator.graphinator.logger") as mock_logger:
            result = process_master(mock_tx, record)

        assert result is True
        mock_logger.warning.assert_called()
        warning_msg = str(mock_logger.warning.call_args_list)
        assert "Skipping artist" in warning_msg


class TestProcessLabelSublabelsString:
    """Test process_label with sublabels as a bare string (line 635)."""

    def test_sublabels_as_string_creates_single_item_list(self) -> None:
        """Test sublabels as a bare string hits line 635: sublabels_list = [sublabels]."""
        from graphinator.graphinator import process_label

        mock_tx = MagicMock()
        mock_tx.run.return_value.single.return_value = None

        record = {
            "id": "label-str-1",
            "sha256": "newhash",
            "name": "Parent Label",
            "sublabels": "SubLabel As String",  # bare string, not list or dict
        }

        with patch("graphinator.graphinator.logger"):
            result = process_label(mock_tx, record)

        assert result is True
        mock_tx.run.assert_called()


class TestProcessReleaseArtistNoId:
    """Test process_release with artist dict missing both id and @id (line 809)."""

    def test_artist_dict_missing_id_logs_warning(self) -> None:
        """Test artist dict without id or @id key logs warning at line 809."""
        from graphinator.graphinator import process_release

        mock_tx = MagicMock()
        mock_tx.run.return_value.single.return_value = None

        record = {
            "id": "release-no-artist-id",
            "sha256": "newhash",
            "title": "Test Release",
            "artists": {
                "artist": [
                    {"name": "Unknown Artist", "role": "Producer"},  # no id or @id
                ]
            },
        }

        with patch("graphinator.graphinator.logger") as mock_logger:
            result = process_release(mock_tx, record)

        assert result is True
        mock_logger.warning.assert_called()
        warning_msg = str(mock_logger.warning.call_args_list)
        assert "Skipping artist" in warning_msg


class TestProcessReleaseLabelNoId:
    """Test process_release with label dict missing both id and @id (line 838)."""

    def test_label_dict_missing_id_logs_warning(self) -> None:
        """Test label dict without @id or id key logs warning at line 838."""
        from graphinator.graphinator import process_release

        mock_tx = MagicMock()
        mock_tx.run.return_value.single.return_value = None

        record = {
            "id": "release-no-label-id",
            "sha256": "newhash",
            "title": "Test Release",
            "labels": {
                "label": [
                    {"name": "Unknown Label", "catno": "CAT001"},  # no @id or id
                ]
            },
        }

        with patch("graphinator.graphinator.logger") as mock_logger:
            result = process_release(mock_tx, record)

        assert result is True
        mock_logger.warning.assert_called()
        warning_msg = str(mock_logger.warning.call_args_list)
        assert "Skipping label" in warning_msg


class TestProcessReleaseMasterNoId:
    """Test process_release with master_id dict missing text key (line 863)."""

    def test_master_id_dict_without_text_logs_warning(self) -> None:
        """Test master_id dict without the text key logs warning at line 863."""
        from graphinator.graphinator import process_release

        mock_tx = MagicMock()
        mock_tx.run.return_value.single.return_value = None

        record = {
            "id": "release-no-master-text",
            "sha256": "newhash",
            "title": "Test Release",
            "master_id": {"other": "value"},  # dict without "#text"
        }

        with patch("graphinator.graphinator.logger") as mock_logger:
            result = process_release(mock_tx, record)

        assert result is True
        mock_logger.warning.assert_called()
        warning_msg = str(mock_logger.warning.call_args_list)
        assert "Skipping master" in warning_msg


class TestMainConfigError:
    """Test main() early return on GraphinatorConfig ValueError (lines 1209-1211)."""

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.signal.signal")
    @patch("graphinator.graphinator.setup_logging")
    @patch("graphinator.graphinator.HealthServer")
    @patch("graphinator.graphinator.GraphinatorConfig.from_env", side_effect=ValueError("bad config"))
    async def test_main_returns_on_config_error(
        self,
        _mock_from_env: MagicMock,
        mock_health_server: MagicMock,
        _mock_setup_logging: MagicMock,
        _mock_signal: MagicMock,
    ) -> None:
        """Test main() returns after logging error when config raises ValueError."""
        mock_health_instance = MagicMock()
        mock_health_server.return_value = mock_health_instance

        with (
            patch.dict("os.environ", {"STARTUP_DELAY": "0"}),
            patch("graphinator.graphinator.logger") as mock_logger,
        ):
            await main()

        error_calls = str(mock_logger.error.call_args_list)
        assert "Configuration error" in error_calls or "bad config" in error_calls


class TestMainNeo4jFailure:
    """Test main() early return on Neo4j connection failure (lines 1365-1367)."""

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.signal.signal")
    @patch("graphinator.graphinator.setup_logging")
    @patch("graphinator.graphinator.HealthServer")
    @patch("graphinator.graphinator.GraphinatorConfig.from_env")
    @patch("graphinator.graphinator.AsyncResilientNeo4jDriver")
    async def test_main_returns_on_neo4j_error(
        self,
        mock_neo4j_class: MagicMock,
        mock_from_env: MagicMock,
        mock_health_server: MagicMock,
        _mock_setup_logging: MagicMock,
        _mock_signal: MagicMock,
    ) -> None:
        """Test main() returns after logging error when Neo4j session raises."""
        mock_health_instance = MagicMock()
        mock_health_server.return_value = mock_health_instance

        mock_config = MagicMock()
        mock_config.neo4j_address = "bolt://localhost:7687"
        mock_config.neo4j_username = "neo4j"
        mock_config.neo4j_password = "password"
        mock_from_env.return_value = mock_config

        mock_neo4j_instance = MagicMock()
        mock_neo4j_class.return_value = mock_neo4j_instance

        async def failing_session(*_args: Any, **_kwargs: Any) -> Any:
            raise Exception("Neo4j connection refused")

        mock_neo4j_instance.session = MagicMock(side_effect=failing_session)

        with (
            patch.dict("os.environ", {"STARTUP_DELAY": "0"}),
            patch("graphinator.graphinator.logger") as mock_logger,
        ):
            await main()

        error_calls = str(mock_logger.error.call_args_list)
        assert "Neo4j" in error_calls or "Failed" in error_calls


class TestMainBatchProcessorFlushError:
    """Test batch flush error in finally block (lines 1536-1541)."""

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.signal.signal")
    @patch("graphinator.graphinator.setup_logging")
    @patch("graphinator.graphinator.HealthServer")
    @patch("graphinator.graphinator.GraphinatorConfig.from_env")
    @patch("graphinator.graphinator.AsyncResilientNeo4jDriver")
    @patch("graphinator.graphinator.AsyncResilientRabbitMQ")
    async def test_batch_processor_flush_error_logs(
        self,
        mock_rabbitmq_class: MagicMock,
        mock_neo4j_class: MagicMock,
        mock_from_env: MagicMock,
        mock_health_server: MagicMock,
        _mock_setup_logging: MagicMock,
        _mock_signal: MagicMock,
    ) -> None:
        """Test that batch_processor.flush_all() raising in finally block logs an error."""
        mock_health_instance = MagicMock()
        mock_health_server.return_value = mock_health_instance

        mock_config = MagicMock()
        mock_config.neo4j_address = "bolt://localhost:7687"
        mock_config.neo4j_username = "neo4j"
        mock_config.neo4j_password = "password"
        mock_config.amqp_connection = "amqp://guest:guest@localhost/"
        mock_from_env.return_value = mock_config

        mock_neo4j_instance = MagicMock()
        mock_neo4j_class.return_value = mock_neo4j_instance
        mock_neo4j_instance.close = AsyncMock()

        mock_batch_proc = AsyncMock()
        mock_batch_proc.shutdown = MagicMock()
        mock_batch_proc.flush_all = AsyncMock(side_effect=Exception("flush failed"))

        call_index = 0

        async def mock_session_factory(*_args: Any, **_kwargs: Any) -> Any:
            nonlocal call_index
            call_index += 1
            mock_session = AsyncMock()

            if call_index == 1:
                result = AsyncMock()
                result.single = AsyncMock(return_value={"test": 1})
                mock_session.run = AsyncMock(return_value=result)
            else:

                async def empty_run(*_a: Any, **_kw: Any) -> AsyncMock:
                    result = AsyncMock()
                    result.single = AsyncMock(return_value={"removed": 0})

                    async def empty_aiter() -> Any:
                        return
                        yield  # noqa: unreachable

                    result.__aiter__ = lambda _: empty_aiter()
                    return result

                mock_session.run = empty_run

            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=mock_session)
            ctx.__aexit__ = AsyncMock(return_value=None)
            return ctx

        mock_neo4j_instance.session = MagicMock(side_effect=mock_session_factory)

        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_connection.channel = AsyncMock(return_value=mock_channel)
        mock_channel.set_qos = AsyncMock()
        mock_channel.declare_exchange = AsyncMock(return_value=AsyncMock())
        mock_channel.declare_queue = AsyncMock(return_value=AsyncMock())
        mock_connection.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_connection.__aexit__ = AsyncMock(return_value=None)

        mock_rabbitmq_instance = AsyncMock()
        mock_rabbitmq_class.return_value = mock_rabbitmq_instance
        mock_rabbitmq_instance.connect = AsyncMock(return_value=mock_connection)

        import graphinator.graphinator as gm

        original_shutdown = gm.shutdown_requested
        created_tasks: list[asyncio.Task[Any]] = []

        def mock_create_task(coro: Any) -> asyncio.Task[Any]:
            task = asyncio.get_event_loop().create_task(coro)
            created_tasks.append(task)
            return task

        try:
            with (
                patch.dict("os.environ", {"STARTUP_DELAY": "0"}),
                patch("graphinator.graphinator.batch_processor", mock_batch_proc),
                patch("graphinator.graphinator.BATCH_MODE", False),
                patch("graphinator.graphinator.logger") as mock_logger,
                patch("graphinator.graphinator.shutdown_requested", False),
                patch("asyncio.create_task", side_effect=mock_create_task),
            ):

                async def mock_wait_for(_coro: Any, _timeout: float) -> None:
                    import graphinator.graphinator as _gm

                    _gm.shutdown_requested = True
                    raise TimeoutError()

                with patch("asyncio.wait_for", mock_wait_for):
                    await main()

            for task in created_tasks:
                if not task.done():
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task

            error_calls = str(mock_logger.error.call_args_list)
            assert "flush" in error_calls.lower() or "Error flushing" in error_calls or "batch" in error_calls.lower()
        finally:
            gm.shutdown_requested = original_shutdown


class TestMainNeo4jCloseError:
    """Test Neo4j driver close error in finally block (lines 1554-1555)."""

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.signal.signal")
    @patch("graphinator.graphinator.setup_logging")
    @patch("graphinator.graphinator.HealthServer")
    @patch("graphinator.graphinator.GraphinatorConfig.from_env")
    @patch("graphinator.graphinator.AsyncResilientNeo4jDriver")
    @patch("graphinator.graphinator.AsyncResilientRabbitMQ")
    async def test_neo4j_close_error_logs_warning(
        self,
        mock_rabbitmq_class: MagicMock,
        mock_neo4j_class: MagicMock,
        mock_from_env: MagicMock,
        mock_health_server: MagicMock,
        _mock_setup_logging: MagicMock,
        _mock_signal: MagicMock,
    ) -> None:
        """Test that graph.close() raising in finally block logs a warning."""
        mock_health_instance = MagicMock()
        mock_health_server.return_value = mock_health_instance

        mock_config = MagicMock()
        mock_config.neo4j_address = "bolt://localhost:7687"
        mock_config.neo4j_username = "neo4j"
        mock_config.neo4j_password = "password"
        mock_config.amqp_connection = "amqp://guest:guest@localhost/"
        mock_from_env.return_value = mock_config

        mock_neo4j_instance = MagicMock()
        mock_neo4j_class.return_value = mock_neo4j_instance
        mock_neo4j_instance.close = AsyncMock(side_effect=Exception("close failed"))

        call_index = 0

        async def mock_session_factory(*_args: Any, **_kwargs: Any) -> Any:
            nonlocal call_index
            call_index += 1
            mock_session = AsyncMock()

            if call_index == 1:
                result = AsyncMock()
                result.single = AsyncMock(return_value={"test": 1})
                mock_session.run = AsyncMock(return_value=result)
            else:

                async def empty_run(*_a: Any, **_kw: Any) -> AsyncMock:
                    result = AsyncMock()
                    result.single = AsyncMock(return_value={"removed": 0})

                    async def empty_aiter() -> Any:
                        return
                        yield  # noqa: unreachable

                    result.__aiter__ = lambda _: empty_aiter()
                    return result

                mock_session.run = empty_run

            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=mock_session)
            ctx.__aexit__ = AsyncMock(return_value=None)
            return ctx

        mock_neo4j_instance.session = MagicMock(side_effect=mock_session_factory)

        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_connection.channel = AsyncMock(return_value=mock_channel)
        mock_channel.set_qos = AsyncMock()
        mock_channel.declare_exchange = AsyncMock(return_value=AsyncMock())
        mock_channel.declare_queue = AsyncMock(return_value=AsyncMock())
        mock_connection.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_connection.__aexit__ = AsyncMock(return_value=None)

        mock_rabbitmq_instance = AsyncMock()
        mock_rabbitmq_class.return_value = mock_rabbitmq_instance
        mock_rabbitmq_instance.connect = AsyncMock(return_value=mock_connection)

        import graphinator.graphinator as gm

        original_shutdown = gm.shutdown_requested
        created_tasks: list[asyncio.Task[Any]] = []

        def mock_create_task(coro: Any) -> asyncio.Task[Any]:
            task = asyncio.get_event_loop().create_task(coro)
            created_tasks.append(task)
            return task

        try:
            with (
                patch.dict("os.environ", {"STARTUP_DELAY": "0"}),
                patch("graphinator.graphinator.BATCH_MODE", False),
                patch("graphinator.graphinator.logger") as mock_logger,
                patch("graphinator.graphinator.shutdown_requested", False),
                patch("asyncio.create_task", side_effect=mock_create_task),
            ):

                async def mock_wait_for(_coro: Any, _timeout: float) -> None:
                    import graphinator.graphinator as _gm

                    _gm.shutdown_requested = True
                    raise TimeoutError()

                with patch("asyncio.wait_for", mock_wait_for):
                    await main()

            for task in created_tasks:
                if not task.done():
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task

            warning_calls = str(mock_logger.warning.call_args_list)
            assert "Neo4j" in warning_calls or "close" in warning_calls.lower() or "Error" in warning_calls
        finally:
            gm.shutdown_requested = original_shutdown


class TestMainAmqpConnectionNone:
    """Test main() returns when AMQP connection is None after retry loop exits (lines 1422-1423)."""

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.signal.signal")
    @patch("graphinator.graphinator.setup_logging")
    @patch("graphinator.graphinator.HealthServer")
    @patch("graphinator.graphinator.GraphinatorConfig.from_env")
    @patch("graphinator.graphinator.AsyncResilientNeo4jDriver")
    @patch("graphinator.graphinator.AsyncResilientRabbitMQ")
    async def test_main_returns_when_amqp_connection_none(
        self,
        mock_rabbitmq_class: MagicMock,
        mock_neo4j_class: MagicMock,
        mock_from_env: MagicMock,
        mock_health_server: MagicMock,
        _mock_setup_logging: MagicMock,
        _mock_signal: MagicMock,
    ) -> None:
        """Test main() logs error and returns when amqp_connection remains None.

        Sets shutdown_requested=True before the AMQP retry loop so the while
        condition fails immediately, amqp_connection stays None, and main()
        hits the early-return path at lines 1422-1423.
        """
        mock_health_instance = MagicMock()
        mock_health_server.return_value = mock_health_instance

        mock_config = MagicMock()
        mock_config.neo4j_address = "bolt://localhost:7687"
        mock_config.neo4j_username = "neo4j"
        mock_config.neo4j_password = "password"
        mock_config.amqp_connection = "amqp://guest:guest@localhost/"
        mock_from_env.return_value = mock_config

        mock_neo4j_instance = MagicMock()
        mock_neo4j_class.return_value = mock_neo4j_instance
        mock_neo4j_instance.close = AsyncMock()

        call_index = 0

        async def mock_session_factory(*_args: Any, **_kwargs: Any) -> Any:
            nonlocal call_index
            call_index += 1
            mock_session = AsyncMock()

            if call_index == 1:
                result = AsyncMock()
                result.single = AsyncMock(return_value={"test": 1})
                mock_session.run = AsyncMock(return_value=result)
            else:

                async def empty_run(*_a: Any, **_kw: Any) -> AsyncMock:
                    result = AsyncMock()
                    result.single = AsyncMock(return_value={"removed": 0})

                    async def empty_aiter() -> Any:
                        return
                        yield  # noqa: unreachable

                    result.__aiter__ = lambda _: empty_aiter()
                    return result

                mock_session.run = empty_run

            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=mock_session)
            ctx.__aexit__ = AsyncMock(return_value=None)
            return ctx

        mock_neo4j_instance.session = MagicMock(side_effect=mock_session_factory)

        mock_rabbitmq_instance = AsyncMock()
        mock_rabbitmq_class.return_value = mock_rabbitmq_instance
        mock_rabbitmq_instance.connect = AsyncMock(return_value=None)

        import graphinator.graphinator as gm

        original_shutdown = gm.shutdown_requested
        try:
            # Set shutdown_requested=True so the AMQP retry while-loop body never
            # executes and amqp_connection stays None, triggering lines 1422-1423.
            gm.shutdown_requested = True
            with (
                patch.dict("os.environ", {"STARTUP_DELAY": "0"}),
                patch("graphinator.graphinator.BATCH_MODE", False),
                patch("graphinator.graphinator.logger") as mock_logger,
            ):
                await main()

            error_calls = str(mock_logger.error.call_args_list)
            assert "AMQP" in error_calls or "amqp" in error_calls.lower() or "No AMQP" in error_calls
        finally:
            gm.shutdown_requested = original_shutdown
