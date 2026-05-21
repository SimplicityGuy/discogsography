"""Tests for digger optimizer stage-1 filtering."""

from __future__ import annotations

from decimal import Decimal
import uuid

from common.digger_optimizer.filtering import filter_candidates
from common.digger_optimizer.models import Listing, OptimizerInput, ReleaseConstraint, Seller


def _input(constraints: list[ReleaseConstraint], listings: list[Listing]) -> OptimizerInput:
    return OptimizerInput(
        user_id=uuid.uuid4(),
        location="US",
        currency="USD",
        must_have_releases=constraints,
        candidate_listings=listings,
        sellers={listing.seller_id: Seller(seller_id=listing.seller_id, region="us") for listing in listings},
    )


def test_drops_below_condition_floor() -> None:
    c = ReleaseConstraint(release_id=1, min_media_condition="VG+", min_sleeve_condition="VG+", max_price_cents=None)
    listings = [
        Listing(
            listing_id=10, release_id=1, seller_id=1, price_value=Decimal("5"), price_currency="USD", media_condition="VG", sleeve_condition="VG"
        ),
        Listing(
            listing_id=11, release_id=1, seller_id=2, price_value=Decimal("12"), price_currency="USD", media_condition="NM", sleeve_condition="NM"
        ),
    ]
    out = filter_candidates(_input([c], listings))
    assert out.usable_by_release[1] == [11]
    assert out.watching == []


def test_drops_above_max_price() -> None:
    c = ReleaseConstraint(release_id=1, min_media_condition="VG", min_sleeve_condition="VG", max_price_cents=1000)
    listings = [
        Listing(
            listing_id=10, release_id=1, seller_id=1, price_value=Decimal("5"), price_currency="USD", media_condition="NM", sleeve_condition="NM"
        ),
        Listing(
            listing_id=11, release_id=1, seller_id=2, price_value=Decimal("15"), price_currency="USD", media_condition="NM", sleeve_condition="NM"
        ),
    ]
    out = filter_candidates(_input([c], listings))
    assert out.usable_by_release[1] == [10]


def test_marks_watching_when_no_qualifying_listings() -> None:
    c = ReleaseConstraint(release_id=99, min_media_condition="NM", min_sleeve_condition="NM", max_price_cents=None)
    out = filter_candidates(_input([c], []))
    assert out.watching == [99]
    assert 99 not in out.usable_by_release


def test_drops_below_sleeve_floor() -> None:
    # Media passes the floor but the sleeve does not — exercises the sleeve branch.
    c = ReleaseConstraint(release_id=1, min_media_condition="VG", min_sleeve_condition="NM", max_price_cents=None)
    listings = [
        Listing(
            listing_id=10, release_id=1, seller_id=1, price_value=Decimal("5"), price_currency="USD", media_condition="NM", sleeve_condition="VG"
        ),
        Listing(
            listing_id=11, release_id=1, seller_id=2, price_value=Decimal("6"), price_currency="USD", media_condition="NM", sleeve_condition="NM"
        ),
    ]
    out = filter_candidates(_input([c], listings))
    assert out.usable_by_release[1] == [11]


def test_skips_currency_mismatched_listings() -> None:
    c = ReleaseConstraint(release_id=1, min_media_condition="VG", min_sleeve_condition="VG", max_price_cents=None)
    listings = [
        Listing(
            listing_id=10, release_id=1, seller_id=1, price_value=Decimal("5"), price_currency="EUR", media_condition="NM", sleeve_condition="NM"
        ),
        Listing(
            listing_id=11, release_id=1, seller_id=2, price_value=Decimal("6"), price_currency="USD", media_condition="NM", sleeve_condition="NM"
        ),
    ]
    out = filter_candidates(_input([c], listings))
    assert out.usable_by_release[1] == [11]
    assert out.skipped_currency == 1
