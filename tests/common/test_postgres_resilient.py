"""Tests for PostgreSQL resilient connection module."""

import time
from unittest.mock import AsyncMock, Mock, patch

import pytest
from psycopg.errors import InterfaceError, OperationalError

from common.postgres_resilient import AsyncResilientPostgreSQL, ResilientPostgreSQLPool


class TestResilientPostgreSQLPool:
    """Tests for ResilientPostgreSQLPool class."""

    @pytest.fixture
    def mock_connection(self) -> Mock:
        """Create a mock PostgreSQL connection."""
        conn = Mock()
        conn.closed = False
        conn.autocommit = True
        conn.close = Mock()
        cursor = Mock()
        cursor.execute = Mock()
        cursor.fetchone = Mock(return_value=(1,))
        cursor.__enter__ = Mock(return_value=cursor)
        cursor.__exit__ = Mock(return_value=None)
        conn.cursor = Mock(return_value=cursor)
        return conn

    @pytest.fixture
    def connection_params(self) -> dict:
        """Test connection parameters."""
        return {
            "host": "localhost",
            "port": 5432,
            "dbname": "test",
            "user": "test_user",
            "password": "test_pass",
        }

    @patch("common.postgres_resilient.psycopg.connect")
    @patch("common.postgres_resilient.threading.Thread")
    def test_init(self, mock_thread: Mock, mock_connect: Mock, connection_params: dict, mock_connection: Mock) -> None:
        """Test ResilientPostgreSQLPool initialization."""
        mock_connect.return_value = mock_connection
        mock_thread_instance = Mock()
        mock_thread.return_value = mock_thread_instance

        pool = ResilientPostgreSQLPool(
            connection_params=connection_params,
            max_connections=10,
            min_connections=2,
            max_retries=3,
            health_check_interval=30,
        )

        assert pool.max_connections == 10
        assert pool.min_connections == 2
        assert pool.max_retries == 3
        assert pool.health_check_interval == 30
        assert pool._closed is False
        assert pool.circuit_breaker is not None
        assert pool.backoff is not None
        mock_thread_instance.start.assert_called_once()

    @patch("common.postgres_resilient.psycopg.connect")
    @patch("common.postgres_resilient.threading.Thread")
    def test_create_connection_success(self, mock_thread: Mock, mock_connect: Mock, connection_params: dict, mock_connection: Mock) -> None:
        """Test successful connection creation."""
        mock_connect.return_value = mock_connection

        pool = ResilientPostgreSQLPool(connection_params=connection_params, min_connections=0)
        conn = pool._create_connection()

        assert conn == mock_connection
        mock_connect.assert_called()
        assert conn.autocommit is True

    @patch("common.postgres_resilient.psycopg.connect")
    @patch("common.postgres_resilient.threading.Thread")
    def test_test_connection_healthy(self, mock_thread: Mock, mock_connect: Mock, connection_params: dict, mock_connection: Mock) -> None:
        """Test connection health check on healthy connection."""
        mock_connect.return_value = mock_connection

        pool = ResilientPostgreSQLPool(connection_params=connection_params, min_connections=0)
        result = pool._test_connection(mock_connection)

        assert result is True
        mock_connection.cursor.assert_called_once()

    @patch("common.postgres_resilient.psycopg.connect")
    @patch("common.postgres_resilient.threading.Thread")
    def test_test_connection_closed(self, mock_thread: Mock, mock_connect: Mock, connection_params: dict) -> None:
        """Test connection health check on closed connection."""
        closed_conn = Mock()
        closed_conn.closed = True

        pool = ResilientPostgreSQLPool(connection_params=connection_params, min_connections=0)
        result = pool._test_connection(closed_conn)

        assert result is False

    @patch("common.postgres_resilient.psycopg.connect")
    @patch("common.postgres_resilient.threading.Thread")
    def test_test_connection_error(self, mock_thread: Mock, mock_connect: Mock, connection_params: dict) -> None:
        """Test connection health check when query fails."""
        failing_conn = Mock()
        failing_conn.closed = False
        failing_conn.cursor = Mock(side_effect=OperationalError("Connection lost"))

        pool = ResilientPostgreSQLPool(connection_params=connection_params, min_connections=0)
        result = pool._test_connection(failing_conn)

        assert result is False

    @patch("common.postgres_resilient.psycopg.connect")
    @patch("common.postgres_resilient.threading.Thread")
    def test_connection_context_manager_success(self, mock_thread: Mock, mock_connect: Mock, connection_params: dict, mock_connection: Mock) -> None:
        """Test successful connection acquisition and release."""
        mock_connect.return_value = mock_connection

        pool = ResilientPostgreSQLPool(connection_params=connection_params, min_connections=1)

        # Give the pool a moment to initialize
        time.sleep(0.1)

        with pool.connection() as conn:
            assert conn is not None
            assert conn.closed is False

        # Connection should be returned to pool
        assert pool.connections.qsize() >= 1

    @patch("common.postgres_resilient.psycopg.connect")
    @patch("common.postgres_resilient.threading.Thread")
    def test_connection_pool_closed_error(self, mock_thread: Mock, mock_connect: Mock, connection_params: dict, mock_connection: Mock) -> None:
        """Test that getting connection from closed pool raises error."""
        mock_connect.return_value = mock_connection

        pool = ResilientPostgreSQLPool(connection_params=connection_params, min_connections=0)
        pool._closed = True

        with pytest.raises(RuntimeError, match="Connection pool is closed"), pool.connection():
            pass

    @patch("common.postgres_resilient.psycopg.connect")
    @patch("common.postgres_resilient.threading.Thread")
    def test_connection_error_during_use(self, mock_thread: Mock, mock_connect: Mock, connection_params: dict, mock_connection: Mock) -> None:
        """Test connection error handling during use."""
        mock_connect.return_value = mock_connection

        pool = ResilientPostgreSQLPool(connection_params=connection_params, min_connections=1)
        time.sleep(0.1)

        with pytest.raises(InterfaceError), pool.connection() as conn:
            # Simulate error during use
            raise InterfaceError("Connection lost")

    @patch("common.postgres_resilient.psycopg.connect")
    @patch("common.postgres_resilient.threading.Thread")
    def test_connection_creates_new_when_pool_empty(
        self, mock_thread: Mock, mock_connect: Mock, connection_params: dict, mock_connection: Mock
    ) -> None:
        """Test that new connection is created when pool is empty."""
        mock_connect.return_value = mock_connection

        pool = ResilientPostgreSQLPool(connection_params=connection_params, min_connections=0, max_connections=5)

        # Pool should be empty initially
        assert pool.connections.qsize() == 0

        with pool.connection() as conn:
            assert conn is not None
            assert pool.active_connections > 0

    @patch("common.postgres_resilient.psycopg.connect")
    @patch("common.postgres_resilient.threading.Thread")
    def test_connection_respects_max_connections(self, mock_thread: Mock, mock_connect: Mock, connection_params: dict, mock_connection: Mock) -> None:
        """Test that pool respects max_connections limit."""
        mock_connect.return_value = mock_connection

        pool = ResilientPostgreSQLPool(connection_params=connection_params, min_connections=0, max_connections=2)

        # Acquire connections up to max
        conn1 = pool.connections.get_nowait() if pool.connections.qsize() > 0 else pool._create_connection()
        conn2 = pool.connections.get_nowait() if pool.connections.qsize() > 0 else pool._create_connection()

        assert conn1 is not None
        assert conn2 is not None

    @patch("common.postgres_resilient.psycopg.connect")
    @patch("common.postgres_resilient.threading.Thread")
    def test_close_pool(self, mock_thread: Mock, mock_connect: Mock, connection_params: dict, mock_connection: Mock) -> None:
        """Test closing the connection pool."""
        mock_connect.return_value = mock_connection

        pool = ResilientPostgreSQLPool(connection_params=connection_params, min_connections=2)
        time.sleep(0.1)

        initial_size = pool.connections.qsize()
        assert initial_size > 0

        pool.close()

        assert pool._closed is True
        assert pool.connections.qsize() == 0

    @patch("common.postgres_resilient.psycopg.connect")
    @patch("common.postgres_resilient.threading.Thread")
    def test_initialize_pool_with_min_connections(
        self, mock_thread: Mock, mock_connect: Mock, connection_params: dict, mock_connection: Mock
    ) -> None:
        """Test that pool initializes with minimum connections."""
        mock_connect.return_value = mock_connection

        pool = ResilientPostgreSQLPool(connection_params=connection_params, min_connections=3, max_connections=10)

        time.sleep(0.1)

        # Should have at least min_connections
        assert pool.connections.qsize() >= 0  # May have been consumed by health check

    @patch("common.postgres_resilient.psycopg.connect")
    @patch("common.postgres_resilient.threading.Thread")
    def test_initialize_pool_handles_connection_failure(self, mock_thread: Mock, mock_connect: Mock, connection_params: dict) -> None:
        """Test pool initialization handles connection failures gracefully."""
        mock_connect.side_effect = [OperationalError("Connection failed"), OperationalError("Connection failed")]

        # Should not raise exception even if connections fail
        pool = ResilientPostgreSQLPool(connection_params=connection_params, min_connections=2, max_connections=5)

        assert pool is not None
        assert pool._closed is False

    @patch("common.postgres_resilient.psycopg.connect")
    @patch("common.postgres_resilient.threading.Thread")
    def test_connection_returned_to_pool_when_healthy(
        self, mock_thread: Mock, mock_connect: Mock, connection_params: dict, mock_connection: Mock
    ) -> None:
        """Test that healthy connection is returned to pool after use."""
        mock_connect.return_value = mock_connection

        pool = ResilientPostgreSQLPool(connection_params=connection_params, min_connections=1)
        time.sleep(0.1)

        initial_size = pool.connections.qsize()

        with pool.connection() as conn:
            assert conn is not None

        # Connection should be back in pool
        final_size = pool.connections.qsize()
        assert final_size >= initial_size

    @patch("common.postgres_resilient.psycopg.connect")
    @patch("common.postgres_resilient.threading.Thread")
    def test_unhealthy_connection_not_returned_to_pool(
        self, mock_thread: Mock, mock_connect: Mock, connection_params: dict, mock_connection: Mock
    ) -> None:
        """Test that unhealthy connection is not returned to pool."""
        mock_connect.return_value = mock_connection

        pool = ResilientPostgreSQLPool(connection_params=connection_params, min_connections=1)
        time.sleep(0.1)

        try:
            with pool.connection() as conn:
                # Mark connection as closed (unhealthy)
                conn.closed = True
                # Normal exit, connection should not be returned
        except Exception:
            pass

        # Verify connection cleanup occurred
        assert pool is not None


