"""Pareto-front coordinator: runs the four bundle variants.

Falls back to greedy on ILP error. Returns an OptimizerOutput with
per-variant diagnostics and an overall shipping-confidence flag.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from common.digger_optimizer.filtering import filter_candidates
from common.digger_optimizer.greedy import greedy_bundle
from common.digger_optimizer.ilp import solve_ilp_bundle
from common.digger_optimizer.models import OptimizerDiagnostics, OptimizerOutput
from common.digger_optimizer.shipping import shipping_confidence_score


if TYPE_CHECKING:
    from typing import Literal

    from common.digger_optimizer.models import Bundle, BundleName, OptimizerInput


log = logging.getLogger(__name__)

_BUNDLE_NAMES: tuple[BundleName, ...] = ("cheapest", "most_coverage", "best_quality", "fewest_sellers")


def pareto_bundles(inp: OptimizerInput, *, ilp_timeout_seconds: int = 5) -> OptimizerOutput:
    fr = filter_candidates(inp)
    bundles: list[Bundle] = []
    solver_used: dict[BundleName, Literal["ilp", "greedy"]] = {}
    solve_time: dict[BundleName, int] = {}

    for name in _BUNDLE_NAMES:
        t0 = time.monotonic()
        used: Literal["ilp", "greedy"]
        try:
            bundle = solve_ilp_bundle(inp, name=name, timeout_seconds=ilp_timeout_seconds)
            used = "ilp"
        except Exception:
            log.exception("⚠️ ILP failed for %s — falling back to greedy", name)
            bundle = None
            used = "greedy"
        if bundle is None:
            bundle = greedy_bundle(inp, name=name)
            used = "greedy"
        solve_time[name] = int((time.monotonic() - t0) * 1000)
        bundles.append(bundle)
        solver_used[name] = used

    return OptimizerOutput(
        bundles=bundles,
        watching=fr.watching,
        diagnostics=OptimizerDiagnostics(
            solver_used=solver_used,
            solve_time_ms=solve_time,
            listings_considered=sum(len(v) for v in fr.usable_by_release.values()),
            sellers_considered=len({listing.seller_id for listing in inp.candidate_listings}),
        ),
        shipping_confidence=shipping_confidence_score(inp.sellers, location=inp.location),
    )
