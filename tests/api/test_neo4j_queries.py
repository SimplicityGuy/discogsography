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

    driver.session = MagicMock(return_value=mock_session)
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
    driver.session = MagicMock(return_value=mock_session)
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

    def test_preserves_space(self) -> None:
        from api.queries.neo4j_queries import _escape_lucene_query

        assert _escape_lucene_query("Warp Records") == "Warp Records"

    def test_escapes_colon(self) -> None:
        from api.queries.neo4j_queries import _escape_lucene_query

        result = _escape_lucene_query("key:value")
        assert r"\:" in result


class TestBuildAutocompleteQuery:
    def test_single_word(self) -> None:
        from api.queries.neo4j_queries import _build_autocomplete_query

        assert _build_autocomplete_query("Indecent") == "Indecent*"

    def test_multi_word(self) -> None:
        from api.queries.neo4j_queries import _build_autocomplete_query

        assert _build_autocomplete_query("Indecent N") == "Indecent* AND N*"

    def test_special_chars_escaped(self) -> None:
        from api.queries.neo4j_queries import _build_autocomplete_query

        assert _build_autocomplete_query("key:val test") == r"key\:val* AND test*"


# ---------------------------------------------------------------------------
# _run_query / _run_single / _run_count
# ---------------------------------------------------------------------------


class TestRunHelpers:
    @pytest.mark.asyncio
    async def test_run_query_returns_list(self) -> None:
        from api.queries.helpers import run_query

        records = [{"id": "1", "name": "Rock"}, {"id": "2", "name": "Jazz"}]
        driver = _make_driver(records=records)
        result = await run_query(driver, "MATCH (n) RETURN n")
        assert result == records

    @pytest.mark.asyncio
    async def test_run_query_empty(self) -> None:
        from api.queries.helpers import run_query

        driver = _make_driver(records=[])
        result = await run_query(driver, "MATCH (n) RETURN n")
        assert result == []

    @pytest.mark.asyncio
    async def test_run_single_with_record(self) -> None:
        from api.queries.helpers import run_single

        record = {"id": "1", "name": "Radiohead"}
        driver = _make_driver(single=record)
        result = await run_single(driver, "MATCH (a) RETURN a LIMIT 1")
        assert result == record

    @pytest.mark.asyncio
    async def test_run_single_none(self) -> None:
        from api.queries.helpers import run_single

        driver = _make_driver(single=None)
        result = await run_single(driver, "MATCH (a) RETURN a LIMIT 1")
        assert result is None

    @pytest.mark.asyncio
    async def test_run_count_with_total(self) -> None:
        from api.queries.helpers import run_count

        driver = _make_driver(single={"total": 42})
        result = await run_count(driver, "RETURN count(*) AS total")
        assert result == 42

    @pytest.mark.asyncio
    async def test_run_count_no_record(self) -> None:
        from api.queries.helpers import run_count

        driver = _make_driver(single=None)
        result = await run_count(driver, "RETURN count(*) AS total")
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
    async def test_explore_label_not_found(self) -> None:
        """Label not found returns None."""
        from api.queries.neo4j_queries import explore_label

        driver = _make_driver(single=None)
        result = await explore_label(driver, "Nonexistent Label")
        assert result is None

    @pytest.mark.asyncio
    async def test_explore_label_fallback_no_precomputed(self) -> None:
        """Label without pre-computed stats falls back to live traversal."""
        from api.queries.neo4j_queries import explore_label

        # First call: pre-computed query returns record with release_count=None
        first_result = _MockResult(single={"id": "200", "name": "New Label", "release_count": None, "artist_count": None, "genre_count": None})
        # Second call: fallback live traversal returns actual counts
        fallback_result = _MockResult(single={"id": "200", "name": "New Label", "release_count": 50, "artist_count": 10, "genre_count": 3})
        driver = _make_driver_with_side_effects([first_result, fallback_result])
        result = await explore_label(driver, "New Label")
        assert result is not None
        assert result["release_count"] == 50
        assert result["artist_count"] == 10
        assert result["genre_count"] == 3

    @pytest.mark.asyncio
    async def test_explore_style(self) -> None:
        from api.queries.neo4j_queries import explore_style

        record = {"id": "Alt Rock", "name": "Alt Rock", "release_count": 2000, "artist_count": 400, "label_count": 100, "genre_count": 3}
        driver = _make_driver(single=record)
        result = await explore_style(driver, "Alt Rock")
        assert result == record

    @pytest.mark.asyncio
    async def test_explore_genre_not_found(self) -> None:
        """Genre not found returns None (line 188)."""
        from api.queries.neo4j_queries import explore_genre

        driver = _make_driver(single=None)
        result = await explore_genre(driver, "Nonexistent Genre")
        assert result is None

    @pytest.mark.asyncio
    async def test_explore_style_not_found(self) -> None:
        """Style not found returns None (line 263)."""
        from api.queries.neo4j_queries import explore_style

        driver = _make_driver(single=None)
        result = await explore_style(driver, "Nonexistent Style")
        assert result is None


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
# Count before_year filtering
# ---------------------------------------------------------------------------


