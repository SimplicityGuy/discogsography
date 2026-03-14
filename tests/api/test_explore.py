"""Tests for explore endpoints in the API service (api/routers/explore.py)."""

from typing import Any
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
import pytest


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
        response = test_client.get("/api/autocomplete?q=ab")
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

    def test_node_no_driver_503(self, test_client: TestClient) -> None:
        import api.routers.explore as explore_module

        original = explore_module._neo4j_driver
        explore_module._neo4j_driver = None
        try:
            response = test_client.get("/api/node/1?type=artist")
            assert response.status_code == 503
        finally:
            explore_module._neo4j_driver = original


class TestBuildCategories:
    """Tests for the _build_categories helper."""

    def test_artist_categories(self) -> None:
        from api.routers.explore import _build_categories

        result = {"release_count": 10, "label_count": 2, "alias_count": 3}
        cats = _build_categories("artist", result)
        assert len(cats) == 3
        assert cats[0]["category"] == "releases"
        assert cats[0]["count"] == 10

    def test_genre_categories(self) -> None:
        from api.routers.explore import _build_categories

        result = {"release_count": 5000, "artist_count": 100, "label_count": 50, "style_count": 20}
        cats = _build_categories("genre", result)
        assert len(cats) == 4
        assert any(c["category"] == "styles" for c in cats)

    def test_label_categories(self) -> None:
        from api.routers.explore import _build_categories

        result = {"release_count": 500, "artist_count": 80, "genre_count": 5}
        cats = _build_categories("label", result)
        assert len(cats) == 3
        assert any(c["category"] == "genres" for c in cats)

    def test_style_categories(self) -> None:
        from api.routers.explore import _build_categories

        result = {"release_count": 2000, "artist_count": 400, "label_count": 60, "genre_count": 4}
        cats = _build_categories("style", result)
        assert len(cats) == 4
        assert any(c["category"] == "genres" for c in cats)

    def test_unknown_type_returns_empty(self) -> None:
        from api.routers.explore import _build_categories

        cats = _build_categories("unknown", {"id": "x", "name": "x"})
        assert cats == []


class TestJWT:
    """Tests for the JWT helpers."""

    def test_b64url_decode_no_padding(self) -> None:
        import base64

        from api.auth import b64url_decode

        data = b'{"sub":"user-1"}'
        encoded = base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")
        assert b64url_decode(encoded) == data

    def test_b64url_decode_with_padding_needed(self) -> None:
        # 1-byte payload needs 3 padding chars
        import base64

        from api.auth import b64url_decode

        data = b"x"
        encoded = base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")
        assert b64url_decode(encoded) == data

    def test_verify_jwt_valid(self) -> None:
        from api.auth import decode_token
        from tests.api.conftest import make_test_jwt

        token = make_test_jwt()
        payload = decode_token(token, "test-jwt-secret-for-unit-tests")
        assert payload is not None
        assert "sub" in payload

    def test_verify_jwt_wrong_secret(self) -> None:
        import pytest

        from api.auth import decode_token
        from tests.api.conftest import make_test_jwt

        token = make_test_jwt()
        with pytest.raises(ValueError):
            decode_token(token, "wrong-secret")

    def test_verify_jwt_invalid_format(self) -> None:
        import pytest

        from api.auth import decode_token

        with pytest.raises(ValueError):
            decode_token("not.a.valid.jwt.token", "secret")
        with pytest.raises(ValueError):
            decode_token("onlytwoparts.here", "secret")

    def test_verify_jwt_expired(self) -> None:
        import pytest

        from api.auth import decode_token
        from tests.api.conftest import make_test_jwt

        token = make_test_jwt(exp=1)  # expired in 1970
        with pytest.raises(ValueError, match="expired"):
            decode_token(token, "test-jwt-secret-for-unit-tests")

    def test_verify_jwt_invalid_json_body(self) -> None:
        """Cover ValueError when body is not valid JSON."""
        import base64 as _b64
        import hashlib
        import hmac as _hmac

        import pytest

        from api.auth import decode_token

        secret = "test-secret"
        header_b64 = _b64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=").decode()
        # Valid base64 but not JSON
        body_b64 = _b64.urlsafe_b64encode(b"not-valid-json-{{{{").rstrip(b"=").decode()
        signing_input = f"{header_b64}.{body_b64}".encode("ascii")
        sig = _b64.urlsafe_b64encode(_hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()).rstrip(b"=").decode()
        with pytest.raises(Exception):  # noqa: B017
            decode_token(f"{header_b64}.{body_b64}.{sig}", secret)

    @pytest.mark.asyncio
    async def test_get_optional_user_no_credentials(self) -> None:
        from api.dependencies import get_optional_user

        result = await get_optional_user(None)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_optional_user_no_secret(self) -> None:
        from unittest.mock import MagicMock

        import api.dependencies as dependencies_module
        from api.dependencies import get_optional_user

        original = dependencies_module._jwt_secret
        dependencies_module._jwt_secret = None
        try:
            creds = MagicMock()
            creds.credentials = "some.token.here"
            result = await get_optional_user(creds)
            assert result is None
        finally:
            dependencies_module._jwt_secret = original

    @pytest.mark.asyncio
    async def test_get_optional_user_with_valid_creds(self) -> None:
        from unittest.mock import MagicMock

        import api.dependencies as dependencies_module
        from api.dependencies import get_optional_user
        from tests.api.conftest import make_test_jwt

        original = dependencies_module._jwt_secret
        dependencies_module._jwt_secret = "test-jwt-secret-for-unit-tests"
        try:
            creds = MagicMock()
            creds.credentials = make_test_jwt()
            result = await get_optional_user(creds)
            assert result is not None
            assert "sub" in result
        finally:
            dependencies_module._jwt_secret = original


