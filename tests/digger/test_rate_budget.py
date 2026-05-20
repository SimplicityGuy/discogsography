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
    rb = RateBudget(redis=redis_test_client, capacity=2, refill_per_second=10.0)
    await rb.acquire()
    await rb.acquire()
    await asyncio.sleep(0.25)
    wait = await rb.peek()
    assert wait == 0.0
