"""Integration tests for AsyncResilientRabbitMQ against a LIVE RabbitMQ broker.

These cover the one thing unit tests fundamentally cannot: that the heartbeat we
put in the AMQP URL is actually *negotiated* with the broker, rather than
silently falling back to aiormq's default of 60s. That matters specifically
because of the aio-pika 10 migration — 10.x removed ``**kwargs`` from
``connect_robust()``, so tuning parameters moved into the URL query string, and a
parameter that fails to parse looks identical to success from the client side.

They also cover reconnect-after-drop, including that RobustChannel restores a
previously-declared queue — the behavior all four consumers depend on and which
nothing else asserts. Getting there needed a real readiness gate: aio-pika fires
its reconnect callback and reports `is_closed == False` while the forced-close
error is still in flight, so a callback wait alone is not sufficient.

Requires a broker; skipped unless RABBITMQ_HOST is set (CI supplies it via a
service container). Marked `integration` so `just test` does not pick them up.

Every await is bounded by an explicit timeout: a broker-side hang must fail with
a message naming the step, not stall until the CI job's ceiling kills it and
discards the output.
"""

import asyncio
from collections.abc import Awaitable, Callable
import os
from urllib.parse import quote

from aio_pika import Message
from aio_pika.abc import AbstractChannel, AbstractRobustConnection
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
RECONNECT_TIMEOUT = 45.0

# Durable + non-exclusive, deliberately: an exclusive queue dies with its
# connection, so it could never demonstrate RobustChannel restoration. Transient
# non-exclusive is not an option either — RabbitMQ 4 refuses those
# (`transient_nonexcl_queues` deprecated, not permitted by default).
RESTORE_QUEUE = "aio-pika-10-restore-probe"

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


async def _await_flag(label: str, predicate: Callable[[], bool], timeout: float) -> None:
    """Poll until predicate() is truthy, failing with `label` on timeout."""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.5)
    pytest.fail(f"timed out after {timeout}s waiting for: {label}")


async def _drop_all_connections(client: httpx.AsyncClient) -> int:
    """Force the broker to close every client connection. Returns how many."""
    conns = await _await_connections(client)
    for info in conns:
        # Connection names contain characters that must be percent-encoded.
        resp = await client.delete(f"/api/connections/{quote(info['name'], safe='')}")
        if resp.status_code not in (204, 404):
            resp.raise_for_status()
    return len(conns)


async def _channel_when_ready(connection: AbstractRobustConnection, timeout: float) -> AbstractChannel:
    """Open a channel once the connection is genuinely usable again.

    Two gates, because neither alone is sufficient:

    1. ``connection.ready()`` awaits aio-pika's ``connected`` Event, which is
       cleared on close and set in ``_on_connected``. This is the readiness signal
       that a reconnect-callback wait does NOT give you.
    2. A bounded retry around ``channel()``. Even after ``ready()``, the
       forced-close error can still be in flight — the previous attempt at this
       test failed with ``ConnectionClosed: CONNECTION_FORCED`` immediately after
       the callback fired and ``is_closed`` read False.
    """
    await _step("await connection.ready()", connection.ready(), timeout)
    deadline = asyncio.get_running_loop().time() + timeout
    last: Exception | None = None
    attempt = 0
    while asyncio.get_running_loop().time() < deadline:
        attempt += 1
        try:
            channel = await asyncio.wait_for(connection.channel(), timeout=OP_TIMEOUT)
        except Exception as exc:  # in-flight close errors are expected here
            last = exc
            print(f"  .. channel attempt {attempt} not ready yet ({type(exc).__name__})", flush=True)
            await asyncio.sleep(1.0)
        else:
            print(f"  -> channel open after reconnect (attempt {attempt})", flush=True)
            return channel
    pytest.fail(f"could not open a channel within {timeout}s of reconnect; last error: {type(last).__name__}: {last}")


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


class TestLiveReconnect:
    """A dropped connection must recover, fire our callbacks, and restore its queues."""

    async def test_reconnects_and_restores_declared_queue(self) -> None:
        manager = AsyncResilientRabbitMQ(
            connection_url=_amqp_url(),
            heartbeat=TEST_HEARTBEAT,
            retry_delay=1.0,  # -> reconnect_interval, keeps recovery quick
        )
        reconnected = asyncio.Event()
        manager.add_reconnect_callback(lambda: reconnected.set())

        connection = await _step("connect", manager.connect(), CONNECT_TIMEOUT)
        try:
            channel = await _step("open channel", connection.channel(), OP_TIMEOUT)
            queue = await _step(
                f"declare durable queue {RESTORE_QUEUE}",
                channel.declare_queue(RESTORE_QUEUE, durable=True),
                OP_TIMEOUT,
            )

            async with _mgmt() as client:
                dropped = await _step("force-close all client connections", _drop_all_connections(client), OP_TIMEOUT + STATS_TIMEOUT)
                assert dropped >= 1, "no connections were dropped, so nothing was tested"

            # The callback proves OUR wiring fired; ready() proves the transport is
            # actually usable. The earlier version of this test asserted only the
            # former and then failed on CONNECTION_FORCED.
            await _await_flag("reconnect callback to fire", reconnected.is_set, RECONNECT_TIMEOUT)
            channel = await _channel_when_ready(connection, RECONNECT_TIMEOUT)

            # RobustChannel is expected to have re-declared the queue on recovery.
            # Round-trip a message through the SAME queue object declared before the
            # drop: that is precisely the contract the four consumers rely on.
            await _step(
                "publish through restored channel",
                channel.default_exchange.publish(Message(b"restored"), routing_key=RESTORE_QUEUE),
                OP_TIMEOUT,
            )
            message = await _step("get message from restored queue", queue.get(timeout=OP_TIMEOUT), OP_TIMEOUT + 5)
            assert message is not None, "restored queue yielded no message"
            assert message.body == b"restored", f"unexpected body {message.body!r}"
            await message.ack()

            await _step("delete probe queue", queue.delete(), OP_TIMEOUT)
        finally:
            await _close_quietly(connection)
