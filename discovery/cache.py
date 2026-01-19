"""Two-level caching module for Discovery service (L1: in-memory, L2: Redis)."""

from collections import OrderedDict
from collections.abc import Callable
import hashlib
import json
import logging
import time
from typing import Any, TypedDict

import orjson
from redis import asyncio as aioredis
from redis.exceptions import RedisError

from common import get_config
from discovery.metrics import cache_hits, cache_misses, cache_size


logger = logging.getLogger(__name__)


class CacheWarmingStats(TypedDict):
    """Type definition for cache warming statistics."""

    total_queries: int
    successful: int
    failed: int
    errors: list[str]


class LRUCache:
    """Simple in-memory LRU cache with TTL support."""

    def __init__(self, max_size: int = 1000, default_ttl: int = 300) -> None:
        """Initialize LRU cache.

        Args:
            max_size: Maximum number of items in cache
            default_ttl: Default time-to-live in seconds (5 minutes)
        """
        self.max_size = max_size
        self.default_ttl = default_ttl
        self.cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()  # key -> (value, expiry_time)

    def get(self, key: str) -> Any | None:
        """Get value from cache if not expired.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found or expired
        """
        if key not in self.cache:
            return None

        value, expiry = self.cache[key]

        # Check if expired
        if time.time() > expiry:
            del self.cache[key]
            return None

        # Move to end (most recently used)
        self.cache.move_to_end(key)
        return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Set value in cache with TTL.

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time-to-live in seconds (uses default if None)
        """
        expiry = time.time() + (ttl or self.default_ttl)

        # Remove oldest if at capacity
        if len(self.cache) >= self.max_size and key not in self.cache:
            self.cache.popitem(last=False)  # Remove oldest (FIFO)

        self.cache[key] = (value, expiry)
        self.cache.move_to_end(key)

    def delete(self, key: str) -> bool:
        """Delete key from cache.

        Args:
            key: Cache key

        Returns:
            True if key was deleted, False if not found
        """
        if key in self.cache:
            del self.cache[key]
            return True
        return False

    def clear(self) -> None:
        """Clear all entries from cache."""
        self.cache.clear()

    def size(self) -> int:
        """Get current cache size (number of items)."""
        return len(self.cache)

    def evict_expired(self) -> int:
        """Remove all expired entries.

        Returns:
            Number of entries evicted
        """
        current_time = time.time()
        expired_keys = [key for key, (_, expiry) in self.cache.items() if current_time > expiry]

        for key in expired_keys:
            del self.cache[key]

        return len(expired_keys)


class CacheManager:
    """Manages two-level caching (L1: in-memory LRU, L2: Redis) for the Discovery service."""

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        default_ttl: int = 3600,
        key_prefix: str = "discovery:",
        l1_max_size: int = 1000,
        l1_ttl: int = 300,
    ) -> None:
        """Initialize the two-level cache manager.

        Args:
            redis_url: Redis connection URL
            default_ttl: Default TTL in seconds for L2 (1 hour)
            key_prefix: Prefix for all cache keys
            l1_max_size: Maximum number of items in L1 cache
            l1_ttl: Default TTL in seconds for L1 cache (5 minutes)
        """
        self.redis_url = redis_url
        self.default_ttl = default_ttl
        self.key_prefix = key_prefix
        self.redis: aioredis.Redis | None = None
        self.connected = False

        # L1 in-memory cache
        self.l1_cache = LRUCache(max_size=l1_max_size, default_ttl=l1_ttl)
        logger.info(f"📦 L1 cache initialized with max_size={l1_max_size}, ttl={l1_ttl}s")

    async def initialize(self) -> None:
        """Initialize Redis connection."""
        try:
            self.redis = await aioredis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=False,  # We'll handle decoding ourselves for orjson
                max_connections=10,
            )
            # Test connection
            await self.redis.ping()
            self.connected = True
            logger.info("🔄 Redis cache connected successfully")
        except (RedisError, OSError) as e:
            logger.warning(f"⚠️ Redis connection failed: {e}. Running without cache.")
            self.connected = False

    async def close(self) -> None:
        """Close Redis connection."""
        if self.redis:
            await self.redis.close()
            logger.info("🔄 Redis cache connection closed")

    async def update_cache_size_metrics(self) -> None:
        """Update cache size metrics for Prometheus."""
        if not self.connected or not self.redis:
            return

        try:
            # Get memory usage info
            info = await self.redis.info("memory")
            used_memory = info.get("used_memory", 0)

            # Update cache size metric
            cache_size.labels(cache_name="redis").set(used_memory)
            logger.debug(f"📊 Cache size updated: {used_memory} bytes")
        except Exception as e:
            logger.error(f"❌ Cache size metric update error: {e}")

    async def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with cache statistics including hits, misses, size
        """
        if not self.connected or not self.redis:
            return {
                "connected": False,
                "keys": 0,
                "memory_used": 0,
                "hit_rate": 0.0,
            }

        try:
            # Get Redis info
            info = await self.redis.info()

            # Count keys with our prefix
            key_count = 0
            async for _ in self.redis.scan_iter(match=f"{self.key_prefix}*"):
                key_count += 1

            return {
                "connected": True,
                "keys": key_count,
                "memory_used": info.get("used_memory", 0),
                "memory_human": info.get("used_memory_human", "0B"),
                "uptime_seconds": info.get("uptime_in_seconds", 0),
            }
        except Exception as e:
            logger.error(f"❌ Cache stats error: {e}")
            return {
                "connected": False,
                "error": str(e),
            }

    def _make_key(self, key: str) -> str:
        """Create a namespaced cache key."""
        return f"{self.key_prefix}{key}"

    @staticmethod
    def _serialize_value(value: Any) -> bytes:
        """Serialize value using orjson for performance."""
        return orjson.dumps(value)

    @staticmethod
    def _deserialize_value(data: bytes) -> Any:
        """Deserialize value using orjson."""
        return orjson.loads(data)

    async def get(self, key: str) -> Any | None:
        """Get value from two-level cache (L1 -> L2).

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found

        Cache lookup strategy:
            1. Check L1 (in-memory) cache first
            2. If L1 miss, check L2 (Redis) cache
            3. If found in L2, populate L1
            4. If miss in both, return None
        """
        # Try L1 cache first (fastest)
        l1_value = self.l1_cache.get(key)
        if l1_value is not None:
            cache_hits.labels(cache_key="l1_" + key.split(":")[0]).inc()
            logger.debug(f"📦 L1 cache hit: {key}")
            return l1_value

        # L1 miss - try L2 (Redis)
        if not self.connected or not self.redis:
            cache_misses.labels(cache_key="l2_disconnected").inc()
            return None

        try:
            cache_key = self._make_key(key)
            data = await self.redis.get(cache_key)

            if data:
                # L2 hit - populate L1 and return
                value = self._deserialize_value(data)
                self.l1_cache.set(key, value)  # Warm L1 cache
                cache_hits.labels(cache_key="l2_" + key.split(":")[0]).inc()
                logger.debug(f"🔄 L2 cache hit, warming L1: {key}")
                return value

            # Miss in both caches
            cache_misses.labels(cache_key=key.split(":")[0]).inc()
            logger.debug(f"❌ Cache miss (L1+L2): {key}")
            return None

        except Exception as e:
            cache_misses.labels(cache_key="error").inc()
            logger.error(f"❌ Cache get error: {e}")
            return None

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """Set value in two-level cache (L1 and L2).

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time to live in seconds (uses default if None)

        Returns:
            True if successful, False otherwise

        Cache write strategy:
            1. Write to L1 cache immediately (fast in-memory)
            2. Write to L2 (Redis) if connected
            3. Use shorter TTL for L1 (default_ttl from LRUCache)
            4. Use longer TTL for L2 (default_ttl from CacheManager)
        """
        # Always write to L1 cache (in-memory, always available)
        l1_ttl = self.l1_cache.default_ttl  # Shorter TTL for L1 (5 minutes)
        self.l1_cache.set(key, value, ttl=l1_ttl)
        logger.debug(f"📦 L1 cache set: {key} (TTL: {l1_ttl}s)")

        # Write to L2 (Redis) if connected
        if not self.connected or not self.redis:
            return True  # L1 write succeeded, L2 unavailable

        try:
            cache_key = self._make_key(key)
            data = self._serialize_value(value)
            l2_ttl = ttl or self.default_ttl  # Longer TTL for L2 (1 hour)
            await self.redis.setex(cache_key, l2_ttl, data)
            logger.debug(f"🔄 L2 cache set: {key} (TTL: {l2_ttl}s)")
            return True
        except Exception as e:
            logger.error(f"❌ L2 cache set error: {e}")
            return True  # L1 write succeeded, L2 failed but not critical

    async def delete(self, key: str) -> bool:
        """Delete value from two-level cache (L1 and L2).

        Args:
            key: Cache key

        Returns:
            True if deleted from at least one cache level, False otherwise

        Cache invalidation strategy:
            1. Delete from L1 cache first (synchronous, fast)
            2. Delete from L2 (Redis) if connected
            3. Return True if deleted from either level
        """
        # Delete from L1 cache first
        l1_deleted = self.l1_cache.delete(key)
        if l1_deleted:
            logger.debug(f"📦 L1 cache deleted: {key}")

        # Delete from L2 (Redis) if connected
        if not self.connected or not self.redis:
            return l1_deleted  # Return L1 result if L2 unavailable

        try:
            cache_key = self._make_key(key)
            l2_result = await self.redis.delete(cache_key)
            l2_deleted = bool(l2_result)
            if l2_deleted:
                logger.debug(f"🔄 L2 cache deleted: {key}")
            return l1_deleted or l2_deleted
        except Exception as e:
            logger.error(f"❌ L2 cache delete error: {e}")
            return l1_deleted  # Return L1 result if L2 failed

    async def clear_pattern(self, pattern: str) -> int:
        """Clear all keys matching a pattern from both cache levels.

        Args:
            pattern: Key pattern (e.g., "search:*")

        Returns:
            Number of keys deleted from both L1 and L2

        Cache clearing strategy:
            1. Clear matching keys from L1 cache (simple pattern matching)
            2. Clear matching keys from L2 (Redis) if connected
            3. Return total count deleted from both levels
        """
        import re

        # Convert glob pattern to regex for L1 matching
        # e.g., "search:*" -> "^search:.*$"
        regex_pattern = "^" + pattern.replace("*", ".*").replace("?", ".") + "$"
        regex = re.compile(regex_pattern)

        # Clear matching keys from L1 cache
        l1_deleted = 0
        matching_keys = [key for key in self.l1_cache.cache if regex.match(key)]
        for key in matching_keys:
            if self.l1_cache.delete(key):
                l1_deleted += 1

        if l1_deleted > 0:
            logger.debug(f"📦 L1 cache cleared {l1_deleted} keys matching: {pattern}")

        # Clear from L2 (Redis) if connected
        l2_deleted = 0
        if self.connected and self.redis:
            try:
                full_pattern = self._make_key(pattern)
                keys = []
                async for key in self.redis.scan_iter(match=full_pattern):
                    keys.append(key)

                if keys:
                    l2_deleted = await self.redis.delete(*keys)
                    logger.debug(f"🔄 L2 cache cleared {l2_deleted} keys matching: {pattern}")
            except Exception as e:
                logger.error(f"❌ L2 cache clear error: {e}")

        total_deleted = l1_deleted + l2_deleted
        if total_deleted > 0:
            logger.info(f"📊 Cleared {total_deleted} total cache keys matching: {pattern} (L1: {l1_deleted}, L2: {l2_deleted})")

        return total_deleted

    def cache_key_for_params(self, prefix: str, **params: Any) -> str:
        """Generate a cache key from parameters.

        Args:
            prefix: Key prefix (e.g., "search", "graph")
            **params: Parameters to include in key

        Returns:
            Cache key string
        """
        # Sort params for consistent keys
        sorted_params = sorted(params.items())
        param_str = json.dumps(sorted_params, sort_keys=True)
        # Using MD5 for cache key generation only - not for security purposes
        param_hash = hashlib.md5(param_str.encode()).hexdigest()[:8]  # nosec B324  # noqa: S324
        return f"{prefix}:{param_hash}"

    async def warm_cache(self, warming_queries: list[dict[str, Any]]) -> CacheWarmingStats:
        """Warm the cache with frequently accessed data.

        Args:
            warming_queries: List of queries to execute for cache warming
                Each query should have:
                - query_func: Async function to execute
                - cache_key: Cache key to store result under
                - ttl: Optional TTL in seconds

        Returns:
            Dictionary with warming statistics

        Cache warming strategy:
            1. Execute each query function
            2. Store results in both L1 and L2 caches
            3. Track success/failure for each query
            4. Return statistics for monitoring
        """
        stats: CacheWarmingStats = {
            "total_queries": len(warming_queries),
            "successful": 0,
            "failed": 0,
            "errors": [],
        }

        logger.info(f"🔥 Cache warming started with {len(warming_queries)} queries")

        for query_config in warming_queries:
            try:
                query_func = query_config["query_func"]
                cache_key = query_config["cache_key"]
                ttl = query_config.get("ttl")

                # Execute query
                result = await query_func()

                # Store in cache
                success = await self.set(cache_key, result, ttl)

                if success:
                    stats["successful"] += 1
                    logger.debug(f"🔥 Warmed cache key: {cache_key}")
                else:
                    stats["failed"] += 1
                    logger.warning(f"⚠️ Failed to warm cache key: {cache_key}")

            except Exception as e:
                stats["failed"] += 1
                error_msg = f"Cache warming error for {query_config.get('cache_key', 'unknown')}: {e}"
                stats["errors"].append(error_msg)
                logger.error(f"❌ {error_msg}")

        logger.info(f"✅ Cache warming completed: {stats['successful']} successful, {stats['failed']} failed out of {stats['total_queries']} total")

        return stats


