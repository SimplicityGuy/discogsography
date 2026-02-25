"""User endpoints — migrated from explore service."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import ORJSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import structlog

from api.auth import decode_token
from api.queries.user_queries import (
    check_releases_user_status,
    get_user_collection,
    get_user_collection_stats,
    get_user_recommendations,
    get_user_wantlist,
)


logger = structlog.get_logger(__name__)

router = APIRouter()
_security = HTTPBearer(auto_error=False)

_neo4j_driver: Any = None
_jwt_secret: str | None = None


def configure(neo4j: Any, jwt_secret: str | None) -> None:
    global _neo4j_driver, _jwt_secret
    _neo4j_driver = neo4j
    _jwt_secret = jwt_secret


async def _get_optional_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_security)],
) -> dict[str, Any] | None:
    if credentials is None or _jwt_secret is None:
        return None
    try:
        return decode_token(credentials.credentials, _jwt_secret)
    except ValueError:
        return None


async def _require_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_security)],
) -> dict[str, Any]:
    if _jwt_secret is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Personalized endpoints not enabled")
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required", headers={"WWW-Authenticate": "Bearer"})
    try:
        return decode_token(credentials.credentials, _jwt_secret)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token", headers={"WWW-Authenticate": "Bearer"}
        ) from exc


@router.get("/api/user/collection")
async def user_collection(
    current_user: Annotated[dict[str, Any], Depends(_require_user)],
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> ORJSONResponse:
    if not _neo4j_driver:
        return ORJSONResponse(content={"error": "Service not ready"}, status_code=503)
    user_id: str = current_user.get("sub", "")
    results, total = await get_user_collection(_neo4j_driver, user_id, limit, offset)
    return ORJSONResponse(content={"releases": results, "total": total, "offset": offset, "limit": limit, "has_more": offset + len(results) < total})


@router.get("/api/user/wantlist")
async def user_wantlist(
    current_user: Annotated[dict[str, Any], Depends(_require_user)],
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> ORJSONResponse:
    if not _neo4j_driver:
        return ORJSONResponse(content={"error": "Service not ready"}, status_code=503)
    user_id: str = current_user.get("sub", "")
    results, total = await get_user_wantlist(_neo4j_driver, user_id, limit, offset)
    return ORJSONResponse(content={"releases": results, "total": total, "offset": offset, "limit": limit, "has_more": offset + len(results) < total})


@router.get("/api/user/recommendations")
async def user_recommendations(
    current_user: Annotated[dict[str, Any], Depends(_require_user)],
    limit: int = Query(20, ge=1, le=100),
) -> ORJSONResponse:
    if not _neo4j_driver:
        return ORJSONResponse(content={"error": "Service not ready"}, status_code=503)
    user_id: str = current_user.get("sub", "")
    results = await get_user_recommendations(_neo4j_driver, user_id, limit)
    return ORJSONResponse(content={"recommendations": results, "total": len(results)})


@router.get("/api/user/collection/stats")
async def user_collection_stats(
    current_user: Annotated[dict[str, Any], Depends(_require_user)],
) -> ORJSONResponse:
    if not _neo4j_driver:
        return ORJSONResponse(content={"error": "Service not ready"}, status_code=503)
    user_id: str = current_user.get("sub", "")
    stats = await get_user_collection_stats(_neo4j_driver, user_id)
    return ORJSONResponse(content=stats)


@router.get("/api/user/status")
async def user_release_status(
    ids: str = Query(...),
    current_user: Annotated[dict[str, Any] | None, Depends(_get_optional_user)] = None,
) -> ORJSONResponse:
    release_ids = [rid.strip() for rid in ids.split(",") if rid.strip()]
    if not release_ids:
        return ORJSONResponse(content={"status": {}})
    if len(release_ids) > 100:
        return ORJSONResponse(content={"error": "Too many IDs: maximum is 100"}, status_code=422)
    if not _neo4j_driver or current_user is None:
        return ORJSONResponse(content={"status": {rid: {"in_collection": False, "in_wantlist": False} for rid in release_ids}})
    user_id: str = current_user.get("sub", "")
    status_map = await check_releases_user_status(_neo4j_driver, user_id, release_ids)
    result = {rid: status_map.get(rid, {"in_collection": False, "in_wantlist": False}) for rid in release_ids}
    return ORJSONResponse(content={"status": result})
