"""Opportunistic refresh: write priority bumps and subscribe to worker progress.

API -> Postgres: set ``next_scrape_due_at = now()`` for stale releases so the
worker picks them up on its next iteration.
Worker -> Redis: publishes per-scrape progress to ``digger:refresh:{user_id}``
(see the scheduler layer); this class consumes those events.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from typing import Any

    import redis.asyncio as aioredis

    from common import AsyncPostgreSQLPool


log = logging.getLogger(__name__)


class RefreshCoordinator:
    """Coordinates opportunistic listing refreshes for the recommend flow."""

    def __init__(self, *, pool: AsyncPostgreSQLPool | None, redis: aioredis.Redis) -> None:
        self._pool = pool
        self._redis = redis

    async def bump_priorities(self, release_ids: list[int]) -> int:
        """Mark releases due now so the worker re-scrapes them; returns rows updated."""
        if not release_ids:
            return 0
        if self._pool is None:
            raise RuntimeError("RefreshCoordinator requires a pool to bump priorities")
        async with self._pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                "UPDATE digger.release_scrape_state SET next_scrape_due_at = now() WHERE release_id = ANY(%s)",
                (release_ids,),
            )
            return cur.rowcount

    async def subscribe_progress(self, user_id: str, *, deadline_seconds: float) -> AsyncIterator[dict[str, Any]]:
        """Yield refresh-progress events for a user until the deadline elapses."""
        channel = f"digger:refresh:{user_id}"
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel)
        try:
            loop = asyncio.get_running_loop()
            end = loop.time() + deadline_seconds
            while True:
                remaining = end - loop.time()
                if remaining <= 0:
                    return
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=remaining)
                if msg is None:
                    continue
                try:
                    data = json.loads(msg["data"])
                except (ValueError, TypeError):
                    continue
                yield data
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
