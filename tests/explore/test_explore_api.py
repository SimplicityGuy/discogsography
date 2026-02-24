"""Tests for Explore service API endpoints."""

import base64
import hashlib
import hmac
import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
import pytest


TEST_EXPLORE_JWT_SECRET = "test-jwt-secret-for-unit-tests"
TEST_EXPLORE_USER_ID = "00000000-0000-0000-0000-000000000001"


def _make_explore_jwt(
    user_id: str = TEST_EXPLORE_USER_ID,
    exp: int = 9_999_999_999,
    secret: str = TEST_EXPLORE_JWT_SECRET,
) -> str:
    """Create a valid HS256 JWT for explore service tests."""

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = b64url(json.dumps({"sub": user_id, "exp": exp}, separators=(",", ":")).encode())
    signing_input = f"{header}.{body}".encode("ascii")
    sig = b64url(hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest())
    return f"{header}.{body}.{sig}"


def _make_invalid_body_jwt(secret: str = TEST_EXPLORE_JWT_SECRET) -> str:
    """Create a JWT with a valid signature but non-JSON body."""

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    header = b64url(b'{"alg":"HS256"}')
    body = b64url(b"not-valid-json!")
    signing_input = f"{header}.{body}".encode("ascii")
    sig = b64url(hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest())
    return f"{header}.{body}.{sig}"


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

        with patch.dict("api.routers.explore.AUTOCOMPLETE_DISPATCH", {"artist": mock_func}):
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

        with patch.dict("api.routers.explore.AUTOCOMPLETE_DISPATCH", {"genre": mock_func}):
            response = test_client.get("/api/autocomplete?q=rock&type=genre")

        assert response.status_code == 200
        data = response.json()
        assert "results" in data

    def test_autocomplete_label(self, test_client: TestClient) -> None:
        mock_func = AsyncMock(return_value=[{"id": "100", "name": "Warp Records", "score": 9.0}])

        with patch.dict("api.routers.explore.AUTOCOMPLETE_DISPATCH", {"label": mock_func}):
            response = test_client.get("/api/autocomplete?q=warp&type=label")

        assert response.status_code == 200
        data = response.json()
        assert "results" in data

    def test_autocomplete_caching(self, test_client: TestClient) -> None:
        """Test that repeated queries use the cache."""
        mock_func = AsyncMock(return_value=[{"id": "1", "name": "Radiohead", "score": 9.5}])

        with patch.dict("api.routers.explore.AUTOCOMPLETE_DISPATCH", {"artist": mock_func}):
            # First call
            response1 = test_client.get("/api/autocomplete?q=cachetest&type=artist")
            assert response1.status_code == 200

            # Second call (should use cache, not call the function again)
            response2 = test_client.get("/api/autocomplete?q=cachetest&type=artist")
            assert response2.status_code == 200

            # The function should only be called once
            assert mock_func.call_count == 1

    def test_autocomplete_service_not_ready(self, test_client: TestClient) -> None:
        import api.routers.explore as explore_module

        original_driver = explore_module._neo4j_driver
        explore_module._neo4j_driver = None

        response = test_client.get("/api/autocomplete?q=test&type=artist")
        assert response.status_code == 503

        explore_module._neo4j_driver = original_driver

    def test_autocomplete_cache_eviction(self, test_client: TestClient) -> None:
        """Test that cache evicts oldest entries when full."""
        import api.routers.explore as explore_module

        # Set a small cache max to trigger eviction
        original_max = explore_module._AUTOCOMPLETE_CACHE_MAX
        explore_module._AUTOCOMPLETE_CACHE_MAX = 4
        explore_module._autocomplete_cache.clear()

        mock_func = AsyncMock(return_value=[{"id": "1", "name": "Test", "score": 1.0}])
        with patch.dict("api.routers.explore.AUTOCOMPLETE_DISPATCH", {"artist": mock_func}):
            # Fill cache beyond max to trigger eviction
            for i in range(5):
                response = test_client.get(f"/api/autocomplete?q=evict{i}&type=artist")
                assert response.status_code == 200

        # Cache should have been evicted (oldest quarter removed)
        assert len(explore_module._autocomplete_cache) <= 4

        explore_module._AUTOCOMPLETE_CACHE_MAX = original_max
        explore_module._autocomplete_cache.clear()


