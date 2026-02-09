"""Resilient PostgreSQL connection management with circuit breaker and retry logic."""

import asyncio
from collections.abc import AsyncIterator, Generator
import contextlib
from contextlib import asynccontextmanager, contextmanager
import logging
from queue import Empty, Full, Queue
import threading
from typing import Any

import psycopg
from psycopg.errors import DatabaseError, InterfaceError, OperationalError

from .db_resilience import (
    AsyncResilientConnection,
    CircuitBreaker,
    CircuitBreakerConfig,
    ExponentialBackoff,
)


logger = logging.getLogger(__name__)


class ResilientPostgreSQLPool:
    """Resilient PostgreSQL connection pool with circuit breaker and health checks."""

    def __init__(
        self,
        connection_params: dict[str, Any],
        max_connections: int = 20,
        min_connections: int = 2,
        max_retries: int = 5,
        health_check_interval: int = 30,
    ):
        self.connection_params = connection_params
        self.max_connections = max_connections
        self.min_connections = min_connections
        self.max_retries = max_retries
        self.health_check_interval = health_check_interval

        # Connection pool
        self.connections: Queue[psycopg.Connection[Any]] = Queue(maxsize=max_connections)
        self.active_connections = 0
        self._lock = threading.Lock()
        self._closed = False

        # Circuit breaker for database failures
        self.circuit_breaker = CircuitBreaker(
            CircuitBreakerConfig(
                name="PostgreSQL", failure_threshold=3, recovery_timeout=30, expected_exception=(DatabaseError, InterfaceError, OperationalError)
            )
        )

        # Exponential backoff for retries
        self.backoff = ExponentialBackoff(initial_delay=0.5, max_delay=30.0, exponential_base=2.0)

        # Health check thread
        self.health_check_thread = threading.Thread(target=self._health_check_loop, daemon=True)
        self.health_check_thread.start()

        # Initialize minimum connections
        self._initialize_pool()

    def _initialize_pool(self) -> None:
        """Initialize the connection pool with minimum connections."""
        logger.info(f"🔗 Initializing PostgreSQL connection pool (min: {self.min_connections}, max: {self.max_connections})")

        for _ in range(self.min_connections):
            try:
                conn = self._create_connection()
                if conn:
                    self.connections.put_nowait(conn)
            except Full:
                break
            except Exception as e:
                logger.warning(f"⚠️ Failed to create initial connection: {e}")

    def _create_connection(self) -> psycopg.Connection[Any]:
        """Create a new PostgreSQL connection with retry logic."""

        def create() -> psycopg.Connection[Any]:
            conn = psycopg.connect(**self.connection_params)
            conn.autocommit = True  # Enable autocommit by default
            # Test the connection
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
            return conn

        return self.circuit_breaker.call(create)

    def _test_connection(self, conn: psycopg.Connection[Any]) -> bool:
        """Test if a connection is healthy."""
        try:
            if conn.closed:
                return False
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
                return result is not None and result[0] == 1
        except Exception:
            return False

    def _health_check_loop(self) -> None:
        """Background thread to check connection health periodically."""
        import time

        while not self._closed:
            time.sleep(self.health_check_interval)

            # Check and remove unhealthy connections
            healthy_connections = []
            check_count = min(self.connections.qsize(), self.max_connections)

            for _ in range(check_count):
                try:
                    conn = self.connections.get_nowait()
                    if self._test_connection(conn):
                        healthy_connections.append(conn)
                    else:
                        logger.warning("⚠️ Removing unhealthy connection from pool")
                        with contextlib.suppress(Exception):
                            conn.close()
                except Empty:
                    break

            # Put healthy connections back
            for conn in healthy_connections:
                try:
                    self.connections.put_nowait(conn)
                except Full:
                    conn.close()

            # Ensure minimum connections
            current_size = self.connections.qsize()
            if current_size < self.min_connections:
                logger.info(f"🔄 Replenishing connection pool ({current_size}/{self.min_connections} connections)")
                for _ in range(self.min_connections - current_size):
                    try:
                        conn = self._create_connection()
                        if conn:
                            self.connections.put_nowait(conn)
                    except Exception as e:
                        logger.warning(f"⚠️ Failed to replenish connection: {e}")
                        break

    @contextmanager
    def connection(self) -> Generator[psycopg.Connection[Any]]:
        """Get a connection from the pool with retry logic."""
        if self._closed:
            raise RuntimeError("Connection pool is closed")

        conn = None
        retry_count = 0
        last_error = None

        while retry_count < self.max_retries:
            try:
                # Try to get existing connection
                try:
                    conn = self.connections.get_nowait()
                except Empty:
                    # Create new connection if pool is not at max
                    with self._lock:
                        if self.active_connections < self.max_connections:
                            self.active_connections += 1
                            try:
                                conn = self._create_connection()
                            except Exception:
                                self.active_connections -= 1
                                raise

                # Test connection health
                if conn and not self._test_connection(conn):
                    logger.warning("⚠️ Got unhealthy connection from pool, creating new one")
                    with contextlib.suppress(Exception):
                        conn.close()
                    conn = self._create_connection()

                if conn:
                    break

            except Exception as e:
                last_error = e
                retry_count += 1

                if retry_count < self.max_retries:
                    delay = self.backoff.get_delay(retry_count - 1)
                    logger.warning(f"⚠️ PostgreSQL connection attempt {retry_count} failed: {e}. Retrying in {delay:.1f} seconds...")
                    import time

                    time.sleep(delay)

        if not conn:
            raise Exception(f"Failed to get PostgreSQL connection after {self.max_retries} attempts") from last_error

        try:
            yield conn
        except (InterfaceError, OperationalError) as e:
            # Connection error during use - don't return to pool
            logger.warning(f"⚠️ Connection error during operation: {e}")
            with contextlib.suppress(Exception):
                conn.close()
            conn = None
            raise
        finally:
            # Return connection to pool if it's still good
            if conn and not conn.closed and not self._closed:
                try:
                    self.connections.put_nowait(conn)
                except Full:
                    # Pool is full, close connection
                    with contextlib.suppress(Exception):
                        conn.close()
            elif conn:
                # Close bad connections
                with contextlib.suppress(Exception):
                    conn.close()
                with self._lock:
                    self.active_connections = max(0, self.active_connections - 1)

    def close(self) -> None:
        """Close all connections in the pool."""
        logger.info("🔌 Closing PostgreSQL connection pool")
        self._closed = True

        # Close all connections
        while not self.connections.empty():
            with contextlib.suppress(Exception):
                conn = self.connections.get_nowait()
                conn.close()

        logger.info("✅ PostgreSQL connection pool closed")


