"""Tool: summarize_marketplace_coverage — must/nice/eventually availability."""

from __future__ import annotations

from typing import TYPE_CHECKING

from psycopg.rows import dict_row


if TYPE_CHECKING:  # pragma: no cover
    from typing import Any

    from api.digger_agent.tools.context import ToolContext


_COVERAGE_SQL = """
SELECT
  SUM(CASE WHEN uwp.tier = 'must' THEN 1 ELSE 0 END)                          AS must_total,
  SUM(CASE WHEN uwp.tier = 'nice' THEN 1 ELSE 0 END)                          AS nice_total,
  SUM(CASE WHEN uwp.tier = 'eventually' THEN 1 ELSE 0 END)                    AS eventually_total,
  SUM(CASE WHEN uwp.tier = 'must' AND lc.active > 0 THEN 1 ELSE 0 END)        AS must_avail,
  SUM(CASE WHEN uwp.tier = 'nice' AND lc.active > 0 THEN 1 ELSE 0 END)        AS nice_avail,
  SUM(CASE WHEN uwp.tier = 'eventually' AND lc.active > 0 THEN 1 ELSE 0 END)  AS eventually_avail
FROM digger.user_wantlist_priorities uwp
LEFT JOIN LATERAL (
  SELECT COUNT(*) AS active FROM digger.listings l
  WHERE l.release_id = uwp.release_id AND l.removed_at IS NULL
) lc ON true
WHERE uwp.user_id = %s
"""


async def summarize_marketplace_coverage(*, ctx: ToolContext) -> dict[str, Any]:
    """Aggregate: of the user's must/nice/eventually releases, how many have qualifying listings."""
    async with ctx.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(_COVERAGE_SQL, (ctx.user_id,))
        row = await cur.fetchone()
    row = row or {}
    return {
        "must": {"total": int(row.get("must_total") or 0), "available": int(row.get("must_avail") or 0)},
        "nice": {"total": int(row.get("nice_total") or 0), "available": int(row.get("nice_avail") or 0)},
        "eventually": {"total": int(row.get("eventually_total") or 0), "available": int(row.get("eventually_avail") or 0)},
    }
