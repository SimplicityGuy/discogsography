"""Tests that NLQToolRunner delegates to common.agent_tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_handle_find_path_delegates_to_shared_tool() -> None:
    from api.nlq.tools import NLQToolRunner

    runner = NLQToolRunner(neo4j_driver=object(), pg_pool=object(), redis=object())

    with patch("common.agent_tools.find_path", new=AsyncMock(return_value={"path": [1, 2]})) as mock_shared:
        result = await runner._handle_find_path(
            {"from_id": "Kraftwerk", "to_id": "Bambaataa", "from_type": "artist", "to_type": "artist"},
            None,
        )

    assert result == {"path": [1, 2]}
    mock_shared.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_explore_entity_delegates() -> None:
    from api.nlq.tools import NLQToolRunner

    runner = NLQToolRunner(neo4j_driver=object(), pg_pool=object(), redis=object())

    with patch(
        "common.agent_tools.get_artist_details",
        new=AsyncMock(return_value={"id": "1", "name": "Kraftwerk", "_entity_type": "artist"}),
    ) as mock:
        result = await runner._handle_explore_entity({"type": "artist", "name": "Kraftwerk"}, None)

    assert result["name"] == "Kraftwerk"
    mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_get_collaborators_delegates() -> None:
    from api.nlq.tools import NLQToolRunner

    runner = NLQToolRunner(neo4j_driver=object(), pg_pool=object(), redis=object())

    with patch(
        "common.agent_tools.get_collaborators",
        new=AsyncMock(return_value={"collaborators": [{"id": "2"}]}),
    ) as mock:
        result = await runner._handle_get_collaborators({"artist_id": "1", "limit": 10}, None)

    assert result == {"collaborators": [{"id": "2"}]}
    mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_get_trends_delegates() -> None:
    from api.nlq.tools import NLQToolRunner

    runner = NLQToolRunner(neo4j_driver=object(), pg_pool=object(), redis=object())

    with patch(
        "common.agent_tools.get_trends",
        new=AsyncMock(return_value={"trends": []}),
    ) as mock:
        result = await runner._handle_get_trends({"type": "artist", "name": "Kraftwerk"}, None)

    assert result == {"trends": []}
    mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_get_graph_stats_delegates() -> None:
    from api.nlq.tools import NLQToolRunner

    runner = NLQToolRunner(neo4j_driver=object(), pg_pool=object(), redis=object())

    with patch(
        "common.agent_tools.get_graph_stats",
        new=AsyncMock(return_value={"artists": 100}),
    ) as mock:
        result = await runner._handle_get_graph_stats({}, None)

    assert result == {"artists": 100}
    mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_get_genre_tree_delegates() -> None:
    from api.nlq.tools import NLQToolRunner

    runner = NLQToolRunner(neo4j_driver=object(), pg_pool=object(), redis=object())

    with patch(
        "common.agent_tools.get_genre_tree",
        new=AsyncMock(return_value={"genres": []}),
    ) as mock:
        result = await runner._handle_get_genre_tree({}, None)

    assert result == {"genres": []}
    mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_search_delegates() -> None:
    from api.nlq.tools import NLQToolRunner

    runner = NLQToolRunner(neo4j_driver=object(), pg_pool=object(), redis=object())

    with patch(
        "common.agent_tools.search",
        new=AsyncMock(return_value={"results": []}),
    ) as mock:
        result = await runner._handle_search({"q": "Kraftwerk"}, None)

    assert result == {"results": []}
    mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_explore_entity_no_dispatch_handler_returns_error() -> None:
    """_handle_explore_entity returns error when EXPLORE_DISPATCH has no handler (first guard)."""

    from api.nlq.tools import NLQToolRunner

    runner = NLQToolRunner(neo4j_driver=object(), pg_pool=object(), redis=object())

    with patch("api.queries.neo4j_queries.EXPLORE_DISPATCH", new={}):
        result = await runner._handle_explore_entity({"type": "unknown_type", "name": "x"}, None)

    assert "error" in result
    assert "unknown_type" in result["error"]


@pytest.mark.asyncio
async def test_handle_explore_entity_dispatch_has_type_but_no_tool_fn() -> None:
    """_handle_explore_entity returns error when EXPLORE_DISPATCH has the type but tool_fn dict does not (line 375)."""
    from unittest.mock import MagicMock

    from api.nlq.tools import NLQToolRunner

    runner = NLQToolRunner(neo4j_driver=object(), pg_pool=object(), redis=object())

    # EXPLORE_DISPATCH has "exotic_type" so handler is not None, but the tool_fn dict doesn't include it
    with patch("api.queries.neo4j_queries.EXPLORE_DISPATCH", new={"exotic_type": MagicMock()}):
        result = await runner._handle_explore_entity({"type": "exotic_type", "name": "x"}, None)

    assert "error" in result
    assert "exotic_type" in result["error"]


@pytest.mark.asyncio
async def test_handle_find_path_resolve_name_returns_none_for_unknown_entity_type() -> None:
    """resolve_name inside _handle_find_path returns None when EXPLORE_DISPATCH has no handler."""
    from api.nlq.tools import NLQToolRunner

    runner = NLQToolRunner(neo4j_driver=object(), pg_pool=object(), redis=object())

    resolve_name_results: list[object] = []

    async def capture_resolve_name(**kwargs: object) -> dict[str, object]:
        """Intercept find_path and invoke resolve_name to exercise the None-return branch."""
        resolve_fn = kwargs.get("resolve_name")
        if callable(resolve_fn):
            result = await resolve_fn(None, "X", "unknown_entity")
            resolve_name_results.append(result)
        return {"path": []}

    with (
        patch("api.queries.neo4j_queries.EXPLORE_DISPATCH", new={}),
        patch("api.queries.neo4j_queries.find_shortest_path", new=AsyncMock(return_value=[])),
        patch("common.agent_tools.find_path", new=AsyncMock(side_effect=capture_resolve_name)),
    ):
        await runner._handle_find_path(
            {"from_id": "X", "to_id": "Y", "from_type": "unknown_entity", "to_type": "unknown_entity"},
            None,
        )

    # resolve_name should have returned None for the unknown entity type
    assert len(resolve_name_results) >= 1
    assert resolve_name_results[0] is None
