"""Tests for the digger opportunistic-refresh coordinator."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import fakeredis.aioredis as aioredis_fake
import pytest

from api.digger_refresh.coordinator import RefreshCoordinator


@pytest.mark.asyncio
async def test_bump_priorities_updates_due_time(mock_pool: object, mock_cur: AsyncMock) -> None:
    mock_cur.rowcount = 2
    coord = RefreshCoordinator(pool=mock_pool, redis=AsyncMock())
    updated = await coord.bump_priorities([1, 2])
    assert updated == 2
    sql = mock_cur.execute.await_args.args[0]
    assert "next_scrape_due_at = now()" in sql
    assert mock_cur.execute.await_args.args[1] == ([1, 2],)


@pytest.mark.asyncio
async def test_bump_priorities_noop_for_empty(mock_pool: object) -> None:
    coord = RefreshCoordinator(pool=mock_pool, redis=AsyncMock())
    assert await coord.bump_priorities([]) == 0


@pytest.mark.asyncio
async def test_subscribe_progress_yields_published_events() -> None:
    redis = aioredis_fake.FakeRedis(decode_responses=True)
    coord = RefreshCoordinator(pool=None, redis=redis)
    user_id = "00000000-0000-0000-0000-000000000001"
    events: list[dict[str, object]] = []

    async def consume() -> None:
        async for ev in coord.subscribe_progress(user_id, deadline_seconds=2):
            events.append(ev)
            break

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.2)  # let the subscriber attach before publishing
    await redis.publish(f"digger:refresh:{user_id}", json.dumps({"release_id": 1, "status": "ok", "eta_seconds_remaining": 0}))
    await asyncio.wait_for(task, timeout=3)

    assert any(e["release_id"] == 1 for e in events)
    await redis.aclose()
