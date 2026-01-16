"""Pytest configuration for tableinator tests."""

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def disable_batch_mode():
    """Disable batch mode for all tableinator tests.

    The tests mock the old per-message processing flow, so we need to
    disable batch mode to use that code path.
    """
    with patch("tableinator.tableinator.BATCH_MODE", False), patch("tableinator.tableinator.batch_processor", None):
        yield
