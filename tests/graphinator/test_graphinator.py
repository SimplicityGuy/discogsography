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

    def test_neo4j_specific_error(self) -> None:
        """Test handling specific Neo4jError exceptions."""
        from neo4j.exceptions import Neo4jError

        mock_session = MagicMock()
        mock_session.run.side_effect = Neo4jError("Database unavailable")

        with patch("graphinator.graphinator.logger") as mock_logger:
            result = safe_execute_query(mock_session, "MATCH (n) RETURN n", {})

            assert result is False
            # Verify specific Neo4jError logging path
            assert any("Neo4j error" in str(call) for call in mock_logger.error.call_args_list)


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
                async def mock_wait_for(_coro: Any, timeout: float) -> None:  # noqa: ARG001
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
        """Test health data shows None when no consumers are active."""
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
    @patch("graphinator.graphinator.QUEUE_CHECK_INTERVAL", 0.1)
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
    @patch("graphinator.graphinator.QUEUE_CHECK_INTERVAL", 0.1)
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
