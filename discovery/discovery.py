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
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from discovery.analytics import (
    AnalyticsRequest,
    AnalyticsResult,
    get_analytics,
    get_analytics_instance,
)
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

    logger.info("✅ Discovery service started successfully")

    try:
        yield
    finally:
        logger.info("🛑 Shutting down Discovery service...")
        await recommender.close()
        await analytics.close()
        await graph_explorer.close()
        await playground_api.close()
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
@app.get("/")  # type: ignore[untyped-decorator]
@limiter.limit("200/minute")
async def root(request: Request) -> Response:
    """Serve the main discovery interface."""
    with (static_path / "index.html").open() as f:
        return Response(content=f.read(), media_type="text/html")


@app.get("/health")  # type: ignore[untyped-decorator]
@limiter.limit("200/minute")
async def health_check(request: Request) -> dict[str, Any]:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "discovery",
        "timestamp": datetime.now().isoformat(),
        "features": {"recommendations": True, "analytics": True, "graph_explorer": True},
    }


# Recommendation API
@app.post("/api/recommendations")  # type: ignore[untyped-decorator]
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
@app.post("/api/analytics")  # type: ignore[untyped-decorator]
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
@app.post("/api/graph/explore")  # type: ignore[untyped-decorator]
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
@app.get("/api/search")  # type: ignore[untyped-decorator]
@limiter.limit("100/minute")
async def search_api(
    request: Request,
    q: str,
    type: str = "all",
    limit: int = 10,
) -> dict[str, Any]:
    """Search endpoint for playground."""
    # Validate and sanitize inputs
    validated_query = validate_search_query(q)
    validated_type = validate_type(type, ALLOWED_TYPES)
    validated_limit = validate_limit(limit)

    return await search_handler(q=validated_query, type=validated_type, limit=validated_limit)


@app.get("/api/graph")  # type: ignore[untyped-decorator]
@limiter.limit("100/minute")
async def graph_api(
    request: Request,
    node_id: str,
    depth: int = 2,
    limit: int = 50,
) -> dict[str, Any]:
    """Graph data endpoint for playground."""
    # Validate and sanitize inputs
    validated_node_id = validate_node_id(node_id)
    validated_depth = validate_depth(depth)
    validated_limit = validate_limit(limit)

    return await graph_data_handler(node_id=validated_node_id, depth=validated_depth, limit=validated_limit)


@app.post("/api/journey")  # type: ignore[untyped-decorator]
@limiter.limit("50/minute")
async def journey_api(request: Request, journey_request: JourneyRequest) -> dict[str, Any]:
    """Music journey endpoint for playground."""
    return await journey_handler(journey_request)


@app.get("/api/trends")  # type: ignore[untyped-decorator]
@limiter.limit("100/minute")
async def trends_api(
    request: Request,
    type: str,
    start_year: int = 1950,
    end_year: int = 2024,
    top_n: int = 20,
) -> dict[str, Any]:
    """Trends endpoint for playground."""
    # Validate and sanitize inputs
    validated_type = validate_type(type, ALLOWED_TREND_TYPES)
    validated_start_year = validate_year(start_year)
    validated_end_year = validate_year(end_year)
    validated_top_n = validate_top_n(top_n)

    # Validate year range
    if validated_start_year > validated_end_year:
        raise HTTPException(status_code=400, detail="start_year must be less than or equal to end_year")

    return await trends_handler(
        type=validated_type,
        start_year=validated_start_year,
        end_year=validated_end_year,
        top_n=validated_top_n,
    )


@app.get("/api/heatmap")  # type: ignore[untyped-decorator]
@limiter.limit("100/minute")
async def heatmap_api(
    request: Request,
    type: str,
    top_n: int = 20,
) -> dict[str, Any]:
    """Heatmap endpoint for playground."""
    # Validate and sanitize inputs
    validated_type = validate_type(type, ALLOWED_HEATMAP_TYPES)
    validated_top_n = validate_top_n(top_n)

    return await heatmap_handler(type=validated_type, top_n=validated_top_n)


@app.get("/api/artists/{artist_id}")  # type: ignore[untyped-decorator]
@limiter.limit("100/minute")
async def artist_details_api(request: Request, artist_id: str) -> dict[str, Any]:
    """Artist details endpoint for playground."""
    # Validate and sanitize inputs
    validated_artist_id = validate_node_id(artist_id)

    return await artist_details_handler(validated_artist_id)


# WebSocket endpoint for real-time updates
@app.websocket("/ws")  # type: ignore[untyped-decorator]
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