class AsyncResilientPostgreSQL(AsyncResilientConnection[Any]):
    """Async resilient PostgreSQL connection with automatic reconnection."""

    def __init__(self, connection_params: dict[str, Any], max_retries: int = 5):
        self.connection_params = connection_params

        # Circuit breaker for PostgreSQL failures
        circuit_breaker = CircuitBreaker(
            CircuitBreakerConfig(
                name="AsyncPostgreSQL", failure_threshold=3, recovery_timeout=30, expected_exception=(DatabaseError, InterfaceError, OperationalError)
            )
        )

        # Exponential backoff for retries
        backoff = ExponentialBackoff(initial_delay=0.5, max_delay=30.0, exponential_base=2.0)

        super().__init__(
            connection_factory=self._create_connection,
            connection_test=self._test_connection,
            circuit_breaker=circuit_breaker,
            backoff=backoff,
            max_retries=max_retries,
            name="AsyncPostgreSQL",
        )

    async def _create_connection(self) -> Any:
        """Create a new async PostgreSQL connection."""
        logger.info("🔗 Creating new async PostgreSQL connection")
        conn = await psycopg.AsyncConnection.connect(**self.connection_params)
        await conn.set_autocommit(True)
        return conn

    async def _test_connection(self, conn: Any) -> bool:
        """Test if the connection is healthy."""
        try:
            if conn.closed:
                return False
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT 1")
                result = await cursor.fetchone()
                return result is not None and result[0] == 1
        except Exception:
            return False


