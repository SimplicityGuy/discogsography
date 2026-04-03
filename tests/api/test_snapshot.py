"""Tests for snapshot endpoints in the API service (api/routers/snapshot.py)."""

import fakeredis
from fastapi.testclient import TestClient

from api.snapshot_store import SnapshotStore


class TestSaveSnapshot:
    """Tests for POST /api/snapshot."""

    def test_save_snapshot_success(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        body = {
            "nodes": [{"id": "1", "type": "artist"}, {"id": "2", "type": "genre"}],
            "center": {"id": "1", "type": "artist"},
        }
        response = test_client.post("/api/snapshot", json=body, headers=auth_headers)
        assert response.status_code == 201
        data = response.json()
        assert "token" in data
        assert "url" in data
        assert "expires_at" in data

    def test_save_snapshot_empty_nodes_422(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        body = {"nodes": [], "center": {"id": "1", "type": "artist"}}
        response = test_client.post("/api/snapshot", json=body, headers=auth_headers)
        assert response.status_code == 422

    def test_save_snapshot_too_many_nodes(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        import api.routers.snapshot as snap_module

        body = {
            "nodes": [{"id": str(i), "type": "artist"} for i in range(5)],
            "center": {"id": "0", "type": "artist"},
        }
        original_store = snap_module._snapshot_store
        import fakeredis.aioredis as aioredis_fake

        small_store = SnapshotStore(aioredis_fake.FakeRedis(), max_nodes=2)
        snap_module._snapshot_store = small_store
        try:
            response = test_client.post("/api/snapshot", json=body, headers=auth_headers)
        finally:
            snap_module._snapshot_store = original_store
        assert response.status_code == 422
        assert "Too many nodes" in response.json()["error"]

    def test_save_snapshot_missing_fields(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        response = test_client.post("/api/snapshot", json={"nodes": [{"id": "1", "type": "artist"}]}, headers=auth_headers)
        assert response.status_code == 422

    def test_save_snapshot_store_not_ready_returns_503(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        """snapshot.py:53 — 503 when _snapshot_store is None."""
        import api.routers.snapshot as snap_module

        original = snap_module._snapshot_store
        snap_module._snapshot_store = None
        try:
            body = {"nodes": [{"id": "1", "type": "artist"}], "center": {"id": "1", "type": "artist"}}
            response = test_client.post("/api/snapshot", json=body, headers=auth_headers)
            assert response.status_code == 503
            assert "error" in response.json()
        finally:
            snap_module._snapshot_store = original


class TestRestoreSnapshot:
    """Tests for GET /api/snapshot/{token}."""

    def test_restore_snapshot_success(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        # First save a snapshot
        body = {
            "nodes": [{"id": "1", "type": "artist"}],
            "center": {"id": "1", "type": "artist"},
        }
        save_response = test_client.post("/api/snapshot", json=body, headers=auth_headers)
        assert save_response.status_code == 201
        token = save_response.json()["token"]

        # Then restore it
        restore_response = test_client.get(f"/api/snapshot/{token}")
        assert restore_response.status_code == 200
        data = restore_response.json()
        assert "nodes" in data
        assert "center" in data
        assert "created_at" in data

    def test_restore_snapshot_not_found(self, test_client: TestClient) -> None:
        response = test_client.get("/api/snapshot/nonexistent-token")
        assert response.status_code == 404
        assert "error" in response.json()

    def test_restore_snapshot_store_not_ready_returns_503(self, test_client: TestClient) -> None:
        """snapshot.py:66 — 503 when _snapshot_store is None."""
        import api.routers.snapshot as snap_module

        original = snap_module._snapshot_store
        snap_module._snapshot_store = None
        try:
            response = test_client.get("/api/snapshot/some-token")
            assert response.status_code == 503
            assert "error" in response.json()
        finally:
            snap_module._snapshot_store = original

    def test_restore_snapshot_expired(self, test_client: TestClient, fake_redis_server: fakeredis.FakeServer) -> None:
        import secrets

        import api.routers.snapshot as snap_module

        token = secrets.token_urlsafe(16)

        # Delete the key (or never insert it) to simulate a missing/expired entry
        sync_redis = fakeredis.FakeRedis(server=fake_redis_server)
        key = f"{snap_module._snapshot_store._KEY_PREFIX}{token}"
        sync_redis.delete(key)

        response = test_client.get(f"/api/snapshot/{token}")
        assert response.status_code == 404


class TestSnapshotAuth:
    """Tests for _get_current_user in snapshot router."""

    def test_no_jwt_secret_returns_503(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        """snapshot.py:30 — 503 when _jwt_secret is None."""
        import api.routers.snapshot as snap_module

        original = snap_module._jwt_secret
        snap_module._jwt_secret = None
        try:
            body = {"nodes": [{"id": "1", "type": "artist"}], "center": {"id": "1", "type": "artist"}}
            response = test_client.post("/api/snapshot", json=body, headers=auth_headers)
            assert response.status_code == 503
        finally:
            snap_module._jwt_secret = original

    def test_invalid_token_returns_401(self, test_client: TestClient) -> None:
        """snapshot.py:33-34 — 401 on bad token."""
        body = {"nodes": [{"id": "1", "type": "artist"}], "center": {"id": "1", "type": "artist"}}
        response = test_client.post(
            "/api/snapshot",
            json=body,
            headers={"Authorization": "Bearer not.a.valid.jwt"},
        )
        assert response.status_code == 401

    def test_missing_sub_returns_401(self, test_client: TestClient) -> None:
        """snapshot.py:55-57 — 401 when token has no sub claim."""
        import base64
        import hashlib
        import hmac
        import json

        from tests.api.conftest import TEST_JWT_SECRET

        def b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

        header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
        body_payload = b64url(
            json.dumps(
                {"email": "test@example.com", "exp": 9_999_999_999},
                separators=(",", ":"),
            ).encode()
        )
        signing_input = f"{header}.{body_payload}".encode("ascii")
        sig = b64url(hmac.new(TEST_JWT_SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest())
        token = f"{header}.{body_payload}.{sig}"

        body = {"nodes": [{"id": "1", "type": "artist"}], "center": {"id": "1", "type": "artist"}}
        response = test_client.post(
            "/api/snapshot",
            json=body,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401
        assert "Invalid token" in response.json()["detail"]

    def test_revoked_jti_returns_401(self, test_client: TestClient) -> None:
        """snapshot.py:42-50 — 401 when jti is in the revocation blacklist."""
        import base64
        import hashlib
        import hmac
        import json
        from unittest.mock import AsyncMock

        from tests.api.conftest import TEST_JWT_SECRET, TEST_USER_EMAIL, TEST_USER_ID

        def b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

        jti_value = "snapshot-revoked-jti-456"
        header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
        body_payload = b64url(
            json.dumps(
                {"sub": TEST_USER_ID, "email": TEST_USER_EMAIL, "exp": 9_999_999_999, "jti": jti_value},
                separators=(",", ":"),
            ).encode()
        )
        signing_input = f"{header}.{body_payload}".encode("ascii")
        sig = b64url(hmac.new(TEST_JWT_SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest())
        token = f"{header}.{body_payload}.{sig}"

        import api.routers.snapshot as snap_module

        original_redis = snap_module._redis
        mock_redis = AsyncMock()

        async def fake_get(key: str) -> str | None:
            if key == f"revoked:jti:{jti_value}":
                return "1"
            return None

        mock_redis.get = AsyncMock(side_effect=fake_get)
        snap_module._redis = mock_redis
        try:
            body = {"nodes": [{"id": "1", "type": "artist"}], "center": {"id": "1", "type": "artist"}}
            response = test_client.post(
                "/api/snapshot",
                json=body,
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 401
            assert "revoked" in response.json()["detail"].lower()
        finally:
            snap_module._redis = original_redis


class TestSnapshotTokenChecks:
    """Tests for admin token rejection (lines 42-43) and password-changed revocation (lines 56-65)."""

    def test_admin_token_rejected(self, test_client: TestClient) -> None:
        """snapshot.py:42-43 — Admin tokens are rejected with 403."""
        import base64
        import hashlib
        import hmac
        import json

        from tests.api.conftest import TEST_JWT_SECRET

        def b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

        header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
        body_payload = b64url(
            json.dumps(
                {"sub": "admin-1", "email": "admin@test.com", "exp": 9_999_999_999, "type": "admin", "jti": "admin:snap-test"},
                separators=(",", ":"),
            ).encode()
        )
        signing_input = f"{header}.{body_payload}".encode("ascii")
        sig = b64url(hmac.new(TEST_JWT_SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest())
        admin_token = f"{header}.{body_payload}.{sig}"

        body = {"nodes": [{"id": "1", "type": "artist"}], "center": {"id": "1", "type": "artist"}}
        response = test_client.post(
            "/api/snapshot",
            json=body,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 403
        assert "admin" in response.json()["detail"].lower()

    def test_password_changed_revocation(self, test_client: TestClient) -> None:
        """snapshot.py:56-65 — Token issued before password change is rejected with 401."""
        import base64
        import hashlib
        import hmac
        import json
        from unittest.mock import AsyncMock

        from tests.api.conftest import TEST_JWT_SECRET, TEST_USER_EMAIL, TEST_USER_ID

        def b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

        # Token with iat=1000 (old)
        header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
        body_payload = b64url(
            json.dumps(
                {"sub": TEST_USER_ID, "email": TEST_USER_EMAIL, "exp": 9_999_999_999, "iat": 1000, "jti": "pw-change-test"},
                separators=(",", ":"),
            ).encode()
        )
        signing_input = f"{header}.{body_payload}".encode("ascii")
        sig = b64url(hmac.new(TEST_JWT_SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest())
        token = f"{header}.{body_payload}.{sig}"

        import api.routers.snapshot as snap_module

        original_redis = snap_module._redis
        mock_redis = AsyncMock()

        async def fake_get(key: str) -> str | None:
            if key == f"password_changed:{TEST_USER_ID}":
                return "2000"  # password changed at timestamp 2000, after iat=1000
            return None

        mock_redis.get = AsyncMock(side_effect=fake_get)
        snap_module._redis = mock_redis
        try:
            body = {"nodes": [{"id": "1", "type": "artist"}], "center": {"id": "1", "type": "artist"}}
            response = test_client.post(
                "/api/snapshot",
                json=body,
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 401
            assert "password" in response.json()["detail"].lower()
        finally:
            snap_module._redis = original_redis
