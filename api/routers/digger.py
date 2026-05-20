"""User-facing Digger endpoints: per-user settings and wantlist priority management."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any
import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import require_user
from api.models import (
    DiggerBulkTierIn,
    DiggerSetPriorityIn,
    DiggerSettingsIn,
    DiggerSettingsOut,
    DiggerWantlistItemOut,
    DiggerWantlistResponse,
)
from api.queries import digger_queries as q


if TYPE_CHECKING:
    from common import AsyncPostgreSQLPool

router = APIRouter(prefix="/api/digger", tags=["digger"])

_pool: AsyncPostgreSQLPool | None = None


def configure(pool: AsyncPostgreSQLPool) -> None:
    """Inject the Postgres pool at application startup."""
    global _pool
    _pool = pool


def _get_pool() -> AsyncPostgreSQLPool:
    if _pool is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")
    return _pool


@router.get("/settings", response_model=DiggerSettingsOut)
async def get_settings(current_user: Annotated[dict[str, Any], Depends(require_user)]) -> DiggerSettingsOut:
    """Return the caller's digger settings, or 404 if they have not enabled digger."""
    pool = _get_pool()
    user_id = uuid.UUID(current_user["sub"])
    s = await q.get_user_settings(pool, user_id)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="digger not enabled")
    return DiggerSettingsOut(
        enabled=s.enabled,
        country_code=s.country_code,
        currency=s.currency,
        scheduled_cadence=s.scheduled_cadence,
        preferred_model=s.preferred_model,
        daily_token_cap_interactive=s.daily_token_cap_interactive,
        daily_token_cap_scheduled=s.daily_token_cap_scheduled,
    )


@router.put("/settings", status_code=status.HTTP_204_NO_CONTENT)
async def put_settings(body: DiggerSettingsIn, current_user: Annotated[dict[str, Any], Depends(require_user)]) -> None:
    """Create or update the caller's digger settings."""
    pool = _get_pool()
    user_id = uuid.UUID(current_user["sub"])
    await q.upsert_user_settings(
        pool,
        user_id,
        enabled=body.enabled,
        country_code=body.country_code,
        currency=body.currency,
        scheduled_cadence=body.scheduled_cadence,
        preferred_model=body.preferred_model,
        daily_token_cap_interactive=(body.daily_token_cap_interactive if body.daily_token_cap_interactive is not None else 200_000),
        daily_token_cap_scheduled=(body.daily_token_cap_scheduled if body.daily_token_cap_scheduled is not None else 100_000),
    )


@router.get("/wantlist", response_model=DiggerWantlistResponse)
async def get_wantlist(current_user: Annotated[dict[str, Any], Depends(require_user)]) -> DiggerWantlistResponse:
    """Return the caller's wantlist with priority tiers and active-listing counts."""
    pool = _get_pool()
    user_id = uuid.UUID(current_user["sub"])
    rows = await q.get_wantlist_with_listings_counts(pool, user_id)
    items = [
        DiggerWantlistItemOut(
            release_id=r["release_id"],
            tier=r["tier"],
            min_media_condition=r["min_media_condition"],
            min_sleeve_condition=r["min_sleeve_condition"],
            max_price_cents=r["max_price_cents"],
            active_listings=int(r["active_listings"] or 0),
            last_scraped_at=r["last_scraped_at"].isoformat() if r["last_scraped_at"] else None,
            title=r["title"],
            artist=r["artist"],
            year=r["year"],
        )
        for r in rows
    ]
    return DiggerWantlistResponse(items=items)


@router.put("/wantlist/{release_id}/priority", status_code=status.HTTP_204_NO_CONTENT)
async def set_priority(
    release_id: int,
    body: DiggerSetPriorityIn,
    current_user: Annotated[dict[str, Any], Depends(require_user)],
) -> None:
    """Update tier and/or condition floors for one release in the caller's wantlist."""
    pool = _get_pool()
    user_id = uuid.UUID(current_user["sub"])
    await q.set_wantlist_priority(
        pool,
        user_id,
        release_id,
        tier=body.tier,
        min_media_condition=body.min_media_condition,
        min_sleeve_condition=body.min_sleeve_condition,
        max_price_cents=body.max_price_cents,
    )


@router.post("/wantlist/bulk-tier")
async def bulk_set_tier(body: DiggerBulkTierIn, current_user: Annotated[dict[str, Any], Depends(require_user)]) -> dict[str, int]:
    """Set the same tier on many releases at once; returns how many rows changed."""
    pool = _get_pool()
    user_id = uuid.UUID(current_user["sub"])
    updated = await q.bulk_set_tier(pool, user_id, body.release_ids, body.tier)
    return {"updated": updated}
