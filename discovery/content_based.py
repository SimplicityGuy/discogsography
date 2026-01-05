"""Content-based recommendation algorithms for music discovery.

This module implements content-based filtering using artist attributes
(genres, styles, labels, collaborators) to compute similarity and generate
recommendations.
"""

from typing import Any

import numpy as np
import structlog
from neo4j import AsyncDriver
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


logger = structlog.get_logger(__name__)


class ContentBasedFilter:
    """Content-based filtering for music recommendations using artist attributes."""

    def __init__(self, driver: AsyncDriver) -> None:
        """Initialize content-based filter.

        Args:
            driver: Neo4j async driver instance
        """
        self.driver = driver
        self.artist_features: dict[str, dict[str, Any]] = {}
        self.artist_to_index: dict[str, int] = {}
        self.index_to_artist: dict[int, str] = {}
        self.tfidf_vectorizer: TfidfVectorizer | None = None
        self.tfidf_matrix: np.ndarray | None = None
        self.feature_weights = {
            "genres": 0.3,
            "styles": 0.25,
            "labels": 0.2,
            "collaborators": 0.15,
            "time_period": 0.1,
        }

    async def build_feature_vectors(self) -> None:
        """Build feature vectors from artist attributes.

        Extracts artist features from Neo4j and creates TF-IDF vectors
        for similarity computation.
        """
        logger.info("🔨 Building feature vectors for content-based filtering...")

        async with self.driver.session() as session:
            # Get all artists with their attributes
            result = await session.run(
                """
                MATCH (a:Artist)
                OPTIONAL MATCH (a)-[:ON]->(label:Label)
                OPTIONAL MATCH (a)-[:IS]->(genre:Genre)
                OPTIONAL MATCH (a)-[:IS]->(style:Style)
                OPTIONAL MATCH (a)-[collab]->(other:Artist)
                OPTIONAL MATCH (a)-[:RELEASED]->(r:Release)
                RETURN a.id AS artist_id, a.name AS artist_name,
                       collect(DISTINCT label.name) AS labels,
                       collect(DISTINCT genre.name) AS genres,
                       collect(DISTINCT style.name) AS styles,
                       collect(DISTINCT other.name) AS collaborators,
                       min(r.year) AS earliest_year,
                       max(r.year) AS latest_year
                LIMIT 10000
                """
            )

            artists_data = []
            async for record in result:
                artist_data = {
                    "id": record["artist_id"],
                    "name": record["artist_name"],
                    "labels": record["labels"] or [],
                    "genres": record["genres"] or [],
                    "styles": record["styles"] or [],
                    "collaborators": record["collaborators"] or [],
                    "earliest_year": record["earliest_year"],
                    "latest_year": record["latest_year"],
                }
                artists_data.append(artist_data)
                self.artist_features[artist_data["name"]] = artist_data

        if not artists_data:
            logger.warning("⚠️ No artist data found for content-based filtering")
            return

        # Create artist index mappings
        for i, artist in enumerate(artists_data):
            self.artist_to_index[artist["name"]] = i
            self.index_to_artist[i] = artist["name"]

        # Build text documents for TF-IDF
        documents = []
        for artist in artists_data:
            # Create weighted text representation
            doc_parts = []

            # Add genres (highest weight)
            genres = " ".join(artist["genres"]) if artist["genres"] else ""
            doc_parts.extend([genres] * int(self.feature_weights["genres"] * 10))

            # Add styles
            styles = " ".join(artist["styles"]) if artist["styles"] else ""
            doc_parts.extend([styles] * int(self.feature_weights["styles"] * 10))

            # Add labels
            labels = " ".join(artist["labels"]) if artist["labels"] else ""
            doc_parts.extend([labels] * int(self.feature_weights["labels"] * 10))

            # Add collaborators (sample to avoid overwhelming the document)
            collabs = " ".join(artist["collaborators"][:10]) if artist["collaborators"] else ""
            doc_parts.extend([collabs] * int(self.feature_weights["collaborators"] * 10))

            # Add time period indicator
            if artist["earliest_year"] and artist["latest_year"]:
                decade = f"{(artist['earliest_year'] // 10) * 10}s"
                doc_parts.extend([decade] * int(self.feature_weights["time_period"] * 10))

            documents.append(" ".join(doc_parts))

        # Create TF-IDF vectors
        self.tfidf_vectorizer = TfidfVectorizer(
            max_features=1000,
            ngram_range=(1, 2),
            min_df=2,
            max_df=0.8,
            sublinear_tf=True,
        )

        self.tfidf_matrix = self.tfidf_vectorizer.fit_transform(documents).toarray()

        logger.info(
            "✅ Built feature vectors",
            artists=len(artists_data),
            features=self.tfidf_matrix.shape[1] if self.tfidf_matrix is not None else 0,
        )

    async def get_recommendations(self, artist_name: str, limit: int = 10) -> list[dict[str, Any]]:
        """Get content-based recommendations for an artist.

        Args:
            artist_name: Name of the artist to get recommendations for
            limit: Maximum number of recommendations to return

        Returns:
            List of recommended artists with similarity scores
        """
        if self.tfidf_matrix is None or artist_name not in self.artist_to_index:
            return []

        artist_idx = self.artist_to_index[artist_name]

        # Get the artist's feature vector
        artist_vector = self.tfidf_matrix[artist_idx].reshape(1, -1)

        # Compute cosine similarity with all other artists
        similarities = cosine_similarity(artist_vector, self.tfidf_matrix).flatten()

        # Get top N similar artists (excluding self)
        similar_indices = np.argsort(similarities)[::-1][1 : limit + 1]

        recommendations = []
        for idx in similar_indices:
            if similarities[idx] > 0:  # Only include artists with positive similarity
                recommendations.append(
                    {
                        "artist_name": self.index_to_artist[idx],
                        "similarity_score": float(similarities[idx]),
                        "method": "content_based",
                    }
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
        """Get similarity score between two artists based on content.

        Args:
            artist1: First artist name
            artist2: Second artist name

        Returns:
            Similarity score (0.0 to 1.0)
        """
        if self.tfidf_matrix is None:
            return 0.0

        if artist1 not in self.artist_to_index or artist2 not in self.artist_to_index:
            return 0.0

        idx1 = self.artist_to_index[artist1]
        idx2 = self.artist_to_index[artist2]

        vector1 = self.tfidf_matrix[idx1].reshape(1, -1)
        vector2 = self.tfidf_matrix[idx2].reshape(1, -1)

        similarity = cosine_similarity(vector1, vector2)[0][0]
        return float(similarity)

    def get_feature_importance(self, artist_name: str, top_n: int = 10) -> list[dict[str, Any]]:
        """Get the most important features for an artist.

        Args:
            artist_name: Name of the artist
            top_n: Number of top features to return

        Returns:
            List of feature names and their importance scores
        """
        if self.tfidf_matrix is None or self.tfidf_vectorizer is None or artist_name not in self.artist_to_index:
            return []

        artist_idx = self.artist_to_index[artist_name]
        feature_vector = self.tfidf_matrix[artist_idx]

        # Get feature names
        feature_names = self.tfidf_vectorizer.get_feature_names_out()

        # Get top N features by TF-IDF score
        top_indices = np.argsort(feature_vector)[::-1][:top_n]

        features = []
        for idx in top_indices:
            if feature_vector[idx] > 0:
                features.append({"feature": feature_names[idx], "importance": float(feature_vector[idx])})

        return features

    async def get_similar_by_attributes(
        self,
        genres: list[str] | None = None,
        styles: list[str] | None = None,
        labels: list[str] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Get artists similar to specified attributes.

        Args:
            genres: List of genre names
            styles: List of style names
            labels: List of label names
            limit: Maximum number of recommendations to return

        Returns:
            List of recommended artists matching the attributes
        """
        if self.tfidf_matrix is None or self.tfidf_vectorizer is None:
            return []

        # Build a query document from the attributes
        doc_parts = []

        if genres:
            genre_text = " ".join(genres)
            doc_parts.extend([genre_text] * int(self.feature_weights["genres"] * 10))

        if styles:
            style_text = " ".join(styles)
            doc_parts.extend([style_text] * int(self.feature_weights["styles"] * 10))

        if labels:
            label_text = " ".join(labels)
            doc_parts.extend([label_text] * int(self.feature_weights["labels"] * 10))

        if not doc_parts:
            return []

        query_doc = " ".join(doc_parts)

        # Transform query document to TF-IDF vector
        query_vector = self.tfidf_vectorizer.transform([query_doc]).toarray()

        # Compute similarity with all artists
        similarities = cosine_similarity(query_vector, self.tfidf_matrix).flatten()

        # Get top N similar artists
        top_indices = np.argsort(similarities)[::-1][:limit]

        recommendations = []
        for idx in top_indices:
            if similarities[idx] > 0:
                recommendations.append(
                    {
                        "artist_name": self.index_to_artist[idx],
                        "similarity_score": float(similarities[idx]),
                        "method": "content_based_attributes",
                    }
                )

        return recommendations
