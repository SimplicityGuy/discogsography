"""Tests for MCP server nlq_query tool."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest


@pytest.fixture
def app_ctx():
    from mcp_server.server import AppContext

    client = MagicMock(spec=httpx.AsyncClient)
    return AppContext(client=client, base_url="http://test-api:8004")


@pytest.fixture
def mock_context(app_ctx):
    ctx = MagicMock()
    ctx.request_context.lifespan_context = app_ctx
    return ctx


def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.json.return_value = json_data
    resp.status_code = status_code
    return resp


class TestNLQQueryTool:
    @pytest.mark.asyncio
    async def test_nlq_query_sends_post_request(self, mock_context, app_ctx) -> None:
        from mcp_server.server import nlq_query

        fake_result = {
            "query": "Find Miles Davis",
            "summary": "Found Miles Davis in the database.",
            "entities": [{"id": "123", "name": "Miles Davis", "type": "artist"}],
            "tools_used": ["search"],
            "cached": False,
        }
        app_ctx.client.post = AsyncMock(return_value=_mock_response(fake_result))
        result = await nlq_query(query="Find Miles Davis", ctx=mock_context)
        assert result["summary"] == "Found Miles Davis in the database."
        app_ctx.client.post.assert_called_once()
        call_args = app_ctx.client.post.call_args
        assert "/api/nlq/query" in call_args.args[0]

    @pytest.mark.asyncio
    async def test_nlq_query_handles_503_disabled(self, mock_context, app_ctx) -> None:
        from mcp_server.server import nlq_query

        error_response = {"error": "Natural language queries are not enabled"}
        app_ctx.client.post = AsyncMock(return_value=_mock_response(error_response, 503))
        result = await nlq_query(query="test", ctx=mock_context)
        assert "error" in result