class TestExploreEndpoint:
    """Test the explore endpoint."""

    def test_explore_artist_success(
        self,
        test_client: TestClient,
        sample_explore_artist: dict[str, Any],
    ) -> None:
        mock_func = AsyncMock(return_value=sample_explore_artist)

        with patch.dict("api.routers.explore.EXPLORE_DISPATCH", {"artist": mock_func}):
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

        with patch.dict("api.routers.explore.EXPLORE_DISPATCH", {"genre": mock_func}):
            response = test_client.get("/api/explore?name=Rock&type=genre")

        assert response.status_code == 200
        data = response.json()
        assert data["center"]["name"] == "Rock"
        assert len(data["categories"]) == 4  # releases, artists, labels, styles

    def test_explore_label_success(
        self,
        test_client: TestClient,
        sample_explore_label: dict[str, Any],
    ) -> None:
        mock_func = AsyncMock(return_value=sample_explore_label)

        with patch.dict("api.routers.explore.EXPLORE_DISPATCH", {"label": mock_func}):
            response = test_client.get("/api/explore?name=Warp%20Records&type=label")

        assert response.status_code == 200
        data = response.json()
        assert data["center"]["name"] == "Warp Records"
        assert len(data["categories"]) == 3  # releases, artists, genres

    def test_explore_style_success(
        self,
        test_client: TestClient,
        sample_explore_style: dict[str, Any],
    ) -> None:
        mock_func = AsyncMock(return_value=sample_explore_style)

        with patch.dict("api.routers.explore.EXPLORE_DISPATCH", {"style": mock_func}):
            response = test_client.get("/api/explore?name=Alternative+Rock&type=style")

        assert response.status_code == 200
        data = response.json()
        assert data["center"]["name"] == "Alternative Rock"
        assert data["center"]["type"] == "style"
        assert len(data["categories"]) == 4  # releases, artists, labels, genres

    def test_explore_not_found(self, test_client: TestClient) -> None:
        mock_func = AsyncMock(return_value=None)

        with patch.dict("api.routers.explore.EXPLORE_DISPATCH", {"artist": mock_func}):
            response = test_client.get("/api/explore?name=NonExistent&type=artist")

        assert response.status_code == 404

    def test_explore_invalid_type(self, test_client: TestClient) -> None:
        response = test_client.get("/api/explore?name=Test&type=invalid")
        assert response.status_code == 400

    def test_explore_service_not_ready(self, test_client: TestClient) -> None:
        import api.routers.explore as explore_module

        original_driver = explore_module._neo4j_driver
        explore_module._neo4j_driver = None

        response = test_client.get("/api/explore?name=Test&type=artist")
        assert response.status_code == 503

        explore_module._neo4j_driver = original_driver

    def test_explore_category_counts(
        self,
        test_client: TestClient,
        sample_explore_artist: dict[str, Any],
    ) -> None:
        mock_func = AsyncMock(return_value=sample_explore_artist)

        with patch.dict("api.routers.explore.EXPLORE_DISPATCH", {"artist": mock_func}):
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
        mock_count = AsyncMock(return_value=3)

        with (
            patch.dict("api.routers.explore.EXPAND_DISPATCH", {"artist": {"releases": mock_func}}),
            patch.dict("api.routers.explore.COUNT_DISPATCH", {"artist": {"releases": mock_count}}),
        ):
            response = test_client.get("/api/expand?node_id=Radiohead&type=artist&category=releases")

        assert response.status_code == 200
        data = response.json()
        assert "children" in data
        assert len(data["children"]) == 3

    def test_expand_response_includes_pagination_fields(
        self,
        test_client: TestClient,
        sample_expand_releases: list[dict[str, Any]],
    ) -> None:
        mock_func = AsyncMock(return_value=sample_expand_releases)
        mock_count = AsyncMock(return_value=3)

        with (
            patch.dict("api.routers.explore.EXPAND_DISPATCH", {"artist": {"releases": mock_func}}),
            patch.dict("api.routers.explore.COUNT_DISPATCH", {"artist": {"releases": mock_count}}),
        ):
            response = test_client.get("/api/expand?node_id=Radiohead&type=artist&category=releases")

        data = response.json()
        assert "total" in data
        assert "offset" in data
        assert "limit" in data
        assert "has_more" in data
        assert data["total"] == 3
        assert data["offset"] == 0
        assert data["has_more"] is False  # 3 items == total 3

    def test_expand_has_more_true_when_more_exist(self, test_client: TestClient) -> None:
        mock_func = AsyncMock(return_value=[{"id": "1", "name": "X", "type": "release"}])
        mock_count = AsyncMock(return_value=100)

        with (
            patch.dict("api.routers.explore.EXPAND_DISPATCH", {"artist": {"releases": mock_func}}),
            patch.dict("api.routers.explore.COUNT_DISPATCH", {"artist": {"releases": mock_count}}),
        ):
            response = test_client.get("/api/expand?node_id=Test&type=artist&category=releases")

        data = response.json()
        assert data["has_more"] is True
        assert data["total"] == 100

    def test_expand_last_page_has_more_false(self, test_client: TestClient) -> None:
        mock_func = AsyncMock(return_value=[{"id": "1", "name": "X", "type": "release"}])
        mock_count = AsyncMock(return_value=1)

        with (
            patch.dict("api.routers.explore.EXPAND_DISPATCH", {"artist": {"releases": mock_func}}),
            patch.dict("api.routers.explore.COUNT_DISPATCH", {"artist": {"releases": mock_count}}),
        ):
            response = test_client.get("/api/expand?node_id=Test&type=artist&category=releases")

        data = response.json()
        assert data["has_more"] is False

    def test_expand_with_offset(self, test_client: TestClient) -> None:
        mock_func = AsyncMock(return_value=[{"id": "51", "name": "Y", "type": "release"}])
        mock_count = AsyncMock(return_value=100)

        with (
            patch.dict("api.routers.explore.EXPAND_DISPATCH", {"artist": {"releases": mock_func}}),
            patch.dict("api.routers.explore.COUNT_DISPATCH", {"artist": {"releases": mock_count}}),
        ):
            response = test_client.get("/api/expand?node_id=Test&type=artist&category=releases&limit=50&offset=50")

        assert response.status_code == 200
        data = response.json()
        assert data["offset"] == 50
        # Verify offset was passed to the query function
        call_args = mock_func.call_args
        assert call_args[0][3] == 50  # offset is 4th positional arg

    def test_expand_invalid_offset(self, test_client: TestClient) -> None:
        response = test_client.get("/api/expand?node_id=Test&type=artist&category=releases&offset=-1")
        assert response.status_code == 422  # FastAPI validation error

    def test_expand_invalid_type(self, test_client: TestClient) -> None:
        response = test_client.get("/api/expand?node_id=Test&type=invalid&category=releases")
        assert response.status_code == 400

    def test_expand_service_not_ready(self, test_client: TestClient) -> None:
        import api.routers.explore as explore_module

        original_driver = explore_module._neo4j_driver
        explore_module._neo4j_driver = None

        response = test_client.get("/api/expand?node_id=Test&type=artist&category=releases")
        assert response.status_code == 503

        explore_module._neo4j_driver = original_driver

    def test_expand_invalid_category(self, test_client: TestClient) -> None:
        mock_func = AsyncMock(return_value=[])
        with patch.dict("api.routers.explore.EXPAND_DISPATCH", {"artist": {"releases": mock_func, "labels": mock_func, "aliases": mock_func}}):
            response = test_client.get("/api/expand?node_id=Test&type=artist&category=invalid")

        assert response.status_code == 400
        data = response.json()
        assert "Valid:" in data["error"]

    def test_expand_genre_artists(self, test_client: TestClient) -> None:
        mock_func = AsyncMock(return_value=[{"id": "1", "name": "Radiohead", "type": "artist"}])
        mock_count = AsyncMock(return_value=1)

        with (
            patch.dict("api.routers.explore.EXPAND_DISPATCH", {"genre": {"artists": mock_func}}),
            patch.dict("api.routers.explore.COUNT_DISPATCH", {"genre": {"artists": mock_count}}),
        ):
            response = test_client.get("/api/expand?node_id=Rock&type=genre&category=artists")

        assert response.status_code == 200
        data = response.json()
        assert len(data["children"]) == 1

    def test_expand_label_releases(self, test_client: TestClient) -> None:
        mock_func = AsyncMock(return_value=[{"id": "10", "name": "OK Computer", "type": "release", "year": 1997}])
        mock_count = AsyncMock(return_value=1)

        with (
            patch.dict("api.routers.explore.EXPAND_DISPATCH", {"label": {"releases": mock_func}}),
            patch.dict("api.routers.explore.COUNT_DISPATCH", {"label": {"releases": mock_count}}),
        ):
            response = test_client.get("/api/expand?node_id=Parlophone&type=label&category=releases")

        assert response.status_code == 200

    def test_expand_with_limit(self, test_client: TestClient) -> None:
        mock_func = AsyncMock(return_value=[])
        mock_count = AsyncMock(return_value=0)

        with (
            patch.dict("api.routers.explore.EXPAND_DISPATCH", {"artist": {"releases": mock_func}}),
            patch.dict("api.routers.explore.COUNT_DISPATCH", {"artist": {"releases": mock_count}}),
        ):
            response = test_client.get("/api/expand?node_id=Test&type=artist&category=releases&limit=5")

        assert response.status_code == 200
        mock_func.assert_called_once()
        # Verify limit and offset were passed correctly
        call_args = mock_func.call_args
        assert call_args[0][1] == "Test"
        assert call_args[0][2] == 5  # limit
        assert call_args[0][3] == 0  # offset (default)


