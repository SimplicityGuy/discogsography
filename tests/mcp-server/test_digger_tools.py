"""Tests for the MCP digger tools (mock-based, no live API).

The digger tools call authenticated /api/digger/* endpoints via httpx; the
recommend SSE stream is collected to its final ``result`` event. All HTTP is
mocked, mirroring tests/mcp-server/test_server.py.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from mcp_server.digger_tools import (
    DIGGER_TOOL_NAMES,
    digger_explain_bundle,
    digger_get_wantlist_status,
    digger_run_recommendation,
    digger_simulate_what_if,
    register_digger_tools,
)


@pytest.fixture()
def app_ctx():
    from mcp_server.server import AppContext

    client = MagicMock(spec=httpx.AsyncClient)
    return AppContext(client=client, base_url="http://test-api:8004", api_token="test-jwt")  # noqa: S106


@pytest.fixture()
def mock_context(app_ctx):
    ctx = MagicMock()
    ctx.request_context.lifespan_context = app_ctx
    return ctx


def _mock_response(json_data, status_code: int = 200):
    resp = MagicMock(spec=httpx.Response)
    resp.json.return_value = json_data
    resp.status_code = status_code
    return resp


class _FakeStreamResp:
    def __init__(self, lines, status: int = 200):
        self._lines = lines
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=httpx.Request("POST", "http://x"), response=httpx.Response(self.status_code))

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeStreamCM:
    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, *_a):
        return False


def _sse(*events):
    """Flatten (event, data) pairs into SSE wire lines."""
    out = []
    for event, data in events:
        out.append(f"event: {event}")
        out.append(f"data: {data}")
        out.append("")
    return out


# --- tool registration -----------------------------------------------------


def test_expected_tools_listed():
    assert {
        "digger_get_wantlist_status",
        "digger_run_recommendation",
        "digger_explain_bundle",
        "digger_simulate_what_if",
    } <= DIGGER_TOOL_NAMES


@pytest.mark.asyncio
async def test_register_adds_tools_to_mcp():
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("test")
    register_digger_tools(mcp)
    names = {t.name for t in await mcp.list_tools()}
    assert names >= DIGGER_TOOL_NAMES


# --- digger_get_wantlist_status --------------------------------------------


@pytest.mark.asyncio
async def test_get_wantlist_status_returns_json(mock_context, app_ctx):
    body = {"items": [{"release_id": 1, "tier": "must", "active_listings": 3}]}
    app_ctx.client.get = AsyncMock(return_value=_mock_response(body))
    result = await digger_get_wantlist_status(ctx=mock_context)
    assert result == body
    url, kwargs = app_ctx.client.get.call_args.args, app_ctx.client.get.call_args.kwargs
    assert "/api/digger/wantlist" in url[0]
    assert kwargs["headers"]["Authorization"] == "Bearer test-jwt"


@pytest.mark.asyncio
async def test_get_wantlist_status_requires_token(app_ctx):
    app_ctx.api_token = None
    app_ctx.client.get = AsyncMock()
    ctx = MagicMock()
    ctx.request_context.lifespan_context = app_ctx
    result = await digger_get_wantlist_status(ctx=ctx)
    assert "error" in result
    app_ctx.client.get.assert_not_called()


@pytest.mark.asyncio
async def test_get_wantlist_status_http_error(mock_context, app_ctx):
    app_ctx.client.get = AsyncMock(side_effect=httpx.HTTPStatusError("e", request=httpx.Request("GET", "http://x"), response=httpx.Response(401)))
    result = await digger_get_wantlist_status(ctx=mock_context)
    assert "error" in result


@pytest.mark.asyncio
async def test_get_wantlist_status_generic_exception(mock_context, app_ctx):
    app_ctx.client.get = AsyncMock(side_effect=httpx.ConnectError("network down"))
    result = await digger_get_wantlist_status(ctx=mock_context)
    assert "error" in result


# --- digger_run_recommendation ---------------------------------------------


@pytest.mark.asyncio
async def test_run_recommendation_collects_result(mock_context, app_ctx):
    out = {"bundles": [{"name": "cheapest"}], "watching": [], "shipping_confidence": "high"}
    lines = _sse(("refresh_started", '{"stale_count":0}'), ("result", json.dumps(out)), ("done", "{}"))
    app_ctx.client.stream = MagicMock(return_value=_FakeStreamCM(_FakeStreamResp(lines)))
    result = await digger_run_recommendation(budget_cap_cents=20000, ctx=mock_context)
    assert result == out
    # body carried the budget cap
    sent = app_ctx.client.stream.call_args.kwargs["json"]
    assert sent["budget_cap_cents"] == 20000


@pytest.mark.asyncio
async def test_run_recommendation_surfaces_error_event(mock_context, app_ctx):
    lines = _sse(("error", '{"reason":"digger not enabled"}'))
    app_ctx.client.stream = MagicMock(return_value=_FakeStreamCM(_FakeStreamResp(lines)))
    result = await digger_run_recommendation(ctx=mock_context)
    assert result["error"] == "digger not enabled"


@pytest.mark.asyncio
async def test_run_recommendation_no_result(mock_context, app_ctx):
    lines = _sse(("refresh_started", '{"stale_count":0}'), ("done", "{}"))
    app_ctx.client.stream = MagicMock(return_value=_FakeStreamCM(_FakeStreamResp(lines)))
    result = await digger_run_recommendation(ctx=mock_context)
    assert "error" in result


@pytest.mark.asyncio
async def test_run_recommendation_requires_token(app_ctx):
    app_ctx.api_token = None
    app_ctx.client.stream = MagicMock()
    ctx = MagicMock()
    ctx.request_context.lifespan_context = app_ctx
    result = await digger_run_recommendation(ctx=ctx)
    assert "error" in result
    app_ctx.client.stream.assert_not_called()


@pytest.mark.asyncio
async def test_run_recommendation_http_error(mock_context, app_ctx):
    app_ctx.client.stream = MagicMock(return_value=_FakeStreamCM(_FakeStreamResp([], status=401)))
    result = await digger_run_recommendation(ctx=mock_context)
    assert "error" in result


@pytest.mark.asyncio
async def test_run_recommendation_request_exception(mock_context, app_ctx):
    app_ctx.client.stream = MagicMock(side_effect=httpx.ConnectError("boom"))
    result = await digger_run_recommendation(ctx=mock_context)
    assert "error" in result


# --- digger_explain_bundle -------------------------------------------------


@pytest.mark.asyncio
async def test_explain_bundle_returns_matching_bundle(mock_context, app_ctx):
    report = {"bundles": [{"name": "cheapest", "grand_total_cents": 1500}, {"name": "best_quality"}]}
    app_ctx.client.get = AsyncMock(return_value=_mock_response(report))
    result = await digger_explain_bundle(report_id="r1", bundle_name="cheapest", ctx=mock_context)
    assert result["grand_total_cents"] == 1500


@pytest.mark.asyncio
async def test_explain_bundle_not_found(mock_context, app_ctx):
    report = {"bundles": [{"name": "cheapest"}]}
    app_ctx.client.get = AsyncMock(return_value=_mock_response(report))
    result = await digger_explain_bundle(report_id="r1", bundle_name="nope", ctx=mock_context)
    assert "error" in result


@pytest.mark.asyncio
async def test_explain_bundle_propagates_api_error(mock_context, app_ctx):
    app_ctx.client.get = AsyncMock(return_value=_mock_response({"error": "report not found"}, status_code=404))
    result = await digger_explain_bundle(report_id="missing", bundle_name="cheapest", ctx=mock_context)
    assert "error" in result


@pytest.mark.asyncio
async def test_explain_bundle_requires_token(app_ctx):
    app_ctx.api_token = None
    app_ctx.client.get = AsyncMock()
    ctx = MagicMock()
    ctx.request_context.lifespan_context = app_ctx
    result = await digger_explain_bundle(report_id="r1", bundle_name="cheapest", ctx=ctx)
    assert "error" in result
    app_ctx.client.get.assert_not_called()


# --- digger_simulate_what_if -----------------------------------------------


@pytest.mark.asyncio
async def test_simulate_what_if_passes_excluded_sellers(mock_context, app_ctx):
    out = {"bundles": [], "watching": [], "shipping_confidence": "low"}
    lines = _sse(("result", json.dumps(out)), ("done", "{}"))
    app_ctx.client.stream = MagicMock(return_value=_FakeStreamCM(_FakeStreamResp(lines)))
    result = await digger_simulate_what_if(budget_cap_cents=5000, excluded_sellers=[7, 9], ctx=mock_context)
    assert result == out
    sent = app_ctx.client.stream.call_args.kwargs["json"]
    assert sent["budget_cap_cents"] == 5000
    assert sent["excluded_sellers"] == [7, 9]


@pytest.mark.asyncio
async def test_simulate_what_if_requires_token(app_ctx):
    app_ctx.api_token = None
    app_ctx.client.stream = MagicMock()
    ctx = MagicMock()
    ctx.request_context.lifespan_context = app_ctx
    result = await digger_simulate_what_if(ctx=ctx)
    assert "error" in result
    app_ctx.client.stream.assert_not_called()


# --- app_lifespan wires the Digger token -----------------------------------


@pytest.mark.asyncio
async def test_app_lifespan_reads_mcp_api_token(monkeypatch):
    from mcp_server.server import AppContext, app_lifespan

    monkeypatch.setenv("MCP_API_TOKEN", "live-jwt")
    monkeypatch.setenv("API_BASE_URL", "http://api:8004")
    async with app_lifespan(MagicMock()) as ctx:
        assert isinstance(ctx, AppContext)
        assert ctx.api_token == "live-jwt"
        assert ctx.base_url == "http://api:8004"


@pytest.mark.asyncio
async def test_app_lifespan_token_none_when_unset(monkeypatch):
    from mcp_server.server import app_lifespan

    monkeypatch.delenv("MCP_API_TOKEN", raising=False)
    async with app_lifespan(MagicMock()) as ctx:
        assert ctx.api_token is None
