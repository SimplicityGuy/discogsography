"""Snapshot endpoints — migrated from explore service."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import redis.asyncio as aioredis

from api.auth import REASON_CREDENTIALS_CHANGED, REASON_REVOKED, decode_token, token_revocation_reason
from api.limiter import bearer_token_key_func, limiter
from api.models import SnapshotRequest, SnapshotResponse, SnapshotRestoreResponse
from api.snapshot_store import SnapshotQuotaExceededError, SnapshotStore, SnapshotTooLargeError


router = APIRouter()
_snapshot_store: SnapshotStore | None = None
_security = HTTPBearer()
_jwt_secret: str | None = None
_redis: aioredis.Redis | None = None


def configure(
    jwt_secret: str | None,
    redis_client: aioredis.Redis | None = None,
    ttl_days: int = 28,
    max_nodes: int = 100,
) -> None:
    global _snapshot_store, _jwt_secret, _redis
    _jwt_secret = jwt_secret
    _redis = redis_client
    _snapshot_store = SnapshotStore(redis_client, ttl_days=ttl_days, max_nodes=max_nodes) if redis_client is not None else None


async def _get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_security)],
) -> dict[str, Any]:
    if _jwt_secret is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not configured")
    try:
        payload = decode_token(credentials.credentials, _jwt_secret)
        # Reject admin tokens
        if payload.get("type") == "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin tokens cannot be used for user endpoints")
        # Allowlist: only pure access tokens (which carry NO `type` claim) may
        # authenticate. A 2FA challenge token (type="2fa_challenge") proves only the
        # password and must be rejected before TOTP verification.
        if payload.get("type") is not None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token", headers={"WWW-Authenticate": "Bearer"})
        # Validate sub claim presence
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token", headers={"WWW-Authenticate": "Bearer"})
        # Revocation (jti blacklist via logout + password change) — shared with
        # every other auth site so no site can silently drift out of lockstep.
        reason = await token_revocation_reason(payload, _redis)
        if reason == REASON_REVOKED:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if reason == REASON_CREDENTIALS_CHANGED:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token invalidated by password change",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return payload
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


@router.post("/api/snapshot", status_code=201)
@limiter.limit("20/minute", key_func=bearer_token_key_func)
async def save_snapshot(
    request: Request,  # noqa: ARG001 — required by slowapi rate limiter
    body: SnapshotRequest,
    _current_user: Annotated[dict[str, Any], Depends(_get_current_user)],
) -> JSONResponse:
    if _snapshot_store is None:
        return JSONResponse(content={"error": "Snapshot service not ready"}, status_code=503)
    if len(body.nodes) > _snapshot_store.max_nodes:
        return JSONResponse(content={"error": f"Too many nodes: maximum is {_snapshot_store.max_nodes}"}, status_code=422)
    nodes = [n.model_dump() for n in body.nodes]
    center = body.center.model_dump()
    user_id = _current_user.get("sub")
    try:
        token, expires_at = await _snapshot_store.save(nodes, center, user_id=user_id)
    except SnapshotTooLargeError as exc:
        return JSONResponse(content={"error": str(exc)}, status_code=413)
    except SnapshotQuotaExceededError as exc:
        return JSONResponse(content={"error": str(exc)}, status_code=429)
    except ValueError as exc:
        # Defense-in-depth: SnapshotStore.save's own max_nodes guard, for any
        # direct caller that bypasses this router's pre-check above.
        return JSONResponse(content={"error": str(exc)}, status_code=422)
    response = SnapshotResponse(token=token, url=f"/snapshot/{token}", expires_at=expires_at.isoformat())
    return JSONResponse(content=response.model_dump(), status_code=201)


@router.get("/api/snapshot/{token}")
@limiter.limit("30/minute")
async def restore_snapshot(request: Request, token: str) -> JSONResponse:  # noqa: ARG001 — request required by slowapi rate limiter
    if _snapshot_store is None:
        return JSONResponse(content={"error": "Snapshot service not ready"}, status_code=503)
    entry = await _snapshot_store.load(token)
    if entry is None:
        return JSONResponse(content={"error": "Snapshot not found or expired"}, status_code=404)
    response = SnapshotRestoreResponse(nodes=entry["nodes"], center=entry["center"], created_at=entry["created_at"])
    return JSONResponse(content=response.model_dump())