class TestNodeDetailsEndpoint:
    """Test the node details endpoint."""

    def test_get_artist_details(
        self,
        test_client: TestClient,
        sample_artist_details: dict[str, Any],
    ) -> None:
        mock_func = AsyncMock(return_value=sample_artist_details)

        with patch.dict("api.routers.explore.DETAILS_DISPATCH", {"artist": mock_func}):
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

        with patch.dict("api.routers.explore.DETAILS_DISPATCH", {"release": mock_func}):
            response = test_client.get("/api/node/10?type=release")

        assert response.status_code == 200
        data = response.json()
        assert data["year"] == 1997

    def test_get_node_not_found(self, test_client: TestClient) -> None:
        mock_func = AsyncMock(return_value=None)

        with patch.dict("api.routers.explore.DETAILS_DISPATCH", {"artist": mock_func}):
            response = test_client.get("/api/node/nonexistent?type=artist")

        assert response.status_code == 404

    def test_get_node_invalid_type(self, test_client: TestClient) -> None:
        response = test_client.get("/api/node/1?type=invalid")
        assert response.status_code == 400

    def test_get_node_service_not_ready(self, test_client: TestClient) -> None:
        import api.routers.explore as explore_module

        original_driver = explore_module._neo4j_driver
        explore_module._neo4j_driver = None

        response = test_client.get("/api/node/1?type=artist")
        assert response.status_code == 503

        explore_module._neo4j_driver = original_driver

    def test_get_genre_details(self, test_client: TestClient) -> None:
        genre_data = {"id": "Rock", "name": "Rock", "artist_count": 1000}
        mock_func = AsyncMock(return_value=genre_data)

        with patch.dict("api.routers.explore.DETAILS_DISPATCH", {"genre": mock_func}):
            response = test_client.get("/api/node/Rock?type=genre")

        assert response.status_code == 200

    def test_get_label_details(self, test_client: TestClient) -> None:
        label_data = {"id": "100", "name": "Warp Records", "release_count": 500}
        mock_func = AsyncMock(return_value=label_data)

        with patch.dict("api.routers.explore.DETAILS_DISPATCH", {"label": mock_func}):
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

        with patch.dict("api.routers.explore.TRENDS_DISPATCH", {"artist": mock_func}):
            response = test_client.get("/api/trends?name=Radiohead&type=artist")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Radiohead"
        assert data["type"] == "artist"
        assert len(data["data"]) == 5

    def test_trends_genre(self, test_client: TestClient) -> None:
        mock_func = AsyncMock(return_value=[{"year": 2000, "count": 100}])

        with patch.dict("api.routers.explore.TRENDS_DISPATCH", {"genre": mock_func}):
            response = test_client.get("/api/trends?name=Rock&type=genre")

        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "genre"

    def test_trends_label(self, test_client: TestClient) -> None:
        mock_func = AsyncMock(return_value=[{"year": 1990, "count": 50}])

        with patch.dict("api.routers.explore.TRENDS_DISPATCH", {"label": mock_func}):
            response = test_client.get("/api/trends?name=Warp%20Records&type=label")

        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "label"

    def test_trends_invalid_type(self, test_client: TestClient) -> None:
        response = test_client.get("/api/trends?name=Test&type=invalid")
        assert response.status_code == 400

    def test_trends_service_not_ready(self, test_client: TestClient) -> None:
        import api.routers.explore as explore_module

        original_driver = explore_module._neo4j_driver
        explore_module._neo4j_driver = None

        response = test_client.get("/api/trends?name=Test&type=artist")
        assert response.status_code == 503

        explore_module._neo4j_driver = original_driver

    def test_trends_empty_results(self, test_client: TestClient) -> None:
        mock_func = AsyncMock(return_value=[])

        with patch.dict("api.routers.explore.TRENDS_DISPATCH", {"artist": mock_func}):
            response = test_client.get("/api/trends?name=Unknown&type=artist")

        assert response.status_code == 200
        data = response.json()
        assert data["data"] == []


