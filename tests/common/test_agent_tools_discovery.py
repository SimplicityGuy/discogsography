"""Tests for common.agent_tools.discovery (search, collaborators, trends)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_search_delegates() -> None:
    from common.agent_tools.discovery import search

    executor = AsyncMock(return_value={"results": [{"id": "1", "name": "Kraftwerk"}]})
    result = await search(
        pool=object(),
        redis=object(),
        q="Kraftwerk",
        types=["artist"],
        genres=[],
        year_min=None,
        year_max=None,
        limit=5,
        offset=0,
        search_fn=executor,
    )
    assert result == {"results": [{"id": "1", "name": "Kraftwerk"}]}
    executor.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_collaborators_wraps_list() -> None:
    from common.agent_tools.discovery import get_collaborators

    fn = AsyncMock(return_value=[{"id": "2"}])
    result = await get_collaborators(driver=object(), artist_id="1", limit=10, collaborators_fn=fn)
    assert result == {"collaborators": [{"id": "2"}]}


@pytest.mark.asyncio
async def test_get_trends_dispatches_by_type() -> None:
    from common.agent_tools.discovery import get_trends

    handler = AsyncMock(return_value=[{"year": 2025, "count": 10}])
    result = await get_trends(
        driver=object(),
        entity_type="artist",
        name="Kraftwerk",
        handler=handler,
    )
    assert result == {"trends": [{"year": 2025, "count": 10}]}


@pytest.mark.asyncio
async def test_get_trends_missing_handler_errors() -> None:
    from common.agent_tools.discovery import get_trends

    result = await get_trends(
        driver=object(),
        entity_type="artist",
        name="Kraftwerk",
        handler=None,
    )
    assert result == {"error": "Unknown trends type: artist"}
