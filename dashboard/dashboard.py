#!/usr/bin/env python3
"""Dashboard service for monitoring discogsography components."""

import asyncio
from collections.abc import AsyncGenerator
import contextlib
from contextlib import asynccontextmanager
from datetime import UTC, datetime
import logging
from pathlib import Path

from fastapi import FastAPI, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from fastapi.staticfiles import StaticFiles
import httpx
import orjson
from prometheus_client import Counter, Gauge, generate_latest
import psycopg
from pydantic import BaseModel

from common import (
    AsyncResilientNeo4jDriver,
    AsyncResilientPostgreSQL,
    AsyncResilientRabbitMQ,
    get_config,
    setup_logging,
)


logger = logging.getLogger(__name__)

# Metrics
try:
    WEBSOCKET_CONNECTIONS = Gauge("dashboard_websocket_connections", "Number of active WebSocket connections")
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
                uri=self.config.neo4j_address,
                auth=(self.config.neo4j_username, self.config.neo4j_password),
                max_retries=5,
                encrypted=False,
            )
            logger.info("🔗 Connected to Neo4j with resilient driver")

            # Initialize resilient PostgreSQL connection
            # Parse host and port from address
            if ":" in self.config.postgres_address:
                host, port_str = self.config.postgres_address.split(":", 1)
                port = int(port_str)
            else:
                host = self.config.postgres_address
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
            ("discovery", "http://discovery:8004/health"),
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
            if not self.rabbitmq:
                return queues

            async with httpx.AsyncClient(timeout=5.0) as client:
                # Use RabbitMQ management API with credentials from config
                response = await client.get(
                    "http://rabbitmq:15672/api/queues",
                    auth=(self.config.rabbitmq_management_user, self.config.rabbitmq_management_password),
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
                                    message_rate=queue.get("message_stats", {}).get("publish_details", {}).get("rate", 0.0),
                                    ack_rate=queue.get("message_stats", {}).get("ack_details", {}).get("rate", 0.0),
                                )
                            )
                elif response.status_code == 401:
                    logger.warning("⚠️ RabbitMQ management API authentication failed. Queue metrics unavailable.")
                else:
                    logger.warning(f"⚠️ RabbitMQ management API returned status {response.status_code}")

        except httpx.ConnectError:
            logger.debug("🔌 RabbitMQ management API unreachable. This is normal if RabbitMQ is not running.")
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
                async with await self.neo4j_driver.session() as session:
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
dashboard: DashboardApp | None = None


# Create FastAPI app with lifespan
@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """Manage application lifecycle."""
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

    logger.info("🚀 Starting Dashboard service...")

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


@app.get("/health")  # type: ignore[untyped-decorator]
async def health_check() -> ORJSONResponse:
    """Health check endpoint for Docker and monitoring."""
    return ORJSONResponse(
        content={
            "status": "healthy",
            "service": "dashboard",
            "timestamp": datetime.now(UTC).isoformat(),
            "uptime": "running",
        }
    )


@app.get("/api/metrics")  # type: ignore[untyped-decorator]
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


@app.get("/api/services")  # type: ignore[untyped-decorator]
async def get_services() -> ORJSONResponse:
    """Get service statuses."""
    API_REQUESTS.labels(endpoint="/api/services", method="GET").inc()
    if not dashboard:
        return ORJSONResponse(content=[])
    services = await dashboard.get_service_statuses()
    return ORJSONResponse(content=[s.model_dump() for s in services])


@app.get("/api/queues")  # type: ignore[untyped-decorator]
async def get_queues() -> ORJSONResponse:
    """Get queue information."""
    API_REQUESTS.labels(endpoint="/api/queues", method="GET").inc()
    if not dashboard:
        return ORJSONResponse(content=[])
    queues = await dashboard.get_queue_info()
    return ORJSONResponse(content=[q.model_dump() for q in queues])


