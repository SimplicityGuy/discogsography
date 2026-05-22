"""MCP tools for the Digger record-hunting agent.

These delegate to the authenticated ``/api/digger/*`` endpoints over HTTP. Unlike
the public knowledge-graph tools, every Digger endpoint requires a per-user JWT —
supplied via the ``MCP_API_TOKEN`` env var and carried on ``AppContext.api_token``.
When no token is configured the tools return a clear error instead of a 401.

The interactive recommendation is an SSE endpoint; rather than handing raw event
text to the MCP client, ``_collect_recommendation`` consumes the stream and
returns the final ``result`` payload (the optimizer output) as JSON.
"""

import json
from typing import Any

import httpx
from mcp.server.fastmcp import Context, FastMCP
import structlog


logger = structlog.get_logger(__name__)

DIGGER_TOOL_NAMES = {
    "digger_get_wantlist_status",
    "digger_run_recommendation",
    "digger_explain_bundle",
    "digger_simulate_what_if",
}


def _app(ctx: Context) -> Any:
    """Extract the typed lifespan context (AppContext) from an MCP Context."""
    return ctx.request_context.lifespan_context


def _auth_headers(app: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {app.api_token}"}


def _no_token_error() -> dict[str, Any]:
    return {"error": "MCP_API_TOKEN is not configured; Digger tools require a per-user API token"}


async def _digger_get(app: Any, path: str) -> dict[str, Any]:
    """Authenticated GET against the Digger API, returning parsed JSON or an error dict."""
    url = f"{app.base_url}{path}"
    try:
        resp = await app.client.get(url, headers=_auth_headers(app))
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]
    except httpx.HTTPStatusError as exc:
        logger.error("Digger API HTTP error", url=url, status=exc.response.status_code)
        return {"error": f"API returned HTTP {exc.response.status_code}", "url": url}
    except Exception as exc:
        logger.error("Digger API request failed", url=url, error=str(exc))
        return {"error": f"API request failed: {exc}", "url": url}


async def _collect_recommendation(app: Any, body: dict[str, Any]) -> dict[str, Any]:
    """Stream POST /api/digger/recommend and return the final ``result`` payload.

    Returns the optimizer output dict, an ``error`` dict if the stream emits an
    error event, or an ``error`` dict if the request fails / yields no result.
    """
    url = f"{app.base_url}/api/digger/recommend"
    headers = {**_auth_headers(app), "accept": "text/event-stream"}
    result: dict[str, Any] | None = None
    try:
        async with app.client.stream("POST", url, json=body, headers=headers) as resp:
            resp.raise_for_status()
            event: str | None = None
            async for line in resp.aiter_lines():
                if line.startswith("event:"):
                    event = line[len("event:") :].strip()
                elif line.startswith("data:") and event:
                    data = line[len("data:") :].strip()
                    if event == "result":
                        result = json.loads(data)
                    elif event == "error":
                        return {"error": json.loads(data).get("reason", "recommendation failed")}
                    event = None
    except httpx.HTTPStatusError as exc:
        logger.error("Digger recommend HTTP error", url=url, status=exc.response.status_code)
        return {"error": f"API returned HTTP {exc.response.status_code}", "url": url}
    except Exception as exc:
        logger.error("Digger recommend request failed", url=url, error=str(exc))
        return {"error": f"API request failed: {exc}", "url": url}
    if result is None:
        return {"error": "no recommendation produced"}
    return result


async def digger_get_wantlist_status(ctx: Context = None) -> dict[str, Any]:  # type: ignore[assignment]
    """Summarize the user's Digger wantlist and current marketplace coverage.

    Returns each wantlist release with its tier, condition/price constraints, and
    the count of active marketplace listings found for it.
    """
    app = _app(ctx)
    if not app.api_token:
        return _no_token_error()
    return await _digger_get(app, "/api/digger/wantlist")


async def digger_run_recommendation(
    budget_cap_cents: int | None = None,
    ctx: Context = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Run the deterministic optimizer over fresh listings and return bundles.

    Returns up to four named Pareto bundles (cheapest, most_coverage,
    best_quality, fewest_sellers) plus a watching list and shipping confidence.

    Args:
        budget_cap_cents: Optional spend ceiling in cents (e.g. 20000 for $200).
    """
    app = _app(ctx)
    if not app.api_token:
        return _no_token_error()
    body: dict[str, Any] = {"deadline_seconds": 30, "budget_cap_cents": budget_cap_cents, "excluded_sellers": []}
    return await _collect_recommendation(app, body)


async def digger_explain_bundle(
    report_id: str,
    bundle_name: str,
    ctx: Context = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Return the itemized breakdown of one named bundle from a saved report.

    Args:
        report_id: The report UUID (from the reports inbox).
        bundle_name: One of cheapest, most_coverage, best_quality, fewest_sellers.
    """
    app = _app(ctx)
    if not app.api_token:
        return _no_token_error()
    report = await _digger_get(app, f"/api/digger/reports/{report_id}")
    if "error" in report:
        return report
    bundle = next((b for b in report.get("bundles", []) if b.get("name") == bundle_name), None)
    if bundle is None:
        return {"error": f"bundle {bundle_name!r} not found in report {report_id}"}
    return bundle  # type: ignore[no-any-return]


async def digger_simulate_what_if(
    budget_cap_cents: int | None = None,
    excluded_sellers: list[int] | None = None,
    ctx: Context = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Run a what-if recommendation with alternate budget / excluded sellers.

    Re-runs the optimizer over the current wantlist with the supplied
    constraints so you can compare against an earlier result.

    Args:
        budget_cap_cents: Optional spend ceiling in cents.
        excluded_sellers: Optional list of seller IDs to exclude.
    """
    app = _app(ctx)
    if not app.api_token:
        return _no_token_error()
    body: dict[str, Any] = {
        "deadline_seconds": 20,
        "budget_cap_cents": budget_cap_cents,
        "excluded_sellers": excluded_sellers or [],
    }
    return await _collect_recommendation(app, body)


_DIGGER_TOOLS = (
    digger_get_wantlist_status,
    digger_run_recommendation,
    digger_explain_bundle,
    digger_simulate_what_if,
)


def register_digger_tools(mcp: FastMCP) -> None:
    """Register the Digger tools on the given FastMCP instance."""
    for fn in _DIGGER_TOOLS:
        mcp.tool()(fn)
