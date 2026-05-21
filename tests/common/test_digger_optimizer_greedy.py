"""Tests for the digger optimizer greedy reference/fallback solver."""

from __future__ import annotations

from decimal import Decimal
import uuid

from common.digger_optimizer.greedy import greedy_bundle
from common.digger_optimizer.models import Bundle, Listing, OptimizerInput, ReleaseConstraint, Seller


def _seller(sid: int) -> Seller:
    return Seller(seller_id=sid, region="us", country_code="US", shipping_policy=None)


def _listing(lid: int, rid: int, sid: int, price: str) -> Listing:
    return Listing(
        listing_id=lid,
        release_id=rid,
        seller_id=sid,
        price_value=Decimal(price),
        price_currency="USD",
        media_condition="NM",
        sleeve_condition="NM",
    )


def test_greedy_covers_all_musts_minimum_sellers_when_possible() -> None:
    inp = OptimizerInput(
        user_id=uuid.uuid4(),
        location="US",
        currency="USD",
        must_have_releases=[
            ReleaseConstraint(release_id=1, min_media_condition="VG", min_sleeve_condition="VG"),
            ReleaseConstraint(release_id=2, min_media_condition="VG", min_sleeve_condition="VG"),
        ],
        candidate_listings=[
            _listing(101, 1, 1, "10"),
            _listing(102, 1, 2, "12"),
            _listing(201, 2, 1, "8"),
            _listing(202, 2, 2, "9"),
        ],
        sellers={1: _seller(1), 2: _seller(2)},
    )
    b: Bundle = greedy_bundle(inp, name="cheapest")
    assert b.coverage.must == 2
    # Seller 1 covers both at 10+8=18 + shipping_once; greedy consolidation prefers seller 1.
    assert {o.seller_id for o in b.seller_orders} == {1}


def test_greedy_returns_zero_coverage_when_no_listings() -> None:
    inp = OptimizerInput(
        user_id=uuid.uuid4(),
        location="US",
        currency="USD",
        must_have_releases=[
            ReleaseConstraint(release_id=99, min_media_condition="NM", min_sleeve_condition="NM"),
        ],
        candidate_listings=[],
        sellers={},
    )
    b = greedy_bundle(inp, name="cheapest")
    assert b.coverage.must == 0
    assert b.grand_total_cents == 0


def test_greedy_extends_with_cheap_nice_and_eventually() -> None:
    inp = OptimizerInput(
        user_id=uuid.uuid4(),
        location="US",
        currency="USD",
        must_have_releases=[ReleaseConstraint(release_id=1, min_media_condition="VG", min_sleeve_condition="VG")],
        nice_have_releases=[ReleaseConstraint(release_id=2, min_media_condition="VG", min_sleeve_condition="VG")],
        eventually_releases=[ReleaseConstraint(release_id=3, min_media_condition="VG", min_sleeve_condition="VG")],
        candidate_listings=[
            _listing(101, 1, 1, "10"),  # must
            _listing(201, 2, 1, "1"),  # cheap nice (same seller, small marginal)
            _listing(301, 3, 1, "1"),  # cheap eventually
        ],
        sellers={1: _seller(1)},
    )
    b = greedy_bundle(inp, name="most_coverage")
    assert b.coverage.must == 1
    assert b.coverage.nice == 1
    assert b.coverage.eventually == 1


def test_greedy_skips_nice_item_above_lambda_budget() -> None:
    inp = OptimizerInput(
        user_id=uuid.uuid4(),
        location="US",
        currency="USD",
        must_have_releases=[ReleaseConstraint(release_id=1, min_media_condition="VG", min_sleeve_condition="VG")],
        nice_have_releases=[ReleaseConstraint(release_id=2, min_media_condition="VG", min_sleeve_condition="VG")],
        candidate_listings=[
            _listing(101, 1, 1, "10"),  # must
            _listing(201, 2, 1, "99"),  # nice, far above the $5 cheapest lambda budget
        ],
        sellers={1: _seller(1)},
    )
    b = greedy_bundle(inp, name="cheapest")
    assert b.coverage.must == 1
    assert b.coverage.nice == 0


def test_greedy_skips_excluded_seller() -> None:
    inp = OptimizerInput(
        user_id=uuid.uuid4(),
        location="US",
        currency="USD",
        must_have_releases=[ReleaseConstraint(release_id=1, min_media_condition="VG", min_sleeve_condition="VG")],
        candidate_listings=[
            _listing(101, 1, 1, "5"),  # cheapest, but seller 1 is excluded
            _listing(102, 1, 2, "10"),
        ],
        sellers={1: _seller(1), 2: _seller(2)},
        excluded_sellers=frozenset({1}),
    )
    b = greedy_bundle(inp, name="cheapest")
    assert b.coverage.must == 1
    assert {o.seller_id for o in b.seller_orders} == {2}
