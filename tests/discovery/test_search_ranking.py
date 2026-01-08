"""Tests for SearchRanker class."""

from discovery.search_ranking import RankingSignal, RankingStrategy, SearchRanker


class TestSearchRankerInit:
    """Test SearchRanker initialization."""

    def test_initialization(self) -> None:
        """Test ranker initializes with correct defaults."""
        ranker = SearchRanker()

        assert ranker.signal_weights[RankingSignal.RELEVANCE] == 0.5
        assert ranker.signal_weights[RankingSignal.POPULARITY] == 0.2
        assert ranker.popularity_cache == {}
        assert ranker.user_profiles == {}


class TestRankResults:
    """Test main rank_results method."""

    def test_rank_empty_results(self) -> None:
        """Test ranking empty results."""
        ranker = SearchRanker()

        result = ranker.rank_results([], "test query")

        assert result == []

    def test_rank_with_linear_strategy(self) -> None:
        """Test ranking with linear strategy."""
        ranker = SearchRanker()

        results = [
            {"name": "Artist A", "similarity_score": 0.9},
            {"name": "Artist B", "similarity_score": 0.7},
        ]

        ranked = ranker.rank_results(results, "test", strategy=RankingStrategy.LINEAR)

        assert len(ranked) == 2
        assert all("ranking_score" in r for r in ranked)
        assert all("ranking_signals" in r for r in ranked)
        # Higher score should be first
        assert ranked[0]["name"] == "Artist A"

    def test_rank_with_multiplicative_strategy(self) -> None:
        """Test ranking with multiplicative strategy."""
        ranker = SearchRanker()

        results = [{"name": "Artist A", "similarity_score": 0.8}]

        ranked = ranker.rank_results(
            results,
            "test",
            strategy=RankingStrategy.MULTIPLICATIVE,
        )

        assert len(ranked) == 1
        assert "ranking_score" in ranked[0]

    def test_rank_with_signal_overrides(self) -> None:
        """Test ranking with custom signal weights."""
        ranker = SearchRanker()

        results = [{"name": "Artist A", "similarity_score": 0.8}]

        custom_weights = {RankingSignal.RELEVANCE: 0.8, RankingSignal.POPULARITY: 0.2}

        ranked = ranker.rank_results(
            results,
            "test",
            signal_overrides=custom_weights,
        )

        assert len(ranked) == 1


class TestCalculateSignals:
    """Test signal calculation."""

    def test_calculate_all_signals(self) -> None:
        """Test calculating all ranking signals."""
        ranker = SearchRanker()

        result = {
            "name": "Test Artist",
            "similarity_score": 0.9,
            "num_releases": 100,
            "year": 2020,
        }

        signals = ranker._calculate_signals(result, "query", user_id=None)

        assert RankingSignal.RELEVANCE in signals
        assert RankingSignal.POPULARITY in signals
        assert RankingSignal.RECENCY in signals
        assert RankingSignal.QUALITY in signals
        assert RankingSignal.PERSONALIZATION in signals
        assert RankingSignal.DIVERSITY in signals

    def test_calculate_signals_with_user(self) -> None:
        """Test signal calculation with user ID."""
        ranker = SearchRanker()
        ranker.set_user_profile(
            "user1",
            {"preferred_genres": ["Rock", "Jazz"]},
        )

        result = {"name": "Artist", "genres": ["Rock"], "similarity_score": 0.8}

        signals = ranker._calculate_signals(result, "query", user_id="user1")

        # Should have non-zero personalization score
        assert signals[RankingSignal.PERSONALIZATION] > 0.0


class TestRelevanceScore:
    """Test relevance score extraction."""

    def test_get_relevance_from_similarity_score(self) -> None:
        """Test extracting relevance from similarity_score field."""
        ranker = SearchRanker()

        result = {"similarity_score": 0.85}
        score = ranker._get_relevance_score(result)

        assert score == 0.85

    def test_get_relevance_from_rank(self) -> None:
        """Test extracting relevance from rank field."""
        ranker = SearchRanker()

        result = {"rank": 0.75}
        score = ranker._get_relevance_score(result)

        assert score == 0.75

    def test_get_relevance_default(self) -> None:
        """Test default relevance score."""
        ranker = SearchRanker()

        result = {"name": "Artist"}
        score = ranker._get_relevance_score(result)

        assert score == 0.5


