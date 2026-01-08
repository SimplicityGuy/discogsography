"""Tests for ContentBasedFilter class."""

from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from scipy.sparse import csr_matrix

from discovery.content_based import ContentBasedFilter


class TestContentBasedFilterInit:
    """Test ContentBasedFilter initialization."""

    def test_initialization(self) -> None:
        """Test filter initializes with correct defaults."""
        mock_driver = MagicMock()
        filter_engine = ContentBasedFilter(mock_driver)

        assert filter_engine.driver == mock_driver
        assert filter_engine.artist_features == {}
        assert filter_engine.artist_to_index == {}
        assert filter_engine.index_to_artist == {}
        assert filter_engine.tfidf_vectorizer is None
        assert filter_engine.tfidf_matrix is None
        assert filter_engine.feature_weights["genres"] == 0.3
        assert filter_engine.feature_weights["styles"] == 0.25


class TestBuildFeatureVectors:
    """Test building feature vectors."""

    @pytest.mark.asyncio
    @patch("discovery.content_based.TfidfVectorizer")
    async def test_build_feature_vectors(self, mock_tfidf_class: MagicMock) -> None:
        """Test building feature vectors from artist data."""
        mock_driver = MagicMock()
        mock_session = AsyncMock()
        mock_result = AsyncMock()

        # Mock artist data from Neo4j
        mock_records = [
            {
                "artist_id": "1",
                "artist_name": "Artist A",
                "labels": ["Label1"],
                "genres": ["Rock"],
                "styles": ["Alternative"],
                "collaborators": ["Artist B"],
                "earliest_year": 1990,
                "latest_year": 2020,
            },
            {
                "artist_id": "2",
                "artist_name": "Artist B",
                "labels": ["Label1"],
                "genres": ["Rock", "Jazz"],
                "styles": ["Fusion"],
                "collaborators": ["Artist A"],
                "earliest_year": 1980,
                "latest_year": 2015,
            },
        ]

        async def async_iter(self):
            for record in mock_records:
                yield record

        mock_result.__aiter__ = async_iter
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__aenter__.return_value = mock_session
        mock_driver.session.return_value.__aexit__.return_value = None

        # Mock TF-IDF vectorizer
        mock_vectorizer = MagicMock()
        # Return sparse matrix (CSR format) instead of numpy array
        mock_matrix = csr_matrix(np.array([[0.5, 0.5], [0.6, 0.4]]))
        mock_vectorizer.fit_transform.return_value = mock_matrix
        mock_tfidf_class.return_value = mock_vectorizer

        filter_engine = ContentBasedFilter(mock_driver)
        await filter_engine.build_feature_vectors()

        # Verify mappings created
        assert "Artist A" in filter_engine.artist_to_index
        assert "Artist B" in filter_engine.artist_to_index
        assert len(filter_engine.index_to_artist) == 2

        # Verify features stored
        assert "Artist A" in filter_engine.artist_features
        assert filter_engine.artist_features["Artist A"]["genres"] == ["Rock"]

        # Verify TF-IDF was created
        assert filter_engine.tfidf_vectorizer is not None
        assert filter_engine.tfidf_matrix is not None

    @pytest.mark.asyncio
    async def test_build_feature_vectors_no_data(self) -> None:
        """Test building vectors with no artist data."""
        mock_driver = MagicMock()
        mock_session = AsyncMock()
        mock_result = AsyncMock()

        # Empty data
        async def async_iter(self):
            return
            yield  # Make it a generator

        mock_result.__aiter__ = async_iter
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__aenter__.return_value = mock_session
        mock_driver.session.return_value.__aexit__.return_value = None

        filter_engine = ContentBasedFilter(mock_driver)
        await filter_engine.build_feature_vectors()

        # Should handle empty data gracefully
        assert filter_engine.artist_to_index == {}
        assert filter_engine.tfidf_matrix is None


class TestGetRecommendations:
    """Test getting recommendations."""

    @pytest.mark.asyncio
    @patch("discovery.content_based.cosine_similarity")
    async def test_get_recommendations(self, mock_cosine: MagicMock) -> None:
        """Test getting recommendations for an artist."""
        mock_driver = MagicMock()
        filter_engine = ContentBasedFilter(mock_driver)

        # Setup feature vectors
        filter_engine.artist_to_index = {"Artist A": 0, "Artist B": 1, "Artist C": 2}
        filter_engine.index_to_artist = {0: "Artist A", 1: "Artist B", 2: "Artist C"}
        filter_engine.tfidf_matrix = np.array([[1.0, 0.0], [0.8, 0.2], [0.1, 0.9]])

        # Mock similarity scores
        mock_cosine.return_value = np.array([[1.0, 0.9, 0.3]])

        result = await filter_engine.get_recommendations("Artist A", limit=2)

        assert len(result) == 2
        assert result[0]["artist_name"] == "Artist B"
        assert result[0]["similarity_score"] == 0.9
        assert result[0]["method"] == "content_based"

    @pytest.mark.asyncio
    async def test_get_recommendations_no_matrix(self) -> None:
        """Test getting recommendations with no matrix built."""
        mock_driver = MagicMock()
        filter_engine = ContentBasedFilter(mock_driver)

        result = await filter_engine.get_recommendations("Artist A")

        assert result == []

    @pytest.mark.asyncio
    async def test_get_recommendations_unknown_artist(self) -> None:
        """Test getting recommendations for unknown artist."""
        mock_driver = MagicMock()
        filter_engine = ContentBasedFilter(mock_driver)

        filter_engine.tfidf_matrix = np.array([[1.0]])
        filter_engine.artist_to_index = {}

        result = await filter_engine.get_recommendations("Unknown Artist")

        assert result == []


