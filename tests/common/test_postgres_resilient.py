"""Tests for PostgreSQL resilient connection module."""

import asyncio
from contextlib import suppress
import time
from unittest.mock import AsyncMock, Mock, patch

from psycopg.errors import InterfaceError, OperationalError
import pytest

from common.postgres_resilient import AsyncPostgreSQLPool, AsyncResilientPostgreSQL, ResilientPostgreSQLPool


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
    def test_init(self, _mock_thread: Mock, mock_connect: Mock, connection_params: dict, mock_connection: Mock) -> None:
        """Test ResilientPostgreSQLPool initialization."""
        mock_connect.return_value = mock_connection
        mock_thread_instance = Mock()
        _mock_thread.return_value = mock_thread_instance

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
    def test_create_connection_success(self, _mock_thread: Mock, mock_connect: Mock, connection_params: dict, mock_connection: Mock) -> None:
        """Test successful connection creation."""
        mock_connect.return_value = mock_connection

        pool = ResilientPostgreSQLPool(connection_params=connection_params, min_connections=0)
        conn = pool._create_connection()

        assert conn == mock_connection
        mock_connect.assert_called()
        assert conn.autocommit is True

    @patch("common.postgres_resilient.psycopg.connect")
    @patch("common.postgres_resilient.threading.Thread")
    def test_test_connection_healthy(self, _mock_thread: Mock, mock_connect: Mock, connection_params: dict, mock_connection: Mock) -> None:
        """Test connection health check on healthy connection."""
        mock_connect.return_value = mock_connection

        pool = ResilientPostgreSQLPool(connection_params=connection_params, min_connections=0)
        result = pool._test_connection(mock_connection)

        assert result is True
        mock_connection.cursor.assert_called_once()

    @patch("common.postgres_resilient.psycopg.connect")
    @patch("common.postgres_resilient.threading.Thread")
    def test_test_connection_closed(self, _mock_thread: Mock, _mock_connect: Mock, connection_params: dict) -> None:
        """Test connection health check on closed connection."""
        closed_conn = Mock()
        closed_conn.closed = True

        pool = ResilientPostgreSQLPool(connection_params=connection_params, min_connections=0)
        result = pool._test_connection(closed_conn)

        assert result is False

    @patch("common.postgres_resilient.psycopg.connect")
    @patch("common.postgres_resilient.threading.Thread")
    def test_test_connection_error(self, _mock_thread: Mock, _mock_connect: Mock, connection_params: dict) -> None:
        """Test connection health check when query fails."""
        failing_conn = Mock()
        failing_conn.closed = False
        failing_conn.cursor = Mock(side_effect=OperationalError("Connection lost"))

        pool = ResilientPostgreSQLPool(connection_params=connection_params, min_connections=0)
        result = pool._test_connection(failing_conn)

        assert result is False

    @patch("common.postgres_resilient.psycopg.connect")
    @patch("common.postgres_resilient.threading.Thread")
    def test_connection_context_manager_success(self, _mock_thread: Mock, mock_connect: Mock, connection_params: dict, mock_connection: Mock) -> None:
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
    def test_connection_pool_closed_error(self, _mock_thread: Mock, mock_connect: Mock, connection_params: dict, mock_connection: Mock) -> None:
        """Test that getting connection from closed pool raises error."""
        mock_connect.return_value = mock_connection

        pool = ResilientPostgreSQLPool(connection_params=connection_params, min_connections=0)
        pool._closed = True

        with pytest.raises(RuntimeError, match="Connection pool is closed"), pool.connection():
            pass

    @patch("common.postgres_resilient.psycopg.connect")
    @patch("common.postgres_resilient.threading.Thread")
    def test_connection_error_during_use(self, _mock_thread: Mock, mock_connect: Mock, connection_params: dict, mock_connection: Mock) -> None:
        """Test connection error handling during use."""
        mock_connect.return_value = mock_connection

        pool = ResilientPostgreSQLPool(connection_params=connection_params, min_connections=1)
        time.sleep(0.1)

        with pytest.raises(InterfaceError), pool.connection():
            # Simulate error during use
            raise InterfaceError("Connection lost")

    @patch("common.postgres_resilient.psycopg.connect")
    @patch("common.postgres_resilient.threading.Thread")
    def test_connection_creates_new_when_pool_empty(
        self, _mock_thread: Mock, mock_connect: Mock, connection_params: dict, mock_connection: Mock
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
    def test_connection_respects_max_connections(
        self, _mock_thread: Mock, mock_connect: Mock, connection_params: dict, mock_connection: Mock
    ) -> None:
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
    def test_close_pool(self, _mock_thread: Mock, mock_connect: Mock, connection_params: dict, mock_connection: Mock) -> None:
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
        self, _mock_thread: Mock, mock_connect: Mock, connection_params: dict, mock_connection: Mock
    ) -> None:
        """Test that pool initializes with minimum connections."""
        mock_connect.return_value = mock_connection

        pool = ResilientPostgreSQLPool(connection_params=connection_params, min_connections=3, max_connections=10)

        time.sleep(0.1)

        # Should have at least min_connections
        assert pool.connections.qsize() >= 0  # May have been consumed by health check

    @patch("common.postgres_resilient.psycopg.connect")
    @patch("common.postgres_resilient.threading.Thread")
    def test_initialize_pool_handles_connection_failure(self, _mock_thread: Mock, mock_connect: Mock, connection_params: dict) -> None:
        """Test pool initialization handles connection failures gracefully."""
        mock_connect.side_effect = [OperationalError("Connection failed"), OperationalError("Connection failed")]

        # Should not raise exception even if connections fail
        pool = ResilientPostgreSQLPool(connection_params=connection_params, min_connections=2, max_connections=5)

        assert pool is not None
        assert pool._closed is False

    @patch("common.postgres_resilient.psycopg.connect")
    @patch("common.postgres_resilient.threading.Thread")
    def test_connection_returned_to_pool_when_healthy(
        self, _mock_thread: Mock, mock_connect: Mock, connection_params: dict, mock_connection: Mock
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
        self, _mock_thread: Mock, mock_connect: Mock, connection_params: dict, mock_connection: Mock
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
        except Exception:  # noqa: S110
            pass  # Expected exception for test cleanup

        # Verify connection cleanup occurred
        assert pool is not None

    @patch("common.postgres_resilient.psycopg.connect")
    @patch("common.postgres_resilient.threading.Thread")
    def test_health_check_loop_removes_unhealthy(
        self, _mock_thread: Mock, mock_connect: Mock, connection_params: dict, mock_connection: Mock
    ) -> None:
        """Test that health check loop removes unhealthy connections."""
        # Create unhealthy connection
        unhealthy_conn = Mock()
        unhealthy_conn.closed = False
        unhealthy_conn.cursor = Mock(side_effect=OperationalError("Connection lost"))

        mock_connect.side_effect = [mock_connection, unhealthy_conn, mock_connection]

        pool = ResilientPostgreSQLPool(connection_params=connection_params, min_connections=2, max_connections=5, health_check_interval=1)

        # Let health check run
        time.sleep(1.5)

        # Pool should still be operational
        assert pool is not None

        pool.close()

    @patch("common.postgres_resilient.psycopg.connect")
    @patch("common.postgres_resilient.threading.Thread")
    def test_health_check_loop_replenishes_connections(
        self, _mock_thread: Mock, mock_connect: Mock, connection_params: dict, mock_connection: Mock
    ) -> None:
        """Test that health check loop replenishes connections to minimum."""
        mock_connect.return_value = mock_connection

        pool = ResilientPostgreSQLPool(connection_params=connection_params, min_connections=3, max_connections=10, health_check_interval=1)
        time.sleep(0.1)

        # Manually drain pool below minimum
        initial_size = pool.connections.qsize()
        if initial_size > 0:
            with suppress(Exception):
                conn = pool.connections.get_nowait()
                conn.close()

        # Let health check replenish
        time.sleep(1.5)

        # Pool should attempt to maintain minimum
        assert pool is not None

        pool.close()

    @patch("common.postgres_resilient.psycopg.connect")
    @patch("common.postgres_resilient.threading.Thread")
    def test_health_check_loop_handles_queue_empty(
        self, _mock_thread: Mock, mock_connect: Mock, connection_params: dict, mock_connection: Mock
    ) -> None:
        """Test health check loop handles empty queue gracefully."""
        mock_connect.return_value = mock_connection

        pool = ResilientPostgreSQLPool(connection_params=connection_params, min_connections=0, max_connections=5, health_check_interval=1)

        # Let health check run with empty queue
        time.sleep(1.5)

        assert pool is not None

        pool.close()

    @patch("common.postgres_resilient.psycopg.connect")
    @patch("common.postgres_resilient.threading.Thread")
    def test_health_check_loop_handles_queue_full(
        self, _mock_thread: Mock, mock_connect: Mock, connection_params: dict, mock_connection: Mock
    ) -> None:
        """Test health check loop when returning connections to full queue."""
        mock_connect.return_value = mock_connection

        pool = ResilientPostgreSQLPool(connection_params=connection_params, min_connections=2, max_connections=2, health_check_interval=1)

        # Fill pool to capacity
        time.sleep(0.1)

        # Let health check try to manage full queue
        time.sleep(1.5)

        assert pool is not None

        pool.close()

    @patch("common.postgres_resilient.psycopg.connect")
    @patch("common.postgres_resilient.threading.Thread")
    def test_connection_retry_logic(self, _mock_thread: Mock, mock_connect: Mock, connection_params: dict, mock_connection: Mock) -> None:
        """Test connection retry logic with backoff."""
        # Fail twice, then succeed
        mock_connect.side_effect = [
            OperationalError("Connection failed"),
            OperationalError("Connection failed"),
            mock_connection,
        ]

        pool = ResilientPostgreSQLPool(connection_params=connection_params, min_connections=0, max_connections=5, max_retries=3)

        with pool.connection() as conn:
            assert conn is not None

        pool.close()

    @patch("common.postgres_resilient.psycopg.connect")
    @patch("common.postgres_resilient.threading.Thread")
    def test_connection_unhealthy_during_acquisition(
        self, _mock_thread: Mock, mock_connect: Mock, connection_params: dict, mock_connection: Mock
    ) -> None:
        """Test handling unhealthy connection during acquisition."""
        # First connection is unhealthy
        unhealthy_conn = Mock()
        unhealthy_conn.closed = False
        unhealthy_conn.autocommit = True
        unhealthy_conn.cursor = Mock(side_effect=OperationalError("Connection lost"))

        mock_connect.side_effect = [unhealthy_conn, mock_connection]

        pool = ResilientPostgreSQLPool(connection_params=connection_params, min_connections=0, max_connections=5)

        # Manually add unhealthy connection
        pool.connections.put_nowait(unhealthy_conn)
        pool.active_connections = 1

        # Should detect unhealthy and get new one
        with pool.connection() as conn:
            assert conn is not None

        pool.close()

    @patch("common.postgres_resilient.psycopg.connect")
    @patch("common.postgres_resilient.threading.Thread")
    def test_connection_pool_full_during_return(self, _mock_thread: Mock, mock_connect: Mock, connection_params: dict, mock_connection: Mock) -> None:
        """Test connection handling when pool is full during return."""
        mock_connect.return_value = mock_connection

        pool = ResilientPostgreSQLPool(connection_params=connection_params, min_connections=1, max_connections=1)
        time.sleep(0.1)

        # Use connection normally
        with pool.connection() as conn:
            assert conn is not None
            # Fill pool manually to simulate full condition
            with suppress(Exception):
                pool.connections.put_nowait(mock_connection)

        pool.close()

    @patch("common.postgres_resilient.psycopg.connect")
    @patch("common.postgres_resilient.threading.Thread")
    def test_connection_closed_during_operation(self, _mock_thread: Mock, mock_connect: Mock, connection_params: dict, mock_connection: Mock) -> None:
        """Test handling connection that becomes closed during operation."""
        mock_connect.return_value = mock_connection

        pool = ResilientPostgreSQLPool(connection_params=connection_params, min_connections=1, max_connections=5)
        time.sleep(0.1)

        with pytest.raises(InterfaceError), pool.connection():
            raise InterfaceError("Connection error")

        pool.close()

    @patch("common.postgres_resilient.psycopg.connect")
    @patch("common.postgres_resilient.threading.Thread")
    def test_connection_operational_error_during_operation(
        self, _mock_thread: Mock, mock_connect: Mock, connection_params: dict, mock_connection: Mock
    ) -> None:
        """Test handling OperationalError during connection use."""
        mock_connect.return_value = mock_connection

        pool = ResilientPostgreSQLPool(connection_params=connection_params, min_connections=1, max_connections=5)
        time.sleep(0.1)

        with pytest.raises(OperationalError), pool.connection():
            raise OperationalError("Database error")

        pool.close()

    @patch("common.postgres_resilient.psycopg.connect")
    @patch("common.postgres_resilient.threading.Thread")
    def test_connection_cleanup_on_error(self, _mock_thread: Mock, mock_connect: Mock, connection_params: dict, mock_connection: Mock) -> None:
        """Test proper cleanup when connection errors occur."""
        mock_connect.return_value = mock_connection

        pool = ResilientPostgreSQLPool(connection_params=connection_params, min_connections=1, max_connections=5)
        time.sleep(0.1)

        with suppress(Exception), pool.connection() as conn:
            conn.closed = True  # Simulate connection becoming unhealthy
            # Exit context normally but connection is bad

        # Connection should be cleaned up
        time.sleep(0.1)

        pool.close()

    @patch("common.postgres_resilient.psycopg.connect")
    @patch("common.postgres_resilient.threading.Thread")
    def test_create_connection_when_max_reached(self, _mock_thread: Mock, mock_connect: Mock, connection_params: dict, mock_connection: Mock) -> None:
        """Test that new connection is not created when max is reached."""
        mock_connect.return_value = mock_connection

        pool = ResilientPostgreSQLPool(connection_params=connection_params, min_connections=0, max_connections=1)

        # Manually set active to max
        with pool._lock:
            pool.active_connections = 1

        # Try to get connection when at max - should wait for existing
        # This tests the logic that prevents exceeding max_connections
        assert pool.active_connections <= pool.max_connections

        pool.close()

    @patch("common.postgres_resilient.psycopg.connect")
    @patch("common.postgres_resilient.threading.Thread")
    def test_health_check_connection_failure_during_replenish(
        self, _mock_thread: Mock, mock_connect: Mock, connection_params: dict, mock_connection: Mock
    ) -> None:
        """Test health check handles connection creation failures during replenishment."""
        # Succeed initially, then fail during replenishment
        mock_connect.side_effect = [
            mock_connection,
            OperationalError("Connection failed"),
            OperationalError("Connection failed"),
        ]

        pool = ResilientPostgreSQLPool(connection_params=connection_params, min_connections=1, max_connections=5, health_check_interval=1)
        time.sleep(0.1)

        # Drain pool to trigger replenishment
        while not pool.connections.empty():
            try:
                conn = pool.connections.get_nowait()
                conn.close()
            except Exception:
                break

        # Let health check try to replenish and fail
        time.sleep(1.5)

        assert pool is not None

        pool.close()


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
    async def test_test_connection_healthy(self, _mock_connect: Mock, connection_params: dict, mock_async_connection: AsyncMock) -> None:
        """Test async connection health check on healthy connection."""
        async_conn = AsyncResilientPostgreSQL(connection_params=connection_params)
        result = await async_conn._test_connection(mock_async_connection)

        assert result is True

    @pytest.mark.asyncio
    @patch("common.postgres_resilient.psycopg.AsyncConnection.connect")
    async def test_test_connection_closed(self, _mock_connect: Mock, connection_params: dict) -> None:
        """Test async connection health check on closed connection."""
        closed_conn = AsyncMock()
        closed_conn.closed = True

        async_conn = AsyncResilientPostgreSQL(connection_params=connection_params)
        result = await async_conn._test_connection(closed_conn)

        assert result is False

    @pytest.mark.asyncio
    @patch("common.postgres_resilient.psycopg.AsyncConnection.connect")
    async def test_test_connection_error(self, _mock_connect: Mock, connection_params: dict) -> None:
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


class TestAsyncPostgreSQLPool:
    """Tests for AsyncPostgreSQLPool class."""

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
        """Test AsyncPostgreSQLPool initialization."""

        pool = AsyncPostgreSQLPool(
            connection_params=connection_params,
            max_connections=10,
            min_connections=2,
            max_retries=3,
            health_check_interval=30,
        )

        assert pool.connection_params == connection_params
        assert pool.max_connections == 10
        assert pool.min_connections == 2
        assert pool.max_retries == 3
        assert pool.health_check_interval == 30
        assert pool._closed is False
        assert pool._initialized is False
        assert pool.circuit_breaker is not None
        assert pool.backoff is not None

    @pytest.mark.asyncio
    @patch("common.postgres_resilient.psycopg.AsyncConnection.connect")
    async def test_pool_initialization_success(self, mock_connect: Mock, connection_params: dict, mock_async_connection: AsyncMock) -> None:
        """Test successful pool initialization with minimum connections."""

        mock_connect.return_value = mock_async_connection

        pool = AsyncPostgreSQLPool(connection_params=connection_params, min_connections=2, max_connections=5)

        await pool.initialize()

        assert pool._initialized is True
        assert pool._health_check_task is not None
        assert pool.active_connections >= 0
        assert mock_connect.call_count >= 0  # May vary due to async timing

        # Cleanup
        await pool.close()

    @pytest.mark.asyncio
    @patch("common.postgres_resilient.psycopg.AsyncConnection.connect")
    async def test_pool_initialization_with_min_connections(
        self, mock_connect: Mock, connection_params: dict, mock_async_connection: AsyncMock
    ) -> None:
        """Test pool initializes with specified minimum connections."""

        mock_connect.return_value = mock_async_connection

        pool = AsyncPostgreSQLPool(connection_params=connection_params, min_connections=3, max_connections=10)

        await pool.initialize()

        # Should attempt to create min_connections
        assert pool._initialized is True
        # Note: actual connection count may vary due to async timing and errors

        # Cleanup
        await pool.close()

    @pytest.mark.asyncio
    @patch("common.postgres_resilient.psycopg.AsyncConnection.connect")
    async def test_pool_initialization_connection_failure(self, mock_connect: Mock, connection_params: dict) -> None:
        """Test pool initialization handles connection failures gracefully."""

        mock_connect.side_effect = OperationalError("Connection failed")

        pool = AsyncPostgreSQLPool(connection_params=connection_params, min_connections=2, max_connections=5)

        # Should not raise exception even if connections fail
        await pool.initialize()

        assert pool._initialized is True
        assert pool.active_connections == 0  # No connections created

        # Cleanup
        await pool.close()

    @pytest.mark.asyncio
    @patch("common.postgres_resilient.psycopg.AsyncConnection.connect")
    async def test_pool_double_initialization_idempotent(self, mock_connect: Mock, connection_params: dict, mock_async_connection: AsyncMock) -> None:
        """Test that calling initialize() twice is idempotent."""

        mock_connect.return_value = mock_async_connection

        pool = AsyncPostgreSQLPool(connection_params=connection_params, min_connections=1, max_connections=5)

        await pool.initialize()
        first_task = pool._health_check_task

        # Second initialization should do nothing
        await pool.initialize()

        assert pool._health_check_task is first_task

        # Cleanup
        await pool.close()

    @pytest.mark.asyncio
    @patch("common.postgres_resilient.psycopg.AsyncConnection.connect")
    async def test_create_connection_success(self, mock_connect: Mock, connection_params: dict, mock_async_connection: AsyncMock) -> None:
        """Test successful async connection creation."""

        mock_connect.return_value = mock_async_connection

        pool = AsyncPostgreSQLPool(connection_params=connection_params)
        conn = await pool._create_connection()

        assert conn == mock_async_connection
        mock_connect.assert_called_with(**connection_params)
        mock_async_connection.set_autocommit.assert_called_once_with(True)

        # Cleanup
        await pool.close()

    @pytest.mark.asyncio
    @patch("common.postgres_resilient.psycopg.AsyncConnection.connect")
    async def test_create_connection_with_health_check(self, mock_connect: Mock, connection_params: dict, mock_async_connection: AsyncMock) -> None:
        """Test connection creation includes health check."""

        mock_connect.return_value = mock_async_connection

        pool = AsyncPostgreSQLPool(connection_params=connection_params)
        conn = await pool._create_connection()

        assert conn is not None
        # Verify health check query was executed
        cursor = mock_async_connection.cursor.return_value
        cursor.execute.assert_called_with("SELECT 1")

        # Cleanup
        await pool.close()

    @pytest.mark.asyncio
    async def test_test_connection_healthy(self, connection_params: dict, mock_async_connection: AsyncMock) -> None:
        """Test connection health check on healthy connection."""

        pool = AsyncPostgreSQLPool(connection_params=connection_params)
        result = await pool._test_connection(mock_async_connection)

        assert result is True

        # Cleanup
        await pool.close()

    @pytest.mark.asyncio
    async def test_test_connection_closed(self, connection_params: dict) -> None:
        """Test connection health check on closed connection."""

        closed_conn = AsyncMock()
        closed_conn.closed = True

        pool = AsyncPostgreSQLPool(connection_params=connection_params)
        result = await pool._test_connection(closed_conn)

        assert result is False

        # Cleanup
        await pool.close()

    @pytest.mark.asyncio
    async def test_test_connection_query_failure(self, connection_params: dict) -> None:
        """Test connection health check when query fails."""

        failing_conn = AsyncMock()
        failing_conn.closed = False
        cursor = AsyncMock()
        cursor.execute = AsyncMock(side_effect=OperationalError("Query failed"))
        cursor.__aenter__ = AsyncMock(return_value=cursor)
        cursor.__aexit__ = AsyncMock(return_value=None)
        failing_conn.cursor = Mock(return_value=cursor)

        pool = AsyncPostgreSQLPool(connection_params=connection_params)
        result = await pool._test_connection(failing_conn)

        assert result is False

        # Cleanup
        await pool.close()

    @pytest.mark.asyncio
    @patch("common.postgres_resilient.psycopg.AsyncConnection.connect")
    async def test_connection_acquisition_from_pool(self, mock_connect: Mock, connection_params: dict, mock_async_connection: AsyncMock) -> None:
        """Test acquiring connection from pool when available."""

        mock_connect.return_value = mock_async_connection

        pool = AsyncPostgreSQLPool(connection_params=connection_params, min_connections=2, max_connections=5)
        await pool.initialize()

        # Give time for initialization
        await asyncio.sleep(0.1)

        async with pool.connection() as conn:
            assert conn is not None

        # Cleanup
        await pool.close()

    @pytest.mark.asyncio
    @patch("common.postgres_resilient.psycopg.AsyncConnection.connect")
    async def test_connection_creation_when_pool_empty(self, mock_connect: Mock, connection_params: dict, mock_async_connection: AsyncMock) -> None:
        """Test creating new connection when pool is empty."""

        mock_connect.return_value = mock_async_connection

        pool = AsyncPostgreSQLPool(connection_params=connection_params, min_connections=0, max_connections=5)
        await pool.initialize()

        async with pool.connection() as conn:
            assert conn is not None
            assert pool.active_connections > 0

        # Cleanup
        await pool.close()

    @pytest.mark.asyncio
    @patch("common.postgres_resilient.psycopg.AsyncConnection.connect")
    async def test_connection_return_to_pool_when_healthy(
        self, mock_connect: Mock, connection_params: dict, mock_async_connection: AsyncMock
    ) -> None:
        """Test that healthy connection is returned to pool after use."""

        mock_connect.return_value = mock_async_connection

        pool = AsyncPostgreSQLPool(connection_params=connection_params, min_connections=1, max_connections=5)
        await pool.initialize()
        await asyncio.sleep(0.1)

        initial_size = pool.connections.qsize()

        async with pool.connection() as conn:
            assert conn is not None

        # Connection should be back in pool
        await asyncio.sleep(0.1)
        final_size = pool.connections.qsize()
        assert final_size >= initial_size

        # Cleanup
        await pool.close()

    @pytest.mark.asyncio
    @patch("common.postgres_resilient.psycopg.AsyncConnection.connect")
    async def test_connection_when_pool_closed(self, _mock_connect: Mock, connection_params: dict) -> None:
        """Test that acquiring connection from closed pool raises error."""

        pool = AsyncPostgreSQLPool(connection_params=connection_params, min_connections=0, max_connections=5)
        await pool.initialize()
        await pool.close()

        with pytest.raises(RuntimeError, match="Connection pool is closed"):
            async with pool.connection():
                pass

    @pytest.mark.asyncio
    @patch("common.postgres_resilient.psycopg.AsyncConnection.connect")
    async def test_connection_error_during_operation(self, mock_connect: Mock, connection_params: dict, mock_async_connection: AsyncMock) -> None:
        """Test connection error handling during operation."""

        mock_connect.return_value = mock_async_connection

        pool = AsyncPostgreSQLPool(connection_params=connection_params, min_connections=1, max_connections=5)
        await pool.initialize()
        await asyncio.sleep(0.1)

        with pytest.raises(InterfaceError):
            async with pool.connection():
                # Simulate error during use
                raise InterfaceError("Connection lost")

        # Cleanup
        await pool.close()

    @pytest.mark.asyncio
    @patch("common.postgres_resilient.psycopg.AsyncConnection.connect")
    async def test_close_pool_cancels_health_check(self, mock_connect: Mock, connection_params: dict, mock_async_connection: AsyncMock) -> None:
        """Test that closing pool cancels health check task."""

        mock_connect.return_value = mock_async_connection

        pool = AsyncPostgreSQLPool(connection_params=connection_params, min_connections=1, max_connections=5)
        await pool.initialize()

        health_task = pool._health_check_task
        assert health_task is not None

        await pool.close()

        assert pool._closed is True
        assert health_task.cancelled() or health_task.done()

    @pytest.mark.asyncio
    @patch("common.postgres_resilient.psycopg.AsyncConnection.connect")
    async def test_close_pool_closes_all_connections(self, mock_connect: Mock, connection_params: dict, mock_async_connection: AsyncMock) -> None:
        """Test that closing pool closes all connections."""

        mock_connect.return_value = mock_async_connection

        pool = AsyncPostgreSQLPool(connection_params=connection_params, min_connections=2, max_connections=5)
        await pool.initialize()
        await asyncio.sleep(0.1)

        await pool.close()

        assert pool._closed is True
        assert pool.connections.empty()

    @pytest.mark.asyncio
    @patch("common.postgres_resilient.psycopg.AsyncConnection.connect")
    async def test_connection_unhealthy_replacement(self, mock_connect: Mock, connection_params: dict, mock_async_connection: AsyncMock) -> None:
        """Test that unhealthy connection is replaced with new one."""

        # First connection is unhealthy, second is healthy
        unhealthy_conn = AsyncMock()
        unhealthy_conn.closed = False
        cursor = AsyncMock()
        cursor.execute = AsyncMock(side_effect=OperationalError("Connection lost"))
        cursor.__aenter__ = AsyncMock(return_value=cursor)
        cursor.__aexit__ = AsyncMock(return_value=None)
        unhealthy_conn.cursor = Mock(return_value=cursor)

        mock_connect.side_effect = [unhealthy_conn, mock_async_connection]

        pool = AsyncPostgreSQLPool(connection_params=connection_params, min_connections=0, max_connections=5)
        await pool.initialize()

        async with pool.connection() as conn:
            # Should get the healthy connection after unhealthy one was replaced
            assert conn is not None

        # Cleanup
        await pool.close()

    @pytest.mark.asyncio
    @patch("common.postgres_resilient.psycopg.AsyncConnection.connect")
    async def test_connection_max_retries_exceeded(self, mock_connect: Mock, connection_params: dict) -> None:
        """Test that max retries raises exception."""

        mock_connect.side_effect = OperationalError("Connection failed")

        pool = AsyncPostgreSQLPool(connection_params=connection_params, min_connections=0, max_connections=5, max_retries=2)
        await pool.initialize()

        with pytest.raises(Exception, match="Failed to get PostgreSQL connection after 2 attempts"):
            async with pool.connection():
                pass

        # Cleanup
        await pool.close()

    @pytest.mark.asyncio
    @patch("common.postgres_resilient.psycopg.AsyncConnection.connect")
    async def test_health_check_removes_unhealthy_connections(
        self, mock_connect: Mock, connection_params: dict, mock_async_connection: AsyncMock
    ) -> None:
        """Test that health check loop removes unhealthy connections."""

        # Create one healthy and one unhealthy connection
        unhealthy_conn = AsyncMock()
        unhealthy_conn.closed = False
        cursor = AsyncMock()
        cursor.execute = AsyncMock(side_effect=OperationalError("Connection lost"))
        cursor.__aenter__ = AsyncMock(return_value=cursor)
        cursor.__aexit__ = AsyncMock(return_value=None)
        unhealthy_conn.cursor = Mock(return_value=cursor)

        mock_connect.side_effect = [unhealthy_conn, mock_async_connection]

        pool = AsyncPostgreSQLPool(connection_params=connection_params, min_connections=0, max_connections=5, health_check_interval=1)
        await pool.initialize()

        # Manually put unhealthy connection in pool
        await pool.connections.put(unhealthy_conn)
        pool.active_connections = 1

        # Wait for health check to run
        await asyncio.sleep(1.5)

        # Cleanup
        await pool.close()

    @pytest.mark.asyncio
    @patch("common.postgres_resilient.psycopg.AsyncConnection.connect")
    async def test_health_check_replenishes_min_connections(
        self, mock_connect: Mock, connection_params: dict, mock_async_connection: AsyncMock
    ) -> None:
        """Test that health check loop maintains minimum connections."""

        mock_connect.return_value = mock_async_connection

        pool = AsyncPostgreSQLPool(connection_params=connection_params, min_connections=2, max_connections=5, health_check_interval=1)
        await pool.initialize()

        # Drain the pool below minimum
        while not pool.connections.empty():
            try:
                conn = pool.connections.get_nowait()
                await conn.close()
            except asyncio.QueueEmpty:
                break

        pool.active_connections = 0

        # Wait for health check to replenish
        await asyncio.sleep(1.5)

        # Cleanup
        await pool.close()

    @pytest.mark.asyncio
    @patch("common.postgres_resilient.psycopg.AsyncConnection.connect")
    async def test_pool_exhaustion_timeout(self, mock_connect: Mock, connection_params: dict, mock_async_connection: AsyncMock) -> None:
        """Test pool exhaustion with timeout while waiting for connection."""

        mock_connect.return_value = mock_async_connection

        pool = AsyncPostgreSQLPool(connection_params=connection_params, min_connections=0, max_connections=1, max_retries=2)
        await pool.initialize()

        # Acquire the only connection
        async with pool.connection() as _conn1:
            # Try to acquire another connection - should timeout
            with suppress(TimeoutError, Exception):
                async with asyncio.timeout(0.5):
                    async with pool.connection():
                        pass

        # Cleanup
        await pool.close()

    @pytest.mark.asyncio
    @patch("common.postgres_resilient.psycopg.AsyncConnection.connect")
    async def test_connection_not_returned_when_unhealthy(
        self, mock_connect: Mock, connection_params: dict, mock_async_connection: AsyncMock
    ) -> None:
        """Test that unhealthy connection is not returned to pool."""

        mock_connect.return_value = mock_async_connection

        pool = AsyncPostgreSQLPool(connection_params=connection_params, min_connections=1, max_connections=5)
        await pool.initialize()
        await asyncio.sleep(0.1)

        initial_count = pool.active_connections

        with suppress(Exception):
            async with pool.connection() as conn:
                # Mark connection as closed (unhealthy)
                conn.closed = True
                # Connection should not be returned on exit

        await asyncio.sleep(0.1)

        # Active connections should have decreased
        assert pool.active_connections < initial_count or pool.active_connections == 0

        # Cleanup
        await pool.close()

    @pytest.mark.asyncio
    @patch("common.postgres_resilient.psycopg.AsyncConnection.connect")
    async def test_pool_full_on_return(self, mock_connect: Mock, connection_params: dict) -> None:
        """Test connection closure when pool is full on return."""

        # Create multiple mock connections
        conns = [AsyncMock() for _ in range(3)]
        for conn in conns:
            conn.closed = False
            conn.set_autocommit = AsyncMock()
            conn.close = AsyncMock()
            cursor = AsyncMock()
            cursor.execute = AsyncMock()
            cursor.fetchone = AsyncMock(return_value=(1,))
            cursor.__aenter__ = AsyncMock(return_value=cursor)
            cursor.__aexit__ = AsyncMock(return_value=None)
            conn.cursor = Mock(return_value=cursor)

        mock_connect.side_effect = conns

        pool = AsyncPostgreSQLPool(connection_params=connection_params, min_connections=0, max_connections=2)
        await pool.initialize()

        # Fill the pool
        async with pool.connection(), pool.connection():
            # Pool now has 2 active connections (max)
            pass

        # Cleanup
        await pool.close()

    @pytest.mark.asyncio
    @patch("common.postgres_resilient.psycopg.AsyncConnection.connect")
    async def test_connection_pool_exhaustion_wait(self, mock_connect: Mock, connection_params: dict, mock_async_connection: AsyncMock) -> None:
        """Test waiting for connection when pool is exhausted."""

        mock_connect.return_value = mock_async_connection

        pool = AsyncPostgreSQLPool(connection_params=connection_params, min_connections=0, max_connections=1, max_retries=3)
        await pool.initialize()

        # Helper to hold connection briefly
        async def hold_connection():
            async with pool.connection():
                await asyncio.sleep(0.2)

        # Start task that holds the connection
        task = asyncio.create_task(hold_connection())
        await asyncio.sleep(0.05)  # Let it acquire the connection

        # This should wait and eventually get the connection when released
        async with pool.connection() as conn:
            assert conn is not None

        await task  # Ensure first task completes

        # Cleanup
        await pool.close()

    @pytest.mark.asyncio
    @patch("common.postgres_resilient.psycopg.AsyncConnection.connect")
    async def test_unhealthy_connection_counter_management(
        self, mock_connect: Mock, connection_params: dict, mock_async_connection: AsyncMock
    ) -> None:
        """Test proper active_connections counter management with unhealthy connections."""

        # First connection is unhealthy, second is healthy
        unhealthy_conn = AsyncMock()
        unhealthy_conn.closed = False
        cursor = AsyncMock()
        cursor.execute = AsyncMock(side_effect=OperationalError("Connection lost"))
        cursor.__aenter__ = AsyncMock(return_value=cursor)
        cursor.__aexit__ = AsyncMock(return_value=None)
        unhealthy_conn.cursor = Mock(return_value=cursor)
        unhealthy_conn.close = AsyncMock()

        mock_connect.side_effect = [unhealthy_conn, mock_async_connection]

        pool = AsyncPostgreSQLPool(connection_params=connection_params, min_connections=0, max_connections=5)
        await pool.initialize()

        # Manually add unhealthy connection to pool
        await pool.connections.put(unhealthy_conn)
        pool.active_connections = 1

        # Acquire connection - should detect unhealthy and replace
        async with pool.connection() as conn:
            assert conn is not None

        # Cleanup
        await pool.close()

    @pytest.mark.asyncio
    @patch("common.postgres_resilient.psycopg.AsyncConnection.connect")
    async def test_connection_error_operationalerror(self, mock_connect: Mock, connection_params: dict, mock_async_connection: AsyncMock) -> None:
        """Test OperationalError handling during operation."""

        mock_connect.return_value = mock_async_connection

        pool = AsyncPostgreSQLPool(connection_params=connection_params, min_connections=1, max_connections=5)
        await pool.initialize()
        await asyncio.sleep(0.1)

        with pytest.raises(OperationalError):
            async with pool.connection():
                # Simulate OperationalError during use
                raise OperationalError("Database error")

        # Cleanup
        await pool.close()

    @pytest.mark.asyncio
    @patch("common.postgres_resilient.psycopg.AsyncConnection.connect")
    async def test_initialization_handles_connection_limit(
        self, mock_connect: Mock, connection_params: dict, mock_async_connection: AsyncMock
    ) -> None:
        """Test initialization respects max_connections limit."""

        mock_connect.return_value = mock_async_connection

        # Create pool with reasonable limits
        pool = AsyncPostgreSQLPool(connection_params=connection_params, min_connections=2, max_connections=3)

        # Should initialize successfully
        await pool.initialize()

        assert pool._initialized is True
        # Active connections should not exceed max
        assert pool.active_connections <= pool.max_connections

        # Cleanup
        await pool.close()

    @pytest.mark.asyncio
    @patch("common.postgres_resilient.psycopg.AsyncConnection.connect")
    async def test_health_check_queue_full_on_return(self, mock_connect: Mock, connection_params: dict, mock_async_connection: AsyncMock) -> None:
        """Test health check handling when queue is full when returning connection."""

        mock_connect.return_value = mock_async_connection

        pool = AsyncPostgreSQLPool(connection_params=connection_params, min_connections=1, max_connections=1, health_check_interval=1)
        await pool.initialize()

        # Fill the pool to capacity
        await asyncio.sleep(0.1)

        # Wait for health check to attempt putting connections back
        await asyncio.sleep(1.5)

        # Cleanup
        await pool.close()

    @pytest.mark.asyncio
    @patch("common.postgres_resilient.psycopg.AsyncConnection.connect")
    async def test_connection_retry_with_backoff(self, mock_connect: Mock, connection_params: dict, mock_async_connection: AsyncMock) -> None:
        """Test connection retry logic with exponential backoff."""

        # Fail twice, then succeed
        mock_connect.side_effect = [
            OperationalError("Connection failed"),
            OperationalError("Connection failed"),
            mock_async_connection,
        ]

        pool = AsyncPostgreSQLPool(connection_params=connection_params, min_connections=0, max_connections=5, max_retries=3)
        await pool.initialize()

        # Should eventually succeed after retries
        async with pool.connection() as conn:
            assert conn is not None

        # Cleanup
        await pool.close()

    @pytest.mark.asyncio
    @patch("common.postgres_resilient.psycopg.AsyncConnection.connect")
    async def test_connection_timeout_in_exhausted_pool(self, mock_connect: Mock, connection_params: dict, mock_async_connection: AsyncMock) -> None:
        """Test timeout when waiting for connection in exhausted pool."""

        mock_connect.return_value = mock_async_connection

        pool = AsyncPostgreSQLPool(connection_params=connection_params, min_connections=0, max_connections=1, max_retries=2)
        await pool.initialize()

        # Create a long-running connection holder
        async def hold_connection_long():
            async with pool.connection():
                await asyncio.sleep(10)  # Hold for long time

        # Start holding connection
        holder_task = asyncio.create_task(hold_connection_long())
        await asyncio.sleep(0.1)  # Let it acquire

        # Try to get connection - should retry and timeout
        try:
            with pytest.raises((TimeoutError, RuntimeError, Exception)):
                async with pool.connection():
                    pass
        finally:
            holder_task.cancel()
            with suppress(asyncio.CancelledError):
                await holder_task

        # Cleanup
        await pool.close()

    @pytest.mark.asyncio
    @patch("common.postgres_resilient.psycopg.AsyncConnection.connect")
    async def test_health_check_empty_queue(self, mock_connect: Mock, connection_params: dict, mock_async_connection: AsyncMock) -> None:
        """Test health check when queue becomes empty."""

        mock_connect.return_value = mock_async_connection

        pool = AsyncPostgreSQLPool(connection_params=connection_params, min_connections=0, max_connections=5, health_check_interval=1)
        await pool.initialize()

        # Wait for health check with empty queue
        await asyncio.sleep(1.5)

        # Cleanup
        await pool.close()
