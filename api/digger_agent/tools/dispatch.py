"""Dispatch a named tool call to its implementation.

Re-exports ``ToolContext`` (defined in ``context.py``) so callers can keep
``from api.digger_agent.tools.dispatch import ToolContext, dispatch_tool``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from api.digger_agent.tools.bundles import compute_bundles
from api.digger_agent.tools.context import ToolContext
from api.digger_agent.tools.explain import explain_bundle
from api.digger_agent.tools.listings import get_listings_for_release
from api.digger_agent.tools.propose import propose_tier_changes
from api.digger_agent.tools.refresh import request_opportunistic_refresh
from api.digger_agent.tools.report import save_report
from api.digger_agent.tools.settings import get_user_settings
from api.digger_agent.tools.summarize import summarize_marketplace_coverage
from api.digger_agent.tools.wantlist import get_wantlist


if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Awaitable, Callable
    from typing import Any


__all__ = ["ToolContext", "dispatch_tool"]

log = logging.getLogger(__name__)


_HANDLERS: dict[str, Callable[..., Awaitable[dict[str, Any]]]] = {
    "get_wantlist": get_wantlist,
    "get_user_settings": get_user_settings,
    "get_listings_for_release": get_listings_for_release,
    "summarize_marketplace_coverage": summarize_marketplace_coverage,
    "request_opportunistic_refresh": request_opportunistic_refresh,
    "compute_bundles": compute_bundles,
    "explain_bundle": explain_bundle,
    "save_report": save_report,
    "propose_tier_changes": propose_tier_changes,
}


async def dispatch_tool(name: str, args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Run the named tool with ``args``, returning its result dict or an ``{"error": ...}`` dict.

    Errors are returned (not raised) so the agent loop can feed them back to the
    model as a tool_result and let it self-correct.
    """
    handler = _HANDLERS.get(name)
    if handler is None:
        return {"error": f"unknown tool: {name}"}
    try:
        return await handler(ctx=ctx, **args)
    except TypeError as exc:
        return {"error": f"bad arguments to {name}: {exc}"}
    except Exception as exc:
        log.exception("🛠️ digger agent tool %s failed", name)
        return {"error": f"{name} failed: {exc!r}"}
