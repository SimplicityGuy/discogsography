"""Shared text-sanitization helpers for digger scraper parsers.

All seller-supplied text (comments, usernames, region names, country labels)
must pass through bleach to neutralize any HTML injection before it reaches
the DB or downstream consumers.
"""

from __future__ import annotations

import bleach
from selectolax.parser import Node


def clean_str(raw: str | None) -> str:
    """Strip all HTML tags from a raw string via bleach.

    Args:
        raw: Untrusted text, possibly containing HTML.

    Returns:
        The text with all HTML tags removed (entities decoded, content kept).
    """
    if not raw:
        return ""
    # bleach.clean returns Any (no stubs); we know it's always str.
    result: str = bleach.clean(raw, tags=[], strip=True)
    return result


def clean_node(node: Node | None) -> str:
    """Extract text from a selectolax node and strip any HTML via bleach.

    Args:
        node: A selectolax node or None.

    Returns:
        The node's sanitized text, or an empty string if node is None.
    """
    if node is None:
        return ""
    return clean_str(node.text(strip=True))
