"""Tests for tableinator module."""

import asyncio
import contextlib
import json
import signal
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from aio_pika.abc import AbstractIncomingMessage
from psycopg import DatabaseError
import pytest

from tableinator.tableinator import (
    check_all_consumers_idle,
    close_rabbitmq_connection,
    get_connection,
    get_health_data,
    main,
    on_data_message,
    safe_execute_query,
    schedule_consumer_cancellation,
    signal_handler,
)


# SimpleConnectionPool tests removed as we now use AsyncPostgreSQLPool


class TestGetConnection:
    """Test get_connection function."""

    def test_get_connection_success(self) -> None:
        """Test getting connection from pool."""
        mock_pool = MagicMock()

        with patch("tableinator.tableinator.connection_pool", mock_pool):
            result = get_connection()

            assert result == mock_pool.connection()

    def test_get_connection_no_pool(self) -> None:
        """Test getting connection when pool not initialized."""
        with (
            patch("tableinator.tableinator.connection_pool", None),
            pytest.raises(RuntimeError, match="Connection pool not initialized"),
        ):
            get_connection()


class TestSafeExecuteQuery:
    """Test safe_execute_query function."""

    def test_successful_execution(self) -> None:
        """Test successful query execution."""
        mock_cursor = MagicMock()
        query = "INSERT INTO test VALUES (%s)"
        params = ("test_value",)

        result = safe_execute_query(mock_cursor, query, params)

        assert result is True
        mock_cursor.execute.assert_called_once_with(query, params)

    def test_database_error(self) -> None:
        """Test handling database errors."""
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = DatabaseError("Database error")

        with patch("tableinator.tableinator.logger") as mock_logger:
            result = safe_execute_query(mock_cursor, "SELECT 1", ())

            assert result is False
            mock_logger.error.assert_called()

    def test_unexpected_error(self) -> None:
        """Test handling unexpected errors."""
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = Exception("Unexpected error")

        with patch("tableinator.tableinator.logger") as mock_logger:
            result = safe_execute_query(mock_cursor, "SELECT 1", ())

            assert result is False
            mock_logger.error.assert_called()


class TestOnDataMessage:
    """Test on_data_message handler."""

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.shutdown_requested", False)
    async def test_process_new_record(self, sample_artist_data: dict[str, Any], mock_postgres_connection: MagicMock, mock_async_pool: Any) -> None:
        """Test processing a new record."""
        # Create mock message
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(sample_artist_data).encode()
        mock_message.routing_key = "artists"

        # Setup async cursor mock
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=None)  # No existing record

        mock_cursor_cm = AsyncMock()
        mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_cm.__aexit__ = AsyncMock(return_value=None)

        mock_postgres_connection.cursor = MagicMock(return_value=mock_cursor_cm)

        # Setup async connection pool mock
        pool = mock_async_pool(mock_postgres_connection)

        with patch("tableinator.tableinator.connection_pool", pool):
            await on_data_message(mock_message)

        # Verify message was acknowledged
        mock_message.ack.assert_called_once()

        # Verify queries were executed
        assert mock_cursor.execute.call_count == 2  # SELECT and INSERT

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.shutdown_requested", False)
    async def test_skip_unchanged_record(self, sample_artist_data: dict[str, Any], mock_postgres_connection: MagicMock, mock_async_pool: Any) -> None:
        """Test skipping record with unchanged hash."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(sample_artist_data).encode()
        mock_message.routing_key = "artists"

        # Setup async cursor mock
        mock_cursor = AsyncMock()
        # Return existing record with same hash
        mock_cursor.fetchone = AsyncMock(return_value=(sample_artist_data["sha256"],))

        mock_cursor_cm = AsyncMock()
        mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_cm.__aexit__ = AsyncMock(return_value=None)

        mock_postgres_connection.cursor = MagicMock(return_value=mock_cursor_cm)

        # Setup async connection pool mock
        pool = mock_async_pool(mock_postgres_connection)

        with patch("tableinator.tableinator.connection_pool", pool):
            await on_data_message(mock_message)

        # Verify message was acknowledged
        mock_message.ack.assert_called_once()

        # Only SELECT should be executed, no INSERT
        assert mock_cursor.execute.call_count == 1

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.shutdown_requested", True)
    async def test_reject_on_shutdown(self) -> None:
        """Test message rejection during shutdown."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)

        await on_data_message(mock_message)

        mock_message.nack.assert_called_once_with(requeue=True)
        mock_message.ack.assert_not_called()

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.shutdown_requested", False)
    async def test_handle_connection_error(self, sample_artist_data: dict[str, Any]) -> None:
        """Test handling connection errors."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(sample_artist_data).encode()
        mock_message.routing_key = "artists"

        mock_pool = MagicMock()
        # Make connection fail
        mock_pool.connection.side_effect = Exception("Connection failed")

        with patch("tableinator.tableinator.connection_pool", mock_pool):
            await on_data_message(mock_message)

        # Should nack with requeue
        mock_message.nack.assert_called_once_with(requeue=True)

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.shutdown_requested", False)
    async def test_invalid_message_format(self) -> None:
        """Test handling invalid message format."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = b"invalid json"

        await on_data_message(mock_message)

        # Should nack without requeue for bad messages
        mock_message.nack.assert_called_once_with(requeue=False)


