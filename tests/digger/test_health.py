"""Tests for digger health data and the HealthServer /metrics endpoint."""

from http.client import HTTPConnection
import threading

import pytest

from common.health_server import HealthServer
from digger.health import get_health_data


class TestGetHealthData:
    """Unit tests for digger get_health_data()."""

    def test_returns_status_ok(self) -> None:
        """get_health_data returns status 'ok'."""
        result = get_health_data()
        assert result["status"] == "ok"

    def test_returns_service_name(self) -> None:
        """get_health_data includes service='digger'."""
        result = get_health_data()
        assert result["service"] == "digger"

    def test_returns_timestamp(self) -> None:
        """get_health_data includes a non-empty ISO timestamp."""
        result = get_health_data()
        assert "timestamp" in result
        assert isinstance(result["timestamp"], str)
        assert len(result["timestamp"]) > 0

    def test_returns_dict(self) -> None:
        """get_health_data return value is a dict."""
        result = get_health_data()
        assert isinstance(result, dict)


class TestHealthServerMetricsEndpoint:
    """Integration tests for the /metrics endpoint on HealthServer."""

    @pytest.fixture
    def running_server_metrics_enabled(self):
        """Start a HealthServer with metrics_enabled=True and yield it."""
        server = HealthServer(0, get_health_data, metrics_enabled=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        yield server
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    @pytest.fixture
    def running_server_metrics_disabled(self):
        """Start a HealthServer with metrics_enabled=False (default) and yield it."""
        server = HealthServer(0, get_health_data, metrics_enabled=False)
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
        """GET /metrics returns prometheus text/plain content type."""
        conn = self._connect(running_server_metrics_enabled)
        conn.request("GET", "/metrics")
        response = conn.getresponse()
        content_type = response.getheader("Content-Type", "")
        assert "text/plain" in content_type

    def test_metrics_enabled_body_contains_prometheus_text(self, running_server_metrics_enabled: HealthServer) -> None:
        """GET /metrics body contains Prometheus metrics text (process or digger metrics)."""
        conn = self._connect(running_server_metrics_enabled)
        conn.request("GET", "/metrics")
        response = conn.getresponse()
        body = response.read().decode()
        # Standard process metrics are always present in the default registry
        assert "process_" in body or "python_" in body or "digger_" in body

    def test_metrics_disabled_returns_404(self, running_server_metrics_disabled: HealthServer) -> None:
        """GET /metrics returns 404 when metrics_enabled=False (default)."""
        conn = self._connect(running_server_metrics_disabled)
        conn.request("GET", "/metrics")
        response = conn.getresponse()
        assert response.status == 404

    def test_health_still_works_when_metrics_enabled(self, running_server_metrics_enabled: HealthServer) -> None:
        """GET /health returns 200 and status=ok even when metrics are enabled."""
        import json

        conn = self._connect(running_server_metrics_enabled)
        conn.request("GET", "/health")
        response = conn.getresponse()
        assert response.status == 200
        body = json.loads(response.read())
        assert body["status"] == "ok"
