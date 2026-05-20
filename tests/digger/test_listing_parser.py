"""Tests for the Discogs listing-page parser.

Fixtures are SYNTHETIC HTML files hand-authored to match the documented Discogs
DOM structure as of 2026-05. They exercise parser logic but do NOT prove
real-Discogs compatibility (deferred to Task 28 / manual QA).
"""

from decimal import Decimal
from pathlib import Path

import pytest

from digger.scraper.listing_parser import UnknownLayoutError, parse_listings
from digger.scraper.types import ParsedListing


FIXTURES = Path(__file__).parent / "fixtures"


def _single_listing_html(price_text: str) -> str:
    """Build a one-row listing page with the given price cell text."""
    return f"""<html><body>
    <table id="pjax_container"><tbody>
      <tr class="shortcut_navigable">
        <td class="item_description">
          <a class="item_description_title" href="/sell/item/30001">Rec</a>
          <p class="item_condition">
            <span class="condition-label-desktop">Media Condition:</span>
            <span>NM (Near Mint)</span>
          </p>
          <p class="item_sleeve_condition">
            <span class="condition-label-desktop">Sleeve Condition:</span>
            <span>NM (Near Mint)</span>
          </p>
        </td>
        <td class="seller_info"><strong><a href="/seller/x">x</a></strong></td>
        <td class="item_price"><span class="price">{price_text}</span></td>
      </tr>
    </tbody></table>
    </body></html>"""


def test_parser_extracts_expected_listings() -> None:
    html = (FIXTURES / "listing_page_basic.html").read_text()
    parsed = parse_listings(html, release_id=12345)
    assert len(parsed) >= 2
    first = parsed[0]
    assert isinstance(first, ParsedListing)
    assert first.release_id == 12345
    assert first.listing_id > 0
    assert first.seller_username
    assert first.price_value > 0
    assert first.price_currency in {"USD", "EUR", "GBP", "JPY", "CAD", "AUD"}
    assert first.media_condition in {"M", "NM", "VG+", "VG", "G+", "G", "F", "P"}


def test_parser_condition_normalisation() -> None:
    """The '(NM or better)' form must resolve to 'NM'."""
    html = (FIXTURES / "listing_page_basic.html").read_text()
    parsed = parse_listings(html, release_id=12345)
    # Fixture row 2 has condition '(NM or better)' — must normalise to NM.
    normalised = [p for p in parsed if p.listing_id == 20002]
    assert len(normalised) == 1
    assert normalised[0].media_condition == "NM"


def test_parser_bleach_strips_html_in_comments() -> None:
    """HTML tags inside seller comments must be stripped by bleach."""
    html = (FIXTURES / "listing_page_basic.html").read_text()
    parsed = parse_listings(html, release_id=12345)
    # Fixture row 1 includes a <b> tag in the comment; bleach must remove it.
    with_comment = [p for p in parsed if p.listing_id == 20001]
    assert len(with_comment) == 1
    assert "<b>" not in (with_comment[0].comments or "")
    assert "great pressing" in (with_comment[0].comments or "")


def test_parser_returns_empty_on_no_listings_div() -> None:
    html = """<html><body>
        <table id="pjax_container"><tr><td><div class="no-results">No listings.</div></td></tr></table>
    </body></html>"""
    assert parse_listings(html, release_id=1) == []


def test_parser_returns_empty_on_text_sentinel() -> None:
    html = "<html><body>No listings available</body></html>"
    assert parse_listings(html, release_id=1) == []


def test_parser_raises_unknown_layout_on_garbage() -> None:
    with pytest.raises(UnknownLayoutError):
        parse_listings("<html><body><div class='unexpected'></div></body></html>", release_id=1)


@pytest.mark.parametrize(
    ("price_text", "expected"),
    [
        ("USD 12.99", Decimal("12.99")),  # simple dot-decimal
        ("USD 1,299.00", Decimal("1299.00")),  # en: comma thousands, dot decimal
        ("EUR 8.500,00", Decimal("8500.00")),  # de/eu: dot thousands, comma decimal
        ("EUR 8,50", Decimal("8.50")),  # de/eu: comma decimal, no thousands
        ("GBP 6.00", Decimal("6.00")),  # simple dot-decimal
        ("USD 1,000,000.00", Decimal("1000000.00")),  # multi-group en thousands
    ],
)
def test_parser_locale_safe_price_parsing(price_text: str, expected: Decimal) -> None:
    parsed = parse_listings(_single_listing_html(price_text), release_id=1)
    assert len(parsed) == 1
    assert parsed[0].price_value == expected


# ---------------------------------------------------------------------------
# Edge / skip branches (previously uncovered)
# ---------------------------------------------------------------------------


def test_parser_empty_container_returns_empty_list() -> None:
    """table#pjax_container present but no shortcut_navigable rows → [] (line 118)."""
    html = "<html><body><table id='pjax_container'><tbody></tbody></table></body></html>"
    assert parse_listings(html, release_id=1) == []


def test_parser_skips_row_missing_listing_anchor() -> None:
    """A row without an item_description_title anchor is silently skipped (line 126)."""
    html = """<html><body>
    <table id="pjax_container"><tbody>
      <tr class="shortcut_navigable">
        <td class="item_description">
          <!-- no <a class="item_description_title"> -->
          <p class="item_condition">
            <span class="condition-label-desktop">Media:</span><span>NM</span>
          </p>
        </td>
        <td class="seller_info"><strong><a href="/seller/x">x</a></strong></td>
        <td class="item_price"><span class="price">USD 5.00</span></td>
      </tr>
    </tbody></table>
    </body></html>"""
    assert parse_listings(html, release_id=1) == []


