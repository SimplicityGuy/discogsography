"""Integration tests for dashboard API using FastAPI TestClient."""

import asyncio
import typing

import pytest
from fastapi.testclient import TestClient

from tests.dashboard.dashboard_test_app import create_test_app


class TestDashboardAPIIntegration:
    """Test dashboard API endpoints with mocked dependencies."""

    @pytest.fixture
    def client(self) -> typing.Generator[TestClient]:
        """Create test client with mocked app."""
        app = create_test_app()
        with TestClient(app) as test_client:
            # Wait a bit for mock data to be initialized
            asyncio.run(asyncio.sleep(0.5))
            yield test_client

    def test_metrics_endpoint(self, client: TestClient) -> None:
        """Test metrics endpoint returns expected structure."""
        response = client.get("/api/metrics")
        assert response.status_code == 200
        data = response.json()
        assert "services" in data
        assert "queues" in data
        assert "databases" in data
        assert "timestamp" in data

    def test_services_endpoint(self, client: TestClient) -> None:
        """Test services endpoint returns service list."""
        response = client.get("/api/services")
        assert response.status_code == 200
        services = response.json()
        assert isinstance(services, list)
        # Should have 3 services when mocked
        assert len(services) == 3
        service_names = {s["name"] for s in services}
        assert service_names == {"extractor", "graphinator", "tableinator"}

    def test_queues_endpoint(self, client: TestClient) -> None:
        """Test queues endpoint returns queue list."""
        response = client.get("/api/queues")
        assert response.status_code == 200
        queues = response.json()
        assert isinstance(queues, list)
        # Should have mocked queues
        assert len(queues) >= 2
        for queue in queues:
            assert "name" in queue
            assert "messages" in queue
            assert "consumers" in queue

    def test_databases_endpoint(self, client: TestClient) -> None:
        """Test databases endpoint returns database list."""
        response = client.get("/api/databases")
        assert response.status_code == 200
        databases = response.json()
        assert isinstance(databases, list)
        # Should have 2 databases
        assert len(databases) == 2
        db_names = {db["name"] for db in databases}
        assert db_names == {"PostgreSQL", "Neo4j"}

    def test_prometheus_metrics(self, client: TestClient) -> None:
        """Test Prometheus metrics endpoint."""
        response = client.get("/metrics")
        assert response.status_code == 200
        # The test app returns a simple string, not full prometheus format
        assert "dashboard_websocket_connections" in response.text

    def test_index_page(self, client: TestClient) -> None:
        """Test that index page is served."""
        response = client.get("/")
        assert response.status_code == 200
        # Should serve HTML file
        assert "text/html" in response.headers["content-type"]

    def test_static_files(self, client: TestClient) -> None:
        """Test that static files are served."""
        # Test CSS
        response = client.get("/styles.css")
        assert response.status_code == 200
        assert "text/css" in response.headers["content-type"]

        # Test JS
        response = client.get("/dashboard.js")
        assert response.status_code == 200
        assert "javascript" in response.headers["content-type"]
