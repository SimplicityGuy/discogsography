"""SQL helpers for the digger.proposals table, used by the proposals API router.

Async psycopg3 throughout: pool.connection() -> conn.cursor() -> cur.execute(sql,
(params,)); %s placeholders, params as tuples. JSONB ``payload`` is returned
already parsed (dict_row). Approving a proposal applies its tier changes and
flips its status in a single transaction (autocommit disabled, FOR UPDATE lock).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from psycopg.rows import dict_row


if TYPE_CHECKING:  # pragma: no cover
    from typing import Any
    import uuid

    from common import AsyncPostgreSQLPool


async def list_pending_proposals(pool: AsyncPostgreSQLPool, user_id: uuid.UUID) -> list[dict[str, Any]]:
    """Return a user's pending, unexpired proposals (newest first)."""
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT proposal_id, created_at, status, payload FROM digger.proposals "
            "WHERE user_id = %s AND status = 'pending' AND expires_at > now() "
            "ORDER BY created_at DESC",
            (user_id,),
        )
        rows = await cur.fetchall()
    return [
        {
            "proposal_id": str(r["proposal_id"]),
            "created_at": r["created_at"].isoformat(),
            "status": r["status"],
            "payload": r["payload"],
        }
        for r in rows
    ]


async def approve_proposal(pool: AsyncPostgreSQLPool, proposal_id: uuid.UUID, user_id: uuid.UUID) -> int | None:
    """Apply a pending proposal's tier changes and mark it approved, in one transaction.

    Returns the number of wantlist rows actually updated (releases still in the
    wantlist), or ``None`` if the proposal does not exist, is not owned by the
    user, or is no longer pending.
    """
    async with pool.connection() as conn:
        await conn.set_autocommit(False)
        async with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT payload FROM digger.proposals WHERE proposal_id = %s AND user_id = %s AND status = 'pending' FOR UPDATE",
                (proposal_id, user_id),
            )
            row = await cur.fetchone()
            if row is None:
                return None
            applied = 0
            for change in row["payload"]:
                await cur.execute(
                    "UPDATE digger.user_wantlist_priorities SET tier = %s, updated_at = now() WHERE user_id = %s AND release_id = %s",
                    (change["proposed_tier"], user_id, change["release_id"]),
                )
                if cur.rowcount > 0:
                    applied += 1
            await cur.execute(
                "UPDATE digger.proposals SET status = 'approved' WHERE proposal_id = %s",
                (proposal_id,),
            )
        return applied


async def reject_proposal(pool: AsyncPostgreSQLPool, proposal_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """Mark a pending proposal rejected; return True if one was updated."""
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "UPDATE digger.proposals SET status = 'rejected' WHERE proposal_id = %s AND user_id = %s AND status = 'pending'",
            (proposal_id, user_id),
        )
        return cur.rowcount > 0
