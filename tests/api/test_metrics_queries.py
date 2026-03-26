"""Tests for api/queries/metrics_queries.py — time-series aggregation queries."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.queries.metrics_queries import (
    GRANULARITY_MAP,
    _bucket_to_trunc_unit,
    _round_or_int,
    get_health_history,
    get_queue_history,
)


def _mock_pool_with_rows(*results: list[dict]) -> MagicMock:
    """Build a mock pool whose cursor returns successive fetchall() results."""
    results_iter = iter(results)

    mock_cur = AsyncMock()

    async def _fetchall_side_effect():
        return mock_cur._current_result

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

    pool = MagicMock()
    pool.connection = MagicMock(return_value=mock_conn_ctx)

    async def _execute_sql_side_effect(_cur, _query, _params=None):
        mock_cur._current_result = next(results_iter)

    return pool, _execute_sql_side_effect


class TestGranularityMap:
    """Tests for GRANULARITY_MAP constant."""

    def test_all_expected_ranges_present(self):
        expected = {"1h", "6h", "24h", "7d", "30d", "90d", "365d"}
        assert set(GRANULARITY_MAP.keys()) == expected

    @pytest.mark.parametrize("range_key", ["1h", "6h", "24h", "7d", "30d", "90d", "365d"])
    def test_each_range_has_required_keys(self, range_key):
        entry = GRANULARITY_MAP[range_key]
        assert "interval" in entry
        assert "bucket" in entry
        assert "raw" in entry
        assert "granularity" in entry

    def test_raw_ranges(self):
        assert GRANULARITY_MAP["1h"]["raw"] is True
        assert GRANULARITY_MAP["6h"]["raw"] is True

    def test_aggregated_ranges(self):
        for key in ("24h", "7d", "30d", "90d", "365d"):
            assert GRANULARITY_MAP[key]["raw"] is False


class TestHelpers:
    """Tests for helper functions."""

    def test_bucket_to_trunc_unit_minutes(self):
        assert _bucket_to_trunc_unit("5 minutes") == "minute"
        assert _bucket_to_trunc_unit("15 minutes") == "minute"

    def test_bucket_to_trunc_unit_hour(self):
        assert _bucket_to_trunc_unit("1 hour") == "hour"

    def test_bucket_to_trunc_unit_day(self):
        assert _bucket_to_trunc_unit("1 day") == "day"

    def test_bucket_to_trunc_unit_hours(self):
        assert _bucket_to_trunc_unit("6 hours") == "hour"

    def test_round_or_int_raw(self):
        assert _round_or_int(42.7, is_raw=True) == 42
        assert isinstance(_round_or_int(42.7, is_raw=True), int)

    def test_round_or_int_aggregated(self):
        assert _round_or_int(42.678, is_raw=False) == 42.68
        assert isinstance(_round_or_int(42.678, is_raw=False), float)

    def test_round_or_int_none(self):
        assert _round_or_int(None, is_raw=True) == 0
        assert _round_or_int(None, is_raw=False) == 0.0


class TestGetQueueHistory:
    """Tests for get_queue_history query function."""

    @pytest.mark.asyncio
    async def test_raw_range_basic(self):
        rows = [
            {
                "queue_name": "graphinator-artists",
                "ts": "2026-03-25T10:00:00",
                "ready": 10,
                "unacked": 2,
                "total": 12,
                "publish_rate": 5.0,
                "deliver_rate": 4.0,
            },
            {
                "queue_name": "graphinator-artists",
                "ts": "2026-03-25T10:05:00",
                "ready": 8,
                "unacked": 1,
                "total": 9,
                "publish_rate": 3.0,
                "deliver_rate": 3.0,
            },
        ]
        pool, execute_side_effect = _mock_pool_with_rows(rows)

        with patch("api.queries.metrics_queries.execute_sql", side_effect=execute_side_effect):
            result = await get_queue_history(pool, "1h")

        assert result["range"] == "1h"
        assert result["granularity"] == "5min"
        assert "graphinator-artists" in result["queues"]
        queue = result["queues"]["graphinator-artists"]
        assert len(queue["history"]) == 2
        assert queue["current"]["ready"] == 8
        assert result["dlq_summary"] == {}

    @pytest.mark.asyncio
    async def test_dlq_separation(self):
        rows = [
            {
                "queue_name": "graphinator-artists",
                "ts": "2026-03-25T10:00:00",
                "ready": 10,
                "unacked": 2,
                "total": 12,
                "publish_rate": 5.0,
                "deliver_rate": 4.0,
            },
            {
                "queue_name": "graphinator-artists-dlq",
                "ts": "2026-03-25T10:00:00",
                "ready": 3,
                "unacked": 0,
                "total": 3,
                "publish_rate": 0.0,
                "deliver_rate": 0.0,
            },
        ]
        pool, execute_side_effect = _mock_pool_with_rows(rows)

        with patch("api.queries.metrics_queries.execute_sql", side_effect=execute_side_effect):
            result = await get_queue_history(pool, "1h")

        assert "graphinator-artists" in result["queues"]
        assert "graphinator-artists-dlq" not in result["queues"]
        assert "graphinator-artists-dlq" in result["dlq_summary"]
        assert result["dlq_summary"]["graphinator-artists-dlq"]["current"]["ready"] == 3

    @pytest.mark.asyncio
    async def test_empty_data(self):
        pool, execute_side_effect = _mock_pool_with_rows([])

        with patch("api.queries.metrics_queries.execute_sql", side_effect=execute_side_effect):
            result = await get_queue_history(pool, "6h")

        assert result["range"] == "6h"
        assert result["queues"] == {}
        assert result["dlq_summary"] == {}

    @pytest.mark.asyncio
    async def test_aggregated_range(self):
        rows = [
            {
                "queue_name": "graphinator-artists",
                "ts": "2026-03-25T10:00:00",
                "ready": 10.5,
                "unacked": 2.3,
                "total": 12.8,
                "publish_rate": 5.2,
                "deliver_rate": 4.1,
            },
        ]
        pool, execute_side_effect = _mock_pool_with_rows(rows)

        with patch("api.queries.metrics_queries.execute_sql", side_effect=execute_side_effect):
            result = await get_queue_history(pool, "24h")

        assert result["granularity"] == "15min"
        queue = result["queues"]["graphinator-artists"]
        # Aggregated values should be rounded floats
        assert isinstance(queue["history"][0]["ready"], float)

    @pytest.mark.asyncio
    async def test_invalid_range(self):
        pool = MagicMock()
        with pytest.raises(ValueError, match="Invalid range"):
            await get_queue_history(pool, "99h")


class TestGetHealthHistory:
    """Tests for get_health_history query function."""

    @pytest.mark.asyncio
    async def test_basic_health_history(self):
        health_rows = [
            {"service_name": "api", "ts": "2026-03-25T10:00:00", "status": "healthy", "response_time_ms": 42, "endpoint_stats": None},
            {
                "service_name": "api",
                "ts": "2026-03-25T10:05:00",
                "status": "healthy",
                "response_time_ms": 38,
                "endpoint_stats": '{"/api/explore": {"avg_latency_ms": 40.1}}',
            },
            {"service_name": "api", "ts": "2026-03-25T10:10:00", "status": "unhealthy", "response_time_ms": 500, "endpoint_stats": None},
        ]
        pool, execute_side_effect = _mock_pool_with_rows(health_rows)

        with patch("api.queries.metrics_queries.execute_sql", side_effect=execute_side_effect):
            result = await get_health_history(pool, "1h")

        assert result["range"] == "1h"
        assert result["granularity"] == "5min"
        assert "api" in result["services"]
        svc = result["services"]["api"]
        assert len(svc["history"]) == 3
        # 2 out of 3 are healthy = 66.67%
        assert svc["uptime_pct"] == pytest.approx(66.67)
        assert svc["current"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_empty_data(self):
        pool, execute_side_effect = _mock_pool_with_rows([])

        with patch("api.queries.metrics_queries.execute_sql", side_effect=execute_side_effect):
            result = await get_health_history(pool, "6h")

        assert result["services"] == {}
        assert result["api_endpoints"] == {}

    @pytest.mark.asyncio
    async def test_uptime_all_healthy(self):
        rows = [
            {"service_name": "api", "ts": "2026-03-25T10:00:00", "status": "healthy", "response_time_ms": 30, "endpoint_stats": None},
            {"service_name": "api", "ts": "2026-03-25T10:05:00", "status": "healthy", "response_time_ms": 32, "endpoint_stats": None},
        ]
        pool, execute_side_effect = _mock_pool_with_rows(rows)

        with patch("api.queries.metrics_queries.execute_sql", side_effect=execute_side_effect):
            result = await get_health_history(pool, "1h")

        assert result["services"]["api"]["uptime_pct"] == 100.0

    @pytest.mark.asyncio
    async def test_endpoint_stats_parsing(self):
        rows = [
            {
                "service_name": "api",
                "ts": "2026-03-25T10:00:00",
                "status": "healthy",
                "response_time_ms": 30,
                "endpoint_stats": '{"/api/explore": {"avg_latency_ms": 40.1, "p99_ms": 120}}',
            },
            {
                "service_name": "api",
                "ts": "2026-03-25T10:05:00",
                "status": "healthy",
                "response_time_ms": 32,
                "endpoint_stats": '{"/api/explore": {"avg_latency_ms": 45.2, "p99_ms": 130}}',
            },
        ]
        pool, execute_side_effect = _mock_pool_with_rows(rows)

        with patch("api.queries.metrics_queries.execute_sql", side_effect=execute_side_effect):
            result = await get_health_history(pool, "1h")

        assert "/api/explore" in result["api_endpoints"]
        ep = result["api_endpoints"]["/api/explore"]
        assert len(ep["history"]) == 2

    @pytest.mark.asyncio
    async def test_invalid_range(self):
        pool = MagicMock()
        with pytest.raises(ValueError, match="Invalid range"):
            await get_health_history(pool, "2w")