class TestPopularityScore:
    """Test popularity score calculation."""

    def test_get_popularity_from_num_releases(self) -> None:
        """Test popularity from num_releases."""
        ranker = SearchRanker()

        result = {"id": "1", "num_releases": 100}
        score = ranker._get_popularity_score(result)

        assert 0.0 <= score <= 1.0
        # Should be cached
        assert "1" in ranker.popularity_cache

    def test_get_popularity_cached(self) -> None:
        """Test popularity retrieval from cache."""
        ranker = SearchRanker()
        ranker.popularity_cache["artist_1"] = 0.8

        result = {"id": "artist_1"}
        score = ranker._get_popularity_score(result)

        assert score == 0.8

    def test_get_popularity_default(self) -> None:
        """Test default popularity score."""
        ranker = SearchRanker()

        result = {"name": "Artist"}
        score = ranker._get_popularity_score(result)

        assert score == 0.5


class TestRecencyScore:
    """Test recency score calculation."""

    def test_get_recency_from_year(self) -> None:
        """Test recency from release year."""
        ranker = SearchRanker()

        result = {"year": 2020}
        score = ranker._get_recency_score(result)

        assert 0.0 <= score <= 1.0
        # More recent year should have higher score
        assert score > 0.5

    def test_get_recency_from_latest_year(self) -> None:
        """Test recency from latest_year field."""
        ranker = SearchRanker()

        result = {"latest_year": 2015}
        score = ranker._get_recency_score(result)

        assert 0.0 <= score <= 1.0

    def test_get_recency_default(self) -> None:
        """Test default recency score."""
        ranker = SearchRanker()

        result = {"name": "Artist"}
        score = ranker._get_recency_score(result)

        assert score == 0.5


class TestQualityScore:
    """Test quality score calculation."""

    def test_get_quality_from_quality_score(self) -> None:
        """Test quality from quality_score field."""
        ranker = SearchRanker()

        result = {"quality_score": 0.85}
        score = ranker._get_quality_score(result)

        assert score == 0.85

    def test_get_quality_from_avg_rating(self) -> None:
        """Test quality from avg_rating field."""
        ranker = SearchRanker()

        result = {"avg_rating": 4.0}  # Rating 1-5
        score = ranker._get_quality_score(result)

        assert 0.0 <= score <= 1.0

    def test_get_quality_default(self) -> None:
        """Test default quality score."""
        ranker = SearchRanker()

        result = {"name": "Artist"}
        score = ranker._get_quality_score(result)

        assert score == 0.5


class TestPersonalizationScore:
    """Test personalization score calculation."""

    def test_get_personalization_no_profile(self) -> None:
        """Test personalization with no user profile."""
        ranker = SearchRanker()

        result = {"genres": ["Rock"]}
        score = ranker._get_personalization_score(result, "unknown_user")

        assert score == 0.0

    def test_get_personalization_genre_match(self) -> None:
        """Test personalization with genre match."""
        ranker = SearchRanker()
        ranker.set_user_profile("user1", {"preferred_genres": ["Rock", "Jazz"]})

        result = {"genres": ["Rock"]}
        score = ranker._get_personalization_score(result, "user1")

        assert score > 0.0

    def test_get_personalization_multiple_matches(self) -> None:
        """Test personalization with multiple preference matches."""
        ranker = SearchRanker()
        ranker.set_user_profile(
            "user1",
            {
                "preferred_genres": ["Rock"],
                "preferred_styles": ["Alternative"],
                "preferred_labels": ["Label A"],
            },
        )

        result = {
            "genres": ["Rock"],
            "styles": ["Alternative"],
            "labels": ["Label A"],
        }

        score = ranker._get_personalization_score(result, "user1")

        assert score > 0.0


