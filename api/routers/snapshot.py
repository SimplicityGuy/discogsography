"""Snapshot endpoints — migrated from explore service."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import redis.asyncio as aioredis

from api.auth import decode_token
from api.models import SnapshotRequest, SnapshotResponse, SnapshotRestoreResponse
from api.snapshot_store import SnapshotStore


router = APIRouter()
_snapshot_store: SnapshotStore | None = None
_security = HTTPBearer()
_jwt_secret: str | None = None


def configure(
    jwt_secret: str | None,
    redis_client: aioredis.Redis | None = None,
    ttl_days: int = 28,
    max_nodes: int = 100,
) -> None:
    global _snapshot_store, _jwt_secret
    _jwt_secret = jwt_secret
    _snapshot_store = SnapshotStore(redis_client, ttl_days=ttl_days, max_nodes=max_nodes) if redis_client is not None else None


async def _get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_security)],
) -> dict[str, Any]:
    if _jwt_secret is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not configured")
    try:
        return decode_token(credentials.credentials, _jwt_secret)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


@router.post("/api/snapshot", status_code=201)
async def save_snapshot(
    body: SnapshotRequest,
    _current_user: Annotated[dict[str, Any], Depends(_get_current_user)],
) -> JSONResponse:
    if _snapshot_store is None:
        return JSONResponse(content={"error": "Snapshot service not ready"}, status_code=503)
    if len(body.nodes) > _snapshot_store.max_nodes:
        return JSONResponse(content={"error": f"Too many nodes: maximum is {_snapshot_store.max_nodes}"}, status_code=422)
    nodes = [n.model_dump() for n in body.nodes]
    center = body.center.model_dump()
    token, expires_at = await _snapshot_store.save(nodes, center)
    response = SnapshotResponse(token=token, url=f"/snapshot/{token}", expires_at=expires_at.isoformat())
    return JSONResponse(content=response.model_dump(), status_code=201)


@router.get("/api/snapshot/{token}")
async def restore_snapshot(token: str) -> JSONResponse:
    if _snapshot_store is None:
        return JSONResponse(content={"error": "Snapshot service not ready"}, status_code=503)
    entry = await _snapshot_store.load(token)
    if entry is None:
        return JSONResponse(content={"error": "Snapshot not found or expired"}, status_code=404)
    response = SnapshotRestoreResponse(nodes=entry["nodes"], center=entry["center"], created_at=entry["created_at"])
    return JSONResponse(content=response.model_dump())
