"""Real-Time Features API.

This module provides endpoints for WebSocket connections, live trending updates,
and cache invalidation management.
"""

from contextlib import suppress
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
import structlog


logger = structlog.get_logger(__name__)

# Create API router
router = APIRouter(prefix="/api/realtime", tags=["Real-Time Features"])


# Request/Response Models


class TrendingRequest(BaseModel):
    """Request for trending items."""

    category: Literal["artists", "genres", "releases"] = Field("artists", description="Trending category")
    limit: int = Field(10, description="Number of trending items", ge=1, le=50)
    time_window: Literal["hour", "day", "week"] = Field("day", description="Time window for trending calculation")


class SubscribeRequest(BaseModel):
    """Request to subscribe to real-time channels."""

    channels: list[str] = Field(..., description="Channel names to subscribe to")
    connection_id: str | None = Field(None, description="Optional connection ID")


class CacheInvalidateRequest(BaseModel):
    """Request for manual cache invalidation."""

    pattern: str = Field(..., description="Cache key pattern to invalidate")
    scope: Literal["exact", "prefix", "pattern", "all"] = Field("prefix", description="Invalidation scope")


# Module-level instances (initialized on startup)
realtime_api_initialized = False
active_websocket_connections: list[WebSocket] = []
websocket_manager: Any = None
trend_tracker: Any = None
cache_invalidation_manager: Any = None


async def initialize_realtime_api(neo4j_driver: Any) -> None:
    """Initialize Real-Time Features API components.

    Args:
        neo4j_driver: Neo4j async driver instance
    """
    global realtime_api_initialized, websocket_manager, trend_tracker, cache_invalidation_manager

    logger.info("🚀 Initializing Real-Time Features API components...")

    # Import Phase 3 components
    from discovery.cache_invalidation import CacheInvalidationManager
    from discovery.trend_tracking import TrendTracker
    from discovery.websocket_manager import WebSocketManager

    # Initialize components
    websocket_manager = WebSocketManager()
    trend_tracker = TrendTracker(neo4j_driver, websocket_manager)
    cache_invalidation_manager = CacheInvalidationManager()

    # Note: TrendTracker background task not started automatically
    # Requires explicit start() call in production environment

    realtime_api_initialized = True
    logger.info("✅ Real-Time Features API initialization complete")


async def close_realtime_api() -> None:
    """Close Real-Time Features API components and cleanup resources."""
    global realtime_api_initialized, active_websocket_connections

    logger.info("🛑 Closing Real-Time Features API components...")

    # Close all active WebSocket connections
    for ws in active_websocket_connections:
        with suppress(Exception):
            await ws.close()
    active_websocket_connections.clear()

    realtime_api_initialized = False
    logger.info("✅ Real-Time Features API components closed")


# API Endpoints


@router.post("/trending")  # type: ignore[untyped-decorator]
async def get_trending_endpoint(request: Request, req_body: TrendingRequest) -> dict[str, Any]:  # noqa: ARG001
    """Get current trending items.

    Returns trending artists, genres, or releases based on recent activity.

    Note: Trending requires background task to be running for real-time updates.
    This endpoint returns current cached trending data.

    Args:
        request: FastAPI request object (required for rate limiting)
        req_body: Request parameters

    Returns:
        Dictionary with trending items

    Raises:
        HTTPException: If real-time API not initialized
    """
    if not realtime_api_initialized or trend_tracker is None:
        raise HTTPException(status_code=503, detail="Real-Time Features API not initialized")

    logger.info(
        "📈 Trending request",
        category=req_body.category,
        time_window=req_body.time_window,
    )

    try:
        # Get trending items from TrendTracker
        trending_items = trend_tracker.get_trending(
            category=req_body.category,
            limit=req_body.limit,
        )

        # Convert TrendingItem dataclass instances to dicts
        trending_data = [
            {"item_id": item.item_id, "item_name": item.item_name, "score": item.score, "change": item.change} for item in trending_items
        ]

        return {
            "category": req_body.category,
            "time_window": req_body.time_window,
            "trending_items": trending_data,
            "total": len(trending_data),
            "status": "success",
            "note": "Trending data updated periodically by background task",
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"❌ Trending error: {e}")
        raise HTTPException(status_code=500, detail=f"Trending error: {e!s}") from e


