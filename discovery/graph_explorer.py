"""Real-time Music Knowledge Graph Explorer for interactive relationship discovery."""

from typing import Any

import structlog
from common import get_config
from neo4j import AsyncDriver, AsyncGraphDatabase
from pydantic import BaseModel


logger = structlog.get_logger(__name__)


class GraphNode(BaseModel):
    """Model for graph nodes."""

    id: str
    label: str  # Artist, Release, Label, Genre, Style
    name: str
    properties: dict[str, Any]
    size: int = 10
    color: str = "#1f77b4"


class GraphEdge(BaseModel):
    """Model for graph edges/relationships."""

    id: str
    source: str
    target: str
    label: str  # BY, ON, IS, MEMBER_OF, etc.
    properties: dict[str, Any]
    weight: float = 1.0


class GraphData(BaseModel):
    """Complete graph data structure."""

    nodes: list[GraphNode]
    edges: list[GraphEdge]
    metadata: dict[str, Any]


class GraphQuery(BaseModel):
    """Query model for graph exploration."""

    query_type: str  # expand, path, search, neighborhood
    node_id: str | None = None
    source_node: str | None = None
    target_node: str | None = None
    search_term: str | None = None
    max_depth: int = 2
    limit: int = 50
    node_types: list[str] | None = None  # Filter by node types


class PathResult(BaseModel):
    """Result for path finding queries."""

    path: list[str]  # List of node IDs
    path_length: int
    total_paths: int
    explanation: str


