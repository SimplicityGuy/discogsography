"""Tests for the curator service (curator/curator.py)."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
import pytest

from tests.curator.conftest import (
    TEST_JWT_SECRET,
    TEST_USER_EMAIL,
    TEST_USER_ID,
    make_curator_jwt,
)


class TestGetHealthData:
    """Tests for curator.get_health_data."""

    def test_healthy_when_pool_and_neo4j_set(self, test_client: TestClient) -> None:  # noqa: ARG002
        from curator.curator import get_health_data

        data = get_health_data()
        assert data["status"] == "healthy"
        assert data["service"] == "curator"
        assert "active_syncs" in data
        assert "timestamp" in data

    def test_starting_when_no_pool(self) -> None:
        import curator.curator as curator_module
        from curator.curator import get_health_data

        original_pool = curator_module._pool
        curator_module._pool = None
        try:
            data = get_health_data()
            assert data["status"] == "starting"
        finally:
            curator_module._pool = original_pool

    def test_active_syncs_count(self, test_client: TestClient) -> None:  # noqa: ARG002
        from curator.curator import _running_syncs, get_health_data

        _running_syncs.clear()
        data = get_health_data()
        assert data["active_syncs"] == 0


class TestVerifyToken:
    """Tests for curator._verify_token."""

    @pytest.mark.asyncio
    async def test_valid_token_returns_payload(self, test_client: TestClient) -> None:  # noqa: ARG002
        from curator.curator import _verify_token

        token = make_curator_jwt()
        payload = await _verify_token(token)
        assert payload["sub"] == TEST_USER_ID
        assert payload["email"] == TEST_USER_EMAIL

    @pytest.mark.asyncio
    async def test_wrong_signature_raises(self, test_client: TestClient) -> None:  # noqa: ARG002
        from curator.curator import _verify_token

        bad_token = make_curator_jwt(secret="wrong-secret")  # noqa: S106
        with pytest.raises(ValueError, match="signature"):
            await _verify_token(bad_token)

    @pytest.mark.asyncio
    async def test_expired_token_raises(self, test_client: TestClient) -> None:  # noqa: ARG002
        from curator.curator import _verify_token

        expired_token = make_curator_jwt(exp=1)
        with pytest.raises(ValueError, match=r"[Ee]xpir"):
            await _verify_token(expired_token)

    @pytest.mark.asyncio
    async def test_malformed_token_raises(self, test_client: TestClient) -> None:  # noqa: ARG002
        from curator.curator import _verify_token

        with pytest.raises(ValueError, match="Invalid token"):
            await _verify_token("only.two.parts.extra")

    @pytest.mark.asyncio
    async def test_token_without_sub_raises_via_endpoint(self, test_client: TestClient) -> None:
        import base64
        import hashlib
        import hmac
        import json

        # Create a valid JWT with no "sub" field
        def b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

        header = b64url(json.dumps({"alg": "HS256"}, separators=(",", ":")).encode())
        body = b64url(json.dumps({"email": "x@y.com", "exp": 9_999_999_999}, separators=(",", ":")).encode())
        signing_input = f"{header}.{body}".encode("ascii")
        sig = b64url(hmac.new(TEST_JWT_SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest())
        token = f"{header}.{body}.{sig}"

        response = test_client.post("/api/sync", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_no_config_raises(self) -> None:
        import curator.curator as curator_module
        from curator.curator import _verify_token

        original = curator_module._config
        curator_module._config = None
        try:
            with pytest.raises(ValueError, match="not initialized"):
                await _verify_token("a.b.c")
        finally:
            curator_module._config = original


class TestHealthEndpoint:
    """Tests for GET /health."""

    def test_health_returns_200(self, test_client: TestClient) -> None:
        response = test_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "curator"


class TestTriggerSyncEndpoint:
    """Tests for POST /api/sync."""

    def test_trigger_sync_no_auth(self, test_client: TestClient) -> None:
        response = test_client.post("/api/sync")
        assert response.status_code in (401, 403)

    def test_trigger_sync_invalid_token_401(self, test_client: TestClient) -> None:
        response = test_client.post(
            "/api/sync",
            headers={"Authorization": "Bearer invalid.token.here"},
        )
        assert response.status_code == 401

    def test_trigger_sync_creates_background_task(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
        auth_headers: dict[str, str],
    ) -> None:

        # _running_syncs is empty, so only the INSERT RETURNING fetchone is called
        mock_cur.fetchone.return_value = {"id": "sync-uuid-1234"}

        with patch("curator.curator.asyncio.create_task") as mock_create_task:
            mock_task = MagicMock(spec=asyncio.Task)
            mock_create_task.return_value = mock_task

            response = test_client.post("/api/sync", headers=auth_headers)

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "started"
        assert "sync_id" in data

    def test_trigger_sync_already_running(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
        auth_headers: dict[str, str],
    ) -> None:
        import curator.curator as curator_module

        # Set up an already-running task for this user
        mock_existing_task = MagicMock(spec=asyncio.Task)
        mock_existing_task.done.return_value = False  # still running
        curator_module._running_syncs[TEST_USER_ID] = mock_existing_task

        # Return existing sync record
        mock_cur.fetchone.return_value = {"id": "existing-sync-id", "status": "running"}

        try:
            response = test_client.post("/api/sync", headers=auth_headers)
            assert response.status_code == 202
            data = response.json()
            assert data["status"] == "already_running"
        finally:
            curator_module._running_syncs.pop(TEST_USER_ID, None)

    def test_trigger_sync_neo4j_not_ready_503(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        import curator.curator as curator_module

        original_neo4j = curator_module._neo4j
        curator_module._neo4j = None
        try:
            response = test_client.post("/api/sync", headers=auth_headers)
            assert response.status_code == 503
        finally:
            curator_module._neo4j = original_neo4j

    def test_trigger_sync_sync_record_creation_fails_500(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
        auth_headers: dict[str, str],
    ) -> None:
        # When INSERT RETURNING returns None, the route returns 500
        mock_cur.fetchone.return_value = None

        response = test_client.post("/api/sync", headers=auth_headers)
        assert response.status_code == 500

    def test_trigger_sync_service_not_ready_503(self) -> None:
        from collections.abc import AsyncGenerator
        from contextlib import asynccontextmanager

        from fastapi import FastAPI

        import curator.curator as curator_module
        from curator.curator import app

        @asynccontextmanager
        async def mock_lifespan(_app: FastAPI) -> AsyncGenerator[None]:
            yield

        original_lifespan = app.router.lifespan_context
        original_pool = curator_module._pool
        app.router.lifespan_context = mock_lifespan
        curator_module._pool = None

        token = make_curator_jwt()
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post(
                    "/api/sync",
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert response.status_code == 503
        finally:
            curator_module._pool = original_pool
            app.router.lifespan_context = original_lifespan


class TestSyncStatusEndpoint:
    """Tests for GET /api/sync/status."""

    def test_sync_status_no_auth(self, test_client: TestClient) -> None:
        response = test_client.get("/api/sync/status")
        assert response.status_code in (401, 403)

    def test_sync_status_returns_history(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
        auth_headers: dict[str, str],
    ) -> None:
        now = datetime.now(UTC)
        mock_cur.fetchall.return_value = [
            {
                "id": "sync-id-1",
                "sync_type": "full",
                "status": "completed",
                "items_synced": 42,
                "error_message": None,
                "started_at": now,
                "completed_at": now,
            },
        ]

        response = test_client.get("/api/sync/status", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data["syncs"]) == 1
        assert data["syncs"][0]["status"] == "completed"
        assert data["syncs"][0]["items_synced"] == 42

    def test_sync_status_empty_history(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
        auth_headers: dict[str, str],
    ) -> None:
        mock_cur.fetchall.return_value = []

        response = test_client.get("/api/sync/status", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["syncs"] == []

    def test_sync_status_pool_not_ready_503(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        import curator.curator as curator_module

        original_pool = curator_module._pool
        curator_module._pool = None
        try:
            response = test_client.get("/api/sync/status", headers=auth_headers)
            assert response.status_code == 503
        finally:
            curator_module._pool = original_pool

    def test_sync_status_service_not_ready_503(self) -> None:
        from collections.abc import AsyncGenerator
        from contextlib import asynccontextmanager

        from fastapi import FastAPI

        import curator.curator as curator_module
        from curator.curator import app

        @asynccontextmanager
        async def mock_lifespan(_app: FastAPI) -> AsyncGenerator[None]:
            yield

        original_lifespan = app.router.lifespan_context
        original_pool = curator_module._pool
        app.router.lifespan_context = mock_lifespan
        curator_module._pool = None

        token = make_curator_jwt()
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get(
                    "/api/sync/status",
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert response.status_code == 503
        finally:
            curator_module._pool = original_pool
            app.router.lifespan_context = original_lifespan

    def test_sync_status_with_null_completed_at(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
        auth_headers: dict[str, str],
    ) -> None:
        now = datetime.now(UTC)
        mock_cur.fetchall.return_value = [
            {
                "id": "sync-id-2",
                "sync_type": "full",
                "status": "running",
                "items_synced": 0,
                "error_message": None,
                "started_at": now,
                "completed_at": None,  # still running
            },
        ]

        response = test_client.get("/api/sync/status", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["syncs"][0]["completed_at"] is None
