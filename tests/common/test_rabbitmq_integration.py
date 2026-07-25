"""Integration tests for AsyncResilientRabbitMQ against a LIVE RabbitMQ broker.

These cover the one thing unit tests fundamentally cannot: that the heartbeat we
put in the AMQP URL is actually *negotiated* with the broker, rather than
silently falling back to aiormq's default of 60s. That matters specifically
because of the aio-pika 10 migration — 10.x removed ``**kwargs`` from
``connect_robust()``, so tuning parameters moved into the URL query string, and a
parameter that fails to parse looks identical to success from the client side.

Reconnect-after-drop coverage is tracked separately: aio-pika fires its reconnect
callback and reports the connection open before the transport is actually ready to
open a channel, so that test needs a readiness gate rather than a callback wait.

Requires a broker; skipped unless RABBITMQ_HOST is set (CI supplies it via a
service container). Marked `integration` so `just test` does not pick it up.

Every await is bounded by an explicit timeout: a broker-side hang must fail with
a message naming the step, not stall until the CI job's ceiling kills it and
discards the output.
"""

import asyncio
from collections.abc import Awaitable
import os

from aio_pika.abc import AbstractRobustConnection
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

# Bounds for individual operations. Deliberately short — the whole point is to
# surface where a hang happens rather than to wait one out.
CONNECT_TIMEOUT = 20.0
OP_TIMEOUT = 15.0
STATS_TIMEOUT = 30.0

pytestmark.append(pytest.mark.skipif(not RABBITMQ_HOST, reason="RABBITMQ_HOST not set; no live broker available"))


def _amqp_url() -> str:
    return f"amqp://{RABBITMQ_USER}:{RABBITMQ_PASS}@{RABBITMQ_HOST}:{AMQP_PORT}/"


def _mgmt() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"http://{RABBITMQ_HOST}:{MGMT_PORT}",
        auth=(RABBITMQ_USER, RABBITMQ_PASS),
        timeout=15.0,
    )


async def _step[T](label: str, coro: Awaitable[T], timeout: float) -> T:
    """Await `coro` with a bound, reporting the step name on timeout."""
    print(f"  -> {label}", flush=True)
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except TimeoutError:
        pytest.fail(f"timed out after {timeout}s during: {label}")


async def _connections(client: httpx.AsyncClient) -> list[dict]:
    resp = await client.get("/api/connections")
    resp.raise_for_status()
    return list(resp.json())


async def _await_connections(client: httpx.AsyncClient, timeout: float = STATS_TIMEOUT) -> list[dict]:
    """Wait for the management stats DB to report at least one connection.

    The stats database is populated asynchronously, so an established connection
    may not appear immediately. An empty list that never fills usually means
    management stats are disabled (the RabbitMQ 4.x default) rather than that
    nothing is connected.
    """
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        conns = await _connections(client)
        if conns:
            return conns
        await asyncio.sleep(1.0)
    pytest.fail("management API reported no client connections; are management stats enabled? (disable_management_stats false)")


async def _close_quietly(connection: AbstractRobustConnection) -> None:
    """Close a connection without letting a stuck close fail an otherwise-good test.

    A RobustConnection whose transport was force-closed can block in close(), so
    this is bounded too — teardown must never decide the test's outcome.
    """
    try:
        await asyncio.wait_for(connection.close(), timeout=OP_TIMEOUT)
    except Exception as exc:  # teardown must never mask the test result
        print(f"  !! ignoring error/timeout while closing connection: {type(exc).__name__}", flush=True)


class TestLiveHeartbeatNegotiation:
    """The configured heartbeat must survive all the way into the AMQP handshake."""

    async def test_broker_reports_negotiated_heartbeat(self) -> None:
        manager = AsyncResilientRabbitMQ(connection_url=_amqp_url(), heartbeat=TEST_HEARTBEAT)
        connection = await _step("connect", manager.connect(), CONNECT_TIMEOUT)

        try:
            async with _mgmt() as client:
                # The broker's own view of the negotiated heartbeat is authoritative.
                conns = await _step("read /api/connections", _await_connections(client), STATS_TIMEOUT + 5)
                timeouts = {c.get("timeout") for c in conns}
                assert TEST_HEARTBEAT in timeouts, (
                    f"broker negotiated {timeouts}, expected {TEST_HEARTBEAT} (60 would mean the URL param was dropped)"
                )
        finally:
            await _close_quietly(connection)
