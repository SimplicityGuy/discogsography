"""Influence and centrality metrics for artist networks.

This module calculates various centrality metrics to identify influential
artists in the collaboration network and music industry.
"""

import time
from typing import Any

from neo4j import AsyncDriver
import networkx as nx
import structlog


logger = structlog.get_logger(__name__)


class CentralityAnalyzer:
    """Calculate centrality and influence metrics for artists."""

    # Cache TTL in seconds (30 minutes)
    NETWORK_CACHE_TTL = 30 * 60

    def __init__(self, driver: AsyncDriver) -> None:
        """Initialize centrality analyzer.

        Args:
            driver: Neo4j async driver instance
        """
        self.driver = driver
        self.graph: nx.Graph | None = None
        self.metrics: dict[str, dict[str, float]] = {}
        self._cache_built_at: float = 0.0
        self._cache_limit: int = 0

    async def build_network(self, limit: int = 5000) -> nx.Graph:
        """Build artist collaboration network, using cache if available.

        Returns the cached graph if the same limit was used and the cache
        hasn't expired (TTL: 30 minutes).

        Args:
            limit: Maximum number of edges to include

        Returns:
            NetworkX graph
        """
        now = time.monotonic()
        if self.graph is not None and self._cache_limit == limit and (now - self._cache_built_at) < self.NETWORK_CACHE_TTL:
            logger.info(
                "⚡ Using cached network",
                age_seconds=round(now - self._cache_built_at),
                nodes=self.graph.number_of_nodes(),
                edges=self.graph.number_of_edges(),
            )
            return self.graph

        logger.info("🔨 Building network for centrality analysis...")

        graph = nx.Graph()

        async with self.driver.session() as session:
            # Get collaboration edges
            result = await session.run(
                """
                MATCH (a1:Artist)-[r]-(a2:Artist)
                WHERE a1.name < a2.name
                WITH a1, a2, count(r) AS weight
                RETURN a1.name AS artist1, a2.name AS artist2, weight
                ORDER BY weight DESC
                LIMIT $limit
                """,
                limit=limit,
            )

            async for record in result:
                graph.add_edge(
                    record["artist1"],
                    record["artist2"],
                    weight=record["weight"],
                )

        self.graph = graph
        self._cache_built_at = time.monotonic()
        self._cache_limit = limit
        # Clear stale metrics when graph is rebuilt
        self.metrics.clear()

        logger.info(
            "✅ Built network",
            nodes=graph.number_of_nodes(),
            edges=graph.number_of_edges(),
        )

        return graph

    def calculate_degree_centrality(self) -> dict[str, float]:
        """Calculate degree centrality for all artists.

        Degree centrality measures the number of connections an artist has.

        Returns:
            Dictionary mapping artist names to degree centrality scores
        """
        if self.graph is None:
            raise ValueError("Graph not built. Call build_network first.")

        logger.info("📊 Calculating degree centrality...")

        centrality = nx.degree_centrality(self.graph)

        # Store in metrics
        for artist, score in centrality.items():
            if artist not in self.metrics:
                self.metrics[artist] = {}
            self.metrics[artist]["degree_centrality"] = score

        logger.info("✅ Calculated degree centrality", artists=len(centrality))

        return dict(centrality)

    def calculate_betweenness_centrality(self, k: int | None = None) -> dict[str, float]:
        """Calculate betweenness centrality for all artists.

        Betweenness centrality measures how often an artist appears on
        shortest paths between other artists (bridge between communities).

        Args:
            k: If set, use k-sample approximation for large graphs

        Returns:
            Dictionary mapping artist names to betweenness centrality scores
        """
        if self.graph is None:
            raise ValueError("Graph not built. Call build_network first.")

        logger.info("📊 Calculating betweenness centrality...")

        centrality = nx.betweenness_centrality(self.graph, k=k, weight="weight") if k else nx.betweenness_centrality(self.graph, weight="weight")

        # Store in metrics
        for artist, score in centrality.items():
            if artist not in self.metrics:
                self.metrics[artist] = {}
            self.metrics[artist]["betweenness_centrality"] = score

        logger.info("✅ Calculated betweenness centrality", artists=len(centrality))

        return dict(centrality)

    def calculate_closeness_centrality(self) -> dict[str, float]:
        """Calculate closeness centrality for all artists.

        Closeness centrality measures how quickly an artist can reach
        other artists in the network (influence propagation speed).

        Returns:
            Dictionary mapping artist names to closeness centrality scores
        """
        if self.graph is None:
            raise ValueError("Graph not built. Call build_network first.")

        logger.info("📊 Calculating closeness centrality...")

        # Only calculate for connected components
        if nx.is_connected(self.graph):
            centrality = nx.closeness_centrality(self.graph, distance="weight")
        else:
            # Calculate for largest connected component
            largest_cc = max(nx.connected_components(self.graph), key=len)
            subgraph = self.graph.subgraph(largest_cc)
            centrality = nx.closeness_centrality(subgraph, distance="weight")

        # Store in metrics
        for artist, score in centrality.items():
            if artist not in self.metrics:
                self.metrics[artist] = {}
            self.metrics[artist]["closeness_centrality"] = score

        logger.info("✅ Calculated closeness centrality", artists=len(centrality))

        return dict(centrality)

    def calculate_eigenvector_centrality(self, max_iter: int = 100) -> dict[str, float]:
        """Calculate eigenvector centrality for all artists.

        Eigenvector centrality measures influence based on being connected
        to other influential artists (quality of connections).

        Args:
            max_iter: Maximum number of iterations

        Returns:
            Dictionary mapping artist names to eigenvector centrality scores
        """
        if self.graph is None:
            raise ValueError("Graph not built. Call build_network first.")

        logger.info("📊 Calculating eigenvector centrality...")

        try:
            centrality = nx.eigenvector_centrality(
                self.graph,
                max_iter=max_iter,
                weight="weight",
            )

            # Store in metrics
            for artist, score in centrality.items():
                if artist not in self.metrics:
                    self.metrics[artist] = {}
                self.metrics[artist]["eigenvector_centrality"] = score

            logger.info("✅ Calculated eigenvector centrality", artists=len(centrality))

            return dict(centrality)

        except nx.PowerIterationFailedConvergence:
            logger.warning("⚠️ Eigenvector centrality did not converge")
            return {}

    def calculate_pagerank(self, alpha: float = 0.85) -> dict[str, float]:
        """Calculate PageRank for all artists.

        PageRank measures importance based on the network structure,
        considering both direct and indirect connections.

        Args:
            alpha: Damping parameter (0.85 is standard)

        Returns:
            Dictionary mapping artist names to PageRank scores
        """
        if self.graph is None:
            raise ValueError("Graph not built. Call build_network first.")

        logger.info("📊 Calculating PageRank...")

        pagerank = nx.pagerank(self.graph, alpha=alpha, weight="weight")

        # Store in metrics
        for artist, score in pagerank.items():
            if artist not in self.metrics:
                self.metrics[artist] = {}
            self.metrics[artist]["pagerank"] = score

        logger.info("✅ Calculated PageRank", artists=len(pagerank))

        return dict(pagerank)

    def calculate_all_metrics(
        self,
        include_expensive: bool = False,
    ) -> dict[str, dict[str, float]]:
        """Calculate all centrality metrics.

        Args:
            include_expensive: Whether to include computationally expensive metrics

        Returns:
            Dictionary mapping artist names to their metrics
        """
        logger.info("📊 Calculating all centrality metrics...")

        # Fast metrics
        self.calculate_degree_centrality()
        self.calculate_pagerank()

        if include_expensive:
            # More expensive metrics
            self.calculate_betweenness_centrality(k=100)  # Use approximation
            self.calculate_closeness_centrality()
            self.calculate_eigenvector_centrality()

        logger.info(
            "✅ Calculated all metrics",
            artists=len(self.metrics),
            metrics=len(self.metrics[next(iter(self.metrics.keys()))]) if self.metrics else 0,
        )

        return self.metrics

    def get_top_influential_artists(
        self,
        metric: str = "pagerank",
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """Get top influential artists by a specific metric.

        Args:
            metric: Metric to rank by
            top_k: Number of top artists to return

        Returns:
            List of top artists with scores
        """
        if not self.metrics:
            return []

        # Filter artists that have the metric
        artists_with_metric = [(artist, scores.get(metric, 0)) for artist, scores in self.metrics.items() if metric in scores]

        # Sort by metric score
        artists_with_metric.sort(key=lambda x: x[1], reverse=True)

        # Return top K
        return [
            {
                "artist_name": artist,
                "score": score,
                "metric": metric,
                "rank": i + 1,
            }
            for i, (artist, score) in enumerate(artists_with_metric[:top_k])
        ]

    def get_artist_influence_profile(self, artist_name: str) -> dict[str, Any]:
        """Get complete influence profile for an artist.

        Args:
            artist_name: Artist name

        Returns:
            Dictionary with all influence metrics and rankings
        """
        if artist_name not in self.metrics:
            return {"artist_name": artist_name, "error": "Artist not found in network"}

        metrics = self.metrics[artist_name]

        # Calculate rankings for each metric
        rankings = {}
        for metric_name in metrics:
            all_scores = sorted(
                [(a, m.get(metric_name, 0)) for a, m in self.metrics.items()],
                key=lambda x: x[1],
                reverse=True,
            )

            rank = next((i + 1 for i, (a, _) in enumerate(all_scores) if a == artist_name), None)

            rankings[f"{metric_name}_rank"] = rank

        return {
            "artist_name": artist_name,
            "metrics": metrics,
            "rankings": rankings,
            "total_artists": len(self.metrics),
        }

    def compare_artists(
        self,
        artist1: str,
        artist2: str,
    ) -> dict[str, Any]:
        """Compare influence metrics between two artists.

        Args:
            artist1: First artist name
            artist2: Second artist name

        Returns:
            Comparison results
        """
        if artist1 not in self.metrics or artist2 not in self.metrics:
            return {"error": "One or both artists not found"}

        metrics1 = self.metrics[artist1]
        metrics2 = self.metrics[artist2]

        comparison = {
            "artist1": {
                "name": artist1,
                "metrics": metrics1,
            },
            "artist2": {
                "name": artist2,
                "metrics": metrics2,
            },
            "differences": {},
        }

        # Calculate differences
        for metric in metrics1:
            if metric in metrics2:
                diff = metrics1[metric] - metrics2[metric]
                comparison["differences"][metric] = {
                    "difference": diff,
                    "higher": artist1 if diff > 0 else artist2,
                }

        return comparison

    def get_network_statistics(self) -> dict[str, Any]:
        """Get overall network statistics.

        Returns:
            Dictionary with network statistics
        """
        if self.graph is None:
            return {}

        stats = {
            "num_nodes": self.graph.number_of_nodes(),
            "num_edges": self.graph.number_of_edges(),
            "density": nx.density(self.graph),
            "num_connected_components": nx.number_connected_components(self.graph),
        }

        # Add diameter and average path length for largest component
        if nx.is_connected(self.graph):
            stats["diameter"] = nx.diameter(self.graph)
            stats["avg_shortest_path_length"] = nx.average_shortest_path_length(self.graph)
        else:
            largest_cc = max(nx.connected_components(self.graph), key=len)
            subgraph = self.graph.subgraph(largest_cc)
            stats["largest_component_size"] = len(largest_cc)
            stats["largest_component_diameter"] = nx.diameter(subgraph)
            stats["largest_component_avg_path_length"] = nx.average_shortest_path_length(subgraph)

        # Clustering coefficient
        stats["avg_clustering_coefficient"] = nx.average_clustering(self.graph, weight="weight")

        logger.info("📊 Network statistics", **stats)

        return stats

    def export_metrics_to_dict(self) -> dict[str, Any]:
        """Export all metrics to dictionary for serialization.

        Returns:
            Dictionary with all metrics and statistics
        """
        return {
            "metrics": self.metrics,
            "network_stats": self.get_network_statistics(),
            "total_artists": len(self.metrics),
        }
