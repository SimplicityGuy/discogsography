"""Tests for the digger optimizer Pydantic models."""

from __future__ import annotations

from decimal import Decimal
import uuid

from common.digger_optimizer.models import (
    BundleName,
    Listing,
    OptimizerInput,
    ReleaseConstraint,
    Seller,
)


def test_models_construct_with_minimal_fields() -> None:
    c = ReleaseConstraint(release_id=1, min_media_condition="VG", min_sleeve_condition="VG", max_price_cents=None)
    s = Seller(seller_id=1, region="us", country_code="US", shipping_policy=None)
    listing = Listing(
        listing_id=1,
        release_id=1,
        seller_id=1,
        price_value=Decimal("10.00"),
        price_currency="USD",
        media_condition="NM",
        sleeve_condition="NM",
    )
    inp = OptimizerInput(
        user_id=uuid.uuid4(),
        location="US",
        currency="USD",
        must_have_releases=[c],
        nice_have_releases=[],
        eventually_releases=[],
        candidate_listings=[listing],
        sellers={1: s},
    )
    assert inp.location == "US"
    assert inp.must_have_releases[0].release_id == 1
    assert inp.sellers[1].seller_id == 1


def test_bundle_name_literal() -> None:
    valid: list[BundleName] = ["cheapest", "most_coverage", "best_quality", "fewest_sellers"]
    assert "cheapest" in valid
