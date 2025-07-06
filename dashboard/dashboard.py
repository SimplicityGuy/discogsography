#!/usr/bin/env python3
"""Dashboard service for monitoring discogsography components."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import aio_pika
import httpx
import orjson
import psycopg
from fastapi import FastAPI, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from fastapi.staticfiles import StaticFiles
from neo4j import AsyncGraphDatabase
from prometheus_client import Counter, Gauge, generate_latest
from pydantic import BaseModel

from common import get_config


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Metrics
WEBSOCKET_CONNECTIONS = Gauge(
    "dashboard_websocket_connections", "Number of active WebSocket connections"
)
API_REQUESTS = Counter("dashboard_api_requests", "Total API requests", ["endpoint", "method"])


class ServiceStatus(BaseModel):
    """Model for service status information."""

    name: str
    status: str  # healthy, unhealthy, unknown
    last_seen: datetime | None
    current_task: str | None
    progress: float | None  # 0.0 to 1.0
    error: str | None


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


class SystemMetrics(BaseModel):
    """Model for system-wide metrics."""

    services: list[ServiceStatus]
    queues: list[QueueInfo]
    databases: list[DatabaseInfo]
    timestamp: datetime


class DashboardApp:
    """Main dashboard application."""

    def __init__(self) -> None:
        """Initialize the dashboard application."""
        self.config = get_config()
        self.websocket_connections: set[WebSocket] = set()
        self.latest_metrics: SystemMetrics | None = None
        self.amqp_connection: aio_pika.abc.AbstractConnection | None = None
        self.neo4j_driver: Any | None = None
        self.update_task: asyncio.Task | None = None

    async def startup(self) -> None:
        """Initialize connections on startup."""
        try:
            # Connect to RabbitMQ
            self.amqp_connection = await aio_pika.connect_robust(self.config.amqp_connection)
            logger.info("🐰 Connected to RabbitMQ")

            # Connect to Neo4j
            self.neo4j_driver = AsyncGraphDatabase.driver(
                self.config.neo4j_address,
                auth=(self.config.neo4j_username, self.config.neo4j_password),
            )
            logger.info("🔗 Connected to Neo4j")

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
            if self.amqp_connection:
                await self.amqp_connection.close()
            if self.neo4j_driver:
                await self.neo4j_driver.close()

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
        """Collect all system metrics."""
        services = await self.get_service_statuses()
        queues = await self.get_queue_info()
        databases = await self.get_database_info()

        return SystemMetrics(
            services=services,
            queues=queues,
            databases=databases,
            timestamp=datetime.now(UTC),
        )

    async def get_service_statuses(self) -> list[ServiceStatus]:
        """Get status of all services."""
        services = []

        # Check each service via health endpoints
        service_configs = [
            ("extractor", "http://extractor:8000/health"),
            ("graphinator", "http://graphinator:8001/health"),
            ("tableinator", "http://tableinator:8002/health"),
        ]

        async with httpx.AsyncClient(timeout=5.0) as client:
            for name, url in service_configs:
                try:
                    response = await client.get(url)
                    if response.status_code == 200:
                        data = response.json()
                        services.append(
                            ServiceStatus(
                                name=name,
                                status="healthy",
                                last_seen=datetime.now(UTC),
                                current_task=data.get("current_task"),
                                progress=data.get("progress"),
                                error=None,
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

    async def get_queue_info(self) -> list[QueueInfo]:
        """Get RabbitMQ queue information."""
        queues: list[QueueInfo] = []

        try:
            if not self.amqp_connection:
                return queues

            async with httpx.AsyncClient(timeout=5.0) as client:
                # Use RabbitMQ management API
                response = await client.get(
                    "http://rabbitmq:15672/api/queues",
                    auth=("discogsography", "discogsography"),
                )

                if response.status_code == 200:
                    queue_data = response.json()
                    for queue in queue_data:
                        if queue["name"].startswith("discogsography"):
                            queues.append(
                                QueueInfo(
                                    name=queue["name"],
                                    messages=queue.get("messages", 0),
                                    messages_ready=queue.get("messages_ready", 0),
                                    messages_unacknowledged=queue.get("messages_unacknowledged", 0),
                                    consumers=queue.get("consumers", 0),
                                    message_rate=queue.get("message_stats", {})
                                    .get("publish_details", {})
                                    .get("rate", 0.0),
                                    ack_rate=queue.get("message_stats", {})
                                    .get("ack_details", {})
                                    .get("rate", 0.0),
                                )
                            )

        except Exception as e:
            logger.error(f"❌ Error getting queue info: {e}")

        return queues

    async def get_database_info(self) -> list[DatabaseInfo]:
        """Get database information."""
        databases = []

        # Check PostgreSQL
        try:
            async with await psycopg.AsyncConnection.connect(
                host=self.config.postgres_address.split(":")[0],
                port=int(self.config.postgres_address.split(":")[1]),
                dbname=self.config.postgres_database,
                user=self.config.postgres_username,
                password=self.config.postgres_password,
            ) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT COUNT(*) FROM pg_stat_activity WHERE datname = %s",
                        (self.config.postgres_database,),
                    )
                    result = await cur.fetchone()
                    connection_count = result[0] if result else 0

                    await cur.execute(
                        "SELECT pg_size_pretty(pg_database_size(%s))",
                        (self.config.postgres_database,),
                    )
                    result = await cur.fetchone()
                    db_size = result[0] if result else "0 bytes"

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

        # Check Neo4j
        try:
            if self.neo4j_driver:
                async with self.neo4j_driver.session() as session:
                    result = await session.run("CALL dbms.components() YIELD name, versions")
                    await result.single()  # Consume result

                    # Get database size
                    result = await session.run("CALL apoc.meta.stats() YIELD nodeCount, relCount")
                    stats = await result.single()
                    node_count = stats["nodeCount"] if stats else 0
                    rel_count = stats["relCount"] if stats else 0

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
        for websocket in self.websocket_connections:
            try:
                await websocket.send_text(message)
            except Exception:
                disconnected.add(websocket)

        # Remove disconnected websockets
        self.websocket_connections -= disconnected
        WEBSOCKET_CONNECTIONS.set(len(self.websocket_connections))


# Create the dashboard app instance
dashboard = DashboardApp()


# Create FastAPI app with lifespan
@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """Manage application lifecycle."""
    await dashboard.startup()
    yield
    await dashboard.shutdown()


app = FastAPI(
    title="Discogsography Dashboard",
    version="0.1.0",
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/metrics")  # type: ignore[misc]
async def get_metrics() -> ORJSONResponse:
    """Get current system metrics."""
    API_REQUESTS.labels(endpoint="/api/metrics", method="GET").inc()

    if dashboard.latest_metrics:
        return dashboard.latest_metrics
    else:
        # Collect metrics on demand if not available
        return await dashboard.collect_all_metrics()


@app.get("/api/services")  # type: ignore[misc]
async def get_services() -> ORJSONResponse:
    """Get service statuses."""
    API_REQUESTS.labels(endpoint="/api/services", method="GET").inc()
    return await dashboard.get_service_statuses()


@app.get("/api/queues")  # type: ignore[misc]
async def get_queues() -> ORJSONResponse:
    """Get queue information."""
    API_REQUESTS.labels(endpoint="/api/queues", method="GET").inc()
    return await dashboard.get_queue_info()


@app.get("/api/databases")  # type: ignore[misc]
async def get_databases() -> ORJSONResponse:
    """Get database information."""
    API_REQUESTS.labels(endpoint="/api/databases", method="GET").inc()
    return await dashboard.get_database_info()


@app.get("/metrics")  # type: ignore[misc]
async def prometheus_metrics() -> Response:
    """Expose Prometheus metrics."""
    return generate_latest()


@app.websocket("/ws")  # type: ignore[misc]
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time updates."""
    await websocket.accept()
    dashboard.websocket_connections.add(websocket)
    WEBSOCKET_CONNECTIONS.inc()

    try:
        # Send initial metrics
        if dashboard.latest_metrics:
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
        dashboard.websocket_connections.remove(websocket)
        WEBSOCKET_CONNECTIONS.dec()
    except Exception as e:
        logger.error(f"❌ WebSocket error: {e}")
        if websocket in dashboard.websocket_connections:
            dashboard.websocket_connections.remove(websocket)
            WEBSOCKET_CONNECTIONS.dec()


# Mount static files for the UI
app.mount("/", StaticFiles(directory="static", html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "dashboard:app",
        host="0.0.0.0",  # nosec B104  # noqa: S104
        port=8003,
        reload=True,
        log_level="info",
    )
