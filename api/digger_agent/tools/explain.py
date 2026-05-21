"""Tool: explain_bundle — itemized breakdown of one recently computed bundle."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:  # pragma: no cover
    from typing import Any

    from api.digger_agent.tools.context import ToolContext


async def explain_bundle(*, ctx: ToolContext, bundle_name: str) -> dict[str, Any]:
    """Return the itemized breakdown of one bundle from the latest compute_bundles result."""
    out = ctx.last_optimizer_output
    if out is None:
        return {"error": "no recent compute_bundles result; call compute_bundles first"}
    bundle = next((b for b in out.bundles if b.name == bundle_name), None)
    if bundle is None:
        return {"error": f"bundle {bundle_name} not in latest result"}
    return {
        "bundle_name": bundle_name,
        "grand_total_cents": bundle.grand_total_cents,
        "coverage": bundle.coverage.model_dump(),
        "seller_orders": [so.model_dump(mode="json") for so in bundle.seller_orders],
        "reasoning_hint": bundle.reasoning_hint,
    }
