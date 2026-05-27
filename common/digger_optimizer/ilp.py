"""ILP-based bundle optimizer using pulp + CBC.

Variables:
  x[lid] in {0,1}     — include this listing
  y[sid] in {0,1}     — order from this seller
  z[sid, k] in {0,1}  — seller s has exactly k items in the bundle (k = 1..K_max)

Constraints:
  must:                 sum(x[lid] for usable listings) == 1
  nice/eventually:      sum(x[lid] for usable listings) <= 1
  listing -> seller:    x[lid] <= y[seller_of_lid]
  z gating per seller:  sum_k z[s,k] == y[s];  sum_k k*z[s,k] == sum(x in s)
  excluded sellers:     y[s] == 0
  budget (optional):    sum(x*price) + sum z*shipping <= cap

Objective (per bundle name): minimize item cost + shipping
  (+ seller_penalty * sum(y))            for 'fewest_sellers'
  (- quality_per_step * sum(x*rank))     for 'best_quality'
  (- lambda_nice/eventually * sum(x))    soft-tier coverage credit
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pulp

from common.digger_optimizer.filtering import filter_candidates
from common.digger_optimizer.greedy import _WEIGHTS, build_bundle_from_listings
from common.digger_optimizer.models import CONDITION_RANK
from common.digger_optimizer.shipping import estimate_shipping_cents


if TYPE_CHECKING:  # pragma: no cover
    from common.digger_optimizer.models import Bundle, BundleName, Listing, OptimizerInput


log = logging.getLogger(__name__)


def solve_ilp_bundle(inp: OptimizerInput, *, name: BundleName, timeout_seconds: int = 5) -> Bundle | None:
    weights = _WEIGHTS[name]
    fr = filter_candidates(inp)

    must_set = {c.release_id for c in inp.must_have_releases}
    nice_set = {c.release_id for c in inp.nice_have_releases}
    eventually_set = {c.release_id for c in inp.eventually_releases}

    if not fr.usable_by_release:
        return build_bundle_from_listings(name, [], inp, must_set, nice_set, eventually_set, solver="ilp")

    listings_by_id: dict[int, Listing] = {listing.listing_id: listing for listing in inp.candidate_listings}
    seller_listings: dict[int, list[int]] = {}
    listing_id_set: set[int] = set()
    for lids in fr.usable_by_release.values():
        for lid in lids:
            listing_id_set.add(lid)
            seller_listings.setdefault(listings_by_id[lid].seller_id, []).append(lid)

    if not listing_id_set:  # pragma: no cover - defensive; non-empty usable_by_release implies non-empty listing set
        return build_bundle_from_listings(name, [], inp, must_set, nice_set, eventually_set, solver="ilp")

    prob = pulp.LpProblem(f"digger_{name}", pulp.LpMinimize)

    x = {lid: prob.add_variable(f"x_{lid}", cat="Binary") for lid in listing_id_set}
    y = {sid: prob.add_variable(f"y_{sid}", cat="Binary") for sid in seller_listings}

    max_k_per_seller: dict[int, int] = {sid: len(lids) for sid, lids in seller_listings.items()}
    z: dict[tuple[int, int], pulp.LpVariable] = {}
    for sid, k_max in max_k_per_seller.items():
        for k in range(1, k_max + 1):
            z[(sid, k)] = prob.add_variable(f"z_{sid}_{k}", cat="Binary")

    # Must-have: each Must release covered exactly once if any usable listing exists.
    for must in inp.must_have_releases:
        lids = fr.usable_by_release.get(must.release_id, [])
        if lids:
            prob += pulp.lpSum(x[lid] for lid in lids) == 1, f"must_{must.release_id}"

    # Nice/Eventually: at most one chosen per release.
    for soft in inp.nice_have_releases + inp.eventually_releases:
        lids = fr.usable_by_release.get(soft.release_id, [])
        if lids:
            prob += pulp.lpSum(x[lid] for lid in lids) <= 1, f"soft_{soft.release_id}"

    # Linking + per-seller item-count gating.
    for sid, lids in seller_listings.items():
        for lid in lids:
            prob += x[lid] <= y[sid], f"link_{lid}"
        prob += pulp.lpSum(z[(sid, k)] for k in range(1, max_k_per_seller[sid] + 1)) == y[sid], f"zsum_{sid}"
        prob += pulp.lpSum(k * z[(sid, k)] for k in range(1, max_k_per_seller[sid] + 1)) == pulp.lpSum(x[lid] for lid in lids), f"zcount_{sid}"

    # Excluded sellers.
    for sid in inp.excluded_sellers:
        if sid in y:
            prob += y[sid] == 0, f"excl_{sid}"

    def _ship(sid: int, k: int) -> int:
        return estimate_shipping_cents(inp.sellers[sid], location=inp.location, count=k)

    # Budget (optional).
    if inp.budget_cap_cents is not None:
        item_cost = pulp.lpSum(x[lid] * int(listings_by_id[lid].price_value * 100) for lid in listing_id_set)
        ship_cost = pulp.lpSum(z[(sid, k)] * _ship(sid, k) for sid in seller_listings for k in range(1, max_k_per_seller[sid] + 1))
        prob += item_cost + ship_cost <= inp.budget_cap_cents, "budget"

    # Objective.
    obj_item = pulp.lpSum(x[lid] * int(listings_by_id[lid].price_value * 100) for lid in listing_id_set)
    obj_ship = pulp.lpSum(z[(sid, k)] * _ship(sid, k) for sid in seller_listings for k in range(1, max_k_per_seller[sid] + 1))
    obj_seller_penalty = weights.seller_penalty * pulp.lpSum(y[sid] for sid in seller_listings)
    obj_quality = -weights.quality_per_step * pulp.lpSum(x[lid] * CONDITION_RANK[listings_by_id[lid].media_condition] for lid in listing_id_set)
    obj_nice = -weights.lambda_nice * pulp.lpSum(x[lid] for lid in listing_id_set if listings_by_id[lid].release_id in nice_set)
    obj_ev = -weights.lambda_eventually * pulp.lpSum(x[lid] for lid in listing_id_set if listings_by_id[lid].release_id in eventually_set)
    prob += obj_item + obj_ship + obj_seller_penalty + obj_quality + obj_nice + obj_ev

    solver = pulp.COIN_CMD(path=pulp.PULP_CBC_CMD.pulp_cbc_path, msg=False, timeLimit=timeout_seconds, options=["randomSeed 42"])
    status = prob.solve(solver)
    status_label = pulp.LpStatus[status]
    if status not in (pulp.LpStatusOptimal, pulp.LpStatusNotSolved):
        log.warning("⚠️ ILP solver returned status=%s for %s", status_label, name)

    if status_label == "Infeasible":
        return build_bundle_from_listings(name, [], inp, must_set, nice_set, eventually_set, solver="ilp")

    chosen: list[Listing] = []
    for lid in sorted(listing_id_set):
        val = pulp.value(x[lid])
        if val is not None and val >= 0.5:
            chosen.append(listings_by_id[lid])
    return build_bundle_from_listings(name, chosen, inp, must_set, nice_set, eventually_set, solver="ilp")
