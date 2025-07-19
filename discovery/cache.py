"""Redis caching module for Discovery service."""

import hashlib
import json
import logging
from collections.abc import Callable
from typing import Any

import orjson
from common import get_config
from redis import asyncio as aioredis
from redis.exceptions import RedisError


logger = logging.getLogger(__name__)


class CacheManager:
    """Manages Redis caching for the Discovery service."""

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        default_ttl: int = 3600,
        key_prefix: str = "discovery:",
    ) -> None:
        """Initialize the cache manager.

        Args:
            redis_url: Redis connection URL
            default_ttl: Default TTL in seconds (1 hour)
            key_prefix: Prefix for all cache keys
        """
        self.redis_url = redis_url
        self.default_ttl = default_ttl
        self.key_prefix = key_prefix
        self.redis: aioredis.Redis | None = None
        self.connected = False

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
        """Get value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found
        """
        if not self.connected or not self.redis:
            return None

        try:
            cache_key = self._make_key(key)
            data = await self.redis.get(cache_key)
            if data:
                logger.debug(f"📊 Cache hit: {key}")
                return self._deserialize_value(data)
            logger.debug(f"📊 Cache miss: {key}")
            return None
        except Exception as e:
            logger.error(f"❌ Cache get error: {e}")
            return None

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """Set value in cache.

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time to live in seconds (uses default if None)

        Returns:
            True if successful, False otherwise
        """
        if not self.connected or not self.redis:
            return False

        try:
            cache_key = self._make_key(key)
            data = self._serialize_value(value)
            ttl = ttl or self.default_ttl
            await self.redis.setex(cache_key, ttl, data)
            logger.debug(f"📊 Cache set: {key} (TTL: {ttl}s)")
            return True
        except Exception as e:
            logger.error(f"❌ Cache set error: {e}")
            return False

    async def delete(self, key: str) -> bool:
        """Delete value from cache.

        Args:
            key: Cache key

        Returns:
            True if deleted, False otherwise
        """
        if not self.connected or not self.redis:
            return False

        try:
            cache_key = self._make_key(key)
            result = await self.redis.delete(cache_key)
            logger.debug(f"📊 Cache delete: {key}")
            return bool(result)
        except Exception as e:
            logger.error(f"❌ Cache delete error: {e}")
            return False

    async def clear_pattern(self, pattern: str) -> int:
        """Clear all keys matching a pattern.

        Args:
            pattern: Key pattern (e.g., "search:*")

        Returns:
            Number of keys deleted
        """
        if not self.connected or not self.redis:
            return 0

        try:
            full_pattern = self._make_key(pattern)
            keys = []
            async for key in self.redis.scan_iter(match=full_pattern):
                keys.append(key)

            if keys:
                deleted = await self.redis.delete(*keys)
                logger.info(f"📊 Cleared {deleted} cache keys matching: {pattern}")
                return int(deleted)
            return 0
        except Exception as e:
            logger.error(f"❌ Cache clear error: {e}")
            return 0

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
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                # Default key generation from all args/kwargs
                cache_key = cache_manager.cache_key_for_params(prefix, args=args, kwargs=kwargs)

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
