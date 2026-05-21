"""POST /api/digger/recommend — SSE-streamed interactive recommendation.

Flow:
1. Confirm the caller has digger enabled.
2. Identify stale releases (last scrape older than the per-tier half-life).
3. Bump their scrape priority and subscribe to refresh-progress over Redis.
4. Stream refresh events as SSE until the deadline or all stale complete.
5. Build the OptimizerInput, run the optimizer, stream the result.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import logging
from typing import TYPE_CHECKING, Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg.rows import dict_row
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from api.dependencies import require_user
from api.digger_refresh.coordinator import RefreshCoordinator
from api.digger_refresh.input_builder import build_optimizer_input
from api.queries import digger_queries as q
from common.digger_optimizer import pareto_bundles


if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import AsyncIterator

    import redis.asyncio as aioredis

    from common import AsyncPostgreSQLPool


log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/digger", tags=["digger"])

_pool: AsyncPostgreSQLPool | None = None
_redis: aioredis.Redis | None = None


def configure(pool: AsyncPostgreSQLPool, redis: aioredis.Redis) -> None:
    """Inject the Postgres pool and Redis client at application startup."""
    global _pool, _redis
    _pool = pool
    _redis = redis


def _get_pool() -> AsyncPostgreSQLPool:
    if _pool is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")
    return _pool


def _get_redis() -> aioredis.Redis:
    if _redis is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")
    return _redis


class RecommendIn(BaseModel):
    deadline_seconds: int = 30
    budget_cap_cents: int | None = None
    excluded_sellers: list[int] = []


_STALE_TIER_HALF_LIFE: dict[str, timedelta] = {
    "must": timedelta(days=3, hours=12),
    "nice": timedelta(days=7),
    "eventually": timedelta(days=14),
}


async def _refresh_progress_events(
    coord: RefreshCoordinator, user_id: UUID, stale: list[int], *, deadline_seconds: int
) -> AsyncIterator[dict[str, str]]:
    """Bump stale releases, then stream refresh-progress SSE events until done or deadline."""
    if not stale:
        return
    await coord.bump_priorities(stale)
    stale_set = set(stale)
    completed: set[int] = set()
    async for ev in coord.subscribe_progress(str(user_id), deadline_seconds=deadline_seconds):
        release_id = ev.get("release_id")
        if release_id is not None:
            completed.add(release_id)
        yield {
            "event": "refresh_progress",
            "data": json.dumps({"release_id": release_id, "status": ev.get("status"), "remaining": max(0, len(stale) - len(completed))}),
        }
        if completed >= stale_set:
            break


async def _identify_stale(pool: AsyncPostgreSQLPool, user_id: UUID) -> list[int]:
    """Return release_ids whose last scrape is older than the user's per-tier half-life."""
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT uwp.release_id, uwp.tier, rs.last_scraped_at "
            "FROM digger.user_wantlist_priorities uwp "
            "LEFT JOIN digger.release_scrape_state rs ON rs.release_id = uwp.release_id "
            "WHERE uwp.user_id = %s",
            (user_id,),
        )
        rows = await cur.fetchall()
    now = datetime.now(UTC)
    stale: list[int] = []
    for r in rows:
        floor = _STALE_TIER_HALF_LIFE.get(r["tier"], timedelta(days=7))
        if r["last_scraped_at"] is None or now - r["last_scraped_at"] > floor:
            stale.append(r["release_id"])
    return stale


@router.post("/recommend")
async def recommend(body: RecommendIn, current_user: Annotated[dict[str, Any], Depends(require_user)]) -> EventSourceResponse:
    """Stream an interactive recommendation: opportunistic refresh, then optimizer bundles."""
    pool = _get_pool()
    redis = _get_redis()
    user_id = UUID(current_user["sub"])
    settings = await q.get_user_settings(pool, user_id)

    async def event_gen() -> AsyncIterator[dict[str, str]]:
        if settings is None or not settings.enabled:
            yield {"event": "error", "data": json.dumps({"reason": "digger not enabled"})}
            return

        coord = RefreshCoordinator(pool=pool, redis=redis)
        stale = await _identify_stale(pool, user_id)
        yield {"event": "refresh_started", "data": json.dumps({"stale_count": len(stale)})}

        async for evt in _refresh_progress_events(coord, user_id, stale, deadline_seconds=body.deadline_seconds):
            yield evt

        inp = await build_optimizer_input(
            pool,
            user_id,
            location=settings.country_code or "US",
            currency=settings.currency,
            budget_cap_cents=body.budget_cap_cents,
            excluded_sellers=frozenset(body.excluded_sellers),
        )
        out = pareto_bundles(inp)
        yield {"event": "result", "data": out.model_dump_json()}
        yield {"event": "done", "data": "{}"}

    return EventSourceResponse(event_gen())
