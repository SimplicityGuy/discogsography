"""Tests for NLQ configuration."""

import os
from unittest.mock import patch

from api.nlq.config import NLQConfig


class TestNLQConfig:
    """NLQ configuration loading from environment."""

    def test_defaults(self) -> None:
        config = NLQConfig()
        assert config.enabled is False
        assert config.api_key is None
        assert config.model == "claude-sonnet-4-20250514"
        assert config.max_iterations == 5
        assert config.max_query_length == 500
        assert config.cache_ttl == 3600
        assert config.rate_limit == "10/minute"

    def test_from_env_enabled(self) -> None:
        env = {
            "NLQ_ENABLED": "true",
            "NLQ_API_KEY": "sk-ant-test-key",
            "NLQ_MODEL": "claude-haiku-4-5-20251001",
        }
        with patch.dict(os.environ, env):
            config = NLQConfig.from_env()
        assert config.enabled is True
        assert config.api_key == "sk-ant-test-key"
        assert config.model == "claude-haiku-4-5-20251001"

    def test_from_env_disabled_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            config = NLQConfig.from_env()
        assert config.enabled is False

    def test_is_available_requires_enabled_and_key(self) -> None:
        assert NLQConfig(enabled=False, api_key="sk-test").is_available is False
        assert NLQConfig(enabled=True, api_key=None).is_available is False
        assert NLQConfig(enabled=True, api_key="sk-test").is_available is True
