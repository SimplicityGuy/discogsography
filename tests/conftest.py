"""Shared pytest fixtures and configuration."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from aio_pika.abc import AbstractChannel, AbstractConnection, AbstractQueue


# Let pytest-asyncio handle the event loop automatically


@pytest.fixture
def mock_amqp_connection() -> AsyncMock:
    """Mock AMQP connection for testing."""
    mock_conn = AsyncMock(spec=AbstractConnection)
    mock_channel = AsyncMock(spec=AbstractChannel)
    mock_queue = AsyncMock(spec=AbstractQueue)

    # Setup mock returns
    mock_conn.channel.return_value = mock_channel
    mock_channel.declare_queue.return_value = mock_queue
    mock_channel.declare_exchange.return_value = AsyncMock()

    return mock_conn


@pytest.fixture
def mock_neo4j_driver() -> MagicMock:
    """Mock Neo4j driver for testing."""
    mock_driver = MagicMock()
    mock_session = AsyncMock()

    # Configure async context manager for session
    mock_context_manager = AsyncMock()
    mock_context_manager.__aenter__ = AsyncMock(return_value=mock_session)
    mock_context_manager.__aexit__ = AsyncMock(return_value=None)

    # For async with await graph.session() pattern:
    # session() should return an awaitable that returns the context manager
    async def mock_session_factory(*_args: Any, **_kwargs: Any) -> Any:
        return mock_context_manager

    mock_driver.session = MagicMock(side_effect=mock_session_factory)

    # Setup mock returns
    mock_session.execute_write = AsyncMock(return_value=True)
    mock_session.run.return_value.single.return_value = None
    mock_session.close = AsyncMock()
    mock_driver.close = AsyncMock()

    return mock_driver


@pytest.fixture
def mock_postgres_connection() -> MagicMock:
    """Mock PostgreSQL connection for testing."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()

    # Setup mock returns
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_cursor.fetchone.return_value = None

    return mock_conn


@pytest_asyncio.fixture
async def mock_postgres_engine() -> AsyncMock:
    """Mock PostgreSQL engine for testing."""
    mock_engine = AsyncMock()
    return mock_engine


@pytest.fixture
def temp_dir(tmp_path: Path) -> Path:
    """Create temporary directory for test files."""
    return tmp_path


@pytest.fixture
def sample_artist_data() -> dict[str, Any]:
    """Sample artist data for testing."""
    return {
        "id": "123456",
        "name": "Test Artist",
        "sha256": "abc123def456",
        "members": {"name": [{"@id": "234567", "#text": "Member 1"}, {"@id": "345678", "#text": "Member 2"}]},
        "aliases": {"name": [{"@id": "456789", "#text": "Alias 1"}]},
    }


@pytest.fixture
def sample_label_data() -> dict[str, Any]:
    """Sample label data for testing."""
    return {
        "id": "987654",
        "name": "Test Label",
        "sha256": "fed321cba654",
        "parentLabel": {"@id": "876543"},
        "sublabels": {"label": [{"@id": "765432"}]},
    }


@pytest.fixture
def sample_release_data() -> dict[str, Any]:
    """Sample release data for testing."""
    return {
        "id": "112233",
        "title": "Test Release",
        "sha256": "112233445566",
        "artists": {"artist": [{"id": "123456", "name": "Test Artist"}]},
        "labels": {"label": [{"@id": "987654", "#text": "Test Label"}]},
        "genres": {"genre": ["Rock", "Pop"]},
        "styles": {"style": ["Alternative Rock", "Indie Pop"]},
        "master_id": {"#text": "998877"},
    }


@pytest.fixture
def sample_master_data() -> dict[str, Any]:
    """Sample master data for testing."""
    return {
        "id": "998877",
        "title": "Test Master",
        "year": 2023,
        "sha256": "998877665544",
        "artists": {"artist": [{"id": "123456", "name": "Test Artist"}]},
        "genres": {"genre": ["Rock"]},
        "styles": {"style": ["Alternative Rock"]},
    }


