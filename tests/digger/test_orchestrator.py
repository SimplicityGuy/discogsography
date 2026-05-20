"""Tests for digger.scraper.orchestrator.

All tests use simple stub objects to avoid Python 3.13 MagicMock recursion issues.
One iteration of scrape_loop pops a release, scrapes it, and records the outcome.
state_loop issues the refresh SQL once per interval.

Real transactional behaviour against a live DB is deferred to the M1 e2e smoke
(Task 28).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from digger.scraper.orchestrator import scrape_loop, state_loop


# ---------------------------------------------------------------------------
# Stub helpers — plain Python classes avoid MagicMock recursion in Python 3.13
# ---------------------------------------------------------------------------


class _CM:
    """Reusable async context manager returning a fixed value."""

    def __init__(self, value: object) -> None:
        self._value = value

    async def __aenter__(self) -> object:
        return self._value

    async def __aexit__(self, *_: object) -> None:
        pass


class _Cursor:
    def __init__(self, release_id: int | None) -> None:
        self._release_id = release_id
        self.execute = AsyncMock()
        self.fetchone = AsyncMock(return_value=(release_id,) if release_id is not None else None)
        self.rowcount = 0


class _Conn:
    def __init__(self, cursor: _Cursor) -> None:
        self._cursor = cursor
        self.set_autocommit = AsyncMock()

    def transaction(self) -> _CM:
        return _CM(None)

    def cursor(self) -> _CM:
        return _CM(self._cursor)


class _Pool:
    def __init__(self, release_id: int | None) -> None:
        self._cursor = _Cursor(release_id)
        self._conn = _Conn(self._cursor)

    def connection(self) -> _CM:
        return _CM(self._conn)

    @property
    def cursor(self) -> _Cursor:
        return self._cursor

    @property
    def conn(self) -> _Conn:
        return self._conn


class _Rate:
    def __init__(self) -> None:
        self._calls = 0

    async def acquire(self) -> float:
        self._calls += 1
        await asyncio.sleep(0)  # yield to event loop once per call
        return 0.0


class _Breaker:
    def __init__(self, open: bool = False) -> None:
        self._open = open
        self._records: list[bool] = []

    async def is_open(self) -> bool:
        return self._open

    async def record(self, success: bool) -> None:
        self._records.append(success)


class _Executor:
    def __init__(self, success: bool = True) -> None:
        self._success = success
        self._calls: list[int] = []

    async def scrape_release(self, release_id: int) -> bool:
        self._calls.append(release_id)
        return self._success


# ---------------------------------------------------------------------------
# scrape_loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scrape_loop_runs_one_iteration_and_stops() -> None:
    """scrape_loop pops release_id=1, scrapes it, then stops when event is set."""
    pool = _Pool(release_id=1)
    rate = _Rate()
    cb = _Breaker(open=False)
    executor = _Executor(success=True)
    stop_event = asyncio.Event()

    async def stopper() -> None:
        await asyncio.sleep(0.05)
        stop_event.set()

    _task = asyncio.create_task(stopper())
    await scrape_loop(pool=pool, executor=executor, rate=rate, breaker=cb, stop_event=stop_event)  # type: ignore[arg-type]
    await _task

    assert 1 in executor._calls, f"release_id=1 was never scraped; calls={executor._calls}"
    assert True in cb._records, f"no success record; records={cb._records}"


@pytest.mark.asyncio
async def test_scrape_loop_records_failure_on_scrape_error() -> None:
    """When scrape_release returns False, record_failure is called for the release."""
    pool = _Pool(release_id=7)
    rate = _Rate()
    cb = _Breaker(open=False)
    executor = _Executor(success=False)
    stop_event = asyncio.Event()

    recorded_ids: list[int] = []

    async def _fake_record_failure(_cur: object, release_id: int) -> None:
        recorded_ids.append(release_id)

    with patch("digger.scraper.orchestrator.record_failure", new=_fake_record_failure):

        async def stopper() -> None:
            await asyncio.sleep(0.05)
            stop_event.set()

        _task = asyncio.create_task(stopper())
        await scrape_loop(pool=pool, executor=executor, rate=rate, breaker=cb, stop_event=stop_event)  # type: ignore[arg-type]
        await _task

    assert 7 in recorded_ids, f"release_id=7 not recorded; got {recorded_ids}"


@pytest.mark.asyncio
async def test_scrape_loop_sleeps_when_circuit_open() -> None:
    """When the circuit breaker is open the loop sleeps and does not scrape."""
    pool = _Pool(release_id=1)
    rate = _Rate()
    cb = _Breaker(open=True)
    executor = _Executor(success=True)

    stop_event = asyncio.Event()
    stop_event.set()  # Stop immediately so the 30-s wait_for exits right away

    await scrape_loop(pool=pool, executor=executor, rate=rate, breaker=cb, stop_event=stop_event)  # type: ignore[arg-type]

    assert executor._calls == [], f"scrape should not have been called; calls={executor._calls}"


@pytest.mark.asyncio
async def test_scrape_loop_sleeps_when_queue_empty() -> None:
    """When pop_next_due returns None the loop sleeps briefly and continues."""
    pool = _Pool(release_id=None)
    rate = _Rate()
    cb = _Breaker(open=False)
    executor = _Executor(success=True)
    stop_event = asyncio.Event()

    async def stopper() -> None:
        await asyncio.sleep(0.05)
        stop_event.set()

    _task = asyncio.create_task(stopper())
    await scrape_loop(pool=pool, executor=executor, rate=rate, breaker=cb, stop_event=stop_event)  # type: ignore[arg-type]
    await _task

    assert executor._calls == [], f"no release should be scraped when queue empty; calls={executor._calls}"


# ---------------------------------------------------------------------------
# state_loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_state_loop_calls_refresh_and_stops() -> None:
    """state_loop calls refresh_all_due_times once then stops when event is set."""
    pool = _Pool(release_id=None)
    stop_event = asyncio.Event()
    refresh_calls: list[object] = []

    async def _fake_refresh(cur: object) -> int:
        refresh_calls.append(cur)
        return 3

    with patch("digger.scraper.orchestrator.refresh_all_due_times", new=_fake_refresh):

        async def stopper() -> None:
            await asyncio.sleep(0.05)
            stop_event.set()

        _task = asyncio.create_task(stopper())
        await state_loop(pool=pool, stop_event=stop_event, interval_seconds=1)  # type: ignore[arg-type]
        await _task

    assert len(refresh_calls) >= 1, "refresh_all_due_times should have been called at least once"
