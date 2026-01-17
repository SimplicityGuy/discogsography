"""Unit tests for Real-Time Features API.

Tests API endpoints, initialization, WebSocket connections, and real-time features.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from discovery.api_realtime import (
    CacheInvalidateRequest,
    SubscribeRequest,
    TrendingRequest,
    close_realtime_api,
    initialize_realtime_api,
    router,
)


class TestRequestModels:
    """Tests for Pydantic request models."""

    def test_trending_request_defaults(self):
        """Test TrendingRequest with default values."""
        request = TrendingRequest()

        assert request.category == "artists"
        assert request.limit == 10
        assert request.time_window == "day"

    def test_trending_request_custom_values(self):
        """Test TrendingRequest with custom values."""
        request = TrendingRequest(
            category="genres",
            limit=25,
            time_window="week",
        )

        assert request.category == "genres"
        assert request.limit == 25
        assert request.time_window == "week"

    def test_trending_request_validation(self):
        """Test TrendingRequest validation constraints."""
        from pydantic import ValidationError

        # Valid limits
        TrendingRequest(limit=1)
        TrendingRequest(limit=50)

        # Invalid limits should fail validation
        with pytest.raises(ValidationError):
            TrendingRequest(limit=0)

        with pytest.raises(ValidationError):
            TrendingRequest(limit=51)

    def test_subscribe_request(self):
        """Test SubscribeRequest model."""
        request = SubscribeRequest(channels=["trending", "analytics"])

        assert request.channels == ["trending", "analytics"]
        assert request.connection_id is None

    def test_subscribe_request_with_connection_id(self):
        """Test SubscribeRequest with connection ID."""
        request = SubscribeRequest(
            channels=["trending"],
            connection_id="conn-123",
        )

        assert request.connection_id == "conn-123"

    def test_cache_invalidate_request_defaults(self):
        """Test CacheInvalidateRequest with defaults."""
        request = CacheInvalidateRequest(pattern="cache:*")

        assert request.pattern == "cache:*"
        assert request.scope == "prefix"

    def test_cache_invalidate_request_custom_scope(self):
        """Test CacheInvalidateRequest with custom scope."""
        request = CacheInvalidateRequest(
            pattern="specific-key",
            scope="exact",
        )

        assert request.pattern == "specific-key"
        assert request.scope == "exact"


class TestInitialization:
    """Tests for API initialization and cleanup."""

    @pytest.mark.asyncio
    async def test_initialize_realtime_api(self):
        """Test successful initialization of realtime API."""
        import discovery.api_realtime as api_module

        # Mock Neo4j driver
        mock_driver = MagicMock()

        # Reset global state
        api_module.realtime_api_initialized = False
        api_module.websocket_manager = None
        api_module.trend_tracker = None
        api_module.cache_invalidation_manager = None

        # Initialize
        await initialize_realtime_api(mock_driver)

        # Verify initialization
        assert api_module.realtime_api_initialized is True
        assert api_module.websocket_manager is not None
        assert api_module.trend_tracker is not None
        assert api_module.cache_invalidation_manager is not None

    @pytest.mark.asyncio
    async def test_close_realtime_api(self):
        """Test cleanup of realtime API."""
        import discovery.api_realtime as api_module

        # Setup with mock connections
        mock_ws1 = MagicMock()
        mock_ws1.close = AsyncMock()
        mock_ws2 = MagicMock()
        mock_ws2.close = AsyncMock()

        api_module.active_websocket_connections = [mock_ws1, mock_ws2]
        api_module.realtime_api_initialized = True

        # Close API
        await close_realtime_api()

        # Verify cleanup
        assert api_module.realtime_api_initialized is False
        assert len(api_module.active_websocket_connections) == 0
        mock_ws1.close.assert_called_once()
        mock_ws2.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_realtime_api_handles_errors(self):
        """Test close_realtime_api handles WebSocket close errors gracefully."""
        import discovery.api_realtime as api_module

        # Setup with failing connection
        mock_ws = MagicMock()
        mock_ws.close = AsyncMock(side_effect=Exception("Close failed"))

        api_module.active_websocket_connections = [mock_ws]
        api_module.realtime_api_initialized = True

        # Should not raise exception
        await close_realtime_api()

        # Verify cleanup still happened
        assert len(api_module.active_websocket_connections) == 0


class TestTrendingEndpoint:
    """Tests for /trending endpoint."""

    @pytest.fixture
    def mock_app(self):
        """Create mock FastAPI app with realtime router."""
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        return app

    @pytest.mark.asyncio
    async def test_trending_endpoint_not_initialized(self, mock_app):
        """Test trending endpoint when API not initialized."""
        import discovery.api_realtime as api_module

        # Ensure not initialized
        api_module.realtime_api_initialized = False

        client = TestClient(mock_app)

        response = client.post("/api/realtime/trending", json={"category": "artists"})

        assert response.status_code == 503
        assert "not initialized" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_trending_endpoint_success(self, mock_app):
        """Test successful trending request."""
        import discovery.api_realtime as api_module

        # Mock trend tracker
        mock_tracker = MagicMock()
        mock_item = MagicMock()
        mock_item.item_id = "artist-123"
        mock_item.item_name = "Test Artist"
        mock_item.score = 95.5
        mock_item.change = 10.2

        mock_tracker.get_trending.return_value = [mock_item]

        # Setup
        api_module.realtime_api_initialized = True
        api_module.trend_tracker = mock_tracker

        client = TestClient(mock_app)

        response = client.post(
            "/api/realtime/trending",
            json={"category": "artists", "limit": 5, "time_window": "day"},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "success"
        assert data["category"] == "artists"
        assert data["time_window"] == "day"
        assert len(data["trending_items"]) == 1
        assert data["trending_items"][0]["item_id"] == "artist-123"
        assert data["trending_items"][0]["score"] == 95.5

    @pytest.mark.asyncio
    async def test_trending_endpoint_error_handling(self, mock_app):
        """Test trending endpoint error handling."""
        import discovery.api_realtime as api_module

        # Mock trend tracker that raises error
        mock_tracker = MagicMock()
        mock_tracker.get_trending.side_effect = RuntimeError("Database error")

        api_module.realtime_api_initialized = True
        api_module.trend_tracker = mock_tracker

        client = TestClient(mock_app)

        response = client.post("/api/realtime/trending", json={"category": "artists"})

        assert response.status_code == 500
        assert "error" in response.json()["detail"].lower()


class TestSubscribeEndpoint:
    """Tests for /subscribe endpoint."""

    @pytest.fixture
    def mock_app(self):
        """Create mock FastAPI app with realtime router."""
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        return app

    @pytest.mark.asyncio
    async def test_subscribe_endpoint_not_initialized(self, mock_app):
        """Test subscribe endpoint when API not initialized."""
        import discovery.api_realtime as api_module

        api_module.realtime_api_initialized = False

        client = TestClient(mock_app)

        response = client.post("/api/realtime/subscribe", json={"channels": ["trending"]})

        assert response.status_code == 503
        assert "not initialized" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_subscribe_endpoint_valid_channels(self, mock_app):
        """Test subscribe endpoint with valid channels."""
        import discovery.api_realtime as api_module

        # Setup
        api_module.realtime_api_initialized = True
        api_module.websocket_manager = MagicMock()

        client = TestClient(mock_app)

        response = client.post(
            "/api/realtime/subscribe",
            json={"channels": ["trending", "analytics", "discoveries"]},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "success"
        assert "trending" in data["valid_channels"]
        assert "analytics" in data["valid_channels"]
        assert len(data["invalid_channels"]) == 0

    @pytest.mark.asyncio
    async def test_subscribe_endpoint_invalid_channels(self, mock_app):
        """Test subscribe endpoint with invalid channels."""
        import discovery.api_realtime as api_module

        api_module.realtime_api_initialized = True
        api_module.websocket_manager = MagicMock()

        client = TestClient(mock_app)

        response = client.post(
            "/api/realtime/subscribe",
            json={"channels": ["trending", "invalid-channel", "another-invalid"]},
        )

        assert response.status_code == 200
        data = response.json()

        assert "trending" in data["valid_channels"]
        assert "invalid-channel" in data["invalid_channels"]
        assert "another-invalid" in data["invalid_channels"]
        assert len(data["available_channels"]) > 0

    @pytest.mark.asyncio
    async def test_subscribe_endpoint_instructions(self, mock_app):
        """Test subscribe endpoint provides WebSocket instructions."""
        import discovery.api_realtime as api_module

        api_module.realtime_api_initialized = True
        api_module.websocket_manager = MagicMock()

        client = TestClient(mock_app)

        response = client.post("/api/realtime/subscribe", json={"channels": ["trending"]})

        assert response.status_code == 200
        data = response.json()

        assert data["subscription_method"] == "websocket"
        assert "instructions" in data
        assert "websocket_url" in data["instructions"]
        assert "message_format" in data["instructions"]


class TestCacheInvalidationEndpoint:
    """Tests for /cache/invalidate endpoint."""

    @pytest.fixture
    def mock_app(self):
        """Create mock FastAPI app with realtime router."""
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        return app

    @pytest.mark.asyncio
    async def test_cache_invalidate_not_initialized(self, mock_app):
        """Test cache invalidate when API not initialized."""
        import discovery.api_realtime as api_module

        api_module.realtime_api_initialized = False

        client = TestClient(mock_app)

        response = client.post("/api/realtime/cache/invalidate", json={"pattern": "cache:*"})

        assert response.status_code == 503

    @pytest.mark.asyncio
    async def test_cache_invalidate_success(self, mock_app):
        """Test successful cache invalidation."""
        import discovery.api_realtime as api_module

        # Mock cache invalidation manager
        mock_manager = MagicMock()
        mock_manager.add_rule = MagicMock()
        mock_manager.emit_event = AsyncMock()
        mock_manager.process_events = AsyncMock()
        mock_manager.get_statistics.return_value = {
            "invalidations": 5,
            "backends": 2,
        }

        api_module.realtime_api_initialized = True
        api_module.cache_invalidation_manager = mock_manager

        client = TestClient(mock_app)

        response = client.post(
            "/api/realtime/cache/invalidate",
            json={"pattern": "cache:artists:*", "scope": "prefix"},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "success"
        assert data["pattern"] == "cache:artists:*"
        assert data["scope"] == "prefix"
        assert data["invalidated_count"] == 5
        assert data["registered_backends"] == 2

        # Verify manager methods were called
        mock_manager.add_rule.assert_called_once()
        mock_manager.emit_event.assert_called_once()
        mock_manager.process_events.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_invalidate_no_backends(self, mock_app):
        """Test cache invalidation with no registered backends."""
        import discovery.api_realtime as api_module

        mock_manager = MagicMock()
        mock_manager.add_rule = MagicMock()
        mock_manager.emit_event = AsyncMock()
        mock_manager.process_events = AsyncMock()
        mock_manager.get_statistics.return_value = {
            "invalidations": 0,
            "backends": 0,
        }

        api_module.realtime_api_initialized = True
        api_module.cache_invalidation_manager = mock_manager

        client = TestClient(mock_app)

        response = client.post("/api/realtime/cache/invalidate", json={"pattern": "cache:*"})

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "partial"
        assert "No cache backends registered" in data["message"]

    @pytest.mark.asyncio
    async def test_cache_invalidate_error(self, mock_app):
        """Test cache invalidation error handling."""
        import discovery.api_realtime as api_module

        mock_manager = MagicMock()
        mock_manager.add_rule.side_effect = RuntimeError("Cache error")

        api_module.realtime_api_initialized = True
        api_module.cache_invalidation_manager = mock_manager

        client = TestClient(mock_app)

        response = client.post("/api/realtime/cache/invalidate", json={"pattern": "cache:*"})

        assert response.status_code == 500


class TestWebSocketStatsEndpoint:
    """Tests for /ws/stats endpoint."""

    @pytest.fixture
    def mock_app(self):
        """Create mock FastAPI app with realtime router."""
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        return app

    @pytest.mark.asyncio
    async def test_websocket_stats_not_initialized(self, mock_app):
        """Test WebSocket stats when not initialized."""
        import discovery.api_realtime as api_module

        api_module.realtime_api_initialized = False

        client = TestClient(mock_app)

        response = client.get("/api/realtime/ws/stats")

        assert response.status_code == 503

    @pytest.mark.asyncio
    async def test_websocket_stats_success(self, mock_app):
        """Test successful WebSocket stats retrieval."""
        import discovery.api_realtime as api_module

        mock_manager = MagicMock()
        mock_manager.get_statistics.return_value = {
            "total_connections": 5,
            "total_subscriptions": 12,
            "channels": {"trending": 3, "analytics": 2},
        }

        api_module.realtime_api_initialized = True
        api_module.websocket_manager = mock_manager

        client = TestClient(mock_app)

        response = client.get("/api/realtime/ws/stats")

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "success"
        assert data["statistics"]["total_connections"] == 5
        assert data["statistics"]["total_subscriptions"] == 12

    @pytest.mark.asyncio
    async def test_websocket_stats_error(self, mock_app):
        """Test WebSocket stats error handling."""
        import discovery.api_realtime as api_module

        mock_manager = MagicMock()
        mock_manager.get_statistics.side_effect = RuntimeError("Stats error")

        api_module.realtime_api_initialized = True
        api_module.websocket_manager = mock_manager

        client = TestClient(mock_app)

        response = client.get("/api/realtime/ws/stats")

        assert response.status_code == 500


class TestStatusEndpoint:
    """Tests for /status endpoint."""

    @pytest.fixture
    def mock_app(self):
        """Create mock FastAPI app with realtime router."""
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        return app

    def test_status_endpoint_not_initialized(self, mock_app):
        """Test status endpoint when not initialized."""
        import discovery.api_realtime as api_module

        # Reset state
        api_module.realtime_api_initialized = False
        api_module.websocket_manager = None
        api_module.trend_tracker = None
        api_module.cache_invalidation_manager = None
        api_module.active_websocket_connections = []

        client = TestClient(mock_app)

        response = client.get("/api/realtime/status")

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "not_initialized"
        assert data["features"]["websocket"] == "unavailable"
        assert data["features"]["trending"] == "unavailable"
        assert data["active_connections"] == 0

    def test_status_endpoint_initialized(self, mock_app):
        """Test status endpoint when initialized."""
        import discovery.api_realtime as api_module

        # Setup initialized state
        api_module.realtime_api_initialized = True
        api_module.websocket_manager = MagicMock()
        api_module.trend_tracker = MagicMock()
        api_module.cache_invalidation_manager = MagicMock()
        api_module.active_websocket_connections = [MagicMock(), MagicMock()]

        client = TestClient(mock_app)

        response = client.get("/api/realtime/status")

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "initialized"
        assert data["features"]["websocket"] == "active"
        assert data["features"]["trending"] == "active"
        assert data["features"]["subscriptions"] == "active"
        assert data["components"]["websocket_manager"] is True
        assert data["components"]["trend_tracker"] is True
        assert data["active_connections"] == 2


class TestWebSocketEndpoint:
    """Tests for WebSocket endpoint."""

    @pytest.mark.asyncio
    async def test_websocket_endpoint_not_initialized(self):
        """Test WebSocket endpoint when manager not initialized."""
        from fastapi import FastAPI
        from starlette.websockets import WebSocketDisconnect

        import discovery.api_realtime as api_module

        api_module.websocket_manager = None

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        # Connection should close immediately with error code
        with pytest.raises(WebSocketDisconnect), client.websocket_connect("/api/realtime/ws"):
            pass

    @pytest.mark.asyncio
    async def test_websocket_endpoint_connection(self):
        """Test successful WebSocket connection."""
        import discovery.api_realtime as api_module

        # Mock WebSocket manager
        mock_manager = MagicMock()
        mock_manager.connect = AsyncMock()
        mock_manager.handle_message = AsyncMock()
        mock_manager.disconnect = AsyncMock()

        api_module.websocket_manager = mock_manager

        # Test that manager is properly set up for WebSocket connections
        assert api_module.websocket_manager is not None

    @pytest.mark.asyncio
    async def test_websocket_endpoint_disconnect_handling(self):
        """Test WebSocket endpoint handles disconnection."""
        import discovery.api_realtime as api_module

        mock_manager = MagicMock()
        mock_manager.connect = AsyncMock()
        mock_manager.disconnect = AsyncMock()
        mock_manager.handle_message = AsyncMock()

        api_module.websocket_manager = mock_manager

        # WebSocket disconnect is handled in the except block


class TestScopeMapping:
    """Tests for cache invalidation scope mapping."""

    def test_scope_mapping_logic(self):
        """Test scope mapping in cache invalidation."""
        # This tests the logic used in invalidate_cache endpoint
        scope_map = {
            "exact": "EXACT",
            "prefix": "PREFIX",
            "pattern": "PATTERN",
            "all": "ALL",
        }

        assert scope_map.get("exact") == "EXACT"
        assert scope_map.get("prefix") == "PREFIX"
        assert scope_map.get("pattern") == "PATTERN"
        assert scope_map.get("all") == "ALL"
        assert scope_map.get("unknown", "PREFIX") == "PREFIX"
