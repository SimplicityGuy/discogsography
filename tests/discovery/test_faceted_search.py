"""Tests for FacetedSearchEngine class."""

from collections import Counter
from unittest.mock import AsyncMock, MagicMock

import pytest

from discovery.faceted_search import FacetedSearchEngine, FacetType


class TestFacetedSearchEngineInit:
    """Test FacetedSearchEngine initialization."""

    def test_initialization(self) -> None:
        """Test engine initializes with correct default values."""
        mock_conn = MagicMock()
        engine = FacetedSearchEngine(mock_conn)

        assert engine.db_conn == mock_conn
        assert engine.facet_cache == {}


class TestSearchWithFacets:
    """Test main search_with_facets method."""

    @pytest.mark.asyncio
    async def test_search_artists_basic(self) -> None:
        """Test basic artist search without facets."""
        mock_conn = MagicMock()
        engine = FacetedSearchEngine(mock_conn)

        # Mock the artist search method
        engine._search_artists_with_facets = AsyncMock(
            return_value=(
                [{"id": 1, "name": "Test Artist"}],
                {FacetType.GENRE: [{"value": "Rock", "count": 1}]},
            )
        )

        result = await engine.search_with_facets("test", entity_type="artist")

        assert result["query"] == "test"
        assert result["total"] == 1
        assert len(result["results"]) == 1
        assert result["results"][0]["name"] == "Test Artist"
        assert FacetType.GENRE in result["facets"]

    @pytest.mark.asyncio
    async def test_search_releases_basic(self) -> None:
        """Test basic release search."""
        mock_conn = MagicMock()
        engine = FacetedSearchEngine(mock_conn)

        engine._search_releases_with_facets = AsyncMock(
            return_value=(
                [{"id": 1, "title": "Test Album", "year": 2020}],
                {FacetType.YEAR: [{"value": "2020", "count": 1}]},
            )
        )

        result = await engine.search_with_facets("album", entity_type="release")

        assert result["query"] == "album"
        assert result["total"] == 1
        assert result["results"][0]["title"] == "Test Album"

    @pytest.mark.asyncio
    async def test_search_unknown_entity_type(self) -> None:
        """Test search with unknown entity type returns empty results."""
        mock_conn = MagicMock()
        engine = FacetedSearchEngine(mock_conn)

        result = await engine.search_with_facets("test", entity_type="unknown")

        assert result["results"] == []
        assert result["facets"] == {}
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_search_with_selected_facets(self) -> None:
        """Test search with selected facets."""
        mock_conn = MagicMock()
        engine = FacetedSearchEngine(mock_conn)

        selected_facets = {FacetType.GENRE: ["Rock", "Jazz"]}
        engine._search_artists_with_facets = AsyncMock(return_value=([], {}))

        result = await engine.search_with_facets(
            "test",
            entity_type="artist",
            selected_facets=selected_facets,
        )

        assert result["selected_facets"] == selected_facets
        engine._search_artists_with_facets.assert_called_once()


