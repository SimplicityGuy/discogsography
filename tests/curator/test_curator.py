"""Tests for the curator service (curator/curator.py)."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
import pytest


class TestGetHealthData:
    """Tests for curator.get_health_data."""

    def test_healthy_when_pool_and_neo4j_set(self, test_client: TestClient) -> None:  # noqa: ARG002
        from curator.curator import get_health_data

        data = get_health_data()
        assert data["status"] == "healthy"
        assert data["service"] == "curator"
        assert "timestamp" in data

    def test_starting_when_no_pool(self) -> None:
        import curator.curator as curator_module
        from curator.curator import get_health_data

        original_pool = curator_module._pool
        curator_module._pool = None
        try:
            data = get_health_data()
            assert data["status"] == "starting"
        finally:
            curator_module._pool = original_pool


class TestHealthEndpoint:
    """Tests for GET /health."""

    def test_health_returns_200(self, test_client: TestClient) -> None:
        response = test_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "curator"


class TestLifespan:
    """Tests for the curator lifespan context manager."""

    @pytest.mark.asyncio
    async def test_lifespan_startup_and_shutdown(self) -> None:
        """Lifespan initialises all services and cleans them up on exit."""
        import curator.curator as curator_module
        from curator.curator import app, lifespan

        mock_pool = MagicMock()
        mock_pool.initialize = AsyncMock()
        mock_pool.close = AsyncMock()

        mock_neo4j = MagicMock()
        mock_neo4j.close = AsyncMock()

        mock_health_server = MagicMock()

        mock_config = MagicMock()
        mock_config.postgres_host = "localhost:5432"
        mock_config.postgres_database = "testdb"
        mock_config.postgres_username = "testuser"
        mock_config.postgres_password = "testpass"
        mock_config.neo4j_host = "bolt://localhost:7687"
        mock_config.neo4j_username = "neo4j"
        mock_config.neo4j_password = "testpass"

        original_pool = curator_module._pool
        original_neo4j = curator_module._neo4j
        original_config = curator_module._config

        try:
            with (
                patch("curator.curator.CuratorConfig.from_env", return_value=mock_config),
                patch("curator.curator.HealthServer", return_value=mock_health_server),
                patch("curator.curator.AsyncPostgreSQLPool", return_value=mock_pool),
                patch("curator.curator.AsyncResilientNeo4jDriver", return_value=mock_neo4j),
            ):
                async with lifespan(app):
                    assert curator_module._pool is mock_pool
                    assert curator_module._neo4j is mock_neo4j
                    assert curator_module._config is mock_config

                mock_pool.initialize.assert_awaited_once()
                mock_pool.close.assert_awaited_once()
                mock_neo4j.close.assert_awaited_once()
                mock_health_server.start_background.assert_called_once()
                mock_health_server.stop.assert_called_once()
        finally:
            curator_module._pool = original_pool
            curator_module._neo4j = original_neo4j
            curator_module._config = original_config

    @pytest.mark.asyncio
    async def test_lifespan_shutdown_skips_close_when_none(self) -> None:
        """Shutdown gracefully handles None pool and neo4j (module state not set)."""
        import curator.curator as curator_module
        from curator.curator import app, lifespan

        mock_health_server = MagicMock()
        mock_config = MagicMock()
        mock_config.postgres_host = "localhost:5432"
        mock_config.postgres_database = "testdb"
        mock_config.postgres_username = "testuser"
        mock_config.postgres_password = "testpass"
        mock_config.neo4j_host = "bolt://localhost:7687"
        mock_config.neo4j_username = "neo4j"
        mock_config.neo4j_password = "testpass"

        mock_pool = MagicMock()
        mock_pool.initialize = AsyncMock()
        mock_pool.close = AsyncMock()
        mock_neo4j = MagicMock()
        mock_neo4j.close = AsyncMock()

        original_pool = curator_module._pool
        original_neo4j = curator_module._neo4j
        original_config = curator_module._config

        try:
            with (
                patch("curator.curator.CuratorConfig.from_env", return_value=mock_config),
                patch("curator.curator.HealthServer", return_value=mock_health_server),
                patch("curator.curator.AsyncPostgreSQLPool", return_value=mock_pool),
                patch("curator.curator.AsyncResilientNeo4jDriver", return_value=mock_neo4j),
            ):
                async with lifespan(app):
                    # Simulate both being cleared during the yield
                    curator_module._pool = None
                    curator_module._neo4j = None

                # close() should NOT have been called
                mock_pool.close.assert_not_awaited()
                mock_neo4j.close.assert_not_awaited()
                mock_health_server.stop.assert_called_once()
        finally:
            curator_module._pool = original_pool
            curator_module._neo4j = original_neo4j
            curator_module._config = original_config


class TestMain:
    """Tests for the curator main() entry point."""

    def test_main_sets_up_logging_and_runs_server(self) -> None:
        """main() calls setup_logging and starts uvicorn."""
        from curator.curator import main

        with (
            patch("curator.curator.setup_logging") as mock_setup_logging,
            patch("curator.curator.uvicorn.run") as mock_uvicorn_run,
        ):
            main()

        mock_setup_logging.assert_called_once_with("curator", log_file=Path("/logs/curator.log"))
        mock_uvicorn_run.assert_called_once()
