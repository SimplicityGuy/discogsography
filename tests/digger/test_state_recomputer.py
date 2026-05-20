"""Tests for digger.scraper.state_recomputer.

Pure-logic tests for compute_next_scrape_due() and BASE_INTERVALS run without
any database.  Mock-cursor test for refresh_all_due_times() verifies the SQL
is issued and the rowcount is returned.

Real transactional behaviour against a live DB is deferred to the M1 e2e smoke
(Task 28).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from digger.scraper.state_recomputer import BASE_INTERVALS, compute_next_scrape_due, refresh_all_due_times


# ---------------------------------------------------------------------------
# BASE_INTERVALS
# ---------------------------------------------------------------------------


def test_base_intervals_match_spec() -> None:
    assert BASE_INTERVALS["must"] == timedelta(days=7)
    assert BASE_INTERVALS["nice"] == timedelta(days=14)
    assert BASE_INTERVALS["eventually"] == timedelta(days=28)


# ---------------------------------------------------------------------------
# compute_next_scrape_due — pure-logic tests
# ---------------------------------------------------------------------------


def test_no_churn_returns_base_interval() -> None:
    last = datetime(2026, 1, 1, tzinfo=UTC)
    nxt = compute_next_scrape_due(last, "must", listings_delta_7d=0)
    assert nxt - last == timedelta(days=7)


def test_high_churn_shortens_interval() -> None:
    last = datetime(2026, 1, 1, tzinfo=UTC)
    nxt = compute_next_scrape_due(last, "must", listings_delta_7d=50)
    assert nxt - last < timedelta(days=7)


def test_clamped_at_half_base() -> None:
    last = datetime(2026, 1, 1, tzinfo=UTC)
    nxt = compute_next_scrape_due(last, "must", listings_delta_7d=10_000)
    assert nxt - last >= timedelta(days=7) * 0.5


def test_clamped_at_one_and_a_half_base() -> None:
    """Negative delta (not normally possible, but defensive) clamps to 1.5x."""
    last = datetime(2026, 1, 1, tzinfo=UTC)
    nxt = compute_next_scrape_due(last, "must", listings_delta_7d=-999)
    assert nxt - last <= timedelta(days=7) * 1.5


def test_nice_tier_uses_14_day_base() -> None:
    last = datetime(2026, 1, 1, tzinfo=UTC)
    nxt = compute_next_scrape_due(last, "nice", listings_delta_7d=0)
    assert nxt - last == timedelta(days=14)


def test_eventually_tier_uses_28_day_base() -> None:
    last = datetime(2026, 1, 1, tzinfo=UTC)
    nxt = compute_next_scrape_due(last, "eventually", listings_delta_7d=0)
    assert nxt - last == timedelta(days=28)


# ---------------------------------------------------------------------------
# refresh_all_due_times — mock cursor test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_all_due_times_executes_update_and_returns_rowcount() -> None:
    cur = AsyncMock()
    cur.execute = AsyncMock()
    cur.rowcount = 7

    result = await refresh_all_due_times(cur)

    cur.execute.assert_awaited_once()
    executed_sql: str = cur.execute.call_args[0][0]
    assert "UPDATE digger.release_scrape_state" in executed_sql
    assert "next_scrape_due_at" in executed_sql
    assert result == 7
