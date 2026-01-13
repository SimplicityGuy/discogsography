"""A/B testing framework for recommendation algorithms.

This module provides infrastructure for running A/B tests on recommendation
algorithms, including test configuration, user assignment, and statistical analysis.
"""

import hashlib
import json
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np
import structlog
from scipy import stats

from discovery.recommender_metrics import RecommendationMetrics, RecommenderMetricsTracker


logger = structlog.get_logger(__name__)


class ABTestStatus(str, Enum):
    """Status of an A/B test."""

    DRAFT = "draft"  # Test is being configured
    RUNNING = "running"  # Test is actively collecting data
    PAUSED = "paused"  # Test is paused
    COMPLETED = "completed"  # Test has finished
    CANCELLED = "cancelled"  # Test was cancelled


class AssignmentStrategy(str, Enum):
    """Strategy for assigning users to test groups."""

    RANDOM = "random"  # Random assignment
    HASH_BASED = "hash_based"  # Deterministic hash-based assignment
    WEIGHTED = "weighted"  # Weighted random assignment


@dataclass
class ABTestVariant:
    """Configuration for a test variant."""

    name: str
    description: str
    weight: float = 1.0  # Relative weight for traffic allocation
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class ABTest:
    """Configuration for an A/B test."""

    test_id: str
    name: str
    description: str
    variants: list[ABTestVariant]
    status: ABTestStatus = ABTestStatus.DRAFT
    assignment_strategy: AssignmentStrategy = AssignmentStrategy.HASH_BASED
    min_sample_size: int = 100  # Minimum samples per variant
    confidence_level: float = 0.95  # Statistical confidence level
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ABTestManager:
    """Manager for A/B tests on recommendation algorithms."""

    def __init__(self, metrics_tracker: RecommenderMetricsTracker) -> None:
        """Initialize A/B test manager.

        Args:
            metrics_tracker: Metrics tracker instance
        """
        self.metrics_tracker = metrics_tracker
        self.tests: dict[str, ABTest] = {}
        self.user_assignments: dict[str, dict[str, str]] = {}  # test_id -> {user_id -> variant}
        self.variant_results: dict[str, dict[str, list[RecommendationMetrics]]] = {}  # test_id -> {variant -> metrics}

    def create_test(
        self,
        test_id: str,
        name: str,
        description: str,
        variants: list[ABTestVariant],
        assignment_strategy: AssignmentStrategy = AssignmentStrategy.HASH_BASED,
        min_sample_size: int = 100,
        confidence_level: float = 0.95,
    ) -> ABTest:
        """Create a new A/B test.

        Args:
            test_id: Unique identifier for the test
            name: Human-readable test name
            description: Test description
            variants: List of test variants
            assignment_strategy: Strategy for assigning users
            min_sample_size: Minimum samples per variant
            confidence_level: Statistical confidence level

        Returns:
            Created test configuration
        """
        if test_id in self.tests:
            raise ValueError(f"Test {test_id} already exists")

        if len(variants) < 2:
            raise ValueError("At least 2 variants required for A/B test")

        test = ABTest(
            test_id=test_id,
            name=name,
            description=description,
            variants=variants,
            assignment_strategy=assignment_strategy,
            min_sample_size=min_sample_size,
            confidence_level=confidence_level,
        )

        self.tests[test_id] = test
        self.user_assignments[test_id] = {}
        self.variant_results[test_id] = {variant.name: [] for variant in variants}

        logger.info(
            "🔬 Created A/B test",
            test_id=test_id,
            name=name,
            variants=[v.name for v in variants],
        )

        return test

    def start_test(self, test_id: str) -> None:
        """Start an A/B test.

        Args:
            test_id: Test identifier
        """
        if test_id not in self.tests:
            raise ValueError(f"Test {test_id} not found")

        test = self.tests[test_id]
        test.status = ABTestStatus.RUNNING
        test.started_at = datetime.now(UTC)

        logger.info("▶️ Started A/B test", test_id=test_id, name=test.name)

    def pause_test(self, test_id: str) -> None:
        """Pause an A/B test.

        Args:
            test_id: Test identifier
        """
        if test_id not in self.tests:
            raise ValueError(f"Test {test_id} not found")

        test = self.tests[test_id]
        test.status = ABTestStatus.PAUSED

        logger.info("⏸️ Paused A/B test", test_id=test_id, name=test.name)

    def complete_test(self, test_id: str) -> None:
        """Complete an A/B test.

        Args:
            test_id: Test identifier
        """
        if test_id not in self.tests:
            raise ValueError(f"Test {test_id} not found")

        test = self.tests[test_id]
        test.status = ABTestStatus.COMPLETED
        test.completed_at = datetime.now(UTC)

        logger.info("✅ Completed A/B test", test_id=test_id, name=test.name)

    def assign_user(self, test_id: str, user_id: str) -> str:
        """Assign a user to a test variant.

        Args:
            test_id: Test identifier
            user_id: User identifier

        Returns:
            Assigned variant name
        """
        if test_id not in self.tests:
            raise ValueError(f"Test {test_id} not found")

        # Check if user already assigned
        if user_id in self.user_assignments[test_id]:
            return self.user_assignments[test_id][user_id]

        test = self.tests[test_id]

        # Assign based on strategy
        if test.assignment_strategy == AssignmentStrategy.HASH_BASED:
            variant = self._hash_based_assignment(test, user_id)
        elif test.assignment_strategy == AssignmentStrategy.WEIGHTED:
            variant = self._weighted_assignment(test)
        else:  # RANDOM
            variant = random.choice(test.variants).name  # noqa: S311  # nosec B311

        self.user_assignments[test_id][user_id] = variant

        logger.debug(
            "👤 Assigned user to variant",
            test_id=test_id,
            user_id=user_id,
            variant=variant,
        )

        return variant

    def _hash_based_assignment(self, test: ABTest, user_id: str) -> str:
        """Deterministic hash-based user assignment.

        Args:
            test: Test configuration
            user_id: User identifier

        Returns:
            Assigned variant name
        """
        # Create hash from test_id + user_id for deterministic assignment
        hash_input = f"{test.test_id}:{user_id}"
        hash_value = int(hashlib.md5(hash_input.encode(), usedforsecurity=False).hexdigest(), 16)

        # Calculate total weight
        total_weight = sum(v.weight for v in test.variants)

        # Normalize hash to [0, total_weight)
        normalized_value = (hash_value % 10000) / 10000 * total_weight

        # Assign to variant based on weight ranges
        cumulative_weight = 0.0
        for variant in test.variants:
            cumulative_weight += variant.weight
            if normalized_value < cumulative_weight:
                return variant.name

        # Fallback to first variant
        return test.variants[0].name

    def _weighted_assignment(self, test: ABTest) -> str:
        """Weighted random user assignment.

        Args:
            test: Test configuration

        Returns:
            Assigned variant name
        """
        weights = [v.weight for v in test.variants]
        return random.choices(test.variants, weights=weights, k=1)[0].name  # noqa: S311  # nosec B311

    def track_result(self, test_id: str, user_id: str, metrics: RecommendationMetrics) -> None:
        """Track metrics for a test participant.

        Args:
            test_id: Test identifier
            user_id: User identifier
            metrics: Recommendation metrics
        """
        if test_id not in self.tests:
            raise ValueError(f"Test {test_id} not found")

        if user_id not in self.user_assignments[test_id]:
            raise ValueError(f"User {user_id} not assigned to test {test_id}")

        variant = self.user_assignments[test_id][user_id]
        self.variant_results[test_id][variant].append(metrics)

    def get_test_results(self, test_id: str) -> dict[str, Any]:
        """Get results summary for a test.

        Args:
            test_id: Test identifier

        Returns:
            Dictionary with test results
        """
        if test_id not in self.tests:
            raise ValueError(f"Test {test_id} not found")

        test = self.tests[test_id]
        results: dict[str, Any] = {
            "test_id": test_id,
            "name": test.name,
            "status": test.status,
            "started_at": test.started_at,
            "completed_at": test.completed_at,
            "variants": {},
        }

        # Calculate metrics for each variant
        for variant in test.variants:
            metrics_list = self.variant_results[test_id][variant.name]

            if not metrics_list:
                results["variants"][variant.name] = {
                    "sample_size": 0,
                    "message": "No data collected yet",
                }
                continue

            successful_metrics = [m for m in metrics_list if not m.error]

            latencies = [m.latency_seconds for m in successful_metrics]
            diversity_scores = [m.diversity_score for m in successful_metrics]
            novelty_scores = [m.novelty_score for m in successful_metrics]

            results["variants"][variant.name] = {
                "sample_size": len(metrics_list),
                "successful_requests": len(successful_metrics),
                "failed_requests": len(metrics_list) - len(successful_metrics),
                "avg_latency": float(np.mean(latencies)) if latencies else 0.0,
                "std_latency": float(np.std(latencies)) if latencies else 0.0,
                "avg_diversity": float(np.mean(diversity_scores)) if diversity_scores else 0.0,
                "std_diversity": float(np.std(diversity_scores)) if diversity_scores else 0.0,
                "avg_novelty": float(np.mean(novelty_scores)) if novelty_scores else 0.0,
                "std_novelty": float(np.std(novelty_scores)) if novelty_scores else 0.0,
            }

        return results

    def calculate_statistical_significance(
        self,
        test_id: str,
        metric: str = "latency",
    ) -> dict[str, Any]:
        """Calculate statistical significance between variants.

        Args:
            test_id: Test identifier
            metric: Metric to analyze ('latency', 'diversity', 'novelty')

        Returns:
            Statistical significance results
        """
        if test_id not in self.tests:
            raise ValueError(f"Test {test_id} not found")

        test = self.tests[test_id]
        results: dict[str, Any] = {
            "test_id": test_id,
            "metric": metric,
            "comparisons": [],
        }

        # Get metric values for each variant
        variant_values: dict[str, list[float]] = {}

        for variant in test.variants:
            metrics_list = self.variant_results[test_id][variant.name]
            successful = [m for m in metrics_list if not m.error]

            if metric == "latency":
                values = [m.latency_seconds for m in successful]
            elif metric == "diversity":
                values = [m.diversity_score for m in successful]
            elif metric == "novelty":
                values = [m.novelty_score for m in successful]
            else:
                raise ValueError(f"Unknown metric: {metric}")

            variant_values[variant.name] = values

        # Perform pairwise t-tests
        variant_names = list(variant_values.keys())
        for i, variant_a in enumerate(variant_names):
            for variant_b in variant_names[i + 1 :]:
                values_a = variant_values[variant_a]
                values_b = variant_values[variant_b]

                if len(values_a) < test.min_sample_size or len(values_b) < test.min_sample_size:
                    results["comparisons"].append(
                        {
                            "variant_a": variant_a,
                            "variant_b": variant_b,
                            "message": "Insufficient sample size",
                            "sample_size_a": len(values_a),
                            "sample_size_b": len(values_b),
                            "min_required": test.min_sample_size,
                        }
                    )
                    continue

                # Perform two-sample t-test
                t_stat, p_value = stats.ttest_ind(values_a, values_b)

                # Calculate effect size (Cohen's d)
                mean_a = np.mean(values_a)
                mean_b = np.mean(values_b)
                pooled_std = np.sqrt((np.var(values_a) + np.var(values_b)) / 2)
                cohens_d = (mean_a - mean_b) / pooled_std if pooled_std > 0 else 0

                significant = p_value < (1 - test.confidence_level)

                results["comparisons"].append(
                    {
                        "variant_a": variant_a,
                        "variant_b": variant_b,
                        "mean_a": float(mean_a),
                        "mean_b": float(mean_b),
                        "t_statistic": float(t_stat),
                        "p_value": float(p_value),
                        "cohens_d": float(cohens_d),
                        "significant": significant,
                        "confidence_level": test.confidence_level,
                    }
                )

        return results

    def get_recommendation(self, test_id: str) -> dict[str, Any]:
        """Get recommendation on which variant to deploy.

        Args:
            test_id: Test identifier

        Returns:
            Recommendation with reasoning
        """
        if test_id not in self.tests:
            raise ValueError(f"Test {test_id} not found")

        test = self.tests[test_id]
        test_results = self.get_test_results(test_id)

        # Check if we have enough data
        insufficient_data = any(variant_data.get("sample_size", 0) < test.min_sample_size for variant_data in test_results["variants"].values())

        if insufficient_data:
            return {
                "recommendation": "continue_collecting",
                "reason": "Insufficient sample size for statistical significance",
                "current_samples": {variant: data.get("sample_size", 0) for variant, data in test_results["variants"].items()},
                "min_required": test.min_sample_size,
            }

        # Analyze multiple metrics
        metrics_analysis = {}
        for metric in ["latency", "diversity", "novelty"]:
            sig_results = self.calculate_statistical_significance(test_id, metric)
            metrics_analysis[metric] = sig_results

        # Simple recommendation: choose variant with best average performance
        # (In production, you'd want more sophisticated decision logic)
        variant_scores: dict[str, float] = {}

        for variant_name, variant_data in test_results["variants"].items():
            # Lower latency is better, higher diversity and novelty is better
            score = (
                -variant_data.get("avg_latency", float("inf")) * 0.3
                + variant_data.get("avg_diversity", 0) * 0.35
                + variant_data.get("avg_novelty", 0) * 0.35
            )
            variant_scores[variant_name] = score

        best_variant = max(variant_scores.items(), key=lambda x: x[1])

        return {
            "recommendation": "deploy_variant",
            "variant": best_variant[0],
            "score": best_variant[1],
            "all_scores": variant_scores,
            "statistical_analysis": metrics_analysis,
            "reason": f"Variant {best_variant[0]} shows best overall performance across metrics",
        }

    def export_test_results(self, test_id: str, filepath: str) -> None:
        """Export test results to a file.

        Args:
            test_id: Test identifier
            filepath: Path to export results to
        """

        test_results = self.get_test_results(test_id)
        recommendation = self.get_recommendation(test_id)

        export_data = {
            "test_results": test_results,
            "recommendation": recommendation,
            "exported_at": datetime.now(UTC).isoformat(),
        }

        with Path(filepath).open("w") as f:
            json.dump(export_data, f, indent=2, default=str)

        logger.info("💾 Exported test results", test_id=test_id, filepath=filepath)
