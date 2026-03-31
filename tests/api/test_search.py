"""Tests for GET /api/search endpoint."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
import pytest


class TestSearchEndpointBasic:
    """Basic search endpoint behaviour."""

    def test_search_returns_200_with_results(self, test_client: TestClient) -> None:
        expected_response = {
            "query": "blue",
            "total": 1,
            "facets": {"type": {"artist": 1}, "genre": {}, "decade": {}},
            "results": [
                {
                    "type": "artist",
                    "id": "123",
                    "name": "Blue Note",
                    "highlight": "<em>Blue</em> Note",
                    "relevance": 0.95,
                    "metadata": {},
                }
            ],
            "pagination": {"limit": 20, "offset": 0, "has_more": False},
        }
        with patch("api.routers.search.execute_search", return_value=expected_response):
            response = test_client.get("/api/search?q=blue")

        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "blue"
        assert data["total"] == 1
        assert len(data["results"]) == 1
        assert data["results"][0]["name"] == "Blue Note"
        assert "facets" in data
        assert "pagination" in data

    def test_search_503_when_pool_not_ready(self, test_client: TestClient) -> None:
        import api.routers.search as search_router

        original_pool = search_router._pool
        try:
            search_router._pool = None
            response = test_client.get("/api/search?q=blue")
        finally:
            search_router._pool = original_pool

        assert response.status_code == 503

    def test_search_422_when_query_too_short(self, test_client: TestClient) -> None:
        response = test_client.get("/api/search?q=ab")
        assert response.status_code == 422  # FastAPI validation rejects min_length=3

    def test_search_400_with_invalid_type(self, test_client: TestClient) -> None:
        with patch("api.routers.search.execute_search", new_callable=AsyncMock):
            response = test_client.get("/api/search?q=blue&types=invalid")
        assert response.status_code == 400
        assert "invalid" in response.json()["error"].lower()

    def test_search_default_params(self, test_client: TestClient) -> None:
        """Defaults: all 4 types, limit=20, offset=0, no genres, no year filters."""
        captured: dict[str, Any] = {}

        async def _capture(**kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {
                "query": "blue",
                "total": 0,
                "facets": {"type": {}, "genre": {}, "decade": {}},
                "results": [],
                "pagination": {"limit": 20, "offset": 0, "has_more": False},
            }

        with patch("api.routers.search.execute_search", side_effect=_capture):
            test_client.get("/api/search?q=blue")

        assert set(captured["types"]) == {"artist", "label", "master", "release"}
        assert captured["limit"] == 20
        assert captured["offset"] == 0
        assert captured["genres"] == []
        assert captured["year_min"] is None
        assert captured["year_max"] is None


class TestSearchFiltering:
    """Filter parameters forwarded correctly to execute_search."""

    def test_types_filter_forwarded(self, test_client: TestClient) -> None:
        captured: dict[str, Any] = {}

        async def _capture(**kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {
                "query": "blue",
                "total": 0,
                "facets": {"type": {}, "genre": {}, "decade": {}},
                "results": [],
                "pagination": {"limit": 20, "offset": 0, "has_more": False},
            }

        with patch("api.routers.search.execute_search", side_effect=_capture):
            test_client.get("/api/search?q=blue&types=artist,label")

        assert set(captured["types"]) == {"artist", "label"}

    def test_year_range_forwarded(self, test_client: TestClient) -> None:
        captured: dict[str, Any] = {}

        async def _capture(**kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {
                "query": "blue",
                "total": 0,
                "facets": {"type": {}, "genre": {}, "decade": {}},
                "results": [],
                "pagination": {"limit": 20, "offset": 0, "has_more": False},
            }

        with patch("api.routers.search.execute_search", side_effect=_capture):
            test_client.get("/api/search?q=blue&year_min=1960&year_max=1980")

        assert captured["year_min"] == 1960
        assert captured["year_max"] == 1980

    def test_genres_filter_forwarded(self, test_client: TestClient) -> None:
        captured: dict[str, Any] = {}

        async def _capture(**kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {
                "query": "blue",
                "total": 0,
                "facets": {"type": {}, "genre": {}, "decade": {}},
                "results": [],
                "pagination": {"limit": 20, "offset": 0, "has_more": False},
            }

        with patch("api.routers.search.execute_search", side_effect=_capture):
            test_client.get("/api/search?q=blue&genres=Jazz,Rock")

        assert set(captured["genres"]) == {"Jazz", "Rock"}

    def test_pagination_forwarded(self, test_client: TestClient) -> None:
        captured: dict[str, Any] = {}

        async def _capture(**kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {
                "query": "blue",
                "total": 0,
                "facets": {"type": {}, "genre": {}, "decade": {}},
                "results": [],
                "pagination": {"limit": 10, "offset": 20, "has_more": False},
            }

        with patch("api.routers.search.execute_search", side_effect=_capture):
            test_client.get("/api/search?q=blue&limit=10&offset=20")

        assert captured["limit"] == 10
        assert captured["offset"] == 20


class TestSearchResponseShape:
    """Response structure validation."""

    def test_response_shape_complete(self, test_client: TestClient) -> None:
        """Response must contain query, total, facets.{type,genre,decade}, results, pagination."""
        expected = {
            "query": "blue",
            "total": 0,
            "facets": {"type": {}, "genre": {}, "decade": {}},
            "results": [],
            "pagination": {"limit": 20, "offset": 0, "has_more": False},
        }
        with patch("api.routers.search.execute_search", return_value=expected):
            response = test_client.get("/api/search?q=blue")

        data = response.json()
        assert "query" in data
        assert "total" in data
        assert "facets" in data
        assert "type" in data["facets"]
        assert "genre" in data["facets"]
        assert "decade" in data["facets"]
        assert "results" in data
        assert "pagination" in data
        assert "limit" in data["pagination"]
        assert "offset" in data["pagination"]
        assert "has_more" in data["pagination"]


class TestSearchQueryModuleHelpers:
    """Unit tests for search_queries helper functions (no router needed)."""

    def test_cache_key_is_stable(self) -> None:
        from api.queries.search_queries import cache_key

        k1 = cache_key("blue", ["artist", "label"], [], None, None, 20, 0)
        k2 = cache_key("blue", ["label", "artist"], [], None, None, 20, 0)
        assert k1 == k2, "Order of types should not affect cache key"

    def test_cache_key_differs_on_query(self) -> None:
        from api.queries.search_queries import cache_key

        k1 = cache_key("blue", ["artist"], [], None, None, 20, 0)
        k2 = cache_key("red", ["artist"], [], None, None, 20, 0)
        assert k1 != k2

    def test_cache_key_differs_on_offset(self) -> None:
        from api.queries.search_queries import cache_key

        k1 = cache_key("blue", ["artist"], [], None, None, 20, 0)
        k2 = cache_key("blue", ["artist"], [], None, None, 20, 20)
        assert k1 != k2

    def test_format_result_artist(self) -> None:
        from api.queries.search_queries import _format_result

        row = {"type": "artist", "id": "1", "name": "Blue Note", "rank": 0.9, "highlight": "<em>Blue</em> Note", "year": None, "genres": None}
        result = _format_result(row)
        assert result["type"] == "artist"
        assert result["id"] == "1"
        assert result["name"] == "Blue Note"
        assert result["relevance"] == 0.9
        assert result["metadata"] == {}

    def test_entity_select_without_per_table_limit(self) -> None:
        from api.queries.search_queries import _entity_select

        frag = _entity_select("artist", "name", has_year=False, has_genres=False)
        rendered = frag.as_string(None)
        assert "LIMIT" not in rendered

    def test_entity_select_with_per_table_limit(self) -> None:
        from api.queries.search_queries import _entity_select

        frag = _entity_select("artist", "name", has_year=False, has_genres=False, per_table_limit=50)
        rendered = frag.as_string(None)
        assert "ORDER BY rank DESC LIMIT 50" in rendered

    def test_build_union_passes_per_table_limit(self) -> None:
        from api.queries.search_queries import _build_union

        frag = _build_union(["artist"], per_table_limit=30)
        rendered = frag.as_string(None)
        assert "LIMIT 30" in rendered

    def test_build_union_no_limit_by_default(self) -> None:
        from api.queries.search_queries import _build_union

        frag = _build_union(["artist"])
        rendered = frag.as_string(None)
        assert "LIMIT" not in rendered

    def test_format_result_release_with_metadata(self) -> None:
        from api.queries.search_queries import _format_result

        row = {
            "type": "release",
            "id": "42",
            "name": "Kind of Blue",
            "rank": 0.8,
            "highlight": "Kind of <em>Blue</em>",
            "year": "1959",
            "genres": ["Jazz"],
        }
        result = _format_result(row)
        assert result["metadata"]["year"] == 1959
        assert result["metadata"]["genres"] == ["Jazz"]

    def test_all_types_constant(self) -> None:
        from api.queries.search_queries import ALL_TYPES

        assert set(ALL_TYPES) == {"artist", "label", "master", "release"}

    @pytest.mark.asyncio
    async def test_run_results_uses_per_table_limit(self) -> None:
        """_run_results passes per_table_limit = limit + offset to _build_union."""
        from api.queries.search_queries import _run_results

        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=False)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        mock_pool = MagicMock()
        mock_pool.connection = MagicMock(return_value=mock_conn)

        with patch("api.queries.search_queries.execute_sql", new_callable=AsyncMock) as mock_exec:
            result = await _run_results(mock_pool, "Rock", ["artist"], [], None, None, 20, 0)

        assert result == []
        # Verify the SQL was built with per_table_limit = (limit + offset) * 2
        # For limit=20, offset=0: (20 + 0) * 2 = 40
        executed_sql = mock_exec.call_args[0][1]
        rendered = executed_sql.as_string(None)
        assert "LIMIT 40" in rendered

    def test_build_union_raises_on_empty_types(self) -> None:
        from api.queries.search_queries import _build_union

        with pytest.raises(ValueError, match="types must not be empty"):
            _build_union([])

    def test_build_union_multiple_types(self) -> None:
        from api.queries.search_queries import _build_union

        frag = _build_union(["artist", "release"])
        rendered = frag.as_string(None)
        assert "UNION ALL" in rendered

    def test_year_filter_clause_no_filters(self) -> None:
        from api.queries.search_queries import _year_filter_clause

        clause, params = _year_filter_clause(None, None)
        assert clause.as_string(None) == "TRUE"
        assert params == []

    def test_year_filter_clause_min_only(self) -> None:
        from api.queries.search_queries import _year_filter_clause

        clause, params = _year_filter_clause(1960, None)
        rendered = clause.as_string(None)
        assert "year::int >= %s" in rendered
        assert params == [1960]

    def test_year_filter_clause_max_only(self) -> None:
        from api.queries.search_queries import _year_filter_clause

        clause, params = _year_filter_clause(None, 1980)
        rendered = clause.as_string(None)
        assert "year::int <= %s" in rendered
        assert params == [1980]

    def test_year_filter_clause_both(self) -> None:
        from api.queries.search_queries import _year_filter_clause

        clause, params = _year_filter_clause(1960, 1980)
        rendered = clause.as_string(None)
        assert ">=" in rendered
        assert "<=" in rendered
        assert params == [1960, 1980]

    def test_genre_filter_clause_empty(self) -> None:
        from api.queries.search_queries import _genre_filter_clause

        clause, params = _genre_filter_clause([])
        assert clause.as_string(None) == "TRUE"
        assert params == []

    def test_genre_filter_clause_with_genres(self) -> None:
        from api.queries.search_queries import _genre_filter_clause

        clause, params = _genre_filter_clause(["Rock", "Jazz"])
        rendered = clause.as_string(None)
        assert "?|" in rendered
        assert params == [["Rock", "Jazz"]]

    def test_format_result_no_rank(self) -> None:
        from api.queries.search_queries import _format_result

        row = {"type": "artist", "id": "1", "name": "X", "rank": None, "highlight": None, "year": None, "genres": None}
        result = _format_result(row)
        assert result["relevance"] == 0.0
        assert result["highlight"] == "X"

    def test_format_result_no_name(self) -> None:
        from api.queries.search_queries import _format_result

        row = {"type": "artist", "id": "1", "name": None, "rank": 0.5, "highlight": None, "year": None, "genres": None}
        result = _format_result(row)
        assert result["name"] == ""
        assert result["highlight"] == ""

    def test_format_result_invalid_year_ignored(self) -> None:
        from api.queries.search_queries import _format_result

        row = {"type": "release", "id": "1", "name": "X", "rank": 0.5, "highlight": "X", "year": "unknown", "genres": None}
        result = _format_result(row)
        assert "year" not in result["metadata"]


class TestSearchQueryAsyncFunctions:
    """Tests for async DB query functions in search_queries."""

    @pytest.mark.asyncio
    async def test_run_total(self) -> None:
        from api.queries.search_queries import _run_total

        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value={"total": 42})
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=False)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        mock_pool = MagicMock()
        mock_pool.connection = MagicMock(return_value=mock_conn)

        with patch("api.queries.search_queries.execute_sql", new_callable=AsyncMock):
            result = await _run_total(mock_pool, "Rock", ["artist"], [], None, None)
        assert result == 42

    @pytest.mark.asyncio
    async def test_run_total_no_result(self) -> None:
        from api.queries.search_queries import _run_total

        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=False)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        mock_pool = MagicMock()
        mock_pool.connection = MagicMock(return_value=mock_conn)

        with patch("api.queries.search_queries.execute_sql", new_callable=AsyncMock):
            result = await _run_total(mock_pool, "Rock", ["artist"], [], None, None)
        assert result == 0

    @pytest.mark.asyncio
    async def test_run_type_counts(self) -> None:
        from api.queries.search_queries import _run_type_counts

        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[{"type": "artist", "cnt": 10}, {"type": "label", "cnt": 5}])
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=False)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        mock_pool = MagicMock()
        mock_pool.connection = MagicMock(return_value=mock_conn)

        with patch("api.queries.search_queries.execute_sql", new_callable=AsyncMock):
            result = await _run_type_counts(mock_pool, "Rock", ["artist", "label"])
        assert result == {"artist": 10, "label": 5}

    @pytest.mark.asyncio
    async def test_run_genre_facets(self) -> None:
        from api.queries.search_queries import _run_genre_facets

        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[{"genre": "Rock", "cnt": 100}, {"genre": "Jazz", "cnt": 50}])
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=False)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        mock_pool = MagicMock()
        mock_pool.connection = MagicMock(return_value=mock_conn)

        with patch("api.queries.search_queries.execute_sql", new_callable=AsyncMock):
            result = await _run_genre_facets(mock_pool, "Hendrix")
        assert result == {"Rock": 100, "Jazz": 50}

    @pytest.mark.asyncio
    async def test_run_decade_facets(self) -> None:
        from api.queries.search_queries import _run_decade_facets

        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[{"decade": "1960s", "cnt": 30}, {"decade": "1970s", "cnt": 45}])
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=False)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        mock_pool = MagicMock()
        mock_pool.connection = MagicMock(return_value=mock_conn)

        with patch("api.queries.search_queries.execute_sql", new_callable=AsyncMock):
            result = await _run_decade_facets(mock_pool, "Hendrix")
        assert result == {"1960s": 30, "1970s": 45}

    @pytest.mark.asyncio
    async def test_execute_search_raises_on_empty_types(self) -> None:
        from api.queries.search_queries import execute_search

        mock_pool = MagicMock()
        with pytest.raises(ValueError, match="types must not be empty"):
            await execute_search(mock_pool, None, "blue", [], [], None, None, 20, 0)

    @pytest.mark.asyncio
    async def test_execute_search_returns_cached(self) -> None:
        import json

        from api.queries.search_queries import execute_search

        cached_response = {"query": "blue", "total": 1, "facets": {}, "results": [], "pagination": {}}
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps(cached_response))
        mock_pool = MagicMock()

        result = await execute_search(mock_pool, mock_redis, "blue", ["artist"], [], None, None, 20, 0)
        assert result == cached_response

    @pytest.mark.asyncio
    async def test_execute_search_cache_miss(self) -> None:
        from api.queries.search_queries import execute_search

        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])
        mock_cursor.fetchone = AsyncMock(return_value={"total": 0})
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=False)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        mock_pool = MagicMock()
        mock_pool.connection = MagicMock(return_value=mock_conn)

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        with patch("api.queries.search_queries.execute_sql", new_callable=AsyncMock):
            result = await execute_search(mock_pool, mock_redis, "blue", ["artist"], [], None, None, 20, 0)

        assert result["query"] == "blue"
        assert result["total"] == 0
        assert "facets" in result
        assert "results" in result
        assert "pagination" in result
        mock_redis.setex.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_execute_search_no_redis(self) -> None:
        from api.queries.search_queries import execute_search

        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])
        mock_cursor.fetchone = AsyncMock(return_value={"total": 0})
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=False)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        mock_pool = MagicMock()
        mock_pool.connection = MagicMock(return_value=mock_conn)

        with patch("api.queries.search_queries.execute_sql", new_callable=AsyncMock):
            result = await execute_search(mock_pool, None, "blue", ["artist"], [], None, None, 20, 0)

        assert result["query"] == "blue"
