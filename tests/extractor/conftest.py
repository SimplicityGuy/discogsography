"""Extractor test fixtures."""

from pathlib import Path

import pytest


@pytest.fixture
def test_discogs_root(tmp_path: Path) -> Path:
    """Provide a temporary discogs root directory for testing."""
    discogs_root = tmp_path / "discogs"
    discogs_root.mkdir(exist_ok=True)
    return discogs_root
