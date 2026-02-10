"""Database connection pool monitoring for Discovery service.

This module tracks connection pool metrics for Neo4j and PostgreSQL connections,
exposing them through Prometheus for observability.
"""

import asyncio
import logging
from typing import Any

from neo4j import AsyncDriver
from prometheus_client import Gauge
from sqlalchemy.ext.asyncio import AsyncEngine


logger = logging.getLogger(__name__)

# Prometheus metrics for Neo4j connection pool
neo4j_pool_size = Gauge(
    "neo4j_connection_pool_size",
    "Total size of Neo4j connection pool",
    ["component"],
)

neo4j_pool_in_use = Gauge(
    "neo4j_connection_pool_in_use",
    "Number of Neo4j connections currently in use",
    ["component"],
)

neo4j_pool_idle = Gauge(
    "neo4j_connection_pool_idle",
    "Number of idle Neo4j connections",
    ["component"],
)

neo4j_pool_acquisition_timeout = Gauge(
    "neo4j_connection_pool_acquisition_timeout_count",
    "Number of connection acquisition timeouts",
    ["component"],
)

# Prometheus metrics for PostgreSQL connection pool
postgres_pool_size = Gauge(
    "postgres_connection_pool_size",
    "Total size of PostgreSQL connection pool",
    ["component"],
)

postgres_pool_in_use = Gauge(
    "postgres_connection_pool_in_use",
    "Number of PostgreSQL connections currently in use",
    ["component"],
)

postgres_pool_overflow = Gauge(
    "postgres_connection_pool_overflow",
    "Number of PostgreSQL connections beyond the pool size",
    ["component"],
)

postgres_pool_checkedout = Gauge(
    "postgres_connection_pool_checkedout",
    "Number of PostgreSQL connections checked out",
    ["component"],
)


