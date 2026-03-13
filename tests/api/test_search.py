"""Tests for GET /api/search endpoint."""

from typing import Any
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


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
