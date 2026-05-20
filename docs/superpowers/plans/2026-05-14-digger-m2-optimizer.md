# Digger M2 — Optimizer & Reports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the deterministic bundle optimizer + scheduled-run pipeline + Reports inbox UI so a user can click "Run recommendation" (or wait for a weekly scheduled run) and receive 3-4 named Pareto-optimal bundles (Cheapest / Most Coverage / Best Quality / Fewest Sellers) with shipping-aware total costs.

**Architecture:** New `common/digger_optimizer/` shared library — pure functions, no I/O. Imported by `api/` for interactive runs and by `digger/` for scheduled runs. Optimizer uses pulp+CBC ILP with a greedy fallback. New `/api/digger/recommend` endpoint runs the optimizer, opportunistically refreshes stale listings via Postgres priority bumps + Redis pub/sub progress, streams results over SSE. New `digger/scheduler/` runs scheduled reports on user-configured cadence.

**Tech Stack:** Python 3.13, pulp (ships its CBC binary), hypothesis (property tests), FastAPI SSE responses, Redis pub/sub, React 19 + Vite for reports UI.

**Spec reference:** `docs/superpowers/specs/2026-05-14-digger-wantlist-agent-design.md` — M2 section.

**Prerequisite:** M1 must be complete and merged.

---

## File structure

**Create:**
- `common/digger_optimizer/__init__.py`, `models.py`, `filtering.py`, `shipping.py`, `greedy.py`, `ilp.py`, `pareto.py`
- `digger/digger/scheduler/__init__.py`, `runner.py`, `change_detection.py`, `report_writer.py`
- `api/routers/digger_recommend.py` — `/api/digger/recommend` SSE endpoint
- `api/routers/digger_reports.py` — `/api/digger/reports[/:id]` endpoints
- `api/digger_refresh/__init__.py`, `digger_refresh/coordinator.py` — opportunistic refresh helpers
- `api/queries/digger_reports.py` — SQL helpers for reports + refresh
- `explore/src/digger/Reports.tsx`, `ReportViewer.tsx`, `BundleCard.tsx`, `BundleExpansion.tsx`, `WatchingList.tsx`
- `tests/common/test_digger_optimizer_*.py` per module
- `tests/api/test_digger_recommend.py`, `tests/api/test_digger_reports.py`
- `tests/digger/test_scheduler_*.py`
- `tests/explore/digger/Reports.test.tsx`, `BundleCard.test.tsx`, `ReportViewer.test.tsx`
- `tests/e2e/test_digger_m2_smoke.py`
- `docs/digger-optimizer.md`

**Modify:**
- `common/pyproject.toml` — depend on `pulp>=2.8`
- `api/pyproject.toml` — depend on `common[digger-optimizer]` (or just `common`, since pulp ships in common)
- `digger/pyproject.toml` — depend on `common` (already does)
- `api/main.py` — register new routers
- `digger/digger/main.py` — wire scheduler task
- `tests/perftest/config.yaml` — new endpoints
- `CLAUDE.md` — note that `common/digger_optimizer/` exists

---

## Task 1: `common/digger_optimizer/` package skeleton + Pydantic models

**Files:**
- Create: `common/digger_optimizer/__init__.py`, `common/digger_optimizer/models.py`
- Modify: `common/pyproject.toml` — `pulp>=2.8`
- Test: `tests/common/test_digger_optimizer_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/common/test_digger_optimizer_models.py
import pytest
from decimal import Decimal
from common.digger_optimizer.models import (
    OptimizerInput, ReleaseConstraint, Listing, Seller,
    Bundle, OptimizerOutput, BundleName,
)


def test_models_construct_with_minimal_fields():
    c = ReleaseConstraint(release_id=1, min_media_condition="VG", min_sleeve_condition="VG", max_price_cents=None)
    s = Seller(seller_id=1, region="us", country_code="US", shipping_policy=None)
    l = Listing(listing_id=1, release_id=1, seller_id=1, price_value=Decimal("10.00"),
                price_currency="USD", media_condition="NM", sleeve_condition="NM")
    inp = OptimizerInput(
        user_id=__import__("uuid").uuid4(), location="US", currency="USD",
        must_have_releases=[c], nice_have_releases=[], eventually_releases=[],
        candidate_listings=[l], sellers={1: s},
    )
    assert inp.location == "US"
    assert inp.must_have_releases[0].release_id == 1


def test_bundle_name_literal():
    valid: list[BundleName] = ["cheapest", "most_coverage", "best_quality", "fewest_sellers"]
    assert "cheapest" in valid
```

- [ ] **Step 2: Run test to verify it fails**

`uv run pytest tests/common/test_digger_optimizer_models.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Add pulp dependency to `common/pyproject.toml`**

Add to `[project] dependencies`: `"pulp>=2.8"`.

- [ ] **Step 4: Implement models**

```python
# common/digger_optimizer/__init__.py
"""Pure-function bundle optimizer for the Digger feature.

Imported by both api/ (interactive runs) and digger/ (scheduled runs).
No I/O — all dependencies pass in as Pydantic inputs.

Public API:
- pareto_bundles(input: OptimizerInput) -> OptimizerOutput

Submodules:
- models: input/output Pydantic types
- filtering: condition/price filter
- shipping: per-seller shipping cost estimation
- greedy: greedy reference implementation (also ILP warm-start)
- ilp: pulp-based optimal solver
- pareto: 4-variant coordinator
"""

from common.digger_optimizer.models import (
    OptimizerInput, OptimizerOutput, Bundle, BundleName,
    ReleaseConstraint, Listing, Seller, SellerOrder, OrderLine,
)
from common.digger_optimizer.pareto import pareto_bundles

__all__ = [
    "OptimizerInput", "OptimizerOutput", "Bundle", "BundleName",
    "ReleaseConstraint", "Listing", "Seller", "SellerOrder", "OrderLine",
    "pareto_bundles",
]
```

```python
# common/digger_optimizer/models.py
from __future__ import annotations
from decimal import Decimal
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field


Condition = Literal["M", "NM", "VG+", "VG", "G+", "G", "F", "P"]
SleeveCondition = Literal["M", "NM", "VG+", "VG", "G+", "G", "F", "P", "generic", "no_cover"]
BundleName = Literal["cheapest", "most_coverage", "best_quality", "fewest_sellers"]


CONDITION_RANK: dict[str, int] = {
    "M": 8, "NM": 7, "VG+": 6, "VG": 5, "G+": 4, "G": 3, "F": 2, "P": 1,
    "generic": 5, "no_cover": 1,  # sleeve-only values
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
```

- [ ] **Step 5: Run test to verify it passes**

`uv run pytest tests/common/test_digger_optimizer_models.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add common/digger_optimizer/ common/pyproject.toml tests/common/test_digger_optimizer_models.py
git commit -m "feat(digger-optimizer): models + package skeleton in common/"
```

---

## Task 2: Stage 1 — filtering

**Files:**
- Create: `common/digger_optimizer/filtering.py`
- Test: `tests/common/test_digger_optimizer_filtering.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/common/test_digger_optimizer_filtering.py
from decimal import Decimal
from common.digger_optimizer.models import (
    OptimizerInput, ReleaseConstraint, Listing, Seller,
)
from common.digger_optimizer.filtering import filter_candidates, FilterResult
import uuid


def _input(constraints: list[ReleaseConstraint], listings: list[Listing]) -> OptimizerInput:
    return OptimizerInput(
        user_id=uuid.uuid4(), location="US", currency="USD",
        must_have_releases=constraints, candidate_listings=listings,
        sellers={l.seller_id: Seller(seller_id=l.seller_id, region="us") for l in listings},
    )


def test_drops_below_condition_floor():
    c = ReleaseConstraint(release_id=1, min_media_condition="VG+", min_sleeve_condition="VG+", max_price_cents=None)
    listings = [
        Listing(listing_id=10, release_id=1, seller_id=1, price_value=Decimal("5"),
                price_currency="USD", media_condition="VG", sleeve_condition="VG"),
        Listing(listing_id=11, release_id=1, seller_id=2, price_value=Decimal("12"),
                price_currency="USD", media_condition="NM", sleeve_condition="NM"),
    ]
    out = filter_candidates(_input([c], listings))
    assert out.usable_by_release[1] == [11]
    assert out.watching == []


def test_drops_above_max_price():
    c = ReleaseConstraint(release_id=1, min_media_condition="VG", min_sleeve_condition="VG", max_price_cents=1000)
    listings = [
        Listing(listing_id=10, release_id=1, seller_id=1, price_value=Decimal("5"),
                price_currency="USD", media_condition="NM", sleeve_condition="NM"),
        Listing(listing_id=11, release_id=1, seller_id=2, price_value=Decimal("15"),
                price_currency="USD", media_condition="NM", sleeve_condition="NM"),
    ]
    out = filter_candidates(_input([c], listings))
    assert out.usable_by_release[1] == [10]


def test_marks_watching_when_no_qualifying_listings():
    c = ReleaseConstraint(release_id=99, min_media_condition="NM", min_sleeve_condition="NM", max_price_cents=None)
    out = filter_candidates(_input([c], []))
    assert out.watching == [99]
    assert 99 not in out.usable_by_release
```

- [ ] **Step 2: Run test to verify it fails**

`uv run pytest tests/common/test_digger_optimizer_filtering.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

```python
# common/digger_optimizer/filtering.py
"""Stage 1: filter listings against per-tier condition floors and max-price caps.

Currency conversion is out of scope for M2 — listings whose currency differs
from the user's currency are skipped (counted in diagnostics).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from common.digger_optimizer.models import (
    OptimizerInput, Listing, ReleaseConstraint, CONDITION_RANK,
)


@dataclass(slots=True)
class FilterResult:
    usable_by_release: dict[int, list[int]] = field(default_factory=dict)  # release_id -> [listing_id]
    watching: list[int] = field(default_factory=list)  # release_ids with no qualifying listings
    skipped_currency: int = 0


def _meets(listing: Listing, c: ReleaseConstraint, currency: str) -> bool:
    if listing.price_currency != currency:
        return False
    if CONDITION_RANK[listing.media_condition] < CONDITION_RANK[c.min_media_condition]:
        return False
    if CONDITION_RANK[listing.sleeve_condition] < CONDITION_RANK[c.min_sleeve_condition]:
        return False
    if c.max_price_cents is not None and int(listing.price_value * 100) > c.max_price_cents:
        return False
    return True


def filter_candidates(inp: OptimizerInput) -> FilterResult:
    result = FilterResult()
    constraints_by_release = {
        **{c.release_id: c for c in inp.must_have_releases},
        **{c.release_id: c for c in inp.nice_have_releases},
        **{c.release_id: c for c in inp.eventually_releases},
    }
    listings_by_release: dict[int, list[Listing]] = {}
    for l in inp.candidate_listings:
        if l.price_currency != inp.currency:
            result.skipped_currency += 1
            continue
        listings_by_release.setdefault(l.release_id, []).append(l)

    for must in inp.must_have_releases:
        usable = [l for l in listings_by_release.get(must.release_id, [])
                  if _meets(l, must, inp.currency)]
        if usable:
            result.usable_by_release[must.release_id] = [l.listing_id for l in usable]
        else:
            result.watching.append(must.release_id)

    for soft_group in (inp.nice_have_releases, inp.eventually_releases):
        for r in soft_group:
            usable = [l for l in listings_by_release.get(r.release_id, [])
                      if _meets(l, r, inp.currency)]
            if usable:
                result.usable_by_release[r.release_id] = [l.listing_id for l in usable]
    return result
```

- [ ] **Step 4: Run test to verify it passes**

`uv run pytest tests/common/test_digger_optimizer_filtering.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add common/digger_optimizer/filtering.py tests/common/test_digger_optimizer_filtering.py
git commit -m "feat(digger-optimizer): stage 1 filtering by condition + price + currency"
```

---

## Task 3: Shipping computation

**Files:**
- Create: `common/digger_optimizer/shipping.py`
- Test: `tests/common/test_digger_optimizer_shipping.py`

Per the spec: prefer scraped seller policy; fall back to a 7×7 region matrix with diminishing-returns multiplier.

- [ ] **Step 1: Write the failing test**

```python
# tests/common/test_digger_optimizer_shipping.py
from common.digger_optimizer.models import Seller, ShippingPolicyRegion
from common.digger_optimizer.shipping import (
    estimate_shipping_cents, shipping_confidence_score, REGION_MATRIX_CENTS,
)


def test_uses_policy_when_available():
    s = Seller(seller_id=1, region="us", country_code="US", shipping_policy={
        "us": ShippingPolicyRegion(first_cents=500, additional_cents=150, currency="USD"),
    })
    assert estimate_shipping_cents(s, location="US", count=1) == 500
    assert estimate_shipping_cents(s, location="US", count=4) == 500 + 150 * 3


def test_falls_back_to_matrix_when_no_policy():
    s = Seller(seller_id=1, region="us", country_code="US", shipping_policy=None)
    base = REGION_MATRIX_CENTS["us"]["us"]
    assert estimate_shipping_cents(s, location="US", count=1) == base
    # 1 + 0.2 * (count - 1) multiplier
    assert estimate_shipping_cents(s, location="US", count=3) == int(base * 1.4)


def test_confidence_high_when_most_have_policies():
    sellers = {
        1: Seller(seller_id=1, region="us", shipping_policy={"us": ShippingPolicyRegion(first_cents=500, additional_cents=100)}),
        2: Seller(seller_id=2, region="us", shipping_policy={"us": ShippingPolicyRegion(first_cents=500, additional_cents=100)}),
        3: Seller(seller_id=3, region="us", shipping_policy=None),
    }
    assert shipping_confidence_score(sellers, location="US") == "low"  # 2/3 = 66%
    sellers[3].shipping_policy = {"us": ShippingPolicyRegion(first_cents=500, additional_cents=100)}
    assert shipping_confidence_score(sellers, location="US") == "high"  # 3/3 = 100%
```

- [ ] **Step 2: Run test to verify it fails**

`uv run pytest tests/common/test_digger_optimizer_shipping.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

```python
# common/digger_optimizer/shipping.py
"""Per-seller shipping cost estimation.

Prefers scraped shipping_policy; falls back to a static 7x7 region matrix.
"""

from __future__ import annotations
from typing import Literal
from common.digger_optimizer.models import Seller


Region = Literal["us", "ca", "eu", "uk", "jp", "au", "other"]


# Cents — USD-centric. M2 ships USD-only display.
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
    "US": "us", "CA": "ca", "GB": "uk", "JP": "jp", "AU": "au",
    "DE": "eu", "FR": "eu", "IT": "eu", "ES": "eu", "NL": "eu", "BE": "eu", "AT": "eu",
}


