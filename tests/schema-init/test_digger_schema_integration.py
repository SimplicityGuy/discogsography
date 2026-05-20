"""Verify create_postgres_schema applies the digger feature schema.

Mock-based (repo convention) — there is no real-Postgres unit fixture, and
`just test` runs `-m 'not e2e'`. Real behavioral verification of the applied
schema (tables actually exist) lives in the M1 e2e smoke (Task 28).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from postgres_schema import create_postgres_schema


@pytest.fixture
def mock_pool() -> MagicMock:
    """Mock AsyncPostgreSQLPool: pool.connection() -> conn -> conn.cursor()."""
    pool = MagicMock()
    conn = AsyncMock()
    cur = AsyncMock()
    cur.__aenter__ = AsyncMock(return_value=cur)
    cur.__aexit__ = AsyncMock(return_value=False)
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    conn.cursor = MagicMock(return_value=cur)  # cursor() is sync, returns an async CM
    pool.connection.return_value = conn
    return pool


@pytest.mark.asyncio
async def test_create_postgres_schema_applies_digger_schema(mock_pool: MagicMock) -> None:
    await create_postgres_schema(mock_pool)
    cur = mock_pool.connection.return_value.__aenter__.return_value.cursor.return_value
    executed = [c.args[0] for c in cur.execute.call_args_list if c.args]
    assert any(isinstance(stmt, str) and "CREATE SCHEMA IF NOT EXISTS digger" in stmt for stmt in executed), (
        "digger schema SQL was not executed by create_postgres_schema"
    )
