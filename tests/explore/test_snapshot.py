"""Tests for snapshot save/restore endpoints and SnapshotStore."""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import fakeredis
import fakeredis.aioredis as aioredis_fake
from fastapi.testclient import TestClient
import pytest

from api.snapshot_store import SnapshotStore


# ---------------------------------------------------------------------------
# SnapshotStore unit tests
# ---------------------------------------------------------------------------


class TestSnapshotStore:
    """Tests for SnapshotStore."""

    @pytest.mark.asyncio
    async def test_save_returns_token_and_expiry(self) -> None:
        store = SnapshotStore(aioredis_fake.FakeRedis())
        nodes = [{"id": "1", "type": "artist"}]
        center = {"id": "1", "type": "artist"}
        token, expires_at = await store.save(nodes, center)
        assert isinstance(token, str)
        assert len(token) > 0
        assert isinstance(expires_at, datetime)
        assert expires_at > datetime.now(UTC)

    @pytest.mark.asyncio
    async def test_save_and_load_round_trip(self) -> None:
        store = SnapshotStore(aioredis_fake.FakeRedis())
        nodes = [{"id": "1", "type": "artist"}, {"id": "2", "type": "release"}]
        center = {"id": "1", "type": "artist"}
        token, _ = await store.save(nodes, center)
        result = await store.load(token)
        assert result is not None
        assert result["nodes"] == nodes
        assert result["center"] == center
        assert "created_at" in result

    @pytest.mark.asyncio
    async def test_load_unknown_token_returns_none(self) -> None:
        store = SnapshotStore(aioredis_fake.FakeRedis())
        result = await store.load("nonexistent_token")
        assert result is None

    @pytest.mark.asyncio
    async def test_load_expired_token_returns_none(self) -> None:
        redis = aioredis_fake.FakeRedis()
        store = SnapshotStore(redis)
        nodes = [{"id": "1", "type": "artist"}]
        center = {"id": "1", "type": "artist"}
        token, _ = await store.save(nodes, center)

        # Delete the key to simulate Redis TTL expiration
        await redis.delete(f"snapshot:{token}")

        result = await store.load(token)
        assert result is None

    @pytest.mark.asyncio
    async def test_ttl_days_from_env(self) -> None:
        with patch.dict("os.environ", {"SNAPSHOT_TTL_DAYS": "7"}):
            store = SnapshotStore(aioredis_fake.FakeRedis())
            assert store.ttl_days == 7

    @pytest.mark.asyncio
    async def test_max_nodes_from_env(self) -> None:
        with patch.dict("os.environ", {"SNAPSHOT_MAX_NODES": "50"}):
            store = SnapshotStore(aioredis_fake.FakeRedis())
            assert store.max_nodes == 50

    @pytest.mark.asyncio
    async def test_tokens_are_unique(self) -> None:
        store = SnapshotStore(aioredis_fake.FakeRedis())
        nodes = [{"id": "1", "type": "artist"}]
        center = {"id": "1", "type": "artist"}
        tokens = set()
        for _ in range(20):
            token, _ = await store.save(nodes, center)
            tokens.add(token)
        assert len(tokens) == 20

    @pytest.mark.asyncio
    async def test_ttl_is_set_on_key(self) -> None:
        redis = aioredis_fake.FakeRedis()
        store = SnapshotStore(redis, ttl_days=7)
        nodes = [{"id": "1", "type": "artist"}]
        center = {"id": "1", "type": "artist"}
        token, _ = await store.save(nodes, center)
        ttl = await redis.ttl(f"snapshot:{token}")
        # TTL should be within a few seconds of 7 * 86400
        expected = 7 * 86400
        assert expected - 5 <= ttl <= expected


