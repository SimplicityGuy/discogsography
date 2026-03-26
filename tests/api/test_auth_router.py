"""Tests for auth router — password reset and 2FA endpoints."""

import json
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from tests.api.conftest import TEST_USER_EMAIL, TEST_USER_ID, make_sample_user_row, make_test_jwt


class TestResetRequest:
    """Tests for POST /api/auth/reset-request."""

    def test_reset_request_known_email(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
        mock_redis: AsyncMock,
    ) -> None:
        mock_cur.fetchone = AsyncMock(return_value=make_sample_user_row())
        response = test_client.post("/api/auth/reset-request", json={"email": TEST_USER_EMAIL})
        assert response.status_code == 200
        assert "message" in response.json()
        mock_redis.setex.assert_called()

    def test_reset_request_unknown_email_same_response(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
    ) -> None:
        mock_cur.fetchone = AsyncMock(return_value=None)
        response = test_client.post("/api/auth/reset-request", json={"email": "unknown@example.com"})
        assert response.status_code == 200
        assert "message" in response.json()

    def test_reset_request_normalizes_email(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
    ) -> None:
        mock_cur.fetchone = AsyncMock(return_value=None)
        response = test_client.post("/api/auth/reset-request", json={"email": " Test@Example.COM "})
        assert response.status_code == 200


class TestResetConfirm:
    """Tests for POST /api/auth/reset-confirm."""

    def test_reset_confirm_valid_token(
        self,
        test_client: TestClient,
        mock_redis: AsyncMock,
    ) -> None:
        mock_redis.get = AsyncMock(
            return_value=json.dumps(
                {
                    "user_id": TEST_USER_ID,
                    "email": TEST_USER_EMAIL,
                }
            )
        )
        response = test_client.post(
            "/api/auth/reset-confirm",
            json={"token": "valid-token", "new_password": "newpassword123"},
        )
        assert response.status_code == 200
        assert "reset" in response.json()["message"].lower()
        mock_redis.delete.assert_called()

    def test_reset_confirm_invalid_token(
        self,
        test_client: TestClient,
        mock_redis: AsyncMock,
    ) -> None:
        mock_redis.get = AsyncMock(return_value=None)
        response = test_client.post(
            "/api/auth/reset-confirm",
            json={"token": "invalid-token", "new_password": "newpassword123"},
        )
        assert response.status_code == 400

    def test_reset_confirm_short_password(self, test_client: TestClient) -> None:
        response = test_client.post(
            "/api/auth/reset-confirm",
            json={"token": "some-token", "new_password": "short"},
        )
        assert response.status_code == 422  # Pydantic validation


class TestTwoFactorSetup:
    """Tests for POST /api/auth/2fa/setup."""

    def test_setup_returns_secret_and_qr_uri(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
        mock_cur: AsyncMock,
        mock_redis: AsyncMock,
    ) -> None:
        import base64
        from dataclasses import replace

        import api.routers.auth as auth_router

        mock_cur.fetchone = AsyncMock(return_value=make_sample_user_row())
        mock_redis.get = AsyncMock(return_value=None)
        # Temporarily set encryption master key for 2FA setup
        test_key = base64.urlsafe_b64encode(b"test-master-key-padded-to-32!!").decode("ascii")
        original_config = auth_router._config
        auth_router._config = replace(original_config, encryption_master_key=test_key)
        try:
            response = test_client.post("/api/auth/2fa/setup", headers=auth_headers)
        finally:
            auth_router._config = original_config
        assert response.status_code == 200
        data = response.json()
        assert "secret" in data
        assert "otpauth_uri" in data
        assert "recovery_codes" in data
        assert len(data["recovery_codes"]) == 8
        assert "otpauth://totp/" in data["otpauth_uri"]


class TestTwoFactorVerify:
    """Tests for POST /api/auth/2fa/verify."""

    def test_verify_invalid_challenge_token(self, test_client: TestClient) -> None:
        response = test_client.post(
            "/api/auth/2fa/verify",
            json={"challenge_token": "invalid.token.here", "code": "123456"},
        )
        assert response.status_code == 401


class TestTwoFactorDisable:
    """Tests for POST /api/auth/2fa/disable."""

    def test_disable_requires_auth(self, test_client: TestClient) -> None:
        response = test_client.post(
            "/api/auth/2fa/disable",
            json={"code": "123456", "password": "testpassword"},
        )
        assert response.status_code in (401, 403)


class TestPasswordChangedRevocation:
    """Tests for password_changed_at session revocation in _get_current_user."""

    def test_token_revoked_after_password_change(
        self,
        test_client: TestClient,
        mock_redis: AsyncMock,
        mock_cur: AsyncMock,
    ) -> None:
        """Token issued before password change should be rejected."""
        import base64
        import hashlib
        import hmac
        import time

        from tests.api.conftest import TEST_JWT_SECRET, TEST_USER_ID

        # Create a JWT with an explicit iat in the past
        old_iat = int(time.time()) - 120

        def b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

        header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
        body = b64url(
            json.dumps(
                {
                    "sub": TEST_USER_ID,
                    "email": "test@example.com",
                    "exp": int(time.time()) + 3600,
                    "iat": old_iat,
                },
                separators=(",", ":"),
            ).encode()
        )
        sig = b64url(hmac.new(TEST_JWT_SECRET.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest())
        token = f"{header}.{body}.{sig}"

        # password_changed timestamp is AFTER iat
        pw_changed_ts = str(int(time.time()) - 60)

        async def redis_get_side_effect(key: str) -> str | None:
            if "password_changed:" in key:
                return pw_changed_ts
            return None  # jti not revoked

        mock_redis.get = AsyncMock(side_effect=redis_get_side_effect)
        mock_cur.fetchone = AsyncMock(return_value=make_sample_user_row())

        response = test_client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401

    def test_token_valid_when_no_password_change(
        self,
        test_client: TestClient,
        mock_redis: AsyncMock,
        mock_cur: AsyncMock,
    ) -> None:
        """Token should work when no password change recorded."""
        mock_redis.get = AsyncMock(return_value=None)
        mock_cur.fetchone = AsyncMock(return_value=make_sample_user_row())

        response = test_client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {make_test_jwt()}"},
        )
        assert response.status_code == 200


class TestTwoFactorRecovery:
    """Tests for POST /api/auth/2fa/recovery."""

    def test_recovery_invalid_challenge(self, test_client: TestClient) -> None:
        response = test_client.post(
            "/api/auth/2fa/recovery",
            json={"challenge_token": "bad.token.here", "code": "some-recovery-code"},
        )
        assert response.status_code == 401
