"""Tests for A/B testing framework.

This module tests the A/B testing infrastructure for running experiments
on recommendation algorithms, including test configuration, user assignment,
and statistical analysis.
"""

from datetime import datetime
import json
from unittest.mock import Mock

import pytest

from discovery.ab_testing import (
    ABTestManager,
    ABTestStatus,
    ABTestVariant,
    AssignmentStrategy,
)
from discovery.recommender_metrics import RecommendationMetrics


@pytest.fixture
def metrics_tracker():
    """Mock metrics tracker."""
    return Mock()


@pytest.fixture
def ab_test_manager(metrics_tracker):
    """Create ABTestManager instance."""
    return ABTestManager(metrics_tracker)


@pytest.fixture
def sample_variants():
    """Sample test variants."""
    return [
        ABTestVariant(name="control", description="Original algorithm", weight=1.0),
        ABTestVariant(name="variant_a", description="New algorithm A", weight=1.0),
        ABTestVariant(name="variant_b", description="New algorithm B", weight=1.0),
    ]


@pytest.fixture
def sample_metrics():
    """Sample recommendation metrics."""
    return RecommendationMetrics(
        method="test_method",
        strategy="default",
        latency_seconds=0.5,
        num_results=10,
        diversity_score=0.8,
        novelty_score=0.7,
        error=None,
    )


class TestABTestVariant:
    """Test ABTestVariant dataclass."""

    def test_variant_creation(self):
        """Test creating a test variant."""
        variant = ABTestVariant(
            name="test",
            description="Test variant",
            weight=2.0,
            config={"param": "value"},
        )

        assert variant.name == "test"
        assert variant.description == "Test variant"
        assert variant.weight == 2.0
        assert variant.config == {"param": "value"}

    def test_variant_defaults(self):
        """Test default values for variant."""
        variant = ABTestVariant(name="test", description="Test")

        assert variant.weight == 1.0
        assert variant.config == {}


class TestABTestCreation:
    """Test A/B test creation and validation."""

    def test_create_valid_test(self, ab_test_manager, sample_variants):
        """Test creating a valid A/B test."""
        test = ab_test_manager.create_test(
            test_id="test_001",
            name="Algorithm Comparison",
            description="Compare recommendation algorithms",
            variants=sample_variants,
        )

        assert test.test_id == "test_001"
        assert test.name == "Algorithm Comparison"
        assert test.status == ABTestStatus.DRAFT
        assert len(test.variants) == 3
        assert test.assignment_strategy == AssignmentStrategy.HASH_BASED

        # Verify test is stored
        assert "test_001" in ab_test_manager.tests
        assert ab_test_manager.tests["test_001"] == test

        # Verify subscriptions initialized
        assert "test_001" in ab_test_manager.user_assignments
        assert "test_001" in ab_test_manager.variant_results

    def test_create_test_with_custom_config(self, ab_test_manager, sample_variants):
        """Test creating test with custom configuration."""
        test = ab_test_manager.create_test(
            test_id="test_002",
            name="Custom Test",
            description="Test with custom config",
            variants=sample_variants,
            assignment_strategy=AssignmentStrategy.WEIGHTED,
            min_sample_size=200,
            confidence_level=0.99,
        )

        assert test.assignment_strategy == AssignmentStrategy.WEIGHTED
        assert test.min_sample_size == 200
        assert test.confidence_level == 0.99

    def test_create_duplicate_test_raises_error(self, ab_test_manager, sample_variants):
        """Test that duplicate test IDs raise ValueError."""
        ab_test_manager.create_test(
            test_id="duplicate_test",
            name="First Test",
            description="First test",
            variants=sample_variants,
        )

        with pytest.raises(ValueError, match="Test duplicate_test already exists"):
            ab_test_manager.create_test(
                test_id="duplicate_test",
                name="Second Test",
                description="Second test",
                variants=sample_variants,
            )

    def test_create_test_insufficient_variants(self, ab_test_manager):
        """Test that < 2 variants raises ValueError."""
        single_variant = [ABTestVariant(name="only", description="Only variant")]

        with pytest.raises(ValueError, match="At least 2 variants required"):
            ab_test_manager.create_test(
                test_id="invalid_test",
                name="Invalid Test",
                description="Not enough variants",
                variants=single_variant,
            )

    def test_variant_results_initialized(self, ab_test_manager, sample_variants):
        """Test that variant results are properly initialized."""
        test = ab_test_manager.create_test(
            test_id="test_003",
            name="Results Test",
            description="Test results initialization",
            variants=sample_variants,
        )

        # Check all variants have empty result lists
        for variant in test.variants:
            assert variant.name in ab_test_manager.variant_results["test_003"]
            assert ab_test_manager.variant_results["test_003"][variant.name] == []


