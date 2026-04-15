"""Tests that NLQEngine returns an action list in NLQResult."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_result_includes_actions_when_agent_emits_them() -> None:
    from api.nlq.actions import SeedGraphAction
    from api.nlq.config import NLQConfig
    from api.nlq.engine import NLQContext, NLQEngine

    first = MagicMock()
    first.stop_reason = "tool_use"
    first.content = [MagicMock(type="tool_use", id="tu1", name="search", input={"q": "Kraftwerk"})]

    final = MagicMock()
    final.stop_reason = "end_turn"
    final.content = [
        MagicMock(
            type="text",
            text='Here is the answer.\n\n<!--actions:[{"type":"seed_graph","entities":[{"name":"Kraftwerk","entity_type":"artist"}]}]-->',
        )
    ]

    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock(side_effect=[first, final])

    tool_runner = MagicMock()
    tool_runner.execute = AsyncMock(return_value={"results": []})
    tool_runner.extract_entities = MagicMock(return_value=[])

    engine = NLQEngine(NLQConfig(), client, tool_runner)
    result = await engine.run("Tell me about Kraftwerk", NLQContext())

    assert result.summary == "Here is the answer."
    assert len(result.actions) == 1
    assert isinstance(result.actions[0], SeedGraphAction)


@pytest.mark.asyncio
async def test_result_has_empty_actions_when_none_emitted() -> None:
    from api.nlq.config import NLQConfig
    from api.nlq.engine import NLQContext, NLQEngine

    final = MagicMock()
    final.stop_reason = "end_turn"
    final.content = [MagicMock(type="text", text="Just a text answer.")]

    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock(return_value=final)

    engine = NLQEngine(NLQConfig(), client, MagicMock())
    result = await engine.run("Hi", NLQContext())

    assert result.summary == "Just a text answer."
    assert result.actions == []
