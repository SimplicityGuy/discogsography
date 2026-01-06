"""Tests for CentralityAnalyzer class."""

from unittest.mock import AsyncMock, MagicMock, patch

import networkx as nx
import pytest

from discovery.centrality_metrics import CentralityAnalyzer


class TestCentralityAnalyzerInit:
    """Test CentralityAnalyzer initialization."""

    def test_initialization(self) -> None:
        """Test analyzer initializes correctly."""
        mock_driver = MagicMock()
        analyzer = CentralityAnalyzer(mock_driver)

        assert analyzer.driver == mock_driver
        assert analyzer.graph is None
        assert analyzer.metrics == {}


class TestBuildNetwork:
    """Test building network."""

    @pytest.mark.asyncio
    async def test_build_network(self) -> None:
        """Test building collaboration network."""
        mock_driver = MagicMock()
        mock_session = AsyncMock()
        mock_result = AsyncMock()

        mock_records = [
            {"artist1": "Artist A", "artist2": "Artist B", "weight": 5},
            {"artist1": "Artist B", "artist2": "Artist C", "weight": 3},
        ]

        async def async_iter(self):
            for record in mock_records:
                yield record

        mock_result.__aiter__ = async_iter
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__aenter__.return_value = mock_session
        mock_driver.session.return_value.__aexit__.return_value = None

        analyzer = CentralityAnalyzer(mock_driver)
        graph = await analyzer.build_network(limit=100)

        assert graph.number_of_nodes() == 3
        assert graph.number_of_edges() == 2


class TestDegreeCentrality:
    """Test degree centrality calculation."""

    @patch("discovery.centrality_metrics.nx.degree_centrality")
    def test_calculate_degree_centrality(self, mock_degree: MagicMock) -> None:
        """Test calculating degree centrality."""
        mock_driver = MagicMock()
        analyzer = CentralityAnalyzer(mock_driver)

        # Setup graph
        graph = nx.Graph()
        graph.add_edge("Artist A", "Artist B")
        analyzer.graph = graph

        mock_degree.return_value = {"Artist A": 1.0, "Artist B": 1.0}

        result = analyzer.calculate_degree_centrality()

        assert "Artist A" in result
        assert result["Artist A"] == 1.0
        assert "Artist A" in analyzer.metrics
        assert analyzer.metrics["Artist A"]["degree_centrality"] == 1.0

    def test_calculate_degree_centrality_no_graph(self) -> None:
        """Test degree centrality without graph."""
        mock_driver = MagicMock()
        analyzer = CentralityAnalyzer(mock_driver)

        with pytest.raises(ValueError, match="Graph not built"):
            analyzer.calculate_degree_centrality()


class TestBetweennessCentrality:
    """Test betweenness centrality calculation."""

    @patch("discovery.centrality_metrics.nx.betweenness_centrality")
    def test_calculate_betweenness_centrality(self, mock_betweenness: MagicMock) -> None:
        """Test calculating betweenness centrality."""
        mock_driver = MagicMock()
        analyzer = CentralityAnalyzer(mock_driver)

        graph = nx.Graph()
        graph.add_edge("Artist A", "Artist B", weight=5)
        analyzer.graph = graph

        mock_betweenness.return_value = {"Artist A": 0.5, "Artist B": 0.5}

        result = analyzer.calculate_betweenness_centrality()

        assert result["Artist A"] == 0.5
        assert analyzer.metrics["Artist A"]["betweenness_centrality"] == 0.5

    @patch("discovery.centrality_metrics.nx.betweenness_centrality")
    def test_calculate_betweenness_centrality_with_k(self, mock_betweenness: MagicMock) -> None:
        """Test betweenness with k approximation."""
        mock_driver = MagicMock()
        analyzer = CentralityAnalyzer(mock_driver)

        graph = nx.Graph()
        graph.add_edge("Artist A", "Artist B", weight=5)
        analyzer.graph = graph

        mock_betweenness.return_value = {"Artist A": 0.5, "Artist B": 0.5}

        result = analyzer.calculate_betweenness_centrality(k=100)

        assert result["Artist A"] == 0.5
        mock_betweenness.assert_called_with(graph, k=100, weight="weight")