class TestTestLifecycle:
    """Test test lifecycle management."""

    def test_start_test(self, ab_test_manager, sample_variants):
        """Test starting an A/B test."""
        test = ab_test_manager.create_test(
            test_id="lifecycle_test",
            name="Lifecycle Test",
            description="Test lifecycle",
            variants=sample_variants,
        )

        assert test.status == ABTestStatus.DRAFT
        assert test.started_at is None

        ab_test_manager.start_test("lifecycle_test")

        assert test.status == ABTestStatus.RUNNING
        assert test.started_at is not None
        assert isinstance(test.started_at, datetime)

    def test_pause_test(self, ab_test_manager, sample_variants):
        """Test pausing an A/B test."""
        test = ab_test_manager.create_test(
            test_id="pause_test",
            name="Pause Test",
            description="Test pausing",
            variants=sample_variants,
        )

        ab_test_manager.start_test("pause_test")
        ab_test_manager.pause_test("pause_test")

        assert test.status == ABTestStatus.PAUSED

    def test_complete_test(self, ab_test_manager, sample_variants):
        """Test completing an A/B test."""
        test = ab_test_manager.create_test(
            test_id="complete_test",
            name="Complete Test",
            description="Test completion",
            variants=sample_variants,
        )

        ab_test_manager.start_test("complete_test")
        ab_test_manager.complete_test("complete_test")

        assert test.status == ABTestStatus.COMPLETED
        assert test.completed_at is not None
        assert isinstance(test.completed_at, datetime)

    def test_lifecycle_transitions(self, ab_test_manager, sample_variants):
        """Test full lifecycle transitions."""
        test = ab_test_manager.create_test(
            test_id="full_lifecycle",
            name="Full Lifecycle",
            description="Complete lifecycle test",
            variants=sample_variants,
        )

        # DRAFT -> RUNNING -> PAUSED -> RUNNING -> COMPLETED
        assert test.status == ABTestStatus.DRAFT

        ab_test_manager.start_test("full_lifecycle")
        assert test.status == ABTestStatus.RUNNING

        ab_test_manager.pause_test("full_lifecycle")
        assert test.status == ABTestStatus.PAUSED

        ab_test_manager.start_test("full_lifecycle")
        assert test.status == ABTestStatus.RUNNING

        ab_test_manager.complete_test("full_lifecycle")
        assert test.status == ABTestStatus.COMPLETED

    def test_start_nonexistent_test_raises_error(self, ab_test_manager):
        """Test that starting nonexistent test raises ValueError."""
        with pytest.raises(ValueError, match="Test nonexistent not found"):
            ab_test_manager.start_test("nonexistent")

    def test_pause_nonexistent_test_raises_error(self, ab_test_manager):
        """Test that pausing nonexistent test raises ValueError."""
        with pytest.raises(ValueError, match="Test nonexistent not found"):
            ab_test_manager.pause_test("nonexistent")

    def test_complete_nonexistent_test_raises_error(self, ab_test_manager):
        """Test that completing nonexistent test raises ValueError."""
        with pytest.raises(ValueError, match="Test nonexistent not found"):
            ab_test_manager.complete_test("nonexistent")


