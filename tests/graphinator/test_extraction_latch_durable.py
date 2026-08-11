"""Regression tests for discogsography-tk7v.

The extraction_complete latch used to be a process-local set. Each signal was
acked — destroying the only durable copy, the queued message — while the set was
never persisted. A restart between the first and the last signal therefore lost
every recorded signal: the final signal found 1-of-4, logged "Deferring stub
cleanup until all data types complete", acked, and waited forever. No further
extraction_complete is ever published for a version, so stub cleanup and the
genre/style/label aggregates silently never ran.

The latch is now a Neo4j :ExtractionCompletion node keyed by extraction version,
written BEFORE the signal is acked and reloaded on the next signal. Keying by
version also stops a long-lived process from carrying a finished run's signals
into the next dump and firing maintenance while other queues still import.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

from aio_pika.abc import AbstractIncomingMessage
import pytest

import graphinator.graphinator as g


# Captured before the suite-wide in_memory_extraction_latch fixture replaces them.
_REAL_LOAD = g._load_extraction_signals
_REAL_PERSIST = g._persist_extraction_signals


def _signal(version: str = "20260101") -> dict[str, Any]:
    return {"type": "extraction_complete", "version": version}


class FakeLatchStore:
    """In-memory stand-in for the Neo4j :ExtractionCompletion node."""

    def __init__(self, initial: dict[str, set[str]] | None = None) -> None:
        self.rows: dict[str, set[str]] = initial or {}
        self.writes: list[tuple[str, set[str]]] = []

    async def load(self, version: str) -> set[str]:
        return set(self.rows.get(version, set()))

    async def persist(self, version: str, signals: set[str]) -> None:
        self.rows[version] = set(signals)
        self.writes.append((version, set(signals)))


@pytest.fixture
def latch(monkeypatch: pytest.MonkeyPatch) -> FakeLatchStore:
    """Replace the Neo4j-backed latch helpers with a durable in-test store."""
    store = FakeLatchStore()
    monkeypatch.setattr(g, "_load_extraction_signals", store.load)
    monkeypatch.setattr(g, "_persist_extraction_signals", store.persist)
    monkeypatch.setattr(g, "extraction_complete_signals", set())
    monkeypatch.setattr(g, "extraction_complete_version", None)
    return store


@pytest.mark.asyncio
async def test_signal_persisted_before_ack(latch: FakeLatchStore) -> None:
    """The latch write happens before the delivery is destroyed by the ack."""
    message = AsyncMock(spec=AbstractIncomingMessage)

    handled = await g.check_file_completion(_signal(), "artists", message)

    assert handled is True
    assert latch.rows["20260101"] == {"artists"}
    message.ack.assert_awaited_once()
    message.nack.assert_not_called()


@pytest.mark.asyncio
async def test_restart_recovers_acked_signals(latch: FakeLatchStore) -> None:  # noqa: ARG001  # fixture installs the durable store
    """Signals acked before a restart still count toward the all-four check.

    artists/labels/masters signal hours before releases finishes draining; a
    deploy in that window used to erase them.
    """
    for data_type in ("artists", "labels", "masters"):
        await g.check_file_completion(_signal(), data_type, AsyncMock(spec=AbstractIncomingMessage))

    # Simulate a container restart: process-local state is gone, Neo4j is not.
    g.extraction_complete_signals = set()
    g.extraction_complete_version = None

    with patch.object(g, "start_post_import_maintenance") as start:
        await g.check_file_completion(_signal(), "releases", AsyncMock(spec=AbstractIncomingMessage))

    assert g.extraction_complete_signals == {"artists", "labels", "masters", "releases"}
    start.assert_called_once()


@pytest.mark.asyncio
async def test_partial_signals_still_defer(latch: FakeLatchStore) -> None:  # noqa: ARG001  # fixture installs the durable store
    """Recovering the latch must not fire maintenance early."""
    await g.check_file_completion(_signal(), "artists", AsyncMock(spec=AbstractIncomingMessage))

    g.extraction_complete_signals = set()
    g.extraction_complete_version = None

    with patch.object(g, "start_post_import_maintenance") as start:
        await g.check_file_completion(_signal(), "labels", AsyncMock(spec=AbstractIncomingMessage))

    start.assert_not_called()


@pytest.mark.asyncio
async def test_new_version_resets_the_latch(latch: FakeLatchStore) -> None:
    """A completed run's signals must not satisfy the NEXT dump's check.

    The latch was never cleared, so a process that survived into the next
    monthly dump fired cleanup on the first signal it saw — DETACH DELETE-ing
    stubs while the release queue was still hours from done.
    """
    for data_type in ("artists", "labels", "masters", "releases"):
        with patch.object(g, "start_post_import_maintenance"):
            await g.check_file_completion(_signal("20260101"), data_type, AsyncMock(spec=AbstractIncomingMessage))

    assert g.extraction_complete_signals == set(g.DATA_TYPES)

    with patch.object(g, "start_post_import_maintenance") as start:
        await g.check_file_completion(_signal("20260201"), "artists", AsyncMock(spec=AbstractIncomingMessage))

    start.assert_not_called()
    assert g.extraction_complete_signals == {"artists"}
    assert latch.rows["20260201"] == {"artists"}
    assert latch.rows["20260101"] == set(g.DATA_TYPES)


@pytest.mark.asyncio
async def test_latch_write_failure_requeues(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the latch cannot be written, the signal must be requeued, not acked.

    Acking an unpersisted signal loses it exactly as before.
    """

    async def _boom(_version: str, _signals: set[str]) -> None:
        raise RuntimeError("Neo4j unavailable")

    monkeypatch.setattr(g, "_load_extraction_signals", AsyncMock(return_value=set()))
    monkeypatch.setattr(g, "_persist_extraction_signals", _boom)
    monkeypatch.setattr(g, "extraction_complete_signals", set())
    monkeypatch.setattr(g, "extraction_complete_version", None)

    message = AsyncMock(spec=AbstractIncomingMessage)
    handled = await g.check_file_completion(_signal(), "artists", message)

    assert handled is True
    message.nack.assert_awaited_once_with(requeue=True)
    message.ack.assert_not_called()
    assert g.extraction_complete_signals == set()


@pytest.mark.asyncio
async def test_load_reads_the_version_row(monkeypatch: pytest.MonkeyPatch) -> None:
    """_load_extraction_signals queries the node for exactly this version."""
    record = {"signals": ["artists", "labels"]}
    result = AsyncMock()
    result.single = AsyncMock(return_value=record)
    session = AsyncMock()
    session.run = AsyncMock(return_value=result)
    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=None)
    driver = AsyncMock()
    driver.session = lambda **_kwargs: session_cm

    monkeypatch.setattr(g, "graph", driver)
    signals = await _REAL_LOAD("20260101")

    assert signals == {"artists", "labels"}
    assert session.run.await_args.kwargs["version"] == "20260101"


@pytest.mark.asyncio
async def test_persist_writes_the_version_row(monkeypatch: pytest.MonkeyPatch) -> None:
    """_persist_extraction_signals MERGEs the node for this version."""
    session = AsyncMock()
    session.run = AsyncMock()
    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=None)
    driver = AsyncMock()
    driver.session = lambda **_kwargs: session_cm

    monkeypatch.setattr(g, "graph", driver)
    await _REAL_PERSIST("20260101", {"labels", "artists"})

    cypher = session.run.await_args.args[0]
    assert "MERGE (m:ExtractionCompletion {version: $version})" in cypher
    assert session.run.await_args.kwargs["signals"] == ["artists", "labels"]