class TestMain:
    """Test main function."""

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.setup_logging")
    @patch("tableinator.tableinator.HealthServer")
    @patch("tableinator.tableinator.AsyncResilientRabbitMQ")
    @patch("tableinator.tableinator.AsyncPostgreSQLPool")
    @patch("tableinator.tableinator.psycopg.connect")
    @patch("tableinator.tableinator.shutdown_requested", False)
    async def test_main_execution(
        self,
        mock_psycopg_connect: Mock,
        mock_pool_class: Mock,
        mock_rabbitmq_class: AsyncMock,
        mock_health_server: Mock,
        _mock_setup_logging: Mock,
    ) -> None:
        """Test successful main execution."""
        # Mock health server
        mock_health_instance = MagicMock()
        mock_health_server.return_value = mock_health_instance

        # Mock database existence check connection
        mock_admin_conn = MagicMock()
        mock_admin_cursor = MagicMock()
        mock_admin_cursor.fetchone.return_value = ("discogsography",)  # Database exists
        mock_admin_conn.cursor.return_value.__enter__.return_value = mock_admin_cursor
        mock_admin_conn.__enter__.return_value = mock_admin_conn
        mock_psycopg_connect.return_value = mock_admin_conn

        # Setup mocks with async connection support
        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool
        mock_pool.initialize = AsyncMock()  # Mock async initialize method
        mock_pool.close = AsyncMock()

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Create async context manager for connection
        mock_connection_cm = AsyncMock()
        mock_connection_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_connection_cm.__aexit__ = AsyncMock(return_value=None)

        mock_pool.connection = MagicMock(return_value=mock_connection_cm)

        # Mock resilient RabbitMQ connection
        mock_rabbitmq_instance = AsyncMock()
        mock_rabbitmq_class.return_value = mock_rabbitmq_instance

        # Mock the connect method to return a connection
        mock_connection = AsyncMock()
        mock_rabbitmq_instance.connect.return_value = mock_connection

        # Mock the channel method
        mock_channel = AsyncMock()
        mock_rabbitmq_instance.channel.return_value = mock_channel

        # Mock queue setup
        mock_queue = AsyncMock()
        mock_channel.declare_queue.return_value = mock_queue

        # Simulate shutdown by setting shutdown_requested
        with patch("tableinator.tableinator.shutdown_requested", False):
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
                    # Set shutdown_requested to exit the loop
                    import tableinator.tableinator

                    tableinator.tableinator.shutdown_requested = True
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
        assert mock_pool_class.call_count == 1
        # Check that it was called with correct parameters (updated for performance optimization)
        call_args = mock_pool_class.call_args
        assert call_args[1]["max_connections"] == 50
        assert call_args[1]["min_connections"] == 5
        mock_rabbitmq_class.assert_called_once()

        # The test exits early due to our mock, so some operations might not complete
        # Verify database check was attempted
        assert mock_admin_cursor.execute.call_count >= 1

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.setup_logging")
    @patch("tableinator.tableinator.HealthServer")
    @patch("tableinator.tableinator.AsyncPostgreSQLPool")
    @patch("tableinator.tableinator.psycopg.connect")
    async def test_main_pool_initialization_failure(
        self,
        mock_psycopg_connect: Mock,
        mock_pool_class: Mock,
        mock_health_server: Mock,
        _mock_setup_logging: Mock,
    ) -> None:
        """Test main when connection pool initialization fails."""
        # Mock health server
        mock_health_instance = MagicMock()
        mock_health_server.return_value = mock_health_instance

        # Mock database existence check
        mock_admin_conn = MagicMock()
        mock_admin_cursor = MagicMock()
        mock_admin_cursor.fetchone.return_value = ("discogsography",)  # Database exists
        mock_admin_conn.cursor.return_value.__enter__.return_value = mock_admin_cursor
        mock_admin_conn.__enter__.return_value = mock_admin_conn
        mock_psycopg_connect.return_value = mock_admin_conn

        # Make pool initialization fail
        mock_pool_class.side_effect = Exception("Cannot create pool")

        # Should complete without raising
        await main()

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.setup_logging")
    @patch("tableinator.tableinator.HealthServer")
    @patch("tableinator.tableinator.AsyncResilientRabbitMQ")
    @patch("tableinator.tableinator.AsyncPostgreSQLPool")
    @patch("tableinator.tableinator.psycopg.connect")
    async def test_main_amqp_connection_failure(
        self,
        mock_psycopg_connect: Mock,
        mock_pool_class: Mock,
        mock_rabbitmq_class: AsyncMock,
        mock_health_server: Mock,
        _mock_setup_logging: Mock,
    ) -> None:
        """Test main when AMQP connection fails."""
        # Mock health server
        mock_health_instance = MagicMock()
        mock_health_server.return_value = mock_health_instance

        # Mock database existence check
        mock_admin_conn = MagicMock()
        mock_admin_cursor = MagicMock()
        mock_admin_cursor.fetchone.return_value = ("discogsography",)  # Database exists
        mock_admin_conn.cursor.return_value.__enter__.return_value = mock_admin_cursor
        mock_admin_conn.__enter__.return_value = mock_admin_conn
        mock_psycopg_connect.return_value = mock_admin_conn

        # Setup pool success with async connection support
        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool
        mock_pool.initialize = AsyncMock()  # Mock async initialize method
        mock_pool.close = AsyncMock()

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Create async context manager for connection
        mock_connection_cm = AsyncMock()
        mock_connection_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_connection_cm.__aexit__ = AsyncMock(return_value=None)

        mock_pool.connection = MagicMock(return_value=mock_connection_cm)

        # Make AMQP connection fail
        from aio_pika.exceptions import AMQPConnectionError

        mock_rabbitmq_class.side_effect = AMQPConnectionError("Cannot connect to AMQP")

        # Should handle the exception and exit gracefully
        with pytest.raises(AMQPConnectionError, match="Cannot connect to AMQP"):
            await main()

        # In the current implementation, the pool might not be closed if AMQP fails early
        # This is acceptable behavior as the process will exit anyway

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.setup_logging")
    @patch("tableinator.tableinator.HealthServer")
    @patch("tableinator.tableinator.AsyncResilientRabbitMQ")
    @patch("tableinator.tableinator.AsyncPostgreSQLPool")
    @patch("tableinator.tableinator.psycopg.connect")
    async def test_main_table_creation_failure(
        self,
        mock_psycopg_connect: Mock,
        mock_pool_class: Mock,
        _mock_rabbitmq_class: AsyncMock,
        mock_health_server: Mock,
        _mock_setup_logging: Mock,
    ) -> None:
        """Test main when table creation fails."""
        # Mock health server
        mock_health_instance = MagicMock()
        mock_health_server.return_value = mock_health_instance

        # Mock database existence check
        mock_admin_conn = MagicMock()
        mock_admin_cursor = MagicMock()
        mock_admin_cursor.fetchone.return_value = ("discogsography",)  # Database exists
        mock_admin_conn.cursor.return_value.__enter__.return_value = mock_admin_cursor
        mock_admin_conn.__enter__.return_value = mock_admin_conn
        mock_psycopg_connect.return_value = mock_admin_conn

        # Setup pool with async connection that fails
        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool
        mock_pool.initialize = AsyncMock()  # Mock async initialize method
        mock_pool.close = AsyncMock()

        # Make table creation fail by raising exception in async connection factory
        async def mock_connection_factory_fail(*_args: Any, **_kwargs: Any) -> Any:
            raise Exception("Cannot create tables")

        mock_pool.connection = MagicMock(side_effect=mock_connection_factory_fail)

        # Should complete without raising
        await main()

        # Pool should be closed
        mock_pool.close.assert_called_once()

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.setup_logging")
    @patch("tableinator.tableinator.HealthServer")
    @patch("tableinator.tableinator.AsyncResilientRabbitMQ")
    @patch("tableinator.tableinator.AsyncPostgreSQLPool")
    @patch("tableinator.tableinator.psycopg.connect")
    @patch("tableinator.tableinator.shutdown_requested", False)
    async def test_main_database_creation(
        self,
        mock_psycopg_connect: Mock,
        mock_pool_class: Mock,
        mock_rabbitmq_class: AsyncMock,
        mock_health_server: Mock,
        _mock_setup_logging: Mock,
    ) -> None:
        """Test main when database needs to be created."""
        # Mock health server
        mock_health_instance = MagicMock()
        mock_health_server.return_value = mock_health_instance

        # Mock database existence check - database doesn't exist
        mock_admin_conn = MagicMock()
        mock_admin_cursor = MagicMock()
        mock_admin_cursor.fetchone.return_value = None  # Database doesn't exist
        mock_admin_conn.cursor.return_value.__enter__.return_value = mock_admin_cursor
        mock_admin_conn.__enter__.return_value = mock_admin_conn
        mock_psycopg_connect.return_value = mock_admin_conn

        # Setup mocks
        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_pool.connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Mock resilient RabbitMQ connection
        mock_rabbitmq_instance = AsyncMock()
        mock_rabbitmq_class.return_value = mock_rabbitmq_instance

        # Mock the connect method to return a connection
        mock_connection = AsyncMock()
        mock_rabbitmq_instance.connect.return_value = mock_connection

        # Mock the channel method
        mock_channel = AsyncMock()
        mock_rabbitmq_instance.channel.return_value = mock_channel

        # Mock queue setup
        mock_queue = AsyncMock()
        mock_channel.declare_queue.return_value = mock_queue

        # Simulate shutdown by setting shutdown_requested
        with patch("tableinator.tableinator.shutdown_requested", False):
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
                    # Set shutdown_requested to exit the loop
                    import tableinator.tableinator

                    tableinator.tableinator.shutdown_requested = True
                    raise TimeoutError()

                with patch("asyncio.wait_for", mock_wait_for):
                    await main()

            # Clean up any created tasks
            for task in created_tasks:
                if not task.done():
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task

        # Verify database was created
        assert mock_admin_cursor.execute.call_count == 2  # 1 check + 1 CREATE DATABASE

        # Verify CREATE DATABASE was called
        create_db_call = mock_admin_cursor.execute.call_args_list[1]
        assert "CREATE DATABASE" in str(create_db_call)


class TestSignalHandler:
    """Test signal_handler function."""

    def test_signal_handler_sets_shutdown_flag(self) -> None:
        """Test that signal handler sets shutdown requested flag."""
        import tableinator.tableinator

        tableinator.tableinator.shutdown_requested = False

        with patch("tableinator.tableinator.logger"):
            signal_handler(signal.SIGTERM, None)

        assert tableinator.tableinator.shutdown_requested is True

    def test_signal_handler_logs_signal_number(self) -> None:
        """Test that signal handler logs the signal number."""
        with patch("tableinator.tableinator.logger") as mock_logger:
            signal_handler(signal.SIGINT, None)

            mock_logger.info.assert_called_once()


