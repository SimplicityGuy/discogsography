"""Tests for RecommenderMetricsTracker class."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# Mock Prometheus metrics before importing to avoid registration conflicts
with patch("prometheus_client.Counter"), patch("prometheus_client.Gauge"), patch("prometheus_client.Histogram"):
    from discovery.recommender_metrics import (
        AlgorithmPerformance,
        RecommendationMetrics,
        RecommenderMetricsTracker,
    )


class TestDataclasses:
    """Test dataclass definitions."""

    def test_recommendation_metrics(self) -> None:
        """Test RecommendationMetrics dataclass."""
        metrics = RecommendationMetrics(
            method="collaborative",
            strategy="item-based",
            latency_seconds=0.5,
            num_results=10,
            diversity_score=0.75,
            novelty_score=0.6,
        )

        assert metrics.method == "collaborative"
        assert metrics.strategy == "item-based"
        assert metrics.latency_seconds == 0.5
        assert metrics.num_results == 10
        assert metrics.error is None

    def test_algorithm_performance(self) -> None:
        """Test AlgorithmPerformance dataclass."""
        perf = AlgorithmPerformance(
            method="content-based",
            total_requests=100,
            successful_requests=95,
            failed_requests=5,
            avg_latency=0.3,
        )

        assert perf.method == "content-based"
        assert perf.total_requests == 100
        assert perf.successful_requests == 95
        assert perf.failed_requests == 5


class TestTrackerInitialization:
    """Test tracker initialization."""

    def test_initialization(self) -> None:
        """Test tracker initializes correctly."""
        tracker = RecommenderMetricsTracker()

        assert tracker.metrics_history == []
        assert tracker.algorithm_performance == {}
        assert tracker.ab_test_groups == {}
        assert isinstance(tracker.start_time, float)


class TestTrackRequest:
    """Test tracking recommendation requests."""

    @patch("discovery.recommender_metrics.recommendation_requests")
    @patch("discovery.recommender_metrics.recommendation_latency")
    @patch("discovery.recommender_metrics.recommendation_diversity")
    def test_track_successful_request(
        self,
        _mock_diversity: MagicMock,
        _mock_latency: MagicMock,
        _mock_requests: MagicMock,
    ) -> None:
        """Test tracking a successful request."""
        tracker = RecommenderMetricsTracker()

        recommendations = [
            {"artist_name": "Artist A", "similarity_score": 0.9},
            {"artist_name": "Artist B", "similarity_score": 0.7},
            {"artist_name": "Artist C", "similarity_score": 0.5},
        ]

        metrics = tracker.track_request(
            method="collaborative",
            recommendations=recommendations,
            latency=0.5,
            strategy="item-based",
        )

        assert metrics.method == "collaborative"
        assert metrics.strategy == "item-based"
        assert metrics.num_results == 3
        assert metrics.latency_seconds == 0.5
        assert metrics.diversity_score > 0  # Should have calculated diversity
        assert metrics.error is None

        # Verify metrics stored
        assert len(tracker.metrics_history) == 1
        assert "collaborative" in tracker.algorithm_performance

    @patch("discovery.recommender_metrics.recommendation_requests")
    @patch("discovery.recommender_metrics.recommendation_latency")
    @patch("discovery.recommender_metrics.recommendation_errors")
    def test_track_failed_request(
        self,
        mock_errors: MagicMock,
        _mock_latency: MagicMock,
        _mock_requests: MagicMock,
    ) -> None:
        """Test tracking a failed request."""
        tracker = RecommenderMetricsTracker()

        metrics = tracker.track_request(
            method="collaborative",
            recommendations=[],
            latency=0.1,
            error="connection_timeout",
        )

        assert metrics.error == "connection_timeout"
        assert metrics.num_results == 0

        # Verify error counter called
        mock_errors.labels.assert_called_once()


class TestDiversityCalculation:
    """Test diversity score calculation."""

    def test_calculate_diversity_with_scores(self) -> None:
        """Test diversity calculation with similarity scores."""
        tracker = RecommenderMetricsTracker()

        recommendations = [
            {"similarity_score": 0.9},
            {"similarity_score": 0.5},
            {"similarity_score": 0.3},
        ]

        diversity = tracker._calculate_diversity(recommendations)

        assert 0.0 <= diversity <= 1.0
        assert diversity > 0  # Should have variance

    def test_calculate_diversity_single_item(self) -> None:
        """Test diversity with single recommendation."""
        tracker = RecommenderMetricsTracker()

        recommendations = [{"similarity_score": 0.9}]

        diversity = tracker._calculate_diversity(recommendations)

        assert diversity == 0.0

    def test_calculate_diversity_no_scores(self) -> None:
        """Test diversity fallback without scores."""
        tracker = RecommenderMetricsTracker()

        recommendations = [{"artist_name": "Artist A"}, {"artist_name": "Artist B"}]

        diversity = tracker._calculate_diversity(recommendations)

        assert diversity == 1.0  # Fallback value


class TestNoveltyCalculation:
    """Test novelty score calculation."""

    def test_calculate_novelty_with_scores(self) -> None:
        """Test novelty calculation with similarity scores."""
        tracker = RecommenderMetricsTracker()

        recommendations = [
            {"similarity_score": 0.9},
            {"similarity_score": 0.8},
            {"similarity_score": 0.7},
        ]

        novelty = tracker._calculate_novelty(recommendations)

        assert 0.0 <= novelty <= 1.0
        # Lower similarity should mean higher novelty
        # Average is 0.8, so novelty should be 1 - 0.8 = 0.2
        assert 0.1 <= novelty <= 0.3

    def test_calculate_novelty_empty(self) -> None:
        """Test novelty with no recommendations."""
        tracker = RecommenderMetricsTracker()

        novelty = tracker._calculate_novelty([])

        assert novelty == 0.0

    def test_calculate_novelty_no_scores(self) -> None:
        """Test novelty fallback without scores."""
        tracker = RecommenderMetricsTracker()

        recommendations = [{"artist_name": "Artist A"}]

        novelty = tracker._calculate_novelty(recommendations)

        assert novelty == 0.5  # Default neutral


class TestAlgorithmPerformance:
    """Test algorithm performance tracking."""

    @patch("discovery.recommender_metrics.recommendation_requests")
    @patch("discovery.recommender_metrics.recommendation_latency")
    @patch("discovery.recommender_metrics.recommendation_diversity")
    def test_update_algorithm_performance(
        self,
        _mock_diversity: MagicMock,
        _mock_latency: MagicMock,
        _mock_requests: MagicMock,
    ) -> None:
        """Test updating algorithm performance metrics."""
        tracker = RecommenderMetricsTracker()

        recommendations = [{"similarity_score": 0.9}, {"similarity_score": 0.7}]

        # Track multiple requests
        tracker.track_request("collaborative", recommendations, 0.5)
        tracker.track_request("collaborative", recommendations, 0.3)
        tracker.track_request("collaborative", recommendations, 0.4)

        perf = tracker.algorithm_performance["collaborative"]

        assert perf.total_requests == 3
        assert perf.successful_requests == 3
        assert perf.failed_requests == 0
        assert perf.avg_latency > 0
        assert len(perf.latencies) == 3
        assert perf.p95_latency > 0
        assert perf.p99_latency > 0

    @patch("discovery.recommender_metrics.recommendation_requests")
    @patch("discovery.recommender_metrics.recommendation_latency")
    @patch("discovery.recommender_metrics.recommendation_errors")
    def test_track_failures(
        self,
        _mock_errors: MagicMock,
        _mock_latency: MagicMock,
        _mock_requests: MagicMock,
    ) -> None:
        """Test tracking failed requests."""
        tracker = RecommenderMetricsTracker()

        tracker.track_request("collaborative", [], 0.1, error="timeout")
        tracker.track_request("collaborative", [{"similarity_score": 0.9}], 0.2)

        perf = tracker.algorithm_performance["collaborative"]

        assert perf.total_requests == 2
        assert perf.successful_requests == 1
        assert perf.failed_requests == 1

    def test_get_algorithm_performance_specific(self) -> None:
        """Test getting specific algorithm performance."""
        tracker = RecommenderMetricsTracker()
        tracker.algorithm_performance["collaborative"] = AlgorithmPerformance(method="collaborative", total_requests=10)

        perf = tracker.get_algorithm_performance("collaborative")

        assert perf.method == "collaborative"
        assert perf.total_requests == 10

    def test_get_algorithm_performance_all(self) -> None:
        """Test getting all algorithm performance."""
        tracker = RecommenderMetricsTracker()
        tracker.algorithm_performance["collaborative"] = AlgorithmPerformance(method="collaborative")
        tracker.algorithm_performance["content-based"] = AlgorithmPerformance(method="content-based")

        perf_dict = tracker.get_algorithm_performance()

        assert len(perf_dict) == 2
        assert "collaborative" in perf_dict
        assert "content-based" in perf_dict

    def test_get_algorithm_performance_not_found(self) -> None:
        """Test getting performance for unknown algorithm."""
        tracker = RecommenderMetricsTracker()

        perf = tracker.get_algorithm_performance("unknown")

        assert perf.method == "unknown"
        assert perf.total_requests == 0


class TestPerformanceSummary:
    """Test performance summary generation."""

    @patch("discovery.recommender_metrics.recommendation_requests")
    @patch("discovery.recommender_metrics.recommendation_latency")
    @patch("discovery.recommender_metrics.recommendation_diversity")
    def test_get_performance_summary(
        self,
        _mock_diversity: MagicMock,
        _mock_latency: MagicMock,
        _mock_requests: MagicMock,
    ) -> None:
        """Test getting performance summary."""
        tracker = RecommenderMetricsTracker()

        recommendations = [{"similarity_score": 0.9}, {"similarity_score": 0.7}]

        tracker.track_request("collaborative", recommendations, 0.5)
        tracker.track_request("content-based", recommendations, 0.3)
        tracker.track_request("collaborative", [], 0.1, error="timeout")

        summary = tracker.get_performance_summary()

        assert summary["total_requests"] == 3
        assert summary["successful_requests"] == 2
        assert summary["failed_requests"] == 1
        assert summary["success_rate"] == pytest.approx(2 / 3)
        assert summary["avg_latency"] > 0
        assert summary["p95_latency"] > 0
        assert "uptime_seconds" in summary

    def test_get_performance_summary_empty(self) -> None:
        """Test summary with no metrics."""
        tracker = RecommenderMetricsTracker()

        summary = tracker.get_performance_summary()

        assert summary["total_requests"] == 0
        assert summary["success_rate"] == 0.0
        assert summary["avg_latency"] == 0.0


class TestABTesting:
    """Test A/B testing support."""

    def test_assign_ab_test_group(self) -> None:
        """Test assigning A/B test group."""
        tracker = RecommenderMetricsTracker()

        tracker.assign_ab_test_group("user1", "variant_a")
        tracker.assign_ab_test_group("user2", "variant_b")

        assert tracker.ab_test_groups["user1"] == "variant_a"
        assert tracker.ab_test_groups["user2"] == "variant_b"

    @patch("discovery.recommender_metrics.recommendation_requests")
    @patch("discovery.recommender_metrics.recommendation_latency")
    @patch("discovery.recommender_metrics.recommendation_diversity")
    def test_track_ab_test_result(
        self,
        _mock_diversity: MagicMock,
        _mock_latency: MagicMock,
        _mock_requests: MagicMock,
    ) -> None:
        """Test tracking A/B test results."""
        tracker = RecommenderMetricsTracker()

        tracker.assign_ab_test_group("user1", "variant_a")

        recommendations = [{"similarity_score": 0.9}]
        metrics = tracker.track_request("collaborative", recommendations, 0.5)

        tracker.track_ab_test_result("user1", metrics)

        assert "variant_a" in tracker.ab_test_metrics
        assert len(tracker.ab_test_metrics["variant_a"]) == 1

    def test_track_ab_test_result_unassigned_user(self) -> None:
        """Test tracking for unassigned user."""
        tracker = RecommenderMetricsTracker()

        metrics = RecommendationMetrics(method="collaborative", latency_seconds=0.5)

        tracker.track_ab_test_result("unknown_user", metrics)

        # Should not store metrics for unassigned user
        assert len(tracker.ab_test_metrics) == 0

    @patch("discovery.recommender_metrics.recommendation_requests")
    @patch("discovery.recommender_metrics.recommendation_latency")
    @patch("discovery.recommender_metrics.recommendation_diversity")
    def test_get_ab_test_comparison(
        self,
        _mock_diversity: MagicMock,
        _mock_latency: MagicMock,
        _mock_requests: MagicMock,
    ) -> None:
        """Test getting A/B test comparison."""
        tracker = RecommenderMetricsTracker()

        tracker.assign_ab_test_group("user1", "variant_a")
        tracker.assign_ab_test_group("user2", "variant_b")

        recommendations = [{"similarity_score": 0.9}]

        metrics_a = tracker.track_request("collaborative", recommendations, 0.5)
        metrics_b = tracker.track_request("collaborative", recommendations, 0.3)

        tracker.track_ab_test_result("user1", metrics_a)
        tracker.track_ab_test_result("user2", metrics_b)

        comparison = tracker.get_ab_test_comparison()

        assert "variant_a" in comparison
        assert "variant_b" in comparison
        assert comparison["variant_a"]["total_requests"] == 1
        assert comparison["variant_b"]["total_requests"] == 1

    def test_get_ab_test_comparison_empty(self) -> None:
        """Test comparison with no A/B test data."""
        tracker = RecommenderMetricsTracker()

        comparison = tracker.get_ab_test_comparison()

        assert comparison == {}


class TestCoverageCalculation:
    """Test coverage metric calculation."""

    @patch("discovery.recommender_metrics.recommendation_coverage")
    def test_calculate_coverage(self, _mock_coverage: MagicMock) -> None:
        """Test calculating coverage metric."""
        tracker = RecommenderMetricsTracker()
        tracker.algorithm_performance["collaborative"] = AlgorithmPerformance(method="collaborative")

        coverage = tracker.calculate_coverage(total_items=1000, recommendable_items=800, method="collaborative")

        assert coverage == 0.8
        assert tracker.algorithm_performance["collaborative"].coverage == 0.8

    @patch("discovery.recommender_metrics.recommendation_coverage")
    def test_calculate_coverage_zero_total(self, _mock_coverage: MagicMock) -> None:
        """Test coverage with zero total items."""
        tracker = RecommenderMetricsTracker()

        coverage = tracker.calculate_coverage(total_items=0, recommendable_items=0, method="collaborative")

        assert coverage == 0.0

    @patch("discovery.recommender_metrics.recommendation_coverage")
    def test_calculate_coverage_new_method(self, _mock_coverage: MagicMock) -> None:
        """Test coverage for method not yet in performance dict."""
        tracker = RecommenderMetricsTracker()

        coverage = tracker.calculate_coverage(total_items=100, recommendable_items=75, method="new_method")

        assert coverage == 0.75
        # Should not crash even if method not in algorithm_performance


class TestExportMetrics:
    """Test metrics export."""

    @patch("discovery.recommender_metrics.recommendation_requests")
    @patch("discovery.recommender_metrics.recommendation_latency")
    @patch("discovery.recommender_metrics.recommendation_diversity")
    def test_export_metrics(
        self,
        _mock_diversity: MagicMock,
        _mock_latency: MagicMock,
        _mock_requests: MagicMock,
    ) -> None:
        """Test exporting metrics to file."""
        tracker = RecommenderMetricsTracker()

        recommendations = [{"similarity_score": 0.9}]
        tracker.track_request("collaborative", recommendations, 0.5)
        tracker.assign_ab_test_group("user1", "variant_a")

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
            filepath = f.name

        try:
            tracker.export_metrics(filepath)

            # Verify file exists and has valid JSON
            data = json.loads(Path(filepath).read_text())

            assert "summary" in data
            assert "algorithm_performance" in data
            assert "ab_test_comparison" in data
            assert "collaborative" in data["algorithm_performance"]
        finally:
            Path(filepath).unlink()


class TestResetMetrics:
    """Test resetting metrics."""

    @patch("discovery.recommender_metrics.recommendation_requests")
    @patch("discovery.recommender_metrics.recommendation_latency")
    @patch("discovery.recommender_metrics.recommendation_diversity")
    def test_reset_metrics(
        self,
        _mock_diversity: MagicMock,
        _mock_latency: MagicMock,
        _mock_requests: MagicMock,
    ) -> None:
        """Test resetting all metrics."""
        tracker = RecommenderMetricsTracker()

        recommendations = [{"similarity_score": 0.9}]
        tracker.track_request("collaborative", recommendations, 0.5)
        tracker.assign_ab_test_group("user1", "variant_a")

        tracker.reset_metrics()

        assert len(tracker.metrics_history) == 0
        assert len(tracker.algorithm_performance) == 0
        assert len(tracker.ab_test_metrics) == 0
        # Note: ab_test_groups is not cleared by reset_metrics() - preserves A/B test assignments
