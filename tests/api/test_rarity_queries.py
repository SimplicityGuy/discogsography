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

    def test_future_dated_release_floors_at_zero(self) -> None:
        """discogsography-cu2.94: a typo'd/erroneous future year (e.g. 2050) must not
        drive the score negative — the age-based base is floored at 0.0, matching the
        existing upper-bound cap at 100.0.
        """
        current_year = datetime.now(UTC).year
        score = compute_temporal_scarcity_score(current_year + 24, None, current_year)
        assert score == 0.0
        assert score >= 0.0

    def test_next_year_release_floors_at_zero(self) -> None:
        """A legitimate upcoming/pre-order release dated next year also must not
        yield a negative signal, even though the magnitude is small (age=-1)."""
        current_year = datetime.now(UTC).year
        score = compute_temporal_scarcity_score(current_year + 1, None, current_year)
        assert score == 0.0


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


def _fake_run_query(
    *,
    pressing: list | None = None,
    label: list | None = None,
    formats: list | None = None,
    temporal: list | None = None,
    degree: list | None = None,
    artist_degree: list | None = None,
    label_size: list | None = None,
    genre_count: list | None = None,
    page_size: int = 20_000,
):
    """Build a run_query stub that dispatches on the cypher, not on call order.

    fetch_all_rarity_signals is paginated, so the call sequence is
    (page query, 8 signal queries)* + a final empty page + a count query.
    Dispatching on the query text keeps these tests independent of that
    interleaving.
    """
    pressing = pressing or []
    signal_rows = {
        "label_catalog_size": label or [],
        "r.formats AS formats": formats or [],
        "latest_sibling_year": temporal or [],
        "AS degree": degree or [],
        "artist_max_degree": artist_degree or [],
        "label_max_catalog": label_size or [],
        "genre_max_release_count": genre_count or [],
    }
    # Every release the pressing query knows about, paged out by the keyset walk.
    all_ids = [row["release_id"] for row in pressing]
    served: list[str] = []

    async def _run(_driver, cypher, **kwargs):
        if "ORDER BY r.id" in cypher:  # keyset page query
            cursor = kwargs["cursor"]
            remaining = [i for i in all_ids if i > cursor]
            page = remaining[:page_size]
            served.extend(page)
            return [{"release_id": i} for i in page]
        if "count(r) AS total" in cypher:  # coverage check
            return [{"total": len(all_ids)}]
        ids = set(kwargs["ids"])
        if "pressing_count," in cypher:
            return [r for r in pressing if r["release_id"] in ids]
        for marker, rows in signal_rows.items():
            if marker in cypher:
                return [r for r in rows if r["release_id"] in ids]
        raise AssertionError(f"unrecognised cypher:\n{cypher}")

    return _run


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

        run_query = _fake_run_query(
            pressing=pressing_data,
            label=label_data,
            formats=format_data,
            temporal=temporal_data,
            degree=degree_data,
            artist_degree=artist_degree_data,
            label_size=label_size_data,
            genre_count=genre_count_data,
        )
        with patch("api.queries.rarity_queries.run_query", side_effect=run_query):
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

        run_query = _fake_run_query(
            pressing=pressing_data,
            label=label_data,
            formats=format_data,
            temporal=temporal_data,
            degree=degree_data,
            artist_degree=artist_degree_data,
            label_size=label_size_data,
            genre_count=genre_count_data,
        )
        with patch("api.queries.rarity_queries.run_query", side_effect=run_query):
            results = await fetch_all_rarity_signals(mock_driver, mock_pool)

        assert len(results) == 1
        assert results[0]["hidden_gem_score"] == 0.0
        assert results[0]["collection_prevalence"] == 50.0  # neutral fallback

    @pytest.mark.asyncio
    async def test_community_counts_exception_uses_fallback(self) -> None:
        """When pool.connection raises, community counts fall back to neutral 50.0."""
        mock_driver = MagicMock()

        pressing_data = [{"release_id": "1", "pressing_count": 1, "title": "R1", "artist_name": "A1", "year": 1970}]
        label_data = [{"release_id": "1", "label_catalog_size": 20}]
        format_data = [{"release_id": "1", "formats": ["LP"]}]
        temporal_data = [{"release_id": "1", "year": 1970, "latest_sibling_year": None}]
        degree_data = [{"release_id": "1", "degree": 3}]
        artist_degree_data = [{"release_id": "1", "artist_max_degree": 500}]
        label_size_data = [{"release_id": "1", "label_max_catalog": 2000}]
        genre_count_data = [{"release_id": "1", "genre_max_release_count": 50000}]

        # Pool connection raises an exception
        mock_pool = MagicMock()
        mock_pool.connection = MagicMock(side_effect=RuntimeError("db connection failed"))

        run_query = _fake_run_query(
            pressing=pressing_data,
            label=label_data,
            formats=format_data,
            temporal=temporal_data,
            degree=degree_data,
            artist_degree=artist_degree_data,
            label_size=label_size_data,
            genre_count=genre_count_data,
        )
        with patch("api.queries.rarity_queries.run_query", side_effect=run_query):
            results = await fetch_all_rarity_signals(mock_driver, mock_pool)

        assert len(results) == 1
        assert results[0]["collection_prevalence"] == 50.0

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

        run_query = _fake_run_query(
            pressing=pressing_data,
            label=label_data,
            formats=format_data,
            temporal=temporal_data,
            degree=degree_data,
            artist_degree=artist_degree_data,
            label_size=label_size_data,
            genre_count=genre_count_data,
        )
        with patch("api.queries.rarity_queries.run_query", side_effect=run_query):
            results = await fetch_all_rarity_signals(mock_driver, None)

        assert len(results) == 1
        assert results[0]["collection_prevalence"] == 50.0

    @pytest.mark.asyncio
    async def test_pressing_query_uses_two_optional_matches(self) -> None:
        """discogsography-cu2.75: the master lookup and sibling lookup must be two
        separate OPTIONAL MATCHes. A single combined pattern makes `m` (and therefore
        pressing_count) null whenever the release is its master's ONLY pressing —
        misclassifying the rarest pressing case as "no master link".

        Asserted against the query actually handed to the driver, so the property
        survives the chunked (page-scoped) rewrite of fetch_all_rarity_signals.
        """
        mock_driver = MagicMock()
        pressing_data = [{"release_id": "1", "pressing_count": 1, "title": "R1", "artist_name": "A1", "year": 1970}]
        run_query = _fake_run_query(pressing=pressing_data)
        sent: list[str] = []

        async def _recording(driver, cypher, **kwargs):
            sent.append(cypher)
            return await run_query(driver, cypher, **kwargs)

        with patch("api.queries.rarity_queries.run_query", side_effect=_recording):
            await fetch_all_rarity_signals(mock_driver, None)

        pressing_cypher = next(c for c in sent if "pressing_count," in c)
        # Two independent OPTIONAL MATCH clauses, not one combined pattern that
        # conditions `m` on a sibling existing.
        assert "OPTIONAL MATCH (r)-[:DERIVED_FROM]->(m:Master)\n" in pressing_cypher
        assert "OPTIONAL MATCH (m)<-[:DERIVED_FROM]-(sibling:Release)" in pressing_cypher
        assert "OPTIONAL MATCH (r)-[:DERIVED_FROM]->(m:Master)<-[:DERIVED_FROM]-(sibling:Release)" not in pressing_cypher
        # The +1 must live inside the non-null branch, not in the aggregate —
        # otherwise the combined-pattern bug returns by another route.
        assert "count(DISTINCT sibling) AS sibling_count" in pressing_cypher
        assert "CASE WHEN m IS NULL THEN 0 ELSE sibling_count + 1 END" in pressing_cypher

    def test_pressing_query_constant_keeps_the_split_lookup(self) -> None:
        """The chunked constant is the single source of truth — pin it directly."""
        from api.queries.rarity_queries import _PRESSING_QUERY

        assert "OPTIONAL MATCH (r)-[:DERIVED_FROM]->(m:Master)\n" in _PRESSING_QUERY
        assert "OPTIONAL MATCH (m)<-[:DERIVED_FROM]-(sibling:Release)" in _PRESSING_QUERY
        assert "OPTIONAL MATCH (r)-[:DERIVED_FROM]->(m:Master)<-[:DERIVED_FROM]-(sibling:Release)" not in _PRESSING_QUERY

    @pytest.mark.asyncio
    async def test_sole_pressing_of_master_scores_as_unique_not_standalone(self) -> None:
        """discogsography-cu2.75: a release that IS linked to a master but has no
        sibling pressings must score pressing_count=1 (-> 100.0, unique pressing),
        not pressing_count=0 (-> 90.0, standalone/no-master-link).
        """
        mock_driver = MagicMock()

        # Post-fix pressing_query semantics for a sole-pressing-with-master release.
        pressing_data = [{"release_id": "1", "pressing_count": 1, "title": "R1", "artist_name": "A1", "year": 1970}]
        label_data = [{"release_id": "1", "label_catalog_size": 20}]
        format_data = [{"release_id": "1", "formats": ["LP"]}]
        temporal_data = [{"release_id": "1", "year": 1970, "latest_sibling_year": None}]
        degree_data = [{"release_id": "1", "degree": 3}]
        artist_degree_data = [{"release_id": "1", "artist_max_degree": 500}]
        label_size_data = [{"release_id": "1", "label_max_catalog": 2000}]
        genre_count_data = [{"release_id": "1", "genre_max_release_count": 50000}]

        run_query = _fake_run_query(
            pressing=pressing_data,
            label=label_data,
            formats=format_data,
            temporal=temporal_data,
            degree=degree_data,
            artist_degree=artist_degree_data,
            label_size=label_size_data,
            genre_count=genre_count_data,
        )
        with patch("api.queries.rarity_queries.run_query", side_effect=run_query):
            results = await fetch_all_rarity_signals(mock_driver, None)

        assert results[0]["pressing_scarcity"] == 100.0


