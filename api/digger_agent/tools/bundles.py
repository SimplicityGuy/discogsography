"""Tool: compute_bundles — run the deterministic optimizer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from api.digger_refresh.input_builder import build_optimizer_input
from api.queries import digger_queries as q
from common.digger_optimizer import pareto_bundles


if TYPE_CHECKING:  # pragma: no cover
    from typing import Any

    from api.digger_agent.tools.context import ToolContext


async def compute_bundles(
    *,
    ctx: ToolContext,
    budget_cap_cents: int | None = None,
    excluded_sellers: list[int] | None = None,
) -> dict[str, Any]:
    """Run the deterministic optimizer and return the named Pareto bundles as JSON."""
    settings = await q.get_user_settings(ctx.pool, ctx.user_id)
    location = (settings.country_code if settings else None) or "US"
    currency = settings.currency if settings else "USD"
    inp = await build_optimizer_input(
        ctx.pool,
        ctx.user_id,
        location=location,
        currency=currency,
        budget_cap_cents=budget_cap_cents,
        excluded_sellers=frozenset(excluded_sellers or []),
    )
    out = pareto_bundles(inp)
    ctx.last_optimizer_output = out
    return out.model_dump(mode="json")
