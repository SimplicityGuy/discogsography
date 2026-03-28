"""Unit tests for recommend query scoring logic."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.queries.recommend_queries import (
    _batch_artist_profiles,
    compute_similar_artists,
    get_candidate_artists,
)


# ---------------------------------------------------------------------------
# Mock helpers (matching test_neo4j_queries.py patterns)
# ---------------------------------------------------------------------------


class _AsyncIter:
    """Async iterator that yields pre-built records for mock Neo4j results."""

    def __init__(self, records: list[dict[str, Any]]) -> None:
        self._records = records
        self._index = 0

    def __aiter__(self) -> "_AsyncIter":
        return self

    async def __anext__(self) -> dict[str, Any]:
        if self._index >= len(self._records):
            raise StopAsyncIteration
        record = self._records[self._index]
        self._index += 1
        return record


class _MockResult:
    """Mock Neo4j result that supports both async iteration and .single()."""

    def __init__(
        self,
        records: list[dict[str, Any]] | None = None,
        single: dict[str, Any] | None = None,
    ) -> None:
        self._records = records or []
        self._single = single

    def __aiter__(self) -> _AsyncIter:
        return _AsyncIter(self._records)

    async def single(self) -> dict[str, Any] | None:
        return self._single


def _make_driver_with_side_effects(results: list[_MockResult]) -> MagicMock:
    """Build a driver whose session().run() returns different results on each call."""
    results_iter = iter(results)

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    async def _run_side_effect(*_args: Any, **_kwargs: Any) -> _MockResult:
        return next(results_iter)

    mock_session.run = AsyncMock(side_effect=_run_side_effect)

    driver = MagicMock()
    driver.session = MagicMock(return_value=mock_session)
    return driver


def _make_driver(records: list[dict[str, Any]] | None = None) -> MagicMock:
    """Build a minimal mock AsyncResilientNeo4jDriver."""
    mock_result = _MockResult(records=records or [])
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.run = AsyncMock(return_value=mock_result)

    driver = MagicMock()
    driver.session = MagicMock(return_value=mock_session)
    return driver


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
        target: dict[str, list[Any]] = {"genres": [], "styles": [], "labels": [], "collaborators": []}
        candidates = [self._make_candidate()]
        results = compute_similar_artists(target, candidates, limit=10)
        assert results == []

    def test_empty_candidates(self) -> None:
        target = {"genres": [{"name": "Rock", "count": 10}], "styles": [], "labels": [], "collaborators": []}
        results = compute_similar_artists(target, [], limit=10)
        assert results == []

    def test_null_artist_name_excluded(self) -> None:
        """Candidates with None artist_name are excluded to prevent validation errors.

        Regression test: some Artist nodes in Neo4j have NULL names, which caused
        pydantic ValidationError in SimilarArtist(artist_name=None). The Cypher
        query now filters these out, but compute_similar_artists also skips them
        as a defense-in-depth measure.
        """
        target = {
            "genres": [{"name": "Rock", "count": 100}],
            "styles": [],
            "labels": [],
            "collaborators": [],
        }
        candidates = [
            self._make_candidate(artist_id="good", artist_name="Valid Artist"),
            {
                "artist_id": "bad",
                "artist_name": None,
                "release_count": 10,
                "genres": [{"name": "Rock", "count": 10}],
                "styles": [],
                "labels": [],
                "collaborators": [],
            },
        ]
        results = compute_similar_artists(target, candidates, limit=10)
        artist_ids = [r["artist_id"] for r in results]
        assert "good" in artist_ids
        assert "bad" not in artist_ids

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


# ---------------------------------------------------------------------------
# _batch_artist_profiles
# ---------------------------------------------------------------------------


class TestBatchArtistProfiles:
    """Tests for batch profile fetching (replaces N+1 pattern)."""

    @pytest.mark.asyncio
    async def test_returns_profiles_for_all_candidates(self) -> None:
        """Each candidate ID gets a profile dict with all 4 dimensions."""
        genre_rows = [{"artist_id": "a1", "items": [{"name": "Rock", "count": 10}]}]
        style_rows = [{"artist_id": "a1", "items": [{"name": "Punk", "count": 5}]}]
        label_rows = [{"artist_id": "a1", "items": [{"name": "Sub Pop", "count": 3}]}]
        collab_rows = [{"artist_id": "a1", "items": [{"name": "Dave", "count": 2}]}]

        driver = _make_driver_with_side_effects(
            [
                _MockResult(records=genre_rows),
                _MockResult(records=style_rows),
                _MockResult(records=label_rows),
                _MockResult(records=collab_rows),
            ]
        )

        profiles = await _batch_artist_profiles(driver, ["a1"])
        assert "a1" in profiles
        assert profiles["a1"]["genres"] == [{"name": "Rock", "count": 10}]
        assert profiles["a1"]["styles"] == [{"name": "Punk", "count": 5}]
        assert profiles["a1"]["labels"] == [{"name": "Sub Pop", "count": 3}]
        assert profiles["a1"]["collaborators"] == [{"name": "Dave", "count": 2}]

    @pytest.mark.asyncio
    async def test_multiple_candidates(self) -> None:
        """Profiles for multiple candidates are returned in a single batch."""
        genre_rows = [
            {"artist_id": "a1", "items": [{"name": "Rock", "count": 10}]},
            {"artist_id": "a2", "items": [{"name": "Jazz", "count": 20}]},
        ]
        style_rows = [
            {"artist_id": "a1", "items": [{"name": "Punk", "count": 5}]},
        ]
        # a2 has no styles — not in style_rows

        driver = _make_driver_with_side_effects(
            [
                _MockResult(records=genre_rows),
                _MockResult(records=style_rows),
                _MockResult(records=[]),
                _MockResult(records=[]),
            ]
        )

        profiles = await _batch_artist_profiles(driver, ["a1", "a2"])
        assert profiles["a1"]["genres"] == [{"name": "Rock", "count": 10}]
        assert profiles["a2"]["genres"] == [{"name": "Jazz", "count": 20}]
        assert profiles["a1"]["styles"] == [{"name": "Punk", "count": 5}]
        # a2 not in style_rows so defaults to empty
        assert profiles["a2"]["styles"] == []

    @pytest.mark.asyncio
    async def test_empty_candidates(self) -> None:
        """Empty candidate list returns empty profiles dict."""
        driver = _make_driver_with_side_effects(
            [
                _MockResult(records=[]),
                _MockResult(records=[]),
                _MockResult(records=[]),
                _MockResult(records=[]),
            ]
        )

        profiles = await _batch_artist_profiles(driver, [])
        assert profiles == {}

    @pytest.mark.asyncio
    async def test_missing_dimension_defaults_to_empty(self) -> None:
        """A candidate with no results in a dimension gets an empty list."""
        driver = _make_driver_with_side_effects(
            [
                _MockResult(records=[]),  # no genres
                _MockResult(records=[]),  # no styles
                _MockResult(records=[]),  # no labels
                _MockResult(records=[]),  # no collaborators
            ]
        )

        profiles = await _batch_artist_profiles(driver, ["a1"])
        assert profiles["a1"] == {"genres": [], "styles": [], "labels": [], "collaborators": []}

    @pytest.mark.asyncio
    async def test_unknown_artist_id_in_results_ignored(self) -> None:
        """Results for artist IDs not in candidate_ids are safely ignored."""
        genre_rows = [{"artist_id": "unknown", "items": [{"name": "X", "count": 1}]}]

        driver = _make_driver_with_side_effects(
            [
                _MockResult(records=genre_rows),
                _MockResult(records=[]),
                _MockResult(records=[]),
                _MockResult(records=[]),
            ]
        )

        profiles = await _batch_artist_profiles(driver, ["a1"])
        assert profiles["a1"]["genres"] == []


# ---------------------------------------------------------------------------
# get_candidate_artists
# ---------------------------------------------------------------------------


class TestGetCandidateArtists:
    """Tests for the candidate artist discovery and profile batching."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_candidates(self) -> None:
        """When the candidate query returns no results, return empty list."""
        driver = _make_driver(records=[])
        result = await get_candidate_artists(driver, "artist123")
        assert result == []

    @pytest.mark.asyncio
    async def test_candidates_merged_with_batch_profiles(self) -> None:
        """Candidates are enriched with profiles from batch queries."""
        candidate_rows = [
            {"artist_id": "c1", "artist_name": "Candidate One", "release_count": 50},
            {"artist_id": "c2", "artist_name": "Candidate Two", "release_count": 30},
        ]
        genre_rows = [
            {"artist_id": "c1", "items": [{"name": "Rock", "count": 40}]},
            {"artist_id": "c2", "items": [{"name": "Jazz", "count": 25}]},
        ]

        # First call: candidate query. Then 4 batch profile queries.
        driver = _make_driver_with_side_effects(
            [
                _MockResult(records=candidate_rows),
                _MockResult(records=genre_rows),
                _MockResult(records=[]),
                _MockResult(records=[]),
                _MockResult(records=[]),
            ]
        )

        result = await get_candidate_artists(driver, "target123")
        assert len(result) == 2
        assert result[0]["artist_id"] == "c1"
        assert result[0]["artist_name"] == "Candidate One"
        assert result[0]["release_count"] == 50
        assert result[0]["genres"] == [{"name": "Rock", "count": 40}]
        assert result[1]["genres"] == [{"name": "Jazz", "count": 25}]
        # Missing dimensions default to empty
        assert result[0]["styles"] == []
        assert result[0]["labels"] == []
        assert result[0]["collaborators"] == []

    @pytest.mark.asyncio
    async def test_single_candidate(self) -> None:
        """Works correctly with just one candidate."""
        candidate_rows = [
            {"artist_id": "c1", "artist_name": "Solo", "release_count": 10},
        ]

        driver = _make_driver_with_side_effects(
            [
                _MockResult(records=candidate_rows),
                _MockResult(records=[{"artist_id": "c1", "items": [{"name": "Electronic", "count": 8}]}]),
                _MockResult(records=[{"artist_id": "c1", "items": [{"name": "Trance", "count": 6}]}]),
                _MockResult(records=[]),
                _MockResult(records=[]),
            ]
        )

        result = await get_candidate_artists(driver, "target123")
        assert len(result) == 1
        assert result[0]["genres"] == [{"name": "Electronic", "count": 8}]
        assert result[0]["styles"] == [{"name": "Trance", "count": 6}]


