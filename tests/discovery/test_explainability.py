"""Tests for RecommendationExplainer class."""

from collections import Counter
from unittest.mock import MagicMock

import pytest

from discovery.explainability import RecommendationExplainer


class TestExplainerInitialization:
    """Test explainer initialization."""

    def test_initialization(self) -> None:
        """Test explainer initializes correctly."""
        mock_collaborative = MagicMock()
        mock_content_based = MagicMock()
        mock_hybrid = MagicMock()

        explainer = RecommendationExplainer(
            collaborative_filter=mock_collaborative,
            content_based_filter=mock_content_based,
            hybrid_recommender=mock_hybrid,
        )

        assert explainer.collaborative == mock_collaborative
        assert explainer.content_based == mock_content_based
        assert explainer.hybrid == mock_hybrid


class TestExplainRecommendation:
    """Test main recommendation explanation."""

    def test_explain_collaborative_method(self) -> None:
        """Test explaining collaborative filtering recommendation."""
        mock_collaborative = MagicMock()
        mock_collaborative.get_similarity_score.return_value = 0.85
        mock_collaborative.artist_features = {
            "Artist A": {"collaborators": ["Collaborator 1"], "labels": [], "genres": [], "styles": []},
            "Artist B": {"collaborators": ["Collaborator 1"], "labels": [], "genres": [], "styles": []},
        }

        explainer = RecommendationExplainer(mock_collaborative, MagicMock(), MagicMock())

        result = explainer.explain_recommendation("Artist A", "Artist B", "collaborative_filtering")

        assert result["method"] == "collaborative_filtering"
        assert result["similarity_score"] == 0.85
        assert "explanation" in result
        assert len(result["factors"]) > 0

    def test_explain_content_based_method(self) -> None:
        """Test explaining content-based recommendation."""
        mock_content_based = MagicMock()
        mock_content_based.get_similarity_score.return_value = 0.75
        mock_content_based.get_feature_importance.return_value = [{"feature": "rock"}, {"feature": "alternative"}]
        mock_content_based.artist_features = {
            "Artist A": {"genres": ["Rock"], "styles": [], "labels": [], "earliest_year": 1990},
            "Artist B": {"genres": ["Rock"], "styles": [], "labels": [], "earliest_year": 1992},
        }

        explainer = RecommendationExplainer(MagicMock(), mock_content_based, MagicMock())

        result = explainer.explain_recommendation("Artist A", "Artist B", "content_based")

        assert result["method"] == "content_based"
        assert result["similarity_score"] == 0.75
        assert "explanation" in result
        assert "common_features" in result

    def test_explain_hybrid_method(self) -> None:
        """Test explaining hybrid recommendation."""
        mock_collaborative = MagicMock()
        mock_collaborative.get_similarity_score.return_value = 0.8
        mock_collaborative.artist_features = {
            "Artist A": {"collaborators": [], "labels": [], "genres": ["Rock"], "styles": []},
            "Artist B": {"collaborators": [], "labels": [], "genres": ["Rock"], "styles": []},
        }

        mock_content_based = MagicMock()
        mock_content_based.get_similarity_score.return_value = 0.7
        mock_content_based.get_feature_importance.return_value = []
        mock_content_based.artist_features = {
            "Artist A": {"genres": ["Rock"], "styles": [], "labels": []},
            "Artist B": {"genres": ["Rock"], "styles": [], "labels": []},
        }

        explainer = RecommendationExplainer(mock_collaborative, mock_content_based, MagicMock())

        result = explainer.explain_recommendation("Artist A", "Artist B", "hybrid")

        assert result["method"] == "hybrid"
        assert "collaborative_score" in result
        assert "content_based_score" in result
        assert "confidence" in result

    def test_explain_unknown_method(self) -> None:
        """Test explaining with unknown method."""
        explainer = RecommendationExplainer(MagicMock(), MagicMock(), MagicMock())

        result = explainer.explain_recommendation("Artist A", "Artist B", "unknown_method")

        assert result["method"] == "unknown_method"
        assert result["confidence"] == 0.0
        assert "not available" in result["explanation"]


