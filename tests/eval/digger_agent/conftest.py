"""Fixtures for the Digger agent eval suite.

The ``agent_eval_harness`` fixture builds a real Anthropic client and a
``ToolContext`` backed by a live Postgres pool + Redis. It is only constructed
for non-skipped eval tests, which require ``ANTHROPIC_API_KEY`` plus a seeded
live stack (``DIGGER_EVAL_USER_ID`` + the standard ``POSTGRES_*`` / ``REDIS_HOST``
env). In regular CI the eval tests are skipped, so this fixture never runs.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from uuid import UUID

import anthropic
import pytest
import pytest_asyncio
import redis.asyncio as aioredis

from api.digger_agent.tools.context import ToolContext
from common import AsyncPostgreSQLPool
from tests.eval.digger_agent.harness import AgentEvalHarness


if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest_asyncio.fixture
async def agent_eval_harness() -> AsyncIterator[AgentEvalHarness]:
    """Build a live agent eval harness, or skip if the live stack is not configured."""
    user_id = os.environ.get("DIGGER_EVAL_USER_ID")
    pg_host = os.environ.get("POSTGRES_HOST")
    if not (os.environ.get("ANTHROPIC_API_KEY") and user_id and pg_host):
        pytest.skip("eval harness needs ANTHROPIC_API_KEY, DIGGER_EVAL_USER_ID, POSTGRES_HOST + a seeded stack")

    host, _, port_str = pg_host.partition(":")
    pool = AsyncPostgreSQLPool(
        connection_params={
            "host": host,
            "port": int(port_str) if port_str else 5432,
            "user": os.environ.get("POSTGRES_USERNAME", "postgres"),
            "password": os.environ.get("POSTGRES_PASSWORD", ""),
            "dbname": os.environ.get("POSTGRES_DATABASE", "discogsography"),
        }
    )
    await pool.initialize()
    redis = aioredis.from_url(os.environ.get("REDIS_HOST", "redis://localhost:6379/0"))
    client = anthropic.AsyncAnthropic()
    ctx = ToolContext(pool=pool, redis=redis, user_id=UUID(user_id))
    try:
        yield AgentEvalHarness(client=client, ctx=ctx)
    finally:
        await redis.aclose()
        await pool.close()
