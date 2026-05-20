"""Discogs seller-profile parser.

Extracts seller_id, username, country code, feedback summary, and shipping
policy from a Discogs /seller/<username> page.

Shipping policy is normalized to:
    {region_name: {"first_cents": int, "additional_cents": int, "currency": str}}

Returns None for shipping_policy if the page doesn't expose a shipping table.
The parser raises ValueError if the page has no seller link, or if the link
carries no numeric user ID (either case is a wrong/invalid page type). All
seller-supplied text is sanitized through bleach before use.
"""

from __future__ import annotations

import re
from decimal import Decimal

from selectolax.parser import HTMLParser

from digger.scraper._textutil import clean_node
from digger.scraper.types import ParsedSeller


_SELLER_ID_RE = re.compile(r"/users/(\d+)")

# Map of Discogs country display names → ISO 3166-1 alpha-2 codes.
_COUNTRY_MAP: dict[str, str] = {
    "Australia": "AU",
    "Austria": "AT",
    "Belgium": "BE",
    "Brazil": "BR",
    "Canada": "CA",
    "Denmark": "DK",
    "Finland": "FI",
    "France": "FR",
    "Germany": "DE",
    "Greece": "GR",
    "Hungary": "HU",
    "Ireland": "IE",
    "Italy": "IT",
    "Japan": "JP",
    "Netherlands": "NL",
    "New Zealand": "NZ",
    "Norway": "NO",
    "Poland": "PL",
    "Portugal": "PT",
    "Russia": "RU",
    "South Korea": "KR",
    "Spain": "ES",
    "Sweden": "SE",
    "Switzerland": "CH",
    "Ukraine": "UA",
    "United Kingdom": "GB",
    "United States": "US",
}


def _to_cents(raw: str) -> int:
    """Convert a price string like "$4.00" or "4.00" to integer cents."""
    cleaned = re.sub(r"[^0-9.]", "", raw)
    if not cleaned:
        return 0
    try:
        return int(Decimal(cleaned) * 100)
    except Exception:
        return 0


def parse_seller_profile(html: str) -> ParsedSeller:
    """Parse a Discogs seller profile page into a ParsedSeller model.

    Args:
        html: Full HTML of the Discogs /seller/<username> page.

    Returns:
        A ParsedSeller with extracted fields. shipping_policy is None if the
        page contains no shipping table.

    Raises:
        ValueError: If no seller link (an anchor whose href contains /users/)
            is found, or if such a link exists but has no numeric user ID —
            either case indicates this is not a valid seller profile page.
            A bogus seller_id would poison the digger.sellers FK in Task 12.
    """
    tree = HTMLParser(html)

    # ---- seller_id from any anchor linking to /users/<id> ----
    seller_link = tree.css_first("a[href*='/users/']")
    if seller_link is None:
        raise ValueError("seller link missing — not a seller profile page")

    href: str = seller_link.attributes.get("href") or ""
    id_match = _SELLER_ID_RE.search(href)
    if id_match is None:
        raise ValueError(
            f"no numeric user ID found in href {href!r} — not a valid seller profile page"
        )
    seller_id = int(id_match.group(1))

    # ---- username: prefer h1.profile-name, fall back to link text (bleach-sanitized) ----
    username_node = tree.css_first("h1.profile-name")
    username = clean_node(username_node) if username_node else clean_node(seller_link)

    # ---- country code (bleach-sanitized before lookup) ----
    country_node = tree.css_first("div.profile-country")
    country_text = clean_node(country_node)
    country_code = _COUNTRY_MAP.get(country_text)

    # ---- feedback ----
    feedback_count: int | None = None
    feedback_score: Decimal | None = None
    count_node = tree.css_first("span.feedback-count")
    score_node = tree.css_first("span.feedback-score")
    if count_node is not None:
        try:
            feedback_count = int(clean_node(count_node).replace(",", ""))
        except ValueError:
            pass
    if score_node is not None:
        try:
            feedback_score = Decimal(clean_node(score_node).rstrip("%"))
        except (ValueError, ArithmeticError):
            pass

    # ---- shipping policy table (all seller-supplied text bleach-sanitized) ----
    shipping_policy: dict[str, dict[str, object]] = {}
    for row in tree.css("table.shipping-policies tr.region-row"):
        region_node = row.css_first("td.region-name")
        first_node = row.css_first("td.first-item-cost")
        addl_node = row.css_first("td.additional-item-cost")
        if not (region_node and first_node and addl_node):
            continue
        region_key = clean_node(region_node).lower()
        shipping_policy[region_key] = {
            "first_cents": _to_cents(clean_node(first_node)),
            "additional_cents": _to_cents(clean_node(addl_node)),
            "currency": "USD",
        }

    return ParsedSeller(
        seller_id=seller_id,
        username=username,
        country_code=country_code,
        feedback_count=feedback_count,
        feedback_score=feedback_score,
        ships_internationally=bool(shipping_policy),
        shipping_policy=shipping_policy or None,
    )