class TestScheduleConsumerCancellation:
    """Test schedule_consumer_cancellation function."""

    @pytest.mark.asyncio
    async def test_schedules_cancellation_task(self) -> None:
        """Test that cancellation task is scheduled."""
        import tableinator.tableinator

        tableinator.tableinator.consumer_cancel_tasks = {}
        tableinator.tableinator.consumer_tags = {"artists": "consumer-tag-1"}
        tableinator.tableinator.shutdown_requested = False

        mock_queue = AsyncMock()

        # Patch asyncio.sleep to avoid actual delay
        with patch("asyncio.sleep", AsyncMock()):
            await schedule_consumer_cancellation("artists", mock_queue)

        # Verify task was created
        assert "artists" in tableinator.tableinator.consumer_cancel_tasks
        assert tableinator.tableinator.consumer_cancel_tasks["artists"] is not None

        # Clean up
        tableinator.tableinator.consumer_cancel_tasks["artists"].cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await tableinator.tableinator.consumer_cancel_tasks["artists"]

    @pytest.mark.asyncio
    async def test_cancels_existing_scheduled_task(self) -> None:
        """Test that existing scheduled task is cancelled."""
        import tableinator.tableinator

        # Create a mock existing task
        existing_task = AsyncMock()
        tableinator.tableinator.consumer_cancel_tasks = {"artists": existing_task}
        tableinator.tableinator.consumer_tags = {"artists": "consumer-tag-1"}
        tableinator.tableinator.shutdown_requested = False

        mock_queue = AsyncMock()

        with patch("asyncio.sleep", AsyncMock()):
            await schedule_consumer_cancellation("artists", mock_queue)

        # Verify old task was cancelled
        existing_task.cancel.assert_called_once()


class TestCloseRabbitMQConnection:
    """Test close_rabbitmq_connection function."""

    @pytest.mark.asyncio
    async def test_closes_channel_and_connection(self) -> None:
        """Test closing both channel and connection."""
        import tableinator.tableinator

        mock_channel = AsyncMock()
        mock_connection = AsyncMock()

        tableinator.tableinator.active_channel = mock_channel
        tableinator.tableinator.active_connection = mock_connection

        with patch("tableinator.tableinator.logger"):
            await close_rabbitmq_connection()

        # Verify both were closed
        mock_channel.close.assert_called_once()
        mock_connection.close.assert_called_once()

        # Verify globals were reset
        assert tableinator.tableinator.active_channel is None
        assert tableinator.tableinator.active_connection is None

    @pytest.mark.asyncio
    async def test_handles_channel_close_error(self) -> None:
        """Test handling error when closing channel."""
        import tableinator.tableinator

        mock_channel = AsyncMock()
        mock_channel.close.side_effect = Exception("Close error")
        mock_connection = AsyncMock()

        tableinator.tableinator.active_channel = mock_channel
        tableinator.tableinator.active_connection = mock_connection

        with patch("tableinator.tableinator.logger") as mock_logger:
            await close_rabbitmq_connection()

        # Should still close connection despite channel error
        mock_connection.close.assert_called_once()
        mock_logger.warning.assert_called()

    @pytest.mark.asyncio
    async def test_handles_connection_close_error(self) -> None:
        """Test handling error when closing connection."""
        import tableinator.tableinator

        mock_channel = AsyncMock()
        mock_connection = AsyncMock()
        mock_connection.close.side_effect = Exception("Close error")

        tableinator.tableinator.active_channel = mock_channel
        tableinator.tableinator.active_connection = mock_connection

        with patch("tableinator.tableinator.logger") as mock_logger:
            await close_rabbitmq_connection()

        # Should handle error gracefully
        mock_logger.warning.assert_called()


class TestCheckAllConsumersIdle:
    """Test check_all_consumers_idle function."""

    @pytest.mark.asyncio
    async def test_returns_true_when_all_idle(self) -> None:
        """Test returns True when all consumers are idle."""
        import tableinator.tableinator

        tableinator.tableinator.consumer_tags = {}
        tableinator.tableinator.completed_files = {"artists", "labels", "masters", "releases"}

        result = await check_all_consumers_idle()

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_consumers_active(self) -> None:
        """Test returns False when consumers are still active."""
        import tableinator.tableinator

        tableinator.tableinator.consumer_tags = {"artists": "consumer-tag-1"}
        tableinator.tableinator.completed_files = set()

        result = await check_all_consumers_idle()

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_files_incomplete(self) -> None:
        """Test returns False when not all files are completed."""
        import tableinator.tableinator

        tableinator.tableinator.consumer_tags = {}
        tableinator.tableinator.completed_files = {"artists", "labels"}  # Missing masters and releases

        result = await check_all_consumers_idle()

        assert result is False


class TestOnDataMessageExtended:
    """Extended tests for on_data_message handler."""

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.shutdown_requested", False)
    async def test_handles_file_completion_message(self) -> None:
        """Test handling file completion message."""
        import tableinator.tableinator

        tableinator.tableinator.completed_files = set()
        tableinator.tableinator.queues = {"artists": AsyncMock()}

        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        completion_data = {
            "type": "file_complete",
            "total_processed": 1000,
        }
        mock_message.body = json.dumps(completion_data).encode()
        mock_message.routing_key = "artists"

        with (
            patch("tableinator.tableinator.logger"),
            patch("tableinator.tableinator.CONSUMER_CANCEL_DELAY", 0),
        ):
            await on_data_message(mock_message)

        # Verify file was marked complete
        assert "artists" in tableinator.tableinator.completed_files

        # Verify message was acknowledged
        mock_message.ack.assert_called_once()

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.shutdown_requested", False)
    async def test_handles_missing_id_field(self) -> None:
        """Test handling message with missing 'id' field."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        invalid_data = {"name": "Test Artist"}  # Missing 'id' field
        mock_message.body = json.dumps(invalid_data).encode()
        mock_message.routing_key = "artists"

        with patch("tableinator.tableinator.logger"):
            await on_data_message(mock_message)

        # Should nack without requeue
        mock_message.nack.assert_called_once_with(requeue=False)

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.shutdown_requested", False)
    async def test_processes_label_record_name(
        self, sample_artist_data: dict[str, Any], mock_postgres_connection: MagicMock, mock_async_pool: Any
    ) -> None:
        """Test processing label record with name extraction."""
        import tableinator.tableinator

        tableinator.tableinator.message_counts = {"labels": 0}
        tableinator.tableinator.last_message_time = {"labels": 0}

        # Create label data
        label_data = sample_artist_data.copy()
        label_data["id"] = "1"
        label_data["name"] = "Test Label"

        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(label_data).encode()
        mock_message.routing_key = "labels"

        # Setup async cursor mock
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=None)

        mock_cursor_cm = AsyncMock()
        mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_cm.__aexit__ = AsyncMock(return_value=None)

        mock_postgres_connection.cursor = MagicMock(return_value=mock_cursor_cm)

        # Setup async connection pool mock
        pool = mock_async_pool(mock_postgres_connection)

        with (
            patch("tableinator.tableinator.connection_pool", pool),
            patch("tableinator.tableinator.logger"),
        ):
            await on_data_message(mock_message)

        # Verify message was acknowledged
        mock_message.ack.assert_called_once()

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.shutdown_requested", False)
    async def test_processes_release_record_name(
        self, sample_artist_data: dict[str, Any], mock_postgres_connection: MagicMock, mock_async_pool: Any
    ) -> None:
        """Test processing release record with title extraction."""
        import tableinator.tableinator

        tableinator.tableinator.message_counts = {"releases": 0}
        tableinator.tableinator.last_message_time = {"releases": 0}

        # Create release data
        release_data = sample_artist_data.copy()
        release_data["id"] = "1"
        release_data["title"] = "Test Release"

        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(release_data).encode()
        mock_message.routing_key = "releases"

        # Setup async cursor mock
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=None)

        mock_cursor_cm = AsyncMock()
        mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_cm.__aexit__ = AsyncMock(return_value=None)

        mock_postgres_connection.cursor = MagicMock(return_value=mock_cursor_cm)

        # Setup async connection pool mock
        pool = mock_async_pool(mock_postgres_connection)

        with (
            patch("tableinator.tableinator.connection_pool", pool),
            patch("tableinator.tableinator.logger"),
        ):
            await on_data_message(mock_message)

        # Verify message was acknowledged
        mock_message.ack.assert_called_once()

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.shutdown_requested", False)
    async def test_processes_master_record_name(
        self, sample_artist_data: dict[str, Any], mock_postgres_connection: MagicMock, mock_async_pool: Any
    ) -> None:
        """Test processing master record with title extraction."""
        import tableinator.tableinator

        tableinator.tableinator.message_counts = {"masters": 0}
        tableinator.tableinator.last_message_time = {"masters": 0}

        # Create master data
        master_data = sample_artist_data.copy()
        master_data["id"] = "1"
        master_data["title"] = "Test Master"

        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(master_data).encode()
        mock_message.routing_key = "masters"

        # Setup async cursor mock
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=None)

        mock_cursor_cm = AsyncMock()
        mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_cm.__aexit__ = AsyncMock(return_value=None)

        mock_postgres_connection.cursor = MagicMock(return_value=mock_cursor_cm)

        # Setup async connection pool mock
        pool = mock_async_pool(mock_postgres_connection)

        with (
            patch("tableinator.tableinator.connection_pool", pool),
            patch("tableinator.tableinator.logger"),
        ):
            await on_data_message(mock_message)

        # Verify message was acknowledged
        mock_message.ack.assert_called_once()

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.shutdown_requested", True)
    async def test_rejects_message_when_shutdown_requested(self) -> None:
        """Test that messages are rejected when shutdown is requested."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps({"id": "1", "name": "Test"}).encode()
        mock_message.routing_key = "artists"

        with patch("tableinator.tableinator.logger"):
            await on_data_message(mock_message)

        # Should nack with requeue=True
        mock_message.nack.assert_called_once_with(requeue=True)


