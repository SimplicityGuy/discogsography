"""Tests for snapshot save/restore endpoints and SnapshotStore."""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from explore.snapshot_store import SnapshotStore


# ---------------------------------------------------------------------------
# SnapshotStore unit tests
# ---------------------------------------------------------------------------


class TestSnapshotStore:
    """Tests for SnapshotStore."""

    def test_save_returns_token_and_expiry(self) -> None:
        store = SnapshotStore()
        nodes = [{"id": "1", "type": "artist"}]
        center = {"id": "1", "type": "artist"}
        token, expires_at = store.save(nodes, center)
        assert isinstance(token, str)
        assert len(token) > 0
        assert isinstance(expires_at, datetime)
        assert expires_at > datetime.now(UTC)

    def test_save_and_load_round_trip(self) -> None:
        store = SnapshotStore()
        nodes = [{"id": "1", "type": "artist"}, {"id": "2", "type": "release"}]
        center = {"id": "1", "type": "artist"}
        token, _ = store.save(nodes, center)
        result = store.load(token)
        assert result is not None
        assert result["nodes"] == nodes
        assert result["center"] == center
        assert "created_at" in result

    def test_load_unknown_token_returns_none(self) -> None:
        store = SnapshotStore()
        result = store.load("nonexistent_token")
        assert result is None

    def test_load_expired_token_returns_none(self) -> None:
        store = SnapshotStore()
        nodes = [{"id": "1", "type": "artist"}]
        center = {"id": "1", "type": "artist"}
        token, _ = store.save(nodes, center)

        # Manually expire the entry
        past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        store._store[token]["expires_at"] = past

        result = store.load(token)
        assert result is None
        # Expired entry should be removed
        assert token not in store._store

    def test_ttl_days_from_env(self) -> None:
        with patch.dict("os.environ", {"SNAPSHOT_TTL_DAYS": "7"}):
            store = SnapshotStore()
            assert store.ttl_days == 7

    def test_max_nodes_from_env(self) -> None:
        with patch.dict("os.environ", {"SNAPSHOT_MAX_NODES": "50"}):
            store = SnapshotStore()
            assert store.max_nodes == 50

    def test_evict_expired_on_save(self) -> None:
        store = SnapshotStore()
        nodes = [{"id": "1", "type": "artist"}]
        center = {"id": "1", "type": "artist"}

        token1, _ = store.save(nodes, center)

        # Manually expire the first entry
        past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        store._store[token1]["expires_at"] = past

        # Save a second entry — should trigger eviction of the first
        store.save(nodes, center)
        assert token1 not in store._store

    def test_tokens_are_unique(self) -> None:
        store = SnapshotStore()
        nodes = [{"id": "1", "type": "artist"}]
        center = {"id": "1", "type": "artist"}
        tokens = {store.save(nodes, center)[0] for _ in range(20)}
        assert len(tokens) == 20


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


class TestSaveSnapshotEndpoint:
    """Tests for POST /api/snapshot."""

    def test_save_snapshot_success(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        payload = {
            "nodes": [
                {"id": "1", "type": "artist"},
                {"id": "94", "type": "release"},
            ],
            "center": {"id": "1", "type": "artist"},
        }
        response = test_client.post("/api/snapshot", json=payload, headers=auth_headers)
        assert response.status_code == 201
        data = response.json()
        assert "token" in data
        assert "url" in data
        assert "expires_at" in data
        assert data["url"] == f"/snapshot/{data['token']}"

    def test_save_snapshot_exceeds_max_nodes(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        import api.routers.snapshot as snapshot_module

        original_store = snapshot_module._snapshot_store
        small_store = SnapshotStore()
        small_store._max_nodes = 2
        snapshot_module._snapshot_store = small_store

        payload = {
            "nodes": [
                {"id": "1", "type": "artist"},
                {"id": "2", "type": "release"},
                {"id": "3", "type": "label"},
            ],
            "center": {"id": "1", "type": "artist"},
        }
        response = test_client.post("/api/snapshot", json=payload, headers=auth_headers)
        assert response.status_code == 422
        data = response.json()
        assert "error" in data

        snapshot_module._snapshot_store = original_store

    def test_save_snapshot_empty_nodes_rejected(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        payload = {
            "nodes": [],
            "center": {"id": "1", "type": "artist"},
        }
        response = test_client.post("/api/snapshot", json=payload, headers=auth_headers)
        assert response.status_code == 422

    def test_save_snapshot_missing_center(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        payload = {
            "nodes": [{"id": "1", "type": "artist"}],
        }
        response = test_client.post("/api/snapshot", json=payload, headers=auth_headers)
        assert response.status_code == 422

    def test_save_snapshot_returns_valid_expiry(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        payload = {
            "nodes": [{"id": "1", "type": "artist"}],
            "center": {"id": "1", "type": "artist"},
        }
        before = datetime.now(UTC)
        response = test_client.post("/api/snapshot", json=payload, headers=auth_headers)
        assert response.status_code == 201
        data = response.json()
        expires_at = datetime.fromisoformat(data["expires_at"])
        # Should expire in the future (at least 27 days from now, allowing clock skew)
        assert expires_at > before + timedelta(days=27)


class TestRestoreSnapshotEndpoint:
    """Tests for GET /api/snapshot/{token}."""

    def test_restore_valid_snapshot(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        # First save a snapshot
        payload: dict[str, Any] = {
            "nodes": [
                {"id": "1", "type": "artist"},
                {"id": "94", "type": "release"},
                {"id": "201", "type": "label"},
            ],
            "center": {"id": "1", "type": "artist"},
        }
        save_response = test_client.post("/api/snapshot", json=payload, headers=auth_headers)
        assert save_response.status_code == 201
        token = save_response.json()["token"]

        # Now restore it
        restore_response = test_client.get(f"/api/snapshot/{token}")
        assert restore_response.status_code == 200
        data = restore_response.json()
        assert "nodes" in data
        assert "center" in data
        assert "created_at" in data
        assert len(data["nodes"]) == 3
        assert data["center"]["id"] == "1"
        assert data["center"]["type"] == "artist"

    def test_restore_unknown_token_returns_404(self, test_client: TestClient) -> None:
        response = test_client.get("/api/snapshot/unknowntoken123")
        assert response.status_code == 404
        data = response.json()
        assert "error" in data

    def test_restore_expired_token_returns_404(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        import api.routers.snapshot as snapshot_module

        # Save a snapshot
        payload: dict[str, Any] = {
            "nodes": [{"id": "1", "type": "artist"}],
            "center": {"id": "1", "type": "artist"},
        }
        save_response = test_client.post("/api/snapshot", json=payload, headers=auth_headers)
        assert save_response.status_code == 201
        token = save_response.json()["token"]

        # Manually expire it
        past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        snapshot_module._snapshot_store._store[token]["expires_at"] = past

        # Restore should return 404
        restore_response = test_client.get(f"/api/snapshot/{token}")
        assert restore_response.status_code == 404
