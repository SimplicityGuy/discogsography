"""Tests for insights FastAPI endpoints."""

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
import pytest


class TestHealthEndpoint:
    def test_health_returns_200(self, test_client: TestClient) -> None:
        response = test_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "insights"
        assert "status" in data


class TestTopArtistsEndpoint:
    def test_returns_200(self, test_client: TestClient) -> None:
        response = test_client.get("/api/insights/top-artists")
        assert response.status_code == 200

    def test_with_limit(self, test_client: TestClient) -> None:
        response = test_client.get("/api/insights/top-artists?limit=10")
        assert response.status_code == 200


class TestGenreTrendsEndpoint:
    def test_requires_genre_param(self, test_client: TestClient) -> None:
        response = test_client.get("/api/insights/genre-trends")
        assert response.status_code == 422

    def test_returns_200_with_genre(self, test_client: TestClient) -> None:
        response = test_client.get("/api/insights/genre-trends?genre=Jazz")
        assert response.status_code == 200


class TestLabelLongevityEndpoint:
    def test_returns_200(self, test_client: TestClient) -> None:
        response = test_client.get("/api/insights/label-longevity")
        assert response.status_code == 200


class TestThisMonthEndpoint:
    def test_returns_200(self, test_client: TestClient) -> None:
        response = test_client.get("/api/insights/this-month")
        assert response.status_code == 200


class TestDataCompletenessEndpoint:
    def test_returns_200(self, test_client: TestClient) -> None:
        response = test_client.get("/api/insights/data-completeness")
        assert response.status_code == 200


class TestComputationStatusEndpoint:
    def test_returns_200(self, test_client: TestClient) -> None:
        response = test_client.get("/api/insights/status")
        assert response.status_code == 200

    def test_never_run_status_when_no_log_rows(self, test_client: TestClient) -> None:
        """When fetchone returns None for an insight type, status should be 'never_run'."""
        response = test_client.get("/api/insights/status")
        assert response.status_code == 200
        data = response.json()
        assert "statuses" in data
        # All 5 insight types should show 'never_run' since fetchone returns None
        assert len(data["statuses"]) == 5
        for status in data["statuses"]:
            assert status["status"] == "never_run"

    def test_status_with_log_rows(self, mock_http_client: AsyncMock, mock_pg_pool: AsyncMock) -> None:
        """When fetchone returns a row, status should reflect actual log data."""
        import insights.insights as _module

        # Return a row with a real datetime for completed_at to verify serialization
        from datetime import datetime, timezone

        mock_cursor = mock_pg_pool.connection.return_value.__aenter__.return_value.cursor.return_value.__aenter__.return_value
        mock_cursor.fetchone = AsyncMock(return_value=("artist_centrality", "completed", datetime(2026, 3, 18, 12, 0, 0, tzinfo=timezone.utc), 1500))

        _module._http_client = mock_http_client
        _module._pool = mock_pg_pool
        _module._cache = None

        from insights.insights import app

        client = TestClient(app)
        response = client.get("/api/insights/status")
        assert response.status_code == 200
        data = response.json()
        assert "statuses" in data
        # Each status should have "completed"
        for status in data["statuses"]:
            assert status["status"] == "completed"


# ============================================================
# Cache integration tests
# ============================================================


class TestTopArtistsCacheIntegration:
    def test_cache_miss_queries_pg_and_stores(
        self,
        test_client_with_cache: TestClient,
        mock_cache: AsyncMock,
    ) -> None:
        mock_cache.get.return_value = None
        response = test_client_with_cache.get("/api/insights/top-artists?limit=10")
        assert response.status_code == 200
        mock_cache.get.assert_called_once_with("insights:top-artists:10")
        mock_cache.set.assert_called_once()
        key = mock_cache.set.call_args[0][0]
        assert key == "insights:top-artists:10"

    def test_cache_hit_returns_cached_data(
        self,
        test_client_with_cache: TestClient,
        mock_cache: AsyncMock,
    ) -> None:
        cached = {"metric": "centrality", "items": [{"rank": 1, "artist_name": "Test"}], "count": 1}
        mock_cache.get.return_value = cached
        response = test_client_with_cache.get("/api/insights/top-artists?limit=10")
        assert response.status_code == 200
        assert response.json() == cached
        mock_cache.set.assert_not_called()


class TestGenreTrendsCacheIntegration:
    def test_cache_miss_queries_pg_and_stores(
        self,
        test_client_with_cache: TestClient,
        mock_cache: AsyncMock,
    ) -> None:
        mock_cache.get.return_value = None
        response = test_client_with_cache.get("/api/insights/genre-trends?genre=Rock")
        assert response.status_code == 200
        mock_cache.get.assert_called_once_with("insights:genre-trends:Rock")
        mock_cache.set.assert_called_once()

    def test_cache_hit_returns_cached_data(
        self,
        test_client_with_cache: TestClient,
        mock_cache: AsyncMock,
    ) -> None:
        cached = {"genre": "Rock", "trends": [], "peak_decade": None}
        mock_cache.get.return_value = cached
        response = test_client_with_cache.get("/api/insights/genre-trends?genre=Rock")
        assert response.status_code == 200
        assert response.json() == cached
        mock_cache.set.assert_not_called()


