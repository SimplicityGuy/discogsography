"""Admin router — login, logout, extraction history, trigger, and DLQ purge."""

import asyncio
from datetime import UTC, datetime
import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
import httpx
from psycopg.rows import dict_row
import structlog

from api.admin_auth import create_admin_token, verify_admin_password
from api.auth import _DUMMY_HASH, _verify_password
from api.dependencies import require_admin
from api.limiter import limiter
from api.models import (
    AdminLoginRequest,
    AdminLoginResponse,
    DlqPurgeResponse,
    ExtractionHistoryResponse,
    ExtractionListResponse,
    ExtractionTriggerResponse,
)
from common.config import DATA_TYPES, ApiConfig


logger = structlog.get_logger(__name__)

router = APIRouter()

# Module-level state (set via configure())
_pool: Any = None
_redis: Any = None
_config: ApiConfig | None = None

# Background tracking tasks keyed by extraction_id
_tracking_tasks: dict[str, asyncio.Task[Any]] = {}

# Valid DLQ names (one per data type per consumer)
_VALID_DLQ_NAMES: set[str] = set()
for _dt in DATA_TYPES:
    _VALID_DLQ_NAMES.add(f"graphinator-{_dt}-dlq")
    _VALID_DLQ_NAMES.add(f"tableinator-{_dt}-dlq")


def configure(pool: Any, redis: Any, config: ApiConfig) -> None:
    """Initialise module state — called once during app lifespan startup."""
    global _pool, _redis, _config
    _pool = pool
    _redis = redis
    _config = config


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------


@router.post("/api/admin/auth/login")
@limiter.limit("5/minute")
async def admin_login(request: Request, body: AdminLoginRequest) -> JSONResponse:  # noqa: ARG001
    """Authenticate an admin and return a JWT."""
    if _pool is None or _config is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")

    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT id, email, hashed_password, is_active FROM dashboard_admins WHERE email = %s",
            (body.email,),
        )
        admin = await cur.fetchone()

    # Constant-time check to prevent enumeration via timing
    if admin is None:
        _verify_password(body.password, _DUMMY_HASH)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")

    password_ok = verify_admin_password(body.password, admin["hashed_password"])
    if not password_ok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")

    if not admin["is_active"]:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")

    access_token, expires_in = create_admin_token(str(admin["id"]), admin["email"], _config.jwt_secret_key)
    logger.info("✅ Admin logged in", email=body.email)

    return JSONResponse(
        content=AdminLoginResponse(access_token=access_token, expires_in=expires_in).model_dump(),
    )


@router.post("/api/admin/auth/logout")
async def admin_logout(
    current_admin: Annotated[dict[str, Any], Depends(require_admin)],
) -> JSONResponse:
    """Logout and revoke the current admin JWT."""
    if _redis:
        jti: str | None = current_admin.get("jti")
        exp: int | None = current_admin.get("exp")
        if jti:
            now = int(datetime.now(UTC).timestamp())
            ttl = max((exp - now), 60) if exp else 3600
            await _redis.setex(f"revoked:jti:{jti}", ttl, "1")
    return JSONResponse(content={"logged_out": True})


# ---------------------------------------------------------------------------
# Extraction history endpoints
# ---------------------------------------------------------------------------


