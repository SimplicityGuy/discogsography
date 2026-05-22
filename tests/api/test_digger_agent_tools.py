"""Tests for the digger agent tool dispatcher and per-tool implementations.

Mock-based (the repo has no real-DB fixtures): query helpers are patched, and
direct-SQL tools drive the conftest ``mock_pool``/``mock_cur`` chain. The
optimizer-output-dependent tools use a real ``OptimizerOutput`` built inline.
"""

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest

from api.digger_agent.tools.dispatch import ToolContext, dispatch_tool
from api.queries.digger_queries import UserDiggerSettings, WantlistPriorityRow
from common.digger_optimizer.models import (
    Bundle,
    Coverage,
    OptimizerDiagnostics,
    OptimizerOutput,
    OrderLine,
    SellerOrder,
)


def _settings(**kw: Any) -> UserDiggerSettings:
    defaults: dict[str, Any] = {
        "user_id": uuid.uuid4(),
        "enabled": True,
        "country_code": "US",
        "currency": "USD",
        "scheduled_cadence": "weekly",
        "preferred_model": "sonnet",
        "daily_token_cap_interactive": 200_000,
        "daily_token_cap_scheduled": 100_000,
    }
    defaults.update(kw)
    return UserDiggerSettings(**defaults)


def _wp(release_id: int, tier: str) -> WantlistPriorityRow:
    return WantlistPriorityRow(
        release_id=release_id,
        tier=tier,  # type: ignore[arg-type]
        min_media_condition="VG+",
        min_sleeve_condition="VG",
        max_price_cents=2500,
    )


def _sample_output() -> OptimizerOutput:
    order = SellerOrder(
        seller_id=1,
        listings=[
            OrderLine(
                listing_id=10,
                release_id=100,
                price_cents=1500,
                currency="USD",
                media_condition="VG+",
                sleeve_condition="VG+",
            )
        ],
        subtotal_item_cents=1500,
        shipping_cents=500,
    )
    bundle = Bundle(
        name="cheapest",
        seller_orders=[order],
        total_item_cost_cents=1500,
        total_shipping_cents=500,
        grand_total_cents=2000,
        coverage=Coverage(must=1, nice=0, eventually=0),
        avg_condition_score=6.0,
        solver="greedy",
        reasoning_hint="cheapest single-seller order",
    )
    diagnostics = OptimizerDiagnostics(
        solver_used={"cheapest": "greedy"},
        solve_time_ms={"cheapest": 1},
        listings_considered=1,
        sellers_considered=1,
    )
    return OptimizerOutput(bundles=[bundle], watching=[200], diagnostics=diagnostics, shipping_confidence="high")


def _ctx(*, pool: Any = None, redis: Any = None, **kw: Any) -> ToolContext:
    return ToolContext(pool=pool or MagicMock(), redis=redis, user_id=uuid.uuid4(), **kw)


# --------------------------------------------------------------------------- #
# dispatcher
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_unknown_tool_returns_error() -> None:
    out = await dispatch_tool("does_not_exist", {}, _ctx())
    assert "error" in out and "unknown tool" in out["error"]


@pytest.mark.asyncio
async def test_bad_arguments_returns_error() -> None:
    out = await dispatch_tool("get_listings_for_release", {}, _ctx())
    assert "error" in out and "bad arguments" in out["error"]


@pytest.mark.asyncio
async def test_handler_exception_returns_error() -> None:
    with patch("api.queries.digger_queries.list_wantlist_priorities", AsyncMock(side_effect=ValueError("boom"))):
        out = await dispatch_tool("get_wantlist", {}, _ctx())
    assert "error" in out and "get_wantlist failed" in out["error"]


# --------------------------------------------------------------------------- #
# get_wantlist
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_get_wantlist_groups_and_counts() -> None:
    rows = [_wp(1, "must"), _wp(2, "nice"), _wp(3, "eventually"), _wp(4, "must")]
    with patch("api.queries.digger_queries.list_wantlist_priorities", AsyncMock(return_value=rows)):
        out = await dispatch_tool("get_wantlist", {}, _ctx())
    assert len(out["must"]) == 2
    assert len(out["nice"]) == 1
    assert len(out["eventually"]) == 1
    assert out["total"] == 4
    assert out["page"] == 1
    assert out["must"][0]["release_id"] == 1


@pytest.mark.asyncio
async def test_get_wantlist_tier_filter() -> None:
    rows = [_wp(1, "must"), _wp(2, "nice")]
    with patch("api.queries.digger_queries.list_wantlist_priorities", AsyncMock(return_value=rows)):
        out = await dispatch_tool("get_wantlist", {"tier_filter": "must"}, _ctx())
    assert len(out["must"]) == 1
    assert out["nice"] == []
    assert out["total"] == 1


@pytest.mark.asyncio
async def test_get_wantlist_pagination() -> None:
    rows = [_wp(i, "nice") for i in range(150)]
    with patch("api.queries.digger_queries.list_wantlist_priorities", AsyncMock(return_value=rows)):
        out = await dispatch_tool("get_wantlist", {"page": 2}, _ctx())
    assert len(out["nice"]) == 50
    assert out["total"] == 150
    assert out["page"] == 2


