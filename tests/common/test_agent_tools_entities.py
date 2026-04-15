"""Tests for common.agent_tools.entities."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.mark.parametrize(
    "tool_name,entity_type",
    [
        ("get_artist_details", "artist"),
        ("get_label_details", "label"),
        ("get_genre_details", "genre"),
        ("get_style_details", "style"),
        ("get_release_details", "release"),
    ],
)
@pytest.mark.asyncio
async def test_entity_details_delegates_to_handler(tool_name: str, entity_type: str) -> None:
    import common.agent_tools.entities as entities

    driver = AsyncMock()
    handler = AsyncMock(return_value={"id": "1", "name": "Example"})
    tool = getattr(entities, tool_name)

    result = await tool(driver=driver, name="Example", handler=handler)
    assert result == {"id": "1", "name": "Example", "_entity_type": entity_type}
    handler.assert_awaited_once_with(driver, "Example")


@pytest.mark.asyncio
async def test_entity_details_returns_error_when_not_found() -> None:
    from common.agent_tools.entities import get_artist_details

    driver = AsyncMock()
    handler = AsyncMock(return_value=None)
    result = await get_artist_details(driver=driver, name="Nobody", handler=handler)
    assert result == {"error": "artist 'Nobody' not found"}
