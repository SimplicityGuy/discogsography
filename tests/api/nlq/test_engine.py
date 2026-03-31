"""Tests for NLQ engine — Claude tool-use loop orchestration."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.nlq.config import NLQConfig
from api.nlq.engine import NLQContext, NLQEngine, NLQResult
from api.nlq.tools import NLQToolRunner


# ── Mock helpers ─────────────────────────────────────────────────────────


def _make_text_response(text: str) -> MagicMock:
    """Simulate Claude response with only text (end_turn)."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    resp.stop_reason = "end_turn"
    return resp


def _make_tool_use_response(tool_name: str, tool_input: dict[str, Any], tool_use_id: str = "tu_1") -> MagicMock:
    """Simulate Claude response requesting a tool call."""
    block = MagicMock()
    block.type = "tool_use"
    block.name = tool_name
    block.input = tool_input
    block.id = tool_use_id
    resp = MagicMock()
    resp.content = [block]
    resp.stop_reason = "tool_use"
    return resp


def _make_config(**overrides: Any) -> NLQConfig:
    """Create a test NLQConfig with sensible defaults."""
    defaults: dict[str, Any] = {
        "enabled": True,
        "api_key": "test-key",
        "model": "claude-sonnet-4-20250514",
        "max_iterations": 5,
        "max_query_length": 500,
        "cache_ttl": 3600,
        "rate_limit": "10/minute",
    }
    defaults.update(overrides)
    return NLQConfig(**defaults)


def _make_client() -> MagicMock:
    """Create a mock Anthropic client."""
    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock()
    return client


def _make_tool_runner() -> MagicMock:
    """Create a mock NLQToolRunner."""
    runner = MagicMock(spec=NLQToolRunner)
    runner.execute = AsyncMock(return_value={"results": []})
    runner.extract_entities = MagicMock(return_value=[])
    return runner


# ── Tests ────────────────────────────────────────────────────────────────


class TestNLQEngineSimpleQuery:
    """Test simple query: tool_use then end_turn."""

    @pytest.mark.asyncio
    async def test_simple_query_single_tool_call(self) -> None:
        """Tool_use then end_turn produces NLQResult with summary, entities, tools_used."""
        config = _make_config()
        client = _make_client()
        runner = _make_tool_runner()

        # First call: Claude requests a tool call
        tool_response = _make_tool_use_response("search", {"q": "Radiohead"})
        # Second call: Claude returns final text
        text_response = _make_text_response("Radiohead is a British rock band on XL Recordings.")
        client.messages.create.side_effect = [tool_response, text_response]

        # Tool runner returns search results with an entity
        runner.execute.return_value = {"results": [{"id": "a123", "name": "Radiohead", "type": "artist"}]}
        runner.extract_entities.return_value = [{"id": "a123", "name": "Radiohead", "type": "artist"}]

        engine = NLQEngine(config=config, client=client, tool_runner=runner)
        result = await engine.run("Tell me about Radiohead", NLQContext())

        assert isinstance(result, NLQResult)
        assert result.summary == "Radiohead is a British rock band on XL Recordings."
        assert result.tools_used == ["search"]
        assert len(result.entities) == 1
        assert result.entities[0]["name"] == "Radiohead"


class TestNLQEngineMultiStep:
    """Test multi-step tool calls."""

    @pytest.mark.asyncio
    async def test_multi_step_tool_calls(self) -> None:
        """Two tool_use iterations then end_turn — verify 3 API calls total."""
        config = _make_config()
        client = _make_client()
        runner = _make_tool_runner()

        # Step 1: search tool
        step1 = _make_tool_use_response("search", {"q": "Radiohead"}, "tu_1")
        # Step 2: explore_entity tool
        step2 = _make_tool_use_response("explore_entity", {"type": "artist", "name": "Radiohead"}, "tu_2")
        # Step 3: final text
        step3 = _make_text_response("Radiohead is an artist on XL Recordings with 9 albums.")
        client.messages.create.side_effect = [step1, step2, step3]

        runner.execute.return_value = {"results": []}
        runner.extract_entities.return_value = []

        engine = NLQEngine(config=config, client=client, tool_runner=runner)
        result = await engine.run("Tell me about Radiohead", NLQContext())

        assert client.messages.create.call_count == 3
        assert result.tools_used == ["search", "explore_entity"]


class TestNLQEngineMaxIterations:
    """Test max iterations cap."""

    @pytest.mark.asyncio
    async def test_max_iterations_cap(self) -> None:
        """Always returns tool_use — verify stops at max_iterations."""
        config = _make_config(max_iterations=3)
        client = _make_client()
        runner = _make_tool_runner()

        # Always return tool_use — engine must stop after max_iterations
        tool_resp = _make_tool_use_response("search", {"q": "test"})
        client.messages.create.return_value = tool_resp

        runner.execute.return_value = {"results": []}
        runner.extract_entities.return_value = []

        engine = NLQEngine(config=config, client=client, tool_runner=runner)
        result = await engine.run("Keep searching forever", NLQContext())

        # Should have made exactly max_iterations API calls
        assert client.messages.create.call_count == 3
        assert isinstance(result, NLQResult)