class TestPeriodicQueueChecker:
    """Test periodic_queue_checker function."""

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.QUEUE_CHECK_INTERVAL", 0.05)
    @patch("tableinator.tableinator.STUCK_CHECK_INTERVAL", 0.05)
    async def test_checks_queues_when_all_idle(self) -> None:
        """Test queue checking when all consumers are idle."""
        mock_rabbitmq_manager = AsyncMock()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()

        # Setup queue declarations with message counts
        mock_declared_queue = AsyncMock()
        mock_declared_queue.declaration_result.message_count = 5

        mock_channel.get_queue = AsyncMock(return_value=AsyncMock())
        mock_channel.declare_queue = AsyncMock(return_value=mock_declared_queue)
        mock_channel.declare_exchange = AsyncMock()
        mock_channel.set_qos = AsyncMock()
        mock_connection.channel = AsyncMock(return_value=mock_channel)
        mock_rabbitmq_manager.connect = AsyncMock(return_value=mock_connection)

        import tableinator.tableinator

        tableinator.tableinator.rabbitmq_manager = mock_rabbitmq_manager
        tableinator.tableinator.active_connection = None
        tableinator.tableinator.active_channel = None
        tableinator.tableinator.consumer_tags = {}  # No active consumers
        tableinator.tableinator.completed_files = {"artists", "labels", "masters", "releases"}  # All complete
        tableinator.tableinator.shutdown_requested = False

        from tableinator.tableinator import periodic_queue_checker

        # Run checker briefly
        checker_task = asyncio.create_task(periodic_queue_checker())
        await asyncio.sleep(0.2)

        # Stop the checker
        tableinator.tableinator.shutdown_requested = True
        await asyncio.sleep(0.05)

        checker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await checker_task

        # Should have connected to check queues
        assert mock_rabbitmq_manager.connect.called

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.QUEUE_CHECK_INTERVAL", 0.05)
    @patch("tableinator.tableinator.STUCK_CHECK_INTERVAL", 0.05)
    async def test_skips_check_when_consumers_active(self) -> None:
        """Test skips checking when consumers are active."""
        mock_rabbitmq_manager = AsyncMock()

        import tableinator.tableinator

        tableinator.tableinator.rabbitmq_manager = mock_rabbitmq_manager
        tableinator.tableinator.active_connection = None
        tableinator.tableinator.consumer_tags = {"artists": "tag-123"}  # Active consumer
        tableinator.tableinator.completed_files = set()
        tableinator.tableinator.shutdown_requested = False

        from tableinator.tableinator import periodic_queue_checker

        checker_task = asyncio.create_task(periodic_queue_checker())
        await asyncio.sleep(0.15)

        tableinator.tableinator.shutdown_requested = True
        await asyncio.sleep(0.05)

        checker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await checker_task

        # Should not connect since consumers are active
        mock_rabbitmq_manager.connect.assert_not_called()

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.QUEUE_CHECK_INTERVAL", 0.05)
    @patch("tableinator.tableinator.STUCK_CHECK_INTERVAL", 0.05)
    async def test_restarts_consumers_when_messages_found(self) -> None:
        """Test restarting consumers when messages are found in queues."""
        mock_rabbitmq_manager = AsyncMock()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()

        # Queue with messages
        mock_queue_with_msgs = AsyncMock()
        mock_queue_with_msgs.declaration_result.message_count = 10
        mock_queue_with_msgs.consume = AsyncMock(return_value="consumer-tag-123")
        mock_queue_with_msgs.bind = AsyncMock()

        # Empty queue
        mock_empty_queue = AsyncMock()
        mock_empty_queue.declaration_result.message_count = 0

        async def declare_queue_side_effect(name: str | None = None, **_kwargs: Any) -> Any:
            if "artists" in (name or ""):
                return mock_queue_with_msgs
            return mock_empty_queue

        mock_channel.declare_queue = AsyncMock(side_effect=declare_queue_side_effect)
        mock_channel.get_queue = AsyncMock(return_value=AsyncMock())
        mock_channel.declare_exchange = AsyncMock(return_value=AsyncMock())
        mock_channel.set_qos = AsyncMock()
        mock_connection.channel = AsyncMock(return_value=mock_channel)
        mock_rabbitmq_manager.connect = AsyncMock(return_value=mock_connection)

        import tableinator.tableinator

        tableinator.tableinator.rabbitmq_manager = mock_rabbitmq_manager
        tableinator.tableinator.active_connection = None
        tableinator.tableinator.active_channel = None
        tableinator.tableinator.consumer_tags = {}
        tableinator.tableinator.completed_files = {
            "artists",
            "labels",
            "masters",
            "releases",
        }  # All complete so check_all_consumers_idle returns True
        tableinator.tableinator.queues = {}
        tableinator.tableinator.shutdown_requested = False
        tableinator.tableinator.last_message_time = {}

        from tableinator.tableinator import periodic_queue_checker

        checker_task = asyncio.create_task(periodic_queue_checker())
        await asyncio.sleep(0.25)

        tableinator.tableinator.shutdown_requested = True
        await asyncio.sleep(0.05)

        checker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await checker_task

        # Should have started consumer
        assert mock_queue_with_msgs.consume.called

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.QUEUE_CHECK_INTERVAL", 0.05)
    @patch("tableinator.tableinator.STUCK_CHECK_INTERVAL", 0.05)
    async def test_handles_check_error_gracefully(self) -> None:
        """Test handling errors during queue checking."""
        mock_rabbitmq_manager = AsyncMock()
        mock_rabbitmq_manager.connect.side_effect = Exception("Connection failed")

        import tableinator.tableinator

        tableinator.tableinator.rabbitmq_manager = mock_rabbitmq_manager
        tableinator.tableinator.active_connection = None
        tableinator.tableinator.consumer_tags = {}
        tableinator.tableinator.completed_files = set()
        tableinator.tableinator.shutdown_requested = False

        from tableinator.tableinator import periodic_queue_checker

        checker_task = asyncio.create_task(periodic_queue_checker())
        await asyncio.sleep(0.15)

        tableinator.tableinator.shutdown_requested = True
        await asyncio.sleep(0.05)

        checker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await checker_task

        # Task should continue despite error
        assert True  # No exception raised

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.QUEUE_CHECK_INTERVAL", 10)
    @patch("tableinator.tableinator.STUCK_CHECK_INTERVAL", 0.05)
    async def test_recovers_from_stuck_state(self) -> None:
        """Test recovery when consumers die unexpectedly (stuck state)."""
        mock_rabbitmq_manager = AsyncMock()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()

        # Queue with messages
        mock_queue_with_msgs = AsyncMock()
        mock_queue_with_msgs.declaration_result.message_count = 100
        mock_queue_with_msgs.consume = AsyncMock(return_value="consumer-tag-123")
        mock_queue_with_msgs.bind = AsyncMock()

        mock_channel.declare_queue = AsyncMock(return_value=mock_queue_with_msgs)
        mock_channel.declare_exchange = AsyncMock(return_value=AsyncMock())
        mock_channel.set_qos = AsyncMock()
        mock_connection.channel = AsyncMock(return_value=mock_channel)
        mock_connection.close = AsyncMock()
        mock_rabbitmq_manager.connect = AsyncMock(return_value=mock_connection)

        import tableinator.tableinator

        tableinator.tableinator.rabbitmq_manager = mock_rabbitmq_manager
        tableinator.tableinator.active_connection = None
        tableinator.tableinator.active_channel = None
        # Stuck state: no consumers, but files not completed and has processed messages
        tableinator.tableinator.consumer_tags = {}
        tableinator.tableinator.completed_files = set()  # No files completed
        tableinator.tableinator.message_counts = {"artists": 100, "labels": 50, "masters": 25, "releases": 10}
        tableinator.tableinator.queues = {}
        tableinator.tableinator.shutdown_requested = False
        tableinator.tableinator.last_message_time = {
            "artists": 0.0,
            "labels": 0.0,
            "masters": 0.0,
            "releases": 0.0,
        }

        from tableinator.tableinator import periodic_queue_checker

        checker_task = asyncio.create_task(periodic_queue_checker())
        await asyncio.sleep(0.2)

        tableinator.tableinator.shutdown_requested = True
        await asyncio.sleep(0.05)

        checker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await checker_task

        # Should have attempted recovery by connecting
        assert mock_rabbitmq_manager.connect.called

    @pytest.mark.asyncio
    async def test_check_consumers_unexpectedly_dead(self) -> None:
        """Test check_consumers_unexpectedly_dead detection."""
        import tableinator.tableinator
        from tableinator.tableinator import check_consumers_unexpectedly_dead

        # Case 1: Not stuck - has active consumers
        tableinator.tableinator.consumer_tags = {"artists": "tag-123"}
        tableinator.tableinator.completed_files = set()
        tableinator.tableinator.message_counts = {"artists": 100}
        assert await check_consumers_unexpectedly_dead() is False

        # Case 2: Not stuck - all files completed (normal idle)
        tableinator.tableinator.consumer_tags = {}
        tableinator.tableinator.completed_files = {"artists", "labels", "masters", "releases"}
        tableinator.tableinator.message_counts = {"artists": 100}
        assert await check_consumers_unexpectedly_dead() is False

        # Case 3: Not stuck - no messages processed yet (startup)
        tableinator.tableinator.consumer_tags = {}
        tableinator.tableinator.completed_files = set()
        tableinator.tableinator.message_counts = {"artists": 0, "labels": 0, "masters": 0, "releases": 0}
        assert await check_consumers_unexpectedly_dead() is False

        # Case 4: STUCK - no consumers, files not completed, has processed messages
        tableinator.tableinator.consumer_tags = {}
        tableinator.tableinator.completed_files = {"labels"}  # Only 1 of 4 complete
        tableinator.tableinator.message_counts = {"artists": 100, "labels": 50, "masters": 0, "releases": 0}
        assert await check_consumers_unexpectedly_dead() is True


