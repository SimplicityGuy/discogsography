"""Search result ranking optimization.

This module provides advanced ranking algorithms that combine multiple signals
(relevance, popularity, recency, user preferences) to optimize search results.
"""

from enum import StrEnum
from typing import Any

import numpy as np
import structlog


logger = structlog.get_logger(__name__)


class RankingSignal(StrEnum):
    """Ranking signals that can be used."""

    RELEVANCE = "relevance"  # Text/semantic relevance
    POPULARITY = "popularity"  # How popular the item is
    RECENCY = "recency"  # How recent the item is
    QUALITY = "quality"  # Quality score (if available)
    PERSONALIZATION = "personalization"  # User-specific preferences
    DIVERSITY = "diversity"  # Promotes diverse results


class RankingStrategy(StrEnum):
    """Ranking strategies."""

    LINEAR = "linear"  # Weighted sum of signals
    MULTIPLICATIVE = "multiplicative"  # Product of signals
    LEARNING_TO_RANK = "ltr"  # Machine learning based
    HYBRID = "hybrid"  # Combination of strategies


class SearchRanker:
    """Advanced search result ranker."""

    def __init__(self) -> None:
        """Initialize search ranker."""
        # Default weights for ranking signals
        self.signal_weights = {
            RankingSignal.RELEVANCE: 0.5,
            RankingSignal.POPULARITY: 0.2,
            RankingSignal.RECENCY: 0.1,
            RankingSignal.QUALITY: 0.1,
            RankingSignal.PERSONALIZATION: 0.05,
            RankingSignal.DIVERSITY: 0.05,
        }

        # Cache for popularity scores
        self.popularity_cache: dict[str, float] = {}

        # User preference profiles
        self.user_profiles: dict[str, dict[str, Any]] = {}

    def rank_results(
        self,
        results: list[dict[str, Any]],
        query: str,
        strategy: RankingStrategy = RankingStrategy.LINEAR,
        user_id: str | None = None,
        signal_overrides: dict[RankingSignal, float] | None = None,
    ) -> list[dict[str, Any]]:
        """Rank search results using multiple signals.

        Args:
            results: List of search results to rank
            query: Original search query
            strategy: Ranking strategy to use
            user_id: Optional user ID for personalization
            signal_overrides: Optional signal weight overrides

        Returns:
            Reranked results with scores
        """
        if not results:
            return []

        # Use custom weights if provided
        weights = self.signal_weights.copy()
        if signal_overrides:
            weights.update(signal_overrides)

        # Calculate signals for each result
        ranked_results = []

        for result in results:
            signals = self._calculate_signals(result, query, user_id)

            # Calculate final score based on strategy
            if strategy == RankingStrategy.LINEAR:
                final_score = self._linear_ranking(signals, weights)
            elif strategy == RankingStrategy.MULTIPLICATIVE:
                final_score = self._multiplicative_ranking(signals, weights)
            elif strategy == RankingStrategy.LEARNING_TO_RANK:
                final_score = self._learning_to_rank(signals, weights)
            else:  # HYBRID
                final_score = self._hybrid_ranking(signals, weights)

            # Add ranking information to result
            result["ranking_score"] = final_score
            result["ranking_signals"] = signals
            ranked_results.append(result)

        # Sort by final score
        ranked_results.sort(key=lambda x: x["ranking_score"], reverse=True)

        logger.info(
            "📊 Ranked search results",
            query=query,
            strategy=strategy,
            results=len(ranked_results),
        )

        return ranked_results

    def _calculate_signals(
        self,
        result: dict[str, Any],
        query: str,  # noqa: ARG002
        user_id: str | None,
    ) -> dict[RankingSignal, float]:
        """Calculate all ranking signals for a result.

        Args:
            result: Search result
            query: Search query (reserved for future relevance scoring)
            user_id: Optional user ID

        Returns:
            Dictionary of signal values
        """
        signals: dict[RankingSignal, float] = {}

        # Relevance signal (from text/semantic search)
        signals[RankingSignal.RELEVANCE] = self._get_relevance_score(result)

        # Popularity signal
        signals[RankingSignal.POPULARITY] = self._get_popularity_score(result)

        # Recency signal
        signals[RankingSignal.RECENCY] = self._get_recency_score(result)

        # Quality signal
        signals[RankingSignal.QUALITY] = self._get_quality_score(result)

        # Personalization signal
        if user_id:
            signals[RankingSignal.PERSONALIZATION] = self._get_personalization_score(result, user_id)
        else:
            signals[RankingSignal.PERSONALIZATION] = 0.0

        # Diversity signal (calculated relative to other results)
        signals[RankingSignal.DIVERSITY] = 0.5  # Placeholder, would be calculated across all results

        return signals

    def _get_relevance_score(self, result: dict[str, Any]) -> float:
        """Extract relevance score from result.

        Args:
            result: Search result

        Returns:
            Relevance score (0.0 to 1.0)
        """
        # Check various possible score fields
        score_fields = ["rank", "similarity_score", "score", "relevance"]

        for field in score_fields:
            if field in result:
                score = float(result[field])
                # Normalize to [0, 1] if needed
                return min(max(score, 0.0), 1.0)

        return 0.5  # Default neutral score

    def _get_popularity_score(self, result: dict[str, Any]) -> float:
        """Calculate popularity score for result.

        Args:
            result: Search result

        Returns:
            Popularity score (0.0 to 1.0)
        """
        # Check cache
        item_id = result.get("id") or result.get("name")
        if item_id and item_id in self.popularity_cache:
            return self.popularity_cache[item_id]

        # Calculate based on available metrics
        popularity = 0.5  # Default

        # Could be based on:
        # - Number of releases (for artists)
        # - Number of ratings/reviews
        # - Number of collections
        # - Play counts, etc.

        if "num_releases" in result:
            # Normalize using log scale
            popularity = min(np.log1p(result["num_releases"]) / 10, 1.0)

        if item_id:
            self.popularity_cache[item_id] = popularity

        return popularity

    def _get_recency_score(self, result: dict[str, Any]) -> float:
        """Calculate recency score for result.

        Args:
            result: Search result

        Returns:
            Recency score (0.0 to 1.0)
        """
        # For releases/masters, use release year
        if result.get("year"):
            year = result["year"]
            # More recent = higher score
            # Normalize from 1950-2024 to [0, 1]
            current_year = 2024
            min_year = 1950

            if year >= min_year:
                recency = (float(year) - min_year) / (current_year - min_year)
                return min(max(recency, 0.0), 1.0)

        # For artists, could use first/last release year
        if result.get("latest_year"):
            year = result["latest_year"]
            current_year = 2024
            min_year = 1950

            if year >= min_year:
                recency = (float(year) - min_year) / (current_year - min_year)
                return min(max(recency, 0.0), 1.0)

        return 0.5  # Neutral if no date information

    def _get_quality_score(self, result: dict[str, Any]) -> float:
        """Calculate quality score for result.

        Args:
            result: Search result

        Returns:
            Quality score (0.0 to 1.0)
        """
        # Could be based on:
        # - Average rating
        # - Data completeness
        # - Number of verified information
        # - Community ratings

        if "quality_score" in result:
            return min(max(float(result["quality_score"]), 0.0), 1.0)

        if "avg_rating" in result:
            # Assuming ratings are 1-5
            return min(max((float(result["avg_rating"]) - 1) / 4, 0.0), 1.0)

        return 0.5  # Neutral default

    def _get_personalization_score(self, result: dict[str, Any], user_id: str) -> float:
        """Calculate personalization score based on user preferences.

        Args:
            result: Search result
            user_id: User identifier

        Returns:
            Personalization score (0.0 to 1.0)
        """
        if user_id not in self.user_profiles:
            return 0.0

        user_profile = self.user_profiles[user_id]

        # Match result against user preferences
        score = 0.0
        matches = 0

        # Genre preferences
        if "preferred_genres" in user_profile and "genres" in result:
            result_genres = set(result.get("genres", []))
            preferred_genres = set(user_profile["preferred_genres"])
            if result_genres & preferred_genres:
                score += 1.0
                matches += 1

        # Style preferences
        if "preferred_styles" in user_profile and "styles" in result:
            result_styles = set(result.get("styles", []))
            preferred_styles = set(user_profile["preferred_styles"])
            if result_styles & preferred_styles:
                score += 1.0
                matches += 1

        # Label preferences
        if "preferred_labels" in user_profile and "labels" in result:
            result_labels = set(result.get("labels", []))
            preferred_labels = set(user_profile["preferred_labels"])
            if result_labels & preferred_labels:
                score += 1.0
                matches += 1

        if matches > 0:
            return min(score / matches, 1.0)

        return 0.0

    def _linear_ranking(
        self,
        signals: dict[RankingSignal, float],
        weights: dict[RankingSignal, float],
    ) -> float:
        """Linear combination of ranking signals.

        Args:
            signals: Signal values
            weights: Signal weights

        Returns:
            Final ranking score
        """
        score = 0.0

        for signal, value in signals.items():
            weight = weights.get(signal, 0.0)
            score += weight * value

        return score

    def _multiplicative_ranking(
        self,
        signals: dict[RankingSignal, float],
        weights: dict[RankingSignal, float],
    ) -> float:
        """Multiplicative combination of ranking signals.

        Args:
            signals: Signal values
            weights: Signal weights

        Returns:
            Final ranking score
        """
        score = 1.0

        for signal, value in signals.items():
            weight = weights.get(signal, 0.0)
            # Use weighted geometric mean
            score *= value**weight

        return score

    def _learning_to_rank(
        self,
        signals: dict[RankingSignal, float],
        weights: dict[RankingSignal, float],
    ) -> float:
        """Learning-to-rank scoring (simplified version).

        Args:
            signals: Signal values
            weights: Signal weights

        Returns:
            Final ranking score
        """
        # In a real LTR system, this would use a trained model
        # For now, use a non-linear combination

        # Create feature vector
        features = np.array([signals.get(s, 0.0) for s in RankingSignal])
        feature_weights = np.array([weights.get(s, 0.0) for s in RankingSignal])

        # Simple non-linear transformation
        transformed = np.tanh(features * 2)  # Squash to [-1, 1]
        score = float(np.dot(transformed, feature_weights))

        # Normalize to [0, 1]
        return (score + 1) / 2

    def _hybrid_ranking(
        self,
        signals: dict[RankingSignal, float],
        weights: dict[RankingSignal, float],
    ) -> float:
        """Hybrid ranking combining multiple strategies.

        Args:
            signals: Signal values
            weights: Signal weights

        Returns:
            Final ranking score
        """
        # Combine linear and multiplicative
        linear_score = self._linear_ranking(signals, weights)
        mult_score = self._multiplicative_ranking(signals, weights)
        ltr_score = self._learning_to_rank(signals, weights)

        # Weighted combination
        score = 0.5 * linear_score + 0.3 * mult_score + 0.2 * ltr_score

        return score

    def set_signal_weights(self, weights: dict[RankingSignal, float]) -> None:
        """Update signal weights.

        Args:
            weights: New signal weights
        """
        self.signal_weights.update(weights)
        logger.info("✅ Updated ranking weights", weights=self.signal_weights)

    def set_user_profile(self, user_id: str, profile: dict[str, Any]) -> None:
        """Set user preference profile.

        Args:
            user_id: User identifier
            profile: User preference profile
        """
        self.user_profiles[user_id] = profile
        logger.info("👤 Updated user profile", user_id=user_id)

    def update_popularity_cache(self, popularity_scores: dict[str, float]) -> None:
        """Bulk update popularity cache.

        Args:
            popularity_scores: Dictionary mapping item IDs to popularity scores
        """
        self.popularity_cache.update(popularity_scores)
        logger.info("📊 Updated popularity cache", items=len(popularity_scores))

    def apply_diversity_reranking(
        self,
        ranked_results: list[dict[str, Any]],
        diversity_factor: float = 0.3,
    ) -> list[dict[str, Any]]:
        """Apply diversity-based reranking to avoid redundant results.

        Args:
            ranked_results: Already ranked results
            diversity_factor: How much to prioritize diversity (0.0 to 1.0)

        Returns:
            Reranked results with diversity
        """
        if not ranked_results or diversity_factor == 0.0:
            return ranked_results

        diversified: list[dict[str, Any]] = []
        remaining = ranked_results.copy()

        while remaining:
            if not diversified:
                # Add highest scoring result first
                diversified.append(remaining.pop(0))
                continue

            # Score remaining results by combination of relevance and diversity
            best_idx = 0
            best_score = -1.0

            for idx, candidate in enumerate(remaining):
                # Original score
                relevance = candidate.get("ranking_score", 0.5)

                # Calculate diversity from already selected results
                diversity = self._calculate_diversity(candidate, diversified)

                # Combined score
                combined = (1 - diversity_factor) * relevance + diversity_factor * diversity

                if combined > best_score:
                    best_score = combined
                    best_idx = idx

            # Add best candidate
            diversified.append(remaining.pop(best_idx))

        logger.info(
            "✨ Applied diversity reranking",
            results=len(diversified),
            diversity_factor=diversity_factor,
        )

        return diversified

    def _calculate_diversity(
        self,
        candidate: dict[str, Any],
        selected: list[dict[str, Any]],
    ) -> float:
        """Calculate how diverse a candidate is from selected results.

        Args:
            candidate: Candidate result
            selected: Already selected results

        Returns:
            Diversity score (0.0 to 1.0)
        """
        if not selected:
            return 1.0

        # Calculate similarity to selected results
        similarities = []

        for result in selected:
            similarity = 0.0

            # Compare genres
            if "genres" in candidate and "genres" in result:
                cand_genres = set(candidate.get("genres", []))
                res_genres = set(result.get("genres", []))
                if cand_genres and res_genres:
                    overlap = len(cand_genres & res_genres) / len(cand_genres | res_genres)
                    similarity += overlap

            # Compare other attributes similarly...

            similarities.append(similarity)

        # Diversity is inverse of average similarity
        avg_similarity = float(np.mean(similarities)) if similarities else 0.0
        diversity = 1.0 - avg_similarity

        return float(max(0.0, min(diversity, 1.0)))