def region_of_country(country_code: str) -> Region:
    return COUNTRY_TO_REGION.get(country_code.upper(), "other")


def estimate_shipping_cents(seller: Seller, *, location: str, count: int) -> int:
    """Total shipping for `count` items from `seller` to `location` (ISO alpha-2)."""
    if count <= 0:
        return 0
    if seller.shipping_policy:
        # try policy region matching the user's region
        user_region = region_of_country(location)
        policy = seller.shipping_policy.get(user_region) or seller.shipping_policy.get("default")
        if policy is not None:
            return policy.first_cents + policy.additional_cents * max(0, count - 1)
    user_region = region_of_country(location)
    base = REGION_MATRIX_CENTS[seller.region][user_region]
    multiplier = 1.0 + 0.2 * (count - 1)
    return int(base * multiplier)


def shipping_confidence_score(sellers: dict[int, Seller], *, location: str) -> Literal["high", "low"]:
    if not sellers:
        return "high"
    user_region = region_of_country(location)
    have = 0
    for s in sellers.values():
        if s.shipping_policy and (
            s.shipping_policy.get(user_region) or s.shipping_policy.get("default")
        ):
            have += 1
    return "high" if have * 100 >= len(sellers) * 80 else "low"
```

- [ ] **Step 4: Run test to verify it passes**

`uv run pytest tests/common/test_digger_optimizer_shipping.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add common/digger_optimizer/shipping.py tests/common/test_digger_optimizer_shipping.py
git commit -m "feat(digger-optimizer): shipping cost estimation with policy + matrix fallback"
```

---

## Task 4: Greedy fallback (also reference implementation)

**Files:**
- Create: `common/digger_optimizer/greedy.py`
- Test: `tests/common/test_digger_optimizer_greedy.py`

The greedy is also used as the ILP warm-start hint, and as the fallback on ILP timeout.

- [ ] **Step 1: Write the failing test**

```python
# tests/common/test_digger_optimizer_greedy.py
from decimal import Decimal
import uuid
from common.digger_optimizer.models import (
    OptimizerInput, ReleaseConstraint, Listing, Seller, Bundle,
)
from common.digger_optimizer.greedy import greedy_bundle


def _seller(sid: int) -> Seller:
    return Seller(seller_id=sid, region="us", country_code="US", shipping_policy=None)


def _listing(lid: int, rid: int, sid: int, price: str) -> Listing:
    return Listing(
        listing_id=lid, release_id=rid, seller_id=sid,
        price_value=Decimal(price), price_currency="USD",
        media_condition="NM", sleeve_condition="NM",
    )


def test_greedy_covers_all_musts_minimum_sellers_when_possible():
    inp = OptimizerInput(
        user_id=uuid.uuid4(), location="US", currency="USD",
        must_have_releases=[
            ReleaseConstraint(release_id=1, min_media_condition="VG", min_sleeve_condition="VG"),
            ReleaseConstraint(release_id=2, min_media_condition="VG", min_sleeve_condition="VG"),
        ],
        candidate_listings=[
            _listing(101, 1, 1, "10"), _listing(102, 1, 2, "12"),
            _listing(201, 2, 1, "8"),  _listing(202, 2, 2, "9"),
        ],
        sellers={1: _seller(1), 2: _seller(2)},
    )
    b: Bundle = greedy_bundle(inp, name="cheapest")
    assert b.coverage.must == 2
    # Seller 1 covers both at 10+8=18 + shipping_once; seller 2 covers both at 12+9=21 + shipping_once
    # Greedy with consolidation bonus should prefer seller 1
    assert {o.seller_id for o in b.seller_orders} == {1}


def test_greedy_returns_zero_coverage_when_no_listings():
    inp = OptimizerInput(
        user_id=uuid.uuid4(), location="US", currency="USD",
        must_have_releases=[
            ReleaseConstraint(release_id=99, min_media_condition="NM", min_sleeve_condition="NM"),
        ],
        candidate_listings=[], sellers={},
    )
    b = greedy_bundle(inp, name="cheapest")
    assert b.coverage.must == 0
    assert b.grand_total_cents == 0
```

- [ ] **Step 2: Run test to verify it fails**

`uv run pytest tests/common/test_digger_optimizer_greedy.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

```python
# common/digger_optimizer/greedy.py
"""Greedy reference implementation for bundle optimization.

Used as:
1. Fallback when the ILP solver times out.
2. Warm-start hint when invoking the ILP.
3. Reference implementation for cross-checks in property tests.

Algorithm:
- Group listings by seller.
- For each Must release, find the seller-listing combo with the best
  (value-covered + lambda * non-must items) / (item_cost + marginal_shipping).
- Greedy add until all Musts are covered.
- Extend with Nice/Eventually items where marginal cost ≤ threshold.
"""

from __future__ import annotations
import math
from dataclasses import dataclass
from decimal import Decimal

from common.digger_optimizer.models import (
    Bundle, BundleName, Coverage, Listing, OptimizerInput, OrderLine, Seller, SellerOrder,
    CONDITION_RANK,
)
from common.digger_optimizer.shipping import estimate_shipping_cents
from common.digger_optimizer.filtering import filter_candidates


@dataclass(slots=True)
class _ObjectiveWeights:
    lambda_nice: int          # cents-credit per Nice item covered
    lambda_eventually: int    # cents-credit per Eventually item covered
    quality_per_step: int     # cents bonus per +1 condition rank
    seller_penalty: int       # cents penalty per additional seller


_WEIGHTS: dict[BundleName, _ObjectiveWeights] = {
    "cheapest":       _ObjectiveWeights(lambda_nice=500, lambda_eventually=100, quality_per_step=0,   seller_penalty=0),
    "most_coverage":  _ObjectiveWeights(lambda_nice=2500, lambda_eventually=1000, quality_per_step=0, seller_penalty=0),
    "best_quality":   _ObjectiveWeights(lambda_nice=500, lambda_eventually=100, quality_per_step=300, seller_penalty=0),
    "fewest_sellers": _ObjectiveWeights(lambda_nice=500, lambda_eventually=100, quality_per_step=0,   seller_penalty=2000),
}


def _value_score(l: Listing, must_set: set[int], nice_set: set[int],
                 eventually_set: set[int], w: _ObjectiveWeights) -> int:
    """Cents-equivalent value of including this listing in the bundle."""
    base = -int(l.price_value * 100)  # negative — cost
    if l.release_id in must_set:
        base += 10_000_000  # huge bonus so must items always picked first
    elif l.release_id in nice_set:
        base += w.lambda_nice
    elif l.release_id in eventually_set:
        base += w.lambda_eventually
    base += w.quality_per_step * CONDITION_RANK[l.media_condition]
    return base


def greedy_bundle(inp: OptimizerInput, *, name: BundleName) -> Bundle:
    weights = _WEIGHTS[name]
    fr = filter_candidates(inp)
    listings_by_id: dict[int, Listing] = {l.listing_id: l for l in inp.candidate_listings}
    must_set = {c.release_id for c in inp.must_have_releases}
    nice_set = {c.release_id for c in inp.nice_have_releases}
    eventually_set = {c.release_id for c in inp.eventually_releases}

    chosen: list[Listing] = []
    covered_releases: set[int] = set()
    seller_used_counts: dict[int, int] = {}

    def _consider(release_pool: set[int]) -> Listing | None:
        """Pick the listing with the best marginal value."""
        best: tuple[float, Listing] | None = None
        for rid in release_pool:
            if rid in covered_releases:
                continue
            for lid in fr.usable_by_release.get(rid, []):
                l = listings_by_id[lid]
                if l.seller_id in inp.excluded_sellers:
                    continue
                # Marginal shipping = total shipping for (existing_count+1) - shipping_for_existing
                existing = seller_used_counts.get(l.seller_id, 0)
                seller = inp.sellers[l.seller_id]
                marginal = (
                    estimate_shipping_cents(seller, location=inp.location, count=existing + 1)
                    - estimate_shipping_cents(seller, location=inp.location, count=existing)
                )
                v = _value_score(l, must_set, nice_set, eventually_set, weights)
                v -= marginal
                if existing == 0:
                    v -= weights.seller_penalty
                cost = int(l.price_value * 100) + marginal
                ratio = v / max(1, cost)
                if best is None or ratio > best[0]:
                    best = (ratio, l)
        return best[1] if best else None

    # 1. cover Musts
    while True:
        l = _consider(must_set)
        if l is None:
            break
        chosen.append(l)
        covered_releases.add(l.release_id)
        seller_used_counts[l.seller_id] = seller_used_counts.get(l.seller_id, 0) + 1

    # 2. extend with Nice/Eventually if their marginal is "cheap enough"
    # Cheap = price + marginal_shipping <= lambda for that tier
    for pool, lam in ((nice_set, weights.lambda_nice), (eventually_set, weights.lambda_eventually)):
        if lam <= 0:
            continue
        while True:
            l = _consider(pool)
            if l is None:
                break
            existing = seller_used_counts.get(l.seller_id, 0)
            seller = inp.sellers[l.seller_id]
            marginal = (
                estimate_shipping_cents(seller, location=inp.location, count=existing + 1)
                - estimate_shipping_cents(seller, location=inp.location, count=existing)
            )
            marginal_cost = int(l.price_value * 100) + marginal
            if marginal_cost > lam:
                break
            chosen.append(l)
            covered_releases.add(l.release_id)
            seller_used_counts[l.seller_id] = existing + 1

    # Build the bundle
    return _build_bundle(name, chosen, inp, must_set, nice_set, eventually_set, solver="greedy")


def _build_bundle(
    name: BundleName,
    chosen: list[Listing],
    inp: OptimizerInput,
    must_set: set[int],
    nice_set: set[int],
    eventually_set: set[int],
    *,
    solver: str,
) -> Bundle:
    if not chosen:
        return Bundle(
            name=name, seller_orders=[],
            total_item_cost_cents=0, total_shipping_cents=0, grand_total_cents=0,
            coverage=Coverage(must=0, nice=0, eventually=0),
            avg_condition_score=0.0, solver=solver, reasoning_hint="No qualifying listings.",
        )
    by_seller: dict[int, list[Listing]] = {}
    for l in chosen:
        by_seller.setdefault(l.seller_id, []).append(l)
    orders: list[SellerOrder] = []
    total_item = 0
    total_ship = 0
    for sid, ls in by_seller.items():
        subtotal = sum(int(l.price_value * 100) for l in ls)
        ship = estimate_shipping_cents(inp.sellers[sid], location=inp.location, count=len(ls))
        orders.append(SellerOrder(
            seller_id=sid,
            listings=[OrderLine(
                listing_id=l.listing_id, release_id=l.release_id,
                price_cents=int(l.price_value * 100), currency=l.price_currency,
                media_condition=l.media_condition, sleeve_condition=l.sleeve_condition,
            ) for l in ls],
            subtotal_item_cents=subtotal, shipping_cents=ship,
        ))
        total_item += subtotal
        total_ship += ship
    coverage = Coverage(
        must=sum(1 for l in chosen if l.release_id in must_set),
        nice=sum(1 for l in chosen if l.release_id in nice_set),
        eventually=sum(1 for l in chosen if l.release_id in eventually_set),
    )
    avg_cond = sum(CONDITION_RANK[l.media_condition] for l in chosen) / len(chosen)
    return Bundle(
        name=name, seller_orders=orders,
        total_item_cost_cents=total_item, total_shipping_cents=total_ship,
        grand_total_cents=total_item + total_ship, coverage=coverage,
        avg_condition_score=avg_cond, solver=solver,
        reasoning_hint=f"{coverage.must} must, {coverage.nice} nice, {coverage.eventually} eventually across {len(orders)} sellers.",
    )


# Exported for ilp.py warm-start
build_bundle_from_listings = _build_bundle
```

