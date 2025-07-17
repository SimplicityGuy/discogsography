#!/usr/bin/env python3
"""Discovery service for music exploration and analytics."""

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from common import get_config
from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from fastapi.staticfiles import StaticFiles

from discovery.analytics import AnalyticsRequest, get_analytics, get_analytics_instance
from discovery.graph_explorer import GraphQuery, explore_graph, get_graph_explorer_instance
from discovery.recommender import (
    RecommendationRequest,
    get_recommendations,
    get_recommender_instance,
)


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Manage application lifespan."""
    logger.info("🚀 Starting Discovery service...")

    # Initialize all engines
    recommender = get_recommender_instance()
    analytics = get_analytics_instance()
    graph_explorer = get_graph_explorer_instance()

    await recommender.initialize()
    await analytics.initialize()
    await graph_explorer.initialize()

    logger.info("✅ Discovery service started successfully")

    try:
        yield
    finally:
        logger.info("🛑 Shutting down Discovery service...")
        await recommender.close()
        await analytics.close()
        await graph_explorer.close()
        logger.info("✅ Discovery service shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="Discogsography Discovery",
    description="Music discovery, analytics, and graph exploration service",
    version="1.0.0",
    lifespan=lifespan,
    default_response_class=ORJSONResponse,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
        logger.info(f"🔌 WebSocket connected. Total connections: {len(self.active_connections)}")

    def disconnect_websocket(self, websocket: WebSocket) -> None:
        """Disconnect a WebSocket client."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"🔌 WebSocket disconnected. Total connections: {len(self.active_connections)}")

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
async def root():
    """Serve the main discovery interface."""
    with (static_path / "index.html").open() as f:
        return Response(content=f.read(), media_type="text/html")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "discovery",
        "timestamp": datetime.now().isoformat(),
        "features": {"recommendations": True, "analytics": True, "graph_explorer": True},
    }


# Recommendation API
@app.post("/api/recommendations")
async def get_recommendations_api(request: RecommendationRequest):
    """Get music recommendations."""
    try:
        recommendations = await get_recommendations(request)
        return {
            "recommendations": recommendations,
            "total": len(recommendations),
            "request": request.dict(),
        }
    except Exception as e:
        logger.error(f"❌ Error getting recommendations: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# Analytics API
@app.post("/api/analytics")
async def get_analytics_api(request: AnalyticsRequest):
    """Get music industry analytics."""
    try:
        result = await get_analytics(request)
        return result
    except Exception as e:
        logger.error(f"❌ Error getting analytics: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# Graph Explorer API
@app.post("/api/graph/explore")
async def explore_graph_api(query: GraphQuery):
    """Explore the music knowledge graph."""
    try:
        graph_data, path_result = await explore_graph(query)

        response = {"graph": graph_data, "query": query.dict()}

        if path_result:
            response["path"] = path_result

        return response
    except Exception as e:
        logger.error(f"❌ Error exploring graph: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# WebSocket endpoint for real-time updates
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    await discovery_app.connect_websocket(websocket)
    try:
        while True:
            # Keep connection alive and handle incoming messages
            data = await websocket.receive_text()

            # Echo back for now - could handle specific commands
            await websocket.send_json(
                {"type": "echo", "message": data, "timestamp": datetime.now().isoformat()}
            )
    except WebSocketDisconnect:
        discovery_app.disconnect_websocket(websocket)


if __name__ == "__main__":
    import uvicorn

    # Start health server in background
    from common import HealthServer

    async def start_servers():
        # Start health server
        health_server = HealthServer(port=8004)
        health_task = asyncio.create_task(health_server.start())

        # Start main FastAPI server
        config = uvicorn.Config(
            app="discovery.discovery:app",
            host="0.0.0.0",  # noqa: S104
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
            health_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await health_task

    asyncio.run(start_servers())
