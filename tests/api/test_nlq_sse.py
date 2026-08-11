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


@pytest.mark.asyncio
async def test_streamed_result_event_carries_actions() -> None:
    """Regression discogsography-l6fm.

    Actions were emitted ONLY on the sideband ``actions`` frame while the
    ``result`` frame omitted them, but the sole SSE consumer reads
    ``result.actions``. Every streaming query therefore applied ``[]`` — the whole
    UI-action system (seed_graph, switch_pane, focus_node, …) was dead in
    production, since the Ask pill only ever uses the streaming path.

    The streamed result must carry the same ``actions`` the non-streaming JSON
    body does.
    """
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

    response = nlq_router._stream_response("Show Kraftwerk on the graph", None, None)
    events = [event async for event in response.body_iterator]

    kinds = [e.get("event") for e in events]
    result_payload = json.loads(events[kinds.index("result")]["data"])
    actions_payload = json.loads(events[kinds.index("actions")]["data"])

    assert result_payload["actions"] == actions_payload["actions"], "the result frame must carry the same actions as the sideband frame"
    assert result_payload["actions"][0]["type"] == "seed_graph"


@pytest.mark.asyncio
async def test_streamed_cached_replay_result_event_carries_actions() -> None:
    """Regression discogsography-l6fm — same omission on the cached-replay path."""
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

    result_payload = json.loads(events[1]["data"])

    assert result_payload["actions"] == [{"type": "seed_graph"}]
    assert result_payload["cached"] is True


@pytest.mark.asyncio
async def test_streaming_query_writes_redis_cache_for_anonymous_user() -> None:
    """Regression discogsography-c584.

    The streaming path is the ONLY path the production Ask UI uses (nlq.js
    always sends Accept: text/event-stream), but the cache write previously
    existed only on the non-streaming JSON branch. So the cache — and the
    cached-replay SSE machinery above — was permanently unpopulated in
    production and every identical anonymous query re-ran the full engine.
    """
    from api.nlq.engine import NLQResult
    from api.routers import nlq as nlq_router

    engine = MagicMock()
    engine.run = AsyncMock(
        return_value=NLQResult(summary="Quincy Jones", entities=[], tools_used=["search"], actions=[]),
    )
    nlq_router._engine = engine

    from api.nlq.config import NLQConfig

    mock_redis = AsyncMock()
    original_redis = nlq_router._redis
    original_config = nlq_router._nlq_config
    nlq_router._redis = mock_redis
    nlq_router._nlq_config = NLQConfig(enabled=True, api_key="k", cache_ttl=3600)
    try:
        response = nlq_router._stream_response("who produced Thriller", None, None)
        events = [event async for event in response.body_iterator]
    finally:
        nlq_router._redis = original_redis
        nlq_router._nlq_config = original_config

    kinds = [e.get("event") for e in events]
    assert "result" in kinds

    mock_redis.setex.assert_awaited_once()
    call_args = mock_redis.setex.call_args
    cache_key, ttl, payload_json = call_args[0]
    assert cache_key == nlq_router._cache_key("who produced Thriller")
    assert ttl == 3600
    payload = json.loads(payload_json)
    assert payload["summary"] == "Quincy Jones"
    assert payload["cached"] is False


@pytest.mark.asyncio
async def test_streaming_query_does_not_cache_for_authenticated_user() -> None:
    """Regression discogsography-c584 — mirror the non-streaming branch's
    user_id is None guard: authenticated results must never populate the
    public query cache."""
    from api.nlq.engine import NLQResult
    from api.routers import nlq as nlq_router

    engine = MagicMock()
    engine.run = AsyncMock(return_value=NLQResult(summary="private answer", entities=[], tools_used=[], actions=[]))
    nlq_router._engine = engine

    mock_redis = AsyncMock()
    original_redis = nlq_router._redis
    nlq_router._redis = mock_redis
    try:
        response = nlq_router._stream_response("my collection stats", "user-123", None)
        _ = [event async for event in response.body_iterator]
    finally:
        nlq_router._redis = original_redis

    mock_redis.setex.assert_not_awaited()


@pytest.mark.asyncio
async def test_streamed_result_matches_non_streaming_body_keys() -> None:
    """The two response modes must expose the same result contract.

    The streaming/non-streaming key divergence is what let ``actions`` go missing
    on one path only; pin the shapes together so they cannot drift again.
    """
    from api.nlq.engine import NLQResult
    from api.routers import nlq as nlq_router

    engine = MagicMock()
    engine.run = AsyncMock(return_value=NLQResult(summary="s", entities=[], tools_used=[], actions=[]))
    nlq_router._engine = engine

    response = nlq_router._stream_response("q", None, None)
    events = [event async for event in response.body_iterator]
    kinds = [e.get("event") for e in events]
    streamed_keys = set(json.loads(events[kinds.index("result")]["data"]))

    non_streaming_keys = {"query", "summary", "entities", "tools_used", "actions", "cached"}

    assert streamed_keys == non_streaming_keys
