"""Tests for insights cache module."""

from unittest.mock import AsyncMock

import pytest

from insights.cache import InsightsCache


@pytest.fixture
def mock_redis() -> AsyncMock:
    """Create a mock Redis client."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()
    redis.scan = AsyncMock(return_value=(0, []))
    redis.delete = AsyncMock()
    return redis


@pytest.fixture
def cache(mock_redis: AsyncMock) -> InsightsCache:
    """Create an InsightsCache with mock Redis."""
    return InsightsCache(mock_redis, ttl_seconds=3600)


class TestCacheGet:
    @pytest.mark.asyncio
    async def test_returns_none_on_miss(self, cache: InsightsCache) -> None:
        result = await cache.get("insights:top-artists:10")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_cached_value_on_hit(self, cache: InsightsCache, mock_redis: AsyncMock) -> None:
        mock_redis.get.return_value = '{"items": [1, 2, 3], "count": 3}'
        result = await cache.get("insights:top-artists:10")
        assert result == {"items": [1, 2, 3], "count": 3}

    @pytest.mark.asyncio
    async def test_returns_none_on_redis_error(self, cache: InsightsCache, mock_redis: AsyncMock) -> None:
        mock_redis.get.side_effect = ConnectionError("Redis down")
        result = await cache.get("insights:top-artists:10")
        assert result is None


class TestCacheSet:
    @pytest.mark.asyncio
    async def test_stores_value_with_ttl(self, cache: InsightsCache, mock_redis: AsyncMock) -> None:
        await cache.set("insights:top-artists:10", {"items": [], "count": 0})
        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        assert call_args[0][0] == "insights:top-artists:10"
        assert call_args[1]["ex"] == 3600

    @pytest.mark.asyncio
    async def test_silently_fails_on_redis_error(self, cache: InsightsCache, mock_redis: AsyncMock) -> None:
        mock_redis.set.side_effect = ConnectionError("Redis down")
        # Should not raise
        await cache.set("insights:top-artists:10", {"items": []})


class TestCacheInvalidateAll:
    @pytest.mark.asyncio
    async def test_deletes_matching_keys(self, cache: InsightsCache, mock_redis: AsyncMock) -> None:
        mock_redis.scan.return_value = (0, ["insights:top-artists:10", "insights:genre-trends:Rock"])
        await cache.invalidate_all()
        mock_redis.delete.assert_called_once_with("insights:top-artists:10", "insights:genre-trends:Rock")

    @pytest.mark.asyncio
    async def test_handles_no_keys(self, cache: InsightsCache, mock_redis: AsyncMock) -> None:
        mock_redis.scan.return_value = (0, [])
        await cache.invalidate_all()
        mock_redis.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_multiple_scan_pages(self, cache: InsightsCache, mock_redis: AsyncMock) -> None:
        # First scan returns cursor=42 (not done), second returns cursor=0 (done)
        mock_redis.scan.side_effect = [
            (42, ["insights:key1"]),
            (0, ["insights:key2"]),
        ]
        await cache.invalidate_all()
        assert mock_redis.delete.call_count == 2

    @pytest.mark.asyncio
    async def test_silently_fails_on_redis_error(self, cache: InsightsCache, mock_redis: AsyncMock) -> None:
        mock_redis.scan.side_effect = ConnectionError("Redis down")
        # Should not raise
        await cache.invalidate_all()
