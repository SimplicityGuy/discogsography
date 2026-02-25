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
