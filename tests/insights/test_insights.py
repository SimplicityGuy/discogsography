"""Tests for insights FastAPI endpoints."""

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient


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
