"""Unit tests for api/snapshot_store.py — SnapshotStore.save's own max_nodes guard.

discogsography-c3w: SnapshotStore.save previously never checked len(nodes)
against self._max_nodes; only the API router (api/routers/snapshot.py)
enforced the cap. Any direct caller of SnapshotStore bypassing the router
(scripts, future reuse) could persist arbitrarily large payloads to Redis.
"""

import fakeredis.aioredis as aioredis_fake
import pytest

from api.snapshot_store import SnapshotStore


class TestSnapshotStoreMaxNodes:
    @pytest.mark.asyncio
    async def test_save_within_limit_succeeds(self) -> None:
        store = SnapshotStore(aioredis_fake.FakeRedis(), max_nodes=2)
        token, expires_at = await store.save(
            [{"id": "1", "type": "artist"}, {"id": "2", "type": "artist"}],
            {"id": "1", "type": "artist"},
        )
        assert token
        assert expires_at is not None

    @pytest.mark.asyncio
    async def test_save_over_limit_raises_value_error(self) -> None:
        """Direct SnapshotStore.save() call must enforce max_nodes itself,
        independent of any caller-side pre-check."""
        store = SnapshotStore(aioredis_fake.FakeRedis(), max_nodes=2)
        nodes = [{"id": str(i), "type": "artist"} for i in range(3)]
        with pytest.raises(ValueError, match="Too many nodes"):
            await store.save(nodes, {"id": "0", "type": "artist"})

    @pytest.mark.asyncio
    async def test_save_over_limit_does_not_persist_to_redis(self) -> None:
        """The rejected snapshot must not be written to Redis at all."""
        redis_client = aioredis_fake.FakeRedis()
        store = SnapshotStore(redis_client, max_nodes=2)
        nodes = [{"id": str(i), "type": "artist"} for i in range(3)]
        with pytest.raises(ValueError):
            await store.save(nodes, {"id": "0", "type": "artist"})
        keys = await redis_client.keys(f"{store._KEY_PREFIX}*")
        assert keys == []

    @pytest.mark.asyncio
    async def test_save_exactly_at_limit_succeeds(self) -> None:
        """The boundary case: exactly max_nodes is allowed, not just under it."""
        store = SnapshotStore(aioredis_fake.FakeRedis(), max_nodes=3)
        nodes = [{"id": str(i), "type": "artist"} for i in range(3)]
        token, _ = await store.save(nodes, {"id": "0", "type": "artist"})
        assert token
