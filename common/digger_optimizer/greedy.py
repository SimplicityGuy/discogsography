"""Greedy reference implementation for bundle optimization.

Used as:
1. Fallback when the ILP solver times out.
2. Warm-start hint when invoking the ILP.
3. Reference implementation for cross-checks in property tests.

Algorithm:
- Group listings by seller.
- For each release, score each usable listing by a cents-equivalent value minus
  its marginal (item + incremental-shipping) cost; greedily take the best.
- Cover all Musts first, then extend with Nice/Eventually items whose marginal
  cost is within that tier's lambda budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from common.digger_optimizer.filtering import filter_candidates
from common.digger_optimizer.models import CONDITION_RANK, Bundle, Coverage, OrderLine, SellerOrder
from common.digger_optimizer.shipping import estimate_shipping_cents


if TYPE_CHECKING:
    from typing import Literal

    from common.digger_optimizer.models import BundleName, Listing, OptimizerInput


@dataclass(slots=True)
class _ObjectiveWeights:
    lambda_nice: int  # cents-credit per Nice item covered
    lambda_eventually: int  # cents-credit per Eventually item covered
    quality_per_step: int  # cents bonus per +1 condition rank
    seller_penalty: int  # cents penalty per additional seller


_WEIGHTS: dict[BundleName, _ObjectiveWeights] = {
    "cheapest": _ObjectiveWeights(lambda_nice=500, lambda_eventually=100, quality_per_step=0, seller_penalty=0),
    "most_coverage": _ObjectiveWeights(lambda_nice=2500, lambda_eventually=1000, quality_per_step=0, seller_penalty=0),
    "best_quality": _ObjectiveWeights(lambda_nice=500, lambda_eventually=100, quality_per_step=300, seller_penalty=0),
    "fewest_sellers": _ObjectiveWeights(lambda_nice=500, lambda_eventually=100, quality_per_step=0, seller_penalty=2000),
}


def _value_score(listing: Listing, must_set: set[int], nice_set: set[int], eventually_set: set[int], w: _ObjectiveWeights) -> int:
    """Cents-equivalent value of including this listing in the bundle."""
    base = -int(listing.price_value * 100)  # negative — cost
    if listing.release_id in must_set:
        base += 10_000_000  # huge bonus so must items always picked first
    elif listing.release_id in nice_set:
        base += w.lambda_nice
    elif listing.release_id in eventually_set:
        base += w.lambda_eventually
    base += w.quality_per_step * CONDITION_RANK[listing.media_condition]
    return base


def greedy_bundle(inp: OptimizerInput, *, name: BundleName) -> Bundle:
    weights = _WEIGHTS[name]
    fr = filter_candidates(inp)
    listings_by_id: dict[int, Listing] = {listing.listing_id: listing for listing in inp.candidate_listings}
    must_set = {c.release_id for c in inp.must_have_releases}
    nice_set = {c.release_id for c in inp.nice_have_releases}
    eventually_set = {c.release_id for c in inp.eventually_releases}

    chosen: list[Listing] = []
    covered_releases: set[int] = set()
    seller_used_counts: dict[int, int] = {}

    def _consider(release_pool: set[int]) -> Listing | None:
        """Pick the uncovered-release listing with the best marginal value."""
        best: tuple[float, Listing] | None = None
        for rid in release_pool:
            if rid in covered_releases:
                continue
            for lid in fr.usable_by_release.get(rid, []):
                listing = listings_by_id[lid]
                if listing.seller_id in inp.excluded_sellers:
                    continue
                existing = seller_used_counts.get(listing.seller_id, 0)
                seller = inp.sellers[listing.seller_id]
                marginal = estimate_shipping_cents(seller, location=inp.location, count=existing + 1) - estimate_shipping_cents(
                    seller, location=inp.location, count=existing
                )
                value = _value_score(listing, must_set, nice_set, eventually_set, weights)
                value -= marginal
                if existing == 0:
                    value -= weights.seller_penalty
                cost = int(listing.price_value * 100) + marginal
                ratio = value / max(1, cost)
                if best is None or ratio > best[0]:
                    best = (ratio, listing)
        return best[1] if best else None

    # 1. cover Musts
    while True:
        listing = _consider(must_set)
        if listing is None:
            break
        chosen.append(listing)
        covered_releases.add(listing.release_id)
        seller_used_counts[listing.seller_id] = seller_used_counts.get(listing.seller_id, 0) + 1

    # 2. extend with Nice/Eventually if their marginal is "cheap enough"
    for release_pool, lam in ((nice_set, weights.lambda_nice), (eventually_set, weights.lambda_eventually)):
        if lam <= 0:
            continue
        while True:
            listing = _consider(release_pool)
            if listing is None:
                break
            existing = seller_used_counts.get(listing.seller_id, 0)
            seller = inp.sellers[listing.seller_id]
            marginal = estimate_shipping_cents(seller, location=inp.location, count=existing + 1) - estimate_shipping_cents(
                seller, location=inp.location, count=existing
            )
            marginal_cost = int(listing.price_value * 100) + marginal
            if marginal_cost > lam:
                break
            chosen.append(listing)
            covered_releases.add(listing.release_id)
            seller_used_counts[listing.seller_id] = existing + 1

    return _build_bundle(name, chosen, inp, must_set, nice_set, eventually_set, solver="greedy")


def _build_bundle(
    name: BundleName,
    chosen: list[Listing],
    inp: OptimizerInput,
    must_set: set[int],
    nice_set: set[int],
    eventually_set: set[int],
    *,
    solver: Literal["ilp", "greedy"],
) -> Bundle:
    if not chosen:
        return Bundle(
            name=name,
            seller_orders=[],
            total_item_cost_cents=0,
            total_shipping_cents=0,
            grand_total_cents=0,
            coverage=Coverage(must=0, nice=0, eventually=0),
            avg_condition_score=0.0,
            solver=solver,
            reasoning_hint="No qualifying listings.",
        )
    by_seller: dict[int, list[Listing]] = {}
    for listing in chosen:
        by_seller.setdefault(listing.seller_id, []).append(listing)
    orders: list[SellerOrder] = []
    total_item = 0
    total_ship = 0
    for sid, listings in by_seller.items():
        subtotal = sum(int(listing.price_value * 100) for listing in listings)
        ship = estimate_shipping_cents(inp.sellers[sid], location=inp.location, count=len(listings))
        orders.append(
            SellerOrder(
                seller_id=sid,
                listings=[
                    OrderLine(
                        listing_id=listing.listing_id,
                        release_id=listing.release_id,
                        price_cents=int(listing.price_value * 100),
                        currency=listing.price_currency,
                        media_condition=listing.media_condition,
                        sleeve_condition=listing.sleeve_condition,
                    )
                    for listing in listings
                ],
                subtotal_item_cents=subtotal,
                shipping_cents=ship,
            )
        )
        total_item += subtotal
        total_ship += ship
    coverage = Coverage(
        must=sum(1 for listing in chosen if listing.release_id in must_set),
        nice=sum(1 for listing in chosen if listing.release_id in nice_set),
        eventually=sum(1 for listing in chosen if listing.release_id in eventually_set),
    )
    avg_cond = sum(CONDITION_RANK[listing.media_condition] for listing in chosen) / len(chosen)
    return Bundle(
        name=name,
        seller_orders=orders,
        total_item_cost_cents=total_item,
        total_shipping_cents=total_ship,
        grand_total_cents=total_item + total_ship,
        coverage=coverage,
        avg_condition_score=avg_cond,
        solver=solver,
        reasoning_hint=f"{coverage.must} must, {coverage.nice} nice, {coverage.eventually} eventually across {len(orders)} sellers.",
    )


# Exported for ilp.py warm-start / fallback bundle construction.
build_bundle_from_listings = _build_bundle
