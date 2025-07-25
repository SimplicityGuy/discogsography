"""Resilient Neo4j connection management with circuit breaker and retry logic."""

import asyncio
import logging
from typing import Any

from neo4j import AsyncGraphDatabase, GraphDatabase
from neo4j.exceptions import Neo4jError, ServiceUnavailable, SessionExpired

from .db_resilience import (
    AsyncResilientConnection,
    CircuitBreaker,
    CircuitBreakerConfig,
    ExponentialBackoff,
    ResilientConnection,
)


logger = logging.getLogger(__name__)


class ResilientNeo4jDriver(ResilientConnection[Any]):
    """Resilient Neo4j driver with automatic reconnection and circuit breaker."""

    def __init__(self, uri: str, auth: tuple[str, str], max_retries: int = 5, **driver_kwargs: Any):
        # Neo4j driver configuration
        self.uri = uri
        self.auth = auth
        self.driver_kwargs = {
            "max_connection_lifetime": 30 * 60,  # 30 minutes
            "max_connection_pool_size": 50,
            "connection_acquisition_timeout": 60.0,
            "keep_alive": True,  # Enable keep-alive
            **driver_kwargs,
        }

        # Circuit breaker for Neo4j failures
        circuit_breaker = CircuitBreaker(
            CircuitBreakerConfig(
                name="Neo4j", failure_threshold=3, recovery_timeout=30, expected_exception=(Neo4jError, ServiceUnavailable, SessionExpired)
            )
        )

        # Exponential backoff for retries
        backoff = ExponentialBackoff(initial_delay=1.0, max_delay=30.0, exponential_base=2.0)

        super().__init__(
            connection_factory=self._create_driver,
            connection_test=self._test_driver,
            circuit_breaker=circuit_breaker,
            backoff=backoff,
            max_retries=max_retries,
            name="Neo4j",
        )

        # Health check query
        self.health_check_query = "RETURN 1 as healthy"

    def _create_driver(self) -> Any:
        """Create a new Neo4j driver instance."""
        logger.info(f"🔗 Creating new Neo4j driver connection to {self.uri}")
        driver = GraphDatabase.driver(self.uri, auth=self.auth, **self.driver_kwargs)
        return driver

    def _test_driver(self, driver: Any) -> bool:
        """Test if the driver connection is healthy."""
        try:
            with driver.session(database="neo4j") as session:
                result = session.run(self.health_check_query)
                record = result.single()
                return record is not None and record["healthy"] == 1
        except Exception as e:
            logger.warning(f"⚠️ Neo4j health check failed: {e}")
            return False

    def session(self, **kwargs: Any) -> Any:
        """Get a Neo4j session with resilient connection."""
        driver = self.get_connection()
        return driver.session(**kwargs)

    def close(self) -> None:
        """Close the Neo4j driver."""
        with self._lock:
            if self._connection:
                try:
                    self._connection.close()
                    logger.info("✅ Neo4j driver closed")
                except Exception as e:
                    logger.warning(f"⚠️ Error closing Neo4j driver: {e}")
                finally:
                    self._connection = None


class AsyncResilientNeo4jDriver(AsyncResilientConnection[Any]):
    """Async resilient Neo4j driver with automatic reconnection and circuit breaker."""

    def __init__(self, uri: str, auth: tuple[str, str], max_retries: int = 5, **driver_kwargs: Any):
        # Neo4j driver configuration
        self.uri = uri
        self.auth = auth
        self.driver_kwargs = {
            "max_connection_lifetime": 30 * 60,  # 30 minutes
            "max_connection_pool_size": 50,
            "connection_acquisition_timeout": 60.0,
            "keep_alive": True,  # Enable keep-alive
            **driver_kwargs,
        }

        # Circuit breaker for Neo4j failures
        circuit_breaker = CircuitBreaker(
            CircuitBreakerConfig(
                name="AsyncNeo4j", failure_threshold=3, recovery_timeout=30, expected_exception=(Neo4jError, ServiceUnavailable, SessionExpired)
            )
        )

        # Exponential backoff for retries
        backoff = ExponentialBackoff(initial_delay=1.0, max_delay=30.0, exponential_base=2.0)

        super().__init__(
            connection_factory=self._create_driver,
            connection_test=self._test_driver,
            circuit_breaker=circuit_breaker,
            backoff=backoff,
            max_retries=max_retries,
            name="AsyncNeo4j",
        )

        # Health check query
        self.health_check_query = "RETURN 1 as healthy"

    async def _create_driver(self) -> Any:
        """Create a new async Neo4j driver instance."""
        logger.info(f"🔗 Creating new async Neo4j driver connection to {self.uri}")
        driver = AsyncGraphDatabase.driver(self.uri, auth=self.auth, **self.driver_kwargs)
        return driver

    async def _test_driver(self, driver: Any) -> bool:
        """Test if the driver connection is healthy."""
        try:
            async with driver.session(database="neo4j") as session:
                result = await session.run(self.health_check_query)
                record = await result.single()
                return record is not None and record["healthy"] == 1
        except Exception as e:
            logger.warning(f"⚠️ Async Neo4j health check failed: {e}")
            return False

    async def session(self, **kwargs: Any) -> Any:
        """Get an async Neo4j session with resilient connection."""
        driver = await self.get_connection()
        return driver.session(**kwargs)

    async def close(self) -> None:
        """Close the async Neo4j driver."""
        async with self._lock:
            if self._connection:
                try:
                    await self._connection.close()
                    logger.info("✅ Async Neo4j driver closed")
                except Exception as e:
                    logger.warning(f"⚠️ Error closing async Neo4j driver: {e}")
                finally:
                    self._connection = None


# Helper function to handle transaction retries
def with_neo4j_retry(func: Any, max_retries: int = 3, backoff: ExponentialBackoff | None = None) -> Any:
    """Decorator to add retry logic to Neo4j transactions."""
    if backoff is None:
        backoff = ExponentialBackoff()

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        last_error = None
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except (ServiceUnavailable, SessionExpired) as e:
                last_error = e
                if attempt < max_retries - 1:
                    delay = backoff.get_delay(attempt)
                    logger.warning(f"⚠️ Neo4j transaction failed (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {delay:.1f} seconds...")
                    import time

                    time.sleep(delay)
                else:
                    logger.error(f"❌ Neo4j transaction failed after {max_retries} attempts")

        if last_error:
            raise last_error
        else:
            raise Exception("Failed after retries")

    return wrapper


# Async version
def with_async_neo4j_retry(func: Any, max_retries: int = 3, backoff: ExponentialBackoff | None = None) -> Any:
    """Async decorator to add retry logic to Neo4j transactions."""
    if backoff is None:
        backoff = ExponentialBackoff()

    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        last_error = None
        for attempt in range(max_retries):
            try:
                return await func(*args, **kwargs)
            except (ServiceUnavailable, SessionExpired) as e:
                last_error = e
                if attempt < max_retries - 1:
                    delay = backoff.get_delay(attempt)
                    logger.warning(f"⚠️ Async Neo4j transaction failed (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {delay:.1f} seconds...")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"❌ Async Neo4j transaction failed after {max_retries} attempts")

        if last_error:
            raise last_error
        else:
            raise Exception("Failed after retries")

    return wrapper
