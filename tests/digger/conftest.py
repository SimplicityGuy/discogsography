"""Shared pytest fixtures for digger tests."""

from __future__ import annotations

import fakeredis.aioredis as aioredis_fake
import pytest_asyncio


@pytest_asyncio.fixture
async def redis_test_client():
    """Provide a flushed async fakeredis client for tests that need Redis."""
    client = aioredis_fake.FakeRedis()
    await client.flushall()
    yield client
    await client.aclose()
