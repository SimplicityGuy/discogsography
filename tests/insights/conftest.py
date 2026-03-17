"""Shared fixtures for insights tests."""

from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient
import httpx
import pytest


@pytest.fixture
def mock_http_client() -> AsyncMock:
    """Mock httpx.AsyncClient for API calls."""
    return AsyncMock(spec=httpx.AsyncClient)


@pytest.fixture
def mock_pg_pool() -> AsyncMock:
    """Mock PostgreSQL pool."""
    mock_cursor = AsyncMock()
    mock_cursor.execute = AsyncMock()
    mock_cursor.fetchall = AsyncMock(return_value=[])
    mock_cursor.fetchone = AsyncMock(return_value=None)
    mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor.__aexit__ = AsyncMock(return_value=False)

    mock_conn = AsyncMock()
    mock_conn.cursor = MagicMock(return_value=mock_cursor)
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)

    pool = AsyncMock()
    pool.connection = MagicMock(return_value=mock_conn)
    return pool


@pytest.fixture
def test_client(mock_http_client: AsyncMock, mock_pg_pool: AsyncMock) -> TestClient:
    """Create a test client with mocked dependencies (no cache)."""
    import insights.insights as _module

    _module._http_client = mock_http_client
    _module._pool = mock_pg_pool
    _module._cache = None

    from insights.insights import app

    return TestClient(app)


@pytest.fixture
def mock_cache() -> AsyncMock:
    """Mock InsightsCache."""
    cache = AsyncMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    cache.invalidate_all = AsyncMock()
    return cache


@pytest.fixture
def test_client_with_cache(
    mock_http_client: AsyncMock,
    mock_pg_pool: AsyncMock,
    mock_cache: AsyncMock,
) -> TestClient:
    """Create a test client with mocked dependencies and cache enabled."""
    import insights.insights as _module

    _module._http_client = mock_http_client
    _module._pool = mock_pg_pool
    _module._cache = mock_cache

    from insights.insights import app

    return TestClient(app)
