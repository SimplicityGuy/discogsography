"""Tests for the digger optimizer Pareto-front coordinator."""

from __future__ import annotations

from decimal import Decimal
import uuid

from common.digger_optimizer import pareto_bundles
from common.digger_optimizer.models import Listing, OptimizerInput, ReleaseConstraint, Seller


def _seller(sid: int) -> Seller:
    return Seller(seller_id=sid, region="us", country_code="US", shipping_policy=None)


def _listing(lid: int, rid: int, sid: int, price: str, media: str = "NM") -> Listing:
    return Listing(
        listing_id=lid,
        release_id=rid,
        seller_id=sid,
        price_value=Decimal(price),
        price_currency="USD",
        media_condition=media,  # type: ignore[arg-type]
        sleeve_condition=media,  # type: ignore[arg-type]
    )


def test_pareto_returns_named_bundles() -> None:
    # One must release with a cheap-low-grade option (seller 1) and a pricey-top-grade
    # option (seller 2). Cheapest should take the cheap one; best_quality the top one.
    inp = OptimizerInput(
        user_id=uuid.uuid4(),
        location="US",
        currency="USD",
        must_have_releases=[ReleaseConstraint(release_id=1, min_media_condition="VG", min_sleeve_condition="VG")],
        candidate_listings=[
            _listing(101, 1, 1, "5", media="VG"),
            _listing(102, 1, 2, "12", media="M"),
        ],
        sellers={1: _seller(1), 2: _seller(2)},
    )
    out = pareto_bundles(inp)

    assert {b.name for b in out.bundles} == {"cheapest", "most_coverage", "best_quality", "fewest_sellers"}
    assert all(b.coverage.must == 1 for b in out.bundles)

    cheapest = next(b for b in out.bundles if b.name == "cheapest")
    quality = next(b for b in out.bundles if b.name == "best_quality")
    assert cheapest.grand_total_cents <= quality.grand_total_cents
    assert quality.avg_condition_score >= cheapest.avg_condition_score

    assert out.shipping_confidence in ("high", "low")
    assert out.diagnostics.listings_considered >= 1
    assert set(out.diagnostics.solver_used) == {"cheapest", "most_coverage", "best_quality", "fewest_sellers"}


def test_pareto_marks_watching_when_must_unavailable() -> None:
    inp = OptimizerInput(
        user_id=uuid.uuid4(),
        location="US",
        currency="USD",
        must_have_releases=[ReleaseConstraint(release_id=99, min_media_condition="M", min_sleeve_condition="M")],
        candidate_listings=[],
        sellers={},
    )
    out = pareto_bundles(inp)
    assert 99 in out.watching
