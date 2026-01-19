"""Tests for SimilarityNetworkBuilder export and analysis methods."""

from pathlib import Path
import tempfile
from unittest.mock import AsyncMock, MagicMock

import networkx as nx
import pytest

from discovery.similarity_network import SimilarityNetworkBuilder


class TestExportToPlotly:
    """Test Plotly export functionality."""

    def test_export_empty_graph(self) -> None:
        """Test exporting when no graph is built."""
        mock_driver = MagicMock()
        builder = SimilarityNetworkBuilder(mock_driver)

        result = builder.export_to_plotly()
        assert result == {}

    def test_export_with_graph(self) -> None:
        """Test exporting a populated graph to Plotly format."""
        mock_driver = MagicMock()
        builder = SimilarityNetworkBuilder(mock_driver)

        # Build a simple graph
        graph = nx.Graph()
        graph.add_node("Artist A", genres=["Rock"], degree=2)
        graph.add_node("Artist B", genres=["Jazz"], degree=1)
        graph.add_edge("Artist A", "Artist B", weight=5)

        builder.graph = graph

        result = builder.export_to_plotly()

        assert "edges" in result
        assert "nodes" in result
        assert "layout" in result
        assert len(result["edges"]) == 1
        assert result["nodes"]["mode"] == "markers+text"
        assert result["layout"]["title"] == "Artist Similarity Network"

    def test_export_node_attributes(self) -> None:
        """Test that node attributes are properly exported."""
        mock_driver = MagicMock()
        builder = SimilarityNetworkBuilder(mock_driver)

        graph = nx.Graph()
        graph.add_node("Test Artist", genres=["Electronic", "Ambient"], degree=3)
        builder.graph = graph

        result = builder.export_to_plotly()

        # Check node data
        assert result["nodes"]["x"]
        assert result["nodes"]["y"]
        assert "Test Artist" in result["nodes"]["text"]


class TestExportToCytoscape:
    """Test Cytoscape export functionality."""

    def test_export_empty_graph(self) -> None:
        """Test exporting when no graph is built."""
        mock_driver = MagicMock()
        builder = SimilarityNetworkBuilder(mock_driver)

        result = builder.export_to_cytoscape()
        assert result == {"elements": {"nodes": [], "edges": []}}

    def test_export_with_graph(self) -> None:
        """Test exporting a populated graph to Cytoscape format."""
        mock_driver = MagicMock()
        builder = SimilarityNetworkBuilder(mock_driver)

        graph = nx.Graph()
        graph.add_node("Artist A", genres=["Rock"], styles=["Alternative"], degree=2)
        graph.add_node("Artist B", genres=["Jazz"], styles=["Bebop"], degree=1)
        graph.add_edge("Artist A", "Artist B", weight=5, similarity=0.8)

        builder.graph = graph

        result = builder.export_to_cytoscape()

        assert "elements" in result
        assert "nodes" in result["elements"]
        assert "edges" in result["elements"]
        assert len(result["elements"]["nodes"]) == 2
        assert len(result["elements"]["edges"]) == 1

        # Check node structure
        node = result["elements"]["nodes"][0]
        assert "data" in node
        assert "id" in node["data"]
        assert "label" in node["data"]
        assert "genres" in node["data"]

        # Check edge structure
        edge = result["elements"]["edges"][0]
        assert "data" in edge
        assert "source" in edge["data"]
        assert "target" in edge["data"]
        assert edge["data"]["weight"] == 5
        assert edge["data"]["similarity"] == 0.8


