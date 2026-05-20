"""Tests for the Discogs listing-page parser.

Fixtures are SYNTHETIC HTML files hand-authored to match the documented Discogs
DOM structure as of 2026-05. They exercise parser logic but do NOT prove
real-Discogs compatibility (deferred to Task 28 / manual QA).
"""

from pathlib import Path

import pytest

from digger.scraper.listing_parser import UnknownLayoutError, parse_listings
from digger.scraper.types import ParsedListing


FIXTURES = Path(__file__).parent / "fixtures"


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