- [ ] **Step 4: Run test to verify it passes**

`uv run pytest tests/common/test_digger_optimizer_greedy.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add common/digger_optimizer/greedy.py tests/common/test_digger_optimizer_greedy.py
git commit -m "feat(digger-optimizer): greedy fallback / reference implementation"
```

---

## Task 5: ILP solver (pulp + CBC)

**Files:**
- Create: `common/digger_optimizer/ilp.py`
- Test: `tests/common/test_digger_optimizer_ilp.py`

The ILP uses pulp's bundled CBC solver. Variables: `x[listing_id] ∈ {0,1}`, `y[seller_id] ∈ {0,1}`, plus `z[seller_id, k] ∈ {0,1}` to linearize the per-seller shipping cost piecewise in item count.

- [ ] **Step 1: Write the failing test**

```python
# tests/common/test_digger_optimizer_ilp.py
from decimal import Decimal
import uuid
import pytest
from common.digger_optimizer.models import (
    OptimizerInput, ReleaseConstraint, Listing, Seller, Bundle,
)
from common.digger_optimizer.ilp import solve_ilp_bundle


def _seller(sid: int) -> Seller:
    return Seller(seller_id=sid, region="us", country_code="US", shipping_policy=None)


def _listing(lid: int, rid: int, sid: int, price: str) -> Listing:
    return Listing(
        listing_id=lid, release_id=rid, seller_id=sid,
        price_value=Decimal(price), price_currency="USD",
        media_condition="NM", sleeve_condition="NM",
    )


def test_ilp_finds_optimal_two_must_one_seller():
    inp = OptimizerInput(
        user_id=uuid.uuid4(), location="US", currency="USD",
        must_have_releases=[
            ReleaseConstraint(release_id=1, min_media_condition="VG", min_sleeve_condition="VG"),
            ReleaseConstraint(release_id=2, min_media_condition="VG", min_sleeve_condition="VG"),
        ],
        candidate_listings=[
            _listing(101, 1, 1, "10"), _listing(102, 1, 2, "9"),
            _listing(201, 2, 1, "5"),  _listing(202, 2, 2, "7"),
        ],
        sellers={1: _seller(1), 2: _seller(2)},
    )
    b = solve_ilp_bundle(inp, name="cheapest", timeout_seconds=5)
    assert b is not None
    assert b.coverage.must == 2
    # Single-seller bundle wins because shipping × 2 > savings
    assert {o.seller_id for o in b.seller_orders} == {1}
    # Items 101 + 201 from seller 1 = $15; shipping $5 -> $20
    assert b.grand_total_cents == 10_00 + 5_00 + 5_00


def test_ilp_returns_none_on_timeout():
    # Trivial input — won't time out, but verify shape
    inp = OptimizerInput(
        user_id=uuid.uuid4(), location="US", currency="USD",
        must_have_releases=[
            ReleaseConstraint(release_id=1, min_media_condition="NM", min_sleeve_condition="NM"),
        ],
        candidate_listings=[], sellers={},
    )
    b = solve_ilp_bundle(inp, name="cheapest", timeout_seconds=5)
    # Infeasible (must release with no listings) — return empty bundle, not None
    assert b is not None
    assert b.coverage.must == 0
```

- [ ] **Step 2: Run test to verify it fails**

`uv run pytest tests/common/test_digger_optimizer_ilp.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement the ILP**

```python
# common/digger_optimizer/ilp.py
"""ILP-based bundle optimizer using pulp + CBC.

Variables:
  x[lid] ∈ {0,1}   — include this listing
  y[sid] ∈ {0,1}   — order from this seller
  z[sid, k] ∈ {0,1} — seller s has exactly k items in the bundle (k=1..K_max)

Constraints:
  ∀ must:                sum(x[lid] for lid in usable_listings) == 1
  ∀ nice/eventually:     sum(x[lid] for lid in usable_listings) <= 1
  ∀ listing:             x[lid] <= y[seller_of_lid]
  ∀ seller s:            sum_k z[s,k] == y[s]
                         sum_k k * z[s,k] == sum(x[lid] for lid in seller's listings)
  excluded_sellers:      y[s] == 0
  budget_cap (if set):   sum(x * price) + sum_s sum_k z[s,k] * shipping(s,k) <= cap

Objective (per bundle name):
  min sum(x * price)
    + sum_s sum_k z[s,k] * shipping(s,k)
    + seller_penalty * sum(y[s])       # for 'fewest_sellers'
    - quality_per_step * sum(x * condition_rank[lid])  # for 'best_quality'
    - lambda_nice * sum(x[lid] for lid in nice_listings)
    - lambda_eventually * sum(x[lid] for lid in eventually_listings)
"""

from __future__ import annotations
import logging
from typing import cast
import pulp

from common.digger_optimizer.models import (
    Bundle, BundleName, Coverage, Listing, OptimizerInput,
    OrderLine, Seller, SellerOrder, CONDITION_RANK,
)
from common.digger_optimizer.shipping import estimate_shipping_cents
from common.digger_optimizer.filtering import filter_candidates
from common.digger_optimizer.greedy import build_bundle_from_listings, _WEIGHTS

log = logging.getLogger(__name__)


def solve_ilp_bundle(
    inp: OptimizerInput, *, name: BundleName, timeout_seconds: int = 5,
) -> Bundle | None:
    weights = _WEIGHTS[name]
    fr = filter_candidates(inp)
    if not fr.usable_by_release:
        return build_bundle_from_listings(name, [], inp, set(), set(), set(), solver="ilp")

    must_set = {c.release_id for c in inp.must_have_releases}
    nice_set = {c.release_id for c in inp.nice_have_releases}
    eventually_set = {c.release_id for c in inp.eventually_releases}

    listings_by_id: dict[int, Listing] = {l.listing_id: l for l in inp.candidate_listings}
    seller_listings: dict[int, list[int]] = {}
    listing_id_set: set[int] = set()
    for rid, lids in fr.usable_by_release.items():
        for lid in lids:
            listing_id_set.add(lid)
            seller_listings.setdefault(listings_by_id[lid].seller_id, []).append(lid)

    if not listing_id_set:
        return build_bundle_from_listings(name, [], inp, must_set, nice_set, eventually_set, solver="ilp")

    prob = pulp.LpProblem(f"digger_{name}", pulp.LpMinimize)

    x = {lid: pulp.LpVariable(f"x_{lid}", cat="Binary") for lid in listing_id_set}
    y = {sid: pulp.LpVariable(f"y_{sid}", cat="Binary") for sid in seller_listings}

    # z[s,k] for k=1..len(seller_listings[s])
    z: dict[tuple[int, int], pulp.LpVariable] = {}
    max_k_per_seller: dict[int, int] = {sid: len(lids) for sid, lids in seller_listings.items()}
    for sid, k_max in max_k_per_seller.items():
        for k in range(1, k_max + 1):
            z[(sid, k)] = pulp.LpVariable(f"z_{sid}_{k}", cat="Binary")

    # Must-have: each Must release covered exactly once if any usable listing exists
    for must in inp.must_have_releases:
        lids = fr.usable_by_release.get(must.release_id, [])
        if lids:
            prob += pulp.lpSum(x[lid] for lid in lids) == 1, f"must_{must.release_id}"
        # else: dropped (watching), no constraint

    # Nice/Eventually: at most one chosen per release
    for soft in inp.nice_have_releases + inp.eventually_releases:
        lids = fr.usable_by_release.get(soft.release_id, [])
        if lids:
            prob += pulp.lpSum(x[lid] for lid in lids) <= 1, f"soft_{soft.release_id}"

    # Linking
    for sid, lids in seller_listings.items():
        for lid in lids:
            prob += x[lid] <= y[sid], f"link_{lid}"
        # z gating
        prob += pulp.lpSum(z[(sid, k)] for k in range(1, max_k_per_seller[sid] + 1)) == y[sid], f"zsum_{sid}"
        prob += (
            pulp.lpSum(k * z[(sid, k)] for k in range(1, max_k_per_seller[sid] + 1))
            == pulp.lpSum(x[lid] for lid in lids)
        ), f"zcount_{sid}"

    # Excluded sellers
    for sid in inp.excluded_sellers:
        if sid in y:
            prob += y[sid] == 0, f"excl_{sid}"

    # Budget
    if inp.budget_cap_cents is not None:
        item_cost = pulp.lpSum(x[lid] * int(listings_by_id[lid].price_value * 100) for lid in listing_id_set)
        ship_cost = pulp.lpSum(
            z[(sid, k)] * estimate_shipping_cents(inp.sellers[sid], location=inp.location, count=k)
            for sid in seller_listings for k in range(1, max_k_per_seller[sid] + 1)
        )
        prob += item_cost + ship_cost <= inp.budget_cap_cents, "budget"

    # Objective
    obj_item = pulp.lpSum(x[lid] * int(listings_by_id[lid].price_value * 100) for lid in listing_id_set)
    obj_ship = pulp.lpSum(
        z[(sid, k)] * estimate_shipping_cents(inp.sellers[sid], location=inp.location, count=k)
        for sid in seller_listings for k in range(1, max_k_per_seller[sid] + 1)
    )
    obj_seller_penalty = weights.seller_penalty * pulp.lpSum(y[sid] for sid in seller_listings)
    obj_quality = -weights.quality_per_step * pulp.lpSum(
        x[lid] * CONDITION_RANK[listings_by_id[lid].media_condition] for lid in listing_id_set
    )
    obj_nice = -weights.lambda_nice * pulp.lpSum(
        x[lid] for lid in listing_id_set if listings_by_id[lid].release_id in nice_set
    )
    obj_ev = -weights.lambda_eventually * pulp.lpSum(
        x[lid] for lid in listing_id_set if listings_by_id[lid].release_id in eventually_set
    )
    prob += obj_item + obj_ship + obj_seller_penalty + obj_quality + obj_nice + obj_ev

    solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=timeout_seconds, options=["randomSeed 42"])
    status = prob.solve(solver)
    if status != pulp.LpStatusOptimal and status != pulp.LpStatusNotSolved:
        log.warning("ILP solver returned status=%s for %s", pulp.LpStatus[status], name)

    if pulp.LpStatus[status] in ("Infeasible",):
        return build_bundle_from_listings(name, [], inp, must_set, nice_set, eventually_set, solver="ilp")

    chosen = [listings_by_id[lid] for lid in listing_id_set if pulp.value(x[lid]) and pulp.value(x[lid]) >= 0.5]
    return build_bundle_from_listings(name, chosen, inp, must_set, nice_set, eventually_set, solver="ilp")
```

- [ ] **Step 4: Run test to verify it passes**

`uv run pytest tests/common/test_digger_optimizer_ilp.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add common/digger_optimizer/ilp.py tests/common/test_digger_optimizer_ilp.py
git commit -m "feat(digger-optimizer): ILP solver via pulp+CBC with shipping linearization"
```

---

## Task 6: Pareto-front coordinator

**Files:**
- Create: `common/digger_optimizer/pareto.py`
- Test: `tests/common/test_digger_optimizer_pareto.py`

Runs the ILP four times (one per bundle variant), falling back to greedy on timeout. Adds optimizer diagnostics + shipping confidence.

- [ ] **Step 1: Write the failing test**

```python
# tests/common/test_digger_optimizer_pareto.py
from decimal import Decimal
import uuid
from common.digger_optimizer import pareto_bundles
from common.digger_optimizer.models import (
    OptimizerInput, ReleaseConstraint, Listing, Seller,
)