class TestAutocompleteCache:
    """Test cache eviction logic in the autocomplete endpoint."""

    def test_cache_eviction_when_full(self, test_client: TestClient) -> None:
        from unittest.mock import AsyncMock, patch

        import api.routers.explore as explore_module

        original_cache = explore_module._autocomplete_cache.copy()
        original_max = explore_module._AUTOCOMPLETE_CACHE_MAX

        try:
            # Fill the cache to its max capacity
            explore_module._AUTOCOMPLETE_CACHE_MAX = 4
            explore_module._autocomplete_cache.clear()
            for i in range(4):
                explore_module._autocomplete_cache[("key" + str(i), "artist", 10)] = [{"id": str(i)}]

            # Adding one more should trigger eviction (removes _MAX//4 = 1 item)
            mock_func = AsyncMock(return_value=[{"id": "new", "name": "New", "score": 1.0}])
            with patch.dict("api.routers.explore.AUTOCOMPLETE_DISPATCH", {"artist": mock_func}):
                response = test_client.get("/api/autocomplete?q=new&type=artist&limit=10")
            assert response.status_code == 200
            # Cache should have shrunk and then grown by one
            assert len(explore_module._autocomplete_cache) <= 4
        finally:
            explore_module._autocomplete_cache.clear()
            explore_module._autocomplete_cache.update(original_cache)
            explore_module._AUTOCOMPLETE_CACHE_MAX = original_max


class TestExpandInvalidCategory:
    """Test expand endpoint with valid type but invalid category."""

    def test_expand_valid_type_invalid_category(self, test_client: TestClient) -> None:
        response = test_client.get("/api/expand?node_id=Radiohead&type=artist&category=bogus")
        assert response.status_code == 400
        data = response.json()
        assert "error" in data
        assert "bogus" in data["error"]

    def test_expand_genre_invalid_category(self, test_client: TestClient) -> None:
        response = test_client.get("/api/expand?node_id=Rock&type=genre&category=nonexistent")
        assert response.status_code == 400


class TestGetOptionalUserInvalidToken:
    """Tests for get_optional_user with an invalid token (explore router)."""

    @pytest.mark.asyncio
    async def test_invalid_token_returns_none(self) -> None:
        """dependencies.py — bad Bearer token causes ValueError which returns None."""
        from unittest.mock import MagicMock

        import api.dependencies as dependencies_module
        from api.dependencies import get_optional_user

        original = dependencies_module._jwt_secret
        dependencies_module._jwt_secret = "test-jwt-secret-for-unit-tests"
        try:
            creds = MagicMock()
            creds.credentials = "not.a.valid.jwt"
            result = await get_optional_user(creds)
            assert result is None
        finally:
            dependencies_module._jwt_secret = original


