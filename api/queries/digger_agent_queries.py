"""SQL helpers for the digger agent session/message tables.

Async psycopg3 throughout: pool.connection() -> conn.cursor() -> cur.execute(sql,
(params,)); %s placeholders, params as tuples. JSONB columns (``content``,
``token_counts``) are written with the psycopg ``Jsonb`` adapter and returned
already parsed (dict_row).
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING
import uuid

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


if TYPE_CHECKING:  # pragma: no cover
    from typing import Any

    from common import AsyncPostgreSQLPool


async def create_session(pool: AsyncPostgreSQLPool, user_id: uuid.UUID, *, model: str) -> uuid.UUID:
    """Create an agent session row and return its new session_id."""
    session_id = uuid.uuid4()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "INSERT INTO digger.agent_sessions (session_id, user_id, model) VALUES (%s, %s, %s)",
            (session_id, user_id, model),
        )
    return session_id


async def append_message(
    pool: AsyncPostgreSQLPool,
    session_id: uuid.UUID,
    *,
    role: str,
    content: list[dict[str, Any]],
    token_counts: dict[str, Any] | None = None,
) -> uuid.UUID:
    """Append a message to a session and bump the session's last_active_at."""
    message_id = uuid.uuid4()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "INSERT INTO digger.agent_messages (message_id, session_id, role, content, token_counts) VALUES (%s, %s, %s, %s, %s)",
            (message_id, session_id, role, Jsonb(content), Jsonb(token_counts) if token_counts else None),
        )
        await cur.execute(
            "UPDATE digger.agent_sessions SET last_active_at = now() WHERE session_id = %s",
            (session_id,),
        )
    return message_id


async def list_messages(pool: AsyncPostgreSQLPool, session_id: uuid.UUID) -> list[dict[str, Any]]:
    """Return a session's messages (oldest first) as ``{"role", "content"}`` dicts."""
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT role, content FROM digger.agent_messages WHERE session_id = %s ORDER BY created_at ASC",
            (session_id,),
        )
        rows = await cur.fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


async def list_sessions(pool: AsyncPostgreSQLPool, user_id: uuid.UUID, limit: int = 50) -> list[dict[str, Any]]:
    """Return a user's agent sessions (most recently active first) for the session list UI."""
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT session_id, started_at, last_active_at, total_cost_usd "
            "FROM digger.agent_sessions WHERE user_id = %s "
            "ORDER BY last_active_at DESC LIMIT %s",
            (user_id, limit),
        )
        rows = await cur.fetchall()
    return [
        {
            "session_id": str(r["session_id"]),
            "started_at": r["started_at"].isoformat(),
            "last_active_at": r["last_active_at"].isoformat(),
            "total_cost_usd": float(r["total_cost_usd"]),
        }
        for r in rows
    ]


async def update_token_totals(
    pool: AsyncPostgreSQLPool,
    session_id: uuid.UUID,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read: int,
    cost_usd: Decimal | float,
) -> None:
    """Add this turn's token counts and cost to the session's running totals."""
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "UPDATE digger.agent_sessions SET "
            "total_input_tokens = total_input_tokens + %s, "
            "total_output_tokens = total_output_tokens + %s, "
            "total_cache_read_tokens = total_cache_read_tokens + %s, "
            "total_cost_usd = total_cost_usd + %s "
            "WHERE session_id = %s",
            (input_tokens, output_tokens, cache_read, Decimal(str(cost_usd)), session_id),
        )