# ---------------------------------------------------------------------------
# get_artist_identity
# ---------------------------------------------------------------------------


class TestGetArtistIdentity:
    """Tests for get_artist_identity (run_single wrapper)."""

    @pytest.mark.asyncio
    async def test_returns_artist_info(self) -> None:
        from api.queries.recommend_queries import get_artist_identity

        record = {"artist_id": "a1", "artist_name": "Miles Davis", "release_count": 200}
        mock_result = _MockResult(single=record)
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.run = AsyncMock(return_value=mock_result)
        driver = MagicMock()
        driver.session = MagicMock(return_value=mock_session)

        result = await get_artist_identity(driver, "a1")
        assert result is not None
        assert result["artist_name"] == "Miles Davis"

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown(self) -> None:
        from api.queries.recommend_queries import get_artist_identity

        mock_result = _MockResult(single=None)
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.run = AsyncMock(return_value=mock_result)
        driver = MagicMock()
        driver.session = MagicMock(return_value=mock_session)

        result = await get_artist_identity(driver, "unknown")
        assert result is None


# ---------------------------------------------------------------------------
# get_artist_profile
# ---------------------------------------------------------------------------


class TestGetArtistProfile:
    """Tests for get_artist_profile (fetches 4 dimension queries)."""

    @pytest.mark.asyncio
    async def test_returns_all_dimensions(self) -> None:
        from api.queries.recommend_queries import get_artist_profile

        genre_rows = [{"name": "Rock", "count": 50}]
        style_rows = [{"name": "Punk", "count": 30}]
        label_rows = [{"name": "Sub Pop", "count": 10}]
        collab_rows = [{"name": "Dave", "count": 5}]

        driver = _make_driver_with_side_effects(
            [
                _MockResult(records=genre_rows),
                _MockResult(records=style_rows),
                _MockResult(records=label_rows),
                _MockResult(records=collab_rows),
            ]
        )

        profile = await get_artist_profile(driver, "a1")
        assert profile["genres"] == genre_rows
        assert profile["styles"] == style_rows
        assert profile["labels"] == label_rows
        assert profile["collaborators"] == collab_rows


