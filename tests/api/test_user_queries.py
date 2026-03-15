"""Tests for api/queries/user_queries.py."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers (mirrors pattern from test_neo4j_queries.py)
# ---------------------------------------------------------------------------


class _AsyncIter:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self._records = records
        self._index = 0

    def __aiter__(self) -> "_AsyncIter":
        return self

    async def __anext__(self) -> dict[str, Any]:
        if self._index >= len(self._records):
            raise StopAsyncIteration
        record = self._records[self._index]
        self._index += 1
        return record


class _MockResult:
    def __init__(
        self,
        records: list[dict[str, Any]] | None = None,
        single: dict[str, Any] | None = None,
    ) -> None:
        self._records = records or []
        self._single = single

    def __aiter__(self) -> _AsyncIter:
        return _AsyncIter(self._records)

    async def single(self) -> dict[str, Any] | None:
        return self._single


def _make_driver_with_results(results: list[_MockResult]) -> MagicMock:
    """Build a driver whose session().run() returns a different result on each call."""
    results_iter = iter(results)

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    async def _run_side(*_a: Any, **_kw: Any) -> _MockResult:
        return next(results_iter)

    mock_session.run = AsyncMock(side_effect=_run_side)

    driver = MagicMock()

    async def _session_factory(*_a: Any, **_kw: Any) -> Any:
        return mock_session

    driver.session = MagicMock(side_effect=_session_factory)
    return driver


def _simple_driver(records: list[dict[str, Any]] | None = None, single: dict[str, Any] | None = None) -> MagicMock:
    """Driver that always returns the same result."""
    return _make_driver_with_results([_MockResult(records=records, single=single)] * 10)


# ---------------------------------------------------------------------------
# _run_query helper
# ---------------------------------------------------------------------------


class TestRunQuery:
    @pytest.mark.asyncio
    async def test_returns_list_of_dicts(self) -> None:
        from api.queries.user_queries import _run_query

        records = [{"id": "1", "name": "OK Computer"}]
        driver = _simple_driver(records=records)
        result = await _run_query(driver, "MATCH (r:Release) RETURN r.id AS id, r.title AS name")
        assert result == records

    @pytest.mark.asyncio
    async def test_returns_empty_list(self) -> None:
        from api.queries.user_queries import _run_query

        driver = _simple_driver(records=[])
        result = await _run_query(driver, "MATCH (r:Release) RETURN r.id AS id")
        assert result == []


# ---------------------------------------------------------------------------
# _run_count helper
# ---------------------------------------------------------------------------


class TestRunCount:
    @pytest.mark.asyncio
    async def test_returns_count(self) -> None:
        from api.queries.user_queries import _run_count

        driver = _simple_driver(single={"total": 7})
        result = await _run_count(driver, "RETURN count(*) AS total")
        assert result == 7

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_record(self) -> None:
        from api.queries.user_queries import _run_count

        driver = _simple_driver(single=None)
        result = await _run_count(driver, "RETURN count(*) AS total")
        assert result == 0


# ---------------------------------------------------------------------------
# get_user_collection
# ---------------------------------------------------------------------------


class TestGetUserCollection:
    @pytest.mark.asyncio
    async def test_returns_results_and_total(self) -> None:
        from api.queries.user_queries import get_user_collection

        releases = [
            {
                "id": "r1",
                "title": "OK Computer",
                "year": 1997,
                "artist": "Radiohead",
                "label": "Parlophone",
                "rating": 5,
                "date_added": "2023-01-01",
                "folder_id": 1,
            }
        ]
        driver = _make_driver_with_results(
            [
                _MockResult(records=releases),  # query results
                _MockResult(single={"total": 1}),  # count query
            ]
        )
        results, total = await get_user_collection(driver, "user-1", limit=50, offset=0)
        assert results == releases
        assert total == 1

    @pytest.mark.asyncio
    async def test_empty_collection(self) -> None:
        from api.queries.user_queries import get_user_collection

        driver = _make_driver_with_results(
            [
                _MockResult(records=[]),
                _MockResult(single={"total": 0}),
            ]
        )
        results, total = await get_user_collection(driver, "user-1")
        assert results == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_pagination_offset(self) -> None:
        from api.queries.user_queries import get_user_collection

        releases = [
            {
                "id": "r5",
                "title": "Kid A",
                "year": 2000,
                "artist": "Radiohead",
                "label": "Parlophone",
                "rating": 4,
                "date_added": "2023-01-05",
                "folder_id": 1,
            }
        ]
        driver = _make_driver_with_results(
            [
                _MockResult(records=releases),
                _MockResult(single={"total": 10}),
            ]
        )
        results, total = await get_user_collection(driver, "user-1", limit=1, offset=4)
        assert len(results) == 1
        assert total == 10


# ---------------------------------------------------------------------------
# get_user_wantlist
# ---------------------------------------------------------------------------


class TestGetUserWantlist:
    @pytest.mark.asyncio
    async def test_returns_results_and_total(self) -> None:
        from api.queries.user_queries import get_user_wantlist

        wants = [{"id": "r2", "title": "Kid A", "year": 2000, "artist": "Radiohead", "label": "Parlophone", "rating": 0, "date_added": "2023-02-01"}]
        driver = _make_driver_with_results(
            [
                _MockResult(records=wants),
                _MockResult(single={"total": 1}),
            ]
        )
        results, total = await get_user_wantlist(driver, "user-2", limit=50, offset=0)
        assert results == wants
        assert total == 1

    @pytest.mark.asyncio
    async def test_empty_wantlist(self) -> None:
        from api.queries.user_queries import get_user_wantlist

        driver = _make_driver_with_results(
            [
                _MockResult(records=[]),
                _MockResult(single={"total": 0}),
            ]
        )
        results, total = await get_user_wantlist(driver, "user-2")
        assert results == []
        assert total == 0


# ---------------------------------------------------------------------------
# get_user_recommendations
# ---------------------------------------------------------------------------


class TestGetUserRecommendations:
    @pytest.mark.asyncio
    async def test_returns_recommendations(self) -> None:
        from api.queries.user_queries import get_user_recommendations

        recs = [
            {"id": "r10", "title": "In Rainbows", "year": 2007, "artist": "Radiohead", "label": "XL", "genres": ["Rock"], "score": 10},
            {"id": "r11", "title": "Amnesiac", "year": 2001, "artist": "Radiohead", "label": "Parlophone", "genres": ["Rock"], "score": 8},
        ]
        driver = _simple_driver(records=recs)
        result = await get_user_recommendations(driver, "user-1", limit=20)
        assert result == recs

    @pytest.mark.asyncio
    async def test_empty_recommendations(self) -> None:
        from api.queries.user_queries import get_user_recommendations

        driver = _simple_driver(records=[])
        result = await get_user_recommendations(driver, "user-1")
        assert result == []


# ---------------------------------------------------------------------------
# get_user_collection_stats
# ---------------------------------------------------------------------------


class TestGetUserCollectionStats:
    @pytest.mark.asyncio
    async def test_returns_stats_structure(self) -> None:
        from api.queries.user_queries import get_user_collection_stats

        genre_records = [{"name": "Rock", "count": 50}, {"name": "Electronic", "count": 20}]
        decade_records = [{"decade": 1990, "count": 30}, {"decade": 2000, "count": 40}]
        label_records = [{"name": "Warp", "count": 15}]

        driver = _make_driver_with_results(
            [
                _MockResult(records=genre_records),  # genre query
                _MockResult(records=decade_records),  # decade query
                _MockResult(records=label_records),  # label query
                _MockResult(single={"total": 70}),  # total count
                _MockResult(single={"total": 25}),  # unique artists count
                _MockResult(single={"total": 8}),  # unique labels count
                _MockResult(records=[{"average": 3.5}]),  # avg rating
            ]
        )
        result = await get_user_collection_stats(driver, "user-1")

        assert result["total"] == 70
        assert result["unique_artists"] == 25
        assert result["unique_labels"] == 8
        assert result["average_rating"] == 3.5
        assert result["by_genre"] == [{"name": "Rock", "count": 50}, {"name": "Electronic", "count": 20}]
        assert result["by_decade"] == [{"decade": 1990, "count": 30}, {"decade": 2000, "count": 40}]
        assert result["by_label"] == [{"name": "Warp", "count": 15}]

    @pytest.mark.asyncio
    async def test_empty_collection_stats(self) -> None:
        from api.queries.user_queries import get_user_collection_stats

        driver = _make_driver_with_results(
            [
                _MockResult(records=[]),
                _MockResult(records=[]),
                _MockResult(records=[]),
                _MockResult(single={"total": 0}),
                _MockResult(single={"total": 0}),
                _MockResult(single={"total": 0}),
                _MockResult(records=[{"average": None}]),
            ]
        )
        result = await get_user_collection_stats(driver, "user-empty")
        assert result["total"] == 0
        assert result["unique_artists"] == 0
        assert result["unique_labels"] == 0
        assert result["average_rating"] is None
        assert result["by_genre"] == []
        assert result["by_decade"] == []
        assert result["by_label"] == []


# ---------------------------------------------------------------------------
# get_user_collection_timeline
# ---------------------------------------------------------------------------


class TestGetUserCollectionTimeline:
    @pytest.mark.asyncio
    async def test_returns_timeline_with_insights(self) -> None:
        from api.queries.user_queries import get_user_collection_timeline

        rows = [
            {"year": 1985, "count": 3, "genres": ["Electronic", "Rock"], "styles": ["Synth-pop"], "labels": ["Factory Records", "4AD"]},
            {"year": 1990, "count": 5, "genres": ["Rock", "Rock", "Jazz"], "styles": ["Post-Punk", "Shoegaze"], "labels": ["4AD"]},
        ]
        driver = _simple_driver(records=rows)
        result = await get_user_collection_timeline(driver, "user-1", bucket="year")

        assert len(result["timeline"]) == 2
        assert result["timeline"][0]["year"] == 1985
        assert result["timeline"][0]["count"] == 3
        assert result["timeline"][1]["year"] == 1990
        assert result["timeline"][1]["count"] == 5

        insights = result["insights"]
        assert insights["peak_year"] == 1990
        assert insights["dominant_genre"] is not None
        assert 0 <= insights["genre_diversity_score"] <= 1
        assert 0 <= insights["style_drift_rate"] <= 1

    @pytest.mark.asyncio
    async def test_empty_collection_timeline(self) -> None:
        from api.queries.user_queries import get_user_collection_timeline

        driver = _simple_driver(records=[])
        result = await get_user_collection_timeline(driver, "user-empty")

        assert result["timeline"] == []
        assert result["insights"]["peak_year"] is None
        assert result["insights"]["dominant_genre"] is None
        assert result["insights"]["genre_diversity_score"] == 0.0
        assert result["insights"]["style_drift_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_single_genre_has_zero_diversity(self) -> None:
        from api.queries.user_queries import get_user_collection_timeline

        rows = [
            {"year": 2000, "count": 10, "genres": ["Electronic"], "styles": ["Ambient"], "labels": ["Warp"]},
        ]
        driver = _simple_driver(records=rows)
        result = await get_user_collection_timeline(driver, "user-1")

        # Single genre = zero entropy (normalized)
        assert result["insights"]["genre_diversity_score"] == 0.0
        assert result["insights"]["dominant_genre"] == "Electronic"

    @pytest.mark.asyncio
    async def test_decade_bucket(self) -> None:
        from api.queries.user_queries import get_user_collection_timeline

        rows = [
            {"year": 1980, "count": 8, "genres": ["Rock"], "styles": ["New Wave"], "labels": ["Island"]},
        ]
        driver = _simple_driver(records=rows)
        result = await get_user_collection_timeline(driver, "user-1", bucket="decade")

        assert result["timeline"][0]["year"] == 1980


# ---------------------------------------------------------------------------
# get_user_collection_evolution
# ---------------------------------------------------------------------------


class TestGetUserCollectionEvolution:
    @pytest.mark.asyncio
    async def test_returns_genre_evolution(self) -> None:
        from api.queries.user_queries import get_user_collection_evolution

        rows = [
            {"year": 1985, "value": "Electronic", "count": 5},
            {"year": 1985, "value": "Rock", "count": 3},
            {"year": 1990, "value": "Jazz", "count": 7},
        ]
        driver = _simple_driver(records=rows)
        result = await get_user_collection_evolution(driver, "user-1", metric="genre")

        assert result["metric"] == "genre"
        assert len(result["data"]) == 2
        assert result["data"][0]["year"] == 1985
        assert result["data"][0]["values"] == {"Electronic": 5, "Rock": 3}
        assert result["data"][1]["year"] == 1990
        assert result["data"][1]["values"] == {"Jazz": 7}
        assert result["summary"]["total_years"] == 2
        assert result["summary"]["unique_values"] == 3

    @pytest.mark.asyncio
    async def test_empty_evolution(self) -> None:
        from api.queries.user_queries import get_user_collection_evolution

        driver = _simple_driver(records=[])
        result = await get_user_collection_evolution(driver, "user-empty")

        assert result["metric"] == "genre"
        assert result["data"] == []
        assert result["summary"]["total_years"] == 0
        assert result["summary"]["unique_values"] == 0

    @pytest.mark.asyncio
    async def test_style_metric(self) -> None:
        from api.queries.user_queries import get_user_collection_evolution

        rows = [{"year": 2000, "value": "Ambient", "count": 4}]
        driver = _simple_driver(records=rows)
        result = await get_user_collection_evolution(driver, "user-1", metric="style")

        assert result["metric"] == "style"
        assert result["data"][0]["values"] == {"Ambient": 4}

    @pytest.mark.asyncio
    async def test_label_metric(self) -> None:
        from api.queries.user_queries import get_user_collection_evolution

        rows = [{"year": 1995, "value": "Warp Records", "count": 6}]
        driver = _simple_driver(records=rows)
        result = await get_user_collection_evolution(driver, "user-1", metric="label")

        assert result["metric"] == "label"
        assert result["data"][0]["values"] == {"Warp Records": 6}


# ---------------------------------------------------------------------------
# check_releases_user_status
# ---------------------------------------------------------------------------


class TestCheckReleasesUserStatus:
    @pytest.mark.asyncio
    async def test_returns_empty_dict_for_no_ids(self) -> None:
        from api.queries.user_queries import check_releases_user_status

        driver = _simple_driver()
        result = await check_releases_user_status(driver, "user-1", [])
        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_status_for_ids(self) -> None:
        from api.queries.user_queries import check_releases_user_status

        rows = [
            {"release_id": "r1", "in_collection": True, "in_wantlist": False},
            {"release_id": "r2", "in_collection": False, "in_wantlist": True},
        ]
        driver = _simple_driver(records=rows)
        result = await check_releases_user_status(driver, "user-1", ["r1", "r2"])

        assert result["r1"] == {"in_collection": True, "in_wantlist": False}
        assert result["r2"] == {"in_collection": False, "in_wantlist": True}

    @pytest.mark.asyncio
    async def test_handles_single_id(self) -> None:
        from api.queries.user_queries import check_releases_user_status

        rows = [{"release_id": "r5", "in_collection": True, "in_wantlist": True}]
        driver = _simple_driver(records=rows)
        result = await check_releases_user_status(driver, "user-1", ["r5"])

        assert result["r5"]["in_collection"] is True
        assert result["r5"]["in_wantlist"] is True
