"""Tests for discovery/fulltext_search.py module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from discovery.fulltext_search import (
    FullTextSearch,
    SearchEntity,
    SearchOperator,
)


class TestFullTextSearch:
    """Tests for FullTextSearch functionality."""

    @pytest.fixture
    def mock_db_conn(self):
        """Create mock database connection."""
        conn = AsyncMock()
        conn.cursor = MagicMock()
        return conn

    @pytest.fixture
    def search_engine(self, mock_db_conn):
        """Create FullTextSearch instance."""
        return FullTextSearch(mock_db_conn)

    # ==================== Initialization ====================

    def test_initialization(self, mock_db_conn):
        """Test FullTextSearch initialization."""
        engine = FullTextSearch(mock_db_conn)
        assert engine.db_conn == mock_db_conn

    # ==================== _build_tsquery Tests ====================

    def test_build_tsquery_empty_query(self, search_engine):
        """Test _build_tsquery with empty query."""
        result = search_engine._build_tsquery("", SearchOperator.AND)
        assert result == ""

        result = search_engine._build_tsquery("   ", SearchOperator.AND)
        assert result == ""

    def test_build_tsquery_and_operator(self, search_engine):
        """Test _build_tsquery with AND operator."""
        result = search_engine._build_tsquery("rock metal", SearchOperator.AND)
        assert result == "rock & metal"

        result = search_engine._build_tsquery("one two three", SearchOperator.AND)
        assert result == "one & two & three"

    def test_build_tsquery_or_operator(self, search_engine):
        """Test _build_tsquery with OR operator."""
        result = search_engine._build_tsquery("rock metal", SearchOperator.OR)
        assert result == "rock | metal"

        result = search_engine._build_tsquery("jazz blues", SearchOperator.OR)
        assert result == "jazz | blues"

    def test_build_tsquery_phrase_operator(self, search_engine):
        """Test _build_tsquery with PHRASE operator."""
        result = search_engine._build_tsquery("pink floyd", SearchOperator.PHRASE)
        assert result == "pink <-> floyd"

        result = search_engine._build_tsquery("led zeppelin", SearchOperator.PHRASE)
        assert result == "led <-> zeppelin"

    def test_build_tsquery_proximity_operator(self, search_engine):
        """Test _build_tsquery with PROXIMITY operator."""
        result = search_engine._build_tsquery("rock band", SearchOperator.PROXIMITY)
        assert result == "rock <2> band"

    # ==================== Main search() Method Tests ====================

    @pytest.mark.asyncio
    async def test_search_all_entities(self, search_engine):
        """Test search with SearchEntity.ALL."""
        with patch.object(search_engine, "_search_all_entities", return_value=[{"id": 1, "name": "Test"}]) as mock_search:
            results = await search_engine.search("test query", SearchEntity.ALL)

            mock_search.assert_called_once()
            assert results == [{"id": 1, "name": "Test"}]

    @pytest.mark.asyncio
    async def test_search_artists_entity(self, search_engine):
        """Test search with SearchEntity.ARTIST."""
        with patch.object(search_engine, "_search_artists", return_value=[{"id": 1, "name": "Artist"}]) as mock_search:
            results = await search_engine.search("artist query", SearchEntity.ARTIST)

            mock_search.assert_called_once()
            assert results == [{"id": 1, "name": "Artist"}]

    @pytest.mark.asyncio
    async def test_search_releases_entity(self, search_engine):
        """Test search with SearchEntity.RELEASE."""
        with patch.object(search_engine, "_search_releases", return_value=[{"id": 1, "title": "Album"}]) as mock_search:
            results = await search_engine.search("album query", SearchEntity.RELEASE)

            mock_search.assert_called_once()
            assert results == [{"id": 1, "title": "Album"}]

    @pytest.mark.asyncio
    async def test_search_labels_entity(self, search_engine):
        """Test search with SearchEntity.LABEL."""
        with patch.object(search_engine, "_search_labels", return_value=[{"id": 1, "name": "Label"}]) as mock_search:
            results = await search_engine.search("label query", SearchEntity.LABEL)

            mock_search.assert_called_once()
            assert results == [{"id": 1, "name": "Label"}]

    @pytest.mark.asyncio
    async def test_search_masters_entity(self, search_engine):
        """Test search with SearchEntity.MASTER."""
        with patch.object(search_engine, "_search_masters", return_value=[{"id": 1, "title": "Master"}]) as mock_search:
            results = await search_engine.search("master query", SearchEntity.MASTER)

            mock_search.assert_called_once()
            assert results == [{"id": 1, "title": "Master"}]

    # ==================== _search_artists Tests ====================

    @pytest.mark.asyncio
    async def test_search_artists(self, search_engine, mock_db_conn):
        """Test _search_artists method."""
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(
            return_value=[
                {"id": 1, "name": "The Beatles", "rank": 0.9, "entity_type": "artist"},
                {"id": 2, "name": "Beatles Cover Band", "rank": 0.7, "entity_type": "artist"},
            ]
        )
        mock_db_conn.cursor.return_value.__aenter__.return_value = mock_cursor

        results = await search_engine._search_artists("beatles", 10, 0, 0.0)

        assert len(results) == 2
        assert results[0]["name"] == "The Beatles"
        assert results[0]["rank"] == 0.9
        mock_cursor.execute.assert_called_once()

    # ==================== _search_releases Tests ====================

    @pytest.mark.asyncio
    async def test_search_releases(self, search_engine, mock_db_conn):
        """Test _search_releases method."""
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(
            return_value=[
                {
                    "id": 1,
                    "title": "Abbey Road",
                    "year": 1969,
                    "rank": 0.95,
                    "entity_type": "release",
                }
            ]
        )
        mock_db_conn.cursor.return_value.__aenter__.return_value = mock_cursor

        results = await search_engine._search_releases("abbey road", 10, 0, 0.0)

        assert len(results) == 1
        assert results[0]["title"] == "Abbey Road"
        assert results[0]["year"] == 1969
        mock_cursor.execute.assert_called_once()

    # ==================== _search_labels Tests ====================

    @pytest.mark.asyncio
    async def test_search_labels(self, search_engine, mock_db_conn):
        """Test _search_labels method."""
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[{"id": 1, "name": "Apple Records", "rank": 0.88, "entity_type": "label"}])
        mock_db_conn.cursor.return_value.__aenter__.return_value = mock_cursor

        results = await search_engine._search_labels("apple", 10, 0, 0.0)

        assert len(results) == 1
        assert results[0]["name"] == "Apple Records"
        mock_cursor.execute.assert_called_once()

    # ==================== _search_masters Tests ====================

    @pytest.mark.asyncio
    async def test_search_masters(self, search_engine, mock_db_conn):
        """Test _search_masters method."""
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(
            return_value=[
                {
                    "id": 1,
                    "title": "Dark Side of the Moon",
                    "year": 1973,
                    "rank": 0.92,
                    "entity_type": "master",
                }
            ]
        )
        mock_db_conn.cursor.return_value.__aenter__.return_value = mock_cursor

        results = await search_engine._search_masters("dark side", 10, 0, 0.0)

        assert len(results) == 1
        assert results[0]["title"] == "Dark Side of the Moon"
        mock_cursor.execute.assert_called_once()

    # ==================== _search_all_entities Tests ====================

    @pytest.mark.asyncio
    async def test_internal_search_all_entities(self, search_engine):
        """Test _search_all_entities internal method."""
        # Mock all entity search methods
        with (
            patch.object(search_engine, "_search_artists", return_value=[{"id": 1, "rank": 0.9}]),
            patch.object(search_engine, "_search_releases", return_value=[{"id": 2, "rank": 0.8}]),
            patch.object(search_engine, "_search_labels", return_value=[{"id": 3, "rank": 0.7}]),
            patch.object(search_engine, "_search_masters", return_value=[{"id": 4, "rank": 0.6}]),
        ):
            results = await search_engine._search_all_entities("test", 50, 0, 0.0)

            # Should combine all results and sort by rank
            assert len(results) == 4
            assert results[0]["rank"] == 0.9  # Highest rank first
            assert results[-1]["rank"] == 0.6  # Lowest rank last

    @pytest.mark.asyncio
    async def test_search_all_entities_with_offset_limit(self, search_engine):
        """Test _search_all_entities with offset and limit."""
        # Mock all entity search methods with multiple results
        with (
            patch.object(
                search_engine,
                "_search_artists",
                return_value=[{"id": 1, "rank": 0.95}, {"id": 2, "rank": 0.85}],
            ),
            patch.object(
                search_engine,
                "_search_releases",
                return_value=[{"id": 3, "rank": 0.90}, {"id": 4, "rank": 0.80}],
            ),
            patch.object(search_engine, "_search_labels", return_value=[{"id": 5, "rank": 0.75}]),
            patch.object(search_engine, "_search_masters", return_value=[{"id": 6, "rank": 0.70}]),
        ):
            # Get results with offset=1, limit=2
            results = await search_engine._search_all_entities("test", 2, 1, 0.0)

            # Should skip first result and return next 2
            assert len(results) == 2
            assert results[0]["rank"] == 0.90  # Second highest
            assert results[1]["rank"] == 0.85  # Third highest

    # ==================== suggest_completions Tests ====================

    @pytest.mark.asyncio
    async def test_suggest_completions_artist(self, search_engine, mock_db_conn):
        """Test suggest_completions for artists."""
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(
            return_value=[
                {"id": 1, "name": "Beatles", "entity_type": "artist"},
                {"id": 2, "name": "Beach Boys", "entity_type": "artist"},
            ]
        )
        mock_db_conn.cursor.return_value.__aenter__.return_value = mock_cursor

        results = await search_engine.suggest_completions("be", SearchEntity.ARTIST, 10)

        assert len(results) == 2
        assert results[0]["name"] == "Beatles"
        mock_cursor.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_suggest_completions_release(self, search_engine, mock_db_conn):
        """Test suggest_completions for releases."""
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[{"id": 1, "name": "Abbey Road", "entity_type": "release"}])
        mock_db_conn.cursor.return_value.__aenter__.return_value = mock_cursor

        results = await search_engine.suggest_completions("ab", SearchEntity.RELEASE, 10)

        assert len(results) == 1
        assert results[0]["name"] == "Abbey Road"

    @pytest.mark.asyncio
    async def test_suggest_completions_label(self, search_engine, mock_db_conn):
        """Test suggest_completions for labels."""
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[{"id": 1, "name": "Apple Records", "entity_type": "label"}])
        mock_db_conn.cursor.return_value.__aenter__.return_value = mock_cursor

        results = await search_engine.suggest_completions("ap", SearchEntity.LABEL, 10)

        assert len(results) == 1
        assert results[0]["name"] == "Apple Records"

    @pytest.mark.asyncio
    async def test_suggest_completions_master(self, search_engine, mock_db_conn):
        """Test suggest_completions for masters."""
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[{"id": 1, "name": "Dark Side", "entity_type": "master"}])
        mock_db_conn.cursor.return_value.__aenter__.return_value = mock_cursor

        results = await search_engine.suggest_completions("da", SearchEntity.MASTER, 10)

        assert len(results) == 1
        assert results[0]["name"] == "Dark Side"

    @pytest.mark.asyncio
    async def test_suggest_completions_all_defaults_to_artists(self, search_engine, mock_db_conn):
        """Test suggest_completions with ALL entity defaults to artists."""
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])
        mock_db_conn.cursor.return_value.__aenter__.return_value = mock_cursor

        await search_engine.suggest_completions("test", SearchEntity.ALL, 10)

        # Should query artists table
        call_args = mock_cursor.execute.call_args[0]
        query = call_args[0]
        assert "FROM artists" in query
        assert "name" in query

    # ==================== search_with_filters Tests ====================

    @pytest.mark.asyncio
    async def test_search_with_filters_release(self, search_engine):
        """Test search_with_filters for releases."""
        with patch.object(
            search_engine,
            "_search_releases_with_filters",
            return_value=[{"id": 1, "title": "Album"}],
        ) as mock_search:
            results = await search_engine.search_with_filters("album", SearchEntity.RELEASE, {"year_min": 1970}, 50, 0)

            mock_search.assert_called_once()
            assert results == [{"id": 1, "title": "Album"}]

    @pytest.mark.asyncio
    async def test_search_with_filters_artist(self, search_engine):
        """Test search_with_filters for artists."""
        with patch.object(
            search_engine,
            "_search_artists_with_filters",
            return_value=[{"id": 1, "name": "Artist"}],
        ) as mock_search:
            results = await search_engine.search_with_filters("artist", SearchEntity.ARTIST, {}, 50, 0)

            mock_search.assert_called_once()
            assert results == [{"id": 1, "name": "Artist"}]

    @pytest.mark.asyncio
    async def test_search_with_filters_fallback(self, search_engine):
        """Test search_with_filters falls back to basic search for other entities."""
        with patch.object(search_engine, "search", return_value=[{"id": 1, "name": "Label"}]) as mock_search:
            results = await search_engine.search_with_filters("label", SearchEntity.LABEL, {}, 50, 0)

            mock_search.assert_called_once_with("label", SearchEntity.LABEL, SearchOperator.AND, 50, 0)
            assert results == [{"id": 1, "name": "Label"}]

    # ==================== _search_releases_with_filters Tests ====================

    @pytest.mark.asyncio
    async def test_search_releases_with_filters_year_min(self, search_engine, mock_db_conn):
        """Test _search_releases_with_filters with year_min filter."""
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[{"id": 1, "title": "Modern Album", "year": 2020}])
        mock_db_conn.cursor.return_value.__aenter__.return_value = mock_cursor

        results = await search_engine._search_releases_with_filters("album", {"year_min": 2015}, 10, 0)

        assert len(results) == 1
        # Verify year filter was applied
        call_args = mock_cursor.execute.call_args[0]
        query = call_args[0]
        assert "year >= %s" in query

    @pytest.mark.asyncio
    async def test_search_releases_with_filters_year_max(self, search_engine, mock_db_conn):
        """Test _search_releases_with_filters with year_max filter."""
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[{"id": 1, "title": "Old Album", "year": 1970}])
        mock_db_conn.cursor.return_value.__aenter__.return_value = mock_cursor

        results = await search_engine._search_releases_with_filters("album", {"year_max": 1980}, 10, 0)

        assert len(results) == 1
        # Verify year filter was applied
        call_args = mock_cursor.execute.call_args[0]
        query = call_args[0]
        assert "year <= %s" in query

    @pytest.mark.asyncio
    async def test_search_releases_with_filters_year_range(self, search_engine, mock_db_conn):
        """Test _search_releases_with_filters with both year_min and year_max."""
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[{"id": 1, "title": "70s Album", "year": 1975}])
        mock_db_conn.cursor.return_value.__aenter__.return_value = mock_cursor

        results = await search_engine._search_releases_with_filters("album", {"year_min": 1970, "year_max": 1979}, 10, 0)

        assert len(results) == 1
        # Verify both filters were applied
        call_args = mock_cursor.execute.call_args[0]
        query = call_args[0]
        assert "year >= %s" in query
        assert "year <= %s" in query

    # ==================== _search_artists_with_filters Tests ====================

    @pytest.mark.asyncio
    async def test_search_artists_with_filters(self, search_engine, mock_db_conn):
        """Test _search_artists_with_filters method."""
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[{"id": 1, "name": "Test Artist", "rank": 0.9}])
        mock_db_conn.cursor.return_value.__aenter__.return_value = mock_cursor

        # Filters are reserved for future use, so pass empty dict
        results = await search_engine._search_artists_with_filters("test", {}, 10, 0)

        assert len(results) == 1
        assert results[0]["name"] == "Test Artist"
        mock_cursor.execute.assert_called_once()

    # ==================== get_search_statistics Tests ====================

    @pytest.mark.asyncio
    async def test_get_search_statistics(self, search_engine, mock_db_conn):
        """Test get_search_statistics method."""
        mock_cursor = AsyncMock()

        # Return different counts for each entity type
        call_count = 0

        async def mock_fetchone():
            nonlocal call_count
            call_count += 1
            counts = [100, 500, 50, 200]  # artists, releases, labels, masters
            return {"count": counts[call_count - 1]}

        mock_cursor.fetchone = mock_fetchone
        mock_db_conn.cursor.return_value.__aenter__.return_value = mock_cursor

        stats = await search_engine.get_search_statistics()

        assert stats["artist"] == 100
        assert stats["release"] == 500
        assert stats["label"] == 50
        assert stats["master"] == 200
        assert stats["total_searchable"] == 850
        assert mock_cursor.execute.call_count == 4

    @pytest.mark.asyncio
    async def test_get_search_statistics_empty_database(self, search_engine, mock_db_conn):
        """Test get_search_statistics with empty database."""
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=None)
        mock_db_conn.cursor.return_value.__aenter__.return_value = mock_cursor

        stats = await search_engine.get_search_statistics()

        # All counts should be 0 when fetchone returns None
        assert stats["artist"] == 0
        assert stats["release"] == 0
        assert stats["label"] == 0
        assert stats["master"] == 0
        assert stats["total_searchable"] == 0