class TestClosenessCentrality:
    """Test closeness centrality calculation."""

    @patch("discovery.centrality_metrics.nx.is_connected")
    @patch("discovery.centrality_metrics.nx.closeness_centrality")
    def test_calculate_closeness_centrality_connected(self, mock_closeness: MagicMock, mock_is_connected: MagicMock) -> None:
        """Test closeness centrality for connected graph."""
        mock_driver = MagicMock()
        analyzer = CentralityAnalyzer(mock_driver)

        graph = nx.Graph()
        graph.add_edge("Artist A", "Artist B", weight=5)
        analyzer.graph = graph

        mock_is_connected.return_value = True
        mock_closeness.return_value = {"Artist A": 1.0, "Artist B": 1.0}

        result = analyzer.calculate_closeness_centrality()

        assert result["Artist A"] == 1.0
        mock_closeness.assert_called_once()

    @patch("discovery.centrality_metrics.nx.is_connected")
    @patch("discovery.centrality_metrics.nx.connected_components")
    @patch("discovery.centrality_metrics.nx.closeness_centrality")
    def test_calculate_closeness_centrality_disconnected(
        self,
        mock_closeness: MagicMock,
        mock_components: MagicMock,
        mock_is_connected: MagicMock,
    ) -> None:
        """Test closeness centrality for disconnected graph."""
        mock_driver = MagicMock()
        analyzer = CentralityAnalyzer(mock_driver)

        graph = nx.Graph()
        graph.add_edge("Artist A", "Artist B")
        graph.add_node("Artist C")
        analyzer.graph = graph

        mock_is_connected.return_value = False
        mock_components.return_value = [{"Artist A", "Artist B"}, {"Artist C"}]
        mock_closeness.return_value = {"Artist A": 1.0, "Artist B": 1.0}

        result = analyzer.calculate_closeness_centrality()

        assert "Artist A" in result


class TestEigenvectorCentrality:
    """Test eigenvector centrality calculation."""

    @patch("discovery.centrality_metrics.nx.eigenvector_centrality")
    def test_calculate_eigenvector_centrality(self, mock_eigenvector: MagicMock) -> None:
        """Test calculating eigenvector centrality."""
        mock_driver = MagicMock()
        analyzer = CentralityAnalyzer(mock_driver)

        graph = nx.Graph()
        graph.add_edge("Artist A", "Artist B", weight=5)
        analyzer.graph = graph

        mock_eigenvector.return_value = {"Artist A": 0.7, "Artist B": 0.7}

        result = analyzer.calculate_eigenvector_centrality(max_iter=100)

        assert result["Artist A"] == 0.7
        mock_eigenvector.assert_called_with(graph, max_iter=100, weight="weight")

    @patch("discovery.centrality_metrics.nx.eigenvector_centrality")
    def test_calculate_eigenvector_centrality_convergence_failure(self, mock_eigenvector: MagicMock) -> None:
        """Test eigenvector centrality convergence failure."""
        mock_driver = MagicMock()
        analyzer = CentralityAnalyzer(mock_driver)

        graph = nx.Graph()
        graph.add_edge("Artist A", "Artist B")
        analyzer.graph = graph

        mock_eigenvector.side_effect = nx.PowerIterationFailedConvergence(10)

        result = analyzer.calculate_eigenvector_centrality()

        assert result == {}


class TestPageRank:
    """Test PageRank calculation."""

    @patch("discovery.centrality_metrics.nx.pagerank")
    def test_calculate_pagerank(self, mock_pagerank: MagicMock) -> None:
        """Test calculating PageRank."""
        mock_driver = MagicMock()
        analyzer = CentralityAnalyzer(mock_driver)

        graph = nx.Graph()
        graph.add_edge("Artist A", "Artist B", weight=5)
        analyzer.graph = graph

        mock_pagerank.return_value = {"Artist A": 0.5, "Artist B": 0.5}

        result = analyzer.calculate_pagerank(alpha=0.85)

        assert result["Artist A"] == 0.5
        mock_pagerank.assert_called_with(graph, alpha=0.85, weight="weight")
        assert analyzer.metrics["Artist A"]["pagerank"] == 0.5


class TestCalculateAllMetrics:
    """Test calculating all metrics."""

    def test_calculate_all_metrics_fast_only(self) -> None:
        """Test calculating only fast metrics."""
        mock_driver = MagicMock()
        analyzer = CentralityAnalyzer(mock_driver)

        graph = nx.Graph()
        graph.add_edge("Artist A", "Artist B", weight=5)
        analyzer.graph = graph

        result = analyzer.calculate_all_metrics(include_expensive=False)

        assert "Artist A" in result
        assert "degree_centrality" in result["Artist A"]
        assert "pagerank" in result["Artist A"]
        assert "betweenness_centrality" not in result["Artist A"]

    def test_calculate_all_metrics_with_expensive(self) -> None:
        """Test calculating all metrics including expensive ones."""
        mock_driver = MagicMock()
        analyzer = CentralityAnalyzer(mock_driver)

        # Create larger graph (> 100 nodes) to support k=100 approximation
        graph = nx.Graph()
        for i in range(105):
            graph.add_edge(f"Artist {i}", f"Artist {i + 1}", weight=1)
        analyzer.graph = graph

        result = analyzer.calculate_all_metrics(include_expensive=True)

        assert "degree_centrality" in result["Artist 0"]
        assert "betweenness_centrality" in result["Artist 0"]


