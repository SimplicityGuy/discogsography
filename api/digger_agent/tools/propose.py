"""Tool: propose_tier_changes — record a pending tier-change proposal for user approval."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
import uuid

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


if TYPE_CHECKING:  # pragma: no cover
    from typing import Any

    from api.digger_agent.tools.context import ToolContext


_PROPOSAL_TTL = timedelta(days=30)


async def propose_tier_changes(*, ctx: ToolContext, changes: list[dict[str, Any]]) -> dict[str, Any]:
    """Record a pending proposal for tier changes. The user must approve it in the UI.

    Each change is validated against the user's current wantlist; releases not in
    the wantlist are skipped. Returns an error if no changes are valid.
    """
    payload_rows: list[dict[str, Any]] = []
    async with ctx.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        for change in changes:
            await cur.execute(
                "SELECT tier FROM digger.user_wantlist_priorities WHERE user_id = %s AND release_id = %s",
                (ctx.user_id, change["release_id"]),
            )
            current = await cur.fetchone()
            if current is None:
                continue
            payload_rows.append(
                {
                    "release_id": change["release_id"],
                    "current_tier": current["tier"],
                    "proposed_tier": change["proposed_tier"],
                    "reason": str(change["reason"])[:240],
                }
            )
        if not payload_rows:
            return {"error": "no valid changes (releases not in wantlist)"}
        proposal_id = uuid.uuid4()
        expires_at = datetime.now(UTC) + _PROPOSAL_TTL
        await cur.execute(
            "INSERT INTO digger.proposals (proposal_id, user_id, session_id, payload, expires_at) VALUES (%s, %s, %s, %s, %s)",
            (proposal_id, ctx.user_id, ctx.session_id, Jsonb(payload_rows), expires_at),
        )
    return {"proposal_id": str(proposal_id), "count": len(payload_rows)}
