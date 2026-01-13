"""Tests for CollaborativeFilter class."""

from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest
from scipy.sparse import csr_matrix

from discovery.collaborative_filtering import CollaborativeFilter


class TestCollaborativeFilterInit:
    """Test CollaborativeFilter initialization."""

    def test_initialization(self) -> None:
        """Test filter initializes with correct default values."""
        mock_driver = MagicMock()
        filter_engine = CollaborativeFilter(mock_driver)

        assert filter_engine.driver == mock_driver
        assert filter_engine.item_similarity_matrix is None
        assert filter_engine.artist_to_index == {}
        assert filter_engine.index_to_artist == {}
        assert filter_engine.co_occurrence_matrix is None
        assert filter_engine.artist_features == {}

        # Verify inverted indices initialized
        assert filter_engine.label_to_artists == {}
        assert filter_engine.genre_to_artists == {}
        assert filter_engine.style_to_artists == {}
        assert filter_engine.collaborator_to_artists == {}


class TestBuildCooccurrenceMatrix:
    """Test co-occurrence matrix building."""

    @pytest.mark.asyncio
    async def test_build_matrix_with_artist_data(self) -> None:
        """Test building co-occurrence matrix with artist data."""
        mock_driver = MagicMock()
        mock_session = AsyncMock()

        # Mock count query result
        mock_count_result = AsyncMock()
        mock_count_single = AsyncMock()
        mock_count_single.__getitem__ = MagicMock(return_value=2)  # total count
        mock_count_result.single = AsyncMock(return_value=mock_count_single)

        # Mock artist data query result
        mock_data_result = AsyncMock()
        mock_records = [
            {
                "artist_id": "1",
                "artist_name": "Artist A",
                "labels": ["Label1"],
                "genres": ["Rock"],
                "styles": ["Alternative"],
                "collaborators": ["Artist B"],
            },
            {
                "artist_id": "2",
                "artist_name": "Artist B",
                "labels": ["Label1"],
                "genres": ["Rock"],
                "styles": ["Alternative"],  # Same style as Artist A to trigger line 123
                "collaborators": ["Artist A"],
            },
        ]

        # Setup async iteration for data query
        async def async_iter(self):
            for record in mock_records:
                yield record

        mock_data_result.__aiter__ = async_iter

        # Setup session.run to return different results for each call
        mock_session.run.side_effect = [mock_count_result, mock_data_result]
        mock_driver.session.return_value.__aenter__.return_value = mock_session
        mock_driver.session.return_value.__aexit__.return_value = None

        filter_engine = CollaborativeFilter(mock_driver)
        await filter_engine.build_cooccurrence_matrix()

        # Verify mappings created
        assert "Artist A" in filter_engine.artist_to_index
        assert "Artist B" in filter_engine.artist_to_index
        assert len(filter_engine.index_to_artist) == 2

        # Verify features stored
        assert "Artist A" in filter_engine.artist_features
        assert filter_engine.artist_features["Artist A"]["labels"] == ["Label1"]

        # Verify matrices created
        assert filter_engine.co_occurrence_matrix is not None
        assert filter_engine.item_similarity_matrix is not None

    @pytest.mark.asyncio
    async def test_build_matrix_no_data(self) -> None:
        """Test building matrix with no artist data."""
        mock_driver = MagicMock()
        mock_session = AsyncMock()

        # Mock count query result with zero artists
        mock_count_result = AsyncMock()
        mock_count_single = AsyncMock()
        mock_count_single.__getitem__ = MagicMock(return_value=0)  # zero total count
        mock_count_result.single = AsyncMock(return_value=mock_count_single)

        # Mock empty data query result
        mock_data_result = AsyncMock()

        # Empty data iterator
        async def async_iter(self):
            return
            yield  # Make it a generator

        mock_data_result.__aiter__ = async_iter

        # Setup session.run to return different results for each call
        mock_session.run.side_effect = [mock_count_result, mock_data_result]
        mock_driver.session.return_value.__aenter__.return_value = mock_session
        mock_driver.session.return_value.__aexit__.return_value = None

        filter_engine = CollaborativeFilter(mock_driver)
        await filter_engine.build_cooccurrence_matrix()

        # Should handle empty data gracefully
        assert filter_engine.artist_to_index == {}


