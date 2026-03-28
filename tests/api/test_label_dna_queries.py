"""Unit tests for Label DNA query functions."""

from unittest.mock import AsyncMock, patch

import pytest

from api.queries.label_dna_queries import (
    compute_similar_labels,
    get_candidate_labels_genre_vectors,
    get_label_active_years,
    get_label_decade_profile,
    get_label_format_profile,
    get_label_full_profile,
    get_label_genre_profile,
    get_label_identity,
    get_label_style_profile,
)
from api.queries.similarity import cosine_similarity, to_genre_vector


class TestCosineSimilarity:
    """Tests for the cosine similarity function."""

    def test_identical_vectors(self) -> None:
        vec = {"Rock": 0.6, "Jazz": 0.4}
        assert cosine_similarity(vec, vec) == pytest.approx(1.0)

    def test_orthogonal_vectors(self) -> None:
        vec_a = {"Rock": 1.0}
        vec_b = {"Jazz": 1.0}
        assert cosine_similarity(vec_a, vec_b) == pytest.approx(0.0)

    def test_partial_overlap(self) -> None:
        vec_a = {"Rock": 0.5, "Jazz": 0.5}
        vec_b = {"Rock": 0.5, "Electronic": 0.5}
        sim = cosine_similarity(vec_a, vec_b)
        assert 0.0 < sim < 1.0

    def test_empty_vector_a(self) -> None:
        assert cosine_similarity({}, {"Rock": 1.0}) == 0.0

    def test_empty_vector_b(self) -> None:
        assert cosine_similarity({"Rock": 1.0}, {}) == 0.0

    def test_both_empty(self) -> None:
        assert cosine_similarity({}, {}) == 0.0

    def test_single_dimension(self) -> None:
        vec_a = {"Rock": 0.8}
        vec_b = {"Rock": 0.3}
        assert cosine_similarity(vec_a, vec_b) == pytest.approx(1.0)


class TestToGenreVector:
    """Tests for _to_genre_vector."""

    def test_normalizes_counts_to_percentages(self) -> None:
        genres = [{"name": "Rock", "count": 60}, {"name": "Jazz", "count": 40}]
        vec = to_genre_vector(genres)
        assert vec["Rock"] == pytest.approx(0.6)
        assert vec["Jazz"] == pytest.approx(0.4)

    def test_empty_list(self) -> None:
        assert to_genre_vector([]) == {}

    def test_uses_name_key(self) -> None:
        genres = [{"name": "Rock", "count": 10}]
        vec = to_genre_vector(genres)
        assert "Rock" in vec

    def test_zero_total(self) -> None:
        genres = [{"name": "Rock", "count": 0}]
        assert to_genre_vector(genres) == {}


class TestComputeSimilarLabels:
    """Tests for compute_similar_labels."""

    def test_returns_ranked_results(self) -> None:
        target = [{"name": "Rock", "count": 80}, {"name": "Jazz", "count": 20}]
        candidates = [
            {
                "label_id": "1",
                "label_name": "Label A",
                "release_count": 50,
                "genres": [{"name": "Rock", "count": 70}, {"name": "Jazz", "count": 30}],
            },
            {
                "label_id": "2",
                "label_name": "Label B",
                "release_count": 30,
                "genres": [{"name": "Electronic", "count": 90}, {"name": "Rock", "count": 10}],
            },
        ]
        results = compute_similar_labels(target, candidates, limit=10)
        assert len(results) == 2
        assert results[0]["label_id"] == "1"
        assert results[0]["similarity"] > results[1]["similarity"]

    def test_respects_limit(self) -> None:
        target = [{"name": "Rock", "count": 100}]
        candidates = [
            {
                "label_id": str(i),
                "label_name": f"Label {i}",
                "release_count": 10,
                "genres": [{"name": "Rock", "count": 10}],
            }
            for i in range(20)
        ]
        results = compute_similar_labels(target, candidates, limit=5)
        assert len(results) == 5

    def test_empty_target(self) -> None:
        results = compute_similar_labels([], [{"label_id": "1", "label_name": "L", "release_count": 5, "genres": []}], limit=10)
        assert results == []

    def test_empty_candidates(self) -> None:
        results = compute_similar_labels([{"name": "Rock", "count": 10}], [], limit=10)
        assert results == []

    def test_shared_genres_populated(self) -> None:
        target = [{"name": "Rock", "count": 50}, {"name": "Jazz", "count": 50}]
        candidates = [
            {
                "label_id": "1",
                "label_name": "Label A",
                "release_count": 10,
                "genres": [{"name": "Rock", "count": 10}, {"name": "Classical", "count": 5}],
            },
        ]
        results = compute_similar_labels(target, candidates, limit=10)
        assert results[0]["shared_genres"] == ["Rock"]


