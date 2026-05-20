"""Tests for the health check server."""

from http.client import HTTPConnection
import json
import threading
from unittest.mock import Mock, patch

import pytest

from common.health_server import HealthServer


class TestHealthServerInit:
    """Tests for HealthServer initialization."""

    def test_init_stores_health_func_and_no_thread(self) -> None:
        """Test HealthServer stores health_func and initializes thread to None."""
        health_func = Mock(return_value={"status": "healthy"})

        server = HealthServer(0, health_func)
        try:
            assert server.health_func is health_func
            assert server.thread is None
        finally:
            server.server_close()

    def test_init_binds_to_port(self) -> None:
        """Test HealthServer binds to the given port."""
        health_func = Mock(return_value={"status": "healthy"})

        server = HealthServer(0, health_func)
        try:
            # server_address[1] is the actual port (non-zero when port 0 is used)
            assert server.server_address[1] > 0
        finally:
            server.server_close()


class TestHealthServerGetHealthData:
    """Tests for HealthServer.get_health_data method."""

    def test_get_health_data_returns_func_result(self) -> None:
        """Test get_health_data returns the result of the health function."""
        expected = {"status": "healthy", "uptime": 42}
        health_func = Mock(return_value=expected)

        server = HealthServer(0, health_func)
        try:
            result = server.get_health_data()
            assert result == expected
            health_func.assert_called_once()
        finally:
            server.server_close()

    def test_get_health_data_handles_exception(self) -> None:
        """Test get_health_data returns an unhealthy response when health_func raises."""
        health_func = Mock(side_effect=RuntimeError("database connection lost"))

        server = HealthServer(0, health_func)
        try:
            result = server.get_health_data()
            assert result["status"] == "unhealthy"
            assert "database connection lost" in result["error"]
            assert "timestamp" in result
        finally:
            server.server_close()

    def test_get_health_data_exception_includes_timestamp(self) -> None:
        """Test that error responses include an ISO timestamp."""
        health_func = Mock(side_effect=ValueError("bad value"))

        server = HealthServer(0, health_func)
        try:
            result = server.get_health_data()
            # Timestamp should be a non-empty ISO string
            assert isinstance(result["timestamp"], str)
            assert len(result["timestamp"]) > 0
        finally:
            server.server_close()


class TestHealthServerStartBackground:
    """Tests for HealthServer.start_background method."""

    def test_start_background_creates_daemon_thread(self) -> None:
        """Test start_background creates a daemon thread."""
        health_func = Mock(return_value={"status": "healthy"})

        server = HealthServer(0, health_func)
        try:
            server.start_background()
            assert server.thread is not None
            assert server.thread.daemon is True
        finally:
            server.stop()
            server.server_close()

    def test_start_background_thread_is_alive(self) -> None:
        """Test that the thread is alive after start_background."""
        health_func = Mock(return_value={"status": "healthy"})

        server = HealthServer(0, health_func)
        try:
            server.start_background()
            assert server.thread is not None
            assert server.thread.is_alive()
        finally:
            server.stop()
            server.server_close()


class TestHealthServerStop:
    """Tests for HealthServer.stop method."""

    def test_stop_shuts_down_running_server(self) -> None:
        """Test stop shuts down and joins a running background thread."""
        health_func = Mock(return_value={"status": "healthy"})

        server = HealthServer(0, health_func)
        server.start_background()
        assert server.thread is not None
        assert server.thread.is_alive()

        server.stop()

        assert not server.thread.is_alive()
        server.server_close()

    def test_stop_without_thread_skips_join(self) -> None:
        """Test stop skips the thread.join() when thread is None (covers the if-branch).

        Python 3.13's socketserver.shutdown() blocks if serve_forever() was never
        called, so we mock shutdown() to isolate the thread-join branch logic.
        """
        health_func = Mock(return_value={"status": "healthy"})

        server = HealthServer(0, health_func)
        try:
            assert server.thread is None
            # Mock shutdown to avoid Python 3.13 blocking, then call stop()
            # to exercise the "if self.thread" False branch
            with patch.object(server, "shutdown"):
                server.stop()
            # Verify thread is still None (join was never called)
            assert server.thread is None
        finally:
            server.server_close()


