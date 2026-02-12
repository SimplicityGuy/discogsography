"""Tests for Explore service API endpoints."""

from typing import Any
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


class TestHealthEndpoint:
    """Test the health check endpoint."""

    def test_health_returns_200(self, test_client: TestClient) -> None:
        response = test_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "explore"
        assert "timestamp" in data

    def test_health_status_healthy(self, test_client: TestClient) -> None:
        response = test_client.get("/health")
        data = response.json()
        assert data["status"] == "healthy"


class TestAutocompleteEndpoint:
    """Test the autocomplete endpoint."""

    def test_autocomplete_artist_success(
        self,
        test_client: TestClient,
        sample_artist_autocomplete: list[dict[str, Any]],
    ) -> None:
        mock_func = AsyncMock(return_value=sample_artist_autocomplete)

        with patch.dict("explore.explore.AUTOCOMPLETE_DISPATCH", {"artist": mock_func}):
            response = test_client.get("/api/autocomplete?q=radio&type=artist&limit=10")

        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert len(data["results"]) == 3

    def test_autocomplete_minimum_length(self, test_client: TestClient) -> None:
        response = test_client.get("/api/autocomplete?q=a")
        assert response.status_code == 422  # Validation error

    def test_autocomplete_invalid_type(self, test_client: TestClient) -> None:
        response = test_client.get("/api/autocomplete?q=test&type=invalid")
        assert response.status_code == 400
        data = response.json()
        assert "error" in data

    def test_autocomplete_genre(self, test_client: TestClient) -> None:
        mock_func = AsyncMock(return_value=[{"id": "Rock", "name": "Rock", "score": 1.0}])

        with patch.dict("explore.explore.AUTOCOMPLETE_DISPATCH", {"genre": mock_func}):
            response = test_client.get("/api/autocomplete?q=rock&type=genre")

        assert response.status_code == 200
        data = response.json()
        assert "results" in data

    def test_autocomplete_label(self, test_client: TestClient) -> None:
        mock_func = AsyncMock(return_value=[{"id": "100", "name": "Warp Records", "score": 9.0}])

        with patch.dict("explore.explore.AUTOCOMPLETE_DISPATCH", {"label": mock_func}):
            response = test_client.get("/api/autocomplete?q=warp&type=label")

        assert response.status_code == 200
        data = response.json()
        assert "results" in data

    def test_autocomplete_caching(self, test_client: TestClient) -> None:
        """Test that repeated queries use the cache."""
        mock_func = AsyncMock(return_value=[{"id": "1", "name": "Radiohead", "score": 9.5}])

        with patch.dict("explore.explore.AUTOCOMPLETE_DISPATCH", {"artist": mock_func}):
            # First call
            response1 = test_client.get("/api/autocomplete?q=cachetest&type=artist")
            assert response1.status_code == 200

            # Second call (should use cache, not call the function again)
            response2 = test_client.get("/api/autocomplete?q=cachetest&type=artist")
            assert response2.status_code == 200

            # The function should only be called once
            assert mock_func.call_count == 1

    def test_autocomplete_service_not_ready(self, test_client: TestClient) -> None:
        import explore.explore as explore_module

        original_driver = explore_module.neo4j_driver
        explore_module.neo4j_driver = None

        response = test_client.get("/api/autocomplete?q=test&type=artist")
        assert response.status_code == 503

        explore_module.neo4j_driver = original_driver


class TestExploreEndpoint:
    """Test the explore endpoint."""

    def test_explore_artist_success(
        self,
        test_client: TestClient,
        sample_explore_artist: dict[str, Any],
    ) -> None:
        mock_func = AsyncMock(return_value=sample_explore_artist)

        with patch.dict("explore.explore.EXPLORE_DISPATCH", {"artist": mock_func}):
            response = test_client.get("/api/explore?name=Radiohead&type=artist")

        assert response.status_code == 200
        data = response.json()
        assert "center" in data
        assert data["center"]["name"] == "Radiohead"
        assert data["center"]["type"] == "artist"
        assert "categories" in data
        assert len(data["categories"]) == 3  # releases, labels, aliases

    def test_explore_genre_success(
        self,
        test_client: TestClient,
        sample_explore_genre: dict[str, Any],
    ) -> None:
        mock_func = AsyncMock(return_value=sample_explore_genre)

        with patch.dict("explore.explore.EXPLORE_DISPATCH", {"genre": mock_func}):
            response = test_client.get("/api/explore?name=Rock&type=genre")

        assert response.status_code == 200
        data = response.json()
        assert data["center"]["name"] == "Rock"
        assert len(data["categories"]) == 3  # artists, labels, styles

    def test_explore_label_success(
        self,
        test_client: TestClient,
        sample_explore_label: dict[str, Any],
    ) -> None:
        mock_func = AsyncMock(return_value=sample_explore_label)

        with patch.dict("explore.explore.EXPLORE_DISPATCH", {"label": mock_func}):
            response = test_client.get("/api/explore?name=Warp%20Records&type=label")

        assert response.status_code == 200
        data = response.json()
        assert data["center"]["name"] == "Warp Records"
        assert len(data["categories"]) == 2  # releases, artists

    def test_explore_not_found(self, test_client: TestClient) -> None:
        mock_func = AsyncMock(return_value=None)

        with patch.dict("explore.explore.EXPLORE_DISPATCH", {"artist": mock_func}):
            response = test_client.get("/api/explore?name=NonExistent&type=artist")

        assert response.status_code == 404

    def test_explore_invalid_type(self, test_client: TestClient) -> None:
        response = test_client.get("/api/explore?name=Test&type=invalid")
        assert response.status_code == 400

    def test_explore_category_counts(
        self,
        test_client: TestClient,
        sample_explore_artist: dict[str, Any],
    ) -> None:
        mock_func = AsyncMock(return_value=sample_explore_artist)

        with patch.dict("explore.explore.EXPLORE_DISPATCH", {"artist": mock_func}):
            response = test_client.get("/api/explore?name=Radiohead&type=artist")

        data = response.json()
        categories = {c["category"]: c["count"] for c in data["categories"]}
        assert categories["releases"] == 42
        assert categories["labels"] == 5
        assert categories["aliases"] == 2