class MusicGraphExplorer:
    """Interactive music knowledge graph explorer."""

    def __init__(self) -> None:
        self.config = get_config()
        self.driver: AsyncDriver | None = None

        # Color scheme for different node types
        self.node_colors = {
            "Artist": "#ff6b6b",  # Red
            "Release": "#4ecdc4",  # Teal
            "Label": "#45b7d1",  # Blue
            "Genre": "#f9ca24",  # Yellow
            "Style": "#f0932b",  # Orange
            "Master": "#eb4d4b",  # Dark Red
        }

    async def initialize(self) -> None:
        """Initialize the graph explorer."""
        logger.info("🔍 Initializing graph explorer engine...")

        self.driver = AsyncGraphDatabase.driver(self.config.neo4j_address, auth=(self.config.neo4j_username, self.config.neo4j_password))

        logger.info("✅ Music Knowledge Graph Explorer initialized")

    async def search_nodes(self, search_term: str, node_types: list[str] | None = None, limit: int = 20) -> GraphData:
        """Search for nodes by name/title."""
        logger.info("🔍 Searching for nodes", search_term=search_term)

        assert self.driver is not None, "Driver must be initialized before searching nodes"  # nosec B101
        # Build type filter
        type_filter = ""
        if node_types:
            type_labels = " OR ".join([f"n:{node_type}" for node_type in node_types])
            type_filter = f"WHERE ({type_labels})"

        assert self.driver is not None, "Driver must be initialized"  # nosec B101
        async with self.driver.session() as session:
            query = f"""
                MATCH (n)
                {type_filter}
                WHERE (n.name CONTAINS $search OR n.title CONTAINS $search)
                RETURN n, labels(n) as node_labels
                LIMIT $limit
            """
            params: dict[str, Any] = {"search": search_term, "limit": limit}
            logger.debug("🔍 Executing Neo4j query", query=query.strip(), params=params)

            result = await session.run(query, **params)

            nodes = []
            async for record in result:
                node = record["n"]
                node_labels = record["node_labels"]
                primary_label = node_labels[0] if node_labels else "Unknown"

                # Get node properties
                properties = dict(node.items())
                node_name = properties.get("name") or properties.get("title", "Unknown")

                nodes.append(
                    GraphNode(
                        id=str(node.element_id),
                        label=primary_label,
                        name=node_name,
                        properties=properties,
                        size=15,
                        color=self.node_colors.get(primary_label, "#666666"),
                    )
                )

        return GraphData(
            nodes=nodes,
            edges=[],
            metadata={
                "query_type": "search",
                "search_term": search_term,
                "total_nodes": len(nodes),
            },
        )

    async def expand_node(self, node_id: str, max_depth: int = 1, limit: int = 30) -> GraphData:
        """Expand around a specific node to show its relationships."""
        logger.info("📈 Expanding node", node_id=node_id)

        assert self.driver is not None, "Driver must be initialized"  # nosec B101
        async with self.driver.session() as session:
            # Get the central node
            query = """
                MATCH (n)
                WHERE elementId(n) = $node_id
                RETURN n, labels(n) as node_labels
            """
            params: dict[str, Any] = {"node_id": node_id}
            logger.debug("🔍 Executing Neo4j query", query=query.strip(), params=params)

            central_result = await session.run(query, **params)

            central_record = await central_result.single()
            if not central_record:
                return GraphData(nodes=[], edges=[], metadata={"error": "Node not found"})

            central_node = central_record["n"]
            central_labels = central_record["node_labels"]
            central_label = central_labels[0] if central_labels else "Unknown"
            central_props = dict(central_node.items())
            central_name = central_props.get("name") or central_props.get("title", "Unknown")

            # Get connected nodes and relationships
            query = """
                MATCH (center)-[r]-(connected)
                WHERE elementId(center) = $node_id
                RETURN center, r, connected, labels(connected) as connected_labels, type(r) as rel_type
                LIMIT $limit
            """
            expand_params: dict[str, Any] = {"node_id": node_id, "limit": limit}
            logger.debug("🔍 Executing Neo4j query", query=query.strip(), params=expand_params)

            expand_result = await session.run(query, **expand_params)

            nodes = [
                GraphNode(
                    id=node_id,
                    label=central_label,
                    name=central_name,
                    properties=central_props,
                    size=20,  # Central node is larger
                    color=self.node_colors.get(central_label, "#666666"),
                )
            ]

            edges = []
            connected_node_ids = {node_id}

            async for record in expand_result:
                connected = record["connected"]
                relationship = record["r"]
                connected_labels = record["connected_labels"]
                rel_type = record["rel_type"]

                connected_label = connected_labels[0] if connected_labels else "Unknown"
                connected_props = dict(connected.items())
                connected_name = connected_props.get("name") or connected_props.get("title", "Unknown")
                connected_id = str(connected.element_id)

                # Add connected node if not already added
                if connected_id not in connected_node_ids:
                    nodes.append(
                        GraphNode(
                            id=connected_id,
                            label=connected_label,
                            name=connected_name,
                            properties=connected_props,
                            size=12,
                            color=self.node_colors.get(connected_label, "#666666"),
                        )
                    )
                    connected_node_ids.add(connected_id)

                # Add relationship
                rel_props = dict(relationship.items())
                edges.append(
                    GraphEdge(
                        id=str(relationship.element_id),
                        source=node_id,
                        target=connected_id,
                        label=rel_type,
                        properties=rel_props,
                        weight=rel_props.get("weight", 1.0),
                    )
                )

        return GraphData(
            nodes=nodes,
            edges=edges,
            metadata={
                "query_type": "expand",
                "central_node": central_name,
                "max_depth": max_depth,
                "total_connections": len(edges),
            },
        )

    async def find_path(self, source_node: str, target_node: str, _max_depth: int = 4) -> tuple[GraphData, PathResult]:
        """Find shortest paths between two nodes."""
        logger.info("🛤️ Finding path", source_node=source_node, target_node=target_node)

        assert self.driver is not None, "Driver must be initialized"  # nosec B101
        async with self.driver.session() as session:
            # Find shortest paths
            query = """
                MATCH (source), (target)
                WHERE elementId(source) = $source_id AND elementId(target) = $target_id
                MATCH path = shortestPath((source)-[*1..6]-(target))
                RETURN path, length(path) as path_length
                ORDER BY path_length
                LIMIT 5
            """
            params: dict[str, Any] = {"source_id": source_node, "target_id": target_node}
            logger.debug("🔍 Executing Neo4j query", query=query.strip(), params=params)

            result = await session.run(query, **params)

            paths = []
            all_nodes = {}
            all_edges = {}

            async for record in result:
                path = record["path"]
                path_length = record["path_length"]

                path_nodes = []
                for node in path.nodes:
                    node_id = str(node.element_id)
                    path_nodes.append(node_id)

                    if node_id not in all_nodes:
                        labels = list(node.labels)
                        primary_label = labels[0] if labels else "Unknown"
                        props = dict(node.items())
                        node_name = props.get("name") or props.get("title", "Unknown")

                        all_nodes[node_id] = GraphNode(
                            id=node_id,
                            label=primary_label,
                            name=node_name,
                            properties=props,
                            size=15,
                            color=self.node_colors.get(primary_label, "#666666"),
                        )

                for rel in path.relationships:
                    rel_id = str(rel.element_id)
                    if rel_id not in all_edges:
                        rel_props = dict(rel.items())
                        all_edges[rel_id] = GraphEdge(
                            id=rel_id,
                            source=str(rel.start_node.element_id),
                            target=str(rel.end_node.element_id),
                            label=rel.type,
                            properties=rel_props,
                            weight=rel_props.get("weight", 1.0),
                        )

                paths.append({"nodes": path_nodes, "length": path_length})

            if not paths:
                return (
                    GraphData(nodes=[], edges=[], metadata={"error": "No path found"}),
                    PathResult(path=[], path_length=0, total_paths=0, explanation="No connection found"),
                )

            # Use the shortest path for visualization
            shortest_path = paths[0]

            # Generate explanation
            path_explanation = f"Shortest path has {shortest_path['length']} degrees of separation"
            if len(paths) > 1:
                path_explanation += f" (found {len(paths)} total paths)"

            graph_data = GraphData(
                nodes=list(all_nodes.values()),
                edges=list(all_edges.values()),
                metadata={
                    "query_type": "path",
                    "total_paths": len(paths),
                    "shortest_length": shortest_path["length"],
                },
            )

            path_result = PathResult(
                path=shortest_path["nodes"],
                path_length=shortest_path["length"],
                total_paths=len(paths),
                explanation=path_explanation,
            )

            return graph_data, path_result

    async def get_neighborhood(self, node_id: str, radius: int = 2, limit: int = 50) -> GraphData:
        """Get the neighborhood around a node up to a certain radius."""
        logger.info("🏘️ Getting neighborhood for node", node_id=node_id)

        assert self.driver is not None, "Driver must be initialized"  # nosec B101
        async with self.driver.session() as session:
            # Get neighborhood using variable-length paths
            query = """
                MATCH (center)-[*1..3]-(neighbor)
                WHERE elementId(center) = $node_id
                OPTIONAL MATCH (neighbor)-[r]-(connected)
                WHERE connected IN [(center)-[*1..2]-(n) | n]
                RETURN DISTINCT neighbor, labels(neighbor) as neighbor_labels,
                       r, connected, labels(connected) as connected_labels, type(r) as rel_type
                LIMIT $limit
            """
            params: dict[str, Any] = {"node_id": node_id, "radius": radius, "limit": limit}
            logger.debug("🔍 Executing Neo4j query", query=query.strip(), params=params)

            result = await session.run(query, **params)

            nodes = {}
            edges = {}

            async for record in result:
                neighbor = record["neighbor"]
                neighbor_labels = record["neighbor_labels"]

                # Add neighbor node
                neighbor_id = str(neighbor.element_id)
                if neighbor_id not in nodes:
                    neighbor_label = neighbor_labels[0] if neighbor_labels else "Unknown"
                    neighbor_props = dict(neighbor.items())
                    neighbor_name = neighbor_props.get("name") or neighbor_props.get("title", "Unknown")

                    nodes[neighbor_id] = GraphNode(
                        id=neighbor_id,
                        label=neighbor_label,
                        name=neighbor_name,
                        properties=neighbor_props,
                        size=12,
                        color=self.node_colors.get(neighbor_label, "#666666"),
                    )

                # Add relationship if exists
                if record["r"] and record["connected"]:
                    rel = record["r"]
                    connected = record["connected"]
                    connected_labels = record["connected_labels"]
                    rel_type = record["rel_type"]

                    connected_id = str(connected.element_id)
                    rel_id = str(rel.element_id)

                    # Add connected node
                    if connected_id not in nodes:
                        connected_label = connected_labels[0] if connected_labels else "Unknown"
                        connected_props = dict(connected.items())
                        connected_name = connected_props.get("name") or connected_props.get("title", "Unknown")

                        nodes[connected_id] = GraphNode(
                            id=connected_id,
                            label=connected_label,
                            name=connected_name,
                            properties=connected_props,
                            size=10,
                            color=self.node_colors.get(connected_label, "#666666"),
                        )

                    # Add edge
                    if rel_id not in edges:
                        rel_props = dict(rel.items())
                        edges[rel_id] = GraphEdge(
                            id=rel_id,
                            source=neighbor_id,
                            target=connected_id,
                            label=rel_type,
                            properties=rel_props,
                            weight=rel_props.get("weight", 1.0),
                        )

        return GraphData(
            nodes=list(nodes.values()),
            edges=list(edges.values()),
            metadata={
                "query_type": "neighborhood",
                "radius": radius,
                "total_nodes": len(nodes),
                "total_edges": len(edges),
            },
        )

    async def semantic_search(self, query: str, _limit: int = 20) -> GraphData:
        """Perform semantic search across the knowledge graph."""
        logger.info("🧠 Performing semantic search", query=query)

        # For now, implement as enhanced text search
        # Could be extended with embedding-based similarity

        assert self.driver is not None, "Driver must be initialized"  # nosec B101
        async with self.driver.session() as session:
            cypher_query = """
                // Search artists
                MATCH (a:Artist)
                WHERE a.name CONTAINS $query OR a.real_name CONTAINS $query OR a.profile CONTAINS $query
                RETURN a as node, labels(a) as node_labels, 'Artist' as search_type
                LIMIT 5

                UNION

                // Search releases
                MATCH (r:Release)
                WHERE r.title CONTAINS $query
                RETURN r as node, labels(r) as node_labels, 'Release' as search_type
                LIMIT 5

                UNION

                // Search labels
                MATCH (l:Label)
                WHERE l.name CONTAINS $query OR l.profile CONTAINS $query
                RETURN l as node, labels(l) as node_labels, 'Label' as search_type
                LIMIT 5

                UNION

                // Search genres
                MATCH (g:Genre)
                WHERE g.name CONTAINS $query
                RETURN g as node, labels(g) as node_labels, 'Genre' as search_type
                LIMIT 5
            """
            params = {"query": query}
            logger.debug("🔍 Executing Neo4j query", query=cypher_query.strip(), params=params)

            result = await session.run(cypher_query, params)

            nodes = []
            async for record in result:
                node = record["node"]
                node_labels = record["node_labels"]
                search_type = record["search_type"]

                primary_label = node_labels[0] if node_labels else "Unknown"
                props = dict(node.items())
                node_name = props.get("name") or props.get("title", "Unknown")

                nodes.append(
                    GraphNode(
                        id=str(node.element_id),
                        label=primary_label,
                        name=node_name,
                        properties={**props, "search_type": search_type},
                        size=15,
                        color=self.node_colors.get(primary_label, "#666666"),
                    )
                )

        return GraphData(
            nodes=nodes,
            edges=[],
            metadata={"query_type": "semantic_search", "query": query, "total_results": len(nodes)},
        )

    async def close(self) -> None:
        """Close database connections."""
        if self.driver:
            await self.driver.close()


