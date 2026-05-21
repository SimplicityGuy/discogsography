"""Tool: get_wantlist — the user's wantlist grouped by tier."""

from __future__ import annotations

from typing import TYPE_CHECKING

from api.queries import digger_queries as q


if TYPE_CHECKING:  # pragma: no cover
    from typing import Any

    from api.digger_agent.tools.context import ToolContext


_PAGE_SIZE = 100


async def get_wantlist(*, ctx: ToolContext, page: int = 1, tier_filter: str | None = None) -> dict[str, Any]:
    """Return the user's wantlist grouped into must/nice/eventually (page size 100)."""
    rows = await q.list_wantlist_priorities(ctx.pool, ctx.user_id)
    if tier_filter:
        rows = [r for r in rows if r.tier == tier_filter]
    start = (page - 1) * _PAGE_SIZE
    page_rows = rows[start : start + _PAGE_SIZE]
    grouped: dict[str, list[dict[str, Any]]] = {"must": [], "nice": [], "eventually": []}
    for r in page_rows:
        grouped[r.tier].append(
            {
                "release_id": r.release_id,
                "min_media_condition": r.min_media_condition,
                "min_sleeve_condition": r.min_sleeve_condition,
                "max_price_cents": r.max_price_cents,
            }
        )
    return {**grouped, "page": page, "total": len(rows)}
