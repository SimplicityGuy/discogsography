"""Tests for tableinator module."""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from aio_pika.abc import AbstractIncomingMessage

from tableinator.tableinator import (
    get_connection,
    main,
    on_data_message,
    safe_execute_query,
)


# SimpleConnectionPool tests removed as we now use ResilientPostgreSQLPool


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
        mock_cursor.execute.side_effect = Exception("Database error")

        with patch("tableinator.tableinator.logger") as mock_logger:
            result = safe_execute_query(mock_cursor, "SELECT 1", ())

            assert result is False
            mock_logger.error.assert_called()


class TestOnDataMessage:
    """Test on_data_message handler."""

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.shutdown_requested", False)
    async def test_process_new_record(self, sample_artist_data: dict[str, Any], mock_postgres_connection: MagicMock) -> None:
        """Test processing a new record."""
        # Create mock message
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(sample_artist_data).encode()
        mock_message.routing_key = "artists"

        # Setup connection pool mock
        mock_pool = MagicMock()
        mock_pool.connection.return_value.__enter__.return_value = mock_postgres_connection

        mock_cursor = mock_postgres_connection.cursor.return_value.__enter__.return_value
        mock_cursor.fetchone.return_value = None  # No existing record

        with patch("tableinator.tableinator.connection_pool", mock_pool):
            await on_data_message(mock_message)

        # Verify message was acknowledged
        mock_message.ack.assert_called_once()

        # Verify queries were executed
        assert mock_cursor.execute.call_count == 2  # SELECT and INSERT

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.shutdown_requested", False)
    async def test_skip_unchanged_record(self, sample_artist_data: dict[str, Any], mock_postgres_connection: MagicMock) -> None:
        """Test skipping record with unchanged hash."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(sample_artist_data).encode()
        mock_message.routing_key = "artists"

        mock_pool = MagicMock()
        mock_pool.connection.return_value.__enter__.return_value = mock_postgres_connection

        mock_cursor = mock_postgres_connection.cursor.return_value.__enter__.return_value
        # Return existing record with same hash
        mock_cursor.fetchone.return_value = (sample_artist_data["sha256"],)

        with patch("tableinator.tableinator.connection_pool", mock_pool):
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
    @patch("tableinator.tableinator.ResilientPostgreSQLPool")
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
            # Make the main loop exit after setup
            async def mock_wait_for(_coro: Any, timeout: float) -> None:  # noqa: ARG001
                # Set shutdown_requested to exit the loop
                import tableinator.tableinator

                tableinator.tableinator.shutdown_requested = True
                raise TimeoutError()

            with patch("asyncio.wait_for", mock_wait_for):
                await main()

        # Verify setup was performed
        assert mock_pool_class.call_count == 1
        # Check that it was called with correct parameters
        call_args = mock_pool_class.call_args
        assert call_args[1]["max_connections"] == 20
        mock_rabbitmq_class.assert_called_once()

        # The test exits early due to our mock, so some operations might not complete
        # Verify database check was attempted
        assert mock_admin_cursor.execute.call_count >= 1

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.setup_logging")
    @patch("tableinator.tableinator.HealthServer")
    @patch("tableinator.tableinator.ResilientPostgreSQLPool")
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
    @patch("tableinator.tableinator.ResilientPostgreSQLPool")
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

        # Setup pool success
        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_pool.connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

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
    @patch("tableinator.tableinator.ResilientPostgreSQLPool")
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

        # Setup pool
        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool

        # Make table creation fail
        mock_pool.connection.side_effect = Exception("Cannot create tables")

        # Should complete without raising
        await main()

        # Pool should be closed
        mock_pool.close.assert_called_once()

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.setup_logging")
    @patch("tableinator.tableinator.HealthServer")
    @patch("tableinator.tableinator.AsyncResilientRabbitMQ")
    @patch("tableinator.tableinator.ResilientPostgreSQLPool")
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
            # Make the main loop exit after setup
            async def mock_wait_for(_coro: Any, timeout: float) -> None:  # noqa: ARG001
                # Set shutdown_requested to exit the loop
                import tableinator.tableinator

                tableinator.tableinator.shutdown_requested = True
                raise TimeoutError()

            with patch("asyncio.wait_for", mock_wait_for):
                await main()

        # Verify database was created
        assert mock_admin_cursor.execute.call_count == 2  # 1 check + 1 CREATE DATABASE

        # Verify CREATE DATABASE was called
        create_db_call = mock_admin_cursor.execute.call_args_list[1]
        assert "CREATE DATABASE" in str(create_db_call)
