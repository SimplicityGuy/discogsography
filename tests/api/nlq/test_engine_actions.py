"""Tests that NLQEngine populates NLQResult.actions from action tool invocations."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.nlq.actions import (
    Action,
    FilterGraphAction,
    FindPathAction,
    FocusNodeAction,
    HighlightPathAction,
    OpenInsightTileAction,
    SeedGraphAction,
    SetTrendRangeAction,
    ShowCreditsAction,
    SuggestFollowupsAction,
    SwitchPaneAction,
)
from api.nlq.config import NLQConfig
from api.nlq.engine import NLQContext, NLQEngine, NLQResult
from api.nlq.tools import NLQToolRunner


def _make_config() -> NLQConfig:
    return NLQConfig(
        enabled=True,
        api_key="test-key",
        model="claude-sonnet-4-20250514",
        max_iterations=5,
        max_query_length=500,
        cache_ttl=3600,
        rate_limit="10/minute",
    )


def _tool_use_block(name: str, inp: dict[str, Any], block_id: str = "tu_act") -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.name = name
    block.input = inp
    block.id = block_id
    return block


def _tool_use_response(blocks: list[MagicMock]) -> MagicMock:
    resp = MagicMock()
    resp.stop_reason = "tool_use"
    resp.content = blocks
    return resp


def _end_turn_response(text: str) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp = MagicMock()
    resp.stop_reason = "end_turn"
    resp.content = [block]
    return resp


async def _run_with_action(tool_name: str, tool_input: dict[str, Any]) -> NLQResult:
    """Run engine with a single action tool_use block followed by end_turn."""
    first = _tool_use_response([_tool_use_block(tool_name, tool_input, "tu_1")])
    final = _end_turn_response("Done.")

    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock(side_effect=[first, final])

    # Use a real runner so action validation and recording happen end-to-end.
    runner = NLQToolRunner(neo4j_driver=MagicMock(), pg_pool=MagicMock(), redis=MagicMock())
    engine = NLQEngine(config=_make_config(), client=client, tool_runner=runner)
    return await engine.run("do the thing", NLQContext())


# ── Per-action tool tests ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_seed_graph_action_recorded() -> None:
    result = await _run_with_action(
        "ui_seed_graph",
        {"entities": [{"name": "Kraftwerk", "entity_type": "artist"}], "replace": True},
    )
    assert len(result.actions) == 1
    action = result.actions[0]
    assert isinstance(action, SeedGraphAction)
    assert action.entities[0].name == "Kraftwerk"
    assert action.entities[0].entity_type == "artist"
    assert action.replace is True


@pytest.mark.asyncio
async def test_highlight_path_action_recorded() -> None:
    result = await _run_with_action("ui_highlight_path", {"nodes": ["A", "B", "C"]})
    assert len(result.actions) == 1
    action = result.actions[0]
    assert isinstance(action, HighlightPathAction)
    assert action.nodes == ["A", "B", "C"]


@pytest.mark.asyncio
async def test_focus_node_action_recorded() -> None:
    result = await _run_with_action("ui_focus_node", {"name": "Aphex Twin", "entity_type": "artist"})
    assert len(result.actions) == 1
    action = result.actions[0]
    assert isinstance(action, FocusNodeAction)
    assert action.name == "Aphex Twin"
    assert action.entity_type == "artist"


@pytest.mark.asyncio
async def test_filter_graph_action_recorded() -> None:
    result = await _run_with_action("ui_filter_graph", {"by": "genre", "value": "Techno"})
    assert len(result.actions) == 1
    action = result.actions[0]
    assert isinstance(action, FilterGraphAction)
    assert action.by == "genre"
    assert action.value == "Techno"


@pytest.mark.asyncio
async def test_ui_find_path_action_recorded_as_find_path() -> None:
    """The ``ui_find_path`` tool records an action with client type ``find_path``."""
    result = await _run_with_action(
        "ui_find_path",
        {"from": "Kraftwerk", "to": "Daft Punk", "from_type": "artist", "to_type": "artist"},
    )
    assert len(result.actions) == 1
    action = result.actions[0]
    assert isinstance(action, FindPathAction)
    assert action.type == "find_path"
    assert action.from_name == "Kraftwerk"
    assert action.to_name == "Daft Punk"


@pytest.mark.asyncio
async def test_show_credits_action_recorded() -> None:
    result = await _run_with_action("ui_show_credits", {"name": "Radiohead", "entity_type": "artist"})
    assert len(result.actions) == 1
    action = result.actions[0]
    assert isinstance(action, ShowCreditsAction)
    assert action.name == "Radiohead"


@pytest.mark.asyncio
async def test_switch_pane_action_recorded() -> None:
    result = await _run_with_action("ui_switch_pane", {"pane": "trends"})
    assert len(result.actions) == 1
    action = result.actions[0]
    assert isinstance(action, SwitchPaneAction)
    assert action.pane == "trends"


@pytest.mark.asyncio
async def test_open_insight_tile_action_recorded() -> None:
    result = await _run_with_action("ui_open_insight_tile", {"tile_id": "top-labels"})
    assert len(result.actions) == 1
    action = result.actions[0]
    assert isinstance(action, OpenInsightTileAction)
    assert action.tile_id == "top-labels"


@pytest.mark.asyncio
async def test_set_trend_range_action_recorded() -> None:
    result = await _run_with_action("ui_set_trend_range", {"from": "1990", "to": "2020"})
    assert len(result.actions) == 1
    action = result.actions[0]
    assert isinstance(action, SetTrendRangeAction)
    assert action.from_year == "1990"
    assert action.to_year == "2020"


@pytest.mark.asyncio
async def test_suggest_followups_action_recorded() -> None:
    result = await _run_with_action(
        "ui_suggest_followups",
        {"queries": ["What about Aphex Twin?", "Show me more like this"]},
    )
    assert len(result.actions) == 1
    action = result.actions[0]
    assert isinstance(action, SuggestFollowupsAction)
    assert len(action.queries) == 2


# ── Multi-action and integration tests ───────────────────────────────────


@pytest.mark.asyncio
async def test_mixed_data_and_action_tools_in_same_iteration() -> None:
    """Data tool + action tool in one iteration both run; action is recorded."""
    first = _tool_use_response(
        [
            _tool_use_block("search", {"q": "Kraftwerk"}, "tu_data"),
            _tool_use_block(
                "ui_seed_graph",
                {"entities": [{"name": "Kraftwerk", "entity_type": "artist"}]},
                "tu_action",
            ),
        ]
    )
    final = _end_turn_response("Here you go.")

    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock(side_effect=[first, final])

    runner = MagicMock()

    async def fake_execute(
        name: str, _params: dict[str, Any], _user_id: str | None = None, action_recorder: list[Action] | None = None
    ) -> dict[str, Any]:
        if name == "search":
            return {"results": []}
        real = NLQToolRunner(MagicMock(), MagicMock(), MagicMock())
        return real.execute_action(name, _params, action_recorder)

    runner.execute = AsyncMock(side_effect=fake_execute)
    runner.extract_entities = MagicMock(return_value=[])

    engine = NLQEngine(config=_make_config(), client=client, tool_runner=runner)
    result = await engine.run("Show me Kraftwerk", NLQContext())

    assert "search" in result.tools_used
    assert "ui_seed_graph" in result.tools_used
    assert len(result.actions) == 1
    assert isinstance(result.actions[0], SeedGraphAction)


@pytest.mark.asyncio
async def test_no_actions_when_model_uses_only_data_tools() -> None:
    """A pure data-tool flow leaves ``actions`` empty."""
    first = _tool_use_response([_tool_use_block("search", {"q": "x"}, "tu_1")])
    final = _end_turn_response("Text only answer.")

    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock(side_effect=[first, final])

    runner = MagicMock()
    runner.execute = AsyncMock(return_value={"results": []})
    runner.extract_entities = MagicMock(return_value=[])

    engine = NLQEngine(config=_make_config(), client=client, tool_runner=runner)
    result = await engine.run("hello", NLQContext())

    assert result.summary == "Text only answer."
    assert result.actions == []


@pytest.mark.asyncio
async def test_invalid_action_payload_returns_error_and_skips_recording() -> None:
    """An action tool with an invalid payload returns an error and is NOT recorded."""
    first = _tool_use_response(
        [
            _tool_use_block(
                "ui_switch_pane",
                {"pane": "not_a_real_pane"},
                "tu_bad",
            ),
        ]
    )
    final = _end_turn_response("Oops.")

    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock(side_effect=[first, final])

    runner = NLQToolRunner(neo4j_driver=MagicMock(), pg_pool=MagicMock(), redis=MagicMock())
    engine = NLQEngine(config=_make_config(), client=client, tool_runner=runner)
    result = await engine.run("switch", NLQContext())

    assert result.actions == []


@pytest.mark.asyncio
async def test_multiple_distinct_actions_recorded_in_order() -> None:
    first = _tool_use_response(
        [
            _tool_use_block("ui_switch_pane", {"pane": "trends"}, "tu_1"),
            _tool_use_block("ui_set_trend_range", {"from": "1990", "to": "2020"}, "tu_2"),
        ]
    )
    final = _end_turn_response("Done.")

    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock(side_effect=[first, final])

    runner = NLQToolRunner(neo4j_driver=MagicMock(), pg_pool=MagicMock(), redis=MagicMock())
    engine = NLQEngine(config=_make_config(), client=client, tool_runner=runner)
    result = await engine.run("trends please", NLQContext())

    assert len(result.actions) == 2
    assert isinstance(result.actions[0], SwitchPaneAction)
    assert isinstance(result.actions[1], SetTrendRangeAction)
