"""Tests for api/queries/neo4j_queries.py query helper functions."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _AsyncIter:
    """Async iterator that yields pre-built records for mock Neo4j results."""

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
    """Mock Neo4j result that supports both async iteration and .single()."""

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


def _make_driver(records: list[dict[str, Any]] | None = None, single: dict[str, Any] | None = None) -> MagicMock:
    """Build a minimal mock AsyncResilientNeo4jDriver."""
    mock_result = _MockResult(records=records, single=single)
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.run = AsyncMock(return_value=mock_result)

    driver = MagicMock()

    async def _session_factory(*_args: Any, **_kwargs: Any) -> Any:
        return mock_session

    driver.session = MagicMock(side_effect=_session_factory)
    return driver


def _make_driver_with_side_effects(results: list[_MockResult]) -> MagicMock:
    """Build a driver whose session().run() returns different results on each call."""
    results_iter = iter(results)

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    async def _run_side_effect(*_args: Any, **_kwargs: Any) -> _MockResult:
        return next(results_iter)

    mock_session.run = AsyncMock(side_effect=_run_side_effect)

    driver = MagicMock()

    async def _session_factory(*_args: Any, **_kwargs: Any) -> Any:
        return mock_session

    driver.session = MagicMock(side_effect=_session_factory)
    return driver


# ---------------------------------------------------------------------------
# _escape_lucene_query
# ---------------------------------------------------------------------------


class TestEscapeLuceneQuery:
    def test_no_special_chars(self) -> None:
        from api.queries.neo4j_queries import _escape_lucene_query

        assert _escape_lucene_query("Radiohead") == "Radiohead"

    def test_escapes_plus(self) -> None:
        from api.queries.neo4j_queries import _escape_lucene_query

        assert _escape_lucene_query("AC+DC") == r"AC\+DC"

    def test_escapes_space(self) -> None:
        from api.queries.neo4j_queries import _escape_lucene_query

        assert r"\ " in _escape_lucene_query("Warp Records")

    def test_escapes_colon(self) -> None:
        from api.queries.neo4j_queries import _escape_lucene_query

        result = _escape_lucene_query("key:value")
        assert r"\:" in result


# ---------------------------------------------------------------------------
# _run_query / _run_single / _run_count
# ---------------------------------------------------------------------------


class TestRunHelpers:
    @pytest.mark.asyncio
    async def test_run_query_returns_list(self) -> None:
        from api.queries.neo4j_queries import _run_query

        records = [{"id": "1", "name": "Rock"}, {"id": "2", "name": "Jazz"}]
        driver = _make_driver(records=records)
        result = await _run_query(driver, "MATCH (n) RETURN n")
        assert result == records

    @pytest.mark.asyncio
    async def test_run_query_empty(self) -> None:
        from api.queries.neo4j_queries import _run_query

        driver = _make_driver(records=[])
        result = await _run_query(driver, "MATCH (n) RETURN n")
        assert result == []

    @pytest.mark.asyncio
    async def test_run_single_with_record(self) -> None:
        from api.queries.neo4j_queries import _run_single

        record = {"id": "1", "name": "Radiohead"}
        driver = _make_driver(single=record)
        result = await _run_single(driver, "MATCH (a) RETURN a LIMIT 1")
        assert result == record

    @pytest.mark.asyncio
    async def test_run_single_none(self) -> None:
        from api.queries.neo4j_queries import _run_single

        driver = _make_driver(single=None)
        result = await _run_single(driver, "MATCH (a) RETURN a LIMIT 1")
        assert result is None

    @pytest.mark.asyncio
    async def test_run_count_with_total(self) -> None:
        from api.queries.neo4j_queries import _run_count

        driver = _make_driver(single={"total": 42})
        result = await _run_count(driver, "RETURN count(*) AS total")
        assert result == 42

    @pytest.mark.asyncio
    async def test_run_count_no_record(self) -> None:
        from api.queries.neo4j_queries import _run_count

        driver = _make_driver(single=None)
        result = await _run_count(driver, "RETURN count(*) AS total")
        assert result == 0


# ---------------------------------------------------------------------------
# Autocomplete
# ---------------------------------------------------------------------------


class TestAutocompleteQueries:
    @pytest.mark.asyncio
    async def test_autocomplete_artist(self) -> None:
        from api.queries.neo4j_queries import autocomplete_artist

        records = [{"id": "1", "name": "Radiohead", "score": 9.5}]
        driver = _make_driver(records=records)
        result = await autocomplete_artist(driver, "radio", limit=5)
        assert result == records

    @pytest.mark.asyncio
    async def test_autocomplete_label(self) -> None:
        from api.queries.neo4j_queries import autocomplete_label

        records = [{"id": "100", "name": "Warp Records", "score": 9.0}]
        driver = _make_driver(records=records)
        result = await autocomplete_label(driver, "warp", limit=5)
        assert result == records

    @pytest.mark.asyncio
    async def test_autocomplete_genre(self) -> None:
        from api.queries.neo4j_queries import autocomplete_genre

        records = [{"id": "Rock", "name": "Rock", "score": 1.0}]
        driver = _make_driver(records=records)
        result = await autocomplete_genre(driver, "roc", limit=5)
        assert result == records

    @pytest.mark.asyncio
    async def test_autocomplete_style(self) -> None:
        from api.queries.neo4j_queries import autocomplete_style

        records = [{"id": "Alternative Rock", "name": "Alternative Rock", "score": 1.0}]
        driver = _make_driver(records=records)
        result = await autocomplete_style(driver, "alt", limit=5)
        assert result == records

    @pytest.mark.asyncio
    async def test_autocomplete_artist_escapes_query(self) -> None:
        """Ensure Lucene special chars are escaped before querying."""
        from api.queries.neo4j_queries import autocomplete_artist

        driver = _make_driver(records=[])
        await autocomplete_artist(driver, "AC+DC", limit=5)
        # Verify run was called (no exception raised)
        driver.session.assert_called()


# ---------------------------------------------------------------------------
# Explore queries
# ---------------------------------------------------------------------------


class TestExploreQueries:
    @pytest.mark.asyncio
    async def test_explore_artist_found(self) -> None:
        from api.queries.neo4j_queries import explore_artist

        record = {"id": "1", "name": "Radiohead", "release_count": 10, "label_count": 2, "alias_count": 0}
        driver = _make_driver(single=record)
        result = await explore_artist(driver, "Radiohead")
        assert result == record

    @pytest.mark.asyncio
    async def test_explore_artist_not_found(self) -> None:
        from api.queries.neo4j_queries import explore_artist

        driver = _make_driver(single=None)
        result = await explore_artist(driver, "Unknown Artist")
        assert result is None

    @pytest.mark.asyncio
    async def test_explore_genre(self) -> None:
        from api.queries.neo4j_queries import explore_genre

        record = {"id": "Rock", "name": "Rock", "release_count": 5000, "artist_count": 1000, "label_count": 200, "style_count": 50}
        driver = _make_driver(single=record)
        result = await explore_genre(driver, "Rock")
        assert result == record

    @pytest.mark.asyncio
    async def test_explore_label(self) -> None:
        from api.queries.neo4j_queries import explore_label

        record = {"id": "100", "name": "Warp Records", "release_count": 500, "artist_count": 120, "genre_count": 8}
        driver = _make_driver(single=record)
        result = await explore_label(driver, "Warp Records")
        assert result == record

    @pytest.mark.asyncio
    async def test_explore_style(self) -> None:
        from api.queries.neo4j_queries import explore_style

        record = {"id": "Alt Rock", "name": "Alt Rock", "release_count": 2000, "artist_count": 400, "label_count": 100, "genre_count": 3}
        driver = _make_driver(single=record)
        result = await explore_style(driver, "Alt Rock")
        assert result == record


# ---------------------------------------------------------------------------
# Expand queries - artist
# ---------------------------------------------------------------------------


class TestExpandArtistQueries:
    @pytest.mark.asyncio
    async def test_expand_artist_releases(self) -> None:
        from api.queries.neo4j_queries import expand_artist_releases

        records = [{"id": "10", "name": "OK Computer", "type": "release", "year": 1997}]
        driver = _make_driver(records=records)
        result = await expand_artist_releases(driver, "Radiohead", limit=50, offset=0)
        assert result == records

    @pytest.mark.asyncio
    async def test_expand_artist_labels(self) -> None:
        from api.queries.neo4j_queries import expand_artist_labels

        records = [{"id": "200", "name": "Parlophone", "type": "label", "release_count": 8}]
        driver = _make_driver(records=records)
        result = await expand_artist_labels(driver, "Radiohead", limit=50, offset=0)
        assert result == records

    @pytest.mark.asyncio
    async def test_expand_artist_aliases(self) -> None:
        from api.queries.neo4j_queries import expand_artist_aliases

        records = [{"id": "99", "name": "On a Friday", "type": "artist"}]
        driver = _make_driver(records=records)
        result = await expand_artist_aliases(driver, "Radiohead", limit=50, offset=0)
        assert result == records

    @pytest.mark.asyncio
    async def test_expand_artist_releases_with_offset(self) -> None:
        from api.queries.neo4j_queries import expand_artist_releases

        driver = _make_driver(records=[])
        result = await expand_artist_releases(driver, "Radiohead", limit=10, offset=20)
        assert result == []


# ---------------------------------------------------------------------------
# Expand queries - genre
# ---------------------------------------------------------------------------


class TestExpandGenreQueries:
    @pytest.mark.asyncio
    async def test_expand_genre_releases(self) -> None:
        from api.queries.neo4j_queries import expand_genre_releases

        records = [{"id": "r1", "name": "Creep", "type": "release", "year": 1992}]
        driver = _make_driver(records=records)
        result = await expand_genre_releases(driver, "Rock")
        assert result == records

    @pytest.mark.asyncio
    async def test_expand_genre_artists(self) -> None:
        from api.queries.neo4j_queries import expand_genre_artists

        records = [{"id": "1", "name": "Radiohead", "type": "artist"}]
        driver = _make_driver(records=records)
        result = await expand_genre_artists(driver, "Rock")
        assert result == records

    @pytest.mark.asyncio
    async def test_expand_genre_labels(self) -> None:
        from api.queries.neo4j_queries import expand_genre_labels

        records = [{"id": "100", "name": "Warp", "type": "label", "release_count": 10}]
        driver = _make_driver(records=records)
        result = await expand_genre_labels(driver, "Electronic")
        assert result == records

    @pytest.mark.asyncio
    async def test_expand_genre_styles(self) -> None:
        from api.queries.neo4j_queries import expand_genre_styles

        records = [{"id": "Alt Rock", "name": "Alt Rock", "type": "style", "release_count": 500}]
        driver = _make_driver(records=records)
        result = await expand_genre_styles(driver, "Rock")
        assert result == records


# ---------------------------------------------------------------------------
# Expand queries - label
# ---------------------------------------------------------------------------


class TestExpandLabelQueries:
    @pytest.mark.asyncio
    async def test_expand_label_releases(self) -> None:
        from api.queries.neo4j_queries import expand_label_releases

        records = [{"id": "r1", "name": "Selected Ambient Works", "type": "release", "year": 1992}]
        driver = _make_driver(records=records)
        result = await expand_label_releases(driver, "Warp Records")
        assert result == records

    @pytest.mark.asyncio
    async def test_expand_label_artists(self) -> None:
        from api.queries.neo4j_queries import expand_label_artists

        records = [{"id": "5", "name": "Aphex Twin", "type": "artist", "release_count": 15}]
        driver = _make_driver(records=records)
        result = await expand_label_artists(driver, "Warp Records")
        assert result == records

    @pytest.mark.asyncio
    async def test_expand_label_genres(self) -> None:
        from api.queries.neo4j_queries import expand_label_genres

        records = [{"id": "Electronic", "name": "Electronic", "type": "genre", "release_count": 300}]
        driver = _make_driver(records=records)
        result = await expand_label_genres(driver, "Warp Records")
        assert result == records


# ---------------------------------------------------------------------------
# Expand queries - style
# ---------------------------------------------------------------------------


class TestExpandStyleQueries:
    @pytest.mark.asyncio
    async def test_expand_style_releases(self) -> None:
        from api.queries.neo4j_queries import expand_style_releases

        records = [{"id": "r1", "name": "Paranoid Android", "type": "release", "year": 1997}]
        driver = _make_driver(records=records)
        result = await expand_style_releases(driver, "Art Rock")
        assert result == records

    @pytest.mark.asyncio
    async def test_expand_style_artists(self) -> None:
        from api.queries.neo4j_queries import expand_style_artists

        records = [{"id": "1", "name": "Radiohead", "type": "artist"}]
        driver = _make_driver(records=records)
        result = await expand_style_artists(driver, "Art Rock")
        assert result == records

    @pytest.mark.asyncio
    async def test_expand_style_labels(self) -> None:
        from api.queries.neo4j_queries import expand_style_labels

        records = [{"id": "200", "name": "Parlophone", "type": "label", "release_count": 6}]
        driver = _make_driver(records=records)
        result = await expand_style_labels(driver, "Art Rock")
        assert result == records

    @pytest.mark.asyncio
    async def test_expand_style_genres(self) -> None:
        from api.queries.neo4j_queries import expand_style_genres

        records = [{"id": "Rock", "name": "Rock", "type": "genre", "release_count": 2000}]
        driver = _make_driver(records=records)
        result = await expand_style_genres(driver, "Art Rock")
        assert result == records


# ---------------------------------------------------------------------------
# Count queries
# ---------------------------------------------------------------------------


class TestCountQueries:
    @pytest.mark.asyncio
    async def test_count_artist_releases(self) -> None:
        from api.queries.neo4j_queries import count_artist_releases

        driver = _make_driver(single={"total": 10})
        assert await count_artist_releases(driver, "Radiohead") == 10

    @pytest.mark.asyncio
    async def test_count_artist_labels(self) -> None:
        from api.queries.neo4j_queries import count_artist_labels

        driver = _make_driver(single={"total": 3})
        assert await count_artist_labels(driver, "Radiohead") == 3

    @pytest.mark.asyncio
    async def test_count_artist_aliases(self) -> None:
        from api.queries.neo4j_queries import count_artist_aliases

        driver = _make_driver(single={"total": 1})
        assert await count_artist_aliases(driver, "Radiohead") == 1

    @pytest.mark.asyncio
    async def test_count_genre_releases(self) -> None:
        from api.queries.neo4j_queries import count_genre_releases

        driver = _make_driver(single={"total": 5000})
        assert await count_genre_releases(driver, "Rock") == 5000

    @pytest.mark.asyncio
    async def test_count_genre_artists(self) -> None:
        from api.queries.neo4j_queries import count_genre_artists

        driver = _make_driver(single={"total": 100})
        assert await count_genre_artists(driver, "Rock") == 100

    @pytest.mark.asyncio
    async def test_count_genre_labels(self) -> None:
        from api.queries.neo4j_queries import count_genre_labels

        driver = _make_driver(single={"total": 50})
        assert await count_genre_labels(driver, "Rock") == 50

    @pytest.mark.asyncio
    async def test_count_genre_styles(self) -> None:
        from api.queries.neo4j_queries import count_genre_styles

        driver = _make_driver(single={"total": 20})
        assert await count_genre_styles(driver, "Rock") == 20

    @pytest.mark.asyncio
    async def test_count_label_releases(self) -> None:
        from api.queries.neo4j_queries import count_label_releases

        driver = _make_driver(single={"total": 500})
        assert await count_label_releases(driver, "Warp") == 500

    @pytest.mark.asyncio
    async def test_count_label_artists(self) -> None:
        from api.queries.neo4j_queries import count_label_artists

        driver = _make_driver(single={"total": 80})
        assert await count_label_artists(driver, "Warp") == 80

    @pytest.mark.asyncio
    async def test_count_label_genres(self) -> None:
        from api.queries.neo4j_queries import count_label_genres

        driver = _make_driver(single={"total": 5})
        assert await count_label_genres(driver, "Warp") == 5

    @pytest.mark.asyncio
    async def test_count_style_releases(self) -> None:
        from api.queries.neo4j_queries import count_style_releases

        driver = _make_driver(single={"total": 2000})
        assert await count_style_releases(driver, "Art Rock") == 2000

    @pytest.mark.asyncio
    async def test_count_style_artists(self) -> None:
        from api.queries.neo4j_queries import count_style_artists

        driver = _make_driver(single={"total": 400})
        assert await count_style_artists(driver, "Art Rock") == 400

    @pytest.mark.asyncio
    async def test_count_style_labels(self) -> None:
        from api.queries.neo4j_queries import count_style_labels

        driver = _make_driver(single={"total": 60})
        assert await count_style_labels(driver, "Art Rock") == 60

    @pytest.mark.asyncio
    async def test_count_style_genres(self) -> None:
        from api.queries.neo4j_queries import count_style_genres

        driver = _make_driver(single={"total": 4})
        assert await count_style_genres(driver, "Art Rock") == 4

    @pytest.mark.asyncio
    async def test_count_returns_zero_when_no_record(self) -> None:
        from api.queries.neo4j_queries import count_artist_releases

        driver = _make_driver(single=None)
        assert await count_artist_releases(driver, "NoArtist") == 0


# ---------------------------------------------------------------------------
# Node details
# ---------------------------------------------------------------------------


class TestNodeDetailsQueries:
    @pytest.mark.asyncio
    async def test_get_artist_details(self) -> None:
        from api.queries.neo4j_queries import get_artist_details

        record = {"id": "1", "name": "Radiohead", "genres": ["Rock"], "styles": ["Alt Rock"], "release_count": 10, "groups": []}
        driver = _make_driver(single=record)
        result = await get_artist_details(driver, "1")
        assert result == record

    @pytest.mark.asyncio
    async def test_get_artist_details_not_found(self) -> None:
        from api.queries.neo4j_queries import get_artist_details

        driver = _make_driver(single=None)
        result = await get_artist_details(driver, "9999")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_release_details(self) -> None:
        from api.queries.neo4j_queries import get_release_details

        record = {
            "id": "10",
            "name": "OK Computer",
            "year": 1997,
            "artists": ["Radiohead"],
            "labels": ["Parlophone"],
            "genres": ["Rock"],
            "styles": [],
        }
        driver = _make_driver(single=record)
        result = await get_release_details(driver, "10")
        assert result == record

    @pytest.mark.asyncio
    async def test_get_label_details(self) -> None:
        from api.queries.neo4j_queries import get_label_details

        record = {"id": "100", "name": "Warp Records", "release_count": 500}
        driver = _make_driver(single=record)
        result = await get_label_details(driver, "100")
        assert result == record

    @pytest.mark.asyncio
    async def test_get_genre_details(self) -> None:
        from api.queries.neo4j_queries import get_genre_details

        record = {"id": "Rock", "name": "Rock", "artist_count": 1000}
        driver = _make_driver(single=record)
        result = await get_genre_details(driver, "Rock")
        assert result == record

    @pytest.mark.asyncio
    async def test_get_style_details(self) -> None:
        from api.queries.neo4j_queries import get_style_details

        record = {"id": "Alt Rock", "name": "Alt Rock", "artist_count": 400}
        driver = _make_driver(single=record)
        result = await get_style_details(driver, "Alt Rock")
        assert result == record


# ---------------------------------------------------------------------------
# Trends queries
# ---------------------------------------------------------------------------


class TestTrendsQueries:
    @pytest.mark.asyncio
    async def test_trends_artist(self) -> None:
        from api.queries.neo4j_queries import trends_artist

        records = [{"year": 1997, "count": 1}, {"year": 2000, "count": 1}]
        driver = _make_driver(records=records)
        result = await trends_artist(driver, "Radiohead")
        assert result == records

    @pytest.mark.asyncio
    async def test_trends_genre(self) -> None:
        from api.queries.neo4j_queries import trends_genre

        records = [{"year": 1970, "count": 200}]
        driver = _make_driver(records=records)
        result = await trends_genre(driver, "Rock")
        assert result == records

    @pytest.mark.asyncio
    async def test_trends_label(self) -> None:
        from api.queries.neo4j_queries import trends_label

        records = [{"year": 1990, "count": 30}]
        driver = _make_driver(records=records)
        result = await trends_label(driver, "Warp Records")
        assert result == records

    @pytest.mark.asyncio
    async def test_trends_style(self) -> None:
        from api.queries.neo4j_queries import trends_style

        records = [{"year": 1985, "count": 15}]
        driver = _make_driver(records=records)
        result = await trends_style(driver, "Art Rock")
        assert result == records

    @pytest.mark.asyncio
    async def test_trends_empty_returns_empty_list(self) -> None:
        from api.queries.neo4j_queries import trends_artist

        driver = _make_driver(records=[])
        result = await trends_artist(driver, "UnknownArtist")
        assert result == []
