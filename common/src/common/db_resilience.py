"""Database resilience utilities for handling connection failures and recovery."""

import asyncio
from collections.abc import Callable
import contextlib
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
import inspect
import logging
import random
from threading import Lock
import time
from typing import Any, TypeVar, cast


logger = logging.getLogger(__name__)

T = TypeVar("T")


class DatabaseUnavailableError(Exception):
    """The database could not be reached — a TRANSIENT, infrastructure-level fault.

    Raised by the resilience layer itself, never by a query. Callers use it to
    tell "the database is down" apart from "this record is bad": the resilience
    wrappers used to raise a bare ``Exception`` here, so consumers classifying on
    exception type saw an outage as a deterministic, poison payload and
    dead-lettered perfectly valid records (discogsography-4lrp).
    """


class ConnectionEstablishmentError(DatabaseUnavailableError):
    """Every attempt to establish (or health-check) a connection failed."""


class CircuitOpenError(DatabaseUnavailableError):
    """The circuit breaker is open, so the call was rejected without an attempt."""


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
        self._async_lock: asyncio.Lock | None = None

    def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Execute function with circuit breaker protection."""
        is_trial = False
        with self._lock:
            if self.state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self.state = CircuitState.HALF_OPEN
                    logger.info(f"🔄 {self.config.name}: Circuit breaker entering HALF_OPEN state")
                    is_trial = True
                else:
                    raise CircuitOpenError(f"{self.config.name}: Circuit breaker is OPEN")
            elif self.state == CircuitState.HALF_OPEN:
                is_trial = True

        if is_trial:
            # Execute trial call outside the lock, then update state under lock
            try:
                result = func(*args, **kwargs)
                with self._lock:
                    self.failure_count = 0
                    if self.state != CircuitState.CLOSED:
                        logger.info(f"✅ {self.config.name}: Circuit breaker reset to CLOSED")
                        self.state = CircuitState.CLOSED
                return result
            except self.config.expected_exception:
                with self._lock:
                    self.failure_count += 1
                    self.last_failure_time = datetime.now(UTC)
                    if self.failure_count >= self.config.failure_threshold and self.state != CircuitState.OPEN:
                        logger.error(f"❌ {self.config.name}: Circuit breaker OPEN after {self.failure_count} failures")
                        self.state = CircuitState.OPEN
                raise

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except self.config.expected_exception:
            self._on_failure()
            raise

    def _get_async_lock(self) -> asyncio.Lock:
        """Return the async lock, creating it lazily in the running event loop."""
        if self._async_lock is None:
            self._async_lock = asyncio.Lock()
        return self._async_lock

    async def call_async(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Execute async function with circuit breaker protection."""
        is_trial = False
        async with self._get_async_lock():
            if self.state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self.state = CircuitState.HALF_OPEN
                    logger.info(f"🔄 {self.config.name}: Circuit breaker entering HALF_OPEN state")
                    is_trial = True
                else:
                    raise CircuitOpenError(f"{self.config.name}: Circuit breaker is OPEN")
            elif self.state == CircuitState.HALF_OPEN:
                is_trial = True

        if is_trial:
            # Execute trial call outside the lock, then update state under lock
            try:
                if inspect.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    result = func(*args, **kwargs)
                async with self._get_async_lock():
                    self.failure_count = 0
                    if self.state != CircuitState.CLOSED:
                        logger.info(f"✅ {self.config.name}: Circuit breaker reset to CLOSED")
                        self.state = CircuitState.CLOSED
                return result
            except self.config.expected_exception:
                async with self._get_async_lock():
                    self.failure_count += 1
                    self.last_failure_time = datetime.now(UTC)
                    if self.failure_count >= self.config.failure_threshold and self.state != CircuitState.OPEN:
                        logger.error(f"❌ {self.config.name}: Circuit breaker OPEN after {self.failure_count} failures")
                        self.state = CircuitState.OPEN
                raise

        try:
            if inspect.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            await self._on_success_async()
            return result
        except self.config.expected_exception:
            await self._on_failure_async()
            raise

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to try reset."""
        return self.last_failure_time is not None and datetime.now(UTC) - self.last_failure_time > timedelta(seconds=self.config.recovery_timeout)

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
            self.last_failure_time = datetime.now(UTC)

            if self.failure_count >= self.config.failure_threshold and self.state != CircuitState.OPEN:
                logger.error(f"❌ {self.config.name}: Circuit breaker OPEN after {self.failure_count} failures")
                self.state = CircuitState.OPEN

    async def _on_success_async(self) -> None:
        """Handle successful async call."""
        async with self._get_async_lock():
            self.failure_count = 0
            if self.state != CircuitState.CLOSED:
                logger.info(f"✅ {self.config.name}: Circuit breaker reset to CLOSED")
                self.state = CircuitState.CLOSED

    async def _on_failure_async(self) -> None:
        """Handle failed async call."""
        async with self._get_async_lock():
            self.failure_count += 1
            self.last_failure_time = datetime.now(UTC)

            if self.failure_count >= self.config.failure_threshold and self.state != CircuitState.OPEN:
                logger.error(f"❌ {self.config.name}: Circuit breaker OPEN after {self.failure_count} failures")
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
            jitter_value = random.uniform(0, 0.25)  # noqa: S311  # nosec B311
            delay = delay * (1 + jitter_value)

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

    def _close_connection(self, connection: Any) -> None:
        """Best-effort close of a connection, matching close()'s dispatch."""
        if connection is None:
            return
        try:
            if hasattr(connection, "close"):
                connection.close()
        except Exception as e:
            logger.warning(f"⚠️ {self.name}: Error closing connection: {e}")

    def get_connection(self) -> T:
        """Get a healthy connection, creating or reconnecting if needed."""
        with self._lock:
            if self._connection and self._test_connection(self._connection):
                return self._connection

            # The existing connection is unhealthy. Close and discard it BEFORE reconnecting —
            # otherwise the retry loop overwrites self._connection and orphans the old object
            # (leaked driver pool / socket that GC cannot reliably clean up).
            if self._connection is not None:
                self._close_connection(self._connection)
                self._connection = None

            # Connection is not healthy, try to create new one
            retry_count = 0
            last_error = None

            while retry_count < self.max_retries:
                try:
                    logger.info(f"🔄 {self.name}: Creating new connection (attempt {retry_count + 1}/{self.max_retries})")

                    def create_connection() -> T:
                        conn = self.connection_factory()
                        if not self.connection_test(conn):
                            # Close the just-built connection before discarding it.
                            self._close_connection(conn)
                            raise ConnectionEstablishmentError("Connection test failed")
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

            raise ConnectionEstablishmentError(f"{self.name}: Failed to establish connection after {self.max_retries} attempts") from last_error

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
            if self._connection is not None:
                self._close_connection(self._connection)
                self._connection = None


