"""Tests for database connection pool metrics."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_register_neo4j_driver() -> None:
    """Test registering a Neo4j driver for monitoring."""
    from discovery.db_pool_metrics import ConnectionPoolMonitor

    monitor = ConnectionPoolMonitor()
    mock_driver = MagicMock()

    monitor.register_neo4j_driver("test_component", mock_driver)

    assert "test_component" in monitor.neo4j_drivers
    assert monitor.neo4j_drivers["test_component"] == mock_driver


@pytest.mark.asyncio
async def test_register_postgres_engine() -> None:
    """Test registering a PostgreSQL engine for monitoring."""
    from discovery.db_pool_metrics import ConnectionPoolMonitor

    monitor = ConnectionPoolMonitor()
    mock_engine = MagicMock()

    monitor.register_postgres_engine("test_component", mock_engine)

    assert "test_component" in monitor.postgres_engines
    assert monitor.postgres_engines["test_component"] == mock_engine


@pytest.mark.asyncio
async def test_collect_neo4j_metrics() -> None:
    """Test collecting Neo4j connection pool metrics."""
    from discovery.db_pool_metrics import ConnectionPoolMonitor

    monitor = ConnectionPoolMonitor()
    mock_driver = MagicMock()

    # Mock the internal pool attributes
    mock_pool = MagicMock()
    mock_pool._max_connection_pool_size = 100
    mock_pool._in_use_connection_count = 5
    mock_pool._idle_connection_count = 95
    mock_driver._pool = mock_pool

    monitor.register_neo4j_driver("test", mock_driver)
    metrics = await monitor.collect_neo4j_metrics()

    assert "test" in metrics
    assert metrics["test"]["size"] == 100
    assert metrics["test"]["in_use"] == 5
    assert metrics["test"]["idle"] == 95


@pytest.mark.asyncio
async def test_collect_neo4j_metrics_fallback() -> None:
    """Test Neo4j metrics collection with fallback when pool not available."""
    from discovery.db_pool_metrics import ConnectionPoolMonitor

    monitor = ConnectionPoolMonitor()
    mock_driver = MagicMock()
    # No _pool attribute (fallback case)
    if hasattr(mock_driver, "_pool"):
        delattr(mock_driver, "_pool")

    monitor.register_neo4j_driver("test", mock_driver)
    metrics = await monitor.collect_neo4j_metrics()

    assert "test" in metrics
    # Should use fallback values
    assert metrics["test"]["size"] == 100


@pytest.mark.asyncio
async def test_collect_postgres_metrics() -> None:
    """Test collecting PostgreSQL connection pool metrics."""
    from discovery.db_pool_metrics import ConnectionPoolMonitor

    monitor = ConnectionPoolMonitor()
    mock_engine = MagicMock()

    # Mock the pool
    mock_pool = MagicMock()
    mock_pool.size.return_value = 20
    mock_pool.checkedout.return_value = 3
    mock_pool.overflow.return_value = 0
    mock_engine.pool = mock_pool

    monitor.register_postgres_engine("test", mock_engine)
    metrics = await monitor.collect_postgres_metrics()

    assert "test" in metrics
    assert metrics["test"]["size"] == 20
    assert metrics["test"]["checkedout"] == 3
    assert metrics["test"]["overflow"] == 0
    assert metrics["test"]["checkedin"] == 17  # size - checkedout


@pytest.mark.asyncio
async def test_collect_all_metrics() -> None:
    """Test collecting all database connection pool metrics."""
    from discovery.db_pool_metrics import ConnectionPoolMonitor

    monitor = ConnectionPoolMonitor()

    # Mock Neo4j driver
    mock_neo4j = MagicMock()
    mock_pool = MagicMock()
    mock_pool._max_connection_pool_size = 100
    mock_pool._in_use_connection_count = 10
    mock_pool._idle_connection_count = 90
    mock_neo4j._pool = mock_pool
    monitor.register_neo4j_driver("neo4j_component", mock_neo4j)

    # Mock PostgreSQL engine
    mock_postgres = MagicMock()
    mock_pg_pool = MagicMock()
    mock_pg_pool.size.return_value = 20
    mock_pg_pool.checkedout.return_value = 5
    mock_pg_pool.overflow.return_value = 2
    mock_postgres.pool = mock_pg_pool
    monitor.register_postgres_engine("postgres_component", mock_postgres)

    metrics = await monitor.collect_all_metrics()

    assert "neo4j" in metrics
    assert "postgres" in metrics
    assert "neo4j_component" in metrics["neo4j"]
    assert "postgres_component" in metrics["postgres"]


@pytest.mark.asyncio
async def test_get_metrics_summary() -> None:
    """Test getting metrics summary."""
    from discovery.db_pool_metrics import ConnectionPoolMonitor

    monitor = ConnectionPoolMonitor()
    mock_driver = MagicMock()
    mock_engine = MagicMock()

    monitor.register_neo4j_driver("neo4j_1", mock_driver)
    monitor.register_neo4j_driver("neo4j_2", mock_driver)
    monitor.register_postgres_engine("postgres_1", mock_engine)

    summary = monitor.get_metrics_summary()

    assert summary["neo4j"]["total_drivers"] == 2
    assert "neo4j_1" in summary["neo4j"]["components"]
    assert "neo4j_2" in summary["neo4j"]["components"]
    assert summary["postgres"]["total_engines"] == 1
    assert "postgres_1" in summary["postgres"]["components"]


@pytest.mark.asyncio
async def test_start_stop_monitoring() -> None:
    """Test starting and stopping connection pool monitoring."""
    from discovery.db_pool_metrics import ConnectionPoolMonitor

    monitor = ConnectionPoolMonitor()

    # Start monitoring with short interval
    await monitor.start_monitoring(interval=0.1)
    assert monitor._monitoring_task is not None
    assert not monitor._stop_monitoring

    # Let it run briefly
    await asyncio.sleep(0.2)

    # Stop monitoring
    await monitor.stop_monitoring()
    assert monitor._monitoring_task is None
    assert monitor._stop_monitoring


@pytest.mark.asyncio
async def test_monitoring_loop_continues_on_error() -> None:
    """Test that monitoring loop continues even if collection fails."""
    from discovery.db_pool_metrics import ConnectionPoolMonitor

    monitor = ConnectionPoolMonitor()

    # Register a driver that will cause an error
    mock_driver = MagicMock()
    mock_driver._pool = MagicMock()
    mock_driver._pool._max_connection_pool_size = MagicMock(side_effect=Exception("Test error"))

    monitor.register_neo4j_driver("faulty", mock_driver)

    # Start monitoring
    await monitor.start_monitoring(interval=0.1)

    # Let it run briefly - should not crash
    await asyncio.sleep(0.3)

    # Stop monitoring
    await monitor.stop_monitoring()


@pytest.mark.asyncio
async def test_double_start_monitoring() -> None:
    """Test that starting monitoring twice doesn't create duplicate tasks."""
    from discovery.db_pool_metrics import ConnectionPoolMonitor

    monitor = ConnectionPoolMonitor()

    await monitor.start_monitoring(interval=0.1)
    first_task = monitor._monitoring_task

    # Try to start again
    await monitor.start_monitoring(interval=0.1)
    second_task = monitor._monitoring_task

    # Should be the same task
    assert first_task == second_task

    await monitor.stop_monitoring()


