"""Tests for RabbitMQ resilient connection module."""

from unittest.mock import AsyncMock, Mock, patch

from aio_pika.exceptions import AMQPConnectionError
from pika.exceptions import AMQPConnectionError as PikaConnectionError
import pytest

from common.db_resilience import ExponentialBackoff
from common.rabbitmq_resilient import (
    AsyncResilientRabbitMQ,
    ResilientRabbitMQConnection,
    process_message_with_retry,
)


class TestResilientRabbitMQConnection:
    """Tests for ResilientRabbitMQConnection class."""

    @pytest.fixture
    def mock_connection(self) -> Mock:
        """Create a mock RabbitMQ blocking connection."""
        conn = Mock()
        conn.is_open = True
        conn.is_closed = False
        conn.close = Mock()
        channel = Mock()
        channel.is_open = True
        channel.close = Mock()
        conn.channel = Mock(return_value=channel)
        return conn

    @pytest.fixture
    def connection_url(self) -> str:
        """Test connection URL."""
        return "amqp://guest:guest@localhost:5672/"

    @patch("common.rabbitmq_resilient.BlockingConnection")
    def test_init(self, _mock_blocking_connection: Mock, connection_url: str) -> None:
        """Test ResilientRabbitMQConnection initialization."""
        conn = ResilientRabbitMQConnection(
            connection_url=connection_url,
            max_retries=5,
            heartbeat=600,
            blocked_connection_timeout=300,
        )

        assert conn.connection_url == connection_url
        assert conn.heartbeat == 600
        assert conn.blocked_connection_timeout == 300
        assert conn.circuit_breaker is not None
        assert conn._channel is None

    @patch("common.rabbitmq_resilient.BlockingConnection")
    def test_create_connection(self, mock_blocking_connection: Mock, connection_url: str, mock_connection: Mock) -> None:
        """Test connection creation."""
        mock_blocking_connection.return_value = mock_connection

        conn = ResilientRabbitMQConnection(connection_url=connection_url)
        created_conn = conn._create_connection()

        assert created_conn == mock_connection
        mock_blocking_connection.assert_called_once()

    @patch("common.rabbitmq_resilient.BlockingConnection")
    def test_test_connection_healthy(self, _mock_blocking_connection: Mock, connection_url: str, mock_connection: Mock) -> None:
        """Test connection health check on healthy connection."""
        conn = ResilientRabbitMQConnection(connection_url=connection_url)
        result = conn._test_connection(mock_connection)

        assert result is True

    @patch("common.rabbitmq_resilient.BlockingConnection")
    def test_test_connection_closed(self, _mock_blocking_connection: Mock, connection_url: str) -> None:
        """Test connection health check on closed connection."""
        closed_conn = Mock()
        closed_conn.is_open = False
        closed_conn.is_closed = True

        conn = ResilientRabbitMQConnection(connection_url=connection_url)
        result = conn._test_connection(closed_conn)

        assert result is False

    @patch("common.rabbitmq_resilient.BlockingConnection")
    def test_test_connection_error(self, _mock_blocking_connection: Mock, connection_url: str) -> None:
        """Test connection health check when query fails."""
        failing_conn = Mock()
        failing_conn.is_open = Mock(side_effect=PikaConnectionError("Connection lost"))

        conn = ResilientRabbitMQConnection(connection_url=connection_url)
        result = conn._test_connection(failing_conn)

        assert result is False

    @patch("common.rabbitmq_resilient.BlockingConnection")
    def test_channel_creates_new(self, mock_blocking_connection: Mock, connection_url: str, mock_connection: Mock) -> None:
        """Test channel creation when no channel exists."""
        mock_blocking_connection.return_value = mock_connection

        conn = ResilientRabbitMQConnection(connection_url=connection_url)
        conn._connection = mock_connection

        channel = conn.channel()

        assert channel is not None
        assert channel.is_open
        mock_connection.channel.assert_called_once()

    @patch("common.rabbitmq_resilient.BlockingConnection")
    def test_channel_reuses_existing(self, mock_blocking_connection: Mock, connection_url: str, mock_connection: Mock) -> None:
        """Test that existing open channel is reused."""
        mock_blocking_connection.return_value = mock_connection

        conn = ResilientRabbitMQConnection(connection_url=connection_url)
        conn._connection = mock_connection

        # First call creates channel
        channel1 = conn.channel()
        # Second call should reuse
        channel2 = conn.channel()

        assert channel1 == channel2
        # Channel should only be created once
        assert mock_connection.channel.call_count == 1

    @patch("common.rabbitmq_resilient.BlockingConnection")
    def test_close_connection_and_channel(self, mock_blocking_connection: Mock, connection_url: str, mock_connection: Mock) -> None:
        """Test closing both connection and channel."""
        mock_blocking_connection.return_value = mock_connection

        conn = ResilientRabbitMQConnection(connection_url=connection_url)
        conn._connection = mock_connection

        # Create and save a reference to the channel before close
        channel = mock_connection.channel()
        conn._channel = channel

        conn.close()

        channel.close.assert_called_once()
        mock_connection.close.assert_called_once()
        assert conn._channel is None
        assert conn._connection is None

    @patch("common.rabbitmq_resilient.BlockingConnection")
    def test_close_handles_errors(self, _mock_blocking_connection: Mock, connection_url: str) -> None:
        """Test that close handles errors gracefully."""
        failing_channel = Mock()
        failing_channel.is_open = True
        failing_channel.close = Mock(side_effect=Exception("Close failed"))

        failing_conn = Mock()
        failing_conn.is_open = True
        failing_conn.close = Mock(side_effect=Exception("Close failed"))

        conn = ResilientRabbitMQConnection(connection_url=connection_url)
        conn._connection = failing_conn
        conn._channel = failing_channel

        # Should not raise exception
        conn.close()

        assert conn._channel is None
        assert conn._connection is None


