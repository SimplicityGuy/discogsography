"""Unit tests for the eval harness + case library (no API key required).

These run in regular CI and cover the assertion helpers, the case library
structure, and ``AgentEvalHarness.run`` (driven by a fake streaming client).
The live model runner lives in ``test_eval_runner.py`` (gated on ANTHROPIC_API_KEY).
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest

from tests.eval.digger_agent.cases import ALL_CASES
from tests.eval.digger_agent.harness import (
    AgentEvalHarness,
    EvalCase,
    assert_called_tool,
    assert_no_fabricated_numbers,
    assert_not_called_tool,
    assert_text_mentions,
    assert_tool_input_equals,
    assert_tool_input_present,
)


# --- case library structure ------------------------------------------------


def test_at_least_twenty_cases():
    assert len(ALL_CASES) >= 20


def test_all_cases_are_evalcases_with_unique_names():
    names = [c.name for c in ALL_CASES]
    assert all(isinstance(c, EvalCase) for c in ALL_CASES)
    assert len(names) == len(set(names)), "case names must be unique"


def test_each_case_has_prompt_and_assertions():
    for c in ALL_CASES:
        assert c.prompt.strip(), f"{c.name} has an empty prompt"
        assert c.assertions, f"{c.name} has no assertions"
        for desc, predicate in c.assertions:
            assert isinstance(desc, str) and callable(predicate)


# --- assertion helpers -----------------------------------------------------


def _tool_call(name: str, **inp: Any) -> dict[str, Any]:
    return {"type": "tool_call", "data": {"name": name, "input": inp}}


def _text(delta: str) -> dict[str, Any]:
    return {"type": "text", "data": {"delta": delta}}


def test_assert_called_tool():
    _, ok = assert_called_tool("compute_bundles")
    assert ok([_tool_call("compute_bundles")]) is True
    assert ok([_tool_call("get_wantlist")]) is False


def test_assert_not_called_tool():
    _, ok = assert_not_called_tool("propose_tier_changes")
    assert ok([_tool_call("compute_bundles")]) is True
    assert ok([_tool_call("propose_tier_changes")]) is False


def test_assert_tool_input_equals():
    _, ok = assert_tool_input_equals("compute_bundles", "budget_cap_cents", 20000)
    assert ok([_tool_call("compute_bundles", budget_cap_cents=20000)]) is True
    assert ok([_tool_call("compute_bundles", budget_cap_cents=5000)]) is False


def test_assert_tool_input_present():
    _, ok = assert_tool_input_present("compute_bundles", "excluded_sellers")
    assert ok([_tool_call("compute_bundles", excluded_sellers=[1, 2])]) is True
    assert ok([_tool_call("compute_bundles", excluded_sellers=[])]) is False
    assert ok([_tool_call("compute_bundles")]) is False


def test_assert_text_mentions():
    _, ok = assert_text_mentions("cheapest")
    assert ok([_text("The CHEAPEST bundle is...")]) is True
    assert ok([_text("nothing here")]) is False


def test_assert_no_fabricated_numbers():
    _, ok = assert_no_fabricated_numbers()
    # $ figure with no compute_bundles call -> fabricated -> fails
    assert ok([_text("That will be $42")]) is False
    # $ figure but compute_bundles was called -> fine
    assert ok([_tool_call("compute_bundles"), _text("That will be $42")]) is True
    # no $ figure -> fine
    assert ok([_text("Here are some ideas")]) is True


# --- AgentEvalHarness.run --------------------------------------------------


def _text_delta(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="text_delta", text=text))


def _text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _tool_use_block(name: str, tool_input: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id="tu1", name=name, input=tool_input)


def _final(stop_reason: str, content: list[Any]) -> SimpleNamespace:
    return SimpleNamespace(
        stop_reason=stop_reason, content=content, usage=SimpleNamespace(input_tokens=5, output_tokens=1, cache_read_input_tokens=0)
    )


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


def _ctx():
    from api.digger_agent.tools.context import ToolContext

    return ToolContext(pool=MagicMock(), redis=MagicMock(), user_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_harness_run_reshapes_events_to_sse_envelope():
    client = _client([_FakeStream([_text_delta("hello")], _final("end_turn", [_text_block("hello")]))])
    harness = AgentEvalHarness(client=client, ctx=_ctx())
    case = EvalCase(name="t", prompt="hi", assertions=[assert_text_mentions("hello")])
    events = await harness.run(case)
    # events carry the {"type", "data"} envelope the assertions expect
    assert any(e["type"] == "text" and e["data"].get("delta") == "hello" for e in events)
    assert any(e["type"] == "done" and "usage" in e["data"] for e in events)
    # the case's own assertion passes against the collected events
    assert all(predicate(events) for _desc, predicate in case.assertions)


@pytest.mark.asyncio
async def test_harness_run_collects_tool_calls():
    streams = [
        _FakeStream([], _final("tool_use", [_tool_use_block("compute_bundles", {"budget_cap_cents": 20000})])),
        _FakeStream([], _final("end_turn", [_text_block("done")])),
    ]
    harness = AgentEvalHarness(client=_client(streams), ctx=_ctx())
    case = EvalCase(name="t", prompt="deals", assertions=[assert_called_tool("compute_bundles")])
    with patch("api.digger_agent.runtime.dispatch_tool", AsyncMock(return_value={"bundles": []})):
        events = await harness.run(case)
    _desc, predicate = case.assertions[0]
    assert predicate(events) is True


@pytest.mark.asyncio
async def test_harness_run_honors_model_override():
    client = _client([_FakeStream([], _final("end_turn", [_text_block("hi")]))])
    harness = AgentEvalHarness(client=client, ctx=_ctx())
    case = EvalCase(name="t", prompt="hi", assertions=[], model_override="opus")
    await harness.run(case)
    assert client.messages.stream.call_args.kwargs["model"] == "claude-opus-4-7"
