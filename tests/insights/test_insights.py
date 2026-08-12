"""Tests for insights FastAPI endpoints."""

import asyncio
from datetime import UTC
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
import pytest

from tests.insights.conftest import TEST_CACHE_GENERATION


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
        # All 7 insight types should show 'never_run' since fetchone returns None (includes community_enrichment)
        assert len(data["statuses"]) == 7
        for status in data["statuses"]:
            assert status["status"] == "never_run"

    def test_status_with_log_rows(self, mock_http_client: AsyncMock, mock_pg_pool: AsyncMock) -> None:
        """When fetchone returns a row, status should reflect actual log data."""
        # Return a row with a real datetime for completed_at to verify serialization
        from datetime import datetime

        import insights.insights as _module

        mock_cursor = mock_pg_pool.connection.return_value.__aenter__.return_value.cursor.return_value.__aenter__.return_value
        mock_cursor.fetchone = AsyncMock(return_value=("artist_centrality", "completed", datetime(2026, 3, 18, 12, 0, 0, tzinfo=UTC), 1500))

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
        mock_cache.get.assert_called_once_with("insights:top-artists:10", TEST_CACHE_GENERATION)
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
        mock_cache.get.assert_called_once_with("insights:genre-trends:Rock", TEST_CACHE_GENERATION)
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

    def test_cache_key_does_not_collide_genres_differing_only_by_colon_vs_underscore(
        self,
        test_client_with_cache: TestClient,
        mock_cache: AsyncMock,
    ) -> None:
        """Regression discogsography-qjri: a prior `.replace(':', '_')` sanitization
        was non-injective — genre="A:B" and genre="A_B" both produced cache key
        "insights:genre-trends:A_B" and were served each other's cached response.
        The cache key must preserve the raw genre value (interior colons are
        harmless to InsightsCache.versioned_key, which only strips the fixed
        "insights:" literal prefix via removeprefix, not a colon split)."""
        mock_cache.get.return_value = None

        response = test_client_with_cache.get("/api/insights/genre-trends?genre=A:B")
        assert response.status_code == 200
        mock_cache.get.assert_called_once_with("insights:genre-trends:A:B", TEST_CACHE_GENERATION)

        mock_cache.reset_mock()
        mock_cache.get.return_value = None
        response = test_client_with_cache.get("/api/insights/genre-trends?genre=A_B")
        assert response.status_code == 200
        mock_cache.get.assert_called_once_with("insights:genre-trends:A_B", TEST_CACHE_GENERATION)