class TestGetRecommendations:
    """Test getting recommendations."""

    @pytest.mark.asyncio
    async def test_get_recommendations_with_matrix(self) -> None:
        """Test getting recommendations when matrix is built."""
        mock_driver = MagicMock()
        filter_engine = CollaborativeFilter(mock_driver)

        # Setup test data
        filter_engine.artist_to_index = {"Artist A": 0, "Artist B": 1, "Artist C": 2}
        filter_engine.index_to_artist = {0: "Artist A", 1: "Artist B", 2: "Artist C"}

        # Create mock similarity matrix
        similarity_data = np.array([[1.0, 0.8, 0.3], [0.8, 1.0, 0.5], [0.3, 0.5, 1.0]])
        filter_engine.item_similarity_matrix = csr_matrix(similarity_data)

        results = await filter_engine.get_recommendations("Artist A", limit=2)

        assert len(results) <= 2
        assert all("artist_name" in r for r in results)
        assert all("similarity_score" in r for r in results)
        assert all(r["artist_name"] != "Artist A" for r in results)  # Should not recommend self

    @pytest.mark.asyncio
    async def test_get_recommendations_no_matrix(self) -> None:
        """Test getting recommendations when matrix not built."""
        mock_driver = MagicMock()
        filter_engine = CollaborativeFilter(mock_driver)

        results = await filter_engine.get_recommendations("Artist A")

        assert results == []

    @pytest.mark.asyncio
    async def test_get_recommendations_unknown_artist(self) -> None:
        """Test getting recommendations for unknown artist."""
        mock_driver = MagicMock()
        filter_engine = CollaborativeFilter(mock_driver)

        filter_engine.artist_to_index = {"Artist A": 0}
        filter_engine.item_similarity_matrix = csr_matrix(np.array([[1.0]]))

        results = await filter_engine.get_recommendations("Unknown Artist")

        assert results == []


class TestBatchRecommendations:
    """Test batch recommendation functionality."""

    @pytest.mark.asyncio
    async def test_get_batch_recommendations(self) -> None:
        """Test getting recommendations for multiple artists."""
        mock_driver = MagicMock()
        filter_engine = CollaborativeFilter(mock_driver)

        # Setup test data
        filter_engine.artist_to_index = {"Artist A": 0, "Artist B": 1}
        filter_engine.index_to_artist = {0: "Artist A", 1: "Artist B"}
        similarity_data = np.array([[1.0, 0.9], [0.9, 1.0]])
        filter_engine.item_similarity_matrix = csr_matrix(similarity_data)

        results = await filter_engine.get_batch_recommendations(["Artist A", "Artist B"])

        assert "Artist A" in results
        assert "Artist B" in results
        assert isinstance(results["Artist A"], list)


class TestSimilarityScore:
    """Test similarity score calculation."""

    def test_get_similarity_score_valid_artists(self) -> None:
        """Test getting similarity score for valid artists."""
        mock_driver = MagicMock()
        filter_engine = CollaborativeFilter(mock_driver)

        filter_engine.artist_to_index = {"Artist A": 0, "Artist B": 1}
        similarity_data = np.array([[1.0, 0.7], [0.7, 1.0]])
        filter_engine.item_similarity_matrix = csr_matrix(similarity_data)

        score = filter_engine.get_similarity_score("Artist A", "Artist B")

        assert 0.0 <= score <= 1.0
        assert score > 0

    def test_get_similarity_score_no_matrix(self) -> None:
        """Test getting similarity score when matrix not built."""
        mock_driver = MagicMock()
        filter_engine = CollaborativeFilter(mock_driver)

        score = filter_engine.get_similarity_score("Artist A", "Artist B")

        assert score == 0.0

    def test_get_similarity_score_unknown_artist(self) -> None:
        """Test getting similarity score for unknown artist."""
        mock_driver = MagicMock()
        filter_engine = CollaborativeFilter(mock_driver)

        filter_engine.artist_to_index = {"Artist A": 0}
        filter_engine.item_similarity_matrix = csr_matrix(np.array([[1.0]]))

        score = filter_engine.get_similarity_score("Artist A", "Unknown")

        assert score == 0.0


class TestMultiArtistRecommendations:
    """Test playlist-based recommendations."""

    @pytest.mark.asyncio
    async def test_get_similar_for_multiple_artists(self) -> None:
        """Test getting recommendations based on multiple artists."""
        mock_driver = MagicMock()
        filter_engine = CollaborativeFilter(mock_driver)

        # Setup test data
        filter_engine.artist_to_index = {"Artist A": 0, "Artist B": 1, "Artist C": 2, "Artist D": 3}
        filter_engine.index_to_artist = {0: "Artist A", 1: "Artist B", 2: "Artist C", 3: "Artist D"}

        similarity_data = np.array([[1.0, 0.8, 0.6, 0.4], [0.8, 1.0, 0.7, 0.5], [0.6, 0.7, 1.0, 0.9], [0.4, 0.5, 0.9, 1.0]])
        filter_engine.item_similarity_matrix = csr_matrix(similarity_data)

        results = await filter_engine.get_similar_artists_for_multiple(["Artist A", "Artist B"], limit=2)

        assert len(results) <= 2
        assert all(r["artist_name"] not in ["Artist A", "Artist B"] for r in results)

    @pytest.mark.asyncio
    async def test_get_similar_for_multiple_no_matrix(self) -> None:
        """Test multi-artist recommendations when matrix not built."""
        mock_driver = MagicMock()
        filter_engine = CollaborativeFilter(mock_driver)

        results = await filter_engine.get_similar_artists_for_multiple(["Artist A"])

        assert results == []

    @pytest.mark.asyncio
    async def test_get_similar_for_multiple_unknown_artists(self) -> None:
        """Test multi-artist recommendations with unknown artists."""
        mock_driver = MagicMock()
        filter_engine = CollaborativeFilter(mock_driver)

        filter_engine.artist_to_index = {"Artist A": 0}
        filter_engine.index_to_artist = {0: "Artist A"}
        filter_engine.item_similarity_matrix = csr_matrix(np.array([[1.0]]))

        results = await filter_engine.get_similar_artists_for_multiple(["Unknown1", "Unknown2"])

        assert results == []


