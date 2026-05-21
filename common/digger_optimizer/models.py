"""Input/output Pydantic types for the digger bundle optimizer.

Condition vocabularies mirror the Postgres enums declared in
``schema-init/digger_schema.py`` (``digger.condition`` and
``digger.sleeve_condition``).

NOTE: deliberately no ``from __future__ import annotations`` — Pydantic resolves
field annotations at runtime, so ``Decimal``/``UUID`` must remain real runtime
imports (matches the ``api/models.py`` convention).
"""

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


Condition = Literal["M", "NM", "VG+", "VG", "G+", "G", "F", "P"]
SleeveCondition = Literal["M", "NM", "VG+", "VG", "G+", "G", "F", "P", "generic", "no_cover"]
BundleName = Literal["cheapest", "most_coverage", "best_quality", "fewest_sellers"]


CONDITION_RANK: dict[str, int] = {
    "M": 8,
    "NM": 7,
    "VG+": 6,
    "VG": 5,
    "G+": 4,
    "G": 3,
    "F": 2,
    "P": 1,
    "generic": 5,  # sleeve-only value
    "no_cover": 1,  # sleeve-only value
}


class ReleaseConstraint(BaseModel):
    release_id: int
    min_media_condition: Condition
    min_sleeve_condition: SleeveCondition
    max_price_cents: int | None = None


class ShippingPolicyRegion(BaseModel):
    first_cents: int
    additional_cents: int
    currency: str = "USD"


class Seller(BaseModel):
    seller_id: int
    region: Literal["us", "ca", "eu", "uk", "jp", "au", "other"]
    country_code: str | None = None
    shipping_policy: dict[str, ShippingPolicyRegion] | None = None
    feedback_score: float | None = None


class Listing(BaseModel):
    listing_id: int
    release_id: int
    seller_id: int
    price_value: Decimal = Field(ge=0)
    price_currency: str
    media_condition: Condition
    sleeve_condition: SleeveCondition


class OptimizerInput(BaseModel):
    user_id: UUID
    location: str = Field(min_length=2, max_length=2, description="ISO-3166 alpha-2")
    currency: str = "USD"
    must_have_releases: list[ReleaseConstraint]
    nice_have_releases: list[ReleaseConstraint] = []
    eventually_releases: list[ReleaseConstraint] = []
    candidate_listings: list[Listing]
    sellers: dict[int, Seller]
    budget_cap_cents: int | None = None
    excluded_sellers: frozenset[int] = frozenset()


class OrderLine(BaseModel):
    listing_id: int
    release_id: int
    price_cents: int
    currency: str
    media_condition: Condition
    sleeve_condition: SleeveCondition


class SellerOrder(BaseModel):
    seller_id: int
    listings: list[OrderLine]
    subtotal_item_cents: int
    shipping_cents: int


class Coverage(BaseModel):
    must: int
    nice: int
    eventually: int


class Bundle(BaseModel):
    name: BundleName
    seller_orders: list[SellerOrder]
    total_item_cost_cents: int
    total_shipping_cents: int
    grand_total_cents: int
    coverage: Coverage
    avg_condition_score: float
    solver: Literal["ilp", "greedy"]
    reasoning_hint: str


class OptimizerDiagnostics(BaseModel):
    solver_used: dict[BundleName, Literal["ilp", "greedy"]]
    solve_time_ms: dict[BundleName, int]
    listings_considered: int
    sellers_considered: int
    partitions: int = 1


class OptimizerOutput(BaseModel):
    bundles: list[Bundle]
    watching: list[int] = []  # release_ids with no qualifying listings
    diagnostics: OptimizerDiagnostics
    shipping_confidence: Literal["high", "low"]