class TestBuildCategories:
    """Test the _build_categories helper function."""

    def test_build_artist_categories(self) -> None:
        from api.routers.explore import _build_categories

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
        from api.routers.explore import _build_categories

        result = {
            "id": "Rock",
            "name": "Rock",
            "release_count": 5000,
            "artist_count": 500,
            "label_count": 100,
            "style_count": 25,
        }
        categories = _build_categories("genre", result)
        assert len(categories) == 4
        cat_map = {c["category"]: c for c in categories}
        assert cat_map["releases"]["count"] == 5000
        assert cat_map["artists"]["count"] == 500
        assert cat_map["styles"]["count"] == 25

    def test_build_label_categories(self) -> None:
        from api.routers.explore import _build_categories

        result = {
            "id": "100",
            "name": "Test Label",
            "release_count": 200,
            "artist_count": 50,
            "genre_count": 8,
        }
        categories = _build_categories("label", result)
        assert len(categories) == 3
        cat_map = {c["category"]: c for c in categories}
        assert cat_map["genres"]["count"] == 8

    def test_build_style_categories(self) -> None:
        from api.routers.explore import _build_categories

        result = {
            "id": "Alternative Rock",
            "name": "Alternative Rock",
            "release_count": 2000,
            "artist_count": 400,
            "label_count": 100,
            "genre_count": 3,
        }
        categories = _build_categories("style", result)
        assert len(categories) == 4
        cat_map = {c["category"]: c for c in categories}
        assert cat_map["releases"]["count"] == 2000
        assert cat_map["genres"]["count"] == 3

    def test_build_unknown_type(self) -> None:
        from api.routers.explore import _build_categories

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