class TestAsyncResilientRabbitMQ:
    """Tests for AsyncResilientRabbitMQ class."""

    @pytest.fixture
    def mock_async_connection(self) -> AsyncMock:
        """Create a mock async RabbitMQ connection."""
        conn = AsyncMock()
        conn.is_closed = False
        conn.close = AsyncMock()
        conn.reconnect_callbacks = Mock()
        conn.reconnect_callbacks.add = Mock()

        channel = AsyncMock()
        channel.is_closed = False
        channel.close = AsyncMock()
        conn.channel = AsyncMock(return_value=channel)
        return conn

    @pytest.fixture
    def connection_url(self) -> str:
        """Test connection URL."""
        return "amqp://guest:guest@localhost:5672/"

    def test_init(self, connection_url: str) -> None:
        """Test AsyncResilientRabbitMQ initialization."""
        conn = AsyncResilientRabbitMQ(
            connection_url=connection_url,
            max_retries=5,
            heartbeat=600,
            connection_attempts=10,
            retry_delay=5.0,
        )

        assert conn.connection_url == connection_url
        assert conn.max_retries == 5
        assert conn.heartbeat == 600
        assert conn.connection_attempts == 10
        assert conn.retry_delay == 5.0
        assert conn._connection is None
        assert conn._channel is None
        assert conn.circuit_breaker is not None

    @pytest.mark.asyncio
    @patch("common.rabbitmq_resilient.connect_robust")
    async def test_connect_success(self, mock_connect_robust: Mock, connection_url: str, mock_async_connection: AsyncMock) -> None:
        """Test successful async connection."""
        mock_connect_robust.return_value = mock_async_connection

        conn = AsyncResilientRabbitMQ(connection_url=connection_url)
        connection = await conn.connect()

        assert connection == mock_async_connection
        mock_connect_robust.assert_called_once()

    @pytest.mark.asyncio
    @patch("common.rabbitmq_resilient.connect_robust")
    async def test_connect_reuses_existing(self, mock_connect_robust: Mock, connection_url: str, mock_async_connection: AsyncMock) -> None:
        """Test that existing connection is reused."""
        mock_connect_robust.return_value = mock_async_connection

        conn = AsyncResilientRabbitMQ(connection_url=connection_url)

        # First connect
        connection1 = await conn.connect()
        # Second connect should reuse
        connection2 = await conn.connect()

        assert connection1 == connection2
        # connect_robust should only be called once
        mock_connect_robust.assert_called_once()

    @pytest.mark.asyncio
    @patch("common.rabbitmq_resilient.connect_robust")
    async def test_connect_retry_on_failure(self, mock_connect_robust: Mock, connection_url: str, mock_async_connection: AsyncMock) -> None:
        """Test connection retry on failure."""
        # Fail first attempt, succeed on second
        mock_connect_robust.side_effect = [AMQPConnectionError("Connection failed"), mock_async_connection]

        conn = AsyncResilientRabbitMQ(connection_url=connection_url, max_retries=3)
        connection = await conn.connect()

        assert connection == mock_async_connection
        assert mock_connect_robust.call_count == 2

    @pytest.mark.asyncio
    @patch("common.rabbitmq_resilient.connect_robust")
    async def test_connect_max_retries_exceeded(self, mock_connect_robust: Mock, connection_url: str) -> None:
        """Test connection failure after max retries."""
        mock_connect_robust.side_effect = AMQPConnectionError("Connection failed")

        conn = AsyncResilientRabbitMQ(connection_url=connection_url, max_retries=2)

        with pytest.raises(Exception, match="Failed to establish RabbitMQ connection"):
            await conn.connect()

        assert mock_connect_robust.call_count == 2

    @pytest.mark.asyncio
    @patch("common.rabbitmq_resilient.connect_robust")
    async def test_channel_creates_new(self, mock_connect_robust: Mock, connection_url: str, mock_async_connection: AsyncMock) -> None:
        """Test channel creation."""
        mock_connect_robust.return_value = mock_async_connection

        conn = AsyncResilientRabbitMQ(connection_url=connection_url)
        channel = await conn.channel()

        assert channel is not None
        mock_async_connection.channel.assert_called_once()

    @pytest.mark.asyncio
    @patch("common.rabbitmq_resilient.connect_robust")
    async def test_channel_reuses_existing(self, mock_connect_robust: Mock, connection_url: str, mock_async_connection: AsyncMock) -> None:
        """Test that existing channel is reused."""
        mock_connect_robust.return_value = mock_async_connection

        conn = AsyncResilientRabbitMQ(connection_url=connection_url)

        # First call creates channel
        channel1 = await conn.channel()
        # Second call should reuse
        channel2 = await conn.channel()

        assert channel1 == channel2
        # Channel should only be created once
        mock_async_connection.channel.assert_called_once()

    @pytest.mark.asyncio
    @patch("common.rabbitmq_resilient.connect_robust")
    async def test_on_reconnect(self, mock_connect_robust: Mock, connection_url: str, mock_async_connection: AsyncMock) -> None:
        """Test reconnection callback."""
        mock_connect_robust.return_value = mock_async_connection

        conn = AsyncResilientRabbitMQ(connection_url=connection_url)
        conn._channel = AsyncMock()

        await conn._on_reconnect()

        # Channel should be reset
        assert conn._channel is None

    def test_add_reconnect_callback(self, connection_url: str) -> None:
        """Test adding reconnect callback."""
        conn = AsyncResilientRabbitMQ(connection_url=connection_url)
        callback = Mock()

        conn.add_reconnect_callback(callback)

        assert callback in conn._reconnect_callbacks

    def test_remove_reconnect_callback(self, connection_url: str) -> None:
        """Test removing reconnect callback."""
        conn = AsyncResilientRabbitMQ(connection_url=connection_url)
        callback = Mock()

        conn.add_reconnect_callback(callback)
        assert callback in conn._reconnect_callbacks

        conn.remove_reconnect_callback(callback)
        assert callback not in conn._reconnect_callbacks

    @pytest.mark.asyncio
    @patch("common.rabbitmq_resilient.connect_robust")
    async def test_close(self, mock_connect_robust: Mock, connection_url: str, mock_async_connection: AsyncMock) -> None:
        """Test closing connection and channel."""
        mock_connect_robust.return_value = mock_async_connection

        conn = AsyncResilientRabbitMQ(connection_url=connection_url)
        # Establish connection and channel
        await conn.connect()
        await conn.channel()

        await conn.close()

        # Both channel and connection should be closed
        assert conn._channel is None
        assert conn._connection is None


