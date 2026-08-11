"""Regression tests for discogsography-lnn4.

All four consumers opened their message handler with the same guard::

    if shutdown_requested:
        await message.nack(requeue=True)
        return

The signal handler only sets the flag — consumers stayed subscribed and the
connection stayed open through progress-task cancellation, queue-checker
cancellation, and a multi-second ``flush_all()`` before teardown. Every nacked
message was therefore redelivered within milliseconds to the same handler, which
nacked it again. Each redelivery increments a quorum queue's ``x-delivery-count``,
and every main queue is declared with ``x-delivery-limit: 20`` plus a DLX, so a
routine ``docker restart`` mid-ingestion silently diverted thousands of valid
records to the DLQ, where nothing replays them.

The fix has two halves, both pinned here across every service:
  1. the shutdown guard leaves the delivery UNSETTLED (connection close requeues
     it exactly once) instead of nacking it into a redelivery loop; and
  2. shutdown cancels the consumers first, so the broker stops handing messages
     to a service that is on its way out.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

import pytest


if TYPE_CHECKING:
    from types import ModuleType


CONSUMER_MODULES = [
    "graphinator.graphinator",
    "tableinator.tableinator",
    "brainzgraphinator.brainzgraphinator",
    "brainztableinator.brainztableinator",
]


def _module(name: str) -> ModuleType:
    return importlib.import_module(name)


async def _dispatch(module: ModuleType, message: Any) -> None:
    """Deliver a message through whichever entry point the service exposes."""
    if hasattr(module, "on_data_message"):
        await module.on_data_message(message, "artists")
    else:  # graphinator-style per-type handler pre-built by make_message_handler
        await module.on_artist_message(message)


@pytest.mark.asyncio
@pytest.mark.parametrize("module_name", CONSUMER_MODULES)
async def test_shutdown_guard_never_nacks(module_name: str) -> None:
    """The guard must not settle the delivery at all.

    A nack here is what burns the quorum delivery-count budget; an ack would be
    worse still (silent loss of an unprocessed record).
    """
    module = _module(module_name)
    message = AsyncMock()
    message.body = b'{"id": "1", "name": "Test"}'
    message.routing_key = "artists"

    with patch.object(module, "shutdown_requested", True), patch.object(module, "logger"):
        await _dispatch(module, message)

    message.nack.assert_not_called()
    message.ack.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("module_name", CONSUMER_MODULES)
async def test_repeated_shutdown_deliveries_settle_nothing(module_name: str) -> None:
    """Even 25 redeliveries (past x-delivery-limit=20) must settle nothing.

    This is the exact loop that dead-lettered valid records: with the old guard
    this test would record 25 nacks, five of them past the limit.
    """
    module = _module(module_name)
    messages = []

    with patch.object(module, "shutdown_requested", True), patch.object(module, "logger"):
        for _ in range(25):
            message = AsyncMock()
            message.body = b'{"id": "1", "name": "Test"}'
            message.routing_key = "artists"
            await _dispatch(module, message)
            messages.append(message)

    assert not any(m.nack.called for m in messages)
    assert not any(m.ack.called for m in messages)


@pytest.mark.asyncio
@pytest.mark.parametrize("module_name", CONSUMER_MODULES)
async def test_shutdown_cancels_every_consumer(module_name: str) -> None:
    """Shutdown must deregister consumers so the broker stops delivering."""
    module = _module(module_name)

    queue = AsyncMock()
    tags = {"artists": "tag-artists", "labels": "tag-labels"}

    with (
        patch.object(module, "consumer_tags", dict(tags)),
        patch.object(module, "queues", dict.fromkeys(tags, queue)),
        patch.object(module, "logger"),
    ):
        await module.cancel_all_consumers()

        cancelled = {call.args[0] for call in queue.cancel.call_args_list}
        assert cancelled == set(tags.values())
        # nowait keeps teardown from hanging on a broker round trip.
        assert all(call.kwargs.get("nowait") is True for call in queue.cancel.call_args_list)
        assert module.consumer_tags == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("module_name", CONSUMER_MODULES)
async def test_consumer_cancellation_failure_does_not_block_shutdown(module_name: str) -> None:
    """A broker error while cancelling must not abort the rest of teardown."""
    module = _module(module_name)

    queue = AsyncMock()
    queue.cancel = AsyncMock(side_effect=RuntimeError("channel already closed"))

    with (
        patch.object(module, "consumer_tags", {"artists": "tag-artists"}),
        patch.object(module, "queues", {"artists": queue}),
        patch.object(module, "logger"),
    ):
        await module.cancel_all_consumers()  # must not raise


@pytest.mark.asyncio
@pytest.mark.parametrize("module_name", CONSUMER_MODULES)
async def test_cancellation_tolerates_missing_queue_handle(module_name: str) -> None:
    """A tag with no queue object (mid-reconnect) is dropped, not crashed on."""
    module = _module(module_name)

    with (
        patch.object(module, "consumer_tags", {"artists": "tag-artists"}),
        patch.object(module, "queues", {}),
        patch.object(module, "logger"),
    ):
        await module.cancel_all_consumers()

        assert module.consumer_tags == {}
