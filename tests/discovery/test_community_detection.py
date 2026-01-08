"""Tests for CommunityDetector class."""

from unittest.mock import AsyncMock, MagicMock, patch

import networkx as nx
import pytest

from discovery.community_detection import CommunityDetector


class TestCommunityDetectorInit:
    """Test CommunityDetector initialization."""

    def test_initialization(self) -> None:
        """Test detector initializes correctly."""
        mock_driver = MagicMock()
        detector = CommunityDetector(mock_driver)

        assert detector.driver == mock_driver
        assert detector.graph is None
        assert detector.communities == {}


class TestBuildCollaborationNetwork:
    """Test building collaboration network."""

    @pytest.mark.asyncio
    async def test_build_collaboration_network(self) -> None:
        """Test building collaboration network from Neo4j."""
        mock_driver = MagicMock()
        mock_session = AsyncMock()
        mock_result = AsyncMock()

        # Mock collaboration data
        mock_records = [
            {"artist1": "Artist A", "artist2": "Artist B", "weight": 5},
            {"artist1": "Artist A", "artist2": "Artist C", "weight": 3},
        ]

        async def async_iter(self):
            for record in mock_records:
                yield record

        mock_result.__aiter__ = async_iter
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__aenter__.return_value = mock_session
        mock_driver.session.return_value.__aexit__.return_value = None

        detector = CommunityDetector(mock_driver)
        graph = await detector.build_collaboration_network(min_weight=1, limit=100)

        assert isinstance(graph, nx.Graph)
        assert graph.number_of_nodes() == 3
        assert graph.number_of_edges() == 2
        assert graph.has_edge("Artist A", "Artist B")
        assert graph["Artist A"]["Artist B"]["weight"] == 5

    @pytest.mark.asyncio
    async def test_build_collaboration_network_empty(self) -> None:
        """Test building network with no data."""
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

        detector = CommunityDetector(mock_driver)
        graph = await detector.build_collaboration_network()

        assert graph.number_of_nodes() == 0
        assert graph.number_of_edges() == 0


class TestLouvainDetection:
    """Test Louvain community detection."""

    @patch("discovery.community_detection.nx.community.louvain_communities")
    def test_detect_communities_louvain(self, mock_louvain: MagicMock) -> None:
        """Test Louvain community detection."""
        mock_driver = MagicMock()
        detector = CommunityDetector(mock_driver)

        # Setup graph
        graph = nx.Graph()
        graph.add_edge("Artist A", "Artist B", weight=5)
        graph.add_edge("Artist B", "Artist C", weight=3)
        detector.graph = graph

        # Mock community detection result
        mock_louvain.return_value = [
            {"Artist A", "Artist B"},
            {"Artist C"},
        ]

        result = detector.detect_communities_louvain()

        assert "community_0" in result
        assert "community_1" in result
        assert len(result["community_0"]) == 2
        assert detector.communities["Artist A"] == 0
        assert detector.communities["Artist C"] == 1

    def test_detect_communities_louvain_no_graph(self) -> None:
        """Test Louvain detection without graph."""
        mock_driver = MagicMock()
        detector = CommunityDetector(mock_driver)

        with pytest.raises(ValueError, match="Graph not built"):
            detector.detect_communities_louvain()


class TestLabelPropagationDetection:
    """Test label propagation community detection."""

    @patch("discovery.community_detection.nx.community.label_propagation_communities")
    def test_detect_communities_label_propagation(self, mock_label_prop: MagicMock) -> None:
        """Test label propagation community detection."""
        mock_driver = MagicMock()
        detector = CommunityDetector(mock_driver)

        # Setup graph
        graph = nx.Graph()
        graph.add_edge("Artist A", "Artist B", weight=5)
        detector.graph = graph

        # Mock community detection result (returns generator)
        def mock_gen():
            yield {"Artist A", "Artist B"}

        mock_label_prop.return_value = mock_gen()

        result = detector.detect_communities_label_propagation()

        assert "community_0" in result
        assert len(result["community_0"]) == 2

    def test_detect_communities_label_propagation_no_graph(self) -> None:
        """Test label propagation without graph."""
        mock_driver = MagicMock()
        detector = CommunityDetector(mock_driver)

        with pytest.raises(ValueError, match="Graph not built"):
            detector.detect_communities_label_propagation()


class TestGreedyModularityDetection:
    """Test greedy modularity community detection."""

    @patch("discovery.community_detection.nx.community.greedy_modularity_communities")
    def test_detect_communities_greedy_modularity(self, mock_greedy: MagicMock) -> None:
        """Test greedy modularity community detection."""
        mock_driver = MagicMock()
        detector = CommunityDetector(mock_driver)

        # Setup graph
        graph = nx.Graph()
        graph.add_edge("Artist A", "Artist B", weight=5)
        detector.graph = graph

        # Mock community detection result
        def mock_gen():
            yield frozenset({"Artist A", "Artist B"})

        mock_greedy.return_value = mock_gen()

        result = detector.detect_communities_greedy_modularity()

        assert "community_0" in result
        assert len(result["community_0"]) == 2

    def test_detect_communities_greedy_modularity_no_graph(self) -> None:
        """Test greedy modularity without graph."""
        mock_driver = MagicMock()
        detector = CommunityDetector(mock_driver)

        with pytest.raises(ValueError, match="Graph not built"):
            detector.detect_communities_greedy_modularity()


