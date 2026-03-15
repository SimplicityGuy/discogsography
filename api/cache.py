"""Redis cache for recommendation results.

Uses cache-aside pattern with configurable TTL per key type.
All operations are safe — Redis failures fall through silently.
"""

import json
from typing import Any

import structlog


logger = structlog.get_logger(__name__)


class RecommendCache:
    """Redis cache for recommendation and similarity results."""

    def __init__(self, redis: Any, default_ttl: int = 3600) -> None:
        self._redis = redis
        self._default_ttl = default_ttl

    async def get(self, key: str) -> dict[str, Any] | None:
        """Get cached value. Returns None on miss or Redis error."""
        try:
            raw = await self._redis.get(key)
            if raw is None:
                return None
            result: dict[str, Any] = json.loads(raw)
            return result
        except Exception:
            logger.debug("Cache get failed", key=key)
            return None

    async def set(self, key: str, value: dict[str, Any], ttl: int | None = None) -> None:
        """Cache a value with TTL. Silently fails if Redis is down."""
        try:
            await self._redis.set(key, json.dumps(value, default=str), ex=ttl or self._default_ttl)
        except Exception:
            logger.debug("Cache set failed", key=key)

    async def invalidate_user(self, user_id: str) -> None:
        """Delete user-scoped recommendation cache keys via SCAN."""
        patterns = [
            f"recommend:explore:{user_id}:*",
            f"recommend:enhanced:{user_id}",
        ]
        try:
            for pattern in patterns:
                cursor: str | int = "0"
                while True:
                    cursor, keys = await self._redis.scan(cursor=int(cursor), match=pattern, count=100)
                    if keys:
                        await self._redis.delete(*keys)
                    if cursor == 0:
                        break
        except Exception:
            logger.debug("Cache invalidation failed", user_id=user_id)
