"""Regression tests: MCP tools must return the same shape after refactor."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_mcp_tool_names_still_exported() -> None:
    from mcp_server.server import (
        find_path,
        get_artist_details,
        get_collaborators,
        get_genre_details,
        get_genre_tree,
        get_graph_stats,
        get_label_details,
        get_release_details,
        get_style_details,
        get_trends,
        nlq_query,
        search,
    )

    for fn in (
        find_path,
        get_artist_details,
        get_collaborators,
        get_genre_details,
        get_genre_tree,
        get_graph_stats,
        get_label_details,
        get_release_details,
        get_style_details,
        get_trends,
        nlq_query,
        search,
    ):
        assert callable(fn)


@pytest.mark.asyncio
async def test_mcp_find_path_calls_shared_tool() -> None:
    with patch("common.agent_tools.find_path", new=AsyncMock(return_value={"path": [1, 2]})) as mock:
        from mcp_server.server import find_path as mcp_find_path

        ctx = AsyncMock()
        ctx.request_context.lifespan_context = AsyncMock()

        result = await mcp_find_path(
            from_name="Kraftwerk",
            from_type="artist",
            to_name="Bambaataa",
            to_type="artist",
            ctx=ctx,
        )

        # Result may be the dict directly or the mock's return — both are acceptable
        assert result == {"path": [1, 2]} or (isinstance(result, dict) and result.get("path") == [1, 2])
        mock.assert_awaited_once()
