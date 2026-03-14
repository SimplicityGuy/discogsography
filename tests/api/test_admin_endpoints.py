"""Tests for admin router endpoints."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
import hashlib
import hmac
import json
import secrets
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4


if TYPE_CHECKING:
    from fastapi.testclient import TestClient

from api.auth import _hash_password


TEST_JWT_SECRET = "test-jwt-secret-for-unit-tests"
TEST_ADMIN_ID = "00000000-0000-0000-0000-000000000099"
TEST_ADMIN_EMAIL = "admin@test.com"


def _make_admin_jwt(
    admin_id: str = TEST_ADMIN_ID,
    email: str = TEST_ADMIN_EMAIL,
    exp: int = 9_999_999_999,
    secret: str = TEST_JWT_SECRET,
    token_type: str = "admin",  # noqa: S107
    jti: str | None = None,
) -> str:
    """Create an admin JWT for testing."""

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = b64url(
        json.dumps(
            {
                "sub": admin_id,
                "email": email,
                "exp": exp,
                "type": token_type,
                "jti": jti or f"admin:{secrets.token_hex(16)}",
            },
            separators=(",", ":"),
        ).encode()
    )
    signing_input = f"{header}.{body}".encode("ascii")
    sig = b64url(hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest())
    return f"{header}.{body}.{sig}"


def _admin_auth_headers(token: str | None = None) -> dict[str, str]:
    """Return Authorization headers with an admin JWT."""
    if token is None:
        token = _make_admin_jwt()
    return {"Authorization": f"Bearer {token}"}


def _make_admin_row(
    admin_id: str = TEST_ADMIN_ID,
    email: str = TEST_ADMIN_EMAIL,
    is_active: bool = True,
    password: str | None = None,
) -> dict[str, Any]:
    """Create a sample dashboard_admins DB row."""
    if password is None:
        password = "adminpassword123"
    return {
        "id": admin_id,
        "email": email,
        "hashed_password": _hash_password(password),
        "is_active": is_active,
        "created_at": datetime.now(UTC),
    }


class TestAdminLogin:
    def test_success(self, test_client: TestClient, mock_cur: AsyncMock) -> None:
        admin_row = _make_admin_row()
        mock_cur.fetchone = AsyncMock(return_value=admin_row)

        resp = test_client.post(
            "/api/admin/auth/login",
            json={"email": TEST_ADMIN_EMAIL, "password": "adminpassword123"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] > 0

    def test_wrong_password(self, test_client: TestClient, mock_cur: AsyncMock) -> None:
        admin_row = _make_admin_row()
        mock_cur.fetchone = AsyncMock(return_value=admin_row)

        resp = test_client.post(
            "/api/admin/auth/login",
            json={"email": TEST_ADMIN_EMAIL, "password": "wrongpassword"},
        )
        assert resp.status_code == 401

    def test_nonexistent_admin(self, test_client: TestClient, mock_cur: AsyncMock) -> None:
        mock_cur.fetchone = AsyncMock(return_value=None)

        resp = test_client.post(
            "/api/admin/auth/login",
            json={"email": "nobody@test.com", "password": "anything"},
        )
        assert resp.status_code == 401

    def test_inactive_admin(self, test_client: TestClient, mock_cur: AsyncMock) -> None:
        admin_row = _make_admin_row(is_active=False)
        mock_cur.fetchone = AsyncMock(return_value=admin_row)

        resp = test_client.post(
            "/api/admin/auth/login",
            json={"email": TEST_ADMIN_EMAIL, "password": "adminpassword123"},
        )
        assert resp.status_code == 401


class TestAdminLogout:
    def test_success(self, test_client: TestClient, mock_redis: AsyncMock) -> None:
        resp = test_client.post(
            "/api/admin/auth/logout",
            headers=_admin_auth_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["logged_out"] is True
        mock_redis.setex.assert_called_once()

    def test_no_token(self, test_client: TestClient) -> None:
        resp = test_client.post("/api/admin/auth/logout")
        assert resp.status_code in (401, 403)


class TestExtractionTrigger:
    @patch("api.routers.admin.httpx.AsyncClient")
    def test_success(self, mock_client_cls: Any, test_client: TestClient, mock_cur: AsyncMock) -> None:
        extraction_id = str(uuid4())
        # First fetchone returns the INSERT RETURNING row, second is the UPDATE
        mock_cur.fetchone = AsyncMock(return_value={"id": extraction_id})

        mock_response = AsyncMock()
        mock_response.status_code = 202
        mock_client_instance = AsyncMock()
        mock_client_instance.post = AsyncMock(return_value=mock_response)
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client_instance

        resp = test_client.post(
            "/api/admin/extractions/trigger",
            headers=_admin_auth_headers(),
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "running"
        assert data["id"] == extraction_id

    @patch("api.routers.admin.httpx.AsyncClient")
    def test_already_running(self, mock_client_cls: Any, test_client: TestClient, mock_cur: AsyncMock) -> None:
        extraction_id = str(uuid4())
        mock_cur.fetchone = AsyncMock(return_value={"id": extraction_id})

        mock_response = AsyncMock()
        mock_response.status_code = 409
        mock_client_instance = AsyncMock()
        mock_client_instance.post = AsyncMock(return_value=mock_response)
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client_instance

        resp = test_client.post(
            "/api/admin/extractions/trigger",
            headers=_admin_auth_headers(),
        )
        assert resp.status_code == 409
        assert resp.json()["detail"] == "Extraction already in progress"

    def test_unauthorized(self, test_client: TestClient) -> None:
        resp = test_client.post("/api/admin/extractions/trigger")
        assert resp.status_code in (401, 403)


class TestExtractionList:
    def test_list_empty(self, test_client: TestClient, mock_cur: AsyncMock) -> None:
        mock_cur.fetchone = AsyncMock(return_value={"total": 0})
        mock_cur.fetchall = AsyncMock(return_value=[])

        resp = test_client.get(
            "/api/admin/extractions",
            headers=_admin_auth_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["extractions"] == []
        assert data["total"] == 0

    def test_unauthorized(self, test_client: TestClient) -> None:
        resp = test_client.get("/api/admin/extractions")
        assert resp.status_code in (401, 403)


class TestDlqPurge:
    @patch("api.routers.admin.httpx.AsyncClient")
    def test_valid_queue(self, mock_client_cls: Any, test_client: TestClient) -> None:
        mock_response = AsyncMock()
        mock_response.status_code = 204
        mock_client_instance = AsyncMock()
        mock_client_instance.delete = AsyncMock(return_value=mock_response)
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client_instance

        resp = test_client.post(
            "/api/admin/dlq/purge/graphinator-artists-dlq",
            headers=_admin_auth_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["queue"] == "graphinator-artists-dlq"
        assert data["messages_purged"] == 0

    def test_invalid_queue(self, test_client: TestClient) -> None:
        resp = test_client.post(
            "/api/admin/dlq/purge/nonexistent-queue",
            headers=_admin_auth_headers(),
        )
        assert resp.status_code == 404

    def test_unauthorized(self, test_client: TestClient) -> None:
        resp = test_client.post("/api/admin/dlq/purge/graphinator-artists-dlq")
        assert resp.status_code in (401, 403)
