"""Tests for insights PostgreSQL queries."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.queries.insights_pg_queries import (
    _COMBINED_QUERIES,
    _COMPLETENESS_FIELDS,
    query_data_completeness,
)


class TestConstants:
    def test_combined_queries_built_for_each_entity_type(self) -> None:
        for table in _COMPLETENESS_FIELDS:
            assert table in _COMBINED_QUERIES
            assert "count(*) AS total_count" in _COMBINED_QUERIES[table]
            assert f"FROM {table}" in _COMBINED_QUERIES[table]

    def test_combined_queries_include_filter_clauses(self) -> None:
        for table, fields in _COMPLETENESS_FIELDS.items():
            for field_name, jsonb_key in fields:
                assert f"AS {field_name}" in _COMBINED_QUERIES[table]
                assert f"data->>'{jsonb_key}'" in _COMBINED_QUERIES[table]

    def test_completeness_fields_cover_all_entity_types(self) -> None:
        assert set(_COMPLETENESS_FIELDS.keys()) == {"artists", "labels", "masters", "releases"}

    def test_releases_has_most_fields(self) -> None:
        assert len(_COMPLETENESS_FIELDS["releases"]) == 4
        field_names = [f[0] for f in _COMPLETENESS_FIELDS["releases"]]
        assert "with_year" in field_names
        assert "with_country" in field_names
        assert "with_genre" in field_names
        assert "with_image" in field_names


def _make_pool_with_fetchone_sequence(sequence: list[tuple[int, ...] | None]) -> MagicMock:
    """Create a mock pool where fetchone returns rows from the sequence in order."""
    idx = 0

    async def mock_fetchone() -> tuple[int, ...] | None:
        nonlocal idx
        result = sequence[idx] if idx < len(sequence) else None
        idx += 1
        return result

    mock_cursor = AsyncMock()
    mock_cursor.execute = AsyncMock()
    mock_cursor.fetchone = AsyncMock(side_effect=mock_fetchone)
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
        # Each entity type returns one row: (total, field1, field2, ...)
        sequence: list[tuple[int, ...] | None] = [
            (1000, 800),  # artists: total, with_image
            (1000, 800),  # labels: total, with_image
            (1000, 800, 800, 800),  # masters: total, with_year, with_genre, with_image
            (1000, 800, 800, 800, 800),  # releases: total, with_year, with_country, with_genre, with_image
        ]
        pool = _make_pool_with_fetchone_sequence(sequence)
        results = await query_data_completeness(pool)

        assert len(results) == 4
        entity_types = {r["entity_type"] for r in results}
        assert entity_types == {"artists", "labels", "masters", "releases"}

    @pytest.mark.asyncio
    async def test_calculates_completeness_percentage(self) -> None:
        # 80/100 = 80% for each field
        sequence: list[tuple[int, ...] | None] = [
            (100, 80),  # artists
            (100, 80),  # labels
            (100, 80, 80, 80),  # masters
            (100, 80, 80, 80, 80),  # releases
        ]
        pool = _make_pool_with_fetchone_sequence(sequence)
        results = await query_data_completeness(pool)

        for result in results:
            assert result["completeness_pct"] == 80.0

    @pytest.mark.asyncio
    async def test_zero_total_count_returns_zero_completeness(self) -> None:
        # Each entity returns 0 total (remaining columns don't matter)
        sequence: list[tuple[int, ...] | None] = [
            (0, 0),
            (0, 0),
            (0, 0, 0, 0),
            (0, 0, 0, 0, 0),
        ]
        pool = _make_pool_with_fetchone_sequence(sequence)
        results = await query_data_completeness(pool)

        for result in results:
            assert result["total_count"] == 0
            assert result["completeness_pct"] == 0.0

    @pytest.mark.asyncio
    async def test_none_fetchone_returns_zero_count(self) -> None:
        sequence: list[tuple[int, ...] | None] = [None, None, None, None]
        pool = _make_pool_with_fetchone_sequence(sequence)
        results = await query_data_completeness(pool)

        for result in results:
            assert result["total_count"] == 0

    @pytest.mark.asyncio
    async def test_result_contains_expected_fields(self) -> None:
        sequence: list[tuple[int, ...] | None] = [
            (100, 50),
            (100, 50),
            (100, 50, 50, 50),
            (100, 50, 50, 50, 50),
        ]
        pool = _make_pool_with_fetchone_sequence(sequence)
        results = await query_data_completeness(pool)

        for result in results:
            assert "entity_type" in result
            assert "total_count" in result
            assert "completeness_pct" in result
            assert "with_image" in result
