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


@pytest.fixture(autouse=True)
def reset_extraction_complete_signals():
    """Reset the extraction_complete signal latch between tests.

    check_file_completion defers stub cleanup until every data type has
    signalled extraction_complete, tracked in a module-level set. Leaking that
    set across tests would let one test's partial signals trigger (or suppress)
    cleanup in another.
    """
    import graphinator.graphinator as g

    saved = set(g.extraction_complete_signals)
    g.extraction_complete_signals = set()
    yield
    g.extraction_complete_signals = saved
