"""Tests for GET /api/nlq/suggestions."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_suggestions_endpoint_returns_chips() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.nlq.config import NLQConfig
    from api.routers import nlq as nlq_router

    nlq_router.configure(NLQConfig(), engine=None, redis=None, jwt_secret=None)
    app = FastAPI()
    app.include_router(nlq_router.router)

    with TestClient(app) as client:
        response = client.get("/api/nlq/suggestions", params={"pane": "explore"})
        assert response.status_code == 200
        body = response.json()
        assert "suggestions" in body
        assert len(body["suggestions"]) >= 4


@pytest.mark.asyncio
async def test_suggestions_endpoint_uses_redis_cache() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.nlq.config import NLQConfig
    from api.routers import nlq as nlq_router

    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock()

    nlq_router.configure(NLQConfig(), engine=None, redis=redis, jwt_secret=None)
    app = FastAPI()
    app.include_router(nlq_router.router)

    with TestClient(app) as client:
        response = client.get("/api/nlq/suggestions", params={"pane": "explore", "focus": "Kraftwerk", "focus_type": "artist"})
        assert response.status_code == 200

    redis.get.assert_awaited_once()
    redis.setex.assert_awaited_once()
    args = redis.setex.call_args.args
    assert 300 in args  # TTL is 5 minutes
