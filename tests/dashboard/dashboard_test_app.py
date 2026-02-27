"""Test application factory for dashboard E2E tests."""

import asyncio
from collections.abc import AsyncGenerator
import contextlib
from contextlib import asynccontextmanager
import logging
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from common import DashboardConfig


logger = logging.getLogger(__name__)


# Mock the dashboard app instance
mock_dashboard_app = None


class MockDashboardApp:
    """Mock dashboard application for testing."""

    def __init__(self) -> None:
        """Initialize mock dashboard."""
        self.config = DashboardConfig(
            amqp_connection="amqp://test:test@localhost:5672/",
            neo4j_address="neo4j://localhost:7687",
            neo4j_username="test",
            neo4j_password="test",  # noqa: S106
            postgres_address="localhost:5432",
            postgres_username="test",
            postgres_password="test",  # noqa: S106
            postgres_database="test",
            rabbitmq_username="test",
            rabbitmq_password="test",  # noqa: S106
        )
        self.websocket_connections: set[WebSocket] = set()
        self.latest_metrics: dict[str, Any] | None = None
        self.amqp_connection = AsyncMock()
        self.neo4j_driver = MagicMock()
        self.update_task: asyncio.Task[None] | None = None

    async def startup(self) -> None:
        """Mock startup."""
        # Start mock update task
        self.update_task = asyncio.create_task(self.mock_collect_metrics_loop())

    async def shutdown(self) -> None:
        """Mock shutdown."""
        if self.update_task:
            self.update_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.update_task

    async def mock_collect_metrics_loop(self) -> None:
        """Mock metrics collection loop."""
        while True:
            try:
                # Update mock metrics every 2 seconds
                self.latest_metrics = {
                    "services": [
                        {
                            "name": "extractor",
                            "status": "healthy",
                            "health_url": "http://localhost:8000/health",
                        },
                        {
                            "name": "graphinator",
                            "status": "healthy",
                            "health_url": "http://localhost:8001/health",
                        },
                        {
                            "name": "tableinator",
                            "status": "healthy",
                            "health_url": "http://localhost:8002/health",
                        },
                    ],
                    "queues": [
                        {
                            "name": "discogsography-graphinator-artists",
                            "messages": 10,
                            "messages_ready": 5,
                            "messages_unacknowledged": 2,
                            "consumers": 1,
                            "message_rate": 0.5,
                            "ack_rate": 0.3,
                        },
                        {
                            "name": "discogsography-tableinator-artists",
                            "messages": 8,
                            "messages_ready": 3,
                            "messages_unacknowledged": 1,
                            "consumers": 1,
                            "message_rate": 0.4,
                            "ack_rate": 0.2,
                        },
                    ],
                    "databases": [
                        {
                            "name": "PostgreSQL",
                            "status": "healthy",
                            "connection_count": "5",
                            "size": "100.5 MB",
                            "address": "localhost:5432",
                        },
                        {
                            "name": "Neo4j",
                            "status": "healthy",
                            "connection_count": "3",
                            "size": "50.2 MB",
                            "nodes": "1000",
                            "relationships": "5000",
                            "address": "neo4j://localhost:7687",
                        },
                    ],
                    "timestamp": "2024-01-01T00:00:00Z",
                }
                # Broadcast to all connected clients
                await self.broadcast_metrics(self.latest_metrics)
                await asyncio.sleep(2)
            except asyncio.CancelledError:
                break

    async def collect_all_metrics(self) -> dict[str, Any]:
        """Return mock metrics."""
        return self.latest_metrics or {
            "services": [],
            "queues": [],
            "databases": [],
            "timestamp": "2024-01-01T00:00:00Z",
        }

    async def broadcast_metrics(self, metrics: Any) -> None:
        """Mock broadcast to all WebSocket connections."""
        if not self.websocket_connections:
            return

        # Send metrics update to all connected clients
        message = {"type": "metrics_update", "data": metrics}

        disconnected = set()
        for ws in self.websocket_connections:
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.add(ws)

        # Remove disconnected clients
        self.websocket_connections -= disconnected


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """Manage test application lifecycle."""
    global mock_dashboard_app
    mock_dashboard_app = MockDashboardApp()
    await mock_dashboard_app.startup()
    yield
    await mock_dashboard_app.shutdown()