class TestSnapshotStoreLimits:
    """Regression for discogsography-cu2.110: SnapshotStore had no cap on the
    serialized payload size and no per-user quota, so a looping authenticated
    user could mint unbounded 28-day-TTL Redis keys — even with small, valid
    payloads under the node-count cap (`max_nodes` only bounds node count, not
    per-node string size or the number of distinct snapshots per user)."""

    @pytest.mark.asyncio
    async def test_save_rejects_oversized_payload(self) -> None:
        from api.snapshot_store import SnapshotTooLargeError

        store = SnapshotStore(aioredis_fake.FakeRedis(), max_payload_bytes=100)
        nodes = [{"id": "1", "type": "artist", "extra": "x" * 200}]
        center = {"id": "1", "type": "artist"}
        with pytest.raises(SnapshotTooLargeError):
            await store.save(nodes, center)

    @pytest.mark.asyncio
    async def test_save_under_payload_cap_succeeds(self) -> None:
        store = SnapshotStore(aioredis_fake.FakeRedis(), max_payload_bytes=64 * 1024)
        nodes = [{"id": "1", "type": "artist"}]
        center = {"id": "1", "type": "artist"}
        token, _ = await store.save(nodes, center)
        assert token

    @pytest.mark.asyncio
    async def test_max_payload_bytes_from_env(self) -> None:
        with patch.dict("os.environ", {"SNAPSHOT_MAX_PAYLOAD_BYTES": "12345"}):
            store = SnapshotStore(aioredis_fake.FakeRedis())
            assert store.max_payload_bytes == 12345

    @pytest.mark.asyncio
    async def test_save_enforces_per_user_quota(self) -> None:
        from api.snapshot_store import SnapshotQuotaExceededError

        store = SnapshotStore(aioredis_fake.FakeRedis(), max_per_user=2)
        nodes = [{"id": "1", "type": "artist"}]
        center = {"id": "1", "type": "artist"}

        await store.save(nodes, center, user_id="user-1")
        await store.save(nodes, center, user_id="user-1")
        with pytest.raises(SnapshotQuotaExceededError):
            await store.save(nodes, center, user_id="user-1")

    @pytest.mark.asyncio
    async def test_per_user_quota_is_scoped_per_user(self) -> None:
        """Hitting one user's quota must not affect a different user's ability to save."""
        store = SnapshotStore(aioredis_fake.FakeRedis(), max_per_user=1)
        nodes = [{"id": "1", "type": "artist"}]
        center = {"id": "1", "type": "artist"}

        await store.save(nodes, center, user_id="user-1")
        # user-1 is now at quota; user-2 must still be able to save.
        token, _ = await store.save(nodes, center, user_id="user-2")
        assert token

    @pytest.mark.asyncio
    async def test_save_without_user_id_skips_quota_check(self) -> None:
        """No user_id (e.g. anonymous callers, if any exist) means no quota is tracked."""
        store = SnapshotStore(aioredis_fake.FakeRedis(), max_per_user=1)
        nodes = [{"id": "1", "type": "artist"}]
        center = {"id": "1", "type": "artist"}

        await store.save(nodes, center)
        token, _ = await store.save(nodes, center)
        assert token

    @pytest.mark.asyncio
    async def test_max_per_user_from_env(self) -> None:
        with patch.dict("os.environ", {"SNAPSHOT_MAX_PER_USER": "7"}):
            store = SnapshotStore(aioredis_fake.FakeRedis())
            assert store.max_per_user == 7

    @pytest.mark.asyncio
    async def test_rejected_save_does_not_consume_quota(self) -> None:
        """A save rejected for being oversized must not still count against the
        user's quota (roll back the increment on the size-cap failure path)."""
        from api.snapshot_store import SnapshotTooLargeError

        redis = aioredis_fake.FakeRedis()
        store = SnapshotStore(redis, max_per_user=5, max_payload_bytes=100)
        oversized_nodes = [{"id": "1", "type": "artist", "extra": "x" * 200}]
        center = {"id": "1", "type": "artist"}

        with pytest.raises(SnapshotTooLargeError):
            await store.save(oversized_nodes, center, user_id="user-1")

        count = await redis.get("snapshot:usercount:user-1")
        assert count is None


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
        small_store = SnapshotStore(aioredis_fake.FakeRedis(), max_nodes=2)
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

    def test_restore_expired_token_returns_404(
        self, test_client: TestClient, auth_headers: dict[str, str], fake_redis_server: fakeredis.FakeServer
    ) -> None:
        import api.routers.snapshot as snapshot_module

        # Save a snapshot
        payload: dict[str, Any] = {
            "nodes": [{"id": "1", "type": "artist"}],
            "center": {"id": "1", "type": "artist"},
        }
        save_response = test_client.post("/api/snapshot", json=payload, headers=auth_headers)
        assert save_response.status_code == 201
        token = save_response.json()["token"]

        # Delete the key via sync fakeredis to simulate Redis TTL expiration
        sync_redis = fakeredis.FakeRedis(server=fake_redis_server)
        key = f"{snapshot_module._snapshot_store._KEY_PREFIX}{token}"
        sync_redis.delete(key)

        # Restore should return 404
        restore_response = test_client.get(f"/api/snapshot/{token}")
        assert restore_response.status_code == 404