class TestLabelLongevityCacheIntegration:
    def test_cache_miss_queries_pg_and_stores(
        self,
        test_client_with_cache: TestClient,
        mock_cache: AsyncMock,
    ) -> None:
        mock_cache.get.return_value = None
        response = test_client_with_cache.get("/api/insights/label-longevity?limit=10")
        assert response.status_code == 200
        mock_cache.get.assert_called_once_with("insights:label-longevity:10")
        mock_cache.set.assert_called_once()

    def test_cache_hit_returns_cached_data(
        self,
        test_client_with_cache: TestClient,
        mock_cache: AsyncMock,
    ) -> None:
        cached = {"items": [], "count": 0}
        mock_cache.get.return_value = cached
        response = test_client_with_cache.get("/api/insights/label-longevity?limit=10")
        assert response.status_code == 200
        assert response.json() == cached
        mock_cache.set.assert_not_called()


class TestThisMonthCacheIntegration:
    def test_cache_miss_queries_pg_and_stores(
        self,
        test_client_with_cache: TestClient,
        mock_cache: AsyncMock,
    ) -> None:
        mock_cache.get.return_value = None
        response = test_client_with_cache.get("/api/insights/this-month")
        assert response.status_code == 200
        # Cache key includes year-month
        call_key = mock_cache.get.call_args[0][0]
        assert call_key.startswith("insights:this-month:")
        mock_cache.set.assert_called_once()

    def test_cache_hit_returns_cached_data(
        self,
        test_client_with_cache: TestClient,
        mock_cache: AsyncMock,
    ) -> None:
        cached = {"month": 3, "year": 2026, "items": [], "count": 0}
        mock_cache.get.return_value = cached
        response = test_client_with_cache.get("/api/insights/this-month")
        assert response.status_code == 200
        assert response.json() == cached
        mock_cache.set.assert_not_called()


class TestDataCompletenessCacheIntegration:
    def test_cache_miss_queries_pg_and_stores(
        self,
        test_client_with_cache: TestClient,
        mock_cache: AsyncMock,
    ) -> None:
        mock_cache.get.return_value = None
        response = test_client_with_cache.get("/api/insights/data-completeness")
        assert response.status_code == 200
        mock_cache.get.assert_called_once_with("insights:data-completeness")
        mock_cache.set.assert_called_once()

    def test_cache_hit_returns_cached_data(
        self,
        test_client_with_cache: TestClient,
        mock_cache: AsyncMock,
    ) -> None:
        cached = {"items": [], "count": 0}
        mock_cache.get.return_value = cached
        response = test_client_with_cache.get("/api/insights/data-completeness")
        assert response.status_code == 200
        assert response.json() == cached
        mock_cache.set.assert_not_called()


class TestStatusEndpointNeverCached:
    def test_status_does_not_use_cache(
        self,
        test_client_with_cache: TestClient,
        mock_cache: AsyncMock,
    ) -> None:
        response = test_client_with_cache.get("/api/insights/status")
        assert response.status_code == 200
        mock_cache.get.assert_not_called()
        mock_cache.set.assert_not_called()


# ============================================================
# 503 "not ready" responses when _pool is None
# ============================================================


@pytest.fixture
def test_client_no_pool() -> TestClient:
    """Create a test client with _pool set to None (service not ready)."""
    import insights.insights as _module

    _module._pool = None
    _module._cache = None

    from insights.insights import app

    return TestClient(app)


class TestServiceNotReadyResponses:
    """All data endpoints must return 503 when the pool is not initialized."""

    def test_top_artists_503_when_no_pool(self, test_client_no_pool: TestClient) -> None:
        response = test_client_no_pool.get("/api/insights/top-artists")
        assert response.status_code == 503
        assert "error" in response.json()

    def test_genre_trends_503_when_no_pool(self, test_client_no_pool: TestClient) -> None:
        response = test_client_no_pool.get("/api/insights/genre-trends?genre=Rock")
        assert response.status_code == 503
        assert "error" in response.json()

    def test_label_longevity_503_when_no_pool(self, test_client_no_pool: TestClient) -> None:
        response = test_client_no_pool.get("/api/insights/label-longevity")
        assert response.status_code == 503
        assert "error" in response.json()

    def test_this_month_503_when_no_pool(self, test_client_no_pool: TestClient) -> None:
        response = test_client_no_pool.get("/api/insights/this-month")
        assert response.status_code == 503
        assert "error" in response.json()

    def test_data_completeness_503_when_no_pool(self, test_client_no_pool: TestClient) -> None:
        response = test_client_no_pool.get("/api/insights/data-completeness")
        assert response.status_code == 503
        assert "error" in response.json()

    def test_status_503_when_no_pool(self, test_client_no_pool: TestClient) -> None:
        response = test_client_no_pool.get("/api/insights/status")
        assert response.status_code == 503
        assert "error" in response.json()
