"""Community detection algorithms for artist networks.

This module implements various community detection algorithms to identify
clusters of artists who frequently collaborate or share similar attributes.
"""

from typing import Any

import networkx as nx
import structlog
from neo4j import AsyncDriver


logger = structlog.get_logger(__name__)


class CommunityDetector:
    """Community detection for artist collaboration networks."""

    def __init__(self, driver: AsyncDriver) -> None:
        """Initialize community detector.

        Args:
            driver: Neo4j async driver instance
        """
        self.driver = driver
        self.graph: nx.Graph | None = None
        self.communities: dict[str, int] = {}  # artist_name -> community_id

    async def build_collaboration_network(
        self,
        min_weight: int = 1,
        limit: int = 5000,
    ) -> nx.Graph:
        """Build collaboration network from Neo4j graph.

        Args:
            min_weight: Minimum collaboration weight to include
            limit: Maximum number of artists to include

        Returns:
            NetworkX graph
        """
        logger.info("🔨 Building collaboration network...")

        graph = nx.Graph()

        async with self.driver.session() as session:
            # Get artist collaborations
            result = await session.run(
                """
                MATCH (a1:Artist)-[r]-(a2:Artist)
                WHERE a1.name < a2.name
                WITH a1, a2, count(r) AS weight
                WHERE weight >= $min_weight
                RETURN a1.name AS artist1, a2.name AS artist2, weight
                ORDER BY weight DESC
                LIMIT $limit
                """,
                min_weight=min_weight,
                limit=limit,
            )

            edges_added = 0
            async for record in result:
                artist1 = record["artist1"]
                artist2 = record["artist2"]
                weight = record["weight"]

                graph.add_edge(artist1, artist2, weight=weight)
                edges_added += 1

        self.graph = graph

        logger.info(
            "✅ Built collaboration network",
            nodes=graph.number_of_nodes(),
            edges=graph.number_of_edges(),
        )

        return graph

    def detect_communities_louvain(self) -> dict[str, list[str]]:
        """Detect communities using Louvain method.

        Returns:
            Dictionary mapping community IDs to artist lists
        """
        if self.graph is None:
            raise ValueError("Graph not built. Call build_collaboration_network first.")

        logger.info("🔍 Detecting communities using Louvain method...")

        # Use Louvain community detection
        communities_dict = nx.community.louvain_communities(self.graph, weight="weight", resolution=1.0)

        # Convert to community ID mapping
        self.communities = {}
        community_members: dict[str, list[str]] = {}

        for community_id, community in enumerate(communities_dict):
            members = list(community)
            community_key = f"community_{community_id}"
            community_members[community_key] = members

            for artist in members:
                self.communities[artist] = community_id

        logger.info(
            "✅ Detected communities",
            num_communities=len(community_members),
            avg_size=sum(len(m) for m in community_members.values()) / len(community_members) if community_members else 0,
        )

        return community_members

    def detect_communities_label_propagation(self) -> dict[str, list[str]]:
        """Detect communities using label propagation.

        Returns:
            Dictionary mapping community IDs to artist lists
        """
        if self.graph is None:
            raise ValueError("Graph not built. Call build_collaboration_network first.")

        logger.info("🔍 Detecting communities using label propagation...")

        communities_gen = nx.community.label_propagation_communities(self.graph)
        communities_dict = list(communities_gen)

        # Convert to community ID mapping
        self.communities = {}
        community_members: dict[str, list[str]] = {}

        for community_id, community in enumerate(communities_dict):
            members = list(community)
            community_key = f"community_{community_id}"
            community_members[community_key] = members

            for artist in members:
                self.communities[artist] = community_id

        logger.info(
            "✅ Detected communities",
            num_communities=len(community_members),
            method="label_propagation",
        )

        return community_members

    def detect_communities_greedy_modularity(self) -> dict[str, list[str]]:
        """Detect communities using greedy modularity optimization.

        Returns:
            Dictionary mapping community IDs to artist lists
        """
        if self.graph is None:
            raise ValueError("Graph not built. Call build_collaboration_network first.")

        logger.info("🔍 Detecting communities using greedy modularity...")

        communities_gen = nx.community.greedy_modularity_communities(self.graph, weight="weight")
        communities_dict = list(communities_gen)

        # Convert to community ID mapping
        self.communities = {}
        community_members: dict[str, list[str]] = {}

        for community_id, community in enumerate(communities_dict):
            members = list(community)
            community_key = f"community_{community_id}"
            community_members[community_key] = members

            for artist in members:
                self.communities[artist] = community_id

        logger.info(
            "✅ Detected communities",
            num_communities=len(community_members),
            method="greedy_modularity",
        )

        return community_members

    def get_artist_community(self, artist_name: str) -> int | None:
        """Get community ID for an artist.

        Args:
            artist_name: Artist name

        Returns:
            Community ID or None
        """
        return self.communities.get(artist_name)

    def get_community_members(self, community_id: int) -> list[str]:
        """Get all artists in a community.

        Args:
            community_id: Community ID

        Returns:
            List of artist names
        """
        return [artist for artist, cid in self.communities.items() if cid == community_id]

    def get_community_stats(self) -> dict[str, Any]:
        """Get statistics about detected communities.

        Returns:
            Dictionary with community statistics
        """
        if not self.communities:
            return {}

        # Count members per community
        community_sizes: dict[int, int] = {}
        for community_id in self.communities.values():
            community_sizes[community_id] = community_sizes.get(community_id, 0) + 1

        return {
            "num_communities": len(community_sizes),
            "total_artists": len(self.communities),
            "min_size": min(community_sizes.values()) if community_sizes else 0,
            "max_size": max(community_sizes.values()) if community_sizes else 0,
            "avg_size": sum(community_sizes.values()) / len(community_sizes) if community_sizes else 0,
            "sizes": dict(sorted(community_sizes.items())),
        }

    def find_similar_communities(
        self,
        artist_name: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Find artists from the same community as the given artist.

        Args:
            artist_name: Artist name
            top_k: Number of similar artists to return

        Returns:
            List of similar artists with community info
        """
        if artist_name not in self.communities:
            return []

        community_id = self.communities[artist_name]
        community_members = [artist for artist, cid in self.communities.items() if cid == community_id and artist != artist_name]

        # If we have the graph, calculate centrality-based ranking
        if self.graph and artist_name in self.graph:
            # Calculate degree centrality for ranking
            centrality = nx.degree_centrality(self.graph)

            # Sort community members by centrality
            ranked_members = sorted(community_members, key=lambda x: centrality.get(x, 0), reverse=True)[:top_k]

            return [
                {
                    "artist_name": artist,
                    "community_id": community_id,
                    "centrality": centrality.get(artist, 0),
                }
                for artist in ranked_members
            ]

        # Fallback: just return first K members
        return [{"artist_name": artist, "community_id": community_id} for artist in community_members[:top_k]]

    def calculate_modularity(self) -> float:
        """Calculate modularity score for current community detection.

        Returns:
            Modularity score (higher is better)
        """
        if self.graph is None or not self.communities:
            return 0.0

        # Convert communities dict to list of sets
        community_sets: dict[int, set[str]] = {}
        for artist, community_id in self.communities.items():
            if community_id not in community_sets:
                community_sets[community_id] = set()
            community_sets[community_id].add(artist)

        communities_list = list(community_sets.values())

        modularity = nx.community.modularity(self.graph, communities_list, weight="weight")

        logger.info("📊 Calculated modularity", modularity=f"{modularity:.4f}")

        return float(modularity)

    async def build_genre_based_network(
        self,
        min_shared_genres: int = 2,
        limit: int = 5000,
    ) -> nx.Graph:
        """Build artist network based on shared genres.

        Args:
            min_shared_genres: Minimum number of shared genres
            limit: Maximum number of artists

        Returns:
            NetworkX graph
        """
        logger.info("🔨 Building genre-based network...")

        graph = nx.Graph()

        async with self.driver.session() as session:
            # Get artists with shared genres
            result = await session.run(
                """
                MATCH (a1:Artist)<-[:BY]-(r1:Release)-[:IS]->(g:Genre)<-[:IS]-(r2:Release)-[:BY]->(a2:Artist)
                WHERE a1.name < a2.name
                WITH a1, a2, collect(DISTINCT g.name) AS shared_genres
                WHERE size(shared_genres) >= $min_shared
                RETURN a1.name AS artist1, a2.name AS artist2,
                       shared_genres, size(shared_genres) AS weight
                ORDER BY weight DESC
                LIMIT $limit
                """,
                min_shared=min_shared_genres,
                limit=limit,
            )

            async for record in result:
                artist1 = record["artist1"]
                artist2 = record["artist2"]
                weight = record["weight"]
                shared_genres = record["shared_genres"]

                graph.add_edge(
                    artist1,
                    artist2,
                    weight=weight,
                    shared_genres=shared_genres,
                )

        self.graph = graph

        logger.info(
            "✅ Built genre-based network",
            nodes=graph.number_of_nodes(),
            edges=graph.number_of_edges(),
        )

        return graph

    def export_communities_to_dict(self) -> dict[str, Any]:
        """Export community detection results to dictionary.

        Returns:
            Dictionary with community information
        """
        if not self.communities:
            return {}

        # Group artists by community
        communities_dict: dict[int, list[str]] = {}
        for artist, community_id in self.communities.items():
            if community_id not in communities_dict:
                communities_dict[community_id] = []
            communities_dict[community_id].append(artist)

        return {
            "communities": {f"community_{cid}": {"id": cid, "members": members, "size": len(members)} for cid, members in communities_dict.items()},
            "stats": self.get_community_stats(),
            "modularity": self.calculate_modularity() if self.graph else 0.0,
        }
