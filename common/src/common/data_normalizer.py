"""Data normalization utilities for Discogs data.

The Rust extractor now handles structural normalization (flattening nested
containers, stripping @ prefixes, unwrapping #text).  This module retains
only consumer-side concerns: year parsing and the normalize_record() entry
point that consumers call.
"""

from datetime import UTC, datetime
from typing import Any

import structlog


logger = structlog.get_logger(__name__)

#: Earliest plausible release year.  Sound recording predates this only
#: marginally (Scott de Martinville's phonautograms, 1857), so anything
#: earlier is a data error — typos, sentinels, or mis-parsed dates.
#: Must stay in sync with the year bounds in ``extractor/extraction-rules.yaml``.
MIN_RELEASE_YEAR = 1860


def _max_release_year() -> int:
    """Latest plausible release year: next calendar year (allows pre-orders/announcements)."""
    return datetime.now(UTC).year + 1


def _parse_year_int(value: Any) -> int | None:
    """Parse a Discogs year value into a *plausible* integer year.

    Handles both plain year strings ("1969", as used in Master.<year>) and
    full/partial date strings ("1969-09-26", "1969-00-00", as used in
    Release.<released>).  Returns None when no valid year is found **or** when
    the year falls outside ``[MIN_RELEASE_YEAR, current_year + 1]``.

    This is the authoritative year gate for releases.  The extractor's
    ``nullify_when`` / ``year-out-of-range`` rules key on a record's ``year``
    field, but a Discogs *release* carries its date in ``released`` (a date
    string) and has no ``year`` field at extraction time — so those rules are
    no-ops for releases.  Release (and master) years are derived here, so the
    plausibility bound must be enforced here too; otherwise dates like
    ``"0400-01-01"`` leak into the graph as year 400.
    """
    if value is None:
        return None
    if isinstance(value, int):
        year = value
    else:
        s = str(value).strip()
        if not s:
            return None
        try:
            year = int(s[:4])
        except ValueError:
            return None
    if MIN_RELEASE_YEAR <= year <= _max_release_year():
        return year
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
