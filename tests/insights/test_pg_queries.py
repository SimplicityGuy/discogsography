"""Tests for insights PostgreSQL query functions."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_mock_pool_fetchone(rows: list[tuple[Any, ...] | None]) -> AsyncMock:
    """Create a mock AsyncPostgreSQLPool where fetchone returns rows in order."""
    idx = 0

    async def mock_fetchone() -> tuple[Any, ...] | None:
        nonlocal idx
        result = rows[idx] if idx < len(rows) else None
        idx += 1
        return result

    mock_cursor = AsyncMock()
    mock_cursor.fetchone = AsyncMock(side_effect=mock_fetchone)
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

        rows: list[tuple[Any, ...] | None] = [
            (1000, 500),  # artists: total, with_image
            (1000, 500),  # labels: total, with_image
            (1000, 500, 500, 500),  # masters: total, with_year, with_genre, with_image
            (1000, 500, 500, 500, 500),  # releases: total, with_year, with_country, with_genre, with_image
        ]
        mock_pool = _make_mock_pool_fetchone(rows)
        result = await query_data_completeness(mock_pool)
        assert len(result) == 4
        entity_types = {r["entity_type"] for r in result}
        assert entity_types == {"artists", "labels", "masters", "releases"}

    @pytest.mark.asyncio
    async def test_handles_empty_tables(self) -> None:
        from api.queries.insights_pg_queries import query_data_completeness

        rows: list[tuple[Any, ...] | None] = [
            (0, 0),
            (0, 0),
            (0, 0, 0, 0),
            (0, 0, 0, 0, 0),
        ]
        mock_pool = _make_mock_pool_fetchone(rows)
        result = await query_data_completeness(mock_pool)
        for item in result:
            assert item["total_count"] == 0
            assert item["completeness_pct"] == 0.0

    @pytest.mark.asyncio
    async def test_calculates_completeness_percentage(self) -> None:
        from api.queries.insights_pg_queries import query_data_completeness

        # artists: 1 field, 500/1000 = 50%
        rows: list[tuple[Any, ...] | None] = [
            (1000, 500),  # artists: 50%
            (1000, 500),  # labels: 50%
            (1000, 500, 500, 500),  # masters: 50%
            (1000, 500, 500, 500, 500),  # releases: 50%
        ]
        mock_pool = _make_mock_pool_fetchone(rows)
        result = await query_data_completeness(mock_pool)
        assert len(result) == 4
        for item in result:
            assert item["total_count"] == 1000
            assert item["completeness_pct"] == 50.0
