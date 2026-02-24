"""Tests for user endpoints in the API service (api/routers/user.py)."""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


class TestUserCollectionEndpoint:
    """Tests for GET /api/user/collection."""

    def test_collection_no_auth(self, test_client: TestClient) -> None:
        response = test_client.get("/api/user/collection")
        assert response.status_code in (401, 403)

    def test_collection_success(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        mock_result = ([{"id": "r1", "name": "OK Computer"}], 1)
        with patch("api.routers.user.get_user_collection", new=AsyncMock(return_value=mock_result)):
            response = test_client.get("/api/user/collection", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "releases" in data
        assert "total" in data
        assert data["total"] == 1

    def test_collection_no_driver_503(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        import api.routers.user as user_module

        original = user_module._neo4j_driver
        user_module._neo4j_driver = None
        try:
            response = test_client.get("/api/user/collection", headers=auth_headers)
            assert response.status_code == 503
        finally:
            user_module._neo4j_driver = original


class TestUserWantlistEndpoint:
    """Tests for GET /api/user/wantlist."""

    def test_wantlist_no_auth(self, test_client: TestClient) -> None:
        response = test_client.get("/api/user/wantlist")
        assert response.status_code in (401, 403)

    def test_wantlist_success(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        mock_result = ([{"id": "r2", "name": "Kid A"}], 1)
        with patch("api.routers.user.get_user_wantlist", new=AsyncMock(return_value=mock_result)):
            response = test_client.get("/api/user/wantlist", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "releases" in data

    def test_wantlist_no_driver_503(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        import api.routers.user as user_module

        original = user_module._neo4j_driver
        user_module._neo4j_driver = None
        try:
            response = test_client.get("/api/user/wantlist", headers=auth_headers)
            assert response.status_code == 503
        finally:
            user_module._neo4j_driver = original


class TestUserRecommendationsEndpoint:
    """Tests for GET /api/user/recommendations."""

    def test_recommendations_no_auth(self, test_client: TestClient) -> None:
        response = test_client.get("/api/user/recommendations")
        assert response.status_code in (401, 403)

    def test_recommendations_success(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        mock_result = [{"id": "r3", "name": "Amnesiac"}]
        with patch("api.routers.user.get_user_recommendations", new=AsyncMock(return_value=mock_result)):
            response = test_client.get("/api/user/recommendations", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "recommendations" in data
        assert data["total"] == 1


class TestUserCollectionStatsEndpoint:
    """Tests for GET /api/user/collection/stats."""

    def test_stats_no_auth(self, test_client: TestClient) -> None:
        response = test_client.get("/api/user/collection/stats")
        assert response.status_code in (401, 403)

    def test_stats_success(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        mock_stats = {"genres": [], "decades": [], "labels": []}
        with patch("api.routers.user.get_user_collection_stats", new=AsyncMock(return_value=mock_stats)):
            response = test_client.get("/api/user/collection/stats", headers=auth_headers)
        assert response.status_code == 200


class TestUserStatusEndpoint:
    """Tests for GET /api/user/status."""

    def test_status_no_auth_returns_all_false(self, test_client: TestClient) -> None:
        response = test_client.get("/api/user/status?ids=1,2,3")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        for rid in ["1", "2", "3"]:
            assert data["status"][rid]["in_collection"] is False
            assert data["status"][rid]["in_wantlist"] is False

    def test_status_with_auth(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        mock_result = {"r1": {"in_collection": True, "in_wantlist": False}}
        with patch("api.routers.user.check_releases_user_status", new=AsyncMock(return_value=mock_result)):
            response = test_client.get("/api/user/status?ids=r1,r2", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["status"]["r1"]["in_collection"] is True
        assert data["status"]["r2"]["in_collection"] is False  # default

    def test_status_empty_ids(self, test_client: TestClient) -> None:
        response = test_client.get("/api/user/status?ids=,,,")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == {}


class TestB64UrlDecode:
    """Tests for api.routers.user._b64url_decode."""

    def test_decode_with_padding_needed(self) -> None:
        """Line 42: padding branch executes when length % 4 != 0."""
        from api.routers.user import _b64url_decode

        # "YQ" decodes to b"a" but needs 2 padding chars ("YQ==")
        result = _b64url_decode("YQ")
        assert result == b"a"

    def test_decode_aligned_no_padding(self) -> None:
        """No padding when length already divisible by 4."""
        from api.routers.user import _b64url_decode

        # "AAAA" is 4 chars, already aligned
        result = _b64url_decode("AAAA")
        assert result == b"\x00\x00\x00"


class TestVerifyJwt:
    """Tests for api.routers.user._verify_jwt."""

    def test_wrong_part_count_returns_none(self) -> None:
        """Line 49: returns None when token doesn't have 3 parts."""
        from api.routers.user import _verify_jwt

        assert _verify_jwt("only.two", "secret") is None
        assert _verify_jwt("a.b.c.d", "secret") is None

    def test_bad_signature_returns_none(self) -> None:
        """Line 54: returns None when signature doesn't match."""
        from api.routers.user import _verify_jwt
        from tests.api.conftest import TEST_JWT_SECRET, make_test_jwt

        token = make_test_jwt(secret="wrong-secret")  # noqa: S106
        assert _verify_jwt(token, TEST_JWT_SECRET) is None

    def test_invalid_json_payload_returns_none(self) -> None:
        """Lines 57-58: returns None when body decodes to non-JSON bytes."""
        import base64
        import hashlib
        import hmac

        from api.routers.user import _verify_jwt

        def b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

        secret = "test-secret"
        header = b64url(b'{"alg":"HS256"}')
        body = b64url(b"not-valid-json!")
        signing_input = f"{header}.{body}".encode("ascii")
        sig = b64url(hmac.new(secret.encode(), signing_input, hashlib.sha256).digest())
        token = f"{header}.{body}.{sig}"

        assert _verify_jwt(token, secret) is None

    def test_expired_token_returns_none(self) -> None:
        """Line 61: returns None when token is expired."""
        from api.routers.user import _verify_jwt
        from tests.api.conftest import TEST_JWT_SECRET, make_test_jwt

        expired_token = make_test_jwt(exp=1)  # epoch 1970
        assert _verify_jwt(expired_token, TEST_JWT_SECRET) is None

    def test_valid_token_returns_payload(self) -> None:
        """Happy path: returns the payload dict for a valid token."""
        from api.routers.user import _verify_jwt
        from tests.api.conftest import TEST_JWT_SECRET, TEST_USER_ID, make_test_jwt

        token = make_test_jwt()
        result = _verify_jwt(token, TEST_JWT_SECRET)
        assert result is not None
        assert result["sub"] == TEST_USER_ID


class TestRequireUser:
    """Tests for api.routers.user._require_user via endpoints."""

    def test_jwt_secret_none_returns_503(self, test_client: TestClient) -> None:
        """Line 77: _require_user raises 503 when _jwt_secret is None."""
        import api.routers.user as user_module

        original = user_module._jwt_secret
        user_module._jwt_secret = None
        try:
            response = test_client.get(
                "/api/user/collection",
                headers={"Authorization": "Bearer anything"},
            )
            assert response.status_code == 503
        finally:
            user_module._jwt_secret = original

    def test_bad_token_returns_401(self, test_client: TestClient) -> None:
        """Line 82: _require_user raises 401 when _verify_jwt returns None (bad sig)."""
        import base64
        import hashlib
        import hmac
        import json

        # Build a token with a wrong signature
        def b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

        header = b64url(json.dumps({"alg": "HS256"}, separators=(",", ":")).encode())
        body = b64url(json.dumps({"sub": "uid", "exp": 9_999_999_999}, separators=(",", ":")).encode())
        signing_input = f"{header}.{body}".encode("ascii")
        sig = b64url(hmac.new(b"wrong-secret", signing_input, hashlib.sha256).digest())
        bad_token = f"{header}.{body}.{sig}"

        response = test_client.get(
            "/api/user/collection",
            headers={"Authorization": f"Bearer {bad_token}"},
        )
        assert response.status_code == 401


class TestUserEndpointsNoNeo4j:
    """Tests for user endpoints that return 503 when neo4j driver is None."""

    def test_recommendations_no_driver_503(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        """Line 118: user_recommendations returns 503 when _neo4j_driver is None."""
        import api.routers.user as user_module

        original = user_module._neo4j_driver
        user_module._neo4j_driver = None
        try:
            response = test_client.get("/api/user/recommendations", headers=auth_headers)
            assert response.status_code == 503
        finally:
            user_module._neo4j_driver = original

    def test_collection_stats_no_driver_503(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        """Line 129: user_collection_stats returns 503 when _neo4j_driver is None."""
        import api.routers.user as user_module

        original = user_module._neo4j_driver
        user_module._neo4j_driver = None
        try:
            response = test_client.get("/api/user/collection/stats", headers=auth_headers)
            assert response.status_code == 503
        finally:
            user_module._neo4j_driver = original
