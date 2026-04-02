"""User endpoints — migrated from explore service."""

import asyncio
from collections import OrderedDict
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
import structlog

from api.dependencies import get_optional_user, require_user
from api.queries.recommend_queries import (
    get_blindspot_candidates,
    get_collector_counts,
    get_label_affinity_candidates,
    merge_recommendation_candidates,
)
from api.queries.user_queries import (
    check_releases_user_status,
    get_user_collection,
    get_user_collection_evolution,
    get_user_collection_stats,
    get_user_collection_timeline,
    get_user_recommendations,
    get_user_wantlist,
)


logger = structlog.get_logger(__name__)

router = APIRouter()

_neo4j_driver: Any = None

# In-memory cache for timeline/evolution queries (keyed by user_id + params)
_timeline_cache: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
_TIMELINE_CACHE_MAX = 128
_TIMELINE_CACHE_TTL = 300  # 5 minutes
_timeline_cache_lock: asyncio.Lock | None = None  # lazy init to avoid binding to wrong event loop


def configure(neo4j: Any, jwt_secret: str | None) -> None:  # noqa: ARG001
    global _neo4j_driver
    _neo4j_driver = neo4j


def _get_cached(key: str) -> dict[str, Any] | None:
    """Get from cache. Caller must hold _timeline_cache_lock."""
    entry = _timeline_cache.get(key)
    if entry is None:
        return None
    ts, data = entry
    if time.monotonic() - ts > _TIMELINE_CACHE_TTL:
        _timeline_cache.pop(key, None)
        return None
    _timeline_cache.move_to_end(key)
    return data


def _set_cached(key: str, data: dict[str, Any]) -> None:
    """Write to cache. Caller must hold _timeline_cache_lock."""
    _timeline_cache[key] = (time.monotonic(), data)
    _timeline_cache.move_to_end(key)
    while len(_timeline_cache) > _TIMELINE_CACHE_MAX:
        _timeline_cache.popitem(last=False)


@router.get("/api/user/collection")
async def user_collection(
    current_user: Annotated[dict[str, Any], Depends(require_user)],
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> JSONResponse:
    if not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)
    user_id: str = current_user.get("sub", "")
    results, total = await get_user_collection(_neo4j_driver, user_id, limit, offset)
    return JSONResponse(content={"releases": results, "total": total, "offset": offset, "limit": limit, "has_more": offset + len(results) < total})


@router.get("/api/user/wantlist")
async def user_wantlist(
    current_user: Annotated[dict[str, Any], Depends(require_user)],
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> JSONResponse:
    if not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)
    user_id: str = current_user.get("sub", "")
    results, total = await get_user_wantlist(_neo4j_driver, user_id, limit, offset)
    return JSONResponse(content={"releases": results, "total": total, "offset": offset, "limit": limit, "has_more": offset + len(results) < total})


@router.get("/api/user/recommendations")
async def user_recommendations(
    current_user: Annotated[dict[str, Any], Depends(require_user)],
    limit: int = Query(20, ge=1, le=100),
    strategy: str = Query("artist", pattern="^(artist|multi)$"),
) -> JSONResponse:
    if not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)
    user_id: str = current_user.get("sub", "")

    if strategy == "artist":
        results = await get_user_recommendations(_neo4j_driver, user_id, limit)
        # Normalize raw count scores to 0-1 range
        if results:
            max_score = max(r.get("score", 0) for r in results)
            if max_score > 0:
                for r in results:
                    r["score"] = round(r.get("score", 0) / max_score, 4)
        return JSONResponse(content={"recommendations": results, "total": len(results)})

    # Multi-signal strategy
    artist_results, label_results, blindspot_results = await asyncio.gather(
        get_user_recommendations(_neo4j_driver, user_id, limit=50),
        get_label_affinity_candidates(_neo4j_driver, user_id, limit=50),
        get_blindspot_candidates(_neo4j_driver, user_id, limit=50),
    )

    # Normalize artist results to candidate format
    artist_candidates = [
        {
            "id": r["id"],
            "title": r.get("title"),
            "artist": r.get("artist"),
            "label": r.get("label"),
            "year": r.get("year"),
            "genres": r.get("genres", []),
            "score": r.get("score", 0),
            "source": f"artist: collected {r.get('score', 0)} releases",
        }
        for r in artist_results
    ]

    # Collect all unique release IDs for obscurity scoring
    all_ids = list({c["id"] for candidates in [artist_candidates, label_results, blindspot_results] for c in candidates if c.get("id")})
    collector_counts = await get_collector_counts(_neo4j_driver, all_ids) if all_ids else {}

    merged = merge_recommendation_candidates(
        artist_candidates,
        label_results,
        blindspot_results,
        collector_counts=collector_counts,
        limit=limit,
    )

    return JSONResponse(
        content={
            "recommendations": merged,
            "total": len(merged),
            "strategy": "multi",
        }
    )


