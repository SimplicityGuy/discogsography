"""Cost + concurrency guardrails for the digger agent.

``TokenBudget`` enforces a per-user, per-kind (interactive/scheduled) daily
token cap using a Redis counter keyed by the UTC date. ``ConcurrencyLock``
limits each user to one in-flight agent stream via a Redis ``SET NX`` lock.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING
import uuid


if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import AsyncIterator

    from redis.asyncio import Redis


# 36h: comfortably covers a UTC day plus slack so a key never expires mid-day.
_TOKEN_KEY_TTL_SECONDS = 60 * 60 * 36


def _today_utc() -> str:
    return datetime.now(UTC).date().isoformat()


class TokenBudget:
    """Per-user daily token counter, scoped by ``kind`` (interactive/scheduled)."""

    def __init__(self, *, redis: Redis, daily_cap: int, kind: str) -> None:
        self._redis = redis
        self._cap = daily_cap
        self._kind = kind

    def _key(self, user_id: uuid.UUID) -> str:
        return f"digger:tokens:{self._kind}:{user_id}:{_today_utc()}"

    async def record(self, user_id: uuid.UUID, *, input_tokens: int, output_tokens: int) -> int:
        """Add this turn's tokens to today's counter and return the new total."""
        key = self._key(user_id)
        total = await self._redis.incrby(key, input_tokens + output_tokens)
        await self._redis.expire(key, _TOKEN_KEY_TTL_SECONDS)
        return int(total)

    async def remaining(self, user_id: uuid.UUID) -> int:
        """Return tokens left under the cap today (floored at zero)."""
        used = int(await self._redis.get(self._key(user_id)) or 0)
        return max(0, self._cap - used)

    async def is_exceeded(self, user_id: uuid.UUID) -> bool:
        """True once the user has reached or passed the daily cap."""
        return await self.remaining(user_id) == 0


class ConcurrencyLock:
    """One in-flight agent stream per user, enforced with a Redis ``SET NX`` lock."""

    def __init__(self, *, redis: Redis, ttl_seconds: int = 300) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    def _key(self, user_id: uuid.UUID) -> str:
        return f"digger:agent_lock:{user_id}"

    @asynccontextmanager
    async def acquire(self, user_id: uuid.UUID) -> AsyncIterator[str]:
        """Acquire the per-user lock, raising RuntimeError if one is already held."""
        token = uuid.uuid4().hex
        ok = await self._redis.set(self._key(user_id), token, nx=True, ex=self._ttl)
        if not ok:
            raise RuntimeError("another agent session is already running for this user")
        try:
            yield token
        finally:
            # Release only if we still own the lock (guards against TTL takeover).
            current = await self._redis.get(self._key(user_id))
            cur_str = current.decode() if isinstance(current, bytes) else current
            if cur_str == token:
                await self._redis.delete(self._key(user_id))
