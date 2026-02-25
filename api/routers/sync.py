"""Sync endpoints — migrated from curator service."""

import asyncio
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import ORJSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg.rows import dict_row
import structlog

from api.auth import decode_token
from api.limiter import limiter
from api.syncer import run_full_sync
from common import AsyncPostgreSQLPool, AsyncResilientNeo4jDriver


logger = structlog.get_logger(__name__)

router = APIRouter()
_security = HTTPBearer()

_pool: AsyncPostgreSQLPool | None = None
_neo4j: AsyncResilientNeo4jDriver | None = None
_config: Any = None
_redis: Any = None
_running_syncs: dict[str, asyncio.Task[Any]] = {}


def configure(
    pool: AsyncPostgreSQLPool,
    neo4j: AsyncResilientNeo4jDriver | None,
    config: Any,
    running_syncs: dict[str, asyncio.Task[Any]],
    redis: Any = None,
) -> None:
    global _pool, _neo4j, _config, _running_syncs, _redis
    _pool = pool
    _neo4j = neo4j
    _config = config
    _running_syncs = running_syncs
    _redis = redis


async def _verify_token(token: str) -> dict[str, Any]:
    if _config is None:
        raise ValueError("Service not initialized")
    return decode_token(token, _config.jwt_secret_key)


async def _get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_security)],
) -> dict[str, Any]:
    if _config is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")
    try:
        payload = await _verify_token(credentials.credentials)
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        return payload
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


@router.post("/api/sync", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("2/10minute")
async def trigger_sync(
    request: Request,  # noqa: ARG001 — required by slowapi rate limiter
    current_user: Annotated[dict[str, Any], Depends(_get_current_user)],
) -> ORJSONResponse:
    if _pool is None or _neo4j is None or _config is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")
    user_id = current_user.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    # Redis-based per-user sync cooldown (prevents rapid re-triggers)
    if _redis:
        cooldown_key = f"sync:cooldown:{user_id}"
        in_cooldown = await _redis.get(cooldown_key)
        if in_cooldown:
            return ORJSONResponse(
                content={"status": "cooldown", "message": "Sync rate limited. Please wait before triggering again."},
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            )

    if user_id in _running_syncs and not _running_syncs[user_id].done():
        async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT id, status FROM sync_history WHERE user_id = %s::uuid AND status = 'running' ORDER BY started_at DESC LIMIT 1",
                (user_id,),
            )
            existing = await cur.fetchone()
        if existing:
            return ORJSONResponse(
                content={"sync_id": str(existing["id"]), "status": "already_running"},
                status_code=status.HTTP_202_ACCEPTED,
            )
    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "INSERT INTO sync_history (user_id, sync_type, status) VALUES (%s::uuid, 'full', 'running') RETURNING id",
            (user_id,),
        )
        sync_row = await cur.fetchone()
    if not sync_row:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create sync record")
    sync_id = str(sync_row["id"])
    task = asyncio.create_task(
        run_full_sync(
            user_uuid=UUID(user_id),
            sync_id=sync_id,
            pg_pool=_pool,
            neo4j_driver=_neo4j,
            discogs_user_agent=_config.discogs_user_agent,
            oauth_encryption_key=getattr(_config, "oauth_encryption_key", None),
        )
    )
    _running_syncs[user_id] = task

    # Set per-user cooldown to prevent rapid re-triggers
    if _redis:
        await _redis.setex(f"sync:cooldown:{user_id}", 600, "1")

    logger.info("🔄 Sync triggered", user_id=user_id, sync_id=sync_id)
    return ORJSONResponse(content={"sync_id": sync_id, "status": "started"}, status_code=status.HTTP_202_ACCEPTED)


@router.get("/api/sync/status")
async def sync_status(
    current_user: Annotated[dict[str, Any], Depends(_get_current_user)],
) -> ORJSONResponse:
    if _pool is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")
    user_id = current_user.get("sub")
    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """SELECT id, sync_type, status, items_synced, error_message, started_at, completed_at
               FROM sync_history WHERE user_id = %s::uuid ORDER BY started_at DESC LIMIT 10""",
            (user_id,),
        )
        rows = await cur.fetchall()
    history = [
        {
            "sync_id": str(row["id"]),
            "sync_type": row["sync_type"],
            "status": row["status"],
            "items_synced": row["items_synced"],
            "error": row["error_message"],
            "started_at": row["started_at"].isoformat(),
            "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
        }
        for row in rows
    ]
    return ORJSONResponse(content={"syncs": history})
