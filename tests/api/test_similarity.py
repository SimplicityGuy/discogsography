"""Tests for cosine similarity utilities."""

from api.queries.similarity import cosine_similarity, to_genre_vector


class TestToGenreVector:
    def test_converts_genre_list_to_percentages(self) -> None:
        genres = [
            {"name": "Rock", "count": 60},
            {"name": "Jazz", "count": 40},
        ]
        result = to_genre_vector(genres)
        assert result == {"Rock": 0.6, "Jazz": 0.4}

    def test_returns_empty_dict_when_total_is_zero(self) -> None:
        genres = [{"name": "Rock", "count": 0}, {"name": "Jazz", "count": 0}]
        assert to_genre_vector(genres) == {}

    def test_returns_empty_dict_for_empty_list(self) -> None:
        assert to_genre_vector([]) == {}

    def test_single_genre_returns_1_point_0(self) -> None:
        genres = [{"name": "Electronic", "count": 100}]
        result = to_genre_vector(genres)
        assert result == {"Electronic": 1.0}

    def test_handles_many_genres(self) -> None:
        genres = [
            {"name": "Rock", "count": 10},
            {"name": "Jazz", "count": 20},
            {"name": "Pop", "count": 30},
            {"name": "Metal", "count": 40},
        ]
        result = to_genre_vector(genres)
        assert abs(sum(result.values()) - 1.0) < 1e-9


class TestCosineSimilarity:
    def test_identical_vectors_return_1(self) -> None:
        vec = {"Rock": 0.5, "Jazz": 0.5}
        assert abs(cosine_similarity(vec, vec) - 1.0) < 1e-9

    def test_orthogonal_vectors_return_0(self) -> None:
        vec_a = {"Rock": 1.0}
        vec_b = {"Jazz": 1.0}
        assert cosine_similarity(vec_a, vec_b) == 0.0

    def test_empty_vec_a_returns_0(self) -> None:
        assert cosine_similarity({}, {"Rock": 1.0}) == 0.0

    def test_empty_vec_b_returns_0(self) -> None:
        assert cosine_similarity({"Rock": 1.0}, {}) == 0.0

    def test_both_empty_returns_0(self) -> None:
        assert cosine_similarity({}, {}) == 0.0

    def test_partial_overlap(self) -> None:
        vec_a = {"Rock": 0.6, "Jazz": 0.4}
        vec_b = {"Rock": 0.8, "Electronic": 0.2}
        result = cosine_similarity(vec_a, vec_b)
        assert 0.0 < result < 1.0

    def test_known_value(self) -> None:
        # vec_a = (3, 4), vec_b = (4, 3) => dot=24, |a|=5, |b|=5 => 24/25
        vec_a = {"x": 3.0, "y": 4.0}
        vec_b = {"x": 4.0, "y": 3.0}
        expected = 24.0 / 25.0
        assert abs(cosine_similarity(vec_a, vec_b) - expected) < 1e-9

    def test_zero_magnitude_vec_returns_0(self) -> None:
        vec_a = {"Rock": 0.0}
        vec_b = {"Rock": 1.0}
        assert cosine_similarity(vec_a, vec_b) == 0.0
