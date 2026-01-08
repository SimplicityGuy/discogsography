"""Tests for cache metrics tracking."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def mock_redis() -> AsyncMock:
    """Create a mock Redis client."""
    redis_mock = AsyncMock()
    redis_mock.ping = AsyncMock(return_value=True)
    redis_mock.get = AsyncMock(return_value=None)
    redis_mock.setex = AsyncMock(return_value=True)
    redis_mock.delete = AsyncMock(return_value=1)
    redis_mock.info = AsyncMock(
        return_value={
            "used_memory": 1024000,
            "used_memory_human": "1000K",
            "uptime_in_seconds": 3600,
        }
    )
    redis_mock.close = AsyncMock()
    return redis_mock


@pytest.mark.asyncio
async def test_cache_hit(mock_redis: AsyncMock) -> None:
    """Test that cache hits work correctly."""
    from discovery.cache import CacheManager

    cache = CacheManager()

    async def mock_from_url(*args, **kwargs):  # type: ignore[no-untyped-def]
        return mock_redis

    with patch("discovery.cache.aioredis.from_url", side_effect=mock_from_url):
        await cache.initialize()

        # Simulate cache hit
        mock_redis.get.return_value = b'{"test": "data"}'
        result = await cache.get("test:key")

        assert result == {"test": "data"}
        assert mock_redis.get.called

        await cache.close()


@pytest.mark.asyncio
async def test_cache_miss(mock_redis: AsyncMock) -> None:
    """Test that cache misses work correctly."""
    from discovery.cache import CacheManager

    cache = CacheManager()

    async def mock_from_url(*args, **kwargs):  # type: ignore[no-untyped-def]
        return mock_redis

    with patch("discovery.cache.aioredis.from_url", side_effect=mock_from_url):
        await cache.initialize()

        # Simulate cache miss
        mock_redis.get.return_value = None
        result = await cache.get("test:miss")

        assert result is None
        assert mock_redis.get.called

        await cache.close()


@pytest.mark.asyncio
async def test_cache_size_update(mock_redis: AsyncMock) -> None:
    """Test that cache size metric update works."""
    from discovery.cache import CacheManager

    cache = CacheManager()

    async def mock_from_url(*args, **kwargs):  # type: ignore[no-untyped-def]
        return mock_redis

    with patch("discovery.cache.aioredis.from_url", side_effect=mock_from_url):
        await cache.initialize()

        # Update cache size metrics
        await cache.update_cache_size_metrics()

        # Verify info was called with memory parameter
        mock_redis.info.assert_called_with("memory")

        await cache.close()


@pytest.mark.asyncio
async def test_cache_disconnected() -> None:
    """Test that cache handles L2 disconnection gracefully using L1."""
    from discovery.cache import CacheManager

    cache = CacheManager()

    # Don't initialize (simulating L2 disconnected, but L1 still works)
    result = await cache.get("test:key")
    assert result is None

    # Set should succeed with L1 even when L2 is unavailable
    success = await cache.set("test:key", "value")
    assert success is True

    # Get should succeed from L1
    result = await cache.get("test:key")
    assert result == "value"


@pytest.mark.asyncio
async def test_cache_stats(mock_redis: AsyncMock) -> None:
    """Test cache statistics retrieval."""
    from discovery.cache import CacheManager

    cache = CacheManager()

    async def mock_from_url(*args, **kwargs):  # type: ignore[no-untyped-def]
        return mock_redis

    # Mock scan_iter properly
    async def mock_scan_iter(match: str) -> None:  # type: ignore[misc]
        yield "discovery:key1"
        yield "discovery:key2"

    mock_redis.scan_iter = mock_scan_iter

    with patch("discovery.cache.aioredis.from_url", side_effect=mock_from_url):
        await cache.initialize()

        # Get cache stats
        stats = await cache.get_cache_stats()

        assert stats["connected"] is True
        assert stats["keys"] == 2
        assert stats["memory_used"] == 1024000
        assert stats["memory_human"] == "1000K"
        assert stats["uptime_seconds"] == 3600

        await cache.close()


@pytest.mark.asyncio
async def test_cache_stats_disconnected() -> None:
    """Test cache stats when disconnected."""
    from discovery.cache import CacheManager

    cache = CacheManager()

    # Don't initialize
    stats = await cache.get_cache_stats()

    assert stats["connected"] is False
    assert stats["keys"] == 0
    assert stats["memory_used"] == 0


@pytest.mark.asyncio
async def test_cache_stats_endpoint(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test the cache stats API endpoint."""
    # Mock the cache_manager.get_cache_stats method
    mock_stats = {
        "connected": True,
        "keys": 10,
        "memory_used": 2048000,
        "memory_human": "2M",
        "uptime_seconds": 7200,
    }

    async def mock_get_cache_stats() -> dict:  # type: ignore[type-arg]
        return mock_stats

    with patch("discovery.cache.cache_manager.get_cache_stats", side_effect=mock_get_cache_stats):
        # Make request to cache stats endpoint
        response = discovery_client.get("/api/cache/stats")

        assert response.status_code == 200
        data = response.json()

        assert "cache_stats" in data
        assert "timestamp" in data

        # Cache stats should have expected fields
        cache_stats = data["cache_stats"]
        assert cache_stats["connected"] is True
        assert cache_stats["keys"] == 10


@pytest.mark.asyncio
async def test_cache_error_handling(mock_redis: AsyncMock) -> None:
    """Test that cache errors are handled gracefully."""
    from discovery.cache import CacheManager

    cache = CacheManager()

    async def mock_from_url(*args, **kwargs):  # type: ignore[no-untyped-def]
        return mock_redis

    with patch("discovery.cache.aioredis.from_url", side_effect=mock_from_url):
        await cache.initialize()

        # Simulate Redis error on get
        mock_redis.get.side_effect = Exception("Redis error")

        result = await cache.get("test:error")

        # Should return None instead of raising
        assert result is None

        await cache.close()


@pytest.mark.asyncio
async def test_cache_set(mock_redis: AsyncMock) -> None:
    """Test cache set operation."""
    from discovery.cache import CacheManager

    cache = CacheManager()

    async def mock_from_url(*args, **kwargs):  # type: ignore[no-untyped-def]
        return mock_redis

    with patch("discovery.cache.aioredis.from_url", side_effect=mock_from_url):
        await cache.initialize()

        # Set a value
        success = await cache.set("test:key", {"data": "value"}, ttl=300)

        assert success is True
        assert mock_redis.setex.called

        await cache.close()