@router.post("/subscribe")  # type: ignore[untyped-decorator]
async def subscribe_channels(request: Request, req_body: SubscribeRequest) -> dict[str, Any]:  # noqa: ARG001
    """Subscribe to real-time update channels.

    Manages subscriptions to channels like trending, discoveries, analytics, etc.

    Note: Actual subscription happens via WebSocket connection using message type "subscribe".
    This endpoint validates channel names and provides subscription instructions.

    Args:
        request: FastAPI request object (required for rate limiting)
        req_body: Request parameters

    Returns:
        Dictionary with subscription information

    Raises:
        HTTPException: If real-time API not initialized
    """
    if not realtime_api_initialized or websocket_manager is None:
        raise HTTPException(status_code=503, detail="Real-Time Features API not initialized")

    logger.info(
        "📡 Channel subscription info request",
        channels=req_body.channels,
    )

    # Import Channel enum for validation
    from discovery.websocket_manager import Channel

    # Validate channel names
    valid_channels = {c.value for c in Channel}
    requested_channels = req_body.channels
    valid_requested = [ch for ch in requested_channels if ch in valid_channels]
    invalid_requested = [ch for ch in requested_channels if ch not in valid_channels]

    return {
        "channels": req_body.channels,
        "valid_channels": valid_requested,
        "invalid_channels": invalid_requested,
        "available_channels": list(valid_channels),
        "subscription_method": "websocket",
        "instructions": {
            "websocket_url": "/api/realtime/ws",
            "message_format": {
                "type": "subscribe",
                "channel": "channel_name",
            },
        },
        "status": "success",
        "timestamp": datetime.now().isoformat(),
    }


@router.post("/cache/invalidate")  # type: ignore[untyped-decorator]
async def invalidate_cache(request: Request, req_body: CacheInvalidateRequest) -> dict[str, Any]:  # noqa: ARG001
    """Manually invalidate cache entries.

    Triggers cache invalidation based on patterns or scopes.

    Note: This endpoint requires cache backends to be registered with CacheInvalidationManager.
    Without registered backends, invalidation requests will be queued but not executed.

    Args:
        request: FastAPI request object (required for rate limiting)
        req_body: Request parameters

    Returns:
        Dictionary with invalidation results

    Raises:
        HTTPException: If real-time API not initialized
    """
    if not realtime_api_initialized or cache_invalidation_manager is None:
        raise HTTPException(status_code=503, detail="Real-Time Features API not initialized")

    logger.info(
        "🗑️ Cache invalidation request",
        pattern=req_body.pattern,
        scope=req_body.scope,
    )

    try:
        # Import required types
        from discovery.cache_invalidation import EventType, InvalidationScope

        # Map request scope to InvalidationScope enum
        scope_map = {
            "exact": InvalidationScope.EXACT,
            "prefix": InvalidationScope.PREFIX,
            "pattern": InvalidationScope.PATTERN,
            "all": InvalidationScope.ALL,
        }
        scope_enum = scope_map.get(req_body.scope, InvalidationScope.PREFIX)

        # Add invalidation rule for manual cache invalidation
        # Using ARTIST_UPDATED as a generic event type for manual invalidation
        cache_invalidation_manager.add_rule(
            event_types=EventType.ARTIST_UPDATED,  # Generic event for manual invalidation
            scope=scope_enum,
            target=req_body.pattern,
            priority=1000,  # High priority for manual invalidation
        )

        # Emit event to trigger invalidation
        await cache_invalidation_manager.emit_event(
            event_type=EventType.ARTIST_UPDATED,
            entity_id="manual_invalidation",
            entity_data={"pattern": req_body.pattern, "scope": req_body.scope},
        )

        # Process events immediately
        await cache_invalidation_manager.process_events()

        # Get statistics
        stats = cache_invalidation_manager.get_statistics()

        return {
            "pattern": req_body.pattern,
            "scope": req_body.scope,
            "invalidated_count": stats.get("invalidations", 0),
            "registered_backends": stats.get("backends", 0),
            "status": "success" if stats.get("backends", 0) > 0 else "partial",
            "message": (
                "Invalidation successful"
                if stats.get("backends", 0) > 0
                else "No cache backends registered. Register backends to enable cache invalidation."
            ),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"❌ Cache invalidation error: {e}")
        raise HTTPException(status_code=500, detail=f"Cache invalidation error: {e!s}") from e


