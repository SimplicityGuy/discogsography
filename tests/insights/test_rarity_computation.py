"""Tests for rarity score computation pipeline."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from insights.computations import compute_and_store_rarity


def _make_mock_pool() -> MagicMock:
    """Create mock pool with cursor for storing results."""
    mock_cursor = AsyncMock()
    mock_cursor.execute = AsyncMock()
    mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor.__aexit__ = AsyncMock(return_value=False)

    mock_conn = AsyncMock()
    mock_conn.cursor = MagicMock(return_value=mock_cursor)
    mock_tx_cm = AsyncMock()
    mock_tx_cm.__aenter__ = AsyncMock(return_value=None)
    mock_tx_cm.__aexit__ = AsyncMock(return_value=None)
    mock_conn.transaction = MagicMock(return_value=mock_tx_cm)
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)

    mock_pool = MagicMock()
    mock_pool.connection = MagicMock(return_value=mock_conn)
    return mock_pool


_MOCK_RARITY_ITEMS = [
    {
        "release_id": "1",
        "title": "Test Release",
        "artist_name": "Test Artist",
        "year": 1970,
        "rarity_score": 85.0,
        "tier": "ultra-rare",
        "hidden_gem_score": 60.0,
        "pressing_scarcity": 100.0,
        "label_catalog": 75.0,
        "format_rarity": 95.0,
        "temporal_scarcity": 80.0,
        "graph_isolation": 70.0,
        "collection_prevalence": 85.0,
    }
]


class TestComputeAndStoreRarity:
    @pytest.mark.asyncio
    async def test_fetches_and_stores(self) -> None:
        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.return_value = _MOCK_RARITY_ITEMS
            rows = await compute_and_store_rarity(mock_client, mock_pool)

        assert rows == 1
        mock_fetch.assert_called_once_with(
            mock_client,
            "/api/internal/insights/rarity-scores",
            timeout=600.0,
        )

    @pytest.mark.asyncio
    async def test_empty_results(self) -> None:
        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.return_value = []
            rows = await compute_and_store_rarity(mock_client, mock_pool)

        assert rows == 0

    @pytest.mark.asyncio
    async def test_logs_computation(self) -> None:
        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with (
            patch("insights.computations._fetch_from_api") as mock_fetch,
            patch("insights.computations._log_computation") as mock_log,
        ):
            mock_fetch.return_value = _MOCK_RARITY_ITEMS
            await compute_and_store_rarity(mock_client, mock_pool)

        mock_log.assert_called_once()
        args = mock_log.call_args
        assert args[0][1] == "release_rarity"
        assert args[0][2] == "completed"

    @pytest.mark.asyncio
    async def test_logs_failure(self) -> None:
        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with (
            patch("insights.computations._fetch_from_api", side_effect=RuntimeError("fail")),
            patch("insights.computations._log_computation") as mock_log,
            pytest.raises(RuntimeError),
        ):
            await compute_and_store_rarity(mock_client, mock_pool)

        mock_log.assert_called_once()
        args = mock_log.call_args
        assert args[0][2] == "failed"
