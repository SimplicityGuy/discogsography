"""Tests for NLQ SSE streaming including the actions event."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_sse_emits_actions_event_before_result() -> None:
    from api.nlq.actions import SeedGraphAction, _SeedEntity  # type: ignore[attr-defined]
    from api.nlq.engine import NLQResult
    from api.routers import nlq as nlq_router

    engine = MagicMock()
    engine.run = AsyncMock(
        return_value=NLQResult(
            summary="Here is the answer.",
            entities=[],
            tools_used=["search"],
            actions=[SeedGraphAction(entities=[_SeedEntity(name="Kraftwerk", entity_type="artist")])],
        )
    )
    nlq_router._engine = engine

    response = nlq_router._stream_response("Tell me about Kraftwerk", None, None)
    events: list[dict[str, str]] = []
    async for event in response.body_iterator:
        events.append(event)

    kinds = [e.get("event") for e in events]
    assert "actions" in kinds
    assert "result" in kinds
    actions_idx = kinds.index("actions")
    result_idx = kinds.index("result")
    assert actions_idx < result_idx
    actions_event = events[actions_idx]
    payload = json.loads(actions_event["data"])
    assert payload["actions"][0]["type"] == "seed_graph"


@pytest.mark.asyncio
async def test_sse_replays_cached_result_without_running_engine() -> None:
    """discogsography-cu2.27: when a streaming request hits a cache entry (written
    by a prior JSON request), the cached result must be replayed as synthetic
    actions/result SSE events — never run the engine, never emit a JSON body.
    """
    from api.routers import nlq as nlq_router

    engine = MagicMock()
    engine.run = AsyncMock(side_effect=AssertionError("engine must not run for a cache hit"))
    nlq_router._engine = engine

    cached = {
        "query": "who produced Thriller",
        "summary": "Quincy Jones",
        "entities": [],
        "tools_used": ["search"],
        "actions": [{"type": "seed_graph"}],
        "cached": True,
    }
    response = nlq_router._stream_response("who produced Thriller", None, None, cached=cached)
    events = [event async for event in response.body_iterator]

    kinds = [e.get("event") for e in events]
    assert kinds == ["actions", "result"]
    result_payload = json.loads(events[1]["data"])
    assert result_payload["summary"] == "Quincy Jones"
    assert result_payload["cached"] is True
    engine.run.assert_not_called()


@pytest.mark.asyncio
async def test_sse_cancels_engine_task_on_client_disconnect() -> None:
    """discogsography-cu2.28: when the SSE client disconnects, the generator is
    closed and the still-running engine task must be cancelled so the
    Anthropic/Neo4j work does not leak and the pending task cannot be GC'd.
    """
    import asyncio

    from api.routers import nlq as nlq_router

    cancelled = asyncio.Event()

    async def slow_run(_query: object, _ctx: object, on_status: object = None) -> None:
        if on_status is not None:
            await on_status("thinking")  # type: ignore[operator]
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    engine = MagicMock()
    engine.run = slow_run
    nlq_router._engine = engine

    response = nlq_router._stream_response("slow question", None, None)
    iterator = response.body_iterator
    first = await iterator.__anext__()
    assert first["event"] == "status"

    # Simulate client disconnect — sse-starlette closes the generator.
    await iterator.aclose()

    assert cancelled.is_set()
