#!/usr/bin/env python3
"""Explore service for interactive graph exploration of Discogs data."""

import asyncio
from collections import OrderedDict
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from fastapi.staticfiles import StaticFiles
import structlog

from common import (
    AsyncResilientNeo4jDriver,
    ExploreConfig,
    HealthServer,
    setup_logging,
)
from explore.models import SnapshotRequest, SnapshotResponse, SnapshotRestoreResponse
from explore.neo4j_indexes import create_all_indexes
from explore.neo4j_queries import (
    AUTOCOMPLETE_DISPATCH,
    COUNT_DISPATCH,
    DETAILS_DISPATCH,
    EXPAND_DISPATCH,
    EXPLORE_DISPATCH,
    TRENDS_DISPATCH,
)
from explore.snapshot_store import SnapshotStore


logger = structlog.get_logger(__name__)

# Module-level state
neo4j_driver: AsyncResilientNeo4jDriver | None = None
config: ExploreConfig | None = None
snapshot_store: SnapshotStore = SnapshotStore()


def get_health_data() -> dict[str, Any]:
    """Return health check data."""
    return {
        "status": "healthy" if neo4j_driver else "starting",
        "service": "explore",
        "timestamp": datetime.now(UTC).isoformat(),
    }


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """Manage application lifecycle."""
    logger.info("🚀 Starting Explore service")

    global neo4j_driver, config
    config = ExploreConfig.from_env()
    logger.info("📋 Configuration loaded from environment")

    # Start health server on separate port
    health_server = HealthServer(8007, get_health_data)
    health_server.start_background()
    logger.info("🏥 Health server started on port 8007")

    # Initialize Neo4j driver
    try:
        neo4j_driver = AsyncResilientNeo4jDriver(
            uri=config.neo4j_address,
            auth=(config.neo4j_username, config.neo4j_password),
            max_retries=5,
            encrypted=False,
        )
        logger.info("🔗 Connected to Neo4j with resilient driver")
    except Exception as e:
        logger.error("❌ Failed to connect to Neo4j", error=str(e))
        raise

    # Create indexes
    try:
        await create_all_indexes(config.neo4j_address, config.neo4j_username, config.neo4j_password)
        logger.info("📑 Neo4j indexes created/verified")
    except Exception as e:
        logger.warning("⚠️ Failed to create Neo4j indexes", error=str(e))

    logger.info("✅ Explore service ready")
    yield

    # Shutdown
    logger.info("🛑 Shutting down Explore service")
    if neo4j_driver:
        await neo4j_driver.close()
        logger.info("🔌 Neo4j connection closed")
    health_server.stop()
    logger.info("✅ Explore service shutdown complete")


