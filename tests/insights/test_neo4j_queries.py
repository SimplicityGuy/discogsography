"""Tests for insights Neo4j query functions."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


class _AsyncIterator:
    """Async iterator wrapper for mock Neo4j result records."""

    def __init__(self, items: list[Any]) -> None:
        self._items = iter(items)

    def __aiter__(self) -> "_AsyncIterator":
        return self

    async def __anext__(self) -> Any:
        try:
            return next(self._items)
        except StopIteration:
            raise StopAsyncIteration from None

    async def consume(self) -> MagicMock:
        return MagicMock()


class _DictRecord(dict):  # type: ignore[type-arg]
    """A dict subclass that also exposes .data() for backward-compat tests."""

    def data(self) -> dict[str, Any]:
        return dict(self)


def _make_mock_driver(records: list[dict[str, Any]]) -> AsyncMock:
    """Create a mock Neo4j driver that returns the given records."""
    mock_records = [_DictRecord(r) for r in records]

    mock_result = _AsyncIterator(mock_records)

    mock_session = AsyncMock()
    mock_session.run = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_driver = AsyncMock()
    mock_driver.session = MagicMock(return_value=mock_session)
    return mock_driver


class TestQueryArtistCentrality:
    @pytest.mark.asyncio
    async def test_returns_ranked_artists(self) -> None:
        from api.queries.insights_neo4j_queries import query_artist_centrality

        records = [
            {"artist_id": "a1", "artist_name": "Artist One", "edge_count": 100},
            {"artist_id": "a2", "artist_name": "Artist Two", "edge_count": 50},
        ]
        driver = _make_mock_driver(records)
        result = await query_artist_centrality(driver, limit=100)
        assert len(result) == 2
        assert result[0]["artist_id"] == "a1"
        assert result[0]["edge_count"] == 100

    @pytest.mark.asyncio
    async def test_empty_results(self) -> None:
        from api.queries.insights_neo4j_queries import query_artist_centrality

        driver = _make_mock_driver([])
        result = await query_artist_centrality(driver, limit=100)
        assert result == []


class TestQueryGenreTrends:
    @pytest.mark.asyncio
    async def test_returns_genre_decade_counts(self) -> None:
        from api.queries.insights_neo4j_queries import query_genre_trends

        records = [
            {"genre": "Rock", "decade": 1970, "release_count": 50000},
            {"genre": "Rock", "decade": 1980, "release_count": 75000},
            {"genre": "Jazz", "decade": 1960, "release_count": 30000},
        ]
        driver = _make_mock_driver(records)
        result = await query_genre_trends(driver)
        assert len(result) == 3
        assert result[0]["genre"] == "Rock"

    @pytest.mark.asyncio
    async def test_filters_by_genre(self) -> None:
        from api.queries.insights_neo4j_queries import query_genre_trends

        driver = _make_mock_driver([{"genre": "Jazz", "decade": 1960, "release_count": 30000}])
        result = await query_genre_trends(driver, genre="Jazz")
        assert len(result) == 1
        assert result[0]["genre"] == "Jazz"


class TestQueryLabelLongevity:
    @pytest.mark.asyncio
    async def test_returns_ranked_labels(self) -> None:
        from api.queries.insights_neo4j_queries import query_label_longevity

        records = [
            {
                "label_id": "l1",
                "label_name": "Blue Note",
                "first_year": 1939,
                "last_year": 2025,
                "years_active": 86,
                "total_releases": 4500,
                "peak_decade": 1960,
            },
        ]
        driver = _make_mock_driver(records)
        result = await query_label_longevity(driver, limit=50)
        assert len(result) == 1
        assert result[0]["years_active"] == 86


class TestQueryAnniversaries:
    @pytest.mark.asyncio
    async def test_returns_anniversary_releases(self) -> None:
        from api.queries.insights_neo4j_queries import query_monthly_anniversaries

        records = [
            {"master_id": "m1", "title": "OK Computer", "artist_name": "Radiohead", "release_year": 1997},
        ]
        driver = _make_mock_driver(records)
        result = await query_monthly_anniversaries(driver, current_year=2022, current_month=6)
        assert len(result) == 1
        assert result[0]["master_id"] == "m1"

    @pytest.mark.asyncio
    async def test_custom_milestones(self) -> None:
        from api.queries.insights_neo4j_queries import query_monthly_anniversaries

        driver = _make_mock_driver([])
        await query_monthly_anniversaries(driver, current_year=2025, current_month=1, milestone_years=[10, 20])
        # Verify target_years were calculated correctly
        call_args = driver.session.return_value.__aenter__.return_value.run.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
        assert params.get("target_years") == [2015, 2005]