class TestBatchRecommendations:
    """Test batch recommendations."""

    @pytest.mark.asyncio
    async def test_get_batch_recommendations(self) -> None:
        """Test getting recommendations for multiple artists."""
        mock_driver = MagicMock()
        filter_engine = ContentBasedFilter(mock_driver)

        # Mock get_recommendations to return empty lists
        filter_engine.get_recommendations = AsyncMock(return_value=[])

        result = await filter_engine.get_batch_recommendations(["Artist A", "Artist B"], limit=5)

        assert "Artist A" in result
        assert "Artist B" in result
        assert filter_engine.get_recommendations.call_count == 2


class TestSimilarityScore:
    """Test similarity score calculation."""

    @patch("discovery.content_based.cosine_similarity")
    def test_get_similarity_score(self, mock_cosine: MagicMock) -> None:
        """Test getting similarity score between two artists."""
        mock_driver = MagicMock()
        filter_engine = ContentBasedFilter(mock_driver)

        filter_engine.artist_to_index = {"Artist A": 0, "Artist B": 1}
        filter_engine.tfidf_matrix = np.array([[1.0, 0.0], [0.8, 0.2]])

        mock_cosine.return_value = np.array([[0.85]])

        score = filter_engine.get_similarity_score("Artist A", "Artist B")

        assert score == 0.85

    def test_get_similarity_score_no_matrix(self) -> None:
        """Test similarity score with no matrix."""
        mock_driver = MagicMock()
        filter_engine = ContentBasedFilter(mock_driver)

        score = filter_engine.get_similarity_score("Artist A", "Artist B")

        assert score == 0.0

    def test_get_similarity_score_unknown_artist(self) -> None:
        """Test similarity score with unknown artist."""
        mock_driver = MagicMock()
        filter_engine = ContentBasedFilter(mock_driver)

        filter_engine.tfidf_matrix = np.array([[1.0]])
        filter_engine.artist_to_index = {"Artist A": 0}

        score = filter_engine.get_similarity_score("Artist A", "Unknown")

        assert score == 0.0


class TestFeatureImportance:
    """Test feature importance extraction."""

    def test_get_feature_importance(self) -> None:
        """Test getting important features for an artist."""
        mock_driver = MagicMock()
        filter_engine = ContentBasedFilter(mock_driver)

        filter_engine.artist_to_index = {"Artist A": 0}
        filter_engine.tfidf_matrix = np.array([[0.5, 0.8, 0.3]])

        mock_vectorizer = MagicMock()
        mock_vectorizer.get_feature_names_out.return_value = np.array(["rock", "alternative", "indie"])
        filter_engine.tfidf_vectorizer = mock_vectorizer

        features = filter_engine.get_feature_importance("Artist A", top_n=2)

        assert len(features) == 2
        assert features[0]["feature"] == "alternative"
        assert features[0]["importance"] == 0.8

    def test_get_feature_importance_no_matrix(self) -> None:
        """Test feature importance with no matrix."""
        mock_driver = MagicMock()
        filter_engine = ContentBasedFilter(mock_driver)

        features = filter_engine.get_feature_importance("Artist A")

        assert features == []


class TestSimilarByAttributes:
    """Test getting similar artists by attributes."""

    @pytest.mark.asyncio
    @patch("discovery.content_based.cosine_similarity")
    async def test_get_similar_by_attributes(self, mock_cosine: MagicMock) -> None:
        """Test getting artists similar to specified attributes."""
        mock_driver = MagicMock()
        filter_engine = ContentBasedFilter(mock_driver)

        filter_engine.index_to_artist = {0: "Artist A", 1: "Artist B"}
        filter_engine.tfidf_matrix = np.array([[1.0, 0.0], [0.8, 0.2]])

        mock_vectorizer = MagicMock()
        mock_sparse = MagicMock()
        mock_sparse.toarray.return_value = np.array([[0.9, 0.1]])
        mock_vectorizer.transform.return_value = mock_sparse
        filter_engine.tfidf_vectorizer = mock_vectorizer

        mock_cosine.return_value = np.array([[0.95, 0.75]])

        result = await filter_engine.get_similar_by_attributes(genres=["Rock"], styles=["Alternative"], limit=2)

        assert len(result) == 2
        assert result[0]["artist_name"] == "Artist A"
        assert result[0]["method"] == "content_based_attributes"

    @pytest.mark.asyncio
    async def test_get_similar_by_attributes_no_matrix(self) -> None:
        """Test attribute similarity with no matrix."""
        mock_driver = MagicMock()
        filter_engine = ContentBasedFilter(mock_driver)

        result = await filter_engine.get_similar_by_attributes(genres=["Rock"])

        assert result == []

    @pytest.mark.asyncio
    async def test_get_similar_by_attributes_no_params(self) -> None:
        """Test attribute similarity with no parameters."""
        mock_driver = MagicMock()
        filter_engine = ContentBasedFilter(mock_driver)

        filter_engine.tfidf_matrix = np.array([[1.0]])
        filter_engine.tfidf_vectorizer = MagicMock()

        result = await filter_engine.get_similar_by_attributes()

        assert result == []
