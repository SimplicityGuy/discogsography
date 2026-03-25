"""Tests for admin router endpoints."""

from __future__ import annotations

import asyncio
import base64
from datetime import UTC, datetime
import hashlib
import hmac
import json
import secrets
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest


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
        # Verify force_reprocess was sent in request body
        mock_client_instance.post.assert_called_once()
        call_kwargs = mock_client_instance.post.call_args
        assert call_kwargs.kwargs.get("json") == {"force_reprocess": True}

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

    @patch("api.routers.admin.httpx.AsyncClient")
    def test_purge_200_response(self, mock_client_cls: Any, test_client: TestClient) -> None:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.content = b'{"messages_purged": 5}'
        mock_response.json = MagicMock(return_value={"messages_purged": 5})
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
        assert resp.json()["messages_purged"] == 5

    @patch("api.routers.admin.httpx.AsyncClient")
    def test_purge_200_empty_body(self, mock_client_cls: Any, test_client: TestClient) -> None:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.content = b""
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
        assert resp.json()["messages_purged"] == 0

    @patch("api.routers.admin.httpx.AsyncClient")
    def test_purge_bad_gateway(self, mock_client_cls: Any, test_client: TestClient) -> None:
        mock_response = AsyncMock()
        mock_response.status_code = 500
        mock_client_instance = AsyncMock()
        mock_client_instance.delete = AsyncMock(return_value=mock_response)
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client_instance

        resp = test_client.post(
            "/api/admin/dlq/purge/graphinator-artists-dlq",
            headers=_admin_auth_headers(),
        )
        assert resp.status_code == 502

    @patch("api.routers.admin.httpx.AsyncClient")
    def test_purge_connection_error(self, mock_client_cls: Any, test_client: TestClient) -> None:
        mock_client_instance = AsyncMock()
        mock_client_instance.delete = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client_instance

        resp = test_client.post(
            "/api/admin/dlq/purge/graphinator-artists-dlq",
            headers=_admin_auth_headers(),
        )
        assert resp.status_code == 502