class TestExpandEndpoint:
    """Test the expand endpoint."""

    def test_expand_artist_releases(
        self,
        test_client: TestClient,
        sample_expand_releases: list[dict[str, Any]],
    ) -> None:
        mock_func = AsyncMock(return_value=sample_expand_releases)

        with patch.dict("explore.explore.EXPAND_DISPATCH", {"artist": {"releases": mock_func}}):
            response = test_client.get("/api/expand?node_id=Radiohead&type=artist&category=releases")

        assert response.status_code == 200
        data = response.json()
        assert "children" in data
        assert len(data["children"]) == 3

    def test_expand_invalid_type(self, test_client: TestClient) -> None:
        response = test_client.get("/api/expand?node_id=Test&type=invalid&category=releases")
        assert response.status_code == 400

    def test_expand_invalid_category(self, test_client: TestClient) -> None:
        mock_func = AsyncMock(return_value=[])
        with patch.dict("explore.explore.EXPAND_DISPATCH", {"artist": {"releases": mock_func, "labels": mock_func, "aliases": mock_func}}):
            response = test_client.get("/api/expand?node_id=Test&type=artist&category=invalid")

        assert response.status_code == 400
        data = response.json()
        assert "Valid:" in data["error"]

    def test_expand_genre_artists(self, test_client: TestClient) -> None:
        mock_func = AsyncMock(return_value=[{"id": "1", "name": "Radiohead", "type": "artist"}])

        with patch.dict("explore.explore.EXPAND_DISPATCH", {"genre": {"artists": mock_func}}):
            response = test_client.get("/api/expand?node_id=Rock&type=genre&category=artists")

        assert response.status_code == 200
        data = response.json()
        assert len(data["children"]) == 1

    def test_expand_label_releases(self, test_client: TestClient) -> None:
        mock_func = AsyncMock(return_value=[{"id": "10", "name": "OK Computer", "type": "release", "year": 1997}])

        with patch.dict("explore.explore.EXPAND_DISPATCH", {"label": {"releases": mock_func}}):
            response = test_client.get("/api/expand?node_id=Parlophone&type=label&category=releases")

        assert response.status_code == 200

    def test_expand_with_limit(self, test_client: TestClient) -> None:
        mock_func = AsyncMock(return_value=[])

        with patch.dict("explore.explore.EXPAND_DISPATCH", {"artist": {"releases": mock_func}}):
            response = test_client.get("/api/expand?node_id=Test&type=artist&category=releases&limit=5")

        assert response.status_code == 200
        mock_func.assert_called_once()
        # Verify the limit was passed
        call_args = mock_func.call_args
        assert call_args[0][1] == "Test"
        assert call_args[0][2] == 5


