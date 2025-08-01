"""AI-Powered Music Discovery Engine using graph algorithms and ML."""

import logging
from typing import TYPE_CHECKING, Any

import networkx as nx
import numpy as np
from common import get_config
from neo4j import AsyncDriver, AsyncGraphDatabase
from pydantic import BaseModel


# Import ONNX sentence transformer if available, fallback to regular
try:
    from discovery.onnx_sentence_transformer import ONNXSentenceTransformer

    ONNX_AVAILABLE = True
except ImportError:
    from sentence_transformers import SentenceTransformer

    ONNX_AVAILABLE = False
from sklearn.metrics.pairwise import cosine_similarity


if TYPE_CHECKING:
    from sklearn.feature_extraction.text import TfidfVectorizer


logger = logging.getLogger(__name__)


class RecommendationRequest(BaseModel):
    """Request model for music recommendations."""

    artist_name: str | None = None
    release_title: str | None = None
    genres: list[str] | None = None
    year_range: tuple[int, int] | None = None
    limit: int = 10
    recommendation_type: str = "similar"  # similar, trending, discovery


class RecommendationResult(BaseModel):
    """Result model for music recommendations."""

    artist_name: str
    release_title: str | None = None
    year: int | None = None
    genres: list[str] = []
    similarity_score: float
    explanation: str
    neo4j_id: str


