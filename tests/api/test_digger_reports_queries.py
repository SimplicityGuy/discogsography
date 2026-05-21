"""Tests for digger.reports SQL helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
import uuid

import pytest

from api.queries import digger_reports as q


@pytest.mark.asyncio
async def test_list_reports_formats_rows(mock_pool: object, mock_cur: AsyncMock) -> None:
    rid = uuid.uuid4()
    gen = datetime(2026, 5, 21, tzinfo=UTC)
    mock_cur.fetchall = AsyncMock(
        return_value=[
            {
                "report_id": rid,
                "kind": "scheduled",
                "generated_at": gen,
                "read_at": None,
                "title": "Weekly",
                "summary": {"wantlist_size": 5},
                "change_flag": "significant",
            }
        ]
    )
    out = await q.list_reports(mock_pool, uuid.uuid4())
    assert out[0]["report_id"] == str(rid)
    assert out[0]["generated_at"] == gen.isoformat()
    assert out[0]["read_at"] is None
    assert out[0]["summary"] == {"wantlist_size": 5}


@pytest.mark.asyncio
async def test_get_report_returns_none_when_missing(mock_pool: object, mock_cur: AsyncMock) -> None:
    mock_cur.fetchone = AsyncMock(return_value=None)
    assert await q.get_report(mock_pool, uuid.uuid4(), uuid.uuid4()) is None


@pytest.mark.asyncio
async def test_get_report_formats_row(mock_pool: object, mock_cur: AsyncMock) -> None:
    rid = uuid.uuid4()
    uid = uuid.uuid4()
    gen = datetime(2026, 5, 21, tzinfo=UTC)
    mock_cur.fetchone = AsyncMock(
        return_value={
            "report_id": rid,
            "user_id": uid,
            "kind": "interactive",
            "generated_at": gen,
            "read_at": None,
            "title": "T",
            "summary": {},
            "bundles": [],
            "watching": [],
            "change_flag": "first_run",
            "shipping_confidence": "high",
        }
    )
    out = await q.get_report(mock_pool, uid, rid)
    assert out is not None
    assert out["report_id"] == str(rid)
    assert out["user_id"] == str(uid)
    assert out["generated_at"] == gen.isoformat()


@pytest.mark.asyncio
async def test_insert_report_returns_uuid(mock_pool: object, mock_cur: AsyncMock) -> None:
    rid = await q.insert_report(
        mock_pool,
        uuid.uuid4(),
        kind="interactive",
        title="T",
        summary={"x": 1},
        bundles=[],
        watching=[],
        change_flag="first_run",
        shipping_confidence="high",
    )
    assert isinstance(rid, uuid.UUID)
    assert mock_cur.execute.await_count == 1


@pytest.mark.asyncio
async def test_mark_read_reflects_rowcount(mock_pool: object, mock_cur: AsyncMock) -> None:
    mock_cur.rowcount = 1
    assert await q.mark_read(mock_pool, uuid.uuid4(), uuid.uuid4()) is True
    mock_cur.rowcount = 0
    assert await q.mark_read(mock_pool, uuid.uuid4(), uuid.uuid4()) is False
