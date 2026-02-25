"""Tests for the API service (api/api.py)."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
import pytest

from tests.api.conftest import (
    TEST_USER_EMAIL,
    TEST_USER_ID,
    make_test_jwt,
)


class TestB64UrlHelpers:
    """Tests for _b64url_encode and _b64url_decode."""

    def test_encode_decode_roundtrip(self) -> None:
        from api.api import _b64url_decode, _b64url_encode

        data = b"hello world"
        encoded = _b64url_encode(data)
        assert isinstance(encoded, str)
        assert "=" not in encoded  # no padding
        assert _b64url_decode(encoded) == data

    def test_encode_produces_urlsafe_chars(self) -> None:
        from api.api import _b64url_encode

        # 0xFF bytes would produce '/' or '+' in standard base64
        data = bytes(range(256))
        encoded = _b64url_encode(data)
        assert "+" not in encoded
        assert "/" not in encoded

    def test_decode_handles_missing_padding(self) -> None:
        from api.api import _b64url_decode

        # Standard base64 of b"a" is "YQ==" (2 padding chars)
        # urlsafe without padding is "YQ"
        result = _b64url_decode("YQ")
        assert result == b"a"

    def test_decode_no_extra_padding_when_aligned(self) -> None:
        from api.api import _b64url_decode

        # "AAAA" is 4 chars, already aligned — no padding needed
        result = _b64url_decode("AAAA")
        assert result == b"\x00\x00\x00"


class TestPasswordHashing:
    """Tests for _hash_password and _verify_password."""

    def test_hash_produces_colon_separated_hex(self) -> None:
        from api.api import _hash_password

        hashed = _hash_password("mypassword")
        assert ":" in hashed
        parts = hashed.split(":")
        assert len(parts) == 2
        # Both parts are hex strings
        bytes.fromhex(parts[0])
        bytes.fromhex(parts[1])

    def test_hash_is_different_each_time(self) -> None:
        from api.api import _hash_password

        h1 = _hash_password("same")
        h2 = _hash_password("same")
        assert h1 != h2  # different salts

    def test_verify_correct_password(self) -> None:
        from api.api import _hash_password, _verify_password

        password = "correct-horse-battery-staple"
        hashed = _hash_password(password)
        assert _verify_password(password, hashed) is True

    def test_verify_wrong_password(self) -> None:
        from api.api import _hash_password, _verify_password

        hashed = _hash_password("correct")
        assert _verify_password("wrong", hashed) is False

    def test_verify_malformed_hash_returns_false(self) -> None:
        from api.api import _verify_password

        assert _verify_password("password", "not-a-valid-hash") is False
        assert _verify_password("password", "") is False


class TestJwtFunctions:
    """Tests for _create_access_token and _decode_access_token."""

    def test_create_access_token_format(self, test_client: TestClient) -> None:  # noqa: ARG002
        """Token should be header.body.signature format."""
        import api.api as api_module
        from api.api import _create_access_token

        token, expires_in = _create_access_token(TEST_USER_ID, TEST_USER_EMAIL)
        parts = token.split(".")
        assert len(parts) == 3
        assert expires_in == api_module._config.jwt_expire_minutes * 60  # type: ignore[union-attr]

    def test_create_then_decode(self, test_client: TestClient) -> None:  # noqa: ARG002
        from api.api import _create_access_token, _decode_access_token

        token, _ = _create_access_token(TEST_USER_ID, TEST_USER_EMAIL)
        payload = _decode_access_token(token)
        assert payload["sub"] == TEST_USER_ID
        assert payload["email"] == TEST_USER_EMAIL

    def test_decode_wrong_signature_raises(self, test_client: TestClient) -> None:  # noqa: ARG002
        from api.api import _decode_access_token

        bad_token = make_test_jwt(secret="wrong-secret")  # noqa: S106
        with pytest.raises(ValueError, match="Invalid token signature"):
            _decode_access_token(bad_token)

    def test_decode_expired_token_raises(self, test_client: TestClient) -> None:  # noqa: ARG002
        from api.api import _decode_access_token

        expired_token = make_test_jwt(exp=1)  # epoch 1970
        with pytest.raises(ValueError, match="expired"):
            _decode_access_token(expired_token)

    def test_decode_malformed_token_raises(self, test_client: TestClient) -> None:  # noqa: ARG002
        from api.api import _decode_access_token

        with pytest.raises(ValueError):
            _decode_access_token("not.enough")

    def test_create_requires_config(self) -> None:
        import api.api as api_module
        from api.api import _create_access_token

        original = api_module._config
        api_module._config = None
        try:
            with pytest.raises(RuntimeError, match="not initialized"):
                _create_access_token("uid", "email@example.com")
        finally:
            api_module._config = original

    def test_decode_requires_config(self) -> None:
        import api.api as api_module
        from api.api import _decode_access_token

        original = api_module._config
        api_module._config = None
        try:
            with pytest.raises(ValueError, match="not initialized"):
                _decode_access_token("a.b.c")
        finally:
            api_module._config = original


class TestGetHealthData:
    """Tests for get_health_data."""

    def test_healthy_when_pool_set(self, test_client: TestClient) -> None:  # noqa: ARG002
        from api.api import get_health_data

        data = get_health_data()
        assert data["status"] == "healthy"
        assert data["service"] == "api"
        assert "timestamp" in data

    def test_starting_when_no_pool(self) -> None:
        import api.api as api_module
        from api.api import get_health_data

        original = api_module._pool
        api_module._pool = None
        try:
            data = get_health_data()
            assert data["status"] == "starting"
        finally:
            api_module._pool = original


class TestHealthEndpoint:
    """Tests for GET /health."""

    def test_health_returns_200(self, test_client: TestClient) -> None:
        response = test_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "api"


class TestRegisterEndpoint:
    """Tests for POST /api/auth/register."""

    def test_register_success(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
    ) -> None:

        mock_cur.fetchone.return_value = {
            "id": TEST_USER_ID,
            "email": TEST_USER_EMAIL,
            "is_active": True,
            "created_at": datetime.now(UTC),
        }

        response = test_client.post(
            "/api/auth/register",
            json={"email": TEST_USER_EMAIL, "password": "Password123!"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["message"] == "Registration processed"

    def test_register_duplicate_email_409(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
    ) -> None:
        mock_cur.execute.side_effect = Exception("unique constraint violation")

        response = test_client.post(
            "/api/auth/register",
            json={"email": "dup@example.com", "password": "Password123!"},
        )
        assert response.status_code == 201
        assert response.json()["message"] == "Registration processed"

    def test_register_generic_db_error_500(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
    ) -> None:
        mock_cur.execute.side_effect = Exception("connection reset")

        response = test_client.post(
            "/api/auth/register",
            json={"email": "new@example.com", "password": "Password123!"},
        )
        assert response.status_code == 500

    def test_register_service_not_ready(self) -> None:
        """When _pool is None, register returns 503."""
        from collections.abc import AsyncGenerator
        from contextlib import asynccontextmanager

        from fastapi import FastAPI

        import api.api as api_module
        from api.api import app

        @asynccontextmanager
        async def mock_lifespan(_app: FastAPI) -> AsyncGenerator[None]:
            yield

        original_lifespan = app.router.lifespan_context
        original_pool = api_module._pool
        app.router.lifespan_context = mock_lifespan
        api_module._pool = None

        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post(
                    "/api/auth/register",
                    json={"email": "x@y.com", "password": "ValidPassword123!"},
                )
            assert response.status_code == 503
        finally:
            api_module._pool = original_pool
            app.router.lifespan_context = original_lifespan

    def test_register_fetchone_none_500(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
    ) -> None:
        mock_cur.fetchone.return_value = None

        response = test_client.post(
            "/api/auth/register",
            json={"email": "none@example.com", "password": "Password123!"},
        )
        assert response.status_code == 500


class TestLoginEndpoint:
    """Tests for POST /api/auth/login."""

    def test_login_success(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
    ) -> None:
        from api.api import _hash_password

        hashed = _hash_password("correctpassword")
        mock_cur.fetchone.return_value = {
            "id": TEST_USER_ID,
            "email": TEST_USER_EMAIL,
            "is_active": True,
            "hashed_password": hashed,
        }

        response = test_client.post(
            "/api/auth/login",
            json={"email": TEST_USER_EMAIL, "password": "correctpassword"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_login_wrong_password_401(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
    ) -> None:
        from api.api import _hash_password

        hashed = _hash_password("correctpassword")
        mock_cur.fetchone.return_value = {
            "id": TEST_USER_ID,
            "email": TEST_USER_EMAIL,
            "is_active": True,
            "hashed_password": hashed,
        }

        response = test_client.post(
            "/api/auth/login",
            json={"email": TEST_USER_EMAIL, "password": "wrongpassword"},
        )
        assert response.status_code == 401

    def test_login_user_not_found_401(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
    ) -> None:
        mock_cur.fetchone.return_value = None

        response = test_client.post(
            "/api/auth/login",
            json={"email": "notfound@example.com", "password": "somepassword"},
        )
        assert response.status_code == 401

    def test_login_inactive_user_401(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
    ) -> None:
        from api.api import _hash_password

        hashed = _hash_password("password")
        mock_cur.fetchone.return_value = {
            "id": TEST_USER_ID,
            "email": TEST_USER_EMAIL,
            "is_active": False,
            "hashed_password": hashed,
        }

        response = test_client.post(
            "/api/auth/login",
            json={"email": TEST_USER_EMAIL, "password": "password"},
        )
        assert response.status_code == 401


class TestMeEndpoint:
    """Tests for GET /api/auth/me."""

    def test_get_me_success(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
        auth_headers: dict[str, str],
    ) -> None:

        mock_cur.fetchone.return_value = {
            "id": TEST_USER_ID,
            "email": TEST_USER_EMAIL,
            "is_active": True,
            "created_at": datetime.now(UTC),
        }

        response = test_client.get("/api/auth/me", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == TEST_USER_EMAIL

    def test_get_me_user_not_found_404(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
        auth_headers: dict[str, str],
    ) -> None:
        mock_cur.fetchone.return_value = None

        response = test_client.get("/api/auth/me", headers=auth_headers)
        assert response.status_code == 404

    def test_get_me_no_auth(self, test_client: TestClient) -> None:
        response = test_client.get("/api/auth/me")
        assert response.status_code in (401, 403)

    def test_get_me_invalid_token_401(self, test_client: TestClient) -> None:
        response = test_client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer not.a.valid.token"},
        )
        assert response.status_code == 401


class TestDiscogsOAuthEndpoints:
    """Tests for Discogs OAuth authorize/verify/status/revoke endpoints."""

    def test_authorize_discogs_no_credentials_503(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
        auth_headers: dict[str, str],
    ) -> None:
        """When Discogs keys are not in app_config, returns 503."""
        mock_cur.fetchone.return_value = None  # no config rows

        response = test_client.get("/api/oauth/authorize/discogs", headers=auth_headers)
        assert response.status_code == 503

    def test_authorize_discogs_success(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
        mock_redis: AsyncMock,  # noqa: ARG002
        auth_headers: dict[str, str],
    ) -> None:
        from unittest.mock import patch

        mock_cur.fetchone.side_effect = [
            {"value": "consumer_key_value"},
            {"value": "consumer_secret_value"},
        ]

        with patch(
            "api.api.request_oauth_token",
            new=AsyncMock(return_value={"oauth_token": "reqtok", "oauth_token_secret": "reqsec"}),
        ):
            response = test_client.get("/api/oauth/authorize/discogs", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert "authorize_url" in data
        assert data["state"] == "reqtok"

    def test_authorize_discogs_oauth_error_502(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
        auth_headers: dict[str, str],
    ) -> None:
        from api.services.discogs import DiscogsOAuthError

        mock_cur.fetchone.side_effect = [
            {"value": "ckey"},
            {"value": "csecret"},
        ]

        with patch(
            "api.api.request_oauth_token",
            new=AsyncMock(side_effect=DiscogsOAuthError("failed")),
        ):
            response = test_client.get("/api/oauth/authorize/discogs", headers=auth_headers)

        assert response.status_code == 502

    def test_verify_discogs_success(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
        mock_redis: AsyncMock,
        auth_headers: dict[str, str],
    ) -> None:
        mock_cur.fetchone.side_effect = [
            {"value": "ckey"},
            {"value": "csecret"},
        ]
        mock_redis.get.return_value = "reqsecret"

        with (
            patch(
                "api.api.exchange_oauth_verifier",
                new=AsyncMock(return_value={"oauth_token": "acctok", "oauth_token_secret": "accsec"}),
            ),
            patch(
                "api.api.fetch_discogs_identity",
                new=AsyncMock(return_value={"username": "discogs_user", "id": 12345}),
            ),
        ):
            response = test_client.post(
                "/api/oauth/verify/discogs",
                headers=auth_headers,
                json={"state": "reqtok", "oauth_verifier": "verif123"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["connected"] is True
        assert data["discogs_username"] == "discogs_user"

    def test_verify_discogs_state_not_found_400(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
        mock_redis: AsyncMock,
        auth_headers: dict[str, str],
    ) -> None:
        mock_cur.fetchone.side_effect = [
            {"value": "ckey"},
            {"value": "csecret"},
        ]
        mock_redis.get.return_value = None  # state expired

        response = test_client.post(
            "/api/oauth/verify/discogs",
            headers=auth_headers,
            json={"state": "expired_state", "oauth_verifier": "verif"},
        )
        assert response.status_code == 400

    def test_discogs_status_connected(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
        auth_headers: dict[str, str],
    ) -> None:

        mock_cur.fetchone.return_value = {
            "provider_username": "discogs_user",
            "provider_user_id": "12345",
            "updated_at": datetime.now(UTC),
        }

        response = test_client.get("/api/oauth/status/discogs", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["connected"] is True
        assert data["discogs_username"] == "discogs_user"

    def test_discogs_status_not_connected(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
        auth_headers: dict[str, str],
    ) -> None:
        mock_cur.fetchone.return_value = None

        response = test_client.get("/api/oauth/status/discogs", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["connected"] is False

    def test_revoke_discogs_success(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        response = test_client.delete("/api/oauth/revoke/discogs", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["revoked"] is True

    def test_authorize_discogs_service_not_ready_503(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Returns 503 when Redis is None."""
        import api.api as api_module

        original_redis = api_module._redis
        api_module._redis = None
        try:
            response = test_client.get("/api/oauth/authorize/discogs", headers=auth_headers)
            assert response.status_code == 503
        finally:
            api_module._redis = original_redis

    def test_verify_discogs_service_not_ready_503(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Returns 503 when Redis is None."""
        import api.api as api_module

        original_redis = api_module._redis
        api_module._redis = None
        try:
            response = test_client.post(
                "/api/oauth/verify/discogs",
                headers=auth_headers,
                json={"state": "tok", "oauth_verifier": "verif"},
            )
            assert response.status_code == 503
        finally:
            api_module._redis = original_redis

    def test_verify_discogs_exchange_error_400(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
        mock_redis: AsyncMock,
        auth_headers: dict[str, str],
    ) -> None:
        """Returns 400 when exchange_oauth_verifier raises DiscogsOAuthError."""
        from api.services.discogs import DiscogsOAuthError

        mock_cur.fetchone.side_effect = [
            {"value": "ckey"},
            {"value": "csecret"},
        ]
        mock_redis.get.return_value = "reqsecret"

        with patch(
            "api.api.exchange_oauth_verifier",
            new=AsyncMock(side_effect=DiscogsOAuthError("bad verifier")),
        ):
            response = test_client.post(
                "/api/oauth/verify/discogs",
                headers=auth_headers,
                json={"state": "tok", "oauth_verifier": "bad"},
            )
        assert response.status_code == 400

    def test_discogs_status_service_not_ready_503(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        import api.api as api_module

        original_pool = api_module._pool
        api_module._pool = None
        try:
            response = test_client.get("/api/oauth/status/discogs", headers=auth_headers)
            assert response.status_code == 503
        finally:
            api_module._pool = original_pool

    def test_revoke_discogs_service_not_ready_503(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        import api.api as api_module

        original_pool = api_module._pool
        api_module._pool = None
        try:
            response = test_client.delete("/api/oauth/revoke/discogs", headers=auth_headers)
            assert response.status_code == 503
        finally:
            api_module._pool = original_pool


class TestGetCurrentUser:
    """Tests for the _get_current_user dependency."""

    def test_get_current_user_config_none_503(self) -> None:
        """When _config is None, protected endpoint returns 503."""
        from collections.abc import AsyncGenerator
        from contextlib import asynccontextmanager

        from fastapi import FastAPI

        import api.api as api_module
        from api.api import app

        @asynccontextmanager
        async def mock_lifespan(_app: FastAPI) -> AsyncGenerator[None]:
            yield

        original_lifespan = app.router.lifespan_context
        original_config = api_module._config
        app.router.lifespan_context = mock_lifespan
        api_module._config = None
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get(
                    "/api/auth/me",
                    headers={"Authorization": "Bearer a.b.c"},
                )
            assert response.status_code in (401, 503)
        finally:
            api_module._config = original_config
            app.router.lifespan_context = original_lifespan

    def test_get_current_user_no_sub_in_token_401(
        self,
        test_client: TestClient,
    ) -> None:
        """A valid-signature token with no 'sub' claim returns 401."""
        import base64
        import hashlib
        import hmac
        import json

        from tests.api.conftest import TEST_JWT_SECRET

        def b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

        header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
        body = b64url(json.dumps({"email": "x@y.com", "exp": 9_999_999_999}, separators=(",", ":")).encode())
        signing_input = f"{header}.{body}".encode("ascii")
        sig = b64url(hmac.new(TEST_JWT_SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest())
        token = f"{header}.{body}.{sig}"

        response = test_client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401


class TestLoginServiceNotReady:
    """Test login 503 when pool/config is None."""

    def test_login_pool_none_503(self) -> None:
        from collections.abc import AsyncGenerator
        from contextlib import asynccontextmanager

        from fastapi import FastAPI

        import api.api as api_module
        from api.api import app

        @asynccontextmanager
        async def mock_lifespan(_app: FastAPI) -> AsyncGenerator[None]:
            yield

        original_lifespan = app.router.lifespan_context
        original_pool = api_module._pool
        app.router.lifespan_context = mock_lifespan
        api_module._pool = None
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post(
                    "/api/auth/login",
                    json={"email": "x@y.com", "password": "password"},
                )
            assert response.status_code == 503
        finally:
            api_module._pool = original_pool
            app.router.lifespan_context = original_lifespan


class TestGetAppConfig:
    """Tests for _get_app_config."""

    @pytest.mark.asyncio
    async def test_returns_none_when_pool_is_none(self) -> None:
        """Line 404: _get_app_config returns None when _pool is None."""
        import api.api as api_module
        from api.api import _get_app_config

        original = api_module._pool
        api_module._pool = None
        try:
            result = await _get_app_config("any_key")
            assert result is None
        finally:
            api_module._pool = original


class TestVerifyDiscogsNoCredentials:
    """Test verify_discogs 503 when app credentials not configured."""

    def test_verify_discogs_no_credentials_503(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
        auth_headers: dict[str, str],
    ) -> None:
        """Line 487: verify_discogs raises 503 when consumer_key/secret not in app_config."""
        mock_cur.fetchone.return_value = None  # _get_app_config returns None

        response = test_client.post(
            "/api/oauth/verify/discogs",
            headers=auth_headers,
            json={"state": "reqtok", "oauth_verifier": "verif123"},
        )
        assert response.status_code == 503


class TestGetMeNoSub:
    """Test get_me line 373: raises 401 when current_user has no sub."""

    def test_get_me_no_sub_401(self, test_client: TestClient) -> None:
        """Line 373: get_me raises 401 when current_user lacks 'sub'."""
        from api.api import _get_current_user, app

        async def override_no_sub() -> dict[str, str]:
            return {"email": "x@y.com"}

        app.dependency_overrides[_get_current_user] = override_no_sub
        try:
            response = test_client.get("/api/auth/me")
            assert response.status_code == 401
        finally:
            del app.dependency_overrides[_get_current_user]


class TestGetMeServiceEdgeCases:
    """Additional get_me edge cases."""

    def test_get_me_pool_none_503(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        import api.api as api_module

        original_pool = api_module._pool
        api_module._pool = None
        try:
            response = test_client.get("/api/auth/me", headers=auth_headers)
            assert response.status_code == 503
        finally:
            api_module._pool = original_pool

    def test_get_me_no_sub_in_valid_token_401(
        self,
        test_client: TestClient,
    ) -> None:
        """Token valid signature but missing 'sub' → 401."""
        import base64
        import hashlib
        import hmac
        import json

        from tests.api.conftest import TEST_JWT_SECRET

        def b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

        header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
        body = b64url(json.dumps({"email": "x@y.com", "exp": 9_999_999_999}, separators=(",", ":")).encode())
        signing_input = f"{header}.{body}".encode("ascii")
        sig = b64url(hmac.new(TEST_JWT_SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest())
        token = f"{header}.{body}.{sig}"
        response = test_client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401


class TestLogoutEndpoint:
    """Tests for POST /api/auth/logout."""

    def test_logout_no_auth_returns_401(self, test_client: TestClient) -> None:
        response = test_client.post("/api/auth/logout")
        assert response.status_code in (401, 403)

    def test_logout_success(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        response = test_client.post("/api/auth/logout", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["logged_out"] is True

    def test_logout_revokes_jti_in_redis(self, test_client: TestClient, mock_redis: AsyncMock) -> None:
        from api.api import _create_access_token

        token, _ = _create_access_token(TEST_USER_ID, TEST_USER_EMAIL)
        response = test_client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        mock_redis.setex.assert_awaited_once()
        assert mock_redis.setex.call_args[0][0].startswith("revoked:jti:")

    def test_logout_redis_none_succeeds_gracefully(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        import api.api as api_module

        original = api_module._redis
        api_module._redis = None
        try:
            response = test_client.post("/api/auth/logout", headers=auth_headers)
            assert response.status_code == 200
        finally:
            api_module._redis = original


class TestJtiBlacklist:
    """Tests for JTI blacklist check in _get_current_user."""

    def test_revoked_jti_returns_401(self, test_client: TestClient, mock_redis: AsyncMock) -> None:
        from api.api import _create_access_token

        token, _ = _create_access_token(TEST_USER_ID, TEST_USER_EMAIL)
        mock_redis.get.return_value = "1"  # jti is revoked
        response = test_client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401

    def test_non_revoked_jti_allows_access(
        self, test_client: TestClient, mock_redis: AsyncMock, mock_cur: AsyncMock, auth_headers: dict[str, str]
    ) -> None:
        from datetime import UTC, datetime

        mock_redis.get.return_value = None  # not revoked
        mock_cur.fetchone.return_value = {
            "id": TEST_USER_ID,
            "email": TEST_USER_EMAIL,
            "is_active": True,
            "created_at": datetime.now(UTC),
        }
        response = test_client.get("/api/auth/me", headers=auth_headers)
        assert response.status_code == 200

    def test_create_access_token_includes_jti(self, test_client: TestClient) -> None:  # noqa: ARG002
        from api.api import _create_access_token, _decode_access_token

        token, _ = _create_access_token(TEST_USER_ID, TEST_USER_EMAIL)
        payload = _decode_access_token(token)
        assert "jti" in payload
        assert isinstance(payload["jti"], str)
        assert len(payload["jti"]) > 0

    def test_jti_is_unique_per_token(self, test_client: TestClient) -> None:  # noqa: ARG002
        from api.api import _create_access_token, _decode_access_token

        t1, _ = _create_access_token(TEST_USER_ID, TEST_USER_EMAIL)
        t2, _ = _create_access_token(TEST_USER_ID, TEST_USER_EMAIL)
        assert _decode_access_token(t1)["jti"] != _decode_access_token(t2)["jti"]


class TestSecurityHeaders:
    """Tests for security headers middleware."""

    def test_x_content_type_options_nosniff(self, test_client: TestClient) -> None:
        response = test_client.get("/health")
        assert response.headers.get("x-content-type-options") == "nosniff"

    def test_x_frame_options_deny(self, test_client: TestClient) -> None:
        response = test_client.get("/health")
        assert response.headers.get("x-frame-options") == "DENY"

    def test_referrer_policy(self, test_client: TestClient) -> None:
        response = test_client.get("/health")
        assert response.headers.get("referrer-policy") == "strict-origin-when-cross-origin"

    def test_permissions_policy(self, test_client: TestClient) -> None:
        response = test_client.get("/health")
        assert "geolocation=()" in response.headers.get("permissions-policy", "")


class TestBlindRegistration:
    """Tests for L1: blind registration (no user enumeration)."""

    def test_duplicate_email_returns_201_not_409(self, test_client: TestClient, mock_cur: AsyncMock) -> None:
        mock_cur.execute.side_effect = Exception("unique constraint violation")
        response = test_client.post("/api/auth/register", json={"email": "dup@example.com", "password": "Password123!"})
        assert response.status_code == 201

    def test_duplicate_and_success_return_same_body(self, test_client: TestClient, mock_cur: AsyncMock) -> None:
        from datetime import UTC, datetime

        # Success case
        mock_cur.execute.side_effect = None
        mock_cur.fetchone.return_value = {"id": TEST_USER_ID, "email": TEST_USER_EMAIL, "is_active": True, "created_at": datetime.now(UTC)}
        r1 = test_client.post("/api/auth/register", json={"email": "a@b.com", "password": "Password123!"})

        # Duplicate case
        mock_cur.execute.side_effect = Exception("duplicate key value violates unique constraint")
        r2 = test_client.post("/api/auth/register", json={"email": "a@b.com", "password": "Password123!"})

        assert r1.status_code == r2.status_code == 201
        assert r1.json() == r2.json()

    def test_register_response_no_user_details(self, test_client: TestClient, mock_cur: AsyncMock) -> None:
        from datetime import UTC, datetime

        mock_cur.fetchone.return_value = {"id": TEST_USER_ID, "email": TEST_USER_EMAIL, "is_active": True, "created_at": datetime.now(UTC)}
        response = test_client.post("/api/auth/register", json={"email": TEST_USER_EMAIL, "password": "Password123!"})
        data = response.json()
        assert "id" not in data
        assert "hashed_password" not in data
