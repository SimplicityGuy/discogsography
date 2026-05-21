"""Property-based tests for the digger optimizer.

Covers invariants that hold across many generated inputs:
- more budget never reduces must coverage (monotonicity),
- every bundle's totals are internally consistent (no arithmetic drift),
- coverage counts stay within bounds and watching never overlaps covered musts.
"""

from __future__ import annotations

from decimal import Decimal
import uuid

from hypothesis import HealthCheck, given, settings, strategies as st

from common.digger_optimizer import pareto_bundles
from common.digger_optimizer.models import Listing, OptimizerInput, ReleaseConstraint, Seller


def _make_input(seed: int) -> OptimizerInput:
    n_must = (seed % 3) + 1
    must = [ReleaseConstraint(release_id=10 + i, min_media_condition="VG", min_sleeve_condition="VG") for i in range(n_must)]
    nice = [ReleaseConstraint(release_id=100 + i, min_media_condition="VG", min_sleeve_condition="VG") for i in range(2)]
    sellers = {
        1: Seller(seller_id=1, region="us", country_code="US"),
        2: Seller(seller_id=2, region="us", country_code="US"),
    }
    listings: list[Listing] = []
    for rid in [c.release_id for c in must + nice]:
        listings.append(
            Listing(
                listing_id=rid * 10 + 1,
                release_id=rid,
                seller_id=1,
                price_value=Decimal(str(5 + (rid % 20))),
                price_currency="USD",
                media_condition="NM",
                sleeve_condition="NM",
            )
        )
        listings.append(
            Listing(
                listing_id=rid * 10 + 2,
                release_id=rid,
                seller_id=2,
                price_value=Decimal(str(7 + (rid % 15))),
                price_currency="USD",
                media_condition="NM",
                sleeve_condition="NM",
            )
        )
    return OptimizerInput(
        user_id=uuid.uuid4(),
        location="US",
        currency="USD",
        must_have_releases=must,
        nice_have_releases=nice,
        candidate_listings=listings,
        sellers=sellers,
    )


@settings(max_examples=15, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.integers(min_value=0, max_value=100))
def test_more_budget_never_reduces_must_coverage(seed: int) -> None:
    base = _make_input(seed)
    low = pareto_bundles(base.model_copy(update={"budget_cap_cents": 1000})).bundles[0]
    high = pareto_bundles(base.model_copy(update={"budget_cap_cents": 1_000_000})).bundles[0]
    assert high.coverage.must >= low.coverage.must


@settings(max_examples=15, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.integers(min_value=0, max_value=100))
def test_bundle_totals_are_internally_consistent(seed: int) -> None:
    out = pareto_bundles(_make_input(seed))
    for b in out.bundles:
        item = sum(o.subtotal_item_cents for o in b.seller_orders)
        ship = sum(o.shipping_cents for o in b.seller_orders)
        assert b.total_item_cost_cents == item
        assert b.total_shipping_cents == ship
        assert b.grand_total_cents == item + ship


@settings(max_examples=15, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.integers(min_value=0, max_value=100))
def test_coverage_within_bounds_and_watching_disjoint(seed: int) -> None:
    inp = _make_input(seed)
    out = pareto_bundles(inp)
    n_must = len(inp.must_have_releases)
    n_nice = len(inp.nice_have_releases)
    must_ids = {c.release_id for c in inp.must_have_releases}
    for b in out.bundles:
        assert 0 <= b.coverage.must <= n_must
        assert 0 <= b.coverage.nice <= n_nice
    # All musts have listings in _make_input, so nothing should be marked "watching".
    assert not (set(out.watching) & must_ids)