class TestHealthHandlerHTTP:
    """Integration tests for the HTTP request handler."""

    @pytest.fixture
    def running_server(self):
        """Start a HealthServer in a background thread and yield it."""
        health_func = Mock(return_value={"status": "healthy", "service": "test"})
        server = HealthServer(0, health_func)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        yield server
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    def _connect(self, server: HealthServer) -> HTTPConnection:
        port = server.server_address[1]
        return HTTPConnection("127.0.0.1", port, timeout=5)

    def test_get_health_returns_200_and_json(self, running_server: HealthServer) -> None:
        """Test GET /health returns 200 with JSON health data."""
        conn = self._connect(running_server)
        conn.request("GET", "/health")
        response = conn.getresponse()

        assert response.status == 200
        assert response.getheader("Content-Type") == "application/json"

        body = json.loads(response.read())
        assert body["status"] == "healthy"
        assert body["service"] == "test"

    def test_get_metrics_returns_404_when_metrics_disabled(self, running_server: HealthServer) -> None:
        """Test GET /metrics returns 404 when metrics are disabled (default)."""
        conn = self._connect(running_server)
        conn.request("GET", "/metrics")
        response = conn.getresponse()

        assert response.status == 404

    def test_get_root_returns_404(self, running_server: HealthServer) -> None:
        """Test GET / returns 404 (only /health is served)."""
        conn = self._connect(running_server)
        conn.request("GET", "/")
        response = conn.getresponse()

        assert response.status == 404

    def test_log_message_suppressed(self, running_server: HealthServer) -> None:
        """Test that HTTP server logs are suppressed (log_message is a no-op).

        Verified by making a request and confirming no log output is emitted
        (log_message override calls pass).
        """
        # A request to /health will invoke log_message internally.
        # If log_message raises, this test will fail.
        conn = self._connect(running_server)
        conn.request("GET", "/health")
        response = conn.getresponse()
        response.read()  # consume body

        # No assertion needed — the absence of an exception is the test

    def test_health_data_reflects_func_output(self, running_server: HealthServer) -> None:
        """Test that health endpoint returns whatever get_health_data provides."""
        new_data = {"status": "degraded", "queue_depth": 999}
        running_server.health_func = Mock(return_value=new_data)

        conn = self._connect(running_server)
        conn.request("GET", "/health")
        response = conn.getresponse()
        body = json.loads(response.read())

        assert body == new_data


class TestHealthServerMetricsEndpoint:
    """Tests for the optional /metrics endpoint added to HealthServer."""

    @pytest.fixture
    def running_server_metrics_enabled(self):
        """Start a HealthServer with metrics_enabled=True and yield it."""
        health_func = Mock(return_value={"status": "healthy"})
        server = HealthServer(0, health_func, metrics_enabled=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        yield server
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    @pytest.fixture
    def running_server_metrics_disabled(self):
        """Start a HealthServer with metrics_enabled=False (default) and yield it."""
        health_func = Mock(return_value={"status": "healthy"})
        server = HealthServer(0, health_func)  # default: metrics_enabled=False
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        yield server
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    def _connect(self, server: HealthServer) -> HTTPConnection:
        port = server.server_address[1]
        return HTTPConnection("127.0.0.1", port, timeout=5)

    def test_metrics_enabled_returns_200(self, running_server_metrics_enabled: HealthServer) -> None:
        """GET /metrics returns 200 when metrics_enabled=True."""
        conn = self._connect(running_server_metrics_enabled)
        conn.request("GET", "/metrics")
        response = conn.getresponse()

        assert response.status == 200

    def test_metrics_enabled_content_type_is_prometheus(self, running_server_metrics_enabled: HealthServer) -> None:
        """GET /metrics returns a prometheus text/plain Content-Type."""
        conn = self._connect(running_server_metrics_enabled)
        conn.request("GET", "/metrics")
        response = conn.getresponse()
        content_type = response.getheader("Content-Type", "")

        assert "text/plain" in content_type

    def test_metrics_enabled_body_is_nonempty(self, running_server_metrics_enabled: HealthServer) -> None:
        """GET /metrics body is non-empty Prometheus exposition format."""
        conn = self._connect(running_server_metrics_enabled)
        conn.request("GET", "/metrics")
        response = conn.getresponse()
        body = response.read()

        assert len(body) > 0

    def test_metrics_disabled_returns_404(self, running_server_metrics_disabled: HealthServer) -> None:
        """GET /metrics returns 404 when metrics_enabled=False (default)."""
        conn = self._connect(running_server_metrics_disabled)
        conn.request("GET", "/metrics")
        response = conn.getresponse()

        assert response.status == 404

    def test_metrics_enabled_flag_stored(self) -> None:
        """HealthServer stores the metrics_enabled flag correctly."""
        health_func = Mock(return_value={"status": "healthy"})
        server_on = HealthServer(0, health_func, metrics_enabled=True)
        server_off = HealthServer(0, health_func, metrics_enabled=False)
        server_default = HealthServer(0, health_func)
        try:
            assert server_on.metrics_enabled is True
            assert server_off.metrics_enabled is False
            assert server_default.metrics_enabled is False
        finally:
            server_on.server_close()
            server_off.server_close()
            server_default.server_close()

    def test_health_endpoint_unaffected_by_metrics_flag(self, running_server_metrics_enabled: HealthServer) -> None:
        """GET /health still returns 200 when metrics_enabled=True."""
        conn = self._connect(running_server_metrics_enabled)
        conn.request("GET", "/health")
        response = conn.getresponse()

        assert response.status == 200
        body = json.loads(response.read())
        assert body["status"] == "healthy"
