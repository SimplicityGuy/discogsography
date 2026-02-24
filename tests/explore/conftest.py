"""Fixtures for Explore service tests."""

import os


# Set environment variables BEFORE importing explore modules
os.environ.setdefault("NEO4J_ADDRESS", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USERNAME", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "testpassword")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-for-unit-tests")

from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager
import subprocess
import sys
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest


@pytest.fixture
def mock_neo4j_driver() -> MagicMock:
    """Create a mock Neo4j async driver."""
    driver = MagicMock()

    # Setup async session context manager
    mock_session = AsyncMock()
    mock_result = AsyncMock()

    # Make session work as async context manager
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.run = AsyncMock(return_value=mock_result)

    # Make result iterable (for list comprehension async for)
    mock_result.__aiter__ = MagicMock(return_value=iter([]))
    mock_result.single = AsyncMock(return_value=None)

    driver.session = MagicMock(return_value=mock_session)
    driver.close = AsyncMock()

    return driver


@pytest.fixture
def mock_neo4j_session(mock_neo4j_driver: MagicMock) -> AsyncMock:
    """Get the mock session from the mock driver."""
    session: AsyncMock = mock_neo4j_driver.session()
    return session


@pytest.fixture
def test_client(mock_neo4j_driver: MagicMock) -> Generator[TestClient]:
    """Create a test client with mocked Neo4j driver, bypassing real lifespan.

    The API endpoints (autocomplete, explore, expand, user) have been migrated
    from explore.explore to api.routers.explore and api.routers.user.  We build
    a minimal FastAPI app that mounts those routers plus a /health endpoint that
    mimics the old explore service health response.
    """
    # Build a minimal test app that includes the migrated API routers
    # plus the explore /health endpoint and static files (still served by explore.explore).
    from pathlib import Path

    from fastapi.staticfiles import StaticFiles

    import api.routers.explore as explore_router_module
    import api.routers.snapshot as snapshot_router_module
    import api.routers.user as user_router_module
    from explore.explore import app as explore_app  # noqa: F401 - explore_app referenced in TestLifespan

    @asynccontextmanager
    async def mock_lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        yield

    test_app = FastAPI(lifespan=mock_lifespan)

    @test_app.get("/health")
    async def health_check() -> dict[str, Any]:
        # Return healthy status since mock driver is configured
        from datetime import UTC, datetime

        return {
            "status": "healthy",
            "service": "explore",
            "timestamp": datetime.now(UTC).isoformat(),
        }

    test_app.include_router(explore_router_module.router)
    test_app.include_router(user_router_module.router)
    test_app.include_router(snapshot_router_module.router)

    # Mount static files from the explore service
    static_dir = Path(__file__).parent.parent.parent / "explore" / "static"
    if static_dir.exists():
        test_app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    # Wire the mock driver into both api routers
    explore_router_module.configure(mock_neo4j_driver, os.environ.get("JWT_SECRET_KEY"))
    user_router_module.configure(mock_neo4j_driver, os.environ.get("JWT_SECRET_KEY"))

    # Clear autocomplete cache between tests
    explore_router_module._autocomplete_cache.clear()

    with TestClient(test_app, raise_server_exceptions=False) as client:
        yield client

    # Restore router state (set driver back to None so tests are isolated)
    explore_router_module.configure(None, None)
    user_router_module.configure(None, None)


@pytest.fixture
def sample_artist_autocomplete() -> list[dict[str, Any]]:
    """Sample autocomplete results for artists."""
    return [
        {"id": "1", "name": "Radiohead", "score": 9.5},
        {"id": "2", "name": "Radio Dept.", "score": 7.2},
        {"id": "3", "name": "Radiator Hospital", "score": 5.1},
    ]


@pytest.fixture
def sample_explore_artist() -> dict[str, Any]:
    """Sample explore result for an artist."""
    return {
        "id": "1",
        "name": "Radiohead",
        "release_count": 42,
        "label_count": 5,
        "alias_count": 2,
    }


@pytest.fixture
def sample_explore_genre() -> dict[str, Any]:
    """Sample explore result for a genre."""
    return {
        "id": "Rock",
        "name": "Rock",
        "release_count": 5000,
        "artist_count": 1000,
        "label_count": 200,
        "style_count": 50,
    }


@pytest.fixture
def sample_explore_label() -> dict[str, Any]:
    """Sample explore result for a label."""
    return {
        "id": "100",
        "name": "Warp Records",
        "release_count": 500,
        "artist_count": 120,
        "genre_count": 8,
    }


@pytest.fixture
def sample_explore_style() -> dict[str, Any]:
    """Sample explore result for a style."""
    return {
        "id": "Alternative Rock",
        "name": "Alternative Rock",
        "release_count": 2000,
        "artist_count": 400,
        "label_count": 100,
        "genre_count": 3,
    }


@pytest.fixture
def sample_expand_releases() -> list[dict[str, Any]]:
    """Sample expand results for releases."""
    return [
        {"id": "10", "name": "OK Computer", "type": "release", "year": 1997},
        {"id": "11", "name": "Kid A", "type": "release", "year": 2000},
        {"id": "12", "name": "In Rainbows", "type": "release", "year": 2007},
    ]


@pytest.fixture
def sample_artist_details() -> dict[str, Any]:
    """Sample artist details."""
    return {
        "id": "1",
        "name": "Radiohead",
        "genres": ["Rock", "Electronic"],
        "styles": ["Alternative Rock", "Art Rock"],
        "release_count": 42,
        "groups": [],
    }


@pytest.fixture
def sample_trends_data() -> list[dict[str, Any]]:
    """Sample trends time-series data."""
    return [
        {"year": 1993, "count": 1},
        {"year": 1995, "count": 2},
        {"year": 1997, "count": 1},
        {"year": 2000, "count": 1},
        {"year": 2003, "count": 1},
    ]


# E2E fixtures


@pytest.fixture(scope="session")
def test_server() -> Generator[str]:
    """Start explore test server for E2E tests."""
    port = 8006
    server_url = f"http://localhost:{port}"

    process = subprocess.Popen(  # noqa: S603
        [
            sys.executable,
            "-m",
            "uvicorn",
            "tests.explore.explore_test_app:create_test_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for server readiness
    max_retries = 40
    for _i in range(max_retries):
        try:
            response = httpx.get(f"{server_url}/health", timeout=2.0)
            if response.status_code == 200:
                break
        except (httpx.ConnectError, httpx.TimeoutException):
            pass
        time.sleep(0.5)
    else:
        process.terminate()
        stdout, stderr = process.communicate(timeout=5)
        raise RuntimeError(f"Test server failed to start.\nStdout: {stdout.decode()}\nStderr: {stderr.decode()}")

    yield server_url

    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


@pytest.fixture(scope="session")
def browser_context_args() -> dict[str, Any]:
    """Configure browser context for E2E tests."""
    return {
        "viewport": {"width": 1280, "height": 720},
        "ignore_https_errors": True,
    }


@pytest.fixture(scope="session")
def browser_type_launch_args() -> dict[str, Any]:
    """Configure browser launch arguments."""
    return {
        "headless": True,
        "args": ["--no-sandbox", "--disable-gpu"],
    }
