"""Tests for the /api/digger/agent SSE message endpoint and session list.

The Anthropic client is faked: ``anthropic.AsyncAnthropic`` is patched so the
runtime drives a fake streaming client (``_FakeStream``). The SSE response is
exercised end-to-end via the sync ``TestClient`` — the EventSourceResponse
generator runs to completion and the full body is asserted on (M2 precedent).
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from api.queries.digger_queries import UserDiggerSettings


def _enabled_settings(*, cap: int = 200_000, model: str = "sonnet") -> UserDiggerSettings:
    return UserDiggerSettings(
        user_id=uuid.uuid4(),
        enabled=True,
        country_code="US",
        currency="USD",
        scheduled_cadence="off",
        preferred_model=model,  # type: ignore[arg-type]
        daily_token_cap_interactive=cap,
        daily_token_cap_scheduled=100_000,
    )


def _text_delta(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="text_delta", text=text))


def _text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _usage(inp: int = 5, out: int = 1, cache_read: int = 0) -> SimpleNamespace:
    return SimpleNamespace(input_tokens=inp, output_tokens=out, cache_read_input_tokens=cache_read)


def _final(stop_reason: str, content: list[Any]) -> SimpleNamespace:
    return SimpleNamespace(stop_reason=stop_reason, content=content, usage=_usage())


class _FakeStream:
    def __init__(self, events: list[Any], final: SimpleNamespace) -> None:
        self._events = events
        self._final = final

    async def __aenter__(self) -> "_FakeStream":
        return self

    async def __aexit__(self, *_: object) -> bool:
        return False

    async def __aiter__(self) -> Any:
        for event in self._events:
            yield event

    async def get_final_message(self) -> SimpleNamespace:
        return self._final


def _fake_anthropic(streams: list[_FakeStream]) -> MagicMock:
    """Patch target for anthropic.AsyncAnthropic — returns a client driving the given streams."""
    client = MagicMock()
    client.messages.stream = MagicMock(side_effect=streams)
    return MagicMock(return_value=client)


def _fake_run(events: list[dict[str, Any]]) -> Any:
    """Build a run_agent_turn replacement that yields the given events."""

    async def _gen(**_kwargs: Any) -> Any:
        for ev in events:
            yield ev

    return _gen


# --- guard / auth paths ----------------------------------------------------


def test_message_requires_auth(test_client: TestClient) -> None:
    r = test_client.post("/api/digger/agent/message", json={"user_message": "hi"})
    assert r.status_code == 401


def test_message_403_when_no_settings(test_client: TestClient, auth_headers: dict[str, str]) -> None:
    with patch("api.routers.digger_agent.q.get_user_settings", AsyncMock(return_value=None)):
        r = test_client.post("/api/digger/agent/message", headers=auth_headers, json={"user_message": "hi"})
    assert r.status_code == 403


def test_message_403_when_disabled(test_client: TestClient, auth_headers: dict[str, str]) -> None:
    settings = _enabled_settings()
    settings.enabled = False
    with patch("api.routers.digger_agent.q.get_user_settings", AsyncMock(return_value=settings)):
        r = test_client.post("/api/digger/agent/message", headers=auth_headers, json={"user_message": "hi"})
    assert r.status_code == 403


def test_message_429_when_cap_exceeded(test_client: TestClient, auth_headers: dict[str, str]) -> None:
    # cap=0 -> remaining is 0 -> is_exceeded True without touching Redis counters.
    with patch("api.routers.digger_agent.q.get_user_settings", AsyncMock(return_value=_enabled_settings(cap=0))):
        r = test_client.post("/api/digger/agent/message", headers=auth_headers, json={"user_message": "hi"})
    assert r.status_code == 429


# --- streaming paths -------------------------------------------------------


def test_message_streams_text_and_done(test_client: TestClient, auth_headers: dict[str, str]) -> None:
    streams = [_FakeStream([_text_delta("hello")], _final("end_turn", [_text_block("hello")]))]
    with (
        patch("api.routers.digger_agent.q.get_user_settings", AsyncMock(return_value=_enabled_settings())),
        patch("api.routers.digger_agent.anthropic.AsyncAnthropic", _fake_anthropic(streams)),
    ):
        r = test_client.post("/api/digger/agent/message", headers=auth_headers, json={"user_message": "hi"})
    assert r.status_code == 200
    assert "event: text" in r.text
    assert "event: done" in r.text


def test_message_prepends_anchor(test_client: TestClient, auth_headers: dict[str, str]) -> None:
    streams = [_FakeStream([_text_delta("ok")], _final("end_turn", [_text_block("ok")]))]
    anchor = {"role": "user", "content": [{"type": "text", "text": "[prior context summary]: ..."}]}
    history = [{"role": "user", "content": [{"type": "text", "text": "earlier"}]}]
    with (
        patch("api.routers.digger_agent.q.get_user_settings", AsyncMock(return_value=_enabled_settings())),
        patch("api.routers.digger_agent.build_message_history", AsyncMock(return_value=(history, anchor))),
        patch("api.routers.digger_agent.anthropic.AsyncAnthropic", _fake_anthropic(streams)),
    ):
        r = test_client.post("/api/digger/agent/message", headers=auth_headers, json={"user_message": "hi"})
    assert r.status_code == 200
    assert "event: done" in r.text


def test_message_emits_error_event_when_lock_held(test_client: TestClient, auth_headers: dict[str, str]) -> None:
    class _RaisingLock:
        def __init__(self, *_a: object, **_k: object) -> None:
            pass

        def acquire(self, *_a: object, **_k: object) -> Any:
            @asynccontextmanager
            async def _cm() -> Any:
                raise RuntimeError("another agent session is already running for this user")
                yield  # pragma: no cover

            return _cm()

    with (
        patch("api.routers.digger_agent.q.get_user_settings", AsyncMock(return_value=_enabled_settings())),
        patch("api.routers.digger_agent.ConcurrencyLock", _RaisingLock),
        patch("api.routers.digger_agent.anthropic.AsyncAnthropic", _fake_anthropic([])),
    ):
        r = test_client.post("/api/digger/agent/message", headers=auth_headers, json={"user_message": "hi"})
    assert r.status_code == 200
    assert "event: error" in r.text
    assert "already running" in r.text


def test_message_emits_error_event_on_unexpected_exception(test_client: TestClient, auth_headers: dict[str, str]) -> None:
    """Non-RuntimeError raised inside the stream must surface as an SSE error event, not abort the response."""

    def _raising_run(**_kwargs: Any) -> Any:
        async def _gen() -> Any:
            raise ValueError("boom from inside the agent loop")
            yield  # pragma: no cover

        return _gen()

    with (
        patch("api.routers.digger_agent.q.get_user_settings", AsyncMock(return_value=_enabled_settings())),
        patch("api.routers.digger_agent.run_agent_turn", _raising_run),
        patch("api.routers.digger_agent.anthropic.AsyncAnthropic", _fake_anthropic([])),
    ):
        r = test_client.post("/api/digger/agent/message", headers=auth_headers, json={"user_message": "hi"})
    assert r.status_code == 200
    assert "event: error" in r.text
    assert "boom from inside the agent loop" in r.text


def test_message_without_done_skips_persistence(test_client: TestClient, auth_headers: dict[str, str]) -> None:
    with (
        patch("api.routers.digger_agent.q.get_user_settings", AsyncMock(return_value=_enabled_settings())),
        patch("api.routers.digger_agent.anthropic.AsyncAnthropic", _fake_anthropic([])),
        patch("api.routers.digger_agent.run_agent_turn", _fake_run([{"type": "text", "delta": "hi"}])),
        patch("api.routers.digger_agent.aq.append_message", AsyncMock()) as append_mock,
        patch("api.routers.digger_agent.aq.update_token_totals", AsyncMock()) as totals_mock,
    ):
        r = test_client.post("/api/digger/agent/message", headers=auth_headers, json={"user_message": "hi"})
    assert r.status_code == 200
    assert "event: text" in r.text
    assert "event: done" not in r.text
    # The user message is appended before streaming; no assistant append and no totals update.
    assert append_mock.await_count == 1
    totals_mock.assert_not_awaited()


def test_message_done_with_trailing_tool_results_skips_assistant_append(test_client: TestClient, auth_headers: dict[str, str]) -> None:
    done_event = {
        "type": "done",
        "usage": {"input": 5, "output": 1, "cache_read": 0},
        "messages_after": [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "{}"}]}],
    }
    with (
        patch("api.routers.digger_agent.q.get_user_settings", AsyncMock(return_value=_enabled_settings())),
        patch("api.routers.digger_agent.anthropic.AsyncAnthropic", _fake_anthropic([])),
        patch("api.routers.digger_agent.run_agent_turn", _fake_run([done_event])),
        patch("api.routers.digger_agent.aq.append_message", AsyncMock()) as append_mock,
        patch("api.routers.digger_agent.aq.update_token_totals", AsyncMock()) as totals_mock,
    ):
        r = test_client.post("/api/digger/agent/message", headers=auth_headers, json={"user_message": "hi"})
    assert r.status_code == 200
    assert "event: done" in r.text
    # Only the initial user message append; the trailing message is not an assistant turn.
    assert append_mock.await_count == 1
    totals_mock.assert_awaited_once()


# --- cost helper -----------------------------------------------------------


def test_estimate_cost_usd_known_model() -> None:
    from decimal import Decimal

    from api.routers.digger_agent import _estimate_cost_usd

    cost = _estimate_cost_usd("haiku", {"input": 1_000_000, "output": 1_000_000, "cache_read": 0})
    assert cost == Decimal("1.0") + Decimal("5.0")


def test_estimate_cost_usd_unknown_model_falls_back_to_sonnet() -> None:
    from api.routers.digger_agent import _estimate_cost_usd

    fallback = _estimate_cost_usd("bogus", {"input": 1_000_000, "output": 0, "cache_read": 0})
    sonnet = _estimate_cost_usd("sonnet", {"input": 1_000_000, "output": 0, "cache_read": 0})
    assert fallback == sonnet


# --- sessions list ---------------------------------------------------------


def test_list_sessions_requires_auth(test_client: TestClient) -> None:
    r = test_client.get("/api/digger/agent/sessions")
    assert r.status_code == 401


def test_list_sessions_returns_items(test_client: TestClient, auth_headers: dict[str, str]) -> None:
    items = [
        {
            "session_id": str(uuid.uuid4()),
            "started_at": "2026-05-21T00:00:00+00:00",
            "last_active_at": "2026-05-22T00:00:00+00:00",
            "total_cost_usd": 0.0123,
        }
    ]
    with patch("api.routers.digger_agent.aq.list_sessions", AsyncMock(return_value=items)):
        r = test_client.get("/api/digger/agent/sessions", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["total_cost_usd"] == 0.0123


# --- DI guards -------------------------------------------------------------


def test_get_pool_and_redis_raise_when_unconfigured() -> None:
    import api.routers.digger_agent as mod

    saved_pool, saved_redis = mod._pool, mod._redis
    mod._pool = None
    mod._redis = None
    try:
        with pytest.raises(HTTPException):
            mod._get_pool()
        with pytest.raises(HTTPException):
            mod._get_redis()
    finally:
        mod._pool, mod._redis = saved_pool, saved_redis
