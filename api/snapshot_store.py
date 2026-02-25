"""Redis-backed snapshot store with native TTL for graph state persistence."""

from datetime import UTC, datetime, timedelta
import os
import secrets
from typing import Any

import orjson
import redis.asyncio as aioredis


class SnapshotStore:
    """Redis-backed store for graph snapshots with native TTL eviction."""

    _KEY_PREFIX = "snapshot:"

    def __init__(
        self,
        redis_client: aioredis.Redis,
        ttl_days: int | None = None,
        max_nodes: int | None = None,
    ) -> None:
        self._redis = redis_client
        self._ttl_days: int = ttl_days if ttl_days is not None else int(os.environ.get("SNAPSHOT_TTL_DAYS", "28"))
        self._max_nodes: int = max_nodes if max_nodes is not None else int(os.environ.get("SNAPSHOT_MAX_NODES", "100"))
        self._ttl_seconds: int = self._ttl_days * 86400

    @property
    def ttl_days(self) -> int:
        return self._ttl_days

    @property
    def max_nodes(self) -> int:
        return self._max_nodes

    async def save(self, nodes: list[dict[str, Any]], center: dict[str, Any]) -> tuple[str, datetime]:
        """Save a snapshot and return (token, expires_at)."""
        token = secrets.token_urlsafe(12)
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=self._ttl_seconds)
        payload = orjson.dumps(
            {
                "nodes": nodes,
                "center": center,
                "created_at": now.isoformat(),
            }
        )
        await self._redis.set(f"{self._KEY_PREFIX}{token}", payload, ex=self._ttl_seconds)
        return token, expires_at

    async def load(self, token: str) -> dict[str, Any] | None:
        """Load a snapshot by token, returning None if not found or expired."""
        raw = await self._redis.get(f"{self._KEY_PREFIX}{token}")
        if raw is None:
            return None
        result: dict[str, Any] = orjson.loads(raw)
        return result
