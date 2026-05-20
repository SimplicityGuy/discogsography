"""Composes queue runner, executor, rate budget, circuit breaker, and state loop.

scrape_loop — pops the next due release and scrapes it; respects rate budget
              and circuit breaker.
state_loop  — periodically recomputes next_scrape_due_at for all rows.
"""

from __future__ import annotations

import asyncio
import logging

from common.postgres_resilient import AsyncPostgreSQLPool
from digger.scraper.backoff import record_failure
from digger.scraper.circuit_breaker import CircuitBreaker
from digger.scraper.executor import ScrapeExecutor
from digger.scraper.queue_runner import pop_next_due
from digger.scraper.rate_budget import RateBudget
from digger.scraper.state_recomputer import refresh_all_due_times

log = logging.getLogger(__name__)


async def scrape_loop(
    *,
    pool: AsyncPostgreSQLPool,
    executor: ScrapeExecutor,
    rate: RateBudget,
    breaker: CircuitBreaker,
    stop_event: asyncio.Event,
) -> None:
    """Main scraper loop.  Runs until *stop_event* is set.

    Each iteration:
    1. Checks the circuit breaker (sleeps 30 s when open).
    2. Acquires a rate-budget token.
    3. Pops the next due release from the queue (inside a transaction).
    4. Scrapes it and records the outcome; on failure, bumps the retry counter.
    """
    while not stop_event.is_set():
        if await breaker.is_open():
            log.warning("⚡ circuit breaker open — sleeping 30s")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=30)
            except asyncio.TimeoutError:
                pass
            continue

        await rate.acquire()

        release_id: int | None = None
        async with pool.connection() as conn:
            await conn.set_autocommit(False)
            async with conn.transaction():
                async with conn.cursor() as cur:
                    release_id = await pop_next_due(cur)

        if release_id is None:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=2)
            except asyncio.TimeoutError:
                pass
            continue

        ok = await executor.scrape_release(release_id)
        await breaker.record(success=ok)
        if not ok:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await record_failure(cur, release_id)


async def state_loop(
    *,
    pool: AsyncPostgreSQLPool,
    stop_event: asyncio.Event,
    interval_seconds: int = 60,
) -> None:
    """Periodically recomputes next_scrape_due_at for all rows.

    Runs until *stop_event* is set.
    """
    while not stop_event.is_set():
        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    updated = await refresh_all_due_times(cur)
            log.info("🔄 state recompute updated %d rows", updated)
        except Exception:
            log.exception("⚠️ state recompute failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            pass