class TestRankingStrategies:
    """Test different ranking strategies."""

    def test_linear_ranking(self) -> None:
        """Test linear ranking strategy."""
        ranker = SearchRanker()

        signals = {
            RankingSignal.RELEVANCE: 0.8,
            RankingSignal.POPULARITY: 0.6,
        }
        weights = {
            RankingSignal.RELEVANCE: 0.7,
            RankingSignal.POPULARITY: 0.3,
        }

        score = ranker._linear_ranking(signals, weights)

        # Should be weighted sum
        expected = 0.8 * 0.7 + 0.6 * 0.3
        assert abs(score - expected) < 0.01

    def test_multiplicative_ranking(self) -> None:
        """Test multiplicative ranking strategy."""
        ranker = SearchRanker()

        signals = {
            RankingSignal.RELEVANCE: 0.8,
            RankingSignal.POPULARITY: 0.9,
        }
        weights = {
            RankingSignal.RELEVANCE: 0.5,
            RankingSignal.POPULARITY: 0.5,
        }

        score = ranker._multiplicative_ranking(signals, weights)

        assert 0.0 <= score <= 1.0

    def test_learning_to_rank(self) -> None:
        """Test learning-to-rank strategy."""
        ranker = SearchRanker()

        signals = dict.fromkeys(RankingSignal, 0.5)
        weights = {s: 1.0 / len(RankingSignal) for s in RankingSignal}

        score = ranker._learning_to_rank(signals, weights)

        assert 0.0 <= score <= 1.0

    def test_hybrid_ranking(self) -> None:
        """Test hybrid ranking strategy."""
        ranker = SearchRanker()

        signals = dict.fromkeys(RankingSignal, 0.6)
        weights = {s: 1.0 / len(RankingSignal) for s in RankingSignal}

        score = ranker._hybrid_ranking(signals, weights)

        assert 0.0 <= score <= 1.0


class TestConfigurationMethods:
    """Test configuration methods."""

    def test_set_signal_weights(self) -> None:
        """Test updating signal weights."""
        ranker = SearchRanker()

        new_weights = {RankingSignal.RELEVANCE: 0.8, RankingSignal.POPULARITY: 0.2}
        ranker.set_signal_weights(new_weights)

        assert ranker.signal_weights[RankingSignal.RELEVANCE] == 0.8
        assert ranker.signal_weights[RankingSignal.POPULARITY] == 0.2

    def test_set_user_profile(self) -> None:
        """Test setting user profile."""
        ranker = SearchRanker()

        profile = {"preferred_genres": ["Rock"]}
        ranker.set_user_profile("user1", profile)

        assert "user1" in ranker.user_profiles
        assert ranker.user_profiles["user1"] == profile

    def test_update_popularity_cache(self) -> None:
        """Test bulk updating popularity cache."""
        ranker = SearchRanker()

        scores = {"artist1": 0.9, "artist2": 0.7}
        ranker.update_popularity_cache(scores)

        assert ranker.popularity_cache["artist1"] == 0.9
        assert ranker.popularity_cache["artist2"] == 0.7


class TestDiversityReranking:
    """Test diversity-based reranking."""

    def test_diversity_reranking_disabled(self) -> None:
        """Test diversity reranking when factor is 0."""
        ranker = SearchRanker()

        results = [
            {"name": "A", "ranking_score": 0.9},
            {"name": "B", "ranking_score": 0.8},
        ]

        reranked = ranker.apply_diversity_reranking(results, diversity_factor=0.0)

        assert reranked == results

    def test_diversity_reranking_empty(self) -> None:
        """Test diversity reranking with empty results."""
        ranker = SearchRanker()

        reranked = ranker.apply_diversity_reranking([], diversity_factor=0.3)

        assert reranked == []

    def test_diversity_reranking_enabled(self) -> None:
        """Test diversity reranking with non-zero factor."""
        ranker = SearchRanker()

        results = [
            {"name": "A", "ranking_score": 0.9, "genres": ["Rock"]},
            {"name": "B", "ranking_score": 0.8, "genres": ["Jazz"]},
            {"name": "C", "ranking_score": 0.7, "genres": ["Rock"]},
        ]

        reranked = ranker.apply_diversity_reranking(results, diversity_factor=0.3)

        assert len(reranked) == 3
        # All results should be present
        names = {r["name"] for r in reranked}
        assert names == {"A", "B", "C"}


class TestCalculateDiversity:
    """Test diversity calculation."""

    def test_calculate_diversity_empty_selected(self) -> None:
        """Test diversity when no results selected yet."""
        ranker = SearchRanker()

        candidate = {"name": "A", "genres": ["Rock"]}
        diversity = ranker._calculate_diversity(candidate, [])

        assert diversity == 1.0

    def test_calculate_diversity_with_overlap(self) -> None:
        """Test diversity with genre overlap."""
        ranker = SearchRanker()

        candidate = {"name": "A", "genres": ["Rock", "Jazz"]}
        selected = [{"name": "B", "genres": ["Rock"]}]

        diversity = ranker._calculate_diversity(candidate, selected)

        assert 0.0 <= diversity <= 1.0
