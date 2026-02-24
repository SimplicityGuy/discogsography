"""Fixtures for curator service tests."""

import base64
import hashlib
import hmac
import json
import os


# Set environment variables BEFORE importing curator modules
os.environ.setdefault("POSTGRES_ADDRESS", "localhost:5432")
os.environ.setdefault("POSTGRES_USERNAME", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("POSTGRES_DATABASE", "test")
os.environ.setdefault("NEO4J_ADDRESS", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USERNAME", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "testpassword")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-for-unit-tests")

from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from common.config import CuratorConfig


TEST_JWT_SECRET = "test-jwt-secret-for-unit-tests"
TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
TEST_USER_EMAIL = "test@example.com"


def make_curator_jwt(
    user_id: str = TEST_USER_ID,
    email: str = TEST_USER_EMAIL,
    exp: int = 9_999_999_999,
    secret: str = TEST_JWT_SECRET,
) -> str:
    """Create a valid HS256 JWT for curator service tests."""

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = b64url(json.dumps({"sub": user_id, "email": email, "exp": exp}, separators=(",", ":")).encode())
    signing_input = f"{header}.{body}".encode("ascii")
    sig = b64url(hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest())
    return f"{header}.{body}.{sig}"


@pytest.fixture
def mock_cur() -> AsyncMock:
    """Mock psycopg cursor."""
    cur = AsyncMock()
    cur.execute = AsyncMock()
    cur.fetchone = AsyncMock(return_value=None)
    cur.fetchall = AsyncMock(return_value=[])
    return cur


@pytest.fixture
def mock_conn(mock_cur: AsyncMock) -> AsyncMock:
    """Mock psycopg connection that yields mock_cur from cursor()."""
    conn = AsyncMock()
    cur_ctx = AsyncMock()
    cur_ctx.__aenter__ = AsyncMock(return_value=mock_cur)
    cur_ctx.__aexit__ = AsyncMock(return_value=False)
    conn.cursor = MagicMock(return_value=cur_ctx)
    return conn


@pytest.fixture
def mock_pool(mock_conn: AsyncMock) -> MagicMock:
    """Mock AsyncPostgreSQLPool that yields mock_conn from connection()."""
    pool = MagicMock()
    conn_ctx = AsyncMock()
    conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    conn_ctx.__aexit__ = AsyncMock(return_value=False)
    pool.connection = MagicMock(return_value=conn_ctx)
    pool.initialize = AsyncMock()
    pool.close = AsyncMock()
    return pool


@pytest.fixture
def mock_neo4j() -> MagicMock:
    """Mock AsyncResilientNeo4jDriver."""
    driver = MagicMock()
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.run = AsyncMock()

    async def _session_factory(*_args: Any, **_kwargs: Any) -> Any:
        return mock_session

    driver.session = MagicMock(side_effect=_session_factory)
    driver.close = AsyncMock()
    return driver


@pytest.fixture
def test_curator_config() -> CuratorConfig:
    """Create a test CuratorConfig."""
    return CuratorConfig(
        postgres_address="localhost:5432",
        postgres_username="test",
        postgres_password="test",  # noqa: S106
        postgres_database="test",
        neo4j_address="bolt://localhost:7687",
        neo4j_username="neo4j",
        neo4j_password="testpassword",  # noqa: S106
        jwt_secret_key=TEST_JWT_SECRET,
    )


@pytest.fixture
def valid_token() -> str:
    """Create a valid JWT token for testing."""
    return make_curator_jwt()


@pytest.fixture
def test_client(
    mock_pool: MagicMock,
    mock_neo4j: MagicMock,
    test_curator_config: CuratorConfig,
) -> Generator[TestClient]:
    """Create a TestClient with mocked lifespan and module-level state."""
    import curator.curator as curator_module
    from curator.curator import _running_syncs, app

    @asynccontextmanager
    async def mock_lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        yield

    original_lifespan = app.router.lifespan_context
    original_pool = curator_module._pool
    original_neo4j = curator_module._neo4j
    original_config = curator_module._config

    app.router.lifespan_context = mock_lifespan
    curator_module._pool = mock_pool
    curator_module._neo4j = mock_neo4j
    curator_module._config = test_curator_config
    _running_syncs.clear()

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client

    # Restore original state
    curator_module._pool = original_pool
    curator_module._neo4j = original_neo4j
    curator_module._config = original_config
    _running_syncs.clear()
    app.router.lifespan_context = original_lifespan


@pytest.fixture
def auth_headers(valid_token: str) -> dict[str, str]:
    """Authorization headers with a valid bearer token."""
    return {"Authorization": f"Bearer {valid_token}"}