class TestLabelLongevityCacheIntegration:
    def test_cache_miss_queries_pg_and_stores(
        self,
        test_client_with_cache: TestClient,
        mock_cache: AsyncMock,
    ) -> None:
        mock_cache.get.return_value = None
        response = test_client_with_cache.get("/api/insights/label-longevity?limit=10")
        assert response.status_code == 200
        mock_cache.get.assert_called_once_with("insights:label-longevity:10", TEST_CACHE_GENERATION)
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
    def test_cache_miss_queries_pg_empty_result_not_cached(
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
        # Empty results are NOT cached to avoid caching stale data on month boundaries
        mock_cache.set.assert_not_called()

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
        mock_cache.get.assert_called_once_with("insights:data-completeness", TEST_CACHE_GENERATION)
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
# Release rarity endpoint tests
# ============================================================


class TestReleaseRarityEndpoint:
    def test_returns_200(self, test_client: TestClient) -> None:
        response = test_client.get("/api/insights/release-rarity")
        assert response.status_code == 200

    def test_with_limit(self, test_client: TestClient) -> None:
        response = test_client.get("/api/insights/release-rarity?limit=10")
        assert response.status_code == 200

    def test_not_ready(self) -> None:
        import insights.insights as _module

        original = _module._pool
        _module._pool = None
        try:
            from insights.insights import app

            client = TestClient(app)
            response = client.get("/api/insights/release-rarity")
            assert response.status_code == 503
        finally:
            _module._pool = original


class TestReleaseRarityCacheIntegration:
    def test_cache_miss_queries_pg_and_stores(
        self,
        mock_http_client: AsyncMock,
        mock_pg_pool: AsyncMock,
        mock_cache: AsyncMock,
    ) -> None:
        import insights.insights as _module

        _module._http_client = mock_http_client
        _module._pool = mock_pg_pool
        _module._cache = mock_cache

        # Return non-empty rows so caching is triggered
        mock_cursor = mock_pg_pool.connection.return_value.__aenter__.return_value.cursor.return_value.__aenter__.return_value
        mock_cursor.fetchall = AsyncMock(return_value=[(1, "Title", "Artist", 1990, 95.0, "ultra-rare", 80.0, 90.0, 85.0, 70.0, 60.0, 50.0, 40.0)])

        mock_cache.get.return_value = None

        from insights.insights import app

        client = TestClient(app)
        response = client.get("/api/insights/release-rarity?limit=10")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["items"][0]["release_id"] == 1
        mock_cache.get.assert_called_once_with("insights:release-rarity:10", TEST_CACHE_GENERATION)
        mock_cache.set.assert_called_once()

    def test_cache_hit_returns_cached_data(
        self,
        test_client_with_cache: TestClient,
        mock_cache: AsyncMock,
    ) -> None:
        cached = {"items": [{"release_id": 1}], "count": 1}
        mock_cache.get.return_value = cached
        response = test_client_with_cache.get("/api/insights/release-rarity")
        assert response.status_code == 200
        assert response.json() == cached
        mock_cache.set.assert_not_called()


class TestThisMonthCacheWithData:
    """Test that this-month endpoint caches when results are non-empty."""

    def test_cache_stores_non_empty_results(
        self,
        mock_http_client: AsyncMock,
        mock_pg_pool: AsyncMock,
        mock_cache: AsyncMock,
    ) -> None:
        import insights.insights as _module

        _module._http_client = mock_http_client
        _module._pool = mock_pg_pool
        _module._cache = mock_cache

        # Return non-empty rows
        mock_cursor = mock_pg_pool.connection.return_value.__aenter__.return_value.cursor.return_value.__aenter__.return_value
        mock_cursor.fetchall = AsyncMock(return_value=[("100", "Album", "Artist", 1990, 25)])
        mock_cache.get.return_value = None

        from insights.insights import app

        client = TestClient(app)
        response = client.get("/api/insights/this-month")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        # Non-empty results SHOULD be cached
        mock_cache.set.assert_called_once()


# ============================================================
# Lifespan tests
# ============================================================


class TestLifespan:
    @pytest.mark.asyncio
    async def test_lifespan_startup_and_shutdown(self) -> None:
        """Test the full lifespan context manager startup and shutdown paths."""
        from fastapi import FastAPI

        import insights.insights as _module

        mock_pool = AsyncMock()
        mock_pool.initialize = AsyncMock()
        mock_pool.close = AsyncMock()

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock()
        mock_redis.aclose = AsyncMock()

        mock_http_client = AsyncMock()
        mock_http_client.aclose = AsyncMock()

        mock_health_srv = MagicMock()
        mock_health_srv.start_background = MagicMock()
        mock_health_srv.stop = MagicMock()

        mock_cache = MagicMock()

        mock_config = MagicMock()
        mock_config.postgres_host = "localhost:5432"
        mock_config.postgres_database = "test"
        mock_config.postgres_username = "user"
        mock_config.postgres_password = "pass"
        mock_config.api_base_url = "http://localhost:8004"
        mock_config.redis_host = "redis://localhost"
        mock_config.schedule_hours = 24
        mock_config.milestone_years = [25, 50]

        # Create a scheduler task that completes immediately
        async def fake_scheduler(*_args: object, **_kwargs: object) -> None:
            await asyncio.sleep(100)

        fake_app = FastAPI()

        with (
            patch.object(_module, "setup_logging"),
            patch.object(_module.InsightsConfig, "from_env", return_value=mock_config),
            patch.object(_module, "HealthServer", return_value=mock_health_srv),
            patch.object(_module, "AsyncPostgreSQLPool", return_value=mock_pool),
            patch("httpx.AsyncClient", return_value=mock_http_client),
            patch("redis.asyncio.from_url", new_callable=AsyncMock, return_value=mock_redis),
            patch.object(_module, "InsightsCache", return_value=mock_cache),
            patch.object(_module, "_scheduler_loop", side_effect=fake_scheduler),
        ):
            async with _module.lifespan(fake_app):
                # Verify startup
                mock_health_srv.start_background.assert_called_once()
                mock_pool.initialize.assert_awaited_once()
                assert _module._cache is mock_cache

            # Verify shutdown
            mock_health_srv.stop.assert_called_once()
            mock_pool.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_lifespan_postgres_host_without_port(self) -> None:
        """When POSTGRES_HOST has no port suffix, default to port 5432."""
        from fastapi import FastAPI

        import insights.insights as _module

        mock_pool = AsyncMock()
        mock_pool.initialize = AsyncMock()
        mock_pool.close = AsyncMock()

        mock_http_client = AsyncMock()
        mock_http_client.aclose = AsyncMock()

        mock_health_srv = MagicMock()
        mock_health_srv.start_background = MagicMock()
        mock_health_srv.stop = MagicMock()

        mock_cache = MagicMock()

        mock_config = MagicMock()
        mock_config.postgres_host = "postgres"  # No port
        mock_config.postgres_database = "test"
        mock_config.postgres_username = "user"
        mock_config.postgres_password = "pass"
        mock_config.api_base_url = "http://localhost:8004"
        mock_config.redis_host = "redis://localhost"
        mock_config.schedule_hours = 24
        mock_config.milestone_years = [25, 50]

        async def fake_scheduler(*_args: object, **_kwargs: object) -> None:
            await asyncio.sleep(100)

        fake_app = FastAPI()

        with (
            patch.object(_module, "setup_logging"),
            patch.object(_module.InsightsConfig, "from_env", return_value=mock_config),
            patch.object(_module, "HealthServer", return_value=mock_health_srv),
            patch.object(_module, "AsyncPostgreSQLPool", return_value=mock_pool) as mock_pool_cls,
            patch("httpx.AsyncClient", return_value=mock_http_client),
            patch("redis.asyncio.from_url", new_callable=AsyncMock, return_value=MagicMock()),
            patch.object(_module, "InsightsCache", return_value=mock_cache),
            patch.object(_module, "_scheduler_loop", side_effect=fake_scheduler),
        ):
            async with _module.lifespan(fake_app):
                # Verify pool was created with host="postgres" and port=5432
                call_kwargs = mock_pool_cls.call_args[1]
                assert call_kwargs["connection_params"]["host"] == "postgres"
                assert call_kwargs["connection_params"]["port"] == 5432

            mock_pool.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_lifespan_missing_internal_secret_warns_and_omits_header(self) -> None:
        """When INSIGHTS_INTERNAL_SECRET is unset, startup logs a warning and the HTTP
        client is built WITHOUT the X-Internal-Secret header (the API will reject calls)."""
        from fastapi import FastAPI

        import insights.insights as _module

        mock_pool = AsyncMock()
        mock_pool.initialize = AsyncMock()
        mock_pool.close = AsyncMock()

        mock_http_client = AsyncMock()
        mock_http_client.aclose = AsyncMock()

        mock_health_srv = MagicMock()
        mock_health_srv.start_background = MagicMock()
        mock_health_srv.stop = MagicMock()

        mock_config = MagicMock()
        mock_config.postgres_host = "localhost:5432"
        mock_config.postgres_database = "test"
        mock_config.postgres_username = "user"
        mock_config.postgres_password = "pass"
        mock_config.api_base_url = "http://localhost:8004"
        mock_config.redis_host = "redis://localhost"
        mock_config.schedule_hours = 24
        mock_config.milestone_years = [25, 50]
        mock_config.internal_secret = None  # secret unset → else branch

        async def fake_scheduler(*_args: object, **_kwargs: object) -> None:
            await asyncio.sleep(100)

        fake_app = FastAPI()

        with (
            patch.object(_module, "setup_logging"),
            patch.object(_module.InsightsConfig, "from_env", return_value=mock_config),
            patch.object(_module, "HealthServer", return_value=mock_health_srv),
            patch.object(_module, "AsyncPostgreSQLPool", return_value=mock_pool),
            patch("httpx.AsyncClient", return_value=mock_http_client) as mock_client_cls,
            patch("redis.asyncio.from_url", new_callable=AsyncMock, return_value=MagicMock()),
            patch.object(_module, "InsightsCache", return_value=MagicMock()),
            patch.object(_module, "_scheduler_loop", side_effect=fake_scheduler),
            patch.object(_module.logger, "warning") as mock_warning,
        ):
            async with _module.lifespan(fake_app):
                # HTTP client built without the internal-secret header.
                headers = mock_client_cls.call_args.kwargs["headers"]
                assert "X-Internal-Secret" not in headers

            # The missing-secret warning was emitted.
            assert any("INSIGHTS_INTERNAL_SECRET is not set" in str(c.args[0]) for c in mock_warning.call_args_list)

    @pytest.mark.asyncio
    async def test_lifespan_redis_unavailable_fallback(self) -> None:
        """When Redis is unavailable, caching should be disabled gracefully."""
        from fastapi import FastAPI

        import insights.insights as _module

        mock_pool = AsyncMock()
        mock_pool.initialize = AsyncMock()
        mock_pool.close = AsyncMock()

        mock_http_client = AsyncMock()
        mock_http_client.aclose = AsyncMock()

        mock_health_srv = MagicMock()
        mock_health_srv.start_background = MagicMock()
        mock_health_srv.stop = MagicMock()

        mock_config = MagicMock()
        mock_config.postgres_host = "localhost:5432"
        mock_config.postgres_database = "test"
        mock_config.postgres_username = "user"
        mock_config.postgres_password = "pass"
        mock_config.api_base_url = "http://localhost:8004"
        mock_config.redis_host = "redis://localhost"
        mock_config.schedule_hours = 24
        mock_config.milestone_years = [25, 50]

        async def fake_scheduler(*_args: object, **_kwargs: object) -> None:
            await asyncio.sleep(100)

        fake_app = FastAPI()

        with (
            patch.object(_module, "setup_logging"),
            patch.object(_module.InsightsConfig, "from_env", return_value=mock_config),
            patch.object(_module, "HealthServer", return_value=mock_health_srv),
            patch.object(_module, "AsyncPostgreSQLPool", return_value=mock_pool),
            patch("httpx.AsyncClient", return_value=mock_http_client),
            patch("redis.asyncio.from_url", side_effect=ConnectionError("Redis down")),
            patch.object(_module, "_scheduler_loop", side_effect=fake_scheduler),
        ):
            async with _module.lifespan(fake_app):
                # Redis failure should result in None cache
                assert _module._redis is None
                assert _module._cache is None

            mock_health_srv.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_lifespan_closes_redis_client_when_ping_fails(self) -> None:
        """discogsography-v1g8: from_url() is lazy — ping() is what actually
        opens the socket. If ping() raises (e.g. requirepass with a missing/
        wrong REDIS_PASSWORD), the client built by from_url() must still be
        closed before the reference is dropped — otherwise the connection
        pool and the socket ping() opened are never released."""
        from fastapi import FastAPI

        import insights.insights as _module

        mock_pool = AsyncMock()
        mock_pool.initialize = AsyncMock()
        mock_pool.close = AsyncMock()

        mock_http_client = AsyncMock()
        mock_http_client.aclose = AsyncMock()

        mock_health_srv = MagicMock()
        mock_health_srv.start_background = MagicMock()
        mock_health_srv.stop = MagicMock()

        mock_config = MagicMock()
        mock_config.postgres_host = "localhost:5432"
        mock_config.postgres_database = "test"
        mock_config.postgres_username = "user"
        mock_config.postgres_password = "pass"
        mock_config.api_base_url = "http://localhost:8004"
        mock_config.redis_host = "redis://localhost"
        mock_config.schedule_hours = 24
        mock_config.milestone_years = [25, 50]

        # from_url() succeeds (lazy) but the socket-opening ping() fails —
        # the exact AUTH-failure-under-requirepass scenario.
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(side_effect=ConnectionError("NOAUTH Authentication required"))
        mock_redis.aclose = AsyncMock()

        async def fake_scheduler(*_args: object, **_kwargs: object) -> None:
            await asyncio.sleep(100)

        fake_app = FastAPI()

        with (
            patch.object(_module, "setup_logging"),
            patch.object(_module.InsightsConfig, "from_env", return_value=mock_config),
            patch.object(_module, "HealthServer", return_value=mock_health_srv),
            patch.object(_module, "AsyncPostgreSQLPool", return_value=mock_pool),
            patch("httpx.AsyncClient", return_value=mock_http_client),
            patch("redis.asyncio.from_url", new_callable=AsyncMock, return_value=mock_redis),
            patch.object(_module, "_scheduler_loop", side_effect=fake_scheduler),
        ):
            async with _module.lifespan(fake_app):
                # Falls back to no caching, exactly like the from_url()-raises case.
                assert _module._redis is None
                assert _module._cache is None

            mock_health_srv.stop.assert_called_once()

        # The orphaned client (from the successful from_url()) must have
        # been closed before _redis was set to None.
        mock_redis.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_lifespan_redis_close_failure_on_ping_error_is_swallowed(self) -> None:
        """A failure while cleaning up the orphaned client (aclose() itself
        raising) must not prevent the graceful PostgreSQL-fallback path."""
        from fastapi import FastAPI

        import insights.insights as _module

        mock_pool = AsyncMock()
        mock_pool.initialize = AsyncMock()
        mock_pool.close = AsyncMock()

        mock_http_client = AsyncMock()
        mock_http_client.aclose = AsyncMock()

        mock_health_srv = MagicMock()
        mock_health_srv.start_background = MagicMock()
        mock_health_srv.stop = MagicMock()

        mock_config = MagicMock()
        mock_config.postgres_host = "localhost:5432"
        mock_config.postgres_database = "test"
        mock_config.postgres_username = "user"
        mock_config.postgres_password = "pass"
        mock_config.api_base_url = "http://localhost:8004"
        mock_config.redis_host = "redis://localhost"
        mock_config.schedule_hours = 24
        mock_config.milestone_years = [25, 50]

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(side_effect=ConnectionError("Redis down"))
        mock_redis.aclose = AsyncMock(side_effect=RuntimeError("close also failed"))

        async def fake_scheduler(*_args: object, **_kwargs: object) -> None:
            await asyncio.sleep(100)

        fake_app = FastAPI()

        with (
            patch.object(_module, "setup_logging"),
            patch.object(_module.InsightsConfig, "from_env", return_value=mock_config),
            patch.object(_module, "HealthServer", return_value=mock_health_srv),
            patch.object(_module, "AsyncPostgreSQLPool", return_value=mock_pool),
            patch("httpx.AsyncClient", return_value=mock_http_client),
            patch("redis.asyncio.from_url", new_callable=AsyncMock, return_value=mock_redis),
            patch.object(_module, "_scheduler_loop", side_effect=fake_scheduler),
        ):
            async with _module.lifespan(fake_app):
                # Must not raise — the service still falls back cleanly.
                assert _module._redis is None
                assert _module._cache is None


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


# Every read endpoint that caches, with the cache key it uses.
_CACHED_ENDPOINTS = [
    ("/api/insights/top-artists?limit=10", "insights:top-artists:10"),
    ("/api/insights/genre-trends?genre=Rock", "insights:genre-trends:Rock"),
    ("/api/insights/label-longevity?limit=10", "insights:label-longevity:10"),
    ("/api/insights/release-rarity?limit=10", "insights:release-rarity:10"),
    ("/api/insights/data-completeness", "insights:data-completeness"),
]


class TestCacheGenerationThreading:
    """discogsography-cu2.109: every read endpoint must write back to the
    generation it read from, so a request straddling a recompute cannot
    re-cache pre-update data over freshly computed results.
    """

    @pytest.mark.parametrize(("url", "cache_key"), _CACHED_ENDPOINTS)
    def test_get_and_set_use_the_same_generation(
        self,
        test_client_with_cache: TestClient,
        mock_cache: AsyncMock,
        url: str,
        cache_key: str,
    ) -> None:
        mock_cache.get.return_value = None

        response = test_client_with_cache.get(url)

        assert response.status_code == 200
        assert mock_cache.get.call_args[0] == (cache_key, TEST_CACHE_GENERATION)
        assert mock_cache.set.call_args[0][0] == cache_key
        assert mock_cache.set.call_args[0][2] == TEST_CACHE_GENERATION, "set() must use the generation captured before the DB read, not a re-read one"

    @pytest.mark.parametrize("url", [url for url, _ in _CACHED_ENDPOINTS])
    def test_generation_is_read_before_the_cache_lookup(
        self,
        test_client_with_cache: TestClient,
        mock_cache: AsyncMock,
        url: str,
    ) -> None:
        """Ordering guard: generation() must precede get() (and therefore the DB read)."""
        calls: list[str] = []
        mock_cache.generation = AsyncMock(side_effect=lambda: calls.append("generation") or TEST_CACHE_GENERATION)
        mock_cache.get = AsyncMock(side_effect=lambda *_a, **_k: calls.append("get"))
        mock_cache.set = AsyncMock(side_effect=lambda *_a, **_k: calls.append("set"))

        response = test_client_with_cache.get(url)

        assert response.status_code == 200
        assert calls == ["generation", "get", "set"]
