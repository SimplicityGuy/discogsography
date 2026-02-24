"""Curator microservice for discogsography — Discogs collection and wantlist sync."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg.rows import dict_row
import structlog
import uvicorn

from common import AsyncPostgreSQLPool, AsyncResilientNeo4jDriver, HealthServer, setup_logging
from common.config import CuratorConfig
from curator.syncer import run_full_sync


logger = structlog.get_logger(__name__)

# Module-level state
_pool: AsyncPostgreSQLPool | None = None
_neo4j: AsyncResilientNeo4jDriver | None = None
_config: CuratorConfig | None = None
_security = HTTPBearer()

CURATOR_PORT = 8010
CURATOR_HEALTH_PORT = 8011

# In-memory registry of running background tasks (user_id -> asyncio.Task)
_running_syncs: dict[str, asyncio.Task[Any]] = {}


def get_health_data() -> dict[str, Any]:
    """Return health status for the curator service."""
    return {
        "status": "healthy" if _pool and _neo4j else "starting",
        "service": "curator",
        "active_syncs": len(_running_syncs),
        "timestamp": datetime.now(UTC).isoformat(),
    }


async def _verify_token(token: str) -> dict[str, Any]:
    """Verify a JWT token using the same logic as the auth service.

    NOTE: In production, this should call the auth service's /api/auth/me endpoint
    or use a shared secret. For now, we decode the token locally using the same
    JWT secret from the environment.
    """
    import base64
    import hashlib
    import hmac
    import json

    if _config is None:
        raise ValueError("Service not initialized")

    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid token")

    header_b64, body_b64, sig_b64 = parts
    signing_input = f"{header_b64}.{body_b64}".encode("ascii")

    def _b64url_encode(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    expected_sig = _b64url_encode(hmac.new(_config.jwt_secret_key.encode("utf-8"), signing_input, hashlib.sha256).digest())

    if not hmac.compare_digest(sig_b64, expected_sig):
        raise ValueError("Invalid token signature")

    padding = 4 - len(body_b64) % 4
    if padding != 4:
        body_b64 += "=" * padding

    payload: dict[str, Any] = json.loads(base64.urlsafe_b64decode(body_b64))
    exp = payload.get("exp")
    if exp and datetime.fromtimestamp(int(exp), UTC) < datetime.now(UTC):
        raise ValueError("Token expired")

    return payload


async def _get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_security)],
) -> dict[str, Any]:
    """Validate JWT and return user payload."""
    if _config is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service not ready",
        )
    try:
        payload = await _verify_token(credentials.credentials)
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )
        return payload
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """Manage curator service lifecycle."""
    global _pool, _neo4j, _config

    logger.info("🚀 Curator service starting...")
    _config = CuratorConfig.from_env()

    # Start health server on separate port
    health_srv = HealthServer(CURATOR_HEALTH_PORT, get_health_data)
    health_srv.start_background()
    logger.info("🏥 Health server started", port=CURATOR_HEALTH_PORT)

    # PostgreSQL connection pool
    host, port_str = _config.postgres_address.rsplit(":", 1)
    _pool = AsyncPostgreSQLPool(
        connection_params={
            "host": host,
            "port": int(port_str),
            "dbname": _config.postgres_database,
            "user": _config.postgres_username,
            "password": _config.postgres_password,
        },
        max_connections=5,
        min_connections=1,
    )
    await _pool.initialize()
    logger.info("💾 Database pool initialized")

    # Neo4j connection
    _neo4j = AsyncResilientNeo4jDriver(
        uri=_config.neo4j_address,
        auth=(_config.neo4j_username, _config.neo4j_password),
        max_retries=5,
        encrypted=False,
    )
    logger.info("🔗 Neo4j driver initialized")
    logger.info("✅ Curator service ready", port=CURATOR_PORT)

    yield

    logger.info("🔧 Curator service shutting down...")
    # Cancel any running sync tasks
    for task in _running_syncs.values():
        task.cancel()
    if _running_syncs:
        await asyncio.gather(*_running_syncs.values(), return_exceptions=True)

    if _pool:
        await _pool.close()
    if _neo4j:
        await _neo4j.close()
    health_srv.stop()
    logger.info("✅ Curator service stopped")


app = FastAPI(
    title="Discogsography Curator",
    version="0.1.0",
    description="Curator service for Discogs collection and wantlist sync for Discogsography",
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check() -> ORJSONResponse:
    """Service health check endpoint."""
    return ORJSONResponse(content=get_health_data())


@app.post("/api/sync", status_code=status.HTTP_202_ACCEPTED)
async def trigger_sync(
    current_user: Annotated[dict[str, Any], Depends(_get_current_user)],
) -> ORJSONResponse:
    """Trigger a full collection + wantlist sync for the current user.

    The sync runs as a background task. Returns a sync_id to track progress.
    If a sync is already running for this user, returns the existing sync_id.
    """
    if _pool is None or _neo4j is None or _config is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service not ready",
        )

    user_id = current_user.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    # Check if sync is already running
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

    # Create sync_history record
    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
                INSERT INTO sync_history (user_id, sync_type, status)
                VALUES (%s::uuid, 'full', 'running')
                RETURNING id
                """,
            (user_id,),
        )
        sync_row = await cur.fetchone()

    if not sync_row:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create sync record",
        )

    from uuid import UUID

    sync_id = str(sync_row["id"])

    # Launch background task
    task = asyncio.create_task(
        run_full_sync(
            user_uuid=UUID(user_id),
            sync_id=sync_id,
            pg_pool=_pool,
            neo4j_driver=_neo4j,
            discogs_user_agent=_config.discogs_user_agent,
        )
    )
    _running_syncs[user_id] = task

    logger.info("🔄 Sync triggered", user_id=user_id, sync_id=sync_id)

    return ORJSONResponse(
        content={"sync_id": sync_id, "status": "started"},
        status_code=status.HTTP_202_ACCEPTED,
    )


@app.get("/api/sync/status")
async def sync_status(
    current_user: Annotated[dict[str, Any], Depends(_get_current_user)],
) -> ORJSONResponse:
    """Get sync history for the current user."""
    if _pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service not ready",
        )

    user_id = current_user.get("sub")
    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
                SELECT id, sync_type, status, items_synced, error_message,
                       started_at, completed_at
                FROM sync_history
                WHERE user_id = %s::uuid
                ORDER BY started_at DESC
                LIMIT 10
                """,
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


def main() -> None:
    """Entry point for the curator service."""
    setup_logging("curator", log_file=Path("/logs/curator.log"))
    print(
        r"""
    ____      _ _           _
   / ___|___ | | | ___  ___| |_ ___  _ __
  | |   / _ \| | |/ _ \/ __| __/ _ \| '__|
  | |__| (_) | | |  __/ (__| || (_) | |
   \____\___/|_|_|\___|\___|\__\___/|_|

    Curator Service — Discogs Collection & Wantlist Sync
    """
    )
    uvicorn.run(app, host="0.0.0.0", port=CURATOR_PORT)  # noqa: S104  # nosec B104


if __name__ == "__main__":
    main()