class TestGetHealthData:
    """Test the get_health_data helper function."""

    def test_health_data_when_driver_exists(self) -> None:
        import explore.explore as explore_module

        original_driver = explore_module.neo4j_driver
        explore_module.neo4j_driver = MagicMock()

        data = explore_module.get_health_data()
        assert data["status"] == "healthy"
        assert data["service"] == "explore"
        assert "timestamp" in data

        explore_module.neo4j_driver = original_driver

    def test_health_data_when_driver_none(self) -> None:
        import explore.explore as explore_module

        original_driver = explore_module.neo4j_driver
        explore_module.neo4j_driver = None

        data = explore_module.get_health_data()
        assert data["status"] == "starting"

        explore_module.neo4j_driver = original_driver


class TestGetCacheKey:
    """Test the _get_cache_key helper function."""

    def test_cache_key_lowercases(self) -> None:
        from api.routers.explore import _get_cache_key

        key = _get_cache_key("Radiohead", "artist", 10)
        assert key == ("radiohead", "artist", 10)

    def test_cache_key_strips_whitespace(self) -> None:
        from api.routers.explore import _get_cache_key

        key = _get_cache_key("  radio  ", "artist", 10)
        assert key == ("radio", "artist", 10)


class TestLifespan:
    """Test the application lifespan context manager."""

    @pytest.mark.asyncio
    async def test_lifespan_startup_and_shutdown(self) -> None:
        from explore.explore import app, lifespan

        mock_driver = MagicMock()
        mock_driver.close = AsyncMock()

        with (
            patch("explore.explore.ExploreConfig") as mock_config_class,
            patch("explore.explore.HealthServer") as mock_health_server_class,
            patch("explore.explore.AsyncResilientNeo4jDriver", return_value=mock_driver),
        ):
            mock_config = MagicMock()
            mock_config.neo4j_address = "bolt://localhost:7687"
            mock_config.neo4j_username = "neo4j"
            mock_config.neo4j_password = "password"
            mock_config_class.from_env.return_value = mock_config

            mock_health_server = MagicMock()
            mock_health_server_class.return_value = mock_health_server

            import explore.explore as explore_module

            original_driver = explore_module.neo4j_driver

            async with lifespan(app):
                # During lifespan, driver should be set
                assert explore_module.neo4j_driver is mock_driver

            # After lifespan, driver close should have been called
            mock_driver.close.assert_awaited_once()
            mock_health_server.stop.assert_called_once()

            explore_module.neo4j_driver = original_driver