# ---------------------------------------------------------------------------
# _normalize_scores
# ---------------------------------------------------------------------------


class TestNormalizeScores:
    """Tests for _normalize_scores."""

    def test_normalizes_to_max(self) -> None:
        from api.queries.recommend_queries import _normalize_scores

        candidates = [{"score": 10}, {"score": 5}, {"score": 0}]
        result = _normalize_scores(candidates)
        assert result[0]["score"] == 1.0
        assert result[1]["score"] == 0.5
        assert result[2]["score"] == 0.0

    def test_empty_list(self) -> None:
        from api.queries.recommend_queries import _normalize_scores

        assert _normalize_scores([]) == []

    def test_all_zero_scores(self) -> None:
        from api.queries.recommend_queries import _normalize_scores

        candidates = [{"score": 0}, {"score": 0}]
        result = _normalize_scores(candidates)
        assert result[0]["score"] == 0
        assert result[1]["score"] == 0


# ---------------------------------------------------------------------------
# get_collector_counts
# ---------------------------------------------------------------------------


class TestGetCollectorCounts:
    """Tests for get_collector_counts."""

    @pytest.mark.asyncio
    async def test_returns_counts(self) -> None:
        from api.queries.recommend_queries import get_collector_counts

        records = [{"id": "r1", "collectors": 100}, {"id": "r2", "collectors": 5}]
        driver = _make_driver(records=records)
        result = await get_collector_counts(driver, ["r1", "r2"])
        assert result == {"r1": 100, "r2": 5}

    @pytest.mark.asyncio
    async def test_empty_release_ids(self) -> None:
        from api.queries.recommend_queries import get_collector_counts

        driver = _make_driver()
        result = await get_collector_counts(driver, [])
        assert result == {}


