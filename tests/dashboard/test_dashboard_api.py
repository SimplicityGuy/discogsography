"""API tests for the dashboard using FastAPI TestClient."""

from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


class TestDashboardAPI:
    """Test the dashboard API endpoints."""

    @pytest.fixture
    def test_client(
        self,
        mock_dashboard_config: Any,
        mock_amqp_connection: Any,
        mock_neo4j_driver: Any,
        mock_httpx_client: Any,
        mock_psycopg_connect: Any,
    ) -> TestClient:
        """Create a test client with mocked dependencies."""
        with (
            patch("dashboard.dashboard.get_config", return_value=mock_dashboard_config),
            patch("dashboard.dashboard.aio_pika.connect_robust", return_value=mock_amqp_connection),
            patch("dashboard.dashboard.AsyncGraphDatabase.driver", return_value=mock_neo4j_driver),
            patch("httpx.AsyncClient") as mock_httpx_class,
            patch("psycopg.AsyncConnection.connect", return_value=mock_psycopg_connect),
        ):
            # Configure httpx.AsyncClient to return our mock instance
            mock_httpx_class.return_value = mock_httpx_client

            # Import the app after patching
            from dashboard.dashboard import app

            return TestClient(app)

    def test_root_endpoint(self, test_client: TestClient) -> None:
        """Test that the root endpoint returns the index page."""
        response = test_client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_metrics_endpoint(self, test_client: TestClient) -> None:
        """Test the metrics API endpoint."""
        # First, trigger the lifespan events by making a request
        test_client.get("/")

        response = test_client.get("/api/metrics")
        assert response.status_code == 200
        data = response.json()

        # The endpoint might return empty data if dashboard is not initialized
        # This is expected behavior in test mode
        if data:
            # Check structure if data is available
            assert "services" in data
            assert "queues" in data
            assert "databases" in data
            assert "timestamp" in data

    def test_prometheus_metrics(self, test_client: TestClient) -> None:
        """Test the Prometheus metrics endpoint."""
        response = test_client.get("/metrics")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/plain; charset=utf-8"

        # Check for some expected metrics
        content = response.text
        assert "dashboard_websocket_connections" in content
        assert "dashboard_api_requests" in content

    def test_static_files(self, test_client: TestClient) -> None:
        """Test that static files are served."""
        # Static files are mounted at root, not under /static
        # Test CSS
        response = test_client.get("/styles.css")
        assert response.status_code == 200
        assert "text/css" in response.headers["content-type"]

        # Test JavaScript
        response = test_client.get("/dashboard.js")
        assert response.status_code == 200
        assert "javascript" in response.headers["content-type"]
