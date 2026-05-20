"""Internal Digger endpoints consumed by the digger worker. Gated by a shared service token."""

from typing import TYPE_CHECKING, Any

# NOTE: `from __future__ import annotations` is intentionally NOT used here.
# `user_id: UUID` is a FastAPI path param that FastAPI resolves at runtime, so
# `UUID` must be a real runtime import. With lazy annotations, ruff's TC003 would
# push it into TYPE_CHECKING and break path-param parsing. The `_pool`
# annotation is therefore quoted so the TYPE_CHECKING-only import stays valid.
# (Matches the api/routers/admin.py pattern.)
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import service_token_required
from api.queries import digger_queries as q


if TYPE_CHECKING:
    from common import AsyncPostgreSQLPool

router = APIRouter(
    prefix="/api/internal/digger",
    tags=["digger-internal"],
    dependencies=[Depends(service_token_required)],
)

_pool: "AsyncPostgreSQLPool | None" = None


def configure(pool: "AsyncPostgreSQLPool") -> None:
    """Inject the Postgres pool at application startup."""
    global _pool
    _pool = pool


def _get_pool() -> "AsyncPostgreSQLPool":
    if _pool is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")
    return _pool


@router.get("/wantlist-snapshot/{user_id}")
async def wantlist_snapshot(user_id: UUID) -> dict[str, Any]:
    """Return a user's wantlist priorities grouped by tier (used by the worker for scheduled runs)."""
    pool = _get_pool()
    rows = await q.list_wantlist_priorities(pool, user_id)
    grouped: dict[str, list[dict[str, Any]]] = {"must": [], "nice": [], "eventually": []}
    for r in rows:
        grouped[r.tier].append(
            {
                "release_id": r.release_id,
                "min_media_condition": r.min_media_condition,
                "min_sleeve_condition": r.min_sleeve_condition,
                "max_price_cents": r.max_price_cents,
            }
        )
    return {"user_id": str(user_id), **grouped}


@router.get("/users-due-for-report")
async def users_due_for_report() -> dict[str, list[dict[str, str]]]:
    """List users whose scheduled run is due (used by the worker scheduler)."""
    pool = _get_pool()
    rows = await q.list_users_due_for_report(pool)
    return {"users": [{"user_id": str(r["user_id"]), "cadence": r["scheduled_cadence"]} for r in rows]}