class TestCollaborativeExplanation:
    """Test collaborative filtering explanation."""

    def test_explain_with_shared_collaborators(self) -> None:
        """Test explanation with shared collaborators."""
        mock_collaborative = MagicMock()
        mock_collaborative.get_similarity_score.return_value = 0.9
        mock_collaborative.artist_features = {
            "Artist A": {"collaborators": ["Collab1", "Collab2"], "labels": [], "genres": [], "styles": []},
            "Artist B": {"collaborators": ["Collab1", "Collab3"], "labels": [], "genres": [], "styles": []},
        }

        explainer = RecommendationExplainer(mock_collaborative, MagicMock(), MagicMock())

        result = explainer._explain_collaborative("Artist A", "Artist B")

        assert result["similarity_score"] == 0.9
        assert any(f["factor"] == "shared_collaborators" for f in result["factors"])
        assert "worked with" in result["explanation"]

    def test_explain_with_shared_labels(self) -> None:
        """Test explanation with shared labels."""
        mock_collaborative = MagicMock()
        mock_collaborative.get_similarity_score.return_value = 0.8
        mock_collaborative.artist_features = {
            "Artist A": {"collaborators": [], "labels": ["Label1"], "genres": [], "styles": []},
            "Artist B": {"collaborators": [], "labels": ["Label1"], "genres": [], "styles": []},
        }

        explainer = RecommendationExplainer(mock_collaborative, MagicMock(), MagicMock())

        result = explainer._explain_collaborative("Artist A", "Artist B")

        assert any(f["factor"] == "shared_labels" for f in result["factors"])
        assert "released on" in result["explanation"]

    def test_explain_with_shared_genres(self) -> None:
        """Test explanation with shared genres."""
        mock_collaborative = MagicMock()
        mock_collaborative.get_similarity_score.return_value = 0.7
        mock_collaborative.artist_features = {
            "Artist A": {"collaborators": [], "labels": [], "genres": ["Rock"], "styles": []},
            "Artist B": {"collaborators": [], "labels": [], "genres": ["Rock"], "styles": []},
        }

        explainer = RecommendationExplainer(mock_collaborative, MagicMock(), MagicMock())

        result = explainer._explain_collaborative("Artist A", "Artist B")

        assert any(f["factor"] == "shared_genres" for f in result["factors"])

    def test_explain_with_shared_styles(self) -> None:
        """Test explanation with shared styles."""
        mock_collaborative = MagicMock()
        mock_collaborative.get_similarity_score.return_value = 0.6
        mock_collaborative.artist_features = {
            "Artist A": {"collaborators": [], "labels": [], "genres": [], "styles": ["Alternative"]},
            "Artist B": {"collaborators": [], "labels": [], "genres": [], "styles": ["Alternative"]},
        }

        explainer = RecommendationExplainer(mock_collaborative, MagicMock(), MagicMock())

        result = explainer._explain_collaborative("Artist A", "Artist B")

        assert any(f["factor"] == "shared_styles" for f in result["factors"])

    def test_explain_with_no_common_factors(self) -> None:
        """Test explanation with no common factors."""
        mock_collaborative = MagicMock()
        mock_collaborative.get_similarity_score.return_value = 0.5
        mock_collaborative.artist_features = {
            "Artist A": {"collaborators": [], "labels": [], "genres": [], "styles": []},
            "Artist B": {"collaborators": [], "labels": [], "genres": [], "styles": []},
        }

        explainer = RecommendationExplainer(mock_collaborative, MagicMock(), MagicMock())

        result = explainer._explain_collaborative("Artist A", "Artist B")

        assert len(result["factors"]) == 0
        assert "patterns from other listeners" in result["explanation"]