class TestProcessMessageWithRetry:
    """Tests for process_message_with_retry helper function."""

    @pytest.mark.asyncio
    async def test_success_on_first_try(self) -> None:
        """Test successful message processing on first try."""
        message = AsyncMock()
        handler = AsyncMock()

        await process_message_with_retry(message, handler, max_retries=3)

        handler.assert_called_once_with(message)
        message.ack.assert_called_once()
        message.nack.assert_not_called()

    @pytest.mark.asyncio
    async def test_retry_on_failure(self) -> None:
        """Test retry on handler failure."""
        message = AsyncMock()
        handler = AsyncMock(side_effect=[Exception("Failed"), Exception("Failed"), None])

        backoff = ExponentialBackoff(initial_delay=0.01, max_delay=0.1)

        await process_message_with_retry(message, handler, max_retries=3, backoff=backoff)

        assert handler.call_count == 3
        message.ack.assert_called_once()

    @pytest.mark.asyncio
    async def test_max_retries_exceeded_with_requeue(self) -> None:
        """Test max retries exceeded with requeue."""
        message = AsyncMock()
        handler = AsyncMock(side_effect=Exception("Failed"))

        backoff = ExponentialBackoff(initial_delay=0.01, max_delay=0.1)

        with pytest.raises(Exception, match="Failed"):
            await process_message_with_retry(message, handler, max_retries=2, backoff=backoff, requeue_on_error=True)

        assert handler.call_count == 2
        message.ack.assert_not_called()
        message.nack.assert_called_once_with(requeue=True)

    @pytest.mark.asyncio
    async def test_max_retries_exceeded_without_requeue(self) -> None:
        """Test max retries exceeded without requeue."""
        message = AsyncMock()
        handler = AsyncMock(side_effect=Exception("Failed"))

        backoff = ExponentialBackoff(initial_delay=0.01, max_delay=0.1)

        with pytest.raises(Exception, match="Failed"):
            await process_message_with_retry(message, handler, max_retries=2, backoff=backoff, requeue_on_error=False)

        assert handler.call_count == 2
        message.ack.assert_not_called()
        message.nack.assert_called_once_with(requeue=False)

    @pytest.mark.asyncio
    async def test_sync_handler(self) -> None:
        """Test processing with synchronous handler."""
        message = AsyncMock()
        handler = Mock()  # Sync handler

        await process_message_with_retry(message, handler, max_retries=3)

        handler.assert_called_once_with(message)
        message.ack.assert_called_once()


