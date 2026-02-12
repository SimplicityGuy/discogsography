"""Tests for Explore service Neo4j query functions."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from explore.neo4j_queries import (
    AUTOCOMPLETE_DISPATCH,
    DETAILS_DISPATCH,
    EXPAND_DISPATCH,
    EXPLORE_DISPATCH,
    TRENDS_DISPATCH,
    autocomplete_artist,
    autocomplete_genre,
    autocomplete_label,
    expand_artist_aliases,
    expand_artist_labels,
    expand_artist_releases,
    expand_genre_artists,
    expand_genre_labels,
    expand_genre_styles,
    expand_label_artists,
    expand_label_releases,
    explore_artist,
    explore_genre,
    explore_label,
    get_artist_details,
    get_genre_details,
    get_label_details,
    get_release_details,
    trends_artist,
    trends_genre,
    trends_label,
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

    driver.session = MagicMock(return_value=mock_session)
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
        assert set(AUTOCOMPLETE_DISPATCH.keys()) == {"artist", "genre", "label"}

    def test_explore_dispatch_keys(self) -> None:
        assert set(EXPLORE_DISPATCH.keys()) == {"artist", "genre", "label"}

    def test_expand_dispatch_keys(self) -> None:
        assert set(EXPAND_DISPATCH.keys()) == {"artist", "genre", "label"}
        assert set(EXPAND_DISPATCH["artist"].keys()) == {"releases", "labels", "aliases"}
        assert set(EXPAND_DISPATCH["genre"].keys()) == {"artists", "labels", "styles"}
        assert set(EXPAND_DISPATCH["label"].keys()) == {"releases", "artists"}

    def test_details_dispatch_keys(self) -> None:
        assert set(DETAILS_DISPATCH.keys()) == {"artist", "release", "label", "genre", "style"}

    def test_trends_dispatch_keys(self) -> None:
        assert set(TRENDS_DISPATCH.keys()) == {"artist", "genre", "label"}

    def test_autocomplete_dispatch_functions(self) -> None:
        assert AUTOCOMPLETE_DISPATCH["artist"] is autocomplete_artist
        assert AUTOCOMPLETE_DISPATCH["genre"] is autocomplete_genre
        assert AUTOCOMPLETE_DISPATCH["label"] is autocomplete_label

    def test_explore_dispatch_functions(self) -> None:
        assert EXPLORE_DISPATCH["artist"] is explore_artist
        assert EXPLORE_DISPATCH["genre"] is explore_genre
        assert EXPLORE_DISPATCH["label"] is explore_label

    def test_expand_dispatch_functions(self) -> None:
        assert EXPAND_DISPATCH["artist"]["releases"] is expand_artist_releases
        assert EXPAND_DISPATCH["artist"]["labels"] is expand_artist_labels
        assert EXPAND_DISPATCH["artist"]["aliases"] is expand_artist_aliases
        assert EXPAND_DISPATCH["genre"]["artists"] is expand_genre_artists
        assert EXPAND_DISPATCH["genre"]["labels"] is expand_genre_labels
        assert EXPAND_DISPATCH["genre"]["styles"] is expand_genre_styles
        assert EXPAND_DISPATCH["label"]["releases"] is expand_label_releases
        assert EXPAND_DISPATCH["label"]["artists"] is expand_label_artists


class TestAutocompleteQueries:
    """Test autocomplete query functions."""

    @pytest.mark.asyncio
    async def test_autocomplete_artist(self, mock_driver: MagicMock) -> None:
        expected = [{"id": "1", "name": "Radiohead", "score": 9.5}]
        mock_session = mock_driver.session().__aenter__.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable(expected))

        results = await autocomplete_artist(mock_driver, "radio", 10)
        assert len(results) == 1
        assert results[0]["name"] == "Radiohead"

    @pytest.mark.asyncio
    async def test_autocomplete_label(self, mock_driver: MagicMock) -> None:
        expected = [{"id": "100", "name": "Warp Records", "score": 9.0}]
        mock_session = mock_driver.session().__aenter__.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable(expected))

        results = await autocomplete_label(mock_driver, "warp", 10)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_autocomplete_genre(self, mock_driver: MagicMock) -> None:
        expected = [{"id": "Rock", "name": "Rock", "score": 1.0}]
        mock_session = mock_driver.session().__aenter__.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable(expected))

        results = await autocomplete_genre(mock_driver, "rock", 10)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_autocomplete_empty(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session().__aenter__.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable([]))

        results = await autocomplete_artist(mock_driver, "zzzzz", 10)
        assert results == []


class TestExploreQueries:
    """Test explore query functions."""

    @pytest.mark.asyncio
    async def test_explore_artist_found(self, mock_driver: MagicMock) -> None:
        expected = {"id": "1", "name": "Radiohead", "release_count": 42, "label_count": 5, "alias_count": 2}
        mock_session = mock_driver.session().__aenter__.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=expected)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await explore_artist(mock_driver, "Radiohead")
        assert result is not None
        assert result["name"] == "Radiohead"
        assert result["release_count"] == 42

    @pytest.mark.asyncio
    async def test_explore_artist_not_found(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session().__aenter__.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=None)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await explore_artist(mock_driver, "NonExistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_explore_genre(self, mock_driver: MagicMock) -> None:
        expected = {"id": "Rock", "name": "Rock", "artist_count": 1000, "label_count": 200, "style_count": 50}
        mock_session = mock_driver.session().__aenter__.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=expected)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await explore_genre(mock_driver, "Rock")
        assert result is not None
        assert result["artist_count"] == 1000

    @pytest.mark.asyncio
    async def test_explore_label(self, mock_driver: MagicMock) -> None:
        expected = {"id": "100", "name": "Warp Records", "release_count": 500, "artist_count": 120}
        mock_session = mock_driver.session().__aenter__.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=expected)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await explore_label(mock_driver, "Warp Records")
        assert result is not None
        assert result["release_count"] == 500


class TestExpandQueries:
    """Test expand query functions."""

    @pytest.mark.asyncio
    async def test_expand_artist_releases(self, mock_driver: MagicMock) -> None:
        expected = [
            {"id": "10", "name": "OK Computer", "type": "release", "year": 1997},
            {"id": "11", "name": "Kid A", "type": "release", "year": 2000},
        ]
        mock_session = mock_driver.session().__aenter__.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable(expected))

        results = await expand_artist_releases(mock_driver, "Radiohead", 50)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_expand_artist_labels(self, mock_driver: MagicMock) -> None:
        expected = [{"id": "200", "name": "Parlophone", "type": "label", "release_count": 10}]
        mock_session = mock_driver.session().__aenter__.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable(expected))

        results = await expand_artist_labels(mock_driver, "Radiohead", 50)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_expand_artist_aliases(self, mock_driver: MagicMock) -> None:
        expected = [{"id": "5", "name": "On a Friday", "type": "artist"}]
        mock_session = mock_driver.session().__aenter__.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable(expected))

        results = await expand_artist_aliases(mock_driver, "Radiohead", 50)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_expand_genre_artists(self, mock_driver: MagicMock) -> None:
        expected = [{"id": "1", "name": "Radiohead", "type": "artist"}]
        mock_session = mock_driver.session().__aenter__.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable(expected))

        results = await expand_genre_artists(mock_driver, "Rock", 50)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_expand_genre_labels(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session().__aenter__.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable([]))

        results = await expand_genre_labels(mock_driver, "Rock", 50)
        assert results == []

    @pytest.mark.asyncio
    async def test_expand_genre_styles(self, mock_driver: MagicMock) -> None:
        expected = [{"id": "Alternative Rock", "name": "Alternative Rock", "type": "style", "artist_count": 500}]
        mock_session = mock_driver.session().__aenter__.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable(expected))

        results = await expand_genre_styles(mock_driver, "Rock", 50)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_expand_label_releases(self, mock_driver: MagicMock) -> None:
        expected = [{"id": "10", "name": "OK Computer", "type": "release", "year": 1997}]
        mock_session = mock_driver.session().__aenter__.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable(expected))

        results = await expand_label_releases(mock_driver, "Parlophone", 50)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_expand_label_artists(self, mock_driver: MagicMock) -> None:
        expected = [{"id": "1", "name": "Radiohead", "type": "artist", "release_count": 10}]
        mock_session = mock_driver.session().__aenter__.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable(expected))

        results = await expand_label_artists(mock_driver, "Parlophone", 50)
        assert len(results) == 1


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
        mock_session = mock_driver.session().__aenter__.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=expected)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await get_artist_details(mock_driver, "1")
        assert result is not None
        assert result["name"] == "Radiohead"
        assert "genres" in result

    @pytest.mark.asyncio
    async def test_get_artist_details_not_found(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session().__aenter__.return_value
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
        mock_session = mock_driver.session().__aenter__.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=expected)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await get_release_details(mock_driver, "10")
        assert result is not None
        assert result["year"] == 1997

    @pytest.mark.asyncio
    async def test_get_label_details(self, mock_driver: MagicMock) -> None:
        expected = {"id": "100", "name": "Warp Records", "release_count": 500}
        mock_session = mock_driver.session().__aenter__.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=expected)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await get_label_details(mock_driver, "100")
        assert result is not None
        assert result["release_count"] == 500

    @pytest.mark.asyncio
    async def test_get_genre_details(self, mock_driver: MagicMock) -> None:
        expected = {"id": "Rock", "name": "Rock", "artist_count": 1000}
        mock_session = mock_driver.session().__aenter__.return_value
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=expected)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await get_genre_details(mock_driver, "Rock")
        assert result is not None
        assert result["artist_count"] == 1000


class TestTrendsQueries:
    """Test trends query functions."""

    @pytest.mark.asyncio
    async def test_trends_artist(self, mock_driver: MagicMock) -> None:
        expected = [
            {"year": 1993, "count": 1},
            {"year": 1997, "count": 1},
            {"year": 2000, "count": 1},
        ]
        mock_session = mock_driver.session().__aenter__.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable(expected))

        results = await trends_artist(mock_driver, "Radiohead")
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_trends_genre(self, mock_driver: MagicMock) -> None:
        expected = [{"year": 2000, "count": 100}]
        mock_session = mock_driver.session().__aenter__.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable(expected))

        results = await trends_genre(mock_driver, "Rock")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_trends_label(self, mock_driver: MagicMock) -> None:
        expected = [{"year": 1990, "count": 50}, {"year": 2000, "count": 100}]
        mock_session = mock_driver.session().__aenter__.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable(expected))

        results = await trends_label(mock_driver, "Warp Records")
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_trends_empty(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session().__aenter__.return_value
        mock_session.run = AsyncMock(return_value=_make_async_iterable([]))

        results = await trends_artist(mock_driver, "Unknown")
        assert results == []
