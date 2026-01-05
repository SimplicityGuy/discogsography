#!/usr/bin/env python3
"""Discovery service for music exploration and analytics."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog
from common import get_config, setup_logging
from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from discovery.analytics import (
    AnalyticsRequest,
    AnalyticsResult,
    get_analytics,
    get_analytics_instance,
)

# Import API routers
from discovery.api_graph import router as graph_router
from discovery.api_ml import router as ml_router
from discovery.api_realtime import router as realtime_router
from discovery.api_search import router as search_router
from discovery.graph_explorer import GraphQuery, explore_graph, get_graph_explorer_instance
from discovery.middleware import RequestIDMiddleware
from discovery.playground_api import (
    JourneyRequest,
    artist_details_handler,
    graph_data_handler,
    heatmap_handler,
    journey_handler,
    playground_api,
    search_handler,
    trends_handler,
)
from discovery.recommender import (
    RecommendationRequest,
    get_recommendations,
    get_recommender_instance,
)
from discovery.validation import (
    ALLOWED_HEATMAP_TYPES,
    ALLOWED_TREND_TYPES,
    ALLOWED_TYPES,
    validate_depth,
    validate_limit,
    validate_node_id,
    validate_search_query,
    validate_top_n,
    validate_type,
    validate_year,
)


logger = structlog.get_logger(__name__)

# Configure rate limiting
# - 100 requests per minute for general API endpoints
# - Uses Redis backend for distributed rate limiting (if available)
limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])


async def _create_cache_warming_queries() -> list[dict[str, Any]]:
    """Create a list of cache warming queries for frequently accessed data.

    Returns:
        List of query configurations for cache warming
    """
    from discovery.cache import CACHE_TTL

    warming_queries = []

    # Import modules for warming queries
    from discovery.playground_api import playground_api

    # Warm popular search queries (if configured)
    popular_searches = [
        {"query": "Beatles", "type": "artist"},
        {"query": "Pink Floyd", "type": "artist"},
        {"query": "Led Zeppelin", "type": "artist"},
    ]

    for search_config in popular_searches:
        warming_queries.append(
            {
                "query_func": lambda q=search_config["query"], t=search_config["type"]: playground_api.search(q=q, type=t, limit=10),
                "cache_key": f"search:{search_config['type']}:{search_config['query'].lower()}",
                "ttl": CACHE_TTL.get("search", 3600),
            }
        )

    # Warm trending data
    warming_queries.append(
        {
            "query_func": lambda: playground_api.get_trends(type="genre", start_year=2000, end_year=2024, top_n=20),
            "cache_key": "trends:genre:2000-2024:20",
            "ttl": CACHE_TTL.get("trends", 7200),
        }
    )

    warming_queries.append(
        {
            "query_func": lambda: playground_api.get_trends(type="artist", start_year=2000, end_year=2024, top_n=20),
            "cache_key": "trends:artist:2000-2024:20",
            "ttl": CACHE_TTL.get("trends", 7200),
        }
    )

    # Warm heatmap data
    warming_queries.append(
        {
            "query_func": lambda: playground_api.get_heatmap(type="genre_year", top_n=20),
            "cache_key": "heatmap:genre_year:20",
            "ttl": CACHE_TTL.get("heatmap", 7200),
        }
    )

    logger.debug(f"🔥 Created {len(warming_queries)} cache warming queries")

    return warming_queries


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """Manage application lifespan."""
    # fmt: off
    print("██████╗ ██╗███████╗ ██████╗ ██████╗  ██████╗ ███████╗                      ")
    print("██╔══██╗██║██╔════╝██╔════╝██╔═══██╗██╔════╝ ██╔════╝                      ")
    print("██║  ██║██║███████╗██║     ██║   ██║██║  ███╗███████╗                      ")
    print("██║  ██║██║╚════██║██║     ██║   ██║██║   ██║╚════██║                      ")
    print("██████╔╝██║███████║╚██████╗╚██████╔╝╚██████╔╝███████║                      ")
    print("╚═════╝ ╚═╝╚══════╝ ╚═════╝ ╚═════╝  ╚═════╝ ╚══════╝                      ")
    print("                                                                           ")
    print("██████╗ ██╗███████╗ ██████╗ ██████╗ ██╗   ██╗███████╗██████╗ ██╗   ██╗     ")
    print("██╔══██╗██║██╔════╝██╔════╝██╔═══██╗██║   ██║██╔════╝██╔══██╗╚██╗ ██╔╝     ")
    print("██║  ██║██║███████╗██║     ██║   ██║██║   ██║█████╗  ██████╔╝ ╚████╔╝      ")
    print("██║  ██║██║╚════██║██║     ██║   ██║╚██╗ ██╔╝██╔══╝  ██╔══██╗  ╚██╔╝       ")
    print("██████╔╝██║███████║╚██████╗╚██████╔╝ ╚████╔╝ ███████╗██║  ██║   ██║        ")
    print("╚═════╝ ╚═╝╚══════╝ ╚═════╝ ╚═════╝   ╚═══╝  ╚══════╝╚═╝  ╚═╝   ╚═╝        ")
    print()
    # fmt: on

    logger.info("🚀 Starting Discovery service...")

    # Setup ONNX model if needed
    from discovery.setup_onnx_model import setup_onnx_model

    setup_onnx_model()

    # Initialize all engines
    recommender = get_recommender_instance()
    analytics = get_analytics_instance()
    graph_explorer = get_graph_explorer_instance()

    await recommender.initialize()
    await analytics.initialize()
    await graph_explorer.initialize()
    await playground_api.initialize()

    # Initialize ML API with Neo4j and PostgreSQL connections
    from discovery.api_ml import initialize_ml_api

    await initialize_ml_api(
        neo4j_driver=recommender.driver,
        postgres_conn=analytics.postgres_engine if hasattr(analytics, "postgres_engine") else None,
    )

    # Initialize Search API
    from discovery.api_search import initialize_search_api

    await initialize_search_api(
        neo4j_driver=recommender.driver,
        postgres_conn=analytics.postgres_engine if hasattr(analytics, "postgres_engine") else None,
    )

    # Initialize Graph Analytics API
    from discovery.api_graph import initialize_graph_api

    await initialize_graph_api(neo4j_driver=recommender.driver)

    # Initialize Real-Time Features API
    from discovery.api_realtime import initialize_realtime_api

    await initialize_realtime_api(neo4j_driver=recommender.driver)

    # Create Neo4j indexes for optimal query performance
    from common import get_config

    from discovery.neo4j_indexes import create_all_indexes

    config = get_config()
    if hasattr(config, "neo4j") and config.neo4j:
        try:
            await create_all_indexes(config.neo4j.uri, config.neo4j.user, config.neo4j.password)
            logger.info("✅ Neo4j indexes created successfully")
        except Exception as e:
            logger.warning(f"⚠️  Failed to create Neo4j indexes (non-fatal): {e}")

    # Initialize cache manager
    from discovery.cache import cache_manager

    await cache_manager.initialize()

    # Initialize database connection pool monitoring
    from discovery.db_pool_metrics import pool_monitor

    # Register all database drivers and engines (with type assertions)
    if recommender.driver is not None:
        pool_monitor.register_neo4j_driver("recommender", recommender.driver)
    if analytics.neo4j_driver is not None:
        pool_monitor.register_neo4j_driver("analytics", analytics.neo4j_driver)
    if graph_explorer.driver is not None:
        pool_monitor.register_neo4j_driver("graph_explorer", graph_explorer.driver)
    if playground_api.neo4j_driver is not None:
        pool_monitor.register_neo4j_driver("playground_api", playground_api.neo4j_driver)

    # Register PostgreSQL engines
    if analytics.postgres_engine is not None:
        pool_monitor.register_postgres_engine("analytics", analytics.postgres_engine)
    if playground_api.pg_engine is not None:
        pool_monitor.register_postgres_engine("playground_api", playground_api.pg_engine)

    # Start connection pool monitoring (every 30 seconds)
    await pool_monitor.start_monitoring(interval=30)

    # Warm cache with frequently accessed data
    if cache_manager.connected:
        from common import get_config

        config = get_config()

        # Only warm cache if enabled in configuration
        if getattr(config, "cache_warming_enabled", True):
            warming_queries = await _create_cache_warming_queries()
            warming_stats = await cache_manager.warm_cache(warming_queries)
            logger.info(f"🔥 Cache warming statistics: {warming_stats['successful']}/{warming_stats['total_queries']} successful")

    # Start background task to update cache metrics
    cache_metrics_task = None
    if cache_manager.connected:

        async def update_cache_metrics_periodically() -> None:
            """Update cache metrics every 60 seconds."""
            while True:
                try:
                    await asyncio.sleep(60)
                    await cache_manager.update_cache_size_metrics()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"❌ Cache metrics update error: {e}")

        cache_metrics_task = asyncio.create_task(update_cache_metrics_periodically())
        logger.info("📊 Cache metrics background task started")

    logger.info("✅ Discovery service started successfully")

    try:
        yield
    finally:
        logger.info("🛑 Shutting down Discovery service...")

        # Stop connection pool monitoring
        from discovery.db_pool_metrics import pool_monitor

        await pool_monitor.stop_monitoring()

        # Cancel cache metrics task
        if cache_metrics_task:
            cache_metrics_task.cancel()
            from contextlib import suppress

            with suppress(asyncio.CancelledError):
                await cache_metrics_task

        # Close all Phase 4 APIs
        from discovery.api_graph import close_graph_api
        from discovery.api_ml import close_ml_api
        from discovery.api_realtime import close_realtime_api
        from discovery.api_search import close_search_api

        await close_ml_api()
        await close_search_api()
        await close_graph_api()
        await close_realtime_api()

        await recommender.close()
        await analytics.close()
        await graph_explorer.close()
        await playground_api.close()
        await cache_manager.close()
        logger.info("✅ Discovery service shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="Discogsography Discovery",
    description="Music discovery, analytics, and graph exploration service",
    version="1.0.0",
    lifespan=lifespan,
    default_response_class=ORJSONResponse,
)

# Configure rate limiting for the app
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Configure CORS origins from environment or use secure defaults
_config = get_config()
cors_origins = _config.cors_origins or [
    "http://localhost:3000",
    "http://localhost:8000",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:8000",
]

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add request ID tracking middleware
app.add_middleware(RequestIDMiddleware)

# Mount static files
static_path = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_path), name="static")

# Include API routers
app.include_router(ml_router)
app.include_router(search_router)
app.include_router(graph_router)
app.include_router(realtime_router)


class DiscoveryApp:
    """Main discovery application."""

    def __init__(self) -> None:
        self.config = get_config()
        self.active_connections: list[WebSocket] = []

    async def connect_websocket(self, websocket: WebSocket) -> None:
        """Connect a new WebSocket client."""
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info("🔌 WebSocket connected", total_connections=len(self.active_connections))

    def disconnect_websocket(self, websocket: WebSocket) -> None:
        """Disconnect a WebSocket client."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info("🔌 WebSocket disconnected", total_connections=len(self.active_connections))

    async def broadcast_update(self, message: dict[str, Any]) -> None:
        """Broadcast an update to all connected WebSocket clients."""
        if not self.active_connections:
            return

        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)

        # Remove disconnected clients
        for connection in disconnected:
            self.disconnect_websocket(connection)


