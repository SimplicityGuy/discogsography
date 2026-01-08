"""Tests for the common health server module."""

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from common.health_server import HealthServer


class TestHealthServer:
    """Test the HealthServer class."""

    @pytest.fixture
    def test_health_func(self) -> Callable[[], dict[str, Any]]:
        """Create a test health function."""

        def health_func() -> dict[str, Any]:
            return {
                "status": "healthy",
                "service": "test_service",
                "timestamp": "2023-01-01T00:00:00Z",
            }

        return health_func

    @pytest.fixture
    def health_server(self, test_health_func: Callable[[], dict[str, Any]]) -> HealthServer:
        """Create a HealthServer instance for testing."""
        return HealthServer(port=8999, health_func=test_health_func)

    def test_health_server_init(self, health_server: HealthServer, test_health_func: Callable[[], dict[str, Any]]) -> None:
        """Test HealthServer initialization."""
        assert health_server.server_port == 8999
        assert health_server.health_func == test_health_func
        assert health_server.thread is None

    def test_get_health_data_success(self, health_server: HealthServer) -> None:
        """Test successful health data retrieval."""
        health_data = health_server.get_health_data()

        assert health_data["status"] == "healthy"
        assert health_data["service"] == "test_service"
        assert health_data["timestamp"] == "2023-01-01T00:00:00Z"

    def test_get_health_data_exception(self) -> None:
        """Test health data retrieval when health function raises exception."""

        def failing_health_func() -> dict[str, Any]:
            raise ValueError("Service unavailable")

        server = HealthServer(port=8999, health_func=failing_health_func)
        health_data = server.get_health_data()

        assert health_data["status"] == "unhealthy"
        assert health_data["error"] == "Service unavailable"
        assert "timestamp" in health_data

    def test_start_background_thread(self, health_server: HealthServer) -> None:
        """Test starting server in background thread."""
        with (
            patch.object(health_server, "serve_forever"),
            patch.object(health_server, "shutdown") as mock_shutdown,
        ):
            health_server.start_background()

            # Verify thread was created and started
            assert health_server.thread is not None
            assert health_server.thread.daemon is True

            # Stop the server to clean up (mocked to avoid hanging)
            health_server.stop()
            mock_shutdown.assert_called_once()

    def test_stop_server(self, health_server: HealthServer) -> None:
        """Test stopping the health server."""
        # Mock the shutdown method and thread
        with patch.object(health_server, "shutdown") as mock_shutdown:
            mock_thread = MagicMock()
            health_server.thread = mock_thread

            health_server.stop()

            mock_shutdown.assert_called_once()
            mock_thread.join.assert_called_once_with(timeout=5)

    def test_stop_server_no_thread(self, health_server: HealthServer) -> None:
        """Test stopping server when no thread exists."""
        health_server.thread = None

        with patch.object(health_server, "shutdown") as mock_shutdown:
            health_server.stop()
            mock_shutdown.assert_called_once()

    def test_custom_port_and_health_func(self) -> None:
        """Test creating health server with custom parameters."""

        def custom_health() -> dict[str, Any]:
            return {"status": "custom", "port": 9000}

        custom_server = HealthServer(port=9000, health_func=custom_health)

        assert custom_server.server_port == 9000
        assert custom_server.health_func == custom_health

        health_data = custom_server.get_health_data()
        assert health_data["status"] == "custom"
        assert health_data["port"] == 9000


class TestHealthHandler:
    """Test the HealthHandler class."""

    def test_log_message_suppressed(self) -> None:
        """Test that log messages are suppressed."""
        from common.health_server import HealthHandler

        # Test the log_message method directly without creating an instance
        # Create a dummy instance just to get the method
        class TestHandler(HealthHandler):
            def __init__(self) -> None:
                # Don't call super().__init__ to avoid HTTP parsing
                pass

        handler = TestHandler()

        # This should not raise any exceptions and should do nothing
        handler.log_message("Test message: %s", "test")
        # If we get here without exception, the test passes
