"""Tests for the digger agent runtime loop (fake streaming client).

The Anthropic client is faked: ``client.messages.stream(...)`` returns an async
context manager that is async-iterable (stream events) and exposes
``get_final_message()``. ``dispatch_tool`` is patched per test.
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest

from api.digger_agent.runtime import run_agent_turn
from api.digger_agent.tools.dispatch import ToolContext


def _text_delta(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="text_delta", text=text))


def _text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _tool_use_block(name: str, tool_input: dict[str, Any], block_id: str = "tu1") -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=block_id, name=name, input=tool_input)


def _usage(inp: int = 5, out: int = 1, cache_read: int = 0) -> SimpleNamespace:
    return SimpleNamespace(input_tokens=inp, output_tokens=out, cache_read_input_tokens=cache_read)


def _final(stop_reason: str, content: list[Any], usage: SimpleNamespace | None = None) -> SimpleNamespace:
    return SimpleNamespace(stop_reason=stop_reason, content=content, usage=usage or _usage())


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


def _client(streams: list[_FakeStream]) -> MagicMock:
    client = MagicMock()
    client.messages.stream = MagicMock(side_effect=streams)
    return client


def _ctx() -> ToolContext:
    return ToolContext(pool=MagicMock(), redis=MagicMock(), user_id=uuid.uuid4())


async def _collect(gen: Any) -> list[dict[str, Any]]:
    return [ev async for ev in gen]


@pytest.mark.asyncio
async def test_text_only_response_yields_text_and_done() -> None:
    client = _client([_FakeStream([_text_delta("hello")], _final("end_turn", [_text_block("hello")]))])
    events = await _collect(
        run_agent_turn(
            client=client,
            model="sonnet",
            ctx=_ctx(),
            messages=[{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
            max_iterations=2,
        )
    )
    kinds = [e["type"] for e in events]
    assert "text" in kinds
    assert "done" in kinds
    done = next(e for e in events if e["type"] == "done")
    assert done["usage"]["input"] == 5


@pytest.mark.asyncio
async def test_tool_use_then_text_emits_tool_and_bundle_events() -> None:
    streams = [
        _FakeStream(
            [_text_delta("let me check")],
            _final("tool_use", [_text_block("let me check"), _tool_use_block("compute_bundles", {"budget_cap_cents": 20000})]),
        ),
        _FakeStream([_text_delta("done")], _final("end_turn", [_text_block("done")])),
    ]
    client = _client(streams)
    with patch(
        "api.digger_agent.runtime.dispatch_tool",
        AsyncMock(return_value={"bundles": [{"name": "cheapest"}]}),
    ):
        events = await _collect(
            run_agent_turn(
                client=client,
                model="sonnet",
                ctx=_ctx(),
                messages=[{"role": "user", "content": [{"type": "text", "text": "find deals"}]}],
            )
        )
    kinds = [e["type"] for e in events]
    assert "tool_call" in kinds
    assert "tool_result" in kinds
    assert "bundle_card" in kinds
    assert "done" in kinds
    # the loop fed the tool result back as a user message
    done = next(e for e in events if e["type"] == "done")
    assert any(m["role"] == "user" and isinstance(m["content"], list) for m in done["messages_after"])


@pytest.mark.asyncio
async def test_proposal_card_emitted() -> None:
    streams = [
        _FakeStream([], _final("tool_use", [_tool_use_block("propose_tier_changes", {"changes": []})])),
        _FakeStream([], _final("end_turn", [_text_block("ok")])),
    ]
    client = _client(streams)
    with patch(
        "api.digger_agent.runtime.dispatch_tool",
        AsyncMock(return_value={"proposal_id": "p1", "count": 1}),
    ):
        events = await _collect(run_agent_turn(client=client, model="sonnet", ctx=_ctx(), messages=[{"role": "user", "content": []}]))
    assert any(e["type"] == "proposal_card" for e in events)


@pytest.mark.asyncio
async def test_error_tool_result_marked_is_error() -> None:
    streams = [
        _FakeStream([], _final("tool_use", [_tool_use_block("explain_bundle", {"bundle_name": "x"})])),
        _FakeStream([], _final("end_turn", [_text_block("sorry")])),
    ]
    client = _client(streams)
    with patch("api.digger_agent.runtime.dispatch_tool", AsyncMock(return_value={"error": "no result"})):
        events = await _collect(run_agent_turn(client=client, model="sonnet", ctx=_ctx(), messages=[{"role": "user", "content": []}]))
    result_ev = next(e for e in events if e["type"] == "tool_result")
    assert result_ev["output"] == {"error": "no result"}


@pytest.mark.asyncio
async def test_iteration_cap_stops_loop() -> None:
    def _always_tool_use(*_a: object, **_k: object) -> _FakeStream:
        return _FakeStream([], _final("tool_use", [_tool_use_block("get_user_settings", {})]))

    client = MagicMock()
    client.messages.stream = MagicMock(side_effect=_always_tool_use)
    with patch("api.digger_agent.runtime.dispatch_tool", AsyncMock(return_value={})):
        events = await _collect(
            run_agent_turn(client=client, model="sonnet", ctx=_ctx(), messages=[{"role": "user", "content": []}], max_iterations=2)
        )
    assert client.messages.stream.call_count == 2
    assert events[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_model_id_mapping() -> None:
    client = _client([_FakeStream([], _final("end_turn", [_text_block("hi")]))])
    await _collect(run_agent_turn(client=client, model="haiku", ctx=_ctx(), messages=[{"role": "user", "content": []}]))
    assert client.messages.stream.call_args.kwargs["model"] == "claude-haiku-4-5"


@pytest.mark.asyncio
async def test_unknown_model_defaults_to_sonnet() -> None:
    client = _client([_FakeStream([], _final("end_turn", [_text_block("hi")]))])
    await _collect(run_agent_turn(client=client, model="bogus", ctx=_ctx(), messages=[{"role": "user", "content": []}]))
    assert client.messages.stream.call_args.kwargs["model"] == "claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_system_prompt_is_cached() -> None:
    client = _client([_FakeStream([], _final("end_turn", [_text_block("hi")]))])
    await _collect(run_agent_turn(client=client, model="sonnet", ctx=_ctx(), messages=[{"role": "user", "content": []}]))
    system = client.messages.stream.call_args.kwargs["system"]
    assert system[0]["cache_control"] == {"type": "ephemeral"}
