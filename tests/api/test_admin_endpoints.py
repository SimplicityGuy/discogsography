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
    is_admin: bool = True,
    password: str | None = None,
) -> dict[str, Any]:
    """Create a sample users DB row."""
    if password is None:
        password = "adminpassword123"
    return {
        "id": admin_id,
        "email": email,
        "hashed_password": _hash_password(password),
        "is_active": is_active,
        "is_admin": is_admin,
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

    def test_non_admin_user_gets_403(self, test_client: TestClient, mock_cur: AsyncMock) -> None:
        admin_row = _make_admin_row(is_admin=False)
        mock_cur.fetchone = AsyncMock(return_value=admin_row)

        resp = test_client.post(
            "/api/admin/auth/login",
            json={"email": TEST_ADMIN_EMAIL, "password": "adminpassword123"},
        )
        assert resp.status_code == 403


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
            "/api/admin/dlq/purge/discogsography-discogs-graphinator-artists.dlq",
            headers=_admin_auth_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["queue"] == "discogsography-discogs-graphinator-artists.dlq"
        assert data["messages_purged"] == 0

    def test_invalid_queue(self, test_client: TestClient) -> None:
        resp = test_client.post(
            "/api/admin/dlq/purge/nonexistent-queue",
            headers=_admin_auth_headers(),
        )
        assert resp.status_code == 404

    def test_unauthorized(self, test_client: TestClient) -> None:
        resp = test_client.post("/api/admin/dlq/purge/discogsography-discogs-graphinator-artists.dlq")
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
            "/api/admin/dlq/purge/discogsography-discogs-graphinator-artists.dlq",
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
            "/api/admin/dlq/purge/discogsography-discogs-graphinator-artists.dlq",
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
            "/api/admin/dlq/purge/discogsography-discogs-graphinator-artists.dlq",
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
            "/api/admin/dlq/purge/discogsography-discogs-graphinator-artists.dlq",
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
                "/api/admin/dlq/purge/discogsography-discogs-graphinator-artists.dlq",
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

    @pytest.mark.asyncio
    async def test_timeout_after_max_iterations(self) -> None:
        """Test that extraction tracking times out after _MAX_TRACKING_ITERATIONS."""
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
        original_max = admin_mod._MAX_TRACKING_ITERATIONS
        admin_mod._pool = mock_pool
        admin_mod._config = mock_config
        admin_mod._MAX_TRACKING_ITERATIONS = 2  # Low iteration count for test

        extraction_id = str(uuid4())

        with (
            patch("api.routers.admin.asyncio.sleep", new_callable=AsyncMock),
            patch("api.routers.admin.httpx.AsyncClient") as mock_client_cls,
        ):
            # Return "extracting" status (non-terminal) forever
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "extraction_status": "extracting",
                "extraction_progress": {"artists": 50, "labels": 25, "masters": 10, "releases": 100},
            }
            mock_client_instance = AsyncMock()
            mock_client_instance.get = AsyncMock(return_value=mock_response)
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client_instance

            await admin_mod._track_extraction(extraction_id)

        # Verify the extraction was marked as failed due to timeout
        calls = mock_cur.execute.call_args_list
        final_call_sql = calls[-1][0][0]
        assert "failed" in final_call_sql
        assert "timed out" in calls[-1][0][1][0]

        admin_mod._pool = original_pool
        admin_mod._config = original_config
        admin_mod._MAX_TRACKING_ITERATIONS = original_max


# ---------------------------------------------------------------------------
# Phase 2 endpoint tests — User Stats, Sync Activity, Storage
# ---------------------------------------------------------------------------


