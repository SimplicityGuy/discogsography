"""Tests for Explore service Neo4j query functions."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from explore.neo4j_queries import (
    AUTOCOMPLETE_DISPATCH,
    COUNT_DISPATCH,
    DETAILS_DISPATCH,
    EXPAND_DISPATCH,
    EXPLORE_DISPATCH,
    TRENDS_DISPATCH,
    autocomplete_artist,
    autocomplete_genre,
    autocomplete_label,
    autocomplete_style,
    count_artist_aliases,
    count_artist_labels,
    count_artist_releases,
    count_genre_artists,
    count_genre_labels,
    count_genre_releases,
    count_genre_styles,
    count_label_artists,
    count_label_genres,
    count_label_releases,
    count_style_artists,
    count_style_genres,
    count_style_labels,
    count_style_releases,
    expand_artist_aliases,
    expand_artist_labels,
    expand_artist_releases,
    expand_genre_artists,
    expand_genre_labels,
    expand_genre_releases,
    expand_genre_styles,
    expand_label_artists,
    expand_label_genres,
    expand_label_releases,
    expand_style_artists,
    expand_style_genres,
    expand_style_labels,
    expand_style_releases,
    explore_artist,
    explore_genre,
    explore_label,
    explore_style,
    get_artist_details,
    get_genre_details,
    get_label_details,
    get_release_details,
    get_style_details,
    trends_artist,
    trends_genre,
    trends_label,
    trends_style,
)


@pytest.fixture
def mock_driver() -> MagicMock:
    """Create a mock async Neo4j driver."""
    driver = MagicMock()
    mock_session = AsyncMock()
    mock_result = AsyncMock()

    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.run = AsyncMock(return_value=mock_result)

    mock_result.single = AsyncMock(return_value=None)

    driver.session = AsyncMock(return_value=mock_session)
    return driver


def _make_async_iterable(items: list[dict[str, Any]]) -> AsyncMock:
    """Create an async iterable mock result from a list of dicts."""
    mock_result = AsyncMock()

    class AsyncIter:
        def __init__(self) -> None:
            self.items = iter(items)

        def __aiter__(self) -> "AsyncIter":
            return self

        async def __anext__(self) -> dict[str, Any]:
            try:
                return next(self.items)
            except StopIteration:
                raise StopAsyncIteration from None

    mock_result.__aiter__ = lambda _self: AsyncIter()
    mock_result.single = AsyncMock(return_value=None)
    return mock_result


class TestDispatchTables:
    """Test that dispatch tables are properly configured."""

    def test_autocomplete_dispatch_keys(self) -> None:
        assert set(AUTOCOMPLETE_DISPATCH.keys()) == {"artist", "genre", "label", "style"}

    def test_explore_dispatch_keys(self) -> None:
        assert set(EXPLORE_DISPATCH.keys()) == {"artist", "genre", "label", "style"}

    def test_expand_dispatch_keys(self) -> None:
        assert set(EXPAND_DISPATCH.keys()) == {"artist", "genre", "label", "style"}
        assert set(EXPAND_DISPATCH["artist"].keys()) == {"releases", "labels", "aliases"}
        assert set(EXPAND_DISPATCH["genre"].keys()) == {"releases", "artists", "labels", "styles"}
        assert set(EXPAND_DISPATCH["label"].keys()) == {"releases", "artists", "genres"}
        assert set(EXPAND_DISPATCH["style"].keys()) == {"releases", "artists", "labels", "genres"}

    def test_details_dispatch_keys(self) -> None:
        assert set(DETAILS_DISPATCH.keys()) == {"artist", "release", "label", "genre", "style"}

    def test_trends_dispatch_keys(self) -> None:
        assert set(TRENDS_DISPATCH.keys()) == {"artist", "genre", "label", "style"}

    def test_count_dispatch_keys(self) -> None:
        assert set(COUNT_DISPATCH.keys()) == {"artist", "genre", "label", "style"}
        assert set(COUNT_DISPATCH["artist"].keys()) == {"releases", "labels", "aliases"}
        assert set(COUNT_DISPATCH["genre"].keys()) == {"releases", "artists", "labels", "styles"}
        assert set(COUNT_DISPATCH["label"].keys()) == {"releases", "artists", "genres"}
        assert set(COUNT_DISPATCH["style"].keys()) == {"releases", "artists", "labels", "genres"}

    def test_autocomplete_dispatch_functions(self) -> None:
        assert AUTOCOMPLETE_DISPATCH["artist"] is autocomplete_artist
        assert AUTOCOMPLETE_DISPATCH["genre"] is autocomplete_genre
        assert AUTOCOMPLETE_DISPATCH["label"] is autocomplete_label
        assert AUTOCOMPLETE_DISPATCH["style"] is autocomplete_style

    def test_explore_dispatch_functions(self) -> None:
        assert EXPLORE_DISPATCH["artist"] is explore_artist
        assert EXPLORE_DISPATCH["genre"] is explore_genre
        assert EXPLORE_DISPATCH["label"] is explore_label
        assert EXPLORE_DISPATCH["style"] is explore_style

    def test_expand_dispatch_functions(self) -> None:
        assert EXPAND_DISPATCH["artist"]["releases"] is expand_artist_releases
        assert EXPAND_DISPATCH["artist"]["labels"] is expand_artist_labels
        assert EXPAND_DISPATCH["artist"]["aliases"] is expand_artist_aliases
        assert EXPAND_DISPATCH["genre"]["releases"] is expand_genre_releases
        assert EXPAND_DISPATCH["genre"]["artists"] is expand_genre_artists
        assert EXPAND_DISPATCH["genre"]["labels"] is expand_genre_labels
        assert EXPAND_DISPATCH["genre"]["styles"] is expand_genre_styles
        assert EXPAND_DISPATCH["label"]["releases"] is expand_label_releases
        assert EXPAND_DISPATCH["label"]["artists"] is expand_label_artists
        assert EXPAND_DISPATCH["label"]["genres"] is expand_label_genres
        assert EXPAND_DISPATCH["style"]["releases"] is expand_style_releases
        assert EXPAND_DISPATCH["style"]["artists"] is expand_style_artists
        assert EXPAND_DISPATCH["style"]["labels"] is expand_style_labels
        assert EXPAND_DISPATCH["style"]["genres"] is expand_style_genres

    def test_count_dispatch_functions(self) -> None:
        assert COUNT_DISPATCH["artist"]["releases"] is count_artist_releases
        assert COUNT_DISPATCH["artist"]["labels"] is count_artist_labels
        assert COUNT_DISPATCH["artist"]["aliases"] is count_artist_aliases
        assert COUNT_DISPATCH["genre"]["releases"] is count_genre_releases
        assert COUNT_DISPATCH["genre"]["artists"] is count_genre_artists
        assert COUNT_DISPATCH["genre"]["labels"] is count_genre_labels
        assert COUNT_DISPATCH["genre"]["styles"] is count_genre_styles
        assert COUNT_DISPATCH["label"]["releases"] is count_label_releases
        assert COUNT_DISPATCH["label"]["artists"] is count_label_artists
        assert COUNT_DISPATCH["label"]["genres"] is count_label_genres
        assert COUNT_DISPATCH["style"]["releases"] is count_style_releases
        assert COUNT_DISPATCH["style"]["artists"] is count_style_artists
        assert COUNT_DISPATCH["style"]["labels"] is count_style_labels
        assert COUNT_DISPATCH["style"]["genres"] is count_style_genres


class TestAutocompleteQueries:
    """Test autocomplete query functions."""

    @pytest.mark.asyncio
    async def test_autocomplete_artist(self, mock_driver: MagicMock) -> None:
        expected = [{"id": "1", "name": "Radiohead", "score": 9.5}]
        mock_session = mock_driver.session.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable(expected))

        results = await autocomplete_artist(mock_driver, "radio", 10)
        assert len(results) == 1
        assert results[0]["name"] == "Radiohead"

    @pytest.mark.asyncio
    async def test_autocomplete_label(self, mock_driver: MagicMock) -> None:
        expected = [{"id": "100", "name": "Warp Records", "score": 9.0}]
        mock_session = mock_driver.session.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable(expected))

        results = await autocomplete_label(mock_driver, "warp", 10)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_autocomplete_genre(self, mock_driver: MagicMock) -> None:
        expected = [{"id": "Rock", "name": "Rock", "score": 1.0}]
        mock_session = mock_driver.session.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable(expected))

        results = await autocomplete_genre(mock_driver, "rock", 10)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_autocomplete_empty(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable([]))

        results = await autocomplete_artist(mock_driver, "zzzzz", 10)
        assert results == []


class TestExploreQueries:
    """Test explore query functions."""

    @pytest.mark.asyncio
    async def test_explore_artist_found(self, mock_driver: MagicMock) -> None:
        expected = {"id": "1", "name": "Radiohead", "release_count": 42, "label_count": 5, "alias_count": 2}
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=expected)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await explore_artist(mock_driver, "Radiohead")
        assert result is not None
        assert result["name"] == "Radiohead"
        assert result["release_count"] == 42

    @pytest.mark.asyncio
    async def test_explore_artist_not_found(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=None)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await explore_artist(mock_driver, "NonExistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_explore_genre(self, mock_driver: MagicMock) -> None:
        expected = {"id": "Rock", "name": "Rock", "artist_count": 1000, "label_count": 200, "style_count": 50}
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=expected)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await explore_genre(mock_driver, "Rock")
        assert result is not None
        assert result["artist_count"] == 1000

    @pytest.mark.asyncio
    async def test_explore_genre_not_found(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=None)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await explore_genre(mock_driver, "NonExistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_explore_label(self, mock_driver: MagicMock) -> None:
        expected = {"id": "100", "name": "Warp Records", "release_count": 500, "artist_count": 120}
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=expected)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await explore_label(mock_driver, "Warp Records")
        assert result is not None
        assert result["release_count"] == 500

    @pytest.mark.asyncio
    async def test_explore_label_not_found(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=None)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await explore_label(mock_driver, "NonExistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_explore_style(self, mock_driver: MagicMock) -> None:
        expected = {
            "id": "Alternative Rock",
            "name": "Alternative Rock",
            "release_count": 2000,
            "artist_count": 400,
            "label_count": 100,
            "genre_count": 3,
        }
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=expected)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await explore_style(mock_driver, "Alternative Rock")
        assert result is not None
        assert result["artist_count"] == 400
        assert result["release_count"] == 2000
        assert result["genre_count"] == 3

    @pytest.mark.asyncio
    async def test_explore_style_not_found(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=None)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await explore_style(mock_driver, "NonExistent")
        assert result is None


class TestExpandQueries:
    """Test expand query functions."""

    @pytest.mark.asyncio
    async def test_expand_artist_releases(self, mock_driver: MagicMock) -> None:
        expected = [
            {"id": "10", "name": "OK Computer", "type": "release", "year": 1997},
            {"id": "11", "name": "Kid A", "type": "release", "year": 2000},
        ]
        mock_session = mock_driver.session.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable(expected))

        results = await expand_artist_releases(mock_driver, "Radiohead", 50)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_expand_artist_labels(self, mock_driver: MagicMock) -> None:
        expected = [{"id": "200", "name": "Parlophone", "type": "label", "release_count": 10}]
        mock_session = mock_driver.session.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable(expected))

        results = await expand_artist_labels(mock_driver, "Radiohead", 50)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_expand_artist_aliases(self, mock_driver: MagicMock) -> None:
        expected = [{"id": "5", "name": "On a Friday", "type": "artist"}]
        mock_session = mock_driver.session.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable(expected))

        results = await expand_artist_aliases(mock_driver, "Radiohead", 50)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_expand_genre_artists(self, mock_driver: MagicMock) -> None:
        expected = [{"id": "1", "name": "Radiohead", "type": "artist"}]
        mock_session = mock_driver.session.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable(expected))

        results = await expand_genre_artists(mock_driver, "Rock", 50)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_expand_genre_labels(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable([]))

        results = await expand_genre_labels(mock_driver, "Rock", 50)
        assert results == []

    @pytest.mark.asyncio
    async def test_expand_genre_styles(self, mock_driver: MagicMock) -> None:
        expected = [{"id": "Alternative Rock", "name": "Alternative Rock", "type": "style", "artist_count": 500}]
        mock_session = mock_driver.session.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable(expected))

        results = await expand_genre_styles(mock_driver, "Rock", 50)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_expand_label_releases(self, mock_driver: MagicMock) -> None:
        expected = [{"id": "10", "name": "OK Computer", "type": "release", "year": 1997}]
        mock_session = mock_driver.session.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable(expected))

        results = await expand_label_releases(mock_driver, "Parlophone", 50)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_expand_label_artists(self, mock_driver: MagicMock) -> None:
        expected = [{"id": "1", "name": "Radiohead", "type": "artist", "release_count": 10}]
        mock_session = mock_driver.session.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable(expected))

        results = await expand_label_artists(mock_driver, "Parlophone", 50)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_expand_label_genres(self, mock_driver: MagicMock) -> None:
        expected = [{"id": "Rock", "name": "Rock", "type": "genre", "release_count": 200}]
        mock_session = mock_driver.session.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable(expected))

        results = await expand_label_genres(mock_driver, "Parlophone", 50)
        assert len(results) == 1
        assert results[0]["type"] == "genre"

    @pytest.mark.asyncio
    async def test_expand_genre_releases(self, mock_driver: MagicMock) -> None:
        expected = [{"id": "10", "name": "OK Computer", "type": "release", "year": 1997}]
        mock_session = mock_driver.session.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable(expected))

        results = await expand_genre_releases(mock_driver, "Rock", 50)
        assert len(results) == 1
        assert results[0]["type"] == "release"

    @pytest.mark.asyncio
    async def test_expand_style_artists(self, mock_driver: MagicMock) -> None:
        expected = [{"id": "1", "name": "Radiohead", "type": "artist"}]
        mock_session = mock_driver.session.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable(expected))

        results = await expand_style_artists(mock_driver, "Alternative Rock", 50)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_expand_style_labels(self, mock_driver: MagicMock) -> None:
        expected = [{"id": "100", "name": "Parlophone", "type": "label", "release_count": 15}]
        mock_session = mock_driver.session.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable(expected))

        results = await expand_style_labels(mock_driver, "Alternative Rock", 50)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_expand_style_genres(self, mock_driver: MagicMock) -> None:
        expected = [{"id": "Rock", "name": "Rock", "type": "genre", "release_count": 500}]
        mock_session = mock_driver.session.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable(expected))

        results = await expand_style_genres(mock_driver, "Alternative Rock", 50)
        assert len(results) == 1
        assert results[0]["type"] == "genre"

    @pytest.mark.asyncio
    async def test_expand_style_releases(self, mock_driver: MagicMock) -> None:
        expected = [{"id": "10", "name": "OK Computer", "type": "release", "year": 1997}]
        mock_session = mock_driver.session.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable(expected))

        results = await expand_style_releases(mock_driver, "Alternative Rock", 50)
        assert len(results) == 1
        assert results[0]["type"] == "release"


class TestNodeDetailsQueries:
    """Test node details query functions."""

    @pytest.mark.asyncio
    async def test_get_artist_details_found(self, mock_driver: MagicMock) -> None:
        expected = {
            "id": "1",
            "name": "Radiohead",
            "genres": ["Rock", "Electronic"],
            "styles": ["Alternative Rock"],
            "release_count": 42,
            "groups": [],
        }
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=expected)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await get_artist_details(mock_driver, "1")
        assert result is not None
        assert result["name"] == "Radiohead"
        assert "genres" in result

    @pytest.mark.asyncio
    async def test_get_artist_details_not_found(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=None)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await get_artist_details(mock_driver, "nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_release_details(self, mock_driver: MagicMock) -> None:
        expected = {
            "id": "10",
            "name": "OK Computer",
            "year": 1997,
            "country": "UK",
            "artists": ["Radiohead"],
            "labels": ["Parlophone"],
            "genres": ["Rock"],
            "styles": ["Alternative Rock"],
        }
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=expected)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await get_release_details(mock_driver, "10")
        assert result is not None
        assert result["year"] == 1997

    @pytest.mark.asyncio
    async def test_get_label_details(self, mock_driver: MagicMock) -> None:
        expected = {"id": "100", "name": "Warp Records", "release_count": 500}
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=expected)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await get_label_details(mock_driver, "100")
        assert result is not None
        assert result["release_count"] == 500

    @pytest.mark.asyncio
    async def test_get_genre_details(self, mock_driver: MagicMock) -> None:
        expected = {"id": "Rock", "name": "Rock", "artist_count": 1000}
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=expected)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await get_genre_details(mock_driver, "Rock")
        assert result is not None
        assert result["artist_count"] == 1000

    @pytest.mark.asyncio
    async def test_get_release_details_not_found(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=None)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await get_release_details(mock_driver, "nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_label_details_not_found(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=None)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await get_label_details(mock_driver, "nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_genre_details_not_found(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=None)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await get_genre_details(mock_driver, "nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_style_details(self, mock_driver: MagicMock) -> None:
        expected = {"id": "Alternative Rock", "name": "Alternative Rock", "artist_count": 400}
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=expected)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await get_style_details(mock_driver, "Alternative Rock")
        assert result is not None
        assert result["artist_count"] == 400

    @pytest.mark.asyncio
    async def test_get_style_details_not_found(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=None)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await get_style_details(mock_driver, "nonexistent")
        assert result is None


class TestTrendsQueries:
    """Test trends query functions."""

    @pytest.mark.asyncio
    async def test_trends_artist(self, mock_driver: MagicMock) -> None:
        expected = [
            {"year": 1993, "count": 1},
            {"year": 1997, "count": 1},
            {"year": 2000, "count": 1},
        ]
        mock_session = mock_driver.session.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable(expected))

        results = await trends_artist(mock_driver, "Radiohead")
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_trends_genre(self, mock_driver: MagicMock) -> None:
        expected = [{"year": 2000, "count": 100}]
        mock_session = mock_driver.session.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable(expected))

        results = await trends_genre(mock_driver, "Rock")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_trends_label(self, mock_driver: MagicMock) -> None:
        expected = [{"year": 1990, "count": 50}, {"year": 2000, "count": 100}]
        mock_session = mock_driver.session.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable(expected))

        results = await trends_label(mock_driver, "Warp Records")
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_trends_empty(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable([]))

        results = await trends_artist(mock_driver, "Unknown")
        assert results == []

    @pytest.mark.asyncio
    async def test_trends_style(self, mock_driver: MagicMock) -> None:
        expected = [{"year": 1991, "count": 5}, {"year": 1994, "count": 20}]
        mock_session = mock_driver.session.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable(expected))

        results = await trends_style(mock_driver, "Alternative Rock")
        assert len(results) == 2
        assert results[0]["year"] == 1991


class TestCountQueries:
    """Test count query functions (used for pagination totals)."""

    @pytest.mark.asyncio
    async def test_count_artist_releases(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value={"total": 42})
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await count_artist_releases(mock_driver, "Radiohead")
        assert result == 42

    @pytest.mark.asyncio
    async def test_count_artist_releases_not_found(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=None)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await count_artist_releases(mock_driver, "NonExistent")
        assert result == 0

    @pytest.mark.asyncio
    async def test_count_artist_labels(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value={"total": 5})
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await count_artist_labels(mock_driver, "Radiohead")
        assert result == 5

    @pytest.mark.asyncio
    async def test_count_artist_labels_not_found(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=None)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await count_artist_labels(mock_driver, "NonExistent")
        assert result == 0

    @pytest.mark.asyncio
    async def test_count_artist_aliases(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value={"total": 3})
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await count_artist_aliases(mock_driver, "Radiohead")
        assert result == 3

    @pytest.mark.asyncio
    async def test_count_artist_aliases_not_found(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=None)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await count_artist_aliases(mock_driver, "NonExistent")
        assert result == 0

    @pytest.mark.asyncio
    async def test_count_genre_artists(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value={"total": 1000})
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await count_genre_artists(mock_driver, "Rock")
        assert result == 1000

    @pytest.mark.asyncio
    async def test_count_genre_artists_not_found(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=None)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await count_genre_artists(mock_driver, "NonExistent")
        assert result == 0

    @pytest.mark.asyncio
    async def test_count_genre_labels(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value={"total": 200})
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await count_genre_labels(mock_driver, "Rock")
        assert result == 200

    @pytest.mark.asyncio
    async def test_count_genre_labels_not_found(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=None)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await count_genre_labels(mock_driver, "NonExistent")
        assert result == 0

    @pytest.mark.asyncio
    async def test_count_genre_styles(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value={"total": 50})
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await count_genre_styles(mock_driver, "Rock")
        assert result == 50

    @pytest.mark.asyncio
    async def test_count_genre_styles_not_found(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=None)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await count_genre_styles(mock_driver, "NonExistent")
        assert result == 0

    @pytest.mark.asyncio
    async def test_count_genre_releases(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value={"total": 5000})
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await count_genre_releases(mock_driver, "Rock")
        assert result == 5000

    @pytest.mark.asyncio
    async def test_count_genre_releases_not_found(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=None)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await count_genre_releases(mock_driver, "NonExistent")
        assert result == 0

    @pytest.mark.asyncio
    async def test_count_label_releases(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value={"total": 500})
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await count_label_releases(mock_driver, "Warp Records")
        assert result == 500

    @pytest.mark.asyncio
    async def test_count_label_releases_not_found(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=None)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await count_label_releases(mock_driver, "NonExistent")
        assert result == 0

    @pytest.mark.asyncio
    async def test_count_label_artists(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value={"total": 120})
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await count_label_artists(mock_driver, "Warp Records")
        assert result == 120

    @pytest.mark.asyncio
    async def test_count_label_artists_not_found(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=None)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await count_label_artists(mock_driver, "NonExistent")
        assert result == 0

    @pytest.mark.asyncio
    async def test_count_label_genres(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value={"total": 8})
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await count_label_genres(mock_driver, "Warp Records")
        assert result == 8

    @pytest.mark.asyncio
    async def test_count_label_genres_not_found(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=None)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await count_label_genres(mock_driver, "NonExistent")
        assert result == 0

    @pytest.mark.asyncio
    async def test_count_style_artists(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value={"total": 400})
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await count_style_artists(mock_driver, "Alternative Rock")
        assert result == 400

    @pytest.mark.asyncio
    async def test_count_style_artists_not_found(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=None)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await count_style_artists(mock_driver, "NonExistent")
        assert result == 0

    @pytest.mark.asyncio
    async def test_count_style_labels(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value={"total": 75})
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await count_style_labels(mock_driver, "Alternative Rock")
        assert result == 75

    @pytest.mark.asyncio
    async def test_count_style_labels_not_found(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=None)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await count_style_labels(mock_driver, "NonExistent")
        assert result == 0

    @pytest.mark.asyncio
    async def test_count_style_genres(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value={"total": 3})
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await count_style_genres(mock_driver, "Alternative Rock")
        assert result == 3

    @pytest.mark.asyncio
    async def test_count_style_genres_not_found(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=None)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await count_style_genres(mock_driver, "NonExistent")
        assert result == 0

    @pytest.mark.asyncio
    async def test_count_style_releases(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value={"total": 2000})
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await count_style_releases(mock_driver, "Alternative Rock")
        assert result == 2000

    @pytest.mark.asyncio
    async def test_count_style_releases_not_found(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=None)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await count_style_releases(mock_driver, "NonExistent")
        assert result == 0
