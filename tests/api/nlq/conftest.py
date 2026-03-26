"""Shared fixtures for NLQ tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_neo4j_driver() -> MagicMock:
    """Mock Neo4j driver for NLQ tool tests."""
    return MagicMock()


@pytest.fixture
def mock_pg_pool() -> MagicMock:
    """Mock PostgreSQL pool for NLQ tool tests."""
    return MagicMock()


@pytest.fixture
def mock_redis_client() -> AsyncMock:
    """Mock Redis client for NLQ tool tests."""
    redis: AsyncMock = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock()
    return redis
