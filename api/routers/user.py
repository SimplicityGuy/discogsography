"""User endpoints — migrated from explore service."""

import base64
from datetime import UTC, datetime
import hashlib
import hmac
import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import ORJSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import structlog

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


def _b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def _verify_jwt(token: str, secret: str) -> dict[str, Any] | None:
    parts = token.split(".")
    if len(parts) != 3:
        return None
    header_b64, body_b64, sig_b64 = parts
    signing_input = f"{header_b64}.{body_b64}".encode("ascii")
    expected_sig = base64.urlsafe_b64encode(hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()).rstrip(b"=").decode("ascii")
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
    if credentials is None or _jwt_secret is None:
        return None
    return _verify_jwt(credentials.credentials, _jwt_secret)


async def _require_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_security)],
) -> dict[str, Any]:
    if _jwt_secret is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Personalized endpoints not enabled")
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required", headers={"WWW-Authenticate": "Bearer"})
    payload = _verify_jwt(credentials.credentials, _jwt_secret)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token", headers={"WWW-Authenticate": "Bearer"})
    return payload


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
    if not _neo4j_driver or current_user is None:
        return ORJSONResponse(content={"status": {rid: {"in_collection": False, "in_wantlist": False} for rid in release_ids}})
    user_id: str = current_user.get("sub", "")
    status_map = await check_releases_user_status(_neo4j_driver, user_id, release_ids)
    result = {rid: status_map.get(rid, {"in_collection": False, "in_wantlist": False}) for rid in release_ids}
    return ORJSONResponse(content={"status": result})
