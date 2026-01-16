"""Pytest configuration for graphinator tests."""

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def disable_batch_mode():
    """Disable batch mode for all graphinator tests.

    The tests mock the old per-message processing flow, so we need to
    disable batch mode to use that code path.
    """
    with patch("graphinator.graphinator.BATCH_MODE", False), patch("graphinator.graphinator.batch_processor", None):
        yield