def test_parser_skips_row_with_bad_listing_href() -> None:
    """A row whose title anchor href has no /sell/item/<id> is skipped (line 130)."""
    html = """<html><body>
    <table id="pjax_container"><tbody>
      <tr class="shortcut_navigable">
        <td class="item_description">
          <a class="item_description_title" href="/not-a-listing-link">Rec</a>
          <p class="item_condition">
            <span class="condition-label-desktop">Media:</span><span>NM</span>
          </p>
        </td>
        <td class="seller_info"><strong><a href="/seller/x">x</a></strong></td>
        <td class="item_price"><span class="price">USD 5.00</span></td>
      </tr>
    </tbody></table>
    </body></html>"""
    assert parse_listings(html, release_id=1) == []


def test_parser_skips_row_missing_seller_node() -> None:
    """A row without td.seller_info strong a is skipped (line 136)."""
    html = """<html><body>
    <table id="pjax_container"><tbody>
      <tr class="shortcut_navigable">
        <td class="item_description">
          <a class="item_description_title" href="/sell/item/50001">Rec</a>
          <p class="item_condition">
            <span class="condition-label-desktop">Media:</span><span>NM</span>
          </p>
        </td>
        <td class="seller_info"><!-- no <strong><a> --></td>
        <td class="item_price"><span class="price">USD 5.00</span></td>
      </tr>
    </tbody></table>
    </body></html>"""
    assert parse_listings(html, release_id=1) == []


def test_parser_skips_row_with_unrecognized_condition() -> None:
    """A row whose media condition cannot be normalized is skipped (line 147)."""
    html = """<html><body>
    <table id="pjax_container"><tbody>
      <tr class="shortcut_navigable">
        <td class="item_description">
          <a class="item_description_title" href="/sell/item/60001">Rec</a>
          <p class="item_condition">
            <span class="condition-label-desktop">Media:</span>
            <span>UNKNOWN_CONDITION_XYZ</span>
          </p>
        </td>
        <td class="seller_info"><strong><a href="/seller/x">x</a></strong></td>
        <td class="item_price"><span class="price">USD 5.00</span></td>
      </tr>
    </tbody></table>
    </body></html>"""
    assert parse_listings(html, release_id=1) == []


def test_parser_skips_row_missing_price() -> None:
    """A row with no price span is skipped (line 171)."""
    html = """<html><body>
    <table id="pjax_container"><tbody>
      <tr class="shortcut_navigable">
        <td class="item_description">
          <a class="item_description_title" href="/sell/item/70001">Rec</a>
          <p class="item_condition">
            <span class="condition-label-desktop">Media:</span><span>NM</span>
          </p>
        </td>
        <td class="seller_info"><strong><a href="/seller/x">x</a></strong></td>
        <td class="item_price"><!-- no <span class="price"> --></td>
      </tr>
    </tbody></table>
    </body></html>"""
    assert parse_listings(html, release_id=1) == []


def test_parser_skips_row_with_empty_seller_username() -> None:
    """A row whose seller anchor has empty text is skipped (line 139)."""
    html = """<html><body>
    <table id="pjax_container"><tbody>
      <tr class="shortcut_navigable">
        <td class="item_description">
          <a class="item_description_title" href="/sell/item/75001">Rec</a>
          <p class="item_condition">
            <span class="condition-label-desktop">Media:</span><span>NM</span>
          </p>
        </td>
        <td class="seller_info"><strong><a href="/seller/empty">   </a></strong></td>
        <td class="item_price"><span class="price">USD 5.00</span></td>
      </tr>
    </tbody></table>
    </body></html>"""
    assert parse_listings(html, release_id=1) == []


def test_normalize_condition_exact_match_fallback() -> None:
    """A bare valid token with no parens and no spaces uses exact-match fallback (line 62)."""
    # "VG" is in _VALID_MEDIA; no parenthetical form, no leading-prefix split needed
    html = """<html><body>
    <table id="pjax_container"><tbody>
      <tr class="shortcut_navigable">
        <td class="item_description">
          <a class="item_description_title" href="/sell/item/80001">Rec</a>
          <p class="item_condition">
            <span class="condition-label-desktop">Media:</span><span>VG</span>
          </p>
        </td>
        <td class="seller_info"><strong><a href="/seller/x">x</a></strong></td>
        <td class="item_price"><span class="price">USD 3.00</span></td>
      </tr>
    </tbody></table>
    </body></html>"""
    parsed = parse_listings(html, release_id=1)
    assert len(parsed) == 1
    assert parsed[0].media_condition == "VG"


def test_parser_skips_row_with_invalid_price_decimal() -> None:
    """A price that matches the regex but cannot be parsed as Decimal is skipped (lines 175-176)."""
    # _PRICE_RE matches "USD ..." then _normalize_amount is called;
    # "USD .." produces a currency match but an empty/invalid numeric part → InvalidOperation
    html = """<html><body>
    <table id="pjax_container"><tbody>
      <tr class="shortcut_navigable">
        <td class="item_description">
          <a class="item_description_title" href="/sell/item/90001">Rec</a>
          <p class="item_condition">
            <span class="condition-label-desktop">Media:</span><span>NM</span>
          </p>
        </td>
        <td class="seller_info"><strong><a href="/seller/x">x</a></strong></td>
        <td class="item_price"><span class="price">USD ..</span></td>
      </tr>
    </tbody></table>
    </body></html>"""
    assert parse_listings(html, release_id=1) == []
