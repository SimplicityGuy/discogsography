"""Tests for database query performance metrics tracking."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_track_query_performance_success() -> None:
    """Test that successful queries are tracked correctly."""
    from discovery.db_metrics import track_query_performance

    # Mock the metrics
    with (
        patch("discovery.db_metrics.db_query_duration") as mock_duration,
        patch("discovery.db_metrics.db_query_count") as mock_count,
    ):
        # Configure mocks
        mock_duration_metric = MagicMock()
        mock_duration.labels.return_value = mock_duration_metric

        mock_count_metric = MagicMock()
        mock_count.labels.return_value = mock_count_metric

        # Execute query within tracking context
        async with track_query_performance("neo4j", "test_operation"):
            # Simulate query execution
            await asyncio.sleep(0.01)

        # Verify duration was observed
        mock_duration.labels.assert_called_once_with(db_type="neo4j", operation="test_operation")
        assert mock_duration_metric.observe.called

        # Verify count was incremented with success status
        mock_count.labels.assert_called_once_with(db_type="neo4j", operation="test_operation", status="success")
        mock_count_metric.inc.assert_called_once()


@pytest.mark.asyncio
async def test_track_query_performance_error() -> None:
    """Test that failed queries are tracked with error status."""
    from discovery.db_metrics import track_query_performance

    # Mock the metrics
    with (
        patch("discovery.db_metrics.db_query_duration") as mock_duration,
        patch("discovery.db_metrics.db_query_count") as mock_count,
    ):
        # Configure mocks
        mock_duration_metric = MagicMock()
        mock_duration.labels.return_value = mock_duration_metric

        mock_count_metric = MagicMock()
        mock_count.labels.return_value = mock_count_metric

        # Execute query that fails
        with pytest.raises(ValueError, match="Test error"):
            async with track_query_performance("neo4j", "failing_operation"):
                raise ValueError("Test error")

        # Verify duration was still observed (to track failed query times)
        mock_duration.labels.assert_called_once_with(db_type="neo4j", operation="failing_operation")
        assert mock_duration_metric.observe.called

        # Verify count was incremented with error status
        mock_count.labels.assert_called_once_with(db_type="neo4j", operation="failing_operation", status="error")
        mock_count_metric.inc.assert_called_once()


@pytest.mark.asyncio
async def test_track_neo4j_query() -> None:
    """Test Neo4j query tracking helper."""
    from discovery.db_metrics import track_neo4j_query

    # Mock query function
    async def mock_query() -> dict:  # type: ignore[type-arg]
        await asyncio.sleep(0.01)
        return {"result": "data"}

    # Mock the metrics
    with (
        patch("discovery.db_metrics.db_query_duration") as mock_duration,
        patch("discovery.db_metrics.db_query_count") as mock_count,
    ):
        # Configure mocks
        mock_duration.labels.return_value = MagicMock()
        mock_count.labels.return_value = MagicMock()

        # Track query
        result = await track_neo4j_query("search", mock_query)

        # Verify result is returned
        assert result == {"result": "data"}

        # Verify metrics were recorded
        mock_duration.labels.assert_called_once_with(db_type="neo4j", operation="search")
        mock_count.labels.assert_called_once_with(db_type="neo4j", operation="search", status="success")


@pytest.mark.asyncio
async def test_track_postgres_query() -> None:
    """Test PostgreSQL query tracking helper."""
    from discovery.db_metrics import track_postgres_query

    # Mock query function
    async def mock_query() -> list:  # type: ignore[type-arg]
        await asyncio.sleep(0.01)
        return [{"id": 1}, {"id": 2}]

    # Mock the metrics
    with (
        patch("discovery.db_metrics.db_query_duration") as mock_duration,
        patch("discovery.db_metrics.db_query_count") as mock_count,
    ):
        # Configure mocks
        mock_duration.labels.return_value = MagicMock()
        mock_count.labels.return_value = MagicMock()

        # Track query
        result = await track_postgres_query("fetch_users", mock_query)

        # Verify result is returned
        assert len(result) == 2

        # Verify metrics were recorded for postgres
        mock_duration.labels.assert_called_once_with(db_type="postgres", operation="fetch_users")
        mock_count.labels.assert_called_once_with(db_type="postgres", operation="fetch_users", status="success")


@pytest.mark.asyncio
async def test_query_duration_timing() -> None:
    """Test that query duration is accurately measured."""
    from discovery.db_metrics import track_query_performance

    # Mock the metrics
    with (
        patch("discovery.db_metrics.db_query_duration") as mock_duration,
        patch("discovery.db_metrics.db_query_count"),
    ):
        # Configure mock
        mock_duration_metric = MagicMock()
        mock_duration.labels.return_value = mock_duration_metric

        # Execute query with known duration
        async with track_query_performance("neo4j", "timed_operation"):
            await asyncio.sleep(0.1)  # Sleep for 100ms

        # Verify duration was observed
        assert mock_duration_metric.observe.called
        observed_duration = mock_duration_metric.observe.call_args[0][0]

        # Duration should be around 0.1 seconds (100ms), allowing for some variance
        assert 0.09 < observed_duration < 0.15


@pytest.mark.asyncio
async def test_multiple_database_types() -> None:
    """Test tracking queries across different database types."""
    from discovery.db_metrics import track_query_performance

    # Mock the metrics
    with (
        patch("discovery.db_metrics.db_query_duration") as mock_duration,
        patch("discovery.db_metrics.db_query_count") as mock_count,
    ):
        # Configure mocks
        mock_duration.labels.return_value = MagicMock()
        mock_count.labels.return_value = MagicMock()

        # Track Neo4j query
        async with track_query_performance("neo4j", "graph_query"):
            await asyncio.sleep(0.01)

        # Track Postgres query
        async with track_query_performance("postgres", "sql_query"):
            await asyncio.sleep(0.01)

        # Verify both database types were tracked
        assert mock_duration.labels.call_count == 2
        assert mock_count.labels.call_count == 2

        # Verify correct db_type labels
        duration_calls = [call[1] for call in mock_duration.labels.call_args_list]
        assert {"db_type": "neo4j", "operation": "graph_query"} in duration_calls
        assert {"db_type": "postgres", "operation": "sql_query"} in duration_calls


@pytest.mark.asyncio
async def test_concurrent_query_tracking() -> None:
    """Test that concurrent queries are tracked independently."""
    from discovery.db_metrics import track_query_performance

    # Mock the metrics
    with (
        patch("discovery.db_metrics.db_query_duration") as mock_duration,
        patch("discovery.db_metrics.db_query_count") as mock_count,
    ):
        # Configure mocks
        mock_duration.labels.return_value = MagicMock()
        mock_count.labels.return_value = MagicMock()

        # Define concurrent queries
        async def query1() -> None:
            async with track_query_performance("neo4j", "query1"):
                await asyncio.sleep(0.05)

        async def query2() -> None:
            async with track_query_performance("neo4j", "query2"):
                await asyncio.sleep(0.03)

        # Execute queries concurrently
        await asyncio.gather(query1(), query2())

        # Verify both queries were tracked
        assert mock_duration.labels.call_count == 2
        assert mock_count.labels.call_count == 2


@pytest.mark.asyncio
async def test_query_tracking_with_return_value() -> None:
    """Test that tracking doesn't interfere with return values."""
    from discovery.db_metrics import track_neo4j_query

    expected_result = {"nodes": [1, 2, 3], "edges": [{"from": 1, "to": 2}]}

    async def mock_query() -> dict:  # type: ignore[type-arg]
        return expected_result

    # Mock the metrics
    with (
        patch("discovery.db_metrics.db_query_duration"),
        patch("discovery.db_metrics.db_query_count"),
    ):
        result = await track_neo4j_query("complex_query", mock_query)

        # Verify exact result is returned
        assert result == expected_result
        assert result is expected_result  # Same object reference
