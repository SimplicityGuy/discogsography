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
