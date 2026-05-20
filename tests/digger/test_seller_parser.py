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


def test_seller_malformed_user_href_raises() -> None:
    """A /users/ anchor with no numeric ID must raise, not fall back to seller_id=0."""
    html = "<html><body><a href='/users/profile'>Some User</a></body></html>"
    with pytest.raises(ValueError, match="no numeric user ID"):
        parse_seller_profile(html)


def test_seller_bleach_strips_html_in_username() -> None:
    """HTML tags in the seller username must be stripped by bleach."""
    html = """<html><body>
        <h1 class="profile-name">Evil<script>alert(1)</script><b>Seller</b></h1>
        <a href="/users/777">Evil Seller</a>
    </body></html>"""
    parsed = parse_seller_profile(html)
    # bleach strips tags but keeps their text content.
    assert "<script>" not in parsed.username
    assert "<b>" not in parsed.username
    assert "</" not in parsed.username
    assert parsed.username.startswith("Evil")
    assert parsed.username.endswith("Seller")


def test_seller_bleach_strips_html_in_region_name() -> None:
    """HTML tags in a shipping region name must be stripped by bleach."""
    html = """<html><body>
        <a href="/users/888">Seller</a>
        <table class="shipping-policies">
          <tr class="region-row">
            <td class="region-name"><b>US</b></td>
            <td class="first-item-cost">$5.00</td>
            <td class="additional-item-cost">$1.00</td>
          </tr>
        </table>
    </body></html>"""
    parsed = parse_seller_profile(html)
    assert parsed.shipping_policy is not None
    for region_key in parsed.shipping_policy:
        assert "<b>" not in region_key
    assert "us" in parsed.shipping_policy


# ---------------------------------------------------------------------------
# Previously uncovered edge cases
# ---------------------------------------------------------------------------


def test_seller_no_country_code_returns_none() -> None:
    """When the div.profile-country is absent, country_code is None."""
    html = """<html><body>
        <h1 class="profile-name">SellerX</h1>
        <a href="/users/999">SellerX</a>
    </body></html>"""
    parsed = parse_seller_profile(html)
    assert parsed.country_code is None


def test_seller_unknown_country_text_returns_none() -> None:
    """A country display name not in _COUNTRY_MAP maps to None (not an error)."""
    html = """<html><body>
        <h1 class="profile-name">SellerY</h1>
        <a href="/users/1001">SellerY</a>
        <div class="profile-country">Atlantis</div>
    </body></html>"""
    parsed = parse_seller_profile(html)
    assert parsed.country_code is None


def test_seller_malformed_feedback_count_is_none() -> None:
    """Non-numeric text in span.feedback-count is caught and feedback_count stays None (lines 119-120)."""
    html = """<html><body>
        <a href="/users/2001">Seller</a>
        <span class="feedback-count">not-a-number</span>
        <span class="feedback-score">99.5%</span>
    </body></html>"""
    parsed = parse_seller_profile(html)
    assert parsed.feedback_count is None
    # score should still parse
    assert parsed.feedback_score is not None


def test_seller_malformed_feedback_score_is_none() -> None:
    """Non-numeric text in span.feedback-score is caught and feedback_score stays None (lines 124-125)."""
    html = """<html><body>
        <a href="/users/2002">Seller</a>
        <span class="feedback-count">1234</span>
        <span class="feedback-score">not-a-decimal%</span>
    </body></html>"""
    parsed = parse_seller_profile(html)
    assert parsed.feedback_count == 1234
    assert parsed.feedback_score is None


def test_seller_shipping_row_missing_cell_is_skipped() -> None:
    """A region-row missing one of the required TDs is silently skipped (line 134)."""
    html = """<html><body>
        <a href="/users/3001">Seller</a>
        <table class="shipping-policies">
          <tr class="region-row">
            <!-- only region-name; first-item-cost and additional-item-cost absent -->
            <td class="region-name">US</td>
          </tr>
          <tr class="region-row">
            <td class="region-name">UK</td>
            <td class="first-item-cost">$3.00</td>
            <td class="additional-item-cost">$1.00</td>
          </tr>
        </table>
    </body></html>"""
    parsed = parse_seller_profile(html)
    assert parsed.shipping_policy is not None
    # The incomplete row must be skipped; only the complete row should appear
    assert "us" not in parsed.shipping_policy
    assert "uk" in parsed.shipping_policy


def test_to_cents_empty_string_returns_zero() -> None:
    """_to_cents with a string that has no digits returns 0 (line 64)."""
    from digger.scraper.seller_parser import _to_cents

    assert _to_cents("$$$$") == 0


def test_to_cents_invalid_decimal_returns_zero() -> None:
    """_to_cents with a value that raises Decimal exception returns 0 (lines 67-68)."""
    from digger.scraper.seller_parser import _to_cents

    # "1.2.3" passes the regex strip (digits and dots left) but Decimal("1.2.3") raises
    assert _to_cents("1.2.3") == 0
