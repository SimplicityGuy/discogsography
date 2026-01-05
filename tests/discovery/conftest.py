"""Discovery service test configuration and fixtures."""

import os
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient


# Set environment variables before any imports
# This ensures discovery modules can initialize properly during import
# These defaults match those in tests/conftest.py setup_test_env
os.environ.setdefault("AMQP_CONNECTION", "amqp://test:test@localhost:5672/")
os.environ.setdefault("DISCOGS_ROOT", "/tmp/test-discogs")  # noqa: S108
os.environ.setdefault("NEO4J_ADDRESS", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USERNAME", "test")
os.environ.setdefault("NEO4J_PASSWORD", "test")
os.environ.setdefault("POSTGRES_ADDRESS", "localhost:5432")
os.environ.setdefault("POSTGRES_USERNAME", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("POSTGRES_DATABASE", "test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("PERIODIC_CHECK_DAYS", "15")


@pytest.fixture(autouse=True)
def mock_discovery_dependencies() -> Generator[None]:
    """Mock all discovery service dependencies for testing."""
    with (
        patch("discovery.cache.cache_manager") as mock_cache,
        patch("discovery.playground_api.playground_api") as mock_playground,
        patch("discovery.discovery.get_config") as mock_config,
        patch("discovery.api_ml.ml_api_initialized", True),
        patch("discovery.api_search.search_api_initialized", True),
        patch("discovery.api_graph.graph_api_initialized", True),
        patch("discovery.api_realtime.realtime_api_initialized", True),
    ):
        # Mock cache manager
        mock_cache.initialize = AsyncMock()
        mock_cache.close = AsyncMock()
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock(return_value=True)
        mock_cache.connected = False

        # Mock playground API
        mock_playground.initialize = AsyncMock()
        mock_playground.close = AsyncMock()

        # Mock config
        mock_config.return_value = MagicMock()

        yield


@pytest.fixture
def discovery_client() -> TestClient:
    """Create a test client for the discovery service."""
    from discovery.discovery import app

    return TestClient(app)


@pytest_asyncio.fixture
async def mock_neo4j_driver() -> MagicMock:
    """Mock Neo4j driver for testing."""
    mock_driver = MagicMock()
    mock_session = AsyncMock()

    # Configure session context manager
    mock_context_manager = AsyncMock()
    mock_context_manager.__aenter__ = AsyncMock(return_value=mock_session)
    mock_context_manager.__aexit__ = AsyncMock(return_value=None)
    mock_driver.session.return_value = mock_context_manager

    # Configure driver close method to be async
    mock_driver.close = AsyncMock()

    # Mock query results
    mock_result = AsyncMock()
    mock_result.__aiter__.return_value = iter([])
    mock_session.run.return_value = mock_result
    mock_session.run = AsyncMock(return_value=mock_result)

    return mock_driver


@pytest_asyncio.fixture
async def mock_postgres_engine() -> AsyncMock:
    """Mock PostgreSQL engine for testing."""
    mock_engine = AsyncMock()
    return mock_engine


@pytest.fixture
def mock_recommender() -> AsyncMock:
    """Mock music recommender for testing."""
    mock = AsyncMock()
    mock.initialize = AsyncMock()
    mock.close = AsyncMock()
    mock.get_similar_artists.return_value = []
    mock.get_trending_music.return_value = []
    mock.discovery_search.return_value = []
    return mock


@pytest.fixture
def mock_analytics() -> AsyncMock:
    """Mock analytics engine for testing."""
    mock = AsyncMock()
    mock.initialize = AsyncMock()
    mock.close = AsyncMock()
    mock.analyze_genre_trends.return_value = {
        "chart_type": "line",
        "chart_data": {},
        "insights": [],
        "metadata": {},
    }
    return mock


@pytest.fixture
def mock_graph_explorer() -> AsyncMock:
    """Mock graph explorer for testing."""
    mock = AsyncMock()
    mock.initialize = AsyncMock()
    mock.close = AsyncMock()
    mock.search_nodes.return_value = {"nodes": [], "edges": [], "metadata": {}}
    return mock


@pytest.fixture
def sample_recommendation_data() -> list[dict[str, Any]]:
    """Sample recommendation data for testing."""
    return [
        {
            "artist_name": "John Coltrane",
            "release_title": "A Love Supreme",
            "year": 1965,
            "genres": ["Jazz"],
            "similarity_score": 0.85,
            "explanation": "Similar jazz style and era",
            "neo4j_id": "artist_123",
        },
        {
            "artist_name": "Bill Evans",
            "release_title": "Waltz for Debby",
            "year": 1961,
            "genres": ["Jazz"],
            "similarity_score": 0.78,
            "explanation": "Similar improvisation style",
            "neo4j_id": "artist_456",
        },
    ]


@pytest.fixture
def sample_analytics_data() -> dict[str, Any]:
    """Sample analytics data for testing."""
    return {
        "chart_type": "line",
        "chart_data": {
            "data": [
                {
                    "x": [1990, 1995, 2000, 2005, 2010],
                    "y": [100, 150, 200, 180, 220],
                    "name": "Jazz",
                    "type": "scatter",
                    "mode": "lines+markers",
                }
            ],
            "layout": {
                "title": "Genre Trends Over Time",
                "xaxis": {"title": "Year"},
                "yaxis": {"title": "Number of Releases"},
            },
        },
        "insights": [
            "Jazz peaked in 2010 with 220 releases",
            "Steady growth from 1990 to 2000",
            "Slight decline in 2005",
        ],
        "metadata": {"time_range": [1990, 2010], "total_records": 850},
    }


@pytest.fixture
def sample_graph_data() -> dict[str, Any]:
    """Sample graph data for testing."""
    return {
        "nodes": [
            {
                "id": "artist_123",
                "label": "Artist",
                "name": "Miles Davis",
                "properties": {"real_name": "Miles Dewey Davis III"},
                "size": 20,
                "color": "#ff6b6b",
            },
            {
                "id": "release_456",
                "label": "Release",
                "name": "Kind of Blue",
                "properties": {"year": 1959},
                "size": 15,
                "color": "#4ecdc4",
            },
        ],
        "edges": [
            {
                "id": "rel_789",
                "source": "artist_123",
                "target": "release_456",
                "label": "BY",
                "properties": {},
                "weight": 1.0,
            }
        ],
        "metadata": {"query_type": "expand", "total_nodes": 2, "total_edges": 1},
    }
