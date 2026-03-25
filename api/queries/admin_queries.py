"""Query functions for admin dashboard Phase 2 endpoints.

All functions receive only their connection dependency and return plain dicts
that the router serialises via Pydantic models.
"""

from __future__ import annotations

import logging
from typing import Any

from psycopg.rows import dict_row

from common.query_debug import execute_sql


logger = logging.getLogger(__name__)


async def get_user_stats(pool: Any) -> dict[str, Any]:
    """Fetch user registration stats, active user counts, and OAuth rate.

    "Active" = user has at least one sync_history row with started_at in the window.
    """
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(
            cur,
            """
            SELECT
                (SELECT COUNT(*) FROM users) AS total_users,
                (SELECT COUNT(DISTINCT user_id) FROM oauth_tokens WHERE provider = 'discogs') AS oauth_users,
                (SELECT COUNT(DISTINCT user_id) FROM sync_history
                 WHERE started_at >= NOW() - INTERVAL '7 days') AS active_7d,
                (SELECT COUNT(DISTINCT user_id) FROM sync_history
                 WHERE started_at >= NOW() - INTERVAL '30 days') AS active_30d
            """,
        )
        summary = await cur.fetchone()

        total = summary["total_users"]
        oauth_rate = round(summary["oauth_users"] / total, 4) if total > 0 else 0.0

        await execute_sql(
            cur,
            """
            SELECT date_trunc('day', created_at)::date::text AS date,
                   COUNT(*) AS count
            FROM users
            WHERE created_at >= NOW() - INTERVAL '30 days'
            GROUP BY 1 ORDER BY 1
            """,
        )
        daily = [dict(row) for row in await cur.fetchall()]

        await execute_sql(
            cur,
            """
            SELECT date_trunc('week', created_at)::date::text AS week_start,
                   COUNT(*) AS count
            FROM users
            WHERE created_at >= NOW() - INTERVAL '12 weeks'
            GROUP BY 1 ORDER BY 1
            """,
        )
        weekly = [dict(row) for row in await cur.fetchall()]

        await execute_sql(
            cur,
            """
            SELECT to_char(date_trunc('month', created_at), 'YYYY-MM') AS month,
                   COUNT(*) AS count
            FROM users
            WHERE created_at >= NOW() - INTERVAL '12 months'
            GROUP BY 1 ORDER BY 1
            """,
        )
        monthly = [dict(row) for row in await cur.fetchall()]

    return {
        "total_users": total,
        "active_7d": summary["active_7d"],
        "active_30d": summary["active_30d"],
        "oauth_connection_rate": oauth_rate,
        "registrations": {
            "daily": daily,
            "weekly": weekly,
            "monthly": monthly,
        },
    }


async def get_sync_activity(pool: Any) -> dict[str, Any]:
    """Fetch sync activity stats for 7d and 30d windows."""

    async def _query_period(cur: Any, days: int) -> dict[str, Any]:
        await execute_sql(
            cur,
            """
            SELECT
                COUNT(*) AS total_syncs,
                COUNT(*) FILTER (WHERE status = 'failed') AS total_failures,
                AVG(COALESCE(items_synced, 0)) AS avg_items
            FROM sync_history
            WHERE started_at >= NOW() - make_interval(days => %s)
            """,
            (days,),
        )
        row = await cur.fetchone()
        total = row["total_syncs"]
        return {
            "total_syncs": total,
            "syncs_per_day": round(total / days, 2) if total > 0 else 0.0,
            "avg_items_synced": round(float(row["avg_items"]), 1) if row["avg_items"] is not None else 0.0,
            "failure_rate": round(row["total_failures"] / total, 4) if total > 0 else 0.0,
            "total_failures": row["total_failures"],
        }

    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        period_7d = await _query_period(cur, 7)
        period_30d = await _query_period(cur, 30)

    return {"period_7d": period_7d, "period_30d": period_30d}
