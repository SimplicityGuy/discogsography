"""Regression tests for discogsography-hh7r.

``flush_queue`` returned None on every path and never raised, so its callers —
``check_file_completion`` / ``on_data_message`` — could not tell a clean drain
from a give-up. Worse, the give-up path popped every pending message and invoked
``nack_callback``, which both services wire as ``message.nack(requeue=False)``:
an immediate dead-letter that bypasses the quorum queue's ``x-delivery-limit``
budget entirely. So ~30 seconds of database downtime around a ``file_complete``
marker sent the whole pending tail to a DLQ nothing replays — and the caller then
marked the file complete, acked the marker, and cancelled the consumer, while
graphinator ran post-import maintenance over an incomplete graph and tableinator
purged the very rows those messages would have refreshed.

The contract is now:
  * ``flush_queue`` / ``flush_all`` return whether the queue actually drained;
  * the give-up path keeps messages queued for ``periodic_flush`` and never nacks
    (genuinely poison batches are still dead-lettered by ``_flush_queue``); and
  * callers requeue the control message instead of declaring the file complete.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from aio_pika.abc import AbstractIncomingMessage
import pytest


FILE_COMPLETE = {"type": "file_complete", "total_processed": 42}
EXTRACTION_COMPLETE = {"type": "extraction_complete", "version": "20260101"}


def _graphinator_processor(config_kwargs: dict[str, Any] | None = None) -> Any:
    from graphinator.batch_processor import BatchConfig, Neo4jBatchProcessor, PendingMessage

    processor = Neo4jBatchProcessor(MagicMock(), BatchConfig(max_flush_retries=2, backoff_initial=0.0, **(config_kwargs or {})))
    processor.queues["artists"].append(PendingMessage("artists", {"id": "1"}, AsyncMock(), AsyncMock()))
    return processor


def _tableinator_processor(config_kwargs: dict[str, Any] | None = None) -> Any:
    from tableinator.batch_processor import BatchConfig, PendingMessage, PostgreSQLBatchProcessor

    processor = PostgreSQLBatchProcessor(MagicMock(), BatchConfig(max_flush_retries=2, backoff_initial=0.0, **(config_kwargs or {})))
    processor.queues["artists"].append(
        PendingMessage(
            data_type="artists",
            data_id="1",
            data={"id": "1"},
            sha256="h1",
            ack_callback=AsyncMock(),
            nack_callback=AsyncMock(),
        )
    )
    return processor


PROCESSORS = {
    "graphinator": (_graphinator_processor, "graphinator.batch_processor.logger"),
    "tableinator": (_tableinator_processor, "tableinator.batch_processor.logger"),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("service", sorted(PROCESSORS))
async def test_stalled_drain_reports_failure_without_nacking(service: str) -> None:
    """The give-up path must report False and leave every message queued."""
    build, logger_path = PROCESSORS[service]
    processor = build()
    pending = processor.queues["artists"][0]
    processor._flush_queue = AsyncMock()  # no progress, ever

    with patch(logger_path):
        drained = await processor.flush_queue("artists")

    assert drained is False
    assert len(processor.queues["artists"]) == 1
    pending.nack_callback.assert_not_called()
    pending.ack_callback.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("service", sorted(PROCESSORS))
async def test_successful_drain_reports_success(service: str) -> None:
    """A queue that empties reports True."""
    build, _ = PROCESSORS[service]
    processor = build()

    async def drain_one(data_type: str) -> None:
        if processor.queues[data_type]:
            processor.queues[data_type].popleft()

    processor._flush_queue = AsyncMock(side_effect=drain_one)

    assert await processor.flush_queue("artists") is True


@pytest.mark.asyncio
@pytest.mark.parametrize("service", sorted(PROCESSORS))
async def test_flush_all_reports_any_stalled_queue_failure(service: str) -> None:
    """flush_all must not report success when one queue is stuck."""
    build, logger_path = PROCESSORS[service]
    processor = build()
    processor._flush_queue = AsyncMock()

    with patch(logger_path):
        assert await processor.flush_all() is False


@pytest.mark.asyncio
async def test_graphinator_file_complete_requeues_on_incomplete_drain() -> None:
    """A stalled drain must not mark the file complete or cancel the consumer."""
    import graphinator.graphinator as g

    processor = MagicMock()
    processor.flush_queue = AsyncMock(return_value=False)
    message = AsyncMock(spec=AbstractIncomingMessage)

    with patch.object(g, "batch_processor", processor), patch.object(g, "completed_files", set()) as completed:
        handled = await g.check_file_completion(FILE_COMPLETE, "artists", message)

    assert handled is True
    message.nack.assert_awaited_once_with(requeue=True)
    message.ack.assert_not_called()
    assert "artists" not in completed


@pytest.mark.asyncio
async def test_graphinator_file_complete_acks_on_clean_drain() -> None:
    """The happy path is unchanged."""
    import graphinator.graphinator as g

    processor = MagicMock()
    processor.flush_queue = AsyncMock(return_value=True)
    message = AsyncMock(spec=AbstractIncomingMessage)

    with (
        patch.object(g, "batch_processor", processor),
        patch.object(g, "completed_files", set()) as completed,
        patch.object(g, "CONSUMER_CANCEL_DELAY", 0),
    ):
        handled = await g.check_file_completion(FILE_COMPLETE, "artists", message)

    assert handled is True
    message.ack.assert_awaited_once()
    message.nack.assert_not_called()
    assert "artists" in completed


@pytest.mark.asyncio
async def test_graphinator_extraction_complete_requeues_on_incomplete_drain() -> None:
    """A stalled drain must not record the completion signal.

    Recording it would let stub cleanup and aggregate stats run over a graph that
    is still missing rows.
    """
    import graphinator.graphinator as g

    processor = MagicMock()
    processor.flush_queue = AsyncMock(return_value=False)
    message = AsyncMock(spec=AbstractIncomingMessage)

    with patch.object(g, "batch_processor", processor), patch.object(g, "extraction_complete_signals", set()) as signals:
        handled = await g.check_file_completion(EXTRACTION_COMPLETE, "artists", message)

    assert handled is True
    message.nack.assert_awaited_once_with(requeue=True)
    message.ack.assert_not_called()
    assert signals == set()


@pytest.mark.asyncio
async def test_tableinator_file_complete_requeues_on_incomplete_drain() -> None:
    """Mirror of the graphinator file_complete guard."""
    import tableinator.tableinator as t

    processor = MagicMock()
    processor.flush_queue = AsyncMock(return_value=False)
    message = AsyncMock(spec=AbstractIncomingMessage)
    message.body = b'{"type": "file_complete", "total_processed": 42}'

    with (
        patch.object(t, "shutdown_requested", False),
        patch.object(t, "batch_processor", processor),
        patch.object(t, "completed_files", set()) as completed,
    ):
        await t.on_data_message(message, "artists")

    message.nack.assert_awaited_once_with(requeue=True)
    message.ack.assert_not_called()
    assert "artists" not in completed


@pytest.mark.asyncio
async def test_tableinator_extraction_complete_does_not_purge_after_incomplete_drain() -> None:
    """The purge is destructive on top of a stalled drain.

    purge_stale_rows deletes rows whose updated_at predates this run — exactly the
    rows the still-pending messages were about to refresh.
    """
    import tableinator.tableinator as t

    processor = MagicMock()
    processor.flush_queue = AsyncMock(return_value=False)
    message = AsyncMock(spec=AbstractIncomingMessage)
    message.body = b'{"type": "extraction_complete", "version": "20260101"}'
    purge = AsyncMock()

    with (
        patch.object(t, "shutdown_requested", False),
        patch.object(t, "batch_processor", processor),
        patch.object(t, "connection_pool", MagicMock()),
        patch.object(t, "purge_stale_rows", purge),
    ):
        await t.on_data_message(message, "artists")

    purge.assert_not_called()
    message.nack.assert_awaited_once_with(requeue=True)
    message.ack.assert_not_called()