class TestRarityPaginationTiebreaker:
    """discogsography-cu2.55: rarity_score / hidden_gem_score are heavily
    quantized (round(..., 1)), so OFFSET pagination without a unique tiebreaker
    duplicates and skips rows across pages. Every paginated ORDER BY must append
    the unique release_id column.
    """

    @staticmethod
    def _pool_with_capture() -> tuple[MagicMock, AsyncMock]:
        mock_cur = AsyncMock()
        mock_cur.fetchall = AsyncMock(return_value=[])
        mock_cur.fetchone = AsyncMock(return_value={"total": 0})
        mock_cur.__aenter__ = AsyncMock(return_value=mock_cur)
        mock_cur.__aexit__ = AsyncMock(return_value=False)
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cur)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_pool = MagicMock()
        mock_pool.connection = MagicMock(return_value=mock_conn)
        return mock_pool, mock_cur

    @staticmethod
    def _first_order_by_sql(mock_cur: AsyncMock) -> str:
        """The SQL of the first (paginated) execute — the count query is second."""
        return str(mock_cur.execute.call_args_list[0].args[0])

    @pytest.mark.asyncio
    async def test_leaderboard_no_tier_has_tiebreaker(self) -> None:
        mock_pool, mock_cur = self._pool_with_capture()
        await get_rarity_leaderboard(mock_pool, page=1, page_size=20)
        assert "ORDER BY rarity_score DESC, release_id" in self._first_order_by_sql(mock_cur)

    @pytest.mark.asyncio
    async def test_leaderboard_with_tier_has_tiebreaker(self) -> None:
        mock_pool, mock_cur = self._pool_with_capture()
        await get_rarity_leaderboard(mock_pool, page=1, page_size=20, tier="ultra-rare")
        assert "ORDER BY rarity_score DESC, release_id" in self._first_order_by_sql(mock_cur)

    @pytest.mark.asyncio
    async def test_hidden_gems_has_tiebreaker(self) -> None:
        mock_pool, mock_cur = self._pool_with_capture()
        await get_rarity_hidden_gems(mock_pool, page=1, page_size=20, min_rarity=41.0)
        assert "ORDER BY hidden_gem_score DESC, release_id" in self._first_order_by_sql(mock_cur)

    @pytest.mark.asyncio
    async def test_by_artist_has_tiebreaker(self) -> None:
        mock_pool, mock_cur = self._pool_with_capture()
        with patch(
            "api.queries.rarity_queries.run_query",
            new=AsyncMock(side_effect=[[{"id": "123", "name": "Artist"}], [{"release_id": "1"}]]),
        ):
            await get_rarity_by_artist(MagicMock(), mock_pool, "123")
        assert "ORDER BY rarity_score DESC, release_id" in self._first_order_by_sql(mock_cur)

    @pytest.mark.asyncio
    async def test_by_label_has_tiebreaker(self) -> None:
        mock_pool, mock_cur = self._pool_with_capture()
        with patch(
            "api.queries.rarity_queries.run_query",
            new=AsyncMock(side_effect=[[{"id": "456", "name": "Label"}], [{"release_id": "1"}]]),
        ):
            await get_rarity_by_label(MagicMock(), mock_pool, "456")
        assert "ORDER BY rarity_score DESC, release_id" in self._first_order_by_sql(mock_cur)


