"""Tests for admin audit log recording."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.audit_log import record_audit_entry


def _make_mock_pool(mock_cur: AsyncMock | None = None) -> tuple[MagicMock, AsyncMock]:
    """Create a mock pool with optional pre-configured cursor."""
    if mock_cur is None:
        mock_cur = AsyncMock()
        mock_cur.execute = AsyncMock()
    pool = MagicMock()
    mock_conn = AsyncMock()
    cur_ctx = AsyncMock()
    cur_ctx.__aenter__ = AsyncMock(return_value=mock_cur)
    cur_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_conn.cursor = MagicMock(return_value=cur_ctx)
    conn_ctx = AsyncMock()
    conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    conn_ctx.__aexit__ = AsyncMock(return_value=False)
    pool.connection = MagicMock(return_value=conn_ctx)
    return pool, mock_cur


class TestRecordAuditEntry:
    @pytest.mark.asyncio
    async def test_records_action_with_all_fields(self) -> None:
        pool, mock_cur = _make_mock_pool()
        await record_audit_entry(
            pool=pool,
            admin_id="admin-uuid-123",
            action="extraction.trigger",
            target=None,
            details={"extraction_id": "ext-uuid-456"},
        )
        mock_cur.execute.assert_called_once()
        call_args = mock_cur.execute.call_args
        sql = call_args[0][0]
        params = call_args[0][1]
        assert "admin_audit_log" in sql
        assert params[0] == "admin-uuid-123"
        assert params[1] == "extraction.trigger"
        assert params[2] is None  # target
        assert '"extraction_id"' in params[3]  # details JSON string

    @pytest.mark.asyncio
    async def test_records_action_with_target(self) -> None:
        pool, mock_cur = _make_mock_pool()
        await record_audit_entry(
            pool=pool,
            admin_id="admin-uuid-123",
            action="dlq.purge",
            target="graphinator-artists-dlq",
            details={"purged_count": 5},
        )
        mock_cur.execute.assert_called_once()
        params = mock_cur.execute.call_args[0][1]
        assert params[1] == "dlq.purge"
        assert params[2] == "graphinator-artists-dlq"

    @pytest.mark.asyncio
    async def test_records_action_without_details(self) -> None:
        pool, mock_cur = _make_mock_pool()
        await record_audit_entry(
            pool=pool,
            admin_id="admin-uuid-123",
            action="admin.logout",
            target="admin@test.com",
        )
        mock_cur.execute.assert_called_once()
        params = mock_cur.execute.call_args[0][1]
        assert params[3] is None  # details

    @pytest.mark.asyncio
    async def test_does_not_raise_on_db_error(self) -> None:
        pool, mock_cur = _make_mock_pool()
        mock_cur.execute = AsyncMock(side_effect=Exception("DB connection lost"))
        await record_audit_entry(
            pool=pool,
            admin_id="admin-uuid-123",
            action="admin.login",
            target="admin@test.com",
        )

    @pytest.mark.asyncio
    async def test_skips_when_pool_is_none(self) -> None:
        await record_audit_entry(
            pool=None,
            admin_id="admin-uuid-123",
            action="admin.login",
            target="admin@test.com",
        )
