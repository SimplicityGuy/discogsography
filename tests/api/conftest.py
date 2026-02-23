"""Fixtures for API service tests."""

import base64
import hashlib
import hmac
import json
import os


# Set environment variables BEFORE importing api modules
os.environ.setdefault("POSTGRES_ADDRESS", "localhost:5432")
os.environ.setdefault("POSTGRES_USERNAME", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("POSTGRES_DATABASE", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-for-unit-tests")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from common.config import ApiConfig


TEST_JWT_SECRET = "test-jwt-secret-for-unit-tests"
TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
TEST_USER_EMAIL = "test@example.com"


def make_test_jwt(
    user_id: str = TEST_USER_ID,
    email: str = TEST_USER_EMAIL,
    exp: int = 9_999_999_999,
    secret: str = TEST_JWT_SECRET,
) -> str:
    """Create a valid HS256 JWT for testing."""

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
def mock_redis() -> AsyncMock:
    """Mock aioredis client."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock()
    redis.delete = AsyncMock()
    redis.aclose = AsyncMock()
    return redis


@pytest.fixture
def test_api_config() -> ApiConfig:
    """Create a test ApiConfig with the test JWT secret."""
    return ApiConfig(
        postgres_address="localhost:5432",
        postgres_username="test",
        postgres_password="test",  # noqa: S106
        postgres_database="test",
        jwt_secret_key=TEST_JWT_SECRET,
        redis_url="redis://localhost:6379/0",
        jwt_expire_minutes=30,
    )


@pytest.fixture
def valid_token() -> str:
    """Create a valid JWT token for testing."""
    return make_test_jwt()


@pytest.fixture
def test_client(
    mock_pool: MagicMock,
    mock_redis: AsyncMock,
    test_api_config: ApiConfig,
) -> Generator[TestClient]:
    """Create a TestClient with mocked lifespan and module-level state."""
    import api.api as api_module
    from api.api import app

    @asynccontextmanager
    async def mock_lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        yield

    original_lifespan = app.router.lifespan_context
    original_pool = api_module._pool
    original_config = api_module._config
    original_redis = api_module._redis

    app.router.lifespan_context = mock_lifespan
    api_module._pool = mock_pool
    api_module._config = test_api_config
    api_module._redis = mock_redis

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client

    # Restore original state
    api_module._pool = original_pool
    api_module._config = original_config
    api_module._redis = original_redis
    app.router.lifespan_context = original_lifespan


@pytest.fixture
def auth_headers(valid_token: str) -> dict[str, str]:
    """Authorization headers with a valid bearer token."""
    return {"Authorization": f"Bearer {valid_token}"}


def make_sample_user_row(
    user_id: str = TEST_USER_ID,
    email: str = TEST_USER_EMAIL,
    is_active: bool = True,
    hashed_password: str | None = None,
) -> dict[str, Any]:
    """Create a sample DB user row dict."""
    from datetime import UTC, datetime

    if hashed_password is None:
        # salt:key format
        import os

        salt = os.urandom(32)
        key = hashlib.pbkdf2_hmac("sha256", b"testpassword", salt, 100_000)
        hashed_password = salt.hex() + ":" + key.hex()

    return {
        "id": user_id,
        "email": email,
        "is_active": is_active,
        "hashed_password": hashed_password,
        "created_at": datetime.now(UTC),
    }
