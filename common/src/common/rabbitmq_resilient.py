"""Resilient RabbitMQ connection management with circuit breaker and retry logic."""

import asyncio
from collections.abc import Callable
import contextlib
import inspect
import logging
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import aio_pika
from aio_pika import connect_robust
from aio_pika.exceptions import AMQPChannelError, AMQPConnectionError, ConnectionClosed
from pika import BlockingConnection, URLParameters
from pika.exceptions import AMQPChannelError as PikaChannelError, AMQPConnectionError as PikaConnectionError

from .db_resilience import (
    CircuitBreaker,
    CircuitBreakerConfig,
    ExponentialBackoff,
    ResilientConnection,
)


logger = logging.getLogger(__name__)


class ResilientRabbitMQConnection(ResilientConnection[BlockingConnection]):
    """Resilient RabbitMQ blocking connection with automatic reconnection."""

    def __init__(self, connection_url: str, max_retries: int = 5, heartbeat: int = 600, blocked_connection_timeout: int = 300):
        self.connection_url = connection_url
        self.heartbeat = heartbeat
        self.blocked_connection_timeout = blocked_connection_timeout

        # Circuit breaker for RabbitMQ failures
        circuit_breaker = CircuitBreaker(
            CircuitBreakerConfig(
                name="RabbitMQ",
                failure_threshold=3,
                recovery_timeout=30,
                expected_exception=(PikaConnectionError, PikaChannelError, ConnectionClosed),
            )
        )

        # Exponential backoff for retries
        backoff = ExponentialBackoff(initial_delay=1.0, max_delay=60.0, exponential_base=2.0)

        super().__init__(
            connection_factory=self._create_connection,
            connection_test=self._test_connection,
            circuit_breaker=circuit_breaker,
            backoff=backoff,
            max_retries=max_retries,
            name="RabbitMQ",
        )

        self._channel: Any | None = None

    def _create_connection(self) -> BlockingConnection:
        """Create a new RabbitMQ blocking connection."""
        # Redact password from URL for logging (never log credentials)
        safe_url = re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", self.connection_url)
        logger.info(f"🐰 Creating new RabbitMQ connection to {safe_url}")

        params = URLParameters(self.connection_url)
        params.heartbeat = self.heartbeat
        params.blocked_connection_timeout = self.blocked_connection_timeout

        connection = BlockingConnection(params)
        return connection

    def _test_connection(self, connection: BlockingConnection) -> bool:
        """Test if the connection is healthy."""
        try:
            return connection.is_open and not connection.is_closed
        except Exception:
            return False

    def channel(self) -> Any:
        """Get a channel with resilient connection."""
        connection = self.get_connection()

        with self._lock:
            # Check if we have a valid channel
            if self._channel and self._channel.is_open:
                return self._channel

            # Create new channel
            logger.info("🐰 Creating new RabbitMQ channel")
            self._channel = connection.channel()
            return self._channel

    def close(self) -> None:
        """Close the RabbitMQ connection and channel."""
        with self._lock:
            if self._channel and self._channel.is_open:
                try:
                    self._channel.close()
                    logger.info("✅ RabbitMQ channel closed")
                except Exception as e:
                    logger.warning(f"⚠️ Error closing RabbitMQ channel: {e}")
                finally:
                    self._channel = None

            if self._connection and self._connection.is_open:
                try:
                    self._connection.close()
                    logger.info("✅ RabbitMQ connection closed")
                except Exception as e:
                    logger.warning(f"⚠️ Error closing RabbitMQ connection: {e}")
                finally:
                    self._connection = None


def _with_amqp_params(url: str, **params: str) -> str:
    """Merge tuning parameters into an AMQP URL's query string.

    aio-pika 10 removed ``**kwargs`` from ``connect_robust()``: its signature now
    accepts only url/host/port/login/password/virtualhost/ssl/loop/ssl_options/
    ssl_context/timeout/client_properties/connection_class. Everything else --
    including ``heartbeat`` and the RobustConnection-specific
    ``reconnect_interval`` -- is supplied as AMQP URL query parameters.

    Parameters already present in the URL win, so an operator can override any of
    these per-deployment via RABBITMQ_* connection settings.
    """
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    for key, value in params.items():
        query.setdefault(key, value)
    return urlunsplit(parts._replace(query=urlencode(query)))


