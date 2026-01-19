"""Simple health check server for monitoring services."""

from collections.abc import Callable
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
from threading import Thread
from typing import Any


logger = logging.getLogger(__name__)


class HealthHandler(BaseHTTPRequestHandler):
    """HTTP request handler for health checks."""

    def do_GET(self) -> None:
        """Handle GET requests."""
        if self.path == "/health":
            # Get health data from the server instance
            health_data = self.server.get_health_data()  # type: ignore

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(health_data).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default HTTP logging."""
        pass


class HealthServer(HTTPServer):
    """HTTP server with health check endpoint."""

    def __init__(self, port: int, health_func: Callable[[], dict[str, Any]]):
        """Initialize health server.

        Args:
            port: Port to listen on
            health_func: Function that returns current health data
        """
        super().__init__(("0.0.0.0", port), HealthHandler)  # noqa: S104  # nosec B104
        self.health_func = health_func
        self.thread: Thread | None = None

    def get_health_data(self) -> dict[str, Any]:
        """Get current health data."""
        try:
            return self.health_func()
        except Exception as e:
            logger.error(f"❌ Error getting health data: {e}")
            return {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.now(UTC).isoformat(),
            }

    def start_background(self) -> None:
        """Start server in background thread."""

        def run_server() -> None:
            logger.info(f"🏥 Health server listening on port {self.server_port}")
            self.serve_forever()

        self.thread = Thread(target=run_server, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        """Stop the health server."""
        self.shutdown()
        if self.thread:
            self.thread.join(timeout=5)
