"""Regression tests for discogsography-zjja.

check_file_completion ran post-import maintenance — stub cleanup across every
entity label plus genre/style/label aggregate stats — INLINE in the consumer
callback and acked only afterwards. That work is hours long by the code's own
measurements (~10-30s per node over 16 genres + ~757 styles, ~2.3M labels,
millions of stub DETACH DELETEs), while the delivery sat unacked on the channel
shared by all four consumers. RabbitMQ's 30-minute consumer ack timeout would
close that channel with PRECONDITION_FAILED: every consumer dies, the signal is
redelivered, maintenance restarts from scratch, and after x-delivery-limit=20
redeliveries the trigger is dead-lettered — maintenance never completing at all.

The contract is now: ack the trigger FIRST, run maintenance detached, and let the
task own the retry the nack used to provide.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from aio_pika.abc import AbstractIncomingMessage
import pytest

import graphinator.graphinator as g


EXTRACTION_COMPLETE = {"type": "extraction_complete", "version": "20260101"}


def _final_signal_pending() -> None:
    """Seed the three non-triggering signals so the next one is the last."""
    g.extraction_complete_signals = {"artists", "labels", "masters"}


@pytest.mark.asyncio
async def test_trigger_is_acked_before_maintenance_runs() -> None:
    """The ack must land BEFORE the first maintenance query, not after the last.

    This is the whole defect: any ordering where maintenance precedes the ack
    puts unbounded Neo4j work inside the broker's ack timeout window.
    """
    order: list[str] = []
    message = AsyncMock(spec=AbstractIncomingMessage)
    message.ack = AsyncMock(side_effect=lambda: order.append("ack"))

    async def slow_cleanup() -> bool:
        order.append("cleanup")
        return True

    async def slow_stats() -> bool:
        order.append("stats")
        return True

    _final_signal_pending()
    with (
        patch.object(g, "graph", AsyncMock()),
        patch.object(g, "cleanup_all_stub_nodes", slow_cleanup),
        patch.object(g, "compute_genre_style_stats", slow_stats),
    ):
        handled = await g.check_file_completion(EXTRACTION_COMPLETE, "releases", message)
        await g.post_import_maintenance_task

    assert handled is True
    assert order[0] == "ack", f"the trigger must be acked before any maintenance work: {order}"
    assert order == ["ack", "cleanup", "stats"]


@pytest.mark.asyncio
async def test_handler_returns_without_waiting_for_maintenance() -> None:
    """The consumer callback must not block on maintenance.

    If it did, the broker would see no acks from ANY of the four consumers
    sharing the channel for the whole duration.
    """
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocking_cleanup() -> bool:
        started.set()
        await release.wait()
        return True

    message = AsyncMock(spec=AbstractIncomingMessage)
    _final_signal_pending()
    with (
        patch.object(g, "graph", AsyncMock()),
        patch.object(g, "cleanup_all_stub_nodes", blocking_cleanup),
        patch.object(g, "compute_genre_style_stats", AsyncMock(return_value=True)),
    ):
        handled = await asyncio.wait_for(g.check_file_completion(EXTRACTION_COMPLETE, "releases", message), timeout=1.0)
        # Handler is done while maintenance is still mid-flight.
        await asyncio.wait_for(started.wait(), timeout=1.0)
        assert g.post_import_maintenance_task is not None
        assert not g.post_import_maintenance_task.done()

        release.set()
        assert await g.post_import_maintenance_task is True

    assert handled is True
    message.ack.assert_awaited_once()
    message.nack.assert_not_called()


@pytest.mark.asyncio
async def test_redelivered_trigger_does_not_start_a_second_run() -> None:
    """Single-flight: a redelivery must not run two concurrent Neo4j sweeps."""
    runs = {"n": 0}
    release = asyncio.Event()

    async def blocking_cleanup() -> bool:
        runs["n"] += 1
        await release.wait()
        return True

    _final_signal_pending()
    with (
        patch.object(g, "graph", AsyncMock()),
        patch.object(g, "cleanup_all_stub_nodes", blocking_cleanup),
        patch.object(g, "compute_genre_style_stats", AsyncMock(return_value=True)),
    ):
        first = AsyncMock(spec=AbstractIncomingMessage)
        await g.check_file_completion(EXTRACTION_COMPLETE, "releases", first)
        await asyncio.sleep(0)

        # Same signal redelivered while the first pass is still running.
        second = AsyncMock(spec=AbstractIncomingMessage)
        await g.check_file_completion(EXTRACTION_COMPLETE, "releases", second)

        release.set()
        await g.post_import_maintenance_task

    assert runs["n"] == 1, "a redelivered trigger must not start a concurrent maintenance run"
    # Both deliveries are still acked — an unacked duplicate would rot on the channel.
    first.ack.assert_awaited_once()
    second.ack.assert_awaited_once()


@pytest.mark.asyncio
async def test_maintenance_drains_every_queue_before_cleanup() -> None:
    """discogsography-fyxy: cleanup DETACH DELETEs sha256-less stubs of EVERY label, so
    every batch queue — not just the signalling type's — must be quiescent first.

    The extraction_complete branch flushes only its own data type, and a type whose
    signal was acked earlier can still hold pending messages: _flush_queue re-enqueues a
    transiently-failed batch at the front of that type's deque, so writes reappear after
    flush_queue already judged it empty. Those batches then MERGE fresh stubs while the
    sweep runs.
    """
    order: list[str] = []

    async def flush_all() -> bool:
        order.append("flush_all")
        return True

    async def cleanup() -> bool:
        order.append("cleanup")
        return True

    async def stats() -> bool:
        order.append("stats")
        return True

    mock_batch = MagicMock()
    mock_batch.flush_all = flush_all

    with (
        patch.object(g, "graph", AsyncMock()),
        patch.object(g, "batch_processor", mock_batch),
        patch.object(g, "cleanup_all_stub_nodes", cleanup),
        patch.object(g, "compute_genre_style_stats", stats),
        patch.object(g, "POST_IMPORT_MAINTENANCE_RETRY_DELAY_SECONDS", 0.0),
    ):
        ok = await g.run_post_import_maintenance()

    assert ok is True
    assert order == ["flush_all", "cleanup", "stats"]


@pytest.mark.asyncio
async def test_maintenance_skips_sweeps_when_queues_do_not_drain() -> None:
    """A queue that will not drain means writers are still creating stubs. Sweeping
    anyway is what strands orphan stubs; defer to the retry instead."""
    swept = {"n": 0}

    async def cleanup() -> bool:
        swept["n"] += 1
        return True

    mock_batch = MagicMock()
    mock_batch.flush_all = AsyncMock(return_value=False)

    with (
        patch.object(g, "graph", AsyncMock()),
        patch.object(g, "batch_processor", mock_batch),
        patch.object(g, "cleanup_all_stub_nodes", cleanup),
        patch.object(g, "compute_genre_style_stats", AsyncMock(return_value=True)),
        patch.object(g, "POST_IMPORT_MAINTENANCE_RETRY_DELAY_SECONDS", 0.0),
    ):
        ok = await g.run_post_import_maintenance()

    assert ok is False
    assert swept["n"] == 0, "stub cleanup must not run over queues that are still writing"
    assert mock_batch.flush_all.await_count == g.POST_IMPORT_MAINTENANCE_MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_maintenance_retries_then_gives_up_loudly() -> None:
    """The task owns the retry that nack(requeue=True) used to provide."""
    attempts = {"n": 0}

    async def failing_cleanup() -> bool:
        attempts["n"] += 1
        return False

    with (
        patch.object(g, "graph", AsyncMock()),
        patch.object(g, "cleanup_all_stub_nodes", failing_cleanup),
        patch.object(g, "compute_genre_style_stats", AsyncMock(return_value=True)),
        patch.object(g, "POST_IMPORT_MAINTENANCE_RETRY_DELAY_SECONDS", 0.0),
    ):
        ok = await g.run_post_import_maintenance()

    assert ok is False
    assert attempts["n"] == g.POST_IMPORT_MAINTENANCE_MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_maintenance_succeeds_on_a_later_attempt() -> None:
    """A transient failure must not poison the whole post-import pass."""
    attempts = {"n": 0}

    async def flaky_cleanup() -> bool:
        attempts["n"] += 1
        return attempts["n"] > 1

    with (
        patch.object(g, "graph", AsyncMock()),
        patch.object(g, "cleanup_all_stub_nodes", flaky_cleanup),
        patch.object(g, "compute_genre_style_stats", AsyncMock(return_value=True)),
        patch.object(g, "POST_IMPORT_MAINTENANCE_RETRY_DELAY_SECONDS", 0.0),
    ):
        ok = await g.run_post_import_maintenance()

    assert ok is True
    assert attempts["n"] == 2


@pytest.mark.asyncio
async def test_maintenance_survives_an_exception_and_retries() -> None:
    """A detached task must not die silently on an unexpected error."""
    attempts = {"n": 0}

    async def exploding_cleanup() -> bool:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("neo4j went away")
        return True

    with (
        patch.object(g, "graph", AsyncMock()),
        patch.object(g, "cleanup_all_stub_nodes", exploding_cleanup),
        patch.object(g, "compute_genre_style_stats", AsyncMock(return_value=True)),
        patch.object(g, "POST_IMPORT_MAINTENANCE_RETRY_DELAY_SECONDS", 0.0),
    ):
        ok = await g.run_post_import_maintenance()

    assert ok is True
    assert attempts["n"] == 2


@pytest.mark.asyncio
async def test_maintenance_stops_retrying_on_shutdown() -> None:
    """Shutdown must not be blocked by a retry backoff."""
    attempts = {"n": 0}

    async def failing_cleanup() -> bool:
        attempts["n"] += 1
        return False

    with (
        patch.object(g, "graph", AsyncMock()),
        patch.object(g, "shutdown_requested", True),
        patch.object(g, "cleanup_all_stub_nodes", failing_cleanup),
        patch.object(g, "compute_genre_style_stats", AsyncMock(return_value=True)),
        patch.object(g, "POST_IMPORT_MAINTENANCE_RETRY_DELAY_SECONDS", 0.0),
    ):
        ok = await g.run_post_import_maintenance()

    assert ok is False
    assert attempts["n"] == 0


@pytest.mark.asyncio
async def test_task_reference_is_held_until_completion() -> None:
    """The loop must not be able to GC a detached maintenance task mid-flight."""
    release = asyncio.Event()

    async def blocking_cleanup() -> bool:
        await release.wait()
        return True

    message = AsyncMock(spec=AbstractIncomingMessage)
    _final_signal_pending()
    with (
        patch.object(g, "graph", AsyncMock()),
        patch.object(g, "cleanup_all_stub_nodes", blocking_cleanup),
        patch.object(g, "compute_genre_style_stats", AsyncMock(return_value=True)),
    ):
        await g.check_file_completion(EXTRACTION_COMPLETE, "releases", message)
        await asyncio.sleep(0)
        assert g.post_import_maintenance_task in g.maintenance_tasks

        release.set()
        await g.post_import_maintenance_task
        await asyncio.sleep(0)

    assert g.post_import_maintenance_task not in g.maintenance_tasks


@pytest.mark.asyncio
async def test_non_final_signal_still_acks_without_maintenance() -> None:
    """Unchanged behavior: an early signal acks and defers all maintenance."""
    g.extraction_complete_signals = set()
    message = AsyncMock(spec=AbstractIncomingMessage)

    with patch.object(g, "graph", AsyncMock()):
        handled = await g.check_file_completion(EXTRACTION_COMPLETE, "artists", message)

    assert handled is True
    message.ack.assert_awaited_once()
    message.nack.assert_not_called()
    assert g.post_import_maintenance_task is None
