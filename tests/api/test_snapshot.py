"""Tests for snapshot endpoints in the API service (api/routers/snapshot.py)."""

from fastapi.testclient import TestClient


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
        from unittest.mock import PropertyMock, patch

        body = {
            "nodes": [{"id": str(i), "type": "artist"} for i in range(5)],
            "center": {"id": "0", "type": "artist"},
        }
        with patch.object(
            type(__import__("api.routers.snapshot", fromlist=["_snapshot_store"])._snapshot_store),
            "max_nodes",
            new_callable=PropertyMock,
            return_value=2,
        ):
            response = test_client.post("/api/snapshot", json=body, headers=auth_headers)
        assert response.status_code == 422
        assert "Too many nodes" in response.json()["error"]

    def test_save_snapshot_missing_fields(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        response = test_client.post("/api/snapshot", json={"nodes": [{"id": "1", "type": "artist"}]}, headers=auth_headers)
        assert response.status_code == 422


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

    def test_restore_snapshot_expired(self, test_client: TestClient) -> None:
        import api.routers.snapshot as snap_module

        store = snap_module._snapshot_store
        # Manually insert an expired entry
        import secrets

        token = secrets.token_urlsafe(16)
        from datetime import UTC, datetime, timedelta

        store._store[token] = {
            "nodes": [{"id": "1", "type": "artist"}],
            "center": {"id": "1", "type": "artist"},
            "created_at": datetime.now(UTC).isoformat(),
            "expires_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        }
        try:
            response = test_client.get(f"/api/snapshot/{token}")
            assert response.status_code == 404
        finally:
            store._store.pop(token, None)


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
