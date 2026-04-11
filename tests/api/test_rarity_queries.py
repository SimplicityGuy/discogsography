"""Tests for rarity scoring query functions."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.queries.rarity_queries import (
    SIGNAL_WEIGHTS,
    compute_collection_prevalence_score,
    compute_format_rarity_score,
    compute_graph_isolation_score,
    compute_label_catalog_score,
    compute_pressing_scarcity_score,
    compute_rarity_tier,
    compute_temporal_scarcity_score,
    fetch_all_rarity_signals,
    get_rarity_by_artist,
    get_rarity_by_label,
    get_rarity_for_release,
    get_rarity_hidden_gems,
    get_rarity_leaderboard,
)


# ── Pure scoring function tests ──────────────────────────────────────


class TestPressingScarcityScore:
    def test_single_pressing(self) -> None:
        assert compute_pressing_scarcity_score(1) == 100.0

    def test_two_pressings(self) -> None:
        assert compute_pressing_scarcity_score(2) == 85.0

    def test_three_to_five(self) -> None:
        assert compute_pressing_scarcity_score(3) == 60.0
        assert compute_pressing_scarcity_score(5) == 60.0

    def test_six_to_ten(self) -> None:
        assert compute_pressing_scarcity_score(6) == 35.0
        assert compute_pressing_scarcity_score(10) == 35.0

    def test_eleven_plus(self) -> None:
        assert compute_pressing_scarcity_score(11) == 10.0
        assert compute_pressing_scarcity_score(100) == 10.0

    def test_zero_standalone(self) -> None:
        assert compute_pressing_scarcity_score(0) == 90.0


class TestLabelCatalogScore:
    def test_tiny_label(self) -> None:
        assert compute_label_catalog_score(5) == 100.0

    def test_small_label(self) -> None:
        assert compute_label_catalog_score(25) == 75.0

    def test_medium_label(self) -> None:
        assert compute_label_catalog_score(100) == 50.0

    def test_large_label(self) -> None:
        assert compute_label_catalog_score(500) == 25.0

    def test_major_label(self) -> None:
        assert compute_label_catalog_score(5000) == 10.0

    def test_zero_catalog(self) -> None:
        assert compute_label_catalog_score(0) == 100.0


class TestFormatRarityScore:
    def test_test_pressing(self) -> None:
        assert compute_format_rarity_score(["Test Pressing"]) == 100.0

    def test_cd_only(self) -> None:
        assert compute_format_rarity_score(["CD"]) == 10.0

    def test_multiple_formats_takes_max(self) -> None:
        assert compute_format_rarity_score(["CD", "Flexi-disc"]) == 95.0

    def test_unknown_format(self) -> None:
        assert compute_format_rarity_score(["UnknownFormat"]) == 50.0

    def test_empty_formats(self) -> None:
        assert compute_format_rarity_score([]) == 50.0

    def test_none_in_list(self) -> None:
        assert compute_format_rarity_score([None, "LP"]) == 30.0


class TestTemporalScarcityScore:
    def test_old_no_reissue(self) -> None:
        current_year = datetime.now(UTC).year
        score = compute_temporal_scarcity_score(1960, None, current_year)
        expected = min(100.0, (current_year - 1960) * 1.5)
        assert score == expected

    def test_old_with_recent_reissue(self) -> None:
        current_year = datetime.now(UTC).year
        score = compute_temporal_scarcity_score(1960, current_year - 5, current_year)
        expected = max(0.0, min(100.0, (current_year - 1960) * 1.5) - 40.0)
        assert score == expected

    def test_recent_release(self) -> None:
        current_year = datetime.now(UTC).year
        score = compute_temporal_scarcity_score(current_year - 2, None, current_year)
        expected = min(100.0, 2 * 1.5)
        assert score == expected

    def test_no_year(self) -> None:
        current_year = datetime.now(UTC).year
        score = compute_temporal_scarcity_score(None, None, current_year)
        assert score == 50.0


class TestGraphIsolationScore:
    def test_very_isolated(self) -> None:
        assert compute_graph_isolation_score(1) == 90.0

    def test_somewhat_isolated(self) -> None:
        assert compute_graph_isolation_score(4) == 70.0

    def test_moderate(self) -> None:
        assert compute_graph_isolation_score(6) == 50.0

    def test_connected(self) -> None:
        assert compute_graph_isolation_score(10) == 30.0

    def test_highly_connected(self) -> None:
        assert compute_graph_isolation_score(20) == 10.0

    def test_zero_rels(self) -> None:
        assert compute_graph_isolation_score(0) == 90.0


class TestCollectionPrevalenceScore:
    def test_zero_have(self) -> None:
        assert compute_collection_prevalence_score(0, 0) == 95.0

    def test_very_few_have(self) -> None:
        assert compute_collection_prevalence_score(5, 0) == 85.0

    def test_few_have(self) -> None:
        assert compute_collection_prevalence_score(50, 0) == 70.0

    def test_moderate_have(self) -> None:
        assert compute_collection_prevalence_score(500, 0) == 50.0

    def test_many_have(self) -> None:
        assert compute_collection_prevalence_score(5000, 0) == 25.0

    def test_mass_market(self) -> None:
        assert compute_collection_prevalence_score(50000, 0) == 10.0

    def test_boundary_1_inclusive(self) -> None:
        assert compute_collection_prevalence_score(1, 0) == 85.0

    def test_boundary_10_inclusive(self) -> None:
        assert compute_collection_prevalence_score(10, 0) == 85.0

    def test_boundary_11(self) -> None:
        assert compute_collection_prevalence_score(11, 0) == 70.0

    def test_boundary_100_inclusive(self) -> None:
        assert compute_collection_prevalence_score(100, 0) == 70.0

    def test_boundary_101(self) -> None:
        assert compute_collection_prevalence_score(101, 0) == 50.0

    def test_boundary_1000_inclusive(self) -> None:
        assert compute_collection_prevalence_score(1000, 0) == 50.0

    def test_boundary_1001(self) -> None:
        assert compute_collection_prevalence_score(1001, 0) == 25.0

    def test_boundary_10000_inclusive(self) -> None:
        assert compute_collection_prevalence_score(10000, 0) == 25.0

    def test_boundary_10001(self) -> None:
        assert compute_collection_prevalence_score(10001, 0) == 10.0

    def test_want_bonus_applied(self) -> None:
        assert compute_collection_prevalence_score(50, 100) == 75.0

    def test_want_bonus_not_applied_when_want_lte_have(self) -> None:
        assert compute_collection_prevalence_score(50, 50) == 70.0
        assert compute_collection_prevalence_score(50, 30) == 70.0

    def test_want_bonus_capped_at_100(self) -> None:
        assert compute_collection_prevalence_score(0, 10) == 100.0


class TestRarityTier:
    def test_common(self) -> None:
        assert compute_rarity_tier(15.0) == "common"

    def test_uncommon(self) -> None:
        assert compute_rarity_tier(35.0) == "uncommon"

    def test_scarce(self) -> None:
        assert compute_rarity_tier(55.0) == "scarce"

    def test_rare(self) -> None:
        assert compute_rarity_tier(75.0) == "rare"

    def test_ultra_rare(self) -> None:
        assert compute_rarity_tier(90.0) == "ultra-rare"

    def test_boundary_20_inclusive(self) -> None:
        assert compute_rarity_tier(20.0) == "uncommon"

    def test_boundary_19(self) -> None:
        assert compute_rarity_tier(19.9) == "common"

    def test_boundary_80_inclusive(self) -> None:
        assert compute_rarity_tier(80.0) == "ultra-rare"

    def test_boundary_60_inclusive(self) -> None:
        assert compute_rarity_tier(60.0) == "rare"

    def test_boundary_40_inclusive(self) -> None:
        assert compute_rarity_tier(40.0) == "scarce"

    def test_zero_score(self) -> None:
        assert compute_rarity_tier(0.0) == "common"


class TestSignalWeights:
    def test_weights_sum_to_one(self) -> None:
        total = sum(SIGNAL_WEIGHTS.values())
        assert abs(total - 1.0) < 0.001


# ── PostgreSQL query function tests ──────────────────────────────────


class TestGetRarityForRelease:
    @pytest.mark.asyncio
    async def test_returns_row(self) -> None:
        mock_pool = MagicMock()
        mock_cur = AsyncMock()
        mock_cur.fetchone = AsyncMock(
            return_value={
                "release_id": 456,
                "title": "Test",
                "artist_name": "Artist",
                "year": 1968,
                "rarity_score": 87.2,
                "tier": "ultra-rare",
                "hidden_gem_score": 72.1,
                "pressing_scarcity": 95.0,
                "label_catalog": 80.0,
                "format_rarity": 70.0,
                "temporal_scarcity": 92.0,
                "graph_isolation": 65.0,
            }
        )
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cur)
        mock_cur.__aenter__ = AsyncMock(return_value=mock_cur)
        mock_cur.__aexit__ = AsyncMock(return_value=False)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_pool.connection = MagicMock(return_value=mock_conn)

        result = await get_rarity_for_release(mock_pool, 456)
        assert result is not None
        assert result["rarity_score"] == 87.2

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self) -> None:
        mock_pool = MagicMock()
        mock_cur = AsyncMock()
        mock_cur.fetchone = AsyncMock(return_value=None)
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cur)
        mock_cur.__aenter__ = AsyncMock(return_value=mock_cur)
        mock_cur.__aexit__ = AsyncMock(return_value=False)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_pool.connection = MagicMock(return_value=mock_conn)

        result = await get_rarity_for_release(mock_pool, 999)
        assert result is None


class TestGetRarityLeaderboard:
    @pytest.mark.asyncio
    async def test_returns_items_and_total(self) -> None:
        mock_pool = MagicMock()
        mock_cur = AsyncMock()
        mock_cur.fetchall = AsyncMock(
            return_value=[
                {
                    "release_id": 1,
                    "title": "R1",
                    "artist_name": "A1",
                    "year": 1970,
                    "rarity_score": 95.0,
                    "tier": "ultra-rare",
                    "hidden_gem_score": 80.0,
                }
            ]
        )
        mock_cur.fetchone = AsyncMock(return_value={"total": 100})
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cur)
        mock_cur.__aenter__ = AsyncMock(return_value=mock_cur)
        mock_cur.__aexit__ = AsyncMock(return_value=False)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_pool.connection = MagicMock(return_value=mock_conn)

        items, total = await get_rarity_leaderboard(mock_pool, page=1, page_size=20)
        assert len(items) == 1
        assert total == 100

    @pytest.mark.asyncio
    async def test_with_tier_filter(self) -> None:
        mock_pool = MagicMock()
        mock_cur = AsyncMock()
        mock_cur.fetchall = AsyncMock(
            return_value=[
                {
                    "release_id": 1,
                    "title": "R1",
                    "artist_name": "A1",
                    "year": 1970,
                    "rarity_score": 95.0,
                    "tier": "ultra-rare",
                    "hidden_gem_score": 80.0,
                }
            ]
        )
        mock_cur.fetchone = AsyncMock(return_value={"total": 1})
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cur)
        mock_cur.__aenter__ = AsyncMock(return_value=mock_cur)
        mock_cur.__aexit__ = AsyncMock(return_value=False)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_pool.connection = MagicMock(return_value=mock_conn)

        items, total = await get_rarity_leaderboard(mock_pool, page=1, page_size=20, tier="ultra-rare")
        assert len(items) == 1
        assert total == 1


class TestGetRarityHiddenGems:
    @pytest.mark.asyncio
    async def test_returns_items_with_min_rarity(self) -> None:
        mock_pool = MagicMock()
        mock_cur = AsyncMock()
        mock_cur.fetchall = AsyncMock(
            return_value=[
                {"release_id": 1, "title": "R1", "artist_name": "A1", "year": 1970, "rarity_score": 65.0, "tier": "rare", "hidden_gem_score": 55.0}
            ]
        )
        mock_cur.fetchone = AsyncMock(return_value={"total": 50})
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cur)
        mock_cur.__aenter__ = AsyncMock(return_value=mock_cur)
        mock_cur.__aexit__ = AsyncMock(return_value=False)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_pool.connection = MagicMock(return_value=mock_conn)

        items, total = await get_rarity_hidden_gems(mock_pool, page=1, page_size=20, min_rarity=41.0)
        assert len(items) == 1
        assert total == 50


class TestGetRarityByArtist:
    @pytest.mark.asyncio
    async def test_artist_not_found(self) -> None:
        mock_driver = MagicMock()
        mock_pool = MagicMock()
        with patch("api.queries.rarity_queries.run_query", new=AsyncMock(return_value=[])):
            result = await get_rarity_by_artist(mock_driver, mock_pool, "nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_artist_with_no_releases(self) -> None:
        mock_driver = MagicMock()
        mock_pool = MagicMock()
        with patch(
            "api.queries.rarity_queries.run_query",
            new=AsyncMock(
                side_effect=[
                    [{"id": "123", "name": "Artist"}],  # artist exists
                    [],  # no releases
                ]
            ),
        ):
            result = await get_rarity_by_artist(mock_driver, mock_pool, "123")
        assert result is not None
        items, total = result
        assert items == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_artist_with_releases(self) -> None:
        mock_driver = MagicMock()
        mock_pool = MagicMock()
        mock_cur = AsyncMock()
        mock_cur.fetchall = AsyncMock(
            return_value=[
                {
                    "release_id": 1,
                    "title": "R1",
                    "artist_name": "A1",
                    "year": 1970,
                    "rarity_score": 85.0,
                    "tier": "ultra-rare",
                    "hidden_gem_score": 60.0,
                }
            ]
        )
        mock_cur.fetchone = AsyncMock(return_value={"total": 1})
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cur)
        mock_cur.__aenter__ = AsyncMock(return_value=mock_cur)
        mock_cur.__aexit__ = AsyncMock(return_value=False)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_pool.connection = MagicMock(return_value=mock_conn)

        with patch(
            "api.queries.rarity_queries.run_query",
            new=AsyncMock(
                side_effect=[
                    [{"id": "123", "name": "Artist"}],  # artist exists
                    [{"release_id": "1"}],  # release ids
                ]
            ),
        ):
            result = await get_rarity_by_artist(mock_driver, mock_pool, "123")
        assert result is not None
        items, total = result
        assert len(items) == 1
        assert total == 1

    @pytest.mark.asyncio
    async def test_artist_with_non_numeric_release_ids(self) -> None:
        """Non-numeric release IDs are filtered out instead of raising ValueError."""
        mock_driver = MagicMock()
        mock_pool = MagicMock()
        with patch(
            "api.queries.rarity_queries.run_query",
            new=AsyncMock(
                side_effect=[
                    [{"id": "123", "name": "Artist"}],  # artist exists
                    [{"release_id": "abc"}, {"release_id": ""}, {"release_id": "not-a-number"}],  # all non-numeric
                ]
            ),
        ):
            result = await get_rarity_by_artist(mock_driver, mock_pool, "123")
        assert result is not None
        items, total = result
        assert items == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_artist_with_mixed_release_ids(self) -> None:
        """Mix of numeric and non-numeric release IDs — only valid ones pass through."""
        mock_driver = MagicMock()
        mock_pool = MagicMock()
        mock_cur = AsyncMock()
        mock_cur.fetchall = AsyncMock(
            return_value=[
                {
                    "release_id": 1,
                    "title": "R1",
                    "artist_name": "A1",
                    "year": 1990,
                    "rarity_score": 90.0,
                    "tier": "ultra-rare",
                    "hidden_gem_score": 75.0,
                }
            ]
        )
        mock_cur.fetchone = AsyncMock(return_value={"total": 1})
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cur)
        mock_cur.__aenter__ = AsyncMock(return_value=mock_cur)
        mock_cur.__aexit__ = AsyncMock(return_value=False)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_pool.connection = MagicMock(return_value=mock_conn)

        with patch(
            "api.queries.rarity_queries.run_query",
            new=AsyncMock(
                side_effect=[
                    [{"id": "123", "name": "Artist"}],  # artist exists
                    [{"release_id": "1"}, {"release_id": "abc"}, {"release_id": "2"}],  # mixed
                ]
            ),
        ):
            result = await get_rarity_by_artist(mock_driver, mock_pool, "123")
        assert result is not None
        items, _total = result
        assert len(items) == 1


class TestGetRarityByLabel:
    @pytest.mark.asyncio
    async def test_label_not_found(self) -> None:
        mock_driver = MagicMock()
        mock_pool = MagicMock()
        with patch("api.queries.rarity_queries.run_query", new=AsyncMock(return_value=[])):
            result = await get_rarity_by_label(mock_driver, mock_pool, "nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_label_with_no_releases(self) -> None:
        mock_driver = MagicMock()
        mock_pool = MagicMock()
        with patch(
            "api.queries.rarity_queries.run_query",
            new=AsyncMock(
                side_effect=[
                    [{"id": "456", "name": "Label"}],  # label exists
                    [],  # no releases
                ]
            ),
        ):
            result = await get_rarity_by_label(mock_driver, mock_pool, "456")
        assert result is not None
        items, total = result
        assert items == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_label_with_releases(self) -> None:
        mock_driver = MagicMock()
        mock_pool = MagicMock()
        mock_cur = AsyncMock()
        mock_cur.fetchall = AsyncMock(
            return_value=[
                {
                    "release_id": 1,
                    "title": "R1",
                    "artist_name": "A1",
                    "year": 1970,
                    "rarity_score": 85.0,
                    "tier": "ultra-rare",
                    "hidden_gem_score": 60.0,
                }
            ]
        )
        mock_cur.fetchone = AsyncMock(return_value={"total": 1})
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cur)
        mock_cur.__aenter__ = AsyncMock(return_value=mock_cur)
        mock_cur.__aexit__ = AsyncMock(return_value=False)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_pool.connection = MagicMock(return_value=mock_conn)

        with patch(
            "api.queries.rarity_queries.run_query",
            new=AsyncMock(
                side_effect=[
                    [{"id": "456", "name": "Label"}],  # label exists
                    [{"release_id": "1"}],  # release ids
                ]
            ),
        ):
            result = await get_rarity_by_label(mock_driver, mock_pool, "456")
        assert result is not None
        items, total = result
        assert len(items) == 1
        assert total == 1

    @pytest.mark.asyncio
    async def test_label_with_non_numeric_release_ids(self) -> None:
        """Non-numeric release IDs in label results are filtered out."""
        mock_driver = MagicMock()
        mock_pool = MagicMock()
        with patch(
            "api.queries.rarity_queries.run_query",
            new=AsyncMock(
                side_effect=[
                    [{"id": "456", "name": "Label"}],  # label exists
                    [{"release_id": "abc"}, {"release_id": ""}],  # all non-numeric
                ]
            ),
        ):
            result = await get_rarity_by_label(mock_driver, mock_pool, "456")
        assert result is not None
        items, total = result
        assert items == []
        assert total == 0


# ── Neo4j batch query tests ──────────────────────────────────────────


class TestFetchAllRaritySignals:
    @pytest.mark.asyncio
    async def test_computes_scores_for_releases(self) -> None:
        """Test end-to-end signal fetch and scoring."""
        mock_driver = MagicMock()

        pressing_data = [{"release_id": "1", "pressing_count": 1, "title": "R1", "artist_name": "A1", "year": 1970}]
        label_data = [{"release_id": "1", "label_catalog_size": 20}]
        format_data = [{"release_id": "1", "formats": ["LP", "Flexi-disc"]}]
        temporal_data = [{"release_id": "1", "year": 1970, "latest_sibling_year": None}]
        degree_data = [{"release_id": "1", "degree": 3}]
        artist_degree_data = [{"release_id": "1", "artist_max_degree": 500}]
        label_size_data = [{"release_id": "1", "label_max_catalog": 2000}]
        genre_count_data = [{"release_id": "1", "genre_max_release_count": 50000}]

        # Mock PostgreSQL pool for community counts
        mock_cur = AsyncMock()
        mock_cur.fetchall = AsyncMock(
            return_value=[
                {"release_id": 1, "have_count": 50, "want_count": 10},
            ]
        )
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cur)
        mock_cur.__aenter__ = AsyncMock(return_value=mock_cur)
        mock_cur.__aexit__ = AsyncMock(return_value=False)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_pool = MagicMock()
        mock_pool.connection = MagicMock(return_value=mock_conn)

        with patch("api.queries.rarity_queries.run_query") as mock_run:
            mock_run.side_effect = [
                pressing_data,
                label_data,
                format_data,
                temporal_data,
                degree_data,
                artist_degree_data,
                label_size_data,
                genre_count_data,
            ]
            results = await fetch_all_rarity_signals(mock_driver, mock_pool)

        assert len(results) == 1
        r = results[0]
        assert r["release_id"] == "1"
        assert 0 <= r["rarity_score"] <= 100
        assert r["tier"] in ("common", "uncommon", "scarce", "rare", "ultra-rare")
        assert r["pressing_scarcity"] == 100.0
        assert r["format_rarity"] == 95.0  # Flexi-disc max
        assert r["collection_prevalence"] == 70.0  # have=50 -> 70.0, want<have -> no bonus
        assert "hidden_gem_score" in r

    @pytest.mark.asyncio
    async def test_handles_zero_quality_signals(self) -> None:
        """Test that releases with zero quality signals get hidden_gem_score of 0."""
        mock_driver = MagicMock()

        pressing_data = [{"release_id": "1", "pressing_count": 1, "title": "R1", "artist_name": "A1", "year": 1970}]
        label_data = [{"release_id": "1", "label_catalog_size": 5}]
        format_data = [{"release_id": "1", "formats": ["LP"]}]
        temporal_data = [{"release_id": "1", "year": 1970, "latest_sibling_year": None}]
        degree_data = [{"release_id": "1", "degree": 2}]
        artist_degree_data = [{"release_id": "1", "artist_max_degree": 0}]
        label_size_data = [{"release_id": "1", "label_max_catalog": 0}]
        genre_count_data = [{"release_id": "1", "genre_max_release_count": 0}]

        # Mock pool with no community data
        mock_cur = AsyncMock()
        mock_cur.fetchall = AsyncMock(return_value=[])
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cur)
        mock_cur.__aenter__ = AsyncMock(return_value=mock_cur)
        mock_cur.__aexit__ = AsyncMock(return_value=False)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_pool = MagicMock()
        mock_pool.connection = MagicMock(return_value=mock_conn)

        with patch("api.queries.rarity_queries.run_query") as mock_run:
            mock_run.side_effect = [
                pressing_data,
                label_data,
                format_data,
                temporal_data,
                degree_data,
                artist_degree_data,
                label_size_data,
                genre_count_data,
            ]
            results = await fetch_all_rarity_signals(mock_driver, mock_pool)

        assert len(results) == 1
        assert results[0]["hidden_gem_score"] == 0.0
        assert results[0]["collection_prevalence"] == 50.0  # neutral fallback

    @pytest.mark.asyncio
    async def test_fallback_when_no_pool(self) -> None:
        """Test that passing pool=None uses neutral fallback for all releases."""
        mock_driver = MagicMock()

        pressing_data = [{"release_id": "1", "pressing_count": 1, "title": "R1", "artist_name": "A1", "year": 1970}]
        label_data = [{"release_id": "1", "label_catalog_size": 20}]
        format_data = [{"release_id": "1", "formats": ["LP"]}]
        temporal_data = [{"release_id": "1", "year": 1970, "latest_sibling_year": None}]
        degree_data = [{"release_id": "1", "degree": 3}]
        artist_degree_data = [{"release_id": "1", "artist_max_degree": 500}]
        label_size_data = [{"release_id": "1", "label_max_catalog": 2000}]
        genre_count_data = [{"release_id": "1", "genre_max_release_count": 50000}]

        with patch("api.queries.rarity_queries.run_query") as mock_run:
            mock_run.side_effect = [
                pressing_data,
                label_data,
                format_data,
                temporal_data,
                degree_data,
                artist_degree_data,
                label_size_data,
                genre_count_data,
            ]
            results = await fetch_all_rarity_signals(mock_driver, None)

        assert len(results) == 1
        assert results[0]["collection_prevalence"] == 50.0
