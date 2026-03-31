"""Admin router — login, logout, extraction history, trigger, and DLQ purge."""

import asyncio
from datetime import UTC, datetime
import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
import httpx
from psycopg.rows import dict_row
import structlog

from api.admin_auth import create_admin_token, verify_admin_password
from api.audit_log import record_audit_entry
from api.auth import _DUMMY_HASH, _verify_password
from api.dependencies import require_admin
from api.limiter import limiter
from api.models import (
    AdminLoginRequest,
    AdminLoginResponse,
    AuditLogEntry,
    AuditLogResponse,
    DlqPurgeResponse,
    ExtractionHistoryResponse,
    ExtractionListResponse,
    ExtractionTriggerResponse,
)
from api.queries.admin_queries import (
    get_audit_log,
    get_neo4j_storage,
    get_postgres_storage,
    get_redis_storage,
    get_sync_activity,
    get_user_stats,
)
from api.queries.metrics_queries import get_health_history, get_queue_history
from common.config import DATA_TYPES, MUSICBRAINZ_DATA_TYPES, ApiConfig


logger = structlog.get_logger(__name__)

router = APIRouter()

# Module-level state (set via configure())
_pool: Any = None
_redis: Any = None
_config: ApiConfig | None = None
_neo4j_driver: Any = None

# Background tracking tasks keyed by extraction_id
_tracking_tasks: dict[str, asyncio.Task[Any]] = {}

# Valid DLQ names (one per data type per consumer)
_VALID_DLQ_NAMES: set[str] = set()
for _dt in DATA_TYPES:
    _VALID_DLQ_NAMES.add(f"graphinator-{_dt}-dlq")
    _VALID_DLQ_NAMES.add(f"tableinator-{_dt}-dlq")
for _dt in MUSICBRAINZ_DATA_TYPES:
    _VALID_DLQ_NAMES.add(f"brainzgraphinator-{_dt}-dlq")
    _VALID_DLQ_NAMES.add(f"brainztableinator-{_dt}-dlq")


