"""Tool: get_listings_for_release — active listings for one release."""

from __future__ import annotations

from typing import TYPE_CHECKING

from psycopg.rows import dict_row


if TYPE_CHECKING:  # pragma: no cover
    from typing import Any

    from api.digger_agent.tools.context import ToolContext


async def get_listings_for_release(*, ctx: ToolContext, release_id: int) -> dict[str, Any]:
    """Return active (not removed) listings for one release_id, cheapest first, with seller info."""
    async with ctx.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT l.listing_id, l.seller_id, l.price_value, l.price_currency, "
            "l.media_condition, l.sleeve_condition, l.last_seen_at, "
            "s.username, s.country_code, s.feedback_score "
            "FROM digger.listings l "
            "JOIN digger.sellers s ON s.seller_id = l.seller_id "
            "WHERE l.release_id = %s AND l.removed_at IS NULL "
            "ORDER BY l.price_value ASC LIMIT 100",
            (release_id,),
        )
        rows = await cur.fetchall()
    listings = [
        {
            "listing_id": r["listing_id"],
            "seller_id": r["seller_id"],
            "price_cents": int(r["price_value"] * 100),
            "currency": r["price_currency"],
            "media_condition": r["media_condition"],
            "sleeve_condition": r["sleeve_condition"],
            "last_seen_at": r["last_seen_at"].isoformat(),
            "seller": {
                "username": r["username"],
                "country_code": r["country_code"],
                "feedback_score": float(r["feedback_score"]) if r["feedback_score"] is not None else None,
            },
        }
        for r in rows
    ]
    return {"release_id": release_id, "listings": listings, "count": len(listings)}
