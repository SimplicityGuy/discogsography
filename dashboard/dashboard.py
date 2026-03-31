#!/usr/bin/env python3
"""Dashboard service for monitoring discogsography components."""

import asyncio
from collections.abc import AsyncGenerator
import contextlib
from contextlib import asynccontextmanager
from datetime import UTC, datetime
import logging
import os
from pathlib import Path
from typing import cast

from fastapi import FastAPI, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import httpx
import orjson
from prometheus_client import REGISTRY, Counter, Gauge, generate_latest
from pydantic import BaseModel
import uvicorn

from common import (
    AsyncResilientNeo4jDriver,
    AsyncResilientPostgreSQL,
    AsyncResilientRabbitMQ,
    get_config,
    setup_logging,
)
from dashboard.admin_proxy import configure as configure_admin_proxy, router as admin_router


logger = logging.getLogger(__name__)

# CORS origins configurable via environment variable (comma-separated list)
_cors_origins_raw = os.environ.get("CORS_ORIGINS", "")
_cors_origins = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()] if _cors_origins_raw else None


# Metrics — guarded against duplicate registration on hot reload
def _get_or_create_gauge(name: str, description: str) -> Gauge:
    try:
        return Gauge(name, description)
    except ValueError:
        return cast("Gauge", REGISTRY._names_to_collectors[name])


def _get_or_create_counter(name: str, description: str, labels: list[str]) -> Counter:
    try:
        return Counter(name, description, labels)
    except ValueError:
        return cast("Counter", REGISTRY._names_to_collectors[name + "_total"])


WEBSOCKET_CONNECTIONS = _get_or_create_gauge("dashboard_websocket_connections", "Number of active WebSocket connections")
API_REQUESTS = _get_or_create_counter("dashboard_api_requests", "Total API requests", ["endpoint", "method"])


class ServiceStatus(BaseModel):
    """Model for service status information."""

    name: str
    status: str  # healthy, unhealthy, unknown, starting, extracting
    last_seen: datetime | None
    current_task: str | None
    progress: float | None  # 0.0 to 1.0
    error: str | None
    extraction_progress: dict[str, int] | None = None  # extractor only: per-type counts + total
    last_extraction_time: dict[str, float | None] | None = None  # extractor only: seconds since last activity


class QueueInfo(BaseModel):
    """Model for RabbitMQ queue information."""

    name: str
    messages: int
    messages_ready: int
    messages_unacknowledged: int
    consumers: int
    message_rate: float  # messages per second
    ack_rate: float  # acknowledgments per second


class DatabaseInfo(BaseModel):
    """Model for database information."""

    name: str
    status: str
    connection_count: int
    size: str | None
    error: str | None


class PipelineMetrics(BaseModel):
    """Metrics for a single data pipeline (Discogs or MusicBrainz)."""

    services: list[ServiceStatus]
    queues: list[QueueInfo]


class SystemMetrics(BaseModel):
    """Model for system-wide metrics."""

    pipelines: dict[str, PipelineMetrics]
    databases: list[DatabaseInfo]
    timestamp: datetime


PIPELINE_CONFIGS: dict[str, dict] = {
    "discogs": {
        "services": [
            ("extractor-discogs", "http://extractor-discogs:8000/health"),
            ("graphinator", "http://graphinator:8001/health"),
            ("tableinator", "http://tableinator:8002/health"),
        ],
        "queue_prefix": "discogsography",
        "entity_types": ["masters", "releases", "artists", "labels"],
    },
    "musicbrainz": {
        "services": [
            ("extractor-musicbrainz", "http://extractor-musicbrainz:8000/health"),
            ("brainzgraphinator", "http://brainzgraphinator:8011/health"),
            ("brainztableinator", "http://brainztableinator:8010/health"),
        ],
        "queue_prefix": "musicbrainz",
        "entity_types": ["artists", "labels", "release-groups", "releases"],
    },
}


