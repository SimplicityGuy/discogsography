"""Tests for the curator service (curator/curator.py)."""

from fastapi.testclient import TestClient


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