# ---------------------------------------------------------------------------
# get_label_affinity_candidates
# ---------------------------------------------------------------------------


class TestGetLabelAffinityCandidates:
    """Tests for get_label_affinity_candidates."""

    @pytest.mark.asyncio
    async def test_returns_candidates_with_source(self) -> None:
        from api.queries.recommend_queries import get_label_affinity_candidates

        records = [
            {"id": "r1", "title": "A", "artist": "X", "label": "Warp", "year": 2000, "genres": ["Electronic"], "score": 10},
        ]
        driver = _make_driver(records=records)
        result = await get_label_affinity_candidates(driver, "user1", limit=10)
        assert len(result) == 1
        assert result[0]["source"].startswith("label:")
        assert "Warp" in result[0]["source"]

    @pytest.mark.asyncio
    async def test_empty_result(self) -> None:
        from api.queries.recommend_queries import get_label_affinity_candidates

        driver = _make_driver(records=[])
        result = await get_label_affinity_candidates(driver, "user1")
        assert result == []


# ---------------------------------------------------------------------------
# get_blindspot_candidates
# ---------------------------------------------------------------------------


class TestGetBlindspotCandidates:
    """Tests for get_blindspot_candidates."""

    @pytest.mark.asyncio
    async def test_returns_candidates_with_source(self) -> None:
        from api.queries.recommend_queries import get_blindspot_candidates

        records = [
            {"id": "r1", "title": "A", "artist": "X", "label": "L", "year": 2000, "genres": ["Jazz"], "score": 3},
        ]
        driver = _make_driver(records=records)
        result = await get_blindspot_candidates(driver, "user1", limit=10)
        assert len(result) == 1
        assert "blind_spot" in result[0]["source"]
        assert "Jazz" in result[0]["source"]

    @pytest.mark.asyncio
    async def test_empty_genres_in_result(self) -> None:
        from api.queries.recommend_queries import get_blindspot_candidates

        records = [
            {"id": "r1", "title": "A", "artist": "X", "label": "L", "year": 2000, "genres": [], "score": 1},
        ]
        driver = _make_driver(records=records)
        result = await get_blindspot_candidates(driver, "user1")
        assert "unknown" in result[0]["source"]


# ---------------------------------------------------------------------------
# get_explore_traversal
# ---------------------------------------------------------------------------


