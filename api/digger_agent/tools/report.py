"""Tool: save_report — persist the most recent bundles to the user's inbox."""

from __future__ import annotations

from typing import TYPE_CHECKING

from api.queries.digger_reports import insert_report


if TYPE_CHECKING:  # pragma: no cover
    from typing import Any

    from api.digger_agent.tools.context import ToolContext


async def save_report(*, ctx: ToolContext, title: str) -> dict[str, Any]:
    """Persist the latest compute_bundles result to the user's report inbox."""
    out = ctx.last_optimizer_output
    if out is None:
        return {"error": "no recent compute_bundles result; call compute_bundles first"}
    bundles_payload = [b.model_dump(mode="json") for b in out.bundles]
    first = out.bundles[0] if out.bundles else None
    summary: dict[str, Any] = {
        "wantlist_size": (first.coverage.must + first.coverage.nice + first.coverage.eventually) if first else 0,
        "must_available": first.coverage.must if first else 0,
        "total_value_cents": first.grand_total_cents if first else 0,
    }
    report_id = await insert_report(
        ctx.pool,
        ctx.user_id,
        kind="interactive",
        title=title,
        summary=summary,
        bundles=bundles_payload,
        watching=out.watching,
        change_flag="first_run",
        shipping_confidence=out.shipping_confidence,
    )
    return {"report_id": str(report_id)}