# Global app instance
discovery_app = DiscoveryApp()


# API Routes
@app.get("/")
@limiter.limit("200/minute")
async def root(request: Request) -> Response:
    """Serve the main discovery interface."""
    with (static_path / "index.html").open() as f:
        return Response(content=f.read(), media_type="text/html")


@app.get("/health")
@limiter.limit("200/minute")
async def health_check(request: Request) -> dict[str, Any]:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "discovery",
        "timestamp": datetime.now().isoformat(),
        "features": {"recommendations": True, "analytics": True, "graph_explorer": True},
    }


@app.get("/metrics")
async def metrics(request: Request) -> Response:
    """Prometheus metrics endpoint."""
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/cache/stats")
@limiter.limit("100/minute")
async def cache_stats_api(request: Request) -> dict[str, Any]:
    """Get cache statistics."""
    from discovery.cache import cache_manager

    stats = await cache_manager.get_cache_stats()
    return {"cache_stats": stats, "timestamp": datetime.now().isoformat()}


@app.get("/api/db/pool/stats")
@limiter.limit("100/minute")
async def db_pool_stats_api(request: Request) -> dict[str, Any]:
    """Get database connection pool statistics.

    Returns real-time metrics for Neo4j and PostgreSQL connection pools,
    including pool size, active connections, and resource utilization.
    """
    from discovery.db_pool_metrics import pool_monitor

    metrics = await pool_monitor.collect_all_metrics()
    summary = pool_monitor.get_metrics_summary()

    return {
        "metrics": metrics,
        "summary": summary,
        "timestamp": datetime.now().isoformat(),
    }


