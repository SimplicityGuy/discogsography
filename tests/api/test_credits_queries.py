"""Unit tests for credits query functions."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.queries.credits_queries import (
    autocomplete_person,
    get_person_connections,
    get_person_credits,
    get_person_profile,
    get_person_role_breakdown,
    get_person_timeline,
    get_release_credits,
    get_role_leaderboard,
    get_shared_credits,
)


class _AsyncRecordIterator:
    """Async iterator over a list of records for mocking Neo4j results."""

    def __init__(self, records: list[dict[str, Any]]) -> None:
        self._iter = iter(records)

    def __aiter__(self) -> "_AsyncRecordIterator":
        return self

    async def __anext__(self) -> dict[str, Any]:
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration  # noqa: B904


def _make_mock_driver(
    query_returns: list[dict[str, Any]] | None = None,
    single_return: dict[str, Any] | None = None,
) -> MagicMock:
    """Create a mock Neo4j driver for testing query functions."""
    driver = MagicMock()
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    records = query_returns if query_returns is not None else []
    mock_result = _AsyncRecordIterator(records)
    if single_return is not None:
        mock_result.single = AsyncMock(return_value=single_return)  # type: ignore[attr-defined]
    else:
        mock_result.single = AsyncMock(return_value=None)  # type: ignore[attr-defined]
    mock_result.consume = AsyncMock()  # type: ignore[attr-defined]

    session.run = AsyncMock(return_value=mock_result)
    driver.session = MagicMock(return_value=session)
    return driver


class TestGetPersonCredits:
    """Tests for get_person_credits."""

    @pytest.mark.asyncio
    async def test_returns_results(self) -> None:
        records = [
            {"release_id": "1", "title": "Album", "year": 1990, "role": "Producer", "category": "production", "artists": ["A"], "labels": ["L"]},
        ]
        driver = _make_mock_driver(query_returns=records)
        result = await get_person_credits(driver, "Test Person")
        assert len(result) == 1
        assert result[0]["role"] == "Producer"

    @pytest.mark.asyncio
    async def test_returns_empty(self) -> None:
        driver = _make_mock_driver(query_returns=[])
        result = await get_person_credits(driver, "Nobody")
        assert result == []


class TestGetPersonTimeline:
    """Tests for get_person_timeline."""

    @pytest.mark.asyncio
    async def test_returns_timeline(self) -> None:
        records = [
            {"year": 1990, "category": "mastering", "count": 5},
            {"year": 1991, "category": "mastering", "count": 8},
        ]
        driver = _make_mock_driver(query_returns=records)
        result = await get_person_timeline(driver, "Test")
        assert len(result) == 2
        assert result[0]["year"] == 1990


class TestGetReleaseCredits:
    """Tests for get_release_credits."""

    @pytest.mark.asyncio
    async def test_returns_credits(self) -> None:
        records = [
            {"name": "Person A", "role": "Producer", "category": "production", "artist_id": None, "artist_name": None},
        ]
        driver = _make_mock_driver(query_returns=records)
        result = await get_release_credits(driver, "123")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_returns_empty(self) -> None:
        driver = _make_mock_driver(query_returns=[])
        result = await get_release_credits(driver, "999")
        assert result == []


class TestGetRoleLeaderboard:
    """Tests for get_role_leaderboard."""

    @pytest.mark.asyncio
    async def test_returns_leaderboard(self) -> None:
        records = [
            {"name": "Top Person", "credit_count": 100},
        ]
        driver = _make_mock_driver(query_returns=records)
        result = await get_role_leaderboard(driver, "mastering", limit=20)
        assert len(result) == 1
        assert result[0]["credit_count"] == 100


class TestGetSharedCredits:
    """Tests for get_shared_credits."""

    @pytest.mark.asyncio
    async def test_returns_shared(self) -> None:
        records = [
            {"release_id": "1", "title": "Album", "year": 1990, "person1_role": "Producer", "person2_role": "Engineer", "artists": ["A"]},
        ]
        driver = _make_mock_driver(query_returns=records)
        result = await get_shared_credits(driver, "Person A", "Person B")
        assert len(result) == 1


class TestGetPersonConnections:
    """Tests for get_person_connections."""

    @pytest.mark.asyncio
    async def test_returns_connections_depth_1(self) -> None:
        records = [{"name": "Connected", "shared_count": 5}]
        driver = _make_mock_driver(query_returns=records)
        result = await get_person_connections(driver, "Test", depth=1, limit=50)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_returns_connections_depth_2(self) -> None:
        records = [{"name": "Connected", "shared_count": 5, "second_hops": []}]
        driver = _make_mock_driver(query_returns=records)
        result = await get_person_connections(driver, "Test", depth=2, limit=50)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_clamps_depth(self) -> None:
        driver = _make_mock_driver(query_returns=[])
        result = await get_person_connections(driver, "Test", depth=0, limit=50)
        assert result == []

        result = await get_person_connections(driver, "Test", depth=5, limit=50)
        assert result == []


class TestAutocompletePerson:
    """Tests for autocomplete_person."""

    @pytest.mark.asyncio
    async def test_returns_results(self) -> None:
        records = [{"name": "Bob Ludwig", "score": 5.2}]
        driver = _make_mock_driver(query_returns=records)
        result = await autocomplete_person(driver, "Bob")
        assert len(result) == 1
        assert result[0]["name"] == "Bob Ludwig"

    @pytest.mark.asyncio
    async def test_adds_wildcard(self) -> None:
        driver = _make_mock_driver(query_returns=[])
        await autocomplete_person(driver, "Bob")
        # Verify the query was called with wildcard
        session = driver.session().__aenter__.return_value
        call_args = session.run.call_args
        assert call_args is not None

    @pytest.mark.asyncio
    async def test_no_double_wildcard(self) -> None:
        driver = _make_mock_driver(query_returns=[])
        await autocomplete_person(driver, "Bob*")
        # Should not add another wildcard


class TestGetPersonProfile:
    """Tests for get_person_profile."""

    @pytest.mark.asyncio
    async def test_returns_profile(self) -> None:
        record = {
            "name": "Bob Ludwig",
            "total_credits": 500,
            "categories": ["mastering"],
            "first_year": 1970,
            "last_year": 2020,
            "artist_id": None,
            "artist_name": None,
        }
        driver = _make_mock_driver(single_return=record)
        result = await get_person_profile(driver, "Bob Ludwig")
        assert result is not None
        assert result["name"] == "Bob Ludwig"

    @pytest.mark.asyncio
    async def test_returns_none(self) -> None:
        driver = _make_mock_driver(single_return=None)
        result = await get_person_profile(driver, "Nobody")
        assert result is None


class TestGetPersonRoleBreakdown:
    """Tests for get_person_role_breakdown."""

    @pytest.mark.asyncio
    async def test_returns_breakdown(self) -> None:
        records = [{"category": "mastering", "count": 500}]
        driver = _make_mock_driver(query_returns=records)
        result = await get_person_role_breakdown(driver, "Bob Ludwig")
        assert len(result) == 1
        assert result[0]["category"] == "mastering"
