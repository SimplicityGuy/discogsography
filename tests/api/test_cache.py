"""Unit tests for RecommendCache."""

import json
from unittest.mock import AsyncMock

import pytest

from api.cache import RecommendCache


class TestRecommendCache:
    """Tests for the RecommendCache class."""

    @pytest.fixture
    def mock_redis(self) -> AsyncMock:
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock()
        redis.scan = AsyncMock(return_value=(0, []))
        redis.delete = AsyncMock()
        return redis

    @pytest.fixture
    def cache(self, mock_redis: AsyncMock) -> RecommendCache:
        return RecommendCache(redis=mock_redis, default_ttl=3600)

    @pytest.mark.asyncio
    async def test_get_miss(self, cache: RecommendCache) -> None:
        result = await cache.get("recommend:missing")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_hit(self, cache: RecommendCache, mock_redis: AsyncMock) -> None:
        mock_redis.get = AsyncMock(return_value=json.dumps({"key": "value"}))
        result = await cache.get("recommend:hit")
        assert result == {"key": "value"}

    @pytest.mark.asyncio
    async def test_get_redis_error(self, cache: RecommendCache, mock_redis: AsyncMock) -> None:
        mock_redis.get = AsyncMock(side_effect=ConnectionError("down"))
        result = await cache.get("recommend:fail")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_stores_with_ttl(self, cache: RecommendCache, mock_redis: AsyncMock) -> None:
        await cache.set("recommend:key", {"data": 1}, ttl=7200)
        mock_redis.set.assert_called_once()
        call_kwargs = mock_redis.set.call_args
        assert call_kwargs[1]["ex"] == 7200

    @pytest.mark.asyncio
    async def test_set_uses_default_ttl(self, cache: RecommendCache, mock_redis: AsyncMock) -> None:
        await cache.set("recommend:key", {"data": 1})
        call_kwargs = mock_redis.set.call_args
        assert call_kwargs[1]["ex"] == 3600

    @pytest.mark.asyncio
    async def test_set_redis_error(self, cache: RecommendCache, mock_redis: AsyncMock) -> None:
        mock_redis.set = AsyncMock(side_effect=ConnectionError("down"))
        await cache.set("recommend:key", {"data": 1})  # should not raise

    @pytest.mark.asyncio
    async def test_invalidate_user(self, cache: RecommendCache, mock_redis: AsyncMock) -> None:
        # Two SCAN responses: one per pattern (explore:*, enhanced:{user_id})
        mock_redis.scan = AsyncMock(
            side_effect=[
                (0, ["recommend:explore:user1:artist:a1"]),
                (0, ["recommend:enhanced:user1"]),
            ]
        )
        await cache.invalidate_user("user1")
        assert mock_redis.delete.call_count == 2

    @pytest.mark.asyncio
    async def test_invalidate_user_no_keys(self, cache: RecommendCache, mock_redis: AsyncMock) -> None:
        mock_redis.scan = AsyncMock(return_value=(0, []))
        await cache.invalidate_user("user1")
        mock_redis.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalidate_user_redis_error(self, cache: RecommendCache, mock_redis: AsyncMock) -> None:
        mock_redis.scan = AsyncMock(side_effect=ConnectionError("down"))
        await cache.invalidate_user("user1")  # should not raise
