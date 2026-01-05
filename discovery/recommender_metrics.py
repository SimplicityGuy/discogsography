"""Performance monitoring and metrics tracking for recommendation algorithms.

This module provides comprehensive metrics tracking for recommendation systems,
including quality metrics, performance metrics, and A/B testing support.
"""

import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import structlog
from prometheus_client import Counter, Gauge, Histogram


logger = structlog.get_logger(__name__)


# Prometheus metrics for recommendation systems
recommendation_requests = Counter(
    "discovery_recommendation_requests_total",
    "Total number of recommendation requests",
    ["method", "strategy"],
)

recommendation_latency = Histogram(
    "discovery_recommendation_latency_seconds",
    "Recommendation request latency",
    ["method", "strategy"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

recommendation_coverage = Gauge(
    "discovery_recommendation_coverage_ratio",
    "Percentage of items that can be recommended",
    ["method"],
)

recommendation_diversity = Gauge(
    "discovery_recommendation_diversity_score",
    "Average diversity score of recommendations",
    ["method"],
)

recommendation_errors = Counter(
    "discovery_recommendation_errors_total",
    "Total number of recommendation errors",
    ["method", "error_type"],
)


@dataclass
class RecommendationMetrics:
    """Metrics for a single recommendation request."""

    method: str
    strategy: str = "default"
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    latency_seconds: float = 0.0
    num_results: int = 0
    diversity_score: float = 0.0
    novelty_score: float = 0.0
    coverage: float = 0.0
    error: str | None = None
    user_feedback: dict[str, Any] = field(default_factory=dict)


@dataclass
class AlgorithmPerformance:
    """Aggregated performance metrics for an algorithm."""

    method: str
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    avg_latency: float = 0.0
    p95_latency: float = 0.0
    p99_latency: float = 0.0
    avg_diversity: float = 0.0
    avg_novelty: float = 0.0
    coverage: float = 0.0
    latencies: list[float] = field(default_factory=list)
    diversity_scores: list[float] = field(default_factory=list)
    novelty_scores: list[float] = field(default_factory=list)


class RecommenderMetricsTracker:
    """Tracker for recommendation system metrics."""

    def __init__(self) -> None:
        """Initialize metrics tracker."""
        self.metrics_history: list[RecommendationMetrics] = []
        self.algorithm_performance: dict[str, AlgorithmPerformance] = {}
        self.start_time = time.time()

        # A/B testing support
        self.ab_test_groups: dict[str, str] = {}  # user_id -> algorithm_variant
        self.ab_test_metrics: dict[str, list[RecommendationMetrics]] = defaultdict(list)

    def track_request(
        self,
        method: str,
        recommendations: list[dict[str, Any]],
        latency: float,
        strategy: str = "default",
        error: str | None = None,
    ) -> RecommendationMetrics:
        """Track a recommendation request.

        Args:
            method: Recommendation method used
            recommendations: List of recommendations returned
            latency: Request latency in seconds
            strategy: Strategy used (for hybrid methods)
            error: Error message if request failed

        Returns:
            Metrics object for this request
        """
        # Calculate diversity score
        diversity = self._calculate_diversity(recommendations)

        # Calculate novelty score (how unexpected the recommendations are)
        novelty = self._calculate_novelty(recommendations)

        # Create metrics object
        metrics = RecommendationMetrics(
            method=method,
            strategy=strategy,
            latency_seconds=latency,
            num_results=len(recommendations),
            diversity_score=diversity,
            novelty_score=novelty,
            error=error,
        )

        # Store in history
        self.metrics_history.append(metrics)

        # Update Prometheus metrics
        recommendation_requests.labels(method=method, strategy=strategy).inc()
        recommendation_latency.labels(method=method, strategy=strategy).observe(latency)

        if diversity > 0:
            recommendation_diversity.labels(method=method).set(diversity)

        if error:
            recommendation_errors.labels(method=method, error_type=error).inc()

        # Update algorithm performance
        self._update_algorithm_performance(metrics)

        logger.info(
            "📊 Tracked recommendation request",
            method=method,
            strategy=strategy,
            latency=f"{latency:.3f}s",
            results=len(recommendations),
            diversity=f"{diversity:.3f}",
        )

        return metrics

    def _calculate_diversity(self, recommendations: list[dict[str, Any]]) -> float:
        """Calculate diversity score for recommendations.

        Diversity measures how different the recommendations are from each other.

        Args:
            recommendations: List of recommendations

        Returns:
            Diversity score (0.0 to 1.0)
        """
        if len(recommendations) < 2:
            return 0.0

        # If recommendations have similarity scores, use them
        # Otherwise, use a simple diversity measure based on unique artists
        if "similarity_score" in recommendations[0]:
            # Calculate pairwise dissimilarity
            scores = [rec["similarity_score"] for rec in recommendations]
            # Higher variance in scores indicates more diversity
            diversity = float(np.std(scores))
            # Normalize to [0, 1]
            return min(diversity, 1.0)

        # Fallback: ratio of unique items
        return 1.0

    def _calculate_novelty(self, recommendations: list[dict[str, Any]]) -> float:
        """Calculate novelty score for recommendations.

        Novelty measures how unexpected or surprising the recommendations are.

        Args:
            recommendations: List of recommendations

        Returns:
            Novelty score (0.0 to 1.0)
        """
        if not recommendations:
            return 0.0

        # If we have similarity scores, lower scores indicate more novelty
        if "similarity_score" in recommendations[0]:
            avg_score = np.mean([rec["similarity_score"] for rec in recommendations])
            # Invert: lower similarity = higher novelty
            novelty = 1.0 - float(avg_score)
            return max(0.0, min(novelty, 1.0))

        return 0.5  # Default neutral novelty

    def _update_algorithm_performance(self, metrics: RecommendationMetrics) -> None:
        """Update aggregated performance metrics for an algorithm.

        Args:
            metrics: Metrics from a single request
        """
        method = metrics.method

        if method not in self.algorithm_performance:
            self.algorithm_performance[method] = AlgorithmPerformance(method=method)

        perf = self.algorithm_performance[method]
        perf.total_requests += 1

        if metrics.error:
            perf.failed_requests += 1
        else:
            perf.successful_requests += 1
            perf.latencies.append(metrics.latency_seconds)
            perf.diversity_scores.append(metrics.diversity_score)
            perf.novelty_scores.append(metrics.novelty_score)

            # Update aggregated metrics
            perf.avg_latency = float(np.mean(perf.latencies))
            perf.p95_latency = float(np.percentile(perf.latencies, 95)) if perf.latencies else 0.0
            perf.p99_latency = float(np.percentile(perf.latencies, 99)) if perf.latencies else 0.0
            perf.avg_diversity = float(np.mean(perf.diversity_scores)) if perf.diversity_scores else 0.0
            perf.avg_novelty = float(np.mean(perf.novelty_scores)) if perf.novelty_scores else 0.0

    def get_algorithm_performance(self, method: str | None = None) -> dict[str, AlgorithmPerformance] | AlgorithmPerformance:
        """Get performance metrics for algorithms.

        Args:
            method: Specific method to get metrics for, or None for all

        Returns:
            Performance metrics for specified method or all methods
        """
        if method:
            return self.algorithm_performance.get(method, AlgorithmPerformance(method=method))
        return self.algorithm_performance

    def get_performance_summary(self) -> dict[str, Any]:
        """Get summary of performance across all algorithms.

        Returns:
            Dictionary with aggregated performance metrics
        """
        total_requests = sum(perf.total_requests for perf in self.algorithm_performance.values())
        total_successful = sum(perf.successful_requests for perf in self.algorithm_performance.values())
        total_failed = sum(perf.failed_requests for perf in self.algorithm_performance.values())

        all_latencies = []
        all_diversity = []
        all_novelty = []

        for perf in self.algorithm_performance.values():
            all_latencies.extend(perf.latencies)
            all_diversity.extend(perf.diversity_scores)
            all_novelty.extend(perf.novelty_scores)

        return {
            "total_requests": total_requests,
            "successful_requests": total_successful,
            "failed_requests": total_failed,
            "success_rate": total_successful / total_requests if total_requests > 0 else 0.0,
            "avg_latency": float(np.mean(all_latencies)) if all_latencies else 0.0,
            "p95_latency": float(np.percentile(all_latencies, 95)) if all_latencies else 0.0,
            "p99_latency": float(np.percentile(all_latencies, 99)) if all_latencies else 0.0,
            "avg_diversity": float(np.mean(all_diversity)) if all_diversity else 0.0,
            "avg_novelty": float(np.mean(all_novelty)) if all_novelty else 0.0,
            "uptime_seconds": time.time() - self.start_time,
        }

    def assign_ab_test_group(self, user_id: str, variant: str) -> None:
        """Assign a user to an A/B test group.

        Args:
            user_id: User identifier
            variant: Algorithm variant to assign
        """
        self.ab_test_groups[user_id] = variant
        logger.info("🔬 Assigned A/B test group", user_id=user_id, variant=variant)

    def track_ab_test_result(self, user_id: str, metrics: RecommendationMetrics) -> None:
        """Track metrics for an A/B test participant.

        Args:
            user_id: User identifier
            metrics: Metrics from recommendation request
        """
        if user_id in self.ab_test_groups:
            variant = self.ab_test_groups[user_id]
            self.ab_test_metrics[variant].append(metrics)

    def get_ab_test_comparison(self) -> dict[str, Any]:
        """Compare performance across A/B test groups.

        Returns:
            Dictionary with comparative metrics for each variant
        """
        comparison: dict[str, Any] = {}

        for variant, metrics_list in self.ab_test_metrics.items():
            if not metrics_list:
                continue

            latencies = [m.latency_seconds for m in metrics_list if not m.error]
            diversity_scores = [m.diversity_score for m in metrics_list if not m.error]
            novelty_scores = [m.novelty_score for m in metrics_list if not m.error]

            comparison[variant] = {
                "total_requests": len(metrics_list),
                "successful_requests": len(latencies),
                "failed_requests": len([m for m in metrics_list if m.error]),
                "avg_latency": float(np.mean(latencies)) if latencies else 0.0,
                "avg_diversity": float(np.mean(diversity_scores)) if diversity_scores else 0.0,
                "avg_novelty": float(np.mean(novelty_scores)) if novelty_scores else 0.0,
            }

        return comparison

    def calculate_coverage(self, total_items: int, recommendable_items: int, method: str) -> float:
        """Calculate and update coverage metric.

        Coverage measures what percentage of items can be recommended.

        Args:
            total_items: Total number of items in catalog
            recommendable_items: Number of items that can be recommended
            method: Recommendation method

        Returns:
            Coverage ratio (0.0 to 1.0)
        """
        if total_items == 0:
            return 0.0

        coverage = recommendable_items / total_items

        # Update Prometheus metric
        recommendation_coverage.labels(method=method).set(coverage)

        # Update algorithm performance
        if method in self.algorithm_performance:
            self.algorithm_performance[method].coverage = coverage

        logger.info(
            "📊 Updated coverage metric",
            method=method,
            coverage=f"{coverage:.2%}",
            recommendable=recommendable_items,
            total=total_items,
        )

        return coverage

    def export_metrics(self, filepath: str) -> None:
        """Export metrics history to a file.

        Args:
            filepath: Path to export metrics to
        """

        metrics_data = {
            "summary": self.get_performance_summary(),
            "algorithm_performance": {
                method: {
                    "method": perf.method,
                    "total_requests": perf.total_requests,
                    "successful_requests": perf.successful_requests,
                    "failed_requests": perf.failed_requests,
                    "avg_latency": perf.avg_latency,
                    "p95_latency": perf.p95_latency,
                    "p99_latency": perf.p99_latency,
                    "avg_diversity": perf.avg_diversity,
                    "avg_novelty": perf.avg_novelty,
                    "coverage": perf.coverage,
                }
                for method, perf in self.algorithm_performance.items()
            },
            "ab_test_comparison": self.get_ab_test_comparison(),
        }

        with Path(filepath).open("w") as f:
            json.dump(metrics_data, f, indent=2, default=str)

        logger.info("💾 Exported metrics to file", filepath=filepath)

    def reset_metrics(self) -> None:
        """Reset all metrics (useful for testing or periodic resets)."""
        self.metrics_history.clear()
        self.algorithm_performance.clear()
        self.ab_test_metrics.clear()
        self.start_time = time.time()
        logger.info("🔄 Reset all metrics")
