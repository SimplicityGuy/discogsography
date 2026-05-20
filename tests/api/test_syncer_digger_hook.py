"""Tests for the digger priority-seeding hook in api/syncer.py."""

from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest

from api.syncer import _seed_digger_priorities_for_wantlist


TEST_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000042")


@pytest.fixture
def mock_cur() -> AsyncMock:
    """Mock psycopg cursor."""
    cur = AsyncMock()
    cur.executemany = AsyncMock()
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
async def test_seed_digger_priorities_batches_inserts(
    mock_pool: MagicMock,
    mock_cur: AsyncMock,
) -> None:
    """Helper issues two executemany calls: release_scrape_state then user_wantlist_priorities."""
    await _seed_digger_priorities_for_wantlist(mock_pool, TEST_USER_ID, [12345, 67890])

    assert mock_cur.executemany.await_count == 2
    first_call, second_call = mock_cur.executemany.await_args_list

    # First executemany: digger.release_scrape_state
    first_sql, first_rows = first_call.args
    assert "digger.release_scrape_state" in first_sql
    assert "ON CONFLICT" in first_sql
    assert "DO NOTHING" in first_sql
    assert first_rows == [(12345,), (67890,)]

    # Second executemany: digger.user_wantlist_priorities
    second_sql, second_rows = second_call.args
    assert "digger.user_wantlist_priorities" in second_sql
    assert "ON CONFLICT" in second_sql
    assert "DO NOTHING" in second_sql
    assert second_rows == [(TEST_USER_ID, 12345), (TEST_USER_ID, 67890)]


@pytest.mark.asyncio
async def test_seed_digger_priorities_empty_is_noop(
    mock_pool: MagicMock,
    mock_cur: AsyncMock,
) -> None:
    """Empty release_ids does nothing — no connection acquired, no executemany."""
    await _seed_digger_priorities_for_wantlist(mock_pool, TEST_USER_ID, [])

    mock_pool.connection.assert_not_called()
    mock_cur.executemany.assert_not_awaited()
