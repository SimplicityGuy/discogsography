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
