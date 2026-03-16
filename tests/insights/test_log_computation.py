"""Tests for the _log_computation helper in insights.computations."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from insights.computations import _log_computation


def _make_mock_pool() -> AsyncMock:
    """Create a mock pool for logging."""
    mock_cursor = AsyncMock()
    mock_cursor.execute = AsyncMock()
    mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor.__aexit__ = AsyncMock(return_value=False)

    mock_conn = AsyncMock()
    mock_conn.cursor = MagicMock(return_value=mock_cursor)
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)

    pool = AsyncMock()
    pool.connection = MagicMock(return_value=mock_conn)
    return pool


class TestLogComputation:
    @pytest.mark.asyncio
    async def test_inserts_completed_log_entry(self) -> None:
        pool = _make_mock_pool()
        started_at = datetime.now(UTC)

        await _log_computation(pool, "artist_centrality", "completed", started_at, rows_affected=10)

        cursor = pool.connection.return_value.__aenter__.return_value.cursor.return_value.__aenter__.return_value
        cursor.execute.assert_called_once()
        call_args = cursor.execute.call_args
        assert "INSERT INTO insights.computation_log" in call_args[0][0]
        params = call_args[0][1]
        assert params[0] == "artist_centrality"
        assert params[1] == "completed"
        assert params[4] == 10
        assert params[6] is None  # error_message

    @pytest.mark.asyncio
    async def test_inserts_failed_log_entry_with_error(self) -> None:
        pool = _make_mock_pool()
        started_at = datetime.now(UTC)

        await _log_computation(
            pool,
            "genre_trends",
            "failed",
            started_at,
            rows_affected=0,
            error_message="DB connection lost",
        )

        cursor = pool.connection.return_value.__aenter__.return_value.cursor.return_value.__aenter__.return_value
        params = cursor.execute.call_args[0][1]
        assert params[0] == "genre_trends"
        assert params[1] == "failed"
        assert params[4] == 0
        assert params[6] == "DB connection lost"

    @pytest.mark.asyncio
    async def test_calculates_positive_duration(self) -> None:
        pool = _make_mock_pool()
        # Use a started_at slightly in the past
        started_at = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)

        await _log_computation(pool, "test_type", "completed", started_at)

        cursor = pool.connection.return_value.__aenter__.return_value.cursor.return_value.__aenter__.return_value
        params = cursor.execute.call_args[0][1]
        duration_ms = params[5]
        assert duration_ms > 0

    @pytest.mark.asyncio
    async def test_default_rows_affected_is_zero(self) -> None:
        pool = _make_mock_pool()
        started_at = datetime.now(UTC)

        await _log_computation(pool, "test_type", "completed", started_at)

        cursor = pool.connection.return_value.__aenter__.return_value.cursor.return_value.__aenter__.return_value
        params = cursor.execute.call_args[0][1]
        assert params[4] == 0

    @pytest.mark.asyncio
    async def test_passes_started_at_and_completed_at(self) -> None:
        pool = _make_mock_pool()
        started_at = datetime(2026, 3, 15, 12, 0, 0, tzinfo=UTC)

        await _log_computation(pool, "test_type", "completed", started_at)

        cursor = pool.connection.return_value.__aenter__.return_value.cursor.return_value.__aenter__.return_value
        params = cursor.execute.call_args[0][1]
        assert params[2] == started_at  # started_at
        assert isinstance(params[3], datetime)  # completed_at
        assert params[3] >= started_at