class TestUserStatsEndpoint:
    """Tests for GET /api/admin/users/stats."""

    def test_returns_200_with_admin_token(self, test_client: TestClient) -> None:
        with patch("api.routers.admin.get_user_stats", new_callable=AsyncMock) as mock_fn:
            mock_fn.return_value = {
                "total_users": 10,
                "active_7d": 5,
                "active_30d": 8,
                "oauth_connection_rate": 0.5,
                "registrations": {"daily": [], "weekly": [], "monthly": []},
            }
            resp = test_client.get("/api/admin/users/stats", headers=_admin_auth_headers())
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_users"] == 10

    def test_rejects_without_token(self, test_client: TestClient) -> None:
        resp = test_client.get("/api/admin/users/stats")
        assert resp.status_code == 401

    def test_rejects_user_token(self, test_client: TestClient, valid_token: str) -> None:
        resp = test_client.get(
            "/api/admin/users/stats",
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert resp.status_code in (401, 403)

    def test_user_stats_not_ready(self, test_client: TestClient) -> None:
        import api.routers.admin as admin_mod

        original_pool = admin_mod._pool
        admin_mod._pool = None
        try:
            resp = test_client.get("/api/admin/users/stats", headers=_admin_auth_headers())
            assert resp.status_code == 503
        finally:
            admin_mod._pool = original_pool


class TestSyncActivityEndpoint:
    """Tests for GET /api/admin/users/sync-activity."""

    def test_returns_200_with_admin_token(self, test_client: TestClient) -> None:
        with patch("api.routers.admin.get_sync_activity", new_callable=AsyncMock) as mock_fn:
            period = {
                "total_syncs": 10,
                "syncs_per_day": 1.4,
                "avg_items_synced": 50.0,
                "failure_rate": 0.1,
                "total_failures": 1,
            }
            mock_fn.return_value = {"period_7d": period, "period_30d": period}
            resp = test_client.get("/api/admin/users/sync-activity", headers=_admin_auth_headers())
            assert resp.status_code == 200

    def test_rejects_without_token(self, test_client: TestClient) -> None:
        resp = test_client.get("/api/admin/users/sync-activity")
        assert resp.status_code == 401

    def test_sync_activity_not_ready(self, test_client: TestClient) -> None:
        import api.routers.admin as admin_mod

        original_pool = admin_mod._pool
        admin_mod._pool = None
        try:
            resp = test_client.get("/api/admin/users/sync-activity", headers=_admin_auth_headers())
            assert resp.status_code == 503
        finally:
            admin_mod._pool = original_pool


class TestStorageEndpoint:
    """Tests for GET /api/admin/storage."""

    def test_returns_200_with_all_sources(self, test_client: TestClient) -> None:
        with (
            patch("api.routers.admin.get_neo4j_storage", new_callable=AsyncMock) as mock_neo4j,
            patch("api.routers.admin.get_postgres_storage", new_callable=AsyncMock) as mock_pg,
            patch("api.routers.admin.get_redis_storage", new_callable=AsyncMock) as mock_redis,
        ):
            mock_neo4j.return_value = {"status": "ok", "nodes": [], "relationships": [], "store_sizes": None}
            mock_pg.return_value = {"status": "ok", "tables": [], "total_size": "10 MB"}
            mock_redis.return_value = {"status": "ok", "memory_used": "1M", "memory_peak": "2M", "total_keys": 5, "keys_by_prefix": {}}
            resp = test_client.get("/api/admin/storage", headers=_admin_auth_headers())
            assert resp.status_code == 200
            data = resp.json()
            assert data["neo4j"]["status"] == "ok"
            assert data["postgresql"]["status"] == "ok"
            assert data["redis"]["status"] == "ok"

    def test_partial_failure(self, test_client: TestClient) -> None:
        with (
            patch("api.routers.admin.get_neo4j_storage", new_callable=AsyncMock) as mock_neo4j,
            patch("api.routers.admin.get_postgres_storage", new_callable=AsyncMock) as mock_pg,
            patch("api.routers.admin.get_redis_storage", new_callable=AsyncMock) as mock_redis,
        ):
            mock_neo4j.side_effect = Exception("connection refused")
            mock_pg.return_value = {"status": "ok", "tables": [], "total_size": "10 MB"}
            mock_redis.return_value = {"status": "ok", "memory_used": "1M", "memory_peak": "2M", "total_keys": 0, "keys_by_prefix": {}}
            resp = test_client.get("/api/admin/storage", headers=_admin_auth_headers())
            assert resp.status_code == 200
            data = resp.json()
            assert data["neo4j"]["status"] == "error"
            assert data["postgresql"]["status"] == "ok"

    def test_rejects_without_token(self, test_client: TestClient) -> None:
        resp = test_client.get("/api/admin/storage")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Phase 3 endpoint tests — Queue History, Health History
# ---------------------------------------------------------------------------


class TestQueueHistory:
    @patch("api.routers.admin.get_queue_history")
    def test_success(self, mock_query: Any, test_client: TestClient) -> None:
        mock_query.return_value = {"range": "24h", "granularity": "15min", "queues": {}, "dlq_summary": {}}
        resp = test_client.get("/api/admin/queues/history?range=24h", headers=_admin_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["range"] == "24h"

    def test_no_token_returns_401_or_403(self, test_client: TestClient) -> None:
        resp = test_client.get("/api/admin/queues/history")
        assert resp.status_code in (401, 403)

    @patch("api.routers.admin.get_queue_history")
    def test_invalid_range_returns_422(self, mock_query: Any, test_client: TestClient) -> None:
        mock_query.side_effect = ValueError("Invalid range: 2h")
        resp = test_client.get("/api/admin/queues/history?range=2h", headers=_admin_auth_headers())
        assert resp.status_code == 422

    @patch("api.routers.admin.get_queue_history")
    def test_default_range_is_24h(self, mock_query: Any, test_client: TestClient) -> None:
        mock_query.return_value = {"range": "24h", "granularity": "15min", "queues": {}, "dlq_summary": {}}
        resp = test_client.get("/api/admin/queues/history", headers=_admin_auth_headers())
        assert resp.status_code == 200
        mock_query.assert_called_once()
        call_args = mock_query.call_args
        assert call_args[0][1] == "24h"


class TestHealthHistory:
    @patch("api.routers.admin.get_health_history")
    def test_success(self, mock_query: Any, test_client: TestClient) -> None:
        mock_query.return_value = {"range": "7d", "granularity": "1hour", "services": {}, "api_endpoints": {}}
        resp = test_client.get("/api/admin/health/history?range=7d", headers=_admin_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["range"] == "7d"

    def test_no_token_returns_401_or_403(self, test_client: TestClient) -> None:
        resp = test_client.get("/api/admin/health/history")
        assert resp.status_code in (401, 403)

    @patch("api.routers.admin.get_health_history")
    def test_invalid_range_returns_422(self, mock_query: Any, test_client: TestClient) -> None:
        mock_query.side_effect = ValueError("Invalid range: bad")
        resp = test_client.get("/api/admin/health/history?range=bad", headers=_admin_auth_headers())
        assert resp.status_code == 422


class TestQueueHistoryServiceUnavailable:
    def test_returns_503_when_pool_is_none(self, test_client: TestClient) -> None:
        """Queue history returns 503 when _pool is not configured."""
        import api.routers.admin as admin_mod

        original = admin_mod._pool
        admin_mod._pool = None
        try:
            resp = test_client.get("/api/admin/queues/history", headers=_admin_auth_headers())
            assert resp.status_code == 503
        finally:
            admin_mod._pool = original


class TestHealthHistoryServiceUnavailable:
    def test_returns_503_when_pool_is_none(self, test_client: TestClient) -> None:
        """Health history returns 503 when _pool is not configured."""
        import api.routers.admin as admin_mod

        original = admin_mod._pool
        admin_mod._pool = None
        try:
            resp = test_client.get("/api/admin/health/history", headers=_admin_auth_headers())
            assert resp.status_code == 503
        finally:
            admin_mod._pool = original


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


# ---------------------------------------------------------------------------
# Phase 4 — Audit Log endpoint tests
# ---------------------------------------------------------------------------


class TestAuditLog:
    @patch("api.routers.admin.get_audit_log")
    def test_list_audit_log(self, mock_get_audit_log: Any, test_client: TestClient) -> None:
        mock_get_audit_log.return_value = {
            "entries": [
                {
                    "id": "00000000-0000-0000-0000-000000000001",
                    "admin_id": TEST_ADMIN_ID,
                    "admin_email": TEST_ADMIN_EMAIL,
                    "action": "admin.login",
                    "target": TEST_ADMIN_EMAIL,
                    "details": {"success": True},
                    "created_at": datetime.now(UTC).isoformat(),
                },
            ],
            "total": 1,
            "page": 1,
            "page_size": 50,
        }

        resp = test_client.get(
            "/api/admin/audit-log",
            headers=_admin_auth_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["entries"]) == 1
        assert data["entries"][0]["action"] == "admin.login"

    def test_audit_log_requires_admin(self, test_client: TestClient) -> None:
        resp = test_client.get("/api/admin/audit-log")
        assert resp.status_code in (401, 403)

    @patch("api.routers.admin._pool", None)
    def test_audit_log_503_when_pool_none(self, test_client: TestClient) -> None:
        resp = test_client.get(
            "/api/admin/audit-log",
            headers=_admin_auth_headers(),
        )
        assert resp.status_code == 503

    @patch("api.routers.admin.get_audit_log")
    def test_audit_log_passes_pagination_params(self, mock_get_audit_log: Any, test_client: TestClient) -> None:
        """Verify page and page_size are forwarded to the query function."""
        mock_get_audit_log.return_value = {"entries": [], "total": 0, "page": 3, "page_size": 25}

        resp = test_client.get(
            "/api/admin/audit-log?page=3&page_size=25",
            headers=_admin_auth_headers(),
        )
        assert resp.status_code == 200
        mock_get_audit_log.assert_called_once()
        call_kwargs = mock_get_audit_log.call_args
        assert call_kwargs.kwargs.get("page") == 3 or call_kwargs[1].get("page") == 3
        assert call_kwargs.kwargs.get("page_size") == 25 or call_kwargs[1].get("page_size") == 25

    @patch("api.routers.admin.get_audit_log")
    def test_audit_log_passes_action_filter(self, mock_get_audit_log: Any, test_client: TestClient) -> None:
        """Verify action filter is forwarded to the query function."""
        mock_get_audit_log.return_value = {"entries": [], "total": 0, "page": 1, "page_size": 50}

        resp = test_client.get(
            "/api/admin/audit-log?action=dlq.purge",
            headers=_admin_auth_headers(),
        )
        assert resp.status_code == 200
        call_kwargs = mock_get_audit_log.call_args
        assert call_kwargs.kwargs.get("action_filter") == "dlq.purge" or call_kwargs[1].get("action_filter") == "dlq.purge"

    @patch("api.routers.admin.get_audit_log")
    def test_audit_log_clamps_page_size(self, mock_get_audit_log: Any, test_client: TestClient) -> None:
        """Verify page_size is clamped to max 100."""
        mock_get_audit_log.return_value = {"entries": [], "total": 0, "page": 1, "page_size": 100}

        resp = test_client.get(
            "/api/admin/audit-log?page_size=500",
            headers=_admin_auth_headers(),
        )
        assert resp.status_code == 200
        call_kwargs = mock_get_audit_log.call_args
        page_size = call_kwargs.kwargs.get("page_size") or call_kwargs[1].get("page_size")
        assert page_size == 100


class TestAuditLogging:
    """Verify audit entries are recorded for all admin write actions."""

    @patch("api.routers.admin.record_audit_entry", new_callable=AsyncMock)
    def test_login_success_records_audit(self, mock_audit: AsyncMock, test_client: TestClient, mock_cur: AsyncMock) -> None:
        admin_row = _make_admin_row()
        mock_cur.fetchone = AsyncMock(return_value=admin_row)

        resp = test_client.post(
            "/api/admin/auth/login",
            json={"email": TEST_ADMIN_EMAIL, "password": "adminpassword123"},
        )
        assert resp.status_code == 200
        # Verify audit entry was recorded for successful login
        mock_audit.assert_called()
        # Find the success=True call (there may be multiple calls)
        calls = mock_audit.call_args_list
        success_call = [c for c in calls if c.kwargs.get("details", {}).get("success") is True]
        assert len(success_call) == 1
        assert success_call[0].kwargs["action"] == "admin.login"
        assert success_call[0].kwargs["target"] == TEST_ADMIN_EMAIL

    @patch("api.routers.admin.record_audit_entry", new_callable=AsyncMock)
    def test_login_failure_records_audit(self, mock_audit: AsyncMock, test_client: TestClient, mock_cur: AsyncMock) -> None:
        admin_row = _make_admin_row()
        mock_cur.fetchone = AsyncMock(return_value=admin_row)

        resp = test_client.post(
            "/api/admin/auth/login",
            json={"email": TEST_ADMIN_EMAIL, "password": "wrongpassword"},
        )
        assert resp.status_code == 401
        mock_audit.assert_called_once()
        assert mock_audit.call_args.kwargs["action"] == "admin.login"
        assert mock_audit.call_args.kwargs["details"]["success"] is False

    @patch("api.routers.admin.record_audit_entry", new_callable=AsyncMock)
    def test_login_non_admin_records_audit(self, mock_audit: AsyncMock, test_client: TestClient, mock_cur: AsyncMock) -> None:
        admin_row = _make_admin_row(is_admin=False)
        mock_cur.fetchone = AsyncMock(return_value=admin_row)

        resp = test_client.post(
            "/api/admin/auth/login",
            json={"email": TEST_ADMIN_EMAIL, "password": "adminpassword123"},
        )
        assert resp.status_code == 403
        mock_audit.assert_called_once()
        assert mock_audit.call_args.kwargs["action"] == "admin.login"
        assert mock_audit.call_args.kwargs["details"]["reason"] == "not_admin"

    @patch("api.routers.admin.record_audit_entry", new_callable=AsyncMock)
    def test_logout_records_audit(self, mock_audit: AsyncMock, test_client: TestClient) -> None:
        resp = test_client.post(
            "/api/admin/auth/logout",
            headers=_admin_auth_headers(),
        )
        assert resp.status_code == 200
        mock_audit.assert_called_once()
        assert mock_audit.call_args.kwargs["action"] == "admin.logout"
        assert mock_audit.call_args.kwargs["target"] == TEST_ADMIN_EMAIL

    @patch("api.routers.admin.httpx.AsyncClient")
    @patch("api.routers.admin.record_audit_entry", new_callable=AsyncMock)
    def test_extraction_trigger_records_audit(
        self, mock_audit: AsyncMock, mock_client_cls: Any, test_client: TestClient, mock_cur: AsyncMock
    ) -> None:
        extraction_id = str(uuid4())
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
        mock_audit.assert_called_once()
        assert mock_audit.call_args.kwargs["action"] == "extraction.trigger"
        assert mock_audit.call_args.kwargs["details"]["extraction_id"] == extraction_id

    @patch("api.routers.admin.httpx.AsyncClient")
    @patch("api.routers.admin.record_audit_entry", new_callable=AsyncMock)
    def test_dlq_purge_records_audit(self, mock_audit: AsyncMock, mock_client_cls: Any, test_client: TestClient) -> None:
        mock_response = AsyncMock()
        mock_response.status_code = 204
        mock_client_instance = AsyncMock()
        mock_client_instance.delete = AsyncMock(return_value=mock_response)
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client_instance

        resp = test_client.post(
            "/api/admin/dlq/purge/discogsography-discogs-graphinator-artists.dlq",
            headers=_admin_auth_headers(),
        )
        assert resp.status_code == 200
        mock_audit.assert_called_once()
        assert mock_audit.call_args.kwargs["action"] == "dlq.purge"
        assert mock_audit.call_args.kwargs["target"] == "discogsography-discogs-graphinator-artists.dlq"


class TestAdminAuthSecurity:
    """Security tests for admin authentication."""

    def test_forged_admin_jwt_rejected_by_db_verification(self, test_client: TestClient) -> None:
        """A token with type=admin is rejected when DB says user is not an admin."""
        import api.dependencies as deps

        # Create a mock pool that returns is_admin=False
        reject_pool = MagicMock()
        reject_cur = AsyncMock()
        reject_cur.fetchone = AsyncMock(return_value={"is_admin": False})
        reject_conn = AsyncMock()
        cur_ctx = AsyncMock()
        cur_ctx.__aenter__ = AsyncMock(return_value=reject_cur)
        cur_ctx.__aexit__ = AsyncMock(return_value=False)
        reject_conn.cursor = MagicMock(return_value=cur_ctx)
        conn_ctx = AsyncMock()
        conn_ctx.__aenter__ = AsyncMock(return_value=reject_conn)
        conn_ctx.__aexit__ = AsyncMock(return_value=False)
        reject_pool.connection = MagicMock(return_value=conn_ctx)

        original_pool = deps._pool
        deps._pool = reject_pool
        try:
            token = _make_admin_jwt()
            resp = test_client.get(
                "/api/admin/audit-log",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 403
        finally:
            deps._pool = original_pool
