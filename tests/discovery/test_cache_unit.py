"""Unit tests for Discovery service Redis caching functionality."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestCacheManagerUnit:
    """Test the CacheManager class in isolation."""

    def test_cache_manager_init(self) -> None:
        """Test CacheManager initialization."""
        # Import the class directly to avoid global execution
        from discovery.cache import CacheManager

        cache = CacheManager(
            redis_url="redis://localhost:6379/1",
            default_ttl=1800,
            key_prefix="test:",
        )

        assert cache.redis_url == "redis://localhost:6379/1"
        assert cache.default_ttl == 1800
        assert cache.key_prefix == "test:"
        assert cache.redis is None
        assert not cache.connected

    @pytest.mark.asyncio
    async def test_initialize_success(self) -> None:
        """Test successful Redis initialization."""
        from discovery.cache import CacheManager

        with patch("discovery.cache.aioredis.from_url", new_callable=AsyncMock) as mock_from_url:
            mock_redis = AsyncMock()
            mock_redis.ping = AsyncMock(return_value=True)
            mock_from_url.return_value = mock_redis

            cache = CacheManager()
            await cache.initialize()

            assert cache.redis == mock_redis
            assert cache.connected
            mock_redis.ping.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialize_failure(self) -> None:
        """Test Redis initialization failure."""
        from discovery.cache import CacheManager

        with patch("discovery.cache.aioredis.from_url", new_callable=AsyncMock) as mock_from_url:
            mock_from_url.side_effect = OSError("Connection failed")

            cache = CacheManager()
            await cache.initialize()

            assert cache.redis is None
            assert not cache.connected

    @pytest.mark.asyncio
    async def test_close(self) -> None:
        """Test closing Redis connection."""
        from discovery.cache import CacheManager

        mock_redis = AsyncMock()
        mock_redis.close = AsyncMock(return_value=None)

        cache = CacheManager()
        cache.redis = mock_redis
        await cache.close()

        mock_redis.close.assert_called_once()

    def test_make_key(self) -> None:
        """Test cache key generation."""
        from discovery.cache import CacheManager

        cache = CacheManager(key_prefix="test:")
        key = cache._make_key("search")
        assert key == "test:search"

    def test_serialize_deserialize(self) -> None:
        """Test value serialization and deserialization."""
        from discovery.cache import CacheManager

        test_data = {"test": "data", "number": 42, "list": [1, 2, 3]}

        serialized = CacheManager._serialize_value(test_data)
        assert isinstance(serialized, bytes)

        deserialized = CacheManager._deserialize_value(serialized)
        assert deserialized == test_data

    @pytest.mark.asyncio
    async def test_get_cache_hit(self) -> None:
        """Test successful cache retrieval."""
        from discovery.cache import CacheManager

        mock_redis = AsyncMock()
        test_data = {"result": "test"}
        serialized_data = json.dumps(test_data).encode()
        mock_redis.get = AsyncMock(return_value=serialized_data)

        cache = CacheManager()
        cache.redis = mock_redis
        cache.connected = True

        with patch.object(cache, "_deserialize_value", return_value=test_data):
            result = await cache.get("test_key")

        assert result == test_data
        mock_redis.get.assert_called_once_with("discovery:test_key")

    @pytest.mark.asyncio
    async def test_get_cache_miss(self) -> None:
        """Test cache miss (no data found)."""
        from discovery.cache import CacheManager

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        cache = CacheManager()
        cache.redis = mock_redis
        cache.connected = True

        result = await cache.get("missing_key")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_not_connected(self) -> None:
        """Test cache get when not connected."""
        from discovery.cache import CacheManager

        cache = CacheManager()
        cache.connected = False

        result = await cache.get("test_key")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_success(self) -> None:
        """Test successful cache set."""
        from discovery.cache import CacheManager

        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock(return_value=True)
        test_data = {"result": "test"}

        cache = CacheManager()
        cache.redis = mock_redis
        cache.connected = True

        with patch.object(cache, "_serialize_value", return_value=b"serialized"):
            result = await cache.set("test_key", test_data, 300)

        assert result is True
        mock_redis.setex.assert_called_once_with("discovery:test_key", 300, b"serialized")

    @pytest.mark.asyncio
    async def test_set_not_connected(self) -> None:
        """Test cache set when not connected."""
        from discovery.cache import CacheManager

        cache = CacheManager()
        cache.connected = False

        result = await cache.set("test_key", {"data": "test"})
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_success(self) -> None:
        """Test successful cache delete."""
        from discovery.cache import CacheManager

        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock(return_value=1)

        cache = CacheManager()
        cache.redis = mock_redis
        cache.connected = True

        result = await cache.delete("test_key")
        assert result is True
        mock_redis.delete.assert_called_once_with("discovery:test_key")

    @pytest.mark.asyncio
    async def test_clear_pattern(self) -> None:
        """Test clearing keys by pattern."""
        from discovery.cache import CacheManager

        mock_redis = AsyncMock()

        # Mock scan_iter to return some keys
        async def mock_scan_iter(match: str):  # noqa: ARG001
            for key in [b"discovery:search:abc", b"discovery:search:def"]:
                yield key

        mock_redis.scan_iter = mock_scan_iter
        mock_redis.delete = AsyncMock(return_value=2)

        cache = CacheManager()
        cache.redis = mock_redis
        cache.connected = True

        result = await cache.clear_pattern("search:*")
        assert result == 2
        mock_redis.delete.assert_called_once()

    def test_cache_key_for_params(self) -> None:
        """Test cache key generation from parameters."""
        from discovery.cache import CacheManager

        cache = CacheManager()

        # Test with consistent parameter ordering
        key1 = cache.cache_key_for_params("search", query="test", limit=10)
        key2 = cache.cache_key_for_params("search", limit=10, query="test")

        assert key1 == key2
        assert key1.startswith("search:")
        assert len(key1.split(":")[1]) == 8  # 8-character hash


class TestCachedDecoratorUnit:
    """Test the @cached decorator in isolation."""

    @pytest.mark.asyncio
    async def test_cached_decorator_cache_miss(self) -> None:
        """Test cached decorator with cache miss."""
        from discovery.cache import cached

        class TestClass:
            def __init__(self) -> None:
                self.cache = AsyncMock()
                self.cache.connected = True
                self.cache.get = AsyncMock(return_value=None)  # Cache miss
                self.cache.set = AsyncMock(return_value=True)
                self.cache.cache_key_for_params = MagicMock(return_value="test_key")

            @cached("test", ttl=300)
            async def test_method(self, arg1: str, arg2: int = 10) -> dict:
                return {"arg1": arg1, "arg2": arg2, "called": True}

        obj = TestClass()
        result = await obj.test_method("hello", arg2=20)

        assert result == {"arg1": "hello", "arg2": 20, "called": True}
        obj.cache.get.assert_called_once_with("test_key")
        obj.cache.set.assert_called_once_with("test_key", result, 300)

    @pytest.mark.asyncio
    async def test_cached_decorator_cache_hit(self) -> None:
        """Test cached decorator with cache hit."""
        from discovery.cache import cached

        cached_data = {"cached": True, "from_cache": True}

        class TestClass:
            def __init__(self) -> None:
                self.cache = AsyncMock()
                self.cache.connected = True
                self.cache.get = AsyncMock(return_value=cached_data)  # Cache hit
                self.cache.cache_key_for_params = MagicMock(return_value="test_key")

            @cached("test", ttl=300)
            async def test_method(self, arg1: str) -> dict:  # noqa: ARG002
                # This should not be called due to cache hit
                return {"should_not": "be_called"}

        obj = TestClass()
        result = await obj.test_method("hello")

        assert result == cached_data
        obj.cache.get.assert_called_once_with("test_key")
        obj.cache.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_cached_decorator_no_cache(self) -> None:
        """Test cached decorator when cache is not available."""
        from discovery.cache import cached

        class TestClass:
            def __init__(self) -> None:
                self.cache = None  # No cache available

            @cached("test", ttl=300)
            async def test_method(self, arg1: str) -> dict:
                return {"arg1": arg1, "no_cache": True}

        obj = TestClass()
        result = await obj.test_method("hello")

        assert result == {"arg1": "hello", "no_cache": True}


class TestCacheConstantsUnit:
    """Test cache configuration constants."""

    def test_cache_ttl_constants(self) -> None:
        """Test that cache TTL constants are properly defined."""
        # Import directly to avoid global execution issues
        with patch("discovery.cache.get_config"):
            from discovery.cache import CACHE_TTL

            assert isinstance(CACHE_TTL, dict)

            # Check required cache types
            required_types = [
                "search",
                "graph",
                "journey",
                "trends",
                "heatmap",
                "artist_details",
                "recommendations",
                "analytics",
            ]

            for cache_type in required_types:
                assert cache_type in CACHE_TTL
                assert isinstance(CACHE_TTL[cache_type], int)
                assert CACHE_TTL[cache_type] > 0
