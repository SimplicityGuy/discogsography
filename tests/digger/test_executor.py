"""Tests for digger.scraper.executor.ScrapeExecutor.

Real transactional behaviour (upsert+soft-delete correctness against a live DB,
SKIP LOCKED ordering) is deferred to the M1 e2e smoke (Task 28).  These tests
use a mock pool/connection/cursor to verify the correct SQL is issued and that
the deterministic placeholder seller_id is stable across calls.
"""

from __future__ import annotations

from decimal import Decimal
import hashlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from digger.scraper.executor import ScrapeExecutor, _placeholder_seller_id
from digger.scraper.types import ParsedListing


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_listing(**kwargs: object) -> ParsedListing:
    defaults: dict[str, object] = {
        "listing_id": 1001,
        "release_id": 99,
        "seller_username": "alice",
        "seller_id": None,
        "price_value": Decimal("12.00"),
        "price_currency": "USD",
        "media_condition": "NM",
        "sleeve_condition": "NM",
        "comments": None,
        "posted_at": None,
    }
    defaults.update(kwargs)
    return ParsedListing(**defaults)  # type: ignore[arg-type]


def _make_pool(fetchone_return: object = None) -> tuple[MagicMock, AsyncMock, AsyncMock]:
    """Build a mock pool -> conn -> cursor chain.

    Returns (pool, conn, cursor).
    """
    cursor = AsyncMock()
    cursor.__aenter__ = AsyncMock(return_value=cursor)
    cursor.__aexit__ = AsyncMock(return_value=False)
    cursor.execute = AsyncMock()
    cursor.fetchone = AsyncMock(return_value=fetchone_return)
    cursor.rowcount = 0

    conn = AsyncMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    conn.set_autocommit = AsyncMock()
    conn.cursor = MagicMock(return_value=cursor)
    # transaction() is an async context manager
    tx = AsyncMock()
    tx.__aenter__ = AsyncMock(return_value=tx)
    tx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx)

    pool = MagicMock()
    pool.connection = MagicMock(return_value=conn)

    return pool, conn, cursor


# ---------------------------------------------------------------------------
# _placeholder_seller_id — stable, deterministic, negative
# ---------------------------------------------------------------------------


def test_placeholder_seller_id_is_negative() -> None:
    assert _placeholder_seller_id("alice") < 0


def test_placeholder_seller_id_is_stable() -> None:
    assert _placeholder_seller_id("alice") == _placeholder_seller_id("alice")


def test_placeholder_seller_id_differs_by_username() -> None:
    assert _placeholder_seller_id("alice") != _placeholder_seller_id("bob")


def test_placeholder_seller_id_matches_blake2b() -> None:
    username = "testuser"
    expected = -int.from_bytes(hashlib.blake2b(username.encode(), digest_size=7).digest(), "big")
    assert _placeholder_seller_id(username) == expected


# ---------------------------------------------------------------------------
# scrape_release — HTTP error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scrape_release_returns_false_on_429() -> None:
    pool, _, _ = _make_pool()
    http = AsyncMock()
    http.get = AsyncMock(return_value=MagicMock(status_code=429))
    exe = ScrapeExecutor(http_client=http, pool=pool)
    assert await exe.scrape_release(1) is False


@pytest.mark.asyncio
async def test_scrape_release_returns_false_on_5xx() -> None:
    pool, _, _ = _make_pool()
    http = AsyncMock()
    http.get = AsyncMock(return_value=MagicMock(status_code=503))
    exe = ScrapeExecutor(http_client=http, pool=pool)
    assert await exe.scrape_release(1) is False


@pytest.mark.asyncio
async def test_scrape_release_returns_false_on_non_200() -> None:
    pool, _, _ = _make_pool()
    http = AsyncMock()
    http.get = AsyncMock(return_value=MagicMock(status_code=404))
    exe = ScrapeExecutor(http_client=http, pool=pool)
    assert await exe.scrape_release(1) is False