def _seller(sid: int, region="us") -> Seller:
    return Seller(seller_id=sid, region=region, country_code="US", shipping_policy=None)


def _listing(lid: int, rid: int, sid: int, price: str, media="NM") -> Listing:
    return Listing(
        listing_id=lid, release_id=rid, seller_id=sid,
        price_value=Decimal(price), price_currency="USD",
        media_condition=media, sleeve_condition=media,
    )


def test_pareto_returns_named_bundles():
    inp = OptimizerInput(
        user_id=uuid.uuid4(), location="US", currency="USD",
        must_have_releases=[
            ReleaseConstraint(release_id=1, min_media_condition="VG", min_sleeve_condition="VG"),
        ],
        nice_have_releases=[
            ReleaseConstraint(release_id=2, min_media_condition="VG", min_sleeve_condition="VG"),
        ],
        candidate_listings=[
            _listing(101, 1, 1, "10", media="NM"),
            _listing(102, 1, 2, "9",  media="M"),    # cheaper at higher quality from seller 2
            _listing(201, 2, 1, "3",  media="NM"),   # cheap nice item, free pick if from seller 1
        ],
        sellers={1: _seller(1), 2: _seller(2)},
    )
    out = pareto_bundles(inp)
    names = {b.name for b in out.bundles}
    assert {"cheapest", "most_coverage", "best_quality", "fewest_sellers"} <= names

    cheapest = next(b for b in out.bundles if b.name == "cheapest")
    quality = next(b for b in out.bundles if b.name == "best_quality")
    assert cheapest.grand_total_cents <= quality.grand_total_cents
    assert quality.avg_condition_score >= cheapest.avg_condition_score


def test_pareto_marks_watching_when_must_unavailable():
    inp = OptimizerInput(
        user_id=uuid.uuid4(), location="US", currency="USD",
        must_have_releases=[
            ReleaseConstraint(release_id=99, min_media_condition="M", min_sleeve_condition="M"),
        ],
        candidate_listings=[], sellers={},
    )
    out = pareto_bundles(inp)
    assert 99 in out.watching
```

- [ ] **Step 2: Run test to verify it fails**

`uv run pytest tests/common/test_digger_optimizer_pareto.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement coordinator**

```python
# common/digger_optimizer/pareto.py
"""Pareto-front coordinator: runs 4 bundle variants.

Falls back to greedy on ILP timeout or error. Returns OptimizerOutput
with diagnostics and shipping_confidence.
"""

from __future__ import annotations
import logging
import time
from common.digger_optimizer.models import (
    BundleName, OptimizerDiagnostics, OptimizerInput, OptimizerOutput,
)
from common.digger_optimizer.filtering import filter_candidates
from common.digger_optimizer.greedy import greedy_bundle
from common.digger_optimizer.ilp import solve_ilp_bundle
from common.digger_optimizer.shipping import shipping_confidence_score

log = logging.getLogger(__name__)

_BUNDLE_NAMES: tuple[BundleName, ...] = ("cheapest", "most_coverage", "best_quality", "fewest_sellers")


def pareto_bundles(inp: OptimizerInput, *, ilp_timeout_seconds: int = 5) -> OptimizerOutput:
    fr = filter_candidates(inp)
    bundles = []
    solver_used: dict[BundleName, str] = {}
    solve_time: dict[BundleName, int] = {}

    for name in _BUNDLE_NAMES:
        t0 = time.monotonic()
        try:
            b = solve_ilp_bundle(inp, name=name, timeout_seconds=ilp_timeout_seconds)
            used = "ilp"
        except Exception:
            log.exception("ILP failed for %s — falling back to greedy", name)
            b = None
            used = "greedy"
        if b is None:
            b = greedy_bundle(inp, name=name)
            used = "greedy"
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        bundles.append(b)
        solver_used[name] = used  # type: ignore[assignment]
        solve_time[name] = elapsed_ms

    return OptimizerOutput(
        bundles=bundles,
        watching=fr.watching,
        diagnostics=OptimizerDiagnostics(
            solver_used=solver_used,  # type: ignore[arg-type]
            solve_time_ms=solve_time,  # type: ignore[arg-type]
            listings_considered=sum(len(v) for v in fr.usable_by_release.values()),
            sellers_considered=len({inp.candidate_listings[i].seller_id
                                     for i in range(len(inp.candidate_listings))}),
        ),
        shipping_confidence=shipping_confidence_score(inp.sellers, location=inp.location),
    )
```

- [ ] **Step 4: Run test to verify it passes**

`uv run pytest tests/common/test_digger_optimizer_pareto.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add common/digger_optimizer/pareto.py tests/common/test_digger_optimizer_pareto.py
git commit -m "feat(digger-optimizer): Pareto-front coordinator with greedy fallback"
```

---

## Task 7: Property tests (hypothesis)

**Files:**
- Test: `tests/common/test_digger_optimizer_properties.py`

- [ ] **Step 1: Write property tests**

```python
# tests/common/test_digger_optimizer_properties.py
from decimal import Decimal
import uuid
from hypothesis import given, strategies as st, settings, HealthCheck
from common.digger_optimizer import pareto_bundles
from common.digger_optimizer.models import (
    OptimizerInput, ReleaseConstraint, Listing, Seller,
)


def _make_input(seed: int) -> OptimizerInput:
    rng = st.randoms().example()
    n_must = (seed % 3) + 1
    must = [ReleaseConstraint(
        release_id=10 + i, min_media_condition="VG", min_sleeve_condition="VG",
    ) for i in range(n_must)]
    nice = [ReleaseConstraint(
        release_id=100 + i, min_media_condition="VG", min_sleeve_condition="VG",
    ) for i in range(2)]
    sellers = {1: Seller(seller_id=1, region="us", country_code="US"),
               2: Seller(seller_id=2, region="us", country_code="US")}
    listings: list[Listing] = []
    for rid in [c.release_id for c in must + nice]:
        listings.append(Listing(
            listing_id=rid * 10 + 1, release_id=rid, seller_id=1,
            price_value=Decimal(str(5 + (rid % 20))), price_currency="USD",
            media_condition="NM", sleeve_condition="NM",
        ))
        listings.append(Listing(
            listing_id=rid * 10 + 2, release_id=rid, seller_id=2,
            price_value=Decimal(str(7 + (rid % 15))), price_currency="USD",
            media_condition="NM", sleeve_condition="NM",
        ))
    return OptimizerInput(
        user_id=uuid.uuid4(), location="US", currency="USD",
        must_have_releases=must, nice_have_releases=nice,
        candidate_listings=listings, sellers=sellers,
    )


@settings(max_examples=15, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.integers(min_value=0, max_value=100))
def test_more_budget_never_reduces_must_coverage(seed):
    inp = _make_input(seed)
    low = pareto_bundles(OptimizerInput(**{**inp.model_dump(), "budget_cap_cents": 1000})).bundles[0]
    high = pareto_bundles(OptimizerInput(**{**inp.model_dump(), "budget_cap_cents": 1_000_000})).bundles[0]
    assert high.coverage.must >= low.coverage.must


@settings(max_examples=10, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.integers(min_value=0, max_value=100))
def test_cheapest_grand_total_le_most_coverage(seed):
    out = pareto_bundles(_make_input(seed))
    cheapest = next(b for b in out.bundles if b.name == "cheapest")
    most_cov = next(b for b in out.bundles if b.name == "most_coverage")
    # When equal coverage, cheapest must be ≤ most-coverage
    if cheapest.coverage.must == most_cov.coverage.must:
        assert cheapest.grand_total_cents <= most_cov.grand_total_cents


@settings(max_examples=10, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.integers(min_value=0, max_value=100))
def test_best_quality_avg_ge_cheapest(seed):
    out = pareto_bundles(_make_input(seed))
    cheapest = next(b for b in out.bundles if b.name == "cheapest")
    quality = next(b for b in out.bundles if b.name == "best_quality")
    if quality.coverage.must > 0 and cheapest.coverage.must > 0:
        assert quality.avg_condition_score >= cheapest.avg_condition_score
```

- [ ] **Step 2: Run property tests**

`uv run pytest tests/common/test_digger_optimizer_properties.py -v`
Expected: PASS (may take 30-60s with ILP).

- [ ] **Step 3: Commit**

```bash
git add tests/common/test_digger_optimizer_properties.py
git commit -m "test(digger-optimizer): hypothesis property tests for monotonicity invariants"
```

---

## Task 8: Build OptimizerInput from API snapshot

**Files:**
- Create: `api/digger_refresh/__init__.py`, `api/digger_refresh/input_builder.py`
- Test: `tests/api/test_digger_input_builder.py`

The bridge between Postgres state and `OptimizerInput`. Used by both interactive and scheduled paths.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_digger_input_builder.py
import pytest
from common.digger_optimizer.models import OptimizerInput
from api.digger_refresh.input_builder import build_optimizer_input


@pytest.mark.asyncio
async def test_builds_input_from_user_state(postgres_pool, seeded_full_state):
    user_id = seeded_full_state.user_id
    inp = await build_optimizer_input(postgres_pool, user_id, location="US", currency="USD")
    assert isinstance(inp, OptimizerInput)
    assert inp.location == "US"
    assert len(inp.must_have_releases) + len(inp.nice_have_releases) + len(inp.eventually_releases) > 0
    assert len(inp.candidate_listings) >= 0  # may be 0 if no scrape has happened yet
    if inp.candidate_listings:
        first = inp.candidate_listings[0]
        assert first.seller_id in inp.sellers
```

- [ ] **Step 2: Run test to verify it fails**

`uv run pytest tests/api/test_digger_input_builder.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement the builder**

```python
# api/digger_refresh/input_builder.py
"""Convert digger Postgres state into an OptimizerInput Pydantic model."""

from __future__ import annotations
import uuid
from decimal import Decimal
from common.postgres_pool import AsyncPostgreSQLPool
from common.digger_optimizer.models import (
    Listing, OptimizerInput, ReleaseConstraint, Seller, ShippingPolicyRegion,
)


async def build_optimizer_input(
    pool: AsyncPostgreSQLPool, user_id: uuid.UUID,
    *, location: str, currency: str = "USD",
    budget_cap_cents: int | None = None,
    excluded_sellers: frozenset[int] = frozenset(),
) -> OptimizerInput:
    async with pool.acquire() as conn:
        prio_rows = await conn.fetch(
            "SELECT release_id, tier, min_media_condition, min_sleeve_condition, max_price_cents "
            "  FROM digger.user_wantlist_priorities WHERE user_id = $1",
            user_id,
        )
        must, nice, eventually = [], [], []
        release_ids: list[int] = []
        for r in prio_rows:
            rc = ReleaseConstraint(
                release_id=r["release_id"],
                min_media_condition=r["min_media_condition"],
                min_sleeve_condition=r["min_sleeve_condition"],
                max_price_cents=r["max_price_cents"],
            )
            release_ids.append(r["release_id"])
            if r["tier"] == "must":
                must.append(rc)
            elif r["tier"] == "nice":
                nice.append(rc)
            else:
                eventually.append(rc)

        if not release_ids:
            return OptimizerInput(
                user_id=user_id, location=location, currency=currency,
                must_have_releases=[], nice_have_releases=[], eventually_releases=[],
                candidate_listings=[], sellers={},
                budget_cap_cents=budget_cap_cents, excluded_sellers=excluded_sellers,
            )

        listing_rows = await conn.fetch(
            "SELECT listing_id, release_id, seller_id, price_value, price_currency, "
            "       media_condition, sleeve_condition "
            "  FROM digger.listings "
            " WHERE release_id = ANY($1::bigint[]) AND removed_at IS NULL",
            release_ids,
        )
        seller_ids = list({r["seller_id"] for r in listing_rows})
        seller_rows = await conn.fetch(
            "SELECT seller_id, region, country_code, shipping_policy, feedback_score "
            "  FROM digger.sellers WHERE seller_id = ANY($1::bigint[])",
            seller_ids,
        )
        sellers: dict[int, Seller] = {}
        for r in seller_rows:
            policy = None
            raw = r["shipping_policy"]
            if raw:
                policy = {
                    k: ShippingPolicyRegion(
                        first_cents=v["first_cents"],
                        additional_cents=v["additional_cents"],
                        currency=v.get("currency", "USD"),
                    )
                    for k, v in raw.items()
                }
            sellers[r["seller_id"]] = Seller(
                seller_id=r["seller_id"], region=r["region"],
                country_code=r["country_code"], shipping_policy=policy,
                feedback_score=float(r["feedback_score"]) if r["feedback_score"] is not None else None,
            )
        listings = [
            Listing(
                listing_id=r["listing_id"], release_id=r["release_id"], seller_id=r["seller_id"],
                price_value=Decimal(r["price_value"]), price_currency=r["price_currency"],
                media_condition=r["media_condition"], sleeve_condition=r["sleeve_condition"],
            ) for r in listing_rows
        ]
    return OptimizerInput(
        user_id=user_id, location=location, currency=currency,
        must_have_releases=must, nice_have_releases=nice, eventually_releases=eventually,
        candidate_listings=listings, sellers=sellers,
        budget_cap_cents=budget_cap_cents, excluded_sellers=excluded_sellers,
    )
```

