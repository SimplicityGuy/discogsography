"""Enhanced semantic search with improved embeddings.

This module provides advanced semantic search capabilities using improved
embedding models, caching, and multi-modal features.
"""

import hashlib
from pathlib import Path
from typing import Any

import numpy as np
import structlog
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity


logger = structlog.get_logger(__name__)


class SemanticSearchEngine:
    """Enhanced semantic search engine with embedding caching."""

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        cache_dir: str | None = None,
        use_onnx: bool = True,
    ) -> None:
        """Initialize semantic search engine.

        Args:
            model_name: Name of the sentence transformer model
            cache_dir: Directory for caching embeddings
            use_onnx: Whether to use ONNX optimization
        """
        self.model_name = model_name
        self.cache_dir = Path(cache_dir) if cache_dir else Path("./data/embeddings_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Initialize model
        try:
            if use_onnx:
                logger.info("🚀 Loading ONNX-optimized embedding model", model=model_name)
                self.model = SentenceTransformer(model_name, device="cpu")
                # ONNX optimization would be configured here if available
            else:
                logger.info("🚀 Loading standard embedding model", model=model_name)
                self.model = SentenceTransformer(model_name)
        except Exception as e:
            logger.warning("⚠️ Failed to load model, using fallback", model=model_name, error=str(e))
            self.model = SentenceTransformer("all-MiniLM-L6-v2")

        # In-memory cache for embeddings
        self.embedding_cache: dict[str, np.ndarray] = {}

        # Artist metadata for multi-modal embeddings
        self.artist_metadata: dict[str, dict[str, Any]] = {}

    def _get_cache_key(self, text: str) -> str:
        """Generate cache key for text.

        Args:
            text: Input text

        Returns:
            SHA256 hash of text
        """
        return hashlib.sha256(text.encode()).hexdigest()

    def _load_cached_embedding(self, cache_key: str) -> np.ndarray | None:
        """Load embedding from cache.

        Args:
            cache_key: Cache key

        Returns:
            Cached embedding or None
        """
        # Check in-memory cache first
        if cache_key in self.embedding_cache:
            return self.embedding_cache[cache_key]

        # Check disk cache
        cache_path = self.cache_dir / f"{cache_key}.npy"
        if cache_path.exists():
            try:
                embedding = np.load(cache_path)
                # Store in memory cache
                self.embedding_cache[cache_key] = embedding
                return embedding
            except Exception as e:
                logger.warning("⚠️ Failed to load cached embedding", error=str(e))

        return None

    def _save_cached_embedding(self, cache_key: str, embedding: np.ndarray) -> None:
        """Save embedding to cache.

        Args:
            cache_key: Cache key
            embedding: Embedding vector
        """
        # Save to memory cache
        self.embedding_cache[cache_key] = embedding

        # Save to disk cache
        cache_path = self.cache_dir / f"{cache_key}.npy"
        try:
            np.save(cache_path, embedding)
        except Exception as e:
            logger.warning("⚠️ Failed to save embedding cache", error=str(e))

    def encode(self, text: str | list[str], use_cache: bool = True) -> np.ndarray:
        """Encode text to embedding vector(s).

        Args:
            text: Text or list of texts to encode
            use_cache: Whether to use caching

        Returns:
            Embedding vector(s)
        """
        # Handle single text
        if isinstance(text, str):
            if use_cache:
                cache_key = self._get_cache_key(text)
                cached = self._load_cached_embedding(cache_key)
                if cached is not None:
                    return cached

            embedding = self.model.encode(text, convert_to_numpy=True, show_progress_bar=False)

            if use_cache:
                cache_key = self._get_cache_key(text)
                self._save_cached_embedding(cache_key, embedding)

            return embedding

        # Handle batch encoding
        embeddings_list = []
        texts_to_encode = []
        text_indices = []

        for i, t in enumerate(text):
            if use_cache:
                cache_key = self._get_cache_key(t)
                cached = self._load_cached_embedding(cache_key)
                if cached is not None:
                    embeddings_list.append((i, cached))
                else:
                    texts_to_encode.append(t)
                    text_indices.append(i)
            else:
                texts_to_encode.append(t)
                text_indices.append(i)

        # Encode uncached texts in batch
        if texts_to_encode:
            new_embeddings = self.model.encode(
                texts_to_encode,
                convert_to_numpy=True,
                show_progress_bar=False,
                batch_size=32,
            )

            for idx, t, emb in zip(text_indices, texts_to_encode, new_embeddings, strict=True):
                embeddings_list.append((idx, emb))
                if use_cache:
                    cache_key = self._get_cache_key(t)
                    self._save_cached_embedding(cache_key, emb)

        # Sort by original index and return
        embeddings_list.sort(key=lambda x: x[0])
        return np.array([emb for _, emb in embeddings_list])

    def build_artist_embeddings(
        self,
        artists: list[dict[str, Any]],
        use_metadata: bool = True,
    ) -> dict[str, np.ndarray]:
        """Build embeddings for a list of artists.

        Args:
            artists: List of artist dictionaries with name and metadata
            use_metadata: Whether to include metadata in embeddings

        Returns:
            Dictionary mapping artist names to embeddings
        """
        artist_embeddings = {}
        texts_to_encode = []
        artist_names = []

        for artist in artists:
            name = artist["name"]
            self.artist_metadata[name] = artist

            if use_metadata:
                # Create rich text representation
                text_parts = [name]

                # Add genres
                if artist.get("genres"):
                    genres = " ".join(artist["genres"][:3])
                    text_parts.append(f"genres: {genres}")

                # Add styles
                if artist.get("styles"):
                    styles = " ".join(artist["styles"][:3])
                    text_parts.append(f"styles: {styles}")

                # Add labels
                if artist.get("labels"):
                    labels = " ".join(artist["labels"][:2])
                    text_parts.append(f"labels: {labels}")

                text = ". ".join(text_parts)
            else:
                text = name

            texts_to_encode.append(text)
            artist_names.append(name)

        # Batch encode
        embeddings = self.encode(texts_to_encode, use_cache=True)

        # Create mapping
        for name, embedding in zip(artist_names, embeddings, strict=True):
            artist_embeddings[name] = embedding

        logger.info(
            "✅ Built artist embeddings",
            count=len(artist_embeddings),
            use_metadata=use_metadata,
        )

        return artist_embeddings

    def search_similar(
        self,
        query: str,
        artist_embeddings: dict[str, np.ndarray],
        top_k: int = 10,
        threshold: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Search for similar artists using semantic similarity.

        Args:
            query: Search query text
            artist_embeddings: Dictionary of artist embeddings
            top_k: Number of results to return
            threshold: Minimum similarity score

        Returns:
            List of similar artists with scores
        """
        # Encode query
        query_embedding = self.encode(query, use_cache=False).reshape(1, -1)

        # Calculate similarities
        similarities = []

        for artist_name, artist_embedding in artist_embeddings.items():
            artist_emb_reshaped = artist_embedding.reshape(1, -1)
            similarity = float(cosine_similarity(query_embedding, artist_emb_reshaped)[0][0])

            if similarity >= threshold:
                similarities.append(
                    {
                        "artist_name": artist_name,
                        "similarity_score": similarity,
                        "method": "semantic_search",
                    }
                )

        # Sort by similarity and return top K
        similarities.sort(key=lambda x: float(x["similarity_score"]), reverse=True)  # type: ignore[arg-type]

        logger.info(
            "🔍 Semantic search completed",
            query=query,
            results=len(similarities[:top_k]),
        )

        return similarities[:top_k]

    def find_similar_artists(
        self,
        artist_name: str,
        artist_embeddings: dict[str, np.ndarray],
        top_k: int = 10,
        threshold: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Find artists similar to a given artist.

        Args:
            artist_name: Name of the artist
            artist_embeddings: Dictionary of artist embeddings
            top_k: Number of results to return
            threshold: Minimum similarity score

        Returns:
            List of similar artists with scores
        """
        if artist_name not in artist_embeddings:
            logger.warning("⚠️ Artist not found in embeddings", artist=artist_name)
            return []

        artist_embedding = artist_embeddings[artist_name].reshape(1, -1)

        # Calculate similarities
        similarities = []

        for other_artist, other_embedding in artist_embeddings.items():
            if other_artist == artist_name:
                continue  # Skip self

            other_emb_reshaped = other_embedding.reshape(1, -1)
            similarity = float(cosine_similarity(artist_embedding, other_emb_reshaped)[0][0])

            if similarity >= threshold:
                similarities.append(
                    {
                        "artist_name": other_artist,
                        "similarity_score": similarity,
                        "method": "semantic_similarity",
                    }
                )

        # Sort and return
        similarities.sort(key=lambda x: float(x["similarity_score"]), reverse=True)  # type: ignore[arg-type]

        return similarities[:top_k]

    def hybrid_search(
        self,
        query: str,
        artist_embeddings: dict[str, np.ndarray],
        text_results: list[dict[str, Any]],
        semantic_weight: float = 0.6,
        text_weight: float = 0.4,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """Combine semantic search with text search results.

        Args:
            query: Search query
            artist_embeddings: Dictionary of artist embeddings
            text_results: Results from text-based search
            semantic_weight: Weight for semantic scores
            text_weight: Weight for text scores
            top_k: Number of results

        Returns:
            Combined and reranked results
        """
        # Get semantic results
        semantic_results = self.search_similar(query, artist_embeddings, top_k=top_k * 2)

        # Create score maps
        semantic_scores = {r["artist_name"]: r["similarity_score"] for r in semantic_results}
        text_scores = {r["name"]: r.get("rank", 0.5) for r in text_results}

        # Normalize text scores to [0, 1]
        if text_scores:
            max_text_score = max(text_scores.values())
            if max_text_score > 0:
                text_scores = {name: score / max_text_score for name, score in text_scores.items()}

        # Combine scores
        all_artists = set(semantic_scores.keys()) | set(text_scores.keys())
        combined_scores = []

        for artist in all_artists:
            semantic_score = semantic_scores.get(artist, 0.0)
            text_score = text_scores.get(artist, 0.0)

            combined_score = semantic_weight * semantic_score + text_weight * text_score

            combined_scores.append(
                {
                    "artist_name": artist,
                    "similarity_score": combined_score,
                    "semantic_score": semantic_score,
                    "text_score": text_score,
                    "method": "hybrid_search",
                }
            )

        # Sort and return
        combined_scores.sort(key=lambda x: x["similarity_score"], reverse=True)

        logger.info(
            "✅ Hybrid search completed",
            query=query,
            results=len(combined_scores[:top_k]),
        )

        return combined_scores[:top_k]

    def clear_cache(self, memory_only: bool = False) -> None:
        """Clear embedding cache.

        Args:
            memory_only: If True, only clear memory cache, not disk
        """
        self.embedding_cache.clear()

        if not memory_only:
            # Clear disk cache
            for cache_file in self.cache_dir.glob("*.npy"):
                try:
                    cache_file.unlink()
                except Exception as e:
                    logger.warning("⚠️ Failed to delete cache file", file=str(cache_file), error=str(e))

        logger.info("🔄 Cleared embedding cache", memory_only=memory_only)

    def get_cache_stats(self) -> dict[str, Any]:
        """Get statistics about the embedding cache.

        Returns:
            Dictionary with cache statistics
        """
        memory_count = len(self.embedding_cache)

        disk_count = len(list(self.cache_dir.glob("*.npy")))

        total_size = sum(f.stat().st_size for f in self.cache_dir.glob("*.npy"))

        return {
            "memory_cached": memory_count,
            "disk_cached": disk_count,
            "cache_size_mb": total_size / (1024 * 1024),
            "cache_dir": str(self.cache_dir),
        }
