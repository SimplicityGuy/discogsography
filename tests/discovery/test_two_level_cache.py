"""Tests for two-level cache (L1: in-memory LRU, L2: Redis) implementation."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_redis() -> AsyncMock:
    """Create a mock Redis client."""
    redis_mock = AsyncMock()
    redis_mock.ping = AsyncMock(return_value=True)
    redis_mock.get = AsyncMock(return_value=None)
    redis_mock.setex = AsyncMock(return_value=True)
    redis_mock.delete = AsyncMock(return_value=1)
    redis_mock.close = AsyncMock()
    return redis_mock


@pytest.mark.asyncio
async def test_l1_cache_hit_bypasses_l2(mock_redis: AsyncMock) -> None:
    """Test that L1 cache hits bypass L2 Redis lookups."""
    from discovery.cache import CacheManager

    cache = CacheManager(l1_max_size=100, l1_ttl=300)

    async def mock_from_url(*args, **kwargs):  # type: ignore[no-untyped-def]
        return mock_redis

    with patch("discovery.cache.aioredis.from_url", side_effect=mock_from_url):
        await cache.initialize()

        # Set value in cache (writes to both L1 and L2)
        await cache.set("test:key", {"data": "value"})

        # Reset Redis mock call count
        mock_redis.get.reset_mock()

        # Get from cache - should hit L1 and not call Redis
        result = await cache.get("test:key")

        assert result == {"data": "value"}
        assert not mock_redis.get.called  # L1 hit, L2 not accessed

        await cache.close()


@pytest.mark.asyncio
async def test_l1_miss_l2_hit_warms_l1(mock_redis: AsyncMock) -> None:
    """Test that L2 hits warm the L1 cache."""
    from discovery.cache import CacheManager

    cache = CacheManager(l1_max_size=100, l1_ttl=300)

    async def mock_from_url(*args, **kwargs):  # type: ignore[no-untyped-def]
        return mock_redis

    with patch("discovery.cache.aioredis.from_url", side_effect=mock_from_url):
        await cache.initialize()

        # Simulate L2 hit (data in Redis but not in L1)
        mock_redis.get.return_value = b'{"data": "value"}'

        # First get - L1 miss, L2 hit, warms L1
        result = await cache.get("test:key")

        assert result == {"data": "value"}
        assert mock_redis.get.called

        # Reset Redis mock
        mock_redis.get.reset_mock()

        # Second get - should hit L1, not call Redis
        result = await cache.get("test:key")

        assert result == {"data": "value"}
        assert not mock_redis.get.called  # L1 warmed, L2 not accessed

        await cache.close()


@pytest.mark.asyncio
async def test_both_caches_miss(mock_redis: AsyncMock) -> None:
    """Test that both cache misses return None."""
    from discovery.cache import CacheManager

    cache = CacheManager(l1_max_size=100, l1_ttl=300)

    async def mock_from_url(*args, **kwargs):  # type: ignore[no-untyped-def]
        return mock_redis

    with patch("discovery.cache.aioredis.from_url", side_effect=mock_from_url):
        await cache.initialize()

        # Both caches empty
        mock_redis.get.return_value = None

        result = await cache.get("test:miss")

        assert result is None
        assert mock_redis.get.called

        await cache.close()


@pytest.mark.asyncio
async def test_set_writes_to_both_levels(mock_redis: AsyncMock) -> None:
    """Test that set() writes to both L1 and L2."""
    from discovery.cache import CacheManager

    cache = CacheManager(l1_max_size=100, l1_ttl=300, default_ttl=3600)

    async def mock_from_url(*args, **kwargs):  # type: ignore[no-untyped-def]
        return mock_redis

    with patch("discovery.cache.aioredis.from_url", side_effect=mock_from_url):
        await cache.initialize()

        # Set value
        success = await cache.set("test:key", {"data": "value"})

        assert success is True

        # Verify L1 has the value
        l1_value = cache.l1_cache.get("test:key")
        assert l1_value == {"data": "value"}

        # Verify L2 setex was called
        assert mock_redis.setex.called

        await cache.close()


@pytest.mark.asyncio
async def test_delete_removes_from_both_levels(mock_redis: AsyncMock) -> None:
    """Test that delete() removes from both L1 and L2."""
    from discovery.cache import CacheManager

    cache = CacheManager(l1_max_size=100, l1_ttl=300)

    async def mock_from_url(*args, **kwargs):  # type: ignore[no-untyped-def]
        return mock_redis

    with patch("discovery.cache.aioredis.from_url", side_effect=mock_from_url):
        await cache.initialize()

        # Set value in both caches
        await cache.set("test:key", {"data": "value"})

        # Verify L1 has it
        assert cache.l1_cache.get("test:key") is not None

        # Delete from both
        mock_redis.delete.return_value = 1
        success = await cache.delete("test:key")

        assert success is True

        # Verify L1 no longer has it
        assert cache.l1_cache.get("test:key") is None

        # Verify L2 delete was called
        assert mock_redis.delete.called

        await cache.close()


@pytest.mark.asyncio
async def test_clear_pattern_clears_both_levels(mock_redis: AsyncMock) -> None:
    """Test that clear_pattern() clears matching keys from both L1 and L2."""
    from discovery.cache import CacheManager

    cache = CacheManager(l1_max_size=100, l1_ttl=300)

    async def mock_from_url(*args, **kwargs):  # type: ignore[no-untyped-def]
        return mock_redis

    # Mock scan_iter to return matching keys
    async def mock_scan_iter(match: str) -> None:  # type: ignore[misc]
        yield "discovery:search:key1"
        yield "discovery:search:key2"

    mock_redis.scan_iter = mock_scan_iter
    mock_redis.delete.return_value = 2

    with patch("discovery.cache.aioredis.from_url", side_effect=mock_from_url):
        await cache.initialize()

        # Add keys to L1 that match pattern
        cache.l1_cache.set("search:key1", "value1")
        cache.l1_cache.set("search:key2", "value2")
        cache.l1_cache.set("other:key", "value3")

        # Clear pattern
        deleted = await cache.clear_pattern("search:*")

        # Should delete 2 from L1 + 2 from L2 = 4 total
        assert deleted == 4

        # Verify L1 keys are gone but other key remains
        assert cache.l1_cache.get("search:key1") is None
        assert cache.l1_cache.get("search:key2") is None
        assert cache.l1_cache.get("other:key") is not None

        # Verify L2 delete was called
        assert mock_redis.delete.called

        await cache.close()


@pytest.mark.asyncio
async def test_l1_ttl_expiration() -> None:
    """Test that L1 cache entries expire based on TTL."""
    from discovery.cache import CacheManager

    # Use very short TTL for testing
    cache = CacheManager(l1_max_size=100, l1_ttl=1)

    # Set value in L1 only (no Redis connection)
    cache.l1_cache.set("test:key", "value", ttl=1)

    # Immediately get - should succeed
    result = cache.l1_cache.get("test:key")
    assert result == "value"

    # Wait for expiration
    await asyncio.sleep(1.1)

    # Get after expiration - should return None
    result = cache.l1_cache.get("test:key")
    assert result is None


@pytest.mark.asyncio
async def test_l2_unavailable_still_uses_l1() -> None:
    """Test that L1 cache works when L2 is unavailable."""
    from discovery.cache import CacheManager

    cache = CacheManager(l1_max_size=100, l1_ttl=300)

    # Don't initialize Redis (L2 unavailable)
    # Set value - should succeed with L1 only
    success = await cache.set("test:key", {"data": "value"})
    assert success is True

    # Get value - should succeed from L1
    result = await cache.get("test:key")
    assert result == {"data": "value"}

    # Delete value - should succeed from L1
    success = await cache.delete("test:key")
    assert success is True

    # Verify L1 is empty
    assert cache.l1_cache.get("test:key") is None


@pytest.mark.asyncio
async def test_l1_cache_eviction() -> None:
    """Test that L1 cache evicts oldest entries when at capacity."""
    from discovery.cache import CacheManager

    # Small cache size for testing
    cache = CacheManager(l1_max_size=3, l1_ttl=300)

    # Fill cache to capacity
    cache.l1_cache.set("key1", "value1")
    cache.l1_cache.set("key2", "value2")
    cache.l1_cache.set("key3", "value3")

    # All keys should be present
    assert cache.l1_cache.get("key1") == "value1"
    assert cache.l1_cache.get("key2") == "value2"
    assert cache.l1_cache.get("key3") == "value3"

    # Add one more key - should evict oldest (key1)
    cache.l1_cache.set("key4", "value4")

    # key1 should be evicted
    assert cache.l1_cache.get("key1") is None
    # Others should remain
    assert cache.l1_cache.get("key2") == "value2"
    assert cache.l1_cache.get("key3") == "value3"
    assert cache.l1_cache.get("key4") == "value4"


@pytest.mark.asyncio
async def test_l1_cache_lru_behavior() -> None:
    """Test that L1 cache uses LRU eviction policy."""
    from discovery.cache import CacheManager

    cache = CacheManager(l1_max_size=3, l1_ttl=300)

    # Fill cache
    cache.l1_cache.set("key1", "value1")
    cache.l1_cache.set("key2", "value2")
    cache.l1_cache.set("key3", "value3")

    # Access key1 to make it most recently used
    _ = cache.l1_cache.get("key1")

    # Add new key - should evict key2 (least recently used)
    cache.l1_cache.set("key4", "value4")

    # key2 should be evicted
    assert cache.l1_cache.get("key2") is None
    # key1 should remain (was recently accessed)
    assert cache.l1_cache.get("key1") == "value1"
    # Others should remain
    assert cache.l1_cache.get("key3") == "value3"
    assert cache.l1_cache.get("key4") == "value4"


@pytest.mark.asyncio
async def test_metrics_tracking_for_l1_l2(mock_redis: AsyncMock) -> None:
    """Test that metrics are tracked separately for L1 and L2 cache hits/misses."""
    from discovery.cache import CacheManager

    cache = CacheManager(l1_max_size=100, l1_ttl=300)

    async def mock_from_url(*args, **kwargs):  # type: ignore[no-untyped-def]
        return mock_redis

    with (
        patch("discovery.cache.aioredis.from_url", side_effect=mock_from_url),
        patch("discovery.cache.cache_hits") as mock_hits,
        patch("discovery.cache.cache_misses") as mock_misses,
    ):
        # Configure mocks
        mock_hits_metric = MagicMock()
        mock_hits.labels.return_value = mock_hits_metric

        mock_misses_metric = MagicMock()
        mock_misses.labels.return_value = mock_misses_metric

        await cache.initialize()

        # L1 hit
        cache.l1_cache.set("test:key", "value")
        await cache.get("test:key")

        # Verify L1 hit metric
        assert any("l1_" in str(call) for call in mock_hits.labels.call_args_list)

        # L2 hit (L1 miss)
        mock_redis.get.return_value = b'{"data": "value"}'
        await cache.get("test:other")

        # Verify L2 hit metric
        assert any("l2_" in str(call) for call in mock_hits.labels.call_args_list)

        # Both miss
        mock_redis.get.return_value = None
        await cache.get("test:miss")

        # Verify miss metric
        assert mock_misses.labels.called

        await cache.close()


@pytest.mark.asyncio
async def test_l1_evict_expired() -> None:
    """Test manual expiration of L1 cache entries."""
    from discovery.cache import CacheManager

    cache = CacheManager(l1_max_size=100, l1_ttl=1)

    # Add entries with short TTL
    cache.l1_cache.set("key1", "value1", ttl=1)
    cache.l1_cache.set("key2", "value2", ttl=1)
    cache.l1_cache.set("key3", "value3", ttl=10)  # Longer TTL

    # Wait for first two to expire
    await asyncio.sleep(1.1)

    # Manually evict expired entries
    evicted = cache.l1_cache.evict_expired()

    # Should evict 2 entries
    assert evicted == 2

    # Verify expired entries are gone
    assert cache.l1_cache.get("key1") is None
    assert cache.l1_cache.get("key2") is None
    # Long TTL entry should remain
    assert cache.l1_cache.get("key3") == "value3"


@pytest.mark.asyncio
async def test_l1_clear_all() -> None:
    """Test clearing all L1 cache entries."""
    from discovery.cache import CacheManager

    cache = CacheManager(l1_max_size=100, l1_ttl=300)

    # Add multiple entries
    cache.l1_cache.set("key1", "value1")
    cache.l1_cache.set("key2", "value2")
    cache.l1_cache.set("key3", "value3")

    assert cache.l1_cache.size() == 3

    # Clear all
    cache.l1_cache.clear()

    # Verify empty
    assert cache.l1_cache.size() == 0
    assert cache.l1_cache.get("key1") is None
    assert cache.l1_cache.get("key2") is None
    assert cache.l1_cache.get("key3") is None