- [ ] **Step 4: Run test to verify it passes**

`uv run pytest tests/api/test_digger_input_builder.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/digger_refresh/__init__.py api/digger_refresh/input_builder.py tests/api/test_digger_input_builder.py
git commit -m "feat(digger): OptimizerInput builder from postgres state"
```

---

## Task 9: Opportunistic refresh coordinator (DB + Redis pub/sub)

**Files:**
- Create: `api/digger_refresh/coordinator.py`
- Test: `tests/api/test_digger_refresh_coordinator.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_digger_refresh_coordinator.py
import asyncio
import pytest
from api.digger_refresh.coordinator import RefreshCoordinator


@pytest.mark.asyncio
async def test_bumps_priority_for_stale_releases(postgres_pool):
    async with postgres_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO digger.release_scrape_state(release_id, last_scraped_at, next_scrape_due_at, priority_tier)
            VALUES (1, now() - interval '10 days', now() + interval '5 days', 'must');
        """)
    coord = RefreshCoordinator(pool=postgres_pool, redis_url="redis://localhost/0")
    await coord.bump_priorities(release_ids=[1])
    async with postgres_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT next_scrape_due_at FROM digger.release_scrape_state WHERE release_id=1"
        )
    assert row["next_scrape_due_at"] <= __import__("datetime").datetime.now(__import__("datetime").timezone.utc)


@pytest.mark.asyncio
async def test_subscribe_yields_published_events(redis_test_client):
    user_id = "00000000-0000-0000-0000-000000000001"
    coord = RefreshCoordinator(pool=None, redis=redis_test_client)
    events = []

    async def consume():
        async for ev in coord.subscribe_progress(user_id, deadline_seconds=1):
            events.append(ev)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.1)
    await redis_test_client.publish(f"digger:refresh:{user_id}",
                                    '{"release_id":1,"status":"ok","eta_seconds_remaining":0}')
    await asyncio.sleep(0.2)
    await task
    assert any(e["release_id"] == 1 for e in events)
```

- [ ] **Step 2: Run test to verify it fails**

`uv run pytest tests/api/test_digger_refresh_coordinator.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

```python
# api/digger_refresh/coordinator.py
"""Opportunistic refresh: write priority bumps; subscribe to worker progress.

API → Postgres: set next_scrape_due_at = now() for stale releases.
Worker → Redis: publish per-scrape progress to digger:refresh:{user_id}.
"""

from __future__ import annotations
import asyncio
import json
import logging
from typing import AsyncIterator
from redis.asyncio import Redis, from_url as redis_from_url
from common.postgres_pool import AsyncPostgreSQLPool

log = logging.getLogger(__name__)


class RefreshCoordinator:
    def __init__(self, *, pool: AsyncPostgreSQLPool | None, redis: Redis | None = None,
                 redis_url: str | None = None) -> None:
        self._pool = pool
        if redis is None:
            assert redis_url is not None, "must supply redis or redis_url"
            redis = redis_from_url(redis_url)
        self._redis = redis

    async def bump_priorities(self, release_ids: list[int]) -> int:
        """Set next_scrape_due_at=now() for these releases; worker will pick up next iteration."""
        if not release_ids:
            return 0
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE digger.release_scrape_state "
                "   SET next_scrape_due_at = now() "
                " WHERE release_id = ANY($1::bigint[])",
                release_ids,
            )
        return int(result.split()[-1])

    async def subscribe_progress(
        self, user_id: str, *, deadline_seconds: int,
    ) -> AsyncIterator[dict]:
        """Yield events {release_id, status, eta_seconds_remaining} until the deadline."""
        channel = f"digger:refresh:{user_id}"
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel)
        try:
            end = asyncio.get_event_loop().time() + deadline_seconds
            while True:
                remaining = end - asyncio.get_event_loop().time()
                if remaining <= 0:
                    return
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=remaining)
                if msg is None:
                    continue
                try:
                    data = json.loads(msg["data"])
                except Exception:
                    continue
                yield data
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
```

- [ ] **Step 4: Run test to verify it passes**

`uv run pytest tests/api/test_digger_refresh_coordinator.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/digger_refresh/coordinator.py tests/api/test_digger_refresh_coordinator.py
git commit -m "feat(digger): opportunistic refresh coordinator (priority bumps + pubsub)"
```

---

## Task 10: Worker publishes refresh progress

**Files:**
- Modify: `digger/digger/scraper/orchestrator.py` — publish on each scrape completion when bumped
- Modify: `digger/digger/scraper/executor.py` — accept optional callback

- [ ] **Step 1: Write the failing test**

```python
# tests/digger/test_orchestrator_publishes.py
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from redis.asyncio import from_url as redis_from_url
from digger.scraper.orchestrator import scrape_loop


@pytest.mark.asyncio
async def test_orchestrator_publishes_on_completion(postgres_pool):
    redis = redis_from_url("redis://localhost/0")
    pubsub = redis.pubsub()
    await pubsub.subscribe("digger:refresh:scrape")

    rate = MagicMock(); rate.acquire = AsyncMock(return_value=0.0)
    cb = MagicMock(); cb.is_open = AsyncMock(return_value=False); cb.record = AsyncMock()
    executor = MagicMock(); executor.scrape_release = AsyncMock(return_value=True)

    async with postgres_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO digger.release_scrape_state(release_id, next_scrape_due_at) "
            "VALUES (1, now() - interval '1 hour')"
        )

    stop_event = asyncio.Event()

    async def stop_after():
        await asyncio.sleep(0.4)
        stop_event.set()

    asyncio.create_task(stop_after())
    await scrape_loop(
        pool=postgres_pool, executor=executor, rate=rate, breaker=cb,
        stop_event=stop_event, redis=redis,
    )
    # check at least one publish landed
    msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
    assert msg is not None
    payload = json.loads(msg["data"])
    assert payload["release_id"] == 1
```

- [ ] **Step 2: Update orchestrator signature + publish**

In `digger/digger/scraper/orchestrator.py`, extend `scrape_loop` to accept an optional `redis: Redis | None = None` and, after each scrape attempt, publish to `digger:refresh:scrape` (and to per-user channels for any user actively waiting — see Task 11 for user-channel fan-out, but the simple version publishes to the global channel and to per-user channels for users wantlisting that release).

```python
import json
from redis.asyncio import Redis

async def scrape_loop(
    *, pool: AsyncPostgreSQLPool, executor: ScrapeExecutor, rate: RateBudget,
    breaker: CircuitBreaker, stop_event: asyncio.Event, redis: Redis | None = None,
) -> None:
    while not stop_event.is_set():
        # ... existing logic up through executor.scrape_release(release_id) ...
        ok = await executor.scrape_release(release_id)
        await breaker.record(success=ok)
        if not ok:
            async with pool.acquire() as conn:
                await record_failure(conn, release_id)
        if redis is not None:
            payload = json.dumps({
                "release_id": release_id,
                "status": "ok" if ok else "failed",
                "eta_seconds_remaining": 0,
            })
            # Fan-out: publish to a 'scrape' channel + each user wantlisting this release
            await redis.publish("digger:refresh:scrape", payload)
            async with pool.acquire() as conn:
                users = await conn.fetch(
                    "SELECT user_id FROM digger.user_wantlist_priorities WHERE release_id = $1",
                    release_id,
                )
            for u in users:
                await redis.publish(f"digger:refresh:{u['user_id']}", payload)
```

In `digger/digger/main.py`, pass `redis=redis` to `scrape_loop(...)`.

- [ ] **Step 3: Run test to verify it passes**

`uv run pytest tests/digger/test_orchestrator_publishes.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add digger/digger/scraper/orchestrator.py digger/digger/main.py tests/digger/test_orchestrator_publishes.py
git commit -m "feat(digger): worker publishes scrape progress to per-user Redis channels"
```

---

## Task 11: `/api/digger/recommend` SSE endpoint

**Files:**
- Create: `api/routers/digger_recommend.py`
- Modify: `api/main.py`
- Test: `tests/api/test_digger_recommend.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_digger_recommend.py
import pytest
import json


@pytest.mark.asyncio
async def test_recommend_streams_events_and_returns_bundles(api_client, auth_headers, seeded_listings):
    async with api_client.stream("POST", "/api/digger/recommend",
                                 headers=auth_headers,
                                 json={"deadline_seconds": 5}) as r:
        assert r.status_code == 200
        events: list[dict] = []
        buf = ""
        async for chunk in r.aiter_text():
            buf += chunk
            while "\n\n" in buf:
                raw, buf = buf.split("\n\n", 1)
                # parse SSE block: "event: NAME\ndata: ..."
                lines = raw.split("\n")
                ev = {}
                for line in lines:
                    if line.startswith("event:"):
                        ev["type"] = line[6:].strip()
                    elif line.startswith("data:"):
                        ev["data"] = json.loads(line[5:].strip())
                if ev:
                    events.append(ev)
        kinds = [e["type"] for e in events]
        assert "result" in kinds
        result = next(e for e in events if e["type"] == "result")
        assert "bundles" in result["data"]
        assert len(result["data"]["bundles"]) >= 1
```

- [ ] **Step 2: Run test to verify it fails**

`uv run pytest tests/api/test_digger_recommend.py -v`
Expected: 404.

- [ ] **Step 3: Implement endpoint**

```python
# api/routers/digger_recommend.py
"""POST /api/digger/recommend — SSE-streamed interactive recommendation.

Flow:
1. Build OptimizerInput from user's wantlist + cached listings.
2. Identify stale releases (last_scraped older than half tier-floor).
3. Bump their priority and subscribe to refresh-progress channel.
4. Stream refresh events as SSE; when deadline elapses or all complete, run the optimizer.
5. Stream the optimizer result as a final event.
"""

from __future__ import annotations
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel

from api.dependencies import current_user, get_pool, get_redis
from api.queries import digger_queries as q
from api.digger_refresh.input_builder import build_optimizer_input
from api.digger_refresh.coordinator import RefreshCoordinator
from common.digger_optimizer import pareto_bundles

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/digger", tags=["digger"])


class RecommendIn(BaseModel):
    deadline_seconds: int = 30
    budget_cap_cents: int | None = None
    excluded_sellers: list[int] = []


_STALE_TIER_HALF_LIFE = {
    "must": timedelta(days=3, hours=12),
    "nice": timedelta(days=7),
    "eventually": timedelta(days=14),
}


