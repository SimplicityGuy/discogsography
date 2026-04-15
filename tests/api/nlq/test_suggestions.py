"""Tests for NLQ template-based suggestions."""

from __future__ import annotations


def test_suggestions_explore_no_focus_uses_default_set() -> None:
    from api.nlq.suggestions import build_suggestions

    result = build_suggestions(pane="explore", focus=None, focus_type=None)
    assert len(result) >= 4
    assert all(isinstance(q, str) for q in result)


def test_suggestions_explore_with_artist_focus_substitutes_name() -> None:
    from api.nlq.suggestions import build_suggestions

    result = build_suggestions(pane="explore", focus="Kraftwerk", focus_type="artist")
    assert any("Kraftwerk" in q for q in result)
    assert len(result) >= 4
    assert len(result) <= 6


def test_suggestions_unknown_pane_falls_back_to_default() -> None:
    from api.nlq.suggestions import build_suggestions

    result = build_suggestions(pane="nonexistent", focus=None, focus_type=None)
    assert len(result) >= 4


def test_suggestions_focus_length_cap() -> None:
    from api.nlq.suggestions import build_suggestions

    oversized = "x" * 1000
    result = build_suggestions(pane="explore", focus=oversized, focus_type="artist")
    assert all(len(q) <= 256 for q in result)
