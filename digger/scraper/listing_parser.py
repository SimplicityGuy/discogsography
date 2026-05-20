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

import bleach
from selectolax.parser import HTMLParser, Node

from digger.scraper.types import Condition, ParsedListing, SleeveCondition


class UnknownLayoutError(RuntimeError):
    """Raised when the page structure does not match expected Discogs layout.

    Specifically: the page is not empty/no-listings but table#pjax_container
    is absent, indicating a structural layout change or an unexpected page type.
    """


# Matches "USD 12.99", "EUR 8,500.00", etc. — currency code then numeric amount.
_PRICE_RE = re.compile(r"([A-Z]{3})\s*([\d,.]+)")

# Extract listing_id from href like "/sell/item/12345678"
_LISTING_ID_RE = re.compile(r"/sell/item/(\d+)")

_VALID_MEDIA: frozenset[str] = frozenset({"M", "NM", "VG+", "VG", "G+", "G", "F", "P"})
_VALID_SLEEVE: frozenset[str] = _VALID_MEDIA | frozenset({"generic", "no_cover"})


def _clean_text(node: Node | None) -> str:
    """Extract text from a selectolax node and strip any HTML via bleach."""
    if node is None:
        return ""
    raw = node.text(strip=True) or ""
    # bleach.clean returns Any (no stubs); we know it's always str.
    result: str = bleach.clean(raw, tags=[], strip=True)
    return result


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
        seller_username = _clean_text(seller_node)
        if not seller_username:
            continue

        # ---- media condition ----
        media_raw = _clean_text(
            row.css_first("p.item_condition span.condition-label-desktop + span")
        )
        media_str = _normalize_condition(media_raw, _VALID_MEDIA)
        if media_str is None:
            continue  # skip rows with unrecognized condition
        media = cast("Condition", media_str)

        # ---- sleeve condition (defaults to "generic" if absent/unrecognized) ----
        sleeve_raw = _clean_text(row.css_first("p.item_sleeve_condition span"))
        sleeve_raw2 = (
            _clean_text(
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
        price_raw = _clean_text(row.css_first("td.item_price span.price"))
        # Remove thousands separators before parsing.
        price_raw_clean = price_raw.replace(",", "")
        price_match = _PRICE_RE.search(price_raw_clean)
        if not price_match:
            continue
        currency = price_match.group(1)
        try:
            price_value = Decimal(price_match.group(2))
        except InvalidOperation:
            continue

        # ---- optional seller comment (bleach-sanitized) ----
        comments = _clean_text(row.css_first("p.item_description_comments")) or None

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