@router.get("/ws/stats")  # type: ignore[untyped-decorator]
async def get_websocket_stats(request: Request) -> dict[str, Any]:  # noqa: ARG001
    """Get WebSocket connection statistics.

    Returns statistics about active connections and channels.

    Args:
        request: FastAPI request object (required for rate limiting)

    Returns:
        Dictionary with WebSocket statistics

    Raises:
        HTTPException: If real-time API not initialized
    """
    if not realtime_api_initialized or websocket_manager is None:
        raise HTTPException(status_code=503, detail="Real-Time Features API not initialized")

    logger.info("📊 WebSocket statistics request")

    try:
        # Get statistics from WebSocketManager
        stats = websocket_manager.get_statistics()

        return {
            "statistics": stats,
            "status": "success",
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"❌ WebSocket stats error: {e}")
        raise HTTPException(status_code=500, detail=f"WebSocket stats error: {e!s}") from e


@router.get("/status")  # type: ignore[untyped-decorator]
async def get_realtime_api_status(request: Request) -> dict[str, Any]:  # noqa: ARG001
    """Get Real-Time Features API status and feature availability.

    Args:
        request: FastAPI request object (required for rate limiting)

    Returns:
        Dictionary with API status and available features
    """
    return {
        "status": "initialized" if realtime_api_initialized else "not_initialized",
        "features": {
            "websocket": "active" if websocket_manager is not None else "unavailable",
            "trending": "active" if trend_tracker is not None else "unavailable",
            "subscriptions": "active" if websocket_manager is not None else "unavailable",
            "cache_invalidation": "partial" if cache_invalidation_manager is not None else "unavailable",
            "statistics": "active" if websocket_manager is not None else "unavailable",
        },
        "components": {
            "websocket_manager": websocket_manager is not None,
            "trend_tracker": trend_tracker is not None,
            "cache_invalidation_manager": cache_invalidation_manager is not None,
        },
        "active_connections": len(active_websocket_connections),
        "phase": "4.2 (Full Implementation)",
        "notes": {
            "cache_invalidation": "Requires cache backends to be registered for full functionality",
            "trending": "Requires TrendTracker background task to be started manually",
        },
        "timestamp": datetime.now().isoformat(),
    }


# WebSocket endpoint
@router.websocket("/ws")  # type: ignore[untyped-decorator]
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time updates.

    Handles WebSocket connections for live updates, trending notifications,
    and real-time analytics using WebSocketManager.

    Connection Flow:
    1. Client connects to /api/realtime/ws
    2. Server accepts connection and assigns connection_id
    3. Client can subscribe to channels via {"type": "subscribe", "channel": "channel_name"}
    4. Server broadcasts updates to subscribed channels
    5. Client can unsubscribe or disconnect

    Message Types:
    - subscribe: Subscribe to a channel
    - unsubscribe: Unsubscribe from a channel
    - ping: Keep connection alive
    - request: Request specific data (status, channels)

    Args:
        websocket: WebSocket connection
    """
    if websocket_manager is None:
        await websocket.close(code=1011, reason="WebSocket manager not initialized")
        return

    # Generate unique connection ID
    import uuid

    connection_id = str(uuid.uuid4())

    try:
        # Connect using WebSocketManager
        await websocket_manager.connect(websocket, connection_id)

        # Keep connection alive and handle messages
        while True:
            # Receive message from client
            message = await websocket.receive_json()

            # Handle message using WebSocketManager
            await websocket_manager.handle_message(connection_id, message)

    except WebSocketDisconnect:
        logger.info("🔌 WebSocket disconnected", connection_id=connection_id)
        await websocket_manager.disconnect(connection_id)
    except Exception as e:
        logger.error(f"❌ WebSocket error: {e}", connection_id=connection_id)
        await websocket_manager.disconnect(connection_id)
