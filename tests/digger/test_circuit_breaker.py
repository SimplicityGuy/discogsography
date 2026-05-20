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


@pytest.mark.asyncio
async def test_circuit_breaker_is_open_returns_false_after_cooldown_elapsed() -> None:
    """is_open returns False when cooldown has elapsed even without a record() call (line 73)."""
    cb = CircuitBreaker(window_seconds=60, failure_pct=30, cooldown_seconds=1)
    for _ in range(10):
        await cb.record(success=False)
    assert await cb.is_open() is True
    # Wait for the cooldown to elapse without calling record()
    await asyncio.sleep(1.1)
    # is_open itself should now return False (hits line 73 branch: elapsed >= cooldown)
    assert await cb.is_open() is False


@pytest.mark.asyncio
async def test_circuit_breaker_success_during_cooldown_does_not_close() -> None:
    """A success recorded while still in cooldown resets _opened_at only after cooldown (line 46 branch)."""
    cb = CircuitBreaker(window_seconds=60, failure_pct=30, cooldown_seconds=10)
    for _ in range(10):
        await cb.record(success=False)
    assert await cb.is_open() is True
    # Record a success immediately — cooldown has NOT elapsed (line 54-58 branch returns early)
    await cb.record(success=True)
    # Still open because cooldown hasn't elapsed
    assert await cb.is_open() is True


@pytest.mark.asyncio
async def test_circuit_breaker_evicts_expired_events() -> None:
    """Events older than window_seconds are evicted when a new event is recorded (line 46: popleft)."""
    # Use a 1-second window so events recorded a moment ago expire quickly.
    cb = CircuitBreaker(window_seconds=1, failure_pct=50, cooldown_seconds=60)
    # Record 5 failures within the window — not enough to trip (needs >= 10 events).
    for _ in range(5):
        await cb.record(success=False)
    # Wait for the window to expire then record one more event.
    # The _evict_expired call inside record() will call popleft() for each stale entry.
    await asyncio.sleep(1.05)
    await cb.record(success=True)
    # After eviction only the fresh event remains; < 10 events → breaker not open.
    assert await cb.is_open() is False