class TestSearchArtistsWithFacets:
    """Test artist search functionality."""

    @pytest.mark.asyncio
    async def test_search_artists_no_facets(self) -> None:
        """Test artist search without facet filters."""
        mock_conn = MagicMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall.return_value = [{"id": 1, "name": "Artist A"}]

        # Mock cursor context manager
        cursor_context = MagicMock()
        cursor_context.__aenter__ = AsyncMock(return_value=mock_cursor)
        cursor_context.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor.return_value = cursor_context

        engine = FacetedSearchEngine(mock_conn)
        engine._compute_facets_for_artists = AsyncMock(return_value={})

        results, _facets = await engine._search_artists_with_facets(
            "artist",
            {},
            [FacetType.GENRE],
            limit=50,
            offset=0,
        )

        assert len(results) == 1
        assert results[0]["name"] == "Artist A"
        mock_cursor.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_artists_with_genre_filter(self) -> None:
        """Test artist search with genre facet filter."""
        mock_conn = MagicMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall.return_value = [{"id": 1, "name": "Rock Artist"}]

        cursor_context = MagicMock()
        cursor_context.__aenter__ = AsyncMock(return_value=mock_cursor)
        cursor_context.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor.return_value = cursor_context

        engine = FacetedSearchEngine(mock_conn)
        engine._compute_facets_for_artists = AsyncMock(return_value={})

        selected_facets = {FacetType.GENRE: ["Rock"]}
        results, _facets = await engine._search_artists_with_facets(
            "artist",
            selected_facets,
            [FacetType.GENRE],
            limit=50,
            offset=0,
        )

        assert len(results) == 1
        # Verify SQL includes genre filter
        call_args = mock_cursor.execute.call_args
        assert "g.name IN" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_search_artists_with_multiple_facets(self) -> None:
        """Test artist search with multiple facet filters."""
        mock_conn = MagicMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall.return_value = []

        cursor_context = MagicMock()
        cursor_context.__aenter__ = AsyncMock(return_value=mock_cursor)
        cursor_context.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor.return_value = cursor_context

        engine = FacetedSearchEngine(mock_conn)
        engine._compute_facets_for_artists = AsyncMock(return_value={})

        selected_facets = {
            FacetType.GENRE: ["Rock"],
            FacetType.STYLE: ["Alternative"],
        }

        _results, _facets = await engine._search_artists_with_facets(
            "test",
            selected_facets,
            [FacetType.GENRE, FacetType.STYLE],
            limit=50,
            offset=0,
        )

        # Verify multiple joins and filters
        call_args = mock_cursor.execute.call_args
        sql = call_args[0][0]
        assert "LEFT JOIN artist_genres" in sql
        assert "LEFT JOIN artist_styles" in sql


class TestSearchReleasesWithFacets:
    """Test release search functionality."""

    @pytest.mark.asyncio
    async def test_search_releases_basic(self) -> None:
        """Test basic release search."""
        mock_conn = MagicMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall.return_value = [{"id": 1, "title": "Album", "year": 2020}]

        cursor_context = MagicMock()
        cursor_context.__aenter__ = AsyncMock(return_value=mock_cursor)
        cursor_context.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor.return_value = cursor_context

        engine = FacetedSearchEngine(mock_conn)
        engine._compute_facets_for_releases = AsyncMock(return_value={})

        results, _facets = await engine._search_releases_with_facets(
            "album",
            {},
            [FacetType.YEAR],
            limit=50,
            offset=0,
        )

        assert len(results) == 1
        assert results[0]["title"] == "Album"

    @pytest.mark.asyncio
    async def test_search_releases_with_year_filter(self) -> None:
        """Test release search with year filter."""
        mock_conn = MagicMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall.return_value = []

        cursor_context = MagicMock()
        cursor_context.__aenter__ = AsyncMock(return_value=mock_cursor)
        cursor_context.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor.return_value = cursor_context

        engine = FacetedSearchEngine(mock_conn)
        engine._compute_facets_for_releases = AsyncMock(return_value={})

        selected_facets = {FacetType.YEAR: ["2020", "2021"]}
        _results, _facets = await engine._search_releases_with_facets(
            "test",
            selected_facets,
            [FacetType.YEAR],
            limit=50,
            offset=0,
        )

        # Verify year filter in SQL
        call_args = mock_cursor.execute.call_args
        assert "r.year IN" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_search_releases_with_decade_filter(self) -> None:
        """Test release search with decade filter."""
        mock_conn = MagicMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall.return_value = []

        cursor_context = MagicMock()
        cursor_context.__aenter__ = AsyncMock(return_value=mock_cursor)
        cursor_context.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor.return_value = cursor_context

        engine = FacetedSearchEngine(mock_conn)
        engine._compute_facets_for_releases = AsyncMock(return_value={})

        selected_facets = {FacetType.DECADE: ["1990"]}
        _results, _facets = await engine._search_releases_with_facets(
            "test",
            selected_facets,
            [FacetType.DECADE],
            limit=50,
            offset=0,
        )

        # Verify decade range filter
        call_args = mock_cursor.execute.call_args
        sql = call_args[0][0]
        assert "r.year >=" in sql
        assert "r.year <" in sql


