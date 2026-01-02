"""Unit tests for Discovery service recommender functionality."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import networkx as nx
import numpy as np
import pytest
from pydantic import ValidationError

from discovery.recommender import (
    MusicRecommender,
    RecommendationRequest,
    RecommendationResult,
    get_recommendations,
    get_recommender_instance,
)


class TestRecommendationRequest:
    """Test the RecommendationRequest model."""

    def test_recommendation_request_minimal(self) -> None:
        """Test RecommendationRequest with minimal data."""
        request = RecommendationRequest()
        assert request.artist_name is None
        assert request.release_title is None
        assert request.genres is None
        assert request.year_range is None
        assert request.limit == 10
        assert request.recommendation_type == "similar"

    def test_recommendation_request_full(self) -> None:
        """Test RecommendationRequest with all fields."""
        request = RecommendationRequest(
            artist_name="Miles Davis",
            release_title="Kind of Blue",
            genres=["Jazz", "Bebop"],
            year_range=(1950, 1970),
            limit=20,
            recommendation_type="trending",
        )
        assert request.artist_name == "Miles Davis"
        assert request.release_title == "Kind of Blue"
        assert request.genres == ["Jazz", "Bebop"]
        assert request.year_range == (1950, 1970)
        assert request.limit == 20
        assert request.recommendation_type == "trending"

    def test_recommendation_request_validation(self) -> None:
        """Test RecommendationRequest validation."""
        # Valid types
        for rec_type in ["similar", "trending", "discovery"]:
            request = RecommendationRequest(recommendation_type=rec_type)
            assert request.recommendation_type == rec_type


class TestRecommendationResult:
    """Test the RecommendationResult model."""

    def test_recommendation_result_minimal(self) -> None:
        """Test RecommendationResult with minimal required fields."""
        result = RecommendationResult(
            artist_name="Test Artist",
            similarity_score=0.85,
            explanation="Test explanation",
            neo4j_id="12345",
        )
        assert result.artist_name == "Test Artist"
        assert result.release_title is None
        assert result.year is None
        assert result.genres == []
        assert result.similarity_score == 0.85
        assert result.explanation == "Test explanation"
        assert result.neo4j_id == "12345"

    def test_recommendation_result_full(self) -> None:
        """Test RecommendationResult with all fields."""
        result = RecommendationResult(
            artist_name="Miles Davis",
            release_title="Kind of Blue",
            year=1959,
            genres=["Jazz", "Modal"],
            similarity_score=0.95,
            explanation="Classic jazz album",
            neo4j_id="67890",
        )
        assert result.artist_name == "Miles Davis"
        assert result.release_title == "Kind of Blue"
        assert result.year == 1959
        assert result.genres == ["Jazz", "Modal"]
        assert result.similarity_score == 0.95
        assert result.explanation == "Classic jazz album"
        assert result.neo4j_id == "67890"

    def test_recommendation_result_validation_missing_fields(self) -> None:
        """Test RecommendationResult validation with missing required fields."""
        with pytest.raises(ValidationError):
            RecommendationResult(  # type: ignore[call-arg]
                artist_name="Test"
                # Missing similarity_score, explanation, neo4j_id
            )


class TestMusicRecommenderInit:
    """Test MusicRecommender initialization."""

    def test_music_recommender_init(self) -> None:
        """Test MusicRecommender initialization."""
        with patch("discovery.recommender.get_config"):
            recommender = MusicRecommender()

            assert recommender.driver is None
            assert recommender.graph is None
            assert recommender.embedding_model is None
            assert recommender.tfidf_vectorizer is None
            assert recommender.artist_embeddings is None
            assert recommender.artist_to_index == {}
            assert recommender.index_to_artist == {}

    @pytest.mark.asyncio
    async def test_music_recommender_initialize_with_onnx(self) -> None:
        """Test MusicRecommender initialization with ONNX model."""
        with (
            patch("discovery.recommender.get_config") as mock_config,
            patch("discovery.recommender.AsyncGraphDatabase.driver") as mock_driver,
            patch("discovery.recommender.ONNX_AVAILABLE", True),
            patch("pathlib.Path") as mock_path,
            patch("discovery.recommender.ONNXSentenceTransformer") as mock_onnx,
        ):
            mock_config.return_value = MagicMock()
            mock_driver.return_value = AsyncMock()

            # Mock ONNX path exists
            mock_path_instance = MagicMock()
            mock_path_instance.exists.return_value = True
            mock_path.return_value = mock_path_instance

            recommender = MusicRecommender()
            recommender._build_collaboration_graph = AsyncMock()  # type: ignore[method-assign]
            recommender._generate_artist_embeddings = AsyncMock()  # type: ignore[method-assign]

            await recommender.initialize()

            assert recommender.driver is not None
            mock_onnx.assert_called_once()
            recommender._build_collaboration_graph.assert_called_once()  # type: ignore[attr-defined]
            recommender._generate_artist_embeddings.assert_called_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_music_recommender_initialize_with_pytorch(self) -> None:
        """Test MusicRecommender initialization with PyTorch model fallback."""
        with (
            patch("discovery.recommender.get_config") as mock_config,
            patch("discovery.recommender.AsyncGraphDatabase.driver") as mock_driver,
            patch("discovery.recommender.ONNX_AVAILABLE", False),
            patch("discovery.recommender.SentenceTransformer") as mock_st,
        ):
            mock_config.return_value = MagicMock()
            mock_driver.return_value = AsyncMock()
            mock_st.return_value = MagicMock()

            recommender = MusicRecommender()
            recommender._build_collaboration_graph = AsyncMock()  # type: ignore[method-assign]
            recommender._generate_artist_embeddings = AsyncMock()  # type: ignore[method-assign]

            await recommender.initialize()

            assert recommender.driver is not None
            mock_st.assert_called_once_with("all-MiniLM-L6-v2")
            recommender._build_collaboration_graph.assert_called_once()  # type: ignore[attr-defined]
            recommender._generate_artist_embeddings.assert_called_once()  # type: ignore[attr-defined]


class TestBuildCollaborationGraph:
    """Test building the collaboration graph."""

    @pytest.mark.asyncio
    async def test_build_collaboration_graph_success(self) -> None:
        """Test successful collaboration graph building."""
        with patch("discovery.recommender.get_config") as mock_config:
            mock_config.return_value = MagicMock()

            # Create mock Neo4j session and results
            mock_session = AsyncMock()
            mock_result = AsyncMock()

            # Mock collaboration data
            async def mock_records(self: Any) -> Any:  # noqa: ARG001
                for record in [
                    {"artist1": "Artist A", "artist2": "Artist B", "collaborations": 5},
                    {"artist1": "Artist B", "artist2": "Artist C", "collaborations": 3},
                    {"artist1": "Artist A", "artist2": "Artist C", "collaborations": 2},
                ]:
                    yield record

            mock_result.__aiter__ = mock_records
            mock_session.run.return_value = mock_result

            # Create proper async context manager mock
            mock_context_manager = AsyncMock()
            mock_context_manager.__aenter__.return_value = mock_session
            mock_context_manager.__aexit__.return_value = None

            mock_driver = MagicMock()
            mock_driver.session.return_value = mock_context_manager

            recommender = MusicRecommender()
            recommender.driver = mock_driver

            await recommender._build_collaboration_graph()

            assert recommender.graph is not None
            assert isinstance(recommender.graph, nx.Graph)
            assert recommender.graph.number_of_nodes() == 3
            assert recommender.graph.number_of_edges() == 3
            assert recommender.graph.has_edge("Artist A", "Artist B")
            assert recommender.graph["Artist A"]["Artist B"]["weight"] == 5

    @pytest.mark.asyncio
    async def test_build_collaboration_graph_no_driver(self) -> None:
        """Test collaboration graph building fails without driver."""
        with patch("discovery.recommender.get_config") as mock_config:
            mock_config.return_value = MagicMock()
            recommender = MusicRecommender()
            recommender.driver = None

            with pytest.raises(AssertionError):
                await recommender._build_collaboration_graph()


class TestGenerateArtistEmbeddings:
    """Test generating artist embeddings."""

    @pytest.mark.asyncio
    async def test_generate_artist_embeddings_success(self) -> None:
        """Test successful artist embedding generation."""
        with patch("discovery.recommender.get_config") as mock_config:
            mock_config.return_value = MagicMock()

            # Create mock Neo4j session and results
            mock_session = AsyncMock()
            mock_result = AsyncMock()

            # Mock artist data
            async def mock_records(self: Any) -> Any:  # noqa: ARG001
                for record in [
                    {
                        "name": "Artist A",
                        "profile": "Jazz musician",
                        "genres": ["Jazz", "Bebop"],
                        "styles": ["Cool Jazz"],
                    },
                    {
                        "name": "Artist B",
                        "profile": "Rock band",
                        "genres": ["Rock"],
                        "styles": ["Hard Rock"],
                    },
                ]:
                    yield record

            mock_result.__aiter__ = mock_records
            mock_session.run.return_value = mock_result

            # Create proper async context manager mock
            mock_context_manager = AsyncMock()
            mock_context_manager.__aenter__.return_value = mock_session
            mock_context_manager.__aexit__.return_value = None

            mock_driver = MagicMock()
            mock_driver.session.return_value = mock_context_manager

            # Mock embedding model
            mock_model = MagicMock()
            mock_model.encode.return_value = np.array([[0.1, 0.2], [0.3, 0.4]])

            recommender = MusicRecommender()
            recommender.driver = mock_driver
            recommender.embedding_model = mock_model

            await recommender._generate_artist_embeddings()

            assert recommender.artist_embeddings is not None
            assert recommender.artist_embeddings.shape == (2, 2)
            assert len(recommender.artist_to_index) == 2
            assert len(recommender.index_to_artist) == 2
            assert recommender.artist_to_index["Artist A"] == 0
            assert recommender.index_to_artist[0] == "Artist A"

    @pytest.mark.asyncio
    async def test_generate_artist_embeddings_no_data(self) -> None:
        """Test embedding generation with no artist data."""
        with patch("discovery.recommender.get_config") as mock_config:
            mock_config.return_value = MagicMock()

            # Create mock Neo4j session with no results
            mock_session = AsyncMock()
            mock_result = AsyncMock()

            async def mock_records(self: Any) -> Any:  # noqa: ARG001
                return
                yield  # pragma: no cover

            mock_result.__aiter__ = mock_records
            mock_session.run.return_value = mock_result

            # Create proper async context manager mock
            mock_context_manager = AsyncMock()
            mock_context_manager.__aenter__.return_value = mock_session
            mock_context_manager.__aexit__.return_value = None

            mock_driver = MagicMock()
            mock_driver.session.return_value = mock_context_manager

            recommender = MusicRecommender()
            recommender.driver = mock_driver
            recommender.embedding_model = MagicMock()

            await recommender._generate_artist_embeddings()

            # Should handle empty data gracefully
            assert recommender.artist_embeddings is None


class TestGetSimilarArtists:
    """Test getting similar artists."""

    @pytest.mark.asyncio
    async def test_get_similar_artists_no_graph(self) -> None:
        """Test getting similar artists with no graph."""
        with patch("discovery.recommender.get_config") as mock_config:
            mock_config.return_value = MagicMock()
            recommender = MusicRecommender()
            recommender.graph = None

            results = await recommender.get_similar_artists("Test Artist", limit=5)
            assert results == []

    @pytest.mark.asyncio
    async def test_get_similar_artists_with_graph(self) -> None:
        """Test getting similar artists using graph data."""
        with patch("discovery.recommender.get_config") as mock_config:
            mock_config.return_value = MagicMock()
            recommender = MusicRecommender()

            # Create test graph
            graph = nx.Graph()
            graph.add_edge("Artist A", "Common 1", weight=1)
            graph.add_edge("Artist A", "Common 2", weight=1)
            graph.add_edge("Artist B", "Common 1", weight=1)
            graph.add_edge("Artist B", "Common 2", weight=1)
            graph.add_edge("Artist C", "Common 1", weight=1)

            recommender.graph = graph
            # Need non-empty embeddings to pass the check
            recommender.artist_embeddings = np.array([[0.1], [0.2]])

            # Mock _get_artist_info
            recommender._get_artist_info = AsyncMock(  # type: ignore[method-assign]
                return_value={
                    "id": "123",
                    "genres": ["Jazz"],
                    "recent_release": "Test Album",
                    "recent_year": 2020,
                }
            )

            results = await recommender.get_similar_artists("Artist A", limit=4)

            # Should find Artist B as most similar (2 shared neighbors)
            assert len(results) > 0
            assert results[0].artist_name == "Artist B"
            assert "shared collaborators" in results[0].explanation


class TestGetTrendingMusic:
    """Test getting trending music."""

    @pytest.mark.asyncio
    async def test_get_trending_music_success(self) -> None:
        """Test successful trending music retrieval."""
        with patch("discovery.recommender.get_config") as mock_config:
            mock_config.return_value = MagicMock()

            # Create mock Neo4j session
            mock_session = AsyncMock()
            mock_result = AsyncMock()

            async def mock_records(self: Any) -> Any:  # noqa: ARG001
                for record in [
                    {
                        "name": "Trending Artist",
                        "id": "123",
                        "genres": ["Pop"],
                        "release_count": 50,
                        "recent_release": "Latest Hit",
                        "recent_year": 2024,
                    }
                ]:
                    yield record

            mock_result.__aiter__ = mock_records
            mock_session.run.return_value = mock_result

            # Create proper async context manager mock
            mock_context_manager = AsyncMock()
            mock_context_manager.__aenter__.return_value = mock_session
            mock_context_manager.__aexit__.return_value = None

            mock_driver = MagicMock()
            mock_driver.session.return_value = mock_context_manager

            recommender = MusicRecommender()
            recommender.driver = mock_driver

            results = await recommender.get_trending_music(limit=10)

            assert len(results) == 1
            assert results[0].artist_name == "Trending Artist"
            assert results[0].release_title == "Latest Hit"
            assert results[0].year == 2024
            assert results[0].similarity_score == 0.5  # 50 / 100
            assert "50 releases" in results[0].explanation


class TestDiscoverySearch:
    """Test discovery search functionality."""

    @pytest.mark.asyncio
    async def test_discovery_search_success(self) -> None:
        """Test successful discovery search."""
        with patch("discovery.recommender.get_config") as mock_config:
            mock_config.return_value = MagicMock()

            # Mock embedding model
            mock_model = MagicMock()
            mock_model.encode.return_value = np.array([[0.5, 0.5]])

            recommender = MusicRecommender()
            recommender.embedding_model = mock_model
            recommender.artist_embeddings = np.array([[0.6, 0.4], [0.3, 0.7]])
            recommender.index_to_artist = {0: "Artist A", 1: "Artist B"}

            # Mock _get_artist_info
            recommender._get_artist_info = AsyncMock(  # type: ignore[method-assign]
                return_value={
                    "id": "123",
                    "genres": ["Jazz"],
                    "recent_release": "Test Album",
                    "recent_year": 2020,
                }
            )

            results = await recommender.discovery_search("jazz music", limit=2)

            assert len(results) == 2
            assert "Semantic match" in results[0].explanation

    @pytest.mark.asyncio
    async def test_discovery_search_no_model(self) -> None:
        """Test discovery search with no embedding model."""
        with patch("discovery.recommender.get_config") as mock_config:
            mock_config.return_value = MagicMock()
            recommender = MusicRecommender()
            recommender.embedding_model = None

            results = await recommender.discovery_search("test query", limit=5)
            assert results == []


class TestGetArtistInfo:
    """Test getting artist information."""

    @pytest.mark.asyncio
    async def test_get_artist_info_success(self) -> None:
        """Test successful artist info retrieval."""
        with patch("discovery.recommender.get_config") as mock_config:
            mock_config.return_value = MagicMock()

            # Create mock Neo4j session
            mock_session = AsyncMock()
            mock_result = AsyncMock()
            mock_result.single.return_value = {
                "id": "12345",
                "genres": ["Jazz", "Bebop"],
                "recent_release": "Kind of Blue",
                "recent_year": 1959,
            }
            mock_session.run.return_value = mock_result

            # Create proper async context manager mock
            mock_context_manager = AsyncMock()
            mock_context_manager.__aenter__.return_value = mock_session
            mock_context_manager.__aexit__.return_value = None

            mock_driver = MagicMock()
            mock_driver.session.return_value = mock_context_manager

            recommender = MusicRecommender()
            recommender.driver = mock_driver

            info = await recommender._get_artist_info("Miles Davis")

            assert info is not None
            assert info["id"] == "12345"
            assert info["genres"] == ["Jazz", "Bebop"]
            assert info["recent_release"] == "Kind of Blue"
            assert info["recent_year"] == 1959

    @pytest.mark.asyncio
    async def test_get_artist_info_not_found(self) -> None:
        """Test artist info retrieval when artist not found."""
        with patch("discovery.recommender.get_config") as mock_config:
            mock_config.return_value = MagicMock()

            # Create mock Neo4j session with no results
            mock_session = AsyncMock()
            mock_result = AsyncMock()
            mock_result.single.return_value = None
            mock_session.run.return_value = mock_result

            # Create proper async context manager mock
            mock_context_manager = AsyncMock()
            mock_context_manager.__aenter__.return_value = mock_session
            mock_context_manager.__aexit__.return_value = None

            mock_driver = MagicMock()
            mock_driver.session.return_value = mock_context_manager

            recommender = MusicRecommender()
            recommender.driver = mock_driver

            info = await recommender._get_artist_info("Unknown Artist")
            assert info is None


class TestCloseAndGlobalInstance:
    """Test close method and global instance management."""

    @pytest.mark.asyncio
    async def test_close_with_driver(self) -> None:
        """Test closing recommender with active driver."""
        with patch("discovery.recommender.get_config") as mock_config:
            mock_config.return_value = MagicMock()
            mock_driver = AsyncMock()

            recommender = MusicRecommender()
            recommender.driver = mock_driver

            await recommender.close()
            mock_driver.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_without_driver(self) -> None:
        """Test closing recommender without driver."""
        with patch("discovery.recommender.get_config") as mock_config:
            mock_config.return_value = MagicMock()
            recommender = MusicRecommender()
            recommender.driver = None

            # Should not raise error
            await recommender.close()

    def test_get_recommender_instance(self) -> None:
        """Test global recommender instance management."""
        with (
            patch("discovery.recommender.get_config") as mock_config,
            patch("discovery.recommender.recommender", None),
        ):
            mock_config.return_value = MagicMock()

            instance1 = get_recommender_instance()
            instance2 = get_recommender_instance()

            # Should return same instance
            assert instance1 is instance2
            assert isinstance(instance1, MusicRecommender)


class TestGetRecommendations:
    """Test the main get_recommendations function."""

    @pytest.mark.asyncio
    async def test_get_recommendations_similar(self) -> None:
        """Test getting similar artist recommendations."""
        with patch("discovery.recommender.get_recommender_instance") as mock_getter:
            mock_instance = AsyncMock()
            mock_instance.get_similar_artists.return_value = [
                RecommendationResult(
                    artist_name="Similar Artist",
                    similarity_score=0.9,
                    explanation="Test",
                    neo4j_id="123",
                )
            ]
            mock_getter.return_value = mock_instance

            request = RecommendationRequest(artist_name="Test Artist", recommendation_type="similar", limit=5)
            results = await get_recommendations(request)

            assert len(results) == 1
            assert results[0].artist_name == "Similar Artist"
            mock_instance.get_similar_artists.assert_called_once_with("Test Artist", 5)

    @pytest.mark.asyncio
    async def test_get_recommendations_trending(self) -> None:
        """Test getting trending recommendations."""
        with patch("discovery.recommender.get_recommender_instance") as mock_getter:
            mock_instance = AsyncMock()
            mock_instance.get_trending_music.return_value = [
                RecommendationResult(
                    artist_name="Trending Artist",
                    similarity_score=0.8,
                    explanation="Test",
                    neo4j_id="456",
                )
            ]
            mock_getter.return_value = mock_instance

            request = RecommendationRequest(recommendation_type="trending", genres=["Pop"], limit=10)
            results = await get_recommendations(request)

            assert len(results) == 1
            assert results[0].artist_name == "Trending Artist"
            mock_instance.get_trending_music.assert_called_once_with(["Pop"], 10)

    @pytest.mark.asyncio
    async def test_get_recommendations_discovery(self) -> None:
        """Test discovery search recommendations."""
        with patch("discovery.recommender.get_recommender_instance") as mock_getter:
            mock_instance = AsyncMock()
            mock_instance.discovery_search.return_value = [
                RecommendationResult(
                    artist_name="Discovered Artist",
                    similarity_score=0.85,
                    explanation="Test",
                    neo4j_id="789",
                )
            ]
            mock_getter.return_value = mock_instance

            request = RecommendationRequest(artist_name="jazz fusion", recommendation_type="discovery", limit=15)
            results = await get_recommendations(request)

            assert len(results) == 1
            assert results[0].artist_name == "Discovered Artist"
            mock_instance.discovery_search.assert_called_once_with("jazz fusion", 15)

    @pytest.mark.asyncio
    async def test_get_recommendations_invalid_type(self) -> None:
        """Test recommendations with invalid type returns empty."""
        with patch("discovery.recommender.get_recommender_instance") as mock_getter:
            mock_instance = AsyncMock()
            mock_getter.return_value = mock_instance

            request = RecommendationRequest(recommendation_type="similar", limit=5)
            # No artist_name provided for similar type
            results = await get_recommendations(request)

            assert results == []
