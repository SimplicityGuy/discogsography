"""User endpoints — migrated from explore service."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
import structlog

import api.dependencies as _dependencies
from api.dependencies import get_optional_user, require_user
from api.queries.user_queries import (
    check_releases_user_status,
    get_user_collection,
    get_user_collection_stats,
    get_user_recommendations,
    get_user_wantlist,
)


logger = structlog.get_logger(__name__)

router = APIRouter()

_neo4j_driver: Any = None


def configure(neo4j: Any, jwt_secret: str | None) -> None:
    global _neo4j_driver
    _neo4j_driver = neo4j
    _dependencies.configure(jwt_secret)


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
) -> JSONResponse:
    if not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)
    user_id: str = current_user.get("sub", "")
    results = await get_user_recommendations(_neo4j_driver, user_id, limit)
    return JSONResponse(content={"recommendations": results, "total": len(results)})


@router.get("/api/user/collection/stats")
async def user_collection_stats(
    current_user: Annotated[dict[str, Any], Depends(require_user)],
) -> JSONResponse:
    if not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)
    user_id: str = current_user.get("sub", "")
    stats = await get_user_collection_stats(_neo4j_driver, user_id)
    return JSONResponse(content=stats)


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