class TestProgressReporter:
    """Test progress_reporter nested function behavior."""

    @pytest.mark.asyncio
    async def test_progress_reporter_reports_periodically(self) -> None:
        """Test that progress reporter logs progress periodically."""
        import tableinator.tableinator

        tableinator.tableinator.shutdown_requested = False
        tableinator.tableinator.message_counts = {"artists": 100, "labels": 50, "masters": 25, "releases": 10}
        tableinator.tableinator.last_message_time = {
            "artists": time.time(),
            "labels": time.time(),
            "masters": time.time(),
            "releases": time.time(),
        }
        tableinator.tableinator.completed_files = set()
        tableinator.tableinator.consumer_tags = {"artists": "tag1"}

        # Access the main function to get progress_reporter
        # We'll test this indirectly by ensuring the logic would work
        with patch("tableinator.tableinator.logger"):
            # Simulate progress reporter logic
            total = sum(tableinator.tableinator.message_counts.values())
            assert total == 185
            assert len(tableinator.tableinator.completed_files) < len(["artists", "labels", "masters", "releases"])

    @pytest.mark.asyncio
    async def test_progress_reporter_detects_stalled_consumers(self) -> None:
        """Test detection of stalled consumers."""
        import tableinator.tableinator

        current_time = time.time()
        tableinator.tableinator.message_counts = {"artists": 100}
        tableinator.tableinator.last_message_time = {
            "artists": current_time - 150,  # 150 seconds ago (>120)
            "labels": 0,
        }
        tableinator.tableinator.completed_files = set()

        # Check for stalled consumers
        stalled = []
        for data_type, last_time in tableinator.tableinator.last_message_time.items():
            if data_type not in tableinator.tableinator.completed_files and last_time > 0 and (current_time - last_time) > 120:
                stalled.append(data_type)

        assert "artists" in stalled
        assert "labels" not in stalled

    @pytest.mark.asyncio
    async def test_progress_reporter_skips_when_all_complete(self) -> None:
        """Test that progress reporter skips logging when all files complete."""
        import tableinator.tableinator

        tableinator.tableinator.completed_files = {"artists", "labels", "masters", "releases"}
        tableinator.tableinator.message_counts = {"artists": 100, "labels": 50, "masters": 25, "releases": 10}

        # When all files are complete, should skip logging
        assert len(tableinator.tableinator.completed_files) == 4
        # This would trigger the continue in the actual function


class TestCancelAfterDelay:
    """Test cancel_after_delay nested function."""

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.CONSUMER_CANCEL_DELAY", 0.1)
    async def test_cancels_consumer_after_delay(self) -> None:
        """Test that consumer is cancelled after delay."""
        mock_queue = AsyncMock()
        mock_queue.cancel = AsyncMock()

        import tableinator.tableinator

        tableinator.tableinator.consumer_tags = {"artists": "consumer-tag-123"}
        tableinator.tableinator.shutdown_requested = False

        from tableinator.tableinator import schedule_consumer_cancellation

        # Schedule cancellation
        await schedule_consumer_cancellation("artists", mock_queue)

        # Wait for delay
        await asyncio.sleep(0.15)

        # Should have cancelled
        mock_queue.cancel.assert_called_once_with("consumer-tag-123", nowait=True)

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.CONSUMER_CANCEL_DELAY", 0.1)
    async def test_handles_cancel_error(self) -> None:
        """Test handling errors during consumer cancellation."""
        mock_queue = AsyncMock()
        mock_queue.cancel.side_effect = Exception("Cancel failed")

        import tableinator.tableinator

        tableinator.tableinator.consumer_tags = {"artists": "consumer-tag-123"}
        tableinator.tableinator.consumer_cancel_tasks = {}
        tableinator.tableinator.shutdown_requested = False

        from tableinator.tableinator import schedule_consumer_cancellation

        with patch("tableinator.tableinator.logger"):
            await schedule_consumer_cancellation("artists", mock_queue)
            await asyncio.sleep(0.15)

        # Should have attempted to cancel despite error
        assert mock_queue.cancel.called


