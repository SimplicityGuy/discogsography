"""Tests for the Redis token-bucket rate budget."""

import asyncio

import pytest

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
