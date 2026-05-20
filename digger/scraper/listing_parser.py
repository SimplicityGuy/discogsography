"""Discogs marketplace listing-page parser.

Listings are <tr class="shortcut_navigable"> rows within table#pjax_container.
Fields extracted via selectolax CSS selectors; seller comments are sanitized
through bleach.clean(strip=True) to neutralize any HTML injection.

The parser does NOT touch metrics — callers (ScrapeExecutor) are responsible
for incrementing digger_unknown_layout_total when UnknownLayoutError is raised.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import cast

from selectolax.parser import HTMLParser

from digger.scraper._textutil import clean_node
from digger.scraper.types import Condition, ParsedListing, SleeveCondition


class UnknownLayoutError(RuntimeError):
    """Raised when the page structure does not match expected Discogs layout.

    Specifically: the page is not empty/no-listings but table#pjax_container
    is absent, indicating a structural layout change or an unexpected page type.
    """


# Matches "USD 12.99", "EUR 8.500,00", etc. — currency code then numeric amount
# (digits with optional grouping/decimal separators). Match on the ORIGINAL
# string so locale normalization can inspect both separators.
_PRICE_RE = re.compile(r"([A-Z]{3})\s*([\d,.]+)")

# Extract listing_id from href like "/sell/item/12345678"
_LISTING_ID_RE = re.compile(r"/sell/item/(\d+)")

_VALID_MEDIA: frozenset[str] = frozenset({"M", "NM", "VG+", "VG", "G+", "G", "F", "P"})
_VALID_SLEEVE: frozenset[str] = _VALID_MEDIA | frozenset({"generic", "no_cover"})


def _normalize_condition(raw: str, valid: frozenset[str]) -> str | None:
    """Normalize a condition string to one of the known enum values.

    Handles both plain values ("NM (Near Mint)") and the parenthetical
    OR form ("(NM or better)"). Returns None if no valid token is found.
    """
    raw = raw.strip()
    # Try the "(X or better)" / "(X or Y)" form first.
    paren_match = re.search(r"\(([^)]+)\)", raw)
    if paren_match:
        for token in paren_match.group(1).split("or"):
            t = token.strip()
            if t in valid:
                return t
    # Try plain prefix match (e.g. "NM (Near Mint)" → "NM").
    parts = raw.split()
    if parts and parts[0] in valid:
        return parts[0]
    # Exact match fallback.
    return raw if raw in valid else None


def _normalize_amount(numeric_str: str) -> str:
    """Normalize a locale-formatted numeric string to a Decimal-parseable form.

    Distinguishes thousands separators from the decimal separator by which
    symbol appears LAST:
      - "1,299.00" (en) → "1299.00"  (comma = thousands, dot = decimal)
      - "8.500,00" (de/eu) → "8500.00"  (dot = thousands, comma = decimal)
      - "1299" / "12.99" / "8,50" handled as the single-separator cases.
    """
    has_comma = "," in numeric_str
    has_dot = "." in numeric_str
    # Comma is the decimal separator when it appears after the last dot
    # (or when there's no dot at all but a comma is present).
    if has_comma and (not has_dot or numeric_str.rfind(",") > numeric_str.rfind(".")):
        return numeric_str.replace(".", "").replace(",", ".")
    # Otherwise dot (if any) is the decimal separator; commas are thousands groups.
    return numeric_str.replace(",", "")


def parse_listings(html: str, release_id: int) -> list[ParsedListing]:
    """Parse a Discogs marketplace release listing page into structured records.

    Args:
        html: Full HTML of the Discogs /sell/release/<id> page.
        release_id: The Discogs release ID to embed in every ParsedListing.

    Returns:
        A list of ParsedListing instances (may be empty if no listings exist).

    Raises:
        UnknownLayoutError: When the page neither signals "no listings" nor
            contains the expected table#pjax_container, suggesting a layout
            change that requires manual investigation.
    """
    tree = HTMLParser(html)

    # ---- fast-path: explicit no-listings signals ----
    if "No listings available" in html:
        return []
    no_results = tree.css_first("div.no-results")
    if no_results is not None:
        return []

    # ---- require the primary container ----
    container = tree.css_first("table#pjax_container")
    if container is None:
        raise UnknownLayoutError(
            "expected table#pjax_container missing — layout may have changed"
        )

    rows = tree.css("table#pjax_container tr.shortcut_navigable")
    if not rows:
        # Container exists but is empty — legitimate "no listings" state.
        return []

    results: list[ParsedListing] = []

    for row in rows:
        # ---- listing_id from the title anchor href ----
        listing_anchor = row.css_first("a.item_description_title")
        if listing_anchor is None:
            continue
        href: str = listing_anchor.attributes.get("href") or ""
        id_match = _LISTING_ID_RE.search(href)
        if not id_match:
            continue
        listing_id = int(id_match.group(1))

        # ---- seller username ----
        seller_node = row.css_first("td.seller_info strong a")
        if seller_node is None:
            continue
        seller_username = clean_node(seller_node)
        if not seller_username:
            continue

        # ---- media condition ----
        media_raw = clean_node(
            row.css_first("p.item_condition span.condition-label-desktop + span")
        )
        media_str = _normalize_condition(media_raw, _VALID_MEDIA)
        if media_str is None:
            continue  # skip rows with unrecognized condition
        media = cast("Condition", media_str)

        # ---- sleeve condition (defaults to "generic" if absent/unrecognized) ----
        sleeve_raw = clean_node(row.css_first("p.item_sleeve_condition span"))
        sleeve_raw2 = (
            clean_node(
                row.css_first(
                    "p.item_sleeve_condition span.condition-label-desktop + span"
                )
            )
            or sleeve_raw
        )
        sleeve = cast(
            "SleeveCondition",
            _normalize_condition(sleeve_raw2, _VALID_SLEEVE) or "generic",
        )

        # ---- price ----
        # Match on the ORIGINAL string so locale normalization can inspect
        # both separators (en uses "1,299.00", de/eu uses "8.500,00").
        price_raw = clean_node(row.css_first("td.item_price span.price"))
        price_match = _PRICE_RE.search(price_raw)
        if not price_match:
            continue
        currency = price_match.group(1)
        try:
            price_value = Decimal(_normalize_amount(price_match.group(2)))
        except InvalidOperation:
            continue

        # ---- optional seller comment (bleach-sanitized) ----
        comments = clean_node(row.css_first("p.item_description_comments")) or None

        results.append(
            ParsedListing(
                listing_id=listing_id,
                release_id=release_id,
                seller_username=seller_username,
                price_value=price_value,
                price_currency=currency,
                media_condition=media,
                sleeve_condition=sleeve,
                comments=comments,
            )
        )

    return results