def _make_capturing_driver(total: int = 10) -> tuple[MagicMock, list[str], list[dict[str, Any]]]:
    """Build a driver that captures the Cypher and params passed to run()."""
    captured_cypher: list[str] = []
    captured_params: list[dict[str, Any]] = []

    class CapturingMockResult:
        async def single(self) -> dict[str, Any]:
            return {"total": total}

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    async def capturing_run(cypher: str, params: dict[str, Any] | None = None, **kwargs: Any) -> CapturingMockResult:
        captured_cypher.append(cypher)
        captured_params.append(params or kwargs)
        return CapturingMockResult()

    mock_session.run = AsyncMock(side_effect=capturing_run)

    driver: MagicMock = MagicMock()

    driver.session = MagicMock(return_value=mock_session)
    return driver, captured_cypher, captured_params


class TestCountBeforeYear:
    @pytest.mark.asyncio
    async def test_count_artist_releases_without_before_year(self) -> None:
        """Without before_year, Cypher must NOT contain 'before_year'."""
        from api.queries.neo4j_queries import count_artist_releases

        driver, captured_cypher, _ = _make_capturing_driver(total=10)
        result = await count_artist_releases(driver, "Radiohead")
        assert result == 10
        assert len(captured_cypher) == 1
        assert "before_year" not in captured_cypher[0]

    @pytest.mark.asyncio
    async def test_count_artist_releases_with_before_year(self) -> None:
        """With before_year=1997, Cypher must include 'before_year' filter and return count."""
        from api.queries.neo4j_queries import count_artist_releases

        driver, captured_cypher, captured_params = _make_capturing_driver(total=5)
        result = await count_artist_releases(driver, "Radiohead", before_year=1997)
        assert result == 5
        assert len(captured_cypher) == 1
        assert "before_year" in captured_cypher[0]
        assert captured_params[0].get("before_year") == 1997

    @pytest.mark.asyncio
    async def test_count_artist_aliases_ignores_before_year(self) -> None:
        """count_artist_aliases accepts before_year but does NOT include it in Cypher."""
        from api.queries.neo4j_queries import count_artist_aliases

        driver, captured_cypher, captured_params = _make_capturing_driver(total=2)
        result = await count_artist_aliases(driver, "Aphex Twin", before_year=1997)
        assert result == 2
        assert len(captured_cypher) == 1
        assert "before_year" not in captured_cypher[0]
        assert "before_year" not in captured_params[0]


