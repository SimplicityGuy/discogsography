"""Unit tests for api/snapshot_store.py — SnapshotStore.save's own max_nodes guard.

discogsography-c3w: SnapshotStore.save previously never checked len(nodes)
against self._max_nodes; only the API router (api/routers/snapshot.py)
enforced the cap. Any direct caller of SnapshotStore bypassing the router
(scripts, future reuse) could persist arbitrarily large payloads to Redis.
"""

from unittest.mock import AsyncMock, patch

import fakeredis.aioredis as aioredis_fake
import pytest

from api.snapshot_store import SnapshotQuotaExceededError, SnapshotStore


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


class TestSnapshotStoreQuotaCounterAtomicity:
    """discogsography-7639: the per-user quota counter must self-heal a
    missing TTL and must not be permanently consumed by a failed save."""

    @pytest.mark.asyncio
    async def test_expire_self_heals_a_ttl_less_counter(self) -> None:
        """If a prior save's EXPIRE call was lost (crash/timeout right after
        INCR), the counter key would be left with NO TTL — permanent, never
        re-armed under the old `if count == 1` one-shot gate. The next save
        must notice the missing TTL and arm it via `EXPIRE ... NX`."""
        redis_client = aioredis_fake.FakeRedis()
        store = SnapshotStore(redis_client, ttl_days=1, max_per_user=50)
        count_key = f"{store._USER_COUNT_KEY_PREFIX}user-1"

        # Simulate the lost-EXPIRE failure mode directly: a counter that
        # exists but carries no TTL at all.
        await redis_client.set(count_key, 1)
        assert await redis_client.ttl(count_key) == -1  # no TTL

        await store.save([{"id": "1", "type": "artist"}], {"id": "1", "type": "artist"}, user_id="user-1")

        assert await redis_client.ttl(count_key) > 0

    @pytest.mark.asyncio
    async def test_expire_nx_does_not_reset_an_existing_ttl(self) -> None:
        """`NX` must be a no-op once a TTL is already armed — otherwise every
        save would keep sliding the window forward indefinitely."""
        redis_client = aioredis_fake.FakeRedis()
        store = SnapshotStore(redis_client, ttl_days=1, max_per_user=50)
        count_key = f"{store._USER_COUNT_KEY_PREFIX}user-1"

        await store.save([{"id": "1", "type": "artist"}], {"id": "1", "type": "artist"}, user_id="user-1")
        first_ttl = await redis_client.ttl(count_key)
        assert first_ttl > 0

        await store.save([{"id": "2", "type": "artist"}], {"id": "2", "type": "artist"}, user_id="user-1")
        second_ttl = await redis_client.ttl(count_key)
        assert second_ttl <= first_ttl

    @pytest.mark.asyncio
    async def test_failed_save_decrements_the_quota_counter(self) -> None:
        """A Redis error on the final `set()` must not permanently consume the
        user's quota slot for a snapshot that was never actually written."""
        redis_client = aioredis_fake.FakeRedis()
        store = SnapshotStore(redis_client, ttl_days=1, max_per_user=50)
        count_key = f"{store._USER_COUNT_KEY_PREFIX}user-1"

        with (
            patch.object(redis_client, "set", AsyncMock(side_effect=ConnectionError("boom"))),
            pytest.raises(ConnectionError),
        ):
            await store.save([{"id": "1", "type": "artist"}], {"id": "1", "type": "artist"}, user_id="user-1")

        # The incr was rolled back — the counter must not remain elevated.
        remaining = await redis_client.get(count_key)
        assert remaining in (None, b"0", "0")

    @pytest.mark.asyncio
    async def test_repeated_failed_saves_never_exhaust_the_quota(self) -> None:
        """Repeated transient failures on the final write must not accumulate
        into a quota lockout with zero live snapshots to show for it."""
        redis_client = aioredis_fake.FakeRedis()
        store = SnapshotStore(redis_client, ttl_days=1, max_per_user=3)
        count_key = f"{store._USER_COUNT_KEY_PREFIX}user-1"

        with patch.object(redis_client, "set", AsyncMock(side_effect=ConnectionError("boom"))):
            for _ in range(10):
                with pytest.raises(ConnectionError):
                    await store.save([{"id": "1", "type": "artist"}], {"id": "1", "type": "artist"}, user_id="user-1")

        remaining = await redis_client.get(count_key)
        assert remaining in (None, b"0", "0")

        # Quota must still be available for a real, successful save.
        token, _ = await store.save([{"id": "1", "type": "artist"}], {"id": "1", "type": "artist"}, user_id="user-1")
        assert token

    @pytest.mark.asyncio
    async def test_quota_exceeded_still_decrements(self) -> None:
        """Existing behavior preserved: exceeding the quota still decrements
        the over-count and raises, without ever calling the final set()."""
        redis_client = aioredis_fake.FakeRedis()
        store = SnapshotStore(redis_client, ttl_days=1, max_per_user=1)

        token, _ = await store.save([{"id": "1", "type": "artist"}], {"id": "1", "type": "artist"}, user_id="user-1")
        assert token

        with pytest.raises(SnapshotQuotaExceededError):
            await store.save([{"id": "2", "type": "artist"}], {"id": "2", "type": "artist"}, user_id="user-1")

        count_key = f"{store._USER_COUNT_KEY_PREFIX}user-1"
        assert (await redis_client.get(count_key)) in (b"1", "1")