class TestOnDemandRecommendations:
    """Test on-demand recommendation functionality for artists not in pre-built matrix."""

    @pytest.mark.asyncio
    async def test_on_demand_recommendations_with_shared_features(self) -> None:
        """Test on-demand recommendations when artist shares features with matrix artists."""
        mock_driver = MagicMock()
        mock_session = AsyncMock()

        # Mock the query for the new artist
        mock_result = AsyncMock()
        mock_record = {
            "artist_id": "999",
            "artist_name": "New Artist",
            "labels": ["Label1"],
            "genres": ["Rock"],
            "styles": ["Alternative"],
            "collaborators": [],
        }

        mock_result.single = AsyncMock(return_value=mock_record)
        mock_session.run = AsyncMock(return_value=mock_result)
        mock_driver.session.return_value.__aenter__.return_value = mock_session
        mock_driver.session.return_value.__aexit__.return_value = None

        filter_engine = CollaborativeFilter(mock_driver)

        # Setup existing matrix with artists that share features
        filter_engine.artist_to_index = {"Artist A": 0, "Artist B": 1}
        filter_engine.index_to_artist = {0: "Artist A", 1: "Artist B"}
        filter_engine.artist_features = {
            "Artist A": {"labels": ["Label1"], "genres": ["Rock"], "styles": ["Alternative"], "collaborators": []},
            "Artist B": {"labels": ["Label2"], "genres": ["Jazz"], "styles": ["Smooth"], "collaborators": []},
        }

        # Setup inverted indices
        filter_engine.label_to_artists["Label1"] = {0}
        filter_engine.label_to_artists["Label2"] = {1}
        filter_engine.genre_to_artists["Rock"] = {0}
        filter_engine.genre_to_artists["Jazz"] = {1}
        filter_engine.style_to_artists["Alternative"] = {0}
        filter_engine.style_to_artists["Smooth"] = {1}

        # Request recommendations for new artist (not in matrix)
        results = await filter_engine.get_recommendations("New Artist", limit=2)

        # Should return Artist A (shares label, genre, and style)
        assert len(results) > 0
        assert results[0]["artist_name"] == "Artist A"
        assert results[0]["method"] == "collaborative_filtering_on_demand"
        assert results[0]["similarity_score"] > 0

    @pytest.mark.asyncio
    async def test_on_demand_recommendations_artist_not_in_graph(self) -> None:
        """Test on-demand recommendations when artist doesn't exist in graph."""
        mock_driver = MagicMock()
        mock_session = AsyncMock()

        # Mock empty query result
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=None)
        mock_session.run = AsyncMock(return_value=mock_result)
        mock_driver.session.return_value.__aenter__.return_value = mock_session
        mock_driver.session.return_value.__aexit__.return_value = None

        filter_engine = CollaborativeFilter(mock_driver)

        # Setup matrix
        filter_engine.artist_to_index = {"Artist A": 0}
        filter_engine.index_to_artist = {0: "Artist A"}

        # Request recommendations for non-existent artist
        results = await filter_engine.get_recommendations("Nonexistent Artist", limit=10)

        assert results == []

    @pytest.mark.asyncio
    async def test_on_demand_recommendations_no_shared_features(self) -> None:
        """Test on-demand recommendations when artist has no shared features."""
        mock_driver = MagicMock()
        mock_session = AsyncMock()

        # Mock the query for the new artist with unique features
        mock_result = AsyncMock()
        mock_record = {
            "artist_id": "999",
            "artist_name": "Unique Artist",
            "labels": ["UniqueLabel"],
            "genres": ["UniqueGenre"],
            "styles": ["UniqueStyle"],
            "collaborators": [],
        }

        mock_result.single = AsyncMock(return_value=mock_record)
        mock_session.run = AsyncMock(return_value=mock_result)
        mock_driver.session.return_value.__aenter__.return_value = mock_session
        mock_driver.session.return_value.__aexit__.return_value = None

        filter_engine = CollaborativeFilter(mock_driver)

        # Setup existing matrix with different features
        filter_engine.artist_to_index = {"Artist A": 0}
        filter_engine.index_to_artist = {0: "Artist A"}
        filter_engine.artist_features = {
            "Artist A": {"labels": ["Label1"], "genres": ["Rock"], "styles": ["Alternative"], "collaborators": []},
        }

        # Setup inverted indices (won't match unique artist)
        filter_engine.label_to_artists["Label1"] = {0}
        filter_engine.genre_to_artists["Rock"] = {0}
        filter_engine.style_to_artists["Alternative"] = {0}

        # Request recommendations
        results = await filter_engine.get_recommendations("Unique Artist", limit=10)

        # Should return empty list (no shared features)
        assert results == []
