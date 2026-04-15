"""Tests for common.agent_tools.graph."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_find_path_resolves_names_and_returns_path() -> None:
    from common.agent_tools.graph import find_path

    driver = AsyncMock()
    resolve_name = AsyncMock(side_effect=[{"id": "42"}, {"id": "99"}])
    find_shortest_path = AsyncMock(return_value={"path": [42, 99], "length": 1})

    result = await find_path(
        driver=driver,
        from_name="Kraftwerk",
        from_type="artist",
        to_name="Afrika Bambaataa",
        to_type="artist",
        max_depth=6,
        resolve_name=resolve_name,
        find_shortest_path_fn=find_shortest_path,
    )

    assert result == {"path": [42, 99], "length": 1}
    assert resolve_name.await_count == 2
    find_shortest_path.assert_awaited_once_with(
        driver=driver,
        from_id="42",
        to_id="99",
        max_depth=6,
        from_type="artist",
        to_type="artist",
    )


@pytest.mark.asyncio
async def test_find_path_returns_error_when_source_missing() -> None:
    from common.agent_tools.graph import find_path

    driver = AsyncMock()
    resolve_name = AsyncMock(return_value=None)
    find_shortest_path = AsyncMock()

    result = await find_path(
        driver=driver,
        from_name="Nobody",
        from_type="artist",
        to_name="Kraftwerk",
        to_type="artist",
        resolve_name=resolve_name,
        find_shortest_path_fn=find_shortest_path,
    )

    assert result == {"error": "artist 'Nobody' not found"}
    find_shortest_path.assert_not_awaited()