def _consume_task_exception(task: "asyncio.Task[Any]") -> None:
    """Retrieve a finished task's exception so asyncio does not warn about it."""
    if not task.cancelled():
        task.exception()


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
        health_check_ttl: float = 30.0,
        unhealthy_threshold: int = 3,
        close_grace_period: float = 30.0,
        reconnect_cooldown: float = 5.0,
    ):
        self.connection_factory = connection_factory
        self.connection_test = connection_test
        self.circuit_breaker = circuit_breaker or CircuitBreaker(CircuitBreakerConfig(name=name))
        self.backoff = backoff or ExponentialBackoff()
        self.max_retries = max_retries
        self.name = name
        # Seconds a successful health probe is trusted before re-probing.
        self.health_check_ttl = health_check_ttl
        # Consecutive failed probes required before a live connection is replaced.
        self.unhealthy_threshold = unhealthy_threshold
        # Seconds a replaced connection is left open so in-flight borrowers can drain.
        self.close_grace_period = close_grace_period
        # Seconds after a fully failed reconnect cycle during which callers fail
        # fast instead of each repeating the cycle (discogsography-y1qn).
        self.reconnect_cooldown = reconnect_cooldown
        self._connection: T | None = None
        self._lock: asyncio.Lock | None = None
        self._last_healthy_at: float = 0.0
        self._failed_probes: int = 0
        # The single in-flight reconnect cycle, shared by all waiters, plus the
        # memo of the last failed one.
        self._reconnect_task: asyncio.Task[T] | None = None
        self._last_failure_at: float | None = None
        self._last_failure_error: Exception | None = None
        # Connections detached from the manager but not yet closed, and the
        # tasks that will close them (discogsography-4ajv).
        self._draining: list[Any] = []
        self._close_tasks: set[asyncio.Task[None]] = set()

    async def _aclose_connection(self, connection: Any) -> None:
        """Best-effort close of a connection, dispatching aclose()/close() like close()."""
        if connection is None:
            return
        try:
            if hasattr(connection, "aclose"):
                await connection.aclose()
            elif hasattr(connection, "close"):
                if inspect.iscoroutinefunction(connection.close):
                    await connection.close()
                else:
                    connection.close()
        except Exception as e:
            logger.warning(f"⚠️ {self.name}: Error closing connection: {e}")

    def _get_lock(self) -> asyncio.Lock:
        """Return the handle lock, creating it lazily on the running event loop."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def _probe_connection(self, connection: T) -> bool:
        """Run the health check, never letting it raise."""
        try:
            return bool(await self._test_connection(connection))
        except Exception as e:
            logger.warning(f"⚠️ {self.name}: Connection test failed: {e}")
            return False

    async def _connection_is_usable(self, connection: T) -> bool:
        """Decide whether an existing connection may still be handed out.

        Two guards keep a merely BUSY connection from being torn down
        (discogsography-4ajv):

        * a successful probe is trusted for ``health_check_ttl`` seconds, so
          borrowing does not pay a health round trip per call — that round trip
          is also what made the pool-starvation trigger reachable; and
        * ``unhealthy_threshold`` CONSECUTIVE probe failures are required before
          the connection is declared dead. One failure is not proof the server
          is gone: a pool-acquisition timeout means every slot is busy, i.e. the
          connection is working, and replacing it would abort the in-flight work
          of every other coroutine holding a session borrowed from it.
        """
        now = time.monotonic()
        if self._last_healthy_at and now - self._last_healthy_at < self.health_check_ttl:
            return True

        if await self._probe_connection(connection):
            self._failed_probes = 0
            self._last_healthy_at = now
            return True

        self._failed_probes += 1
        if self._failed_probes < self.unhealthy_threshold:
            logger.warning(
                f"⚠️ {self.name}: Health check failed ({self._failed_probes}/{self.unhealthy_threshold}) — "
                "keeping the existing connection; in-flight borrowers must not be aborted on one probe"
            )
            return True

        logger.error(f"❌ {self.name}: Health check failed {self._failed_probes} consecutive times — replacing the connection")
        return False

    def _schedule_deferred_close(self, connection: Any) -> None:
        """Close a replaced connection only after in-flight borrowers can drain.

        The manager's lock serializes access to the HANDLE, never use of the
        object: a caller keeps using a session borrowed from it long after
        get_connection() returned, and the neo4j driver documents close() as
        NOT concurrency-safe with live sessions. So the replaced connection is
        detached immediately and closed after ``close_grace_period``
        (discogsography-4ajv).
        """
        if connection is None:
            return
        self._draining.append(connection)
        task = asyncio.create_task(self._close_after_grace(connection))
        self._close_tasks.add(task)
        task.add_done_callback(self._close_tasks.discard)

    async def _close_after_grace(self, connection: Any) -> None:
        """Wait out the grace period, then close a detached connection."""
        if self.close_grace_period > 0:
            await asyncio.sleep(self.close_grace_period)
        try:
            await self._aclose_connection(connection)
        finally:
            with contextlib.suppress(ValueError):
                self._draining.remove(connection)

    async def _drain_deferred_closes(self) -> None:
        """Close every detached connection immediately (explicit shutdown)."""
        if self._reconnect_task is not None and not self._reconnect_task.done():
            self._reconnect_task.cancel()
        self._reconnect_task = None
        self._last_failure_at = None
        self._last_failure_error = None
        for task in list(self._close_tasks):
            task.cancel()
        self._close_tasks.clear()
        draining, self._draining = self._draining, []
        for connection in draining:
            await self._aclose_connection(connection)

    async def get_connection(self) -> T:
        """Get a healthy connection, creating or reconnecting if needed.

        The manager's lock guards ONLY the connection handle. The reconnect
        cycle — up to ``max_retries`` driver-creation attempts, each of which can
        block for the driver's whole acquisition timeout, plus the backoff
        sleeps between them — runs OUTSIDE the lock as a single shared task
        (discogsography-y1qn). Before the fix, the first caller held the process
        singleton lock for the entire failed cycle, every other coroutine in the
        process queued behind it, and each waiter then re-ran the full cycle
        itself, so the k-th caller failed only after roughly k cycles. Now
        concurrent callers join the one in-flight reconnect, and callers arriving
        inside ``reconnect_cooldown`` of a failed cycle fail fast instead of
        repeating it.
        """
        if self._lock is None:
            self._lock = asyncio.Lock()

        async with self._lock:
            connection = self._connection
            if connection is not None:
                if await self._connection_is_usable(connection):
                    return connection

                # Declared dead. Detach it BEFORE reconnecting — otherwise the retry loop
                # overwrites self._connection and orphans the old object (e.g. a whole Neo4j
                # driver pool of 50 sockets that GC cannot close via __del__) — but close it
                # on a grace timer rather than out from under live sessions.
                self._connection = None
                self._failed_probes = 0
                self._last_healthy_at = 0.0
                self._schedule_deferred_close(connection)

            # Fail fast if another coroutine just burned a full failed cycle:
            # repeating it would only stack another multi-minute wait onto a
            # caller that is going to fail anyway.
            if self._last_failure_at is not None and time.monotonic() - self._last_failure_at < self.reconnect_cooldown:
                raise ConnectionEstablishmentError(
                    f"{self.name}: Connection unavailable — a reconnect cycle failed less than {self.reconnect_cooldown:.0f}s ago"
                ) from self._last_failure_error

            if self._reconnect_task is None or self._reconnect_task.done():
                self._reconnect_task = asyncio.create_task(self._reconnect())
                # Mark the failure retrieved even if every waiter is cancelled,
                # so a failed cycle cannot log "exception was never retrieved".
                self._reconnect_task.add_done_callback(_consume_task_exception)
            task = self._reconnect_task

        # Awaited WITHOUT the lock so borrowers of a still-healthy connection
        # (and close()) are never blocked behind a reconnect, and so every
        # concurrent caller joins the SAME cycle instead of running its own.
        # Shielded so one cancelled waiter cannot cancel the shared cycle.
        return await asyncio.shield(task)

    async def _reconnect(self) -> T:
        """Run the retry/backoff cycle, publishing the result under the lock."""
        retry_count = 0
        last_error: Exception | None = None

        while retry_count < self.max_retries:
            try:
                logger.info(f"🔄 {self.name}: Creating new connection (attempt {retry_count + 1}/{self.max_retries})")

                async def create_connection() -> T:
                    if inspect.iscoroutinefunction(self.connection_factory):
                        conn = await self.connection_factory()
                    else:
                        conn = self.connection_factory()
                    if inspect.iscoroutinefunction(self.connection_test):
                        test_ok = await self.connection_test(conn)
                    else:
                        test_ok = self.connection_test(conn)
                    if not test_ok:
                        # Close the just-built connection before discarding it, so a failed
                        # health test does not leak a fresh pool/socket per attempt.
                        await self._aclose_connection(conn)
                        raise ConnectionEstablishmentError("Connection test failed")
                    return cast("T", conn)

                conn = await self.circuit_breaker.call_async(create_connection)

                # Publishing the handle is the only step that needs the lock.
                async with self._get_lock():
                    self._connection = cast("T", conn)
                    # create_connection already health-checked it — don't re-probe
                    # borrowers for another health_check_ttl seconds.
                    self._last_healthy_at = time.monotonic()
                    self._failed_probes = 0
                    self._last_failure_at = None
                    self._last_failure_error = None
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

        self._last_failure_at = time.monotonic()
        self._last_failure_error = last_error
        raise ConnectionEstablishmentError(f"{self.name}: Failed to establish connection after {self.max_retries} attempts") from last_error

    async def _test_connection(self, connection: T) -> bool:
        """Test if connection is healthy."""
        try:
            if inspect.iscoroutinefunction(self.connection_test):
                result = await self.connection_test(connection)
                return bool(result)
            else:
                return bool(self.connection_test(connection))
        except Exception as e:
            logger.warning(f"⚠️ {self.name}: Connection test failed: {e}")
            return False

    async def close(self) -> None:
        """Close the connection."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            await self._drain_deferred_closes()
            if self._connection is not None:
                await self._aclose_connection(self._connection)
                self._connection = None
            self._last_healthy_at = 0.0
            self._failed_probes = 0


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
