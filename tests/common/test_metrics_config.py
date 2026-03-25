"""Tests for metrics configuration fields on ApiConfig."""

from __future__ import annotations

import os
from unittest.mock import patch

from common.config import ApiConfig


def _make_api_config(**overrides: str) -> ApiConfig:
    """Create an ApiConfig with required env vars + overrides."""
    base_env = {
        "POSTGRES_HOST": "localhost",
        "POSTGRES_USERNAME": "test",
        "POSTGRES_PASSWORD": "test",
        "POSTGRES_DATABASE": "test",
        "JWT_SECRET_KEY": "secret",
        "NEO4J_HOST": "localhost",
        "NEO4J_USERNAME": "neo4j",
        "NEO4J_PASSWORD": "pass",
    }
    base_env.update(overrides)
    with patch.dict(os.environ, base_env, clear=False):
        return ApiConfig.from_env()


def test_default_retention_days() -> None:
    config = _make_api_config()
    assert config.metrics_retention_days == 366


def test_default_collection_interval() -> None:
    config = _make_api_config()
    assert config.metrics_collection_interval == 300


def test_custom_retention_days() -> None:
    config = _make_api_config(METRICS_RETENTION_DAYS="90")
    assert config.metrics_retention_days == 90


def test_custom_collection_interval() -> None:
    config = _make_api_config(METRICS_COLLECTION_INTERVAL="60")
    assert config.metrics_collection_interval == 60


def test_invalid_retention_days_uses_default() -> None:
    config = _make_api_config(METRICS_RETENTION_DAYS="abc")
    assert config.metrics_retention_days == 366


def test_invalid_collection_interval_uses_default() -> None:
    config = _make_api_config(METRICS_COLLECTION_INTERVAL="abc")
    assert config.metrics_collection_interval == 300