class TestGetExploreTraversal:
    """Tests for get_explore_traversal."""

    @pytest.mark.asyncio
    async def test_traversal_returns_results(self) -> None:
        from api.queries.recommend_queries import get_explore_traversal

        records = [
            {"id": "a2", "name": "Related Artist", "type": "artist", "path_names": ["Start", "Related Artist"], "rel_types": ["BY"], "dist": 1},
        ]
        driver = _make_driver(records=records)
        result = await get_explore_traversal(driver, "artist", "a1", hops=2)
        assert len(result) == 1
        assert result[0]["name"] == "Related Artist"

    @pytest.mark.asyncio
    async def test_genre_entity_type(self) -> None:
        from api.queries.recommend_queries import get_explore_traversal

        driver = _make_driver(records=[])
        await get_explore_traversal(driver, "genre", "Rock")
        call_args = driver.session.return_value.__aenter__.return_value.run.call_args
        cypher = call_args[0][0]
        assert "Genre" in cypher
        assert "name:" in cypher

    @pytest.mark.asyncio
    async def test_hops_clamped_low(self) -> None:
        from api.queries.recommend_queries import get_explore_traversal

        driver = _make_driver(records=[])
        await get_explore_traversal(driver, "artist", "a1", hops=0)
        call_args = driver.session.return_value.__aenter__.return_value.run.call_args
        cypher = call_args[0][0]
        assert "*1..2" in cypher

    @pytest.mark.asyncio
    async def test_hops_clamped_high(self) -> None:
        from api.queries.recommend_queries import get_explore_traversal

        driver = _make_driver(records=[])
        await get_explore_traversal(driver, "artist", "a1", hops=10)
        call_args = driver.session.return_value.__aenter__.return_value.run.call_args
        cypher = call_args[0][0]
        assert "*1..2" in cypher


# ---------------------------------------------------------------------------
# score_discoveries
# ---------------------------------------------------------------------------


class TestScoreDiscoveries:
    """Tests for score_discoveries."""

    def test_scores_genre_blind_spot(self) -> None:
        from api.queries.recommend_queries import score_discoveries

        discoveries = [{"id": "g1", "name": "Jazz", "type": "genre", "path_names": ["Start", "Jazz"], "rel_types": ["IS"], "dist": 1}]
        result = score_discoveries(discoveries, {}, {"Jazz"}, limit=10)
        assert len(result) == 1
        assert result[0]["reason"] == "blind_spot_boost"
        assert result[0]["score"] > 0

    def test_scores_genre_from_user_vector(self) -> None:
        from api.queries.recommend_queries import score_discoveries

        discoveries = [{"id": "g1", "name": "Rock", "type": "genre", "path_names": ["Start", "Rock"], "rel_types": ["IS"], "dist": 1}]
        result = score_discoveries(discoveries, {"Rock": 0.8}, set(), limit=10)
        assert result[0]["score"] == 0.8
        assert result[0]["reason"] == "graph_proximity"

    def test_scores_artist_by_distance(self) -> None:
        from api.queries.recommend_queries import score_discoveries

        discoveries = [{"id": "a1", "name": "Artist X", "type": "artist", "path_names": ["Start", "Artist X"], "rel_types": ["BY"], "dist": 2}]
        result = score_discoveries(discoveries, {}, set(), limit=10)
        assert result[0]["score"] == 0.5

    def test_scores_style_blind_spot(self) -> None:
        from api.queries.recommend_queries import score_discoveries

        discoveries = [{"id": "s1", "name": "Bossa Nova", "type": "style", "path_names": ["Start", "Bossa Nova"], "rel_types": ["IS"], "dist": 1}]
        result = score_discoveries(discoveries, {}, {"Bossa Nova"}, limit=10)
        assert result[0]["reason"] == "blind_spot_boost"

    def test_respects_limit(self) -> None:
        from api.queries.recommend_queries import score_discoveries

        discoveries = [{"id": f"a{i}", "name": f"Artist {i}", "type": "artist", "path_names": [], "rel_types": [], "dist": 1} for i in range(20)]
        result = score_discoveries(discoveries, {}, set(), limit=5)
        assert len(result) == 5

    def test_unknown_genre_scores_zero(self) -> None:
        from api.queries.recommend_queries import score_discoveries

        discoveries = [{"id": "g1", "name": "Unknown", "type": "genre", "path_names": [], "rel_types": [], "dist": 1}]
        result = score_discoveries(discoveries, {"Rock": 0.8}, set(), limit=10)
        assert result[0]["score"] == 0.0
