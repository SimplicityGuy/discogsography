"""Tests for the /api/digger/recommend SSE endpoint."""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
from unittest.mock import AsyncMock, patch
import uuid

import fakeredis.aioredis as aioredis_fake
from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from api.digger_refresh.coordinator import RefreshCoordinator
from api.queries.digger_queries import UserDiggerSettings
from common.digger_optimizer.models import Listing, OptimizerInput, ReleaseConstraint, Seller


def _enabled_settings() -> UserDiggerSettings:
    return UserDiggerSettings(
        user_id=uuid.uuid4(),
        enabled=True,
        country_code="US",
        currency="USD",
        scheduled_cadence="off",
        preferred_model="sonnet",
        daily_token_cap_interactive=200_000,
        daily_token_cap_scheduled=100_000,
    )


def _sample_input() -> OptimizerInput:
    return OptimizerInput(
        user_id=uuid.uuid4(),
        location="US",
        currency="USD",
        must_have_releases=[ReleaseConstraint(release_id=1, min_media_condition="VG", min_sleeve_condition="VG")],
        candidate_listings=[
            Listing(
                listing_id=101,
                release_id=1,
                seller_id=1,
                price_value=Decimal("5"),
                price_currency="USD",
                media_condition="NM",
                sleeve_condition="NM",
            )
        ],
        sellers={1: Seller(seller_id=1, region="us", country_code="US")},
    )


def test_recommend_requires_auth(test_client: TestClient) -> None:
    r = test_client.post("/api/digger/recommend", json={"deadline_seconds": 5})
    assert r.status_code == 401


def test_recommend_streams_result_when_no_stale(test_client: TestClient, auth_headers: dict[str, str]) -> None:
    with (
        patch("api.routers.digger_recommend.q.get_user_settings", AsyncMock(return_value=_enabled_settings())),
        patch("api.routers.digger_recommend._identify_stale", AsyncMock(return_value=[])),
        patch("api.routers.digger_recommend.build_optimizer_input", AsyncMock(return_value=_sample_input())),
    ):
        r = test_client.post("/api/digger/recommend", headers=auth_headers, json={"deadline_seconds": 5})
    assert r.status_code == 200
    assert "event: refresh_started" in r.text
    assert "event: result" in r.text
    assert "event: done" in r.text


def test_recommend_emits_error_when_not_enabled(test_client: TestClient, auth_headers: dict[str, str]) -> None:
    with patch("api.routers.digger_recommend.q.get_user_settings", AsyncMock(return_value=None)):
        r = test_client.post("/api/digger/recommend", headers=auth_headers, json={"deadline_seconds": 5})
    assert r.status_code == 200
    assert "event: error" in r.text
    assert "digger not enabled" in r.text


def test_recommend_streams_refresh_progress_when_stale(test_client: TestClient, auth_headers: dict[str, str]) -> None:
    async def fake_events(*_args: object, **_kwargs: object):
        yield {"event": "refresh_progress", "data": json.dumps({"release_id": 1})}

    with (
        patch("api.routers.digger_recommend.q.get_user_settings", AsyncMock(return_value=_enabled_settings())),
        patch("api.routers.digger_recommend._identify_stale", AsyncMock(return_value=[1])),
        patch("api.routers.digger_recommend._refresh_progress_events", fake_events),
        patch("api.routers.digger_recommend.build_optimizer_input", AsyncMock(return_value=_sample_input())),
    ):
        r = test_client.post("/api/digger/recommend", headers=auth_headers, json={"deadline_seconds": 5})
    assert r.status_code == 200
    assert "event: refresh_progress" in r.text
    assert "event: result" in r.text


@pytest.mark.asyncio
async def test_identify_stale_flags_old_and_unscraped(mock_pool: object, mock_cur: AsyncMock) -> None:
    from api.routers.digger_recommend import _identify_stale

    now = datetime.now(UTC)
    mock_cur.fetchall = AsyncMock(
        return_value=[
            {"release_id": 1, "tier": "must", "last_scraped_at": None},  # never scraped -> stale
            {"release_id": 2, "tier": "must", "last_scraped_at": now - timedelta(days=10)},  # old -> stale
            {"release_id": 3, "tier": "eventually", "last_scraped_at": now - timedelta(days=1)},  # fresh -> not stale
        ]
    )
    stale = await _identify_stale(mock_pool, uuid.uuid4())
    assert set(stale) == {1, 2}


@pytest.mark.asyncio
async def test_refresh_progress_events_empty_when_no_stale() -> None:
    from api.routers.digger_recommend import _refresh_progress_events

    coord = RefreshCoordinator(pool=None, redis=AsyncMock())
    out = [e async for e in _refresh_progress_events(coord, uuid.uuid4(), [], deadline_seconds=1)]
    assert out == []


@pytest.mark.asyncio
async def test_refresh_progress_events_streams_then_stops(mock_pool: object, mock_cur: AsyncMock) -> None:
    from api.routers.digger_recommend import _refresh_progress_events

    mock_cur.rowcount = 1
    redis = aioredis_fake.FakeRedis(decode_responses=True)
    coord = RefreshCoordinator(pool=mock_pool, redis=redis)
    uid = uuid.uuid4()
    out: list[dict[str, str]] = []

    async def run() -> None:
        async for evt in _refresh_progress_events(coord, uid, [1], deadline_seconds=2):
            out.append(evt)

    task = asyncio.create_task(run())
    await asyncio.sleep(0.2)
    await redis.publish(f"digger:refresh:{uid}", json.dumps({"release_id": 1, "status": "ok"}))
    await asyncio.wait_for(task, timeout=3)
    assert out and out[0]["event"] == "refresh_progress"
    await redis.aclose()


def test_get_pool_and_redis_raise_when_unconfigured() -> None:
    import api.routers.digger_recommend as mod

    saved_pool, saved_redis = mod._pool, mod._redis
    mod._pool = None
    mod._redis = None
    try:
        with pytest.raises(HTTPException):
            mod._get_pool()
        with pytest.raises(HTTPException):
            mod._get_redis()
    finally:
        mod._pool, mod._redis = saved_pool, saved_redis
