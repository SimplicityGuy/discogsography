"""Tests for insights computation orchestration."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


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


class TestComputeAndStoreArtistCentrality:
    @pytest.mark.asyncio
    async def test_queries_neo4j_and_stores_results(self) -> None:
        from insights.computations import compute_and_store_artist_centrality

        mock_driver = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations.query_artist_centrality") as mock_query:
            mock_query.return_value = [
                {"artist_id": "a1", "artist_name": "Artist One", "edge_count": 100},
            ]
            rows = await compute_and_store_artist_centrality(mock_driver, mock_pool)

        assert rows == 1
        mock_query.assert_called_once_with(mock_driver, limit=100)

    @pytest.mark.asyncio
    async def test_handles_empty_results(self) -> None:
        from insights.computations import compute_and_store_artist_centrality

        mock_driver = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations.query_artist_centrality") as mock_query:
            mock_query.return_value = []
            rows = await compute_and_store_artist_centrality(mock_driver, mock_pool)

        assert rows == 0


class TestComputeAndStoreGenreTrends:
    @pytest.mark.asyncio
    async def test_queries_and_stores(self) -> None:
        from insights.computations import compute_and_store_genre_trends

        mock_driver = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations.query_genre_trends") as mock_query:
            mock_query.return_value = [
                {"genre": "Rock", "decade": 1990, "release_count": 5000},
            ]
            rows = await compute_and_store_genre_trends(mock_driver, mock_pool)

        assert rows == 1


class TestComputeAndStoreLabelLongevity:
    @pytest.mark.asyncio
    async def test_queries_and_stores(self) -> None:
        from insights.computations import compute_and_store_label_longevity

        mock_driver = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations.query_label_longevity") as mock_query:
            mock_query.return_value = [
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
            rows = await compute_and_store_label_longevity(mock_driver, mock_pool)

        assert rows == 1


class TestComputeAndStoreAnniversaries:
    @pytest.mark.asyncio
    async def test_queries_and_stores(self) -> None:
        from insights.computations import compute_and_store_anniversaries

        mock_driver = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations.query_monthly_anniversaries") as mock_query:
            mock_query.return_value = [
                {"master_id": "m1", "title": "OK Computer", "artist_name": "Radiohead", "release_year": 1997},
            ]
            rows = await compute_and_store_anniversaries(mock_driver, mock_pool, current_year=2022, current_month=6)

        # 2022-1997=25, which IS in milestone_years, so 1 row written
        assert rows == 1

    @pytest.mark.asyncio
    async def test_custom_milestone_years_passed_to_query(self) -> None:
        from insights.computations import compute_and_store_anniversaries

        mock_driver = AsyncMock()
        mock_pool = _make_mock_pool()
        custom_milestones = [10, 20]

        with patch("insights.computations.query_monthly_anniversaries") as mock_query:
            mock_query.return_value = [
                {"master_id": "m1", "title": "Album", "artist_name": "Artist", "release_year": 2006},
            ]
            rows = await compute_and_store_anniversaries(
                mock_driver,
                mock_pool,
                current_year=2026,
                current_month=3,
                milestone_years=custom_milestones,
            )

        # Verify custom milestones were passed to the Neo4j query
        mock_query.assert_called_once_with(
            mock_driver,
            current_year=2026,
            current_month=3,
            milestone_years=custom_milestones,
        )
        # 2026-2006=20, which IS in custom_milestones
        assert rows == 1

    @pytest.mark.asyncio
    async def test_custom_milestone_years_filters_results(self) -> None:
        from insights.computations import compute_and_store_anniversaries

        mock_driver = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations.query_monthly_anniversaries") as mock_query:
            mock_query.return_value = [
                {"master_id": "m1", "title": "Album", "artist_name": "Artist", "release_year": 2016},
            ]
            # 2026-2016=10, but milestone_years=[20] so should NOT be stored
            rows = await compute_and_store_anniversaries(
                mock_driver,
                mock_pool,
                current_year=2026,
                current_month=3,
                milestone_years=[20],
            )

        assert rows == 0


class TestComputeAndStoreDataCompleteness:
    @pytest.mark.asyncio
    async def test_queries_and_stores(self) -> None:
        from insights.computations import compute_and_store_data_completeness

        mock_pool = _make_mock_pool()

        with patch("insights.computations.query_data_completeness") as mock_query:
            mock_query.return_value = [
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
            rows = await compute_and_store_data_completeness(mock_pool)

        assert rows == 1


class TestRunAllComputations:
    @pytest.mark.asyncio
    async def test_runs_all_five(self) -> None:
        from insights.computations import run_all_computations

        mock_driver = AsyncMock()
        mock_pool = _make_mock_pool()

        with (
            patch("insights.computations.compute_and_store_artist_centrality", return_value=10),
            patch("insights.computations.compute_and_store_genre_trends", return_value=20),
            patch("insights.computations.compute_and_store_label_longevity", return_value=5),
            patch("insights.computations.compute_and_store_anniversaries", return_value=3),
            patch("insights.computations.compute_and_store_data_completeness", return_value=4),
        ):
            results = await run_all_computations(mock_driver, mock_pool)

        assert results["artist_centrality"] == 10
        assert results["genre_trends"] == 20
        assert results["label_longevity"] == 5
        assert results["anniversaries"] == 3
        assert results["data_completeness"] == 4

    @pytest.mark.asyncio
    async def test_passes_milestone_years_to_anniversaries(self) -> None:
        from insights.computations import run_all_computations

        mock_driver = AsyncMock()
        mock_pool = _make_mock_pool()
        custom_milestones = [10, 50]

        with (
            patch("insights.computations.compute_and_store_artist_centrality", return_value=0),
            patch("insights.computations.compute_and_store_genre_trends", return_value=0),
            patch("insights.computations.compute_and_store_label_longevity", return_value=0),
            patch("insights.computations.compute_and_store_anniversaries", return_value=0) as mock_anniv,
            patch("insights.computations.compute_and_store_data_completeness", return_value=0),
        ):
            await run_all_computations(mock_driver, mock_pool, milestone_years=custom_milestones)

        mock_anniv.assert_called_once_with(mock_driver, mock_pool, milestone_years=custom_milestones)
