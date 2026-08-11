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


@pytest.fixture(autouse=True)
def instant_maintenance_delays():
    """Collapse post-import maintenance wall-clock delays to zero.

    Maintenance staggers heavy queries (MAINTENANCE_SETTLE_SECONDS) and backs
    off on Neo4j transaction-memory pressure (MAINTENANCE_RETRY_BASE_DELAY_SECONDS).
    Those are production pacing values; tests assert the control flow, not the
    clock, so waiting on them would only make the suite slow.
    """
    with (
        patch("graphinator.graphinator.MAINTENANCE_SETTLE_SECONDS", 0.0),
        patch("graphinator.graphinator.MAINTENANCE_RETRY_BASE_DELAY_SECONDS", 0.0),
        patch("graphinator.graphinator.POST_IMPORT_MAINTENANCE_RETRY_DELAY_SECONDS", 0.0),
    ):
        yield


@pytest.fixture(autouse=True)
def reset_post_import_maintenance_task():
    """Clear the detached post-import maintenance task between tests.

    Post-import maintenance runs in its own task so the extraction_complete
    delivery can be acked immediately (discogsography-zjja). The task handle is
    module-level and single-flight, so a leaked handle from one test would make
    the next test's trigger a no-op — or have it await the wrong task.
    """
    import graphinator.graphinator as g

    g.post_import_maintenance_task = None
    g.maintenance_tasks = set()
    yield
    task = g.post_import_maintenance_task
    if task is not None and not task.done():
        task.cancel()
    g.post_import_maintenance_task = None
    g.maintenance_tasks = set()
