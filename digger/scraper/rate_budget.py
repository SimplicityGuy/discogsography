"""Redis-backed token bucket via optimistic concurrency.

Uses WATCH/MULTI/EXEC instead of Lua scripts. Suitable for the single-worker
deployment in M1 and scales to multi-worker via the same mechanism.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from redis.asyncio import Redis
from redis.exceptions import WatchError

from digger.metrics import RATE_BUDGET_REMAINING

KEY_TOKENS = "digger:rate_budget:tokens"
KEY_LAST = "digger:rate_budget:last_refill"


@dataclass(slots=True)
class RateBudget:
    """Token bucket rate limiter backed by Redis.

    Args:
        redis: An async Redis client.
        capacity: Maximum number of tokens in the bucket.
        refill_per_second: Tokens added per second (0.0 = no refill).
    """

    redis: Redis
    capacity: int
    refill_per_second: float

    async def _read_and_refill(self, pipe: object) -> tuple[float, float]:
        """Inside an open WATCH block, compute the refilled token count and current timestamp."""
        now = time.time()
        tokens_raw = await pipe.get(KEY_TOKENS)  # type: ignore[attr-defined]
        last_raw = await pipe.get(KEY_LAST)  # type: ignore[attr-defined]
        tokens = float(tokens_raw) if tokens_raw is not None else float(self.capacity)
        last = float(last_raw) if last_raw is not None else now
        if self.refill_per_second > 0:
            tokens = min(
                float(self.capacity), tokens + (now - last) * self.refill_per_second
            )
        return tokens, now

    async def peek(self) -> float:
        """Return seconds to wait until at least 1 token is available (0 if ready)."""
        async with self.redis.pipeline(transaction=True) as pipe:
            await pipe.watch(KEY_TOKENS, KEY_LAST)
            tokens, _ = await self._read_and_refill(pipe)
            await pipe.unwatch()
        RATE_BUDGET_REMAINING.set(tokens)
        if tokens >= 1.0:
            return 0.0
        if self.refill_per_second <= 0:
            return float("inf")
        return (1.0 - tokens) / self.refill_per_second

    async def acquire(self) -> float:
        """Block until a token is available, then consume it. Returns total wait time in seconds."""
        total_wait = 0.0
        while True:
            async with self.redis.pipeline(transaction=True) as pipe:
                try:
                    await pipe.watch(KEY_TOKENS, KEY_LAST)
                    tokens, now = await self._read_and_refill(pipe)
                    if tokens >= 1.0:
                        pipe.multi()
                        await pipe.set(KEY_TOKENS, tokens - 1.0)
                        await pipe.set(KEY_LAST, now)
                        await pipe.execute()
                        RATE_BUDGET_REMAINING.set(tokens - 1.0)
                        return total_wait
                    await pipe.unwatch()
                except WatchError:
                    continue
            if self.refill_per_second <= 0:
                raise RuntimeError("Rate budget exhausted with no refill rate")
            wait = (1.0 - tokens) / self.refill_per_second
            await asyncio.sleep(wait)
            total_wait += wait
