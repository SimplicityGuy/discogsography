"""Data normalization utilities for Discogs data.

The Rust extractor now handles structural normalization (flattening nested
containers, stripping @ prefixes, unwrapping #text).  This module retains
only consumer-side concerns: year parsing and the normalize_record() entry
point that consumers call.
"""

from typing import Any

import structlog


logger = structlog.get_logger(__name__)


def _parse_year_int(value: Any) -> int | None:
    """Parse a Discogs year value into an integer.

    Handles both plain year strings ("1969", as used in Master.<year>) and
    full/partial date strings ("1969-09-26", "1969-00-00", as used in
    Release.<released>).  Returns None when no valid year is found.

    Note: The extractor's ``nullify_when`` filter now converts sentinel years
    (year < 1860, including 0) to null before messages reach consumers.  The
    ``year == 0`` check below is a defensive fallback for extractions run
    without the updated rules config.
    """
    if value is None:
        return None
    if isinstance(value, int):
        return value if value != 0 else None
    s = str(value).strip()
    if not s:
        return None
    try:
        year = int(s[:4])
        return year if year != 0 else None
    except ValueError:
        return None


def normalize_record(data_type: str, data: dict[str, Any]) -> dict[str, Any]:
    """Normalize a record based on its data type.

    The Rust extractor now handles structural normalization. This function
    performs only consumer-side transforms:
    - Parse year fields from date strings

    Args:
        data_type: The type of record ("artists", "labels", "masters", "releases")
        data: The record data (already structurally normalized by the extractor)

    Returns:
        Record data with consumer-side transforms applied
    """
    if data_type == "masters":
        data["year"] = _parse_year_int(data.get("year"))
    elif data_type == "releases":
        data["year"] = _parse_year_int(data.get("released"))

    return data