class MusicRecommender:
    """AI-powered music recommendation engine."""

    def __init__(self) -> None:
        self.config = get_config()
        self.driver: AsyncDriver | None = None
        self.graph: nx.Graph | None = None
        self.embedding_model: ONNXSentenceTransformer | SentenceTransformer | None = None
        self.tfidf_vectorizer: TfidfVectorizer | None = None
        self.artist_embeddings: np.ndarray | None = None
        self.artist_to_index: dict[str, int] = {}
        self.index_to_artist: dict[int, str] = {}

    async def initialize(self) -> None:
        """Initialize the recommender with ML models and graph data."""
        logger.info("🤖 Initializing recommender engine...")

        # Initialize Neo4j connection
        self.driver = AsyncGraphDatabase.driver(self.config.neo4j_address, auth=(self.config.neo4j_username, self.config.neo4j_password))

        # Initialize ML models
        logger.info("🧠 Loading sentence transformer model...")

        # Check for ONNX model first
        from pathlib import Path

        onnx_model_path = Path("/models/onnx/all-MiniLM-L6-v2")

        if ONNX_AVAILABLE and onnx_model_path.exists():
            logger.info("⚡ Using optimized ONNX model for inference")
            self.embedding_model = ONNXSentenceTransformer(str(onnx_model_path))
        else:
            logger.info("🔄 Using standard PyTorch model")
            self.embedding_model = SentenceTransformer("all-MiniLM-L6-v2")

        # Build collaboration graph
        await self._build_collaboration_graph()

        # Generate artist embeddings
        await self._generate_artist_embeddings()

        logger.info("✅ Music Discovery Engine initialized successfully")

    async def _build_collaboration_graph(self) -> None:
        """Build NetworkX graph from Neo4j artist relationships."""
        logger.info("🔗 Building artist collaboration graph...")

        assert self.driver is not None, "Driver must be initialized before building graph"  # nosec B101
        self.graph = nx.Graph()

        async with self.driver.session() as session:
            # Get artist collaborations through releases
            result = await session.run("""
                MATCH (a1:Artist)-[:BY]->(r:Release)<-[:BY]-(a2:Artist)
                WHERE a1.name <> a2.name
                RETURN a1.name as artist1, a2.name as artist2, count(r) as collaborations
                ORDER BY collaborations DESC
                LIMIT 10000
            """)

            async for record in result:
                artist1 = record["artist1"]
                artist2 = record["artist2"]
                weight = record["collaborations"]

                self.graph.add_edge(artist1, artist2, weight=weight)

        logger.info(f"📊 Built collaboration graph with {self.graph.number_of_nodes()} artists and {self.graph.number_of_edges()} collaborations")

    async def _generate_artist_embeddings(self) -> None:
        """Generate semantic embeddings for artists based on their profiles."""
        logger.info("🧬 Generating artist embeddings...")

        assert self.driver is not None, "Driver must be initialized before generating embeddings"  # nosec B101
        artists_data = []

        async with self.driver.session() as session:
            result = await session.run("""
                MATCH (a:Artist)
                OPTIONAL MATCH (a)-[:BY]->(r:Release)-[:IS]->(g:Genre)
                WITH a, collect(DISTINCT g.name) as genres
                OPTIONAL MATCH (a)-[:BY]->(r:Release)-[:IS]->(s:Style)
                WITH a, genres, collect(DISTINCT s.name) as styles
                RETURN a.name as name,
                       coalesce(a.profile, '') as profile,
                       genres,
                       styles
                LIMIT 5000
            """)

            async for record in result:
                artist_name = record["name"]
                profile = record["profile"] or ""
                genres = record["genres"] or []
                styles = record["styles"] or []

                # Create text representation
                text_features = f"{profile} {' '.join(genres)} {' '.join(styles)}"
                artists_data.append({"name": artist_name, "text": text_features})

        if not artists_data:
            logger.warning("⚠️ No artist data found for embeddings")
            return

        # Generate embeddings
        assert self.embedding_model is not None, "Embedding model must be initialized"  # nosec B101
        artist_texts = [data["text"] for data in artists_data]
        self.artist_embeddings = self.embedding_model.encode(artist_texts)

        # Create mapping indices
        for i, data in enumerate(artists_data):
            self.artist_to_index[data["name"]] = i
            self.index_to_artist[i] = data["name"]

        logger.info(f"✅ Generated embeddings for {len(artists_data)} artists")

    async def get_similar_artists(self, artist_name: str, limit: int = 10) -> list[RecommendationResult]:
        """Get similar artists using graph algorithms and embeddings."""
        if not self.graph or self.artist_embeddings is None or self.artist_embeddings.size == 0:
            return []

        recommendations = []

        # Graph-based similarity (collaboration network)
        if artist_name in self.graph:
            # Find artists with shared collaborators
            neighbors = set(self.graph.neighbors(artist_name))

            # Calculate similarity scores
            similarity_scores = {}
            for other_artist in self.graph.nodes():
                if other_artist == artist_name:
                    continue

                other_neighbors = set(self.graph.neighbors(other_artist))
                common_neighbors = neighbors.intersection(other_neighbors)

                if common_neighbors:
                    jaccard_similarity = len(common_neighbors) / len(neighbors.union(other_neighbors))
                    similarity_scores[other_artist] = jaccard_similarity

            # Get top similar artists from graph
            graph_similar = sorted(similarity_scores.items(), key=lambda x: x[1], reverse=True)[: limit // 2]

            for similar_artist, score in graph_similar:
                # Get artist details
                artist_info = await self._get_artist_info(similar_artist)
                if artist_info:
                    recommendations.append(
                        RecommendationResult(
                            artist_name=similar_artist,
                            release_title=artist_info.get("recent_release"),
                            year=artist_info.get("recent_year"),
                            genres=artist_info.get("genres", []),
                            similarity_score=score,
                            explanation=f"Similar collaboration network ({len(neighbors.intersection(set(self.graph.neighbors(similar_artist))))} shared collaborators)",
                            neo4j_id=artist_info.get("id", ""),
                        )
                    )

        # Embedding-based similarity (semantic)
        if artist_name in self.artist_to_index:
            artist_idx = self.artist_to_index[artist_name]
            artist_embedding = self.artist_embeddings[artist_idx].reshape(1, -1)

            # Calculate cosine similarity
            similarities = cosine_similarity(artist_embedding, self.artist_embeddings)[0]

            # Get top similar artists (excluding self)
            similar_indices = np.argsort(similarities)[::-1][1 : limit // 2 + 1]

            for idx in similar_indices:
                similar_artist = self.index_to_artist[idx]
                score = similarities[idx]

                # Get artist details
                artist_info = await self._get_artist_info(similar_artist)
                if artist_info:
                    recommendations.append(
                        RecommendationResult(
                            artist_name=similar_artist,
                            release_title=artist_info.get("recent_release"),
                            year=artist_info.get("recent_year"),
                            genres=artist_info.get("genres", []),
                            similarity_score=float(score),
                            explanation=f"Similar musical style and profile (semantic similarity: {score:.3f})",
                            neo4j_id=artist_info.get("id", ""),
                        )
                    )

        return recommendations[:limit]

    async def get_trending_music(self, genres: list[str] | None = None, limit: int = 10) -> list[RecommendationResult]:
        """Get trending music based on collaboration frequency and recent activity."""
        assert self.driver is not None, "Driver must be initialized before getting trending music"  # nosec B101
        trending = []

        async with self.driver.session() as session:
            # Get artists with high collaboration activity
            genre_filter = ""
            if genres:
                genre_filter = "AND any(g IN genres WHERE g IN $genres)"

            result = await session.run(
                f"""
                MATCH (a:Artist)-[:BY]->(r:Release)
                OPTIONAL MATCH (r)-[:IS]->(g:Genre)
                WITH a, collect(DISTINCT g.name) as genres, count(DISTINCT r) as release_count
                WHERE release_count > 5 {genre_filter}
                OPTIONAL MATCH (a)-[:BY]->(recent:Release)
                WITH a, genres, release_count, recent
                ORDER BY recent.year DESC
                WITH a, genres, release_count, collect(recent)[0] as latest_release
                RETURN a.name as name,
                       a.id as id,
                       genres,
                       release_count,
                       latest_release.title as recent_release,
                       latest_release.year as recent_year
                ORDER BY release_count DESC
                LIMIT $limit
            """,
                genres=genres or [],
                limit=limit,
            )

            async for record in result:
                trending.append(
                    RecommendationResult(
                        artist_name=record["name"],
                        release_title=record["recent_release"],
                        year=record["recent_year"],
                        genres=record["genres"] or [],
                        similarity_score=float(record["release_count"]) / 100.0,  # Normalize to 0-1
                        explanation=f"High activity artist with {record['release_count']} releases",
                        neo4j_id=str(record["id"]),
                    )
                )

        return trending

    async def discovery_search(self, query: str, limit: int = 10) -> list[RecommendationResult]:
        """Semantic search for music discovery."""
        if not self.embedding_model:
            return []

        # Generate query embedding
        query_embedding = self.embedding_model.encode([query])

        # Find similar artists
        if self.artist_embeddings is not None and self.artist_embeddings.size > 0:
            similarities = cosine_similarity(query_embedding, self.artist_embeddings)[0]
            similar_indices = np.argsort(similarities)[::-1][:limit]

            results = []
            for idx in similar_indices:
                artist_name = self.index_to_artist[idx]
                score = similarities[idx]

                artist_info = await self._get_artist_info(artist_name)
                if artist_info:
                    results.append(
                        RecommendationResult(
                            artist_name=artist_name,
                            release_title=artist_info.get("recent_release"),
                            year=artist_info.get("recent_year"),
                            genres=artist_info.get("genres", []),
                            similarity_score=float(score),
                            explanation=f"Semantic match for '{query}' (similarity: {score:.3f})",
                            neo4j_id=artist_info.get("id", ""),
                        )
                    )

            return results

        return []

    async def _get_artist_info(self, artist_name: str) -> dict[str, Any] | None:
        """Get detailed artist information from Neo4j."""
        assert self.driver is not None, "Driver must be initialized before getting artist info"  # nosec B101
        async with self.driver.session() as session:
            result = await session.run(
                """
                MATCH (a:Artist {name: $name})
                OPTIONAL MATCH (a)-[:BY]->(r:Release)-[:IS]->(g:Genre)
                WITH a, collect(DISTINCT g.name) as genres
                OPTIONAL MATCH (a)-[:BY]->(recent:Release)
                WITH a, genres, recent
                ORDER BY recent.year DESC
                WITH a, genres, collect(recent)[0] as latest_release
                RETURN a.id as id,
                       genres,
                       latest_release.title as recent_release,
                       latest_release.year as recent_year
            """,
                name=artist_name,
            )

            record = await result.single()
            if record:
                return {
                    "id": str(record["id"]),
                    "genres": record["genres"] or [],
                    "recent_release": record["recent_release"],
                    "recent_year": record["recent_year"],
                }

        return None

    async def close(self) -> None:
        """Close database connections."""
        if self.driver:
            await self.driver.close()


# Global recommender instance - initialized lazily
recommender: MusicRecommender | None = None


def get_recommender_instance() -> MusicRecommender:
    """Get or create the global recommender instance."""
    global recommender
    if recommender is None:
        recommender = MusicRecommender()
    return recommender


async def get_recommendations(request: RecommendationRequest) -> list[RecommendationResult]:
    """Get music recommendations based on request type."""
    recommender_instance = get_recommender_instance()

    if request.recommendation_type == "similar" and request.artist_name:
        return await recommender_instance.get_similar_artists(request.artist_name, request.limit)
    elif request.recommendation_type == "trending":
        return await recommender_instance.get_trending_music(request.genres, request.limit)
    elif request.recommendation_type == "discovery" and (request.artist_name or request.release_title):
        query = request.artist_name or request.release_title or ""
        return await recommender_instance.discovery_search(query, request.limit)

    return []