@app.get("/api/databases")  # type: ignore[untyped-decorator]
async def get_databases() -> ORJSONResponse:
    """Get database information."""
    API_REQUESTS.labels(endpoint="/api/databases", method="GET").inc()
    if not dashboard:
        return ORJSONResponse(content=[])
    databases = await dashboard.get_database_info()
    return ORJSONResponse(content=[d.model_dump() for d in databases])


@app.get("/metrics")  # type: ignore[untyped-decorator]
async def prometheus_metrics() -> Response:
    """Expose Prometheus metrics."""
    return Response(content=generate_latest(), media_type="text/plain")


# Discovery API Proxy Endpoints for Phase 4.3 UI


@app.get("/api/discovery/ml/status")  # type: ignore[untyped-decorator]
async def get_ml_status() -> ORJSONResponse:
    """Get ML API status from Discovery service."""
    API_REQUESTS.labels(endpoint="/api/discovery/ml/status", method="GET").inc()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get("http://discovery:8005/api/ml/status")
            if response.status_code == 200:
                return ORJSONResponse(content=response.json())
            return ORJSONResponse(content={"error": f"Discovery API returned {response.status_code}"}, status_code=response.status_code)
    except Exception as e:
        logger.error(f"❌ Error fetching ML status: {e}")
        return ORJSONResponse(content={"error": str(e)}, status_code=503)


@app.post("/api/discovery/ml/recommend/collaborative")  # type: ignore[untyped-decorator]
async def get_collaborative_recommendations(artist_id: str = "The Beatles", limit: int = 10, min_similarity: float = 0.1) -> ORJSONResponse:
    """Get collaborative filtering recommendations from Discovery service."""
    API_REQUESTS.labels(endpoint="/api/discovery/ml/recommend/collaborative", method="POST").inc()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                "http://discovery:8005/api/ml/recommend/collaborative",
                json={"artist_id": artist_id, "limit": limit, "min_similarity": min_similarity},
            )
            if response.status_code == 200:
                return ORJSONResponse(content=response.json())
            return ORJSONResponse(content={"error": f"Discovery API returned {response.status_code}"}, status_code=response.status_code)
    except Exception as e:
        logger.error(f"❌ Error fetching collaborative recommendations: {e}")
        return ORJSONResponse(content={"error": str(e)}, status_code=503)


@app.post("/api/discovery/ml/recommend/hybrid")  # type: ignore[untyped-decorator]
async def get_hybrid_recommendations(artist_name: str = "The Beatles", limit: int = 10, strategy: str = "weighted") -> ORJSONResponse:
    """Get hybrid recommendations from Discovery service."""
    API_REQUESTS.labels(endpoint="/api/discovery/ml/recommend/hybrid", method="POST").inc()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                "http://discovery:8005/api/ml/recommend/hybrid",
                json={"artist_name": artist_name, "limit": limit, "strategy": strategy},
            )
            if response.status_code == 200:
                return ORJSONResponse(content=response.json())
            return ORJSONResponse(content={"error": f"Discovery API returned {response.status_code}"}, status_code=response.status_code)
    except Exception as e:
        logger.error(f"❌ Error fetching hybrid recommendations: {e}")
        return ORJSONResponse(content={"error": str(e)}, status_code=503)


@app.get("/api/discovery/search/status")  # type: ignore[untyped-decorator]
async def get_search_status() -> ORJSONResponse:
    """Get Search API status from Discovery service."""
    API_REQUESTS.labels(endpoint="/api/discovery/search/status", method="GET").inc()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get("http://discovery:8005/api/search/status")
            if response.status_code == 200:
                return ORJSONResponse(content=response.json())
            return ORJSONResponse(content={"error": f"Discovery API returned {response.status_code}"}, status_code=response.status_code)
    except Exception as e:
        logger.error(f"❌ Error fetching search status: {e}")
        return ORJSONResponse(content={"error": str(e)}, status_code=503)


