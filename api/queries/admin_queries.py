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


async def get_neo4j_storage(driver: Any) -> dict[str, Any]:
    """Fetch Neo4j node/relationship counts and best-effort store sizes via JMX."""
    if driver is None:
        return {"status": "error", "error": "Neo4j driver not configured"}

    async with driver.session() as session:
        result = await session.run("CALL apoc.meta.stats() YIELD labels, relTypesCount")
        record = await result.single()

        nodes = [{"label": label, "count": count} for label, count in sorted(record["labels"].items())]
        relationships = [{"type": rel_type, "count": count} for rel_type, count in sorted(record["relTypesCount"].items())]

    store_sizes = None
    try:
        async with driver.session() as session:
            result = await session.run("CALL dbms.queryJmx('org.neo4j:instance=kernel#0,name=Store sizes') YIELD attributes RETURN attributes")
            record = await result.single()
            if record and record.get("attributes"):
                attrs = record["attributes"]

                def _fmt(key: str) -> str:
                    val = attrs.get(key, {})
                    bytes_val = val.get("value", 0) if isinstance(val, dict) else 0
                    if bytes_val >= 1_073_741_824:
                        return f"{bytes_val / 1_073_741_824:.1f} GB"
                    if bytes_val >= 1_048_576:
                        return f"{bytes_val / 1_048_576:.0f} MB"
                    return f"{bytes_val / 1024:.0f} kB"

                store_sizes = {
                    "total": _fmt("TotalStoreSize"),
                    "nodes": _fmt("NodeStoreSize"),
                    "relationships": _fmt("RelationshipStoreSize"),
                    "strings": _fmt("StringStoreSize"),
                }
    except Exception:
        logger.debug("⚙️ Neo4j JMX store sizes not available — skipping")

    return {
        "status": "ok",
        "nodes": nodes,
        "relationships": relationships,
        "store_sizes": store_sizes,
    }


async def get_postgres_storage(pool: Any) -> dict[str, Any]:
    """Fetch PostgreSQL table sizes, row estimates, and total database size."""
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(
            cur,
            """
            SELECT
                relname AS table_name,
                n_live_tup AS row_estimate,
                pg_size_pretty(pg_total_relation_size(relid)) AS total_size,
                pg_size_pretty(pg_indexes_size(relid)) AS index_size
            FROM pg_stat_user_tables
            ORDER BY pg_total_relation_size(relid) DESC
            """,
        )
        tables = [
            {
                "name": row["table_name"],
                "row_count": row["row_estimate"],
                "size": row["total_size"],
                "index_size": row["index_size"],
            }
            for row in await cur.fetchall()
        ]

        await execute_sql(
            cur,
            "SELECT pg_size_pretty(pg_database_size(current_database())) AS total_size",
        )
        db_size_row = await cur.fetchone()
        total_size = db_size_row["total_size"] if db_size_row else "0 bytes"

    return {"status": "ok", "tables": tables, "total_size": total_size}


_AUDIT_LOG_BASE_WINDOW = "a.created_at >= NOW() - INTERVAL '90 days'"

# Four fixed query variants — one per filter combination.  All SQL structure is
# hardcoded; user-supplied values are always bound as %s parameters, never
# interpolated into the query string.
_AUDIT_COUNT_UNFILTERED = f"SELECT count(*) AS total FROM admin_audit_log a WHERE {_AUDIT_LOG_BASE_WINDOW}"  # noqa: S608
_AUDIT_COUNT_ACTION = f"SELECT count(*) AS total FROM admin_audit_log a WHERE {_AUDIT_LOG_BASE_WINDOW} AND a.action = %s"  # noqa: S608
_AUDIT_COUNT_ADMIN = f"SELECT count(*) AS total FROM admin_audit_log a WHERE {_AUDIT_LOG_BASE_WINDOW} AND a.admin_id = %s::uuid"  # noqa: S608
_AUDIT_COUNT_BOTH = f"SELECT count(*) AS total FROM admin_audit_log a WHERE {_AUDIT_LOG_BASE_WINDOW} AND a.action = %s AND a.admin_id = %s::uuid"  # noqa: S608

