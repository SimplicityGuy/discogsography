"""Tests for cache warming functionality."""

# ruff: noqa: ARG001
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def mock_redis() -> AsyncMock:
    """Create a mock Redis client."""
    redis_mock = AsyncMock()
    redis_mock.ping = AsyncMock(return_value=True)
    redis_mock.setex = AsyncMock(return_value=True)
    redis_mock.close = AsyncMock()
    return redis_mock


@pytest.mark.asyncio
async def test_warm_cache_basic(mock_redis: AsyncMock) -> None:
    """Test basic cache warming with simple queries."""
    from discovery.cache import CacheManager

    cache = CacheManager(l1_max_size=100, l1_ttl=300)

    async def mock_from_url(*args, **kwargs):  # type: ignore[no-untyped-def]
        return mock_redis

    with patch("discovery.cache.aioredis.from_url", side_effect=mock_from_url):
        await cache.initialize()

        # Define warming queries
        async def query1() -> dict:  # type: ignore[type-arg]
            return {"result": "data1"}

        async def query2() -> dict:  # type: ignore[type-arg]
            return {"result": "data2"}

        warming_queries = [
            {"query_func": query1, "cache_key": "test:key1", "ttl": 300},
            {"query_func": query2, "cache_key": "test:key2", "ttl": 600},
        ]

        # Warm cache
        stats = await cache.warm_cache(warming_queries)

        # Verify statistics
        assert stats["total_queries"] == 2
        assert stats["successful"] == 2
        assert stats["failed"] == 0
        assert len(stats["errors"]) == 0

        # Verify data is in L1 cache
        assert cache.l1_cache.get("test:key1") == {"result": "data1"}
        assert cache.l1_cache.get("test:key2") == {"result": "data2"}

        # Verify L2 (Redis) setex was called
        assert mock_redis.setex.call_count == 2

        await cache.close()


@pytest.mark.asyncio
async def test_warm_cache_with_errors(mock_redis: AsyncMock) -> None:
    """Test cache warming handles query errors gracefully."""
    from discovery.cache import CacheManager

    cache = CacheManager(l1_max_size=100, l1_ttl=300)

    async def mock_from_url(*args, **kwargs):  # type: ignore[no-untyped-def]
        return mock_redis

    with patch("discovery.cache.aioredis.from_url", side_effect=mock_from_url):
        await cache.initialize()

        # Define queries - one succeeds, one fails
        async def query_success() -> dict:  # type: ignore[type-arg]
            return {"result": "success"}

        async def query_fail() -> None:
            raise ValueError("Query failed")

        warming_queries = [
            {"query_func": query_success, "cache_key": "test:success", "ttl": 300},
            {"query_func": query_fail, "cache_key": "test:fail", "ttl": 300},
        ]

        # Warm cache
        stats = await cache.warm_cache(warming_queries)

        # Verify statistics
        assert stats["total_queries"] == 2
        assert stats["successful"] == 1
        assert stats["failed"] == 1
        assert len(stats["errors"]) == 1
        assert "Query failed" in stats["errors"][0]

        # Verify successful query is in cache
        assert cache.l1_cache.get("test:success") == {"result": "success"}

        # Verify failed query is not in cache
        assert cache.l1_cache.get("test:fail") is None

        await cache.close()


@pytest.mark.asyncio
async def test_warm_cache_empty_queries(mock_redis: AsyncMock) -> None:
    """Test cache warming with empty query list."""
    from discovery.cache import CacheManager

    cache = CacheManager(l1_max_size=100, l1_ttl=300)

    async def mock_from_url(*args, **kwargs):  # type: ignore[no-untyped-def]
        return mock_redis

    with patch("discovery.cache.aioredis.from_url", side_effect=mock_from_url):
        await cache.initialize()

        # Warm with empty list
        stats = await cache.warm_cache([])

        # Verify statistics
        assert stats["total_queries"] == 0
        assert stats["successful"] == 0
        assert stats["failed"] == 0
        assert len(stats["errors"]) == 0

        await cache.close()


@pytest.mark.asyncio
async def test_warm_cache_without_redis() -> None:
    """Test cache warming works with L1 only when Redis is unavailable."""
    from discovery.cache import CacheManager

    cache = CacheManager(l1_max_size=100, l1_ttl=300)

    # Don't initialize Redis

    async def query1() -> dict:  # type: ignore[type-arg]
        return {"result": "data1"}

    warming_queries = [{"query_func": query1, "cache_key": "test:key1", "ttl": 300}]

    # Warm cache - should still work with L1
    stats = await cache.warm_cache(warming_queries)

    # Verify statistics
    assert stats["total_queries"] == 1
    assert stats["successful"] == 1
    assert stats["failed"] == 0

    # Verify data is in L1 cache
    assert cache.l1_cache.get("test:key1") == {"result": "data1"}


