"""Tests for the digger optimizer ILP solver (pulp + CBC)."""

from __future__ import annotations

from decimal import Decimal
import uuid

from common.digger_optimizer.ilp import solve_ilp_bundle
from common.digger_optimizer.models import Listing, OptimizerInput, ReleaseConstraint, Seller


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


def test_ilp_finds_optimal_two_must_one_seller() -> None:
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
            _listing(102, 1, 2, "9"),
            _listing(201, 2, 1, "5"),
            _listing(202, 2, 2, "7"),
        ],
        sellers={1: _seller(1), 2: _seller(2)},
    )
    b = solve_ilp_bundle(inp, name="cheapest", timeout_seconds=5)
    assert b is not None
    assert b.coverage.must == 2
    # Single-seller bundle wins because a second seller's shipping outweighs the item savings.
    assert {o.seller_id for o in b.seller_orders} == {1}
    # Items 101 ($10) + 201 ($5) = $15; shipping for 2 items from seller 1 = int($5 * 1.2) = $6 -> $21.
    assert b.grand_total_cents == 10_00 + 5_00 + 6_00


def test_ilp_returns_empty_bundle_when_must_unavailable() -> None:
    inp = OptimizerInput(
        user_id=uuid.uuid4(),
        location="US",
        currency="USD",
        must_have_releases=[
            ReleaseConstraint(release_id=1, min_media_condition="NM", min_sleeve_condition="NM"),
        ],
        candidate_listings=[],
        sellers={},
    )
    b = solve_ilp_bundle(inp, name="cheapest", timeout_seconds=5)
    # Infeasible (must release with no listings) — return an empty bundle, not None.
    assert b is not None
    assert b.coverage.must == 0


def test_ilp_excludes_seller() -> None:
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
    b = solve_ilp_bundle(inp, name="cheapest", timeout_seconds=5)
    assert b is not None
    assert b.coverage.must == 1
    assert {o.seller_id for o in b.seller_orders} == {2}
