"""Tool: get_user_settings — the user's digger preferences."""

from __future__ import annotations

from typing import TYPE_CHECKING

from api.queries import digger_queries as q


if TYPE_CHECKING:  # pragma: no cover
    from typing import Any

    from api.digger_agent.tools.context import ToolContext


async def get_user_settings(*, ctx: ToolContext) -> dict[str, Any]:
    """Return the user's location, currency, scheduled cadence, and preferred model."""
    settings = await q.get_user_settings(ctx.pool, ctx.user_id)
    if settings is None:
        return {"enabled": False}
    return {
        "enabled": settings.enabled,
        "country_code": settings.country_code,
        "currency": settings.currency,
        "scheduled_cadence": settings.scheduled_cadence,
        "preferred_model": settings.preferred_model,
    }