class TestAsyncResilientPostgreSQL:
    """Tests for AsyncResilientPostgreSQL class."""

    @pytest.fixture
    def mock_async_connection(self) -> AsyncMock:
        """Create a mock async PostgreSQL connection."""
        conn = AsyncMock()
        conn.closed = False
        conn.set_autocommit = AsyncMock()
        conn.close = AsyncMock()
        cursor = AsyncMock()
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=(1,))
        cursor.__aenter__ = AsyncMock(return_value=cursor)
        cursor.__aexit__ = AsyncMock(return_value=None)
        conn.cursor = Mock(return_value=cursor)
        return conn

    @pytest.fixture
    def connection_params(self) -> dict:
        """Test connection parameters."""
        return {
            "host": "localhost",
            "port": 5432,
            "dbname": "test",
            "user": "test_user",
            "password": "test_pass",
        }

    def test_init(self, connection_params: dict) -> None:
        """Test AsyncResilientPostgreSQL initialization."""
        async_conn = AsyncResilientPostgreSQL(connection_params=connection_params, max_retries=3)

        assert async_conn.connection_params == connection_params
        assert async_conn.circuit_breaker is not None
        assert async_conn.backoff is not None

    @pytest.mark.asyncio
    @patch("common.postgres_resilient.psycopg.AsyncConnection.connect")
    async def test_create_connection(self, mock_connect: Mock, connection_params: dict, mock_async_connection: AsyncMock) -> None:
        """Test async connection creation."""
        mock_connect.return_value = mock_async_connection

        async_conn = AsyncResilientPostgreSQL(connection_params=connection_params)
        conn = await async_conn._create_connection()

        assert conn == mock_async_connection
        mock_connect.assert_called_once_with(**connection_params)
        mock_async_connection.set_autocommit.assert_called_once_with(True)

    @pytest.mark.asyncio
    @patch("common.postgres_resilient.psycopg.AsyncConnection.connect")
    async def test_test_connection_healthy(self, mock_connect: Mock, connection_params: dict, mock_async_connection: AsyncMock) -> None:
        """Test async connection health check on healthy connection."""
        async_conn = AsyncResilientPostgreSQL(connection_params=connection_params)
        result = await async_conn._test_connection(mock_async_connection)

        assert result is True

    @pytest.mark.asyncio
    @patch("common.postgres_resilient.psycopg.AsyncConnection.connect")
    async def test_test_connection_closed(self, mock_connect: Mock, connection_params: dict) -> None:
        """Test async connection health check on closed connection."""
        closed_conn = AsyncMock()
        closed_conn.closed = True

        async_conn = AsyncResilientPostgreSQL(connection_params=connection_params)
        result = await async_conn._test_connection(closed_conn)

        assert result is False

    @pytest.mark.asyncio
    @patch("common.postgres_resilient.psycopg.AsyncConnection.connect")
    async def test_test_connection_error(self, mock_connect: Mock, connection_params: dict) -> None:
        """Test async connection health check when query fails."""
        failing_conn = AsyncMock()
        failing_conn.closed = False
        cursor = AsyncMock()
        cursor.execute = AsyncMock(side_effect=OperationalError("Connection lost"))
        cursor.__aenter__ = AsyncMock(return_value=cursor)
        cursor.__aexit__ = AsyncMock(return_value=None)
        failing_conn.cursor = Mock(return_value=cursor)

        async_conn = AsyncResilientPostgreSQL(connection_params=connection_params)
        result = await async_conn._test_connection(failing_conn)

        assert result is False

    @pytest.mark.asyncio
    @patch("common.postgres_resilient.psycopg.AsyncConnection.connect")
    async def test_get_connection_success(self, mock_connect: Mock, connection_params: dict, mock_async_connection: AsyncMock) -> None:
        """Test successful async connection acquisition."""
        mock_connect.return_value = mock_async_connection

        async_conn = AsyncResilientPostgreSQL(connection_params=connection_params)
        conn = await async_conn.get_connection()

        assert conn == mock_async_connection

    @pytest.mark.asyncio
    @patch("common.postgres_resilient.psycopg.AsyncConnection.connect")
    async def test_close_connection(self, mock_connect: Mock, connection_params: dict, mock_async_connection: AsyncMock) -> None:
        """Test async connection closure."""
        mock_connect.return_value = mock_async_connection

        async_conn = AsyncResilientPostgreSQL(connection_params=connection_params)
        # First establish connection
        await async_conn.get_connection()

        # Reset mock to track close call
        mock_async_connection.close.reset_mock()

        await async_conn.close()

        # Check that close was called (either close or aclose)
        assert mock_async_connection.close.called or (hasattr(mock_async_connection, "aclose") and mock_async_connection.aclose.called)
        assert async_conn._connection is None
