"""Pytest configuration for dashboard tests."""

import time
from multiprocessing import Process
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import uvicorn

from common import DashboardConfig


def run_test_server() -> None:
    """Run the test server in a separate process."""
    from tests.dashboard.dashboard_test_app import create_test_app

    app = create_test_app()
    uvicorn.run(app, host="127.0.0.1", port=8003, log_level="info")


@pytest.fixture(scope="session")
def test_server() -> Any:
    """Start the test dashboard server for E2E tests.

    This fixture is only used when running E2E tests.
    """
    # Start server in a separate process
    server_process = Process(target=run_test_server)
    server_process.start()

    # Wait for server to be ready
    import httpx

    for _ in range(20):
        try:
            response = httpx.get("http://127.0.0.1:8003/api/metrics")
            if response.status_code == 200:
                break
        except Exception:  # noqa: S110
            pass  # Server might not be ready yet
        time.sleep(0.5)
    else:
        server_process.terminate()
        raise RuntimeError("Test server failed to start")

    yield

    # Cleanup
    server_process.terminate()
    server_process.join(timeout=5)
    if server_process.is_alive():
        server_process.kill()


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args: dict[str, Any]) -> dict[str, Any]:
    """Configure browser context for testing."""
    return {
        **browser_context_args,
        "viewport": {"width": 1280, "height": 720},
        "ignore_https_errors": True,
        "locale": "en-US",
        "timezone_id": "UTC",
    }


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args: dict[str, Any]) -> dict[str, Any]:
    """Configure browser launch arguments for headless mode."""
    return {
        **browser_type_launch_args,
        "headless": True,  # Always run headless
        "timeout": 30000,  # 30 second timeout for browser launch
        "args": [
            "--no-sandbox",  # Required for CI environments
            "--disable-setuid-sandbox",  # Required for CI environments
            "--disable-dev-shm-usage",  # Overcome limited resource problems
            "--disable-gpu",  # Disable GPU hardware acceleration
        ],
    }


@pytest.fixture(scope="session")
def mock_dashboard_config() -> DashboardConfig:
    """Create a mock dashboard configuration for testing."""
    return DashboardConfig(
        amqp_connection="amqp://test:test@localhost:5672/",
        neo4j_address="neo4j://localhost:7687",
        neo4j_username="test",
        neo4j_password="test",  # noqa: S106
        postgres_address="localhost:5432",
        postgres_username="test",
        postgres_password="test",  # noqa: S106
        postgres_database="test",
    )


@pytest.fixture(scope="session")
def mock_amqp_connection() -> AsyncMock:
    """Create a mock AMQP connection."""
    mock = AsyncMock()
    mock.close = AsyncMock()

    # Mock channel
    mock_channel = AsyncMock()
    mock.channel = AsyncMock(return_value=mock_channel)

    return mock


@pytest.fixture(scope="session")
def mock_neo4j_driver() -> MagicMock:
    """Create a mock Neo4j driver."""
    mock = MagicMock()
    mock.close = AsyncMock()

    # Mock session
    mock_session = AsyncMock()
    mock.session = MagicMock(return_value=mock_session)

    # Mock query results
    mock_result = AsyncMock()
    mock_result.data = AsyncMock(return_value=[{"count": 10}])
    mock_session.run = AsyncMock(return_value=mock_result)

    return mock


@pytest.fixture(scope="session")
def mock_httpx_client() -> MagicMock:
    """Create a mock httpx client."""
    mock = MagicMock()

    # Create different responses based on URL
    async def mock_get(url: str, **kwargs: Any) -> AsyncMock:  # noqa: ARG001
        response = AsyncMock()
        response.raise_for_status = AsyncMock()

        if "/health" in url:
            # Mock health endpoint responses
            response.status_code = 200
            response.json = lambda: {
                "status": "healthy",
                "current_task": "Processing",
                "progress": 0.5,
                "timestamp": "2024-01-01T00:00:00+00:00",
            }
        elif "api/v1/queues" in url:
            # Mock RabbitMQ management API
            response.json = AsyncMock(
                return_value=[
                    {
                        "name": "discogsography-graphinator-artists",
                        "messages": 5,
                        "messages_ready": 3,
                        "messages_unacknowledged": 2,
                        "consumers": 1,
                        "message_stats": {"ack_details": {"rate": 1.5}},
                    }
                ]
            )
        else:
            response.status_code = 404
            response.json = lambda: {"error": "Not found"}

        return response

    mock.get = AsyncMock(side_effect=mock_get)
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=None)

    return mock


@pytest.fixture(scope="session")
def mock_psycopg_connect() -> AsyncMock:
    """Create a mock PostgreSQL connection."""
    mock_conn = AsyncMock()

    # Mock cursor
    mock_cursor = AsyncMock()
    mock_cursor.fetchone = AsyncMock(return_value=(10,))
    mock_cursor.close = AsyncMock()

    mock_conn.cursor = AsyncMock(return_value=mock_cursor)
    mock_conn.close = AsyncMock()

    return mock_conn