class TestPathEndpoint:
    """Tests for GET /api/path."""

    def test_path_found(self, test_client: TestClient) -> None:
        from_result = {"id": 1, "name": "Miles Davis"}
        to_result = {"id": 2, "name": "Daft Punk"}
        path_data = {
            "nodes": [
                {"id": "1", "name": "Miles Davis", "labels": ["Artist"]},
                {"id": "201", "name": "Kind of Blue", "labels": ["Release"]},
                {"id": "2", "name": "Daft Punk", "labels": ["Artist"]},
            ],
            "rels": ["BY", "BY"],
        }

        with (
            patch("api.routers.explore.EXPLORE_DISPATCH", {"artist": AsyncMock(side_effect=[from_result, to_result])}),
            patch("api.routers.explore.find_shortest_path", AsyncMock(return_value=path_data)),
        ):
            response = test_client.get("/api/path?from_name=Miles+Davis&from_type=artist&to_name=Daft+Punk&to_type=artist")

        assert response.status_code == 200
        data = response.json()
        assert data["found"] is True
        assert data["length"] == 2
        assert len(data["path"]) == 3
        assert data["path"][0]["rel"] is None
        assert data["path"][1]["rel"] == "BY"

    def test_path_not_found(self, test_client: TestClient) -> None:
        from_result = {"id": 1, "name": "Miles Davis"}
        to_result = {"id": 2, "name": "Daft Punk"}

        with (
            patch("api.routers.explore.EXPLORE_DISPATCH", {"artist": AsyncMock(side_effect=[from_result, to_result])}),
            patch("api.routers.explore.find_shortest_path", AsyncMock(return_value=None)),
        ):
            response = test_client.get("/api/path?from_name=Miles+Davis&from_type=artist&to_name=Daft+Punk&to_type=artist")

        assert response.status_code == 200
        data = response.json()
        assert data["found"] is False
        assert data["length"] is None
        assert data["path"] == []

    def test_path_from_entity_not_found_404(self, test_client: TestClient) -> None:
        with patch("api.routers.explore.EXPLORE_DISPATCH", {"artist": AsyncMock(return_value=None)}):
            response = test_client.get("/api/path?from_name=Nobody&from_type=artist&to_name=Daft+Punk&to_type=artist")

        assert response.status_code == 404
        assert "error" in response.json()

    def test_path_to_entity_not_found_404(self, test_client: TestClient) -> None:
        from_result = {"id": 1, "name": "Miles Davis"}

        with patch("api.routers.explore.EXPLORE_DISPATCH", {"artist": AsyncMock(side_effect=[from_result, None])}):
            response = test_client.get("/api/path?from_name=Miles+Davis&from_type=artist&to_name=Nobody&to_type=artist")

        assert response.status_code == 404

    def test_path_max_depth_capped_at_15(self, test_client: TestClient) -> None:
        """FastAPI rejects max_depth > 15 with 422 (Query le=15 constraint)."""
        response = test_client.get("/api/path?from_name=Miles+Davis&from_type=artist&to_name=Daft+Punk&to_type=artist&max_depth=99")
        assert response.status_code == 422

    def test_path_no_driver_503(self, test_client: TestClient) -> None:
        import api.routers.explore as explore_module

        original = explore_module._neo4j_driver
        explore_module._neo4j_driver = None
        try:
            response = test_client.get("/api/path?from_name=Miles+Davis&from_type=artist&to_name=Daft+Punk&to_type=artist")
            assert response.status_code == 503
        finally:
            explore_module._neo4j_driver = original

    def test_path_invalid_from_type_400(self, test_client: TestClient) -> None:
        response = test_client.get("/api/path?from_name=Miles+Davis&from_type=banana&to_name=Daft+Punk&to_type=artist")
        assert response.status_code == 400

    def test_path_invalid_to_type_400(self, test_client: TestClient) -> None:
        response = test_client.get("/api/path?from_name=Miles+Davis&from_type=artist&to_name=Daft+Punk&to_type=banana")
        assert response.status_code == 400

    def test_path_same_entity_length_zero(self, test_client: TestClient) -> None:
        entity = {"id": 1, "name": "Miles Davis"}
        path_data = {
            "nodes": [{"id": "1", "name": "Miles Davis", "labels": ["Artist"]}],
            "rels": [],
        }

        with (
            patch("api.routers.explore.EXPLORE_DISPATCH", {"artist": AsyncMock(side_effect=[entity, entity])}),
            patch("api.routers.explore.find_shortest_path", AsyncMock(return_value=path_data)),
        ):
            response = test_client.get("/api/path?from_name=Miles+Davis&from_type=artist&to_name=Miles+Davis&to_type=artist")

        assert response.status_code == 200
        data = response.json()
        assert data["found"] is True
        assert data["length"] == 0
        assert len(data["path"]) == 1