class TestExportToD3:
    """Test D3 export functionality."""

    def test_export_empty_graph(self) -> None:
        """Test exporting when no graph is built."""
        mock_driver = MagicMock()
        builder = SimilarityNetworkBuilder(mock_driver)

        result = builder.export_to_d3()
        assert result == {"nodes": [], "links": []}

    def test_export_with_graph(self) -> None:
        """Test exporting a populated graph to D3 format."""
        mock_driver = MagicMock()
        builder = SimilarityNetworkBuilder(mock_driver)

        graph = nx.Graph()
        graph.add_node("Artist A", genres=["Rock", "Alternative"], degree=2)
        graph.add_node("Artist B", genres=["Jazz"], degree=1)
        graph.add_edge("Artist A", "Artist B", weight=5, similarity=0.8)

        builder.graph = graph

        result = builder.export_to_d3()

        assert "nodes" in result
        assert "links" in result
        assert len(result["nodes"]) == 2
        assert len(result["links"]) == 1

        # Check node structure
        node = result["nodes"][0]
        assert "id" in node
        assert "group" in node
        assert "genres" in node
        assert "degree" in node

        # Check link structure - uses node indices
        link = result["links"][0]
        assert "source" in link
        assert "target" in link
        assert isinstance(link["source"], int)
        assert isinstance(link["target"], int)
        assert link["value"] == 5
        assert link["similarity"] == 0.8

    def test_export_node_index_mapping(self) -> None:
        """Test that node indices are correctly mapped in D3 export."""
        mock_driver = MagicMock()
        builder = SimilarityNetworkBuilder(mock_driver)

        graph = nx.Graph()
        graph.add_node("A")
        graph.add_node("B")
        graph.add_node("C")
        graph.add_edge("A", "C", weight=1)
        graph.add_edge("B", "C", weight=2)

        builder.graph = graph

        result = builder.export_to_d3()

        # All links should use valid node indices
        for link in result["links"]:
            assert 0 <= link["source"] < len(result["nodes"])
            assert 0 <= link["target"] < len(result["nodes"])


class TestFileExports:
    """Test file-based export methods."""

    def test_export_to_gexf_no_graph(self) -> None:
        """Test GEXF export with no graph."""
        mock_driver = MagicMock()
        builder = SimilarityNetworkBuilder(mock_driver)

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "test.gexf"
            builder.export_to_gexf(str(filepath))
            # Should not create file when no graph
            assert not filepath.exists()

    def test_export_to_gexf_with_graph(self) -> None:
        """Test GEXF export with a graph."""
        mock_driver = MagicMock()
        builder = SimilarityNetworkBuilder(mock_driver)

        graph = nx.Graph()
        graph.add_node("Artist A")
        graph.add_node("Artist B")
        graph.add_edge("Artist A", "Artist B", weight=5)
        builder.graph = graph

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "test.gexf"
            builder.export_to_gexf(str(filepath))
            assert filepath.exists()
            # Verify file content
            content = filepath.read_text()
            assert "Artist A" in content
            assert "Artist B" in content

    def test_export_to_graphml_no_graph(self) -> None:
        """Test GraphML export with no graph."""
        mock_driver = MagicMock()
        builder = SimilarityNetworkBuilder(mock_driver)

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "test.graphml"
            builder.export_to_graphml(str(filepath))
            # Should not create file when no graph
            assert not filepath.exists()

    def test_export_to_graphml_with_graph(self) -> None:
        """Test GraphML export with a graph."""
        mock_driver = MagicMock()
        builder = SimilarityNetworkBuilder(mock_driver)

        graph = nx.Graph()
        graph.add_node("Artist A")
        graph.add_node("Artist B")
        graph.add_edge("Artist A", "Artist B", weight=5)
        builder.graph = graph

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "test.graphml"
            builder.export_to_graphml(str(filepath))
            assert filepath.exists()
            # Verify file content
            content = filepath.read_text()
            assert "Artist A" in content
            assert "Artist B" in content


