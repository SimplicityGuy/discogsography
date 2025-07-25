"""Database resilience utilities for handling connection failures and recovery."""

import asyncio
import logging
import time
from collections.abc import Callable
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from threading import Lock
from typing import Any, TypeVar, cast


logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failures exceeded threshold, rejecting calls
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""

    failure_threshold: int = 5  # Number of failures before opening
    recovery_timeout: int = 60  # Seconds before trying half-open
    expected_exception: type[Exception] | tuple[type[Exception], ...] = Exception
    name: str = "CircuitBreaker"


class CircuitBreaker:
    """Circuit breaker pattern implementation for database connections."""

    def __init__(self, config: CircuitBreakerConfig):
        self.config = config
        self.failure_count = 0
        self.last_failure_time: datetime | None = None
        self.state = CircuitState.CLOSED
        self._lock = Lock()

    def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Execute function with circuit breaker protection."""
        with self._lock:
            if self.state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self.state = CircuitState.HALF_OPEN
                    logger.info(f"🔄 {self.config.name}: Circuit breaker entering HALF_OPEN state")
                else:
                    raise Exception(f"{self.config.name}: Circuit breaker is OPEN")

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except self.config.expected_exception:
            self._on_failure()
            raise

    async def call_async(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Execute async function with circuit breaker protection."""
        with self._lock:
            if self.state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self.state = CircuitState.HALF_OPEN
                    logger.info(f"🔄 {self.config.name}: Circuit breaker entering HALF_OPEN state")
                else:
                    raise Exception(f"{self.config.name}: Circuit breaker is OPEN")

        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            self._on_success()
            return result
        except self.config.expected_exception:
            self._on_failure()
            raise

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to try reset."""
        return self.last_failure_time is not None and datetime.now() - self.last_failure_time > timedelta(seconds=self.config.recovery_timeout)

    def _on_success(self) -> None:
        """Handle successful call."""
        with self._lock:
            self.failure_count = 0
            if self.state != CircuitState.CLOSED:
                logger.info(f"✅ {self.config.name}: Circuit breaker reset to CLOSED")
                self.state = CircuitState.CLOSED

    def _on_failure(self) -> None:
        """Handle failed call."""
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = datetime.now()

            if self.failure_count >= self.config.failure_threshold and self.state != CircuitState.OPEN:
                logger.error(f"🚨 {self.config.name}: Circuit breaker OPEN after {self.failure_count} failures")
                self.state = CircuitState.OPEN


class ExponentialBackoff:
    """Exponential backoff retry strategy."""

    def __init__(self, initial_delay: float = 1.0, max_delay: float = 60.0, exponential_base: float = 2.0, jitter: bool = True):
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter

    def get_delay(self, retry_count: int) -> float:
        """Calculate delay for given retry count."""
        delay = min(self.initial_delay * (self.exponential_base**retry_count), self.max_delay)

        if self.jitter:
            # Add random jitter (0-25% of delay)
            # Using time-based jitter instead of random for non-cryptographic randomness
            import time

            # Use microseconds from current time as a pseudo-random value
            jitter_value = (time.time() * 1000000) % 100 / 100.0  # Value between 0 and 1
            delay = delay * (1 + jitter_value * 0.25)

        return delay


class ResilientConnection[T]:
    """Base class for resilient database connections with circuit breaker and retry logic."""

    def __init__(
        self,
        connection_factory: Callable[[], T],
        connection_test: Callable[[T], bool],
        circuit_breaker: CircuitBreaker | None = None,
        backoff: ExponentialBackoff | None = None,
        max_retries: int = 3,
        name: str = "Connection",
    ):
        self.connection_factory = connection_factory
        self.connection_test = connection_test
        self.circuit_breaker = circuit_breaker or CircuitBreaker(CircuitBreakerConfig(name=name))
        self.backoff = backoff or ExponentialBackoff()
        self.max_retries = max_retries
        self.name = name
        self._connection: T | None = None
        self._lock = Lock()

    def get_connection(self) -> T:
        """Get a healthy connection, creating or reconnecting if needed."""
        with self._lock:
            if self._connection and self._test_connection(self._connection):
                return self._connection

            # Connection is not healthy, try to create new one
            retry_count = 0
            last_error = None

            while retry_count < self.max_retries:
                try:
                    logger.info(f"🔄 {self.name}: Creating new connection (attempt {retry_count + 1}/{self.max_retries})")

                    def create_connection() -> T:
                        conn = self.connection_factory()
                        if not self.connection_test(conn):
                            raise Exception("Connection test failed")
                        return conn

                    self._connection = self.circuit_breaker.call(create_connection)
                    logger.info(f"✅ {self.name}: Connection established successfully")
                    return self._connection

                except Exception as e:
                    last_error = e
                    retry_count += 1

                    if retry_count < self.max_retries:
                        delay = self.backoff.get_delay(retry_count - 1)
                        logger.warning(f"⚠️ {self.name}: Connection attempt {retry_count} failed: {e}. Retrying in {delay:.1f} seconds...")
                        time.sleep(delay)
                    else:
                        logger.error(f"❌ {self.name}: All connection attempts failed")

            raise Exception(f"{self.name}: Failed to establish connection after {self.max_retries} attempts") from last_error

    def _test_connection(self, connection: T) -> bool:
        """Test if connection is healthy."""
        try:
            return self.connection_test(connection)
        except Exception as e:
            logger.warning(f"⚠️ {self.name}: Connection test failed: {e}")
            return False

    def close(self) -> None:
        """Close the connection."""
        with self._lock:
            if self._connection:
                try:
                    # Attempt to close gracefully (implementation specific)
                    if hasattr(self._connection, "close"):
                        self._connection.close()
                except Exception as e:
                    logger.warning(f"⚠️ {self.name}: Error closing connection: {e}")
                finally:
                    self._connection = None


class AsyncResilientConnection[T]:
    """Async version of resilient database connection."""

    def __init__(
        self,
        connection_factory: Callable[[], T] | Callable[[], Any],
        connection_test: Callable[[T], bool] | Callable[[T], Any],
        circuit_breaker: CircuitBreaker | None = None,
        backoff: ExponentialBackoff | None = None,
        max_retries: int = 3,
        name: str = "AsyncConnection",
    ):
        self.connection_factory = connection_factory
        self.connection_test = connection_test
        self.circuit_breaker = circuit_breaker or CircuitBreaker(CircuitBreakerConfig(name=name))
        self.backoff = backoff or ExponentialBackoff()
        self.max_retries = max_retries
        self.name = name
        self._connection: T | None = None
        self._lock = asyncio.Lock()

    async def get_connection(self) -> T:
        """Get a healthy connection, creating or reconnecting if needed."""
        async with self._lock:
            if self._connection and await self._test_connection(self._connection):
                return self._connection

            # Connection is not healthy, try to create new one
            retry_count = 0
            last_error = None

            while retry_count < self.max_retries:
                try:
                    logger.info(f"🔄 {self.name}: Creating new connection (attempt {retry_count + 1}/{self.max_retries})")

                    async def create_connection() -> T:
                        if asyncio.iscoroutinefunction(self.connection_factory):
                            conn = await self.connection_factory()
                        else:
                            conn = self.connection_factory()
                        if asyncio.iscoroutinefunction(self.connection_test):
                            if not await self.connection_test(conn):
                                raise Exception("Connection test failed")
                        else:
                            if not self.connection_test(conn):
                                raise Exception("Connection test failed")
                        return cast("T", conn)

                    conn = await self.circuit_breaker.call_async(create_connection)
                    self._connection = cast("T", conn)
                    logger.info(f"✅ {self.name}: Connection established successfully")
                    return cast("T", conn)

                except Exception as e:
                    last_error = e
                    retry_count += 1

                    if retry_count < self.max_retries:
                        delay = self.backoff.get_delay(retry_count - 1)
                        logger.warning(f"⚠️ {self.name}: Connection attempt {retry_count} failed: {e}. Retrying in {delay:.1f} seconds...")
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"❌ {self.name}: All connection attempts failed")

            raise Exception(f"{self.name}: Failed to establish connection after {self.max_retries} attempts") from last_error

    async def _test_connection(self, connection: T) -> bool:
        """Test if connection is healthy."""
        try:
            if asyncio.iscoroutinefunction(self.connection_test):
                result = await self.connection_test(connection)
                return bool(result)
            else:
                return bool(self.connection_test(connection))
        except Exception as e:
            logger.warning(f"⚠️ {self.name}: Connection test failed: {e}")
            return False

    async def close(self) -> None:
        """Close the connection."""
        async with self._lock:
            if self._connection:
                try:
                    # Attempt to close gracefully
                    if hasattr(self._connection, "aclose"):
                        await self._connection.aclose()
                    elif hasattr(self._connection, "close"):
                        if asyncio.iscoroutinefunction(self._connection.close):
                            await self._connection.close()
                        else:
                            self._connection.close()
                except Exception as e:
                    logger.warning(f"⚠️ {self.name}: Error closing connection: {e}")
                finally:
                    self._connection = None


# Context managers for resilient connections
@contextmanager
def resilient_connection[T](connection_manager: ResilientConnection[T]) -> Any:
    """Context manager for resilient connections."""
    conn = connection_manager.get_connection()
    try:
        yield conn
    finally:
        # Don't close the connection - it's managed by the connection manager
        pass


@asynccontextmanager
async def async_resilient_connection[T](connection_manager: AsyncResilientConnection[T]) -> Any:
    """Async context manager for resilient connections."""
    conn = await connection_manager.get_connection()
    try:
        yield conn
    finally:
        # Don't close the connection - it's managed by the connection manager
        pass
