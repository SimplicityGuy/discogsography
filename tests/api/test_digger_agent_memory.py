"""Tests for digger agent conversation memory + summarization (mock-based).

The plan's ``seeded_agent_session`` fixtures do not exist; ``list_messages`` is
patched instead, and the Anthropic client is a stub.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.digger_agent.memory import MAX_TURNS, build_message_history


def _text_msg(role: str, text: str) -> dict[str, Any]:
    return {"role": role, "content": [{"type": "text", "text": text}]}


def _mixed_messages(n: int = 50) -> list[dict[str, Any]]:
    # Includes a tool_use block (dict w/o "text"), a string content, and a list with
    # a bare string element so the token/dump helpers exercise every branch.
    special: list[dict[str, Any]] = [
        {"role": "user", "content": [{"type": "text", "text": "hello there"}]},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "compute_bundles", "input": {}}]},
        {"role": "user", "content": "a plain string message"},
        {"role": "assistant", "content": ["a bare string block"]},
    ]
    padding = [_text_msg("user" if i % 2 == 0 else "assistant", f"m{i}") for i in range(n - len(special))]
    return special + padding


@pytest.mark.asyncio
async def test_under_cap_returns_messages_and_no_anchor() -> None:
    msgs = [_text_msg("user", "hi"), _text_msg("assistant", "hello")]
    with patch("api.digger_agent.memory.list_messages", AsyncMock(return_value=msgs)):
        out, anchor = await build_message_history(MagicMock(), "sid")
    assert out == msgs
    assert anchor is None


@pytest.mark.asyncio
async def test_over_turn_cap_no_client_truncates() -> None:
    msgs = _mixed_messages(50)
    with patch("api.digger_agent.memory.list_messages", AsyncMock(return_value=msgs)):
        tail, anchor = await build_message_history(MagicMock(), "sid")
    assert len(tail) == MAX_TURNS
    assert anchor is not None
    assert anchor["role"] == "user"
    assert anchor["content"][0]["text"].startswith("[prior context summary]")


@pytest.mark.asyncio
async def test_over_turn_cap_with_client_uses_model_summary() -> None:
    msgs = _mixed_messages(50)

    block = MagicMock()
    block.text = "MODEL SUMMARY"
    resp = MagicMock()
    resp.content = [block]
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=resp)

    with patch("api.digger_agent.memory.list_messages", AsyncMock(return_value=msgs)):
        _tail, anchor = await build_message_history(MagicMock(), "sid", client=client)

    assert anchor is not None
    assert "MODEL SUMMARY" in anchor["content"][0]["text"]
    assert client.messages.create.await_args.kwargs["model"] == "claude-haiku-4-5"


@pytest.mark.asyncio
async def test_summarization_failure_falls_back() -> None:
    msgs = _mixed_messages(50)
    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=RuntimeError("api down"))
    with patch("api.digger_agent.memory.list_messages", AsyncMock(return_value=msgs)):
        _tail, anchor = await build_message_history(MagicMock(), "sid", client=client)
    assert anchor is not None
    assert "(prior context truncated)" in anchor["content"][0]["text"]


@pytest.mark.asyncio
async def test_over_token_cap_triggers_summary() -> None:
    # 30 messages (< MAX_TURNS*2) but each large enough to exceed the token cap.
    big = "x" * 8000
    msgs = [_text_msg("user" if i % 2 == 0 else "assistant", big) for i in range(30)]
    with patch("api.digger_agent.memory.list_messages", AsyncMock(return_value=msgs)):
        tail, anchor = await build_message_history(MagicMock(), "sid")
    assert len(tail) == MAX_TURNS
    assert anchor is not None
