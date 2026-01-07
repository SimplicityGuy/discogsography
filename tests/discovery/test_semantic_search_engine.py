"""Tests for SemanticSearchEngine class."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import numpy as np

from discovery.semantic_search import SemanticSearchEngine


class TestSemanticSearchEngineInit:
    """Test SemanticSearchEngine initialization."""

    @patch("discovery.semantic_search.SentenceTransformer")
    def test_initialization_default(self, mock_transformer: Mock) -> None:
        """Test default initialization."""
        mock_model = MagicMock()
        mock_transformer.return_value = mock_model

        engine = SemanticSearchEngine()

        assert engine.model_name == "all-MiniLM-L6-v2"
        assert engine.embedding_cache == {}
        assert engine.artist_metadata == {}
        assert engine.cache_dir.exists()

    @patch("discovery.semantic_search.SentenceTransformer")
    def test_initialization_custom_model(self, mock_transformer: Mock) -> None:
        """Test initialization with custom model."""
        mock_model = MagicMock()
        mock_transformer.return_value = mock_model

        with tempfile.TemporaryDirectory() as tmpdir:
            engine = SemanticSearchEngine(
                model_name="custom-model",
                cache_dir=tmpdir,
                use_onnx=False,
            )

            assert engine.model_name == "custom-model"
            assert str(engine.cache_dir) == tmpdir

    @patch("discovery.semantic_search.SentenceTransformer")
    def test_initialization_model_load_error_fallback(self, mock_transformer: Mock) -> None:
        """Test fallback to default model on load error."""
        # First call fails, second call succeeds with fallback
        mock_transformer.side_effect = [Exception("Model not found"), MagicMock()]

        SemanticSearchEngine(model_name="invalid-model")

        # Should have attempted fallback
        assert mock_transformer.call_count == 2


class TestCacheKeyGeneration:
    """Test cache key generation."""

    @patch("discovery.semantic_search.SentenceTransformer")
    def test_cache_key_generation(self, mock_transformer: Mock) -> None:
        """Test cache key is generated correctly."""
        mock_transformer.return_value = MagicMock()
        engine = SemanticSearchEngine()

        key1 = engine._get_cache_key("test text")
        key2 = engine._get_cache_key("test text")
        key3 = engine._get_cache_key("different text")

        # Same text should produce same key
        assert key1 == key2

        # Different text should produce different key
        assert key1 != key3

        # Key should be SHA256 hex digest
        assert len(key1) == 64


class TestCaching:
    """Test embedding caching."""

    @patch("discovery.semantic_search.SentenceTransformer")
    def test_memory_cache_hit(self, mock_transformer: Mock) -> None:
        """Test loading from memory cache."""
        mock_transformer.return_value = MagicMock()
        engine = SemanticSearchEngine()

        # Add to memory cache
        test_embedding = np.array([1.0, 2.0, 3.0])
        cache_key = "test_key"
        engine.embedding_cache[cache_key] = test_embedding

        # Load should return cached value
        result = engine._load_cached_embedding(cache_key)

        assert result is not None
        np.testing.assert_array_equal(result, test_embedding)

    @patch("discovery.semantic_search.SentenceTransformer")
    def test_cache_miss(self, mock_transformer: Mock) -> None:
        """Test cache miss returns None."""
        mock_transformer.return_value = MagicMock()
        engine = SemanticSearchEngine()

        result = engine._load_cached_embedding("nonexistent_key")

        assert result is None

    @patch("discovery.semantic_search.SentenceTransformer")
    def test_disk_cache_save_and_load(self, mock_transformer: Mock) -> None:
        """Test saving and loading from disk cache."""
        mock_transformer.return_value = MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            engine = SemanticSearchEngine(cache_dir=tmpdir)

            test_embedding = np.array([1.0, 2.0, 3.0])
            cache_key = engine._get_cache_key("test text")

            # Save to cache
            engine._save_cached_embedding(cache_key, test_embedding)

            # Verify saved to memory
            assert cache_key in engine.embedding_cache

            # Verify saved to disk
            cache_path = Path(tmpdir) / f"{cache_key}.npy"
            assert cache_path.exists()

            # Clear memory cache
            engine.embedding_cache.clear()

            # Should still load from disk
            result = engine._load_cached_embedding(cache_key)
            assert result is not None
            np.testing.assert_array_equal(result, test_embedding)


class TestEncoding:
    """Test text encoding."""

    @patch("discovery.semantic_search.SentenceTransformer")
    def test_encode_single_text_without_cache(self, mock_transformer: Mock) -> None:
        """Test encoding single text without caching."""
        mock_model = MagicMock()
        test_embedding = np.array([0.1, 0.2, 0.3])
        mock_model.encode.return_value = test_embedding
        mock_transformer.return_value = mock_model

        engine = SemanticSearchEngine()

        result = engine.encode("test text", use_cache=False)

        np.testing.assert_array_equal(result, test_embedding)
        mock_model.encode.assert_called_once()

    @patch("discovery.semantic_search.SentenceTransformer")
    def test_encode_single_text_with_cache(self, mock_transformer: Mock) -> None:
        """Test encoding single text with caching."""
        mock_model = MagicMock()
        test_embedding = np.array([0.1, 0.2, 0.3])
        mock_model.encode.return_value = test_embedding
        mock_transformer.return_value = mock_model

        with tempfile.TemporaryDirectory() as tmpdir:
            engine = SemanticSearchEngine(cache_dir=tmpdir)

            # First call should encode
            result1 = engine.encode("test text", use_cache=True)
            np.testing.assert_array_equal(result1, test_embedding)

            # Clear memory cache to test disk cache
            engine.embedding_cache.clear()

            # Second call should load from cache (no encode call)
            result2 = engine.encode("test text", use_cache=True)
            np.testing.assert_array_equal(result2, test_embedding)

            # Model should only be called once
            assert mock_model.encode.call_count == 1

    @patch("discovery.semantic_search.SentenceTransformer")
    def test_encode_batch_texts(self, mock_transformer: Mock) -> None:
        """Test encoding batch of texts."""
        mock_model = MagicMock()
        test_embeddings = np.array([[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]])
        mock_model.encode.return_value = test_embeddings
        mock_transformer.return_value = mock_model

        engine = SemanticSearchEngine()

        texts = ["text1", "text2", "text3"]
        result = engine.encode(texts, use_cache=False)

        assert result.shape == test_embeddings.shape
        mock_model.encode.assert_called_once()


class TestArtistEmbeddings:
    """Test artist embedding generation."""

    @patch("discovery.semantic_search.SentenceTransformer")
    def test_build_artist_embeddings_without_metadata(self, mock_transformer: Mock) -> None:
        """Test building artist embeddings without metadata."""
        mock_model = MagicMock()
        test_embeddings = np.array([[0.1, 0.2], [0.3, 0.4]])
        mock_model.encode.return_value = test_embeddings
        mock_transformer.return_value = mock_model

        engine = SemanticSearchEngine()

        artists = [
            {"name": "Artist 1"},
            {"name": "Artist 2"},
        ]

        result = engine.build_artist_embeddings(artists, use_metadata=False)

        assert len(result) == 2
        assert "Artist 1" in result
        assert "Artist 2" in result
        assert result["Artist 1"].shape == (2,)

    @patch("discovery.semantic_search.SentenceTransformer")
    def test_build_artist_embeddings_with_metadata(self, mock_transformer: Mock) -> None:
        """Test building artist embeddings with metadata."""
        mock_model = MagicMock()
        test_embeddings = np.array([[0.1, 0.2, 0.3]])
        mock_model.encode.return_value = test_embeddings
        mock_transformer.return_value = mock_model

        engine = SemanticSearchEngine()

        artists = [
            {
                "name": "Test Artist",
                "genres": ["Rock", "Alternative"],
                "styles": ["Grunge", "Alternative Rock"],
                "labels": ["Label A", "Label B"],
            },
        ]

        result = engine.build_artist_embeddings(artists, use_metadata=True)

        assert len(result) == 1
        assert "Test Artist" in result
        assert "Test Artist" in engine.artist_metadata


class TestSimilaritySearch:
    """Test similarity search functionality."""

    @patch("discovery.semantic_search.SentenceTransformer")
    def test_search_similar_basic(self, mock_transformer: Mock) -> None:
        """Test basic semantic similarity search."""
        mock_model = MagicMock()
        # Query embedding
        query_emb = np.array([1.0, 0.0, 0.0])
        # Artist embeddings (will vary in similarity)
        mock_model.encode.return_value = query_emb
        mock_transformer.return_value = mock_model

        engine = SemanticSearchEngine()

        # Create artist embeddings
        artist_embeddings = {
            "Artist A": np.array([1.0, 0.0, 0.0]),  # Very similar
            "Artist B": np.array([0.5, 0.5, 0.0]),  # Somewhat similar
            "Artist C": np.array([0.0, 1.0, 0.0]),  # Less similar
        }

        results = engine.search_similar("test query", artist_embeddings, top_k=2)

        assert len(results) <= 2
        assert all("artist_name" in r for r in results)
        assert all("similarity_score" in r for r in results)
        assert all("method" in r for r in results)

    @patch("discovery.semantic_search.SentenceTransformer")
    def test_search_similar_with_threshold(self, mock_transformer: Mock) -> None:
        """Test semantic search with similarity threshold."""
        mock_model = MagicMock()
        query_emb = np.array([1.0, 0.0])
        mock_model.encode.return_value = query_emb
        mock_transformer.return_value = mock_model

        engine = SemanticSearchEngine()

        artist_embeddings = {
            "Artist A": np.array([1.0, 0.0]),
            "Artist B": np.array([0.5, 0.5]),
        }

        # High threshold should filter out low similarity results
        results = engine.search_similar("query", artist_embeddings, threshold=0.9)

        # Should return only very similar artists
        assert all(r["similarity_score"] >= 0.9 for r in results)

    @patch("discovery.semantic_search.SentenceTransformer")
    def test_find_similar_artists_basic(self, mock_transformer: Mock) -> None:
        """Test finding similar artists."""
        mock_transformer.return_value = MagicMock()
        engine = SemanticSearchEngine()

        artist_embeddings = {
            "Artist A": np.array([1.0, 0.0]),
            "Artist B": np.array([0.9, 0.1]),
            "Artist C": np.array([0.0, 1.0]),
        }

        results = engine.find_similar_artists("Artist A", artist_embeddings, top_k=2)

        assert len(results) <= 2
        # Should not include the query artist itself
        assert all(r["artist_name"] != "Artist A" for r in results)

    @patch("discovery.semantic_search.SentenceTransformer")
    def test_find_similar_artists_not_found(self, mock_transformer: Mock) -> None:
        """Test finding similar artists when artist not in embeddings."""
        mock_transformer.return_value = MagicMock()
        engine = SemanticSearchEngine()

        artist_embeddings = {
            "Artist A": np.array([1.0, 0.0]),
        }

        results = engine.find_similar_artists("Unknown Artist", artist_embeddings)

        assert results == []


class TestCacheManagement:
    """Test cache management."""

    @patch("discovery.semantic_search.SentenceTransformer")
    def test_clear_cache_memory_only(self, mock_transformer: Mock) -> None:
        """Test clearing only memory cache."""
        mock_transformer.return_value = MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            engine = SemanticSearchEngine(cache_dir=tmpdir)

            # Add to memory cache
            engine.embedding_cache["key1"] = np.array([1.0, 2.0])

            # Save to disk
            test_emb = np.array([3.0, 4.0])
            cache_key = engine._get_cache_key("test")
            engine._save_cached_embedding(cache_key, test_emb)

            # Clear memory only
            engine.clear_cache(memory_only=True)

            assert len(engine.embedding_cache) == 0
            # Disk cache should still exist
            cache_path = Path(tmpdir) / f"{cache_key}.npy"
            assert cache_path.exists()

    @patch("discovery.semantic_search.SentenceTransformer")
    def test_clear_cache_full(self, mock_transformer: Mock) -> None:
        """Test clearing both memory and disk cache."""
        mock_transformer.return_value = MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            engine = SemanticSearchEngine(cache_dir=tmpdir)

            # Add to cache
            test_emb = np.array([1.0, 2.0])
            cache_key = engine._get_cache_key("test")
            engine._save_cached_embedding(cache_key, test_emb)

            # Clear all cache
            engine.clear_cache(memory_only=False)

            assert len(engine.embedding_cache) == 0
            # Disk cache should be cleared
            cache_files = list(Path(tmpdir).glob("*.npy"))
            assert len(cache_files) == 0

    @patch("discovery.semantic_search.SentenceTransformer")
    def test_get_cache_stats(self, mock_transformer: Mock) -> None:
        """Test getting cache statistics."""
        mock_transformer.return_value = MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            engine = SemanticSearchEngine(cache_dir=tmpdir)

            # Add some cached embeddings
            test_emb = np.array([1.0, 2.0, 3.0])
            for i in range(3):
                cache_key = engine._get_cache_key(f"text{i}")
                engine._save_cached_embedding(cache_key, test_emb)

            stats = engine.get_cache_stats()

            assert stats["memory_cached"] == 3
            assert stats["disk_cached"] == 3
            assert stats["cache_size_mb"] > 0
            assert stats["cache_dir"] == tmpdir