class TestProcessMessageAckFailure:
    """Tests for process_message_with_retry ack failure path."""

    @pytest.mark.asyncio
    async def test_process_message_ack_failure_after_success(self) -> None:
        """Ack failure after successful handler is logged but does not re-process."""
        message = AsyncMock()
        message.ack = AsyncMock(side_effect=Exception("ack failed"))
        handler = AsyncMock()  # succeeds

        # Should not raise -- ack failure is logged but doesn't re-process
        await process_message_with_retry(message, handler, max_retries=3)
        handler.assert_called_once()  # handler only called once


class TestSyncChannelReuse:
    """Tests for sync channel() returning existing valid channel."""

    @patch("common.rabbitmq_resilient.BlockingConnection")
    def test_channel_returns_existing_valid_channel(self, _mock_blocking_connection: Mock) -> None:
        """Test sync channel() returns existing open channel without creating a new one."""
        rmq = ResilientRabbitMQConnection(connection_url="amqp://guest:guest@localhost:5672/")

        # Mock an existing open channel
        mock_channel = Mock()
        mock_channel.is_open = True
        rmq._channel = mock_channel

        # Mock the connection
        rmq._connection = Mock()
        rmq._connection.is_open = True
        rmq._connection.is_closed = False

        result = rmq.channel()
        assert result is mock_channel