@pytest.fixture(autouse=True)
def setup_test_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Set up test environment variables."""
    test_env = {
        "AMQP_CONNECTION": "amqp://test:test@localhost:5672/",
        "DISCOGS_ROOT": str(tmp_path / "test-discogs"),
        "NEO4J_ADDRESS": "bolt://localhost:7687",
        "NEO4J_USERNAME": "test",
        "NEO4J_PASSWORD": "test",
        "POSTGRES_ADDRESS": "localhost:5432",
        "POSTGRES_USERNAME": "test",
        "POSTGRES_PASSWORD": "test",
        "POSTGRES_DATABASE": "test",
        "REDIS_URL": "redis://localhost:6379/0",
        "PERIODIC_CHECK_DAYS": "15",
    }

    for key, value in test_env.items():
        monkeypatch.setenv(key, value)


@pytest.fixture(autouse=True)
def reset_global_state() -> Iterator[None]:
    """Reset global state in service modules between tests."""
    # Reset state BEFORE test runs
    try:
        import graphinator.graphinator

        graphinator.graphinator.shutdown_requested = False
        graphinator.graphinator.graph = None
        graphinator.graphinator.message_counts = {
            "artists": 0,
            "labels": 0,
            "masters": 0,
            "releases": 0,
        }
        graphinator.graphinator.progress_interval = 100
        graphinator.graphinator.last_message_time = {
            "artists": 0.0,
            "labels": 0.0,
            "masters": 0.0,
            "releases": 0.0,
        }
        graphinator.graphinator.current_task = None
        graphinator.graphinator.current_progress = 0.0
        graphinator.graphinator.consumer_tags = {}
    except (ImportError, AttributeError):
        pass

    try:
        import tableinator.tableinator

        tableinator.tableinator.shutdown_requested = False
        tableinator.tableinator.connection_pool = None
        tableinator.tableinator.config = None
        tableinator.tableinator.current_task = None
        tableinator.tableinator.current_progress = 0.0
        tableinator.tableinator.connection_params = {}
        # Reset message counts
        tableinator.tableinator.message_counts = {
            "artists": 0,
            "labels": 0,
            "masters": 0,
            "releases": 0,
        }
        tableinator.tableinator.last_message_time = {
            "artists": 0.0,
            "labels": 0.0,
            "masters": 0.0,
            "releases": 0.0,
        }
        tableinator.tableinator.consumer_tags = {}
    except (ImportError, AttributeError):
        pass

    try:
        import extractor.extractor

        extractor.extractor.shutdown_requested = False
    except (ImportError, AttributeError):
        pass

    yield

    # Reset state AFTER test runs too
    try:
        import graphinator.graphinator

        graphinator.graphinator.shutdown_requested = False
        graphinator.graphinator.graph = None
        graphinator.graphinator.message_counts = {
            "artists": 0,
            "labels": 0,
            "masters": 0,
            "releases": 0,
        }
        graphinator.graphinator.progress_interval = 100
        graphinator.graphinator.last_message_time = {
            "artists": 0.0,
            "labels": 0.0,
            "masters": 0.0,
            "releases": 0.0,
        }
        graphinator.graphinator.current_task = None
        graphinator.graphinator.current_progress = 0.0
        graphinator.graphinator.consumer_tags = {}
    except (ImportError, AttributeError):
        pass

    try:
        import tableinator.tableinator

        tableinator.tableinator.shutdown_requested = False
        tableinator.tableinator.connection_pool = None
        tableinator.tableinator.config = None
        tableinator.tableinator.current_task = None
        tableinator.tableinator.current_progress = 0.0
        tableinator.tableinator.connection_params = {}
        tableinator.tableinator.message_counts = {
            "artists": 0,
            "labels": 0,
            "masters": 0,
            "releases": 0,
        }
        tableinator.tableinator.last_message_time = {
            "artists": 0.0,
            "labels": 0.0,
            "masters": 0.0,
            "releases": 0.0,
        }
        tableinator.tableinator.consumer_tags = {}
    except (ImportError, AttributeError):
        pass

    try:
        import extractor.extractor

        extractor.extractor.shutdown_requested = False
    except (ImportError, AttributeError):
        pass