class TestNetworkStatistics:
    """Test network statistics methods."""

    def test_statistics_empty_graph(self) -> None:
        """Test statistics for no graph."""
        mock_driver = MagicMock()
        builder = SimilarityNetworkBuilder(mock_driver)

        stats = builder.get_network_statistics()
        assert stats == {}

    def test_statistics_basic_graph(self) -> None:
        """Test statistics for a simple graph."""
        mock_driver = MagicMock()
        builder = SimilarityNetworkBuilder(mock_driver)

        graph = nx.Graph()
        graph.add_node("A")
        graph.add_node("B")
        graph.add_node("C")
        graph.add_edge("A", "B", weight=1)
        graph.add_edge("B", "C", weight=2)
        builder.graph = graph

        stats = builder.get_network_statistics()

        assert stats["num_nodes"] == 3
        assert stats["num_edges"] == 2
        assert "density" in stats
        assert "avg_degree" in stats
        assert "avg_clustering" in stats
        assert "num_components" in stats

    def test_statistics_connected_graph(self) -> None:
        """Test statistics for a connected graph."""
        mock_driver = MagicMock()
        builder = SimilarityNetworkBuilder(mock_driver)

        # Create a connected graph
        graph = nx.complete_graph(4)
        # Add weights
        for edge in graph.edges():
            graph.edges[edge]["weight"] = 1.0
        builder.graph = graph

        stats = builder.get_network_statistics()

        assert stats["num_nodes"] == 4
        assert stats["num_edges"] == 6
        assert stats["num_components"] == 1
        # Connected graph should have diameter and avg path length
        assert "diameter" in stats
        assert "avg_path_length" in stats
        assert stats["diameter"] > 0
        assert stats["avg_path_length"] > 0

    def test_statistics_disconnected_graph(self) -> None:
        """Test statistics for a disconnected graph."""
        mock_driver = MagicMock()
        builder = SimilarityNetworkBuilder(mock_driver)

        graph = nx.Graph()
        # Create two separate components
        graph.add_edge("A", "B", weight=1)
        graph.add_edge("C", "D", weight=1)
        builder.graph = graph

        stats = builder.get_network_statistics()

        assert stats["num_components"] == 2
        # Disconnected graph should not have diameter or avg path length
        assert "diameter" not in stats
        assert "avg_path_length" not in stats


class TestFindArtistNeighborhood:
    """Test artist neighborhood extraction."""

    def test_find_neighborhood_no_graph(self) -> None:
        """Test neighborhood extraction with no graph."""
        mock_driver = MagicMock()
        builder = SimilarityNetworkBuilder(mock_driver)

        result = builder.find_artist_neighborhood("Artist A")
        assert isinstance(result, nx.Graph)
        assert result.number_of_nodes() == 0

    def test_find_neighborhood_artist_not_found(self) -> None:
        """Test neighborhood extraction for non-existent artist."""
        mock_driver = MagicMock()
        builder = SimilarityNetworkBuilder(mock_driver)

        graph = nx.Graph()
        graph.add_node("Artist A")
        graph.add_node("Artist B")
        builder.graph = graph

        result = builder.find_artist_neighborhood("Unknown Artist")
        assert isinstance(result, nx.Graph)
        assert result.number_of_nodes() == 0

    def test_find_neighborhood_depth_1(self) -> None:
        """Test neighborhood extraction with depth 1."""
        mock_driver = MagicMock()
        builder = SimilarityNetworkBuilder(mock_driver)

        # Create a chain: A - B - C - D
        graph = nx.Graph()
        graph.add_edge("A", "B")
        graph.add_edge("B", "C")
        graph.add_edge("C", "D")
        builder.graph = graph

        # Depth 1 should include only direct neighbors
        result = builder.find_artist_neighborhood("B", depth=1)

        assert result.number_of_nodes() == 3  # B, A, C
        assert "B" in result
        assert "A" in result
        assert "C" in result
        assert "D" not in result

    def test_find_neighborhood_depth_2(self) -> None:
        """Test neighborhood extraction with depth 2."""
        mock_driver = MagicMock()
        builder = SimilarityNetworkBuilder(mock_driver)

        # Create a chain: A - B - C - D
        graph = nx.Graph()
        graph.add_edge("A", "B")
        graph.add_edge("B", "C")
        graph.add_edge("C", "D")
        builder.graph = graph

        # Depth 2 should include neighbors of neighbors
        result = builder.find_artist_neighborhood("B", depth=2)

        assert result.number_of_nodes() == 4  # B, A, C, D
        assert "A" in result
        assert "B" in result
        assert "C" in result
        assert "D" in result

    def test_find_neighborhood_preserves_edges(self) -> None:
        """Test that neighborhood extraction preserves edge attributes."""
        mock_driver = MagicMock()
        builder = SimilarityNetworkBuilder(mock_driver)

        graph = nx.Graph()
        graph.add_edge("A", "B", weight=5, similarity=0.8)
        graph.add_edge("B", "C", weight=3, similarity=0.6)
        builder.graph = graph

        result = builder.find_artist_neighborhood("B", depth=1)

        # Check edge attributes are preserved
        assert result.has_edge("A", "B")
        assert result.edges["A", "B"]["weight"] == 5
        assert result.edges["A", "B"]["similarity"] == 0.8