class TestUserAssignment:
    """Test user assignment strategies."""

    def test_hash_based_assignment_deterministic(self, ab_test_manager, sample_variants):
        """Test hash-based assignment is deterministic."""
        ab_test_manager.create_test(
            test_id="hash_test",
            name="Hash Test",
            description="Test hash-based assignment",
            variants=sample_variants,
            assignment_strategy=AssignmentStrategy.HASH_BASED,
        )

        # Same user should get same variant every time
        user_id = "user_12345"
        variant1 = ab_test_manager.assign_user("hash_test", user_id)
        variant2 = ab_test_manager.assign_user("hash_test", user_id)
        variant3 = ab_test_manager.assign_user("hash_test", user_id)

        assert variant1 == variant2 == variant3

    def test_hash_based_assignment_distribution(self, ab_test_manager, sample_variants):
        """Test hash-based assignment distributes users across variants."""
        ab_test_manager.create_test(
            test_id="distribution_test",
            name="Distribution Test",
            description="Test distribution",
            variants=sample_variants,
            assignment_strategy=AssignmentStrategy.HASH_BASED,
        )

        # Assign many users
        variant_counts = {v.name: 0 for v in sample_variants}
        for i in range(1000):
            user_id = f"user_{i}"
            variant = ab_test_manager.assign_user("distribution_test", user_id)
            variant_counts[variant] += 1

        # Each variant should have some users (rough distribution)
        for _variant_name, count in variant_counts.items():
            assert count > 200  # At least 20% per variant
            assert count < 500  # At most 50% per variant

    def test_weighted_assignment(self, ab_test_manager):
        """Test weighted assignment respects weights."""
        # Create variants with different weights
        weighted_variants = [
            ABTestVariant(name="control", description="Control", weight=1.0),
            ABTestVariant(name="variant_a", description="Variant A", weight=2.0),
            ABTestVariant(name="variant_b", description="Variant B", weight=3.0),
        ]

        ab_test_manager.create_test(
            test_id="weighted_test",
            name="Weighted Test",
            description="Test weighted assignment",
            variants=weighted_variants,
            assignment_strategy=AssignmentStrategy.WEIGHTED,
        )

        # Assign many users and check distribution
        variant_counts = {v.name: 0 for v in weighted_variants}
        for i in range(3000):
            user_id = f"user_{i}"
            variant = ab_test_manager.assign_user("weighted_test", user_id)
            variant_counts[variant] += 1

        # Weights are 1:2:3, so roughly 16.7%, 33.3%, 50% distribution
        # Allow some variance
        assert variant_counts["control"] < variant_counts["variant_a"]
        assert variant_counts["variant_a"] < variant_counts["variant_b"]

    def test_random_assignment(self, ab_test_manager, sample_variants):
        """Test random assignment."""
        ab_test_manager.create_test(
            test_id="random_test",
            name="Random Test",
            description="Test random assignment",
            variants=sample_variants,
            assignment_strategy=AssignmentStrategy.RANDOM,
        )

        # Assign many users
        variant_counts = {v.name: 0 for v in sample_variants}
        for i in range(1000):
            user_id = f"user_{i}"
            variant = ab_test_manager.assign_user("random_test", user_id)
            variant_counts[variant] += 1

        # All variants should have some users
        for _variant_name, count in variant_counts.items():
            assert count > 200  # At least 20% per variant

    def test_user_reassignment_consistent(self, ab_test_manager, sample_variants):
        """Test that reassigning same user returns same variant."""
        ab_test_manager.create_test(
            test_id="reassignment_test",
            name="Reassignment Test",
            description="Test reassignment",
            variants=sample_variants,
        )

        user_id = "consistent_user"
        variant1 = ab_test_manager.assign_user("reassignment_test", user_id)
        variant2 = ab_test_manager.assign_user("reassignment_test", user_id)

        assert variant1 == variant2

    def test_assign_user_nonexistent_test(self, ab_test_manager):
        """Test assigning user to nonexistent test raises error."""
        with pytest.raises(ValueError, match="Test nonexistent not found"):
            ab_test_manager.assign_user("nonexistent", "user_123")


class TestResultsTracking:
    """Test metrics tracking and results."""

    def test_track_results(self, ab_test_manager, sample_variants, sample_metrics):
        """Test tracking recommendation metrics."""
        ab_test_manager.create_test(
            test_id="tracking_test",
            name="Tracking Test",
            description="Test metrics tracking",
            variants=sample_variants,
        )

        user_id = "tracked_user"
        variant = ab_test_manager.assign_user("tracking_test", user_id)
        ab_test_manager.track_result("tracking_test", user_id, sample_metrics)

        # Verify metrics stored in correct variant
        assert len(ab_test_manager.variant_results["tracking_test"][variant]) == 1
        assert ab_test_manager.variant_results["tracking_test"][variant][0] == sample_metrics

    def test_track_multiple_results(self, ab_test_manager, sample_variants, sample_metrics):
        """Test tracking multiple results for same user."""
        ab_test_manager.create_test(
            test_id="multi_track_test",
            name="Multi Track Test",
            description="Test multiple tracking",
            variants=sample_variants,
        )

        user_id = "multi_user"
        variant = ab_test_manager.assign_user("multi_track_test", user_id)

        # Track multiple metrics
        for _i in range(5):
            ab_test_manager.track_result("multi_track_test", user_id, sample_metrics)

        assert len(ab_test_manager.variant_results["multi_track_test"][variant]) == 5

    def test_track_result_nonexistent_test(self, ab_test_manager, sample_metrics):
        """Test tracking result for nonexistent test raises error."""
        with pytest.raises(ValueError, match="Test nonexistent not found"):
            ab_test_manager.track_result("nonexistent", "user_123", sample_metrics)

    def test_track_result_unassigned_user(self, ab_test_manager, sample_variants, sample_metrics):
        """Test tracking result for unassigned user raises error."""
        ab_test_manager.create_test(
            test_id="unassigned_test",
            name="Unassigned Test",
            description="Test unassigned user",
            variants=sample_variants,
        )

        with pytest.raises(ValueError, match="User unassigned_user not assigned"):
            ab_test_manager.track_result("unassigned_test", "unassigned_user", sample_metrics)

    def test_get_test_results_no_data(self, ab_test_manager, sample_variants):
        """Test getting results when no data collected."""
        ab_test_manager.create_test(
            test_id="no_data_test",
            name="No Data Test",
            description="Test with no data",
            variants=sample_variants,
        )

        results = ab_test_manager.get_test_results("no_data_test")

        assert results["test_id"] == "no_data_test"
        assert results["name"] == "No Data Test"
        assert results["status"] == ABTestStatus.DRAFT

        # All variants should show no data
        for variant in sample_variants:
            assert results["variants"][variant.name]["sample_size"] == 0
            assert "No data collected yet" in results["variants"][variant.name]["message"]

    def test_get_test_results_with_data(self, ab_test_manager, sample_variants):
        """Test getting results summary with data."""
        ab_test_manager.create_test(
            test_id="data_test",
            name="Data Test",
            description="Test with data",
            variants=sample_variants,
        )

        # Add some metrics to each variant
        for variant in sample_variants:
            user_id = f"user_{variant.name}"
            ab_test_manager.user_assignments["data_test"][user_id] = variant.name

            metrics = RecommendationMetrics(
                method="test",
                strategy="default",
                num_results=10,
                latency_seconds=0.5 if variant.name == "control" else 0.3,
                diversity_score=0.7 if variant.name == "control" else 0.9,
                novelty_score=0.6 if variant.name == "control" else 0.8,
                error=None,
            )
            ab_test_manager.variant_results["data_test"][variant.name].append(metrics)

        results = ab_test_manager.get_test_results("data_test")

        # Check control variant
        assert results["variants"]["control"]["sample_size"] == 1
        assert results["variants"]["control"]["successful_requests"] == 1
        assert results["variants"]["control"]["avg_latency"] == 0.5
        assert results["variants"]["control"]["avg_diversity"] == 0.7

        # Check variant_a
        assert results["variants"]["variant_a"]["avg_latency"] == 0.3
        assert results["variants"]["variant_a"]["avg_diversity"] == 0.9

    def test_get_test_results_nonexistent_test(self, ab_test_manager):
        """Test getting results for nonexistent test raises error."""
        with pytest.raises(ValueError, match="Test nonexistent not found"):
            ab_test_manager.get_test_results("nonexistent")


