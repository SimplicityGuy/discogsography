"""Query functions for admin metrics history endpoints (Phase 3).

Provides time-series aggregation queries for queue metrics and service
health data, supporting multiple time ranges and granularities.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from psycopg.rows import dict_row

from common.query_debug import execute_sql


logger = logging.getLogger(__name__)


GRANULARITY_MAP: dict[str, dict[str, Any]] = {
    "1h": {"interval": "1 hour", "bucket": "5 minutes", "raw": True, "granularity": "5min"},
    "6h": {"interval": "6 hours", "bucket": "5 minutes", "raw": True, "granularity": "5min"},
    "24h": {"interval": "24 hours", "bucket": "15 minutes", "raw": False, "granularity": "15min"},
    "7d": {"interval": "7 days", "bucket": "1 hour", "raw": False, "granularity": "1hour"},
    "30d": {"interval": "30 days", "bucket": "6 hours", "raw": False, "granularity": "6hour"},
    "90d": {"interval": "90 days", "bucket": "1 day", "raw": False, "granularity": "1day"},
    "365d": {"interval": "365 days", "bucket": "1 day", "raw": False, "granularity": "1day"},
}


def _bucket_to_trunc_unit(bucket: str) -> str:
    """Convert a bucket string like '15 minutes' to a date_trunc unit like 'minute'."""
    unit = bucket.rsplit(maxsplit=1)[-1].rstrip("s")  # "minutes" -> "minute", "hours" -> "hour"
    return unit


def _round_or_int(value: Any, *, is_raw: bool) -> int | float:
    """Return int for raw data, rounded float for aggregated. Handles None."""
    if value is None:
        return 0 if is_raw else 0.0
    if is_raw:
        return int(value)
    return round(float(value), 2)


async def get_queue_history(pool: Any, range_value: str) -> dict[str, Any]:
    """Fetch queue metrics history for the given time range.

    Returns a dict with keys: range, granularity, queues, dlq_summary.
    Raises ValueError for invalid range values.
    """
    if range_value not in GRANULARITY_MAP:
        msg = f"Invalid range: {range_value!r}. Valid ranges: {sorted(GRANULARITY_MAP.keys())}"
        raise ValueError(msg)

    spec = GRANULARITY_MAP[range_value]
    is_raw = spec["raw"]

    if is_raw:
        query = """
            SELECT queue_name,
                   recorded_at::text AS ts,
                   messages_ready AS ready,
                   messages_unacknowledged AS unacked,
                   consumers,
                   publish_rate,
                   ack_rate AS deliver_rate
            FROM queue_metrics
            WHERE recorded_at >= NOW() - %s::interval
            ORDER BY queue_name, recorded_at
        """
    else:
        trunc_unit = _bucket_to_trunc_unit(spec["bucket"])
        query = f"""
            SELECT queue_name,
                   date_trunc('{trunc_unit}', recorded_at)::text AS ts,
                   AVG(messages_ready) AS ready,
                   AVG(messages_unacknowledged) AS unacked,
                   AVG(consumers) AS consumers,
                   AVG(publish_rate) AS publish_rate,
                   AVG(ack_rate) AS deliver_rate
            FROM queue_metrics
            WHERE recorded_at >= NOW() - %s::interval
            GROUP BY queue_name, date_trunc('{trunc_unit}', recorded_at)
            ORDER BY queue_name, ts
        """

    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(cur, query, (spec["interval"],))
        rows = await cur.fetchall()

    queues: dict[str, Any] = {}
    dlq_summary: dict[str, Any] = {}

    for row in rows:
        name = row["queue_name"]
        point = {
            "ts": row["ts"],
            "ready": _round_or_int(row["ready"], is_raw=is_raw),
            "unacked": _round_or_int(row["unacked"], is_raw=is_raw),
            "total": _round_or_int(row["total"], is_raw=is_raw),
            "publish_rate": _round_or_int(row["publish_rate"], is_raw=is_raw),
            "deliver_rate": _round_or_int(row["deliver_rate"], is_raw=is_raw),
        }

        target = dlq_summary if name.endswith("-dlq") else queues
        if name not in target:
            target[name] = {"history": [], "current": {}}
        target[name]["history"].append(point)
        target[name]["current"] = {k: v for k, v in point.items() if k != "ts"}

    return {
        "range": range_value,
        "granularity": spec["granularity"],
        "queues": queues,
        "dlq_summary": dlq_summary,
    }


async def get_health_history(pool: Any, range_value: str) -> dict[str, Any]:
    """Fetch service health history for the given time range.

    Returns a dict with keys: range, granularity, services, api_endpoints.
    Raises ValueError for invalid range values.
    """
    if range_value not in GRANULARITY_MAP:
        msg = f"Invalid range: {range_value!r}. Valid ranges: {sorted(GRANULARITY_MAP.keys())}"
        raise ValueError(msg)

    spec = GRANULARITY_MAP[range_value]

    query = """
        SELECT service_name,
               recorded_at::text AS ts,
               status,
               response_time_ms,
               endpoint_stats
        FROM service_health_metrics
        WHERE recorded_at >= NOW() - %s::interval
        ORDER BY service_name, recorded_at
    """

    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(cur, query, (spec["interval"],))
        rows = await cur.fetchall()

    services: dict[str, Any] = {}
    api_endpoints: dict[str, Any] = {}

    for row in rows:
        name = row["service_name"]
        if name not in services:
            services[name] = {"history": [], "healthy_count": 0, "total_count": 0, "current": None}

        services[name]["history"].append(
            {
                "ts": row["ts"],
                "status": row["status"],
                "response_time_ms": row["response_time_ms"],
            }
        )
        services[name]["total_count"] += 1
        if row["status"] == "healthy":
            services[name]["healthy_count"] += 1
        services[name]["current"] = row["status"]

        # Parse endpoint_stats JSONB from API service rows
        if row.get("endpoint_stats"):
            try:
                stats = row["endpoint_stats"]
                if isinstance(stats, str):
                    stats = json.loads(stats)
                for ep_path, ep_data in stats.items():
                    if ep_path not in api_endpoints:
                        api_endpoints[ep_path] = {"history": []}
                    api_endpoints[ep_path]["history"].append(
                        {
                            "ts": row["ts"],
                            **ep_data,
                        }
                    )
            except (json.JSONDecodeError, AttributeError):
                logger.debug("Failed to parse endpoint_stats for %s at %s", name, row["ts"])

    # Compute uptime_pct and clean up internal counters
    for svc_data in services.values():
        total = svc_data.pop("total_count")
        healthy = svc_data.pop("healthy_count")
        svc_data["uptime_pct"] = round(healthy / total * 100, 2) if total > 0 else 0.0

    return {
        "range": range_value,
        "granularity": spec["granularity"],
        "services": services,
        "api_endpoints": api_endpoints,
    }
