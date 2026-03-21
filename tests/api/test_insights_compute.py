"""Tests for the insights compute router — data-completeness caching."""

import json
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


class TestDataCompletenessCache:
    """Tests for Redis caching on /api/internal/insights/data-completeness."""

    def test_cache_hit_returns_cached(self, test_client: TestClient, mock_redis: AsyncMock) -> None:
        """Cache hit returns cached data without querying PostgreSQL."""
        cached = {"items": [{"entity_type": "artists", "total_count": 100}]}
        mock_redis.get = AsyncMock(return_value=json.dumps(cached))

        with patch("api.routers.insights_compute.query_data_completeness") as mock_query:
            response = test_client.get("/api/internal/insights/data-completeness")

        assert response.status_code == 200
        assert response.json() == cached
        mock_query.assert_not_called()

    def test_cache_miss_queries_and_caches(self, test_client: TestClient, mock_redis: AsyncMock) -> None:
        """Cache miss queries PostgreSQL and stores result in Redis."""
        mock_redis.get = AsyncMock(return_value=None)
        items = [{"entity_type": "artists", "total_count": 500, "completeness_pct": 85.0}]

        with patch("api.routers.insights_compute.query_data_completeness", new_callable=AsyncMock, return_value=items):
            response = test_client.get("/api/internal/insights/data-completeness")

        assert response.status_code == 200
        assert response.json() == {"items": items}
        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args[0]
        assert call_args[0] == "insights:data-completeness"
        assert call_args[1] == 21600  # 6h TTL

    def test_cache_get_failure_falls_through(self, test_client: TestClient, mock_redis: AsyncMock) -> None:
        """Redis get failure falls through to PostgreSQL query."""
        mock_redis.get = AsyncMock(side_effect=Exception("connection lost"))
        items = [{"entity_type": "labels", "total_count": 200}]

        with patch("api.routers.insights_compute.query_data_completeness", new_callable=AsyncMock, return_value=items):
            response = test_client.get("/api/internal/insights/data-completeness")

        assert response.status_code == 200
        assert response.json() == {"items": items}

    def test_cache_set_failure_still_returns(self, test_client: TestClient, mock_redis: AsyncMock) -> None:
        """Redis set failure does not prevent response."""
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock(side_effect=Exception("write failed"))
        items = [{"entity_type": "masters", "total_count": 300}]

        with patch("api.routers.insights_compute.query_data_completeness", new_callable=AsyncMock, return_value=items):
            response = test_client.get("/api/internal/insights/data-completeness")

        assert response.status_code == 200
        assert response.json() == {"items": items}


class TestDataCompletenessNoRedis:
    """Tests for data-completeness when Redis is not configured."""

    def test_no_redis_queries_directly(self, test_client: TestClient) -> None:
        """When Redis is None, queries PostgreSQL directly."""
        import api.routers.insights_compute as mod

        original_redis = mod._redis
        mod._redis = None
        try:
            items = [{"entity_type": "releases", "total_count": 1000}]
            with patch("api.routers.insights_compute.query_data_completeness", new_callable=AsyncMock, return_value=items):
                response = test_client.get("/api/internal/insights/data-completeness")
            assert response.status_code == 200
            assert response.json() == {"items": items}
        finally:
            mod._redis = original_redis


class TestDataCompletenessNotReady:
    """Test 503 when pool is not configured."""

    def test_pool_not_ready(self, test_client: TestClient) -> None:
        """Returns 503 when _pool is None."""
        import api.routers.insights_compute as mod

        original = mod._pool
        mod._pool = None
        try:
            response = test_client.get("/api/internal/insights/data-completeness")
            assert response.status_code == 503
        finally:
            mod._pool = original


class TestConfigureWithRedis:
    """Test configure() accepts redis parameter."""

    def test_configure_sets_redis(self) -> None:
        """configure() stores redis reference."""
        import api.routers.insights_compute as mod

        original = mod._redis
        mock = AsyncMock()
        try:
            mod.configure(AsyncMock(), AsyncMock(), redis=mock)
            assert mod._redis is mock
        finally:
            mod._redis = original

    def test_configure_without_redis(self) -> None:
        """configure() without redis sets _redis to None."""
        import api.routers.insights_compute as mod

        original = mod._redis
        try:
            mod.configure(AsyncMock(), AsyncMock())
            assert mod._redis is None
        finally:
            mod._redis = original