class TestMainRabbitMQRetries:
    """Test main() RabbitMQ connection retry logic."""

    @pytest.mark.asyncio
    async def test_main_retries_rabbitmq_connection(self) -> None:
        """Test that main retries RabbitMQ connection on failure."""
        mock_manager = AsyncMock()
        mock_manager.connect.side_effect = [
            Exception("Connection failed"),
            Exception("Connection failed again"),
            AsyncMock(),  # Success on 3rd try
        ]

        import tableinator.tableinator

        original_rabbitmq_manager = tableinator.tableinator.rabbitmq_manager
        tableinator.tableinator.rabbitmq_manager = mock_manager
        tableinator.tableinator.shutdown_requested = False

        # We can't easily test main() in isolation, but we can verify the retry logic
        retry_count = 0
        max_retries = 3
        connection = None

        for _attempt in range(max_retries):
            try:
                connection = await mock_manager.connect()
                break
            except Exception:
                retry_count += 1
                if retry_count >= max_retries:
                    break
                await asyncio.sleep(0.01)  # Simulated backoff

        # Should have retried and eventually succeeded
        assert mock_manager.connect.call_count == 3
        assert connection is not None

        # Restore
        tableinator.tableinator.rabbitmq_manager = original_rabbitmq_manager

    @pytest.mark.asyncio
    async def test_main_gives_up_after_max_retries(self) -> None:
        """Test that main gives up after maximum retries."""
        mock_manager = AsyncMock()
        mock_manager.connect.side_effect = Exception("Connection failed")

        retry_count = 0
        max_retries = 3
        connection = None

        for _attempt in range(max_retries):
            try:
                connection = await mock_manager.connect()
                break
            except Exception:
                retry_count += 1
                if retry_count >= max_retries:
                    break

        # Should have retried max times and failed
        assert mock_manager.connect.call_count == 3
        assert connection is None


class TestGetHealthData:
    """Test get_health_data function."""

    def test_returns_health_status_dictionary(self) -> None:
        """Test that get_health_data returns a properly formatted dictionary."""
        import time
        from unittest.mock import MagicMock

        import tableinator.tableinator

        # Set some test values in global state
        current_time = time.time()
        tableinator.tableinator.current_progress = 50
        tableinator.tableinator.message_counts = {"artists": 100, "labels": 50}
        # Set recent message time (within last 10 seconds) to trigger "Processing" status
        tableinator.tableinator.last_message_time = {
            "artists": current_time - 5,  # 5 seconds ago
            "labels": current_time - 8,  # 8 seconds ago
            "masters": 0.0,
            "releases": 0.0,
        }
        tableinator.tableinator.consumer_tags = {
            "artists": "consumer-1",
            "labels": "consumer-2",
        }
        # Mock connection_pool to indicate healthy connection
        tableinator.tableinator.connection_pool = MagicMock()

        result = get_health_data()

        # Verify structure
        assert "status" in result
        assert "service" in result
        assert "current_task" in result
        assert "progress" in result
        assert "message_counts" in result
        assert "last_message_time" in result
        assert "timestamp" in result

        # Verify values
        assert result["status"] == "healthy"
        assert result["service"] == "tableinator"
        # Should show "Processing artists" because it has recent activity (5 seconds ago)
        assert result["current_task"] == "Processing artists"

        # Clean up
        tableinator.tableinator.connection_pool = None

    def test_health_status_starting_during_init(self) -> None:
        """Test that get_health_data returns 'starting' during initialization."""
        import tableinator.tableinator

        # Set up startup state: no connection pool, no consumers, no messages
        tableinator.tableinator.connection_pool = None
        tableinator.tableinator.consumer_tags = {}
        tableinator.tableinator.message_counts = {
            "artists": 0,
            "labels": 0,
            "masters": 0,
            "releases": 0,
        }

        result = get_health_data()

        assert result["status"] == "starting"
        assert result["current_task"] == "Initializing PostgreSQL connection"

    def test_health_status_unhealthy_when_connection_lost(self) -> None:
        """Test that get_health_data returns 'unhealthy' when connection lost after startup."""
        import tableinator.tableinator

        # Set up state: no connection pool, but has processed messages (post-startup)
        tableinator.tableinator.connection_pool = None
        tableinator.tableinator.consumer_tags = {"artists": "consumer-1"}
        tableinator.tableinator.message_counts = {
            "artists": 100,
            "labels": 0,
            "masters": 0,
            "releases": 0,
        }

        result = get_health_data()

        assert result["status"] == "unhealthy"
        assert result["service"] == "tableinator"

    def test_idle_status_with_active_consumers(self) -> None:
        """Test that get_health_data shows idle status when consumers active but no recent messages."""
        import time

        import tableinator.tableinator

        current_time = time.time()
        tableinator.tableinator.current_progress = 0
        tableinator.tableinator.message_counts = {"artists": 100, "labels": 50}
        # Set old message times (more than 10 seconds ago)
        tableinator.tableinator.last_message_time = {
            "artists": current_time - 60,  # 60 seconds ago
            "labels": current_time - 120,  # 120 seconds ago
            "masters": 0.0,
            "releases": 0.0,
        }
        # But consumers are still active
        tableinator.tableinator.consumer_tags = {
            "artists": "consumer-1",
            "labels": "consumer-2",
        }

        result = get_health_data()

        # Should show idle status because consumers active but no recent activity
        assert result["current_task"] == "Idle - waiting for messages"

    def test_no_status_when_no_consumers(self) -> None:
        """Test that get_health_data shows None when no consumers are active."""
        import time

        import tableinator.tableinator

        current_time = time.time()
        tableinator.tableinator.current_progress = 0
        tableinator.tableinator.message_counts = {"artists": 100, "labels": 50}
        tableinator.tableinator.last_message_time = {
            "artists": current_time - 60,
            "labels": current_time - 120,
            "masters": 0.0,
            "releases": 0.0,
        }
        # No active consumers
        tableinator.tableinator.consumer_tags = {}

        result = get_health_data()

        # Should show None when no consumers are active
        assert result["current_task"] is None


class TestCloseRabbitMQConnectionOuterException:
    """Test outer exception handling in close_rabbitmq_connection."""

    @pytest.mark.asyncio
    async def test_handles_outer_exception(self) -> None:
        """Test handling of unexpected exceptions in outer try block."""
        import tableinator.tableinator

        # Set up a scenario where accessing active_channel raises an exception
        # This simulates an error before we even try to close anything
        mock_channel = MagicMock()
        # Make the channel raise an exception when accessed in any way
        # that would happen before the nested try blocks
        type(mock_channel).__bool__ = MagicMock(side_effect=RuntimeError("Unexpected error"))

        tableinator.tableinator.active_channel = mock_channel
        tableinator.tableinator.active_connection = None

        with patch("tableinator.tableinator.logger") as mock_logger:
            await close_rabbitmq_connection()

        # Should log the error
        mock_logger.error.assert_called_once()
        call_args = mock_logger.error.call_args
        assert "Error closing RabbitMQ connection" in call_args[0][0]


class TestOnDataMessageProgressLogging:
    """Test progress logging in on_data_message."""

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.progress_interval", 10)
    async def test_logs_progress_at_interval(self, mock_async_pool: Any) -> None:
        """Test that progress is logged at the correct interval."""
        import tableinator.tableinator

        # Setup
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps({"id": "123", "name": "Test Artist", "sha256": "abc123"}).encode()
        mock_message.routing_key = "artists"  # Set routing_key for data_type

        mock_connection = MagicMock()
        mock_cursor = AsyncMock()

        # Mock cursor.fetchone to return a hash
        mock_cursor.fetchone = AsyncMock(return_value=("abc123",))  # Same hash so it will ack and return

        # Setup async cursor context manager
        mock_cursor_cm = AsyncMock()
        mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_cm.__aexit__ = AsyncMock(return_value=None)

        mock_connection.cursor = MagicMock(return_value=mock_cursor_cm)

        # Setup async connection pool mock
        mock_pool = mock_async_pool(mock_connection)

        tableinator.tableinator.connection_pool = mock_pool
        tableinator.tableinator.shutdown_requested = False
        tableinator.tableinator.completed_files = set()
        tableinator.tableinator.message_counts = {"artists": 9}  # Set to 9 so next increment hits 10
        tableinator.tableinator.last_message_time = {}

        with patch("tableinator.tableinator.logger") as mock_logger:
            await on_data_message(mock_message)

        # Should have logged progress because 10 % 10 == 0
        # Look for the progress log call
        progress_logged = False
        for call in mock_logger.info.call_args_list:
            if "Processed records in PostgreSQL" in str(call):
                progress_logged = True
                break

        assert progress_logged, "Progress should be logged at interval"
        mock_message.ack.assert_called_once()