app = FastAPI(
    title="Discogsography Explore",
    version="0.1.0",
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Autocomplete cache ---

_autocomplete_cache: OrderedDict[tuple[str, str, int], list[dict[str, Any]]] = OrderedDict()
_AUTOCOMPLETE_CACHE_MAX = 512


def _get_cache_key(query: str, entity_type: str, limit: int) -> tuple[str, str, int]:
    return (query.lower().strip(), entity_type, limit)


# --- API Endpoints ---


@app.get("/health")
async def health_check() -> ORJSONResponse:
    """Health check endpoint."""
    return ORJSONResponse(content=get_health_data())


@app.get("/api/autocomplete")
async def autocomplete(
    q: str = Query(..., min_length=2, description="Search query"),
    type: str = Query("artist", description="Entity type: artist, genre, label, style"),
    limit: int = Query(10, ge=1, le=50, description="Max results"),
) -> ORJSONResponse:
    """Autocomplete search for entities."""
    if not neo4j_driver:
        return ORJSONResponse(content={"error": "Service not ready"}, status_code=503)

    entity_type = type.lower()
    if entity_type not in AUTOCOMPLETE_DISPATCH:
        return ORJSONResponse(content={"error": f"Invalid type: {type}. Must be artist, genre, label, or style"}, status_code=400)

    # Check cache
    cache_key = _get_cache_key(q, entity_type, limit)
    if cache_key in _autocomplete_cache:
        return ORJSONResponse(content={"results": _autocomplete_cache[cache_key]})

    query_func = AUTOCOMPLETE_DISPATCH[entity_type]
    results = await query_func(neo4j_driver, q, limit)

    # Cache result (FIFO eviction using OrderedDict)
    if len(_autocomplete_cache) >= _AUTOCOMPLETE_CACHE_MAX:
        evict_count = _AUTOCOMPLETE_CACHE_MAX // 4
        for _ in range(evict_count):
            _autocomplete_cache.popitem(last=False)
    _autocomplete_cache[cache_key] = results

    return ORJSONResponse(content={"results": results})


@app.get("/api/explore")
async def explore(
    name: str = Query(..., description="Entity name to explore"),
    type: str = Query("artist", description="Entity type: artist, genre, label, style"),
) -> ORJSONResponse:
    """Get center node with category counts for graph exploration."""
    if not neo4j_driver:
        return ORJSONResponse(content={"error": "Service not ready"}, status_code=503)

    entity_type = type.lower()
    if entity_type not in EXPLORE_DISPATCH:
        return ORJSONResponse(content={"error": f"Invalid type: {type}. Must be artist, genre, label, or style"}, status_code=400)

    query_func = EXPLORE_DISPATCH[entity_type]
    result = await query_func(neo4j_driver, name)

    if not result:
        return ORJSONResponse(content={"error": f"{type.capitalize()} '{name}' not found"}, status_code=404)

    # Build category nodes based on type
    categories = _build_categories(entity_type, result)

    return ORJSONResponse(
        content={
            "center": {"id": str(result["id"]), "name": result["name"], "type": entity_type},
            "categories": categories,
        }
    )


def _build_categories(entity_type: str, result: dict[str, Any]) -> list[dict[str, Any]]:
    """Build artificial category nodes from explore result."""
    categories = []

    if entity_type == "artist":
        categories = [
            {"id": "cat-releases", "name": "Releases", "category": "releases", "count": result.get("release_count", 0)},
            {"id": "cat-labels", "name": "Labels", "category": "labels", "count": result.get("label_count", 0)},
            {"id": "cat-aliases", "name": "Aliases & Members", "category": "aliases", "count": result.get("alias_count", 0)},
        ]
    elif entity_type == "genre":
        categories = [
            {"id": "cat-releases", "name": "Releases", "category": "releases", "count": result.get("release_count", 0)},
            {"id": "cat-artists", "name": "Artists", "category": "artists", "count": result.get("artist_count", 0)},
            {"id": "cat-labels", "name": "Labels", "category": "labels", "count": result.get("label_count", 0)},
            {"id": "cat-styles", "name": "Styles", "category": "styles", "count": result.get("style_count", 0)},
        ]
    elif entity_type == "label":
        categories = [
            {"id": "cat-releases", "name": "Releases", "category": "releases", "count": result.get("release_count", 0)},
            {"id": "cat-artists", "name": "Artists", "category": "artists", "count": result.get("artist_count", 0)},
            {"id": "cat-genres", "name": "Genres", "category": "genres", "count": result.get("genre_count", 0)},
        ]
    elif entity_type == "style":
        categories = [
            {"id": "cat-releases", "name": "Releases", "category": "releases", "count": result.get("release_count", 0)},
            {"id": "cat-artists", "name": "Artists", "category": "artists", "count": result.get("artist_count", 0)},
            {"id": "cat-labels", "name": "Labels", "category": "labels", "count": result.get("label_count", 0)},
            {"id": "cat-genres", "name": "Genres", "category": "genres", "count": result.get("genre_count", 0)},
        ]

    return categories


@app.get("/api/expand")
async def expand(
    node_id: str = Query(..., description="Parent entity name"),
    type: str = Query(..., description="Parent entity type: artist, genre, label, style"),
    category: str = Query(..., description="Category to expand: releases, labels, aliases, artists, styles, genres"),
    limit: int = Query(50, ge=1, le=200, description="Max results per page"),
    offset: int = Query(0, ge=0, description="Number of results to skip (for pagination)"),
) -> ORJSONResponse:
    """Expand a category node to get its children, with pagination."""
    if not neo4j_driver:
        return ORJSONResponse(content={"error": "Service not ready"}, status_code=503)

    entity_type = type.lower()
    category_lower = category.lower()

    if entity_type not in EXPAND_DISPATCH:
        return ORJSONResponse(content={"error": f"Invalid type: {type}"}, status_code=400)

    type_categories = EXPAND_DISPATCH[entity_type]
    if category_lower not in type_categories:
        valid = ", ".join(type_categories.keys())
        return ORJSONResponse(content={"error": f"Invalid category '{category}' for type '{type}'. Valid: {valid}"}, status_code=400)

    query_func = type_categories[category_lower]
    count_func = COUNT_DISPATCH[entity_type][category_lower]

    results, total = await asyncio.gather(
        query_func(neo4j_driver, node_id, limit, offset),
        count_func(neo4j_driver, node_id),
    )

    return ORJSONResponse(
        content={
            "children": results,
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + len(results) < total,
        }
    )


@app.get("/api/node/{node_id}")
async def get_node_details(
    node_id: str,
    type: str = Query("artist", description="Node type: artist, release, label, genre, style"),
) -> ORJSONResponse:
    """Get full details for a specific node."""
    if not neo4j_driver:
        return ORJSONResponse(content={"error": "Service not ready"}, status_code=503)

    entity_type = type.lower()
    if entity_type not in DETAILS_DISPATCH:
        return ORJSONResponse(content={"error": f"Invalid type: {type}"}, status_code=400)

    query_func = DETAILS_DISPATCH[entity_type]
    result = await query_func(neo4j_driver, node_id)

    if not result:
        return ORJSONResponse(content={"error": f"{type.capitalize()} '{node_id}' not found"}, status_code=404)

    return ORJSONResponse(content=result)


@app.get("/api/trends")
async def get_trends(
    name: str = Query(..., description="Entity name"),
    type: str = Query("artist", description="Entity type: artist, genre, label, style"),
) -> ORJSONResponse:
    """Get time-series release counts for an entity."""
    if not neo4j_driver:
        return ORJSONResponse(content={"error": "Service not ready"}, status_code=503)

    entity_type = type.lower()
    if entity_type not in TRENDS_DISPATCH:
        return ORJSONResponse(content={"error": f"Invalid type: {type}. Must be artist, genre, label, or style"}, status_code=400)

    query_func = TRENDS_DISPATCH[entity_type]
    results = await query_func(neo4j_driver, name)

    return ORJSONResponse(
        content={
            "name": name,
            "type": entity_type,
            "data": results,
        }
    )


@app.post("/api/snapshot", status_code=201)
async def save_snapshot(body: SnapshotRequest) -> ORJSONResponse:
    """Save a graph snapshot and return a shareable token."""
    if len(body.nodes) > snapshot_store.max_nodes:
        return ORJSONResponse(
            content={"error": f"Too many nodes: maximum is {snapshot_store.max_nodes}"},
            status_code=422,
        )

    nodes = [n.model_dump() for n in body.nodes]
    center = body.center.model_dump()
    token, expires_at = snapshot_store.save(nodes, center)

    response = SnapshotResponse(
        token=token,
        url=f"/snapshot/{token}",
        expires_at=expires_at.isoformat(),
    )
    return ORJSONResponse(content=response.model_dump(), status_code=201)


@app.get("/api/snapshot/{token}")
async def restore_snapshot(token: str) -> ORJSONResponse:
    """Restore a graph snapshot by token."""
    entry = snapshot_store.load(token)
    if entry is None:
        return ORJSONResponse(content={"error": "Snapshot not found or expired"}, status_code=404)

    response = SnapshotRestoreResponse(
        nodes=entry["nodes"],
        center=entry["center"],
        created_at=entry["created_at"],
    )
    return ORJSONResponse(content=response.model_dump())


# Mount static files for the UI
static_dir = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    setup_logging("explore", log_file=Path("/logs/explore.log"))

    # fmt: off
    print("██████╗ ██╗███████╗ ██████╗ ██████╗  ██████╗ ███████╗               ")
    print("██╔══██╗██║██╔════╝██╔════╝██╔═══██╗██╔════╝ ██╔════╝               ")
    print("██║  ██║██║███████╗██║     ██║   ██║██║  ███╗███████╗               ")
    print("██║  ██║██║╚════██║██║     ██║   ██║██║   ██║╚════██║               ")
    print("██████╔╝██║███████║╚██████╗╚██████╔╝╚██████╔╝███████║               ")
    print("╚═════╝ ╚═╝╚══════╝ ╚═════╝ ╚═════╝  ╚═════╝ ╚══════╝               ")
    print("                                                                     ")
    print("███████╗██╗  ██╗██████╗ ██╗      ██████╗ ██████╗ ███████╗            ")
    print("██╔════╝╚██╗██╔╝██╔══██╗██║     ██╔═══██╗██╔══██╗██╔════╝            ")
    print("█████╗   ╚███╔╝ ██████╔╝██║     ██║   ██║██████╔╝█████╗              ")
    print("██╔══╝   ██╔██╗ ██╔═══╝ ██║     ██║   ██║██╔══██╗██╔══╝              ")
    print("███████╗██╔╝ ██╗██║     ███████╗╚██████╔╝██║  ██║███████╗            ")
    print("╚══════╝╚═╝  ╚═╝╚═╝     ╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚══════╝            ")
    print()
    # fmt: on

    uvicorn.run(
        "explore.explore:app",
        host="0.0.0.0",  # noqa: S104  # nosec B104
        port=8006,
        reload=False,
        log_level="info",
    )
