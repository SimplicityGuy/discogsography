"""Test fixtures for brainztableinator tests."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_async_pool():
    """Mock AsyncPostgreSQLPool with async context manager support.

    Returns a function that creates a mock pool with a given connection mock.
    This allows tests to configure the connection's behavior before creating the pool.

    Usage:
        mock_conn = MagicMock()
        mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
        mock_cursor.fetchone.return_value = None

        pool = mock_async_pool(mock_conn)
        with patch("brainztableinator.brainztableinator.connection_pool", pool):
            # test code
    """

    def create_pool(mock_connection: Any = None) -> MagicMock:
        """Create a mock pool that returns the given connection."""
        if mock_connection is None:
            mock_connection = MagicMock()

        mock_pool = MagicMock()

        # Create async context manager for connection
        mock_connection_cm = AsyncMock()
        mock_connection_cm.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_connection_cm.__aexit__ = AsyncMock(return_value=None)

        # For async with connection_pool.connection() pattern:
        # connection() should return the context manager directly (not a coroutine)
        mock_pool.connection = MagicMock(return_value=mock_connection_cm)
        mock_pool.close = AsyncMock()

        return mock_pool

    return create_pool
