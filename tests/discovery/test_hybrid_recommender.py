"""Tests for HybridRecommender class."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from discovery.hybrid_recommender import HybridRecommender, HybridStrategy


class TestHybridRecommenderInit:
    """Test HybridRecommender initialization."""

    def test_initialization(self) -> None:
        """Test recommender initializes with correct defaults."""
        mock_collab = MagicMock()
        mock_content = MagicMock()

        recommender = HybridRecommender(mock_collab, mock_content)

        assert recommender.collaborative == mock_collab
        assert recommender.content_based == mock_content
        assert recommender.method_weights["collaborative_filtering"] == 0.5
        assert recommender.method_weights["content_based"] == 0.4
        assert recommender.diversity_weight == 0.2
        assert recommender.min_diversity_threshold == 0.3


class TestGetRecommendations:
    """Test main get_recommendations routing method."""

    @pytest.mark.asyncio
    async def test_weighted_strategy(self) -> None:
        """Test routing to weighted strategy."""
        mock_collab = MagicMock()
        mock_content = MagicMock()
        recommender = HybridRecommender(mock_collab, mock_content)

        recommender._weighted_recommendations = AsyncMock(return_value=[])

        result = await recommender.get_recommendations(
            "Test Artist",
            strategy=HybridStrategy.WEIGHTED,
        )

        recommender._weighted_recommendations.assert_called_once()
        assert result == []

    @pytest.mark.asyncio
    async def test_rank_fusion_strategy(self) -> None:
        """Test routing to rank fusion strategy."""
        mock_collab = MagicMock()
        mock_content = MagicMock()
        recommender = HybridRecommender(mock_collab, mock_content)

        recommender._rank_fusion_recommendations = AsyncMock(return_value=[])

        await recommender.get_recommendations(
            "Test Artist",
            strategy=HybridStrategy.RANK_FUSION,
        )

        recommender._rank_fusion_recommendations.assert_called_once()

    @pytest.mark.asyncio
    async def test_cascade_strategy(self) -> None:
        """Test routing to cascade strategy."""
        mock_collab = MagicMock()
        mock_content = MagicMock()
        recommender = HybridRecommender(mock_collab, mock_content)

        recommender._cascade_recommendations = AsyncMock(return_value=[])

        await recommender.get_recommendations(
            "Test Artist",
            strategy=HybridStrategy.CASCADE,
        )

        recommender._cascade_recommendations.assert_called_once()


class TestWeightedRecommendations:
    """Test weighted recommendation strategy."""

    @pytest.mark.asyncio
    async def test_weighted_combination(self) -> None:
        """Test weighted combination of recommendations."""
        mock_collab = MagicMock()
        mock_content = MagicMock()

        # Mock collaborative recommendations
        mock_collab.get_recommendations = AsyncMock(
            return_value=[
                {"artist_name": "Artist A", "similarity_score": 0.9},
                {"artist_name": "Artist B", "similarity_score": 0.8},
            ]
        )

        # Mock content-based recommendations
        mock_content.get_recommendations = AsyncMock(
            return_value=[
                {"artist_name": "Artist A", "similarity_score": 0.7},
                {"artist_name": "Artist C", "similarity_score": 0.6},
            ]
        )

        recommender = HybridRecommender(mock_collab, mock_content)

        result = await recommender._weighted_recommendations(
            "Test Artist",
            limit=2,
            diversity_boost=False,
        )

        assert len(result) <= 2
        assert all("artist_name" in r for r in result)
        assert all("similarity_score" in r for r in result)
        assert all("method_scores" in r for r in result)

    @pytest.mark.asyncio
    async def test_weighted_with_custom_weights(self) -> None:
        """Test weighted recommendations with custom weights."""
        mock_collab = MagicMock()
        mock_content = MagicMock()

        mock_collab.get_recommendations = AsyncMock(return_value=[{"artist_name": "Artist A", "similarity_score": 0.9}])
        mock_content.get_recommendations = AsyncMock(return_value=[{"artist_name": "Artist A", "similarity_score": 0.7}])

        recommender = HybridRecommender(mock_collab, mock_content)

        custom_weights = {"collaborative_filtering": 0.7, "content_based": 0.3}
        result = await recommender._weighted_recommendations(
            "Test Artist",
            limit=1,
            weights=custom_weights,
            diversity_boost=False,
        )

        assert len(result) == 1


class TestRankFusionRecommendations:
    """Test rank fusion recommendation strategy."""

    @pytest.mark.asyncio
    async def test_rank_fusion(self) -> None:
        """Test reciprocal rank fusion."""
        mock_collab = MagicMock()
        mock_content = MagicMock()

        # Mock recommendations with ranks
        mock_collab.get_recommendations = AsyncMock(
            return_value=[
                {"artist_name": "Artist A", "similarity_score": 0.9},
                {"artist_name": "Artist B", "similarity_score": 0.8},
            ]
        )
        mock_content.get_recommendations = AsyncMock(
            return_value=[
                {"artist_name": "Artist B", "similarity_score": 0.85},
                {"artist_name": "Artist C", "similarity_score": 0.75},
            ]
        )

        recommender = HybridRecommender(mock_collab, mock_content)

        result = await recommender._rank_fusion_recommendations("Test Artist", limit=2)

        assert len(result) <= 2
        assert all(r["method"] == "hybrid_rank_fusion" for r in result)

    @pytest.mark.asyncio
    async def test_rank_fusion_with_custom_k(self) -> None:
        """Test rank fusion with custom RRF parameter."""
        mock_collab = MagicMock()
        mock_content = MagicMock()

        mock_collab.get_recommendations = AsyncMock(return_value=[{"artist_name": "Artist A", "similarity_score": 0.9}])
        mock_content.get_recommendations = AsyncMock(return_value=[])

        recommender = HybridRecommender(mock_collab, mock_content)

        result = await recommender._rank_fusion_recommendations(
            "Test Artist",
            limit=1,
            rrf_k=100,
        )

        assert len(result) == 1


class TestCascadeRecommendations:
    """Test cascade recommendation strategy."""

    @pytest.mark.asyncio
    async def test_cascade_collaborative_then_content(self) -> None:
        """Test cascade: collaborative filter, content-based rank."""
        mock_collab = MagicMock()
        mock_content = MagicMock()

        # Mock collaborative filtering for candidates
        mock_collab.get_recommendations = AsyncMock(
            return_value=[
                {"artist_name": "Artist A", "similarity_score": 0.9},
                {"artist_name": "Artist B", "similarity_score": 0.8},
            ]
        )

        # Mock content-based similarity for re-ranking
        mock_content.get_similarity_score = MagicMock(side_effect=lambda artist, candidate: 0.7 if candidate == "Artist A" else 0.6)

        recommender = HybridRecommender(mock_collab, mock_content)

        result = await recommender._cascade_recommendations(
            "Test Artist",
            limit=2,
            filter_method="collaborative",
            rank_method="content",
        )

        assert len(result) <= 2
        assert all(r["filter_method"] == "collaborative" for r in result)
        assert all(r["rank_method"] == "content" for r in result)


class TestMixedRecommendations:
    """Test mixed recommendation strategy."""

    @pytest.mark.asyncio
    async def test_mixed_interleaving(self) -> None:
        """Test interleaving of recommendations."""
        mock_collab = MagicMock()
        mock_content = MagicMock()

        mock_collab.get_recommendations = AsyncMock(
            return_value=[
                {"artist_name": "Artist A", "similarity_score": 0.9},
                {"artist_name": "Artist B", "similarity_score": 0.8},
            ]
        )
        mock_content.get_recommendations = AsyncMock(
            return_value=[
                {"artist_name": "Artist C", "similarity_score": 0.85},
                {"artist_name": "Artist D", "similarity_score": 0.75},
            ]
        )

        recommender = HybridRecommender(mock_collab, mock_content)

        result = await recommender._mixed_recommendations("Test Artist", limit=4)

        assert len(result) <= 4
        # Should have items from both methods
        methods = {r["method"] for r in result}
        assert len(methods) > 0

    @pytest.mark.asyncio
    async def test_mixed_no_duplicates(self) -> None:
        """Test that mixed strategy avoids duplicates."""
        mock_collab = MagicMock()
        mock_content = MagicMock()

        # Same artist in both recommendations
        mock_collab.get_recommendations = AsyncMock(return_value=[{"artist_name": "Artist A", "similarity_score": 0.9}])
        mock_content.get_recommendations = AsyncMock(return_value=[{"artist_name": "Artist A", "similarity_score": 0.85}])

        recommender = HybridRecommender(mock_collab, mock_content)

        result = await recommender._mixed_recommendations("Test Artist", limit=2)

        # Should only have one instance of Artist A
        artist_names = [r["artist_name"] for r in result]
        assert artist_names.count("Artist A") == 1


class TestSwitchingRecommendations:
    """Test switching recommendation strategy."""

    @pytest.mark.asyncio
    async def test_switching_both_available(self) -> None:
        """Test switching when both methods have data."""
        mock_collab = MagicMock()
        mock_content = MagicMock()

        mock_collab.artist_to_index = {"Test Artist": 0}
        mock_content.artist_to_index = {"Test Artist": 0}

        recommender = HybridRecommender(mock_collab, mock_content)
        recommender._weighted_recommendations = AsyncMock(return_value=[])

        await recommender._switching_recommendations("Test Artist", limit=2)

        recommender._weighted_recommendations.assert_called_once()

    @pytest.mark.asyncio
    async def test_switching_collab_only(self) -> None:
        """Test switching to collaborative when only it has data."""
        mock_collab = MagicMock()
        mock_content = MagicMock()

        mock_collab.artist_to_index = {"Test Artist": 0}
        mock_content.artist_to_index = {}
        mock_collab.get_recommendations = AsyncMock(return_value=[{"artist_name": "Artist A", "similarity_score": 0.9}])

        recommender = HybridRecommender(mock_collab, mock_content)

        result = await recommender._switching_recommendations("Test Artist", limit=2)

        assert len(result) > 0
        assert all(r["method"] == "hybrid_switching_collaborative" for r in result)

    @pytest.mark.asyncio
    async def test_switching_content_only(self) -> None:
        """Test switching to content-based when only it has data."""
        mock_collab = MagicMock()
        mock_content = MagicMock()

        mock_collab.artist_to_index = {}
        mock_content.artist_to_index = {"Test Artist": 0}
        mock_content.get_recommendations = AsyncMock(return_value=[{"artist_name": "Artist A", "similarity_score": 0.9}])

        recommender = HybridRecommender(mock_collab, mock_content)

        result = await recommender._switching_recommendations("Test Artist", limit=2)

        assert all(r["method"] == "hybrid_switching_content" for r in result)

    @pytest.mark.asyncio
    async def test_switching_no_data(self) -> None:
        """Test switching when no data available."""
        mock_collab = MagicMock()
        mock_content = MagicMock()

        mock_collab.artist_to_index = {}
        mock_content.artist_to_index = {}

        recommender = HybridRecommender(mock_collab, mock_content)

        result = await recommender._switching_recommendations("Test Artist", limit=2)

        assert result == []


class TestNormalizeScores:
    """Test score normalization."""

    def test_normalize_empty_recommendations(self) -> None:
        """Test normalizing empty recommendations."""
        recommender = HybridRecommender(MagicMock(), MagicMock())

        result = recommender._normalize_scores([])

        assert result == {}

    def test_normalize_single_score(self) -> None:
        """Test normalizing single score."""
        recommender = HybridRecommender(MagicMock(), MagicMock())

        recs = [{"artist_name": "Artist A", "similarity_score": 0.5}]
        result = recommender._normalize_scores(recs)

        assert result["Artist A"] == 1.0

    def test_normalize_multiple_scores(self) -> None:
        """Test normalizing multiple scores."""
        recommender = HybridRecommender(MagicMock(), MagicMock())

        recs = [
            {"artist_name": "Artist A", "similarity_score": 1.0},
            {"artist_name": "Artist B", "similarity_score": 0.5},
            {"artist_name": "Artist C", "similarity_score": 0.0},
        ]

        result = recommender._normalize_scores(recs)

        # Min-max normalization: (value - min) / (max - min)
        assert result["Artist A"] == 1.0
        assert result["Artist B"] == 0.5
        assert result["Artist C"] == 0.0


class TestConfigurationMethods:
    """Test configuration methods."""

    def test_set_method_weights(self) -> None:
        """Test updating method weights."""
        recommender = HybridRecommender(MagicMock(), MagicMock())

        new_weights = {"collaborative_filtering": 0.6, "content_based": 0.4}
        recommender.set_method_weights(new_weights)

        assert recommender.method_weights["collaborative_filtering"] == 0.6
        assert recommender.method_weights["content_based"] == 0.4

    def test_set_diversity_parameters(self) -> None:
        """Test updating diversity parameters."""
        recommender = HybridRecommender(MagicMock(), MagicMock())

        recommender.set_diversity_parameters(diversity_weight=0.3, min_threshold=0.4)

        assert recommender.diversity_weight == 0.3
        assert recommender.min_diversity_threshold == 0.4