class TestBuildStyleSimilarityNetwork:
    """Test style-based network building."""

    @pytest.mark.asyncio
    async def test_build_style_network_with_artists(self) -> None:
        """Test building style network for specific artists."""
        mock_driver = MagicMock()
        mock_session = AsyncMock()
        mock_result = AsyncMock()

        mock_records = [
            {
                "artist1": "Artist A",
                "artist2": "Artist B",
                "weight": 2,
                "shared_styles": ["Alternative Rock", "Indie"],
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

        graph = await builder._build_style_similarity_network(
            artist_list=["Artist A", "Artist B"],
            similarity_threshold=1.0,
            max_artists=100,
        )

        assert graph.number_of_nodes() == 2
        assert graph.number_of_edges() == 1
        assert graph.has_edge("Artist A", "Artist B")

        # Check edge attributes
        edge_data = graph.get_edge_data("Artist A", "Artist B")
        assert "shared_styles" in edge_data
        assert len(edge_data["shared_styles"]) == 2

    @pytest.mark.asyncio
    async def test_build_style_network_without_artists(self) -> None:
        """Test building style network for top artists."""
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

        graph = await builder._build_style_similarity_network(
            artist_list=None,
            similarity_threshold=1.0,
            max_artists=100,
        )

        # Should return empty graph when no data
        assert isinstance(graph, nx.Graph)


class TestEnrichNodeAttributes:
    """Test node attribute enrichment."""

    @pytest.mark.asyncio
    async def test_enrich_empty_graph(self) -> None:
        """Test enriching a graph with no nodes."""
        mock_driver = MagicMock()
        builder = SimilarityNetworkBuilder(mock_driver)

        graph = nx.Graph()
        await builder._enrich_node_attributes(graph)

        # Should complete without error
        assert graph.number_of_nodes() == 0

    @pytest.mark.asyncio
    async def test_enrich_with_data(self) -> None:
        """Test enriching nodes with genre and style data."""
        mock_driver = MagicMock()
        mock_session = AsyncMock()
        mock_result = AsyncMock()

        mock_records = [
            {
                "name": "Artist A",
                "genres": ["Rock", "Alternative"],
                "styles": ["Indie Rock", "Post-Punk"],
            },
            {
                "name": "Artist B",
                "genres": ["Jazz"],
                "styles": ["Bebop", "Cool Jazz"],
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

        # Create graph with nodes
        graph = nx.Graph()
        graph.add_node("Artist A")
        graph.add_node("Artist B")
        graph.add_edge("Artist A", "Artist B")

        await builder._enrich_node_attributes(graph)

        # Check that attributes were added
        assert "genres" in graph.nodes["Artist A"]
        assert "styles" in graph.nodes["Artist A"]
        assert "degree" in graph.nodes["Artist A"]
        assert graph.nodes["Artist A"]["genres"] == ["Rock", "Alternative"]
        assert len(graph.nodes["Artist A"]["styles"]) == 2

    @pytest.mark.asyncio
    async def test_enrich_with_null_data(self) -> None:
        """Test enriching nodes when database returns null values."""
        mock_driver = MagicMock()
        mock_session = AsyncMock()
        mock_result = AsyncMock()

        mock_records = [
            {
                "name": "Artist A",
                "genres": None,
                "styles": None,
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

        graph = nx.Graph()
        graph.add_node("Artist A")

        await builder._enrich_node_attributes(graph)

        # Should have empty lists when data is null
        assert graph.nodes["Artist A"]["genres"] == []
        assert graph.nodes["Artist A"]["styles"] == []
