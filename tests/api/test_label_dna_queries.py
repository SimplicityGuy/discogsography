"""Unit tests for Label DNA query functions."""

import pytest

from api.queries.label_dna_queries import (
    _to_genre_vector,
    compute_similar_labels,
    cosine_similarity,
)


class TestCosimSimilarity:
    """Tests for the cosine similarity function."""

    def test_identical_vectors(self) -> None:
        vec = {"Rock": 0.6, "Jazz": 0.4}
        assert cosine_similarity(vec, vec) == pytest.approx(1.0)

    def test_orthogonal_vectors(self) -> None:
        vec_a = {"Rock": 1.0}
        vec_b = {"Jazz": 1.0}
        assert cosine_similarity(vec_a, vec_b) == pytest.approx(0.0)

    def test_partial_overlap(self) -> None:
        vec_a = {"Rock": 0.5, "Jazz": 0.5}
        vec_b = {"Rock": 0.5, "Electronic": 0.5}
        sim = cosine_similarity(vec_a, vec_b)
        assert 0.0 < sim < 1.0

    def test_empty_vector_a(self) -> None:
        assert cosine_similarity({}, {"Rock": 1.0}) == 0.0

    def test_empty_vector_b(self) -> None:
        assert cosine_similarity({"Rock": 1.0}, {}) == 0.0

    def test_both_empty(self) -> None:
        assert cosine_similarity({}, {}) == 0.0

    def test_single_dimension(self) -> None:
        vec_a = {"Rock": 0.8}
        vec_b = {"Rock": 0.3}
        assert cosine_similarity(vec_a, vec_b) == pytest.approx(1.0)


class TestToGenreVector:
    """Tests for _to_genre_vector."""

    def test_normalizes_counts_to_percentages(self) -> None:
        genres = [{"name": "Rock", "count": 60}, {"name": "Jazz", "count": 40}]
        vec = _to_genre_vector(genres)
        assert vec["Rock"] == pytest.approx(0.6)
        assert vec["Jazz"] == pytest.approx(0.4)

    def test_empty_list(self) -> None:
        assert _to_genre_vector([]) == {}

    def test_uses_genre_key(self) -> None:
        genres = [{"genre": "Rock", "count": 10}]
        vec = _to_genre_vector(genres)
        assert "Rock" in vec

    def test_zero_total(self) -> None:
        genres = [{"name": "Rock", "count": 0}]
        assert _to_genre_vector(genres) == {}


class TestComputeSimilarLabels:
    """Tests for compute_similar_labels."""

    def test_returns_ranked_results(self) -> None:
        target = [{"name": "Rock", "count": 80}, {"name": "Jazz", "count": 20}]
        candidates = [
            {
                "label_id": "1",
                "label_name": "Label A",
                "release_count": 50,
                "genres": [{"genre": "Rock", "count": 70}, {"genre": "Jazz", "count": 30}],
            },
            {
                "label_id": "2",
                "label_name": "Label B",
                "release_count": 30,
                "genres": [{"genre": "Electronic", "count": 90}, {"genre": "Rock", "count": 10}],
            },
        ]
        results = compute_similar_labels(target, candidates, limit=10)
        assert len(results) == 2
        assert results[0]["label_id"] == "1"
        assert results[0]["similarity"] > results[1]["similarity"]

    def test_respects_limit(self) -> None:
        target = [{"name": "Rock", "count": 100}]
        candidates = [
            {
                "label_id": str(i),
                "label_name": f"Label {i}",
                "release_count": 10,
                "genres": [{"genre": "Rock", "count": 10}],
            }
            for i in range(20)
        ]
        results = compute_similar_labels(target, candidates, limit=5)
        assert len(results) == 5

    def test_empty_target(self) -> None:
        results = compute_similar_labels([], [{"label_id": "1", "label_name": "L", "release_count": 5, "genres": []}], limit=10)
        assert results == []

    def test_empty_candidates(self) -> None:
        results = compute_similar_labels([{"name": "Rock", "count": 10}], [], limit=10)
        assert results == []

    def test_shared_genres_populated(self) -> None:
        target = [{"name": "Rock", "count": 50}, {"name": "Jazz", "count": 50}]
        candidates = [
            {
                "label_id": "1",
                "label_name": "Label A",
                "release_count": 10,
                "genres": [{"genre": "Rock", "count": 10}, {"genre": "Classical", "count": 5}],
            },
        ]
        results = compute_similar_labels(target, candidates, limit=10)
        assert results[0]["shared_genres"] == ["Rock"]