# Decorator for caching async functions
def cached(
    prefix: str,
    ttl: int | None = None,
    key_func: Callable[..., str] | None = None,
) -> Callable:
    """Decorator for caching async function results.

    Args:
        prefix: Cache key prefix
        ttl: Time to live in seconds
        key_func: Custom function to generate cache key from args

    Returns:
        Decorated function
    """

    def decorator(func: Callable) -> Callable:
        async def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            # Check if cache manager is available
            cache_manager = getattr(self, "cache", None)
            if not cache_manager or not cache_manager.connected:
                return await func(self, *args, **kwargs)

            # Generate cache key
            cache_key = key_func(*args, **kwargs) if key_func else cache_manager.cache_key_for_params(prefix, args=args, kwargs=kwargs)

            # Try to get from cache
            cached_value = await cache_manager.get(cache_key)
            if cached_value is not None:
                return cached_value

            # Execute function and cache result
            result = await func(self, *args, **kwargs)
            await cache_manager.set(cache_key, result, ttl)
            return result

        return wrapper

    return decorator


# Global cache manager instance with configuration
def _get_cache_manager() -> CacheManager:
    """Get cache manager with configuration."""
    config = get_config()
    return CacheManager(redis_url=config.redis_url)


cache_manager = _get_cache_manager()


# Cache configuration for different data types
CACHE_TTL = {
    "search": 3600,  # 1 hour
    "graph": 1800,  # 30 minutes
    "journey": 3600,  # 1 hour
    "trends": 7200,  # 2 hours
    "heatmap": 7200,  # 2 hours
    "artist_details": 3600,  # 1 hour
    "recommendations": 1800,  # 30 minutes
    "analytics": 3600,  # 1 hour
}
