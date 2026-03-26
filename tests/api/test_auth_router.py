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