class TestComputeFacetsForArtists:
    """Test facet computation for artists."""

    @pytest.mark.asyncio
    async def test_compute_facets_empty_results(self) -> None:
        """Test facet computation with empty results."""
        mock_conn = MagicMock()
        engine = FacetedSearchEngine(mock_conn)

        facets = await engine._compute_facets_for_artists([], [FacetType.GENRE])

        assert facets == {}

    @pytest.mark.asyncio
    async def test_compute_genre_facets(self) -> None:
        """Test computing genre facets for artists."""
        mock_conn = MagicMock()
        engine = FacetedSearchEngine(mock_conn)

        artists = [{"id": 1, "name": "Artist A"}, {"id": 2, "name": "Artist B"}]
        engine._get_genre_counts_for_artists = AsyncMock(return_value=Counter({"Rock": 5, "Jazz": 3}))

        facets = await engine._compute_facets_for_artists(
            artists,
            [FacetType.GENRE],
        )

        assert FacetType.GENRE in facets
        assert len(facets[FacetType.GENRE]) == 2
        assert facets[FacetType.GENRE][0]["value"] == "Rock"
        assert facets[FacetType.GENRE][0]["count"] == 5

    @pytest.mark.asyncio
    async def test_compute_multiple_artist_facets(self) -> None:
        """Test computing multiple facet types for artists."""
        mock_conn = MagicMock()
        engine = FacetedSearchEngine(mock_conn)

        artists = [{"id": 1, "name": "Artist"}]
        engine._get_genre_counts_for_artists = AsyncMock(return_value=Counter({"Rock": 1}))
        engine._get_style_counts_for_artists = AsyncMock(return_value=Counter({"Alternative": 1}))
        engine._get_label_counts_for_artists = AsyncMock(return_value=Counter({"Label A": 1}))

        facets = await engine._compute_facets_for_artists(
            artists,
            [FacetType.GENRE, FacetType.STYLE, FacetType.LABEL],
        )

        assert len(facets) == 3
        assert FacetType.GENRE in facets
        assert FacetType.STYLE in facets
        assert FacetType.LABEL in facets


class TestComputeFacetsForReleases:
    """Test facet computation for releases."""

    @pytest.mark.asyncio
    async def test_compute_facets_empty_results(self) -> None:
        """Test facet computation with empty results."""
        mock_conn = MagicMock()
        engine = FacetedSearchEngine(mock_conn)

        facets = await engine._compute_facets_for_releases([], [FacetType.YEAR])

        assert facets == {}

    @pytest.mark.asyncio
    async def test_compute_year_facets(self) -> None:
        """Test computing year facets for releases."""
        mock_conn = MagicMock()
        engine = FacetedSearchEngine(mock_conn)

        releases = [
            {"id": 1, "title": "Album 1", "year": 2020},
            {"id": 2, "title": "Album 2", "year": 2020},
            {"id": 3, "title": "Album 3", "year": 2019},
        ]

        facets = await engine._compute_facets_for_releases(
            releases,
            [FacetType.YEAR],
        )

        assert FacetType.YEAR in facets
        assert len(facets[FacetType.YEAR]) == 2
        # Should be sorted by year descending
        assert facets[FacetType.YEAR][0]["value"] == "2020"
        assert facets[FacetType.YEAR][0]["count"] == 2

    @pytest.mark.asyncio
    async def test_compute_decade_facets(self) -> None:
        """Test computing decade facets for releases."""
        mock_conn = MagicMock()
        engine = FacetedSearchEngine(mock_conn)

        releases = [
            {"id": 1, "year": 1995},
            {"id": 2, "year": 1998},
            {"id": 3, "year": 2005},
        ]

        facets = await engine._compute_facets_for_releases(
            releases,
            [FacetType.DECADE],
        )

        assert FacetType.DECADE in facets
        assert len(facets[FacetType.DECADE]) == 2
        # Check decade grouping
        decade_values = {f["value"] for f in facets[FacetType.DECADE]}
        assert "1990s" in decade_values
        assert "2000s" in decade_values


