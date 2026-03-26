"""Tests for metrics schema table definitions."""

from __future__ import annotations

from postgres_schema import _USER_TABLES


def test_queue_metrics_table_in_schema() -> None:
    """Verify queue_metrics table definition exists in schema."""
    names = [name for name, _ in _USER_TABLES]
    assert "queue_metrics table" in names


def test_service_health_metrics_table_in_schema() -> None:
    """Verify service_health_metrics table definition exists in schema."""
    names = [name for name, _ in _USER_TABLES]
    assert "service_health_metrics table" in names


def test_queue_metrics_index_in_schema() -> None:
    """Verify composite index for queue_metrics exists."""
    names = [name for name, _ in _USER_TABLES]
    assert "idx_queue_metrics_recorded_queue" in names


def test_service_health_metrics_index_in_schema() -> None:
    """Verify composite index for service_health_metrics exists."""
    names = [name for name, _ in _USER_TABLES]
    assert "idx_service_health_recorded_service" in names
