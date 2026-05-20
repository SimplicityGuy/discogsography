"""Tests for the digger priority-seeding hook in api/syncer.py."""

from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest

from api.syncer import _seed_digger_priority_for_wantlist_item


TEST_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000042")
TEST_RELEASE_ID = 12345


@pytest.fixture
def mock_cur() -> AsyncMock:
    """Mock psycopg cursor."""
    cur = AsyncMock()
    cur.execute = AsyncMock()
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
    return pool


@pytest.mark.asyncio
async def test_seed_digger_priority_executes_two_idempotent_inserts(
    mock_pool: MagicMock,
    mock_cur: AsyncMock,
) -> None:
    """Helper issues two ON CONFLICT DO NOTHING INSERTs: release_scrape_state then user_wantlist_priorities."""
    await _seed_digger_priority_for_wantlist_item(mock_pool, TEST_USER_ID, TEST_RELEASE_ID)

    assert mock_cur.execute.await_count == 2
    first_call, second_call = mock_cur.execute.await_args_list

    # First INSERT: digger.release_scrape_state
    first_sql, first_params = first_call.args
    assert "digger.release_scrape_state" in first_sql
    assert "ON CONFLICT" in first_sql
    assert "DO NOTHING" in first_sql
    assert first_params == (TEST_RELEASE_ID,)

    # Second INSERT: digger.user_wantlist_priorities
    second_sql, second_params = second_call.args
    assert "digger.user_wantlist_priorities" in second_sql
    assert "ON CONFLICT" in second_sql
    assert "DO NOTHING" in second_sql
    assert second_params == (TEST_USER_ID, TEST_RELEASE_ID)


@pytest.mark.asyncio
async def test_seed_digger_priority_is_idempotent_on_second_call(
    mock_pool: MagicMock,
    mock_cur: AsyncMock,
) -> None:
    """Calling the helper twice issues the same two INSERTs both times (ON CONFLICT handles duplicates)."""
    await _seed_digger_priority_for_wantlist_item(mock_pool, TEST_USER_ID, TEST_RELEASE_ID)
    await _seed_digger_priority_for_wantlist_item(mock_pool, TEST_USER_ID, TEST_RELEASE_ID)

    # 2 calls x 2 INSERTs = 4 total execute calls
    assert mock_cur.execute.await_count == 4


@pytest.mark.asyncio
async def test_seed_digger_priority_uses_correct_param_types(
    mock_pool: MagicMock,
    mock_cur: AsyncMock,
) -> None:
    """Params are passed as tuples (psycopg3 convention), not positional args."""
    await _seed_digger_priority_for_wantlist_item(mock_pool, TEST_USER_ID, TEST_RELEASE_ID)

    for awaited_call in mock_cur.execute.await_args_list:
        # Each call must have exactly 2 positional args: sql string and params tuple
        assert len(awaited_call.args) == 2
        sql, params = awaited_call.args
        assert isinstance(sql, str)
        assert isinstance(params, tuple)