@pytest.mark.asyncio
async def test_warm_cache_custom_ttls(mock_redis: AsyncMock) -> None:
    """Test cache warming with custom TTLs for different queries."""
    from discovery.cache import CacheManager

    cache = CacheManager(l1_max_size=100, l1_ttl=300, default_ttl=3600)

    async def mock_from_url(*args, **kwargs):  # type: ignore[no-untyped-def]
        return mock_redis

    with patch("discovery.cache.aioredis.from_url", side_effect=mock_from_url):
        await cache.initialize()

        async def query1() -> dict:  # type: ignore[type-arg]
            return {"result": "data1"}

        warming_queries = [
            {"query_func": query1, "cache_key": "test:short_ttl", "ttl": 60},
            {"query_func": query1, "cache_key": "test:long_ttl", "ttl": 7200},
            {"query_func": query1, "cache_key": "test:default_ttl"},  # No TTL specified
        ]

        # Warm cache
        stats = await cache.warm_cache(warming_queries)

        # Verify all succeeded
        assert stats["successful"] == 3
        assert stats["failed"] == 0

        # Verify setex was called with correct TTLs
        assert mock_redis.setex.call_count == 3

        await cache.close()


@pytest.mark.asyncio
async def test_create_cache_warming_queries() -> None:
    """Test creation of cache warming queries."""
    # Mock playground_api methods
    with patch("discovery.playground_api.playground_api") as mock_api:
        mock_api.search = AsyncMock(return_value=[])
        mock_api.get_trends = AsyncMock(return_value=[])
        mock_api.get_heatmap = AsyncMock(return_value=[])

        # Import after patching
        from discovery.discovery import _create_cache_warming_queries

        queries = await _create_cache_warming_queries()

        # Verify we got queries
        assert len(queries) > 0

        # Verify query structure
        for query in queries:
            assert "query_func" in query
            assert "cache_key" in query
            assert "ttl" in query
            assert callable(query["query_func"])
            assert isinstance(query["cache_key"], str)
            assert isinstance(query["ttl"], int)


@pytest.mark.asyncio
async def test_cache_warming_integration(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test cache warming integration in discovery service."""
    # This test verifies that the discovery service can start with cache warming
    # The fixture already initializes the service, so we just verify it's running
    response = discovery_client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


@pytest.mark.asyncio
async def test_cache_warming_disabled_by_config() -> None:
    """Test that cache warming can be disabled via configuration."""
    from common.config import DashboardConfig

    # Mock environment to disable cache warming
    with patch("common.config.getenv") as mock_getenv:
        # Setup mock to return values
        def getenv_side_effect(key: str, default: str | None = None) -> str | None:
            if key == "CACHE_WARMING_ENABLED":
                return "false"
            # Return defaults for required fields
            return default or "mock_value"

        mock_getenv.side_effect = getenv_side_effect

        # Reload config
        config = DashboardConfig.from_env()

        assert config.cache_warming_enabled is False


@pytest.mark.asyncio
async def test_cache_warming_enabled_by_default() -> None:
    """Test that cache warming is enabled by default."""
    from common.config import DashboardConfig

    # Mock environment without CACHE_WARMING_ENABLED
    with patch("common.config.getenv") as mock_getenv:
        # Setup mock to return defaults
        def getenv_side_effect(key: str, default: str | None = None) -> str | None:
            if key == "CACHE_WARMING_ENABLED":
                return default  # Returns "true"
            # Return defaults for required fields
            return default or "mock_value"

        mock_getenv.side_effect = getenv_side_effect

        # Reload config
        config = DashboardConfig.from_env()

        assert config.cache_warming_enabled is True


@pytest.mark.asyncio
async def test_cache_warming_returns_statistics(mock_redis: AsyncMock) -> None:
    """Test that cache warming returns detailed statistics."""
    from discovery.cache import CacheManager

    cache = CacheManager(l1_max_size=100, l1_ttl=300)

    async def mock_from_url(*args, **kwargs):  # type: ignore[no-untyped-def]
        return mock_redis

    with patch("discovery.cache.aioredis.from_url", side_effect=mock_from_url):
        await cache.initialize()

        async def query() -> dict:  # type: ignore[type-arg]
            return {"result": "data"}

        warming_queries = [
            {"query_func": query, "cache_key": "test:key1", "ttl": 300},
            {"query_func": query, "cache_key": "test:key2", "ttl": 300},
        ]

        # Warm cache
        stats = await cache.warm_cache(warming_queries)

        # Verify detailed statistics structure
        assert "total_queries" in stats
        assert "successful" in stats
        assert "failed" in stats
        assert "errors" in stats
        assert stats["total_queries"] == 2
        assert stats["successful"] == 2
        assert stats["failed"] == 0
        assert isinstance(stats["errors"], list)

        await cache.close()
