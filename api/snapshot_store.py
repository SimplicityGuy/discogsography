"""Redis-backed snapshot store with native TTL for graph state persistence."""

from datetime import UTC, datetime, timedelta
import os
import secrets
from typing import Any

import orjson
import redis.asyncio as aioredis


class SnapshotTooLargeError(ValueError):
    """Raised when a snapshot's serialized payload exceeds the size cap."""


class SnapshotQuotaExceededError(ValueError):
    """Raised when a user already has too many active (non-expired) snapshots."""


class SnapshotStore:
    """Redis-backed store for graph snapshots with native TTL eviction."""

    _KEY_PREFIX = "snapshot:"
    _USER_COUNT_KEY_PREFIX = "snapshot:usercount:"

    def __init__(
        self,
        redis_client: aioredis.Redis,
        ttl_days: int | None = None,
        max_nodes: int | None = None,
        max_payload_bytes: int | None = None,
        max_per_user: int | None = None,
    ) -> None:
        self._redis = redis_client
        self._ttl_days: int = ttl_days if ttl_days is not None else int(os.environ.get("SNAPSHOT_TTL_DAYS", "28"))
        self._max_nodes: int = max_nodes if max_nodes is not None else int(os.environ.get("SNAPSHOT_MAX_NODES", "100"))
        # Node-count alone doesn't bound per-node string size (SnapshotNode.id/type
        # are now Field(max_length=...) too, but this is a second, independent
        # backstop on the whole serialized payload — discogsography-cu2.110).
        self._max_payload_bytes: int = (
            max_payload_bytes if max_payload_bytes is not None else int(os.environ.get("SNAPSHOT_MAX_PAYLOAD_BYTES", str(64 * 1024)))
        )
        # Caps the number of live (non-expired) snapshots a single user can
        # accumulate, so looping POST /api/snapshot can't mint unbounded
        # 28-day-TTL Redis keys even with small, valid payloads.
        self._max_per_user: int = max_per_user if max_per_user is not None else int(os.environ.get("SNAPSHOT_MAX_PER_USER", "50"))
        self._ttl_seconds: int = self._ttl_days * 86400

    @property
    def ttl_days(self) -> int:
        return self._ttl_days

    @property
    def max_nodes(self) -> int:
        return self._max_nodes

    @property
    def max_payload_bytes(self) -> int:
        return self._max_payload_bytes

    @property
    def max_per_user(self) -> int:
        return self._max_per_user

    async def save(self, nodes: list[dict[str, Any]], center: dict[str, Any], user_id: str | None = None) -> tuple[str, datetime]:
        """Save a snapshot and return (token, expires_at).

        Raises:
            ValueError: if ``nodes`` exceeds ``max_nodes``. The API router also
                pre-checks this (for a friendlier error message), but this guard
                protects any direct caller of SnapshotStore that bypasses the
                router — e.g. scripts or future reuse.
            SnapshotTooLargeError: if the serialized payload exceeds
                ``max_payload_bytes``.
            SnapshotQuotaExceededError: if *user_id* has already reached
                ``max_per_user`` live snapshots.
        """
        if len(nodes) > self._max_nodes:
            raise ValueError(f"Too many nodes: {len(nodes)} exceeds maximum of {self._max_nodes}")
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
        if len(payload) > self._max_payload_bytes:
            raise SnapshotTooLargeError(f"Snapshot payload is {len(payload)} bytes, maximum is {self._max_payload_bytes}")

        if user_id:
            count_key = f"{self._USER_COUNT_KEY_PREFIX}{user_id}"
            count = await self._redis.incr(count_key)
            # Self-healing TTL: `nx=True` means "set the TTL only if the key
            # doesn't already have one." Normally a no-op after the first
            # save. Previously this was gated on `count == 1` — a ONE-SHOT
            # opportunity per key generation — so if that single EXPIRE call
            # failed or the process died between incr and expire, the counter
            # was left permanent (no TTL, never re-armed by any later save),
            # silently converting "live snapshots in a 28-day window" into
            # "lifetime saves, forever" and eventually locking the user out
            # permanently (discogsography-7639). `nx=True` makes every save a
            # chance to arm a missing TTL, not just the first.
            await self._redis.expire(count_key, self._ttl_seconds, nx=True)
            if count > self._max_per_user:
                await self._redis.decr(count_key)
                raise SnapshotQuotaExceededError(f"User already has {count - 1} snapshots, maximum is {self._max_per_user}")

            try:
                await self._redis.set(f"{self._KEY_PREFIX}{token}", payload, ex=self._ttl_seconds)
            except Exception:
                # Compensate: the save didn't happen, so the quota slot it
                # reserved above must be freed — mirrors the decrement on the
                # quota-exceeded path. Without this, a transient Redis/network
                # failure on this specific call permanently burns the user's
                # quota with zero live snapshots to show for it.
                await self._redis.decr(count_key)
                raise
        else:
            await self._redis.set(f"{self._KEY_PREFIX}{token}", payload, ex=self._ttl_seconds)

        return token, expires_at

    async def load(self, token: str) -> dict[str, Any] | None:
        """Load a snapshot by token, returning None if not found or expired."""
        raw = await self._redis.get(f"{self._KEY_PREFIX}{token}")
        if raw is None:
            return None
        result: dict[str, Any] = orjson.loads(raw)
        return result
