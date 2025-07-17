#!/usr/bin/env python3
"""Dashboard service for monitoring discogsography components."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
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
from common.changes_consumer import ChangesConsumer


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Metrics
try:
    WEBSOCKET_CONNECTIONS = Gauge(
        "dashboard_websocket_connections", "Number of active WebSocket connections"
    )
except ValueError:
    # Metric already registered (happens during reload)
    from prometheus_client import REGISTRY

    WEBSOCKET_CONNECTIONS = REGISTRY._names_to_collectors["dashboard_websocket_connections"]

try:
    API_REQUESTS = Counter("dashboard_api_requests", "Total API requests", ["endpoint", "method"])
except ValueError:
    # Metric already registered (happens during reload)
    from prometheus_client import REGISTRY

    API_REQUESTS = REGISTRY._names_to_collectors["dashboard_api_requests_total"]


class ServiceStatus(BaseModel):
    """Model for service status information."""

    name: str
    status: str  # healthy, unhealthy, unknown
    last_seen: datetime | None
    current_task: str | None
    progress: float | None  # 0.0 to 1.0
    error: str | None
    # Incremental processing stats
    change_stats: dict[str, dict[str, int]] | None = None


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


class ChangeNotification(BaseModel):
    """Model for change notifications from incremental processing."""

    data_type: str
    record_id: str
    change_type: str  # created, updated, deleted
    processing_run_id: str
    timestamp: datetime


class DashboardChangesConsumer(ChangesConsumer):
    """Changes consumer that broadcasts to WebSocket connections."""

    def __init__(self, amqp_connection_url: str, dashboard_app: "DashboardApp"):
        super().__init__(amqp_connection_url, "dashboard")
        self.dashboard_app = dashboard_app

    async def process_change(self, change_data: dict[str, Any]) -> None:
        """Process a change notification and broadcast to WebSocket clients."""
        # Create a ChangeNotification model
        notification = ChangeNotification(
            data_type=change_data["data_type"],
            record_id=change_data["record_id"],
            change_type=change_data["change_type"],
            processing_run_id=change_data["processing_run_id"],
            timestamp=datetime.fromisoformat(change_data["timestamp"]),
        )

        # Broadcast to all connected WebSocket clients
        await self.dashboard_app.broadcast_change(notification)


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
        self.changes_consumer: DashboardChangesConsumer | None = None
        self.changes_task: asyncio.Task | None = None

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

            # Start changes consumer for real-time notifications
            try:
                self.changes_consumer = DashboardChangesConsumer(self.config.amqp_connection, self)
                await self.changes_consumer.connect()
                self.changes_task = asyncio.create_task(self.changes_consumer.start_consuming())
                logger.info("📡 Started changes consumer for real-time notifications")
            except Exception as e:
                logger.warning(f"⚠️ Could not start changes consumer: {e}")

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

            # Cancel changes task
            if self.changes_task:
                self.changes_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self.changes_task

            # Close changes consumer
            if self.changes_consumer:
                await self.changes_consumer.close()

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
                                change_stats=data.get("change_stats"),
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

    async def broadcast_change(self, notification: ChangeNotification) -> None:
        """Broadcast a change notification to all connected websockets."""
        if not self.websocket_connections:
            return

        message = orjson.dumps(
            {
                "type": "change_notification",
                "data": notification.model_dump(mode="json"),
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
dashboard: DashboardApp | None = None


# Create FastAPI app with lifespan
@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """Manage application lifecycle."""
    global dashboard
    dashboard = DashboardApp()
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

    if dashboard and dashboard.latest_metrics:
        return ORJSONResponse(content=dashboard.latest_metrics.model_dump())
    elif dashboard:
        # Collect metrics on demand if not available
        metrics = await dashboard.collect_all_metrics()
        return ORJSONResponse(content=metrics.model_dump())
    else:
        return ORJSONResponse(content={})


@app.get("/api/services")  # type: ignore[misc]
async def get_services() -> ORJSONResponse:
    """Get service statuses."""
    API_REQUESTS.labels(endpoint="/api/services", method="GET").inc()
    if not dashboard:
        return ORJSONResponse(content=[])
    services = await dashboard.get_service_statuses()
    return ORJSONResponse(content=[s.model_dump() for s in services])


@app.get("/api/queues")  # type: ignore[misc]
async def get_queues() -> ORJSONResponse:
    """Get queue information."""
    API_REQUESTS.labels(endpoint="/api/queues", method="GET").inc()
    if not dashboard:
        return ORJSONResponse(content=[])
    queues = await dashboard.get_queue_info()
    return ORJSONResponse(content=[q.model_dump() for q in queues])


@app.get("/api/databases")  # type: ignore[misc]
async def get_databases() -> ORJSONResponse:
    """Get database information."""
    API_REQUESTS.labels(endpoint="/api/databases", method="GET").inc()
    if not dashboard:
        return ORJSONResponse(content=[])
    databases = await dashboard.get_database_info()
    return ORJSONResponse(content=[d.model_dump() for d in databases])


@app.get("/metrics")  # type: ignore[misc]
async def prometheus_metrics() -> Response:
    """Expose Prometheus metrics."""
    return Response(content=generate_latest(), media_type="text/plain")


@app.websocket("/ws")  # type: ignore[misc]
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time updates."""
    await websocket.accept()
    if dashboard:
        dashboard.websocket_connections.add(websocket)
    WEBSOCKET_CONNECTIONS.inc()

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
            dashboard.websocket_connections.remove(websocket)
        WEBSOCKET_CONNECTIONS.dec()
    except Exception as e:
        logger.error(f"❌ WebSocket error: {e}")
        if dashboard and websocket in dashboard.websocket_connections:
            dashboard.websocket_connections.remove(websocket)
            WEBSOCKET_CONNECTIONS.dec()


# Mount static files for the UI
static_dir = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "dashboard.dashboard:app",
        host="0.0.0.0",  # noqa: S104  # nosec B104
        port=8003,
        reload=False,
        log_level="info",
    )