@app.get("/api/discovery/search/stats")  # type: ignore[untyped-decorator]
async def get_search_stats() -> ORJSONResponse:
    """Get search statistics from Discovery service."""
    API_REQUESTS.labels(endpoint="/api/discovery/search/stats", method="GET").inc()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get("http://discovery:8005/api/search/stats")
            if response.status_code == 200:
                return ORJSONResponse(content=response.json())
            return ORJSONResponse(content={"error": f"Discovery API returned {response.status_code}"}, status_code=response.status_code)
    except Exception as e:
        logger.error(f"❌ Error fetching search stats: {e}")
        return ORJSONResponse(content={"error": str(e)}, status_code=503)


@app.get("/api/discovery/graph/status")  # type: ignore[untyped-decorator]
async def get_graph_status() -> ORJSONResponse:
    """Get Graph Analytics API status from Discovery service."""
    API_REQUESTS.labels(endpoint="/api/discovery/graph/status", method="GET").inc()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get("http://discovery:8005/api/graph/status")
            if response.status_code == 200:
                return ORJSONResponse(content=response.json())
            return ORJSONResponse(content={"error": f"Discovery API returned {response.status_code}"}, status_code=response.status_code)
    except Exception as e:
        logger.error(f"❌ Error fetching graph status: {e}")
        return ORJSONResponse(content={"error": str(e)}, status_code=503)


@app.post("/api/discovery/graph/centrality")  # type: ignore[untyped-decorator]
async def get_centrality_metrics(
    metric: str = "pagerank", limit: int = 20, node_type: str = "artist", sample_size: int | None = None
) -> ORJSONResponse:
    """Get centrality metrics from Discovery service."""
    API_REQUESTS.labels(endpoint="/api/discovery/graph/centrality", method="POST").inc()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "http://discovery:8005/api/graph/centrality",
                json={"metric": metric, "limit": limit, "node_type": node_type, "sample_size": sample_size},
            )
            if response.status_code == 200:
                return ORJSONResponse(content=response.json())
            return ORJSONResponse(content={"error": f"Discovery API returned {response.status_code}"}, status_code=response.status_code)
    except Exception as e:
        logger.error(f"❌ Error fetching centrality metrics: {e}")
        return ORJSONResponse(content={"error": str(e)}, status_code=503)


@app.get("/api/discovery/realtime/status")  # type: ignore[untyped-decorator]
async def get_realtime_status() -> ORJSONResponse:
    """Get Real-Time API status from Discovery service."""
    API_REQUESTS.labels(endpoint="/api/discovery/realtime/status", method="GET").inc()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get("http://discovery:8005/api/realtime/status")
            if response.status_code == 200:
                return ORJSONResponse(content=response.json())
            return ORJSONResponse(content={"error": f"Discovery API returned {response.status_code}"}, status_code=response.status_code)
    except Exception as e:
        logger.error(f"❌ Error fetching realtime status: {e}")
        return ORJSONResponse(content={"error": str(e)}, status_code=503)


@app.post("/api/discovery/realtime/trending")  # type: ignore[untyped-decorator]
async def get_trending(category: str = "artists", limit: int = 10, time_window: str = "day") -> ORJSONResponse:
    """Get trending items from Discovery service."""
    API_REQUESTS.labels(endpoint="/api/discovery/realtime/trending", method="POST").inc()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                "http://discovery:8005/api/realtime/trending",
                json={"category": category, "limit": limit, "time_window": time_window},
            )
            if response.status_code == 200:
                return ORJSONResponse(content=response.json())
            return ORJSONResponse(content={"error": f"Discovery API returned {response.status_code}"}, status_code=response.status_code)
    except Exception as e:
        logger.error(f"❌ Error fetching trending items: {e}")
        return ORJSONResponse(content={"error": str(e)}, status_code=503)


@app.websocket("/ws")  # type: ignore[untyped-decorator]
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

    # Set up logging
    setup_logging("dashboard", log_file=Path("/logs/dashboard.log"))

    uvicorn.run(
        "dashboard.dashboard:app",
        host="0.0.0.0",  # noqa: S104  # nosec B104
        port=8003,
        reload=False,
        log_level="info",
    )
