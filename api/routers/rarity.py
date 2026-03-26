"""Rarity scoring API endpoints.

Serves precomputed rarity scores from PostgreSQL, with Redis caching.
Artist and label endpoints also query Neo4j for release ID lookups.
"""

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
import structlog

from api.limiter import limiter
from api.queries.rarity_queries import (
    SIGNAL_WEIGHTS,
    get_rarity_by_artist,
    get_rarity_by_label,
    get_rarity_for_release,
    get_rarity_hidden_gems,
    get_rarity_leaderboard,
)


logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/rarity", tags=["rarity"])

_neo4j_driver: Any = None
_pg_pool: Any = None
_redis: Any = None

_CACHE_TTL = 3600  # 1 hour


def configure(neo4j: Any, pg_pool: Any, redis: Any = None) -> None:
    """Configure the rarity router with database connections."""
    global _neo4j_driver, _pg_pool, _redis
    _neo4j_driver = neo4j
    _pg_pool = pg_pool
    _redis = redis


def _format_breakdown(row: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Build the breakdown dict from a flat database row."""
    return {signal: {"score": row.get(signal, 0.0) or 0.0, "weight": weight} for signal, weight in SIGNAL_WEIGHTS.items()}


def _format_list_item(row: dict[str, Any]) -> dict[str, Any]:
    """Format a database row as a list item."""
    return {
        "release_id": row["release_id"],
        "title": row.get("title") or "",
        "artist": row.get("artist_name") or "",
        "year": row.get("year"),
        "rarity_score": row["rarity_score"],
        "tier": row["tier"],
        "hidden_gem_score": row.get("hidden_gem_score"),
    }


# ── Static path endpoints FIRST (before /{release_id}) ─────────────


@router.get("/leaderboard")
@limiter.limit("30/minute")
async def rarity_leaderboard(
    request: Request,  # noqa: ARG001
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tier: str | None = Query(None),
) -> JSONResponse:
    """Get global rarity leaderboard, paginated."""
    if not _pg_pool:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    items, total = await get_rarity_leaderboard(_pg_pool, page, page_size, tier)
    return JSONResponse(
        content={
            "items": [_format_list_item(r) for r in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/hidden-gems")
@limiter.limit("30/minute")
async def hidden_gems(
    request: Request,  # noqa: ARG001
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    min_rarity: float = Query(41.0, ge=0, le=100),
) -> JSONResponse:
    """Get top hidden gems sorted by hidden gem score."""
    if not _pg_pool:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    items, total = await get_rarity_hidden_gems(_pg_pool, page, page_size, min_rarity)
    return JSONResponse(
        content={
            "items": [_format_list_item(r) for r in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/artist/{artist_id}")
@limiter.limit("30/minute")
async def artist_rarity(
    request: Request,  # noqa: ARG001
    artist_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> JSONResponse:
    """Get rarest releases by a specific artist."""
    if not _pg_pool or not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    result = await get_rarity_by_artist(_neo4j_driver, _pg_pool, artist_id, page, page_size)
    if result is None:
        return JSONResponse(content={"error": "Artist not found"}, status_code=404)

    items, total = result
    return JSONResponse(
        content={
            "items": [_format_list_item(r) for r in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/label/{label_id}")
@limiter.limit("30/minute")
async def label_rarity(
    request: Request,  # noqa: ARG001
    label_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> JSONResponse:
    """Get rarest releases on a specific label."""
    if not _pg_pool or not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    result = await get_rarity_by_label(_neo4j_driver, _pg_pool, label_id, page, page_size)
    if result is None:
        return JSONResponse(content={"error": "Label not found"}, status_code=404)

    items, total = result
    return JSONResponse(
        content={
            "items": [_format_list_item(r) for r in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


# ── Parameterized path endpoint LAST ───────────────────────────────


@router.get("/{release_id}")
@limiter.limit("30/minute")
async def get_release_rarity(request: Request, release_id: int) -> JSONResponse:  # noqa: ARG001
    """Get full rarity breakdown for a single release."""
    if not _pg_pool:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    row = await get_rarity_for_release(_pg_pool, release_id)
    if row is None:
        return JSONResponse(content={"error": "Release rarity not found"}, status_code=404)

    return JSONResponse(
        content={
            "release_id": row["release_id"],
            "title": row.get("title") or "",
            "artist": row.get("artist_name") or "",
            "year": row.get("year"),
            "rarity_score": row["rarity_score"],
            "tier": row["tier"],
            "hidden_gem_score": row.get("hidden_gem_score"),
            "breakdown": _format_breakdown(row),
        }
    )
