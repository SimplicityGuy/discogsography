"""Stage 1: filter listings against per-tier condition floors and max-price caps.

Currency conversion is out of scope for M2 — listings whose currency differs
from the user's currency are skipped (counted in diagnostics).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from common.digger_optimizer.models import CONDITION_RANK


if TYPE_CHECKING:  # pragma: no cover
    from common.digger_optimizer.models import Listing, OptimizerInput, ReleaseConstraint


@dataclass(slots=True)
class FilterResult:
    usable_by_release: dict[int, list[int]] = field(default_factory=dict)  # release_id -> [listing_id]
    watching: list[int] = field(default_factory=list)  # release_ids with no qualifying listings
    skipped_currency: int = 0


def _meets(listing: Listing, constraint: ReleaseConstraint) -> bool:
    # Currency is already filtered upstream in filter_candidates, so it is not re-checked here.
    if CONDITION_RANK[listing.media_condition] < CONDITION_RANK[constraint.min_media_condition]:
        return False
    if CONDITION_RANK[listing.sleeve_condition] < CONDITION_RANK[constraint.min_sleeve_condition]:
        return False
    return not (constraint.max_price_cents is not None and int(listing.price_value * 100) > constraint.max_price_cents)


def filter_candidates(inp: OptimizerInput) -> FilterResult:
    result = FilterResult()
    listings_by_release: dict[int, list[Listing]] = {}
    for listing in inp.candidate_listings:
        if listing.price_currency != inp.currency:
            result.skipped_currency += 1
            continue
        listings_by_release.setdefault(listing.release_id, []).append(listing)

    for must in inp.must_have_releases:
        usable = [listing.listing_id for listing in listings_by_release.get(must.release_id, []) if _meets(listing, must)]
        if usable:
            result.usable_by_release[must.release_id] = usable
        else:
            result.watching.append(must.release_id)

    for soft_group in (inp.nice_have_releases, inp.eventually_releases):
        for constraint in soft_group:
            usable = [listing.listing_id for listing in listings_by_release.get(constraint.release_id, []) if _meets(listing, constraint)]
            if usable:
                result.usable_by_release[constraint.release_id] = usable
    return result
