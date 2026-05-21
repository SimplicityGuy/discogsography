"""SQL helpers for the digger.reports table, used by the reports API router.

Async psycopg3 throughout: pool.connection() -> conn.cursor() -> cur.execute(sql,
(params,)); %s placeholders, params as tuples. JSONB columns are written with the
psycopg ``Jsonb`` adapter and returned already parsed (dict_row).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
import uuid

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


if TYPE_CHECKING:  # pragma: no cover
    from typing import Any

    from common import AsyncPostgreSQLPool


async def list_reports(pool: AsyncPostgreSQLPool, user_id: uuid.UUID, limit: int = 50) -> list[dict[str, Any]]:
    """Return a user's reports (newest first) as inbox summaries."""
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT report_id, kind, generated_at, read_at, title, summary, change_flag "
            "FROM digger.reports WHERE user_id = %s ORDER BY generated_at DESC LIMIT %s",
            (user_id, limit),
        )
        rows = await cur.fetchall()
    return [
        {
            "report_id": str(r["report_id"]),
            "kind": r["kind"],
            "generated_at": r["generated_at"].isoformat(),
            "read_at": r["read_at"].isoformat() if r["read_at"] else None,
            "title": r["title"],
            "summary": r["summary"],
            "change_flag": r["change_flag"],
        }
        for r in rows
    ]


async def get_report(pool: AsyncPostgreSQLPool, user_id: uuid.UUID, report_id: uuid.UUID) -> dict[str, Any] | None:
    """Return one full report owned by the user, or None if it does not exist."""
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT report_id, user_id, kind, generated_at, read_at, title, summary, bundles, watching, change_flag, shipping_confidence "
            "FROM digger.reports WHERE report_id = %s AND user_id = %s",
            (report_id, user_id),
        )
        row = await cur.fetchone()
    if row is None:
        return None
    result = dict(row)
    result["report_id"] = str(result["report_id"])
    result["user_id"] = str(result["user_id"])
    result["generated_at"] = result["generated_at"].isoformat()
    result["read_at"] = result["read_at"].isoformat() if result["read_at"] else None
    return result


async def insert_report(
    pool: AsyncPostgreSQLPool,
    user_id: uuid.UUID,
    *,
    kind: str,
    title: str,
    summary: dict[str, Any],
    bundles: list[Any],
    watching: list[int],
    change_flag: str,
    shipping_confidence: str,
) -> uuid.UUID:
    """Insert a report row and return its new report_id."""
    report_id = uuid.uuid4()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "INSERT INTO digger.reports "
            "(report_id, user_id, kind, title, summary, bundles, watching, change_flag, shipping_confidence) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (report_id, user_id, kind, title, Jsonb(summary), Jsonb(bundles), Jsonb(watching), change_flag, shipping_confidence),
        )
    return report_id


async def mark_read(pool: AsyncPostgreSQLPool, user_id: uuid.UUID, report_id: uuid.UUID) -> bool:
    """Mark a report read; return True if a still-unread report was updated."""
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "UPDATE digger.reports SET read_at = now() WHERE report_id = %s AND user_id = %s AND read_at IS NULL",
            (report_id, user_id),
        )
        return cur.rowcount > 0