# --------------------------------------------------------------------------- #
# get_user_settings
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_get_user_settings_present() -> None:
    with patch("api.queries.digger_queries.get_user_settings", AsyncMock(return_value=_settings())):
        out = await dispatch_tool("get_user_settings", {}, _ctx())
    assert out["enabled"] is True
    assert out["preferred_model"] == "sonnet"
    assert out["currency"] == "USD"


@pytest.mark.asyncio
async def test_get_user_settings_absent() -> None:
    with patch("api.queries.digger_queries.get_user_settings", AsyncMock(return_value=None)):
        out = await dispatch_tool("get_user_settings", {}, _ctx())
    assert out == {"enabled": False}


# --------------------------------------------------------------------------- #
# get_listings_for_release (direct SQL)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_get_listings_for_release(mock_pool: MagicMock, mock_cur: AsyncMock) -> None:
    from datetime import UTC, datetime
    from decimal import Decimal

    mock_cur.fetchall.return_value = [
        {
            "listing_id": 10,
            "seller_id": 1,
            "price_value": Decimal("15.00"),
            "price_currency": "USD",
            "media_condition": "VG+",
            "sleeve_condition": "VG",
            "last_seen_at": datetime(2026, 5, 21, tzinfo=UTC),
            "username": "seller_one",
            "country_code": "US",
            "feedback_score": Decimal("99.5"),
        }
    ]
    out = await dispatch_tool("get_listings_for_release", {"release_id": 100}, _ctx(pool=mock_pool))
    assert out["release_id"] == 100
    assert out["count"] == 1
    listing = out["listings"][0]
    assert listing["price_cents"] == 1500
    assert listing["seller"]["username"] == "seller_one"
    assert listing["seller"]["feedback_score"] == 99.5


@pytest.mark.asyncio
async def test_get_listings_for_release_null_feedback(mock_pool: MagicMock, mock_cur: AsyncMock) -> None:
    from datetime import UTC, datetime
    from decimal import Decimal

    mock_cur.fetchall.return_value = [
        {
            "listing_id": 11,
            "seller_id": 2,
            "price_value": Decimal("9.99"),
            "price_currency": "USD",
            "media_condition": "VG",
            "sleeve_condition": "G+",
            "last_seen_at": datetime(2026, 5, 21, tzinfo=UTC),
            "username": "seller_two",
            "country_code": None,
            "feedback_score": None,
        }
    ]
    out = await dispatch_tool("get_listings_for_release", {"release_id": 101}, _ctx(pool=mock_pool))
    assert out["listings"][0]["seller"]["feedback_score"] is None


# --------------------------------------------------------------------------- #
# summarize_marketplace_coverage (direct SQL)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_summarize_marketplace_coverage(mock_pool: MagicMock, mock_cur: AsyncMock) -> None:
    mock_cur.fetchone.return_value = {
        "must_total": 5,
        "nice_total": 3,
        "eventually_total": 2,
        "must_avail": 4,
        "nice_avail": 1,
        "eventually_avail": 0,
    }
    out = await dispatch_tool("summarize_marketplace_coverage", {}, _ctx(pool=mock_pool))
    assert out["must"] == {"total": 5, "available": 4}
    assert out["nice"] == {"total": 3, "available": 1}
    assert out["eventually"] == {"total": 2, "available": 0}


@pytest.mark.asyncio
async def test_summarize_marketplace_coverage_empty(mock_pool: MagicMock, mock_cur: AsyncMock) -> None:
    mock_cur.fetchone.return_value = {
        "must_total": None,
        "nice_total": None,
        "eventually_total": None,
        "must_avail": None,
        "nice_avail": None,
        "eventually_avail": None,
    }
    out = await dispatch_tool("summarize_marketplace_coverage", {}, _ctx(pool=mock_pool))
    assert out["must"] == {"total": 0, "available": 0}


# --------------------------------------------------------------------------- #
# compute_bundles
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_compute_bundles_sets_last_output() -> None:
    ctx = _ctx()
    out_model = _sample_output()
    with (
        patch("api.queries.digger_queries.get_user_settings", AsyncMock(return_value=_settings())),
        patch("api.digger_agent.tools.bundles.build_optimizer_input", AsyncMock(return_value=MagicMock())),
        patch("api.digger_agent.tools.bundles.pareto_bundles", MagicMock(return_value=out_model)),
    ):
        out = await dispatch_tool("compute_bundles", {"budget_cap_cents": 20000}, ctx)
    assert "bundles" in out
    assert out["bundles"][0]["name"] == "cheapest"
    assert ctx.last_optimizer_output is out_model


@pytest.mark.asyncio
async def test_compute_bundles_defaults_location_when_no_settings() -> None:
    ctx = _ctx()
    captured: dict[str, Any] = {}

    async def _fake_build(pool: Any, user_id: Any, **kw: Any) -> Any:  # noqa: ARG001
        captured.update(kw)
        return MagicMock()

    with (
        patch("api.queries.digger_queries.get_user_settings", AsyncMock(return_value=None)),
        patch("api.digger_agent.tools.bundles.build_optimizer_input", _fake_build),
        patch("api.digger_agent.tools.bundles.pareto_bundles", MagicMock(return_value=_sample_output())),
    ):
        await dispatch_tool("compute_bundles", {}, ctx)
    assert captured["location"] == "US"
    assert captured["currency"] == "USD"


