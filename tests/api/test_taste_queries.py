"""Tests for api/queries/taste_queries.py."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers (same pattern as test_user_queries.py)
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

    driver.session = MagicMock(return_value=mock_session)
    return driver


def _simple_driver(records: list[dict[str, Any]] | None = None, single: dict[str, Any] | None = None) -> MagicMock:
    """Driver that always returns the same result."""
    return _make_driver_with_results([_MockResult(records=records, single=single)] * 10)


# ---------------------------------------------------------------------------
# get_collection_count
# ---------------------------------------------------------------------------


class TestGetCollectionCount:
    @pytest.mark.asyncio
    async def test_returns_count(self) -> None:
        from api.queries.taste_queries import get_collection_count

        driver = _simple_driver(single={"total": 42})
        result = await get_collection_count(driver, "user-1")
        assert result == 42

    @pytest.mark.asyncio
    async def test_returns_zero_when_empty(self) -> None:
        from api.queries.taste_queries import get_collection_count

        driver = _simple_driver(single={"total": 0})
        result = await get_collection_count(driver, "user-1")
        assert result == 0

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_record(self) -> None:
        from api.queries.taste_queries import get_collection_count

        driver = _simple_driver(single=None)
        result = await get_collection_count(driver, "user-1")
        assert result == 0


# ---------------------------------------------------------------------------
# get_taste_heatmap
# ---------------------------------------------------------------------------


class TestGetTasteHeatmap:
    @pytest.mark.asyncio
    async def test_returns_cells_and_total(self) -> None:
        from api.queries.taste_queries import get_taste_heatmap

        cells = [
            {"genre": "Rock", "decade": 1990, "count": 15},
            {"genre": "Electronic", "decade": 2000, "count": 10},
        ]
        driver = _make_driver_with_results(
            [
                _MockResult(records=cells),
                _MockResult(single={"total": 25}),
            ]
        )
        result_cells, total = await get_taste_heatmap(driver, "user-1")
        assert result_cells == cells
        assert total == 25

    @pytest.mark.asyncio
    async def test_empty_collection(self) -> None:
        from api.queries.taste_queries import get_taste_heatmap

        driver = _make_driver_with_results(
            [
                _MockResult(records=[]),
                _MockResult(single={"total": 0}),
            ]
        )
        result_cells, total = await get_taste_heatmap(driver, "user-1")
        assert result_cells == []
        assert total == 0


# ---------------------------------------------------------------------------
# get_obscurity_score
# ---------------------------------------------------------------------------


class TestGetObscurityScore:
    @pytest.mark.asyncio
    async def test_no_releases_returns_max_obscurity(self) -> None:
        from api.queries.taste_queries import get_obscurity_score

        driver = _make_driver_with_results(
            [
                _MockResult(records=[]),
                _MockResult(single={"total": 0}),
            ]
        )
        result = await get_obscurity_score(driver, "user-1")
        assert result["score"] == 1.0
        assert result["median_collectors"] == 0.0
        assert result["total_releases"] == 0

    @pytest.mark.asyncio
    async def test_zero_collectors_returns_max_obscurity(self) -> None:
        from api.queries.taste_queries import get_obscurity_score

        driver = _make_driver_with_results(
            [
                _MockResult(records=[{"collectors": 0}, {"collectors": 0}, {"collectors": 0}]),
                _MockResult(single={"total": 3}),
            ]
        )
        result = await get_obscurity_score(driver, "user-1")
        assert result["score"] == 1.0
        assert result["total_releases"] == 3

    @pytest.mark.asyncio
    async def test_some_collectors(self) -> None:
        from api.queries.taste_queries import get_obscurity_score

        # Sorted: [1, 2, 5] -> median = 2, max = 5
        # score = 1 - (2/5) = 0.6
        driver = _make_driver_with_results(
            [
                _MockResult(records=[{"collectors": 1}, {"collectors": 2}, {"collectors": 5}]),
                _MockResult(single={"total": 3}),
            ]
        )
        result = await get_obscurity_score(driver, "user-1")
        assert result["score"] == 0.6
        assert result["median_collectors"] == 2.0
        assert result["total_releases"] == 3

    @pytest.mark.asyncio
    async def test_even_number_of_releases(self) -> None:
        from api.queries.taste_queries import get_obscurity_score

        # Sorted: [0, 2, 4, 10] -> median = (2+4)/2 = 3.0, max = 10
        # score = 1 - (3/10) = 0.7
        driver = _make_driver_with_results(
            [
                _MockResult(
                    records=[
                        {"collectors": 0},
                        {"collectors": 2},
                        {"collectors": 4},
                        {"collectors": 10},
                    ]
                ),
                _MockResult(single={"total": 4}),
            ]
        )
        result = await get_obscurity_score(driver, "user-1")
        assert result["score"] == 0.7
        assert result["median_collectors"] == 3.0


# ---------------------------------------------------------------------------
# get_taste_drift
# ---------------------------------------------------------------------------


class TestGetTasteDrift:
    @pytest.mark.asyncio
    async def test_returns_drift_timeline(self) -> None:
        from api.queries.taste_queries import get_taste_drift

        rows = [
            {"year": "2020", "top_genre": "Rock", "count": 10},
            {"year": "2021", "top_genre": "Electronic", "count": 8},
        ]
        driver = _simple_driver(records=rows)
        result = await get_taste_drift(driver, "user-1")
        assert result == rows

    @pytest.mark.asyncio
    async def test_empty_drift(self) -> None:
        from api.queries.taste_queries import get_taste_drift

        driver = _simple_driver(records=[])
        result = await get_taste_drift(driver, "user-1")
        assert result == []


# ---------------------------------------------------------------------------
# get_blind_spots
# ---------------------------------------------------------------------------


class TestGetBlindSpots:
    @pytest.mark.asyncio
    async def test_returns_blind_spots(self) -> None:
        from api.queries.taste_queries import get_blind_spots

        rows = [
            {"genre": "Jazz", "artist_overlap": 3, "example_release": "Kind of Blue"},
            {"genre": "Classical", "artist_overlap": 2, "example_release": None},
        ]
        driver = _simple_driver(records=rows)
        result = await get_blind_spots(driver, "user-1", limit=5)
        assert result == rows

    @pytest.mark.asyncio
    async def test_empty_blind_spots(self) -> None:
        from api.queries.taste_queries import get_blind_spots

        driver = _simple_driver(records=[])
        result = await get_blind_spots(driver, "user-1")
        assert result == []


# ---------------------------------------------------------------------------
# get_top_labels
# ---------------------------------------------------------------------------


class TestGetTopLabels:
    @pytest.mark.asyncio
    async def test_returns_top_labels(self) -> None:
        from api.queries.taste_queries import get_top_labels

        rows = [
            {"label": "Warp Records", "count": 15},
            {"label": "4AD", "count": 10},
            {"label": "Merge", "count": 5},
        ]
        driver = _simple_driver(records=rows)
        result = await get_top_labels(driver, "user-1", limit=10)
        assert result == rows

    @pytest.mark.asyncio
    async def test_empty_labels(self) -> None:
        from api.queries.taste_queries import get_top_labels

        driver = _simple_driver(records=[])
        result = await get_top_labels(driver, "user-1")
        assert result == []

    @pytest.mark.asyncio
    async def test_custom_limit(self) -> None:
        from api.queries.taste_queries import get_top_labels

        rows = [{"label": "Warp Records", "count": 15}]
        driver = _simple_driver(records=rows)
        result = await get_top_labels(driver, "user-1", limit=1)
        assert len(result) == 1
