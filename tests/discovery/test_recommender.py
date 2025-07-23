"""Tests for the music recommendation engine."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
import pytest_asyncio

from discovery.recommender import (
    MusicRecommender,
    RecommendationRequest,
    RecommendationResult,
    get_recommendations,
)


class TestMusicRecommender:
    """Test the MusicRecommender class."""

    @pytest_asyncio.fixture
    async def recommender(self, mock_neo4j_driver: Any) -> Any:
        """Create a MusicRecommender instance with mocked dependencies."""
        with patch("discovery.recommender.get_config") as mock_config:
            mock_config.return_value = MagicMock(
                neo4j_address="bolt://localhost:7687",
                neo4j_username="neo4j",
                neo4j_password="password",  # noqa: S106
            )

            recommender = MusicRecommender()
            recommender.driver = mock_neo4j_driver

            # Mock ML components
            recommender.embedding_model = MagicMock()
            recommender.embedding_model.encode.return_value = np.array([[0.1, 0.2, 0.3]])

            # Mock graph
            recommender.graph = MagicMock()
            recommender.graph.nodes.return_value = ["Miles Davis", "John Coltrane"]
            recommender.graph.neighbors.return_value = ["John Coltrane"]

            # Mock embeddings
            recommender.artist_embeddings = np.array([[0.1, 0.2, 0.3], [0.2, 0.3, 0.4]])
            recommender.artist_to_index = {"Miles Davis": 0, "John Coltrane": 1}
            recommender.index_to_artist = {0: "Miles Davis", 1: "John Coltrane"}

            return recommender

    async def test_initialize(self, recommender: Any) -> None:
        """Test recommender initialization."""
        with (
            patch.object(recommender, "_build_collaboration_graph") as mock_build,
            patch.object(recommender, "_generate_artist_embeddings") as mock_embeddings,
        ):
            await recommender.initialize()
            mock_build.assert_called_once()
            mock_embeddings.assert_called_once()

    async def test_get_similar_artists(self, recommender: Any) -> None:
        """Test getting similar artists."""
        # Mock _get_artist_info
        with patch.object(recommender, "_get_artist_info") as mock_get_info:
            mock_get_info.return_value = {
                "id": "123",
                "genres": ["Jazz"],
                "recent_release": "A Love Supreme",
                "recent_year": 1965,
            }

            recommendations = await recommender.get_similar_artists("Miles Davis", 5)

            assert isinstance(recommendations, list)
            assert len(recommendations) <= 5

    async def test_get_trending_music(self, recommender: Any, mock_neo4j_driver: Any) -> None:
        """Test getting trending music."""
        # Mock database results
        mock_result = AsyncMock()
        mock_records = [
            {
                "name": "Miles Davis",
                "id": "123",
                "genres": ["Jazz"],
                "release_count": 50,
                "recent_release": "Kind of Blue",
                "recent_year": 1959,
            }
        ]
        mock_result = (
            mock_neo4j_driver.session.return_value.__aenter__.return_value.run.return_value
        )
        mock_result.__aiter__.return_value = iter(mock_records)

        trending = await recommender.get_trending_music(["Jazz"], 10)

        assert isinstance(trending, list)
        assert len(trending) <= 10

    async def test_discovery_search(self, recommender: Any) -> None:
        """Test semantic discovery search."""
        with patch.object(recommender, "_get_artist_info") as mock_get_info:
            mock_get_info.return_value = {
                "id": "123",
                "genres": ["Jazz"],
                "recent_release": "Kind of Blue",
                "recent_year": 1959,
            }

            results = await recommender.discovery_search("cool jazz", 5)

            assert isinstance(results, list)
            assert len(results) <= 5

    async def test_get_artist_info(self, recommender: Any, mock_neo4j_driver: Any) -> None:
        """Test getting artist information."""
        # Mock database result
        mock_result = AsyncMock()
        mock_record = {
            "id": "123",
            "genres": ["Jazz"],
            "recent_release": "Kind of Blue",
            "recent_year": 1959,
        }
        mock_result.single.return_value = mock_record
        mock_neo4j_driver.session.return_value.__aenter__.return_value.run.return_value = (
            mock_result
        )

        info = await recommender._get_artist_info("Miles Davis")

        assert info is not None
        assert info["id"] == "123"
        assert "Jazz" in info["genres"]

    async def test_close(self, recommender: Any) -> None:
        """Test closing the recommender."""
        await recommender.close()
        if recommender.driver:
            recommender.driver.close.assert_called_once()


class TestRecommendationModels:
    """Test recommendation request/result models."""

    def test_recommendation_request_model(self) -> None:
        """Test RecommendationRequest model validation."""
        request = RecommendationRequest(
            artist_name="Miles Davis", recommendation_type="similar", limit=10
        )

        assert request.artist_name == "Miles Davis"
        assert request.recommendation_type == "similar"
        assert request.limit == 10

    def test_recommendation_request_defaults(self) -> None:
        """Test RecommendationRequest default values."""
        request = RecommendationRequest()

        assert request.limit == 10
        assert request.recommendation_type == "similar"

    def test_recommendation_result_model(self) -> None:
        """Test RecommendationResult model."""
        result = RecommendationResult(
            artist_name="John Coltrane",
            release_title="A Love Supreme",
            year=1965,
            genres=["Jazz"],
            similarity_score=0.85,
            explanation="Similar style",
            neo4j_id="123",
        )

        assert result.artist_name == "John Coltrane"
        assert result.similarity_score == 0.85
        assert "Jazz" in result.genres


class TestRecommendationAPI:
    """Test the recommendation API functions."""

    @pytest.mark.asyncio
    async def test_get_recommendations_similar(
        self, mock_recommender: Any, sample_recommendation_data: Any
    ) -> None:
        """Test getting similar artist recommendations."""
        with patch("discovery.recommender.recommender", mock_recommender):
            mock_recommender.get_similar_artists.return_value = sample_recommendation_data

            request = RecommendationRequest(
                artist_name="Miles Davis", recommendation_type="similar"
            )

            results = await get_recommendations(request)

            assert len(results) == 2
            assert results[0]["artist_name"] == "John Coltrane"

    @pytest.mark.asyncio
    async def test_get_recommendations_trending(
        self, mock_recommender: Any, sample_recommendation_data: Any
    ) -> None:
        """Test getting trending music recommendations."""
        with patch("discovery.recommender.recommender", mock_recommender):
            mock_recommender.get_trending_music.return_value = sample_recommendation_data

            request = RecommendationRequest(recommendation_type="trending", genres=["Jazz"])

            results = await get_recommendations(request)

            assert len(results) == 2

    @pytest.mark.asyncio
    async def test_get_recommendations_discovery(
        self, mock_recommender: Any, sample_recommendation_data: Any
    ) -> None:
        """Test discovery search recommendations."""
        with patch("discovery.recommender.recommender", mock_recommender):
            mock_recommender.discovery_search.return_value = sample_recommendation_data

            request = RecommendationRequest(
                artist_name="cool jazz", recommendation_type="discovery"
            )

            results = await get_recommendations(request)

            assert len(results) == 2

    @pytest.mark.asyncio
    async def test_get_recommendations_invalid_type(self, mock_recommender: Any) -> None:
        """Test handling invalid recommendation type."""
        with patch("discovery.recommender.recommender", mock_recommender):
            request = RecommendationRequest(recommendation_type="invalid")

            results = await get_recommendations(request)

            assert results == []
