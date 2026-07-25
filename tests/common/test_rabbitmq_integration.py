"""Integration tests for AsyncResilientRabbitMQ against a LIVE RabbitMQ broker.

These cover the two things unit tests fundamentally cannot: that the heartbeat we
put in the AMQP URL is actually *negotiated* with the broker, and that a dropped
connection is recovered by aio-pika's RobustConnection with our reconnect
callbacks firing.

Both matter specifically because of the aio-pika 10 migration: 10.x removed
``**kwargs`` from ``connect_robust()``, so tuning parameters moved into the URL
query string. A parameter that silently fails to parse looks identical to success
from the client side — the heartbeat would quietly fall back to aiormq's default
of 60s instead of the configured value.

Requires a broker; skipped unless RABBITMQ_HOST is set (CI supplies it via a
service container). Marked `integration` so `just test` does not pick them up.
"""

import asyncio
from collections.abc import Callable
import os
from urllib.parse import quote

import httpx
import pytest

from common.rabbitmq_resilient import AsyncResilientRabbitMQ


pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

RABBITMQ_HOST = os.environ.get("RABBITMQ_HOST", "")
RABBITMQ_USER = os.environ.get("RABBITMQ_USERNAME", "discogsography")
RABBITMQ_PASS = os.environ.get("RABBITMQ_PASSWORD", "discogsography")
AMQP_PORT = int(os.environ.get("RABBITMQ_AMQP_PORT", "5672"))
MGMT_PORT = int(os.environ.get("RABBITMQ_MGMT_PORT", "15672"))

# A deliberately distinctive value: it must match neither aiormq's default (60)
# nor the production default (600), so a fallback cannot masquerade as success.
TEST_HEARTBEAT = 37

pytestmark.append(pytest.mark.skipif(not RABBITMQ_HOST, reason="RABBITMQ_HOST not set; no live broker available"))


def _amqp_url() -> str:
    return f"amqp://{RABBITMQ_USER}:{RABBITMQ_PASS}@{RABBITMQ_HOST}:{AMQP_PORT}/"


def _mgmt() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"http://{RABBITMQ_HOST}:{MGMT_PORT}",
        auth=(RABBITMQ_USER, RABBITMQ_PASS),
        timeout=15.0,
    )


async def _connections(client: httpx.AsyncClient) -> list[dict]:
    resp = await client.get("/api/connections")
    resp.raise_for_status()
    return list(resp.json())


async def _await_condition(predicate: Callable[[], bool], timeout: float, interval: float = 0.5) -> bool:
    """Poll until predicate() is truthy or timeout elapses."""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return False


class TestLiveHeartbeatNegotiation:
    """The configured heartbeat must survive all the way into the AMQP handshake."""

    async def test_broker_reports_negotiated_heartbeat(self) -> None:
        manager = AsyncResilientRabbitMQ(connection_url=_amqp_url(), heartbeat=TEST_HEARTBEAT)
        connection = await manager.connect()

        try:
            async with _mgmt() as client:
                # The broker's own view of the negotiated heartbeat is authoritative.
                conns = await _connections(client)
                assert conns, "broker reports no client connections"
                timeouts = {c.get("timeout") for c in conns}
                assert TEST_HEARTBEAT in timeouts, (
                    f"broker negotiated {timeouts}, expected {TEST_HEARTBEAT} (60 would mean the URL param was dropped)"
                )
        finally:
            await connection.close()


class TestLiveReconnect:
    """A dropped connection must be recovered, and our callbacks must fire."""

    async def test_reconnects_and_fires_callbacks_after_broker_drops_connection(self) -> None:
        manager = AsyncResilientRabbitMQ(
            connection_url=_amqp_url(),
            heartbeat=TEST_HEARTBEAT,
            retry_delay=1.0,  # -> reconnect_interval, keeps the test quick
        )
        reconnected = asyncio.Event()
        manager.add_reconnect_callback(lambda: reconnected.set())

        connection = await manager.connect()

        # Prove the connection works before we break it. The queue must be
        # exclusive: RabbitMQ 4 refuses transient non-exclusive queues
        # (`transient_nonexcl_queues` is deprecated and not permitted by default),
        # so a plain auto_delete queue kills the whole connection with
        # internal_error. Exclusive queues are still allowed and vanish with the
        # connection, so they need no cleanup.
        channel = await connection.channel()
        await channel.declare_queue("aio-pika-10-reconnect-probe", exclusive=True)

        async with _mgmt() as client:
            before = await _connections(client)
            assert before, "broker reports no client connections"
            # Force the broker to drop every client connection. Connection names
            # contain characters that must be percent-encoded in the path.
            for conn_info in before:
                resp = await client.delete(f"/api/connections/{quote(conn_info['name'], safe='')}")
                if resp.status_code not in (204, 404):
                    resp.raise_for_status()

        # RobustConnection should re-establish on its own within reconnect_interval.
        assert await _await_condition(lambda: reconnected.is_set(), timeout=60.0), (
            "reconnect callback never fired after the broker closed the connection"
        )

        # And the recovered connection must be usable again.
        assert await _await_condition(lambda: not connection.is_closed, timeout=30.0), "connection still closed after reconnect"

        channel = await connection.channel()
        await channel.declare_queue("aio-pika-10-reconnect-probe-after", exclusive=True)

        await connection.close()