@router.get("/api/admin/extractions")
async def list_extractions(
    current_admin: Annotated[dict[str, Any], Depends(require_admin)],  # noqa: ARG001
    offset: int = 0,
    limit: int = 20,
) -> JSONResponse:
    """List extraction history records, newest first."""
    if _pool is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")

    limit = min(max(limit, 1), 100)
    offset = max(offset, 0)

    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT count(*) AS total FROM extraction_history")
        total_row = await cur.fetchone()
        total = total_row["total"] if total_row else 0

        await cur.execute(
            "SELECT * FROM extraction_history ORDER BY created_at DESC LIMIT %s OFFSET %s",
            (limit, offset),
        )
        rows = await cur.fetchall()

    extractions = []
    for row in rows:
        duration_seconds: float | None = None
        if row.get("started_at") and row.get("completed_at"):
            duration_seconds = (row["completed_at"] - row["started_at"]).total_seconds()
        extractions.append(
            ExtractionHistoryResponse(
                id=row["id"],
                triggered_by=row["triggered_by"],
                status=row["status"],
                started_at=row.get("started_at"),
                completed_at=row.get("completed_at"),
                duration_seconds=duration_seconds,
                record_counts=row.get("record_counts"),
                error_message=row.get("error_message"),
                extractor_version=row.get("extractor_version"),
                created_at=row["created_at"],
            ).model_dump(mode="json")
        )

    return JSONResponse(
        content=ExtractionListResponse(
            extractions=[ExtractionHistoryResponse(**e) for e in extractions],
            total=total,
            offset=offset,
            limit=limit,
        ).model_dump(mode="json"),
    )


@router.get("/api/admin/extractions/{extraction_id}")
async def get_extraction(
    extraction_id: UUID,
    current_admin: Annotated[dict[str, Any], Depends(require_admin)],  # noqa: ARG001
) -> JSONResponse:
    """Get a single extraction history record."""
    if _pool is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")

    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT * FROM extraction_history WHERE id = %s", (str(extraction_id),))
        row = await cur.fetchone()

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Extraction not found")

    duration_seconds: float | None = None
    if row.get("started_at") and row.get("completed_at"):
        duration_seconds = (row["completed_at"] - row["started_at"]).total_seconds()

    return JSONResponse(
        content=ExtractionHistoryResponse(
            id=row["id"],
            triggered_by=row["triggered_by"],
            status=row["status"],
            started_at=row.get("started_at"),
            completed_at=row.get("completed_at"),
            duration_seconds=duration_seconds,
            record_counts=row.get("record_counts"),
            error_message=row.get("error_message"),
            extractor_version=row.get("extractor_version"),
            created_at=row["created_at"],
        ).model_dump(mode="json"),
    )


# ---------------------------------------------------------------------------
# Extraction trigger
# ---------------------------------------------------------------------------


async def _track_extraction(extraction_id: str) -> None:
    """Background task: poll extractor /health and update extraction record."""
    if _pool is None or _config is None:
        return

    url = f"http://{_config.extractor_host}:{_config.extractor_health_port}/health"
    try:
        while True:
            await asyncio.sleep(10)
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    health_status = data.get("status", "")
                    record_counts = data.get("record_counts")

                    if record_counts:
                        async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
                            await cur.execute(
                                "UPDATE extraction_history SET record_counts = %s WHERE id = %s",
                                (json.dumps(record_counts), extraction_id),
                            )

                    if health_status in ("idle", "completed"):
                        async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
                            await cur.execute(
                                "UPDATE extraction_history SET status = 'completed', completed_at = NOW() WHERE id = %s",
                                (extraction_id,),
                            )
                        logger.info("✅ Extraction completed", extraction_id=extraction_id)
                        return

                    if health_status == "failed":
                        error_msg = data.get("error", "Extraction failed")
                        async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
                            await cur.execute(
                                "UPDATE extraction_history SET status = 'failed', completed_at = NOW(), error_message = %s WHERE id = %s",
                                (error_msg, extraction_id),
                            )
                        logger.error("❌ Extraction failed", extraction_id=extraction_id, error=error_msg)
                        return
                else:
                    logger.warning("⚠️ Extractor health check returned non-200", status_code=resp.status_code)
            except httpx.ConnectError:
                async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        "UPDATE extraction_history SET status = 'failed', completed_at = NOW(), error_message = %s WHERE id = %s",
                        ("Extractor unreachable", extraction_id),
                    )
                logger.error("❌ Extractor unreachable", extraction_id=extraction_id)
                return
    finally:
        _tracking_tasks.pop(extraction_id, None)


