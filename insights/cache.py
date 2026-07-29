"""Redis cache for precomputed insight results.

Uses cache-aside (lazy loading) with a **generation-versioned key namespace**.
All operations are safe — Redis failures fall through silently so the service
can always fall back to PostgreSQL.

Why a generation, not a plain DELETE
------------------------------------
Cache-aside is a read-then-populate pair with an unbounded gap between the two
(the endpoint reads Postgres, exits the connection context — a real cooperative
scheduling yield — then serialises and writes to Redis). The scheduler
concurrently does DELETE+INSERT in a transaction and then invalidates.

With a plain SCAN+DELETE invalidation the two can interleave as:

1. endpoint reads the OLD rows from Postgres,
2. scheduler commits the NEW rows and invalidates the cache,
3. endpoint's ``set`` lands — writing the stale result *after* the invalidation.

That stale entry then survives with TTL = ``schedule_hours`` (24h by default)
and is served to every subsequent request until the *next* cycle's
invalidation, masking freshly computed data for a full day.

Versioning the namespace removes the race instead of narrowing it. Every key is
written as ``insights:g{generation}:...``, and the scheduler bumps the
generation on invalidation. A request captures the generation *before* its
database read, so a request that straddles a recompute writes into the OLD
generation's namespace — which nobody reads any more — while readers arriving
after the bump miss cleanly and repopulate from the new data. There is no
ordering requirement between the endpoint's ``set`` and the scheduler's
invalidation at all.
"""

import json
from typing import Any

import structlog


logger = structlog.get_logger(__name__)

# The monotonically increasing cache generation.
#
# Deliberately OUTSIDE the "insights:*" namespace: invalidate_all scans and
# deletes that namespace, and deleting the generation counter would roll the
# namespace back to g0 and resurrect keys from an earlier generation.
GENERATION_KEY = "insights-generation"

# Only generation-scoped keys belong to this cache. Scanning "insights:*" would
# also sweep the API service's own "insights:data-completeness" entry (a 6h
# cache) when both services share a Redis.
_VERSIONED_KEY_PATTERN = "insights:g*"


class InsightsCache:
    """Redis cache for precomputed insight results, keyed by generation."""

    def __init__(self, redis: Any, ttl_seconds: int) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    @staticmethod
    def versioned_key(key: str, generation: int) -> str:
        """Return ``key`` rewritten into ``generation``'s namespace.

        Accepts keys with or without the legacy ``insights:`` prefix so call
        sites can keep using their existing cache-key strings.
        """
        suffix = key.removeprefix("insights:")
        return f"insights:g{generation}:{suffix}"

    async def generation(self) -> int:
        """Return the current cache generation.

        Callers MUST read this *before* their database read, and pass the same
        value to both :meth:`get` and :meth:`set`, so a request that straddles a
        recompute writes to the generation it actually read from.

        Returns ``0`` when the counter is unset or Redis is unavailable.
        """
        try:
            raw = await self._redis.get(GENERATION_KEY)
            if raw is None:
                return 0
            return int(raw)
        except Exception:
            logger.debug("⚠️ Cache generation read failed, using generation 0")
            return 0

    async def get(self, key: str, generation: int) -> dict[str, Any] | None:
        """Get a cached value from ``generation``. Returns None on miss or Redis error."""
        try:
            raw = await self._redis.get(self.versioned_key(key, generation))
            if raw is None:
                return None
            result: dict[str, Any] = json.loads(raw)
            return result
        except Exception:
            logger.debug("⚠️ Cache get failed, falling through to database", key=key)
            return None

    async def set(self, key: str, value: dict[str, Any], generation: int) -> None:
        """Cache a value in ``generation`` with TTL. Silently fails if Redis is down.

        Writing into a superseded generation is harmless by construction: those
        keys are unreachable and expire on their own.
        """
        try:
            await self._redis.set(
                self.versioned_key(key, generation),
                json.dumps(value, default=str),
                ex=self._ttl,
            )
        except Exception:
            logger.debug("⚠️ Cache set failed", key=key)

    async def invalidate_all(self) -> None:
        """Retire the current generation and reclaim its keys.

        Bumping the generation is what actually invalidates: it happens
        atomically (INCR) and takes effect for every subsequent reader
        immediately. The SCAN+DELETE that follows is only housekeeping to free
        memory sooner than the TTL would; keys belonging to the new generation
        are deliberately skipped, since a request may already have populated
        them from freshly committed data.
        """
        try:
            generation = int(await self._redis.incr(GENERATION_KEY))
        except Exception:
            logger.warning("⚠️ Cache generation bump failed — cache may serve stale data until TTL")
            return

        logger.info("🔄 Cache generation advanced", generation=generation)

        current_prefix = f"insights:g{generation}:"
        try:
            cursor: str | int = "0"
            deleted = 0
            while True:
                cursor, keys = await self._redis.scan(cursor=int(cursor), match=_VERSIONED_KEY_PATTERN, count=100)
                stale = [k for k in keys if not _as_str(k).startswith(current_prefix)]
                if stale:
                    await self._redis.delete(*stale)
                    deleted += len(stale)
                if int(cursor) == 0:
                    break
            if deleted:
                logger.info("🔄 Cache invalidated", keys_deleted=deleted, generation=generation)
        except Exception:
            # Non-fatal: the generation bump already invalidated the cache.
            logger.debug("⚠️ Cache key reclamation failed")


def _as_str(key: Any) -> str:
    """Normalise a Redis key to str (clients may return bytes)."""
    return key.decode() if isinstance(key, bytes) else str(key)
