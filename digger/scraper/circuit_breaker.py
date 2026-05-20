"""Global circuit breaker for scrape outcomes.

In-memory rolling deque; suitable for single-worker M1 deployment.
The asyncio.Lock is lazily initialized to avoid binding to a stale event loop.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field

from digger.metrics import CIRCUIT_BREAKER_OPEN


@dataclass
class CircuitBreaker:
    """Rolling-window circuit breaker tracking scrape success/failure rates.

    Opens when the failure percentage within ``window_seconds`` meets or exceeds
    ``failure_pct`` (requires at least 10 events). Resets after ``cooldown_seconds``
    once a success is recorded.

    Args:
        window_seconds: Observation window for events.
        failure_pct: Failure threshold (0–100); ``>=`` comparison opens the breaker.
        cooldown_seconds: Seconds the breaker stays open before it can be reset.
    """

    window_seconds: int
    failure_pct: int  # 0-100; >= threshold opens
    cooldown_seconds: int
    _events: deque[tuple[float, bool]] = field(default_factory=deque)
    _opened_at: float | None = None
    _lock: asyncio.Lock | None = None  # lazy: never bind a loop at construct time

    async def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _evict_expired(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

    async def record(self, success: bool) -> None:
        """Record a scrape outcome and update the breaker state."""
        async with await self._get_lock():
            now = time.time()
            self._events.append((now, success))
            self._evict_expired(now)
            if self._opened_at is not None and success:
                if time.time() - self._opened_at >= self.cooldown_seconds:
                    self._opened_at = None
                    CIRCUIT_BREAKER_OPEN.set(0)
                return
            total = len(self._events)
            if total < 10:
                return
            failures = sum(1 for _, ok in self._events if not ok)
            if failures * 100 >= total * self.failure_pct and self._opened_at is None:
                self._opened_at = now
                CIRCUIT_BREAKER_OPEN.set(1)

    async def is_open(self) -> bool:
        """Return True if the circuit breaker is currently open."""
        async with await self._get_lock():
            if self._opened_at is None:
                return False
            if time.time() - self._opened_at >= self.cooldown_seconds:
                return False
            return True