class TestRarityChunking:
    """discogsography-lx1n: the rarity signal scans must never run unbounded.

    Eight full-graph `MATCH (r:Release)` scans blew Neo4j's 600s
    db.transaction.timeout on every production run, failing release_rarity 33
    cycles in a row.
    """

    def test_no_signal_query_scans_the_whole_release_set(self) -> None:
        """Every signal query must be scoped to an explicit $ids page."""
        from api.queries import rarity_queries

        signal_queries = {
            name: value
            for name, value in vars(rarity_queries).items()
            if name.endswith("_QUERY") and name not in {"_RELEASE_ID_PAGE_QUERY", "_RELEASE_COUNT_QUERY"}
        }
        assert signal_queries, "no signal queries discovered — did they get renamed?"

        for name, cypher in signal_queries.items():
            assert "UNWIND $ids AS rid" in cypher, f"{name} is not page-scoped"
            assert "MATCH (r:Release {id: rid})" in cypher, f"{name} does not seek by indexed id"
            # The unbounded scan that caused the outage.
            assert "MATCH (r:Release)\n" not in cypher, f"{name} reintroduced a full-graph scan"

    def test_query_timeout_stays_under_the_server_transaction_timeout(self) -> None:
        """Must fail fast rather than burn the full 600s db.transaction.timeout."""
        from api.queries.rarity_queries import RARITY_QUERY_TIMEOUT_SECONDS

        assert RARITY_QUERY_TIMEOUT_SECONDS < 600.0

    @pytest.mark.asyncio
    async def test_every_neo4j_query_carries_an_explicit_timeout(self) -> None:
        mock_driver = MagicMock()
        pressing_data = [{"release_id": "1", "pressing_count": 1, "title": "R1", "artist_name": "A1", "year": 1970}]
        run_query = _fake_run_query(pressing=pressing_data)
        seen: list[float | None] = []

        async def _recording(driver, cypher, **kwargs):
            seen.append(kwargs.get("timeout"))
            return await run_query(driver, cypher, **kwargs)

        with patch("api.queries.rarity_queries.run_query", side_effect=_recording):
            await fetch_all_rarity_signals(mock_driver, None)

        from api.queries.rarity_queries import RARITY_QUERY_TIMEOUT_SECONDS

        assert seen, "no queries were run"
        assert all(t == RARITY_QUERY_TIMEOUT_SECONDS for t in seen), seen

    @pytest.mark.asyncio
    async def test_pages_the_release_set_and_scores_every_release(self) -> None:
        """A release set larger than one page is fully covered across pages."""
        mock_driver = MagicMock()
        # Ids are strings and the walk is a lexicographic keyset scan, so use
        # zero-padded ids to keep string order == numeric order.
        ids = [f"{i:04d}" for i in range(25)]
        pressing_data = [{"release_id": rid, "pressing_count": 1, "title": f"R{rid}", "artist_name": "A", "year": 1970} for rid in ids]
        degree_data = [{"release_id": rid, "degree": 3} for rid in ids]

        page_size = 10
        run_query = _fake_run_query(pressing=pressing_data, degree=degree_data, page_size=page_size)
        pages: list[int] = []

        async def _recording(driver, cypher, **kwargs):
            rows = await run_query(driver, cypher, **kwargs)
            if "ORDER BY r.id" in cypher and rows:
                pages.append(len(rows))
            return rows

        with patch("api.queries.rarity_queries.run_query", side_effect=_recording):
            results = await fetch_all_rarity_signals(mock_driver, None, page_size=page_size)

        # 25 releases at 10/page -> 10, 10, 5
        assert pages == [10, 10, 5]
        assert [r["release_id"] for r in results] == ids

    @pytest.mark.asyncio
    async def test_no_page_query_requests_more_than_page_size(self) -> None:
        mock_driver = MagicMock()
        ids = [f"{i:04d}" for i in range(12)]
        pressing_data = [{"release_id": rid, "pressing_count": 1, "title": "R", "artist_name": "A", "year": 1970} for rid in ids]
        run_query = _fake_run_query(pressing=pressing_data, page_size=5)
        limits: list[int] = []

        async def _recording(driver, cypher, **kwargs):
            if "ORDER BY r.id" in cypher:
                limits.append(kwargs["limit"])
            return await run_query(driver, cypher, **kwargs)

        with patch("api.queries.rarity_queries.run_query", side_effect=_recording):
            await fetch_all_rarity_signals(mock_driver, None, page_size=5)

        assert limits and all(limit == 5 for limit in limits)

    @pytest.mark.asyncio
    async def test_signal_queries_only_receive_ids_from_the_current_page(self) -> None:
        mock_driver = MagicMock()
        ids = [f"{i:04d}" for i in range(6)]
        pressing_data = [{"release_id": rid, "pressing_count": 1, "title": "R", "artist_name": "A", "year": 1970} for rid in ids]
        run_query = _fake_run_query(pressing=pressing_data, page_size=2)
        id_batches: list[list[str]] = []

        async def _recording(driver, cypher, **kwargs):
            if "UNWIND $ids AS rid" in cypher:
                id_batches.append(list(kwargs["ids"]))
            return await run_query(driver, cypher, **kwargs)

        with patch("api.queries.rarity_queries.run_query", side_effect=_recording):
            await fetch_all_rarity_signals(mock_driver, None, page_size=2)

        assert id_batches
        assert all(len(batch) <= 2 for batch in id_batches)
        # 3 pages x 8 signal queries
        assert len(id_batches) == 24

    @pytest.mark.asyncio
    async def test_hidden_gem_percentiles_span_pages(self) -> None:
        """Percentile ranks are global, not per-page — a paged walk must not change them."""
        mock_driver = MagicMock()
        ids = [f"{i:04d}" for i in range(6)]
        pressing_data = [{"release_id": rid, "pressing_count": 1, "title": "R", "artist_name": "A", "year": 1970} for rid in ids]
        artist_degree_data = [{"release_id": rid, "artist_max_degree": (i + 1) * 10} for i, rid in enumerate(ids)]

        def _score(page_size: int) -> list[float]:
            return [r["hidden_gem_score"] for r in scored[page_size]]

        scored = {}
        for page_size in (6, 2, 1):
            run_query = _fake_run_query(
                pressing=pressing_data,
                artist_degree=artist_degree_data,
                page_size=page_size,
            )
            with patch("api.queries.rarity_queries.run_query", side_effect=run_query):
                scored[page_size] = await fetch_all_rarity_signals(mock_driver, None, page_size=page_size)

        # Identical results regardless of how the walk was chunked.
        assert _score(6) == _score(2) == _score(1)
        # And the percentiles are actually doing something.
        assert len(set(_score(6))) > 1

    @pytest.mark.asyncio
    async def test_warns_when_pagination_covers_fewer_releases_than_the_graph(self) -> None:
        """A truncated keyset walk must be loud, not silent."""
        mock_driver = MagicMock()
        pressing_data = [{"release_id": "1", "pressing_count": 1, "title": "R", "artist_name": "A", "year": 1970}]
        run_query = _fake_run_query(pressing=pressing_data)

        async def _undercounting(driver, cypher, **kwargs):
            if "count(r) AS total" in cypher:
                return [{"total": 999}]
            return await run_query(driver, cypher, **kwargs)

        with (
            patch("api.queries.rarity_queries.run_query", side_effect=_undercounting),
            patch("api.queries.rarity_queries.logger.warning") as mock_warning,
        ):
            await fetch_all_rarity_signals(mock_driver, None)

        assert mock_warning.called
        assert mock_warning.call_args.kwargs["missing"] == 998

    @pytest.mark.asyncio
    async def test_empty_graph_returns_no_results(self) -> None:
        mock_driver = MagicMock()
        run_query = _fake_run_query()

        with patch("api.queries.rarity_queries.run_query", side_effect=run_query):
            results = await fetch_all_rarity_signals(mock_driver, None)

        assert results == []
