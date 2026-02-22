#!/usr/bin/env python3
"""Explore service for interactive graph exploration of Discogs data."""

import asyncio
import base64
import hashlib
import hmac
import json
from collections import OrderedDict
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
import structlog

from common import (
    AsyncResilientNeo4jDriver,
    ExploreConfig,
    HealthServer,
    setup_logging,
)
from explore.models import SnapshotRequest, SnapshotResponse, SnapshotRestoreResponse
from explore.neo4j_queries import (
    AUTOCOMPLETE_DISPATCH,
    COUNT_DISPATCH,
    DETAILS_DISPATCH,
    EXPAND_DISPATCH,
    EXPLORE_DISPATCH,
    TRENDS_DISPATCH,
)
from explore.snapshot_store import SnapshotStore
from explore.user_queries import (
    check_releases_user_status,
    get_user_collection,
    get_user_collection_stats,
    get_user_recommendations,
    get_user_wantlist,
)


logger = structlog.get_logger(__name__)

# Module-level state
neo4j_driver: AsyncResilientNeo4jDriver | None = None
config: ExploreConfig | None = None
snapshot_store: SnapshotStore = SnapshotStore()

_security = HTTPBearer(auto_error=False)


def _b64url_decode(s: str) -> bytes:
    """Decode a base64url-encoded string (without padding)."""
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def _verify_jwt(token: str, secret: str) -> dict[str, Any] | None:
    """Verify a JWT token and return the payload, or None if invalid/expired."""
    parts = token.split(".")
    if len(parts) != 3:
        return None

    header_b64, body_b64, sig_b64 = parts
    signing_input = f"{header_b64}.{body_b64}".encode("ascii")
    expected_sig = base64.urlsafe_b64encode(
        hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    ).rstrip(b"=").decode("ascii")

    if not hmac.compare_digest(sig_b64, expected_sig):
        return None

    try:
        payload: dict[str, Any] = json.loads(_b64url_decode(body_b64))
    except Exception:
        return None

    exp = payload.get("exp")
    if exp and datetime.fromtimestamp(int(exp), UTC) < datetime.now(UTC):
        return None

    return payload


async def _get_optional_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_security)],
) -> dict[str, Any] | None:
    """Extract JWT payload if a valid bearer token is provided; returns None otherwise."""
    if credentials is None or config is None or config.jwt_secret_key is None:
        return None
    return _verify_jwt(credentials.credentials, config.jwt_secret_key)


async def _require_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_security)],
) -> dict[str, Any]:
    """Require a valid JWT; raises 401 if missing or invalid."""
    if config is None or config.jwt_secret_key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Personalized endpoints not enabled (JWT_SECRET_KEY not configured)",
        )
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = _verify_jwt(credentials.credentials, config.jwt_secret_key)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


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
    if entity_type == "artist":
        return [
            {"id": "cat-releases", "name": "Releases", "category": "releases", "count": result.get("release_count", 0)},
            {"id": "cat-labels", "name": "Labels", "category": "labels", "count": result.get("label_count", 0)},
            {"id": "cat-aliases", "name": "Aliases & Members", "category": "aliases", "count": result.get("alias_count", 0)},
        ]
    if entity_type == "genre":
        return [
            {"id": "cat-releases", "name": "Releases", "category": "releases", "count": result.get("release_count", 0)},
            {"id": "cat-artists", "name": "Artists", "category": "artists", "count": result.get("artist_count", 0)},
            {"id": "cat-labels", "name": "Labels", "category": "labels", "count": result.get("label_count", 0)},
            {"id": "cat-styles", "name": "Styles", "category": "styles", "count": result.get("style_count", 0)},
        ]
    if entity_type == "label":
        return [
            {"id": "cat-releases", "name": "Releases", "category": "releases", "count": result.get("release_count", 0)},
            {"id": "cat-artists", "name": "Artists", "category": "artists", "count": result.get("artist_count", 0)},
            {"id": "cat-genres", "name": "Genres", "category": "genres", "count": result.get("genre_count", 0)},
        ]
    if entity_type == "style":
        return [
            {"id": "cat-releases", "name": "Releases", "category": "releases", "count": result.get("release_count", 0)},
            {"id": "cat-artists", "name": "Artists", "category": "artists", "count": result.get("artist_count", 0)},
            {"id": "cat-labels", "name": "Labels", "category": "labels", "count": result.get("label_count", 0)},
            {"id": "cat-genres", "name": "Genres", "category": "genres", "count": result.get("genre_count", 0)},
        ]
    return []


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