class TestGetCandidateLabelsGenreVectors:
    """Tests for the two-phase get_candidate_labels_genre_vectors query.

    Phase 1: style-based candidate discovery (1 run_query call)
    Phase 2: split into 25-label batches, each with 2 concurrent queries
             (count + genre), so 2 run_query calls per batch.
    """

    @pytest.mark.asyncio
    @patch("api.queries.label_dna_queries.run_query", new_callable=AsyncMock)
    async def test_returns_profiles_for_candidates(self, mock_run_query: AsyncMock) -> None:
        """Phase 1 returns candidates, phase 2 returns their genre profiles."""
        phase1_result = [
            {"label_id": "10", "label_name": "Warp Records", "total_shared": 42},
            {"label_id": "20", "label_name": "Ninja Tune", "total_shared": 31},
        ]
        # Phase 2: count query result and genre query result (1 batch of 2 labels)
        count_result = [
            {"label_id": "10", "label_name": "Warp Records", "release_count": 100},
            {"label_id": "20", "label_name": "Ninja Tune", "release_count": 60},
        ]
        genre_result = [
            {"label_id": "10", "genres": [{"name": "Electronic", "count": 80}]},
            {"label_id": "20", "genres": [{"name": "Electronic", "count": 50}]},
        ]
        mock_run_query.side_effect = [phase1_result, count_result, genre_result]

        driver = AsyncMock()
        result = await get_candidate_labels_genre_vectors(driver, "1")

        assert len(result) == 2
        assert result[0]["label_id"] == "10"
        assert result[0]["release_count"] == 100
        assert result[0]["genres"] == [{"name": "Electronic", "count": 80}]
        assert result[1]["label_id"] == "20"
        assert result[1]["release_count"] == 60
        # Phase 1 + 2 queries per batch (1 batch for 2 candidates)
        assert mock_run_query.call_count == 3

    @pytest.mark.asyncio
    @patch("api.queries.label_dna_queries.run_query", new_callable=AsyncMock)
    async def test_returns_empty_when_no_candidates(self, mock_run_query: AsyncMock) -> None:
        """Early return when phase 1 finds no candidate labels."""
        mock_run_query.return_value = []

        driver = AsyncMock()
        result = await get_candidate_labels_genre_vectors(driver, "nonexistent")

        assert result == []
        # Only phase 1 should run — phase 2 is skipped
        assert mock_run_query.call_count == 1

    @pytest.mark.asyncio
    @patch("api.queries.label_dna_queries.run_query", new_callable=AsyncMock)
    async def test_passes_timeout_to_all_queries(self, mock_run_query: AsyncMock) -> None:
        """All query phases use timeout=60."""
        mock_run_query.side_effect = [
            [{"label_id": "5", "label_name": "L", "total_shared": 10}],
            [{"label_id": "5", "label_name": "L", "release_count": 20}],
            [{"label_id": "5", "genres": []}],
        ]

        driver = AsyncMock()
        await get_candidate_labels_genre_vectors(driver, "1")

        for call in mock_run_query.call_args_list:
            assert call.kwargs["timeout"] == 60


# ---------------------------------------------------------------------------
# Individual query functions
# ---------------------------------------------------------------------------


class TestLabelIdentity:
    @pytest.mark.asyncio
    @patch("api.queries.label_dna_queries.run_single", new_callable=AsyncMock)
    async def test_returns_result(self, mock_run_single: AsyncMock) -> None:
        mock_run_single.return_value = {"label_id": "L1", "label_name": "Warp", "release_count": 50, "artist_count": 20}
        driver = AsyncMock()
        result = await get_label_identity(driver, "L1")
        assert result["label_name"] == "Warp"
        mock_run_single.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("api.queries.label_dna_queries.run_single", new_callable=AsyncMock)
    async def test_returns_none(self, mock_run_single: AsyncMock) -> None:
        mock_run_single.return_value = None
        driver = AsyncMock()
        result = await get_label_identity(driver, "X")
        assert result is None


class TestLabelGenreProfile:
    @pytest.mark.asyncio
    @patch("api.queries.label_dna_queries.run_query", new_callable=AsyncMock)
    async def test_returns_genres(self, mock_run_query: AsyncMock) -> None:
        mock_run_query.return_value = [{"name": "Electronic", "count": 80}, {"name": "Rock", "count": 20}]
        driver = AsyncMock()
        result = await get_label_genre_profile(driver, "L1")
        assert len(result) == 2
        assert result[0]["name"] == "Electronic"


