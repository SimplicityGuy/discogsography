"""Tests for auth router — password reset and 2FA endpoints."""

import json
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from tests.api.conftest import TEST_USER_EMAIL, TEST_USER_ID, make_sample_user_row


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
        mock_cur.fetchone = AsyncMock(return_value=make_sample_user_row())
        mock_redis.get = AsyncMock(return_value=None)
        response = test_client.post("/api/auth/2fa/setup", headers=auth_headers)
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


class TestTwoFactorRecovery:
    """Tests for POST /api/auth/2fa/recovery."""

    def test_recovery_invalid_challenge(self, test_client: TestClient) -> None:
        response = test_client.post(
            "/api/auth/2fa/recovery",
            json={"challenge_token": "bad.token.here", "code": "some-recovery-code"},
        )
        assert response.status_code == 401
