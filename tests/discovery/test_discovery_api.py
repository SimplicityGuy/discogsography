"""Tests for the Discovery service API endpoints."""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


class TestDiscoveryAPI:
    """Test Discovery service API endpoints."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Create a test client for the Discovery service."""
        from discovery.discovery import app

        return TestClient(app)

    def test_root_endpoint(self, client: TestClient) -> None:
        """Test the root endpoint serves HTML."""
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_health_endpoint(self, client: TestClient) -> None:
        """Test the health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "discovery"
        assert "timestamp" in data
        assert "features" in data

    def test_recommendations_endpoint(self, client: TestClient, sample_recommendation_data: Any) -> None:
        """Test the recommendations API endpoint."""
        with patch("discovery.discovery.get_recommendations") as mock_get_recs:
            mock_get_recs.return_value = sample_recommendation_data

            request_data = {
                "artist_name": "Miles Davis",
                "recommendation_type": "similar",
                "limit": 10,
            }

            response = client.post("/api/recommendations", json=request_data)
            assert response.status_code == 200

            data = response.json()
            assert "recommendations" in data
            assert "total" in data
            assert data["total"] == len(sample_recommendation_data)

    def test_recommendations_endpoint_error(self, client: TestClient) -> None:
        """Test the recommendations API endpoint with error."""
        with patch("discovery.discovery.get_recommendations") as mock_get_recs:
            mock_get_recs.side_effect = Exception("Test error")

            request_data = {"artist_name": "Miles Davis", "recommendation_type": "similar"}

            response = client.post("/api/recommendations", json=request_data)
            assert response.status_code == 500

    def test_analytics_endpoint(self, client: TestClient, sample_analytics_data: Any) -> None:
        """Test the analytics API endpoint."""
        with patch("discovery.discovery.get_analytics") as mock_get_analytics:
            mock_get_analytics.return_value = sample_analytics_data

            request_data = {
                "analysis_type": "genre_trends",
                "time_range": [1990, 2020],
                "limit": 20,
            }

            response = client.post("/api/analytics", json=request_data)
            assert response.status_code == 200

            data = response.json()
            assert data["chart_type"] == "line"
            assert "insights" in data

    def test_analytics_endpoint_error(self, client: TestClient) -> None:
        """Test the analytics API endpoint with error."""
        with patch("discovery.discovery.get_analytics") as mock_get_analytics:
            mock_get_analytics.side_effect = Exception("Test error")

            request_data = {"analysis_type": "genre_trends"}

            response = client.post("/api/analytics", json=request_data)
            assert response.status_code == 500

    def test_graph_explore_endpoint(self, client: TestClient, sample_graph_data: Any) -> None:
        """Test the graph exploration API endpoint."""
        with patch("discovery.discovery.explore_graph") as mock_explore:
            mock_explore.return_value = (sample_graph_data, None)

            request_data = {"query_type": "search", "search_term": "Miles Davis", "limit": 20}

            response = client.post("/api/graph/explore", json=request_data)
            assert response.status_code == 200

            data = response.json()
            assert "graph" in data
            assert "query" in data

    def test_graph_explore_endpoint_with_path(self, client: TestClient, sample_graph_data: Any) -> None:
        """Test the graph exploration API endpoint with path result."""
        from discovery.graph_explorer import PathResult

        path_result = PathResult(path=["123", "456"], path_length=1, total_paths=1, explanation="Test path")

        with patch("discovery.discovery.explore_graph") as mock_explore:
            mock_explore.return_value = (sample_graph_data, path_result)

            request_data = {"query_type": "path", "source_node": "123", "target_node": "456"}

            response = client.post("/api/graph/explore", json=request_data)
            assert response.status_code == 200

            data = response.json()
            assert "graph" in data
            assert "path" in data
            assert data["path"]["path_length"] == 1

    def test_graph_explore_endpoint_error(self, client: TestClient) -> None:
        """Test the graph exploration API endpoint with error."""
        with patch("discovery.discovery.explore_graph") as mock_explore:
            mock_explore.side_effect = Exception("Test error")

            request_data = {"query_type": "search", "search_term": "Miles Davis"}

            response = client.post("/api/graph/explore", json=request_data)
            assert response.status_code == 500


class TestDiscoveryAppClass:
    """Test the DiscoveryApp class."""

    def _create_discovery_app(self) -> Any:
        """Create a DiscoveryApp with mocked config."""
        from unittest.mock import MagicMock

        from discovery.discovery import DiscoveryApp

        with patch("discovery.discovery.get_config") as mock_config:
            mock_config.return_value = MagicMock()
            return DiscoveryApp()

    def test_discovery_app_init(self) -> None:
        """Test DiscoveryApp initialization."""
        app = self._create_discovery_app()
        assert app.active_connections == []

    @pytest.mark.asyncio
    async def test_connect_websocket(self) -> None:
        """Test WebSocket connection."""
        app = self._create_discovery_app()
        mock_websocket = AsyncMock()

        await app.connect_websocket(mock_websocket)

        mock_websocket.accept.assert_called_once()
        assert mock_websocket in app.active_connections

    def test_disconnect_websocket(self) -> None:
        """Test WebSocket disconnection."""
        from unittest.mock import MagicMock

        app = self._create_discovery_app()
        mock_websocket = MagicMock()
        app.active_connections = [mock_websocket]

        app.disconnect_websocket(mock_websocket)

        assert mock_websocket not in app.active_connections

    @pytest.mark.asyncio
    async def test_broadcast_update(self) -> None:
        """Test broadcasting updates to WebSocket clients."""
        app = self._create_discovery_app()
        mock_websocket1 = AsyncMock()
        mock_websocket2 = AsyncMock()
        app.active_connections = [mock_websocket1, mock_websocket2]

        message = {"type": "test", "data": "hello"}
        await app.broadcast_update(message)

        mock_websocket1.send_json.assert_called_once_with(message)
        mock_websocket2.send_json.assert_called_once_with(message)

    @pytest.mark.asyncio
    async def test_broadcast_update_with_disconnected_client(self) -> None:
        """Test broadcasting updates with disconnected clients."""
        app = self._create_discovery_app()
        mock_websocket1 = AsyncMock()
        mock_websocket2 = AsyncMock()

        # Make one websocket fail
        mock_websocket1.send_json.side_effect = Exception("Connection lost")

        app.active_connections = [mock_websocket1, mock_websocket2]

        message = {"type": "test", "data": "hello"}
        await app.broadcast_update(message)

        # Failed websocket should be removed
        assert mock_websocket1 not in app.active_connections
        assert mock_websocket2 in app.active_connections

    @pytest.mark.asyncio
    async def test_broadcast_update_no_connections(self) -> None:
        """Test broadcasting updates with no active connections."""
        app = self._create_discovery_app()
        app.active_connections = []

        message = {"type": "test", "data": "hello"}
        # Should not raise any errors
        await app.broadcast_update(message)
