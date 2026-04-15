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