class ConnectionPoolMonitor:
    """Monitor database connection pools and expose metrics."""

    def __init__(self) -> None:
        """Initialize the connection pool monitor."""
        self.neo4j_drivers: dict[str, AsyncDriver] = {}
        self.postgres_engines: dict[str, AsyncEngine] = {}
        self._monitoring_task: asyncio.Task[None] | None = None
        self._stop_monitoring = False

    def register_neo4j_driver(self, component: str, driver: AsyncDriver) -> None:
        """Register a Neo4j driver for monitoring.

        Args:
            component: Component name (e.g., 'recommender', 'analytics')
            driver: Neo4j async driver instance
        """
        self.neo4j_drivers[component] = driver
        logger.info(f"📊 Registered Neo4j driver for monitoring: {component}")

    def register_postgres_engine(self, component: str, engine: AsyncEngine) -> None:
        """Register a PostgreSQL engine for monitoring.

        Args:
            component: Component name (e.g., 'analytics', 'playground_api')
            engine: SQLAlchemy async engine instance
        """
        self.postgres_engines[component] = engine
        logger.info(f"📊 Registered PostgreSQL engine for monitoring: {component}")

    async def collect_neo4j_metrics(self) -> dict[str, dict[str, Any]]:
        """Collect Neo4j connection pool metrics.

        Returns:
            Dictionary of component metrics
        """
        metrics: dict[str, dict[str, Any]] = {}

        for component, driver in self.neo4j_drivers.items():
            try:
                # Access internal connection pool metrics
                # Note: This uses internal APIs that may change between versions
                if hasattr(driver, "_pool"):
                    pool = driver._pool
                    pool_metrics = {
                        "size": getattr(pool, "_max_connection_pool_size", 0),
                        "in_use": getattr(pool, "_in_use_connection_count", 0),
                        "idle": getattr(pool, "_idle_connection_count", 0),
                        "acquisition_timeout_count": 0,  # Not directly available
                    }

                    # Update Prometheus metrics
                    neo4j_pool_size.labels(component=component).set(pool_metrics["size"])
                    neo4j_pool_in_use.labels(component=component).set(pool_metrics["in_use"])
                    neo4j_pool_idle.labels(component=component).set(pool_metrics["idle"])

                    metrics[component] = pool_metrics
                else:
                    # Fallback: estimate based on active sessions
                    metrics[component] = {
                        "size": 100,  # Default Neo4j pool size
                        "in_use": 0,
                        "idle": 0,
                        "acquisition_timeout_count": 0,
                    }

            except Exception as e:
                logger.warning(f"⚠️  Failed to collect Neo4j metrics for {component}: {e}")
                metrics[component] = {
                    "size": 0,
                    "in_use": 0,
                    "idle": 0,
                    "acquisition_timeout_count": 0,
                }

        return metrics

    async def collect_postgres_metrics(self) -> dict[str, dict[str, Any]]:
        """Collect PostgreSQL connection pool metrics.

        Returns:
            Dictionary of component metrics
        """
        metrics: dict[str, dict[str, Any]] = {}

        for component, engine in self.postgres_engines.items():
            try:
                pool = engine.pool

                # Get pool statistics (using getattr for type safety with async pools)
                size = getattr(pool, "size", lambda: 0)()
                checkedout = getattr(pool, "checkedout", lambda: 0)()
                overflow = getattr(pool, "overflow", lambda: 0)()

                pool_metrics = {
                    "size": size,
                    "checkedout": checkedout,
                    "overflow": overflow,
                    "checkedin": size - checkedout,
                }

                # Update Prometheus metrics
                postgres_pool_size.labels(component=component).set(pool_metrics["size"])
                postgres_pool_checkedout.labels(component=component).set(pool_metrics["checkedout"])
                postgres_pool_overflow.labels(component=component).set(pool_metrics["overflow"])
                postgres_pool_in_use.labels(component=component).set(pool_metrics["checkedout"])

                metrics[component] = pool_metrics

            except Exception as e:
                logger.warning(f"⚠️  Failed to collect PostgreSQL metrics for {component}: {e}")
                metrics[component] = {
                    "size": 0,
                    "checkedout": 0,
                    "overflow": 0,
                    "checkedin": 0,
                }

        return metrics

    async def collect_all_metrics(self) -> dict[str, Any]:
        """Collect all database connection pool metrics.

        Returns:
            Dictionary with neo4j and postgres metrics
        """
        neo4j_metrics = await self.collect_neo4j_metrics()
        postgres_metrics = await self.collect_postgres_metrics()

        return {
            "neo4j": neo4j_metrics,
            "postgres": postgres_metrics,
        }

    async def start_monitoring(self, interval: int = 30) -> None:
        """Start periodic connection pool monitoring.

        Args:
            interval: Monitoring interval in seconds (default: 30)
        """
        if self._monitoring_task is not None:
            logger.warning("⚠️  Connection pool monitoring already running")
            return

        async def monitor_loop() -> None:
            """Periodic monitoring loop."""
            logger.info(f"📊 Starting connection pool monitoring (interval: {interval}s)")
            while not self._stop_monitoring:
                try:
                    await self.collect_all_metrics()
                    await asyncio.sleep(interval)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"❌ Connection pool monitoring error: {e}")
                    await asyncio.sleep(interval)

        self._stop_monitoring = False
        self._monitoring_task = asyncio.create_task(monitor_loop())
        logger.info("✅ Connection pool monitoring started")

    async def stop_monitoring(self) -> None:
        """Stop periodic connection pool monitoring."""
        if self._monitoring_task is None:
            return

        self._stop_monitoring = True
        self._monitoring_task.cancel()

        from contextlib import suppress

        with suppress(asyncio.CancelledError):
            await self._monitoring_task

        self._monitoring_task = None
        logger.info("✅ Connection pool monitoring stopped")

    def get_metrics_summary(self) -> dict[str, Any]:
        """Get a summary of current connection pool metrics.

        Returns:
            Summary dictionary with total connections and component breakdown
        """
        summary = {
            "neo4j": {
                "total_drivers": len(self.neo4j_drivers),
                "components": list(self.neo4j_drivers.keys()),
            },
            "postgres": {
                "total_engines": len(self.postgres_engines),
                "components": list(self.postgres_engines.keys()),
            },
        }

        return summary


# Global connection pool monitor instance
pool_monitor = ConnectionPoolMonitor()
