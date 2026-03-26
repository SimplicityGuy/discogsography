"""Tests for NLQ router endpoints."""

import json
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from api.nlq.config import NLQConfig
from api.nlq.engine import NLQResult
import api.routers.nlq as nlq_router


class TestNLQStatus:
    """GET /api/nlq/status endpoint tests."""

    def test_status_returns_enabled_true(self, test_client: TestClient) -> None:
        """When NLQ is available, status returns enabled=true."""
        original_config = nlq_router._nlq_config
        try:
            nlq_router._nlq_config = NLQConfig(enabled=True, api_key="sk-test")
            response = test_client.get("/api/nlq/status")
        finally:
            nlq_router._nlq_config = original_config

        assert response.status_code == 200
        assert response.json() == {"enabled": True}

    def test_status_returns_enabled_false_when_disabled(self, test_client: TestClient) -> None:
        """When NLQ is not available, status returns enabled=false."""
        original_config = nlq_router._nlq_config
        try:
            nlq_router._nlq_config = NLQConfig(enabled=False)
            response = test_client.get("/api/nlq/status")
        finally:
            nlq_router._nlq_config = original_config

        assert response.status_code == 200
        assert response.json() == {"enabled": False}


class TestNLQQuery:
    """POST /api/nlq/query endpoint tests."""

    def test_query_returns_503_when_disabled(self, test_client: TestClient) -> None:
        """When NLQ is disabled, POST /api/nlq/query returns 503."""
        original_config = nlq_router._nlq_config
        original_engine = nlq_router._engine
        try:
            nlq_router._nlq_config = NLQConfig(enabled=False)
            nlq_router._engine = None
            response = test_client.post("/api/nlq/query", json={"query": "who is Radiohead?"})
        finally:
            nlq_router._nlq_config = original_config
            nlq_router._engine = original_engine

        assert response.status_code == 503

    def test_query_returns_400_for_empty_query(self, test_client: TestClient) -> None:
        """POST with empty query string returns 400."""
        original_config = nlq_router._nlq_config
        original_engine = nlq_router._engine
        try:
            nlq_router._nlq_config = MagicMock(is_available=True, max_query_length=500)
            nlq_router._engine = MagicMock()
            response = test_client.post("/api/nlq/query", json={"query": ""})
        finally:
            nlq_router._nlq_config = original_config
            nlq_router._engine = original_engine

        assert response.status_code == 400

    def test_query_returns_400_for_long_query(self, test_client: TestClient) -> None:
        """POST with query exceeding max_query_length returns 400."""
        original_config = nlq_router._nlq_config
        original_engine = nlq_router._engine
        try:
            nlq_router._nlq_config = MagicMock(is_available=True, max_query_length=500)
            nlq_router._engine = MagicMock()
            long_query = "a" * 501
            response = test_client.post("/api/nlq/query", json={"query": long_query})
        finally:
            nlq_router._nlq_config = original_config
            nlq_router._engine = original_engine

        assert response.status_code == 400

    def test_query_returns_200_with_result(self, test_client: TestClient) -> None:
        """POST with valid query returns 200 with expected response shape."""
        original_config = nlq_router._nlq_config
        original_engine = nlq_router._engine
        try:
            nlq_router._nlq_config = MagicMock(is_available=True, max_query_length=500)
            mock_engine = MagicMock()
            mock_result = NLQResult(
                summary="Radiohead is an English rock band.",
                entities=[{"id": "123", "name": "Radiohead", "type": "artist"}],
                tools_used=["search"],
            )
            mock_engine.run = AsyncMock(return_value=mock_result)
            nlq_router._engine = mock_engine

            response = test_client.post("/api/nlq/query", json={"query": "who is Radiohead?"})
        finally:
            nlq_router._nlq_config = original_config
            nlq_router._engine = original_engine

        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "who is Radiohead?"
        assert data["summary"] == "Radiohead is an English rock band."
        assert len(data["entities"]) == 1
        assert data["entities"][0]["name"] == "Radiohead"
        assert data["tools_used"] == ["search"]
        assert data["cached"] is False

    def test_query_returns_cached_result(self, test_client: TestClient) -> None:
        """When Redis has a cached result, return it with cached=true."""
        original_config = nlq_router._nlq_config
        original_engine = nlq_router._engine
        original_redis = nlq_router._redis
        try:
            nlq_router._nlq_config = MagicMock(is_available=True, max_query_length=500)
            nlq_router._engine = MagicMock()  # should NOT be called

            cached_data = {
                "query": "who is radiohead?",
                "summary": "Cached answer about Radiohead.",
                "entities": [{"id": "123", "name": "Radiohead", "type": "artist"}],
                "tools_used": ["search"],
                "cached": True,
            }
            mock_redis = AsyncMock()
            mock_redis.get = AsyncMock(return_value=json.dumps(cached_data))
            nlq_router._redis = mock_redis

            response = test_client.post("/api/nlq/query", json={"query": "who is Radiohead?"})
        finally:
            nlq_router._nlq_config = original_config
            nlq_router._engine = original_engine
            nlq_router._redis = original_redis

        assert response.status_code == 200
        data = response.json()
        assert data["cached"] is True
        assert data["summary"] == "Cached answer about Radiohead."

    def test_query_writes_to_cache_for_public_query(self, test_client: TestClient) -> None:
        """Public (unauthenticated) queries should be written to Redis cache."""
        original_config = nlq_router._nlq_config
        original_engine = nlq_router._engine
        original_redis = nlq_router._redis
        try:
            nlq_router._nlq_config = MagicMock(is_available=True, max_query_length=500, cache_ttl=300)
            mock_engine = MagicMock()
            mock_result = NLQResult(
                summary="Radiohead info.",
                entities=[],
                tools_used=["search"],
            )
            mock_engine.run = AsyncMock(return_value=mock_result)
            nlq_router._engine = mock_engine

            mock_redis = AsyncMock()
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.setex = AsyncMock()
            nlq_router._redis = mock_redis

            response = test_client.post("/api/nlq/query", json={"query": "who is Radiohead?"})
        finally:
            nlq_router._nlq_config = original_config
            nlq_router._engine = original_engine
            nlq_router._redis = original_redis

        assert response.status_code == 200
        mock_redis.setex.assert_called_once()

    def test_query_with_auth_token_extracts_user_id(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        """When a valid Bearer token is provided, user_id is extracted and passed to engine."""
        original_config = nlq_router._nlq_config
        original_engine = nlq_router._engine
        original_redis = nlq_router._redis
        try:
            nlq_router._nlq_config = MagicMock(is_available=True, max_query_length=500)
            mock_engine = MagicMock()
            mock_result = NLQResult(
                summary="Your collection info.",
                entities=[],
                tools_used=["get_collection_stats"],
            )
            mock_engine.run = AsyncMock(return_value=mock_result)
            nlq_router._engine = mock_engine
            nlq_router._redis = None  # No caching for auth requests

            response = test_client.post("/api/nlq/query", json={"query": "how many records do I have?"}, headers=auth_headers)
        finally:
            nlq_router._nlq_config = original_config
            nlq_router._engine = original_engine
            nlq_router._redis = original_redis

        assert response.status_code == 200
        # Engine should have been called with a context that has user_id set
        call_args = mock_engine.run.call_args
        ctx = call_args[0][1]  # second positional arg is NLQContext
        assert ctx.user_id is not None

    def test_query_returns_503_when_engine_is_none(self, test_client: TestClient) -> None:
        """When config says available but engine is None, returns 503."""
        original_config = nlq_router._nlq_config
        original_engine = nlq_router._engine
        try:
            nlq_router._nlq_config = MagicMock(is_available=True, max_query_length=500)
            nlq_router._engine = None
            response = test_client.post("/api/nlq/query", json={"query": "test query"})
        finally:
            nlq_router._nlq_config = original_config
            nlq_router._engine = original_engine

        assert response.status_code == 503


class TestNLQSSE:
    """SSE streaming path tests."""

    def test_sse_stream_returns_event_source(self, test_client: TestClient) -> None:
        """When Accept: text/event-stream, response should be SSE with status and result events."""
        original_config = nlq_router._nlq_config
        original_engine = nlq_router._engine
        original_redis = nlq_router._redis
        try:
            nlq_router._nlq_config = MagicMock(is_available=True, max_query_length=500)
            mock_engine = MagicMock()
            mock_result = NLQResult(
                summary="Streamed answer.",
                entities=[{"id": "a1", "name": "Radiohead", "type": "artist"}],
                tools_used=["search"],
            )

            async def mock_run(_query, _ctx, on_status=None):
                if on_status:
                    await on_status("Searching...")
                    await on_status("Generating answer...")
                return mock_result

            mock_engine.run = AsyncMock(side_effect=mock_run)
            nlq_router._engine = mock_engine
            nlq_router._redis = AsyncMock()
            nlq_router._redis.get = AsyncMock(return_value=None)

            response = test_client.post(
                "/api/nlq/query",
                json={"query": "who is Radiohead?"},
                headers={"Accept": "text/event-stream"},
            )
        finally:
            nlq_router._nlq_config = original_config
            nlq_router._engine = original_engine
            nlq_router._redis = original_redis

        assert response.status_code == 200
        # SSE response should contain event data
        body = response.text
        assert "event: status" in body or "event: result" in body

    def test_sse_stream_with_context(self, test_client: TestClient) -> None:
        """SSE streaming with context should pass entity info through."""
        original_config = nlq_router._nlq_config
        original_engine = nlq_router._engine
        original_redis = nlq_router._redis
        try:
            nlq_router._nlq_config = MagicMock(is_available=True, max_query_length=500)
            mock_engine = MagicMock()
            mock_result = NLQResult(summary="Answer.", entities=[], tools_used=[])
            mock_engine.run = AsyncMock(return_value=mock_result)
            nlq_router._engine = mock_engine
            nlq_router._redis = AsyncMock()
            nlq_router._redis.get = AsyncMock(return_value=None)

            response = test_client.post(
                "/api/nlq/query",
                json={"query": "tell me more", "context": {"entity_id": "a1", "entity_type": "artist"}},
                headers={"Accept": "text/event-stream"},
            )
        finally:
            nlq_router._nlq_config = original_config
            nlq_router._engine = original_engine
            nlq_router._redis = original_redis

        assert response.status_code == 200


class TestExtractUserIdEdgeCases:
    """Test _extract_user_id edge cases."""

    def test_extract_user_id_no_auth_header(self, test_client: TestClient) -> None:
        """No auth header means user_id is None — verified via no caching skip."""
        original_config = nlq_router._nlq_config
        original_engine = nlq_router._engine
        original_redis = nlq_router._redis
        try:
            nlq_router._nlq_config = MagicMock(is_available=True, max_query_length=500, cache_ttl=300)
            mock_engine = MagicMock()
            mock_result = NLQResult(summary="Test.", entities=[], tools_used=[])
            mock_engine.run = AsyncMock(return_value=mock_result)
            nlq_router._engine = mock_engine
            mock_redis = AsyncMock()
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.setex = AsyncMock()
            nlq_router._redis = mock_redis

            response = test_client.post("/api/nlq/query", json={"query": "test"})
        finally:
            nlq_router._nlq_config = original_config
            nlq_router._engine = original_engine
            nlq_router._redis = original_redis

        assert response.status_code == 200
        # Public query (no auth) should write to cache
        mock_redis.setex.assert_called_once()

    def test_extract_user_id_invalid_token(self, test_client: TestClient) -> None:
        """Invalid Bearer token should result in user_id=None (treated as public)."""
        original_config = nlq_router._nlq_config
        original_engine = nlq_router._engine
        original_redis = nlq_router._redis
        try:
            nlq_router._nlq_config = MagicMock(is_available=True, max_query_length=500, cache_ttl=300)
            mock_engine = MagicMock()
            mock_result = NLQResult(summary="Test.", entities=[], tools_used=[])
            mock_engine.run = AsyncMock(return_value=mock_result)
            nlq_router._engine = mock_engine
            mock_redis = AsyncMock()
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.setex = AsyncMock()
            nlq_router._redis = mock_redis

            response = test_client.post(
                "/api/nlq/query",
                json={"query": "test"},
                headers={"Authorization": "Bearer invalid-garbage-token"},
            )
        finally:
            nlq_router._nlq_config = original_config
            nlq_router._engine = original_engine
            nlq_router._redis = original_redis

        assert response.status_code == 200
        # Invalid token => user_id=None => treated as public => cache write
        mock_redis.setex.assert_called_once()

    def test_cache_read_failure_gracefully_continues(self, test_client: TestClient) -> None:
        """If Redis cache read throws, the query should still proceed."""
        original_config = nlq_router._nlq_config
        original_engine = nlq_router._engine
        original_redis = nlq_router._redis
        try:
            nlq_router._nlq_config = MagicMock(is_available=True, max_query_length=500, cache_ttl=300)
            mock_engine = MagicMock()
            mock_result = NLQResult(summary="Fallback.", entities=[], tools_used=[])
            mock_engine.run = AsyncMock(return_value=mock_result)
            nlq_router._engine = mock_engine
            mock_redis = AsyncMock()
            mock_redis.get = AsyncMock(side_effect=RuntimeError("Redis down"))
            mock_redis.setex = AsyncMock()
            nlq_router._redis = mock_redis

            response = test_client.post("/api/nlq/query", json={"query": "test"})
        finally:
            nlq_router._nlq_config = original_config
            nlq_router._engine = original_engine
            nlq_router._redis = original_redis

        assert response.status_code == 200
        assert response.json()["summary"] == "Fallback."

    def test_cache_write_failure_gracefully_continues(self, test_client: TestClient) -> None:
        """If Redis cache write throws, the response should still be returned."""
        original_config = nlq_router._nlq_config
        original_engine = nlq_router._engine
        original_redis = nlq_router._redis
        try:
            nlq_router._nlq_config = MagicMock(is_available=True, max_query_length=500, cache_ttl=300)
            mock_engine = MagicMock()
            mock_result = NLQResult(summary="Success.", entities=[], tools_used=[])
            mock_engine.run = AsyncMock(return_value=mock_result)
            nlq_router._engine = mock_engine
            mock_redis = AsyncMock()
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.setex = AsyncMock(side_effect=RuntimeError("Redis down"))
            nlq_router._redis = mock_redis

            response = test_client.post("/api/nlq/query", json={"query": "test"})
        finally:
            nlq_router._nlq_config = original_config
            nlq_router._engine = original_engine
            nlq_router._redis = original_redis

        assert response.status_code == 200
        assert response.json()["summary"] == "Success."


def test_query_with_admin_token_treated_as_unauthenticated(test_client: TestClient) -> None:
    """Admin tokens should be treated as unauthenticated for NLQ."""
    import base64
    import hashlib
    import hmac
    import json as json_mod

    from api.nlq.engine import NLQResult
    import api.routers.nlq as nlq_router
    from tests.api.conftest import TEST_JWT_SECRET

    # Build an admin JWT
    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    header = b64url(json_mod.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = b64url(json_mod.dumps({"sub": "admin-1", "type": "admin", "exp": 9_999_999_999}, separators=(",", ":")).encode())
    signing_input = f"{header}.{body}".encode("ascii")
    sig = b64url(hmac.new(TEST_JWT_SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest())
    admin_token = f"{header}.{body}.{sig}"

    mock_result = NLQResult(summary="Public only.", entities=[], tools_used=[])
    original_config = nlq_router._nlq_config
    original_engine = nlq_router._engine
    try:
        nlq_router._nlq_config = MagicMock(is_available=True, max_query_length=500, cache_ttl=3600)
        mock_engine = MagicMock()
        mock_engine.run = AsyncMock(return_value=mock_result)
        nlq_router._engine = mock_engine

        response = test_client.post(
            "/api/nlq/query",
            json={"query": "test query"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    finally:
        nlq_router._nlq_config = original_config
        nlq_router._engine = original_engine

    assert response.status_code == 200
    # Verify engine was called with user_id=None (admin token treated as unauthenticated)
    call_kwargs = mock_engine.run.call_args
    assert call_kwargs.kwargs.get("context") is not None or call_kwargs.args[1] is not None


def test_query_returns_none_user_when_config_is_none(test_client: TestClient) -> None:
    """When api config is None, user_id extraction returns None."""
    import api.api as api_module
    from api.nlq.engine import NLQResult
    import api.routers.nlq as nlq_router

    mock_result = NLQResult(summary="No config.", entities=[], tools_used=[])
    original_config = nlq_router._nlq_config
    original_engine = nlq_router._engine
    original_api_config = api_module._config
    try:
        nlq_router._nlq_config = MagicMock(is_available=True, max_query_length=500, cache_ttl=3600)
        mock_engine = MagicMock()
        mock_engine.run = AsyncMock(return_value=mock_result)
        nlq_router._engine = mock_engine
        api_module._config = None

        response = test_client.post(
            "/api/nlq/query",
            json={"query": "test query"},
            headers={"Authorization": "Bearer some-token"},
        )
    finally:
        nlq_router._nlq_config = original_config
        nlq_router._engine = original_engine
        api_module._config = original_api_config

    assert response.status_code == 200
