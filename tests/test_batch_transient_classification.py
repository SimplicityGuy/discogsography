"""Regression tests for discogsography-4lrp.

Both batch processors classified a flush failure by exception type: a short
transient tuple (``ServiceUnavailable``/``SessionExpired``, ``InterfaceError``/
``OperationalError``) meant "retry with backoff", and everything else meant
"deterministic poison" — which, after ``max_poison_retries`` consecutive hits,
nacks the WHOLE batch with ``requeue=False`` straight to the DLQ.

But the resilient wrappers never raise those types when the database is down.
``AsyncResilientNeo4jDriver`` / ``AsyncPostgreSQLPool`` raised a bare
``Exception("Failed to establish connection after N attempts")`` or
``Exception("Circuit breaker is OPEN")``, both of which landed in the poison
branch. A few minutes of Neo4j or Postgres downtime therefore dead-lettered
whole batches of perfectly valid Discogs records, repeating batch after batch
until the database returned.

Two changes are pinned here for both processors:
  1. the resilience layer raises typed ``DatabaseUnavailableError`` subclasses,
     which both processors classify as transient; and
  2. transient failures and deterministic poison failures use SEPARATE counters,
     so an outage can never pre-charge the poison guard.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from common.db_resilience import (
    CircuitOpenError,
    ConnectionEstablishmentError,
    DatabaseUnavailableError,
)


OUTAGE_ERRORS = [
    ConnectionEstablishmentError("AsyncNeo4j: Failed to establish connection after 5 attempts"),
    CircuitOpenError("AsyncNeo4j: Circuit breaker is OPEN"),
]


def _graphinator_processor(error: BaseException) -> tuple[Any, Any]:
    """Build a graphinator processor whose session raises ``error``."""
    from graphinator.batch_processor import Neo4jBatchProcessor, PendingMessage

    driver = MagicMock()
    driver.session = MagicMock(side_effect=error)

    processor = Neo4jBatchProcessor(driver)
    message = PendingMessage("artists", {"id": "1", "name": "Artist 1", "sha256": "h1"}, AsyncMock(), AsyncMock())
    processor.queues["artists"].append(message)
    return processor, message


def _tableinator_processor(error: BaseException) -> tuple[Any, Any]:
    """Build a tableinator processor whose pool raises ``error``."""
    from tableinator.batch_processor import PendingMessage, PostgreSQLBatchProcessor

    pool = MagicMock()
    pool.connection = MagicMock(side_effect=error)

    processor = PostgreSQLBatchProcessor(pool)
    message = PendingMessage(
        data_type="artists",
        data_id="1",
        data={"id": "1"},
        sha256="h1",
        ack_callback=AsyncMock(),
        nack_callback=AsyncMock(),
    )
    processor.queues["artists"].append(message)
    return processor, message


BUILDERS = {
    "graphinator": (_graphinator_processor, "graphinator.batch_processor.logger"),
    "tableinator": (_tableinator_processor, "tableinator.batch_processor.logger"),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("service", sorted(BUILDERS))
@pytest.mark.parametrize("error", OUTAGE_ERRORS, ids=lambda e: type(e).__name__)
async def test_outage_is_transient_not_poison(service: str, error: BaseException) -> None:
    """A resilience-layer outage must re-enqueue, not charge the poison counter."""
    build, logger_path = BUILDERS[service]
    processor, message = build(error)

    with patch(logger_path):
        await processor._flush_queue("artists")

    assert len(processor.queues["artists"]) == 1, "the message must be re-enqueued for retry"
    message.nack_callback.assert_not_called()
    message.ack_callback.assert_not_called()
    assert processor._transient_failures["artists"] == 1
    assert processor._consecutive_failures["artists"] == 0, "an outage must never charge the poison guard"


@pytest.mark.asyncio
@pytest.mark.parametrize("service", sorted(BUILDERS))
async def test_sustained_db_outage_never_dead_letters(service: str) -> None:
    """The exact production scenario: minutes of downtime, no DLQ traffic.

    With the old classification, flush #5 nacked every message with
    requeue=False; here all ten flushes must leave the batch intact.
    """
    build, logger_path = BUILDERS[service]
    processor, message = build(ConnectionEstablishmentError("db down"))

    with patch(logger_path):
        for _ in range(10):
            processor._backoff_until["artists"] = 0.0  # skip the backoff wait
            await processor._flush_queue("artists")

    message.nack_callback.assert_not_called()
    assert len(processor.queues["artists"]) == 1
    assert processor._consecutive_failures["artists"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("service", sorted(BUILDERS))
async def test_transient_failures_do_not_precharge_the_poison_guard(service: str) -> None:
    """Transient hits must not shorten the runway for a later deterministic error.

    Four outage failures followed by one genuine poison error used to trip the
    guard on that error's FIRST occurrence and DLQ the whole batch.
    """
    build, logger_path = BUILDERS[service]
    processor, message = build(ConnectionEstablishmentError("db down"))

    with patch(logger_path):
        for _ in range(4):
            processor._backoff_until["artists"] = 0.0
            await processor._flush_queue("artists")

        assert processor._transient_failures["artists"] == 4

        # Now a genuinely deterministic error arrives.
        with patch.object(
            processor, "_process_artists_batch" if service == "graphinator" else "_process_batch", side_effect=ValueError("bad record")
        ):
            processor._backoff_until["artists"] = 0.0
            await processor._flush_queue("artists")

    # The first deterministic failure must not dead-letter the batch.
    message.nack_callback.assert_not_called()
    assert processor._consecutive_failures["artists"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("service", sorted(BUILDERS))
async def test_genuine_poison_still_reaches_the_dlq(service: str) -> None:
    """The poison guard must keep working — this is not a blanket "never nack"."""
    build, logger_path = BUILDERS[service]
    processor, message = build(ConnectionEstablishmentError("unused"))
    target = "_process_artists_batch" if service == "graphinator" else "_process_batch"

    with patch(logger_path), patch.object(processor, target, side_effect=ValueError("bad record")):
        for _ in range(processor.config.max_poison_retries):
            processor._backoff_until["artists"] = 0.0
            await processor._flush_queue("artists")

    message.nack_callback.assert_awaited_once()
    assert len(processor.queues["artists"]) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("service", sorted(BUILDERS))
async def test_success_resets_both_counters(service: str) -> None:
    """Recovery must clear transient and poison state alike."""
    build, logger_path = BUILDERS[service]
    processor, _ = build(ConnectionEstablishmentError("db down"))
    target = "_process_artists_batch" if service == "graphinator" else "_process_batch"

    with patch(logger_path):
        await processor._flush_queue("artists")
        assert processor._transient_failures["artists"] == 1

        processor._consecutive_failures["artists"] = 2
        processor._backoff_until["artists"] = 0.0
        with patch.object(processor, target, AsyncMock(return_value=set())):
            await processor._flush_queue("artists")

    assert processor._transient_failures["artists"] == 0
    assert processor._consecutive_failures["artists"] == 0


def test_resilience_layer_raises_typed_errors() -> None:
    """The typed hierarchy is what makes classification possible at all."""
    assert issubclass(ConnectionEstablishmentError, DatabaseUnavailableError)
    assert issubclass(CircuitOpenError, DatabaseUnavailableError)
    assert issubclass(DatabaseUnavailableError, Exception)


def test_circuit_breakers_count_connection_failures() -> None:
    """A breaker that ignores connection failures never opens during an outage.

    ``expected_exception`` excluded the connection layer's own error, so the
    breaker was dead weight during exactly the outage it exists for.
    """
    from common import neo4j_resilient, postgres_resilient

    for module in (neo4j_resilient, postgres_resilient):
        source = module.__file__
        assert source is not None
        text = Path(source).read_text(encoding="utf-8")
        for line in text.splitlines():
            if "expected_exception=(" in line:
                assert "DatabaseUnavailableError" in line, f"{module.__name__}: breaker must count connection-layer failures: {line.strip()}"