class TestCountBeforeYearAllFunctions:
    """Parametrized tests for before_year branches in all count_* functions."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "func_name, entity_type, entity_arg_name",
        [
            ("count_artist_labels", "artist", "Radiohead"),
            ("count_genre_releases", "genre", "Rock"),
            ("count_genre_artists", "genre", "Rock"),
            ("count_genre_labels", "genre", "Rock"),
            ("count_genre_styles", "genre", "Rock"),
            ("count_label_releases", "label", "Warp Records"),
            ("count_label_artists", "label", "Warp Records"),
            ("count_label_genres", "label", "Warp Records"),
            ("count_style_releases", "style", "Alt Rock"),
            ("count_style_artists", "style", "Alt Rock"),
            ("count_style_labels", "style", "Alt Rock"),
            ("count_style_genres", "style", "Alt Rock"),
        ],
    )
    async def test_count_with_before_year(self, func_name: str, entity_type: str, entity_arg_name: str) -> None:  # noqa: ARG002
        """Each count_* function with before_year includes it in Cypher and params."""
        import api.queries.neo4j_queries as mod

        func = getattr(mod, func_name)
        driver, captured_cypher, captured_params = _make_capturing_driver(total=7)
        result = await func(driver, entity_arg_name, before_year=2000)
        assert result == 7
        assert len(captured_cypher) == 1
        assert "before_year" in captured_cypher[0]
        assert captured_params[0].get("before_year") == 2000


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


# ---------------------------------------------------------------------------
# before_year filtering on expand_* functions
# ---------------------------------------------------------------------------


class TestExpandBeforeYear:
    """Verify that expand_* functions respect the before_year keyword argument."""

    def _capture_driver(self) -> tuple[MagicMock, list[tuple[str, Any]]]:
        """Build a driver that captures (cypher, params) from each session.run() call."""
        calls: list[tuple[str, Any]] = []

        mock_result = _MockResult(records=[])
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        async def _run_side_effect(cypher: str, params: Any, **_kwargs: Any) -> _MockResult:
            calls.append((cypher, params))
            return mock_result

        mock_session.run = AsyncMock(side_effect=_run_side_effect)

        driver = MagicMock()

        driver.session = MagicMock(return_value=mock_session)
        return driver, calls

    @pytest.mark.asyncio
    async def test_expand_artist_releases_no_year_filter(self) -> None:
        """When before_year is None, Cypher must NOT contain 'before_year'."""
        from api.queries.neo4j_queries import expand_artist_releases

        driver, calls = self._capture_driver()
        await expand_artist_releases(driver, "Radiohead", limit=10, offset=0)
        assert calls, "Expected session.run to be called"
        cypher, params = calls[0]
        assert "before_year" not in cypher
        assert "before_year" not in params

    @pytest.mark.asyncio
    async def test_expand_artist_releases_with_year_filter(self) -> None:
        """When before_year=1997, Cypher must contain 'before_year' and params too."""
        from api.queries.neo4j_queries import expand_artist_releases

        driver, calls = self._capture_driver()
        await expand_artist_releases(driver, "Radiohead", limit=10, offset=0, before_year=1997)
        assert calls, "Expected session.run to be called"
        cypher, params = calls[0]
        assert "before_year" in cypher
        assert params.get("before_year") == 1997

    @pytest.mark.asyncio
    async def test_expand_genre_releases_with_year_filter(self) -> None:
        """expand_genre_releases passes before_year through _expand_releases."""
        from api.queries.neo4j_queries import expand_genre_releases

        driver, calls = self._capture_driver()
        await expand_genre_releases(driver, "Rock", limit=10, offset=0, before_year=2000)
        cypher, params = calls[0]
        assert "before_year" in cypher
        assert params.get("before_year") == 2000

    @pytest.mark.asyncio
    async def test_expand_label_releases_with_year_filter(self) -> None:
        """expand_label_releases passes before_year through _expand_releases."""
        from api.queries.neo4j_queries import expand_label_releases

        driver, calls = self._capture_driver()
        await expand_label_releases(driver, "Warp Records", limit=10, offset=0, before_year=1995)
        cypher, params = calls[0]
        assert "before_year" in cypher
        assert params.get("before_year") == 1995

    @pytest.mark.asyncio
    async def test_expand_style_releases_with_year_filter(self) -> None:
        """expand_style_releases passes before_year through _expand_releases."""
        from api.queries.neo4j_queries import expand_style_releases

        driver, calls = self._capture_driver()
        await expand_style_releases(driver, "Art Rock", limit=10, offset=0, before_year=1990)
        cypher, params = calls[0]
        assert "before_year" in cypher
        assert params.get("before_year") == 1990

    @pytest.mark.asyncio
    async def test_expand_artist_aliases_ignores_before_year(self) -> None:
        """expand_artist_aliases accepts before_year but must NOT use it in Cypher."""
        from api.queries.neo4j_queries import expand_artist_aliases

        driver, calls = self._capture_driver()
        await expand_artist_aliases(driver, "Radiohead", limit=10, offset=0, before_year=1997)
        cypher, params = calls[0]
        assert "before_year" not in cypher
        assert "before_year" not in params

    @pytest.mark.asyncio
    async def test_expand_artist_labels_with_year_filter(self) -> None:
        """expand_artist_labels applies year filter in the transitive query."""
        from api.queries.neo4j_queries import expand_artist_labels

        driver, calls = self._capture_driver()
        await expand_artist_labels(driver, "Radiohead", limit=10, offset=0, before_year=1997)
        cypher, params = calls[0]
        assert "before_year" in cypher
        assert params.get("before_year") == 1997

    @pytest.mark.asyncio
    async def test_expand_artist_labels_no_year_filter(self) -> None:
        """When before_year is None, transitive queries must NOT add the clause."""
        from api.queries.neo4j_queries import expand_artist_labels

        driver, calls = self._capture_driver()
        await expand_artist_labels(driver, "Radiohead", limit=10, offset=0)
        cypher, params = calls[0]
        assert "before_year" not in cypher
        assert "before_year" not in params

    @pytest.mark.asyncio
    async def test_expand_genre_artists_with_year_filter(self) -> None:
        """expand_genre_artists applies year filter."""
        from api.queries.neo4j_queries import expand_genre_artists

        driver, calls = self._capture_driver()
        await expand_genre_artists(driver, "Rock", limit=10, offset=0, before_year=1980)
        cypher, params = calls[0]
        assert "before_year" in cypher
        assert params.get("before_year") == 1980

    @pytest.mark.asyncio
    async def test_expand_genre_labels_with_year_filter(self) -> None:
        """expand_genre_labels applies year filter."""
        from api.queries.neo4j_queries import expand_genre_labels

        driver, calls = self._capture_driver()
        await expand_genre_labels(driver, "Electronic", limit=10, offset=0, before_year=2005)
        cypher, params = calls[0]
        assert "before_year" in cypher
        assert params.get("before_year") == 2005

    @pytest.mark.asyncio
    async def test_expand_genre_styles_with_year_filter(self) -> None:
        """expand_genre_styles applies year filter."""
        from api.queries.neo4j_queries import expand_genre_styles

        driver, calls = self._capture_driver()
        await expand_genre_styles(driver, "Rock", limit=10, offset=0, before_year=1999)
        cypher, params = calls[0]
        assert "before_year" in cypher
        assert params.get("before_year") == 1999

    @pytest.mark.asyncio
    async def test_expand_label_artists_with_year_filter(self) -> None:
        """expand_label_artists applies year filter."""
        from api.queries.neo4j_queries import expand_label_artists

        driver, calls = self._capture_driver()
        await expand_label_artists(driver, "Warp Records", limit=10, offset=0, before_year=2000)
        cypher, params = calls[0]
        assert "before_year" in cypher
        assert params.get("before_year") == 2000

    @pytest.mark.asyncio
    async def test_expand_label_genres_with_year_filter(self) -> None:
        """expand_label_genres applies year filter."""
        from api.queries.neo4j_queries import expand_label_genres

        driver, calls = self._capture_driver()
        await expand_label_genres(driver, "Warp Records", limit=10, offset=0, before_year=2010)
        cypher, params = calls[0]
        assert "before_year" in cypher
        assert params.get("before_year") == 2010

    @pytest.mark.asyncio
    async def test_expand_style_artists_with_year_filter(self) -> None:
        """expand_style_artists applies year filter."""
        from api.queries.neo4j_queries import expand_style_artists

        driver, calls = self._capture_driver()
        await expand_style_artists(driver, "Art Rock", limit=10, offset=0, before_year=1985)
        cypher, params = calls[0]
        assert "before_year" in cypher
        assert params.get("before_year") == 1985

    @pytest.mark.asyncio
    async def test_expand_style_labels_with_year_filter(self) -> None:
        """expand_style_labels applies year filter."""
        from api.queries.neo4j_queries import expand_style_labels

        driver, calls = self._capture_driver()
        await expand_style_labels(driver, "Art Rock", limit=10, offset=0, before_year=1992)
        cypher, params = calls[0]
        assert "before_year" in cypher
        assert params.get("before_year") == 1992

    @pytest.mark.asyncio
    async def test_expand_style_genres_with_year_filter(self) -> None:
        """expand_style_genres applies year filter."""
        from api.queries.neo4j_queries import expand_style_genres

        driver, calls = self._capture_driver()
        await expand_style_genres(driver, "Art Rock", limit=10, offset=0, before_year=2003)
        cypher, params = calls[0]
        assert "before_year" in cypher
        assert params.get("before_year") == 2003


class TestFindShortestPath:
    """Tests for find_shortest_path()."""

    @pytest.mark.asyncio
    async def test_path_found(self) -> None:
        """Returns populated path when nodes are connected."""
        from api.queries.neo4j_queries import find_shortest_path

        mock_record = {
            "nodes": [
                {"id": "1", "name": "Miles Davis", "labels": ["Artist"]},
                {"id": "201", "name": "Kind of Blue", "labels": ["Release"]},
                {"id": "2", "name": "Daft Punk", "labels": ["Artist"]},
            ],
            "rels": ["BY", "BY"],
        }
        mock_driver = AsyncMock()
        mock_session = AsyncMock()
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=mock_record)
        mock_session.run = AsyncMock(return_value=mock_result)
        mock_driver.session = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_session), __aexit__=AsyncMock()))

        result = await find_shortest_path(mock_driver, "1", "2", max_depth=10)

        assert result is not None
        assert len(result["nodes"]) == 3
        assert result["rels"] == ["BY", "BY"]

    @pytest.mark.asyncio
    async def test_no_path_returns_none(self) -> None:
        """Returns None when no path exists."""
        from api.queries.neo4j_queries import find_shortest_path

        mock_driver = AsyncMock()
        mock_session = AsyncMock()
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=None)
        mock_session.run = AsyncMock(return_value=mock_result)
        mock_driver.session = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_session), __aexit__=AsyncMock()))

        result = await find_shortest_path(mock_driver, "1", "999", max_depth=10)

        assert result is None

    @pytest.mark.asyncio
    async def test_same_node_path(self) -> None:
        """Same from/to node returns trivial path (single node, no rels)."""
        from api.queries.neo4j_queries import find_shortest_path

        mock_record = {
            "nodes": [{"id": "1", "name": "Miles Davis", "labels": ["Artist"]}],
            "rels": [],
        }
        mock_driver = AsyncMock()
        mock_session = AsyncMock()
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=mock_record)
        mock_session.run = AsyncMock(return_value=mock_result)
        mock_driver.session = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_session), __aexit__=AsyncMock()))

        result = await find_shortest_path(mock_driver, "1", "1", max_depth=10)

        assert result is not None
        assert len(result["nodes"]) == 1
        assert result["rels"] == []


# ---------------------------------------------------------------------------
# get_year_range
# ---------------------------------------------------------------------------


class TestYearRangeQuery:
    @pytest.mark.asyncio
    async def test_year_range_returns_min_max(self) -> None:
        from api.queries.neo4j_queries import get_year_range

        mock_driver = AsyncMock()
        mock_session = AsyncMock()
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value={"min_year": 1950, "max_year": 2025})
        mock_session.run = AsyncMock(return_value=mock_result)
        mock_driver.session = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_session), __aexit__=AsyncMock()))

        result = await get_year_range(mock_driver)
        assert result == {"min_year": 1950, "max_year": 2025}

    @pytest.mark.asyncio
    async def test_year_range_empty_graph(self) -> None:
        from api.queries.neo4j_queries import get_year_range

        mock_driver = AsyncMock()
        mock_session = AsyncMock()
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=None)
        mock_session.run = AsyncMock(return_value=mock_result)
        mock_driver.session = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_session), __aexit__=AsyncMock()))

        result = await get_year_range(mock_driver)
        assert result is None


# ---------------------------------------------------------------------------
# get_genre_emergence
# ---------------------------------------------------------------------------


class TestGenreEmergenceQuery:
    @pytest.mark.asyncio
    async def test_genre_emergence_returns_genres_and_styles(self) -> None:
        from api.queries.neo4j_queries import get_genre_emergence

        genre_records = [
            {"name": "Punk", "first_year": 1976},
            {"name": "Rock", "first_year": 1955},
        ]
        style_records = [
            {"name": "Post-Punk", "first_year": 1978},
        ]

        genre_result = _MockResult(records=genre_records)
        style_result = _MockResult(records=style_records)

        mock_driver = _make_driver_with_side_effects([genre_result, style_result])

        result = await get_genre_emergence(mock_driver, 1980)
        assert len(result["genres"]) == 2
        assert len(result["styles"]) == 1
        assert result["genres"][0]["name"] == "Punk"

    @pytest.mark.asyncio
    async def test_genre_emergence_empty_results(self) -> None:
        from api.queries.neo4j_queries import get_genre_emergence

        # Fast path returns empty (no pre-computed first_year), then
        # fallback slow path also returns empty.
        mock_driver = _make_driver_with_side_effects(
            [
                _MockResult(),
                _MockResult(),  # fast path (empty)
                _MockResult(),
                _MockResult(),  # slow fallback (empty)
            ]
        )

        result = await get_genre_emergence(mock_driver, 2000)
        assert result == {"genres": [], "styles": []}


# ---------------------------------------------------------------------------
# get_graph_stats
# ---------------------------------------------------------------------------


class TestGraphStatsQuery:
    @pytest.mark.asyncio
    async def test_graph_stats_returns_counts(self) -> None:
        from api.queries.neo4j_queries import get_graph_stats

        records = [
            {"label": "artists", "cnt": 1000},
            {"label": "labels", "cnt": 500},
            {"label": "releases", "cnt": 5000},
            {"label": "masters", "cnt": 2000},
            {"label": "genres", "cnt": 15},
            {"label": "styles", "cnt": 300},
        ]
        driver = _make_driver(records=records)
        result = await get_graph_stats(driver)
        assert result == {"artists": 1000, "labels": 500, "releases": 5000, "masters": 2000, "genres": 15, "styles": 300}

    @pytest.mark.asyncio
    async def test_graph_stats_empty_graph(self) -> None:
        from api.queries.neo4j_queries import get_graph_stats

        driver = _make_driver(records=[])
        result = await get_graph_stats(driver)
        assert result == {}