class TestLabelStyleProfile:
    @pytest.mark.asyncio
    @patch("api.queries.label_dna_queries.run_query", new_callable=AsyncMock)
    async def test_returns_styles(self, mock_run_query: AsyncMock) -> None:
        mock_run_query.return_value = [{"name": "Techno", "count": 50}]
        driver = AsyncMock()
        result = await get_label_style_profile(driver, "L1")
        assert len(result) == 1
        assert result[0]["name"] == "Techno"


class TestLabelDecadeProfile:
    @pytest.mark.asyncio
    @patch("api.queries.label_dna_queries.run_query", new_callable=AsyncMock)
    async def test_returns_decades(self, mock_run_query: AsyncMock) -> None:
        mock_run_query.return_value = [{"decade": 1990, "count": 30}, {"decade": 2000, "count": 50}]
        driver = AsyncMock()
        result = await get_label_decade_profile(driver, "L1")
        assert len(result) == 2
        assert result[0]["decade"] == 1990


class TestLabelActiveYears:
    @pytest.mark.asyncio
    @patch("api.queries.label_dna_queries.run_query", new_callable=AsyncMock)
    async def test_returns_years(self, mock_run_query: AsyncMock) -> None:
        mock_run_query.return_value = [{"year": 1992}, {"year": 1995}, {"year": 2001}]
        driver = AsyncMock()
        result = await get_label_active_years(driver, "L1")
        assert result == [1992, 1995, 2001]


class TestLabelFormatProfile:
    @pytest.mark.asyncio
    @patch("api.queries.label_dna_queries.run_query", new_callable=AsyncMock)
    async def test_returns_formats(self, mock_run_query: AsyncMock) -> None:
        mock_run_query.return_value = [{"name": "Vinyl", "count": 40}, {"name": "CD", "count": 30}]
        driver = AsyncMock()
        result = await get_label_format_profile(driver, "L1")
        assert len(result) == 2
        assert result[0]["name"] == "Vinyl"


class TestLabelFullProfile:
    @pytest.mark.asyncio
    @patch("api.queries.label_dna_queries.get_label_identity", new_callable=AsyncMock)
    async def test_identity_none_returns_none(self, mock_identity: AsyncMock) -> None:
        """When identity returns None, full profile returns None."""
        mock_identity.return_value = None
        driver = AsyncMock()
        result = await get_label_full_profile(driver, "X")
        assert result is None

    @pytest.mark.asyncio
    @patch("api.queries.label_dna_queries.get_label_identity", new_callable=AsyncMock)
    async def test_below_min_releases_returns_early(self, mock_identity: AsyncMock) -> None:
        """When release_count < MIN_RELEASES, returns early with empty profiles."""
        mock_identity.return_value = {"label_id": "L1", "label_name": "Tiny Label", "release_count": 2, "artist_count": 1}
        driver = AsyncMock()
        result = await get_label_full_profile(driver, "L1")
        assert result is not None
        assert result["release_count"] == 2
        assert result["genres"] == []
        assert result["styles"] == []
        assert result["decades"] == []

    @pytest.mark.asyncio
    @patch("api.queries.label_dna_queries.get_label_decade_profile", new_callable=AsyncMock)
    @patch("api.queries.label_dna_queries.get_label_style_profile", new_callable=AsyncMock)
    @patch("api.queries.label_dna_queries.get_label_genre_profile", new_callable=AsyncMock)
    @patch("api.queries.label_dna_queries.get_label_identity", new_callable=AsyncMock)
    async def test_normal_path(
        self,
        mock_identity: AsyncMock,
        mock_genres: AsyncMock,
        mock_styles: AsyncMock,
        mock_decades: AsyncMock,
    ) -> None:
        """Normal path with enough releases fetches genres, styles, decades in parallel."""
        mock_identity.return_value = {"label_id": "L1", "label_name": "Warp", "release_count": 100, "artist_count": 40}
        mock_genres.return_value = [{"name": "Electronic", "count": 80}]
        mock_styles.return_value = [{"name": "Techno", "count": 50}]
        mock_decades.return_value = [{"decade": 1990, "count": 60}]

        driver = AsyncMock()
        result = await get_label_full_profile(driver, "L1")
        assert result["label_id"] == "L1"
        assert result["label_name"] == "Warp"
        assert result["release_count"] == 100
        assert result["genres"] == [{"name": "Electronic", "count": 80}]
        assert result["styles"] == [{"name": "Techno", "count": 50}]
        assert result["decades"] == [{"decade": 1990, "count": 60}]