@pytest.mark.asyncio
async def test_db_pool_stats_endpoint(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test /api/db/pool/stats endpoint."""
    from discovery.db_pool_metrics import pool_monitor

    # Mock the pool monitor methods
    with (
        patch.object(pool_monitor, "collect_all_metrics", new_callable=AsyncMock) as mock_collect,
        patch.object(pool_monitor, "get_metrics_summary") as mock_summary,
    ):
        mock_collect.return_value = {
            "neo4j": {"test": {"size": 100, "in_use": 10, "idle": 90, "acquisition_timeout_count": 0}},
            "postgres": {"test": {"size": 20, "checkedout": 5, "overflow": 0, "checkedin": 15}},
        }
        mock_summary.return_value = {
            "neo4j": {"total_drivers": 1, "components": ["test"]},
            "postgres": {"total_engines": 1, "components": ["test"]},
        }

        response = discovery_client.get("/api/db/pool/stats")

        assert response.status_code == 200
        data = response.json()

        assert "metrics" in data
        assert "summary" in data
        assert "timestamp" in data

        # Check metrics structure
        assert "neo4j" in data["metrics"]
        assert "postgres" in data["metrics"]

        # Check summary structure
        assert data["summary"]["neo4j"]["total_drivers"] == 1
        assert data["summary"]["postgres"]["total_engines"] == 1