@router.post("/api/admin/extractions/trigger", status_code=status.HTTP_202_ACCEPTED)
async def trigger_extraction(
    current_admin: Annotated[dict[str, Any], Depends(require_admin)],
) -> JSONResponse:
    """Trigger a new extraction run."""
    if _pool is None or _config is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")

    admin_id = current_admin.get("sub")
    trigger_url = f"http://{_config.extractor_host}:{_config.extractor_health_port}/trigger"

    # Create a pending extraction record
    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "INSERT INTO extraction_history (triggered_by, status) VALUES (%s::uuid, 'pending') RETURNING id",
            (admin_id,),
        )
        row = await cur.fetchone()

    if not row:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create extraction record")

    extraction_id = str(row["id"])

    # Call extractor /trigger
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(trigger_url)

        if resp.status_code == 202:
            # Update to running
            async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "UPDATE extraction_history SET status = 'running', started_at = NOW() WHERE id = %s",
                    (extraction_id,),
                )
            # Spawn background tracking task
            task = asyncio.create_task(_track_extraction(extraction_id))
            _tracking_tasks[extraction_id] = task

            logger.info("🚀 Extraction triggered", extraction_id=extraction_id, admin_id=admin_id)
            return JSONResponse(
                content=ExtractionTriggerResponse(id=UUID(extraction_id), status="running").model_dump(mode="json"),
                status_code=status.HTTP_202_ACCEPTED,
            )

        if resp.status_code == 409:
            # Already running — update record
            async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "UPDATE extraction_history SET status = 'already_running' WHERE id = %s",
                    (extraction_id,),
                )
            return JSONResponse(
                content=ExtractionTriggerResponse(id=UUID(extraction_id), status="already_running").model_dump(mode="json"),
                status_code=status.HTTP_409_CONFLICT,
            )

        # Unexpected status
        async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "UPDATE extraction_history SET status = 'failed', error_message = %s WHERE id = %s",
                (f"Extractor returned {resp.status_code}", extraction_id),
            )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Extractor returned unexpected status {resp.status_code}",
        )
    except httpx.ConnectError as exc:
        async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "UPDATE extraction_history SET status = 'failed', error_message = 'Extractor unreachable' WHERE id = %s",
                (extraction_id,),
            )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Extractor service unreachable",
        ) from exc


# ---------------------------------------------------------------------------
# DLQ purge
# ---------------------------------------------------------------------------


@router.post("/api/admin/dlq/purge/{queue}")
async def purge_dlq(
    queue: str,
    current_admin: Annotated[dict[str, Any], Depends(require_admin)],
) -> JSONResponse:
    """Purge a dead-letter queue via the RabbitMQ management API."""
    if _config is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")

    if queue not in _VALID_DLQ_NAMES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown DLQ: {queue}")

    mgmt_url = f"http://{_config.rabbitmq_management_host}:{_config.rabbitmq_management_port}/api/queues/%2F/{queue}/contents"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.delete(
                mgmt_url,
                auth=(_config.rabbitmq_username, _config.rabbitmq_password),
            )
        if resp.status_code == 204:
            messages_purged = 0  # RabbitMQ DELETE /contents returns 204 with no body
        elif resp.status_code == 200:
            data = resp.json() if resp.content else {}
            messages_purged = data.get("messages_purged", 0) if isinstance(data, dict) else 0
        else:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"RabbitMQ returned {resp.status_code}",
            )
    except httpx.ConnectError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="RabbitMQ management API unreachable",
        ) from exc

    admin_email = current_admin.get("email", "unknown")
    logger.info("🗑️ DLQ purged", queue=queue, messages_purged=messages_purged, admin_email=admin_email)

    return JSONResponse(
        content=DlqPurgeResponse(queue=queue, messages_purged=messages_purged).model_dump(),
    )
