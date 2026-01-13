"""Artist similarity networks and visualization support.

This module builds similarity networks for artists and provides
export functionality for various visualization formats (Plotly, D3, Cytoscape).
"""

from typing import Any

import networkx as nx
import structlog
from neo4j import AsyncDriver


logger = structlog.get_logger(__name__)


class SimilarityNetworkBuilder:
    """Build and export artist similarity networks."""

    def __init__(self, driver: AsyncDriver) -> None:
        """Initialize similarity network builder.

        Args:
            driver: Neo4j async driver instance
        """
        self.driver = driver
        self.graph: nx.Graph | None = None

    async def build_similarity_network(
        self,
        artist_list: list[str] | None = None,
        similarity_threshold: float = 0.3,
        max_artists: int = 100,
        similarity_method: str = "collaboration",
    ) -> nx.Graph:
        """Build artist similarity network.

        Args:
            artist_list: Specific artists to include, or None for top artists
            similarity_threshold: Minimum similarity to create edge
            max_artists: Maximum number of artists if artist_list is None
            similarity_method: Method to calculate similarity (collaboration, genre, style)

        Returns:
            NetworkX graph with similarity edges
        """
        logger.info("🔨 Building artist similarity network...")

        graph = nx.Graph()

        if similarity_method == "collaboration":
            graph = await self._build_collaboration_network(artist_list, similarity_threshold, max_artists)
        elif similarity_method == "genre":
            graph = await self._build_genre_similarity_network(artist_list, similarity_threshold, max_artists)
        elif similarity_method == "style":
            graph = await self._build_style_similarity_network(artist_list, similarity_threshold, max_artists)

        self.graph = graph

        logger.info(
            "✅ Built similarity network",
            nodes=graph.number_of_nodes(),
            edges=graph.number_of_edges(),
            method=similarity_method,
        )

        return graph

    async def _build_collaboration_network(
        self,
        artist_list: list[str] | None,
        similarity_threshold: float,
        max_artists: int,
    ) -> nx.Graph:
        """Build network based on collaboration strength.

        Args:
            artist_list: Optional list of artists
            similarity_threshold: Minimum collaboration count
            max_artists: Maximum artists

        Returns:
            NetworkX graph
        """
        graph = nx.Graph()

        async with self.driver.session() as session:
            if artist_list:
                # Build network for specific artists
                result = await session.run(
                    """
                    MATCH (a1:Artist)-[r]-(a2:Artist)
                    WHERE a1.name IN $artist_list AND a2.name IN $artist_list
                          AND a1.name < a2.name
                    WITH a1, a2, count(r) AS weight
                    WHERE weight >= $threshold
                    RETURN a1.name AS artist1, a2.name AS artist2, weight
                    """,
                    artist_list=artist_list,
                    threshold=int(similarity_threshold),
                )
            else:
                # Build network for top connected artists
                result = await session.run(
                    """
                    MATCH (a1:Artist)-[r]-(a2:Artist)
                    WHERE a1.name < a2.name
                    WITH a1, a2, count(r) AS weight
                    WHERE weight >= $threshold
                    RETURN a1.name AS artist1, a2.name AS artist2, weight
                    ORDER BY weight DESC
                    LIMIT $max_artists
                    """,
                    threshold=int(similarity_threshold),
                    max_artists=max_artists,
                )

            async for record in result:
                artist1 = record["artist1"]
                artist2 = record["artist2"]
                weight = record["weight"]

                # Add nodes with attributes (will be fetched later)
                graph.add_node(artist1)
                graph.add_node(artist2)

                # Add edge with similarity weight
                graph.add_edge(artist1, artist2, weight=weight, similarity=float(weight))

        # Fetch node attributes
        await self._enrich_node_attributes(graph)

        return graph

    async def _build_genre_similarity_network(
        self,
        artist_list: list[str] | None,
        similarity_threshold: float,
        max_artists: int,
    ) -> nx.Graph:
        """Build network based on shared genres.

        Args:
            artist_list: Optional list of artists
            similarity_threshold: Minimum shared genres
            max_artists: Maximum artists

        Returns:
            NetworkX graph
        """
        graph = nx.Graph()

        async with self.driver.session() as session:
            query_params: dict[str, Any] = {
                "threshold": int(similarity_threshold),
                "max_artists": max_artists,
            }

            if artist_list:
                query = """
                    MATCH (a1:Artist)<-[:BY]-(r1:Release)-[:IS]->(g:Genre)<-[:IS]-(r2:Release)-[:BY]->(a2:Artist)
                    WHERE a1.name IN $artist_list AND a2.name IN $artist_list
                          AND a1.name < a2.name
                    WITH a1, a2, collect(DISTINCT g.name) AS shared_genres
                    WHERE size(shared_genres) >= $threshold
                    RETURN a1.name AS artist1, a2.name AS artist2,
                           shared_genres, size(shared_genres) AS weight
                """
                query_params["artist_list"] = artist_list
            else:
                query = """
                    MATCH (a1:Artist)<-[:BY]-(r1:Release)-[:IS]->(g:Genre)<-[:IS]-(r2:Release)-[:BY]->(a2:Artist)
                    WHERE a1.name < a2.name
                    WITH a1, a2, collect(DISTINCT g.name) AS shared_genres
                    WHERE size(shared_genres) >= $threshold
                    RETURN a1.name AS artist1, a2.name AS artist2,
                           shared_genres, size(shared_genres) AS weight
                    ORDER BY weight DESC
                    LIMIT $max_artists
                """

            result = await session.run(query, **query_params)

            async for record in result:
                artist1 = record["artist1"]
                artist2 = record["artist2"]
                weight = record["weight"]
                shared_genres = record["shared_genres"]

                graph.add_node(artist1)
                graph.add_node(artist2)

                graph.add_edge(
                    artist1,
                    artist2,
                    weight=weight,
                    similarity=float(weight),
                    shared_genres=shared_genres,
                )

        await self._enrich_node_attributes(graph)

        return graph

    async def _build_style_similarity_network(
        self,
        artist_list: list[str] | None,
        similarity_threshold: float,
        max_artists: int,
    ) -> nx.Graph:
        """Build network based on shared styles.

        Args:
            artist_list: Optional list of artists
            similarity_threshold: Minimum shared styles
            max_artists: Maximum artists

        Returns:
            NetworkX graph
        """
        graph = nx.Graph()

        async with self.driver.session() as session:
            query_params: dict[str, Any] = {
                "threshold": int(similarity_threshold),
                "max_artists": max_artists,
            }

            if artist_list:
                query = """
                    MATCH (a1:Artist)<-[:BY]-(r1:Release)-[:IS]->(s:Style)<-[:IS]-(r2:Release)-[:BY]->(a2:Artist)
                    WHERE a1.name IN $artist_list AND a2.name IN $artist_list
                          AND a1.name < a2.name
                    WITH a1, a2, collect(DISTINCT s.name) AS shared_styles
                    WHERE size(shared_styles) >= $threshold
                    RETURN a1.name AS artist1, a2.name AS artist2,
                           shared_styles, size(shared_styles) AS weight
                """
                query_params["artist_list"] = artist_list
            else:
                query = """
                    MATCH (a1:Artist)<-[:BY]-(r1:Release)-[:IS]->(s:Style)<-[:IS]-(r2:Release)-[:BY]->(a2:Artist)
                    WHERE a1.name < a2.name
                    WITH a1, a2, collect(DISTINCT s.name) AS shared_styles
                    WHERE size(shared_styles) >= $threshold
                    RETURN a1.name AS artist1, a2.name AS artist2,
                           shared_styles, size(shared_styles) AS weight
                    ORDER BY weight DESC
                    LIMIT $max_artists
                """

            result = await session.run(query, **query_params)

            async for record in result:
                artist1 = record["artist1"]
                artist2 = record["artist2"]
                weight = record["weight"]
                shared_styles = record["shared_styles"]

                graph.add_node(artist1)
                graph.add_node(artist2)

                graph.add_edge(
                    artist1,
                    artist2,
                    weight=weight,
                    similarity=float(weight),
                    shared_styles=shared_styles,
                )

        await self._enrich_node_attributes(graph)

        return graph

    async def _enrich_node_attributes(self, graph: nx.Graph) -> None:
        """Fetch and add attributes to graph nodes.

        Args:
            graph: NetworkX graph to enrich
        """
        artist_names = list(graph.nodes())

        if not artist_names:
            return

        async with self.driver.session() as session:
            result = await session.run(
                """
                MATCH (a:Artist)
                WHERE a.name IN $artist_names
                OPTIONAL MATCH (a)-[:IS]->(g:Genre)
                OPTIONAL MATCH (a)-[:IS]->(s:Style)
                RETURN a.name AS name,
                       collect(DISTINCT g.name) AS genres,
                       collect(DISTINCT s.name) AS styles
                """,
                artist_names=artist_names,
            )

            async for record in result:
                name = record["name"]
                if name in graph:
                    graph.nodes[name]["genres"] = record["genres"] or []
                    graph.nodes[name]["styles"] = record["styles"] or []
                    graph.nodes[name]["degree"] = graph.degree(name)

    def export_to_plotly(self) -> dict[str, Any]:
        """Export network to Plotly format.

        Returns:
            Dictionary with node and edge data for Plotly
        """
        if self.graph is None:
            return {}

        # Calculate layout using spring layout
        pos = nx.spring_layout(self.graph, k=1, iterations=50)

        # Prepare edge traces
        edge_traces = []

        for edge in self.graph.edges(data=True):
            x0, y0 = pos[edge[0]]
            x1, y1 = pos[edge[1]]
            weight = edge[2].get("weight", 1)

            edge_trace = {
                "x": [x0, x1, None],
                "y": [y0, y1, None],
                "mode": "lines",
                "line": {
                    "width": min(weight, 10),  # Cap line width
                    "color": "#888",
                },
                "hoverinfo": "text",
                "text": f"{edge[0]} - {edge[1]}<br>Weight: {weight}",
            }

            edge_traces.append(edge_trace)

        # Prepare node trace
        node_x = []
        node_y = []
        node_text = []
        node_size = []

        for node in self.graph.nodes():
            x, y = pos[node]
            node_x.append(x)
            node_y.append(y)

            # Node label with attributes
            genres = self.graph.nodes[node].get("genres", [])
            degree = self.graph.nodes[node].get("degree", 0)

            node_text.append(f"{node}<br>Degree: {degree}<br>Genres: {', '.join(genres[:3])}")

            # Node size based on degree
            node_size.append(max(10, min(degree * 5, 50)))

        node_trace = {
            "x": node_x,
            "y": node_y,
            "mode": "markers+text",
            "text": list(self.graph.nodes()),
            "textposition": "top center",
            "hovertext": node_text,
            "marker": {
                "size": node_size,
                "color": node_size,
                "colorscale": "Viridis",
                "showscale": True,
                "colorbar": {"title": "Connections"},
            },
        }

        return {
            "edges": edge_traces,
            "nodes": node_trace,
            "layout": {
                "title": "Artist Similarity Network",
                "showlegend": False,
                "hovermode": "closest",
                "xaxis": {"showgrid": False, "zeroline": False, "showticklabels": False},
                "yaxis": {"showgrid": False, "zeroline": False, "showticklabels": False},
            },
        }

    def export_to_cytoscape(self) -> dict[str, Any]:
        """Export network to Cytoscape.js format.

        Returns:
            Dictionary with elements for Cytoscape.js
        """
        if self.graph is None:
            return {"elements": {"nodes": [], "edges": []}}

        nodes = []
        edges = []

        # Add nodes
        for node in self.graph.nodes(data=True):
            node_id = node[0]
            node_data = node[1]

            nodes.append(
                {
                    "data": {
                        "id": node_id,
                        "label": node_id,
                        "genres": node_data.get("genres", []),
                        "styles": node_data.get("styles", []),
                        "degree": node_data.get("degree", 0),
                    }
                }
            )

        # Add edges
        for edge in self.graph.edges(data=True):
            source = edge[0]
            target = edge[1]
            edge_data = edge[2]

            edges.append(
                {
                    "data": {
                        "id": f"{source}-{target}",
                        "source": source,
                        "target": target,
                        "weight": edge_data.get("weight", 1),
                        "similarity": edge_data.get("similarity", 0),
                    }
                }
            )

        return {
            "elements": {
                "nodes": nodes,
                "edges": edges,
            }
        }

    def export_to_d3(self) -> dict[str, Any]:
        """Export network to D3.js force-directed graph format.

        Returns:
            Dictionary with nodes and links for D3.js
        """
        if self.graph is None:
            return {"nodes": [], "links": []}

        nodes = []
        links = []

        # Create node index mapping
        node_index = {node: idx for idx, node in enumerate(self.graph.nodes())}

        # Add nodes
        for node in self.graph.nodes(data=True):
            node_id = node[0]
            node_data = node[1]

            nodes.append(
                {
                    "id": node_id,
                    "group": len(node_data.get("genres", [])),  # Group by genre count
                    "genres": node_data.get("genres", []),
                    "styles": node_data.get("styles", []),
                    "degree": node_data.get("degree", 0),
                }
            )

        # Add links
        for edge in self.graph.edges(data=True):
            source = edge[0]
            target = edge[1]
            edge_data = edge[2]

            links.append(
                {
                    "source": node_index[source],
                    "target": node_index[target],
                    "value": edge_data.get("weight", 1),
                    "similarity": edge_data.get("similarity", 0),
                }
            )

        return {
            "nodes": nodes,
            "links": links,
        }

    def export_to_gexf(self, filepath: str) -> None:
        """Export network to GEXF format (for Gephi).

        Args:
            filepath: Path to save GEXF file
        """
        if self.graph is None:
            logger.warning("⚠️ No graph to export")
            return

        nx.write_gexf(self.graph, filepath)
        logger.info("💾 Exported network to GEXF", filepath=filepath)

    def export_to_graphml(self, filepath: str) -> None:
        """Export network to GraphML format.

        Args:
            filepath: Path to save GraphML file
        """
        if self.graph is None:
            logger.warning("⚠️ No graph to export")
            return

        nx.write_graphml(self.graph, filepath)
        logger.info("💾 Exported network to GraphML", filepath=filepath)

    def get_network_statistics(self) -> dict[str, Any]:
        """Get statistics about the similarity network.

        Returns:
            Network statistics
        """
        if self.graph is None:
            return {}

        stats = {
            "num_nodes": self.graph.number_of_nodes(),
            "num_edges": self.graph.number_of_edges(),
            "density": nx.density(self.graph),
            "avg_degree": sum(dict(self.graph.degree()).values()) / self.graph.number_of_nodes() if self.graph.number_of_nodes() > 0 else 0,
        }

        # Add clustering coefficient
        stats["avg_clustering"] = nx.average_clustering(self.graph, weight="weight")

        # Connected components
        stats["num_components"] = nx.number_connected_components(self.graph)

        if nx.is_connected(self.graph):
            stats["diameter"] = nx.diameter(self.graph)
            stats["avg_path_length"] = nx.average_shortest_path_length(self.graph)

        return stats

    def find_artist_neighborhood(
        self,
        artist_name: str,
        depth: int = 2,
    ) -> nx.Graph:
        """Extract ego network (neighborhood) for a specific artist.

        Args:
            artist_name: Artist to center the network on
            depth: Depth of neighborhood to include

        Returns:
            Subgraph containing the artist and their neighborhood
        """
        if self.graph is None or artist_name not in self.graph:
            return nx.Graph()

        # Get ego network
        ego_graph = nx.ego_graph(self.graph, artist_name, radius=depth)

        logger.info(
            "🎯 Extracted artist neighborhood",
            artist=artist_name,
            depth=depth,
            nodes=ego_graph.number_of_nodes(),
            edges=ego_graph.number_of_edges(),
        )

        return ego_graph