class DashboardApp:
    """Main dashboard application."""

    def __init__(self) -> None:
        """Initialize the dashboard application."""
        self.config = get_config()
        self.websocket_connections: set[WebSocket] = set()
        self.latest_metrics: SystemMetrics | None = None
        self.rabbitmq: AsyncResilientRabbitMQ | None = None
        self.neo4j_driver: AsyncResilientNeo4jDriver | None = None
        self.postgres_conn: AsyncResilientPostgreSQL | None = None
        self.update_task: asyncio.Task | None = None

    async def startup(self) -> None:
        """Initialize connections on startup."""
        try:
            # Initialize resilient RabbitMQ connection
            self.rabbitmq = AsyncResilientRabbitMQ(connection_url=self.config.amqp_connection, heartbeat=600, connection_attempts=10, retry_delay=5.0)
            await self.rabbitmq.connect()
            logger.info("🐰 Connected to RabbitMQ with resilient connection")

            # Initialize resilient Neo4j driver
            self.neo4j_driver = AsyncResilientNeo4jDriver(
                uri=self.config.neo4j_host,
                auth=(self.config.neo4j_username, self.config.neo4j_password),
                max_retries=5,
                encrypted=False,
            )
            logger.info("🔗 Connected to Neo4j with resilient driver")

            # Initialize resilient PostgreSQL connection
            # Parse host and port from address
            if ":" in self.config.postgres_host:
                host, port_str = self.config.postgres_host.split(":", 1)
                port = int(port_str)
            else:
                host = self.config.postgres_host
                port = 5432

            self.postgres_conn = AsyncResilientPostgreSQL(
                connection_params={
                    "host": host,
                    "port": port,
                    "dbname": self.config.postgres_database,
                    "user": self.config.postgres_username,
                    "password": self.config.postgres_password,
                },
                max_retries=5,
            )
            logger.info("🐘 Connected to PostgreSQL with resilient connection")

            # Start background metrics collection
            self.update_task = asyncio.create_task(self.collect_metrics_loop())
            logger.info("📊 Started metrics collection")

        except Exception as e:
            logger.error(f"❌ Startup error: {e}")
            raise

    async def shutdown(self) -> None:
        """Clean up connections on shutdown."""
        try:
            # Cancel update task
            if self.update_task:
                self.update_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self.update_task

            # Close connections
            if self.rabbitmq:
                await self.rabbitmq.close()
            if self.neo4j_driver:
                await self.neo4j_driver.close()
            if self.postgres_conn:
                await self.postgres_conn.close()

            # Close all websocket connections
            for ws in self.websocket_connections:
                await ws.close()

            logger.info("✅ Shutdown complete")

        except Exception as e:
            logger.error(f"❌ Shutdown error: {e}")

    async def collect_metrics_loop(self) -> None:
        """Continuously collect metrics in the background."""
        while True:
            try:
                metrics = await self.collect_all_metrics()
                self.latest_metrics = metrics

                # Broadcast to all connected websockets
                await self.broadcast_metrics(metrics)

                await asyncio.sleep(2)  # Update every 2 seconds

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ Error collecting metrics: {e}")
                await asyncio.sleep(5)

    async def collect_all_metrics(self) -> SystemMetrics:
        """Collect all system metrics grouped by pipeline."""
        pipelines: dict[str, PipelineMetrics] = {}

        for pipeline_name, config in PIPELINE_CONFIGS.items():
            services = await self.get_service_statuses(config["services"])
            queues = await self.get_queue_info(config["queue_prefix"])
            # Auto-detect: include pipeline only if at least one service is reachable
            if any(s.status != "unknown" for s in services):
                pipelines[pipeline_name] = PipelineMetrics(services=services, queues=queues)

        databases = await self.get_database_info()

        return SystemMetrics(
            pipelines=pipelines,
            databases=databases,
            timestamp=datetime.now(UTC),
        )

    async def get_service_statuses(self, service_configs: list[tuple[str, str]]) -> list[ServiceStatus]:
        """Get status of all services."""
        services = []

        async with httpx.AsyncClient(timeout=5.0) as client:
            for name, url in service_configs:
                try:
                    response = await client.get(url)
                    if response.status_code == 200:
                        data = response.json()
                        # Use actual status from service health response
                        # Valid statuses: healthy, unhealthy, starting
                        service_status = data.get("status", "healthy")
                        services.append(
                            ServiceStatus(
                                name=name,
                                status=service_status,
                                last_seen=datetime.now(UTC),
                                current_task=data.get("current_task"),
                                progress=data.get("progress"),
                                error=None,
                                extraction_progress=data.get("extraction_progress"),
                                last_extraction_time=data.get("last_extraction_time"),
                            )
                        )
                    else:
                        services.append(
                            ServiceStatus(
                                name=name,
                                status="unhealthy",
                                last_seen=datetime.now(UTC),
                                current_task=None,
                                progress=None,
                                error=f"HTTP {response.status_code}",
                            )
                        )
                except Exception as e:
                    services.append(
                        ServiceStatus(
                            name=name,
                            status="unknown",
                            last_seen=None,
                            current_task=None,
                            progress=None,
                            error=str(e),
                        )
                    )

        return services

    async def get_queue_info(self, prefix: str) -> list[QueueInfo]:
        """Get RabbitMQ queue information."""
        queues: list[QueueInfo] = []

        try:
            if not self.rabbitmq:
                return queues

            async with httpx.AsyncClient(timeout=5.0) as client:
                # Use RabbitMQ management API with credentials from config
                response = await client.get(
                    "http://rabbitmq:15672/api/queues",
                    auth=(self.config.rabbitmq_username, self.config.rabbitmq_password),
                )

                if response.status_code == 200:
                    queue_data = response.json()
                    for queue in queue_data:
                        if queue["name"].startswith(prefix):
                            queues.append(
                                QueueInfo(
                                    name=queue["name"],
                                    messages=queue.get("messages", 0),
                                    messages_ready=queue.get("messages_ready", 0),
                                    messages_unacknowledged=queue.get("messages_unacknowledged", 0),
                                    consumers=queue.get("consumers", 0),
                                    message_rate=queue.get("message_stats", {}).get("publish_details", {}).get("rate", 0.0),
                                    ack_rate=queue.get("message_stats", {}).get("ack_details", {}).get("rate", 0.0),
                                )
                            )
                elif response.status_code == 401:
                    logger.warning("⚠️ RabbitMQ management API authentication failed. Queue metrics unavailable.")
                else:
                    logger.warning(f"⚠️ RabbitMQ management API returned status {response.status_code}")

        except httpx.ConnectError:
            logger.debug("🐰 RabbitMQ management API unreachable. This is normal if RabbitMQ is not running.")
        except Exception as e:
            logger.error(f"❌ Error getting queue info: {e}")

        return queues

    async def get_database_info(self) -> list[DatabaseInfo]:
        """Get database information."""
        databases = []

        # Check PostgreSQL
        conn = None
        try:
            if self.postgres_conn is None:
                raise RuntimeError("PostgreSQL resilient connection not initialized")
            conn = await self.postgres_conn.get_connection()
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT COUNT(*) FROM pg_stat_activity WHERE datname = %s",
                    (self.config.postgres_database,),
                )
                result = await cur.fetchone()
                connection_count = result[0] if result else 0

                await cur.execute(
                    "SELECT pg_database_size(%s)",
                    (self.config.postgres_database,),
                )
                result = await cur.fetchone()
                raw_bytes = result[0] if result else 0
                if raw_bytes >= 1024**3:
                    gb = raw_bytes / 1024**3
                    db_size = f"{gb:,.2f} GB"
                else:
                    mb = raw_bytes / 1024**2
                    db_size = f"{mb:,.0f} MB"

            databases.append(
                DatabaseInfo(
                    name="PostgreSQL",
                    status="healthy",
                    connection_count=connection_count,
                    size=db_size,
                    error=None,
                )
            )
        except Exception as e:
            databases.append(
                DatabaseInfo(
                    name="PostgreSQL",
                    status="unhealthy",
                    connection_count=0,
                    size=None,
                    error=str(e),
                )
            )
        finally:
            if conn is not None:
                with contextlib.suppress(Exception):
                    await conn.rollback()
                with contextlib.suppress(Exception):
                    await conn.close()

        # Check Neo4j
        try:
            if self.neo4j_driver:
                async with self.neo4j_driver.session() as session:
                    result = await session.run("CALL dbms.components() YIELD name, versions")
                    await result.single()
                    await result.consume()

                    # Get database size — fall back to basic count if APOC is not installed
                    try:
                        result = await session.run("CALL apoc.meta.stats() YIELD nodeCount, relCount")
                        stats = await result.single()
                        node_count = stats["nodeCount"] if stats else 0
                        rel_count = stats["relCount"] if stats else 0
                    except Exception:
                        result = await session.run("MATCH (n) RETURN count(n) AS cnt")
                        stats = await result.single()
                        node_count = stats["cnt"] if stats else 0
                        rel_count = 0

                databases.append(
                    DatabaseInfo(
                        name="Neo4j",
                        status="healthy",
                        connection_count=1,  # Neo4j doesn't expose this easily
                        size=f"{node_count:,} nodes, {rel_count:,} relationships",
                        error=None,
                    )
                )
        except Exception as e:
            databases.append(
                DatabaseInfo(
                    name="Neo4j",
                    status="unhealthy",
                    connection_count=0,
                    size=None,
                    error=str(e),
                )
            )

        return databases

    async def broadcast_metrics(self, metrics: SystemMetrics) -> None:
        """Broadcast metrics to all connected websockets."""
        if not self.websocket_connections:
            return

        message = orjson.dumps(
            {
                "type": "metrics_update",
                "data": metrics.model_dump(mode="json"),
            }
        ).decode()

        disconnected = set()
        for websocket in list(self.websocket_connections):
            try:
                await websocket.send_text(message)
            except Exception:
                disconnected.add(websocket)

        # Remove disconnected websockets
        self.websocket_connections -= disconnected
        WEBSOCKET_CONNECTIONS.set(len(self.websocket_connections))


