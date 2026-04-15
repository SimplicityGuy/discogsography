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


@pytest.mark.asyncio
async def test_suggestions_endpoint_cache_hit_returns_cached_payload() -> None:
    """When Redis has a cached payload, return it directly without calling build_suggestions."""
    import json

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.nlq.config import NLQConfig
    from api.routers import nlq as nlq_router

    cached_payload = {"suggestions": ["cached suggestion 1", "cached suggestion 2"]}
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=json.dumps(cached_payload))

    nlq_router.configure(NLQConfig(), engine=None, redis=redis, jwt_secret=None)
    app = FastAPI()
    app.include_router(nlq_router.router)

    with TestClient(app) as client:
        response = client.get("/api/nlq/suggestions", params={"pane": "explore"})
        assert response.status_code == 200
        body = response.json()

    assert body == cached_payload
    # setex should NOT be called — we served from cache
    redis.setex.assert_not_awaited()


@pytest.mark.asyncio
async def test_suggestions_endpoint_cache_read_failure_falls_through() -> None:
    """When Redis.get raises, suggestions are still built and returned."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.nlq.config import NLQConfig
    from api.routers import nlq as nlq_router

    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=RuntimeError("Redis down"))
    redis.setex = AsyncMock()

    nlq_router.configure(NLQConfig(), engine=None, redis=redis, jwt_secret=None)
    app = FastAPI()
    app.include_router(nlq_router.router)

    with TestClient(app) as client:
        response = client.get("/api/nlq/suggestions", params={"pane": "explore"})
        assert response.status_code == 200
        body = response.json()

    assert "suggestions" in body
    assert len(body["suggestions"]) >= 4


@pytest.mark.asyncio
async def test_suggestions_endpoint_cache_write_failure_still_returns_payload() -> None:
    """When Redis.setex raises, the response is still returned to the client."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.nlq.config import NLQConfig
    from api.routers import nlq as nlq_router

    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock(side_effect=RuntimeError("Redis down"))

    nlq_router.configure(NLQConfig(), engine=None, redis=redis, jwt_secret=None)
    app = FastAPI()
    app.include_router(nlq_router.router)

    with TestClient(app) as client:
        response = client.get("/api/nlq/suggestions", params={"pane": "explore"})
        assert response.status_code == 200
        body = response.json()

    assert "suggestions" in body


@pytest.mark.asyncio
async def test_extract_user_id_returns_none_when_jwt_secret_is_none() -> None:
    """When _jwt_secret is None, a valid-format Bearer token still yields user_id=None."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.nlq.config import NLQConfig
    from api.nlq.engine import NLQResult
    from api.routers import nlq as nlq_router

    mock_engine = AsyncMock()
    mock_engine.run = AsyncMock(return_value=NLQResult(summary="ok", entities=[], tools_used=[]))

    # Configure with jwt_secret=None so the bearer-token branch returns None early
    nlq_router.configure(NLQConfig(enabled=True, api_key="sk-test"), engine=mock_engine, redis=None, jwt_secret=None)
    app = FastAPI()
    app.include_router(nlq_router.router)

    with TestClient(app) as client:
        response = client.post(
            "/api/nlq/query",
            json={"query": "test"},
            headers={"Authorization": "Bearer some.token.value"},
        )
        assert response.status_code == 200

    # user_id should be None → context.user_id is None
    call_args = mock_engine.run.call_args
    ctx = call_args[0][1]
    assert ctx.user_id is None