class TestJwtHelpers:
    """Test the JWT helper functions _b64url_decode and _verify_jwt."""

    def test_b64url_decode_with_padding(self) -> None:
        """Test _b64url_decode adds padding when length % 4 != 0 (covers lines 61-62)."""
        from api.routers.explore import _b64url_decode

        # "dGVzdA" is 6 chars (6 % 4 == 2), so padding = 2 is added
        # This is base64url encoding of b"test"
        result = _b64url_decode("dGVzdA")
        assert result == b"test"

    def test_b64url_decode_no_padding_needed(self) -> None:
        """Test _b64url_decode when length % 4 == 0 (no padding added)."""
        from api.routers.explore import _b64url_decode

        # "YWJj" is 4 chars (4 % 4 == 0), no padding added
        # This is base64url encoding of b"abc"
        result = _b64url_decode("YWJj")
        assert result == b"abc"

    def test_verify_jwt_valid_token(self) -> None:
        """Test _verify_jwt returns payload for a valid token."""
        from api.routers.explore import _verify_jwt

        token = _make_explore_jwt()
        payload = _verify_jwt(token, TEST_EXPLORE_JWT_SECRET)
        assert payload is not None
        assert payload["sub"] == TEST_EXPLORE_USER_ID

    def test_verify_jwt_malformed_token_too_few_parts(self) -> None:
        """Test _verify_jwt returns None when token has wrong number of parts."""
        from api.routers.explore import _verify_jwt

        result = _verify_jwt("only.two", TEST_EXPLORE_JWT_SECRET)
        assert result is None

    def test_verify_jwt_wrong_signature(self) -> None:
        """Test _verify_jwt returns None when signature is invalid."""
        from api.routers.explore import _verify_jwt

        token = _make_explore_jwt()
        parts = token.split(".")
        # Corrupt the last character of the signature
        bad_sig = parts[2][:-1] + ("A" if parts[2][-1] != "A" else "B")
        bad_token = f"{parts[0]}.{parts[1]}.{bad_sig}"
        result = _verify_jwt(bad_token, TEST_EXPLORE_JWT_SECRET)
        assert result is None

    def test_verify_jwt_invalid_body_not_json(self) -> None:
        """Test _verify_jwt returns None when body cannot be JSON decoded."""
        from api.routers.explore import _verify_jwt

        token = _make_invalid_body_jwt()
        result = _verify_jwt(token, TEST_EXPLORE_JWT_SECRET)
        assert result is None

    def test_verify_jwt_expired_token(self) -> None:
        """Test _verify_jwt returns None for an expired token."""
        from api.routers.explore import _verify_jwt

        expired_token = _make_explore_jwt(exp=int(time.time()) - 100)
        result = _verify_jwt(expired_token, TEST_EXPLORE_JWT_SECRET)
        assert result is None

    def test_verify_jwt_wrong_secret(self) -> None:
        """Test _verify_jwt returns None when wrong secret is used."""
        from api.routers.explore import _verify_jwt

        token = _make_explore_jwt(secret=TEST_EXPLORE_JWT_SECRET)
        result = _verify_jwt(token, "wrong-secret")
        assert result is None