# ---------------------------------------------------------------------------
# scrape_release — happy path: correct SQL is issued
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scrape_release_upserts_listing_and_updates_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies the SQL sequence for a single new listing from a new seller."""
    release_id = 99
    listing = _make_listing(release_id=release_id)

    pool, conn, cursor = _make_pool(fetchone_return=None)  # seller not in DB

    monkeypatch.setattr(
        "digger.scraper.executor.parse_listings",
        lambda _html, _rid: [listing],
    )
    http = AsyncMock()
    http.get = AsyncMock(return_value=MagicMock(status_code=200, text="<html/>"))

    exe = ScrapeExecutor(http_client=http, pool=pool)
    result = await exe.scrape_release(release_id)

    assert result is True
    conn.set_autocommit.assert_awaited_once_with(False)

    calls = cursor.execute.call_args_list
    # 1st call: SELECT seller_id FROM digger.sellers WHERE username = %s
    assert "SELECT seller_id" in calls[0][0][0]
    # 2nd call: INSERT INTO digger.sellers ... ON CONFLICT ... DO NOTHING
    assert "INSERT INTO digger.sellers" in calls[1][0][0]
    # 3rd call: INSERT INTO digger.listings ... ON CONFLICT ... DO UPDATE
    assert "INSERT INTO digger.listings" in calls[2][0][0]
    # 4th call: soft-delete (UPDATE ... != ALL(%s))
    assert "!= ALL(%s)" in calls[3][0][0] or "removed_at" in calls[3][0][0]
    # 5th call: update scrape state — must set next_scrape_due_at so the queue
    # runner does not immediately re-pop and re-scrape this release.
    state_sql = calls[4][0][0]
    assert "release_scrape_state" in state_sql
    assert "next_scrape_due_at" in state_sql
    assert "last_scraped_at" in state_sql
    assert "consecutive_failures" in state_sql


@pytest.mark.asyncio
async def test_scrape_release_soft_deletes_vanished_listings(monkeypatch: pytest.MonkeyPatch) -> None:
    """When parse_listings returns [], the soft-delete runs without the != ALL clause."""
    release_id = 77

    pool, _conn, cursor = _make_pool(fetchone_return=None)

    monkeypatch.setattr(
        "digger.scraper.executor.parse_listings",
        lambda _html, _rid: [],
    )
    http = AsyncMock()
    http.get = AsyncMock(return_value=MagicMock(status_code=200, text=""))

    exe = ScrapeExecutor(http_client=http, pool=pool)
    result = await exe.scrape_release(release_id)

    assert result is True
    calls = [c[0][0] for c in cursor.execute.call_args_list]
    # Only the blanket soft-delete + state update (no seller/listing upserts)
    delete_sql = next((s for s in calls if "removed_at" in s and "release_scrape_state" not in s), None)
    assert delete_sql is not None
    assert "!= ALL" not in delete_sql


@pytest.mark.asyncio
async def test_scrape_release_uses_existing_seller_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the seller already exists, no INSERT INTO sellers is issued."""
    release_id = 55
    existing_seller_id = 12345
    listing = _make_listing(release_id=release_id)

    pool, _conn, cursor = _make_pool(fetchone_return=(existing_seller_id,))

    monkeypatch.setattr(
        "digger.scraper.executor.parse_listings",
        lambda _html, _rid: [listing],
    )
    http = AsyncMock()
    http.get = AsyncMock(return_value=MagicMock(status_code=200, text=""))

    exe = ScrapeExecutor(http_client=http, pool=pool)
    await exe.scrape_release(release_id)

    calls = [c[0][0] for c in cursor.execute.call_args_list]
    assert not any("INSERT INTO digger.sellers" in s for s in calls), "Should not insert seller when one already exists"


@pytest.mark.asyncio
async def test_placeholder_id_used_in_listing_insert(monkeypatch: pytest.MonkeyPatch) -> None:
    """The deterministic placeholder seller_id is passed to the listing INSERT."""
    release_id = 11
    listing = _make_listing(release_id=release_id, seller_username="newuser")

    pool, _conn, cursor = _make_pool(fetchone_return=None)

    monkeypatch.setattr(
        "digger.scraper.executor.parse_listings",
        lambda _html, _rid: [listing],
    )
    http = AsyncMock()
    http.get = AsyncMock(return_value=MagicMock(status_code=200, text=""))

    exe = ScrapeExecutor(http_client=http, pool=pool)
    await exe.scrape_release(release_id)

    # Find the listing INSERT call
    listing_insert_call = next(c for c in cursor.execute.call_args_list if "INSERT INTO digger.listings" in c[0][0])
    params = listing_insert_call[0][1]
    expected_placeholder = _placeholder_seller_id("newuser")
    assert params[2] == expected_placeholder  # seller_id is 3rd positional param


# ---------------------------------------------------------------------------
# scrape_release — UnknownLayoutError path (lines 61-64)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scrape_release_returns_false_on_unknown_layout(monkeypatch: pytest.MonkeyPatch) -> None:
    """When parse_listings raises UnknownLayoutError, scrape_release returns False."""
    from digger.scraper.listing_parser import UnknownLayoutError

    def _raise_unknown(_html: str, _rid: int) -> list[ParsedListing]:
        raise UnknownLayoutError("bad layout")

    pool, _, _ = _make_pool()
    http = AsyncMock()
    http.get = AsyncMock(return_value=MagicMock(status_code=200, text="<html/>"))

    monkeypatch.setattr("digger.scraper.executor.parse_listings", _raise_unknown)
    exe = ScrapeExecutor(http_client=http, pool=pool)
    result = await exe.scrape_release(42)
    assert result is False


# ---------------------------------------------------------------------------
# scrape_release — generic Exception path (lines 68-71)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scrape_release_returns_false_on_http_exception() -> None:
    """When http.get raises an arbitrary exception, scrape_release returns False."""
    pool, _, _ = _make_pool()
    http = AsyncMock()
    http.get = AsyncMock(side_effect=RuntimeError("network dead"))

    exe = ScrapeExecutor(http_client=http, pool=pool)
    result = await exe.scrape_release(99)
    assert result is False


# ---------------------------------------------------------------------------
# _persist — duplicate seller dedup (line 91: `continue` branch)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scrape_release_deduplicates_seller_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two listings from the same seller only issue one SELECT for that seller."""
    release_id = 200
    listing_a = _make_listing(listing_id=2001, release_id=release_id, seller_username="shared_seller")
    listing_b = _make_listing(listing_id=2002, release_id=release_id, seller_username="shared_seller")

    pool, _conn, cursor = _make_pool(fetchone_return=None)

    monkeypatch.setattr(
        "digger.scraper.executor.parse_listings",
        lambda _html, _rid: [listing_a, listing_b],
    )
    http = AsyncMock()
    http.get = AsyncMock(return_value=MagicMock(status_code=200, text=""))

    exe = ScrapeExecutor(http_client=http, pool=pool)
    await exe.scrape_release(release_id)

    # Only one SELECT per seller — the second listing hits the `continue` branch
    select_calls = [c for c in cursor.execute.call_args_list if "SELECT seller_id" in c[0][0]]
    assert len(select_calls) == 1, f"Expected 1 SELECT for the shared seller, got {len(select_calls)}"
