"""Tests for digger.scheduler.runner.scheduler_loop + fetch_users_due_for_report.

The loop polls the API's internal "users due for report" endpoint and runs a
scheduled report for each due user, surviving both per-user and per-iteration
failures. HTTP is faked with respx; the per-user runner and the due-user fetch
are monkeypatched.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock
import uuid

import httpx
import pytest
import respx

from digger.scheduler.runner import fetch_users_due_for_report, scheduler_loop


_API_BASE = "http://api:8004"
_SERVICE_TOKEN = "test-service-token"  # not a real secret — S105 is ignored for tests
_USER_ID = "00000000-0000-0000-0000-000000000001"


# ---------------------------------------------------------------------------
# fetch_users_due_for_report
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_users_due_for_report_returns_user_list() -> None:
    with respx.mock(base_url=_API_BASE) as mock:
        route = mock.get("/api/internal/digger/users-due-for-report").mock(
            return_value=httpx.Response(200, json={"users": [{"user_id": _USER_ID, "cadence": "weekly"}]})
        )
        users = await fetch_users_due_for_report(_API_BASE, _SERVICE_TOKEN)

    assert route.called
    assert route.calls.last.request.headers["X-Service-Token"] == _SERVICE_TOKEN
    assert users == [{"user_id": _USER_ID, "cadence": "weekly"}]


@pytest.mark.asyncio
async def test_fetch_users_due_for_report_raises_on_error_status() -> None:
    with respx.mock(base_url=_API_BASE) as mock:
        mock.get("/api/internal/digger/users-due-for-report").mock(return_value=httpx.Response(503))
        with pytest.raises(httpx.HTTPStatusError):
            await fetch_users_due_for_report(_API_BASE, _SERVICE_TOKEN)


# ---------------------------------------------------------------------------
# scheduler_loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scheduler_loop_runs_each_due_user(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each due user is handed to run_scheduled_for_user with its cadence."""
    monkeypatch.setattr(
        "digger.scheduler.runner.fetch_users_due_for_report",
        AsyncMock(return_value=[{"user_id": _USER_ID, "cadence": "monthly"}]),
    )
    runner = AsyncMock(return_value=None)
    monkeypatch.setattr("digger.scheduler.runner.run_scheduled_for_user", runner)

    stop_event = asyncio.Event()

    async def stopper() -> None:
        await asyncio.sleep(0.2)
        stop_event.set()

    task = asyncio.create_task(stopper())
    await scheduler_loop(
        pool=object(),  # type: ignore[arg-type]
        stop_event=stop_event,
        api_base_url=_API_BASE,
        service_token=_SERVICE_TOKEN,
        poll_interval=0.05,
    )
    await task

    runner.assert_awaited()
    assert runner.await_args is not None
    assert runner.await_args.args[1] == uuid.UUID(_USER_ID)
    assert runner.await_args.kwargs["cadence"] == "monthly"


@pytest.mark.asyncio
async def test_scheduler_loop_survives_per_user_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failing per-user run is logged and does not abort the loop."""
    monkeypatch.setattr(
        "digger.scheduler.runner.fetch_users_due_for_report",
        AsyncMock(return_value=[{"user_id": _USER_ID, "cadence": "weekly"}]),
    )
    runner = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr("digger.scheduler.runner.run_scheduled_for_user", runner)

    stop_event = asyncio.Event()

    async def stopper() -> None:
        await asyncio.sleep(0.2)
        stop_event.set()

    task = asyncio.create_task(stopper())
    await scheduler_loop(
        pool=object(),  # type: ignore[arg-type]
        stop_event=stop_event,
        api_base_url=_API_BASE,
        service_token=_SERVICE_TOKEN,
        poll_interval=0.05,
    )
    await task

    runner.assert_awaited()  # the failing call happened; the loop kept going


@pytest.mark.asyncio
async def test_scheduler_loop_survives_iteration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failing due-user fetch is logged and does not abort the loop."""
    monkeypatch.setattr(
        "digger.scheduler.runner.fetch_users_due_for_report",
        AsyncMock(side_effect=RuntimeError("api down")),
    )
    runner = AsyncMock(return_value=None)
    monkeypatch.setattr("digger.scheduler.runner.run_scheduled_for_user", runner)

    stop_event = asyncio.Event()

    async def stopper() -> None:
        await asyncio.sleep(0.2)
        stop_event.set()

    task = asyncio.create_task(stopper())
    await scheduler_loop(
        pool=object(),  # type: ignore[arg-type]
        stop_event=stop_event,
        api_base_url=_API_BASE,
        service_token=_SERVICE_TOKEN,
        poll_interval=0.05,
    )
    await task

    runner.assert_not_awaited()  # fetch failed before any user ran


@pytest.mark.asyncio
async def test_scheduler_loop_poll_timeout_continues(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the poll wait times out (stop not set), the loop iterates again."""
    monkeypatch.setattr(
        "digger.scheduler.runner.fetch_users_due_for_report",
        AsyncMock(return_value=[]),
    )

    stop_event = asyncio.Event()
    timeouts = 0

    async def _timeout_wait_for(coro: object, *, timeout: float = 0) -> None:  # noqa: ARG001
        nonlocal timeouts
        if hasattr(coro, "close"):
            coro.close()  # type: ignore[union-attr]
        timeouts += 1
        if timeouts >= 2:
            stop_event.set()
        raise TimeoutError

    monkeypatch.setattr("digger.scheduler.runner.asyncio.wait_for", _timeout_wait_for)

    await scheduler_loop(
        pool=object(),  # type: ignore[arg-type]
        stop_event=stop_event,
        api_base_url=_API_BASE,
        service_token=_SERVICE_TOKEN,
        poll_interval=0.05,
    )

    assert timeouts >= 2