class TestRequireUserDependency:
    """Test the _require_user FastAPI dependency via user endpoints."""

    def test_user_collection_no_config_returns_503(self, test_client: TestClient) -> None:
        """When config is None, _require_user raises 503."""
        import api.routers.user as explore_module

        original_config = explore_module._jwt_secret
        explore_module._jwt_secret = None

        response = test_client.get("/api/user/collection")
        assert response.status_code == 503

        explore_module._jwt_secret = original_config

    def test_user_collection_no_auth_returns_401(self, test_client: TestClient) -> None:
        """When no bearer token is provided, _require_user raises 401."""
        import api.routers.user as explore_module

        original_config = explore_module._jwt_secret
        explore_module._jwt_secret = TEST_EXPLORE_JWT_SECRET

        response = test_client.get("/api/user/collection")
        assert response.status_code == 401

        explore_module._jwt_secret = original_config

    def test_user_collection_invalid_token_returns_401(self, test_client: TestClient) -> None:
        """When token signature is invalid, _require_user raises 401."""
        import api.routers.user as explore_module

        original_config = explore_module._jwt_secret
        explore_module._jwt_secret = TEST_EXPLORE_JWT_SECRET

        response = test_client.get(
            "/api/user/collection",
            headers={"Authorization": "Bearer header.body.badsig"},
        )
        assert response.status_code == 401

        explore_module._jwt_secret = original_config


