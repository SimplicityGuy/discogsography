"""Tests for api/queries/admin_queries.py."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_pool_with_rows(*query_results: list[dict]) -> tuple[MagicMock, object]:
    """Build a mock pool whose cursor returns different results for successive queries.

    Each element in *query_results* is the list of dicts returned by fetchall()
    (or fetchone() returning the first element) for the corresponding execute() call.

    Returns (pool, execute_side_effect) — the side-effect function should be used
    to patch ``api.queries.admin_queries.execute_sql`` in each test.
    """
    results_iter = iter(query_results)

    mock_cur = AsyncMock()

    async def _fetchone_side_effect():
        return mock_cur._current_result[0] if mock_cur._current_result else None

    async def _fetchall_side_effect():
        return mock_cur._current_result

    mock_cur.fetchone = AsyncMock(side_effect=_fetchone_side_effect)
    mock_cur.fetchall = AsyncMock(side_effect=_fetchall_side_effect)
    mock_cur._current_result = []

    mock_cur_ctx = MagicMock()
    mock_cur_ctx.__aenter__ = AsyncMock(return_value=mock_cur)
    mock_cur_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_conn = AsyncMock()
    mock_conn.cursor = MagicMock(return_value=mock_cur_ctx)

    mock_conn_ctx = AsyncMock()
    mock_conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_pool = MagicMock()
    mock_pool.connection = MagicMock(return_value=mock_conn_ctx)

    async def _execute_sql_side_effect(_cur, _query, _params=None):
        mock_cur._current_result = next(results_iter)

    return mock_pool, _execute_sql_side_effect


class TestGetUserStats:
    """Tests for get_user_stats query function."""

    @pytest.mark.asyncio
    async def test_basic_user_stats(self):
        from api.queries.admin_queries import get_user_stats

        pool, execute_side_effect = _mock_pool_with_rows(
            [{"total_users": 150, "oauth_users": 95, "active_7d": 42, "active_30d": 89}],
            [{"date": "2026-03-18", "count": 5}],
            [{"week_start": "2026-03-17", "count": 12}],
            [{"month": "2026-03", "count": 34}],
        )

        with patch("api.queries.admin_queries.execute_sql", side_effect=execute_side_effect):
            result = await get_user_stats(pool)

        assert result["total_users"] == 150
        assert result["active_7d"] == 42
        assert result["active_30d"] == 89
        assert result["oauth_connection_rate"] == pytest.approx(round(95 / 150, 4))
        assert result["registrations"]["daily"] == [{"date": "2026-03-18", "count": 5}]
        assert result["registrations"]["weekly"] == [{"week_start": "2026-03-17", "count": 12}]
        assert result["registrations"]["monthly"] == [{"month": "2026-03", "count": 34}]

    @pytest.mark.asyncio
    async def test_zero_users(self):
        from api.queries.admin_queries import get_user_stats

        pool, execute_side_effect = _mock_pool_with_rows(
            [{"total_users": 0, "oauth_users": 0, "active_7d": 0, "active_30d": 0}],
            [],
            [],
            [],
        )

        with patch("api.queries.admin_queries.execute_sql", side_effect=execute_side_effect):
            result = await get_user_stats(pool)

        assert result["total_users"] == 0
        assert result["oauth_connection_rate"] == 0.0
        assert result["registrations"]["daily"] == []

    @pytest.mark.asyncio
    async def test_oauth_connection_rate_precision(self):
        from api.queries.admin_queries import get_user_stats

        pool, execute_side_effect = _mock_pool_with_rows(
            [{"total_users": 3, "oauth_users": 1, "active_7d": 1, "active_30d": 2}],
            [],
            [],
            [],
        )

        with patch("api.queries.admin_queries.execute_sql", side_effect=execute_side_effect):
            result = await get_user_stats(pool)

        # round(..., 4) applied
        assert result["oauth_connection_rate"] == pytest.approx(round(1 / 3, 4))

    @pytest.mark.asyncio
    async def test_empty_registrations(self):
        from api.queries.admin_queries import get_user_stats

        pool, execute_side_effect = _mock_pool_with_rows(
            [{"total_users": 10, "oauth_users": 5, "active_7d": 2, "active_30d": 4}],
            [],
            [],
            [],
        )

        with patch("api.queries.admin_queries.execute_sql", side_effect=execute_side_effect):
            result = await get_user_stats(pool)

        assert result["registrations"]["daily"] == []
        assert result["registrations"]["weekly"] == []
        assert result["registrations"]["monthly"] == []

    @pytest.mark.asyncio
    async def test_multiple_registration_rows(self):
        from api.queries.admin_queries import get_user_stats

        daily_rows = [
            {"date": "2026-03-01", "count": 3},
            {"date": "2026-03-02", "count": 7},
            {"date": "2026-03-03", "count": 2},
        ]
        weekly_rows = [
            {"week_start": "2026-02-10", "count": 20},
            {"week_start": "2026-02-17", "count": 15},
        ]
        monthly_rows = [
            {"month": "2026-01", "count": 50},
            {"month": "2026-02", "count": 60},
            {"month": "2026-03", "count": 40},
        ]

        pool, execute_side_effect = _mock_pool_with_rows(
            [{"total_users": 200, "oauth_users": 100, "active_7d": 30, "active_30d": 80}],
            daily_rows,
            weekly_rows,
            monthly_rows,
        )

        with patch("api.queries.admin_queries.execute_sql", side_effect=execute_side_effect):
            result = await get_user_stats(pool)

        assert result["registrations"]["daily"] == daily_rows
        assert result["registrations"]["weekly"] == weekly_rows
        assert result["registrations"]["monthly"] == monthly_rows
        assert result["total_users"] == 200
        assert result["active_7d"] == 30
        assert result["active_30d"] == 80


class TestGetSyncActivity:
    """Tests for get_sync_activity query function."""

    @pytest.mark.asyncio
    async def test_basic_sync_activity(self):
        from api.queries.admin_queries import get_sync_activity

        pool, execute_side_effect = _mock_pool_with_rows(
            [{"total_syncs": 28, "total_failures": 2, "avg_items": 142.5}],
            [{"total_syncs": 95, "total_failures": 5, "avg_items": 138.2}],
        )

        with patch("api.queries.admin_queries.execute_sql", side_effect=execute_side_effect):
            result = await get_sync_activity(pool)

        assert result["period_7d"]["total_syncs"] == 28
        assert result["period_7d"]["syncs_per_day"] == pytest.approx(4.0)
        assert result["period_7d"]["failure_rate"] == pytest.approx(round(2 / 28, 4))
        assert result["period_30d"]["total_syncs"] == 95

    @pytest.mark.asyncio
    async def test_zero_syncs(self):
        from api.queries.admin_queries import get_sync_activity

        pool, execute_side_effect = _mock_pool_with_rows(
            [{"total_syncs": 0, "total_failures": 0, "avg_items": None}],
            [{"total_syncs": 0, "total_failures": 0, "avg_items": None}],
        )

        with patch("api.queries.admin_queries.execute_sql", side_effect=execute_side_effect):
            result = await get_sync_activity(pool)

        assert result["period_7d"]["syncs_per_day"] == 0.0
        assert result["period_7d"]["failure_rate"] == 0.0
        assert result["period_7d"]["avg_items_synced"] == 0.0


class TestGetNeo4jStorage:
    """Tests for get_neo4j_storage query function."""

    @pytest.mark.asyncio
    async def test_basic_neo4j_storage(self):
        from api.queries.admin_queries import get_neo4j_storage

        mock_result = AsyncMock()
        mock_result.single = AsyncMock(
            return_value={
                "labels": {"Artist": 245000, "Label": 5000},
                "relTypesCount": {"RELEASED_ON": 890000, "BY": 600000},
            }
        )

        # First session: apoc.meta.stats succeeds
        mock_session1 = AsyncMock()
        mock_session1.run = AsyncMock(return_value=mock_result)
        mock_session1.__aenter__ = AsyncMock(return_value=mock_session1)
        mock_session1.__aexit__ = AsyncMock(return_value=False)

        # Second session: JMX query raises so store_sizes stays None
        mock_session2 = AsyncMock()
        mock_session2.run = AsyncMock(side_effect=Exception("JMX not available"))
        mock_session2.__aenter__ = AsyncMock(return_value=mock_session2)
        mock_session2.__aexit__ = AsyncMock(return_value=False)

        mock_driver = MagicMock()
        mock_driver.session = MagicMock(side_effect=[mock_session1, mock_session2])

        result = await get_neo4j_storage(mock_driver)

        assert result["status"] == "ok"
        assert {"label": "Artist", "count": 245000} in result["nodes"]
        assert {"type": "RELEASED_ON", "count": 890000} in result["relationships"]
        assert result["store_sizes"] is None

    @pytest.mark.asyncio
    async def test_neo4j_with_jmx_store_sizes(self):
        """Test the JMX store sizes happy path (lines 141-154)."""
        from api.queries.admin_queries import get_neo4j_storage

        # apoc.meta.stats result
        mock_stats_result = AsyncMock()
        mock_stats_result.single = AsyncMock(
            return_value={
                "labels": {"Artist": 100},
                "relTypesCount": {"BY": 200},
            }
        )

        # JMX result with store size attributes
        mock_jmx_result = AsyncMock()
        mock_jmx_result.single = AsyncMock(
            return_value={
                "attributes": {
                    "TotalStoreSize": {"value": 2_200_000_000},
                    "NodeStoreSize": {"value": 800_000_000},
                    "RelationshipStoreSize": {"value": 1_100_000_000},
                    "StringStoreSize": {"value": 200_000_000},
                },
            }
        )

        mock_session1 = AsyncMock()
        mock_session1.run = AsyncMock(return_value=mock_stats_result)
        mock_session1.__aenter__ = AsyncMock(return_value=mock_session1)
        mock_session1.__aexit__ = AsyncMock(return_value=False)

        mock_session2 = AsyncMock()
        mock_session2.run = AsyncMock(return_value=mock_jmx_result)
        mock_session2.__aenter__ = AsyncMock(return_value=mock_session2)
        mock_session2.__aexit__ = AsyncMock(return_value=False)

        mock_driver = MagicMock()
        mock_driver.session = MagicMock(side_effect=[mock_session1, mock_session2])

        result = await get_neo4j_storage(mock_driver)

        assert result["status"] == "ok"
        assert result["store_sizes"] is not None
        assert result["store_sizes"]["total"] == "2.0 GB"
        assert result["store_sizes"]["nodes"] == "763 MB"
        assert result["store_sizes"]["relationships"] == "1.0 GB"
        assert result["store_sizes"]["strings"] == "191 MB"

    @pytest.mark.asyncio
    async def test_neo4j_driver_none(self):
        from api.queries.admin_queries import get_neo4j_storage

        result = await get_neo4j_storage(None)
        assert result["status"] == "error"
        assert "not configured" in result["error"]


class TestGetPostgresStorage:
    """Tests for get_postgres_storage query function."""

    @pytest.mark.asyncio
    async def test_basic_postgres_storage(self):
        from api.queries.admin_queries import get_postgres_storage

        pool, execute_side_effect = _mock_pool_with_rows(
            [{"table_name": "users", "row_estimate": 150, "total_size": "48 kB", "index_size": "32 kB"}],
            [{"total_size": "156 MB"}],
        )

        with patch("api.queries.admin_queries.execute_sql", side_effect=execute_side_effect):
            result = await get_postgres_storage(pool)

        assert result["status"] == "ok"
        assert result["tables"][0]["name"] == "users"
        assert result["tables"][0]["row_count"] == 150
        assert result["tables"][0]["size"] == "48 kB"
        assert result["tables"][0]["index_size"] == "32 kB"
        assert result["total_size"] == "156 MB"

    @pytest.mark.asyncio
    async def test_empty_tables(self):
        from api.queries.admin_queries import get_postgres_storage

        pool, execute_side_effect = _mock_pool_with_rows(
            [],
            [{"total_size": "8192 bytes"}],
        )

        with patch("api.queries.admin_queries.execute_sql", side_effect=execute_side_effect):
            result = await get_postgres_storage(pool)

        assert result["status"] == "ok"
        assert result["tables"] == []
        assert result["total_size"] == "8192 bytes"


class TestGetRedisStorage:
    """Tests for get_redis_storage query function."""

    @pytest.mark.asyncio
    async def test_basic_redis_storage(self):
        from api.queries.admin_queries import get_redis_storage

        mock_redis = AsyncMock()
        mock_redis.info = AsyncMock(
            side_effect=lambda section: {
                "memory": {"used_memory_human": "12.5M", "used_memory_peak_human": "15.2M"},
                "keyspace": {"db0": {"keys": 342}},
            }.get(section, {})
        )
        mock_redis.scan = AsyncMock(return_value=(0, [b"cache:foo", b"cache:bar", b"revoked:jti:abc"]))

        result = await get_redis_storage(mock_redis)

        assert result["status"] == "ok"
        assert result["memory_used"] == "12.5M"
        assert result["memory_peak"] == "15.2M"
        assert result["total_keys"] == 342
        assert any(entry["prefix"] == "cache:" for entry in result["keys_by_prefix"])
        assert any(entry["prefix"] == "revoked:" for entry in result["keys_by_prefix"])

    @pytest.mark.asyncio
    async def test_redis_none(self):
        from api.queries.admin_queries import get_redis_storage

        result = await get_redis_storage(None)
        assert result["status"] == "error"
        assert "not configured" in result["error"]

    @pytest.mark.asyncio
    async def test_redis_no_keys(self):
        from api.queries.admin_queries import get_redis_storage

        mock_redis = AsyncMock()
        mock_redis.info = AsyncMock(
            side_effect=lambda section: {
                "memory": {"used_memory_human": "1.2M", "used_memory_peak_human": "1.5M"},
                "keyspace": {},
            }.get(section, {})
        )
        mock_redis.scan = AsyncMock(return_value=(0, []))

        result = await get_redis_storage(mock_redis)

        assert result["status"] == "ok"
        assert result["total_keys"] == 0
        assert result["keys_by_prefix"] == []


class TestGetAuditLog:
    @pytest.mark.asyncio
    async def test_returns_paginated_entries(self) -> None:
        from api.queries.admin_queries import get_audit_log

        mock_cur = AsyncMock()
        mock_cur.fetchone = AsyncMock(return_value={"total": 2})
        mock_cur.fetchall = AsyncMock(
            return_value=[
                {
                    "id": "uuid-1",
                    "admin_id": "admin-uuid",
                    "admin_email": "admin@test.com",
                    "action": "admin.login",
                    "target": "admin@test.com",
                    "details": {"success": True},
                    "created_at": datetime.now(UTC),
                },
                {
                    "id": "uuid-2",
                    "admin_id": "admin-uuid",
                    "admin_email": "admin@test.com",
                    "action": "dlq.purge",
                    "target": "graphinator-artists-dlq",
                    "details": {"purged_count": 3},
                    "created_at": datetime.now(UTC),
                },
            ]
        )
        mock_conn = AsyncMock()
        cur_ctx = AsyncMock()
        cur_ctx.__aenter__ = AsyncMock(return_value=mock_cur)
        cur_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_conn.cursor = MagicMock(return_value=cur_ctx)
        conn_ctx = AsyncMock()
        conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        conn_ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.connection = MagicMock(return_value=conn_ctx)

        result = await get_audit_log(pool, page=1, page_size=50)
        assert result["total"] == 2
        assert len(result["entries"]) == 2
        assert result["page"] == 1
        assert result["page_size"] == 50

    @pytest.mark.asyncio
    async def test_filters_by_action(self) -> None:
        from api.queries.admin_queries import get_audit_log

        mock_cur = AsyncMock()
        mock_cur.fetchone = AsyncMock(return_value={"total": 0})
        mock_cur.fetchall = AsyncMock(return_value=[])
        mock_conn = AsyncMock()
        cur_ctx = AsyncMock()
        cur_ctx.__aenter__ = AsyncMock(return_value=mock_cur)
        cur_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_conn.cursor = MagicMock(return_value=cur_ctx)
        conn_ctx = AsyncMock()
        conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        conn_ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.connection = MagicMock(return_value=conn_ctx)

        await get_audit_log(pool, page=1, page_size=50, action_filter="dlq.purge")

        count_call = mock_cur.execute.call_args_list[0]
        assert "action = %s" in count_call[0][0]

    @pytest.mark.asyncio
    async def test_filters_by_admin_id(self) -> None:
        from api.queries.admin_queries import get_audit_log

        mock_cur = AsyncMock()
        mock_cur.fetchone = AsyncMock(return_value={"total": 0})
        mock_cur.fetchall = AsyncMock(return_value=[])
        mock_conn = AsyncMock()
        cur_ctx = AsyncMock()
        cur_ctx.__aenter__ = AsyncMock(return_value=mock_cur)
        cur_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_conn.cursor = MagicMock(return_value=cur_ctx)
        conn_ctx = AsyncMock()
        conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        conn_ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.connection = MagicMock(return_value=conn_ctx)

        result = await get_audit_log(pool, page=1, page_size=50, admin_id_filter="admin-uuid-123")
        assert result["total"] == 0
        assert result["entries"] == []
        # Verify SQL was called with admin_id parameter
        count_call = mock_cur.execute.call_args_list[0]
        assert "admin_id" in count_call[0][0]

    @pytest.mark.asyncio
    async def test_filters_by_both_action_and_admin_id(self) -> None:
        from api.queries.admin_queries import get_audit_log

        mock_cur = AsyncMock()
        mock_cur.fetchone = AsyncMock(return_value={"total": 0})
        mock_cur.fetchall = AsyncMock(return_value=[])
        mock_conn = AsyncMock()
        cur_ctx = AsyncMock()
        cur_ctx.__aenter__ = AsyncMock(return_value=mock_cur)
        cur_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_conn.cursor = MagicMock(return_value=cur_ctx)
        conn_ctx = AsyncMock()
        conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        conn_ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.connection = MagicMock(return_value=conn_ctx)

        result = await get_audit_log(pool, page=1, page_size=50, action_filter="dlq.purge", admin_id_filter="admin-uuid-123")
        assert result["total"] == 0
        # Verify SQL was called with both parameters
        count_call = mock_cur.execute.call_args_list[0]
        sql = count_call[0][0]
        assert "action" in sql
        assert "admin_id" in sql
