"""Tests for digger.scraper.queue_runner.

Structural tests verify SQL content (FOR UPDATE SKIP LOCKED, tier ordering).
Mock-DB tests verify pop_next_due() returns the id from fetchone().

Real transactional ordering (SKIP LOCKED under concurrent workers, true
priority-tier precedence against a live DB) is deferred to the M1 e2e smoke
(Task 28).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from digger.scraper.queue_runner import POP_SQL, pop_next_due


# ---------------------------------------------------------------------------
# Structural tests — POP_SQL content
# ---------------------------------------------------------------------------


def test_pop_sql_contains_skip_locked() -> None:
    assert "FOR UPDATE SKIP LOCKED" in POP_SQL


def test_pop_sql_orders_must_first() -> None:
    assert "WHEN 'must' THEN 1" in POP_SQL


def test_pop_sql_orders_nice_second() -> None:
    assert "WHEN 'nice' THEN 2" in POP_SQL


def test_pop_sql_orders_eventually_last() -> None:
    # eventually maps to ELSE 3 in the CASE expression
    assert "ELSE 3" in POP_SQL


def test_pop_sql_filters_by_next_scrape_due_at() -> None:
    assert "next_scrape_due_at <= now()" in POP_SQL


def test_pop_sql_filters_next_retry_at() -> None:
    assert "next_retry_at IS NULL OR next_retry_at <= now()" in POP_SQL


def test_pop_sql_limits_to_one() -> None:
    assert "LIMIT 1" in POP_SQL


# ---------------------------------------------------------------------------
# pop_next_due — mock cursor tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pop_next_due_returns_id_from_fetchone() -> None:
    cur = AsyncMock()
    cur.execute = AsyncMock()
    cur.fetchone = AsyncMock(return_value=(42,))

    result = await pop_next_due(cur)

    cur.execute.assert_awaited_once()
    assert result == 42


@pytest.mark.asyncio
async def test_pop_next_due_returns_none_when_queue_empty() -> None:
    cur = AsyncMock()
    cur.execute = AsyncMock()
    cur.fetchone = AsyncMock(return_value=None)

    result = await pop_next_due(cur)

    assert result is None


@pytest.mark.asyncio
async def test_pop_next_due_executes_pop_sql() -> None:
    """pop_next_due must execute POP_SQL (or a normalised equivalent)."""
    cur = AsyncMock()
    cur.execute = AsyncMock()
    cur.fetchone = AsyncMock(return_value=None)

    await pop_next_due(cur)

    executed_sql: str = cur.execute.call_args[0][0]
    assert "FOR UPDATE SKIP LOCKED" in executed_sql