# --------------------------------------------------------------------------- #
# explain_bundle
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_explain_bundle_no_prior_output() -> None:
    out = await dispatch_tool("explain_bundle", {"bundle_name": "cheapest"}, _ctx())
    assert "error" in out


@pytest.mark.asyncio
async def test_explain_bundle_ok() -> None:
    ctx = _ctx(last_optimizer_output=_sample_output())
    out = await dispatch_tool("explain_bundle", {"bundle_name": "cheapest"}, ctx)
    assert out["bundle_name"] == "cheapest"
    assert out["grand_total_cents"] == 2000
    assert out["coverage"]["must"] == 1
    assert len(out["seller_orders"]) == 1


@pytest.mark.asyncio
async def test_explain_bundle_unknown_name() -> None:
    ctx = _ctx(last_optimizer_output=_sample_output())
    out = await dispatch_tool("explain_bundle", {"bundle_name": "best_quality"}, ctx)
    assert "error" in out


# --------------------------------------------------------------------------- #
# save_report
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_save_report_no_prior_output() -> None:
    out = await dispatch_tool("save_report", {"title": "Q1 hunt"}, _ctx())
    assert "error" in out


@pytest.mark.asyncio
async def test_save_report_ok() -> None:
    ctx = _ctx(last_optimizer_output=_sample_output())
    new_id = uuid.uuid4()
    with patch("api.digger_agent.tools.report.insert_report", AsyncMock(return_value=new_id)) as ins:
        out = await dispatch_tool("save_report", {"title": "Q1 hunt"}, ctx)
    assert out["report_id"] == str(new_id)
    kwargs = ins.await_args.kwargs
    assert kwargs["kind"] == "interactive"
    assert kwargs["title"] == "Q1 hunt"
    assert kwargs["watching"] == [200]
    assert kwargs["shipping_confidence"] == "high"
    assert kwargs["summary"]["must_available"] == 1


# --------------------------------------------------------------------------- #
# propose_tier_changes (direct SQL)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_propose_tier_changes_inserts(mock_pool: MagicMock, mock_cur: AsyncMock) -> None:
    mock_cur.fetchone.return_value = {"tier": "nice"}
    session_id = uuid.uuid4()
    out = await dispatch_tool(
        "propose_tier_changes",
        {"changes": [{"release_id": 1, "proposed_tier": "must", "reason": "rare pressing"}]},
        _ctx(pool=mock_pool, session_id=session_id),
    )
    assert out["count"] == 1
    assert uuid.UUID(out["proposal_id"])
    # last execute is the INSERT into digger.proposals
    insert_sql = mock_cur.execute.await_args_list[-1].args[0]
    assert "INSERT INTO digger.proposals" in insert_sql


@pytest.mark.asyncio
async def test_propose_tier_changes_skips_unknown_releases(mock_pool: MagicMock, mock_cur: AsyncMock) -> None:
    mock_cur.fetchone.return_value = None  # release not in wantlist
    out = await dispatch_tool(
        "propose_tier_changes",
        {"changes": [{"release_id": 999, "proposed_tier": "must", "reason": "x"}]},
        _ctx(pool=mock_pool),
    )
    assert "error" in out


# --------------------------------------------------------------------------- #
# request_opportunistic_refresh
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_refresh_no_redis() -> None:
    out = await dispatch_tool("request_opportunistic_refresh", {}, _ctx(redis=None))
    assert "error" in out


@pytest.mark.asyncio
async def test_refresh_no_releases(mock_pool: MagicMock, mock_cur: AsyncMock) -> None:
    mock_cur.fetchall.return_value = []
    out = await dispatch_tool("request_opportunistic_refresh", {}, _ctx(pool=mock_pool, redis=AsyncMock()))
    assert out == {"refreshed": 0, "stale_count": 0}


@pytest.mark.asyncio
async def test_refresh_completes(mock_pool: MagicMock, mock_cur: AsyncMock) -> None:
    mock_cur.fetchall.return_value = [{"release_id": 1}, {"release_id": 2}]

    async def _progress(user_id: str, *, deadline_seconds: float) -> AsyncIterator[dict[str, Any]]:  # noqa: ARG001
        yield {"release_id": 1, "status": "ok"}
        yield {"release_id": 2, "status": "ok"}

    fake_coord = MagicMock()
    fake_coord.bump_priorities = AsyncMock(return_value=2)
    fake_coord.subscribe_progress = _progress
    with patch("api.digger_agent.tools.refresh.RefreshCoordinator", MagicMock(return_value=fake_coord)):
        out = await dispatch_tool("request_opportunistic_refresh", {"deadline_seconds": 10}, _ctx(pool=mock_pool, redis=AsyncMock()))
    assert out == {"refreshed": 2, "stale_count": 2}
    fake_coord.bump_priorities.assert_awaited_once_with([1, 2])
