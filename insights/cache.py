"""Redis cache for precomputed insight results.

Uses cache-aside (lazy loading) pattern with configurable TTL.
All operations are safe — Redis failures fall through silently
so the service can always fall back to PostgreSQL.
"""

import json
from typing import Any

import structlog


logger = structlog.get_logger(__name__)


class InsightsCache:
    """Redis cache for precomputed insight results."""

    def __init__(self, redis: Any, ttl_seconds: int) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    async def get(self, key: str) -> dict[str, Any] | None:
        """Get cached value. Returns None on miss or Redis error."""
        try:
            raw = await self._redis.get(key)
            if raw is None:
                return None
            result: dict[str, Any] = json.loads(raw)
            return result
        except Exception:
            logger.debug("⚠️ Cache get failed, falling through to database", key=key)
            return None

    async def set(self, key: str, value: dict[str, Any]) -> None:
        """Cache a value with TTL. Silently fails if Redis is down."""
        try:
            await self._redis.set(key, json.dumps(value, default=str), ex=self._ttl)
        except Exception:
            logger.debug("⚠️ Cache set failed", key=key)

    async def invalidate_all(self) -> None:
        """Delete all insights:* keys using SCAN + DELETE (never KEYS *)."""
        try:
            cursor: str | int = "0"
            deleted = 0
            while True:
                cursor, keys = await self._redis.scan(cursor=int(cursor), match="insights:*", count=100)
                if keys:
                    await self._redis.delete(*keys)
                    deleted += len(keys)
                if cursor == 0:
                    break
            if deleted:
                logger.info("🔄 Cache invalidated", keys_deleted=deleted)
        except Exception:
            logger.debug("⚠️ Cache invalidation failed")
