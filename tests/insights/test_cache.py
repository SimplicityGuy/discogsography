"""Tests for insights cache module."""

from typing import Any
from unittest.mock import AsyncMock

import fakeredis.aioredis as aioredis_fake
import pytest

from insights.cache import GENERATION_KEY, InsightsCache


@pytest.fixture
def mock_redis() -> AsyncMock:
    """Create a mock Redis client (for error-path tests)."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()
    redis.incr = AsyncMock(return_value=1)
    redis.scan = AsyncMock(return_value=(0, []))
    redis.delete = AsyncMock()
    return redis


@pytest.fixture
def cache(mock_redis: AsyncMock) -> InsightsCache:
    """Create an InsightsCache with mock Redis."""
    return InsightsCache(mock_redis, ttl_seconds=3600)


@pytest.fixture
def real_redis() -> Any:
    """A real (in-memory) Redis, so generation semantics are exercised for real."""
    return aioredis_fake.FakeRedis(decode_responses=True)


@pytest.fixture
def real_cache(real_redis: Any) -> InsightsCache:
    return InsightsCache(real_redis, ttl_seconds=3600)


class TestVersionedKey:
    def test_namespaces_by_generation(self) -> None:
        assert InsightsCache.versioned_key("insights:top-artists:10", 3) == "insights:g3:top-artists:10"

    def test_accepts_keys_without_the_legacy_prefix(self) -> None:
        assert InsightsCache.versioned_key("top-artists:10", 3) == "insights:g3:top-artists:10"

    def test_generation_key_is_outside_the_scanned_namespace(self) -> None:
        """invalidate_all deletes insights:g* — the counter must not be swept with it."""
        assert not GENERATION_KEY.startswith("insights:g")


class TestCacheGet:
    @pytest.mark.asyncio
    async def test_returns_none_on_miss(self, cache: InsightsCache) -> None:
        assert await cache.get("insights:top-artists:10", 0) is None

    @pytest.mark.asyncio
    async def test_returns_cached_value_on_hit(self, cache: InsightsCache, mock_redis: AsyncMock) -> None:
        mock_redis.get.return_value = '{"items": [1, 2, 3], "count": 3}'
        assert await cache.get("insights:top-artists:10", 0) == {"items": [1, 2, 3], "count": 3}

    @pytest.mark.asyncio
    async def test_reads_from_the_requested_generation(self, cache: InsightsCache, mock_redis: AsyncMock) -> None:
        await cache.get("insights:top-artists:10", 7)
        mock_redis.get.assert_awaited_once_with("insights:g7:top-artists:10")

    @pytest.mark.asyncio
    async def test_returns_none_on_redis_error(self, cache: InsightsCache, mock_redis: AsyncMock) -> None:
        mock_redis.get.side_effect = ConnectionError("Redis down")
        assert await cache.get("insights:top-artists:10", 0) is None


class TestCacheSet:
    @pytest.mark.asyncio
    async def test_stores_value_with_ttl_in_the_generation_namespace(self, cache: InsightsCache, mock_redis: AsyncMock) -> None:
        await cache.set("insights:top-artists:10", {"items": [], "count": 0}, 2)
        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        assert call_args[0][0] == "insights:g2:top-artists:10"
        assert call_args[1]["ex"] == 3600

    @pytest.mark.asyncio
    async def test_silently_fails_on_redis_error(self, cache: InsightsCache, mock_redis: AsyncMock) -> None:
        mock_redis.set.side_effect = ConnectionError("Redis down")
        await cache.set("insights:top-artists:10", {"items": []}, 0)  # must not raise


class TestCacheGeneration:
    @pytest.mark.asyncio
    async def test_starts_at_zero(self, real_cache: InsightsCache) -> None:
        assert await real_cache.generation() == 0

    @pytest.mark.asyncio
    async def test_advances_on_invalidation(self, real_cache: InsightsCache) -> None:
        await real_cache.invalidate_all()
        assert await real_cache.generation() == 1
        await real_cache.invalidate_all()
        assert await real_cache.generation() == 2

    @pytest.mark.asyncio
    async def test_falls_back_to_zero_on_redis_error(self, cache: InsightsCache, mock_redis: AsyncMock) -> None:
        mock_redis.get.side_effect = ConnectionError("Redis down")
        assert await cache.generation() == 0


class TestCacheAsideRace:
    """discogsography-cu2.109: a request straddling a recompute must not re-cache stale data.

    Interleaving that used to poison the cache for a full schedule interval:
      1. endpoint reads OLD rows from Postgres,
      2. scheduler commits NEW rows and invalidates,
      3. endpoint's set() lands — writing the stale result AFTER the invalidation.
    """

    @pytest.mark.asyncio
    async def test_set_after_invalidation_is_not_served(self, real_cache: InsightsCache) -> None:
        # 1. The request captures the generation before its database read.
        generation = await real_cache.generation()
        stale = {"items": ["yesterday's rankings"], "count": 1}

        # 2. The scheduler finishes its cycle and invalidates.
        await real_cache.invalidate_all()

        # 3. The in-flight request's set finally lands — into the retired generation.
        await real_cache.set("insights:top-artists:100", stale, generation)

        # A subsequent request reads the CURRENT generation and must miss,
        # falling through to the freshly computed Postgres rows.
        current = await real_cache.generation()
        assert current != generation
        assert await real_cache.get("insights:top-artists:100", current) is None

    @pytest.mark.asyncio
    async def test_normal_cache_aside_still_hits(self, real_cache: InsightsCache) -> None:
        """The fix must not break the non-racing path."""
        generation = await real_cache.generation()
        payload = {"items": [1, 2, 3], "count": 3}
        await real_cache.set("insights:top-artists:100", payload, generation)
        assert await real_cache.get("insights:top-artists:100", await real_cache.generation()) == payload

    @pytest.mark.asyncio
    async def test_entries_written_after_the_bump_are_preserved(self, real_cache: InsightsCache) -> None:
        """Housekeeping must not delete keys from the generation now being served."""
        await real_cache.invalidate_all()
        generation = await real_cache.generation()
        payload = {"items": ["fresh"], "count": 1}
        await real_cache.set("insights:top-artists:100", payload, generation)
        assert await real_cache.get("insights:top-artists:100", generation) == payload

    @pytest.mark.asyncio
    async def test_every_generation_is_distinct(self, real_cache: InsightsCache) -> None:
        seen = set()
        for _ in range(3):
            seen.add(await real_cache.generation())
            await real_cache.invalidate_all()
        assert len(seen) == 3


class TestCacheInvalidateAll:
    @pytest.mark.asyncio
    async def test_reclaims_superseded_generation_keys(self, real_cache: InsightsCache, real_redis: Any) -> None:
        generation = await real_cache.generation()
        await real_cache.set("insights:top-artists:10", {"a": 1}, generation)
        await real_cache.set("insights:genre-trends:Rock", {"b": 2}, generation)

        await real_cache.invalidate_all()

        assert await real_redis.get(f"insights:g{generation}:top-artists:10") is None
        assert await real_redis.get(f"insights:g{generation}:genre-trends:Rock") is None

    @pytest.mark.asyncio
    async def test_does_not_touch_unversioned_insights_keys(self, real_cache: InsightsCache, real_redis: Any) -> None:
        """The API service caches insights:data-completeness on a possibly-shared Redis."""
        await real_redis.set("insights:data-completeness", "api-owned")

        await real_cache.invalidate_all()

        assert await real_redis.get("insights:data-completeness") == "api-owned"

    @pytest.mark.asyncio
    async def test_preserves_the_generation_counter(self, real_cache: InsightsCache, real_redis: Any) -> None:
        await real_cache.invalidate_all()
        await real_cache.invalidate_all()
        assert await real_redis.get(GENERATION_KEY) == "2"

    @pytest.mark.asyncio
    async def test_handles_no_keys(self, cache: InsightsCache, mock_redis: AsyncMock) -> None:
        mock_redis.scan.return_value = (0, [])
        await cache.invalidate_all()
        mock_redis.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_multiple_scan_pages(self, cache: InsightsCache, mock_redis: AsyncMock) -> None:
        # incr returns 1, so "insights:g1:" is the live generation and is skipped.
        mock_redis.scan.side_effect = [
            ("42", ["insights:g0:key1"]),
            ("0", ["insights:g0:key2"]),
        ]
        await cache.invalidate_all()
        assert mock_redis.delete.call_count == 2

    @pytest.mark.asyncio
    async def test_handles_bytes_keys_from_the_client(self, cache: InsightsCache, mock_redis: AsyncMock) -> None:
        mock_redis.scan.side_effect = [(0, [b"insights:g0:key1"])]
        await cache.invalidate_all()
        mock_redis.delete.assert_called_once_with(b"insights:g0:key1")

    @pytest.mark.asyncio
    async def test_scan_failure_does_not_raise(self, cache: InsightsCache, mock_redis: AsyncMock) -> None:
        mock_redis.scan.side_effect = ConnectionError("Redis down")
        await cache.invalidate_all()  # must not raise

    @pytest.mark.asyncio
    async def test_incr_failure_does_not_raise(self, cache: InsightsCache, mock_redis: AsyncMock) -> None:
        mock_redis.incr.side_effect = ConnectionError("Redis down")
        await cache.invalidate_all()  # must not raise
        mock_redis.delete.assert_not_called()
