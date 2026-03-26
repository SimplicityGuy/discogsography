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
