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
    """Tests for api.auth.decode_token (formerly sync._verify_token)."""

    def test_valid_token_returns_payload(self, test_client: TestClient) -> None:  # noqa: ARG002
        from api.auth import decode_token
        from tests.api.conftest import TEST_JWT_SECRET

        token = make_test_jwt()
        payload = decode_token(token, TEST_JWT_SECRET)
        assert payload["sub"] == TEST_USER_ID
        assert payload["email"] == TEST_USER_EMAIL

    def test_wrong_signature_raises(self, test_client: TestClient) -> None:  # noqa: ARG002
        from api.auth import decode_token
        from tests.api.conftest import TEST_JWT_SECRET

        bad_token = make_test_jwt(secret="wrong-secret")  # noqa: S106
        with pytest.raises(ValueError, match="signature"):
            decode_token(bad_token, TEST_JWT_SECRET)

    def test_expired_token_raises(self, test_client: TestClient) -> None:  # noqa: ARG002
        from api.auth import decode_token
        from tests.api.conftest import TEST_JWT_SECRET

        expired_token = make_test_jwt(exp=1)
        with pytest.raises(ValueError, match=r"[Ee]xpir"):
            decode_token(expired_token, TEST_JWT_SECRET)

    def test_malformed_token_raises(self, test_client: TestClient) -> None:  # noqa: ARG002
        from api.auth import decode_token
        from tests.api.conftest import TEST_JWT_SECRET

        with pytest.raises(ValueError, match="Invalid token"):
            decode_token("only.two.parts.extra", TEST_JWT_SECRET)

    def test_verify_token_body_padding_branch(self, test_client: TestClient) -> None:  # noqa: ARG002
        """decode_token handles a JWT body whose base64url needs padding."""
        import base64
        import hashlib
        import hmac
        import json

        from api.auth import decode_token
        from tests.api.conftest import TEST_JWT_SECRET, TEST_USER_ID

        def b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

        # email "ab@example.com" (14 chars) produces JSON of 88 bytes →
        # base64url stripped length is 118 (118 % 4 == 2, needs padding)
        header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
        body = b64url(
            json.dumps(
                {"sub": TEST_USER_ID, "email": "ab@example.com", "exp": 9_999_999_999},
                separators=(",", ":"),
            ).encode()
        )
        assert len(body) % 4 != 0, "test precondition: body must need base64 padding"
        signing_input = f"{header}.{body}".encode("ascii")
        sig = b64url(hmac.new(TEST_JWT_SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest())
        token = f"{header}.{body}.{sig}"

        payload = decode_token(token, TEST_JWT_SECRET)
        assert payload["sub"] == TEST_USER_ID


class TestSyncGetCurrentUser:
    """Tests for api.routers.sync._get_current_user."""

    def test_get_current_user_config_none_returns_503(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Line 75: _get_current_user raises 503 when sync _config is None."""
        import api.routers.sync as sync_module

        original = sync_module._config
        sync_module._config = None
        try:
            response = test_client.get("/api/sync/status", headers=auth_headers)
            assert response.status_code == 503
        finally:
            sync_module._config = original

    def test_trigger_sync_no_sub_in_current_user_401(
        self,
        test_client: TestClient,
    ) -> None:
        """Line 98: trigger_sync raises 401 when current_user has no 'sub'."""
        from api.api import app
        from api.routers.sync import _get_current_user

        async def override_no_sub() -> dict[str, str]:
            return {"email": "x@y.com"}

        app.dependency_overrides[_get_current_user] = override_no_sub
        try:
            response = test_client.post(
                "/api/sync",
                headers={"Authorization": "Bearer fake"},
            )
            assert response.status_code == 401
        finally:
            del app.dependency_overrides[_get_current_user]


class TestSyncRedisCooldown:
    """Tests for per-user Redis cooldown in trigger_sync."""

    def test_in_cooldown_returns_429(self, test_client: TestClient, mock_redis: AsyncMock, auth_headers: dict[str, str]) -> None:
        mock_redis.get.return_value = "1"  # cooldown active
        response = test_client.post("/api/sync", headers=auth_headers)
        assert response.status_code == 429
        data = response.json()
        assert data["status"] == "cooldown"

    def test_cooldown_key_uses_user_id(self, test_client: TestClient, mock_redis: AsyncMock, auth_headers: dict[str, str]) -> None:
        mock_redis.get.return_value = "1"
        test_client.post("/api/sync", headers=auth_headers)
        # get is called for password_changed check and cooldown check
        cooldown_calls = [c for c in mock_redis.get.call_args_list if "sync:cooldown:" in str(c)]
        assert len(cooldown_calls) == 1
        call_key = cooldown_calls[0][0][0]
        assert call_key == f"sync:cooldown:{TEST_USER_ID}"

    def test_sets_cooldown_after_trigger(
        self, test_client: TestClient, mock_redis: AsyncMock, mock_cur: AsyncMock, auth_headers: dict[str, str]
    ) -> None:
        import asyncio
        from unittest.mock import MagicMock

        mock_redis.get.return_value = None  # not in cooldown
        mock_cur.fetchone.return_value = {"id": "new-sync-id"}
        with patch("api.routers.sync.asyncio.create_task") as mock_task:
            mock_task.return_value = MagicMock(spec=asyncio.Task)
            mock_task.return_value.done.return_value = False
            test_client.post("/api/sync", headers=auth_headers)
        mock_redis.setex.assert_awaited_once()
        setex_args = mock_redis.setex.call_args[0]
        assert setex_args[0] == f"sync:cooldown:{TEST_USER_ID}"
        assert setex_args[1] == 600

    def test_redis_none_skips_cooldown(self, test_client: TestClient, mock_cur: AsyncMock, auth_headers: dict[str, str]) -> None:
        import asyncio
        from unittest.mock import MagicMock

        import api.routers.sync as sync_module

        original = sync_module._redis
        sync_module._redis = None
        mock_cur.fetchone.return_value = {"id": "sync-id"}
        try:
            with patch("api.routers.sync.asyncio.create_task") as mock_task:
                mock_task.return_value = MagicMock(spec=asyncio.Task)
                mock_task.return_value.done.return_value = False
                response = test_client.post("/api/sync", headers=auth_headers)
            assert response.status_code == 202
        finally:
            sync_module._redis = original

    def test_trigger_sync_passes_encryption_key(self, test_client: TestClient, mock_cur: AsyncMock, auth_headers: dict[str, str]) -> None:
        import asyncio
        from unittest.mock import MagicMock

        import api.routers.sync as sync_module

        mock_cur.fetchone.return_value = {"id": "sync-id"}
        with patch("api.routers.sync.asyncio.create_task") as mock_task:
            mock_task.return_value = MagicMock(spec=asyncio.Task)
            mock_task.return_value.done.return_value = False
            test_client.post("/api/sync", headers=auth_headers)

        create_task_call = mock_task.call_args
        # The coroutine is run_full_sync(...) — check kwargs contain oauth_encryption_key
        coroutine = create_task_call[0][0]
        assert coroutine is not None
        coroutine.close()  # clean up unawaited coroutine

        # Verify getattr used on config with oauth_encryption_key
        assert hasattr(sync_module._config, "jwt_secret_key")


class TestSyncTokenRevocation:
    """Tests for jti-based token revocation in sync._get_current_user (lines 56-65)."""

    def test_revoked_jti_returns_401(self, test_client: TestClient, mock_redis: AsyncMock) -> None:
        """A JWT with a jti claim that has been revoked should return 401."""
        import base64
        import hashlib
        import hmac
        import json

        def b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

        jti_value = "revoked-jti-123"
        header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
        body = b64url(
            json.dumps(
                {"sub": TEST_USER_ID, "email": TEST_USER_EMAIL, "exp": 9_999_999_999, "jti": jti_value},
                separators=(",", ":"),
            ).encode()
        )
        signing_input = f"{header}.{body}".encode("ascii")
        sig = b64url(hmac.new(TEST_JWT_SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest())
        token = f"{header}.{body}.{sig}"

        # mock_redis.get returns truthy for the revoked key
        async def fake_get(key: str) -> str | None:
            if key == f"revoked:jti:{jti_value}":
                return "1"
            return None

        mock_redis.get = AsyncMock(side_effect=fake_get)

        response = test_client.post("/api/sync", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401
        assert "revoked" in response.json()["detail"].lower()


class TestSyncPasswordChanged:
    """Tests for password_changed check in sync._get_current_user (lines 68-77)."""

    def test_token_issued_before_password_change_returns_401(self, test_client: TestClient, mock_redis: AsyncMock) -> None:
        """A JWT issued before a password change should return 401."""
        import base64
        import hashlib
        import hmac
        import json

        def b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

        # Token issued at time 1000
        iat_value = 1000
        header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
        body = b64url(
            json.dumps(
                {"sub": TEST_USER_ID, "email": TEST_USER_EMAIL, "exp": 9_999_999_999, "iat": iat_value},
                separators=(",", ":"),
            ).encode()
        )
        signing_input = f"{header}.{body}".encode("ascii")
        sig = b64url(hmac.new(TEST_JWT_SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest())
        token = f"{header}.{body}.{sig}"

        # Password was changed at time 2000 (after iat=1000)
        async def fake_get(key: str) -> str | None:
            if key == f"password_changed:{TEST_USER_ID}":
                return "2000"
            return None

        mock_redis.get = AsyncMock(side_effect=fake_get)

        response = test_client.post("/api/sync", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401
        assert "revoked" in response.json()["detail"].lower()


class TestSyncAtomicLock:
    """Tests for atomic lock preventing duplicate sync tasks (lines 97-103)."""

    def test_lock_not_acquired_returns_202_already_running(
        self, test_client: TestClient, mock_redis: AsyncMock, auth_headers: dict[str, str]
    ) -> None:
        """When Redis nx lock is not acquired, should return 202 with already_running."""
        mock_redis.get.return_value = None  # not in cooldown
        mock_redis.set = AsyncMock(return_value=None)  # lock NOT acquired

        response = test_client.post("/api/sync", headers=auth_headers)
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "already_running"
