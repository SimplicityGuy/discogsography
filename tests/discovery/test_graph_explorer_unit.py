"""Unit tests for Discovery service graph explorer functionality."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from discovery.graph_explorer import (
    GraphData,
    GraphEdge,
    GraphNode,
    GraphQuery,
    MusicGraphExplorer,
    PathResult,
    explore_graph,
    get_graph_explorer_instance,
)


class TestGraphNode:
    """Test the GraphNode model."""

    def test_graph_node_minimal(self) -> None:
        """Test GraphNode with minimal required fields."""
        node = GraphNode(
            id="123",
            label="Artist",
            name="Miles Davis",
            properties={"id": "123", "name": "Miles Davis"},
        )
        assert node.id == "123"
        assert node.label == "Artist"
        assert node.name == "Miles Davis"
        assert node.size == 10  # Default
        assert node.color == "#1f77b4"  # Default

    def test_graph_node_full(self) -> None:
        """Test GraphNode with all fields."""
        properties = {"id": "123", "name": "Miles Davis", "profile": "Jazz legend"}
        node = GraphNode(
            id="123",
            label="Artist",
            name="Miles Davis",
            properties=properties,
            size=20,
            color="#ff6b6b",
        )
        assert node.id == "123"
        assert node.label == "Artist"
        assert node.name == "Miles Davis"
        assert node.properties == properties
        assert node.size == 20
        assert node.color == "#ff6b6b"

    def test_graph_node_validation(self) -> None:
        """Test GraphNode validation."""
        with pytest.raises(ValidationError):
            GraphNode(id="123", label="Artist")  # type: ignore[call-arg]  # Missing name and properties


class TestGraphEdge:
    """Test the GraphEdge model."""

    def test_graph_edge_minimal(self) -> None:
        """Test GraphEdge with minimal required fields."""
        edge = GraphEdge(
            id="456",
            source="123",
            target="789",
            label="BY",
            properties={},
        )
        assert edge.id == "456"
        assert edge.source == "123"
        assert edge.target == "789"
        assert edge.label == "BY"
        assert edge.weight == 1.0  # Default

    def test_graph_edge_full(self) -> None:
        """Test GraphEdge with all fields."""
        properties = {"type": "collaboration", "year": 1959}
        edge = GraphEdge(
            id="456",
            source="123",
            target="789",
            label="COLLABORATED_ON",
            properties=properties,
            weight=5.0,
        )
        assert edge.id == "456"
        assert edge.source == "123"
        assert edge.target == "789"
        assert edge.label == "COLLABORATED_ON"
        assert edge.properties == properties
        assert edge.weight == 5.0


class TestGraphData:
    """Test the GraphData model."""

    def test_graph_data_empty(self) -> None:
        """Test GraphData with empty data."""
        data = GraphData(nodes=[], edges=[], metadata={})
        assert data.nodes == []
        assert data.edges == []
        assert data.metadata == {}

    def test_graph_data_with_content(self) -> None:
        """Test GraphData with nodes and edges."""
        node1 = GraphNode(id="1", label="Artist", name="Artist 1", properties={})
        node2 = GraphNode(id="2", label="Release", name="Album 1", properties={})
        edge = GraphEdge(id="e1", source="1", target="2", label="BY", properties={})

        data = GraphData(
            nodes=[node1, node2],
            edges=[edge],
            metadata={"query_type": "expand", "total": 2},
        )
        assert len(data.nodes) == 2
        assert len(data.edges) == 1
        assert data.metadata["query_type"] == "expand"


class TestGraphQuery:
    """Test the GraphQuery model."""

    def test_graph_query_minimal(self) -> None:
        """Test GraphQuery with minimal fields."""
        query = GraphQuery(query_type="search")
        assert query.query_type == "search"
        assert query.node_id is None
        assert query.source_node is None
        assert query.target_node is None
        assert query.search_term is None
        assert query.max_depth == 2
        assert query.limit == 50
        assert query.node_types is None

    def test_graph_query_expand(self) -> None:
        """Test GraphQuery for expand operation."""
        query = GraphQuery(
            query_type="expand",
            node_id="123",
            max_depth=3,
            limit=100,
        )
        assert query.query_type == "expand"
        assert query.node_id == "123"
        assert query.max_depth == 3
        assert query.limit == 100

    def test_graph_query_path(self) -> None:
        """Test GraphQuery for path finding."""
        query = GraphQuery(
            query_type="path",
            source_node="123",
            target_node="456",
            max_depth=5,
        )
        assert query.query_type == "path"
        assert query.source_node == "123"
        assert query.target_node == "456"
        assert query.max_depth == 5

    def test_graph_query_search_with_filter(self) -> None:
        """Test GraphQuery with node type filter."""
        query = GraphQuery(
            query_type="search",
            search_term="jazz",
            node_types=["Artist", "Genre"],
            limit=20,
        )
        assert query.search_term == "jazz"
        assert query.node_types == ["Artist", "Genre"]


class TestPathResult:
    """Test the PathResult model."""

    def test_path_result(self) -> None:
        """Test PathResult model."""
        result = PathResult(
            path=["node1", "node2", "node3"],
            path_length=2,
            total_paths=5,
            explanation="Found 5 paths, shortest has 2 degrees",
        )
        assert result.path == ["node1", "node2", "node3"]
        assert result.path_length == 2
        assert result.total_paths == 5
        assert "5 paths" in result.explanation


class TestMusicGraphExplorerInit:
    """Test MusicGraphExplorer initialization."""

    def test_music_graph_explorer_init(self) -> None:
        """Test MusicGraphExplorer initialization."""
        with patch("discovery.graph_explorer.get_config"):
            explorer = MusicGraphExplorer()
            assert explorer.driver is None
            assert explorer.node_colors["Artist"] == "#ff6b6b"
            assert explorer.node_colors["Release"] == "#4ecdc4"

    @pytest.mark.asyncio
    async def test_music_graph_explorer_initialize(self) -> None:
        """Test MusicGraphExplorer async initialization."""
        with (
            patch("discovery.graph_explorer.get_config") as mock_config,
            patch("discovery.graph_explorer.AsyncGraphDatabase.driver") as mock_driver,
        ):
            mock_config.return_value = MagicMock()
            mock_driver.return_value = AsyncMock()

            explorer = MusicGraphExplorer()
            await explorer.initialize()

            assert explorer.driver is not None
            mock_driver.assert_called_once()


class TestSearchNodes:
    """Test search_nodes method."""

    @pytest.mark.asyncio
    async def test_search_nodes_success(self) -> None:
        """Test successful node search."""
        with patch("discovery.graph_explorer.get_config") as mock_config:
            mock_config.return_value = MagicMock()

            # Create mock Neo4j session
            mock_session = AsyncMock()
            mock_result = AsyncMock()

            # Mock node with element_id
            mock_node = MagicMock()
            mock_node.element_id = "element-123"
            mock_node.items.return_value = [("name", "Miles Davis"), ("id", "123")]

            async def mock_records(self: Any) -> Any:
                yield {"n": mock_node, "node_labels": ["Artist"]}

            mock_result.__aiter__ = mock_records
            mock_session.run.return_value = mock_result

            # Create proper async context manager mock
            mock_context_manager = AsyncMock()
            mock_context_manager.__aenter__.return_value = mock_session
            mock_context_manager.__aexit__.return_value = None

            mock_driver = MagicMock()
            mock_driver.session.return_value = mock_context_manager

            explorer = MusicGraphExplorer()
            explorer.driver = mock_driver

            result = await explorer.search_nodes("Miles", limit=10)

            assert len(result.nodes) == 1
            assert result.nodes[0].name == "Miles Davis"
            assert result.nodes[0].label == "Artist"
            assert result.metadata["query_type"] == "search"
            assert result.metadata["search_term"] == "Miles"

    @pytest.mark.asyncio
    async def test_search_nodes_with_type_filter(self) -> None:
        """Test node search with type filter."""
        with patch("discovery.graph_explorer.get_config") as mock_config:
            mock_config.return_value = MagicMock()

            # Create mock Neo4j session
            mock_session = AsyncMock()
            mock_result = AsyncMock()

            mock_node = MagicMock()
            mock_node.element_id = "element-123"
            mock_node.items.return_value = [("name", "Jazz"), ("id", "g123")]

            async def mock_records(self: Any) -> Any:
                yield {"n": mock_node, "node_labels": ["Genre"]}

            mock_result.__aiter__ = mock_records
            mock_session.run.return_value = mock_result

            mock_context_manager = AsyncMock()
            mock_context_manager.__aenter__.return_value = mock_session
            mock_context_manager.__aexit__.return_value = None

            mock_driver = MagicMock()
            mock_driver.session.return_value = mock_context_manager

            explorer = MusicGraphExplorer()
            explorer.driver = mock_driver

            result = await explorer.search_nodes("Jazz", node_types=["Genre"], limit=10)

            assert len(result.nodes) == 1
            assert result.nodes[0].label == "Genre"


class TestExpandNode:
    """Test expand_node method."""

    @pytest.mark.asyncio
    async def test_expand_node_success(self) -> None:
        """Test successful node expansion."""
        with patch("discovery.graph_explorer.get_config") as mock_config:
            mock_config.return_value = MagicMock()

            # Create mock Neo4j session
            mock_session = AsyncMock()

            # Mock central node
            central_node = MagicMock()
            central_node.element_id = "center-123"
            central_node.items.return_value = [("name", "Miles Davis")]

            central_result = AsyncMock()
            central_result.single.return_value = {
                "n": central_node,
                "node_labels": ["Artist"],
            }

            # Mock connected nodes
            connected_node = MagicMock()
            connected_node.element_id = "connected-456"
            connected_node.items.return_value = [("title", "Kind of Blue")]

            relationship = MagicMock()
            relationship.element_id = "rel-789"
            relationship.items.return_value = []

            expand_result = AsyncMock()

            async def mock_expand_records(self: Any) -> Any:
                yield {
                    "center": central_node,
                    "r": relationship,
                    "connected": connected_node,
                    "connected_labels": ["Release"],
                    "rel_type": "BY",
                }

            expand_result.__aiter__ = mock_expand_records

            # Mock session to return different results
            call_count = [0]

            async def mock_run(*args: Any, **kwargs: Any) -> Any:
                call_count[0] += 1
                return central_result if call_count[0] == 1 else expand_result

            mock_session.run = mock_run

            mock_context_manager = AsyncMock()
            mock_context_manager.__aenter__.return_value = mock_session
            mock_context_manager.__aexit__.return_value = None

            mock_driver = MagicMock()
            mock_driver.session.return_value = mock_context_manager

            explorer = MusicGraphExplorer()
            explorer.driver = mock_driver

            result = await explorer.expand_node("center-123", max_depth=1, limit=30)

            assert len(result.nodes) == 2  # Central + connected
            assert len(result.edges) == 1
            assert result.metadata["query_type"] == "expand"

    @pytest.mark.asyncio
    async def test_expand_node_not_found(self) -> None:
        """Test expand_node when node not found."""
        with patch("discovery.graph_explorer.get_config") as mock_config:
            mock_config.return_value = MagicMock()

            mock_session = AsyncMock()
            central_result = AsyncMock()
            central_result.single.return_value = None

            mock_session.run.return_value = central_result

            mock_context_manager = AsyncMock()
            mock_context_manager.__aenter__.return_value = mock_session
            mock_context_manager.__aexit__.return_value = None

            mock_driver = MagicMock()
            mock_driver.session.return_value = mock_context_manager

            explorer = MusicGraphExplorer()
            explorer.driver = mock_driver

            result = await explorer.expand_node("invalid-id")

            assert result.nodes == []
            assert result.edges == []
            assert "error" in result.metadata


class TestFindPath:
    """Test find_path method."""

    @pytest.mark.asyncio
    async def test_find_path_success(self) -> None:
        """Test successful path finding."""
        with patch("discovery.graph_explorer.get_config") as mock_config:
            mock_config.return_value = MagicMock()

            # Create mock path components
            node1 = MagicMock()
            node1.element_id = "node1"
            node1.labels = ["Artist"]
            node1.items.return_value = [("name", "Artist 1")]

            node2 = MagicMock()
            node2.element_id = "node2"
            node2.labels = ["Release"]
            node2.items.return_value = [("title", "Album 1")]

            relationship = MagicMock()
            relationship.element_id = "rel1"
            relationship.type = "BY"
            relationship.start_node.element_id = "node1"
            relationship.end_node.element_id = "node2"
            relationship.items.return_value = []

            mock_path = MagicMock()
            mock_path.nodes = [node1, node2]
            mock_path.relationships = [relationship]

            mock_session = AsyncMock()
            mock_result = AsyncMock()

            async def mock_records(self: Any) -> Any:
                yield {"path": mock_path, "path_length": 1}

            mock_result.__aiter__ = mock_records
            mock_session.run.return_value = mock_result

            mock_context_manager = AsyncMock()
            mock_context_manager.__aenter__.return_value = mock_session
            mock_context_manager.__aexit__.return_value = None

            mock_driver = MagicMock()
            mock_driver.session.return_value = mock_context_manager

            explorer = MusicGraphExplorer()
            explorer.driver = mock_driver

            graph_data, path_result = await explorer.find_path("node1", "node2")

            assert len(graph_data.nodes) == 2
            assert len(graph_data.edges) == 1
            assert path_result.path_length == 1
            assert path_result.total_paths == 1

    @pytest.mark.asyncio
    async def test_find_path_not_found(self) -> None:
        """Test find_path when no path exists."""
        with patch("discovery.graph_explorer.get_config") as mock_config:
            mock_config.return_value = MagicMock()

            mock_session = AsyncMock()
            mock_result = AsyncMock()

            async def mock_records(self: Any) -> Any:
                return
                yield  # pragma: no cover

            mock_result.__aiter__ = mock_records
            mock_session.run.return_value = mock_result

            mock_context_manager = AsyncMock()
            mock_context_manager.__aenter__.return_value = mock_session
            mock_context_manager.__aexit__.return_value = None

            mock_driver = MagicMock()
            mock_driver.session.return_value = mock_context_manager

            explorer = MusicGraphExplorer()
            explorer.driver = mock_driver

            graph_data, path_result = await explorer.find_path("node1", "node2")

            assert graph_data.nodes == []
            assert path_result.path == []
            assert path_result.path_length == 0
            assert "No connection found" in path_result.explanation


class TestGetNeighborhood:
    """Test get_neighborhood method."""

    @pytest.mark.asyncio
    async def test_get_neighborhood_success(self) -> None:
        """Test successful neighborhood retrieval."""
        with patch("discovery.graph_explorer.get_config") as mock_config:
            mock_config.return_value = MagicMock()

            neighbor_node = MagicMock()
            neighbor_node.element_id = "neighbor1"
            neighbor_node.items.return_value = [("name", "Neighbor Artist")]

            mock_session = AsyncMock()
            mock_result = AsyncMock()

            async def mock_records(self: Any) -> Any:
                yield {
                    "neighbor": neighbor_node,
                    "neighbor_labels": ["Artist"],
                    "r": None,
                    "connected": None,
                    "connected_labels": None,
                    "rel_type": None,
                }

            mock_result.__aiter__ = mock_records
            mock_session.run.return_value = mock_result

            mock_context_manager = AsyncMock()
            mock_context_manager.__aenter__.return_value = mock_session
            mock_context_manager.__aexit__.return_value = None

            mock_driver = MagicMock()
            mock_driver.session.return_value = mock_context_manager

            explorer = MusicGraphExplorer()
            explorer.driver = mock_driver

            result = await explorer.get_neighborhood("center-node", radius=2, limit=50)

            assert len(result.nodes) > 0
            assert result.metadata["query_type"] == "neighborhood"
            assert result.metadata["radius"] == 2


class TestSemanticSearch:
    """Test semantic_search method."""

    @pytest.mark.asyncio
    async def test_semantic_search_success(self) -> None:
        """Test successful semantic search."""
        with patch("discovery.graph_explorer.get_config") as mock_config:
            mock_config.return_value = MagicMock()

            mock_node = MagicMock()
            mock_node.element_id = "search-result-1"
            mock_node.items.return_value = [("name", "Jazz Artist")]

            mock_session = AsyncMock()
            mock_result = AsyncMock()

            async def mock_records(self: Any) -> Any:
                yield {
                    "node": mock_node,
                    "node_labels": ["Artist"],
                    "search_type": "Artist",
                }

            mock_result.__aiter__ = mock_records
            mock_session.run.return_value = mock_result

            mock_context_manager = AsyncMock()
            mock_context_manager.__aenter__.return_value = mock_session
            mock_context_manager.__aexit__.return_value = None

            mock_driver = MagicMock()
            mock_driver.session.return_value = mock_context_manager

            explorer = MusicGraphExplorer()
            explorer.driver = mock_driver

            result = await explorer.semantic_search("jazz")

            assert len(result.nodes) == 1
            assert result.nodes[0].name == "Jazz Artist"
            assert result.metadata["query_type"] == "semantic_search"
            assert result.metadata["query"] == "jazz"


class TestCloseAndGlobalInstance:
    """Test close method and global instance management."""

    @pytest.mark.asyncio
    async def test_close_with_driver(self) -> None:
        """Test closing graph explorer with active driver."""
        with patch("discovery.graph_explorer.get_config") as mock_config:
            mock_config.return_value = MagicMock()
            mock_driver = AsyncMock()

            explorer = MusicGraphExplorer()
            explorer.driver = mock_driver

            await explorer.close()
            mock_driver.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_without_driver(self) -> None:
        """Test closing graph explorer without driver."""
        with patch("discovery.graph_explorer.get_config") as mock_config:
            mock_config.return_value = MagicMock()
            explorer = MusicGraphExplorer()
            explorer.driver = None

            # Should not raise error
            await explorer.close()

    def test_get_graph_explorer_instance(self) -> None:
        """Test global graph explorer instance management."""
        with (
            patch("discovery.graph_explorer.get_config") as mock_config,
            patch("discovery.graph_explorer.graph_explorer", None),
        ):
            mock_config.return_value = MagicMock()

            instance1 = get_graph_explorer_instance()
            instance2 = get_graph_explorer_instance()

            # Should return same instance
            assert instance1 is instance2
            assert isinstance(instance1, MusicGraphExplorer)


class TestExploreGraph:
    """Test the main explore_graph function."""

    @pytest.mark.asyncio
    async def test_explore_graph_search(self) -> None:
        """Test explore_graph with search query."""
        with patch("discovery.graph_explorer.get_graph_explorer_instance") as mock_getter:
            mock_instance = AsyncMock()
            mock_instance.search_nodes.return_value = GraphData(
                nodes=[],
                edges=[],
                metadata={"query_type": "search"},
            )
            mock_getter.return_value = mock_instance

            query = GraphQuery(query_type="search", search_term="jazz", limit=10)
            graph_data, path_result = await explore_graph(query)

            assert graph_data.metadata["query_type"] == "search"
            assert path_result is None
            mock_instance.search_nodes.assert_called_once_with("jazz", None, 10)

    @pytest.mark.asyncio
    async def test_explore_graph_expand(self) -> None:
        """Test explore_graph with expand query."""
        with patch("discovery.graph_explorer.get_graph_explorer_instance") as mock_getter:
            mock_instance = AsyncMock()
            mock_instance.expand_node.return_value = GraphData(
                nodes=[],
                edges=[],
                metadata={"query_type": "expand"},
            )
            mock_getter.return_value = mock_instance

            query = GraphQuery(query_type="expand", node_id="123", max_depth=2, limit=50)
            graph_data, path_result = await explore_graph(query)

            assert graph_data.metadata["query_type"] == "expand"
            assert path_result is None
            mock_instance.expand_node.assert_called_once_with("123", 2, 50)

    @pytest.mark.asyncio
    async def test_explore_graph_path(self) -> None:
        """Test explore_graph with path query."""
        with patch("discovery.graph_explorer.get_graph_explorer_instance") as mock_getter:
            mock_instance = AsyncMock()
            mock_instance.find_path.return_value = (
                GraphData(nodes=[], edges=[], metadata={"query_type": "path"}),
                PathResult(path=[], path_length=0, total_paths=0, explanation="Test"),
            )
            mock_getter.return_value = mock_instance

            query = GraphQuery(
                query_type="path",
                source_node="123",
                target_node="456",
                max_depth=4,
            )
            graph_data, path_result = await explore_graph(query)

            assert graph_data.metadata["query_type"] == "path"
            assert path_result is not None
            mock_instance.find_path.assert_called_once_with("123", "456", 4)

    @pytest.mark.asyncio
    async def test_explore_graph_neighborhood(self) -> None:
        """Test explore_graph with neighborhood query."""
        with patch("discovery.graph_explorer.get_graph_explorer_instance") as mock_getter:
            mock_instance = AsyncMock()
            mock_instance.get_neighborhood.return_value = GraphData(
                nodes=[],
                edges=[],
                metadata={"query_type": "neighborhood"},
            )
            mock_getter.return_value = mock_instance

            query = GraphQuery(query_type="neighborhood", node_id="123", max_depth=2, limit=50)
            graph_data, path_result = await explore_graph(query)

            assert graph_data.metadata["query_type"] == "neighborhood"
            assert path_result is None
            mock_instance.get_neighborhood.assert_called_once_with("123", 2, 50)

    @pytest.mark.asyncio
    async def test_explore_graph_semantic(self) -> None:
        """Test explore_graph with semantic search query."""
        with patch("discovery.graph_explorer.get_graph_explorer_instance") as mock_getter:
            mock_instance = AsyncMock()
            mock_instance.semantic_search.return_value = GraphData(
                nodes=[],
                edges=[],
                metadata={"query_type": "semantic_search"},
            )
            mock_getter.return_value = mock_instance

            query = GraphQuery(query_type="semantic", search_term="jazz fusion", limit=20)
            graph_data, path_result = await explore_graph(query)

            assert graph_data.metadata["query_type"] == "semantic_search"
            assert path_result is None
            mock_instance.semantic_search.assert_called_once_with("jazz fusion", 20)

    @pytest.mark.asyncio
    async def test_explore_graph_invalid_query(self) -> None:
        """Test explore_graph with invalid query parameters."""
        with patch("discovery.graph_explorer.get_graph_explorer_instance") as mock_getter:
            mock_instance = AsyncMock()
            mock_getter.return_value = mock_instance

            query = GraphQuery(query_type="search")  # Missing search_term
            graph_data, path_result = await explore_graph(query)

            assert "error" in graph_data.metadata
            assert path_result is None
