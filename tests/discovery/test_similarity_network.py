"""Tests for SimilarityNetworkBuilder class."""

from unittest.mock import AsyncMock, MagicMock

import networkx as nx
import pytest

from discovery.similarity_network import SimilarityNetworkBuilder


class TestSimilarityNetworkBuilderInit:
    """Test SimilarityNetworkBuilder initialization."""

    def test_initialization(self) -> None:
        """Test builder initializes correctly."""
        mock_driver = MagicMock()
        builder = SimilarityNetworkBuilder(mock_driver)

        assert builder.driver == mock_driver
        assert builder.graph is None


class TestBuildSimilarityNetwork:
    """Test main build_similarity_network method."""

    @pytest.mark.asyncio
    async def test_build_collaboration_network(self) -> None:
        """Test building collaboration-based network."""
        mock_driver = MagicMock()
        builder = SimilarityNetworkBuilder(mock_driver)

        # Mock the specific network building method
        mock_graph = nx.Graph()
        mock_graph.add_node("Artist A")
        mock_graph.add_node("Artist B")
        mock_graph.add_edge("Artist A", "Artist B", weight=5)

        builder._build_collaboration_network = AsyncMock(return_value=mock_graph)

        result = await builder.build_similarity_network(
            similarity_method="collaboration",
            similarity_threshold=0.3,
        )

        assert isinstance(result, nx.Graph)
        assert result.number_of_nodes() == 2
        assert result.number_of_edges() == 1
        assert builder.graph is not None

    @pytest.mark.asyncio
    async def test_build_genre_network(self) -> None:
        """Test building genre-based network."""
        mock_driver = MagicMock()
        builder = SimilarityNetworkBuilder(mock_driver)

        mock_graph = nx.Graph()
        builder._build_genre_similarity_network = AsyncMock(return_value=mock_graph)

        result = await builder.build_similarity_network(
            similarity_method="genre",
            similarity_threshold=1,
        )

        builder._build_genre_similarity_network.assert_called_once()
        assert isinstance(result, nx.Graph)

    @pytest.mark.asyncio
    async def test_build_style_network(self) -> None:
        """Test building style-based network."""
        mock_driver = MagicMock()
        builder = SimilarityNetworkBuilder(mock_driver)

        mock_graph = nx.Graph()
        builder._build_style_similarity_network = AsyncMock(return_value=mock_graph)

        await builder.build_similarity_network(
            similarity_method="style",
            similarity_threshold=1,
        )

        builder._build_style_similarity_network.assert_called_once()


class TestBuildCollaborationNetwork:
    """Test collaboration network building."""

    @pytest.mark.asyncio
    async def test_build_with_artist_list(self) -> None:
        """Test building network for specific artists."""
        mock_driver = MagicMock()
        mock_session = AsyncMock()
        mock_result = AsyncMock()

        # Mock Neo4j data
        mock_records = [
            {
                "artist1": "Artist A",
                "artist2": "Artist B",
                "weight": 5,
            },
        ]

        async def async_iter(self):
            for record in mock_records:
                yield record

        mock_result.__aiter__ = async_iter
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__aenter__.return_value = mock_session
        mock_driver.session.return_value.__aexit__.return_value = None

        builder = SimilarityNetworkBuilder(mock_driver)
        builder._enrich_node_attributes = AsyncMock()

        graph = await builder._build_collaboration_network(
            artist_list=["Artist A", "Artist B"],
            similarity_threshold=1.0,
            max_artists=100,
        )

        assert graph.number_of_nodes() == 2
        assert graph.number_of_edges() == 1
        assert graph.has_edge("Artist A", "Artist B")

    @pytest.mark.asyncio
    async def test_build_without_artist_list(self) -> None:
        """Test building network for top artists."""
        mock_driver = MagicMock()
        mock_session = AsyncMock()
        mock_result = AsyncMock()

        mock_records = [
            {
                "artist1": "Popular A",
                "artist2": "Popular B",
                "weight": 10,
            },
        ]

        async def async_iter(self):
            for record in mock_records:
                yield record

        mock_result.__aiter__ = async_iter
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__aenter__.return_value = mock_session
        mock_driver.session.return_value.__aexit__.return_value = None

        builder = SimilarityNetworkBuilder(mock_driver)
        builder._enrich_node_attributes = AsyncMock()

        graph = await builder._build_collaboration_network(
            artist_list=None,
            similarity_threshold=1.0,
            max_artists=50,
        )

        assert graph.number_of_nodes() == 2
        assert graph.has_edge("Popular A", "Popular B")


class TestBuildGenreSimilarityNetwork:
    """Test genre-based network building."""

    @pytest.mark.asyncio
    async def test_build_genre_network_with_artists(self) -> None:
        """Test building genre network for specific artists."""
        mock_driver = MagicMock()
        mock_session = AsyncMock()
        mock_result = AsyncMock()

        mock_records = [
            {
                "artist1": "Artist A",
                "artist2": "Artist B",
                "weight": 2,
                "shared_genres": ["Rock", "Alternative"],
            },
        ]

        async def async_iter(self):
            for record in mock_records:
                yield record

        mock_result.__aiter__ = async_iter
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__aenter__.return_value = mock_session
        mock_driver.session.return_value.__aexit__.return_value = None

        builder = SimilarityNetworkBuilder(mock_driver)
        builder._enrich_node_attributes = AsyncMock()

        graph = await builder._build_genre_similarity_network(
            artist_list=["Artist A", "Artist B"],
            similarity_threshold=1.0,
            max_artists=100,
        )

        assert graph.number_of_nodes() == 2
        assert graph.number_of_edges() == 1
        # Check edge attributes
        edge_data = graph.get_edge_data("Artist A", "Artist B")
        assert "shared_genres" in edge_data

    @pytest.mark.asyncio
    async def test_build_genre_network_without_artists(self) -> None:
        """Test building genre network for top artists."""
        mock_driver = MagicMock()
        mock_session = AsyncMock()
        mock_result = AsyncMock()

        async def async_iter(self):
            return
            yield  # Make it a generator

        mock_result.__aiter__ = async_iter
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__aenter__.return_value = mock_session
        mock_driver.session.return_value.__aexit__.return_value = None

        builder = SimilarityNetworkBuilder(mock_driver)
        builder._enrich_node_attributes = AsyncMock()

        graph = await builder._build_genre_similarity_network(
            artist_list=None,
            similarity_threshold=1.0,
            max_artists=100,
        )

        # Should return empty graph when no data
        assert isinstance(graph, nx.Graph)