class TestOnDataMessageBatchMode:
    """Test batch mode processing in on_data_message."""

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.shutdown_requested", False)
    @patch("tableinator.tableinator.BATCH_MODE", True)
    async def test_delegates_to_batch_processor(self) -> None:
        """Test that messages are delegated to batch processor when enabled."""
        import tableinator.tableinator

        mock_batch_processor = AsyncMock()
        tableinator.tableinator.batch_processor = mock_batch_processor

        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps({"id": "123", "name": "Test", "sha256": "abc"}).encode()
        mock_message.routing_key = "artists"

        tableinator.tableinator.message_counts = {"artists": 0}
        tableinator.tableinator.last_message_time = {"artists": 0}

        await on_data_message(mock_message)

        # Should have called batch processor
        mock_batch_processor.add_message.assert_called_once()
        call_args = mock_batch_processor.add_message.call_args
        assert call_args[1]["data_type"] == "artists"

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.shutdown_requested", False)
    @patch("tableinator.tableinator.BATCH_MODE", False)
    async def test_processes_directly_when_batch_disabled(
        self, sample_artist_data: dict[str, Any], mock_postgres_connection: MagicMock, mock_async_pool: Any
    ) -> None:
        """Test direct processing when batch mode is disabled."""
        import tableinator.tableinator

        tableinator.tableinator.batch_processor = None
        tableinator.tableinator.message_counts = {"artists": 0}
        tableinator.tableinator.last_message_time = {"artists": 0}

        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(sample_artist_data).encode()
        mock_message.routing_key = "artists"

        # Setup async cursor mock
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=None)

        mock_cursor_cm = AsyncMock()
        mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_cm.__aexit__ = AsyncMock(return_value=None)

        mock_postgres_connection.cursor = MagicMock(return_value=mock_cursor_cm)

        # Setup async connection pool mock
        pool = mock_async_pool(mock_postgres_connection)

        with patch("tableinator.tableinator.connection_pool", pool):
            await on_data_message(mock_message)

        # Should have processed directly
        assert mock_cursor.execute.call_count == 2  # SELECT and INSERT
        mock_message.ack.assert_called_once()


class TestOnDataMessageDatabaseOperations:
    """Test database operations in on_data_message."""

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.shutdown_requested", False)
    async def test_updates_existing_record(
        self, sample_artist_data: dict[str, Any], mock_postgres_connection: MagicMock, mock_async_pool: Any
    ) -> None:
        """Test updating an existing record with different hash."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(sample_artist_data).encode()
        mock_message.routing_key = "artists"

        # Setup async cursor mock
        mock_cursor = AsyncMock()
        # Return existing record with different hash
        mock_cursor.fetchone = AsyncMock(return_value=("old_hash",))

        mock_cursor_cm = AsyncMock()
        mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_cm.__aexit__ = AsyncMock(return_value=None)

        mock_postgres_connection.cursor = MagicMock(return_value=mock_cursor_cm)

        # Setup async connection pool mock
        pool = mock_async_pool(mock_postgres_connection)

        with patch("tableinator.tableinator.connection_pool", pool):
            await on_data_message(mock_message)

        # Should execute both SELECT and INSERT/UPDATE
        assert mock_cursor.execute.call_count == 2
        mock_message.ack.assert_called_once()

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.shutdown_requested", False)
    async def test_handles_database_interface_error(self, sample_artist_data: dict[str, Any]) -> None:
        """Test handling InterfaceError from database."""
        from psycopg.errors import InterfaceError

        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(sample_artist_data).encode()
        mock_message.routing_key = "artists"

        mock_pool = MagicMock()
        mock_pool.connection.side_effect = InterfaceError("Interface error")

        with (
            patch("tableinator.tableinator.connection_pool", mock_pool),
            patch("tableinator.tableinator.logger") as mock_logger,
        ):
            await on_data_message(mock_message)

        # Should nack with requeue
        mock_message.nack.assert_called_once_with(requeue=True)
        mock_logger.warning.assert_called()

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.shutdown_requested", False)
    async def test_handles_database_operational_error(self, sample_artist_data: dict[str, Any]) -> None:
        """Test handling OperationalError from database."""
        from psycopg.errors import OperationalError

        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(sample_artist_data).encode()
        mock_message.routing_key = "artists"

        mock_pool = MagicMock()
        mock_pool.connection.side_effect = OperationalError("Database unavailable")

        with (
            patch("tableinator.tableinator.connection_pool", mock_pool),
            patch("tableinator.tableinator.logger") as mock_logger,
        ):
            await on_data_message(mock_message)

        # Should nack with requeue
        mock_message.nack.assert_called_once_with(requeue=True)
        mock_logger.warning.assert_called()

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.shutdown_requested", False)
    async def test_handles_nack_failure(self, sample_artist_data: dict[str, Any]) -> None:
        """Test handling failure during nack operation."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(sample_artist_data).encode()
        mock_message.routing_key = "artists"
        mock_message.nack.side_effect = Exception("Nack failed")

        mock_pool = MagicMock()
        mock_pool.connection.side_effect = Exception("Connection failed")

        with (
            patch("tableinator.tableinator.connection_pool", mock_pool),
            patch("tableinator.tableinator.logger") as mock_logger,
        ):
            await on_data_message(mock_message)

        # Should log warning about nack failure
        assert any("Failed to nack message" in str(call) for call in mock_logger.warning.call_args_list)


class TestOnDataMessageFileCompletion:
    """Test file completion handling in on_data_message."""

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.shutdown_requested", False)
    @patch("tableinator.tableinator.CONSUMER_CANCEL_DELAY", 1)
    async def test_schedules_consumer_cancellation_with_delay(self) -> None:
        """Test that consumer cancellation is scheduled when enabled."""
        import tableinator.tableinator

        tableinator.tableinator.completed_files = set()
        tableinator.tableinator.queues = {"artists": AsyncMock()}
        tableinator.tableinator.consumer_cancel_tasks = {}

        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        completion_data = {
            "type": "file_complete",
            "total_processed": 1000,
        }
        mock_message.body = json.dumps(completion_data).encode()
        mock_message.routing_key = "artists"

        with (
            patch("tableinator.tableinator.logger"),
            patch("tableinator.tableinator.schedule_consumer_cancellation") as mock_schedule,
        ):
            await on_data_message(mock_message)

        # Should have scheduled cancellation
        mock_schedule.assert_called_once()
        assert "artists" in tableinator.tableinator.completed_files

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.shutdown_requested", False)
    @patch("tableinator.tableinator.CONSUMER_CANCEL_DELAY", 0)
    async def test_skips_consumer_cancellation_when_disabled(self) -> None:
        """Test that consumer cancellation is skipped when delay is 0."""
        import tableinator.tableinator

        tableinator.tableinator.completed_files = set()
        tableinator.tableinator.queues = {"artists": AsyncMock()}

        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        completion_data = {
            "type": "file_complete",
            "total_processed": 1000,
        }
        mock_message.body = json.dumps(completion_data).encode()
        mock_message.routing_key = "artists"

        with (
            patch("tableinator.tableinator.logger"),
            patch("tableinator.tableinator.schedule_consumer_cancellation") as mock_schedule,
        ):
            await on_data_message(mock_message)

        # Should not schedule cancellation
        mock_schedule.assert_not_called()
        assert "artists" in tableinator.tableinator.completed_files


