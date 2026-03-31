"""Resilient RabbitMQ connection management with circuit breaker and retry logic."""

import asyncio
from collections.abc import Callable
import contextlib
import logging
import re
from typing import Any

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


class AsyncResilientRabbitMQ:
    """Async resilient RabbitMQ connection using aio_pika's robust connection."""

    def __init__(self, connection_url: str, max_retries: int = 5, heartbeat: int = 600, connection_attempts: int = 10, retry_delay: float = 5.0):
        self.connection_url = connection_url
        self.max_retries = max_retries
        self.heartbeat = heartbeat
        self.connection_attempts = connection_attempts
        self.retry_delay = retry_delay

        self._connection: aio_pika.abc.AbstractRobustConnection | None = None
        self._channel: aio_pika.abc.AbstractChannel | None = None
        self._lock = asyncio.Lock()

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
        # Fast path: check without lock
        if self._connection and not self._connection.is_closed:
            return self._connection

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
                    connection = await connect_robust(
                        self.connection_url,
                        heartbeat=self.heartbeat,
                        connection_attempts=self.connection_attempts,
                        retry_delay=self.retry_delay,
                    )

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

                # Notify reconnect callbacks
                for callback in self._reconnect_callbacks:
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            await callback()
                        else:
                            callback()
                    except Exception as e:
                        logger.error(f"❌ Error in reconnect callback: {e}")

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
        connection = await self.connect()

        async with self._lock:
            if self._channel and not self._channel.is_closed:
                return self._channel

            logger.info("🐰 Creating robust RabbitMQ channel")
            self._channel = await connection.channel()
            return self._channel

    async def _on_reconnect(self, *_args: Any, **_kwargs: Any) -> None:
        """Handle reconnection event."""
        logger.info("🔄 RabbitMQ connection re-established")
        # Reset channel so it will be recreated
        self._channel = None

    def add_reconnect_callback(self, callback: Callable) -> None:
        """Add a callback to be called on reconnection."""
        self._reconnect_callbacks.append(callback)

    def remove_reconnect_callback(self, callback: Callable) -> None:
        """Remove a reconnect callback."""
        if callback in self._reconnect_callbacks:
            self._reconnect_callbacks.remove(callback)

    async def close(self) -> None:
        """Close the RabbitMQ connection and channel."""
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
            if asyncio.iscoroutinefunction(handler):
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

                # Decide whether to requeue or reject
                if requeue_on_error:
                    await message.nack(requeue=True)
                else:
                    await message.nack(requeue=False)

                raise

    if handler_succeeded:
        try:
            await message.ack()
        except Exception as e:
            logger.error(f"❌ Failed to ack message after successful processing: {e}")
            raise