class AsyncPostgreSQLPool:
    """Async PostgreSQL connection pool with circuit breaker and health checks.

    Manages a pool of async PostgreSQL connections for concurrent operations.
    """

    def __init__(
        self,
        connection_params: dict[str, Any],
        max_connections: int = 20,
        min_connections: int = 2,
        max_retries: int = 5,
        health_check_interval: int = 30,
    ):
        self.connection_params = connection_params
        self.max_connections = max_connections
        self.min_connections = min_connections
        self.max_retries = max_retries
        self.health_check_interval = health_check_interval

        # Connection pool using asyncio.Queue
        self.connections: asyncio.Queue[psycopg.AsyncConnection[Any]] = asyncio.Queue(maxsize=max_connections)
        self.active_connections = 0
        self._lock = asyncio.Lock()
        self._closed = False

        # Circuit breaker for database failures
        self.circuit_breaker = CircuitBreaker(
            CircuitBreakerConfig(
                name="AsyncPostgreSQL",
                failure_threshold=3,
                recovery_timeout=30,
                expected_exception=(DatabaseError, InterfaceError, OperationalError),
            )
        )

        # Exponential backoff for retries
        self.backoff = ExponentialBackoff(initial_delay=0.5, max_delay=30.0, exponential_base=2.0)

        # Health check task
        self._health_check_task: asyncio.Task[None] | None = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the connection pool with minimum connections."""
        if self._initialized:
            return

        logger.info(f"🔗 Initializing async PostgreSQL connection pool (min: {self.min_connections}, max: {self.max_connections})")

        # Create initial connections
        for _ in range(self.min_connections):
            try:
                conn = await self._create_connection()
                if conn:
                    await self.connections.put(conn)
                    self.active_connections += 1
            except asyncio.QueueFull:
                break
            except Exception as e:
                logger.warning(f"⚠️ Failed to create initial connection: {e}")

        # Start health check task
        self._health_check_task = asyncio.create_task(self._health_check_loop())
        self._initialized = True

    async def _create_connection(self) -> psycopg.AsyncConnection[Any]:
        """Create a new async PostgreSQL connection with retry logic."""
        logger.info("🔗 Creating new async PostgreSQL connection")
        conn = await psycopg.AsyncConnection.connect(**self.connection_params)
        await conn.set_autocommit(True)
        # Test the connection
        async with conn.cursor() as cursor:
            await cursor.execute("SELECT 1")
        return conn

    async def _test_connection(self, conn: psycopg.AsyncConnection[Any]) -> bool:
        """Test if a connection is healthy."""
        try:
            if conn.closed:
                return False
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT 1")
                result = await cursor.fetchone()
                return result is not None and result[0] == 1
        except Exception:
            return False

    async def _health_check_loop(self) -> None:
        """Background task to check connection health periodically."""
        while not self._closed:
            await asyncio.sleep(self.health_check_interval)

            # Check and remove unhealthy connections
            healthy_connections = []
            check_count = min(self.connections.qsize(), self.max_connections)

            for _ in range(check_count):
                try:
                    conn = self.connections.get_nowait()
                    if await self._test_connection(conn):
                        healthy_connections.append(conn)
                    else:
                        logger.warning("⚠️ Removing unhealthy connection from pool")
                        with contextlib.suppress(Exception):
                            await conn.close()
                        async with self._lock:
                            self.active_connections = max(0, self.active_connections - 1)
                except asyncio.QueueEmpty:
                    break

            # Put healthy connections back
            for conn in healthy_connections:
                try:
                    self.connections.put_nowait(conn)
                except asyncio.QueueFull:
                    await conn.close()
                    async with self._lock:
                        self.active_connections = max(0, self.active_connections - 1)

            # Ensure minimum connections
            current_size = self.connections.qsize()
            if current_size < self.min_connections:
                logger.info(f"🔄 Replenishing connection pool ({current_size}/{self.min_connections} connections)")
                for _ in range(self.min_connections - current_size):
                    try:
                        conn = await self._create_connection()
                        if conn:
                            await self.connections.put(conn)
                            async with self._lock:
                                self.active_connections += 1
                    except Exception as e:
                        logger.warning(f"⚠️ Failed to replenish connection: {e}")
                        break

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
        """Get a connection from the pool with retry logic."""
        if self._closed:
            raise RuntimeError("Connection pool is closed")

        if not self._initialized:
            await self.initialize()

        conn = None
        retry_count = 0
        last_error = None

        while retry_count < self.max_retries:
            try:
                # Try to get existing connection (non-blocking)
                try:
                    conn = self.connections.get_nowait()
                except asyncio.QueueEmpty:
                    # Pool is empty - try to create a new connection
                    created = False
                    async with self._lock:
                        if self.active_connections < self.max_connections:
                            self.active_connections += 1
                            created = True

                    if created:
                        try:
                            conn = await self._create_connection()
                        except Exception:
                            async with self._lock:
                                self.active_connections -= 1
                            raise
                    else:
                        # Pool exhausted - wait for a connection to be returned
                        try:
                            conn = await asyncio.wait_for(
                                self.connections.get(),
                                timeout=self.backoff.get_delay(retry_count),
                            )
                        except asyncio.TimeoutError:
                            retry_count += 1
                            if retry_count < self.max_retries:
                                logger.warning(
                                    f"⚠️ Connection pool exhausted (attempt {retry_count}/{self.max_retries}), "
                                    f"waiting for available connection..."
                                )
                            continue

                # Test connection health
                if conn and not await self._test_connection(conn):
                    logger.warning("⚠️ Got unhealthy connection from pool, creating new one")
                    with contextlib.suppress(Exception):
                        await conn.close()
                    try:
                        conn = await self._create_connection()
                    except Exception:
                        async with self._lock:
                            self.active_connections = max(0, self.active_connections - 1)
                        raise

                if conn:
                    break

            except Exception as e:
                last_error = e
                retry_count += 1

                if retry_count < self.max_retries:
                    delay = self.backoff.get_delay(retry_count - 1)
                    logger.warning(f"⚠️ PostgreSQL connection attempt {retry_count} failed: {e}. Retrying in {delay:.1f} seconds...")
                    await asyncio.sleep(delay)

        if not conn:
            raise Exception(f"Failed to get PostgreSQL connection after {self.max_retries} attempts") from last_error

        try:
            yield conn
        except (InterfaceError, OperationalError) as e:
            # Connection error during use - don't return to pool
            logger.warning(f"⚠️ Connection error during operation: {e}")
            with contextlib.suppress(Exception):
                await conn.close()
            async with self._lock:
                self.active_connections = max(0, self.active_connections - 1)
            conn = None
            raise
        finally:
            # Return connection to pool if it's still good
            if conn and not conn.closed and not self._closed:
                try:
                    self.connections.put_nowait(conn)
                except asyncio.QueueFull:
                    # Pool is full, close connection
                    with contextlib.suppress(Exception):
                        await conn.close()
                    async with self._lock:
                        self.active_connections = max(0, self.active_connections - 1)
            elif conn:
                # Close bad connections
                with contextlib.suppress(Exception):
                    await conn.close()
                async with self._lock:
                    self.active_connections = max(0, self.active_connections - 1)

    async def close(self) -> None:
        """Close all connections in the pool."""
        logger.info("🔌 Closing async PostgreSQL connection pool")
        self._closed = True

        # Cancel health check task
        if self._health_check_task:
            self._health_check_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._health_check_task

        # Close all connections
        while not self.connections.empty():
            with contextlib.suppress(Exception):
                conn = self.connections.get_nowait()
                await conn.close()

        logger.info("✅ Async PostgreSQL connection pool closed")
