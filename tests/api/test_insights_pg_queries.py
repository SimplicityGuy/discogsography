"""Tests for insights PostgreSQL queries."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.queries.insights_pg_queries import (
    _ALLOWED_TABLES,
    _COMPLETENESS_FIELDS,
    _COUNT_QUERIES,
    _FIELD_QUERIES,
    query_data_completeness,
)


class TestConstants:
    def test_allowed_tables_are_expected(self) -> None:
        assert frozenset({"artists", "labels", "masters", "releases"}) == _ALLOWED_TABLES

    def test_count_queries_are_built_for_each_table(self) -> None:
        for table in _ALLOWED_TABLES:
            assert table in _COUNT_QUERIES
            assert _COUNT_QUERIES[table] == f"SELECT count(*) FROM {table}"  # noqa: S608

    def test_field_queries_built_for_completeness_fields(self) -> None:
        for table, fields in _COMPLETENESS_FIELDS.items():
            assert table in _FIELD_QUERIES
            for field_name, _jsonb_key in fields:
                assert field_name in _FIELD_QUERIES[table]

    def test_completeness_fields_cover_all_entity_types(self) -> None:
        assert set(_COMPLETENESS_FIELDS.keys()) == {"artists", "labels", "masters", "releases"}

    def test_releases_has_most_fields(self) -> None:
        assert len(_COMPLETENESS_FIELDS["releases"]) == 4
        field_names = [f[0] for f in _COMPLETENESS_FIELDS["releases"]]
        assert "with_year" in field_names
        assert "with_country" in field_names
        assert "with_genre" in field_names
        assert "with_image" in field_names


def _make_mock_pool(count_result: int = 100, field_result: int = 80) -> MagicMock:
    """Create a mock pool that returns configurable counts."""
    call_count = 0

    async def mock_execute(query: str, *args: Any) -> None:
        pass

    async def mock_fetchall() -> list[tuple[int]]:
        nonlocal call_count
        call_count += 1
        # First call per entity is the total count, subsequent are field counts
        return [(count_result,)] if call_count % 2 == 1 else [(field_result,)]

    mock_cursor = AsyncMock()
    mock_cursor.execute = AsyncMock(side_effect=mock_execute)
    mock_cursor.fetchall = AsyncMock(side_effect=mock_fetchall)
    mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor.__aexit__ = AsyncMock(return_value=False)

    mock_conn = AsyncMock()
    mock_conn.cursor = MagicMock(return_value=mock_cursor)
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.connection = MagicMock(return_value=mock_conn)
    return pool


def _make_pool_with_sequence(sequence: list[list[tuple[int]]]) -> MagicMock:
    """Create a mock pool that returns results in order from the sequence list."""
    idx = 0

    async def mock_fetchall() -> list[tuple[int]]:
        nonlocal idx
        result = sequence[idx] if idx < len(sequence) else []
        idx += 1
        return result

    mock_cursor = AsyncMock()
    mock_cursor.execute = AsyncMock()
    mock_cursor.fetchall = AsyncMock(side_effect=mock_fetchall)
    mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor.__aexit__ = AsyncMock(return_value=False)

    mock_conn = AsyncMock()
    mock_conn.cursor = MagicMock(return_value=mock_cursor)
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.connection = MagicMock(return_value=mock_conn)
    return pool


class TestQueryDataCompleteness:
    @pytest.mark.asyncio
    async def test_returns_results_for_all_entity_types(self) -> None:
        # Build sequence: for each entity type, first call is total, then field counts
        sequence: list[list[tuple[int]]] = []
        for _table, fields in _COMPLETENESS_FIELDS.items():
            sequence.append([(1000,)])  # total count
            for _ in fields:
                sequence.append([(800,)])  # field count

        pool = _make_pool_with_sequence(sequence)
        results = await query_data_completeness(pool)

        assert len(results) == 4
        entity_types = {r["entity_type"] for r in results}
        assert entity_types == {"artists", "labels", "masters", "releases"}

    @pytest.mark.asyncio
    async def test_calculates_completeness_percentage(self) -> None:
        # artists has 1 field (with_image), so completeness = 80/100 * 100 = 80%
        sequence: list[list[tuple[int]]] = []
        for _table, fields in _COMPLETENESS_FIELDS.items():
            sequence.append([(100,)])  # total
            for _ in fields:
                sequence.append([(80,)])  # field count

        pool = _make_pool_with_sequence(sequence)
        results = await query_data_completeness(pool)

        # All should have completeness_pct = 80.0 (80/100 * 100)
        for result in results:
            assert result["completeness_pct"] == 80.0

    @pytest.mark.asyncio
    async def test_zero_total_count_returns_zero_completeness(self) -> None:
        # All tables return 0 total
        sequence: list[list[tuple[int]]] = []
        for _table, _fields in _COMPLETENESS_FIELDS.items():
            sequence.append([(0,)])  # total count = 0, no field queries needed

        pool = _make_pool_with_sequence(sequence)
        results = await query_data_completeness(pool)

        for result in results:
            assert result["total_count"] == 0
            assert result["completeness_pct"] == 0.0

    @pytest.mark.asyncio
    async def test_empty_fetchall_returns_zero_count(self) -> None:
        # All fetchall return empty list
        sequence: list[list[tuple[int]]] = []
        for _table, _fields in _COMPLETENESS_FIELDS.items():
            sequence.append([])  # empty result for total count

        pool = _make_pool_with_sequence(sequence)
        results = await query_data_completeness(pool)

        for result in results:
            assert result["total_count"] == 0

    @pytest.mark.asyncio
    async def test_result_contains_expected_fields(self) -> None:
        sequence: list[list[tuple[int]]] = []
        for _table, fields in _COMPLETENESS_FIELDS.items():
            sequence.append([(100,)])
            for _ in fields:
                sequence.append([(50,)])

        pool = _make_pool_with_sequence(sequence)
        results = await query_data_completeness(pool)

        for result in results:
            assert "entity_type" in result
            assert "total_count" in result
            assert "completeness_pct" in result
            assert "with_image" in result
