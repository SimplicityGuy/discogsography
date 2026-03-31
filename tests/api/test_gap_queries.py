"""Tests for api/queries/gap_queries.py."""

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

    async def consume(self) -> MagicMock:
        return MagicMock()


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
    return _make_driver_with_results([_MockResult(records=records, single=single)] * 10)


# ---------------------------------------------------------------------------
# get_label_gaps
# ---------------------------------------------------------------------------


class TestGetLabelGaps:
    @pytest.mark.asyncio
    async def test_returns_results_and_total(self) -> None:
        from api.queries.gap_queries import get_label_gaps

        releases = [{"id": "r1", "title": "Blue Monday", "year": 1983, "artist": "New Order", "genres": ["Electronic"], "on_wantlist": False}]
        driver = _make_driver_with_results(
            [
                _MockResult(records=releases),
                _MockResult(single={"total": 1}),
            ]
        )
        results, total = await get_label_gaps(driver, "user-1", "label-1", limit=50, offset=0)
        assert results == releases
        assert total == 1

    @pytest.mark.asyncio
    async def test_empty_gaps(self) -> None:
        from api.queries.gap_queries import get_label_gaps

        driver = _make_driver_with_results(
            [
                _MockResult(records=[]),
                _MockResult(single={"total": 0}),
            ]
        )
        results, total = await get_label_gaps(driver, "user-1", "label-1")
        assert results == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_exclude_wantlist(self) -> None:
        from api.queries.gap_queries import get_label_gaps

        driver = _make_driver_with_results(
            [
                _MockResult(records=[]),
                _MockResult(single={"total": 0}),
            ]
        )
        results, total = await get_label_gaps(driver, "user-1", "label-1", exclude_wantlist=True)
        assert results == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_format_filter(self) -> None:
        from api.queries.gap_queries import get_label_gaps

        releases = [
            {
                "id": "r1",
                "title": "Blue Monday",
                "year": 1983,
                "formats": ["Vinyl"],
                "artist": "New Order",
                "genres": ["Electronic"],
                "on_wantlist": False,
            }
        ]
        driver = _make_driver_with_results(
            [
                _MockResult(records=releases),
                _MockResult(single={"total": 1}),
            ]
        )
        results, total = await get_label_gaps(driver, "user-1", "label-1", formats=["Vinyl"])
        assert results == releases
        assert total == 1


# ---------------------------------------------------------------------------
# get_label_gap_summary
# ---------------------------------------------------------------------------


class TestGetLabelGapSummary:
    @pytest.mark.asyncio
    async def test_returns_summary(self) -> None:
        from api.queries.gap_queries import get_label_gap_summary

        driver = _simple_driver(records=[{"total": 100, "owned": 25, "missing": 75}])
        result = await get_label_gap_summary(driver, "user-1", "label-1")
        assert result == {"total": 100, "owned": 25, "missing": 75}

    @pytest.mark.asyncio
    async def test_empty_summary(self) -> None:
        from api.queries.gap_queries import get_label_gap_summary

        driver = _simple_driver(records=[])
        result = await get_label_gap_summary(driver, "user-1", "label-1")
        assert result == {"total": 0, "owned": 0, "missing": 0}


# ---------------------------------------------------------------------------
# get_label_metadata
# ---------------------------------------------------------------------------


class TestGetLabelMetadata:
    @pytest.mark.asyncio
    async def test_returns_metadata(self) -> None:
        from api.queries.gap_queries import get_label_metadata

        driver = _simple_driver(records=[{"id": "label-1", "name": "Factory Records"}])
        result = await get_label_metadata(driver, "label-1")
        assert result == {"id": "label-1", "name": "Factory Records"}

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self) -> None:
        from api.queries.gap_queries import get_label_metadata

        driver = _simple_driver(records=[])
        result = await get_label_metadata(driver, "nonexistent")
        assert result is None


# ---------------------------------------------------------------------------
# get_artist_gaps
# ---------------------------------------------------------------------------


class TestGetArtistGaps:
    @pytest.mark.asyncio
    async def test_returns_results_and_total(self) -> None:
        from api.queries.gap_queries import get_artist_gaps

        releases = [{"id": "r2", "title": "Kid A", "year": 2000, "label": "Parlophone", "genres": ["Rock"], "on_wantlist": True}]
        driver = _make_driver_with_results(
            [
                _MockResult(records=releases),
                _MockResult(single={"total": 5}),
            ]
        )
        results, total = await get_artist_gaps(driver, "user-1", "artist-1", limit=50, offset=0)
        assert results == releases
        assert total == 5

    @pytest.mark.asyncio
    async def test_empty_gaps(self) -> None:
        from api.queries.gap_queries import get_artist_gaps

        driver = _make_driver_with_results(
            [
                _MockResult(records=[]),
                _MockResult(single={"total": 0}),
            ]
        )
        results, total = await get_artist_gaps(driver, "user-1", "artist-1")
        assert results == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_format_filter(self) -> None:
        from api.queries.gap_queries import get_artist_gaps

        releases = [{"id": "r2", "title": "Kid A", "year": 2000, "formats": ["CD"]}]
        driver = _make_driver_with_results(
            [
                _MockResult(records=releases),
                _MockResult(single={"total": 1}),
            ]
        )
        results, total = await get_artist_gaps(driver, "user-1", "artist-1", formats=["CD"])
        assert results == releases
        assert total == 1


