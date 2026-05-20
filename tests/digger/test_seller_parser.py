"""Tests for the Discogs seller-profile parser.

Fixtures are SYNTHETIC HTML files hand-authored to match the documented Discogs
DOM structure as of 2026-05. They exercise parser logic but do NOT prove
real-Discogs compatibility (deferred to Task 28 / manual QA).
"""

from pathlib import Path

import pytest

from digger.scraper.seller_parser import parse_seller_profile
from digger.scraper.types import ParsedSeller


FIXTURES = Path(__file__).parent / "fixtures"


def test_seller_profile_fields_extracted() -> None:
    parsed = parse_seller_profile((FIXTURES / "seller_page_basic.html").read_text())
    assert isinstance(parsed, ParsedSeller)
    assert parsed.seller_id > 0
    assert parsed.username
    assert parsed.country_code is None or len(parsed.country_code) == 2
    if parsed.shipping_policy:
        for _region, policy in parsed.shipping_policy.items():
            assert "first_cents" in policy and "additional_cents" in policy
            assert int(policy["first_cents"]) >= 0 and int(policy["additional_cents"]) >= 0


def test_seller_shipping_policy_populated() -> None:
    """The basic fixture must include at least one shipping region."""
    parsed = parse_seller_profile((FIXTURES / "seller_page_basic.html").read_text())
    assert parsed.shipping_policy is not None
    assert len(parsed.shipping_policy) >= 1


def test_seller_ships_internationally_flag() -> None:
    """ships_internationally must be True when a shipping policy is present."""
    parsed = parse_seller_profile((FIXTURES / "seller_page_basic.html").read_text())
    assert parsed.ships_internationally is True


def test_seller_country_code_extracted() -> None:
    parsed = parse_seller_profile((FIXTURES / "seller_page_basic.html").read_text())
    assert parsed.country_code == "US"


def test_seller_missing_link_raises() -> None:
    with pytest.raises(ValueError, match="seller link missing"):
        parse_seller_profile("<html><body><h1>Not a seller page</h1></body></html>")