class TestExportResults:
    """Test exporting test results."""

    def test_export_test_results(self, ab_test_manager, sample_variants, tmp_path):
        """Test exporting test results to file."""
        ab_test_manager.create_test(
            test_id="export_test",
            name="Export Test",
            description="Test export functionality",
            variants=sample_variants,
        )

        # Add some data
        user_id = "export_user"
        ab_test_manager.assign_user("export_test", user_id)
        metrics = RecommendationMetrics(
            method="test",
            strategy="default",
            num_results=10,
            latency_seconds=0.5,
            diversity_score=0.8,
            novelty_score=0.7,
            error=None,
        )
        ab_test_manager.track_result("export_test", user_id, metrics)

        # Export
        export_path = tmp_path / "test_results.json"
        ab_test_manager.export_test_results("export_test", str(export_path))

        # Verify file created
        assert export_path.exists()

        # Load and verify content
        with export_path.open() as f:
            data = json.load(f)

        assert "test_results" in data
        assert "recommendation" in data
        assert "exported_at" in data
        assert data["test_results"]["test_id"] == "export_test"


class TestStatisticalAnalysis:
    """Test statistical significance calculations."""

    def test_calculate_significance_insufficient_data(self, ab_test_manager, sample_variants):
        """Test significance calculation with insufficient data."""
        ab_test_manager.create_test(
            test_id="insufficient_test",
            name="Insufficient Test",
            description="Test with insufficient data",
            variants=sample_variants,
            min_sample_size=100,
        )

        results = ab_test_manager.calculate_statistical_significance("insufficient_test")

        assert results["test_id"] == "insufficient_test"
        assert results["metric"] == "latency"

        # Should have comparisons but with insufficient sample size messages
        assert len(results["comparisons"]) > 0

    def test_get_recommendation_insufficient_data(self, ab_test_manager, sample_variants):
        """Test getting recommendation with insufficient data."""
        ab_test_manager.create_test(
            test_id="rec_insufficient_test",
            name="Recommendation Insufficient Test",
            description="Test recommendation with insufficient data",
            variants=sample_variants,
            min_sample_size=100,
        )

        recommendation = ab_test_manager.get_recommendation("rec_insufficient_test")

        assert recommendation["recommendation"] == "continue_collecting"
        assert "Insufficient sample size" in recommendation["reason"]
        assert "current_samples" in recommendation
        assert recommendation["min_required"] == 100

    def test_get_recommendation_nonexistent_test(self, ab_test_manager):
        """Test getting recommendation for nonexistent test raises error."""
        with pytest.raises(ValueError, match="Test nonexistent not found"):
            ab_test_manager.get_recommendation("nonexistent")
