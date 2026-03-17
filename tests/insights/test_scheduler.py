"""Tests for the insights scheduler loop."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest


class TestSchedulerLoop:
    @pytest.mark.asyncio
    async def test_runs_computations_then_sleeps(self) -> None:
        from insights.insights import _scheduler_loop

        mock_client = AsyncMock()
        mock_pool = AsyncMock()
        call_count = 0

        async def mock_run_all(_client: object, _pool: object, **_kwargs: object) -> dict[str, int]:
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
            await _scheduler_loop(mock_client, mock_pool, interval_hours=1)

        assert call_count == 2
        mock_sleep.assert_called_with(3600)

    @pytest.mark.asyncio
    async def test_continues_on_computation_error(self) -> None:
        from insights.insights import _scheduler_loop

        mock_client = AsyncMock()
        mock_pool = AsyncMock()
        call_count = 0

        async def mock_run_all(_client: object, _pool: object, **_kwargs: object) -> dict[str, int]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("API unavailable")
            raise asyncio.CancelledError

        with (
            patch("insights.insights.run_all_computations", side_effect=mock_run_all),
            patch("asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(asyncio.CancelledError),
        ):
            await _scheduler_loop(mock_client, mock_pool, interval_hours=1)

        assert call_count == 2

    @pytest.mark.asyncio
    async def test_invalidates_cache_after_computation(self) -> None:
        from insights.insights import _scheduler_loop

        mock_client = AsyncMock()
        mock_pool = AsyncMock()
        mock_cache = AsyncMock()
        call_count = 0

        async def mock_run_all(_client: object, _pool: object, **_kwargs: object) -> dict[str, int]:
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError
            return {"test": 1}

        with (
            patch("insights.insights.run_all_computations", side_effect=mock_run_all),
            patch("asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(asyncio.CancelledError),
        ):
            await _scheduler_loop(mock_client, mock_pool, interval_hours=1, cache=mock_cache)

        mock_cache.invalidate_all.assert_called_once()