def configure(pool: Any, redis: Any, config: ApiConfig, neo4j_driver: Any = None) -> None:
    """Initialise module state — called once during app lifespan startup."""
    global _pool, _redis, _config, _neo4j_driver
    _pool = pool
    _redis = redis
    _config = config
    _neo4j_driver = neo4j_driver


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
            "SELECT id, email, hashed_password, is_active, is_admin FROM users WHERE email = %s",
            (body.email,),
        )
        admin = await cur.fetchone()

    # Constant-time check to prevent enumeration via timing
    if admin is None:
        _verify_password(body.password, _DUMMY_HASH)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")

    # Always verify password before checking is_active to prevent timing oracle
    password_ok = verify_admin_password(body.password, admin["hashed_password"])
    if not password_ok or not admin["is_active"]:
        await record_audit_entry(pool=_pool, admin_id=str(admin["id"]), action="admin.login", target=body.email, details={"success": False})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")

    if not admin.get("is_admin"):
        await record_audit_entry(
            pool=_pool, admin_id=str(admin["id"]), action="admin.login", target=body.email, details={"success": False, "reason": "not_admin"}
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    access_token, expires_in = create_admin_token(str(admin["id"]), admin["email"], _config.jwt_secret_key)
    logger.info("✅ Admin logged in", email=body.email)
    await record_audit_entry(pool=_pool, admin_id=str(admin["id"]), action="admin.login", target=body.email, details={"success": True})

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
    admin_email = current_admin.get("email", "unknown")
    if _pool is not None:
        await record_audit_entry(pool=_pool, admin_id=current_admin["sub"], action="admin.logout", target=admin_email)
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
            )
        )

    return JSONResponse(
        content=ExtractionListResponse(
            extractions=extractions,
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
# Phase 2 — User Activity & Storage endpoints
# ---------------------------------------------------------------------------


@router.get("/api/admin/users/stats")
async def admin_user_stats(
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
) -> JSONResponse:
    """User registration stats, active users, and OAuth connection rate."""
    if _pool is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")
    data = await get_user_stats(_pool)
    return JSONResponse(content=data)


@router.get("/api/admin/users/sync-activity")
async def admin_sync_activity(
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
) -> JSONResponse:
    """Sync activity stats for 7d and 30d windows."""
    if _pool is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")
    data = await get_sync_activity(_pool)
    return JSONResponse(content=data)


@router.get("/api/admin/storage")
async def admin_storage(
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
) -> JSONResponse:
    """Storage utilization for Neo4j, PostgreSQL, and Redis."""
    results = await asyncio.gather(
        get_neo4j_storage(_neo4j_driver),
        get_postgres_storage(_pool),
        get_redis_storage(_redis),
        return_exceptions=True,
    )

    def _wrap(result: Any, name: str) -> dict[str, Any]:
        if isinstance(result, BaseException):
            logger.warning("⚠️ Storage query failed", source=name, error=str(result))
            return {"status": "error", "error": str(result)}
        return dict(result)

    return JSONResponse(
        content={
            "neo4j": _wrap(results[0], "neo4j"),
            "postgresql": _wrap(results[1], "postgresql"),
            "redis": _wrap(results[2], "redis"),
        }
    )


# ---------------------------------------------------------------------------
# Phase 3 — Queue Health Trends & System Health
# ---------------------------------------------------------------------------


@router.get("/api/admin/queues/history")
async def admin_queue_history(
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
    range: str = "24h",
) -> JSONResponse:
    """Queue depth time-series for the given range."""
    if _pool is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")
    try:
        data = await get_queue_history(_pool, range)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return JSONResponse(content=data)


@router.get("/api/admin/health/history")
async def admin_health_history(
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
    range: str = "24h",
) -> JSONResponse:
    """Service health and API endpoint metrics for the given range."""
    if _pool is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")
    try:
        data = await get_health_history(_pool, range)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return JSONResponse(content=data)


# ---------------------------------------------------------------------------
# Extraction trigger
# ---------------------------------------------------------------------------


async def _track_extraction(extraction_id: str) -> None:
    """Background task: poll extractor /health and update extraction record."""
    if _pool is None or _config is None:
        return

    url = f"http://{_config.extractor_host}:{_config.extractor_health_port}/health"
    consecutive_failures = 0
    max_failures = 5

    try:
        while True:
            await asyncio.sleep(10)
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(url)
                if resp.status_code == 200:
                    consecutive_failures = 0
                    data = resp.json()
                    extraction_status = data.get("extraction_status", "")
                    progress = data.get("extraction_progress", {})
                    record_counts = {
                        "artists": progress.get("artists", 0),
                        "labels": progress.get("labels", 0),
                        "masters": progress.get("masters", 0),
                        "releases": progress.get("releases", 0),
                    }

                    # Update progress
                    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
                        await cur.execute(
                            "UPDATE extraction_history SET record_counts = %s WHERE id = %s",
                            (json.dumps(record_counts), extraction_id),
                        )

                    if extraction_status == "completed":
                        async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
                            await cur.execute(
                                "UPDATE extraction_history SET status = 'completed', completed_at = NOW(), record_counts = %s WHERE id = %s",
                                (json.dumps(record_counts), extraction_id),
                            )
                        logger.info("✅ Extraction completed", extraction_id=extraction_id, record_counts=record_counts)
                        return

                    if extraction_status == "failed":
                        error_msg = data.get("error_message", "Extraction failed")
                        async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
                            await cur.execute(
                                "UPDATE extraction_history SET status = 'failed', completed_at = NOW(), error_message = %s, record_counts = %s WHERE id = %s",
                                (error_msg, json.dumps(record_counts), extraction_id),
                            )
                        logger.error("❌ Extraction failed", extraction_id=extraction_id, error=error_msg)
                        return
                else:
                    consecutive_failures += 1
                    logger.warning("⚠️ Extractor health check returned non-200", status_code=resp.status_code)
            except (httpx.ConnectError, httpx.RequestError):
                consecutive_failures += 1
                logger.warning("⚠️ Extractor unreachable", extraction_id=extraction_id, attempt=consecutive_failures)

            if consecutive_failures >= max_failures:
                async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        "UPDATE extraction_history SET status = 'failed', completed_at = NOW(), error_message = %s WHERE id = %s",
                        ("Extractor became unreachable", extraction_id),
                    )
                logger.error("❌ Extraction tracking failed — extractor unreachable after %d attempts", max_failures, extraction_id=extraction_id)
                return
    except asyncio.CancelledError:
        logger.info("🛑 Extraction tracking cancelled", extraction_id=extraction_id)
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
        # Update any dangling 'pending' record to 'failed' to avoid orphans
        async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "UPDATE extraction_history SET status = 'failed', completed_at = NOW(), error_message = 'Failed to create extraction record' "
                "WHERE triggered_by = %s::uuid AND status = 'pending'",
                (admin_id,),
            )
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create extraction record")

    extraction_id = str(row["id"])

    # Call extractor /trigger
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(trigger_url, json={"force_reprocess": True})

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
            await record_audit_entry(pool=_pool, admin_id=str(admin_id), action="extraction.trigger", details={"extraction_id": extraction_id})
            return JSONResponse(
                content=ExtractionTriggerResponse(id=UUID(extraction_id), status="running").model_dump(mode="json"),
                status_code=status.HTTP_202_ACCEPTED,
            )

        if resp.status_code == 409:
            # Already running — delete the orphan pending record
            async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "DELETE FROM extraction_history WHERE id = %s",
                    (extraction_id,),
                )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Extraction already in progress",
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
    except (httpx.ConnectError, httpx.RequestError) as exc:
        async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "UPDATE extraction_history SET status = 'failed', error_message = 'Extractor unreachable' WHERE id = %s",
                (extraction_id,),
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Extractor service unavailable",
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
    if _pool is not None:
        await record_audit_entry(
            pool=_pool, admin_id=current_admin["sub"], action="dlq.purge", target=queue, details={"purged_count": messages_purged}
        )

    return JSONResponse(
        content=DlqPurgeResponse(queue=queue, messages_purged=messages_purged).model_dump(),
    )


# ---------------------------------------------------------------------------
# Phase 4 — Audit Log
# ---------------------------------------------------------------------------


@router.get("/api/admin/audit-log")
async def list_audit_log(
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
    page: int = 1,
    page_size: int = 50,
    action: str | None = None,
    admin_id: str | None = Query(None, pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"),
) -> JSONResponse:
    """Paginated admin audit log (last 90 days by default)."""
    if _pool is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")

    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)

    data = await get_audit_log(_pool, page=page, page_size=page_size, action_filter=action, admin_id_filter=admin_id)
    entries = [AuditLogEntry(**e) for e in data["entries"]]
    response = AuditLogResponse(entries=entries, total=data["total"], page=data["page"], page_size=data["page_size"])
    return JSONResponse(content=response.model_dump(mode="json"))