@router.get("/api/user/collection/stats")
async def user_collection_stats(
    current_user: Annotated[dict[str, Any], Depends(require_user)],
) -> JSONResponse:
    if not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)
    user_id: str = current_user.get("sub", "")
    stats = await get_user_collection_stats(_neo4j_driver, user_id)
    return JSONResponse(content=stats)


@router.get("/api/user/collection/timeline")
async def user_collection_timeline(
    current_user: Annotated[dict[str, Any], Depends(require_user)],
    bucket: str = Query("year", pattern="^(year|decade)$"),
) -> JSONResponse:
    if not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)
    user_id: str = current_user.get("sub", "")
    global _timeline_cache_lock
    if _timeline_cache_lock is None:
        _timeline_cache_lock = asyncio.Lock()
    cache_key = f"timeline:{user_id}:{bucket}"
    async with _timeline_cache_lock:
        cached = _get_cached(cache_key)
    if cached is not None:
        return JSONResponse(content=cached)
    result = await get_user_collection_timeline(_neo4j_driver, user_id, bucket)
    async with _timeline_cache_lock:
        _set_cached(cache_key, result)
    return JSONResponse(content=result)


@router.get("/api/user/collection/evolution")
async def user_collection_evolution(
    current_user: Annotated[dict[str, Any], Depends(require_user)],
    metric: str = Query("genre", pattern="^(genre|style|label)$"),
) -> JSONResponse:
    if not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)
    user_id: str = current_user.get("sub", "")
    global _timeline_cache_lock
    if _timeline_cache_lock is None:
        _timeline_cache_lock = asyncio.Lock()
    cache_key = f"evolution:{user_id}:{metric}"
    async with _timeline_cache_lock:
        cached = _get_cached(cache_key)
    if cached is not None:
        return JSONResponse(content=cached)
    result = await get_user_collection_evolution(_neo4j_driver, user_id, metric)
    async with _timeline_cache_lock:
        _set_cached(cache_key, result)
    return JSONResponse(content=result)


@router.get("/api/user/status")
async def user_release_status(
    ids: str = Query(...),
    current_user: Annotated[dict[str, Any] | None, Depends(get_optional_user)] = None,
) -> JSONResponse:
    release_ids = [rid.strip() for rid in ids.split(",") if rid.strip()]
    if not release_ids:
        return JSONResponse(content={"status": {}})
    if len(release_ids) > 100:
        return JSONResponse(content={"error": "Too many IDs: maximum is 100"}, status_code=422)
    if not _neo4j_driver or current_user is None:
        return JSONResponse(content={"status": {rid: {"in_collection": False, "in_wantlist": False} for rid in release_ids}})
    user_id: str = current_user.get("sub", "")
    status_map = await check_releases_user_status(_neo4j_driver, user_id, release_ids)
    result = {rid: status_map.get(rid, {"in_collection": False, "in_wantlist": False}) for rid in release_ids}
    return JSONResponse(content={"status": result})