class TestContentBasedExplanation:
    """Test content-based explanation."""

    def test_explain_with_genre_match(self) -> None:
        """Test explanation with genre match."""
        mock_content_based = MagicMock()
        mock_content_based.get_similarity_score.return_value = 0.8
        mock_content_based.get_feature_importance.return_value = []
        mock_content_based.artist_features = {
            "Artist A": {"genres": ["Rock", "Alternative"], "styles": [], "labels": []},
            "Artist B": {"genres": ["Rock", "Indie"], "styles": [], "labels": []},
        }

        explainer = RecommendationExplainer(MagicMock(), mock_content_based, MagicMock())

        result = explainer._explain_content_based("Artist A", "Artist B")

        assert any(f["factor"] == "genre_match" for f in result["factors"])
        assert "Rock" in str(result["factors"])

    def test_explain_with_style_match(self) -> None:
        """Test explanation with style match."""
        mock_content_based = MagicMock()
        mock_content_based.get_similarity_score.return_value = 0.75
        mock_content_based.get_feature_importance.return_value = []
        mock_content_based.artist_features = {
            "Artist A": {"genres": [], "styles": ["Indie Rock"], "labels": []},
            "Artist B": {"genres": [], "styles": ["Indie Rock"], "labels": []},
        }

        explainer = RecommendationExplainer(MagicMock(), mock_content_based, MagicMock())

        result = explainer._explain_content_based("Artist A", "Artist B")

        assert any(f["factor"] == "style_match" for f in result["factors"])

    def test_explain_with_label_match(self) -> None:
        """Test explanation with label match."""
        mock_content_based = MagicMock()
        mock_content_based.get_similarity_score.return_value = 0.7
        mock_content_based.get_feature_importance.return_value = []
        mock_content_based.artist_features = {
            "Artist A": {"genres": [], "styles": [], "labels": ["Indie Label"]},
            "Artist B": {"genres": [], "styles": [], "labels": ["Indie Label"]},
        }

        explainer = RecommendationExplainer(MagicMock(), mock_content_based, MagicMock())

        result = explainer._explain_content_based("Artist A", "Artist B")

        assert any(f["factor"] == "label_match" for f in result["factors"])

    def test_explain_with_era_match(self) -> None:
        """Test explanation with era match."""
        mock_content_based = MagicMock()
        mock_content_based.get_similarity_score.return_value = 0.6
        mock_content_based.get_feature_importance.return_value = []
        mock_content_based.artist_features = {
            "Artist A": {"genres": [], "styles": [], "labels": [], "earliest_year": 1995},
            "Artist B": {"genres": [], "styles": [], "labels": [], "earliest_year": 1998},
        }

        explainer = RecommendationExplainer(MagicMock(), mock_content_based, MagicMock())

        result = explainer._explain_content_based("Artist A", "Artist B")

        assert any(f["factor"] == "era_match" for f in result["factors"])
        assert "1990s" in str(result["factors"])

    def test_explain_with_common_features(self) -> None:
        """Test explanation with common important features."""
        mock_content_based = MagicMock()
        mock_content_based.get_similarity_score.return_value = 0.85
        mock_content_based.get_feature_importance.return_value = [
            {"feature": "rock"},
            {"feature": "guitar"},
        ]
        mock_content_based.artist_features = {
            "Artist A": {"genres": [], "styles": [], "labels": []},
            "Artist B": {"genres": [], "styles": [], "labels": []},
        }

        explainer = RecommendationExplainer(MagicMock(), mock_content_based, MagicMock())

        result = explainer._explain_content_based("Artist A", "Artist B")

        assert "common_features" in result
        assert len(result["common_features"]) > 0


class TestHybridExplanation:
    """Test hybrid explanation."""

    def test_explain_hybrid_combines_factors(self) -> None:
        """Test that hybrid explanation combines factors from both methods."""
        mock_collaborative = MagicMock()
        mock_collaborative.get_similarity_score.return_value = 0.9
        mock_collaborative.artist_features = {
            "Artist A": {"collaborators": ["Collab1"], "labels": [], "genres": [], "styles": []},
            "Artist B": {"collaborators": ["Collab1"], "labels": [], "genres": [], "styles": []},
        }

        mock_content_based = MagicMock()
        mock_content_based.get_similarity_score.return_value = 0.8
        mock_content_based.get_feature_importance.return_value = []
        mock_content_based.artist_features = {
            "Artist A": {"genres": ["Rock"], "styles": [], "labels": []},
            "Artist B": {"genres": ["Rock"], "styles": [], "labels": []},
        }

        explainer = RecommendationExplainer(mock_collaborative, mock_content_based, MagicMock())

        result = explainer._explain_hybrid("Artist A", "Artist B")

        assert len(result["factors"]) > 0
        assert result["collaborative_score"] == 0.9
        assert result["content_based_score"] == 0.8
        assert result["confidence"] == pytest.approx(0.85, rel=0.01)  # Average

    def test_explain_hybrid_sorts_factors_by_importance(self) -> None:
        """Test that hybrid sorts factors by importance."""
        mock_collaborative = MagicMock()
        mock_collaborative.get_similarity_score.return_value = 0.7
        mock_collaborative.artist_features = {
            "Artist A": {
                "collaborators": ["C1", "C2", "C3"],  # High weight * count
                "labels": ["L1"],  # Lower weight * count
                "genres": [],
                "styles": [],
            },
            "Artist B": {
                "collaborators": ["C1", "C2"],
                "labels": ["L1"],
                "genres": [],
                "styles": [],
            },
        }

        mock_content_based = MagicMock()
        mock_content_based.get_similarity_score.return_value = 0.6
        mock_content_based.get_feature_importance.return_value = []
        mock_content_based.artist_features = {
            "Artist A": {"genres": [], "styles": [], "labels": []},
            "Artist B": {"genres": [], "styles": [], "labels": []},
        }

        explainer = RecommendationExplainer(mock_collaborative, mock_content_based, MagicMock())

        result = explainer._explain_hybrid("Artist A", "Artist B")

        # First factor should be shared_collaborators (highest weight * count)
        assert result["factors"][0]["factor"] == "shared_collaborators"


