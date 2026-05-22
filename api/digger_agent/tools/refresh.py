"""Tool: request_opportunistic_refresh — bump stale releases and await a fresh scrape."""

from __future__ import annotations

from typing import TYPE_CHECKING

from psycopg.rows import dict_row

from api.digger_refresh.coordinator import RefreshCoordinator


if TYPE_CHECKING:  # pragma: no cover
    from typing import Any

    from api.digger_agent.tools.context import ToolContext


async def request_opportunistic_refresh(*, ctx: ToolContext, deadline_seconds: int = 30) -> dict[str, Any]:
    """Bump scrape priority for the user's wantlist, then await refresh progress until the deadline."""
    if ctx.redis is None:
        return {"error": "refresh unavailable: no redis connection"}
    async with ctx.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT release_id FROM digger.user_wantlist_priorities WHERE user_id = %s",
            (ctx.user_id,),
        )
        rows = await cur.fetchall()
    release_ids = [r["release_id"] for r in rows]
    if not release_ids:
        return {"refreshed": 0, "stale_count": 0}
    coord = RefreshCoordinator(pool=ctx.pool, redis=ctx.redis)
    await coord.bump_priorities(release_ids)
    completed = 0
    async for _ev in coord.subscribe_progress(str(ctx.user_id), deadline_seconds=deadline_seconds):
        completed += 1
        if completed >= len(release_ids):
            break
    return {"refreshed": completed, "stale_count": len(release_ids)}
