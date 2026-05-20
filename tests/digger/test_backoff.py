"""Tests for digger.scraper.backoff.

Pure-logic tests for next_retry_delay() run without any database.
Mock-cursor test for record_failure() verifies the correct UPDATE SQL is issued.

Real transactional behaviour against a live DB is deferred to the M1 e2e smoke
(Task 28).
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

from digger.scraper.backoff import MAX_BACKOFF, next_retry_delay, record_failure


# ---------------------------------------------------------------------------
# next_retry_delay — pure-logic tests
# ---------------------------------------------------------------------------


def test_exponential_growth() -> None:
    assert next_retry_delay(0) == timedelta(hours=1)
    assert next_retry_delay(1) == timedelta(hours=2)
    assert next_retry_delay(2) == timedelta(hours=4)
    assert next_retry_delay(3) == timedelta(hours=8)


def test_capped_at_24h() -> None:
    assert next_retry_delay(10) == timedelta(hours=24)
    assert next_retry_delay(100) == MAX_BACKOFF


def test_max_backoff_is_24h() -> None:
    assert timedelta(hours=24) == MAX_BACKOFF


def test_zero_failures_returns_one_hour() -> None:
    assert next_retry_delay(0) == timedelta(hours=1)


# ---------------------------------------------------------------------------
# record_failure — mock cursor test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_failure_issues_update_sql() -> None:
    cur = AsyncMock()
    cur.execute = AsyncMock()

    await record_failure(cur, release_id=42)

    cur.execute.assert_awaited_once()
    sql: str = cur.execute.call_args[0][0]
    params: tuple = cur.execute.call_args[0][1]
    assert "UPDATE digger.release_scrape_state" in sql
    assert "consecutive_failures" in sql
    assert "next_retry_at" in sql
    assert params == (42,)


@pytest.mark.asyncio
async def test_record_failure_sql_uses_power_for_backoff() -> None:
    cur = AsyncMock()
    cur.execute = AsyncMock()

    await record_failure(cur, release_id=1)

    sql: str = cur.execute.call_args[0][0]
    assert "power(2, consecutive_failures)" in sql
