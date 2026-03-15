"""Unit tests for recommend query scoring logic."""

from api.queries.recommend_queries import (
    compute_similar_artists,
)


class TestComputeSimilarArtists:
    """Tests for the artist similarity scoring function."""

    def _make_candidate(
        self,
        artist_id: str = "a1",
        artist_name: str = "Artist A",
        release_count: int = 10,
        genres: list | None = None,
        styles: list | None = None,
        labels: list | None = None,
        collaborators: list | None = None,
    ) -> dict:
        return {
            "artist_id": artist_id,
            "artist_name": artist_name,
            "release_count": release_count,
            "genres": genres or [{"name": "Rock", "count": 10}],
            "styles": styles or [{"name": "Punk", "count": 5}],
            "labels": labels or [{"name": "Sub Pop", "count": 3}],
            "collaborators": collaborators or [],
        }

    def test_returns_ranked_results(self) -> None:
        target = {
            "genres": [{"name": "Rock", "count": 80}, {"name": "Jazz", "count": 20}],
            "styles": [{"name": "Punk", "count": 50}],
            "labels": [{"name": "Sub Pop", "count": 30}],
            "collaborators": [{"name": "Dave Grohl", "count": 5}],
        }
        candidates = [
            self._make_candidate(
                artist_id="a1",
                artist_name="Close Match",
                genres=[{"name": "Rock", "count": 70}, {"name": "Jazz", "count": 30}],
                styles=[{"name": "Punk", "count": 40}],
                labels=[{"name": "Sub Pop", "count": 20}],
                collaborators=[{"name": "Dave Grohl", "count": 3}],
            ),
            self._make_candidate(
                artist_id="a2",
                artist_name="Far Match",
                genres=[{"name": "Electronic", "count": 90}, {"name": "Rock", "count": 10}],
                styles=[{"name": "House", "count": 80}],
                labels=[{"name": "Warp", "count": 50}],
            ),
        ]
        results = compute_similar_artists(target, candidates, limit=10)
        assert len(results) == 2
        assert results[0]["artist_id"] == "a1"
        assert results[0]["similarity"] > results[1]["similarity"]

    def test_breakdown_has_all_dimensions(self) -> None:
        target = {
            "genres": [{"name": "Rock", "count": 10}],
            "styles": [{"name": "Punk", "count": 5}],
            "labels": [{"name": "Sub Pop", "count": 3}],
            "collaborators": [],
        }
        candidates = [self._make_candidate()]
        results = compute_similar_artists(target, candidates, limit=10)
        assert len(results) == 1
        breakdown = results[0]["breakdown"]
        assert set(breakdown.keys()) == {"genre", "style", "label", "collaborator"}

    def test_shared_genres_and_labels_populated(self) -> None:
        target = {
            "genres": [{"name": "Rock", "count": 50}, {"name": "Jazz", "count": 50}],
            "styles": [],
            "labels": [{"name": "Sub Pop", "count": 10}, {"name": "Merge", "count": 5}],
            "collaborators": [],
        }
        candidates = [
            self._make_candidate(
                genres=[{"name": "Rock", "count": 10}, {"name": "Classical", "count": 5}],
                labels=[{"name": "Sub Pop", "count": 8}],
            ),
        ]
        results = compute_similar_artists(target, candidates, limit=10)
        assert "Rock" in results[0]["shared_genres"]
        assert "Jazz" not in results[0]["shared_genres"]
        assert "Sub Pop" in results[0]["shared_labels"]

    def test_respects_limit(self) -> None:
        target = {
            "genres": [{"name": "Rock", "count": 100}],
            "styles": [],
            "labels": [],
            "collaborators": [],
        }
        candidates = [self._make_candidate(artist_id=str(i), artist_name=f"Artist {i}") for i in range(20)]
        results = compute_similar_artists(target, candidates, limit=5)
        assert len(results) == 5

    def test_empty_target(self) -> None:
        target = {"genres": [], "styles": [], "labels": [], "collaborators": []}
        candidates = [self._make_candidate()]
        results = compute_similar_artists(target, candidates, limit=10)
        assert results == []

    def test_empty_candidates(self) -> None:
        target = {"genres": [{"name": "Rock", "count": 10}], "styles": [], "labels": [], "collaborators": []}
        results = compute_similar_artists(target, [], limit=10)
        assert results == []

    def test_zero_similarity_excluded(self) -> None:
        target = {
            "genres": [{"name": "Rock", "count": 100}],
            "styles": [{"name": "Punk", "count": 100}],
            "labels": [{"name": "Sub Pop", "count": 100}],
            "collaborators": [{"name": "A", "count": 1}],
        }
        candidates = [
            self._make_candidate(
                genres=[{"name": "Classical", "count": 100}],
                styles=[{"name": "Baroque", "count": 100}],
                labels=[{"name": "DG", "count": 100}],
                collaborators=[{"name": "B", "count": 1}],
            ),
        ]
        results = compute_similar_artists(target, candidates, limit=10)
        assert results == []