class TestNLQEngineAuthTools:
    """Test auth tool inclusion based on context."""

    @pytest.mark.asyncio
    async def test_authenticated_context_adds_tools(self) -> None:
        """Verify auth tools in request when user_id is set."""
        config = _make_config()
        client = _make_client()
        runner = _make_tool_runner()

        text_response = _make_text_response("Your collection has 500 releases.")
        client.messages.create.return_value = text_response

        engine = NLQEngine(config=config, client=client, tool_runner=runner)
        await engine.run("How many releases do I have?", NLQContext(user_id="user-42"))

        # Check the tools passed to the API call
        call_kwargs = client.messages.create.call_args
        tools = call_kwargs.kwargs.get("tools", []) if call_kwargs.kwargs else call_kwargs[1].get("tools", [])
        tool_names = {t["name"] for t in tools}
        # Auth tools should be present
        assert "get_collection_stats" in tool_names
        assert "get_taste_fingerprint" in tool_names
        assert "get_taste_blindspots" in tool_names
        assert "get_collection_gaps" in tool_names

    @pytest.mark.asyncio
    async def test_unauthenticated_context_no_auth_tools(self) -> None:
        """Verify no auth tools when user_id is None."""
        config = _make_config()
        client = _make_client()
        runner = _make_tool_runner()

        text_response = _make_text_response("I can only help with music queries.")
        client.messages.create.return_value = text_response

        engine = NLQEngine(config=config, client=client, tool_runner=runner)
        await engine.run("Hello", NLQContext())

        call_kwargs = client.messages.create.call_args
        tools = call_kwargs.kwargs.get("tools", []) if call_kwargs.kwargs else call_kwargs[1].get("tools", [])
        tool_names = {t["name"] for t in tools}
        # Auth tools should NOT be present
        assert "get_collection_stats" not in tool_names
        assert "get_taste_fingerprint" not in tool_names
        assert "get_taste_blindspots" not in tool_names
        assert "get_collection_gaps" not in tool_names
        # Public tools should still be present
        assert "search" in tool_names


class TestNLQEngineGuardrails:
    """Test off-topic guardrails."""

    @pytest.mark.asyncio
    async def test_off_topic_guardrail_zero_tools(self) -> None:
        """Zero tools used + substantive answer -> redirect message."""
        config = _make_config()
        client = _make_client()
        runner = _make_tool_runner()

        # Claude responds without using any tools — off-topic
        text_response = _make_text_response("The capital of France is Paris.")
        client.messages.create.return_value = text_response

        engine = NLQEngine(config=config, client=client, tool_runner=runner)
        result = await engine.run("What is the capital of France?", NLQContext())

        assert result.tools_used == []
        assert "I can only answer questions about the Discogsography music database" in result.summary

    @pytest.mark.asyncio
    async def test_off_topic_guardrail_allows_refusals(self) -> None:
        """Zero tools used + refusal text -> pass through."""
        config = _make_config()
        client = _make_client()
        runner = _make_tool_runner()

        refusal_text = "I can only help with questions about the Discogsography music database. Try asking about an artist or genre!"
        text_response = _make_text_response(refusal_text)
        client.messages.create.return_value = text_response

        engine = NLQEngine(config=config, client=client, tool_runner=runner)
        result = await engine.run("What is the capital of France?", NLQContext())

        assert result.tools_used == []
        # Refusal text should pass through unchanged
        assert result.summary == refusal_text


class TestNLQEngineOnStatusCallback:
    """Test on_status callback for SSE streaming."""

    @pytest.mark.asyncio
    async def test_on_status_called_during_tool_use(self) -> None:
        """Verify on_status callback is invoked during tool execution."""
        config = _make_config()
        client = _make_client()
        runner = _make_tool_runner()

        tool_response = _make_tool_use_response("search", {"q": "test"})
        text_response = _make_text_response("Found results.")
        client.messages.create.side_effect = [tool_response, text_response]

        runner.execute.return_value = {"results": []}
        runner.extract_entities.return_value = []

        on_status = AsyncMock()

        engine = NLQEngine(config=config, client=client, tool_runner=runner)
        await engine.run("Search for test", NLQContext(), on_status=on_status)

        on_status.assert_called_once_with("Running search...")


class TestNLQEngineEntityDedup:
    """Test entity deduplication."""

    @pytest.mark.asyncio
    async def test_entity_deduplication(self) -> None:
        """Duplicate entities from multiple tool calls are deduplicated."""
        config = _make_config()
        client = _make_client()
        runner = _make_tool_runner()

        # Two tool calls returning same entity
        step1 = _make_tool_use_response("search", {"q": "Radiohead"}, "tu_1")
        step2 = _make_tool_use_response("explore_entity", {"type": "artist", "name": "Radiohead"}, "tu_2")
        step3 = _make_text_response("Radiohead is great.")
        client.messages.create.side_effect = [step1, step2, step3]

        # Both tool calls return the same entity
        runner.execute.return_value = {"results": []}
        runner.extract_entities.return_value = [{"id": "a123", "name": "Radiohead", "type": "artist"}]

        engine = NLQEngine(config=config, client=client, tool_runner=runner)
        result = await engine.run("Tell me about Radiohead", NLQContext())

        # Should be deduplicated to just one entity
        assert len(result.entities) == 1
        assert result.entities[0]["id"] == "a123"


class TestNLQEngineNonToolStop:
    """Test handling of non-tool, non-end_turn stop reasons (e.g., max_tokens)."""

    @pytest.mark.asyncio
    async def test_max_tokens_stop_returns_result(self) -> None:
        """When Claude stops with max_tokens and no tool_use blocks, return the partial text."""
        config = _make_config()
        client = _make_client()
        runner = _make_tool_runner()

        # Simulate max_tokens stop with text content but no tool_use
        block = MagicMock()
        block.type = "text"
        block.text = "Here is a partial answer about Radiohead..."
        resp = MagicMock()
        resp.content = [block]
        resp.stop_reason = "max_tokens"
        client.messages.create.return_value = resp

        engine = NLQEngine(config=config, client=client, tool_runner=runner)
        result = await engine.run("Tell me about Radiohead", NLQContext())

        assert isinstance(result, NLQResult)
        assert "partial answer" in result.summary
        # Only one API call — no tool loop
        assert client.messages.create.call_count == 1