_AUDIT_SELECT = (
    "SELECT a.id, a.admin_id, u.email AS admin_email,"
    " a.action, a.target, a.details, a.created_at"
    " FROM admin_audit_log a JOIN users u ON u.id = a.admin_id"
    " WHERE"
)
_AUDIT_ENTRIES_UNFILTERED = f"{_AUDIT_SELECT} {_AUDIT_LOG_BASE_WINDOW} ORDER BY a.created_at DESC LIMIT %s OFFSET %s"
_AUDIT_ENTRIES_ACTION = f"{_AUDIT_SELECT} {_AUDIT_LOG_BASE_WINDOW} AND a.action = %s ORDER BY a.created_at DESC LIMIT %s OFFSET %s"
_AUDIT_ENTRIES_ADMIN = f"{_AUDIT_SELECT} {_AUDIT_LOG_BASE_WINDOW} AND a.admin_id = %s::uuid ORDER BY a.created_at DESC LIMIT %s OFFSET %s"
_AUDIT_ENTRIES_BOTH = (
    f"{_AUDIT_SELECT} {_AUDIT_LOG_BASE_WINDOW} AND a.action = %s AND a.admin_id = %s::uuid ORDER BY a.created_at DESC LIMIT %s OFFSET %s"
)


async def get_audit_log(
    pool: Any,
    page: int = 1,
    page_size: int = 50,
    action_filter: str | None = None,
    admin_id_filter: str | None = None,
) -> dict[str, Any]:
    """Fetch paginated audit log entries (last 90 days by default)."""
    offset = (page - 1) * page_size

    # Select the appropriate pre-built query string and parameter list based on
    # which filters are active.  No runtime string construction occurs here.
    if action_filter and admin_id_filter:
        count_sql = _AUDIT_COUNT_BOTH
        count_params: list[Any] = [action_filter, admin_id_filter]
        entries_sql = _AUDIT_ENTRIES_BOTH
        entries_params: list[Any] = [action_filter, admin_id_filter, page_size, offset]
    elif action_filter:
        count_sql = _AUDIT_COUNT_ACTION
        count_params = [action_filter]
        entries_sql = _AUDIT_ENTRIES_ACTION
        entries_params = [action_filter, page_size, offset]
    elif admin_id_filter:
        count_sql = _AUDIT_COUNT_ADMIN
        count_params = [admin_id_filter]
        entries_sql = _AUDIT_ENTRIES_ADMIN
        entries_params = [admin_id_filter, page_size, offset]
    else:
        count_sql = _AUDIT_COUNT_UNFILTERED
        count_params = []
        entries_sql = _AUDIT_ENTRIES_UNFILTERED
        entries_params = [page_size, offset]

    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(cur, count_sql, count_params)
        total_row = await cur.fetchone()
        total = total_row["total"] if total_row else 0

        await execute_sql(cur, entries_sql, entries_params)
        entries = await cur.fetchall()

    return {
        "entries": entries,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def get_redis_storage(redis: Any) -> dict[str, Any]:
    """Fetch Redis memory usage and key distribution grouped by prefix."""
    if redis is None:
        return {"status": "error", "error": "Redis not configured"}

    memory_info = await redis.info("memory")
    keyspace_info = await redis.info("keyspace")

    total_keys = 0
    for db_info in keyspace_info.values():
        if isinstance(db_info, dict) and "keys" in db_info:
            total_keys += db_info["keys"]

    prefix_counts: dict[str, int] = {}
    cursor = 0
    max_scan_keys = 10_000
    total_scanned = 0
    while True:
        cursor, keys = await redis.scan(cursor=cursor, count=500)
        for key in keys:
            key_str = key if isinstance(key, str) else key.decode("utf-8", errors="replace")
            prefix = key_str.split(":")[0] + ":" if ":" in key_str else key_str
            prefix_counts[prefix] = prefix_counts.get(prefix, 0) + 1
        total_scanned += len(keys)
        if cursor == 0 or total_scanned >= max_scan_keys:
            break

    keys_by_prefix = [{"prefix": prefix, "count": count} for prefix, count in sorted(prefix_counts.items(), key=lambda x: -x[1])]

    return {
        "status": "ok",
        "memory_used": memory_info.get("used_memory_human", ""),
        "memory_peak": memory_info.get("used_memory_peak_human", ""),
        "total_keys": total_keys,
        "keys_by_prefix": keys_by_prefix,
    }
