"""Tests for common.agent_tools.stats (graph_stats, genre_tree)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_get_graph_stats_delegates() -> None:
    from common.agent_tools.stats import get_graph_stats

    fn = AsyncMock(return_value={"artists": 100, "labels": 50})
    result = await get_graph_stats(driver=object(), stats_fn=fn)
    assert result == {"artists": 100, "labels": 50}


@pytest.mark.asyncio
async def test_get_genre_tree_wraps_list() -> None:
    from common.agent_tools.stats import get_genre_tree

    fn = AsyncMock(return_value=[{"name": "Electronic", "children": []}])
    result = await get_genre_tree(driver=object(), tree_fn=fn)
    assert result == {"genres": [{"name": "Electronic", "children": []}]}