def create_test_app() -> FastAPI:
    """Create a test FastAPI app with mocked dependencies."""
    app = FastAPI(
        title="Discogsography Dashboard",
        version="0.1.0",
        default_response_class=JSONResponse,
        lifespan=lifespan,
    )

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Add API routes

    @app.get("/api/metrics")
    async def get_metrics() -> dict[str, Any]:
        """Get current system metrics."""
        if mock_dashboard_app:
            metrics = await mock_dashboard_app.collect_all_metrics()
            return metrics
        return {}

    @app.get("/api/services")
    async def get_services() -> list[dict[str, str]]:
        """Get service statuses."""
        if mock_dashboard_app and mock_dashboard_app.latest_metrics:
            services = mock_dashboard_app.latest_metrics.get("services", [])
            return list(services)  # Ensure we return a list
        return []

    @app.get("/api/queues")
    async def get_queues() -> list[dict[str, Any]]:
        """Get queue information."""
        if mock_dashboard_app and mock_dashboard_app.latest_metrics:
            queues = mock_dashboard_app.latest_metrics.get("queues", [])
            return list(queues)  # Ensure we return a list
        return []

    @app.get("/api/databases")
    async def get_databases() -> list[dict[str, str]]:
        """Get database information."""
        if mock_dashboard_app and mock_dashboard_app.latest_metrics:
            databases = mock_dashboard_app.latest_metrics.get("databases", [])
            return list(databases)  # Ensure we return a list
        return []

    @app.get("/metrics")
    async def prometheus_metrics() -> str:
        """Return Prometheus metrics."""
        return "# HELP dashboard_websocket_connections Number of active WebSocket connections\n"

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        """WebSocket endpoint for real-time updates."""
        await websocket.accept()
        logger.info("🔗 WebSocket connection accepted")
        if mock_dashboard_app:
            mock_dashboard_app.websocket_connections.add(websocket)
        try:
            # Send initial metrics update
            if mock_dashboard_app and mock_dashboard_app.latest_metrics:
                await websocket.send_json({"type": "metrics_update", "data": mock_dashboard_app.latest_metrics})
            # Keep connection alive
            while True:
                try:
                    data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                    logger.debug(f"📥 Received WebSocket data: {data}")
                except TimeoutError:
                    # Send ping to keep connection alive
                    await websocket.send_json({"type": "ping"})
        except Exception as e:
            logger.debug(f"🔌 WebSocket disconnected: {e}")
        finally:
            if mock_dashboard_app:
                mock_dashboard_app.websocket_connections.discard(websocket)

    # Configure static files
    static_dir = Path(__file__).parent.parent.parent / "dashboard" / "static"
    logger.info(f"📁 Static dir path: {static_dir}")
    logger.info(f"📁 Static dir exists: {static_dir.exists()}")

    if static_dir.exists():
        # Serve index.html at root
        @app.get("/", response_class=FileResponse)
        async def serve_index() -> FileResponse:
            """Serve the index.html file."""
            index_path = static_dir / "index.html"
            logger.info(f"📄 Serving index.html from: {index_path}")
            return FileResponse(str(index_path))

        # Serve static assets
        @app.get("/styles.css", response_class=FileResponse)
        async def serve_styles() -> FileResponse:
            """Serve the styles.css file."""
            return FileResponse(str(static_dir / "styles.css"))

        @app.get("/dashboard.js", response_class=FileResponse)
        async def serve_js() -> FileResponse:
            """Serve the dashboard.js file."""
            return FileResponse(str(static_dir / "dashboard.js"))

        # Mount static files for any additional assets
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    else:
        logger.error(f"❌ Static directory not found: {static_dir}")

    return app