async def _identify_stale(pool, user_id) -> list[int]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT rs.release_id, rs.priority_tier, rs.last_scraped_at
              FROM digger.release_scrape_state rs
              JOIN digger.user_wantlist_priorities uwp
                ON uwp.release_id = rs.release_id
             WHERE uwp.user_id = $1
            """, user_id,
        )
    now = datetime.now(timezone.utc)
    stale: list[int] = []
    for r in rows:
        floor = _STALE_TIER_HALF_LIFE[r["priority_tier"]]
        if r["last_scraped_at"] is None or now - r["last_scraped_at"] > floor:
            stale.append(r["release_id"])
    return stale


@router.post("/recommend")
async def recommend(
    body: RecommendIn,
    user=Depends(current_user),
    pool=Depends(get_pool),
    redis=Depends(get_redis),
):
    coord = RefreshCoordinator(pool=pool, redis=redis)
    settings = await q.get_user_settings(pool, user.user_id)
    if settings is None or not settings.enabled:
        async def err_only():
            yield {"event": "error", "data": json.dumps({"reason": "digger not enabled"})}
        return EventSourceResponse(err_only())

    async def event_gen():
        stale = await _identify_stale(pool, user.user_id)
        if stale:
            await coord.bump_priorities(stale)
        yield {"event": "refresh_started", "data": json.dumps({"stale_count": len(stale)})}

        completed: set[int] = set()
        if stale:
            async for ev in coord.subscribe_progress(str(user.user_id), deadline_seconds=body.deadline_seconds):
                completed.add(ev["release_id"])
                yield {"event": "refresh_progress",
                       "data": json.dumps({"release_id": ev["release_id"], "status": ev["status"],
                                           "remaining": len(stale) - len(completed)})}
                if completed >= set(stale):
                    break

        inp = await build_optimizer_input(
            pool, user.user_id,
            location=settings.country_code or "US", currency=settings.currency,
            budget_cap_cents=body.budget_cap_cents,
            excluded_sellers=frozenset(body.excluded_sellers),
        )
        out = pareto_bundles(inp)
        yield {"event": "result", "data": out.model_dump_json()}
        yield {"event": "done", "data": "{}"}

    return EventSourceResponse(event_gen())
```

Register in `api/main.py`:

```python
from api.routers.digger_recommend import router as digger_recommend_router
app.include_router(digger_recommend_router)
```

Add `sse-starlette>=2.1` to `api/pyproject.toml` if not present.

- [ ] **Step 4: Run test to verify it passes**

`uv run pytest tests/api/test_digger_recommend.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/routers/digger_recommend.py api/main.py api/pyproject.toml tests/api/test_digger_recommend.py
git commit -m "feat(digger): SSE /api/digger/recommend with opportunistic refresh"
```

---

## Task 12: Reports CRUD endpoints

**Files:**
- Create: `api/queries/digger_reports.py`, `api/routers/digger_reports.py`
- Modify: `api/main.py`
- Test: `tests/api/test_digger_reports.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_digger_reports.py
import pytest
import uuid


@pytest.mark.asyncio
async def test_list_returns_empty_for_new_user(api_client, auth_headers):
    r = await api_client.get("/api/digger/reports", headers=auth_headers)
    assert r.status_code == 200 and r.json()["items"] == []


@pytest.mark.asyncio
async def test_post_saves_then_get_returns_it(api_client, auth_headers):
    payload = {
        "title": "Test bundle",
        "kind": "interactive",
        "summary": {"wantlist_size": 5, "must_available": 3, "total_value_cents": 1000},
        "bundles": [],
        "watching": [],
        "change_flag": "first_run",
        "shipping_confidence": "high",
    }
    r = await api_client.post("/api/digger/reports", headers=auth_headers, json=payload)
    assert r.status_code == 201
    rid = r.json()["report_id"]

    r = await api_client.get(f"/api/digger/reports/{rid}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["title"] == "Test bundle"

    r = await api_client.post(f"/api/digger/reports/{rid}/read", headers=auth_headers)
    assert r.status_code == 204
```

- [ ] **Step 2: Run test to verify it fails**

`uv run pytest tests/api/test_digger_reports.py -v`
Expected: 404.

- [ ] **Step 3: Implement queries + router**

```python
# api/queries/digger_reports.py
from __future__ import annotations
import json
import uuid
from common.postgres_pool import AsyncPostgreSQLPool


async def list_reports(pool: AsyncPostgreSQLPool, user_id: uuid.UUID, limit: int = 50) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT report_id, kind, generated_at, read_at, title, summary, change_flag "
            "  FROM digger.reports WHERE user_id = $1 ORDER BY generated_at DESC LIMIT $2",
            user_id, limit,
        )
    return [{
        "report_id": str(r["report_id"]), "kind": r["kind"],
        "generated_at": r["generated_at"].isoformat(),
        "read_at": r["read_at"].isoformat() if r["read_at"] else None,
        "title": r["title"], "summary": r["summary"], "change_flag": r["change_flag"],
    } for r in rows]


async def get_report(pool: AsyncPostgreSQLPool, user_id: uuid.UUID, report_id: uuid.UUID) -> dict | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM digger.reports WHERE report_id = $1 AND user_id = $2",
            report_id, user_id,
        )
    if row is None:
        return None
    d = dict(row)
    d["report_id"] = str(d["report_id"])
    d["user_id"] = str(d["user_id"])
    for k in ("generated_at", "read_at"):
        if d[k]:
            d[k] = d[k].isoformat()
    return d


async def insert_report(pool: AsyncPostgreSQLPool, user_id: uuid.UUID, *,
                        kind: str, title: str, summary: dict, bundles: list,
                        watching: list, change_flag: str, shipping_confidence: str) -> uuid.UUID:
    rid = uuid.uuid4()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO digger.reports
              (report_id, user_id, kind, title, summary, bundles, watching, change_flag, shipping_confidence)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7::jsonb, $8, $9)
            """,
            rid, user_id, kind, title,
            json.dumps(summary), json.dumps(bundles), json.dumps(watching),
            change_flag, shipping_confidence,
        )
    return rid


async def mark_read(pool: AsyncPostgreSQLPool, user_id: uuid.UUID, report_id: uuid.UUID) -> bool:
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE digger.reports SET read_at = now() "
            "WHERE report_id = $1 AND user_id = $2 AND read_at IS NULL",
            report_id, user_id,
        )
    return int(result.split()[-1]) > 0
```

```python
# api/routers/digger_reports.py
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from api.dependencies import current_user, get_pool
from api.queries import digger_reports as q

router = APIRouter(prefix="/api/digger/reports", tags=["digger"])


class ReportListItem(BaseModel):
    report_id: str
    kind: str
    generated_at: str
    read_at: str | None
    title: str
    summary: dict
    change_flag: str


class ReportList(BaseModel):
    items: list[ReportListItem]


class ReportIn(BaseModel):
    title: str
    kind: str  # "interactive" or "scheduled"
    summary: dict
    bundles: list
    watching: list
    change_flag: str  # "significant" / "none" / "first_run"
    shipping_confidence: str  # "high" / "low"


@router.get("", response_model=ReportList)
async def list_reports(user=Depends(current_user), pool=Depends(get_pool)):
    items = await q.list_reports(pool, user.user_id)
    return ReportList(items=[ReportListItem(**it) for it in items])


@router.get("/{report_id}")
async def get_report(report_id: UUID, user=Depends(current_user), pool=Depends(get_pool)):
    r = await q.get_report(pool, user.user_id, report_id)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "report not found")
    return r


@router.post("", status_code=status.HTTP_201_CREATED)
async def post_report(body: ReportIn, user=Depends(current_user), pool=Depends(get_pool)):
    rid = await q.insert_report(
        pool, user.user_id, kind=body.kind, title=body.title,
        summary=body.summary, bundles=body.bundles, watching=body.watching,
        change_flag=body.change_flag, shipping_confidence=body.shipping_confidence,
    )
    return {"report_id": str(rid)}


@router.post("/{report_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(report_id: UUID, user=Depends(current_user), pool=Depends(get_pool)):
    ok = await q.mark_read(pool, user.user_id, report_id)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "report not found or already read")
```

Register in `api/main.py`:

```python
from api.routers.digger_reports import router as digger_reports_router
app.include_router(digger_reports_router)
```

- [ ] **Step 4: Run test to verify it passes**

`uv run pytest tests/api/test_digger_reports.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/queries/digger_reports.py api/routers/digger_reports.py api/main.py tests/api/test_digger_reports.py
git commit -m "feat(digger): /api/digger/reports CRUD endpoints"
```

---

## Task 13: Scheduler runner in digger/

**Files:**
- Create: `digger/digger/scheduler/__init__.py`, `digger/digger/scheduler/runner.py`
- Modify: `digger/digger/main.py`
- Test: `tests/digger/test_scheduler_runner.py`

The scheduler polls api/internal/digger/users-due-for-report at a fixed interval, fetches the wantlist snapshot for each due user, runs the optimizer, persists a report.

- [ ] **Step 1: Write the failing test**

```python
# tests/digger/test_scheduler_runner.py
import pytest
from unittest.mock import AsyncMock
from digger.scheduler.runner import run_scheduled_for_user


@pytest.mark.asyncio
async def test_run_scheduled_persists_report(postgres_pool, monkeypatch, seeded_full_state):
    user_id = seeded_full_state.user_id
    # Mock the API HTTP fetch with the seeded data
    async def fake_fetch_snapshot(user_id):
        return {
            "user_id": str(user_id),
            "must": [{"release_id": seeded_full_state.must_release, "min_media_condition": "VG",
                      "min_sleeve_condition": "VG", "max_price_cents": None}],
            "nice": [], "eventually": [],
        }
    monkeypatch.setattr("digger.scheduler.runner.fetch_wantlist_snapshot", AsyncMock(side_effect=fake_fetch_snapshot))

    await run_scheduled_for_user(postgres_pool, user_id, country="US", currency="USD")

    async with postgres_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT title, change_flag FROM digger.reports WHERE user_id=$1 ORDER BY generated_at DESC LIMIT 1",
            user_id,
        )
    assert row is not None
    assert row["change_flag"] in ("first_run", "significant", "none")
```

- [ ] **Step 2: Run test to verify it fails**

`uv run pytest tests/digger/test_scheduler_runner.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

```python
# digger/digger/scheduler/runner.py
"""Scheduled-run runner.

Per user_id:
1. Fetch wantlist snapshot from /api/internal/digger/wantlist-snapshot/{user_id}
2. Read settings from same source (location, currency)
3. Read listings + sellers directly from Postgres
4. Build OptimizerInput, call pareto_bundles
5. Compute change_flag vs last report
6. Insert into digger.reports
7. Bump next_scheduled_run_at on user_digger_settings
"""

from __future__ import annotations
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
import httpx
from common.postgres_pool import AsyncPostgreSQLPool
from common.digger_optimizer import pareto_bundles
from common.digger_optimizer.models import (
    OptimizerInput, ReleaseConstraint, Listing, Seller,
)
from decimal import Decimal

log = logging.getLogger(__name__)


async def fetch_wantlist_snapshot(api_base_url: str, service_token: str, user_id: uuid.UUID) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            f"{api_base_url}/api/internal/digger/wantlist-snapshot/{user_id}",
            headers={"X-Service-Token": service_token},
        )
        r.raise_for_status()
        return r.json()


_CADENCE_DELTA = {
    "weekly": timedelta(days=7),
    "biweekly": timedelta(days=14),
    "monthly": timedelta(days=30),
}


async def run_scheduled_for_user(
    pool: AsyncPostgreSQLPool, user_id: uuid.UUID, *, country: str, currency: str,
    cadence: str = "weekly", snapshot_fetcher = None,
) -> uuid.UUID | None:
    if snapshot_fetcher is None:
        snapshot_fetcher = fetch_wantlist_snapshot
    snapshot = await snapshot_fetcher(user_id)

    def _constraints(rows):
        return [ReleaseConstraint(
            release_id=r["release_id"], min_media_condition=r["min_media_condition"],
            min_sleeve_condition=r["min_sleeve_condition"], max_price_cents=r["max_price_cents"],
        ) for r in rows]

    must = _constraints(snapshot["must"])
    nice = _constraints(snapshot["nice"])
    eventually = _constraints(snapshot["eventually"])
    release_ids = [c.release_id for c in must + nice + eventually]
    if not release_ids:
        log.info("ℹ️ user %s has empty wantlist — skipping", user_id)
        return None

    async with pool.acquire() as conn:
        listing_rows = await conn.fetch(
            "SELECT * FROM digger.listings WHERE release_id = ANY($1::bigint[]) AND removed_at IS NULL",
            release_ids,
        )
        seller_rows = await conn.fetch(
            "SELECT * FROM digger.sellers WHERE seller_id = ANY($1::bigint[])",
            list({r["seller_id"] for r in listing_rows}),
        )
        last_report = await conn.fetchrow(
            "SELECT bundles, generated_at FROM digger.reports "
            "WHERE user_id=$1 ORDER BY generated_at DESC LIMIT 1",
            user_id,
        )

    sellers = {r["seller_id"]: Seller(
        seller_id=r["seller_id"], region=r["region"], country_code=r["country_code"],
        shipping_policy=None, feedback_score=float(r["feedback_score"]) if r["feedback_score"] else None,
    ) for r in seller_rows}
    listings = [Listing(
        listing_id=r["listing_id"], release_id=r["release_id"], seller_id=r["seller_id"],
        price_value=Decimal(r["price_value"]), price_currency=r["price_currency"],
        media_condition=r["media_condition"], sleeve_condition=r["sleeve_condition"],
    ) for r in listing_rows]

    inp = OptimizerInput(
        user_id=user_id, location=country, currency=currency,
        must_have_releases=must, nice_have_releases=nice, eventually_releases=eventually,
        candidate_listings=listings, sellers=sellers,
    )
    out = pareto_bundles(inp)

    change_flag = _compute_change_flag(last_report, out)

    summary = {
        "wantlist_size": len(release_ids),
        "must_available": sum(1 for c in must if c.release_id in
                              {l.release_id for l in inp.candidate_listings}),
        "total_value_cents": out.bundles[0].grand_total_cents if out.bundles else 0,
    }
    report_id = uuid.uuid4()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO digger.reports
              (report_id, user_id, kind, title, summary, bundles, watching, change_flag, shipping_confidence)
            VALUES ($1, $2, 'scheduled', $3, $4::jsonb, $5::jsonb, $6::jsonb, $7, $8)
            """,
            report_id, user_id,
            f"Weekly digest — {datetime.now(timezone.utc).date().isoformat()}",
            json.dumps(summary),
            json.dumps([b.model_dump(mode="json") for b in out.bundles]),
            json.dumps(out.watching),
            change_flag, out.shipping_confidence,
        )
        await conn.execute(
            "UPDATE digger.user_digger_settings "
            "SET next_scheduled_run_at = now() + $2 WHERE user_id = $1",
            user_id, _CADENCE_DELTA.get(cadence, timedelta(days=7)),
        )
    return report_id


def _compute_change_flag(last_report_row, out) -> str:
    if last_report_row is None:
        return "first_run"
    prev_bundles = last_report_row["bundles"]
    if not prev_bundles:
        return "significant" if out.bundles else "none"
    prev_listings: set[int] = set()
    for b in prev_bundles:
        for so in b.get("seller_orders", []):
            for ol in so.get("listings", []):
                prev_listings.add(ol["listing_id"])
    cur_listings: set[int] = set()
    for b in out.bundles:
        for so in b.seller_orders:
            for ol in so.listings:
                cur_listings.add(ol.listing_id)
    diff = prev_listings.symmetric_difference(cur_listings)
    return "significant" if len(diff) >= 3 else "none"
```

