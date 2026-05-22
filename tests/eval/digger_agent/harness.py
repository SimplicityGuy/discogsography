"""Eval harness for the Digger agent.

An ``EvalCase`` pairs a user prompt with a set of behavioral assertions. The
harness runs the prompt through the real agent loop (``run_agent_turn``) and
collects the streamed events, reshaped into the same ``{"type", "data"}``
envelope the SSE endpoint emits, so assertions can inspect tool calls and text.

The runner that exercises these against a live model is gated on
``ANTHROPIC_API_KEY`` (``test_eval_runner.py``); the harness logic and the case
library themselves are unit-tested without a key in ``test_eval_cases.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from api.digger_agent.runtime import run_agent_turn


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    import anthropic

    from api.digger_agent.tools.context import ToolContext


@dataclass
class EvalCase:
    """A single agent eval: a prompt plus assertions over the streamed events."""

    name: str
    prompt: str
    assertions: list[tuple[str, Callable[[list[dict[str, Any]]], bool]]]
    setup: Callable[..., Awaitable[None]] | None = None
    model_override: str | None = None


def _tool_calls(events: list[dict[str, Any]], name: str | None = None) -> list[dict[str, Any]]:
    calls = [e for e in events if e["type"] == "tool_call"]
    if name is not None:
        calls = [e for e in calls if e["data"].get("name") == name]
    return calls


def assert_called_tool(name: str) -> tuple[str, Callable[[list[dict[str, Any]]], bool]]:
    """The agent called the named tool at least once."""
    return (f"called {name}", lambda events: bool(_tool_calls(events, name)))


def assert_not_called_tool(name: str) -> tuple[str, Callable[[list[dict[str, Any]]], bool]]:
    """The agent never called the named tool."""
    return (f"did not call {name}", lambda events: not _tool_calls(events, name))


def assert_tool_input_equals(name: str, key: str, value: Any) -> tuple[str, Callable[[list[dict[str, Any]]], bool]]:
    """Some call to ``name`` had ``input[key] == value``."""
    return (
        f"{name}.{key} == {value!r}",
        lambda events: any(e["data"].get("input", {}).get(key) == value for e in _tool_calls(events, name)),
    )


def assert_tool_input_present(name: str, key: str) -> tuple[str, Callable[[list[dict[str, Any]]], bool]]:
    """Some call to ``name`` supplied a non-empty ``input[key]``."""
    return (
        f"{name} called with {key}",
        lambda events: any(e["data"].get("input", {}).get(key) not in (None, [], "") for e in _tool_calls(events, name)),
    )


def assert_text_mentions(substring: str) -> tuple[str, Callable[[list[dict[str, Any]]], bool]]:
    """Some streamed text delta contains ``substring`` (case-insensitive)."""
    sub = substring.lower()
    return (
        f"text mentions {substring!r}",
        lambda events: any(sub in (e["data"].get("delta") or "").lower() for e in events if e["type"] == "text"),
    )


def assert_no_fabricated_numbers() -> tuple[str, Callable[[list[dict[str, Any]]], bool]]:
    """No dollar figures appear in text unless the optimizer was actually run."""
    return (
        "no $ figures without compute_bundles",
        lambda events: (
            not (any(e["type"] == "text" and "$" in (e["data"].get("delta") or "") for e in events) and not _tool_calls(events, "compute_bundles"))
        ),
    )


@dataclass
class AgentEvalHarness:
    """Runs an EvalCase through the real agent loop and collects its events."""

    client: anthropic.AsyncAnthropic
    ctx: ToolContext
    model: str = "sonnet"

    async def run(self, case: EvalCase) -> list[dict[str, Any]]:
        """Drive ``case.prompt`` through the agent and return SSE-shaped events."""
        model = case.model_override or self.model
        messages = [{"role": "user", "content": [{"type": "text", "text": case.prompt}]}]
        events: list[dict[str, Any]] = []
        async for ev in run_agent_turn(client=self.client, model=model, ctx=self.ctx, messages=messages):
            events.append({"type": ev["type"], "data": {k: v for k, v in ev.items() if k != "type"}})
        return events
