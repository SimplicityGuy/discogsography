"""Tests for digger optimizer per-seller shipping estimation."""

from __future__ import annotations

from common.digger_optimizer.models import Seller, ShippingPolicyRegion
from common.digger_optimizer.shipping import REGION_MATRIX_CENTS, estimate_shipping_cents, shipping_confidence_score


def test_uses_policy_when_available() -> None:
    s = Seller(
        seller_id=1,
        region="us",
        country_code="US",
        shipping_policy={"us": ShippingPolicyRegion(first_cents=500, additional_cents=150, currency="USD")},
    )
    assert estimate_shipping_cents(s, location="US", count=1) == 500
    assert estimate_shipping_cents(s, location="US", count=4) == 500 + 150 * 3


def test_falls_back_to_matrix_when_no_policy() -> None:
    s = Seller(seller_id=1, region="us", country_code="US", shipping_policy=None)
    base = REGION_MATRIX_CENTS["us"]["us"]
    assert estimate_shipping_cents(s, location="US", count=1) == base
    # 1 + 0.2 * (count - 1) multiplier
    assert estimate_shipping_cents(s, location="US", count=3) == int(base * 1.4)


def test_confidence_high_when_most_have_policies() -> None:
    sellers = {
        1: Seller(seller_id=1, region="us", shipping_policy={"us": ShippingPolicyRegion(first_cents=500, additional_cents=100)}),
        2: Seller(seller_id=2, region="us", shipping_policy={"us": ShippingPolicyRegion(first_cents=500, additional_cents=100)}),
        3: Seller(seller_id=3, region="us", shipping_policy=None),
    }
    assert shipping_confidence_score(sellers, location="US") == "low"  # 2/3 = 66%
    sellers[3].shipping_policy = {"us": ShippingPolicyRegion(first_cents=500, additional_cents=100)}
    assert shipping_confidence_score(sellers, location="US") == "high"  # 3/3 = 100%
