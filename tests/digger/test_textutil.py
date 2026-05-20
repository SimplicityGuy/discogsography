"""Tests for digger.scraper._textutil shared text-sanitization helpers."""

from __future__ import annotations

from digger.scraper._textutil import clean_node, clean_str


def test_clean_str_removes_html_tags() -> None:
    """clean_str strips all HTML tags but keeps text content."""
    assert clean_str("<b>hello</b>") == "hello"


def test_clean_str_returns_empty_for_none() -> None:
    """clean_str returns empty string for None input."""
    assert clean_str(None) == ""


def test_clean_str_returns_empty_for_empty_string() -> None:
    """clean_str returns empty string for empty-string input."""
    assert clean_str("") == ""


def test_clean_node_returns_empty_for_none_node() -> None:
    """clean_node returns empty string when node is None (line 24 in _textutil.py)."""
    assert clean_node(None) == ""