# Global graph explorer instance - initialized lazily
graph_explorer: MusicGraphExplorer | None = None


def get_graph_explorer_instance() -> MusicGraphExplorer:
    """Get or create the global graph explorer instance."""
    global graph_explorer
    if graph_explorer is None:
        graph_explorer = MusicGraphExplorer()
    return graph_explorer


async def explore_graph(query: GraphQuery) -> tuple[GraphData, PathResult | None]:
    """Main entry point for graph exploration."""
    graph_explorer_instance = get_graph_explorer_instance()
    path_result = None

    if query.query_type == "search" and query.search_term:
        graph_data = await graph_explorer_instance.search_nodes(query.search_term, query.node_types, query.limit)
    elif query.query_type == "expand" and query.node_id:
        graph_data = await graph_explorer_instance.expand_node(query.node_id, query.max_depth, query.limit)
    elif query.query_type == "path" and query.source_node and query.target_node:
        graph_data, path_result = await graph_explorer_instance.find_path(query.source_node, query.target_node, query.max_depth)
    elif query.query_type == "neighborhood" and query.node_id:
        graph_data = await graph_explorer_instance.get_neighborhood(query.node_id, query.max_depth, query.limit)
    elif query.query_type == "semantic" and query.search_term:
        graph_data = await graph_explorer_instance.semantic_search(query.search_term, query.limit)
    else:
        graph_data = GraphData(nodes=[], edges=[], metadata={"error": "Invalid query parameters"})

    return graph_data, path_result