class TestEnhancedRecommendationScoring:
    """Tests for multi-signal recommendation merging."""

    def test_merge_candidates_by_release_id(self) -> None:
        from api.queries.recommend_queries import merge_recommendation_candidates

        artist_candidates = [
            {"id": "r1", "title": "A", "artist": "X", "label": "L", "year": 2000, "genres": ["Rock"], "score": 0.8, "source": "artist"},
        ]
        label_candidates = [
            {"id": "r1", "title": "A", "artist": "X", "label": "L", "year": 2000, "genres": ["Rock"], "score": 0.6, "source": "label"},
            {"id": "r2", "title": "B", "artist": "Y", "label": "M", "year": 2010, "genres": ["Jazz"], "score": 0.5, "source": "label"},
        ]
        blindspot_candidates: list = []

        results = merge_recommendation_candidates(artist_candidates, label_candidates, blindspot_candidates, limit=10)
        assert results[0]["id"] == "r1"
        assert len(results[0]["reasons"]) == 2
        assert len(results) == 2

    def test_merge_respects_limit(self) -> None:
        from api.queries.recommend_queries import merge_recommendation_candidates

        artists = [
            {"id": f"r{i}", "title": f"T{i}", "artist": "A", "label": "L", "year": 2000, "genres": [], "score": 0.5, "source": "artist"}
            for i in range(20)
        ]
        results = merge_recommendation_candidates(artists, [], [], limit=5)
        assert len(results) == 5

    def test_merge_empty_inputs(self) -> None:
        from api.queries.recommend_queries import merge_recommendation_candidates

        results = merge_recommendation_candidates([], [], [], limit=10)
        assert results == []

    def test_scores_normalized_to_0_1_range(self) -> None:
        from api.queries.recommend_queries import merge_recommendation_candidates

        artists = [
            {"id": "r1", "title": "A", "artist": "X", "label": "L", "year": 2000, "genres": [], "score": 50, "source": "artist"},
            {"id": "r2", "title": "B", "artist": "Y", "label": "M", "year": 2010, "genres": [], "score": 25, "source": "artist"},
        ]
        results = merge_recommendation_candidates(artists, [], [], limit=10)
        assert all(0 <= r["score"] <= 1.0 for r in results)

    def test_obscurity_bonus_applied(self) -> None:
        from api.queries.recommend_queries import merge_recommendation_candidates

        artists = [
            {"id": "r1", "title": "A", "artist": "X", "label": "L", "year": 2000, "genres": [], "score": 10, "source": "artist"},
            {"id": "r2", "title": "B", "artist": "Y", "label": "M", "year": 2010, "genres": [], "score": 10, "source": "artist"},
        ]
        collector_counts = {"r1": 2, "r2": 100}
        results = merge_recommendation_candidates(artists, [], [], collector_counts=collector_counts, limit=10)
        r1 = next(r for r in results if r["id"] == "r1")
        r2 = next(r for r in results if r["id"] == "r2")
        assert r1["score"] > r2["score"]
