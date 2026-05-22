"""Tests for the digger.proposals SQL helpers (mock-based)."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest

from api.queries import digger_proposals as q


def _txn_pool(mock_cur: AsyncMock) -> MagicMock:
    """Build a pool whose connection supports set_autocommit + transaction() + cursor()."""
    conn = AsyncMock()
    conn.set_autocommit = AsyncMock()

    txn_ctx = AsyncMock()
    txn_ctx.__aenter__ = AsyncMock(return_value=None)
    txn_ctx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=txn_ctx)

    cur_ctx = AsyncMock()
    cur_ctx.__aenter__ = AsyncMock(return_value=mock_cur)
    cur_ctx.__aexit__ = AsyncMock(return_value=False)
    conn.cursor = MagicMock(return_value=cur_ctx)

    conn_ctx = AsyncMock()
    conn_ctx.__aenter__ = AsyncMock(return_value=conn)
    conn_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.connection = MagicMock(return_value=conn_ctx)
    return pool


@pytest.mark.asyncio
async def test_list_pending_proposals_formats_rows(mock_pool: MagicMock, mock_cur: AsyncMock) -> None:
    pid = uuid.uuid4()
    created = datetime(2026, 5, 21, tzinfo=UTC)
    payload = [{"release_id": 1, "current_tier": "nice", "proposed_tier": "must", "reason": "rare"}]
    mock_cur.fetchall.return_value = [{"proposal_id": pid, "created_at": created, "status": "pending", "payload": payload}]
    user_id = uuid.uuid4()
    out = await q.list_pending_proposals(mock_pool, user_id)
    assert out == [{"proposal_id": str(pid), "created_at": created.isoformat(), "status": "pending", "payload": payload}]
    sql, params = mock_cur.execute.await_args.args
    assert "status = 'pending'" in sql
    assert "expires_at > now()" in sql
    assert params == (user_id,)


@pytest.mark.asyncio
async def test_approve_proposal_returns_none_when_missing(mock_cur: AsyncMock) -> None:
    mock_cur.fetchone = AsyncMock(return_value=None)
    pool = _txn_pool(mock_cur)
    result = await q.approve_proposal(pool, uuid.uuid4(), uuid.uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_approve_proposal_applies_matching_changes(mock_cur: AsyncMock) -> None:
    payload = [
        {"release_id": 1, "proposed_tier": "must"},
        {"release_id": 2, "proposed_tier": "nice"},
    ]
    mock_cur.fetchone = AsyncMock(return_value={"payload": payload})
    mock_cur.rowcount = 1
    pool = _txn_pool(mock_cur)
    user_id = uuid.uuid4()
    applied = await q.approve_proposal(pool, uuid.uuid4(), user_id)
    assert applied == 2
    sqls = [c.args[0] for c in mock_cur.execute.await_args_list]
    assert any("FOR UPDATE" in s for s in sqls)
    assert any("UPDATE digger.user_wantlist_priorities" in s for s in sqls)
    assert any("status = 'approved'" in s for s in sqls)


@pytest.mark.asyncio
async def test_approve_proposal_skips_unmatched_releases(mock_cur: AsyncMock) -> None:
    mock_cur.fetchone = AsyncMock(return_value={"payload": [{"release_id": 99, "proposed_tier": "must"}]})
    mock_cur.rowcount = 0  # release no longer in the wantlist -> no row updated
    pool = _txn_pool(mock_cur)
    applied = await q.approve_proposal(pool, uuid.uuid4(), uuid.uuid4())
    assert applied == 0


@pytest.mark.asyncio
async def test_reject_proposal_reflects_rowcount(mock_pool: MagicMock, mock_cur: AsyncMock) -> None:
    mock_cur.rowcount = 1
    assert await q.reject_proposal(mock_pool, uuid.uuid4(), uuid.uuid4()) is True
    mock_cur.rowcount = 0
    assert await q.reject_proposal(mock_pool, uuid.uuid4(), uuid.uuid4()) is False
