"""Regression test for discogsography-cu2.35.

Pins dashboard/static/admin.js's DLQ name generation to the backend contract
in api/routers/admin.py::_VALID_DLQ_NAMES so the two lists can never silently
drift apart again (they previously used incompatible naming shapes, causing
every DLQ purge button to 404).
"""

from pathlib import Path
import re

from api.routers.admin import _VALID_DLQ_NAMES
from common.config import DISCOGS_EXCHANGE_PREFIX, MUSICBRAINZ_EXCHANGE_PREFIX


ADMIN_JS_PATH = Path(__file__).parent.parent.parent / "dashboard" / "static" / "admin.js"

_SOURCE_PREFIXES = {
    "discogs": DISCOGS_EXCHANGE_PREFIX,
    "musicbrainz": MUSICBRAINZ_EXCHANGE_PREFIX,
}

_GROUP_RE = re.compile(r"\{\s*source:\s*'(?P<source>\w+)',\s*consumer:\s*'(?P<consumer>[\w-]+)',\s*types:\s*\[(?P<types>[^\]]+)\]\s*\}")
_TYPE_RE = re.compile(r"'([\w-]+)'")


def _parse_dlq_names_from_admin_js() -> set[str]:
    """Extract the DLQ_CONSUMER_GROUPS definition from admin.js and reconstruct queue names."""
    source = ADMIN_JS_PATH.read_text(encoding="utf-8")
    matches = _GROUP_RE.findall(source)
    assert matches, "DLQ_CONSUMER_GROUPS not found (or shape changed) in dashboard/static/admin.js"

    names: set[str] = set()
    for group_source, consumer, types_blob in matches:
        prefix = _SOURCE_PREFIXES[group_source]
        for data_type in _TYPE_RE.findall(types_blob):
            names.add(f"{prefix}-{consumer}-{data_type}.dlq")
    return names


def test_admin_js_dlq_names_match_backend_valid_dlq_names() -> None:
    """admin.js's generated DLQ names must exactly equal the backend's _VALID_DLQ_NAMES.

    Regression for discogsography-cu2.35: the frontend previously hardcoded
    bare `{consumer}-{type}-dlq` names while the backend required
    `{source-exchange-prefix}-{consumer}-{type}.dlq`, so no Purge button could
    ever succeed.
    """
    frontend_names = _parse_dlq_names_from_admin_js()

    assert frontend_names, "Failed to reconstruct any DLQ names from admin.js"
    assert frontend_names == _VALID_DLQ_NAMES, (
        f"admin.js DLQ names drifted from backend _VALID_DLQ_NAMES.\n"
        f"Only in admin.js: {sorted(frontend_names - _VALID_DLQ_NAMES)}\n"
        f"Only in backend:  {sorted(_VALID_DLQ_NAMES - frontend_names)}"
    )


def test_admin_js_dlq_names_all_valid_path_segments() -> None:
    """Every generated DLQ name must satisfy the proxy's safe-path-segment regex."""
    safe_segment = re.compile(r"^[a-zA-Z0-9._-]+$")
    for name in _parse_dlq_names_from_admin_js():
        assert safe_segment.match(name), f"DLQ name {name!r} would be rejected by admin_proxy._validate_path_segment"
