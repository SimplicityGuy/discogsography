"""Recommendation explainability and interpretability features.

This module provides human-readable explanations for why certain artists
are being recommended, helping build trust and understanding in the system.
"""

from collections import Counter
from typing import Any

import structlog

from discovery.collaborative_filtering import CollaborativeFilter
from discovery.content_based import ContentBasedFilter
from discovery.hybrid_recommender import HybridRecommender


logger = structlog.get_logger(__name__)


class RecommendationExplainer:
    """Generate explanations for recommendations."""

    def __init__(
        self,
        collaborative_filter: CollaborativeFilter,
        content_based_filter: ContentBasedFilter,
        hybrid_recommender: HybridRecommender,
    ) -> None:
        """Initialize recommendation explainer.

        Args:
            collaborative_filter: Collaborative filtering instance
            content_based_filter: Content-based filtering instance
            hybrid_recommender: Hybrid recommender instance
        """
        self.collaborative = collaborative_filter
        self.content_based = content_based_filter
        self.hybrid = hybrid_recommender

    def explain_recommendation(
        self,
        source_artist: str,
        recommended_artist: str,
        method: str = "hybrid",
    ) -> dict[str, Any]:
        """Generate explanation for why an artist was recommended.

        Args:
            source_artist: The artist the user is interested in
            recommended_artist: The recommended artist
            method: Recommendation method used

        Returns:
            Dictionary with explanation details
        """
        if method == "collaborative_filtering":
            return self._explain_collaborative(source_artist, recommended_artist)
        elif method == "content_based":
            return self._explain_content_based(source_artist, recommended_artist)
        elif method == "hybrid":
            return self._explain_hybrid(source_artist, recommended_artist)
        else:
            return {
                "method": method,
                "explanation": "Explanation not available for this method",
                "confidence": 0.0,
            }

    def _explain_collaborative(self, source_artist: str, recommended_artist: str) -> dict[str, Any]:
        """Explain collaborative filtering recommendation.

        Args:
            source_artist: Source artist
            recommended_artist: Recommended artist

        Returns:
            Explanation details
        """
        # Get similarity score
        similarity = self.collaborative.get_similarity_score(source_artist, recommended_artist)

        # Get artist features to find common patterns
        source_features = self.collaborative.artist_features.get(source_artist, {})
        rec_features = self.collaborative.artist_features.get(recommended_artist, {})

        # Find common attributes
        common_collaborators = set(source_features.get("collaborators", [])) & set(rec_features.get("collaborators", []))
        common_labels = set(source_features.get("labels", [])) & set(rec_features.get("labels", []))
        common_genres = set(source_features.get("genres", [])) & set(rec_features.get("genres", []))
        common_styles = set(source_features.get("styles", [])) & set(rec_features.get("styles", []))

        # Build explanation
        factors = []

        if common_collaborators:
            factors.append(
                {
                    "factor": "shared_collaborators",
                    "weight": 5.0,
                    "description": f"Both have worked with: {', '.join(list(common_collaborators)[:3])}",
                    "count": len(common_collaborators),
                }
            )

        if common_labels:
            factors.append(
                {
                    "factor": "shared_labels",
                    "weight": 2.0,
                    "description": f"Both released on: {', '.join(list(common_labels)[:3])}",
                    "count": len(common_labels),
                }
            )

        if common_genres:
            factors.append(
                {
                    "factor": "shared_genres",
                    "weight": 1.5,
                    "description": f"Both play: {', '.join(list(common_genres)[:3])}",
                    "count": len(common_genres),
                }
            )

        if common_styles:
            factors.append(
                {
                    "factor": "shared_styles",
                    "weight": 1.0,
                    "description": f"Similar styles: {', '.join(list(common_styles)[:3])}",
                    "count": len(common_styles),
                }
            )

        # Generate human-readable explanation
        if factors:
            primary_factor = max(factors, key=lambda x: float(x["weight"]) * float(x["count"]))  # type: ignore[arg-type]
            explanation = self._generate_collaborative_text(source_artist, recommended_artist, factors, primary_factor)
        else:
            explanation = f"{recommended_artist} is recommended based on patterns from other listeners who enjoy {source_artist}."

        return {
            "method": "collaborative_filtering",
            "similarity_score": similarity,
            "explanation": explanation,
            "factors": factors,
            "confidence": min(similarity, 1.0),
        }

    def _explain_content_based(self, source_artist: str, recommended_artist: str) -> dict[str, Any]:
        """Explain content-based filtering recommendation.

        Args:
            source_artist: Source artist
            recommended_artist: Recommended artist

        Returns:
            Explanation details
        """
        # Get similarity score
        similarity = self.content_based.get_similarity_score(source_artist, recommended_artist)

        # Get important features for both artists
        source_features_list = self.content_based.get_feature_importance(source_artist, top_n=10)
        rec_features_list = self.content_based.get_feature_importance(recommended_artist, top_n=10)

        # Find overlapping important features
        source_features_set = {f["feature"] for f in source_features_list}
        rec_features_set = {f["feature"] for f in rec_features_list}
        common_features = source_features_set & rec_features_set

        # Get artist attributes
        source_attrs = self.content_based.artist_features.get(source_artist, {})
        rec_attrs = self.content_based.artist_features.get(recommended_artist, {})

        # Analyze attribute similarities
        factors = []

        # Genre similarity
        common_genres = set(source_attrs.get("genres", [])) & set(rec_attrs.get("genres", []))
        if common_genres:
            factors.append(
                {
                    "factor": "genre_match",
                    "weight": 0.3,
                    "description": f"Both artists are known for {', '.join(list(common_genres)[:2])}",
                    "values": list(common_genres),
                }
            )

        # Style similarity
        common_styles = set(source_attrs.get("styles", [])) & set(rec_attrs.get("styles", []))
        if common_styles:
            factors.append(
                {
                    "factor": "style_match",
                    "weight": 0.25,
                    "description": f"Share musical styles: {', '.join(list(common_styles)[:2])}",
                    "values": list(common_styles),
                }
            )

        # Label similarity
        common_labels = set(source_attrs.get("labels", [])) & set(rec_attrs.get("labels", []))
        if common_labels:
            factors.append(
                {
                    "factor": "label_match",
                    "weight": 0.2,
                    "description": f"Both on labels like {', '.join(list(common_labels)[:2])}",
                    "values": list(common_labels),
                }
            )

        # Time period similarity
        source_era = source_attrs.get("earliest_year")
        rec_era = rec_attrs.get("earliest_year")
        if source_era and rec_era:
            source_decade = (source_era // 10) * 10
            rec_decade = (rec_era // 10) * 10
            if source_decade == rec_decade:
                factors.append(
                    {
                        "factor": "era_match",
                        "weight": 0.1,
                        "description": f"Both active in the {source_decade}s",
                        "value": f"{source_decade}s",
                    }
                )

        # Generate explanation
        explanation = self._generate_content_based_text(source_artist, recommended_artist, factors)

        return {
            "method": "content_based",
            "similarity_score": similarity,
            "explanation": explanation,
            "factors": factors,
            "common_features": list(common_features)[:5],
            "confidence": min(similarity, 1.0),
        }

    def _explain_hybrid(self, source_artist: str, recommended_artist: str) -> dict[str, Any]:
        """Explain hybrid recommendation.

        Args:
            source_artist: Source artist
            recommended_artist: Recommended artist

        Returns:
            Explanation details
        """
        # Get explanations from both methods
        collab_explanation = self._explain_collaborative(source_artist, recommended_artist)
        content_explanation = self._explain_content_based(source_artist, recommended_artist)

        # Combine insights
        all_factors = collab_explanation.get("factors", []) + content_explanation.get("factors", [])

        # Sort by importance (weight * count or presence)
        all_factors.sort(
            key=lambda x: x.get("weight", 0) * x.get("count", 1),
            reverse=True,
        )

        # Generate combined explanation
        explanation_parts = []

        if all_factors:
            top_factors = all_factors[:3]

            explanation_parts.append(f"{recommended_artist} is recommended because:")

            for i, factor in enumerate(top_factors, 1):
                explanation_parts.append(f"{i}. {factor['description']}")

        combined_explanation = (
            " ".join(explanation_parts)
            if explanation_parts
            else (f"{recommended_artist} matches {source_artist} based on multiple similarity factors.")
        )

        # Calculate combined confidence
        combined_confidence = collab_explanation.get("confidence", 0) * 0.5 + content_explanation.get("confidence", 0) * 0.5

        return {
            "method": "hybrid",
            "explanation": combined_explanation,
            "factors": all_factors[:5],  # Top 5 factors
            "collaborative_score": collab_explanation.get("similarity_score", 0),
            "content_based_score": content_explanation.get("similarity_score", 0),
            "confidence": combined_confidence,
        }

    def _generate_collaborative_text(
        self,
        source_artist: str,
        recommended_artist: str,
        factors: list[dict[str, Any]],
        primary_factor: dict[str, Any],
    ) -> str:
        """Generate human-readable text for collaborative filtering.

        Args:
            source_artist: Source artist
            recommended_artist: Recommended artist
            factors: List of factors
            primary_factor: Most important factor

        Returns:
            Human-readable explanation
        """
        templates = {
            "shared_collaborators": f"Fans of {source_artist} also enjoy {recommended_artist}. {primary_factor['description']}.",
            "shared_labels": f"{recommended_artist} is similar to {source_artist}. {primary_factor['description']}.",
            "shared_genres": f"Like {source_artist}, {recommended_artist} is known for {primary_factor['description'].lower()}.",
            "shared_styles": f"{recommended_artist} has a similar sound to {source_artist}. {primary_factor['description']}.",
        }

        template = templates.get(
            primary_factor["factor"],
            f"{recommended_artist} is recommended based on similarities with {source_artist}.",
        )

        # Add secondary factors if present
        if len(factors) > 1:
            secondary = factors[1]
            template += f" Additionally, {secondary['description'].lower()}."

        return template

    def _generate_content_based_text(
        self,
        source_artist: str,
        recommended_artist: str,
        factors: list[dict[str, Any]],
    ) -> str:
        """Generate human-readable text for content-based filtering.

        Args:
            source_artist: Source artist
            recommended_artist: Recommended artist
            factors: List of factors

        Returns:
            Human-readable explanation
        """
        if not factors:
            return f"{recommended_artist} has similar musical attributes to {source_artist}."

        primary = factors[0]

        explanation = f"If you like {source_artist}, you might enjoy {recommended_artist}. {primary['description']}."

        # Add additional factors
        if len(factors) > 1:
            additional = [f["description"] for f in factors[1:3]]
            if additional:
                explanation += " They also " + " and ".join([desc.lower() for desc in additional]) + "."

        return explanation

    def get_explanation_summary(
        self,
        source_artist: str,
        recommendations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Get summary explanation for a list of recommendations.

        Args:
            source_artist: Source artist
            recommendations: List of recommendations with artist names and methods

        Returns:
            Summary of common recommendation patterns
        """
        all_factors: list[str] = []
        methods_used: Counter[str] = Counter()

        for rec in recommendations:
            artist = rec["artist_name"]
            method = rec.get("method", "hybrid")

            explanation = self.explain_recommendation(source_artist, artist, method)
            methods_used[method] += 1

            # Collect factors
            for factor in explanation.get("factors", []):
                all_factors.append(factor.get("factor", "unknown"))

        # Find most common factors
        factor_counts = Counter(all_factors)

        return {
            "source_artist": source_artist,
            "total_recommendations": len(recommendations),
            "methods_used": dict(methods_used),
            "common_factors": [{"factor": factor, "count": count} for factor, count in factor_counts.most_common(5)],
            "summary": self._generate_summary_text(source_artist, factor_counts),
        }

    def _generate_summary_text(self, source_artist: str, factor_counts: Counter[str]) -> str:
        """Generate summary text for multiple recommendations.

        Args:
            source_artist: Source artist
            factor_counts: Counter of factors

        Returns:
            Summary text
        """
        if not factor_counts:
            return f"These artists are recommended based on various similarities with {source_artist}."

        most_common = factor_counts.most_common(1)[0][0]

        factor_descriptions = {
            "shared_genres": "similar musical genres",
            "shared_styles": "comparable musical styles",
            "shared_labels": "common record labels",
            "shared_collaborators": "mutual collaborations",
            "genre_match": "matching genres",
            "style_match": "similar styles",
            "label_match": "shared labels",
            "era_match": "same time period",
        }

        description = factor_descriptions.get(most_common, "various similarities")

        return f"These recommendations for {source_artist} are primarily based on {description}."

    def compare_recommendations(
        self,
        source_artist: str,
        artist_a: str,
        artist_b: str,
    ) -> dict[str, Any]:
        """Compare two recommendations to explain why one might be preferred.

        Args:
            source_artist: Source artist
            artist_a: First recommended artist
            artist_b: Second recommended artist

        Returns:
            Comparison details
        """
        explanation_a = self.explain_recommendation(source_artist, artist_a, "hybrid")
        explanation_b = self.explain_recommendation(source_artist, artist_b, "hybrid")

        comparison = {
            "source_artist": source_artist,
            "artist_a": {
                "name": artist_a,
                "confidence": explanation_a.get("confidence", 0),
                "explanation": explanation_a.get("explanation", ""),
                "num_factors": len(explanation_a.get("factors", [])),
            },
            "artist_b": {
                "name": artist_b,
                "confidence": explanation_b.get("confidence", 0),
                "explanation": explanation_b.get("explanation", ""),
                "num_factors": len(explanation_b.get("factors", [])),
            },
        }

        # Determine which is stronger
        if explanation_a.get("confidence", 0) > explanation_b.get("confidence", 0):
            comparison["stronger_match"] = artist_a
            comparison["reason"] = f"{artist_a} has a higher similarity score and more matching factors."
        elif explanation_b.get("confidence", 0) > explanation_a.get("confidence", 0):
            comparison["stronger_match"] = artist_b
            comparison["reason"] = f"{artist_b} has a higher similarity score and more matching factors."
        else:
            comparison["stronger_match"] = "equal"
            comparison["reason"] = "Both artists have similar match quality."

        return comparison
