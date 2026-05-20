"""Mock-based unit tests for digger query helpers.

Repo convention: no real-Postgres unit fixture; the pool is mocked
(pool.connection() -> conn -> conn.cursor() -> cur, all AsyncMock). Real-DB
behavior is deferred to the M1 e2e smoke.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest

from api.queries import digger_queries as q


def _mock_pool(*, fetchone: Any = None, fetchall: list[Any] | None = None, rowcount: int = 0) -> tuple[MagicMock, AsyncMock]:
    pool = MagicMock()
    conn = AsyncMock()
    cur = AsyncMock()
    cur.fetchone.return_value = fetchone
    cur.fetchall.return_value = [] if fetchall is None else fetchall
    cur.rowcount = rowcount
    cur.__aenter__ = AsyncMock(return_value=cur)
    cur.__aexit__ = AsyncMock(return_value=False)
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    conn.cursor = MagicMock(return_value=cur)
    pool.connection = MagicMock(return_value=conn)
    return pool, cur


@pytest.mark.asyncio
async def test_get_user_settings_returns_none_when_absent() -> None:
    pool, _cur = _mock_pool(fetchone=None)
    assert await q.get_user_settings(pool, uuid.uuid4()) is None


@pytest.mark.asyncio
async def test_get_user_settings_maps_row() -> None:
    uid = uuid.uuid4()
    pool, cur = _mock_pool(
        fetchone={
            "user_id": uid,
            "enabled": True,
            "country_code": "US",
            "currency": "USD",
            "scheduled_cadence": "weekly",
            "preferred_model": "sonnet",
            "daily_token_cap_interactive": 200000,
            "daily_token_cap_scheduled": 100000,
        }
    )
    s = await q.get_user_settings(pool, uid)
    assert s is not None
    assert s.enabled is True
    assert s.country_code == "US"
    assert s.scheduled_cadence == "weekly"
    sql = cur.execute.call_args.args[0]
    assert "FROM digger.user_digger_settings" in sql
    assert "%s" in sql and "$1" not in sql


@pytest.mark.asyncio
async def test_upsert_user_settings_issues_upsert_with_params() -> None:
    uid = uuid.uuid4()
    pool, cur = _mock_pool()
    await q.upsert_user_settings(
        pool,
        uid,
        enabled=True,
        country_code="US",
        currency="USD",
        scheduled_cadence="weekly",
        preferred_model="sonnet",
    )
    sql, params = cur.execute.call_args.args
    assert "INSERT INTO digger.user_digger_settings" in sql
    assert "ON CONFLICT (user_id) DO UPDATE" in sql
    assert params[0] == uid and params[1] is True
    assert params[6] == 200000 and params[7] == 100000  # default token caps


@pytest.mark.asyncio
async def test_list_wantlist_priorities_maps_rows() -> None:
    pool, _cur = _mock_pool(
        fetchall=[
            {"release_id": 1, "tier": "must", "min_media_condition": "VG", "min_sleeve_condition": "VG", "max_price_cents": None},
            {"release_id": 2, "tier": "nice", "min_media_condition": "NM", "min_sleeve_condition": "VG+", "max_price_cents": 5000},
        ]
    )
    rows = await q.list_wantlist_priorities(pool, uuid.uuid4())
    assert [r.release_id for r in rows] == [1, 2]
    assert rows[0].tier == "must" and rows[1].max_price_cents == 5000


@pytest.mark.asyncio
async def test_set_wantlist_priority_builds_partial_update() -> None:
    uid = uuid.uuid4()
    pool, cur = _mock_pool()
    await q.set_wantlist_priority(pool, uid, 42, tier="must", max_price_cents=3000)
    sql, params = cur.execute.call_args.args
    assert "tier = %s" in sql and "max_price_cents = %s" in sql
    assert "min_media_condition" not in sql  # not provided -> not in SET
    assert "updated_at = now()" in sql
    # provided fields first, then user_id + release_id at the end
    assert params == ("must", 3000, uid, 42)


@pytest.mark.asyncio
async def test_set_wantlist_priority_noop_when_nothing_provided() -> None:
    pool, cur = _mock_pool()
    await q.set_wantlist_priority(pool, uuid.uuid4(), 42)
    cur.execute.assert_not_called()
    pool.connection.assert_not_called()


@pytest.mark.asyncio
async def test_bulk_set_tier_uses_array_and_returns_rowcount() -> None:
    uid = uuid.uuid4()
    pool, cur = _mock_pool(rowcount=2)
    n = await q.bulk_set_tier(pool, uid, [1, 2], "must")
    assert n == 2
    sql, params = cur.execute.call_args.args
    assert "release_id = ANY(%s)" in sql
    assert params == ("must", uid, [1, 2])


@pytest.mark.asyncio
async def test_get_wantlist_with_listings_counts_uses_public_wantlists() -> None:
    pool, cur = _mock_pool(fetchall=[{"release_id": 1, "tier": "must", "active_listings": 3, "title": "X"}])
    rows = await q.get_wantlist_with_listings_counts(pool, uuid.uuid4())
    assert rows[0]["active_listings"] == 3
    sql = cur.execute.call_args.args[0]
    assert "JOIN user_wantlists uw" in sql
    assert "discogs.user_wantlists" not in sql  # public table, not discogs schema
    assert "cover_image_url" not in sql  # column does not exist on user_wantlists


@pytest.mark.asyncio
async def test_list_users_due_for_report_returns_rows() -> None:
    pool, cur = _mock_pool(fetchall=[{"user_id": uuid.uuid4(), "scheduled_cadence": "weekly"}])
    rows = await q.list_users_due_for_report(pool)
    assert rows[0]["scheduled_cadence"] == "weekly"
    sql = cur.execute.call_args.args[0]
    assert "FROM digger.user_digger_settings" in sql
    assert "scheduled_cadence <> 'off'" in sql