class TestResilientRabbitMQConnectionExceptionBranch:
    """Tests for ResilientRabbitMQConnection exception branches."""

    @patch("common.rabbitmq_resilient.BlockingConnection")
    def test_test_connection_generic_exception_returns_false(self, _mock_blocking_connection: Mock) -> None:
        """Test _test_connection returns False when a generic exception is raised (lines 72-73)."""
        conn = ResilientRabbitMQConnection(connection_url="amqp://guest:guest@localhost:5672/")

        # Use PropertyMock so accessing is_open as a property raises an exception
        failing_conn = Mock()
        type(failing_conn).is_open = property(Mock(side_effect=RuntimeError("unexpected error")))

        result = conn._test_connection(failing_conn)

        assert result is False


class TestAsyncResilientRabbitMQAdditionalCoverage:
    """Additional tests for AsyncResilientRabbitMQ to cover missing lines."""

    @pytest.fixture
    def connection_url(self) -> str:
        """Test connection URL."""
        return "amqp://guest:guest@localhost:5672/"

    @pytest.fixture
    def mock_async_connection(self) -> AsyncMock:
        """Create a mock async RabbitMQ connection."""
        conn = AsyncMock()
        conn.is_closed = False
        conn.close = AsyncMock()
        conn.reconnect_callbacks = Mock()
        conn.reconnect_callbacks.add = Mock()

        channel = AsyncMock()
        channel.is_closed = False
        channel.close = AsyncMock()
        conn.channel = AsyncMock(return_value=channel)
        return conn

    @pytest.mark.asyncio
    @patch("common.rabbitmq_resilient.connect_robust", new_callable=AsyncMock)
    async def test_connect_double_check_under_lock_returns_existing(
        self, mock_connect_robust: AsyncMock, connection_url: str, mock_async_connection: AsyncMock
    ) -> None:
        """Test that connect() returns existing connection under lock (line 154).

        When two tasks race to connect, the second one should find the connection
        already established under the lock and return it without calling connect_robust again.
        """
        mock_connect_robust.return_value = mock_async_connection

        conn = AsyncResilientRabbitMQ(connection_url=connection_url)

        # Simulate the scenario: fast-path check sees is_closed=True (so it enters the loop),
        # but under the lock, is_closed=False (another task connected in the meantime).
        mock_reconnecting = AsyncMock()
        # PropertyMock on the type so is_closed returns True first, then False
        is_closed_mock = Mock(side_effect=[True, False])
        type(mock_reconnecting).is_closed = property(lambda self: is_closed_mock())  # noqa: ARG005

        conn._connection = mock_reconnecting

        result = await conn.connect()

        # Should return the existing connection without calling connect_robust
        assert result is mock_reconnecting
        mock_connect_robust.assert_not_called()

    @pytest.mark.asyncio
    @patch("common.rabbitmq_resilient.connect_robust", new_callable=AsyncMock)
    async def test_connect_executes_async_reconnect_callbacks(
        self, mock_connect_robust: AsyncMock, connection_url: str, mock_async_connection: AsyncMock
    ) -> None:
        """Test that async reconnect callbacks are executed on connect (lines 177-183)."""
        mock_connect_robust.return_value = mock_async_connection

        conn = AsyncResilientRabbitMQ(connection_url=connection_url)

        async_callback = AsyncMock()
        conn.add_reconnect_callback(async_callback)

        await conn.connect()

        async_callback.assert_called_once()

    @pytest.mark.asyncio
    @patch("common.rabbitmq_resilient.connect_robust", new_callable=AsyncMock)
    async def test_connect_executes_sync_reconnect_callbacks(
        self, mock_connect_robust: AsyncMock, connection_url: str, mock_async_connection: AsyncMock
    ) -> None:
        """Test that sync reconnect callbacks are executed on connect (lines 180-181)."""
        mock_connect_robust.return_value = mock_async_connection

        conn = AsyncResilientRabbitMQ(connection_url=connection_url)

        sync_callback = Mock()
        conn.add_reconnect_callback(sync_callback)

        await conn.connect()

        sync_callback.assert_called_once()

    @pytest.mark.asyncio
    @patch("common.rabbitmq_resilient.connect_robust", new_callable=AsyncMock)
    async def test_connect_handles_failing_reconnect_callback(
        self, mock_connect_robust: AsyncMock, connection_url: str, mock_async_connection: AsyncMock
    ) -> None:
        """Test that errors in reconnect callbacks are logged but do not prevent connection (lines 182-183)."""
        mock_connect_robust.return_value = mock_async_connection

        conn = AsyncResilientRabbitMQ(connection_url=connection_url)

        failing_callback = Mock(side_effect=RuntimeError("callback error"))
        good_callback = Mock()
        conn.add_reconnect_callback(failing_callback)
        conn.add_reconnect_callback(good_callback)

        # Should not raise despite the failing callback
        connection = await conn.connect()

        assert connection == mock_async_connection
        failing_callback.assert_called_once()
        good_callback.assert_called_once()

    @pytest.mark.asyncio
    @patch("common.rabbitmq_resilient.connect_robust", new_callable=AsyncMock)
    async def test_connect_handles_failing_async_reconnect_callback(
        self, mock_connect_robust: AsyncMock, connection_url: str, mock_async_connection: AsyncMock
    ) -> None:
        """Test that errors in async reconnect callbacks are logged but do not prevent connection (lines 182-183)."""
        mock_connect_robust.return_value = mock_async_connection

        conn = AsyncResilientRabbitMQ(connection_url=connection_url)

        failing_async_callback = AsyncMock(side_effect=RuntimeError("async callback error"))
        conn.add_reconnect_callback(failing_async_callback)

        # Should not raise despite the failing async callback
        connection = await conn.connect()

        assert connection == mock_async_connection
        failing_async_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_handles_channel_close_exception(self, connection_url: str) -> None:
        """Test that close() handles channel close exceptions gracefully (lines 236-237)."""
        conn = AsyncResilientRabbitMQ(connection_url=connection_url)

        # Set up a channel that raises on close
        failing_channel = AsyncMock()
        failing_channel.is_closed = False
        failing_channel.close = AsyncMock(side_effect=RuntimeError("channel close error"))

        # Set up a normal connection
        mock_connection = AsyncMock()
        mock_connection.is_closed = False
        mock_connection.close = AsyncMock()

        conn._channel = failing_channel
        conn._connection = mock_connection

        # Should not raise
        await conn.close()

        assert conn._channel is None
        assert conn._connection is None
        mock_connection.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_handles_connection_close_exception(self, connection_url: str) -> None:
        """Test that close() handles connection close exceptions gracefully (lines 245-246)."""
        conn = AsyncResilientRabbitMQ(connection_url=connection_url)

        # No channel to close
        conn._channel = None

        # Set up a connection that raises on close
        failing_connection = AsyncMock()
        failing_connection.is_closed = False
        failing_connection.close = AsyncMock(side_effect=RuntimeError("connection close error"))

        conn._connection = failing_connection

        # Should not raise
        await conn.close()

        assert conn._connection is None