class TestTextGeneration:
    """Test text generation methods."""

    def test_generate_collaborative_text_shared_collaborators(self) -> None:
        """Test generating text for shared collaborators."""
        mock_collaborative = MagicMock()
        explainer = RecommendationExplainer(mock_collaborative, MagicMock(), MagicMock())

        factors = [{"factor": "shared_collaborators", "description": "Both worked with XYZ", "count": 2, "weight": 5.0}]

        text = explainer._generate_collaborative_text("Artist A", "Artist B", factors, factors[0])

        assert "Artist A" in text
        assert "Artist B" in text
        assert "Fans of" in text

    def test_generate_collaborative_text_with_secondary_factor(self) -> None:
        """Test generating text with secondary factor."""
        mock_collaborative = MagicMock()
        explainer = RecommendationExplainer(mock_collaborative, MagicMock(), MagicMock())

        factors = [
            {"factor": "shared_labels", "description": "Both on Label X", "count": 1, "weight": 2.0},
            {"factor": "shared_genres", "description": "Both play Rock", "count": 1, "weight": 1.5},
        ]

        text = explainer._generate_collaborative_text("Artist A", "Artist B", factors, factors[0])

        assert "Additionally" in text

    def test_generate_content_based_text_with_factors(self) -> None:
        """Test generating content-based text with factors."""
        mock_content_based = MagicMock()
        explainer = RecommendationExplainer(MagicMock(), mock_content_based, MagicMock())

        factors = [
            {"factor": "genre_match", "description": "Both play Rock", "weight": 0.3},
            {"factor": "style_match", "description": "Share Indie style", "weight": 0.25},
        ]

        text = explainer._generate_content_based_text("Artist A", "Artist B", factors)

        assert "If you like" in text
        assert "Artist A" in text
        assert "Artist B" in text

    def test_generate_content_based_text_no_factors(self) -> None:
        """Test generating content-based text without factors."""
        mock_content_based = MagicMock()
        explainer = RecommendationExplainer(MagicMock(), mock_content_based, MagicMock())

        text = explainer._generate_content_based_text("Artist A", "Artist B", [])

        assert "similar musical attributes" in text


class TestExplanationSummary:
    """Test explanation summary generation."""

    def test_get_explanation_summary(self) -> None:
        """Test getting summary for multiple recommendations."""
        mock_collaborative = MagicMock()
        mock_collaborative.get_similarity_score.return_value = 0.8
        mock_collaborative.artist_features = {
            "Artist A": {"collaborators": [], "labels": [], "genres": ["Rock"], "styles": []},
            "Artist B": {"collaborators": [], "labels": [], "genres": ["Rock"], "styles": []},
            "Artist C": {"collaborators": [], "labels": [], "genres": ["Rock"], "styles": []},
        }

        mock_content_based = MagicMock()
        mock_content_based.get_similarity_score.return_value = 0.7
        mock_content_based.get_feature_importance.return_value = []
        mock_content_based.artist_features = {
            "Artist A": {"genres": ["Rock"], "styles": [], "labels": []},
            "Artist B": {"genres": ["Rock"], "styles": [], "labels": []},
            "Artist C": {"genres": ["Rock"], "styles": [], "labels": []},
        }

        explainer = RecommendationExplainer(mock_collaborative, mock_content_based, MagicMock())

        recommendations = [
            {"artist_name": "Artist B", "method": "hybrid"},
            {"artist_name": "Artist C", "method": "hybrid"},
        ]

        summary = explainer.get_explanation_summary("Artist A", recommendations)

        assert summary["source_artist"] == "Artist A"
        assert summary["total_recommendations"] == 2
        assert "methods_used" in summary
        assert "common_factors" in summary
        assert "summary" in summary

    def test_generate_summary_text_with_factors(self) -> None:
        """Test generating summary text with factors."""
        mock_collaborative = MagicMock()
        explainer = RecommendationExplainer(mock_collaborative, MagicMock(), MagicMock())

        factor_counts = Counter({"shared_genres": 5, "shared_styles": 3})

        text = explainer._generate_summary_text("Artist A", factor_counts)

        assert "Artist A" in text
        assert "similar musical genres" in text

    def test_generate_summary_text_no_factors(self) -> None:
        """Test generating summary text without factors."""
        mock_collaborative = MagicMock()
        explainer = RecommendationExplainer(mock_collaborative, MagicMock(), MagicMock())

        text = explainer._generate_summary_text("Artist A", Counter())

        assert "various similarities" in text


