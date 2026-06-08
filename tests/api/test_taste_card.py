"""Tests for api/taste_card.py."""

from api.models import TasteDriftYear
from api.taste_card import render_taste_card


def _default_card(**overrides: object) -> str:
    """Render a card with sensible defaults, allowing overrides."""
    kwargs: dict[str, object] = {
        "peak_decade": 1990,
        "obscurity_score": 0.65,
        "top_genres": [("Rock", 120), ("Electronic", 90), ("Jazz", 40)],
        "top_labels": [("Warp Records", 30), ("4AD", 18)],
        "drift": [
            TasteDriftYear(year="2020", top_genre="Rock", count=10),
            TasteDriftYear(year="2021", top_genre="Electronic", count=8),
        ],
    }
    kwargs.update(overrides)
    return render_taste_card(**kwargs)  # type: ignore[arg-type]


class TestRenderTasteCard:
    def test_valid_svg(self) -> None:
        svg = _default_card()
        assert svg.startswith("<svg")
        assert svg.endswith("</svg>")
        assert 'width="1200"' in svg
        assert 'height="630"' in svg

    def test_size_limit(self) -> None:
        svg = _default_card()
        # SVG should stay reasonably small for an inline asset.
        assert len(svg) < 20_000

    def test_none_decade(self) -> None:
        svg = _default_card(peak_decade=None)
        assert "N/A" in svg

    def test_decade_present(self) -> None:
        svg = _default_card(peak_decade=1990)
        assert "1990s" in svg

    def test_empty_lists(self) -> None:
        svg = _default_card(top_genres=[], top_labels=[], drift=[])
        assert svg.startswith("<svg")
        assert svg.endswith("</svg>")
        # Graceful empty-state placeholders, no crash.
        assert "No data yet" in svg
        assert "No drift data yet" in svg

    def test_special_chars_escaped(self) -> None:
        svg = _default_card(top_genres=[("Rock & Roll", 10), ("R&B", 5)])
        assert "Rock &amp; Roll" in svg
        assert "R&amp;B" in svg

    def test_xss_injection(self) -> None:
        malicious = '<script>alert("xss")</script>'
        svg = _default_card(top_genres=[(malicious, 1)])
        assert "<script>" not in svg
        assert "&lt;script&gt;" in svg

    def test_xss_injection_in_drift(self) -> None:
        svg = _default_card(drift=[TasteDriftYear(year="2020", top_genre="<b>x</b>", count=1)])
        assert "<b>x</b>" not in svg
        assert "&lt;b&gt;x&lt;/b&gt;" in svg

    def test_obscurity_percentage(self) -> None:
        svg = _default_card(obscurity_score=0.65)
        assert "65%" in svg

    def test_obscurity_ring_bounds(self) -> None:
        # Extremes render without error and show the right percentage.
        assert "0%" in _default_card(obscurity_score=0.0)
        assert "100%" in _default_card(obscurity_score=1.0)

    def test_drift_year_labels(self) -> None:
        svg = _default_card()
        # Years are rendered as axis labels under the sparkline.
        assert ">2020<" in svg
        assert ">2021<" in svg

    def test_drift_genre_in_tooltip(self) -> None:
        svg = _default_card()
        # Genre is preserved in the point tooltip.
        assert "2020: Rock" in svg

    def test_single_drift_point(self) -> None:
        svg = _default_card(drift=[TasteDriftYear(year="2024", top_genre="Pop", count=3)])
        assert svg.startswith("<svg")
        assert ">2024<" in svg

    def test_label_entries(self) -> None:
        svg = _default_card()
        assert "Warp Records" in svg
        assert "4AD" in svg

    def test_genre_counts_rendered(self) -> None:
        svg = _default_card()
        assert "Rock" in svg
        # Counts are shown alongside the bars (formatted with thousands separators).
        assert "120" in svg

    def test_branding_present(self) -> None:
        assert "discogsography" in _default_card()
