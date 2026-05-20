"""Tests for the Redis token-bucket rate budget."""

import asyncio
from unittest.mock import patch

import pytest
from redis.exceptions import WatchError

from digger.scraper.rate_budget import RateBudget


@pytest.mark.asyncio
async def test_rate_budget_allows_burst_then_throttles(redis_test_client):
    rb = RateBudget(redis=redis_test_client, capacity=5, refill_per_second=0.0)
    for _ in range(5):
        wait = await rb.acquire()
        assert wait == 0.0
    wait = await rb.peek()
    assert wait > 0.0  # exhausted, no refill


@pytest.mark.asyncio
async def test_rate_budget_refills_over_time(redis_test_client):
    # Generous refill rate + sleep so the net refill comfortably exceeds 1 token,
    # keeping the test robust under CI scheduling jitter.
    rb = RateBudget(redis=redis_test_client, capacity=2, refill_per_second=20.0)
    await rb.acquire()
    await rb.acquire()
    await asyncio.sleep(0.3)
    wait = await rb.peek()
    assert wait <= 0.5


@pytest.mark.asyncio
async def test_rate_budget_peek_returns_inf_when_no_refill(redis_test_client) -> None:
    """peek() returns inf when the bucket is empty and refill_per_second == 0 (line 59)."""
    rb = RateBudget(redis=redis_test_client, capacity=1, refill_per_second=0.0)
    await rb.acquire()  # drain the single token
    wait = await rb.peek()
    assert wait == float("inf")


@pytest.mark.asyncio
async def test_rate_budget_peek_returns_seconds_when_partially_empty(redis_test_client) -> None:
    """peek() returns a positive finite wait when tokens < 1 and refill_per_second > 0 (line 60)."""
    rb = RateBudget(redis=redis_test_client, capacity=1, refill_per_second=1.0)
    await rb.acquire()  # drain
    wait = await rb.peek()
    # With refill_per_second=1.0 and ~0 tokens, wait ≈ 1.0 (but slightly less due to elapsed time)
    assert 0.0 < wait <= 1.0


@pytest.mark.asyncio
async def test_rate_budget_acquire_raises_on_no_refill_exhausted(redis_test_client) -> None:
    """acquire() raises RuntimeError when bucket is empty with no refill rate (lines 80-81)."""
    rb = RateBudget(redis=redis_test_client, capacity=1, refill_per_second=0.0)
    await rb.acquire()  # drain the single token
    with pytest.raises(RuntimeError, match="exhausted"):
        await rb.acquire()


@pytest.mark.asyncio
async def test_rate_budget_acquire_sleeps_and_retries_with_refill(redis_test_client) -> None:
    """acquire() sleeps and accumulates wait time when bucket is empty but has refill (lines 82-84)."""
    rb = RateBudget(redis=redis_test_client, capacity=1, refill_per_second=100.0)
    await rb.acquire()  # drain
    # After draining, acquire() must sleep until 1 token refills.
    # With refill_per_second=100.0 the wait is ~0.01 s — fast enough for a unit test.
    total_wait = await rb.acquire()
    assert total_wait > 0.0, "total_wait should be positive after sleeping"


@pytest.mark.asyncio
async def test_rate_budget_acquire_retries_on_watch_error(redis_test_client) -> None:
    """acquire() retries transparently when a WatchError is raised (lines 77-79 continue branch)."""
    # RateBudget uses slots=True so we cannot patch instance attributes directly.
    # Instead we patch _read_and_refill on the class for the duration of this test.
    call_count = 0
    original_read = RateBudget._read_and_refill  # type: ignore[attr-defined]

    async def _maybe_raise(self: RateBudget, pipe: object) -> tuple[float, float]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise WatchError("simulated contention")
        return await original_read(self, pipe)

    with patch.object(RateBudget, "_read_and_refill", new=_maybe_raise):
        rb = RateBudget(redis=redis_test_client, capacity=5, refill_per_second=0.0)
        wait = await rb.acquire()

    assert wait == 0.0  # eventually succeeded
    assert call_count >= 2  # first call raised, second succeeded