class TestGetTopInfluentialArtists:
    """Test getting top influential artists."""

    def test_get_top_influential_artists(self) -> None:
        """Test getting top influential artists."""
        mock_driver = MagicMock()
        analyzer = CentralityAnalyzer(mock_driver)

        analyzer.metrics = {
            "Artist A": {"pagerank": 0.9},
            "Artist B": {"pagerank": 0.7},
            "Artist C": {"pagerank": 0.5},
        }

        result = analyzer.get_top_influential_artists(metric="pagerank", top_k=2)

        assert len(result) == 2
        assert result[0]["artist_name"] == "Artist A"
        assert result[0]["score"] == 0.9
        assert result[0]["rank"] == 1

    def test_get_top_influential_artists_empty_metrics(self) -> None:
        """Test with no metrics."""
        mock_driver = MagicMock()
        analyzer = CentralityAnalyzer(mock_driver)

        result = analyzer.get_top_influential_artists()

        assert result == []


class TestGetArtistInfluenceProfile:
    """Test getting artist influence profile."""

    def test_get_artist_influence_profile(self) -> None:
        """Test getting complete influence profile."""
        mock_driver = MagicMock()
        analyzer = CentralityAnalyzer(mock_driver)

        analyzer.metrics = {
            "Artist A": {"pagerank": 0.9, "degree_centrality": 0.8},
            "Artist B": {"pagerank": 0.7, "degree_centrality": 0.6},
        }

        profile = analyzer.get_artist_influence_profile("Artist A")

        assert profile["artist_name"] == "Artist A"
        assert profile["metrics"]["pagerank"] == 0.9
        assert "rankings" in profile
        assert profile["total_artists"] == 2

    def test_get_artist_influence_profile_not_found(self) -> None:
        """Test with unknown artist."""
        mock_driver = MagicMock()
        analyzer = CentralityAnalyzer(mock_driver)

        profile = analyzer.get_artist_influence_profile("Unknown")

        assert "error" in profile


class TestCompareArtists:
    """Test comparing artists."""

    def test_compare_artists(self) -> None:
        """Test comparing two artists."""
        mock_driver = MagicMock()
        analyzer = CentralityAnalyzer(mock_driver)

        analyzer.metrics = {
            "Artist A": {"pagerank": 0.9},
            "Artist B": {"pagerank": 0.7},
        }

        comparison = analyzer.compare_artists("Artist A", "Artist B")

        assert comparison["artist1"]["name"] == "Artist A"
        assert comparison["artist2"]["name"] == "Artist B"
        assert "differences" in comparison
        assert comparison["differences"]["pagerank"]["higher"] == "Artist A"

    def test_compare_artists_not_found(self) -> None:
        """Test comparing with unknown artist."""
        mock_driver = MagicMock()
        analyzer = CentralityAnalyzer(mock_driver)

        comparison = analyzer.compare_artists("Unknown1", "Unknown2")

        assert "error" in comparison


class TestGetNetworkStatistics:
    """Test getting network statistics."""

    def test_get_network_statistics_connected(self) -> None:
        """Test statistics for connected graph."""
        mock_driver = MagicMock()
        analyzer = CentralityAnalyzer(mock_driver)

        graph = nx.Graph()
        graph.add_edge("A", "B")
        graph.add_edge("B", "C")
        analyzer.graph = graph

        stats = analyzer.get_network_statistics()

        assert stats["num_nodes"] == 3
        assert stats["num_edges"] == 2
        assert "density" in stats
        assert "diameter" in stats

    def test_get_network_statistics_disconnected(self) -> None:
        """Test statistics for disconnected graph."""
        mock_driver = MagicMock()
        analyzer = CentralityAnalyzer(mock_driver)

        graph = nx.Graph()
        graph.add_edge("A", "B")
        graph.add_node("C")
        analyzer.graph = graph

        stats = analyzer.get_network_statistics()

        assert stats["num_connected_components"] == 2
        assert "largest_component_size" in stats

    def test_get_network_statistics_no_graph(self) -> None:
        """Test statistics without graph."""
        mock_driver = MagicMock()
        analyzer = CentralityAnalyzer(mock_driver)

        stats = analyzer.get_network_statistics()

        assert stats == {}


class TestExportMetrics:
    """Test exporting metrics."""

    def test_export_metrics_to_dict(self) -> None:
        """Test exporting all metrics."""
        mock_driver = MagicMock()
        analyzer = CentralityAnalyzer(mock_driver)

        graph = nx.Graph()
        graph.add_edge("A", "B")
        analyzer.graph = graph
        analyzer.metrics = {"A": {"pagerank": 0.5}}

        export = analyzer.export_metrics_to_dict()

        assert "metrics" in export
        assert "network_stats" in export
        assert export["total_artists"] == 1