# ---------------------------------------------------------------------------
# get_artist_gap_summary / get_artist_metadata
# ---------------------------------------------------------------------------


class TestGetArtistGapSummary:
    @pytest.mark.asyncio
    async def test_returns_summary(self) -> None:
        from api.queries.gap_queries import get_artist_gap_summary

        driver = _simple_driver(records=[{"total": 50, "owned": 10, "missing": 40}])
        result = await get_artist_gap_summary(driver, "user-1", "artist-1")
        assert result == {"total": 50, "owned": 10, "missing": 40}

    @pytest.mark.asyncio
    async def test_empty_summary(self) -> None:
        from api.queries.gap_queries import get_artist_gap_summary

        driver = _simple_driver(records=[])
        result = await get_artist_gap_summary(driver, "user-1", "artist-1")
        assert result == {"total": 0, "owned": 0, "missing": 0}


class TestGetArtistMetadata:
    @pytest.mark.asyncio
    async def test_returns_metadata(self) -> None:
        from api.queries.gap_queries import get_artist_metadata

        driver = _simple_driver(records=[{"id": "artist-1", "name": "Radiohead"}])
        result = await get_artist_metadata(driver, "artist-1")
        assert result == {"id": "artist-1", "name": "Radiohead"}

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self) -> None:
        from api.queries.gap_queries import get_artist_metadata

        driver = _simple_driver(records=[])
        result = await get_artist_metadata(driver, "nonexistent")
        assert result is None


# ---------------------------------------------------------------------------
# get_master_gaps
# ---------------------------------------------------------------------------


class TestGetMasterGaps:
    @pytest.mark.asyncio
    async def test_returns_results_and_total(self) -> None:
        from api.queries.gap_queries import get_master_gaps

        releases = [
            {
                "id": "r3",
                "title": "OK Computer (UK)",
                "year": 1997,
                "artist": "Radiohead",
                "label": "Parlophone",
                "genres": ["Rock"],
                "on_wantlist": False,
            }
        ]
        driver = _make_driver_with_results(
            [
                _MockResult(records=releases),
                _MockResult(single={"total": 3}),
            ]
        )
        results, total = await get_master_gaps(driver, "user-1", "master-1", limit=50, offset=0)
        assert results == releases
        assert total == 3

    @pytest.mark.asyncio
    async def test_empty_gaps(self) -> None:
        from api.queries.gap_queries import get_master_gaps

        driver = _make_driver_with_results(
            [
                _MockResult(records=[]),
                _MockResult(single={"total": 0}),
            ]
        )
        results, total = await get_master_gaps(driver, "user-1", "master-1")
        assert results == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_format_filter(self) -> None:
        from api.queries.gap_queries import get_master_gaps

        releases = [{"id": "r3", "title": "OK Computer (JP)", "year": 1997, "formats": ["Vinyl"]}]
        driver = _make_driver_with_results(
            [
                _MockResult(records=releases),
                _MockResult(single={"total": 1}),
            ]
        )
        results, total = await get_master_gaps(driver, "user-1", "master-1", formats=["Vinyl"])
        assert results == releases
        assert total == 1


# ---------------------------------------------------------------------------
# get_master_gap_summary / get_master_metadata
# ---------------------------------------------------------------------------


class TestGetMasterGapSummary:
    @pytest.mark.asyncio
    async def test_returns_summary(self) -> None:
        from api.queries.gap_queries import get_master_gap_summary

        driver = _simple_driver(records=[{"total": 20, "owned": 1, "missing": 19}])
        result = await get_master_gap_summary(driver, "user-1", "master-1")
        assert result == {"total": 20, "owned": 1, "missing": 19}

    @pytest.mark.asyncio
    async def test_empty_summary(self) -> None:
        from api.queries.gap_queries import get_master_gap_summary

        driver = _simple_driver(records=[])
        result = await get_master_gap_summary(driver, "user-1", "master-1")
        assert result == {"total": 0, "owned": 0, "missing": 0}


class TestGetMasterMetadata:
    @pytest.mark.asyncio
    async def test_returns_metadata(self) -> None:
        from api.queries.gap_queries import get_master_metadata

        driver = _simple_driver(records=[{"id": "master-1", "name": "OK Computer"}])
        result = await get_master_metadata(driver, "master-1")
        assert result == {"id": "master-1", "name": "OK Computer"}

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self) -> None:
        from api.queries.gap_queries import get_master_metadata

        driver = _simple_driver(records=[])
        result = await get_master_metadata(driver, "nonexistent")
        assert result is None
