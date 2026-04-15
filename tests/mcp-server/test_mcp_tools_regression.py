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