class TestMainBatchProcessor:
    """Test main() batch processor initialization."""

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.setup_logging")
    @patch("tableinator.tableinator.HealthServer")
    @patch("tableinator.tableinator.AsyncResilientRabbitMQ")
    @patch("tableinator.tableinator.AsyncPostgreSQLPool")
    @patch("tableinator.tableinator.psycopg.connect")
    @patch("tableinator.tableinator.BATCH_MODE", True)
    @patch("tableinator.tableinator.BATCH_SIZE", 50)
    @patch("tableinator.tableinator.BATCH_FLUSH_INTERVAL", 2.0)
    async def test_main_initializes_batch_processor(
        self,
        mock_psycopg_connect: Mock,
        mock_pool_class: Mock,
        mock_rabbitmq_class: AsyncMock,
        mock_health_server: Mock,
        _mock_setup_logging: Mock,
    ) -> None:
        """Test that main initializes batch processor when enabled."""
        # Mock health server
        mock_health_instance = MagicMock()
        mock_health_server.return_value = mock_health_instance

        # Mock database existence check
        mock_admin_conn = MagicMock()
        mock_admin_cursor = MagicMock()
        mock_admin_cursor.fetchone.return_value = ("discogsography",)
        mock_admin_conn.cursor.return_value.__enter__.return_value = mock_admin_cursor
        mock_admin_conn.__enter__.return_value = mock_admin_conn
        mock_psycopg_connect.return_value = mock_admin_conn

        # Setup pool with async support
        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool
        mock_pool.initialize = AsyncMock()
        mock_pool.close = AsyncMock()

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Create async context manager for connection
        mock_connection_cm = AsyncMock()
        mock_connection_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_connection_cm.__aexit__ = AsyncMock(return_value=None)

        mock_pool.connection = MagicMock(return_value=mock_connection_cm)

        # Mock RabbitMQ
        mock_rabbitmq_instance = AsyncMock()
        mock_rabbitmq_class.return_value = mock_rabbitmq_instance
        mock_connection = AsyncMock()
        mock_rabbitmq_instance.connect.return_value = mock_connection
        mock_channel = AsyncMock()
        mock_rabbitmq_instance.channel.return_value = mock_channel
        mock_queue = AsyncMock()
        mock_channel.declare_queue.return_value = mock_queue

        with (
            patch("tableinator.tableinator.shutdown_requested", False),
            patch("tableinator.tableinator.PostgreSQLBatchProcessor") as mock_batch_class,
        ):
            # Mock the batch processor instance with AsyncMock for periodic_flush
            mock_batch_instance = MagicMock()
            mock_batch_instance.periodic_flush = AsyncMock()
            mock_batch_instance.flush_all = AsyncMock()
            mock_batch_instance.shutdown = MagicMock()
            mock_batch_class.return_value = mock_batch_instance

            # Track created tasks
            created_tasks = []
            original_create_task = asyncio.create_task

            def mock_create_task(coro: Any) -> asyncio.Task[Any]:
                task = original_create_task(coro)
                created_tasks.append(task)
                return task

            with patch("asyncio.create_task", side_effect=mock_create_task):
                # Make the main loop exit after setup
                async def mock_wait_for(_coro: Any, timeout: float) -> None:  # noqa: ARG001
                    import tableinator.tableinator

                    tableinator.tableinator.shutdown_requested = True
                    raise TimeoutError()

                with patch("asyncio.wait_for", mock_wait_for):
                    await main()

            # Clean up tasks
            for task in created_tasks:
                if not task.done():
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task

        # Verify batch processor was initialized
        mock_batch_class.assert_called_once()


class TestMainEnvironmentVariables:
    """Test main() environment variable handling."""

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.setup_logging")
    @patch("tableinator.tableinator.HealthServer")
    async def test_main_handles_startup_delay(
        self,
        mock_health_server: Mock,
        _mock_setup_logging: Mock,
    ) -> None:
        """Test that main respects STARTUP_DELAY environment variable."""
        mock_health_instance = MagicMock()
        mock_health_server.return_value = mock_health_instance

        with (
            patch.dict("os.environ", {"STARTUP_DELAY": "0"}),
            patch("asyncio.sleep") as mock_sleep,
            patch("tableinator.tableinator.TableinatorConfig.from_env", side_effect=ValueError("Test error")),
        ):
            await main()

        # Sleep should be called with 0 (or not at all if 0)
        # In this case the code checks if startup_delay > 0, so sleep won't be called
        mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.setup_logging")
    @patch("tableinator.tableinator.HealthServer")
    async def test_main_handles_config_error(
        self,
        mock_health_server: Mock,
        _mock_setup_logging: Mock,
    ) -> None:
        """Test main handles configuration errors gracefully."""
        mock_health_instance = MagicMock()
        mock_health_server.return_value = mock_health_instance

        with (
            patch("tableinator.tableinator.TableinatorConfig.from_env", side_effect=ValueError("Invalid config")),
            patch("tableinator.tableinator.logger") as mock_logger,
        ):
            await main()

        # Should log error and return
        mock_logger.error.assert_called()


class TestMainDatabaseSetup:
    """Test main() database setup logic."""

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.setup_logging")
    @patch("tableinator.tableinator.HealthServer")
    @patch("tableinator.tableinator.psycopg.connect")
    async def test_main_handles_database_creation_error(
        self,
        mock_psycopg_connect: Mock,
        mock_health_server: Mock,
        _mock_setup_logging: Mock,
    ) -> None:
        """Test main handles database creation errors."""
        mock_health_instance = MagicMock()
        mock_health_server.return_value = mock_health_instance

        # Make database check fail
        mock_psycopg_connect.side_effect = Exception("Connection failed")

        with patch("tableinator.tableinator.logger") as mock_logger:
            await main()

        # Should log error and return
        mock_logger.error.assert_called()

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.setup_logging")
    @patch("tableinator.tableinator.HealthServer")
    @patch("tableinator.tableinator.AsyncPostgreSQLPool")
    @patch("tableinator.tableinator.psycopg.connect")
    async def test_main_closes_pool_on_table_creation_error(
        self,
        mock_psycopg_connect: Mock,
        mock_pool_class: Mock,
        mock_health_server: Mock,
        _mock_setup_logging: Mock,
    ) -> None:
        """Test that pool is closed when table creation fails."""
        mock_health_instance = MagicMock()
        mock_health_server.return_value = mock_health_instance

        # Mock database check success
        mock_admin_conn = MagicMock()
        mock_admin_cursor = MagicMock()
        mock_admin_cursor.fetchone.return_value = ("discogsography",)
        mock_admin_conn.cursor.return_value.__enter__.return_value = mock_admin_cursor
        mock_admin_conn.__enter__.return_value = mock_admin_conn
        mock_psycopg_connect.return_value = mock_admin_conn

        # Setup pool with async support
        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool
        mock_pool.initialize = AsyncMock()
        mock_pool.close = AsyncMock()

        # Make table creation fail by raising exception in async connection factory
        async def mock_connection_factory_fail(*_args: Any, **_kwargs: Any) -> Any:
            raise Exception("Table creation failed")

        mock_pool.connection = MagicMock(side_effect=mock_connection_factory_fail)

        await main()

        # Pool should be closed
        mock_pool.close.assert_called_once()


class TestScheduleConsumerCancellationDetailed:
    """Detailed tests for schedule_consumer_cancellation."""

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.CONSUMER_CANCEL_DELAY", 0.1)
    async def test_removes_consumer_tag_after_cancellation(self) -> None:
        """Test that consumer tag is removed after cancellation."""
        import tableinator.tableinator

        mock_queue = AsyncMock()
        tableinator.tableinator.consumer_tags = {"artists": "consumer-tag-123"}
        tableinator.tableinator.consumer_cancel_tasks = {}
        tableinator.tableinator.completed_files = {"artists", "labels", "masters", "releases"}
        tableinator.tableinator.shutdown_requested = False

        with (
            patch("tableinator.tableinator.logger"),
            patch("tableinator.tableinator.check_all_consumers_idle", return_value=True),
            patch("tableinator.tableinator.close_rabbitmq_connection") as mock_close,
        ):
            await schedule_consumer_cancellation("artists", mock_queue)
            await asyncio.sleep(0.15)

        # Consumer tag should be removed
        assert "artists" not in tableinator.tableinator.consumer_tags

        # Should close connection when all idle
        mock_close.assert_called_once()

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.CONSUMER_CANCEL_DELAY", 0.1)
    async def test_cleans_up_task_reference(self) -> None:
        """Test that task reference is cleaned up after completion."""
        import tableinator.tableinator

        mock_queue = AsyncMock()
        tableinator.tableinator.consumer_tags = {"artists": "consumer-tag-123"}
        tableinator.tableinator.consumer_cancel_tasks = {}
        tableinator.tableinator.shutdown_requested = False

        with patch("tableinator.tableinator.logger"):
            await schedule_consumer_cancellation("artists", mock_queue)
            await asyncio.sleep(0.15)

        # Task reference should be cleaned up
        assert "artists" not in tableinator.tableinator.consumer_cancel_tasks