class TestCompareRecommendations:
    """Test recommendation comparison."""

    def test_compare_recommendations_artist_a_stronger(self) -> None:
        """Test comparing when artist A is stronger."""
        mock_collaborative = MagicMock()
        mock_collaborative.get_similarity_score.side_effect = [0.9, 0.6]
        mock_collaborative.artist_features = {
            "Source": {"collaborators": [], "labels": [], "genres": [], "styles": []},
            "Artist A": {"collaborators": [], "labels": [], "genres": [], "styles": []},
            "Artist B": {"collaborators": [], "labels": [], "genres": [], "styles": []},
        }

        mock_content_based = MagicMock()
        mock_content_based.get_similarity_score.side_effect = [0.8, 0.5]
        mock_content_based.get_feature_importance.return_value = []
        mock_content_based.artist_features = {
            "Source": {"genres": [], "styles": [], "labels": []},
            "Artist A": {"genres": [], "styles": [], "labels": []},
            "Artist B": {"genres": [], "styles": [], "labels": []},
        }

        explainer = RecommendationExplainer(mock_collaborative, mock_content_based, MagicMock())

        comparison = explainer.compare_recommendations("Source", "Artist A", "Artist B")

        assert comparison["stronger_match"] == "Artist A"
        assert "higher similarity" in comparison["reason"]

    def test_compare_recommendations_artist_b_stronger(self) -> None:
        """Test comparing when artist B is stronger."""
        mock_collaborative = MagicMock()
        mock_collaborative.get_similarity_score.side_effect = [0.5, 0.9]
        mock_collaborative.artist_features = {
            "Source": {"collaborators": [], "labels": [], "genres": [], "styles": []},
            "Artist A": {"collaborators": [], "labels": [], "genres": [], "styles": []},
            "Artist B": {"collaborators": [], "labels": [], "genres": [], "styles": []},
        }

        mock_content_based = MagicMock()
        mock_content_based.get_similarity_score.side_effect = [0.4, 0.8]
        mock_content_based.get_feature_importance.return_value = []
        mock_content_based.artist_features = {
            "Source": {"genres": [], "styles": [], "labels": []},
            "Artist A": {"genres": [], "styles": [], "labels": []},
            "Artist B": {"genres": [], "styles": [], "labels": []},
        }

        explainer = RecommendationExplainer(mock_collaborative, mock_content_based, MagicMock())

        comparison = explainer.compare_recommendations("Source", "Artist A", "Artist B")

        assert comparison["stronger_match"] == "Artist B"

    def test_compare_recommendations_equal(self) -> None:
        """Test comparing when both are equal."""
        mock_collaborative = MagicMock()
        mock_collaborative.get_similarity_score.return_value = 0.7
        mock_collaborative.artist_features = {
            "Source": {"collaborators": [], "labels": [], "genres": [], "styles": []},
            "Artist A": {"collaborators": [], "labels": [], "genres": [], "styles": []},
            "Artist B": {"collaborators": [], "labels": [], "genres": [], "styles": []},
        }

        mock_content_based = MagicMock()
        mock_content_based.get_similarity_score.return_value = 0.7
        mock_content_based.get_feature_importance.return_value = []
        mock_content_based.artist_features = {
            "Source": {"genres": [], "styles": [], "labels": []},
            "Artist A": {"genres": [], "styles": [], "labels": []},
            "Artist B": {"genres": [], "styles": [], "labels": []},
        }

        explainer = RecommendationExplainer(mock_collaborative, mock_content_based, MagicMock())

        comparison = explainer.compare_recommendations("Source", "Artist A", "Artist B")

        assert comparison["stronger_match"] == "equal"
        assert "similar match quality" in comparison["reason"]
