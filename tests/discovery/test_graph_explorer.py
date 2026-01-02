"""Tests for the music knowledge graph explorer."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from discovery.graph_explorer import (
    GraphData,
    GraphEdge,
    GraphNode,
    GraphQuery,
    MusicGraphExplorer,
    PathResult,
    explore_graph,
)


class TestMusicGraphExplorer:
    """Test the MusicGraphExplorer class."""

    @pytest_asyncio.fixture
    async def graph_explorer(self, mock_neo4j_driver: Any) -> Any:
        """Create a MusicGraphExplorer instance with mocked dependencies."""
        with patch("discovery.graph_explorer.get_config") as mock_config:
            mock_config.return_value = MagicMock(
                neo4j_address="bolt://localhost:7687",
                neo4j_username="neo4j",
                neo4j_password="password",  # noqa: S106
            )

            explorer = MusicGraphExplorer()
            explorer.driver = mock_neo4j_driver

            return explorer

    @pytest.mark.asyncio
    async def test_initialize(self, graph_explorer: Any) -> None:
        """Test graph explorer initialization."""
        await graph_explorer.initialize()
        # Should not raise any exceptions

    @pytest.mark.asyncio
    async def test_search_nodes(self, graph_explorer: Any, mock_neo4j_driver: Any) -> None:
        """Test searching for nodes."""
        # Mock database results
        mock_result = AsyncMock()
        mock_node = MagicMock()
        mock_node.element_id = "123"
        mock_node.items.return_value = [
            ("name", "Miles Davis"),
            ("real_name", "Miles Dewey Davis III"),
        ]

        mock_records = [{"n": mock_node, "node_labels": ["Artist"]}]
        mock_result = mock_neo4j_driver.session.return_value.__aenter__.return_value.run.return_value
        mock_result.__aiter__.return_value = iter(mock_records)

        result = await graph_explorer.search_nodes("Miles", ["Artist"], 10)

        assert isinstance(result, GraphData)
        assert len(result.nodes) == 1
        assert result.nodes[0].name == "Miles Davis"

    @pytest.mark.asyncio
    async def test_expand_node(self, graph_explorer: Any, mock_neo4j_driver: Any) -> None:
        """Test expanding around a node."""
        # Mock central node result
        mock_central_result = AsyncMock()
        mock_central_node = MagicMock()
        mock_central_node.element_id = "123"
        mock_central_node.items.return_value = [("name", "Miles Davis")]

        mock_central_record = {"n": mock_central_node, "node_labels": ["Artist"]}
        mock_central_result.single.return_value = mock_central_record

        # Mock expansion result
        mock_expand_result = AsyncMock()
        mock_connected_node = MagicMock()
        mock_connected_node.element_id = "456"
        mock_connected_node.items.return_value = [("title", "Kind of Blue")]

        mock_relationship = MagicMock()
        mock_relationship.element_id = "789"
        mock_relationship.items.return_value = []

        mock_expand_records = [
            {
                "center": mock_central_node,
                "r": mock_relationship,
                "connected": mock_connected_node,
                "connected_labels": ["Release"],
                "rel_type": "BY",
            }
        ]
        mock_expand_result.__aiter__.return_value = iter(mock_expand_records)

        # Set up session mock to return different results for different queries
        session_mock = mock_neo4j_driver.session.return_value.__aenter__.return_value
        session_mock.run.side_effect = [mock_central_result, mock_expand_result]

        result = await graph_explorer.expand_node("123", 1, 30)

        assert isinstance(result, GraphData)
        assert len(result.nodes) == 2
        assert len(result.edges) == 1

    @pytest.mark.asyncio
    async def test_expand_node_not_found(self, graph_explorer: Any, mock_neo4j_driver: Any) -> None:
        """Test expanding around a non-existent node."""
        mock_result = AsyncMock()
        mock_result.single.return_value = None
        mock_neo4j_driver.session.return_value.__aenter__.return_value.run.return_value = mock_result

        result = await graph_explorer.expand_node("nonexistent")

        assert isinstance(result, GraphData)
        assert len(result.nodes) == 0
        assert "error" in result.metadata

    @pytest.mark.asyncio
    async def test_find_path(self, graph_explorer: Any, mock_neo4j_driver: Any) -> None:
        """Test finding path between nodes."""
        # Mock path result
        mock_result = AsyncMock()

        # Create mock path
        mock_path = MagicMock()
        mock_node1 = MagicMock()
        mock_node1.element_id = "123"
        mock_node1.labels = ["Artist"]
        mock_node1.items.return_value = [("name", "Miles Davis")]

        mock_node2 = MagicMock()
        mock_node2.element_id = "456"
        mock_node2.labels = ["Release"]
        mock_node2.items.return_value = [("title", "Kind of Blue")]

        mock_path.nodes = [mock_node1, mock_node2]

        mock_rel = MagicMock()
        mock_rel.element_id = "789"
        mock_rel.type = "BY"
        mock_rel.start_node.element_id = "123"
        mock_rel.end_node.element_id = "456"
        mock_rel.items.return_value = []

        mock_path.relationships = [mock_rel]

        mock_records = [{"path": mock_path, "path_length": 1}]
        mock_result = mock_neo4j_driver.session.return_value.__aenter__.return_value.run.return_value
        mock_result.__aiter__.return_value = iter(mock_records)

        graph_data, path_result = await graph_explorer.find_path("123", "456")

        assert isinstance(graph_data, GraphData)
        assert isinstance(path_result, PathResult)
        assert path_result.path_length == 1
        assert len(path_result.path) == 2

    @pytest.mark.asyncio
    async def test_find_path_no_path(self, graph_explorer: Any, mock_neo4j_driver: Any) -> None:
        """Test finding path when no path exists."""
        mock_result = mock_neo4j_driver.session.return_value.__aenter__.return_value.run.return_value
        mock_result.__aiter__.return_value = iter([])

        graph_data, path_result = await graph_explorer.find_path("123", "456")

        assert isinstance(graph_data, GraphData)
        assert isinstance(path_result, PathResult)
        assert path_result.path_length == 0
        assert "No connection found" in path_result.explanation

    @pytest.mark.asyncio
    async def test_get_neighborhood(self, graph_explorer: Any, mock_neo4j_driver: Any) -> None:
        """Test getting neighborhood around a node."""
        mock_result = AsyncMock()
        mock_neighbor = MagicMock()
        mock_neighbor.element_id = "456"
        mock_neighbor.items.return_value = [("name", "John Coltrane")]

        mock_records = [
            {
                "neighbor": mock_neighbor,
                "neighbor_labels": ["Artist"],
                "r": None,
                "connected": None,
                "connected_labels": None,
                "rel_type": None,
            }
        ]
        mock_result = mock_neo4j_driver.session.return_value.__aenter__.return_value.run.return_value
        mock_result.__aiter__.return_value = iter(mock_records)

        result = await graph_explorer.get_neighborhood("123", 2, 50)

        assert isinstance(result, GraphData)
        assert len(result.nodes) >= 1

    @pytest.mark.asyncio
    async def test_semantic_search(self, graph_explorer: Any, mock_neo4j_driver: Any) -> None:
        """Test semantic search across the graph."""
        mock_result = AsyncMock()
        mock_node = MagicMock()
        mock_node.element_id = "123"
        mock_node.items.return_value = [("name", "Miles Davis")]

        mock_records = [{"node": mock_node, "node_labels": ["Artist"], "search_type": "Artist"}]
        mock_result = mock_neo4j_driver.session.return_value.__aenter__.return_value.run.return_value
        mock_result.__aiter__.return_value = iter(mock_records)

        result = await graph_explorer.semantic_search("jazz trumpet", 20)

        assert isinstance(result, GraphData)
        assert len(result.nodes) == 1

    @pytest.mark.asyncio
    async def test_close(self, graph_explorer: Any) -> None:
        """Test closing the graph explorer."""
        await graph_explorer.close()
        if graph_explorer.driver:
            graph_explorer.driver.close.assert_called_once()


class TestGraphModels:
    """Test graph data models."""

    def test_graph_node_model(self) -> None:
        """Test GraphNode model."""
        node = GraphNode(
            id="123",
            label="Artist",
            name="Miles Davis",
            properties={"real_name": "Miles Dewey Davis III"},
            size=20,
            color="#ff6b6b",
        )

        assert node.id == "123"
        assert node.label == "Artist"
        assert node.name == "Miles Davis"
        assert node.size == 20

    def test_graph_edge_model(self) -> None:
        """Test GraphEdge model."""
        edge = GraphEdge(id="789", source="123", target="456", label="BY", properties={}, weight=1.0)

        assert edge.id == "789"
        assert edge.source == "123"
        assert edge.target == "456"
        assert edge.label == "BY"

    def test_graph_data_model(self) -> None:
        """Test GraphData model."""
        node = GraphNode(id="123", label="Artist", name="Miles Davis", properties={})

        edge = GraphEdge(id="789", source="123", target="456", label="BY", properties={})

        graph_data = GraphData(nodes=[node], edges=[edge], metadata={"total": 1})

        assert len(graph_data.nodes) == 1
        assert len(graph_data.edges) == 1
        assert graph_data.metadata["total"] == 1

    def test_graph_query_model(self) -> None:
        """Test GraphQuery model."""
        query = GraphQuery(query_type="expand", node_id="123", max_depth=2, limit=50)

        assert query.query_type == "expand"
        assert query.node_id == "123"
        assert query.max_depth == 2

    def test_path_result_model(self) -> None:
        """Test PathResult model."""
        path_result = PathResult(path=["123", "456"], path_length=1, total_paths=1, explanation="Direct connection")

        assert len(path_result.path) == 2
        assert path_result.path_length == 1
        assert path_result.total_paths == 1


class TestGraphExplorerAPI:
    """Test the graph explorer API functions."""

    @pytest.mark.asyncio
    async def test_explore_graph_search(self, mock_graph_explorer: Any, sample_graph_data: Any) -> None:
        """Test graph exploration search."""
        with patch("discovery.graph_explorer.graph_explorer", mock_graph_explorer):
            mock_graph_explorer.search_nodes.return_value = sample_graph_data

            query = GraphQuery(query_type="search", search_term="Miles Davis")

            graph_data, path_result = await explore_graph(query)

            assert isinstance(graph_data, dict)
            assert path_result is None

    @pytest.mark.asyncio
    async def test_explore_graph_expand(self, mock_graph_explorer: Any, sample_graph_data: Any) -> None:
        """Test graph exploration expand."""
        with patch("discovery.graph_explorer.graph_explorer", mock_graph_explorer):
            mock_graph_explorer.expand_node.return_value = sample_graph_data

            query = GraphQuery(query_type="expand", node_id="123")

            graph_data, _path_result = await explore_graph(query)

            assert isinstance(graph_data, dict)

    @pytest.mark.asyncio
    async def test_explore_graph_path(self, mock_graph_explorer: Any, sample_graph_data: Any) -> None:
        """Test graph exploration path finding."""
        with patch("discovery.graph_explorer.graph_explorer", mock_graph_explorer):
            path_result = PathResult(path=["123", "456"], path_length=1, total_paths=1, explanation="Test path")
            mock_graph_explorer.find_path.return_value = (sample_graph_data, path_result)

            query = GraphQuery(query_type="path", source_node="123", target_node="456")

            graph_data, returned_path = await explore_graph(query)

            assert isinstance(graph_data, dict)
            assert returned_path is not None

    @pytest.mark.asyncio
    async def test_explore_graph_invalid_query(self, mock_graph_explorer: Any) -> None:
        """Test handling invalid graph query."""
        with patch("discovery.graph_explorer.graph_explorer", mock_graph_explorer):
            query = GraphQuery(query_type="invalid")

            graph_data, path_result = await explore_graph(query)

            assert "error" in graph_data.metadata
            assert path_result is None
