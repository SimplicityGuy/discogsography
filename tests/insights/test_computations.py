"""Tests for insights computation orchestration."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_failing_pool() -> AsyncMock:
    """Create a mock pool whose cursor.execute raises on the first call."""
    mock_cursor = AsyncMock()
    mock_cursor.execute = AsyncMock(side_effect=RuntimeError("DB error"))
    mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor.__aexit__ = AsyncMock(return_value=False)

    mock_conn = AsyncMock()
    mock_conn.cursor = MagicMock(return_value=mock_cursor)
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)

    mock_pool = AsyncMock()
    mock_pool.connection = MagicMock(return_value=mock_conn)
    return mock_pool


def _make_mock_pool() -> AsyncMock:
    """Create a mock pool for storing results."""
    mock_cursor = AsyncMock()
    mock_cursor.execute = AsyncMock()
    mock_cursor.fetchone = AsyncMock(return_value=(1,))

    mock_conn = AsyncMock()
    mock_conn.cursor = MagicMock(return_value=mock_cursor)
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)
    mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor.__aexit__ = AsyncMock(return_value=False)

    mock_pool = AsyncMock()
    mock_pool.connection = MagicMock(return_value=mock_conn)
    return mock_pool


class TestFetchFromApi:
    @pytest.mark.asyncio
    async def test_basic_call_without_params_or_timeout(self) -> None:
        from insights.computations import _fetch_from_api

        mock_response = MagicMock()
        mock_response.json.return_value = {"items": [{"id": 1}]}
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        result = await _fetch_from_api(mock_client, "/api/test")

        mock_client.get.assert_called_once_with("/api/test")
        assert result == [{"id": 1}]

    @pytest.mark.asyncio
    async def test_passes_params_when_provided(self) -> None:
        from insights.computations import _fetch_from_api

        mock_response = MagicMock()
        mock_response.json.return_value = {"items": []}
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        await _fetch_from_api(mock_client, "/api/test", params={"limit": 10})

        mock_client.get.assert_called_once_with("/api/test", params={"limit": 10})

    @pytest.mark.asyncio
    async def test_passes_timeout_when_provided(self) -> None:
        from insights.computations import _fetch_from_api

        mock_response = MagicMock()
        mock_response.json.return_value = {"items": []}
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        await _fetch_from_api(mock_client, "/api/test", timeout=600.0)

        mock_client.get.assert_called_once_with("/api/test", timeout=600.0)

    @pytest.mark.asyncio
    async def test_passes_both_params_and_timeout(self) -> None:
        from insights.computations import _fetch_from_api

        mock_response = MagicMock()
        mock_response.json.return_value = {"items": [{"id": 1}]}
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        result = await _fetch_from_api(mock_client, "/api/test", params={"limit": 5}, timeout=600.0)

        mock_client.get.assert_called_once_with("/api/test", params={"limit": 5}, timeout=600.0)
        assert result == [{"id": 1}]

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_items_key(self) -> None:
        from insights.computations import _fetch_from_api

        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "something"}
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        result = await _fetch_from_api(mock_client, "/api/test")

        assert result == []


class TestComputeAndStoreArtistCentrality:
    @pytest.mark.asyncio
    async def test_fetches_from_api_and_stores_results(self) -> None:
        from insights.computations import compute_and_store_artist_centrality

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.return_value = [
                {"artist_id": "a1", "artist_name": "Artist One", "edge_count": 100},
            ]
            rows = await compute_and_store_artist_centrality(mock_client, mock_pool)

        assert rows == 1
        mock_fetch.assert_called_once_with(mock_client, "/api/internal/insights/artist-centrality", {"limit": 100})

    @pytest.mark.asyncio
    async def test_handles_empty_results(self) -> None:
        from insights.computations import compute_and_store_artist_centrality

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.return_value = []
            rows = await compute_and_store_artist_centrality(mock_client, mock_pool)

        assert rows == 0

    @pytest.mark.asyncio
    async def test_filters_out_null_artist_names(self) -> None:
        from insights.computations import compute_and_store_artist_centrality

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.return_value = [
                {"artist_id": "a1", "artist_name": "Artist One", "edge_count": 100},
                {"artist_id": "a2", "artist_name": None, "edge_count": 90},
                {"artist_id": "a3", "artist_name": "", "edge_count": 80},
                {"artist_id": "a4", "artist_name": "Artist Four", "edge_count": 70},
            ]
            rows = await compute_and_store_artist_centrality(mock_client, mock_pool)

        assert rows == 2

    @pytest.mark.asyncio
    async def test_all_results_filtered_returns_zero(self) -> None:
        from insights.computations import compute_and_store_artist_centrality

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            # All results have None or empty names — should return 0 after filtering
            mock_fetch.return_value = [
                {"artist_id": "a1", "artist_name": None, "edge_count": 100},
                {"artist_id": "a2", "artist_name": "", "edge_count": 90},
            ]
            rows = await compute_and_store_artist_centrality(mock_client, mock_pool)

        assert rows == 0

    @pytest.mark.asyncio
    async def test_raises_on_api_error(self) -> None:
        from insights.computations import compute_and_store_artist_centrality

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.side_effect = RuntimeError("API unavailable")
            with pytest.raises(RuntimeError, match="API unavailable"):
                await compute_and_store_artist_centrality(mock_client, mock_pool)


class TestComputeAndStoreGenreTrends:
    @pytest.mark.asyncio
    async def test_fetches_and_stores(self) -> None:
        from insights.computations import compute_and_store_genre_trends

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.return_value = [
                {"genre": "Rock", "decade": 1990, "release_count": 5000},
            ]
            rows = await compute_and_store_genre_trends(mock_client, mock_pool)

        assert rows == 1

    @pytest.mark.asyncio
    async def test_handles_empty_results(self) -> None:
        from insights.computations import compute_and_store_genre_trends

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.return_value = []
            rows = await compute_and_store_genre_trends(mock_client, mock_pool)

        assert rows == 0

    @pytest.mark.asyncio
    async def test_raises_on_api_error(self) -> None:
        from insights.computations import compute_and_store_genre_trends

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.side_effect = RuntimeError("API unavailable")
            with pytest.raises(RuntimeError, match="API unavailable"):
                await compute_and_store_genre_trends(mock_client, mock_pool)


class TestComputeAndStoreLabelLongevity:
    @pytest.mark.asyncio
    async def test_fetches_and_stores(self) -> None:
        from insights.computations import compute_and_store_label_longevity

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.return_value = [
                {
                    "label_id": "l1",
                    "label_name": "Blue Note",
                    "first_year": 1939,
                    "last_year": 2025,
                    "years_active": 86,
                    "total_releases": 4500,
                    "peak_decade": 1960,
                },
            ]
            rows = await compute_and_store_label_longevity(mock_client, mock_pool)

        assert rows == 1

    @pytest.mark.asyncio
    async def test_handles_empty_results(self) -> None:
        from insights.computations import compute_and_store_label_longevity

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.return_value = []
            rows = await compute_and_store_label_longevity(mock_client, mock_pool)

        assert rows == 0

    @pytest.mark.asyncio
    async def test_raises_on_api_error(self) -> None:
        from insights.computations import compute_and_store_label_longevity

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.side_effect = RuntimeError("API unavailable")
            with pytest.raises(RuntimeError, match="API unavailable"):
                await compute_and_store_label_longevity(mock_client, mock_pool)


class TestComputeAndStoreAnniversaries:
    @pytest.mark.asyncio
    async def test_handles_empty_results(self) -> None:
        from insights.computations import compute_and_store_anniversaries

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.return_value = []
            rows = await compute_and_store_anniversaries(mock_client, mock_pool, current_year=2026, current_month=3)

        assert rows == 0

    @pytest.mark.asyncio
    async def test_raises_on_api_error(self) -> None:
        from insights.computations import compute_and_store_anniversaries

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.side_effect = RuntimeError("API unavailable")
            with pytest.raises(RuntimeError, match="API unavailable"):
                await compute_and_store_anniversaries(mock_client, mock_pool, current_year=2026, current_month=3)

    @pytest.mark.asyncio
    async def test_fetches_and_stores(self) -> None:
        from insights.computations import compute_and_store_anniversaries

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.return_value = [
                {"master_id": "m1", "title": "OK Computer", "artist_name": "Radiohead", "release_year": 1997},
            ]
            rows = await compute_and_store_anniversaries(mock_client, mock_pool, current_year=2022, current_month=6)

        # 2022-1997=25, which IS in milestone_years, so 1 row written
        assert rows == 1

    @pytest.mark.asyncio
    async def test_custom_milestone_years_passed_to_api(self) -> None:
        from insights.computations import compute_and_store_anniversaries

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()
        custom_milestones = [10, 20]

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.return_value = [
                {"master_id": "m1", "title": "Album", "artist_name": "Artist", "release_year": 2006},
            ]
            rows = await compute_and_store_anniversaries(
                mock_client,
                mock_pool,
                current_year=2026,
                current_month=3,
                milestone_years=custom_milestones,
            )

        # Verify milestones were passed to the API call
        mock_fetch.assert_called_once_with(
            mock_client,
            "/api/internal/insights/anniversaries",
            {"year": 2026, "month": 3, "milestones": "10,20"},
        )
        # 2026-2006=20, which IS in custom_milestones
        assert rows == 1

    @pytest.mark.asyncio
    async def test_custom_milestone_years_filters_results(self) -> None:
        from insights.computations import compute_and_store_anniversaries

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.return_value = [
                {"master_id": "m1", "title": "Album", "artist_name": "Artist", "release_year": 2016},
            ]
            # 2026-2016=10, but milestone_years=[20] so should NOT be stored
            rows = await compute_and_store_anniversaries(
                mock_client,
                mock_pool,
                current_year=2026,
                current_month=3,
                milestone_years=[20],
            )

        assert rows == 0


class TestComputeAndStoreDataCompleteness:
    @pytest.mark.asyncio
    async def test_fetches_and_stores(self) -> None:
        from insights.computations import compute_and_store_data_completeness

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.return_value = [
                {
                    "entity_type": "releases",
                    "total_count": 15000000,
                    "with_image": 12000000,
                    "with_year": 14500000,
                    "with_country": 13000000,
                    "with_genre": 14000000,
                    "completeness_pct": 89.67,
                },
            ]
            rows = await compute_and_store_data_completeness(mock_client, mock_pool)

        assert rows == 1

    @pytest.mark.asyncio
    async def test_handles_empty_results(self) -> None:
        from insights.computations import compute_and_store_data_completeness

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.return_value = []
            rows = await compute_and_store_data_completeness(mock_client, mock_pool)

        assert rows == 0

    @pytest.mark.asyncio
    async def test_raises_on_api_error(self) -> None:
        from insights.computations import compute_and_store_data_completeness

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.side_effect = RuntimeError("DB error")
            with pytest.raises(RuntimeError, match="DB error"):
                await compute_and_store_data_completeness(mock_client, mock_pool)


class TestLogComputationFailureDuringError:
    """Test that when _log_computation raises, the original exception still propagates."""

    @pytest.mark.asyncio
    async def test_original_exception_propagates_when_log_computation_fails(self) -> None:
        """When _fetch_from_api raises and _log_computation also raises, the original error propagates."""
        from insights.computations import compute_and_store_artist_centrality

        mock_client = AsyncMock()
        # Create a pool where _log_computation will fail (cursor.execute raises)
        mock_cursor = AsyncMock()
        mock_cursor.execute = AsyncMock(side_effect=RuntimeError("DB log write failed"))
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=False)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        mock_pool = AsyncMock()
        mock_pool.connection = MagicMock(return_value=mock_conn)

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.side_effect = RuntimeError("API unavailable")
            with pytest.raises(RuntimeError, match="API unavailable"):
                await compute_and_store_artist_centrality(mock_client, mock_pool)

    @pytest.mark.asyncio
    async def test_genre_trends_original_exception_propagates_when_log_fails(self) -> None:
        """Genre trends: original exception propagates even when _log_computation raises."""
        from insights.computations import compute_and_store_genre_trends

        mock_client = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.execute = AsyncMock(side_effect=RuntimeError("DB log write failed"))
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=False)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        mock_pool = AsyncMock()
        mock_pool.connection = MagicMock(return_value=mock_conn)

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.side_effect = RuntimeError("API down")
            with pytest.raises(RuntimeError, match="API down"):
                await compute_and_store_genre_trends(mock_client, mock_pool)


class TestRunAllComputations:
    @pytest.mark.asyncio
    async def test_runs_all_five(self) -> None:
        from insights.computations import run_all_computations

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with (
            patch("insights.computations.compute_and_store_artist_centrality", return_value=10),
            patch("insights.computations.compute_and_store_genre_trends", return_value=20),
            patch("insights.computations.compute_and_store_label_longevity", return_value=5),
            patch("insights.computations.compute_and_store_anniversaries", return_value=3),
            patch("insights.computations.compute_and_store_data_completeness", return_value=4),
            patch("insights.computations.compute_and_store_rarity", return_value=7),
        ):
            results = await run_all_computations(mock_client, mock_pool)

        assert results["artist_centrality"] == 10
        assert results["genre_trends"] == 20
        assert results["label_longevity"] == 5
        assert results["anniversaries"] == 3
        assert results["data_completeness"] == 4
        assert results["release_rarity"] == 7

    @pytest.mark.asyncio
    async def test_passes_milestone_years_to_anniversaries(self) -> None:
        from insights.computations import run_all_computations

        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()
        custom_milestones = [10, 50]

        with (
            patch("insights.computations.compute_and_store_artist_centrality", return_value=0),
            patch("insights.computations.compute_and_store_genre_trends", return_value=0),
            patch("insights.computations.compute_and_store_label_longevity", return_value=0),
            patch("insights.computations.compute_and_store_anniversaries", return_value=0) as mock_anniv,
            patch("insights.computations.compute_and_store_data_completeness", return_value=0),
            patch("insights.computations.compute_and_store_rarity", return_value=0),
        ):
            await run_all_computations(mock_client, mock_pool, milestone_years=custom_milestones)

        mock_anniv.assert_called_once_with(mock_client, mock_pool, milestone_years=custom_milestones)
