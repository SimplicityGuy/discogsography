"""Hybrid recommendation system combining multiple algorithms.

This module implements hybrid recommendation strategies that combine
collaborative filtering, content-based filtering, and other methods
to provide more accurate and diverse recommendations.
"""

from collections import defaultdict
from enum import StrEnum
from typing import Any

import structlog

from discovery.collaborative_filtering import CollaborativeFilter
from discovery.content_based import ContentBasedFilter


logger = structlog.get_logger(__name__)


class HybridStrategy(StrEnum):
    """Hybrid recommendation combination strategies."""

    WEIGHTED = "weighted"  # Weighted average of scores
    RANK_FUSION = "rank_fusion"  # Reciprocal rank fusion
    CASCADE = "cascade"  # Sequential filtering
    MIXED = "mixed"  # Interleave results from different methods
    SWITCHING = "switching"  # Switch between methods based on context


class HybridRecommender:
    """Hybrid recommendation system combining multiple algorithms."""

    def __init__(
        self,
        collaborative_filter: CollaborativeFilter,
        content_based_filter: ContentBasedFilter,
    ) -> None:
        """Initialize hybrid recommender.

        Args:
            collaborative_filter: Collaborative filtering instance
            content_based_filter: Content-based filtering instance
        """
        self.collaborative = collaborative_filter
        self.content_based = content_based_filter

        # Default weights for different methods
        self.method_weights = {
            "collaborative_filtering": 0.5,
            "content_based": 0.4,
            "graph_based": 0.1,
        }

        # Diversity parameters
        self.diversity_weight = 0.2  # How much to penalize similar items
        self.min_diversity_threshold = 0.3  # Minimum similarity for diversity calculation

    async def get_recommendations(
        self,
        artist_name: str,
        limit: int = 10,
        strategy: HybridStrategy = HybridStrategy.WEIGHTED,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Get hybrid recommendations for an artist.

        Args:
            artist_name: Name of the artist to get recommendations for
            limit: Maximum number of recommendations to return
            strategy: Hybrid combination strategy to use
            **kwargs: Additional parameters for specific strategies

        Returns:
            List of recommended artists with scores and metadata
        """
        if strategy == HybridStrategy.WEIGHTED:
            return await self._weighted_recommendations(artist_name, limit, **kwargs)
        elif strategy == HybridStrategy.RANK_FUSION:
            return await self._rank_fusion_recommendations(artist_name, limit, **kwargs)
        elif strategy == HybridStrategy.CASCADE:
            return await self._cascade_recommendations(artist_name, limit, **kwargs)
        elif strategy == HybridStrategy.MIXED:
            return await self._mixed_recommendations(artist_name, limit, **kwargs)
        # SWITCHING
        return await self._switching_recommendations(artist_name, limit, **kwargs)

    async def _weighted_recommendations(
        self,
        artist_name: str,
        limit: int,
        weights: dict[str, float] | None = None,
        diversity_boost: bool = True,
    ) -> list[dict[str, Any]]:
        """Combine recommendations using weighted average of scores.

        Args:
            artist_name: Artist to get recommendations for
            limit: Number of recommendations
            weights: Custom weights for each method
            diversity_boost: Whether to apply diversity boosting

        Returns:
            List of recommendations with combined scores
        """
        # Use custom weights or defaults
        method_weights = weights if weights else self.method_weights

        # Get recommendations from each method
        collab_recs = await self.collaborative.get_recommendations(artist_name, limit=limit * 2)
        content_recs = await self.content_based.get_recommendations(artist_name, limit=limit * 2)

        # Normalize scores to [0, 1] range for each method
        collab_scores = self._normalize_scores(collab_recs)
        content_scores = self._normalize_scores(content_recs)

        # Combine scores with weights
        combined_scores: dict[str, float] = defaultdict(float)
        method_contributions: dict[str, dict[str, float]] = defaultdict(dict)

        for artist, score in collab_scores.items():
            weighted_score = score * method_weights.get("collaborative_filtering", 0.5)
            combined_scores[artist] += weighted_score
            method_contributions[artist]["collaborative"] = score

        for artist, score in content_scores.items():
            weighted_score = score * method_weights.get("content_based", 0.4)
            combined_scores[artist] += weighted_score
            method_contributions[artist]["content"] = score

        # Apply diversity boosting if enabled
        if diversity_boost:
            combined_scores = self._apply_diversity_boost(combined_scores, artist_name)

        # Sort by combined score and return top N
        sorted_artists = sorted(combined_scores.items(), key=lambda x: x[1], reverse=True)[:limit]

        recommendations = []
        for artist, score in sorted_artists:
            rec = {
                "artist_name": artist,
                "similarity_score": float(score),
                "method": "hybrid_weighted",
                "method_scores": method_contributions.get(artist, {}),
            }
            recommendations.append(rec)

        logger.info(
            "✅ Generated weighted hybrid recommendations",
            artist=artist_name,
            count=len(recommendations),
            strategy="weighted",
        )

        return recommendations

    async def _rank_fusion_recommendations(self, artist_name: str, limit: int, **kwargs: Any) -> list[dict[str, Any]]:
        """Combine recommendations using reciprocal rank fusion.

        Reciprocal Rank Fusion (RRF) combines rankings from different methods
        by summing reciprocal ranks. This is robust to different score scales.

        Args:
            artist_name: Artist to get recommendations for
            limit: Number of recommendations
            **kwargs: Additional parameters

        Returns:
            List of recommendations with RRF scores
        """
        k = kwargs.get("rrf_k", 60)  # RRF parameter (default 60)

        # Get recommendations from each method
        collab_recs = await self.collaborative.get_recommendations(artist_name, limit=limit * 2)
        content_recs = await self.content_based.get_recommendations(artist_name, limit=limit * 2)

        # Calculate RRF scores
        rrf_scores: dict[str, float] = defaultdict(float)

        for rank, rec in enumerate(collab_recs, start=1):
            artist = rec["artist_name"]
            rrf_scores[artist] += 1.0 / (k + rank)

        for rank, rec in enumerate(content_recs, start=1):
            artist = rec["artist_name"]
            rrf_scores[artist] += 1.0 / (k + rank)

        # Sort by RRF score
        sorted_artists = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)[:limit]

        recommendations = []
        for artist, score in sorted_artists:
            recommendations.append(
                {
                    "artist_name": artist,
                    "similarity_score": float(score),
                    "method": "hybrid_rank_fusion",
                }
            )

        logger.info(
            "✅ Generated rank fusion recommendations",
            artist=artist_name,
            count=len(recommendations),
            strategy="rank_fusion",
        )

        return recommendations

    async def _cascade_recommendations(self, artist_name: str, limit: int, **kwargs: Any) -> list[dict[str, Any]]:
        """Use cascade approach: filter with one method, rank with another.

        Args:
            artist_name: Artist to get recommendations for
            limit: Number of recommendations
            **kwargs: Additional parameters

        Returns:
            List of recommendations
        """
        filter_method = kwargs.get("filter_method", "collaborative")
        rank_method = kwargs.get("rank_method", "content")

        # Get candidates from filter method
        if filter_method == "collaborative":
            candidates = await self.collaborative.get_recommendations(artist_name, limit=limit * 3)
        else:
            candidates = await self.content_based.get_recommendations(artist_name, limit=limit * 3)

        # Re-rank candidates with ranking method
        candidate_names = [rec["artist_name"] for rec in candidates]
        reranked_scores: dict[str, float] = {}

        for candidate_name in candidate_names:
            if rank_method == "collaborative":
                score = self.collaborative.get_similarity_score(artist_name, candidate_name)
            else:
                score = self.content_based.get_similarity_score(artist_name, candidate_name)

            reranked_scores[candidate_name] = score

        # Sort by reranked scores
        sorted_artists = sorted(reranked_scores.items(), key=lambda x: x[1], reverse=True)[:limit]

        recommendations = []
        for artist, score in sorted_artists:
            recommendations.append(
                {
                    "artist_name": artist,
                    "similarity_score": float(score),
                    "method": "hybrid_cascade",
                    "filter_method": filter_method,
                    "rank_method": rank_method,
                }
            )

        logger.info(
            "✅ Generated cascade recommendations",
            artist=artist_name,
            count=len(recommendations),
            strategy="cascade",
        )

        return recommendations

    async def _mixed_recommendations(self, artist_name: str, limit: int, **kwargs: Any) -> list[dict[str, Any]]:
        """Interleave results from different methods for diversity.

        Args:
            artist_name: Artist to get recommendations for
            limit: Number of recommendations
            **kwargs: Additional parameters

        Returns:
            List of recommendations
        """
        ratio = kwargs.get("ratio", [0.5, 0.5])  # [collaborative, content]

        # Get recommendations from each method
        collab_limit = int(limit * ratio[0]) + 1
        content_limit = int(limit * ratio[1]) + 1

        collab_recs = await self.collaborative.get_recommendations(artist_name, limit=collab_limit)
        content_recs = await self.content_based.get_recommendations(artist_name, limit=content_limit)

        # Interleave results
        recommendations: list[dict[str, Any]] = []
        seen: set[str] = set()

        collab_idx, content_idx = 0, 0

        while len(recommendations) < limit and (collab_idx < len(collab_recs) or content_idx < len(content_recs)):
            # Add from collaborative filtering
            if collab_idx < len(collab_recs):
                rec = collab_recs[collab_idx]
                if rec["artist_name"] not in seen:
                    rec["method"] = "hybrid_mixed_collaborative"
                    recommendations.append(rec)
                    seen.add(rec["artist_name"])
                collab_idx += 1

            if len(recommendations) >= limit:
                break

            # Add from content-based
            if content_idx < len(content_recs):
                rec = content_recs[content_idx]
                if rec["artist_name"] not in seen:
                    rec["method"] = "hybrid_mixed_content"
                    recommendations.append(rec)
                    seen.add(rec["artist_name"])
                content_idx += 1

        logger.info(
            "✅ Generated mixed recommendations",
            artist=artist_name,
            count=len(recommendations),
            strategy="mixed",
        )

        return recommendations[:limit]

    async def _switching_recommendations(
        self,
        artist_name: str,
        limit: int,
        **kwargs: Any,  # noqa: ARG002
    ) -> list[dict[str, Any]]:
        """Switch between methods based on context and data availability.

        Args:
            artist_name: Artist to get recommendations for
            limit: Number of recommendations
            **kwargs: Additional parameters (reserved for future use)

        Returns:
            List of recommendations
        """
        # Check data availability for the artist
        has_collab_data = artist_name in self.collaborative.artist_to_index
        has_content_data = artist_name in self.content_based.artist_to_index

        # Decide which method to use
        if has_collab_data and has_content_data:
            # Use weighted combination when both available
            return await self._weighted_recommendations(artist_name, limit)
        elif has_collab_data:
            # Use collaborative filtering only
            logger.info("📊 Using collaborative filtering only", artist=artist_name)
            recs = await self.collaborative.get_recommendations(artist_name, limit)
            for rec in recs:
                rec["method"] = "hybrid_switching_collaborative"
            return recs
        elif has_content_data:
            # Use content-based only
            logger.info("📊 Using content-based filtering only", artist=artist_name)
            recs = await self.content_based.get_recommendations(artist_name, limit)
            for rec in recs:
                rec["method"] = "hybrid_switching_content"
            return recs
        else:
            logger.warning("⚠️ No data available for artist", artist=artist_name)
            return []

    def _normalize_scores(self, recommendations: list[dict[str, Any]]) -> dict[str, float]:
        """Normalize recommendation scores to [0, 1] range.

        Args:
            recommendations: List of recommendations with similarity_score

        Returns:
            Dictionary mapping artist names to normalized scores
        """
        if not recommendations:
            return {}

        scores = {rec["artist_name"]: rec["similarity_score"] for rec in recommendations}

        min_score = min(scores.values())
        max_score = max(scores.values())

        if max_score == min_score:
            # All scores are the same
            return dict.fromkeys(scores, 1.0)

        # Min-max normalization
        normalized = {}
        for artist, score in scores.items():
            normalized[artist] = (score - min_score) / (max_score - min_score)

        return normalized

    def _apply_diversity_boost(
        self,
        scores: dict[str, float],
        reference_artist: str,  # noqa: ARG002
    ) -> dict[str, float]:
        """Apply diversity boosting to reduce similarity between recommended items.

        Args:
            scores: Current scores for artists
            reference_artist: The artist we're getting recommendations for (reserved for future use)

        Returns:
            Adjusted scores with diversity boost
        """
        # Create a copy to avoid modifying the original
        boosted_scores = scores.copy()
        selected_artists: list[str] = []

        # Iteratively select artists, applying diversity penalty
        for _ in range(len(scores)):
            if not boosted_scores:
                break

            # Find the highest scoring artist
            best_artist = max(boosted_scores.items(), key=lambda x: x[1])[0]
            selected_artists.append(best_artist)

            # Remove from consideration
            del boosted_scores[best_artist]

            # Penalize similar artists
            for artist in list(boosted_scores.keys()):
                similarity = self.content_based.get_similarity_score(best_artist, artist)
                if similarity > self.min_diversity_threshold:
                    penalty = self.diversity_weight * similarity
                    boosted_scores[artist] *= 1 - penalty

        # Return original scores in the diversified order
        return {artist: scores[artist] for artist in selected_artists}

    def set_method_weights(self, weights: dict[str, float]) -> None:
        """Update the weights for different recommendation methods.

        Args:
            weights: Dictionary mapping method names to weights
        """
        self.method_weights.update(weights)
        logger.info("✅ Updated method weights", weights=self.method_weights)

    def set_diversity_parameters(self, diversity_weight: float, min_threshold: float) -> None:
        """Update diversity boosting parameters.

        Args:
            diversity_weight: Weight for diversity penalty (0.0 to 1.0)
            min_threshold: Minimum similarity threshold for diversity calculation
        """
        self.diversity_weight = diversity_weight
        self.min_diversity_threshold = min_threshold
        logger.info(
            "✅ Updated diversity parameters",
            diversity_weight=diversity_weight,
            min_threshold=min_threshold,
        )
