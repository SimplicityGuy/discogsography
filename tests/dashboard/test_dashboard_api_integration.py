"""Integration tests for dashboard API using FastAPI TestClient."""

import typing

from fastapi.testclient import TestClient
import pytest

from tests.dashboard.dashboard_test_app import create_test_app


class TestDashboardAPIIntegration:
    """Test dashboard API endpoints with mocked dependencies."""

    @pytest.fixture
    def client(self) -> typing.Generator[TestClient]:
        """Create test client with mocked app."""
        app = create_test_app()
        with TestClient(app) as test_client:
            # TestClient handles async internally, no need for explicit asyncio.run
            yield test_client

    def test_metrics_endpoint(self, client: TestClient) -> None:
        """Test metrics endpoint returns expected structure."""
        response = client.get("/api/metrics")
        assert response.status_code == 200
        data = response.json()
        assert "pipelines" in data
        assert "databases" in data
        assert "timestamp" in data
        assert "discogs" in data["pipelines"]
        discogs = data["pipelines"]["discogs"]
        assert "services" in discogs
        assert "queues" in discogs

    def test_services_endpoint(self, client: TestClient) -> None:
        """Test services endpoint returns service dict grouped by pipeline."""
        response = client.get("/api/services")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "discogs" in data
        assert len(data["discogs"]) == 3
        service_names = {s["name"] for s in data["discogs"]}
        assert service_names == {"extractor-discogs", "graphinator", "tableinator"}

    def test_queues_endpoint(self, client: TestClient) -> None:
        """Test queues endpoint returns queue dict grouped by pipeline."""
        response = client.get("/api/queues")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "discogs" in data
        assert len(data["discogs"]) >= 2
        for queue in data["discogs"]:
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
        # Test JS (CSS is tailwind.css, a build artifact not present in source)
        response = client.get("/dashboard.js")
        assert response.status_code == 200
        assert "javascript" in response.headers["content-type"]

    def test_musicbrainz_pipeline_absent_when_not_deployed(self, client: TestClient) -> None:
        """Test that MusicBrainz pipeline is absent when services are not deployed."""
        response = client.get("/api/metrics")
        assert response.status_code == 200
        data = response.json()
        assert "musicbrainz" not in data["pipelines"]


class TestDashboardPipelineDetection:
    """Test pipeline auto-detection with MusicBrainz enabled."""

    @pytest.fixture
    def client_with_musicbrainz(self) -> typing.Generator[TestClient]:
        """Create test client with MusicBrainz pipeline included."""
        from tests.dashboard.dashboard_test_app import create_test_app_with_musicbrainz

        app = create_test_app_with_musicbrainz()
        with TestClient(app) as test_client:
            yield test_client

    def test_both_pipelines_present(self, client_with_musicbrainz: TestClient) -> None:
        """Test that both Discogs and MusicBrainz pipelines are present."""
        response = client_with_musicbrainz.get("/api/metrics")
        assert response.status_code == 200
        data = response.json()
        assert "discogs" in data["pipelines"]
        assert "musicbrainz" in data["pipelines"]
        mb = data["pipelines"]["musicbrainz"]
        service_names = {s["name"] for s in mb["services"]}
        assert service_names == {"extractor-musicbrainz", "brainzgraphinator", "brainztableinator"}

    def test_musicbrainz_services_endpoint(self, client_with_musicbrainz: TestClient) -> None:
        """Test services endpoint includes MusicBrainz pipeline."""
        response = client_with_musicbrainz.get("/api/services")
        assert response.status_code == 200
        data = response.json()
        assert "discogs" in data
        assert "musicbrainz" in data
        mb_names = {s["name"] for s in data["musicbrainz"]}
        assert mb_names == {"extractor-musicbrainz", "brainzgraphinator", "brainztableinator"}

    def test_musicbrainz_queues_endpoint(self, client_with_musicbrainz: TestClient) -> None:
        """Test queues endpoint includes MusicBrainz pipeline."""
        response = client_with_musicbrainz.get("/api/queues")
        assert response.status_code == 200
        data = response.json()
        assert "discogs" in data
        assert "musicbrainz" in data
        assert len(data["musicbrainz"]) >= 1
        assert data["musicbrainz"][0]["name"] == "discogsography-musicbrainz-brainzgraphinator-artists"
