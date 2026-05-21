"""Per-seller shipping cost estimation.

Prefers scraped ``shipping_policy``; falls back to a static 7x7 region matrix.
M2 ships USD-only display, so the matrix is USD-centric.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal


if TYPE_CHECKING:
    from common.digger_optimizer.models import Seller


Region = Literal["us", "ca", "eu", "uk", "jp", "au", "other"]


# Cents — USD-centric.
REGION_MATRIX_CENTS: dict[Region, dict[Region, int]] = {
    "us": {"us": 500, "ca": 1500, "eu": 2500, "uk": 2500, "jp": 3000, "au": 3500, "other": 4000},
    "ca": {"us": 1500, "ca": 800, "eu": 2500, "uk": 2500, "jp": 3000, "au": 3500, "other": 4000},
    "eu": {"us": 2500, "ca": 2500, "eu": 1200, "uk": 1500, "jp": 3000, "au": 3500, "other": 4000},
    "uk": {"us": 2500, "ca": 2500, "eu": 1500, "uk": 700, "jp": 3000, "au": 3500, "other": 4000},
    "jp": {"us": 3000, "ca": 3000, "eu": 3000, "uk": 3000, "jp": 800, "au": 2500, "other": 4000},
    "au": {"us": 3500, "ca": 3500, "eu": 3500, "uk": 3500, "jp": 2500, "au": 800, "other": 4000},
    "other": {"us": 4000, "ca": 4000, "eu": 4000, "uk": 4000, "jp": 4000, "au": 4000, "other": 4000},
}


COUNTRY_TO_REGION: dict[str, Region] = {
    "US": "us",
    "CA": "ca",
    "GB": "uk",
    "JP": "jp",
    "AU": "au",
    "DE": "eu",
    "FR": "eu",
    "IT": "eu",
    "ES": "eu",
    "NL": "eu",
    "BE": "eu",
    "AT": "eu",
}

_DEFAULT_REGION: Region = "other"


def region_of_country(country_code: str) -> Region:
    return COUNTRY_TO_REGION.get(country_code.upper(), _DEFAULT_REGION)


def estimate_shipping_cents(seller: Seller, *, location: str, count: int) -> int:
    """Total shipping for ``count`` items from ``seller`` to ``location`` (ISO alpha-2)."""
    if count <= 0:
        return 0
    user_region = region_of_country(location)
    if seller.shipping_policy:
        policy = seller.shipping_policy.get(user_region) or seller.shipping_policy.get("default")
        if policy is not None:
            return policy.first_cents + policy.additional_cents * max(0, count - 1)
    base = REGION_MATRIX_CENTS[seller.region][user_region]
    multiplier = 1.0 + 0.2 * (count - 1)
    return int(base * multiplier)


def shipping_confidence_score(sellers: dict[int, Seller], *, location: str) -> Literal["high", "low"]:
    if not sellers:
        return "high"
    user_region = region_of_country(location)
    have = 0
    for seller in sellers.values():
        if seller.shipping_policy and (seller.shipping_policy.get(user_region) or seller.shipping_policy.get("default")):
            have += 1
    return "high" if have * 100 >= len(sellers) * 80 else "low"