class TestGetFacetCounts:
    """Test facet count retrieval methods."""

    @pytest.mark.asyncio
    async def test_get_genre_counts_empty_ids(self) -> None:
        """Test genre counts with empty artist IDs."""
        mock_conn = MagicMock()
        engine = FacetedSearchEngine(mock_conn)

        counts = await engine._get_genre_counts_for_artists([])

        assert counts == Counter()

    @pytest.mark.asyncio
    async def test_get_genre_counts_for_artists(self) -> None:
        """Test getting genre counts for artists."""
        mock_conn = MagicMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall.return_value = [
            {"name": "Rock", "count": 5},
            {"name": "Jazz", "count": 3},
        ]

        cursor_context = MagicMock()
        cursor_context.__aenter__ = AsyncMock(return_value=mock_cursor)
        cursor_context.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor.return_value = cursor_context

        engine = FacetedSearchEngine(mock_conn)
        counts = await engine._get_genre_counts_for_artists([1, 2, 3])

        assert counts["Rock"] == 5
        assert counts["Jazz"] == 3

    @pytest.mark.asyncio
    async def test_get_style_counts_empty_ids(self) -> None:
        """Test style counts with empty artist IDs."""
        mock_conn = MagicMock()
        engine = FacetedSearchEngine(mock_conn)

        counts = await engine._get_style_counts_for_artists([])

        assert counts == Counter()

    @pytest.mark.asyncio
    async def test_get_label_counts_empty_ids(self) -> None:
        """Test label counts with empty artist IDs."""
        mock_conn = MagicMock()
        engine = FacetedSearchEngine(mock_conn)

        counts = await engine._get_label_counts_for_artists([])

        assert counts == Counter()


class TestGetAvailableFacets:
    """Test get_available_facets method."""

    @pytest.mark.asyncio
    async def test_get_available_artist_facets(self) -> None:
        """Test getting available facets for artists."""
        mock_conn = MagicMock()
        mock_cursor = AsyncMock()

        # Mock three separate query results
        mock_cursor.fetchall.side_effect = [
            [{"name": "Rock"}, {"name": "Jazz"}],  # Genres
            [{"name": "Alternative"}],  # Styles
            [{"name": "Label A"}],  # Labels
        ]

        cursor_context = MagicMock()
        cursor_context.__aenter__ = AsyncMock(return_value=mock_cursor)
        cursor_context.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor.return_value = cursor_context

        engine = FacetedSearchEngine(mock_conn)
        facets = await engine.get_available_facets(entity_type="artist")

        assert FacetType.GENRE in facets
        assert FacetType.STYLE in facets
        assert FacetType.LABEL in facets
        assert "Rock" in facets[FacetType.GENRE]
        assert "Jazz" in facets[FacetType.GENRE]

    @pytest.mark.asyncio
    async def test_get_available_release_facets(self) -> None:
        """Test getting available facets for releases."""
        mock_conn = MagicMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall.return_value = [{"year": 2020}, {"year": 2019}]

        cursor_context = MagicMock()
        cursor_context.__aenter__ = AsyncMock(return_value=mock_cursor)
        cursor_context.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor.return_value = cursor_context

        engine = FacetedSearchEngine(mock_conn)
        facets = await engine.get_available_facets(entity_type="release")

        assert FacetType.YEAR in facets
        assert "2020" in facets[FacetType.YEAR]
        assert "2019" in facets[FacetType.YEAR]
