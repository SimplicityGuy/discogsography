"""Tests for sync endpoints in the API service (api/routers/sync.py)."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
import pytest

from tests.api.conftest import TEST_JWT_SECRET, TEST_USER_EMAIL, TEST_USER_ID, make_test_jwt


class TestTriggerSyncEndpoint:
    """Tests for POST /api/sync."""

    def test_trigger_sync_no_auth(self, test_client: TestClient) -> None:
        response = test_client.post("/api/sync")
        assert response.status_code in (401, 403)

    def test_trigger_sync_invalid_token_401(self, test_client: TestClient) -> None:
        response = test_client.post("/api/sync", headers={"Authorization": "Bearer invalid.token.here"})
        assert response.status_code == 401

    def test_trigger_sync_creates_background_task(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
        auth_headers: dict[str, str],
    ) -> None:
        mock_cur.fetchone.return_value = {"id": "new-sync-id"}

        with patch("api.routers.sync.asyncio.create_task") as mock_task:
            mock_task.return_value = MagicMock(spec=asyncio.Task)
            mock_task.return_value.done.return_value = False
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
        import api.api as api_module

        mock_existing_task = MagicMock(spec=asyncio.Task)
        mock_existing_task.done.return_value = False
        api_module._running_syncs[TEST_USER_ID] = mock_existing_task
        mock_cur.fetchone.return_value = {"id": "existing-sync-id", "status": "running"}

        try:
            response = test_client.post("/api/sync", headers=auth_headers)
            assert response.status_code == 202
            data = response.json()
            assert data["status"] == "already_running"
        finally:
            api_module._running_syncs.pop(TEST_USER_ID, None)

    def test_trigger_sync_neo4j_not_ready_503(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        import api.routers.sync as sync_module

        original_neo4j = sync_module._neo4j
        sync_module._neo4j = None
        try:
            response = test_client.post("/api/sync", headers=auth_headers)
            assert response.status_code == 503
        finally:
            sync_module._neo4j = original_neo4j

    def test_trigger_sync_sync_record_creation_fails_500(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
        auth_headers: dict[str, str],
    ) -> None:
        mock_cur.fetchone.return_value = None
        response = test_client.post("/api/sync", headers=auth_headers)
        assert response.status_code == 500

    def test_trigger_sync_token_without_sub_returns_401(self, test_client: TestClient) -> None:
        import base64
        import hashlib
        import hmac
        import json

        def b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

        header = b64url(json.dumps({"alg": "HS256"}, separators=(",", ":")).encode())
        body = b64url(json.dumps({"email": "x@y.com", "exp": 9_999_999_999}, separators=(",", ":")).encode())
        signing_input = f"{header}.{body}".encode("ascii")
        sig = b64url(hmac.new(TEST_JWT_SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest())
        token = f"{header}.{body}.{sig}"
        response = test_client.post("/api/sync", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401


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
        import api.routers.sync as sync_module

        original_pool = sync_module._pool
        sync_module._pool = None
        try:
            response = test_client.get("/api/sync/status", headers=auth_headers)
            assert response.status_code == 503
        finally:
            sync_module._pool = original_pool

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
                "completed_at": None,
            },
        ]
        response = test_client.get("/api/sync/status", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["syncs"][0]["completed_at"] is None


class TestVerifyToken:
    """Tests for api.routers.sync._verify_token."""

    @pytest.mark.asyncio
    async def test_valid_token_returns_payload(self, test_client: TestClient) -> None:  # noqa: ARG002
        from api.routers.sync import _verify_token

        token = make_test_jwt()
        payload = await _verify_token(token)
        assert payload["sub"] == TEST_USER_ID
        assert payload["email"] == TEST_USER_EMAIL

    @pytest.mark.asyncio
    async def test_wrong_signature_raises(self, test_client: TestClient) -> None:  # noqa: ARG002
        from api.routers.sync import _verify_token

        bad_token = make_test_jwt(secret="wrong-secret")  # noqa: S106
        with pytest.raises(ValueError, match="signature"):
            await _verify_token(bad_token)

    @pytest.mark.asyncio
    async def test_expired_token_raises(self, test_client: TestClient) -> None:  # noqa: ARG002
        from api.routers.sync import _verify_token

        expired_token = make_test_jwt(exp=1)
        with pytest.raises(ValueError, match=r"[Ee]xpir"):
            await _verify_token(expired_token)

    @pytest.mark.asyncio
    async def test_malformed_token_raises(self, test_client: TestClient) -> None:  # noqa: ARG002
        from api.routers.sync import _verify_token

        with pytest.raises(ValueError, match="Invalid token"):
            await _verify_token("only.two.parts.extra")