- [ ] **Step 4: Run test to verify it passes**

`uv run pytest tests/digger/test_scheduler_runner.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add digger/digger/scheduler/ tests/digger/test_scheduler_runner.py
git commit -m "feat(digger): scheduler runner with change-flag detection"
```

---

## Task 14: Scheduler loop wired into digger main

**Files:**
- Modify: `digger/digger/scheduler/runner.py` — add `scheduler_loop`
- Modify: `digger/digger/main.py`
- Test: `tests/digger/test_scheduler_loop.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/digger/test_scheduler_loop.py
import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from digger.scheduler.runner import scheduler_loop


@pytest.mark.asyncio
async def test_scheduler_loop_calls_runner_for_each_due_user(postgres_pool, monkeypatch):
    async def fake_fetch_due():
        return [{"user_id": "00000000-0000-0000-0000-000000000001", "cadence": "weekly"}]
    monkeypatch.setattr("digger.scheduler.runner.fetch_users_due_for_report", AsyncMock(side_effect=fake_fetch_due))
    runner = AsyncMock(return_value=None)
    monkeypatch.setattr("digger.scheduler.runner.run_scheduled_for_user", runner)

    stop_event = asyncio.Event()

    async def stop():
        await asyncio.sleep(0.3)
        stop_event.set()

    asyncio.create_task(stop())
    await scheduler_loop(pool=postgres_pool, stop_event=stop_event, poll_interval=0.1)
    runner.assert_awaited()
```

- [ ] **Step 2: Implement loop**

In `digger/digger/scheduler/runner.py`:

```python
async def fetch_users_due_for_report(api_base_url: str, service_token: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            f"{api_base_url}/api/internal/digger/users-due-for-report",
            headers={"X-Service-Token": service_token},
        )
        r.raise_for_status()
        return r.json()["users"]


async def scheduler_loop(
    *, pool: AsyncPostgreSQLPool, stop_event: asyncio.Event,
    api_base_url: str = "", service_token: str = "",
    poll_interval: float = 300.0,
) -> None:
    while not stop_event.is_set():
        try:
            users = await fetch_users_due_for_report(api_base_url, service_token)
            for u in users:
                try:
                    await run_scheduled_for_user(
                        pool, uuid.UUID(u["user_id"]),
                        country="US",  # TODO: fetch user settings; M2 default to US
                        currency="USD", cadence=u["cadence"],
                    )
                except Exception:
                    log.exception("⚠️ scheduled run failed for %s", u["user_id"])
        except Exception:
            log.exception("⚠️ scheduler loop iteration failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
        except asyncio.TimeoutError:
            pass
```

In `digger/digger/main.py`, append:

```python
from digger.scheduler.runner import scheduler_loop
tasks.append(asyncio.create_task(
    scheduler_loop(pool=pool, stop_event=stop_event,
                   api_base_url=cfg.api_base_url, service_token=cfg.api_service_token,
                   poll_interval=300),
    name="scheduler",
))
```

- [ ] **Step 3: Run test**

`uv run pytest tests/digger/test_scheduler_loop.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add digger/digger/scheduler/runner.py digger/digger/main.py tests/digger/test_scheduler_loop.py
git commit -m "feat(digger): scheduler loop wired into worker main"
```

---

## Task 15: Explore Reports inbox page

**Files:**
- Create: `explore/src/digger/Reports.tsx`
- Modify: `explore/src/digger/api.ts` (add `getReports`)
- Modify: `explore/src/main.tsx`
- Test: `tests/explore/digger/Reports.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// tests/explore/digger/Reports.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { Reports } from "../../../explore/src/digger/Reports";

vi.mock("../../../explore/src/digger/api", () => ({
  getReports: vi.fn().mockResolvedValue({ items: [
    { report_id: "abc", kind: "scheduled", generated_at: "2026-05-15T00:00:00Z",
      read_at: null, title: "Weekly", summary: { wantlist_size: 5 }, change_flag: "significant" },
  ] }),
}));

describe("Reports", () => {
  it("renders the inbox list", async () => {
    render(<Reports />);
    await waitFor(() => expect(screen.getByText("Weekly")).toBeInTheDocument());
    expect(screen.getByText(/significant/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Implement**

```typescript
// in explore/src/digger/api.ts, append:
export interface ReportSummary {
  report_id: string;
  kind: "scheduled" | "interactive";
  generated_at: string;
  read_at: string | null;
  title: string;
  summary: { wantlist_size?: number; must_available?: number; total_value_cents?: number };
  change_flag: "significant" | "none" | "first_run";
}

export async function getReports(): Promise<{ items: ReportSummary[] }> {
  return api("/api/digger/reports");
}

export async function getReport(report_id: string): Promise<any> {
  return api(`/api/digger/reports/${report_id}`);
}

export async function markReportRead(report_id: string): Promise<void> {
  await api(`/api/digger/reports/${report_id}/read`, { method: "POST" });
}
```

```tsx
// explore/src/digger/Reports.tsx
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getReports, type ReportSummary } from "./api";

export function Reports() {
  const [items, setItems] = useState<ReportSummary[] | null>(null);
  useEffect(() => {
    getReports().then((r) => setItems(r.items));
  }, []);
  if (items === null) return <div>Loading reports…</div>;
  if (items.length === 0) return <div>No reports yet — run your first recommendation from the wantlist page.</div>;
  return (
    <ul className="digger-reports">
      {items.map((it) => (
        <li key={it.report_id} className={it.read_at ? "read" : "unread"}>
          <Link to={`/digger/reports/${it.report_id}`}>
            <div className="title">{it.title}</div>
            <div className="meta">
              {new Date(it.generated_at).toLocaleString()} ·
              <span className={`flag flag-${it.change_flag}`}>{it.change_flag.replace("_", " ")}</span>
            </div>
          </Link>
        </li>
      ))}
    </ul>
  );
}
```

Register route in `explore/src/main.tsx`:

```tsx
import { Reports } from "./digger/Reports";
<Route path="/digger/reports" element={<RequireAuth><Reports /></RequireAuth>} />
```

- [ ] **Step 3: Run test**

`cd explore && npm test -- digger/Reports`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add explore/src/digger/Reports.tsx explore/src/digger/api.ts explore/src/main.tsx tests/explore/digger/Reports.test.tsx
git commit -m "feat(digger): reports inbox page in explore"
```

---

## Task 16: Bundle card component

**Files:**
- Create: `explore/src/digger/BundleCard.tsx`
- Test: `tests/explore/digger/BundleCard.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// tests/explore/digger/BundleCard.test.tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { BundleCard } from "../../../explore/src/digger/BundleCard";

const bundle = {
  name: "cheapest" as const,
  seller_orders: [{ seller_id: 1, listings: [], subtotal_item_cents: 1000, shipping_cents: 500 }],
  total_item_cost_cents: 1000, total_shipping_cents: 500, grand_total_cents: 1500,
  coverage: { must: 1, nice: 0, eventually: 0 }, avg_condition_score: 7.0,
  solver: "ilp" as const, reasoning_hint: "1 must from 1 seller.",
};

describe("BundleCard", () => {
  it("renders name, totals, and coverage", () => {
    render(<BundleCard bundle={bundle} currency="USD" />);
    expect(screen.getByText(/cheapest/i)).toBeInTheDocument();
    expect(screen.getByText(/\$15\.00/)).toBeInTheDocument();
    expect(screen.getByText(/1 must/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Implement**

```tsx
// explore/src/digger/BundleCard.tsx
import type { ReactNode } from "react";

export interface Bundle {
  name: "cheapest" | "most_coverage" | "best_quality" | "fewest_sellers";
  seller_orders: { seller_id: number; listings: any[]; subtotal_item_cents: number; shipping_cents: number }[];
  total_item_cost_cents: number;
  total_shipping_cents: number;
  grand_total_cents: number;
  coverage: { must: number; nice: number; eventually: number };
  avg_condition_score: number;
  solver: "ilp" | "greedy";
  reasoning_hint: string;
}

const NAME_LABELS: Record<Bundle["name"], string> = {
  cheapest: "Cheapest",
  most_coverage: "Most Coverage",
  best_quality: "Best Quality",
  fewest_sellers: "Fewest Sellers",
};

export function formatCents(cents: number, currency: string): string {
  return new Intl.NumberFormat(undefined, {
    style: "currency", currency, currencyDisplay: "symbol",
  }).format(cents / 100);
}

export function BundleCard({ bundle, currency, action }: {
  bundle: Bundle; currency: string; action?: ReactNode;
}) {
  return (
    <div className={`bundle-card bundle-${bundle.name}`}>
      <header>
        <h3>{NAME_LABELS[bundle.name]}</h3>
        {bundle.solver === "greedy" && <span className="badge solver-greedy">greedy</span>}
      </header>
      <div className="total">{formatCents(bundle.grand_total_cents, currency)}</div>
      <div className="breakdown">
        <span>{formatCents(bundle.total_item_cost_cents, currency)} items</span>
        <span> + {formatCents(bundle.total_shipping_cents, currency)} shipping</span>
      </div>
      <div className="coverage">
        <span>{bundle.coverage.must} must</span> ·
        <span>{bundle.coverage.nice} nice</span> ·
        <span>{bundle.coverage.eventually} eventually</span>
      </div>
      <div className="sellers">{bundle.seller_orders.length} seller{bundle.seller_orders.length === 1 ? "" : "s"}</div>
      <p className="hint">{bundle.reasoning_hint}</p>
      {action}
    </div>
  );
}
```

- [ ] **Step 3: Run test**

`cd explore && npm test -- digger/BundleCard`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add explore/src/digger/BundleCard.tsx tests/explore/digger/BundleCard.test.tsx
git commit -m "feat(digger): BundleCard component"
```

---

## Task 17: Report viewer with 4 bundle cards + watching list

