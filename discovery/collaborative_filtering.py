"""Collaborative filtering recommendation algorithms for music discovery.

This module implements item-item collaborative filtering based on co-occurrence
patterns in the music graph (collaborations, shared labels, shared genres).
"""

from typing import Any

import numpy as np
import structlog
from neo4j import AsyncDriver
from scipy.sparse import csr_matrix, lil_matrix
from sklearn.metrics.pairwise import cosine_similarity


logger = structlog.get_logger(__name__)


class CollaborativeFilter:
    """Item-item collaborative filtering for music recommendations."""

    def __init__(self, driver: AsyncDriver) -> None:
        """Initialize collaborative filter.

        Args:
            driver: Neo4j async driver instance
        """
        self.driver = driver
        self.item_similarity_matrix: csr_matrix | None = None
        self.artist_to_index: dict[str, int] = {}
        self.index_to_artist: dict[int, str] = {}
        self.co_occurrence_matrix: lil_matrix | None = None
        self.artist_features: dict[str, dict[str, list[str]]] = {}

    async def build_cooccurrence_matrix(self) -> None:
        """Build co-occurrence matrix from graph relationships.

        Co-occurrence is based on:
        - Artists appearing on same label
        - Artists sharing genres/styles
        - Artists collaborating (via relationship edges)
        - Artists appearing in similar time periods
        """
        logger.info("🔨 Building co-occurrence matrix for collaborative filtering...")

        # Fetch all artists and their relationships
        async with self.driver.session() as session:
            # Get all artists with their properties
            result = await session.run(
                """
                MATCH (a:Artist)
                OPTIONAL MATCH (a)-[:ON]->(label:Label)
                OPTIONAL MATCH (a)-[:IS]->(genre:Genre)
                OPTIONAL MATCH (a)-[:IS]->(style:Style)
                OPTIONAL MATCH (a)-[collab]->(other:Artist)
                RETURN a.id AS artist_id, a.name AS artist_name,
                       collect(DISTINCT label.name) AS labels,
                       collect(DISTINCT genre.name) AS genres,
                       collect(DISTINCT style.name) AS styles,
                       collect(DISTINCT other.name) AS collaborators
                LIMIT 10000
                """
            )

            artists_data = []
            async for record in result:
                artists_data.append(
                    {
                        "id": record["artist_id"],
                        "name": record["artist_name"],
                        "labels": record["labels"] or [],
                        "genres": record["genres"] or [],
                        "styles": record["styles"] or [],
                        "collaborators": record["collaborators"] or [],
                    }
                )

        if not artists_data:
            logger.warning("⚠️ No artist data found for collaborative filtering")
            return

        # Create artist index mappings and store features
        for i, artist in enumerate(artists_data):
            artist_name = artist["name"]
            self.artist_to_index[artist_name] = i
            self.index_to_artist[i] = artist_name
            # Store artist features for explainability
            self.artist_features[artist_name] = {
                "labels": artist["labels"],
                "genres": artist["genres"],
                "styles": artist["styles"],
                "collaborators": artist["collaborators"],
            }

        n_artists = len(artists_data)
        self.co_occurrence_matrix = lil_matrix((n_artists, n_artists), dtype=np.float32)

        # Build co-occurrence matrix
        for i, artist in enumerate(artists_data):
            for j, other_artist in enumerate(artists_data):
                if i == j:
                    continue

                score = 0.0

                # Collaboration weight (strongest signal)
                if artist["name"] in other_artist["collaborators"] or other_artist["name"] in artist["collaborators"]:
                    score += 5.0

                # Shared label weight
                shared_labels = set(artist["labels"]) & set(other_artist["labels"])
                if shared_labels:
                    score += 2.0 * len(shared_labels)

                # Shared genre weight
                shared_genres = set(artist["genres"]) & set(other_artist["genres"])
                if shared_genres:
                    score += 1.5 * len(shared_genres)

                # Shared style weight
                shared_styles = set(artist["styles"]) & set(other_artist["styles"])
                if shared_styles:
                    score += 1.0 * len(shared_styles)

                if score > 0:
                    self.co_occurrence_matrix[i, j] = score

        # Convert to CSR for efficient operations
        self.co_occurrence_matrix = self.co_occurrence_matrix.tocsr()

        # Calculate item-item similarity using cosine similarity
        self.item_similarity_matrix = cosine_similarity(self.co_occurrence_matrix, dense_output=False)

        logger.info("✅ Built co-occurrence matrix", artists=n_artists, nnz=self.co_occurrence_matrix.nnz)

    async def get_recommendations(self, artist_name: str, limit: int = 10) -> list[dict[str, Any]]:
        """Get collaborative filtering recommendations for an artist.

        Args:
            artist_name: Name of the artist to get recommendations for
            limit: Maximum number of recommendations to return

        Returns:
            List of recommended artists with similarity scores
        """
        if self.item_similarity_matrix is None or artist_name not in self.artist_to_index:
            return []

        artist_idx = self.artist_to_index[artist_name]

        # Get similarity scores for this artist
        similarity_scores = self.item_similarity_matrix[artist_idx].toarray().flatten()

        # Get top N similar artists (excluding self)
        similar_indices = np.argsort(similarity_scores)[::-1][1 : limit + 1]

        recommendations = []
        for idx in similar_indices:
            if similarity_scores[idx] > 0:  # Only include artists with positive similarity
                recommendations.append(
                    {"artist_name": self.index_to_artist[idx], "similarity_score": float(similarity_scores[idx]), "method": "collaborative_filtering"}
                )

        return recommendations

    async def get_batch_recommendations(self, artist_names: list[str], limit: int = 10) -> dict[str, list[dict[str, Any]]]:
        """Get recommendations for multiple artists in batch.

        Args:
            artist_names: List of artist names to get recommendations for
            limit: Maximum number of recommendations per artist

        Returns:
            Dictionary mapping artist names to their recommendations
        """
        results = {}
        for artist_name in artist_names:
            results[artist_name] = await self.get_recommendations(artist_name, limit)
        return results

    def get_similarity_score(self, artist1: str, artist2: str) -> float:
        """Get similarity score between two artists.

        Args:
            artist1: First artist name
            artist2: Second artist name

        Returns:
            Similarity score (0.0 to 1.0)
        """
        if self.item_similarity_matrix is None:
            return 0.0

        if artist1 not in self.artist_to_index or artist2 not in self.artist_to_index:
            return 0.0

        idx1 = self.artist_to_index[artist1]
        idx2 = self.artist_to_index[artist2]

        return float(self.item_similarity_matrix[idx1, idx2])

    async def get_similar_artists_for_multiple(self, artist_names: list[str], limit: int = 10) -> list[dict[str, Any]]:
        """Get recommendations based on multiple input artists (playlist-based recommendations).

        Args:
            artist_names: List of artist names to base recommendations on
            limit: Maximum number of recommendations to return

        Returns:
            List of recommended artists based on the combined preferences
        """
        if self.item_similarity_matrix is None:
            return []

        # Get valid artist indices
        valid_indices = [self.artist_to_index[name] for name in artist_names if name in self.artist_to_index]

        if not valid_indices:
            return []

        # Aggregate similarity scores across all input artists
        aggregated_scores = np.zeros(len(self.index_to_artist))

        for idx in valid_indices:
            similarity_scores = self.item_similarity_matrix[idx].toarray().flatten()
            aggregated_scores += similarity_scores

        # Normalize by number of input artists
        aggregated_scores /= len(valid_indices)

        # Remove input artists from recommendations
        for idx in valid_indices:
            aggregated_scores[idx] = 0

        # Get top N recommendations
        top_indices = np.argsort(aggregated_scores)[::-1][:limit]

        recommendations = []
        for idx in top_indices:
            if aggregated_scores[idx] > 0:
                recommendations.append(
                    {
                        "artist_name": self.index_to_artist[idx],
                        "similarity_score": float(aggregated_scores[idx]),
                        "method": "collaborative_filtering_multi",
                    }
                )

        return recommendations