class AsyncResilientRabbitMQ:
    """Async resilient RabbitMQ connection using aio_pika's robust connection."""

    def __init__(self, connection_url: str, max_retries: int = 5, heartbeat: int = 600, connection_attempts: int = 10, retry_delay: float = 5.0):
        self.connection_url = connection_url
        self.max_retries = max_retries
        self.heartbeat = heartbeat
        self.connection_attempts = connection_attempts
        self.retry_delay = retry_delay

        # aio-pika 10 takes these as URL query parameters rather than kwargs.
        # `retry_delay` maps to RobustConnection's `reconnect_interval` -- the delay
        # between its own reconnect attempts after an established connection drops.
        #
        # `connection_attempts` has NO aio-pika equivalent: RobustConnection retries
        # indefinitely (bounded only by `fail_fast` on the very first attempt). Initial
        # connection attempts are bounded by the `max_retries` loop in connect() below,
        # which is the authoritative retry policy here. The parameter is retained for
        # call-site compatibility.
        self._connect_url = _with_amqp_params(
            connection_url,
            heartbeat=str(heartbeat),
            reconnect_interval=str(retry_delay),
        )

        self._connection: aio_pika.abc.AbstractRobustConnection | None = None
        self._channel: aio_pika.abc.AbstractChannel | None = None
        self._lock: asyncio.Lock | None = None

        # Circuit breaker for RabbitMQ failures
        # Use higher threshold and longer recovery for startup scenarios
        self.circuit_breaker = CircuitBreaker(
            CircuitBreakerConfig(
                name="AsyncRabbitMQ",
                failure_threshold=5,  # Allow more attempts before opening
                recovery_timeout=60,  # Give more time for RabbitMQ to start
                expected_exception=(AMQPConnectionError, AMQPChannelError, ConnectionClosed),
            )
        )

        # Exponential backoff for retries
        self.backoff = ExponentialBackoff(initial_delay=1.0, max_delay=60.0, exponential_base=2.0)

        # Reconnect callbacks
        self._reconnect_callbacks: list[Callable] = []

    async def connect(self) -> aio_pika.abc.AbstractRobustConnection:
        """Get or create a robust connection."""
        if self._lock is None:
            self._lock = asyncio.Lock()

        retry_count = 0
        last_error = None

        while retry_count < self.max_retries:
            # Check-and-set connecting flag under the lock, but do I/O outside
            should_connect = False
            async with self._lock:
                # Double-check under lock (another task may have connected)
                if self._connection and not self._connection.is_closed:
                    return self._connection
                should_connect = True

            if not should_connect:
                continue  # pragma: no cover

            try:
                logger.info(f"🐰 Creating robust RabbitMQ connection (attempt {retry_count + 1}/{self.max_retries})")

                async def create_connection() -> Any:
                    # Tuning params ride in the URL query string — see _with_amqp_params.
                    connection = await connect_robust(self._connect_url)

                    # Add reconnect callback
                    connection.reconnect_callbacks.add(self._on_reconnect)

                    return connection

                new_connection = await self.circuit_breaker.call_async(create_connection)

                # Store the connection under the lock
                async with self._lock:
                    # Another task may have connected while we were doing I/O
                    if self._connection and not self._connection.is_closed:
                        # Close our redundant connection
                        with contextlib.suppress(Exception):
                            await new_connection.close()
                        return self._connection
                    self._connection = new_connection

                logger.info("✅ Robust RabbitMQ connection established")

                await self._notify_reconnect_callbacks("connect")

                return self._connection

            except Exception as e:
                last_error = e
                retry_count += 1

                if retry_count >= self.max_retries:
                    logger.error("❌ All RabbitMQ connection attempts failed")

            # Sleep outside the lock to allow other tasks to proceed
            if retry_count < self.max_retries:
                delay = self.backoff.get_delay(retry_count - 1)
                logger.warning(f"⚠️ RabbitMQ connection attempt {retry_count} failed: {last_error}. Retrying in {delay:.1f} seconds...")
                await asyncio.sleep(delay)

        raise Exception(f"Failed to establish RabbitMQ connection after {self.max_retries} attempts") from last_error

    async def channel(self) -> aio_pika.abc.AbstractChannel:
        """Get or create a robust channel."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        connection = await self.connect()

        async with self._lock:
            if self._channel and not self._channel.is_closed:
                return self._channel

            logger.info("🐰 Creating robust RabbitMQ channel")
            self._channel = await connection.channel()
            return self._channel

    async def _notify_reconnect_callbacks(self, event: str) -> None:
        """Invoke every registered callback, isolating failures.

        Must be called with ``self._lock`` NOT held: a callback that re-establishes
        state typically calls back into :meth:`channel`, which takes the same lock.
        """
        for callback in self._reconnect_callbacks:
            try:
                if inspect.iscoroutinefunction(callback):
                    await callback()
                else:
                    callback()
            except Exception as e:
                logger.error(f"❌ Error in reconnect callback ({event}): {e}")

    async def _on_reconnect(self, *_args: Any, **_kwargs: Any) -> None:
        """Handle an aio-pika auto-reconnect: reset the channel, then notify callbacks.

        RobustConnection reports ``is_closed == False`` across its own internal
        reconnects, so :meth:`connect` early-returns and never re-runs its notify
        block. This hook is the ONLY place a caller-visible reconnect is observable,
        so it is where ``add_reconnect_callback`` subscribers have to be fired —
        otherwise the API is a no-op exactly when re-registration is needed
        (discogsography-6ino).
        """
        logger.info("🔄 RabbitMQ connection re-established")
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            # Reset channel so it will be recreated
            self._channel = None

        # Outside the lock: callbacks commonly call channel(), which acquires it.
        await self._notify_reconnect_callbacks("reconnect")

    def add_reconnect_callback(self, callback: Callable) -> None:
        """Add a callback invoked on every connection establishment.

        Fires both when :meth:`connect` establishes a connection and when aio-pika's
        RobustConnection transparently re-establishes a dropped one. Callbacks must
        therefore be idempotent. Exceptions are logged and swallowed so one bad
        subscriber cannot break connection recovery for the others.
        """
        self._reconnect_callbacks.append(callback)

    def remove_reconnect_callback(self, callback: Callable) -> None:
        """Remove a reconnect callback."""
        if callback in self._reconnect_callbacks:
            self._reconnect_callbacks.remove(callback)

    async def close(self) -> None:
        """Close the RabbitMQ connection and channel."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            if self._channel and not self._channel.is_closed:
                try:
                    await self._channel.close()
                    logger.info("✅ RabbitMQ channel closed")
                except Exception as e:
                    logger.warning(f"⚠️ Error closing RabbitMQ channel: {e}")
                finally:
                    self._channel = None

            if self._connection and not self._connection.is_closed:
                try:
                    await self._connection.close()
                    logger.info("✅ RabbitMQ connection closed")
                except Exception as e:
                    logger.warning(f"⚠️ Error closing RabbitMQ connection: {e}")
                finally:
                    self._connection = None


