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
        await asyncio.sleep(0.2)
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
            await asyncio.sleep(0.2)
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
        await asyncio.sleep(0.2)
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
            await asyncio.sleep(0.2)
            stop_event.set()

        _task = asyncio.create_task(stopper())
        await state_loop(pool=pool, stop_event=stop_event, interval_seconds=1)  # type: ignore[arg-type]
        await _task

    assert len(refresh_calls) >= 1, "refresh_all_due_times should have been called at least once"


# ---------------------------------------------------------------------------
# scrape_loop — breaker open path (lines 42-47)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scrape_loop_breaker_open_stop_during_wait() -> None:
    """Breaker is open; stop_event is set while the loop waits → loop exits cleanly (lines 42-45)."""
    pool = _Pool(release_id=1)
    rate = _Rate()
    cb = _Breaker(open=True)
    executor = _Executor(success=True)
    stop_event = asyncio.Event()

    # Set stop_event shortly after the loop enters the breaker-open wait
    async def stopper() -> None:
        await asyncio.sleep(0.05)
        stop_event.set()

    _task = asyncio.create_task(stopper())
    await scrape_loop(pool=pool, executor=executor, rate=rate, breaker=cb, stop_event=stop_event)  # type: ignore[arg-type]
    await _task

    # Nothing should have been scraped — breaker was open the whole time
    assert executor._calls == []


@pytest.mark.asyncio
async def test_scrape_loop_breaker_open_timeout_then_stops() -> None:
    """Breaker is open; wait_for times out (lines 45-46: TimeoutError pass), then the breaker closes and loop runs."""

    class _ToggleBreaker:
        """Returns open=True exactly once then open=False thereafter."""

        def __init__(self) -> None:
            self._call = 0
            self._records: list[bool] = []

        async def is_open(self) -> bool:
            self._call += 1
            # First two calls: open (first call enters the wait_for timeout branch)
            return self._call <= 1

        async def record(self, success: bool) -> None:
            self._records.append(success)

    pool = _Pool(release_id=1)
    rate = _Rate()
    cb = _ToggleBreaker()
    executor = _Executor(success=True)
    stop_event = asyncio.Event()

    # Stop quickly after a couple of loop iterations
    async def stopper() -> None:
        await asyncio.sleep(0.3)
        stop_event.set()

    with patch("digger.scraper.orchestrator.asyncio.wait_for", new=_fast_timeout_wait_for):
        _task = asyncio.create_task(stopper())
        await scrape_loop(pool=pool, executor=executor, rate=rate, breaker=cb, stop_event=stop_event)  # type: ignore[arg-type]
        await _task

    # At least one scrape ran after the breaker opened
    assert len(executor._calls) >= 1


async def _fast_timeout_wait_for(coro: object, *, timeout: float = 0) -> None:  # noqa: ARG001
    """Replacement for asyncio.wait_for that raises TimeoutError immediately."""
    coro_obj = coro  # type: ignore[assignment]
    # Close the coroutine to avoid 'was never awaited' warnings
    if hasattr(coro_obj, "close"):
        coro_obj.close()  # type: ignore[union-attr]
    raise TimeoutError


# ---------------------------------------------------------------------------
# scrape_loop — queue empty timeout path (lines 61-62)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scrape_loop_queue_empty_timeout_continues() -> None:
    """When the queue is empty and the 2-s wait times out, the loop continues (lines 61-62)."""
    pool = _Pool(release_id=None)
    rate = _Rate()
    cb = _Breaker(open=False)
    executor = _Executor(success=True)
    stop_event = asyncio.Event()

    iterations = 0

    async def _counting_wait_for(coro: object, *, timeout: float = 0) -> None:  # noqa: ARG001
        """Raise TimeoutError immediately to simulate the 2 s queue-empty wait expiring."""
        nonlocal iterations
        coro_obj = coro  # type: ignore[assignment]
        if hasattr(coro_obj, "close"):
            coro_obj.close()  # type: ignore[union-attr]
        iterations += 1
        if iterations >= 2:
            stop_event.set()
        raise TimeoutError

    with patch("digger.scraper.orchestrator.asyncio.wait_for", new=_counting_wait_for):
        await scrape_loop(pool=pool, executor=executor, rate=rate, breaker=cb, stop_event=stop_event)  # type: ignore[arg-type]

    assert executor._calls == [], "No scrape when queue always empty"
    assert iterations >= 2


# ---------------------------------------------------------------------------
# state_loop — exception handler (lines 89-90) and interval timeout (lines 93-94)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_state_loop_handles_exception_and_continues() -> None:
    """state_loop logs exceptions from refresh_all_due_times and continues (lines 89-90)."""
    pool = _Pool(release_id=None)
    stop_event = asyncio.Event()
    call_count = 0

    async def _failing_refresh(_cur: object) -> int:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("db blew up")
        return 0

    with patch("digger.scraper.orchestrator.refresh_all_due_times", new=_failing_refresh):

        async def stopper() -> None:
            await asyncio.sleep(0.2)
            stop_event.set()

        _task = asyncio.create_task(stopper())
        await state_loop(pool=pool, stop_event=stop_event, interval_seconds=1)  # type: ignore[arg-type]
        await _task

    # Must have been called at least once despite the exception
    assert call_count >= 1


@pytest.mark.asyncio
async def test_state_loop_interval_timeout_continues() -> None:
    """state_loop's wait_for raises TimeoutError when stop_event is not set (lines 93-94)."""
    pool = _Pool(release_id=None)
    stop_event = asyncio.Event()
    call_count = 0

    async def _fast_refresh(_cur: object) -> int:
        nonlocal call_count
        call_count += 1
        return 0

    timeouts = 0

    async def _timeout_wait_for(coro: object, *, timeout: float = 0) -> None:  # noqa: ARG001
        """Always raise TimeoutError, then let the outer stopper end the loop."""
        nonlocal timeouts
        coro_obj = coro  # type: ignore[assignment]
        if hasattr(coro_obj, "close"):
            coro_obj.close()  # type: ignore[union-attr]
        timeouts += 1
        if timeouts >= 2:
            stop_event.set()
        raise TimeoutError

    with (
        patch("digger.scraper.orchestrator.refresh_all_due_times", new=_fast_refresh),
        patch("digger.scraper.orchestrator.asyncio.wait_for", new=_timeout_wait_for),
    ):
        await state_loop(pool=pool, stop_event=stop_event, interval_seconds=1)  # type: ignore[arg-type]

    assert call_count >= 2, f"refresh should have run ≥2 times; got {call_count}"
    assert timeouts >= 2