# Create the dashboard app instance
dashboard: DashboardApp | None = None


# Create FastAPI app with lifespan
@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """Manage application lifecycle."""
    logger.info("🚀 Starting Dashboard service...")

    global dashboard
    dashboard = DashboardApp()
    await dashboard.startup()
    yield
    await dashboard.shutdown()


app = FastAPI(
    title="Discogsography Dashboard",
    version="0.1.0",
    default_response_class=JSONResponse,
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or ["http://localhost:3000", "http://localhost:8003"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check() -> JSONResponse:
    """Health check endpoint for Docker and monitoring."""
    return JSONResponse(
        content={
            "status": "healthy",
            "service": "dashboard",
            "timestamp": datetime.now(UTC).isoformat(),
            "uptime": "running",
        }
    )


@app.get("/api/metrics")
async def get_metrics() -> JSONResponse:
    """Get current system metrics."""
    API_REQUESTS.labels(endpoint="/api/metrics", method="GET").inc()

    if dashboard and dashboard.latest_metrics:
        return JSONResponse(content=dashboard.latest_metrics.model_dump(mode="json"))
    elif dashboard:
        # Collect metrics on demand if not available
        metrics = await dashboard.collect_all_metrics()
        return JSONResponse(content=metrics.model_dump(mode="json"))
    else:
        return JSONResponse(content={})


@app.get("/api/services")
async def get_services() -> JSONResponse:
    """Get service statuses grouped by pipeline."""
    API_REQUESTS.labels(endpoint="/api/services", method="GET").inc()
    if not dashboard:
        return JSONResponse(content={})
    result = {}
    for pipeline_name, config in PIPELINE_CONFIGS.items():
        services = await dashboard.get_service_statuses(config["services"])
        if any(s.status != "unknown" for s in services):
            result[pipeline_name] = [s.model_dump(mode="json") for s in services]
    return JSONResponse(content=result)


@app.get("/api/queues")
async def get_queues() -> JSONResponse:
    """Get queue information grouped by pipeline."""
    API_REQUESTS.labels(endpoint="/api/queues", method="GET").inc()
    if not dashboard:
        return JSONResponse(content={})
    result = {}
    for pipeline_name, config in PIPELINE_CONFIGS.items():
        queues = await dashboard.get_queue_info(config["queue_prefix"])
        if queues:
            result[pipeline_name] = [q.model_dump(mode="json") for q in queues]
    return JSONResponse(content=result)


@app.get("/api/databases")
async def get_databases() -> JSONResponse:
    """Get database information."""
    API_REQUESTS.labels(endpoint="/api/databases", method="GET").inc()
    if not dashboard:
        return JSONResponse(content=[])
    databases = await dashboard.get_database_info()
    return JSONResponse(content=[d.model_dump(mode="json") for d in databases])


@app.get("/metrics")
async def prometheus_metrics() -> Response:
    """Expose Prometheus metrics."""
    return Response(content=generate_latest(), media_type="text/plain")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time updates."""
    await websocket.accept()
    if dashboard:
        dashboard.websocket_connections.add(websocket)
        WEBSOCKET_CONNECTIONS.set(len(dashboard.websocket_connections))

    try:
        # Send initial metrics
        if dashboard and dashboard.latest_metrics:
            await websocket.send_text(
                orjson.dumps(
                    {
                        "type": "metrics_update",
                        "data": dashboard.latest_metrics.model_dump(mode="json"),
                    }
                ).decode()
            )

        # Keep connection alive
        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        if dashboard:
            dashboard.websocket_connections.discard(websocket)
            WEBSOCKET_CONNECTIONS.set(len(dashboard.websocket_connections))
    except Exception as e:
        logger.error(f"❌ WebSocket error: {e}")
        if dashboard:
            dashboard.websocket_connections.discard(websocket)
            WEBSOCKET_CONNECTIONS.set(len(dashboard.websocket_connections))


# Admin proxy routes (must be before StaticFiles catch-all)
# Note: reads env vars at import time; this is acceptable because
# Docker containers set env vars before module import.
_admin_api_host = os.getenv("API_HOST", "api")
_admin_api_port = int(os.getenv("API_PORT", "8004"))
configure_admin_proxy(_admin_api_host, _admin_api_port)
app.include_router(admin_router)


@app.get("/admin")
async def serve_admin() -> HTMLResponse:
    """Serve admin page directly to avoid StaticFiles routing issues."""
    admin_path = Path(__file__).parent / "static" / "admin.html"
    return HTMLResponse(admin_path.read_text())


# Mount static files for the UI
static_dir = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")


def main() -> None:  # pragma: no cover
    """Entry point for the Dashboard service."""
    setup_logging("dashboard", log_file=Path("/logs/dashboard.log"))
    # fmt: off
    print("██████╗ ██╗███████╗ ██████╗ ██████╗  ██████╗ ███████╗                      ")
    print("██╔══██╗██║██╔════╝██╔════╝██╔═══██╗██╔════╝ ██╔════╝                      ")
    print("██║  ██║██║███████╗██║     ██║   ██║██║  ███╗███████╗                      ")
    print("██║  ██║██║╚════██║██║     ██║   ██║██║   ██║╚════██║                      ")
    print("██████╔╝██║███████║╚██████╗╚██████╔╝╚██████╔╝███████║                      ")
    print("╚═════╝ ╚═╝╚══════╝ ╚═════╝ ╚═════╝  ╚═════╝ ╚══════╝                      ")
    print("                                                                           ")
    print("██████╗  █████╗ ███████╗██╗  ██╗██████╗  ██████╗  █████╗ ██████╗ ██████╗   ")
    print("██╔══██╗██╔══██╗██╔════╝██║  ██║██╔══██╗██╔═══██╗██╔══██╗██╔══██╗██╔══██╗  ")
    print("██║  ██║███████║███████╗███████║██████╔╝██║   ██║███████║██████╔╝██║  ██║  ")
    print("██║  ██║██╔══██║╚════██║██╔══██║██╔══██╗██║   ██║██╔══██║██╔══██╗██║  ██║  ")
    print("██████╔╝██║  ██║███████║██║  ██║██████╔╝╚██████╔╝██║  ██║██║  ██║██████╔╝  ")
    print("╚═════╝ ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═════╝  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝   ")
    print()
    # fmt: on
    uvicorn.run(
        "dashboard.dashboard:app",
        host="0.0.0.0",  # noqa: S104  # nosec B104
        port=8003,
        reload=False,
        log_level=os.getenv("LOG_LEVEL", "INFO").lower(),
    )


if __name__ == "__main__":
    main()