class TestGetExtraction:
    def test_success(self, test_client: TestClient, mock_cur: AsyncMock) -> None:
        extraction_id = str(uuid4())
        mock_cur.fetchone = AsyncMock(
            return_value={
                "id": extraction_id,
                "triggered_by": TEST_ADMIN_ID,
                "status": "completed",
                "started_at": datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
                "completed_at": datetime(2026, 1, 1, 0, 10, tzinfo=UTC),
                "record_counts": {"artists": 100},
                "error_message": None,
                "extractor_version": "1.0.0",
                "created_at": datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
            }
        )

        resp = test_client.get(
            f"/api/admin/extractions/{extraction_id}",
            headers=_admin_auth_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["duration_seconds"] == 600.0

    def test_not_found(self, test_client: TestClient, mock_cur: AsyncMock) -> None:
        mock_cur.fetchone = AsyncMock(return_value=None)

        resp = test_client.get(
            f"/api/admin/extractions/{uuid4()}",
            headers=_admin_auth_headers(),
        )
        assert resp.status_code == 404

    def test_no_duration_when_incomplete(self, test_client: TestClient, mock_cur: AsyncMock) -> None:
        extraction_id = str(uuid4())
        mock_cur.fetchone = AsyncMock(
            return_value={
                "id": extraction_id,
                "triggered_by": TEST_ADMIN_ID,
                "status": "running",
                "started_at": datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
                "completed_at": None,
                "record_counts": None,
                "error_message": None,
                "extractor_version": None,
                "created_at": datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
            }
        )

        resp = test_client.get(
            f"/api/admin/extractions/{extraction_id}",
            headers=_admin_auth_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["duration_seconds"] is None


class TestExtractionListWithData:
    def test_list_with_rows(self, test_client: TestClient, mock_cur: AsyncMock) -> None:
        extraction_id = str(uuid4())
        mock_cur.fetchone = AsyncMock(return_value={"total": 1})
        mock_cur.fetchall = AsyncMock(
            return_value=[
                {
                    "id": extraction_id,
                    "triggered_by": TEST_ADMIN_ID,
                    "status": "completed",
                    "started_at": datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
                    "completed_at": datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
                    "record_counts": {"artists": 50},
                    "error_message": None,
                    "extractor_version": "1.0.0",
                    "created_at": datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
                }
            ]
        )

        resp = test_client.get(
            "/api/admin/extractions",
            headers=_admin_auth_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["extractions"]) == 1
        assert data["extractions"][0]["duration_seconds"] == 300.0


class TestExtractionTriggerEdgeCases:
    @patch("api.routers.admin.httpx.AsyncClient")
    def test_unexpected_status(self, mock_client_cls: Any, test_client: TestClient, mock_cur: AsyncMock) -> None:
        extraction_id = str(uuid4())
        mock_cur.fetchone = AsyncMock(return_value={"id": extraction_id})

        mock_response = AsyncMock()
        mock_response.status_code = 500
        mock_client_instance = AsyncMock()
        mock_client_instance.post = AsyncMock(return_value=mock_response)
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client_instance

        resp = test_client.post(
            "/api/admin/extractions/trigger",
            headers=_admin_auth_headers(),
        )
        assert resp.status_code == 502

    @patch("api.routers.admin.httpx.AsyncClient")
    def test_connection_error(self, mock_client_cls: Any, test_client: TestClient, mock_cur: AsyncMock) -> None:
        extraction_id = str(uuid4())
        mock_cur.fetchone = AsyncMock(return_value={"id": extraction_id})

        mock_client_instance = AsyncMock()
        mock_client_instance.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client_instance

        resp = test_client.post(
            "/api/admin/extractions/trigger",
            headers=_admin_auth_headers(),
        )
        assert resp.status_code == 503

    def test_create_record_failure(self, test_client: TestClient, mock_cur: AsyncMock) -> None:
        mock_cur.fetchone = AsyncMock(return_value=None)

        resp = test_client.post(
            "/api/admin/extractions/trigger",
            headers=_admin_auth_headers(),
        )
        assert resp.status_code == 500


class TestServiceNotReady:
    def test_login_not_ready(self, test_client: TestClient) -> None:
        import api.routers.admin as admin_mod

        original_pool = admin_mod._pool
        admin_mod._pool = None
        try:
            resp = test_client.post(
                "/api/admin/auth/login",
                json={"email": "a@b.com", "password": "password123"},
            )
            assert resp.status_code == 503
        finally:
            admin_mod._pool = original_pool

    def test_list_extractions_not_ready(self, test_client: TestClient) -> None:
        import api.routers.admin as admin_mod

        original_pool = admin_mod._pool
        admin_mod._pool = None
        try:
            resp = test_client.get(
                "/api/admin/extractions",
                headers=_admin_auth_headers(),
            )
            assert resp.status_code == 503
        finally:
            admin_mod._pool = original_pool

    def test_get_extraction_not_ready(self, test_client: TestClient) -> None:
        import api.routers.admin as admin_mod

        original_pool = admin_mod._pool
        admin_mod._pool = None
        try:
            resp = test_client.get(
                f"/api/admin/extractions/{uuid4()}",
                headers=_admin_auth_headers(),
            )
            assert resp.status_code == 503
        finally:
            admin_mod._pool = original_pool

    def test_trigger_not_ready(self, test_client: TestClient) -> None:
        import api.routers.admin as admin_mod

        original_pool = admin_mod._pool
        admin_mod._pool = None
        try:
            resp = test_client.post(
                "/api/admin/extractions/trigger",
                headers=_admin_auth_headers(),
            )
            assert resp.status_code == 503
        finally:
            admin_mod._pool = original_pool

    def test_dlq_purge_not_ready(self, test_client: TestClient) -> None:
        import api.routers.admin as admin_mod

        original_config = admin_mod._config
        admin_mod._config = None
        try:
            resp = test_client.post(
                "/api/admin/dlq/purge/graphinator-artists-dlq",
                headers=_admin_auth_headers(),
            )
            assert resp.status_code == 503
        finally:
            admin_mod._config = original_config


class TestTrackExtraction:
    @pytest.mark.asyncio
    async def test_completed_extraction(self) -> None:
        import api.routers.admin as admin_mod

        mock_pool = MagicMock()
        mock_cur = AsyncMock()
        mock_conn = AsyncMock()
        cur_ctx = AsyncMock()
        cur_ctx.__aenter__ = AsyncMock(return_value=mock_cur)
        cur_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_conn.cursor = MagicMock(return_value=cur_ctx)
        conn_ctx = AsyncMock()
        conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        conn_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_pool.connection = MagicMock(return_value=conn_ctx)

        mock_config = MagicMock()
        mock_config.extractor_host = "localhost"
        mock_config.extractor_health_port = 8000

        original_pool = admin_mod._pool
        original_config = admin_mod._config
        admin_mod._pool = mock_pool
        admin_mod._config = mock_config

        extraction_id = str(uuid4())

        with (
            patch("api.routers.admin.asyncio.sleep", new_callable=AsyncMock),
            patch("api.routers.admin.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "extraction_status": "completed",
                "extraction_progress": {"artists": 100, "labels": 50, "masters": 25, "releases": 200},
            }
            mock_client_instance = AsyncMock()
            mock_client_instance.get = AsyncMock(return_value=mock_response)
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client_instance

            await admin_mod._track_extraction(extraction_id)

        admin_mod._pool = original_pool
        admin_mod._config = original_config

    @pytest.mark.asyncio
    async def test_failed_extraction(self) -> None:
        import api.routers.admin as admin_mod

        mock_pool = MagicMock()
        mock_cur = AsyncMock()
        mock_conn = AsyncMock()
        cur_ctx = AsyncMock()
        cur_ctx.__aenter__ = AsyncMock(return_value=mock_cur)
        cur_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_conn.cursor = MagicMock(return_value=cur_ctx)
        conn_ctx = AsyncMock()
        conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        conn_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_pool.connection = MagicMock(return_value=conn_ctx)

        mock_config = MagicMock()
        mock_config.extractor_host = "localhost"
        mock_config.extractor_health_port = 8000

        original_pool = admin_mod._pool
        original_config = admin_mod._config
        admin_mod._pool = mock_pool
        admin_mod._config = mock_config

        extraction_id = str(uuid4())

        with (
            patch("api.routers.admin.asyncio.sleep", new_callable=AsyncMock),
            patch("api.routers.admin.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "extraction_status": "failed",
                "error_message": "Disk full",
                "extraction_progress": {"artists": 10, "labels": 0, "masters": 0, "releases": 0},
            }
            mock_client_instance = AsyncMock()
            mock_client_instance.get = AsyncMock(return_value=mock_response)
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client_instance

            await admin_mod._track_extraction(extraction_id)

        admin_mod._pool = original_pool
        admin_mod._config = original_config

    @pytest.mark.asyncio
    async def test_unreachable_extractor(self) -> None:
        import api.routers.admin as admin_mod

        mock_pool = MagicMock()
        mock_cur = AsyncMock()
        mock_conn = AsyncMock()
        cur_ctx = AsyncMock()
        cur_ctx.__aenter__ = AsyncMock(return_value=mock_cur)
        cur_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_conn.cursor = MagicMock(return_value=cur_ctx)
        conn_ctx = AsyncMock()
        conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        conn_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_pool.connection = MagicMock(return_value=conn_ctx)

        mock_config = MagicMock()
        mock_config.extractor_host = "localhost"
        mock_config.extractor_health_port = 8000

        original_pool = admin_mod._pool
        original_config = admin_mod._config
        admin_mod._pool = mock_pool
        admin_mod._config = mock_config

        extraction_id = str(uuid4())

        with (
            patch("api.routers.admin.asyncio.sleep", new_callable=AsyncMock),
            patch("api.routers.admin.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client_instance = AsyncMock()
            mock_client_instance.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client_instance

            await admin_mod._track_extraction(extraction_id)

        admin_mod._pool = original_pool
        admin_mod._config = original_config

    @pytest.mark.asyncio
    async def test_non_200_health_response(self) -> None:
        import api.routers.admin as admin_mod

        mock_pool = MagicMock()
        mock_cur = AsyncMock()
        mock_conn = AsyncMock()
        cur_ctx = AsyncMock()
        cur_ctx.__aenter__ = AsyncMock(return_value=mock_cur)
        cur_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_conn.cursor = MagicMock(return_value=cur_ctx)
        conn_ctx = AsyncMock()
        conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        conn_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_pool.connection = MagicMock(return_value=conn_ctx)

        mock_config = MagicMock()
        mock_config.extractor_host = "localhost"
        mock_config.extractor_health_port = 8000

        original_pool = admin_mod._pool
        original_config = admin_mod._config
        admin_mod._pool = mock_pool
        admin_mod._config = mock_config

        extraction_id = str(uuid4())

        with (
            patch("api.routers.admin.asyncio.sleep", new_callable=AsyncMock),
            patch("api.routers.admin.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_response = MagicMock()
            mock_response.status_code = 503
            mock_client_instance = AsyncMock()
            mock_client_instance.get = AsyncMock(return_value=mock_response)
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client_instance

            await admin_mod._track_extraction(extraction_id)

        admin_mod._pool = original_pool
        admin_mod._config = original_config

    @pytest.mark.asyncio
    async def test_cancelled(self) -> None:
        import api.routers.admin as admin_mod

        mock_pool = MagicMock()
        mock_config = MagicMock()
        mock_config.extractor_host = "localhost"
        mock_config.extractor_health_port = 8000

        original_pool = admin_mod._pool
        original_config = admin_mod._config
        admin_mod._pool = mock_pool
        admin_mod._config = mock_config

        extraction_id = str(uuid4())
        admin_mod._tracking_tasks[extraction_id] = MagicMock()

        with patch("api.routers.admin.asyncio.sleep", side_effect=asyncio.CancelledError):
            await admin_mod._track_extraction(extraction_id)

        assert extraction_id not in admin_mod._tracking_tasks

        admin_mod._pool = original_pool
        admin_mod._config = original_config

    @pytest.mark.asyncio
    async def test_no_pool(self) -> None:
        import api.routers.admin as admin_mod

        original_pool = admin_mod._pool
        admin_mod._pool = None

        await admin_mod._track_extraction("fake-id")

        admin_mod._pool = original_pool


class TestAdminTokenIsolation:
    def test_admin_token_rejected_on_user_endpoint(self, test_client: TestClient) -> None:
        """Admin tokens must not work on user endpoints."""
        admin_token = _make_admin_jwt()
        resp = test_client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 401


class TestRequireAdminRevocation:
    @pytest.mark.asyncio
    async def test_revoked_token(self) -> None:
        import api.dependencies as deps

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="1")  # Token is revoked
        deps.configure(TEST_JWT_SECRET, mock_redis)

        from fastapi import HTTPException
        from fastapi.security import HTTPAuthorizationCredentials

        token = _make_admin_jwt(jti="admin:revoked-jti")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        with pytest.raises(HTTPException) as exc_info:
            await deps.require_admin(creds)
        assert exc_info.value.status_code == 401
        assert "revoked" in exc_info.value.detail.lower()