# --- Personalized user endpoints ---


@app.get("/api/user/collection")
async def user_collection(
    current_user: Annotated[dict[str, Any], Depends(_require_user)],
    limit: int = Query(50, ge=1, le=200, description="Max results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
) -> ORJSONResponse:
    """Get the authenticated user's Discogs collection from Neo4j."""
    if not neo4j_driver:
        return ORJSONResponse(content={"error": "Service not ready"}, status_code=503)

    user_id: str = current_user.get("sub", "")
    results, total = await get_user_collection(neo4j_driver, user_id, limit, offset)

    return ORJSONResponse(
        content={
            "releases": results,
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + len(results) < total,
        }
    )


@app.get("/api/user/wantlist")
async def user_wantlist(
    current_user: Annotated[dict[str, Any], Depends(_require_user)],
    limit: int = Query(50, ge=1, le=200, description="Max results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
) -> ORJSONResponse:
    """Get the authenticated user's Discogs wantlist from Neo4j."""
    if not neo4j_driver:
        return ORJSONResponse(content={"error": "Service not ready"}, status_code=503)

    user_id: str = current_user.get("sub", "")
    results, total = await get_user_wantlist(neo4j_driver, user_id, limit, offset)

    return ORJSONResponse(
        content={
            "releases": results,
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + len(results) < total,
        }
    )


@app.get("/api/user/recommendations")
async def user_recommendations(
    current_user: Annotated[dict[str, Any], Depends(_require_user)],
    limit: int = Query(20, ge=1, le=100, description="Max results"),
) -> ORJSONResponse:
    """Get release recommendations based on artists in user's collection."""
    if not neo4j_driver:
        return ORJSONResponse(content={"error": "Service not ready"}, status_code=503)

    user_id: str = current_user.get("sub", "")
    results = await get_user_recommendations(neo4j_driver, user_id, limit)

    return ORJSONResponse(content={"recommendations": results, "total": len(results)})


@app.get("/api/user/collection/stats")
async def user_collection_stats(
    current_user: Annotated[dict[str, Any], Depends(_require_user)],
) -> ORJSONResponse:
    """Get statistics for the authenticated user's collection grouped by genre, decade, and label."""
    if not neo4j_driver:
        return ORJSONResponse(content={"error": "Service not ready"}, status_code=503)

    user_id: str = current_user.get("sub", "")
    stats = await get_user_collection_stats(neo4j_driver, user_id)

    return ORJSONResponse(content=stats)


@app.get("/api/user/status")
async def user_release_status(
    ids: str = Query(..., description="Comma-separated release IDs to check"),
    current_user: Annotated[dict[str, Any] | None, Depends(_get_optional_user)] = None,
) -> ORJSONResponse:
    """Check which of the given release IDs are in the user's collection or wantlist.

    Returns in_collection/in_wantlist flags for each provided release ID.
    If no valid auth token is provided, all flags default to false.
    """
    release_ids = [rid.strip() for rid in ids.split(",") if rid.strip()]
    if not release_ids:
        return ORJSONResponse(content={"status": {}})

    if not neo4j_driver or current_user is None:
        return ORJSONResponse(content={"status": {rid: {"in_collection": False, "in_wantlist": False} for rid in release_ids}})

    user_id: str = current_user.get("sub", "")
    status_map = await check_releases_user_status(neo4j_driver, user_id, release_ids)

    # Fill in missing IDs with defaults
    result = {rid: status_map.get(rid, {"in_collection": False, "in_wantlist": False}) for rid in release_ids}
    return ORJSONResponse(content={"status": result})


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
