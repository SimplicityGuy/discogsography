"""Tests for digger.scheduler.runner.

The runner fetches a user's wantlist snapshot over HTTP (the API's internal
contract), reads scraped listings/sellers directly from the worker's Postgres
pool, runs the deterministic optimizer, and persists a digger.reports row while
advancing the user's schedule.

All I/O is faked: HTTP via respx, Postgres via lightweight async stubs (plain
classes to avoid MagicMock recursion on Python 3.13/3.14). The optimizer runs
for real on tiny inputs.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock
import uuid

import httpx
import pytest
import respx

from common.digger_optimizer import pareto_bundles
from common.digger_optimizer.models import Listing, OptimizerInput, OptimizerOutput, ReleaseConstraint, Seller
from digger.scheduler.runner import (
    _compute_change_flag,
    fetch_wantlist_snapshot,
    run_scheduled_for_user,
)


_API_BASE = "http://api:8004"
_SERVICE_TOKEN = "test-service-token"  # not a real secret — S105 is ignored for tests


# ---------------------------------------------------------------------------
# Fake Postgres pool — routes fetch results by the most recent SQL
# ---------------------------------------------------------------------------


class _ACM:
    def __init__(self, value: object) -> None:
        self._value = value

    async def __aenter__(self) -> object:
        return self._value

    async def __aexit__(self, *_: object) -> bool:
        return False


class _FakeCursor:
    def __init__(self, *, listings: list[dict[str, Any]], sellers: list[dict[str, Any]], last_report: dict[str, Any] | None) -> None:
        self._listings = listings
        self._sellers = sellers
        self._last_report = last_report
        self.executed: list[tuple[str, Any]] = []
        self._last_sql = ""

    async def execute(self, sql: str, params: Any = None) -> None:
        self._last_sql = sql
        self.executed.append((sql, params))

    async def fetchall(self) -> list[dict[str, Any]]:
        if "FROM digger.listings" in self._last_sql:
            return self._listings
        if "FROM digger.sellers" in self._last_sql:
            return self._sellers
        return []

    async def fetchone(self) -> dict[str, Any] | None:
        if "FROM digger.reports" in self._last_sql:
            return self._last_report
        return None


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor
        self.autocommit_calls: list[bool] = []

    def cursor(self, *_args: object, **_kwargs: object) -> _ACM:
        return _ACM(self._cursor)

    async def set_autocommit(self, value: bool) -> None:
        self.autocommit_calls.append(value)

    def transaction(self) -> _ACM:
        return _ACM(None)


class _FakePool:
    def __init__(
        self,
        *,
        listings: list[dict[str, Any]] | None = None,
        sellers: list[dict[str, Any]] | None = None,
        last_report: dict[str, Any] | None = None,
    ) -> None:
        self.cursor = _FakeCursor(listings=listings or [], sellers=sellers or [], last_report=last_report)
        self.conn = _FakeConn(self.cursor)

    def connection(self) -> _ACM:
        return _ACM(self.conn)


def _executed_sql(pool: _FakePool) -> list[str]:
    return [sql for sql, _ in pool.cursor.executed]


def _insert_params(pool: _FakePool) -> tuple[Any, ...]:
    return next(params for sql, params in pool.cursor.executed if "INSERT INTO digger.reports" in sql)


# ---------------------------------------------------------------------------
# fetch_wantlist_snapshot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_wantlist_snapshot_calls_internal_endpoint() -> None:
    user_id = uuid.UUID("00000000-0000-0000-0000-0000000000b1")
    with respx.mock(base_url="http://api:8004") as mock:
        route = mock.get(f"/api/internal/digger/wantlist-snapshot/{user_id}").mock(
            return_value=httpx.Response(200, json={"user_id": str(user_id), "must": [], "nice": [], "eventually": []})
        )
        result = await fetch_wantlist_snapshot("http://api:8004", "tok-123", user_id)

    assert route.called
    assert route.calls.last.request.headers["X-Service-Token"] == "tok-123"
    assert result["user_id"] == str(user_id)


@pytest.mark.asyncio
async def test_fetch_wantlist_snapshot_raises_on_error_status() -> None:
    user_id = uuid.uuid4()
    with respx.mock(base_url="http://api:8004") as mock:
        mock.get(f"/api/internal/digger/wantlist-snapshot/{user_id}").mock(return_value=httpx.Response(500))
        with pytest.raises(httpx.HTTPStatusError):
            await fetch_wantlist_snapshot("http://api:8004", "tok", user_id)


# ---------------------------------------------------------------------------
# _compute_change_flag
# ---------------------------------------------------------------------------


def _single_listing_output() -> OptimizerOutput:
    inp = OptimizerInput(
        user_id=uuid.uuid4(),
        location="US",
        currency="USD",
        must_have_releases=[ReleaseConstraint(release_id=1, min_media_condition="VG", min_sleeve_condition="VG")],
        candidate_listings=[
            Listing(
                listing_id=101,
                release_id=1,
                seller_id=11,
                price_value=Decimal("10.00"),
                price_currency="USD",
                media_condition="NM",
                sleeve_condition="NM",
            )
        ],
        sellers={11: Seller(seller_id=11, region="us", country_code="US")},
    )
    return pareto_bundles(inp)


def _prior_report(listing_ids: tuple[int, ...]) -> dict[str, Any]:
    return {"bundles": [{"seller_orders": [{"listings": [{"listing_id": lid} for lid in listing_ids]}]}]}


def test_change_flag_first_run_when_no_prior_report() -> None:
    out = _single_listing_output()
    assert _compute_change_flag(None, out) == "first_run"


def test_change_flag_none_for_small_difference() -> None:
    out = _single_listing_output()  # current listing ids == {101}
    prior = _prior_report((101, 9001, 9002))  # symmetric diff == {9001, 9002} -> 2 < 3
    assert _compute_change_flag(prior, out) == "none"


def test_change_flag_significant_at_threshold() -> None:
    out = _single_listing_output()  # current listing ids == {101}
    prior = _prior_report((9001, 9002, 9003))  # symmetric diff == {101, 9001, 9002, 9003} -> >= 3
    assert _compute_change_flag(prior, out) == "significant"


# ---------------------------------------------------------------------------
# run_scheduled_for_user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_scheduled_persists_report_and_advances_schedule(monkeypatch: pytest.MonkeyPatch) -> None:
    user_id = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
    snapshot = {
        "user_id": str(user_id),
        "must": [{"release_id": 1, "min_media_condition": "VG", "min_sleeve_condition": "VG", "max_price_cents": None}],
        "nice": [],
        "eventually": [],
    }
    monkeypatch.setattr("digger.scheduler.runner.fetch_wantlist_snapshot", AsyncMock(return_value=snapshot))

    pool = _FakePool(
        listings=[
            {
                "listing_id": 101,
                "release_id": 1,
                "seller_id": 11,
                "price_value": Decimal("10.00"),
                "price_currency": "USD",
                "media_condition": "NM",
                "sleeve_condition": "NM",
            }
        ],
        sellers=[{"seller_id": 11, "region": "us", "country_code": "US", "shipping_policy": None, "feedback_score": None}],
        last_report=None,
    )

    report_id = await run_scheduled_for_user(
        pool,  # type: ignore[arg-type]
        user_id,
        api_base_url="http://api:8004",
        service_token=_SERVICE_TOKEN,
        cadence="biweekly",
    )

    assert isinstance(report_id, uuid.UUID)
    sqls = _executed_sql(pool)
    assert any("INSERT INTO digger.reports" in s for s in sqls)
    assert any("UPDATE digger.user_digger_settings" in s for s in sqls)
    assert False in pool.conn.autocommit_calls  # writes ran inside a transaction

    params = _insert_params(pool)
    assert "scheduled" in params  # kind literal
    assert "first_run" in params  # change_flag (no prior report)


@pytest.mark.asyncio
async def test_run_scheduled_skips_seller_query_when_no_listings(monkeypatch: pytest.MonkeyPatch) -> None:
    user_id = uuid.uuid4()
    snapshot = {
        "must": [{"release_id": 5, "min_media_condition": "NM", "min_sleeve_condition": "NM", "max_price_cents": None}],
        "nice": [],
        "eventually": [],
    }
    monkeypatch.setattr("digger.scheduler.runner.fetch_wantlist_snapshot", AsyncMock(return_value=snapshot))

    pool = _FakePool(listings=[], sellers=[], last_report=None)
    report_id = await run_scheduled_for_user(pool, user_id, api_base_url=_API_BASE, service_token=_SERVICE_TOKEN)  # type: ignore[arg-type]

    assert isinstance(report_id, uuid.UUID)
    sqls = _executed_sql(pool)
    assert not any("FROM digger.sellers" in s for s in sqls)  # no listings -> no seller lookup
    assert any("INSERT INTO digger.reports" in s for s in sqls)


@pytest.mark.asyncio
async def test_run_scheduled_empty_wantlist_advances_without_report(monkeypatch: pytest.MonkeyPatch) -> None:
    user_id = uuid.uuid4()
    snapshot = {"user_id": str(user_id), "must": [], "nice": [], "eventually": []}
    monkeypatch.setattr("digger.scheduler.runner.fetch_wantlist_snapshot", AsyncMock(return_value=snapshot))

    pool = _FakePool()
    result = await run_scheduled_for_user(pool, user_id, api_base_url=_API_BASE, service_token=_SERVICE_TOKEN, cadence="off")  # type: ignore[arg-type]

    assert result is None
    sqls = _executed_sql(pool)
    assert any("UPDATE digger.user_digger_settings" in s for s in sqls)
    assert not any("INSERT INTO digger.reports" in s for s in sqls)