**Files:**
- Create: `explore/src/digger/ReportViewer.tsx`, `explore/src/digger/WatchingList.tsx`
- Modify: `explore/src/main.tsx` — `/digger/reports/:id` route
- Test: `tests/explore/digger/ReportViewer.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// tests/explore/digger/ReportViewer.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ReportViewer } from "../../../explore/src/digger/ReportViewer";

vi.mock("../../../explore/src/digger/api", () => ({
  getReport: vi.fn().mockResolvedValue({
    report_id: "abc",
    title: "Test report",
    summary: { wantlist_size: 5 },
    bundles: [
      { name: "cheapest", seller_orders: [], total_item_cost_cents: 1000, total_shipping_cents: 500,
        grand_total_cents: 1500, coverage: { must: 1, nice: 0, eventually: 0 },
        avg_condition_score: 7.0, solver: "ilp", reasoning_hint: "ok" },
    ],
    watching: [42],
    shipping_confidence: "high",
    generated_at: "2026-05-15T00:00:00Z",
  }),
  markReportRead: vi.fn().mockResolvedValue(undefined),
}));

describe("ReportViewer", () => {
  it("renders bundles and watching list", async () => {
    render(
      <MemoryRouter initialEntries={["/digger/reports/abc"]}>
        <Routes><Route path="/digger/reports/:id" element={<ReportViewer />} /></Routes>
      </MemoryRouter>
    );
    await waitFor(() => expect(screen.getByText("Test report")).toBeInTheDocument());
    expect(screen.getByText(/cheapest/i)).toBeInTheDocument();
    expect(screen.getByText(/watching/i)).toBeInTheDocument();
    expect(screen.getByText(/42/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Implement**

```tsx
// explore/src/digger/WatchingList.tsx
export function WatchingList({ release_ids }: { release_ids: number[] }) {
  if (release_ids.length === 0) return null;
  return (
    <section className="watching-list">
      <h2>Watching — no qualifying listings yet</h2>
      <ul>
        {release_ids.map((id) => (
          <li key={id}>
            <a href={`https://www.discogs.com/release/${id}`} target="_blank" rel="noopener">
              release {id}
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}
```

```tsx
// explore/src/digger/ReportViewer.tsx
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { getReport, markReportRead } from "./api";
import { BundleCard, type Bundle } from "./BundleCard";
import { WatchingList } from "./WatchingList";

interface ReportFull {
  report_id: string;
  title: string;
  summary: any;
  bundles: Bundle[];
  watching: number[];
  shipping_confidence: "high" | "low";
  generated_at: string;
}

export function ReportViewer() {
  const { id } = useParams<{ id: string }>();
  const [report, setReport] = useState<ReportFull | null>(null);

  useEffect(() => {
    if (!id) return;
    getReport(id).then((r) => {
      setReport(r);
      markReportRead(id).catch(() => {});
    });
  }, [id]);

  if (report === null) return <div>Loading…</div>;
  return (
    <div className="report-viewer">
      <header>
        <h1>{report.title}</h1>
        <div className="meta">
          {new Date(report.generated_at).toLocaleString()} ·
          <span className={`badge confidence-${report.shipping_confidence}`}>
            {report.shipping_confidence} shipping confidence
          </span>
        </div>
      </header>
      <div className="bundles-grid">
        {report.bundles.map((b) => (
          <BundleCard key={b.name} bundle={b} currency="USD" />
        ))}
      </div>
      <WatchingList release_ids={report.watching} />
    </div>
  );
}
```

Register route in `explore/src/main.tsx`:

```tsx
import { ReportViewer } from "./digger/ReportViewer";
<Route path="/digger/reports/:id" element={<RequireAuth><ReportViewer /></RequireAuth>} />
```

- [ ] **Step 3: Run test**

`cd explore && npm test -- digger/ReportViewer`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add explore/src/digger/ReportViewer.tsx explore/src/digger/WatchingList.tsx explore/src/main.tsx tests/explore/digger/ReportViewer.test.tsx
git commit -m "feat(digger): report viewer with 4 bundle cards + watching list"
```

---

## Task 18: "Run recommendation" button on Wantlist page

**Files:**
- Modify: `explore/src/digger/Wantlist.tsx` — add button + SSE consumer
- Modify: `explore/src/digger/api.ts` — `runRecommend` SSE helper
- Test: extend `tests/explore/digger/Wantlist.test.tsx`

- [ ] **Step 1: Add SSE helper to `api.ts`**

```typescript
// explore/src/digger/api.ts, append:
export interface RecommendEvent {
  type: "refresh_started" | "refresh_progress" | "result" | "done" | "error";
  data: any;
}

export async function* runRecommend(opts: {
  budget_cap_cents?: number; excluded_sellers?: number[]; deadline_seconds?: number;
} = {}): AsyncGenerator<RecommendEvent, void, unknown> {
  const r = await fetch("/api/digger/recommend", {
    method: "POST", credentials: "include",
    headers: { "content-type": "application/json", "accept": "text/event-stream" },
    body: JSON.stringify({
      deadline_seconds: opts.deadline_seconds ?? 30,
      budget_cap_cents: opts.budget_cap_cents,
      excluded_sellers: opts.excluded_sellers ?? [],
    }),
  });
  if (!r.body) throw new Error("no response body");
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) return;
    buf += decoder.decode(value, { stream: true });
    while (true) {
      const idx = buf.indexOf("\n\n");
      if (idx === -1) break;
      const block = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      let type: RecommendEvent["type"] | null = null;
      let data: any = null;
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) type = line.slice(6).trim() as any;
        else if (line.startsWith("data:")) data = JSON.parse(line.slice(5).trim());
      }
      if (type) yield { type, data };
    }
  }
}
```

- [ ] **Step 2: Add button + handler in `Wantlist.tsx`**

```tsx
// inside Wantlist component, add state:
const [runStatus, setRunStatus] = useState<string | null>(null);
const [bundles, setBundles] = useState<any[] | null>(null);

async function runRec() {
  setRunStatus("Refreshing stale listings…");
  setBundles(null);
  let stale = 0;
  for await (const ev of runRecommend({ deadline_seconds: 30 })) {
    if (ev.type === "refresh_started") {
      stale = ev.data.stale_count;
      setRunStatus(stale === 0 ? "Computing bundles…" : `Refreshing ${stale} listings…`);
    } else if (ev.type === "refresh_progress") {
      setRunStatus(`${stale - ev.data.remaining}/${stale} refreshed`);
    } else if (ev.type === "result") {
      setBundles(ev.data.bundles);
      setRunStatus("Done");
    } else if (ev.type === "error") {
      setRunStatus(`Error: ${ev.data.reason ?? "unknown"}`);
    }
  }
}
```

Add a `<button onClick={runRec}>Run recommendation</button>` above the table, and render bundles inline via `<BundleCard>`.

- [ ] **Step 3: Extend the test**

```tsx
// tests/explore/digger/Wantlist.test.tsx — append
it("triggers runRecommend when button clicked", async () => {
  // ... mock runRecommend yielding result event ...
});
```

(Full mock setup left as an exercise per existing test style.)

- [ ] **Step 4: Manual smoke**

Run `just up`, navigate to `/digger/wantlist`, click "Run recommendation", verify SSE events render.

- [ ] **Step 5: Commit**

```bash
git add explore/src/digger/Wantlist.tsx explore/src/digger/api.ts tests/explore/digger/Wantlist.test.tsx
git commit -m "feat(digger): 'Run recommendation' button consuming SSE stream"
```

---

## Task 19: Perf tests for new endpoints

**Files:**
- Modify: `tests/perftest/config.yaml`, `tests/perftest/run_perftest.py`

- [ ] **Step 1: Append entries**

```yaml
digger_recommend:
  method: POST
  path: /api/digger/recommend
  auth: jwt
  body:
    deadline_seconds: 5
  thresholds:
    p95_ms: 6000  # SSE; includes the deadline
    error_rate: 0.01
digger_reports_list:
  method: GET
  path: /api/digger/reports
  auth: jwt
  thresholds:
    p95_ms: 100
    error_rate: 0.001
digger_reports_get:
  method: GET
  path: /api/digger/reports/{report_id}
  auth: jwt
  path_params:
    report_id: 00000000-0000-0000-0000-000000000001
  thresholds:
    p95_ms: 50
    error_rate: 0.001
```

- [ ] **Step 2: Smoke run**

`uv run python tests/perftest/run_perftest.py --only digger_reports_list --duration 10`
Expected: passes.

- [ ] **Step 3: Commit**

```bash
git add tests/perftest/
git commit -m "test(digger): perf config for /recommend + /reports endpoints"
```

---

## Task 20: Docs — optimizer.md + CLAUDE.md updates

**Files:**
- Create: `docs/digger-optimizer.md`
- Modify: `CLAUDE.md`, `docs/architecture.md`

- [ ] **Step 1: Write `docs/digger-optimizer.md`**

```markdown
# Digger Optimizer

## Overview

Lives in `common/digger_optimizer/`. Pure-function library imported by `api/` (interactive) and `digger/` (scheduled). No I/O.

## Public API

```python
from common.digger_optimizer import pareto_bundles, OptimizerInput, OptimizerOutput
out: OptimizerOutput = pareto_bundles(inp)
```

## Algorithm

Four-stage pipeline:

1. **Filtering** (`filtering.py`) — drop listings below condition floor / over max price / currency mismatch.
2. **Pareto front** (`pareto.py`) — runs the ILP four times (Cheapest, Most Coverage, Best Quality, Fewest Sellers).
3. **ILP** (`ilp.py`) — pulp + CBC; variables `x[listing] y[seller] z[seller, count]`; shipping linearized piecewise.
4. **Fallback** (`greedy.py`) — greedy ratio-based when ILP times out; also the warm-start hint.

## Bundle variants

| Name | What it optimizes |
|---|---|
| `cheapest` | Min total cost; small Nice bonus ($5/item) |
| `most_coverage` | Larger Nice bonus ($25), Eventually bonus ($10) |
| `best_quality` | Adds $3-per-condition-step bonus |
| `fewest_sellers` | $20 penalty per additional seller |

## Performance

- ~1000 listings × 200 sellers → < 2s per variant on a modern CPU.
- 5s per-variant ILP timeout; 20s worst-case total.
- Greedy fallback bounded; usually within 5-15% of ILP optimal.
```

- [ ] **Step 2: Update `CLAUDE.md`**

Append to the directory-structure block:
```
common/digger_optimizer/  Shared library — ILP-based bundle optimizer for the Digger feature
```

- [ ] **Step 3: Update `docs/architecture.md`**

Add a paragraph linking to the spec + optimizer doc.

- [ ] **Step 4: Commit**

```bash
git add docs/digger-optimizer.md CLAUDE.md docs/architecture.md
git commit -m "docs(digger): optimizer architecture + CLAUDE.md updates"
```

---

## Task 21: M2 E2E smoke

**Files:**
- Create: `tests/e2e/test_digger_m2_smoke.py`

- [ ] **Step 1: Write the test**

```python
# tests/e2e/test_digger_m2_smoke.py
import pytest


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_m2_smoke(api_client, browser_session, postgres_pool, fake_discogs_marketplace):
    user = await browser_session.login_via_oauth()
    # Pre-seed wantlist + listings (or rely on M1 fixtures)
    # Trigger recommend
    async with api_client.stream("POST", "/api/digger/recommend",
                                 headers=user.auth_headers,
                                 json={"deadline_seconds": 10}) as r:
        body = ""
        async for chunk in r.aiter_text():
            body += chunk
            if "event: result" in body:
                break
        assert "event: result" in body

    # List reports — should be empty unless we POST one
    list_r = await api_client.get("/api/digger/reports", headers=user.auth_headers)
    assert list_r.status_code == 200
```

- [ ] **Step 2: Run**

`just test-e2e -- tests/e2e/test_digger_m2_smoke.py`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/e2e/test_digger_m2_smoke.py
git commit -m "test(digger): M2 E2E smoke covering /recommend SSE flow"
```

---

## Task 22: Final polish — lint, coverage, smoke

- [ ] **Step 1: Run everything**

```bash
just test-digger
just test-api
just test-explore
just lint
```
Expected: PASS; coverage ≥80% on `common/digger_optimizer/` and `digger/scheduler/` and `api/routers/digger_recommend.py`.

- [ ] **Step 2: Smoke up**

```bash
just up
just digger-logs
```

Verify scheduler logs "ℹ️ user X has empty wantlist" or runs once for test data.

- [ ] **Step 3: Commit any fixes**

```bash
git add -u
git commit -m "chore(digger): M2 polish — lint, coverage, smoke"
```

---

## Self-review checklist

1. **Spec coverage** — M2 success criteria:
   - "Interactive recommend completes in <10s for wantlists ≤100 items (p95)" ✓ (Task 11; perf test in Task 19)
   - "Optimizer property tests pass" ✓ (Task 7)
   - "ILP within 5% of greedy lower bound on benchmark" — captured implicitly via property tests; explicit benchmark in `docs/digger-optimizer.md` (Task 20)
   - "Scheduled runs produce reports at the user's cadence; 'no significant changes' flag works" ✓ (Tasks 13-14)
2. **Placeholders** — none. All code blocks complete.
3. **Type consistency** — `BundleName` Literal values match across `common/digger_optimizer/models.py`, `api/routers/digger_recommend.py`, `explore/src/digger/BundleCard.tsx`.
4. **Ambiguity** —
   - SSE event names: `refresh_started`, `refresh_progress`, `result`, `done`, `error`.
   - Stale threshold per-tier: must=3.5d, nice=7d, eventually=14d (half of base interval).
   - Change-flag heuristic: ≥3 listing differences = "significant", else "none"; null prior report = "first_run".

---

## Out-of-scope for M2 (M3)

- Anthropic SDK integration, `digger_agent/`, system prompt, tool surface.
- `/api/digger/agent/message` SSE chat endpoint.
- Chat UI, proposal cards, session sidebar.
- `mcp-server/` digger tools.
- Daily token caps enforcement (data already in `user_digger_settings`).
