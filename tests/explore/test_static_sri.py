"""Guard SRI-pinned static assets against floating (unversioned) URLs.

A ``integrity`` hash only matches one exact set of bytes. If the URL it is paired with
can change content (e.g. ``https://d3js.org/d3.v7.min.js``, which now serves a newer
release), the browser blocks the asset and the page breaks. Every SRI-pinned
``<script>``/``<link>`` in the Explore and Dashboard static HTML must therefore point at
a version-pinned URL.
"""

from html.parser import HTMLParser
from pathlib import Path
import re

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIRS = [REPO_ROOT / "explore" / "static", REPO_ROOT / "dashboard" / "static"]

# A version pin is a semver-like token in the URL: ``d3@7.9.0``, ``plotly-2.27.0.min.js``,
# ``marked@18.0.0/+esm``. Bare major-only pins such as ``chart.js@4`` are not accepted.
VERSION_PIN = re.compile(r"\d+\.\d+(?:\.\d+)?")


class _SRITagCollector(HTMLParser):
    """Collect (tag, url) for every script/link element carrying an integrity attribute."""

    def __init__(self) -> None:
        super().__init__()
        self.found: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in ("script", "link"):
            return
        attr_map = dict(attrs)
        if attr_map.get("integrity") is None:
            return
        url = attr_map.get("src") if tag == "script" else attr_map.get("href")
        if url:
            self.found.append((tag, url))


def _is_remote(url: str) -> bool:
    return url.startswith(("http://", "https://", "//"))


def _unversioned_sri_urls(html: str) -> list[tuple[str, str]]:
    """Return the (tag, url) pairs with an integrity hash whose remote URL has no version pin."""
    collector = _SRITagCollector()
    collector.feed(html)
    return [(tag, url) for tag, url in collector.found if _is_remote(url) and not VERSION_PIN.search(url)]


def _static_html_files() -> list[Path]:
    files: list[Path] = []
    for static_dir in STATIC_DIRS:
        files.extend(sorted(static_dir.rglob("*.html")))
    return files


@pytest.mark.parametrize("html_file", _static_html_files(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_sri_pinned_assets_use_versioned_urls(html_file: Path) -> None:
    """Every SRI-pinned remote script/link in the static HTML must use a versioned URL."""
    offenders = _unversioned_sri_urls(html_file.read_text(encoding="utf-8"))
    assert not offenders, (
        f"{html_file.relative_to(REPO_ROOT)} pairs an integrity hash with an unversioned URL (the content can change under the hash): {offenders}"
    )


def test_static_html_files_are_discovered() -> None:
    """Guard against the scan silently covering nothing."""
    names = {p.name for p in _static_html_files()}
    assert "index.html" in names
    assert "admin.html" in names


def test_detector_flags_floating_url_and_accepts_pinned_url() -> None:
    """Self-check: the detector must catch the d3 regression and accept the pinned replacement."""
    floating = '<script src="https://d3js.org/d3.v7.min.js" integrity="sha384-abc" crossorigin="anonymous"></script>'
    pinned = '<script src="https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js" integrity="sha384-abc"></script>'
    local = '<link rel="stylesheet" href="/static/app.css" integrity="sha384-abc">'
    unhashed = '<script src="https://d3js.org/d3.v7.min.js"></script>'

    assert _unversioned_sri_urls(floating) == [("script", "https://d3js.org/d3.v7.min.js")]
    assert _unversioned_sri_urls(pinned) == []
    assert _unversioned_sri_urls(local) == []
    assert _unversioned_sri_urls(unhashed) == []