class TestNodeDetailsEndpoint:
    """Test the node details endpoint."""

    def test_get_artist_details(
        self,
        test_client: TestClient,
        sample_artist_details: dict[str, Any],
    ) -> None:
        mock_func = AsyncMock(return_value=sample_artist_details)

        with patch.dict("explore.explore.DETAILS_DISPATCH", {"artist": mock_func}):
            response = test_client.get("/api/node/1?type=artist")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Radiohead"
        assert "genres" in data
        assert "styles" in data

    def test_get_release_details(self, test_client: TestClient) -> None:
        release_data = {
            "id": "10",
            "name": "OK Computer",
            "year": 1997,
            "country": "UK",
            "artists": ["Radiohead"],
            "labels": ["Parlophone"],
            "genres": ["Rock"],
            "styles": ["Alternative Rock"],
        }
        mock_func = AsyncMock(return_value=release_data)

        with patch.dict("explore.explore.DETAILS_DISPATCH", {"release": mock_func}):
            response = test_client.get("/api/node/10?type=release")

        assert response.status_code == 200
        data = response.json()
        assert data["year"] == 1997

    def test_get_node_not_found(self, test_client: TestClient) -> None:
        mock_func = AsyncMock(return_value=None)

        with patch.dict("explore.explore.DETAILS_DISPATCH", {"artist": mock_func}):
            response = test_client.get("/api/node/nonexistent?type=artist")

        assert response.status_code == 404

    def test_get_node_invalid_type(self, test_client: TestClient) -> None:
        response = test_client.get("/api/node/1?type=invalid")
        assert response.status_code == 400

    def test_get_genre_details(self, test_client: TestClient) -> None:
        genre_data = {"id": "Rock", "name": "Rock", "artist_count": 1000}
        mock_func = AsyncMock(return_value=genre_data)

        with patch.dict("explore.explore.DETAILS_DISPATCH", {"genre": mock_func}):
            response = test_client.get("/api/node/Rock?type=genre")

        assert response.status_code == 200

    def test_get_label_details(self, test_client: TestClient) -> None:
        label_data = {"id": "100", "name": "Warp Records", "release_count": 500}
        mock_func = AsyncMock(return_value=label_data)

        with patch.dict("explore.explore.DETAILS_DISPATCH", {"label": mock_func}):
            response = test_client.get("/api/node/100?type=label")

        assert response.status_code == 200


class TestTrendsEndpoint:
    """Test the trends endpoint."""

    def test_trends_artist_success(
        self,
        test_client: TestClient,
        sample_trends_data: list[dict[str, Any]],
    ) -> None:
        mock_func = AsyncMock(return_value=sample_trends_data)

        with patch.dict("explore.explore.TRENDS_DISPATCH", {"artist": mock_func}):
            response = test_client.get("/api/trends?name=Radiohead&type=artist")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Radiohead"
        assert data["type"] == "artist"
        assert len(data["data"]) == 5

    def test_trends_genre(self, test_client: TestClient) -> None:
        mock_func = AsyncMock(return_value=[{"year": 2000, "count": 100}])

        with patch.dict("explore.explore.TRENDS_DISPATCH", {"genre": mock_func}):
            response = test_client.get("/api/trends?name=Rock&type=genre")

        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "genre"

    def test_trends_label(self, test_client: TestClient) -> None:
        mock_func = AsyncMock(return_value=[{"year": 1990, "count": 50}])

        with patch.dict("explore.explore.TRENDS_DISPATCH", {"label": mock_func}):
            response = test_client.get("/api/trends?name=Warp%20Records&type=label")

        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "label"

    def test_trends_invalid_type(self, test_client: TestClient) -> None:
        response = test_client.get("/api/trends?name=Test&type=invalid")
        assert response.status_code == 400

    def test_trends_empty_results(self, test_client: TestClient) -> None:
        mock_func = AsyncMock(return_value=[])

        with patch.dict("explore.explore.TRENDS_DISPATCH", {"artist": mock_func}):
            response = test_client.get("/api/trends?name=Unknown&type=artist")

        assert response.status_code == 200
        data = response.json()
        assert data["data"] == []


class TestBuildCategories:
    """Test the _build_categories helper function."""

    def test_build_artist_categories(self) -> None:
        from explore.explore import _build_categories

        result = {
            "id": "1",
            "name": "Test",
            "release_count": 10,
            "label_count": 3,
            "alias_count": 1,
        }
        categories = _build_categories("artist", result)
        assert len(categories) == 3
        cat_map = {c["category"]: c for c in categories}
        assert cat_map["releases"]["count"] == 10
        assert cat_map["labels"]["count"] == 3
        assert cat_map["aliases"]["count"] == 1

    def test_build_genre_categories(self) -> None:
        from explore.explore import _build_categories

        result = {
            "id": "Rock",
            "name": "Rock",
            "artist_count": 500,
            "label_count": 100,
            "style_count": 25,
        }
        categories = _build_categories("genre", result)
        assert len(categories) == 3
        cat_map = {c["category"]: c for c in categories}
        assert cat_map["artists"]["count"] == 500
        assert cat_map["styles"]["count"] == 25

    def test_build_label_categories(self) -> None:
        from explore.explore import _build_categories

        result = {
            "id": "100",
            "name": "Test Label",
            "release_count": 200,
            "artist_count": 50,
        }
        categories = _build_categories("label", result)
        assert len(categories) == 2

    def test_build_unknown_type(self) -> None:
        from explore.explore import _build_categories

        categories = _build_categories("unknown", {"id": "x", "name": "x"})
        assert categories == []


class TestStaticFiles:
    """Test static file serving."""

    def test_index_html_served(self, test_client: TestClient) -> None:
        response = test_client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    def test_css_served(self, test_client: TestClient) -> None:
        response = test_client.get("/css/styles.css")
        assert response.status_code == 200

    def test_js_files_served(self, test_client: TestClient) -> None:
        js_files = ["js/app.js", "js/api-client.js", "js/autocomplete.js", "js/graph.js", "js/trends.js"]
        for js_file in js_files:
            response = test_client.get(f"/{js_file}")
            assert response.status_code == 200, f"Failed to serve {js_file}"
