"""Tests for api/taste_card.py."""

from api.models import TasteDriftYear
from api.taste_card import render_taste_card


def _default_card(**overrides: object) -> str:
    """Render a card with sensible defaults, allowing overrides."""
    kwargs: dict[str, object] = {
        "peak_decade": 1990,
        "obscurity_score": 0.65,
        "top_genres": ["Rock", "Electronic", "Jazz"],
        "top_labels": ["Warp Records", "4AD"],
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
        assert 'width="600"' in svg
        assert 'height="400"' in svg

    def test_size_limit(self) -> None:
        svg = _default_card()
        # SVG should be reasonably small (< 10KB for a simple card)
        assert len(svg) < 10_000

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

    def test_special_chars_escaped(self) -> None:
        svg = _default_card(top_genres=["Rock & Roll", "R&B"])
        assert "Rock &amp; Roll" in svg
        assert "R&amp;B" in svg

    def test_xss_injection(self) -> None:
        malicious = '<script>alert("xss")</script>'
        svg = _default_card(top_genres=[malicious])
        assert "<script>" not in svg
        assert "&lt;script&gt;" in svg

    def test_bar_width_clamped_low(self) -> None:
        svg = _default_card(obscurity_score=0.0)
        # 0.0 * 200 = 0 -> clamped to 4
        assert 'width="4"' in svg

    def test_bar_width_clamped_high(self) -> None:
        svg = _default_card(obscurity_score=1.0)
        # 1.0 * 200 = 200
        assert 'width="200"' in svg

    def test_obscurity_percentage(self) -> None:
        svg = _default_card(obscurity_score=0.65)
        assert "65%" in svg

    def test_drift_entries(self) -> None:
        svg = _default_card()
        assert "2020: Rock" in svg
        assert "2021: Electronic" in svg

    def test_label_entries(self) -> None:
        svg = _default_card()
        assert "Warp Records" in svg
        assert "4AD" in svg
