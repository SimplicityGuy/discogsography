"""Internal computation query endpoints for the insights service.

Exposes raw Neo4j and PostgreSQL query results as JSON so the insights
service can fetch data over HTTP instead of importing query modules directly.
"""

import json
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
import structlog

from api.queries.insights_neo4j_queries import (
    query_artist_centrality,
    query_genre_trends,
    query_label_longevity,
    query_monthly_anniversaries,
)
from api.queries.insights_pg_queries import query_data_completeness


logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/internal/insights", tags=["insights-compute"])

_neo4j: Any = None
_pool: Any = None
_redis: Any = None

# Cache TTL for data-completeness (6 hours — full table scans are very expensive)
_COMPLETENESS_CACHE_TTL = 21600


def configure(neo4j: Any, pool: Any, redis: Any = None) -> None:
    """Configure the insights compute router with database connections."""
    global _neo4j, _pool, _redis
    _neo4j = neo4j
    _pool = pool
    _redis = redis


@router.get("/artist-centrality")
async def artist_centrality(limit: int = Query(100, ge=1, le=500)) -> JSONResponse:
    """Return raw artist centrality query results from Neo4j."""
    if not _neo4j:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)
    results = await query_artist_centrality(_neo4j, limit=limit)
    return JSONResponse(content={"items": results})


@router.get("/genre-trends")
async def genre_trends() -> JSONResponse:
    """Return raw genre trends query results from Neo4j."""
    if not _neo4j:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)
    results = await query_genre_trends(_neo4j)
    return JSONResponse(content={"items": results})


@router.get("/label-longevity")
async def label_longevity(limit: int = Query(50, ge=1, le=500)) -> JSONResponse:
    """Return raw label longevity query results from Neo4j."""
    if not _neo4j:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)
    results = await query_label_longevity(_neo4j, limit=limit)
    return JSONResponse(content={"items": results})


@router.get("/anniversaries")
async def anniversaries(
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    milestones: str = Query("25,30,40,50,75,100"),
) -> JSONResponse:
    """Return raw monthly anniversary query results from Neo4j."""
    if not _neo4j:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)
    milestone_years = [int(m.strip()) for m in milestones.split(",") if m.strip()]
    results = await query_monthly_anniversaries(_neo4j, current_year=year, current_month=month, milestone_years=milestone_years)
    return JSONResponse(content={"items": results})


@router.get("/data-completeness")
async def data_completeness() -> JSONResponse:
    """Return raw data completeness query results from PostgreSQL.

    Caches results in Redis (6h TTL) because the underlying queries do
    full sequential scans — the releases table alone takes ~400s.
    """
    if not _pool:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    cache_key = "insights:data-completeness"
    if _redis:
        try:
            cached = await _redis.get(cache_key)
            if cached:
                return JSONResponse(content=json.loads(cached))
        except Exception:
            logger.debug("⚠️ Data completeness cache get failed")

    results = await query_data_completeness(_pool)
    response = {"items": results}

    if _redis:
        try:
            await _redis.setex(cache_key, _COMPLETENESS_CACHE_TTL, json.dumps(response))
        except Exception:
            logger.debug("⚠️ Data completeness cache set failed")

    return JSONResponse(content=response)