# Cache Invalidation Webhooks


class CacheInvalidationRequest(BaseModel):
    """Request model for cache invalidation webhook."""

    pattern: str = Field(..., description="Cache key pattern to invalidate (e.g., 'search:*', 'trends:*', or specific key)")
    secret: str = Field(..., description="Webhook secret for authentication")


@app.post("/api/cache/invalidate")
@limiter.limit("10/minute")
async def invalidate_cache_api(request: Request, invalidation_request: CacheInvalidationRequest) -> dict[str, Any]:
    """Invalidate cache entries matching a pattern.

    This webhook allows external systems to invalidate cached data.
    Requires a secret token for authentication.

    Args:
        invalidation_request: Contains pattern and authentication secret

    Returns:
        Dictionary with invalidation results

    Raises:
        HTTPException: If authentication fails or invalidation errors occur
    """
    from discovery.cache import cache_manager

    # Validate webhook secret
    config = get_config()
    expected_secret = getattr(config, "cache_webhook_secret", None)

    if not expected_secret:
        raise HTTPException(status_code=503, detail="Cache invalidation webhook not configured")

    if invalidation_request.secret != expected_secret:
        logger.warning(
            "❌ Cache invalidation webhook authentication failed",
            pattern=invalidation_request.pattern,
            remote_addr=request.client.host if request.client else "unknown",
        )
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    # Perform cache invalidation
    try:
        deleted_count = await cache_manager.clear_pattern(invalidation_request.pattern)

        logger.info(
            f"🔄 Cache invalidation webhook: {deleted_count} keys cleared",
            pattern=invalidation_request.pattern,
            deleted_count=deleted_count,
            remote_addr=request.client.host if request.client else "unknown",
        )

        return {
            "status": "success",
            "pattern": invalidation_request.pattern,
            "deleted_count": deleted_count,
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        logger.error(
            "❌ Cache invalidation webhook error",
            pattern=invalidation_request.pattern,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail=f"Cache invalidation failed: {e}") from e


# Recommendation API
@app.post("/api/recommendations")
@limiter.limit("50/minute")
async def get_recommendations_api(request: Request, rec_request: RecommendationRequest) -> dict[str, Any]:
    """Get music recommendations."""
    try:
        recommendations = await get_recommendations(rec_request)
        return {
            "recommendations": recommendations,
            "total": len(recommendations),
            "request": rec_request.model_dump(),
        }
    except Exception as e:
        logger.error("❌ Error getting recommendations", error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from e


# Analytics API
@app.post("/api/analytics")
@limiter.limit("50/minute")
async def get_analytics_api(request: Request, analytics_request: AnalyticsRequest) -> AnalyticsResult:
    """Get music industry analytics."""
    try:
        result = await get_analytics(analytics_request)
        return result
    except Exception as e:
        logger.error("❌ Error getting analytics", error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from e


# Graph Explorer API
@app.post("/api/graph/explore")
@limiter.limit("50/minute")
async def explore_graph_api(request: Request, query: GraphQuery) -> dict[str, Any]:
    """Explore the music knowledge graph."""
    try:
        graph_data, path_result = await explore_graph(query)

        response = {"graph": graph_data, "query": query.model_dump()}

        if path_result:
            response["path"] = path_result

        return response
    except Exception as e:
        logger.error("❌ Error exploring graph", error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from e


# Playground API Routes
@app.get("/api/search")
@limiter.limit("100/minute")
async def search_api(
    request: Request,
    q: str,
    type: str = "all",
    limit: int = 10,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Search endpoint for playground with cursor-based pagination."""
    # Validate and sanitize inputs
    validated_query = validate_search_query(q)
    validated_type = validate_type(type, ALLOWED_TYPES)
    validated_limit = validate_limit(limit)

    return await search_handler(q=validated_query, type=validated_type, limit=validated_limit, cursor=cursor)


@app.get("/api/graph")
@limiter.limit("100/minute")
async def graph_api(
    request: Request,
    node_id: str,
    depth: int = 2,
    limit: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Graph data endpoint for playground with cursor-based pagination."""
    # Validate and sanitize inputs
    validated_node_id = validate_node_id(node_id)
    validated_depth = validate_depth(depth)
    validated_limit = validate_limit(limit)

    return await graph_data_handler(node_id=validated_node_id, depth=validated_depth, limit=validated_limit, cursor=cursor)


@app.post("/api/journey")
@limiter.limit("50/minute")
async def journey_api(request: Request, journey_request: JourneyRequest) -> dict[str, Any]:
    """Music journey endpoint for playground."""
    return await journey_handler(journey_request)


@app.get("/api/trends")
@limiter.limit("100/minute")
async def trends_api(
    request: Request,
    type: str,
    start_year: int = 1950,
    end_year: int = 2024,
    top_n: int = 20,
    limit: int = 20,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Trends endpoint for playground with cursor-based pagination."""
    # Validate and sanitize inputs
    validated_type = validate_type(type, ALLOWED_TREND_TYPES)
    validated_start_year = validate_year(start_year)
    validated_end_year = validate_year(end_year)
    validated_top_n = validate_top_n(top_n)
    validated_limit = validate_limit(limit)

    # Validate year range
    if validated_start_year > validated_end_year:
        raise HTTPException(status_code=400, detail="start_year must be less than or equal to end_year")

    return await trends_handler(
        type=validated_type,
        start_year=validated_start_year,
        end_year=validated_end_year,
        top_n=validated_top_n,
        limit=validated_limit,
        cursor=cursor,
    )


@app.get("/api/heatmap")
@limiter.limit("100/minute")
async def heatmap_api(
    request: Request,
    type: str,
    top_n: int = 20,
    limit: int = 100,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Heatmap endpoint for playground with cursor-based pagination."""
    # Validate and sanitize inputs
    validated_type = validate_type(type, ALLOWED_HEATMAP_TYPES)
    validated_top_n = validate_top_n(top_n)
    validated_limit = validate_limit(limit)

    return await heatmap_handler(type=validated_type, top_n=validated_top_n, limit=validated_limit, cursor=cursor)


@app.get("/api/artists/{artist_id}")
@limiter.limit("100/minute")
async def artist_details_api(request: Request, artist_id: str) -> dict[str, Any]:
    """Artist details endpoint for playground."""
    # Validate and sanitize inputs
    validated_artist_id = validate_node_id(artist_id)

    return await artist_details_handler(validated_artist_id)


# WebSocket endpoint for real-time updates
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time updates."""
    await discovery_app.connect_websocket(websocket)
    try:
        while True:
            # Keep connection alive and handle incoming messages
            data = await websocket.receive_text()

            # Echo back for now - could handle specific commands
            await websocket.send_json({"type": "echo", "message": data, "timestamp": datetime.now().isoformat()})
    except WebSocketDisconnect:
        discovery_app.disconnect_websocket(websocket)


def get_health_data() -> dict[str, Any]:
    """Get current health data for monitoring."""
    from datetime import datetime

    return {
        "status": "healthy",
        "service": "discovery",
        "ai_features": "active",
        "semantic_search": "ready",
        "visualization_engine": "online",
        "timestamp": datetime.now().isoformat(),
    }


if __name__ == "__main__":
    import uvicorn

    # Set up logging
    setup_logging("discovery", log_file=Path("/logs/discovery.log"))

    # Start health server in background
    from common import HealthServer

    async def start_servers() -> None:
        # Start health server
        health_server = HealthServer(8004, get_health_data)
        health_server.start_background()

        # Start main FastAPI server
        config = uvicorn.Config(
            app="discovery.discovery:app",
            host="0.0.0.0",  # nosec B104  # noqa: S104
            port=8005,  # Different port from dashboard
            log_level="info",
            reload=False,
        )
        server = uvicorn.Server(config)

        logger.info("🏥 Health server started on port 8004")
        logger.info("🎵 Discovery service starting on port 8005...")

        try:
            await server.serve()
        except KeyboardInterrupt:
            logger.info("🛑 Received shutdown signal")
        finally:
            # Health server runs in background thread, will stop when process exits
            logger.info("🏥 Health server will stop with main process")

    asyncio.run(start_servers())
