"""Tests for insights PostgreSQL query functions."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_mock_pool(rows: list[tuple[Any, ...]]) -> AsyncMock:
    """Create a mock AsyncPostgreSQLPool that returns given rows."""
    mock_cursor = AsyncMock()
    mock_cursor.fetchall = AsyncMock(return_value=rows)
    mock_cursor.execute = AsyncMock()

    mock_conn = AsyncMock()
    mock_conn.cursor = MagicMock(return_value=mock_cursor)
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)
    mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor.__aexit__ = AsyncMock(return_value=False)

    mock_pool = AsyncMock()
    mock_pool.connection = MagicMock(return_value=mock_conn)
    return mock_pool


class TestQueryDataCompleteness:
    @pytest.mark.asyncio
    async def test_returns_completeness_for_all_entity_types(self) -> None:
        from api.queries.insights_pg_queries import query_data_completeness

        mock_pool = _make_mock_pool([(1000,)])
        result = await query_data_completeness(mock_pool)
        assert len(result) == 4
        entity_types = {r["entity_type"] for r in result}
        assert entity_types == {"artists", "labels", "masters", "releases"}

    @pytest.mark.asyncio
    async def test_handles_empty_tables(self) -> None:
        from api.queries.insights_pg_queries import query_data_completeness

        mock_pool = _make_mock_pool([(0,)])
        result = await query_data_completeness(mock_pool)
        for item in result:
            assert item["total_count"] == 0
            assert item["completeness_pct"] == 0.0

    @pytest.mark.asyncio
    async def test_calculates_completeness_percentage(self) -> None:
        from api.queries.insights_pg_queries import query_data_completeness

        # artists has only 1 field (with_image), so if count=1000 and image count=500, pct=50%
        call_count = 0

        async def side_effect(*_args: Any) -> list[tuple[int]]:
            nonlocal call_count
            call_count += 1
            if call_count % 2 == 1:  # Total count queries (odd calls)
                return [(1000,)]
            return [(500,)]  # Field count queries (even calls)

        mock_pool = _make_mock_pool([])
        cursor = mock_pool.connection.return_value.__aenter__.return_value.cursor.return_value.__aenter__.return_value
        cursor.fetchall = AsyncMock(side_effect=side_effect)

        result = await query_data_completeness(mock_pool)
        assert len(result) == 4
        # All should have non-zero completeness since total > 0
        for item in result:
            assert item["total_count"] == 1000
            assert item["completeness_pct"] > 0
