"""Collaborative filtering recommendation algorithms for music discovery.

This module implements item-item collaborative filtering based on co-occurrence
patterns in the music graph (collaborations, shared labels, shared genres).
"""

import asyncio
from collections import defaultdict
import os
from typing import Any

from neo4j import AsyncDriver
import numpy as np
from scipy.sparse import csr_matrix, lil_matrix
from sklearn.metrics.pairwise import cosine_similarity
import structlog


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

        # Inverted indices for efficient lookups (feature -> list of artist indices)
        self.label_to_artists: dict[str, set[int]] = defaultdict(set)
        self.genre_to_artists: dict[str, set[int]] = defaultdict(set)
        self.style_to_artists: dict[str, set[int]] = defaultdict(set)
        self.collaborator_to_artists: dict[str, set[int]] = defaultdict(set)

    def reset(self) -> None:
        """Reset all state so the co-occurrence matrix can be rebuilt cleanly."""
        self.item_similarity_matrix = None
        self.artist_to_index.clear()
        self.index_to_artist.clear()
        self.co_occurrence_matrix = None
        self.artist_features.clear()
        self.label_to_artists.clear()
        self.genre_to_artists.clear()
        self.style_to_artists.clear()
        self.collaborator_to_artists.clear()
        logger.info("🔄 Collaborative filter state reset")

    async def build_cooccurrence_matrix(self) -> None:
        """Build co-occurrence matrix from graph relationships.

        Co-occurrence is based on:
        - Artists appearing on same label
        - Artists sharing genres/styles
        - Artists collaborating (via relationship edges)

        Uses inverted indices for O(n*k) complexity instead of O(n^2).
        """
        logger.info("🔨 Building co-occurrence matrix for collaborative filtering...")

        # Configuration for batch processing
        BATCH_SIZE = 2000  # Process 2000 artists at a time to avoid memory issues
        MAX_ARTISTS = int(os.getenv("COLLAB_FILTER_MAX_ARTISTS", "50000"))  # Configurable limit

        artists_data = []

        async with self.driver.session() as session:
            # First, get total artist count
            count_result = await session.run("MATCH (a:Artist) RETURN count(a) AS total")
            total_artists = await count_result.single()
            total_count = total_artists["total"] if total_artists else 0

            # Limit to MAX_ARTISTS for memory efficiency
            artists_to_process = min(total_count, MAX_ARTISTS)

            logger.info(
                "📊 Processing artists in batches",
                total_artists=total_count,
                processing=artists_to_process,
                batch_size=BATCH_SIZE,
                max_configurable=MAX_ARTISTS,
            )

            # Fetch artists in batches
            for offset in range(0, artists_to_process, BATCH_SIZE):
                batch_num = (offset // BATCH_SIZE) + 1
                total_batches = (artists_to_process + BATCH_SIZE - 1) // BATCH_SIZE

                logger.info(
                    f"🔄 Processing batch {batch_num}/{total_batches}",
                    offset=offset,
                    batch_size=BATCH_SIZE,
                )

                result = await session.run(
                    """
                    MATCH (a:Artist)
                    OPTIONAL MATCH (a)<-[:BY]-(r:Release)-[:ON]->(label:Label)
                    WITH a, collect(DISTINCT label.name) AS labels
                    OPTIONAL MATCH (a)<-[:BY]-(r:Release)-[:IS]->(genre:Genre)
                    WITH a, labels, collect(DISTINCT genre.name) AS genres
                    OPTIONAL MATCH (a)<-[:BY]-(r:Release)-[:IS]->(style:Style)
                    WITH a, labels, genres, collect(DISTINCT style.name) AS styles
                    OPTIONAL MATCH (a)<-[:BY]-(rel:Release)-[:BY]->(other:Artist)
                    WHERE a.name <> other.name
                    WITH a, labels, genres, styles, collect(DISTINCT other.name) AS collaborators
                    RETURN a.id AS artist_id, a.name AS artist_name,
                           labels, genres, styles, collaborators
                    SKIP $offset
                    LIMIT $batch_size
                    """,
                    offset=offset,
                    batch_size=BATCH_SIZE,
                )

                batch_data = []
                async for record in result:
                    batch_data.append(
                        {
                            "id": record["artist_id"],
                            "name": record["artist_name"],
                            "labels": record["labels"] or [],
                            "genres": record["genres"] or [],
                            "styles": record["styles"] or [],
                            "collaborators": record["collaborators"] or [],
                        }
                    )

                artists_data.extend(batch_data)
                logger.info(f"✅ Batch {batch_num}/{total_batches} complete", batch_size=len(batch_data))

        if not artists_data:
            logger.warning("⚠️ No artist data found for collaborative filtering")
            return

        # Offload CPU-bound matrix computation to a thread so the event loop
        # stays free for health checks and API requests.
        await asyncio.to_thread(self._build_matrix_sync, artists_data)

    def _build_matrix_sync(self, artists_data: list[dict[str, Any]]) -> None:
        """Build the co-occurrence and similarity matrices (CPU-bound).

        This runs in a thread pool via asyncio.to_thread() so it doesn't
        block the event loop.

        Args:
            artists_data: List of artist dicts with labels, genres, styles, collaborators.
        """
        # Debug: Analyze feature distribution
        label_counts = sum(1 for a in artists_data if a["labels"])
        genre_counts = sum(1 for a in artists_data if a["genres"])
        style_counts = sum(1 for a in artists_data if a["styles"])
        collab_counts = sum(1 for a in artists_data if a["collaborators"])

        logger.info(
            "🔍 Feature distribution",
            total_artists=len(artists_data),
            artists_with_labels=label_counts,
            artists_with_genres=genre_counts,
            artists_with_styles=style_counts,
            artists_with_collaborators=collab_counts,
        )

        # Sample first artist for debugging
        if artists_data:
            sample = artists_data[0]
            logger.info(
                "🔍 Sample artist features",
                name=sample["name"],
                num_labels=len(sample["labels"]),
                num_genres=len(sample["genres"]),
                num_styles=len(sample["styles"]),
                num_collaborators=len(sample["collaborators"]),
            )

        # Create artist index mappings and build inverted indices
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

            # Build inverted indices
            for label in artist["labels"]:
                self.label_to_artists[label].add(i)
            for genre in artist["genres"]:
                self.genre_to_artists[genre].add(i)
            for style in artist["styles"]:
                self.style_to_artists[style].add(i)
            for collaborator in artist["collaborators"]:
                self.collaborator_to_artists[collaborator].add(i)

        logger.info(
            "🔍 Inverted index sizes",
            unique_labels=len(self.label_to_artists),
            unique_genres=len(self.genre_to_artists),
            unique_styles=len(self.style_to_artists),
            unique_collaborators=len(self.collaborator_to_artists),
        )

        n_artists = len(artists_data)
        self.co_occurrence_matrix = lil_matrix((n_artists, n_artists), dtype=np.float32)

        # Build co-occurrence matrix using inverted indices (O(n*k) instead of O(n^2))
        logger.info("🔨 Building co-occurrence matrix with inverted indices...")
        total_comparisons = 0
        total_edges = 0

        for i, artist in enumerate(artists_data):
            # Find all artists that share at least one feature with this artist
            potential_similar_artists: set[int] = set()

            # Add artists sharing labels
            for label in artist["labels"]:
                potential_similar_artists.update(self.label_to_artists[label])

            # Add artists sharing genres
            for genre in artist["genres"]:
                potential_similar_artists.update(self.genre_to_artists[genre])

            # Add artists sharing styles
            for style in artist["styles"]:
                potential_similar_artists.update(self.style_to_artists[style])

            # Add collaborators
            for collaborator in artist["collaborators"]:
                potential_similar_artists.update(self.collaborator_to_artists.get(collaborator, set()))

            # Remove self
            potential_similar_artists.discard(i)

            total_comparisons += len(potential_similar_artists)

            # Calculate similarity scores only with potential matches
            for j in potential_similar_artists:
                other_artist = artists_data[j]
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
                    total_edges += 1

            # Yield to event loop periodically to avoid starving other tasks
            if (i + 1) % 100 == 0:
                await asyncio.sleep(0)  # type: ignore[await-not-async]

            # Log progress every 1000 artists
            if (i + 1) % 1000 == 0:
                logger.info(
                    f"🔄 Processing artists {i + 1}/{n_artists}",
                    edges_so_far=total_edges,
                )

        logger.info(
            "🔍 Comparison statistics",
            total_comparisons=total_comparisons,
            avg_comparisons_per_artist=total_comparisons / n_artists if n_artists > 0 else 0,
            theoretical_worst_case=n_artists * (n_artists - 1),
            efficiency_gain=f"{100 * (1 - total_comparisons / (n_artists * (n_artists - 1)) if n_artists > 1 else 0):.2f}%",
        )

        # Convert to CSR for efficient operations
        self.co_occurrence_matrix = self.co_occurrence_matrix.tocsr()

        # Safety cap: skip dense cosine_similarity when the matrix is too large,
        # as it can OOM or hang. On-demand recommendations still work without it.
        MAX_NNZ = int(os.getenv("COLLAB_FILTER_MAX_NNZ", "10000000"))  # 10M default
        if self.co_occurrence_matrix.nnz > MAX_NNZ:
            logger.warning(
                "⚠️ Co-occurrence matrix too large for cosine similarity, skipping pre-built similarity matrix (on-demand recs still work)",
                nnz=self.co_occurrence_matrix.nnz,
                max_nnz=MAX_NNZ,
            )
        else:
            # Calculate item-item similarity using cosine similarity
            self.item_similarity_matrix = cosine_similarity(self.co_occurrence_matrix, dense_output=False)

        logger.info(
            "✅ Built co-occurrence matrix",
            artists=n_artists,
            nnz=self.co_occurrence_matrix.nnz,
            density=f"{100 * self.co_occurrence_matrix.nnz / (n_artists * n_artists) if n_artists > 0 else 0:.4f}%",
            similarity_matrix_built=self.item_similarity_matrix is not None,
        )

    async def get_recommendations(self, artist_name: str, limit: int = 10) -> list[dict[str, Any]]:
        """Get collaborative filtering recommendations for an artist.

        If the artist is in the pre-built matrix, use that. Otherwise, compute
        recommendations on-demand by fetching the artist's data from the graph.

        Args:
            artist_name: Name of the artist to get recommendations for
            limit: Maximum number of recommendations to return

        Returns:
            List of recommended artists with similarity scores
        """
        # Lazy initialization: if matrix was never built (e.g. Neo4j was empty at startup), try now
        if self.item_similarity_matrix is None and not self.artist_to_index:
            logger.info("🔄 Lazy init: building co-occurrence matrix on first recommendation request")
            try:
                await self.build_cooccurrence_matrix()
            except Exception as e:
                logger.warning(f"⚠️ Lazy init failed: {e}")

        # If artist is in pre-built matrix, use it
        if self.item_similarity_matrix is not None and artist_name in self.artist_to_index:
            artist_idx = self.artist_to_index[artist_name]

            # Get similarity scores for this artist
            similarity_scores = self.item_similarity_matrix[artist_idx].toarray().flatten()

            # Get top N similar artists (excluding self)
            similar_indices = np.argsort(similarity_scores)[::-1][1 : limit + 1]

            recommendations = []
            for idx in similar_indices:
                if similarity_scores[idx] > 0:  # Only include artists with positive similarity
                    recommendations.append(
                        {
                            "artist_name": self.index_to_artist[idx],
                            "similarity_score": float(similarity_scores[idx]),
                            "method": "collaborative_filtering",
                        }
                    )

            return recommendations

        # Artist not in pre-built matrix - compute on-demand
        logger.info("🔍 Computing on-demand recommendations for artist not in matrix", artist_name=artist_name)
        return await self._compute_on_demand_recommendations(artist_name, limit)

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

    async def _compute_on_demand_recommendations(self, artist_name: str, limit: int = 10) -> list[dict[str, Any]]:
        """Compute recommendations for an artist not in the pre-built matrix.

        Fetches the artist's data from the graph and computes similarities using
        the existing inverted indices and pre-built artist features.

        Args:
            artist_name: Name of the artist to get recommendations for
            limit: Maximum number of recommendations to return

        Returns:
            List of recommended artists with similarity scores
        """
        # Fetch artist data from the graph
        async with self.driver.session() as session:
            result = await session.run(
                """
                MATCH (a:Artist {name: $artist_name})
                OPTIONAL MATCH (a)<-[:BY]-(r:Release)-[:ON]->(label:Label)
                WITH a, collect(DISTINCT label.name) AS labels
                OPTIONAL MATCH (a)<-[:BY]-(r:Release)-[:IS]->(genre:Genre)
                WITH a, labels, collect(DISTINCT genre.name) AS genres
                OPTIONAL MATCH (a)<-[:BY]-(r:Release)-[:IS]->(style:Style)
                WITH a, labels, genres, collect(DISTINCT style.name) AS styles
                OPTIONAL MATCH (a)<-[:BY]-(rel:Release)-[:BY]->(other:Artist)
                WHERE a.name <> other.name
                WITH a, labels, genres, styles, collect(DISTINCT other.name) AS collaborators
                RETURN a.id AS artist_id, a.name AS artist_name,
                       labels, genres, styles, collaborators
                """,
                artist_name=artist_name,
            )

            record = await result.single()

            if not record:
                logger.warning("⚠️ Artist not found in graph", artist_name=artist_name)
                return []

            query_artist = {
                "id": record["artist_id"],
                "name": record["artist_name"],
                "labels": record["labels"] or [],
                "genres": record["genres"] or [],
                "styles": record["styles"] or [],
                "collaborators": record["collaborators"] or [],
            }

        # Find all artists that share features with this artist using inverted indices
        potential_similar_artists: set[int] = set()

        for label in query_artist["labels"]:
            potential_similar_artists.update(self.label_to_artists.get(label, set()))
        for genre in query_artist["genres"]:
            potential_similar_artists.update(self.genre_to_artists.get(genre, set()))
        for style in query_artist["styles"]:
            potential_similar_artists.update(self.style_to_artists.get(style, set()))
        for collaborator in query_artist["collaborators"]:
            potential_similar_artists.update(self.collaborator_to_artists.get(collaborator, set()))

        # Compute similarity scores
        similarity_scores: list[tuple[int, float]] = []

        for idx in potential_similar_artists:
            candidate_artist_name = self.index_to_artist[idx]
            candidate_features = self.artist_features[candidate_artist_name]

            score = 0.0

            # Collaboration weight
            if query_artist["name"] in candidate_features["collaborators"] or candidate_artist_name in query_artist["collaborators"]:
                score += 5.0

            # Shared label weight
            shared_labels = set(query_artist["labels"]) & set(candidate_features["labels"])
            if shared_labels:
                score += 2.0 * len(shared_labels)

            # Shared genre weight
            shared_genres = set(query_artist["genres"]) & set(candidate_features["genres"])
            if shared_genres:
                score += 1.5 * len(shared_genres)

            # Shared style weight
            shared_styles = set(query_artist["styles"]) & set(candidate_features["styles"])
            if shared_styles:
                score += 1.0 * len(shared_styles)

            if score > 0:
                similarity_scores.append((idx, score))

        # Sort by score and take top N
        similarity_scores.sort(key=lambda x: x[1], reverse=True)
        top_recommendations = similarity_scores[:limit]

        # Normalize scores using cosine similarity-like normalization
        # (divide by magnitude to get scores in [0, 1] range)
        max_score = max((score for _, score in top_recommendations), default=1.0)

        recommendations = []
        for idx, score in top_recommendations:
            recommendations.append(
                {
                    "artist_name": self.index_to_artist[idx],
                    "similarity_score": float(score / max_score),  # Normalize to [0, 1]
                    "method": "collaborative_filtering_on_demand",
                }
            )

        logger.info(
            "✅ Computed on-demand recommendations",
            artist_name=artist_name,
            candidates_evaluated=len(potential_similar_artists),
            recommendations_found=len(recommendations),
        )

        return recommendations

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
