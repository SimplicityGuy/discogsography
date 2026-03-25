"""Tests for api/queries/admin_queries.py."""

from __future__ import annotations

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
