"""Tests for the insights scheduler loop."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest


class TestSchedulerLoop:
    @pytest.mark.asyncio
    async def test_runs_computations_then_sleeps(self) -> None:
        from insights.insights import _scheduler_loop

        mock_driver = AsyncMock()
        mock_pool = AsyncMock()
        call_count = 0

        async def mock_run_all(_driver: object, _pool: object) -> dict[str, int]:
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError
            return {"test": 1}

        with (
            patch("insights.insights.run_all_computations", side_effect=mock_run_all),
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
            pytest.raises(asyncio.CancelledError),
        ):
            await _scheduler_loop(mock_driver, mock_pool, interval_hours=1)

        assert call_count == 2
        mock_sleep.assert_called_with(3600)

    @pytest.mark.asyncio
    async def test_continues_on_computation_error(self) -> None:
        from insights.insights import _scheduler_loop

        mock_driver = AsyncMock()
        mock_pool = AsyncMock()
        call_count = 0

        async def mock_run_all(_driver: object, _pool: object) -> dict[str, int]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Neo4j unavailable")
            raise asyncio.CancelledError

        with (
            patch("insights.insights.run_all_computations", side_effect=mock_run_all),
            patch("asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(asyncio.CancelledError),
        ):
            await _scheduler_loop(mock_driver, mock_pool, interval_hours=1)

        assert call_count == 2
