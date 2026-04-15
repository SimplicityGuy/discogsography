"""E2E test fixtures for Playwright browser tests."""

import pytest


@pytest.fixture(scope="session")
def explore_url() -> str:
    """Return the URL of the explore service for E2E tests."""
    return "http://localhost:8006"