# Helper function for message processing with retry
async def process_message_with_retry(
    message: aio_pika.abc.AbstractIncomingMessage,
    handler: Callable,
    max_retries: int = 3,
    backoff: ExponentialBackoff | None = None,
    requeue_on_error: bool = True,
) -> None:
    """Process a message with retry logic and proper acknowledgment."""
    if backoff is None:
        backoff = ExponentialBackoff(initial_delay=1.0, max_delay=30.0)

    retry_count = 0
    handler_succeeded = False

    while retry_count < max_retries:
        try:
            # Process the message
            if inspect.iscoroutinefunction(handler):
                await handler(message)
            else:
                handler(message)

            handler_succeeded = True
            break

        except Exception as e:
            retry_count += 1

            if retry_count < max_retries:
                delay = backoff.get_delay(retry_count - 1)
                logger.warning(f"⚠️ Message processing failed (attempt {retry_count}/{max_retries}): {e}. Retrying in {delay:.1f} seconds...")
                await asyncio.sleep(delay)
            else:
                logger.error(f"❌ Message processing failed after {max_retries} attempts: {e}")

                # Nack the message (caller should not nack again)
                try:
                    if requeue_on_error:
                        await message.nack(requeue=True)
                    else:
                        await message.nack(requeue=False)
                except Exception as nack_err:
                    logger.warning(f"⚠️ Failed to nack message after retries exhausted: {nack_err}")

                raise

    if handler_succeeded:
        try:
            await message.ack()
        except Exception as e:
            logger.error(f"❌ Failed to ack message after successful processing: {e}")
            raise
