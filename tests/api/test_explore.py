"""Tests for explore endpoints in the API service (api/routers/explore.py)."""

from typing import Any
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


class TestAutocompleteEndpoint:
    """Tests for GET /api/autocomplete."""

    def test_autocomplete_artist_success(self, test_client: TestClient) -> None:
        sample = [{"id": "1", "name": "Radiohead", "score": 1.0}]
        mock_func = AsyncMock(return_value=sample)
        with patch.dict("api.routers.explore.AUTOCOMPLETE_DISPATCH", {"artist": mock_func}):
            response = test_client.get("/api/autocomplete?q=radio&type=artist&limit=10")
        assert response.status_code == 200
        data = response.json()
        assert "results" in data

    def test_autocomplete_minimum_length_validation(self, test_client: TestClient) -> None:
        response = test_client.get("/api/autocomplete?q=a")
        assert response.status_code == 422

    def test_autocomplete_invalid_type(self, test_client: TestClient) -> None:
        response = test_client.get("/api/autocomplete?q=test&type=invalid")
        assert response.status_code == 400
        assert "error" in response.json()

    def test_autocomplete_no_driver_503(self, test_client: TestClient) -> None:
        import api.routers.explore as explore_module

        original = explore_module._neo4j_driver
        explore_module._neo4j_driver = None
        try:
            response = test_client.get("/api/autocomplete?q=test&type=artist")
            assert response.status_code == 503
        finally:
            explore_module._neo4j_driver = original

    def test_autocomplete_uses_cache(self, test_client: TestClient) -> None:
        import api.routers.explore as explore_module

        sample = [{"id": "1", "name": "Cached", "score": 1.0}]
        cache_key = ("cached", "artist", 10)
        explore_module._autocomplete_cache[cache_key] = sample
        try:
            response = test_client.get("/api/autocomplete?q=cached&type=artist&limit=10")
            assert response.status_code == 200
            assert response.json()["results"] == sample
        finally:
            explore_module._autocomplete_cache.pop(cache_key, None)


class TestExploreEndpoint:
    """Tests for GET /api/explore."""

    def test_explore_artist_found(self, test_client: TestClient) -> None:
        result = {"id": 1, "name": "Radiohead", "release_count": 10, "label_count": 2, "alias_count": 0}
        mock_func = AsyncMock(return_value=result)
        with patch.dict("api.routers.explore.EXPLORE_DISPATCH", {"artist": mock_func}):
            response = test_client.get("/api/explore?name=Radiohead&type=artist")
        assert response.status_code == 200
        data = response.json()
        assert data["center"]["name"] == "Radiohead"
        assert "categories" in data

    def test_explore_not_found_404(self, test_client: TestClient) -> None:
        mock_func = AsyncMock(return_value=None)
        with patch.dict("api.routers.explore.EXPLORE_DISPATCH", {"artist": mock_func}):
            response = test_client.get("/api/explore?name=Unknown&type=artist")
        assert response.status_code == 404

    def test_explore_invalid_type(self, test_client: TestClient) -> None:
        response = test_client.get("/api/explore?name=test&type=invalid")
        assert response.status_code == 400

    def test_explore_no_driver_503(self, test_client: TestClient) -> None:
        import api.routers.explore as explore_module

        original = explore_module._neo4j_driver
        explore_module._neo4j_driver = None
        try:
            response = test_client.get("/api/explore?name=test&type=artist")
            assert response.status_code == 503
        finally:
            explore_module._neo4j_driver = original


class TestExpandEndpoint:
    """Tests for GET /api/expand."""

    def test_expand_success(self, test_client: TestClient) -> None:
        mock_query = AsyncMock(return_value=[{"id": "r1", "name": "OK Computer"}])
        mock_count = AsyncMock(return_value=1)
        type_cats = {"releases": mock_query}
        count_cats = {"releases": mock_count}
        with (
            patch.dict("api.routers.explore.EXPAND_DISPATCH", {"artist": type_cats}),
            patch.dict("api.routers.explore.COUNT_DISPATCH", {"artist": count_cats}),
        ):
            response = test_client.get("/api/expand?node_id=Radiohead&type=artist&category=releases")
        assert response.status_code == 200
        data = response.json()
        assert "children" in data
        assert "total" in data

    def test_expand_invalid_type(self, test_client: TestClient) -> None:
        response = test_client.get("/api/expand?node_id=x&type=invalid&category=releases")
        assert response.status_code == 400

    def test_expand_no_driver_503(self, test_client: TestClient) -> None:
        import api.routers.explore as explore_module

        original = explore_module._neo4j_driver
        explore_module._neo4j_driver = None
        try:
            response = test_client.get("/api/expand?node_id=x&type=artist&category=releases")
            assert response.status_code == 503
        finally:
            explore_module._neo4j_driver = original


class TestTrendsEndpoint:
    """Tests for GET /api/trends."""

    def test_trends_success(self, test_client: TestClient) -> None:
        mock_func = AsyncMock(return_value=[{"year": 2000, "count": 5}])
        with patch.dict("api.routers.explore.TRENDS_DISPATCH", {"artist": mock_func}):
            response = test_client.get("/api/trends?name=Radiohead&type=artist")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Radiohead"
        assert "data" in data

    def test_trends_invalid_type(self, test_client: TestClient) -> None:
        response = test_client.get("/api/trends?name=test&type=invalid")
        assert response.status_code == 400

    def test_trends_no_driver_503(self, test_client: TestClient) -> None:
        import api.routers.explore as explore_module

        original = explore_module._neo4j_driver
        explore_module._neo4j_driver = None
        try:
            response = test_client.get("/api/trends?name=test&type=artist")
            assert response.status_code == 503
        finally:
            explore_module._neo4j_driver = original


class TestNodeDetailsEndpoint:
    """Tests for GET /api/node/{node_id}."""

    def test_node_found(self, test_client: TestClient) -> None:
        result: dict[str, Any] = {"id": "1", "name": "Radiohead", "type": "artist"}
        mock_func = AsyncMock(return_value=result)
        with patch.dict("api.routers.explore.DETAILS_DISPATCH", {"artist": mock_func}):
            response = test_client.get("/api/node/1?type=artist")
        assert response.status_code == 200

    def test_node_not_found_404(self, test_client: TestClient) -> None:
        mock_func = AsyncMock(return_value=None)
        with patch.dict("api.routers.explore.DETAILS_DISPATCH", {"artist": mock_func}):
            response = test_client.get("/api/node/999?type=artist")
        assert response.status_code == 404

    def test_node_invalid_type(self, test_client: TestClient) -> None:
        response = test_client.get("/api/node/1?type=invalid")
        assert response.status_code == 400
