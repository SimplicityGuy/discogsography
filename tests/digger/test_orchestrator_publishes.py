"""Tests for Redis scrape-progress publishing in digger.scraper.orchestrator.

The worker publishes a small JSON progress payload after each scrape attempt:
- once to the global ``digger:refresh:scrape`` channel, and
- once per user wantlisting the scraped release on ``digger:refresh:{user_id}``.

Pub/sub is exercised against an in-process fakeredis client; the Postgres
fan-out query is served by a lightweight stub pool (plain async classes to
avoid MagicMock recursion on Python 3.13/3.14).
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from digger.scraper.orchestrator import (
    SCRAPE_CHANNEL,
    _publish_scrape_progress,
    scrape_loop,
)


# ---------------------------------------------------------------------------
# Stub pool that serves the per-user fan-out query
# ---------------------------------------------------------------------------


class _CM:
    def __init__(self, value: object) -> None:
        self._value = value

    async def __aenter__(self) -> object:
        return self._value

    async def __aexit__(self, *_: object) -> None:
        pass


class _Cursor:
    def __init__(self, rows: list[tuple[uuid.UUID]]) -> None:
        self._rows = rows
        self.executed: list[tuple[str, tuple[object, ...]]] = []

    async def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.executed.append((sql, params))

    async def fetchall(self) -> list[tuple[uuid.UUID]]:
        return self._rows


class _Conn:
    def __init__(self, cursor: _Cursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _CM:
        return _CM(self._cursor)


class _Pool:
    def __init__(self, rows: list[tuple[uuid.UUID]]) -> None:
        self.cursor = _Cursor(rows)
        self._conn = _Conn(self.cursor)
        self.raise_on_connection = False

    def connection(self) -> _CM:
        if self.raise_on_connection:
            raise RuntimeError("pool unavailable")
        return _CM(self._conn)


# ---------------------------------------------------------------------------
# _publish_scrape_progress
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_fans_out_to_global_and_user_channels(redis_test_client) -> None:
    """A scrape publishes to the global channel and to each wantlisting user."""
    user_id = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
    pool = _Pool(rows=[(user_id,)])

    pubsub = redis_test_client.pubsub()
    await pubsub.subscribe(SCRAPE_CHANNEL, f"digger:refresh:{user_id}")
    await asyncio.sleep(0.05)

    await _publish_scrape_progress(redis=redis_test_client, pool=pool, release_id=42, ok=True)

    received: dict[str, dict[str, object]] = {}
    for _ in range(6):
        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
        if msg is None:
            continue
        channel = msg["channel"]
        channel_str = channel.decode() if isinstance(channel, bytes) else channel
        data = msg["data"]
        data_str = data.decode() if isinstance(data, bytes) else data
        received[channel_str] = json.loads(data_str)

    await pubsub.aclose()

    assert SCRAPE_CHANNEL in received
    assert f"digger:refresh:{user_id}" in received
    assert received[SCRAPE_CHANNEL] == {"release_id": 42, "status": "ok", "eta_seconds_remaining": 0}
    assert received[f"digger:refresh:{user_id}"]["release_id"] == 42


@pytest.mark.asyncio
async def test_publish_reports_failed_status(redis_test_client) -> None:
    """A failed scrape publishes status='failed'."""
    pool = _Pool(rows=[])

    pubsub = redis_test_client.pubsub()
    await pubsub.subscribe(SCRAPE_CHANNEL)
    await asyncio.sleep(0.05)

    await _publish_scrape_progress(redis=redis_test_client, pool=pool, release_id=7, ok=False)

    payload = None
    for _ in range(6):
        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
        if msg is None:
            continue
        data = msg["data"]
        payload = json.loads(data.decode() if isinstance(data, bytes) else data)
        break

    await pubsub.aclose()

    assert payload == {"release_id": 7, "status": "failed", "eta_seconds_remaining": 0}


@pytest.mark.asyncio
async def test_publish_swallows_errors(redis_test_client) -> None:
    """A failure mid-publish is logged, not raised (must never kill the scrape loop)."""
    pool = _Pool(rows=[])
    pool.raise_on_connection = True

    # Should not raise even though the pool fan-out query blows up.
    await _publish_scrape_progress(redis=redis_test_client, pool=pool, release_id=99, ok=True)


# ---------------------------------------------------------------------------
# scrape_loop integration — only publishes when redis is provided
# ---------------------------------------------------------------------------


class _LoopCursor:
    def __init__(self, release_id: int | None) -> None:
        self.fetchone = _make_async(return_value=(release_id,) if release_id is not None else None)
        self.execute = _make_async()
        self.rowcount = 0


def _make_async(return_value: object = None):
    async def _fn(*_a: object, **_k: object) -> object:
        return return_value

    return _fn


class _LoopConn:
    def __init__(self, cursor: _LoopCursor) -> None:
        self._cursor = cursor

    def transaction(self) -> _CM:
        return _CM(None)

    def cursor(self) -> _CM:
        return _CM(self._cursor)

    async def set_autocommit(self, _value: bool) -> None:
        pass


class _LoopPool:
    def __init__(self, release_id: int | None) -> None:
        self._conn = _LoopConn(_LoopCursor(release_id))

    def connection(self) -> _CM:
        return _CM(self._conn)


class _Rate:
    async def acquire(self) -> float:
        await asyncio.sleep(0)
        return 0.0


class _Breaker:
    def __init__(self) -> None:
        self.records: list[bool] = []

    async def is_open(self) -> bool:
        return False

    async def record(self, success: bool) -> None:
        self.records.append(success)


class _Executor:
    def __init__(self) -> None:
        self.calls: list[int] = []

    async def scrape_release(self, release_id: int) -> bool:
        self.calls.append(release_id)
        return True


@pytest.mark.asyncio
async def test_scrape_loop_publishes_when_redis_provided(monkeypatch: pytest.MonkeyPatch) -> None:
    """When redis is supplied, scrape_loop publishes progress after each scrape."""
    published: list[tuple[int, bool]] = []

    async def _fake_publish(*, redis: object, pool: object, release_id: int, ok: bool) -> None:  # noqa: ARG001
        published.append((release_id, ok))

    monkeypatch.setattr("digger.scraper.orchestrator._publish_scrape_progress", _fake_publish)

    pool = _LoopPool(release_id=1)
    stop_event = asyncio.Event()

    async def stopper() -> None:
        await asyncio.sleep(0.2)
        stop_event.set()

    sentinel_redis = object()
    task = asyncio.create_task(stopper())
    await scrape_loop(
        pool=pool,  # type: ignore[arg-type]
        executor=_Executor(),  # type: ignore[arg-type]
        rate=_Rate(),  # type: ignore[arg-type]
        breaker=_Breaker(),  # type: ignore[arg-type]
        stop_event=stop_event,
        redis=sentinel_redis,  # type: ignore[arg-type]
    )
    await task

    assert (1, True) in published


@pytest.mark.asyncio
async def test_scrape_loop_skips_publish_when_redis_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """With redis=None (default), scrape_loop never publishes."""
    published: list[tuple[int, bool]] = []

    async def _fake_publish(**_kwargs: object) -> None:
        published.append((1, True))

    monkeypatch.setattr("digger.scraper.orchestrator._publish_scrape_progress", _fake_publish)

    pool = _LoopPool(release_id=1)
    stop_event = asyncio.Event()

    async def stopper() -> None:
        await asyncio.sleep(0.2)
        stop_event.set()

    task = asyncio.create_task(stopper())
    await scrape_loop(
        pool=pool,  # type: ignore[arg-type]
        executor=_Executor(),  # type: ignore[arg-type]
        rate=_Rate(),  # type: ignore[arg-type]
        breaker=_Breaker(),  # type: ignore[arg-type]
        stop_event=stop_event,
    )
    await task

    assert published == []