class TestUserEndpoints:
    """Test the user-personalized endpoints."""

    def test_user_status_no_auth_returns_defaults(self, test_client: TestClient) -> None:
        """Without auth, /api/user/status returns false for all release IDs."""
        response = test_client.get("/api/user/status?ids=123,456")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"]["123"] == {"in_collection": False, "in_wantlist": False}
        assert data["status"]["456"] == {"in_collection": False, "in_wantlist": False}

    def test_user_status_empty_ids_returns_empty(self, test_client: TestClient) -> None:
        """When ids contains only whitespace/commas, returns empty status dict."""
        response = test_client.get("/api/user/status?ids=,,,")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == {}

    def test_user_collection_service_not_ready(self, test_client: TestClient) -> None:
        """When neo4j_driver is None (but config set), collection returns 503."""
        import api.routers.user as explore_module

        original_config = explore_module._jwt_secret
        original_driver = explore_module._neo4j_driver
        explore_module._jwt_secret = TEST_EXPLORE_JWT_SECRET
        explore_module._neo4j_driver = None

        token = _make_explore_jwt()
        response = test_client.get(
            "/api/user/collection",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 503

        explore_module._jwt_secret = original_config
        explore_module._neo4j_driver = original_driver

    def test_user_collection_success(self, test_client: TestClient) -> None:
        """With valid auth and neo4j driver, collection endpoint returns 200."""
        import api.routers.user as explore_module

        original_config = explore_module._jwt_secret
        explore_module._jwt_secret = TEST_EXPLORE_JWT_SECRET

        token = _make_explore_jwt()
        with patch("api.routers.user.get_user_collection", new=AsyncMock(return_value=([], 0))):
            response = test_client.get(
                "/api/user/collection",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 200
        data = response.json()
        assert "releases" in data
        assert data["total"] == 0

        explore_module._jwt_secret = original_config

    def test_user_wantlist_service_not_ready(self, test_client: TestClient) -> None:
        """When neo4j_driver is None (but config set), wantlist returns 503."""
        import api.routers.user as explore_module

        original_config = explore_module._jwt_secret
        original_driver = explore_module._neo4j_driver
        explore_module._jwt_secret = TEST_EXPLORE_JWT_SECRET
        explore_module._neo4j_driver = None

        token = _make_explore_jwt()
        response = test_client.get(
            "/api/user/wantlist",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 503

        explore_module._jwt_secret = original_config
        explore_module._neo4j_driver = original_driver

    def test_user_wantlist_success(self, test_client: TestClient) -> None:
        """With valid auth and neo4j driver, wantlist endpoint returns 200."""
        import api.routers.user as explore_module

        original_config = explore_module._jwt_secret
        explore_module._jwt_secret = TEST_EXPLORE_JWT_SECRET

        token = _make_explore_jwt()
        with patch("api.routers.user.get_user_wantlist", new=AsyncMock(return_value=([], 0))):
            response = test_client.get(
                "/api/user/wantlist",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 200
        data = response.json()
        assert "releases" in data

        explore_module._jwt_secret = original_config

    def test_user_recommendations_service_not_ready(self, test_client: TestClient) -> None:
        """When neo4j_driver is None, recommendations returns 503."""
        import api.routers.user as explore_module

        original_config = explore_module._jwt_secret
        original_driver = explore_module._neo4j_driver
        explore_module._jwt_secret = TEST_EXPLORE_JWT_SECRET
        explore_module._neo4j_driver = None

        token = _make_explore_jwt()
        response = test_client.get(
            "/api/user/recommendations",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 503

        explore_module._jwt_secret = original_config
        explore_module._neo4j_driver = original_driver

    def test_user_recommendations_success(self, test_client: TestClient) -> None:
        """With valid auth and neo4j driver, recommendations endpoint returns 200."""
        import api.routers.user as explore_module

        original_config = explore_module._jwt_secret
        explore_module._jwt_secret = TEST_EXPLORE_JWT_SECRET

        token = _make_explore_jwt()
        with patch("api.routers.user.get_user_recommendations", new=AsyncMock(return_value=[])):
            response = test_client.get(
                "/api/user/recommendations",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 200
        data = response.json()
        assert "recommendations" in data

        explore_module._jwt_secret = original_config

    def test_user_collection_stats_service_not_ready(self, test_client: TestClient) -> None:
        """When neo4j_driver is None, collection stats returns 503."""
        import api.routers.user as explore_module

        original_config = explore_module._jwt_secret
        original_driver = explore_module._neo4j_driver
        explore_module._jwt_secret = TEST_EXPLORE_JWT_SECRET
        explore_module._neo4j_driver = None

        token = _make_explore_jwt()
        response = test_client.get(
            "/api/user/collection/stats",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 503

        explore_module._jwt_secret = original_config
        explore_module._neo4j_driver = original_driver

    def test_user_collection_stats_success(self, test_client: TestClient) -> None:
        """With valid auth and neo4j driver, collection stats returns 200."""
        import api.routers.user as explore_module

        original_config = explore_module._jwt_secret
        explore_module._jwt_secret = TEST_EXPLORE_JWT_SECRET

        token = _make_explore_jwt()
        stats = {"genres": [], "decades": [], "labels": []}
        with patch("api.routers.user.get_user_collection_stats", new=AsyncMock(return_value=stats)):
            response = test_client.get(
                "/api/user/collection/stats",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 200

        explore_module._jwt_secret = original_config

    def test_user_status_with_auth_uses_db_query(self, test_client: TestClient) -> None:
        """With valid auth and driver, /api/user/status queries Neo4j."""
        import api.routers.user as explore_module

        original_config = explore_module._jwt_secret
        explore_module._jwt_secret = TEST_EXPLORE_JWT_SECRET

        token = _make_explore_jwt()
        status_result = {"123": {"in_collection": True, "in_wantlist": False}}
        with patch("api.routers.user.check_releases_user_status", new=AsyncMock(return_value=status_result)):
            response = test_client.get(
                "/api/user/status?ids=123",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"]["123"]["in_collection"] is True

        explore_module._jwt_secret = original_config
