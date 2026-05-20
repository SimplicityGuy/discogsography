"""Tests for the global circuit breaker."""

import asyncio

import pytest

from digger.scraper.circuit_breaker import CircuitBreaker


@pytest.mark.asyncio
async def test_circuit_breaker_opens_above_threshold():
    cb = CircuitBreaker(window_seconds=60, failure_pct=30, cooldown_seconds=10)
    for _ in range(7):
        await cb.record(success=True)
    for _ in range(3):
        await cb.record(success=False)
    assert await cb.is_open() is True


@pytest.mark.asyncio
async def test_circuit_breaker_closes_after_cooldown():
    cb = CircuitBreaker(window_seconds=60, failure_pct=30, cooldown_seconds=1)
    for _ in range(10):
        await cb.record(success=False)
    assert await cb.is_open() is True
    await asyncio.sleep(1.1)
    await cb.record(success=True)
    assert await cb.is_open() is False