class TestArtistCommunity:
    """Test getting artist community."""

    def test_get_artist_community(self) -> None:
        """Test getting community ID for an artist."""
        mock_driver = MagicMock()
        detector = CommunityDetector(mock_driver)

        detector.communities = {"Artist A": 0, "Artist B": 1}

        assert detector.get_artist_community("Artist A") == 0
        assert detector.get_artist_community("Unknown") is None


class TestCommunityMembers:
    """Test getting community members."""

    def test_get_community_members(self) -> None:
        """Test getting all artists in a community."""
        mock_driver = MagicMock()
        detector = CommunityDetector(mock_driver)

        detector.communities = {"Artist A": 0, "Artist B": 0, "Artist C": 1}

        members = detector.get_community_members(0)

        assert len(members) == 2
        assert "Artist A" in members
        assert "Artist B" in members


class TestCommunityStats:
    """Test community statistics."""

    def test_get_community_stats(self) -> None:
        """Test getting statistics about communities."""
        mock_driver = MagicMock()
        detector = CommunityDetector(mock_driver)

        detector.communities = {
            "Artist A": 0,
            "Artist B": 0,
            "Artist C": 0,
            "Artist D": 1,
            "Artist E": 1,
        }

        stats = detector.get_community_stats()

        assert stats["num_communities"] == 2
        assert stats["total_artists"] == 5
        assert stats["min_size"] == 2
        assert stats["max_size"] == 3

    def test_get_community_stats_empty(self) -> None:
        """Test statistics with no communities."""
        mock_driver = MagicMock()
        detector = CommunityDetector(mock_driver)

        stats = detector.get_community_stats()

        assert stats == {}


class TestFindSimilarCommunities:
    """Test finding similar communities."""

    @patch("discovery.community_detection.nx.degree_centrality")
    def test_find_similar_communities_with_graph(self, mock_centrality: MagicMock) -> None:
        """Test finding similar artists with graph."""
        mock_driver = MagicMock()
        detector = CommunityDetector(mock_driver)

        # Setup graph
        graph = nx.Graph()
        graph.add_edge("Artist A", "Artist B")
        graph.add_edge("Artist A", "Artist C")
        detector.graph = graph

        detector.communities = {"Artist A": 0, "Artist B": 0, "Artist C": 0}

        mock_centrality.return_value = {"Artist A": 0.8, "Artist B": 0.6, "Artist C": 0.4}

        result = detector.find_similar_communities("Artist A", top_k=2)

        assert len(result) == 2
        assert result[0]["artist_name"] == "Artist B"
        assert "centrality" in result[0]

    def test_find_similar_communities_without_graph(self) -> None:
        """Test finding similar artists without graph."""
        mock_driver = MagicMock()
        detector = CommunityDetector(mock_driver)

        detector.communities = {"Artist A": 0, "Artist B": 0, "Artist C": 0}

        result = detector.find_similar_communities("Artist A", top_k=2)

        assert len(result) == 2
        assert all("artist_name" in r for r in result)

    def test_find_similar_communities_unknown_artist(self) -> None:
        """Test finding similar with unknown artist."""
        mock_driver = MagicMock()
        detector = CommunityDetector(mock_driver)

        detector.communities = {}

        result = detector.find_similar_communities("Unknown")

        assert result == []


class TestCalculateModularity:
    """Test modularity calculation."""

    @patch("discovery.community_detection.nx.community.modularity")
    def test_calculate_modularity(self, mock_modularity: MagicMock) -> None:
        """Test calculating modularity score."""
        mock_driver = MagicMock()
        detector = CommunityDetector(mock_driver)

        # Setup graph
        graph = nx.Graph()
        graph.add_edge("Artist A", "Artist B", weight=5)
        detector.graph = graph

        detector.communities = {"Artist A": 0, "Artist B": 0}

        mock_modularity.return_value = 0.75

        score = detector.calculate_modularity()

        assert score == 0.75

    def test_calculate_modularity_no_graph(self) -> None:
        """Test modularity without graph."""
        mock_driver = MagicMock()
        detector = CommunityDetector(mock_driver)

        score = detector.calculate_modularity()

        assert score == 0.0


class TestBuildGenreBasedNetwork:
    """Test building genre-based network."""

    @pytest.mark.asyncio
    async def test_build_genre_based_network(self) -> None:
        """Test building network based on shared genres."""
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

        detector = CommunityDetector(mock_driver)
        graph = await detector.build_genre_based_network(min_shared_genres=2)

        assert graph.number_of_nodes() == 2
        assert graph.number_of_edges() == 1
        assert "shared_genres" in graph["Artist A"]["Artist B"]


class TestExportCommunities:
    """Test exporting communities."""

    def test_export_communities_to_dict(self) -> None:
        """Test exporting community results to dictionary."""
        mock_driver = MagicMock()
        detector = CommunityDetector(mock_driver)

        # Setup graph and communities
        graph = nx.Graph()
        graph.add_edge("Artist A", "Artist B", weight=5)
        detector.graph = graph
        detector.communities = {"Artist A": 0, "Artist B": 0}

        result = detector.export_communities_to_dict()

        assert "communities" in result
        assert "stats" in result
        assert "modularity" in result
        assert "community_0" in result["communities"]

    def test_export_communities_empty(self) -> None:
        """Test exporting with no communities."""
        mock_driver = MagicMock()
        detector = CommunityDetector(mock_driver)

        result = detector.export_communities_to_dict()

        assert result == {}
