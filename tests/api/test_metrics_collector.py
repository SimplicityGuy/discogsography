"""Tests for api.metrics_collector — path normalization, buffer, collection, persistence."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Task 3: Path normalization
# ---------------------------------------------------------------------------


class TestNormalizePath:
    """Test normalize_path replaces integer and UUID segments with :id."""

    def test_integer_segment(self) -> None:
        from api.metrics_collector import normalize_path

        assert normalize_path("/api/artists/12345") == "/api/artists/:id"

    def test_uuid_segment(self) -> None:
        from api.metrics_collector import normalize_path

        assert normalize_path("/api/users/550e8400-e29b-41d4-a716-446655440000/profile") == "/api/users/:id/profile"

    def test_multiple_ids(self) -> None:
        from api.metrics_collector import normalize_path

        assert normalize_path("/api/labels/42/releases/99") == "/api/labels/:id/releases/:id"

    def test_no_ids(self) -> None:
        from api.metrics_collector import normalize_path

        assert normalize_path("/api/search") == "/api/search"

    def test_admin_path_normalized(self) -> None:
        from api.metrics_collector import normalize_path

        assert normalize_path("/api/admin/users/7") == "/api/admin/users/:id"

    def test_uuid_at_end(self) -> None:
        from api.metrics_collector import normalize_path

        assert normalize_path("/api/snapshots/AABBCCDD-1122-3344-5566-778899aabbcc") == "/api/snapshots/:id"


# ---------------------------------------------------------------------------
# Task 3: MetricsBuffer
# ---------------------------------------------------------------------------


class TestMetricsBuffer:
    """Test MetricsBuffer record + flush behaviour."""

    def test_record_and_flush(self) -> None:
        from api.metrics_collector import MetricsBuffer

        buf = MetricsBuffer(max_size=100)
        buf.record("/api/artists/:id", 200, 15.0)
        buf.record("/api/artists/:id", 200, 25.0)
        buf.record("/api/search", 200, 5.0)

        result = buf.flush()
        assert "/api/artists/:id" in result
        assert "/api/search" in result
        stats = result["/api/artists/:id"]
        assert stats["count"] == 2
        assert stats["error_count"] == 0

    def test_flush_is_non_destructive(self) -> None:
        """flush() must NOT clear the buffer — only clear() does, and only after a successful persist."""
        from api.metrics_collector import MetricsBuffer

        buf = MetricsBuffer(max_size=100)
        buf.record("/api/search", 200, 10.0)
        first = buf.flush()
        second = buf.flush()
        assert first == second
        assert second["/api/search"]["count"] == 1

    def test_clear_empties_buffer(self) -> None:
        from api.metrics_collector import MetricsBuffer

        buf = MetricsBuffer(max_size=100)
        buf.record("/api/search", 200, 10.0)
        buf.flush()
        buf.clear()
        result = buf.flush()
        assert result == {}

    def test_flush_after_failed_persist_accumulates(self) -> None:
        """Entries recorded between a failed flush and the retry are included next cycle."""
        from api.metrics_collector import MetricsBuffer

        buf = MetricsBuffer(max_size=100)
        buf.record("/api/search", 200, 10.0)
        first = buf.flush()
        assert first["/api/search"]["count"] == 1

        # Simulate more requests arriving before the buffer is ever cleared
        buf.record("/api/search", 200, 20.0)
        second = buf.flush()
        assert second["/api/search"]["count"] == 2

    def test_max_size_drops_oldest(self) -> None:
        from api.metrics_collector import MetricsBuffer

        buf = MetricsBuffer(max_size=3)
        buf.record("/a", 200, 1.0)
        buf.record("/b", 200, 2.0)
        buf.record("/c", 200, 3.0)
        buf.record("/d", 200, 4.0)  # should evict /a
        result = buf.flush()
        # /a should be gone, /b /c /d present
        all_paths = set(result.keys())
        assert "/a" not in all_paths
        assert "/d" in all_paths

    def test_percentile_computation(self) -> None:
        from api.metrics_collector import MetricsBuffer

        buf = MetricsBuffer(max_size=200)
        for i in range(1, 101):
            buf.record("/api/test", 200, float(i))
        result = buf.flush()
        stats = result["/api/test"]
        assert stats["p50"] == pytest.approx(50.0, abs=1.0)
        assert stats["p95"] == pytest.approx(95.0, abs=1.0)
        assert stats["p99"] == pytest.approx(99.0, abs=1.0)

    def test_error_count(self) -> None:
        from api.metrics_collector import MetricsBuffer

        buf = MetricsBuffer(max_size=100)
        buf.record("/api/x", 200, 1.0)
        buf.record("/api/x", 500, 2.0)
        buf.record("/api/x", 503, 3.0)
        result = buf.flush()
        assert result["/api/x"]["error_count"] == 2

    def test_excluded_paths_not_recorded(self) -> None:
        from api.metrics_collector import MetricsBuffer

        buf = MetricsBuffer(max_size=100)
        buf.record("/health", 200, 1.0)
        buf.record("/metrics", 200, 1.0)
        buf.record("/api/admin/users", 200, 1.0)
        buf.record("/api/admin/config/key", 200, 1.0)
        result = buf.flush()
        assert result == {}


class TestMetricsBufferDrainRestore:
    """discogsography-qtts: drain()/restore() must be safe to pair across an
    await, unlike flush()/clear() which race with concurrent record()."""

    def test_drain_removes_entries_and_returns_stats_and_samples(self) -> None:
        from api.metrics_collector import MetricsBuffer

        buf = MetricsBuffer(max_size=100)
        buf.record("/api/search", 200, 10.0)
        buf.record("/api/search", 200, 20.0)

        stats, samples = buf.drain()

        assert stats["/api/search"]["count"] == 2
        assert len(samples) == 2
        # Unlike flush(), drain() actually empties the live buffer.
        assert buf.flush() == {}

    def test_entries_recorded_after_drain_are_not_in_the_snapshot(self) -> None:
        """The whole point of the atomic swap: anything record()ed AFTER
        drain() returns must land in the fresh buffer, never in the
        snapshot drain() already computed stats from."""
        from api.metrics_collector import MetricsBuffer

        buf = MetricsBuffer(max_size=100)
        buf.record("/api/before", 200, 5.0)

        stats, samples = buf.drain()
        buf.record("/api/after", 200, 7.0)

        assert "/api/before" in stats
        assert "/api/after" not in stats
        assert all(s.path == "/api/before" for s in samples)
        # The post-drain record must be visible in a fresh flush.
        assert buf.flush() == {"/api/after": {"count": 1, "p50": 7.0, "p95": 7.0, "p99": 7.0, "error_count": 0}}

    def test_restore_puts_samples_back_ahead_of_newer_entries(self) -> None:
        """restore() must re-prepend the failed batch AHEAD of (i.e. older
        than) anything recorded since the matching drain() — samples arrived
        first in wall-clock terms and eviction order must reflect that."""
        from api.metrics_collector import MetricsBuffer

        buf = MetricsBuffer(max_size=100)
        buf.record("/api/before", 200, 5.0)
        _stats, samples = buf.drain()
        buf.record("/api/after", 200, 7.0)

        buf.restore(samples)

        result = buf.flush()
        assert result["/api/before"]["count"] == 1
        assert result["/api/after"]["count"] == 1
        # "before" was recorded first and restored ahead of "after" — it must
        # be the entry evicted first once the buffer fills.
        buf2 = MetricsBuffer(max_size=1)
        buf2.restore(samples)
        buf2.record("/api/after", 200, 7.0)
        assert buf2.flush() == {"/api/after": {"count": 1, "p50": 7.0, "p95": 7.0, "p99": 7.0, "error_count": 0}}

    def test_restore_trims_to_max_size_from_the_left(self) -> None:
        """A restore that would push the buffer over max_size must evict the
        OLDEST entries first — the same order record()'s own eviction uses."""
        from api.metrics_collector import MetricsBuffer

        buf = MetricsBuffer(max_size=3)
        buf.record("/a", 200, 1.0)
        buf.record("/b", 200, 2.0)
        _stats, samples = buf.drain()  # samples = [/a, /b]
        buf.record("/c", 200, 3.0)
        buf.record("/d", 200, 4.0)

        buf.restore(samples)  # would be [/a, /b, /c, /d] — over max_size=3

        result = buf.flush()
        assert len(buf._entries) == 3
        assert "/a" not in result  # oldest, evicted first
        assert "/b" in result
        assert "/c" in result
        assert "/d" in result

    def test_restore_with_empty_samples_is_a_no_op(self) -> None:
        from api.metrics_collector import MetricsBuffer

        buf = MetricsBuffer(max_size=100)
        buf.record("/api/x", 200, 1.0)
        buf.drain()  # empties the buffer
        _stats, empty_samples = buf.drain()  # nothing left to drain this time
        assert len(empty_samples) == 0

        buf.restore(empty_samples)  # nothing to restore

        assert buf.flush() == {}

    def test_drain_on_empty_buffer_returns_empty_stats_and_samples(self) -> None:
        from api.metrics_collector import MetricsBuffer

        buf = MetricsBuffer(max_size=100)
        stats, samples = buf.drain()

        assert stats == {}
        assert len(samples) == 0


# ---------------------------------------------------------------------------
# Task 3: _percentile_index helper
# ---------------------------------------------------------------------------


class TestPercentileIndex:
    """Test the _percentile_index helper."""

    def test_basic(self) -> None:
        from api.metrics_collector import _percentile_index

        assert _percentile_index(100, 50) == 49
        assert _percentile_index(100, 95) == 94
        assert _percentile_index(100, 99) == 98

    def test_small_n(self) -> None:
        from api.metrics_collector import _percentile_index

        assert _percentile_index(1, 99) == 0


# ---------------------------------------------------------------------------
# Task 4: collect_queue_metrics
# ---------------------------------------------------------------------------


class TestCollectQueueMetrics:
    """Test collect_queue_metrics with mocked httpx."""

    @pytest.mark.anyio
    async def test_returns_filtered_queues(self) -> None:
        from api.metrics_collector import collect_queue_metrics

        fake_queues = [
            {
                "name": "discogsography-artists-graphinator",
                "messages_ready": 10,
                "messages_unacknowledged": 2,
                "consumers": 1,
                "message_stats": {"publish_details": {"rate": 5.0}, "ack_details": {"rate": 3.0}},
            },
            {
                "name": "other-queue",
                "messages_ready": 99,
                "messages_unacknowledged": 0,
                "consumers": 0,
            },
        ]
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = fake_queues

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("api.metrics_collector.httpx.AsyncClient", return_value=mock_client):
            rows = await collect_queue_metrics("localhost", 15672, "guest", "guest")

        assert len(rows) == 1
        assert rows[0]["queue_name"] == "discogsography-artists-graphinator"
        assert rows[0]["messages_ready"] == 10
        assert rows[0]["publish_rate"] == pytest.approx(5.0)
        assert rows[0]["ack_rate"] == pytest.approx(3.0)

    @pytest.mark.anyio
    async def test_returns_empty_on_failure(self) -> None:
        from api.metrics_collector import collect_queue_metrics

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("api.metrics_collector.httpx.AsyncClient", return_value=mock_client):
            rows = await collect_queue_metrics("localhost", 15672, "guest", "guest")

        assert rows == []

    @pytest.mark.anyio
    async def test_missing_message_stats(self) -> None:
        """Queues without message_stats should have zero rates."""
        from api.metrics_collector import collect_queue_metrics

        fake_queues = [
            {
                "name": "discogsography-releases-tableinator",
                "messages_ready": 0,
                "messages_unacknowledged": 0,
                "consumers": 1,
            },
        ]
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = fake_queues

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("api.metrics_collector.httpx.AsyncClient", return_value=mock_client):
            rows = await collect_queue_metrics("localhost", 15672, "guest", "guest")

        assert len(rows) == 1
        assert rows[0]["publish_rate"] == 0.0
        assert rows[0]["ack_rate"] == 0.0


# ---------------------------------------------------------------------------
# Task 4: collect_service_health
# ---------------------------------------------------------------------------


class TestCollectServiceHealth:
    """Test collect_service_health with mocked httpx."""

    @pytest.mark.anyio
    async def test_healthy_service(self) -> None:
        from api.metrics_collector import collect_service_health

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("api.metrics_collector.httpx.AsyncClient", return_value=mock_client):
            rows = await collect_service_health()

        assert len(rows) > 0
        # All services should be healthy since mock returns 200
        for row in rows:
            assert row["status"] == "healthy"
            assert row["response_time_ms"] >= 0

    @pytest.mark.anyio
    async def test_unreachable_service(self) -> None:
        from api.metrics_collector import collect_service_health

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("unreachable"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("api.metrics_collector.httpx.AsyncClient", return_value=mock_client):
            rows = await collect_service_health()

        for row in rows:
            assert row["status"] == "unknown"

    @pytest.mark.anyio
    async def test_custom_endpoints(self) -> None:
        from api.metrics_collector import collect_service_health

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        custom = {"myservice": ("myhost", 9999)}
        with patch("api.metrics_collector.httpx.AsyncClient", return_value=mock_client):
            rows = await collect_service_health(endpoints=custom)

        assert len(rows) == 1
        assert rows[0]["service_name"] == "myservice"


# ---------------------------------------------------------------------------
# Task 5: persist_metrics
# ---------------------------------------------------------------------------


class TestPersistMetrics:
    """Test persist_metrics inserts rows."""

    @pytest.mark.anyio
    async def test_inserts_rows(self) -> None:
        from api.metrics_collector import persist_metrics

        mock_cur = AsyncMock()

        # conn must be MagicMock so .cursor() is synchronous (returns cm, not coroutine)
        mock_conn = MagicMock()
        cursor_cm = MagicMock()
        cursor_cm.__aenter__ = AsyncMock(return_value=mock_cur)
        cursor_cm.__aexit__ = AsyncMock(return_value=False)
        mock_conn.cursor.return_value = cursor_cm

        conn_cm = MagicMock()
        conn_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        conn_cm.__aexit__ = AsyncMock(return_value=False)

        mock_pool = MagicMock()
        mock_pool.connection.return_value = conn_cm

        queue_rows = [
            {
                "queue_name": "discogsography-artists-graphinator",
                "messages_ready": 5,
                "messages_unacknowledged": 1,
                "consumers": 1,
                "publish_rate": 2.0,
                "ack_rate": 1.5,
            }
        ]
        health_rows = [
            {
                "service_name": "api",
                "status": "healthy",
                "response_time_ms": 12.3,
                "endpoint_stats": None,
            }
        ]

        await persist_metrics(mock_pool, queue_rows, health_rows)
        # Should have been called for queue insert and health insert
        assert mock_cur.executemany.call_count == 2

    @pytest.mark.anyio
    async def test_wraps_endpoint_stats_with_jsonb(self) -> None:
        """endpoint_stats dicts are wrapped with Jsonb() before insertion."""
        from psycopg.types.json import Jsonb

        from api.metrics_collector import persist_metrics

        mock_cur = AsyncMock()

        mock_conn = MagicMock()
        cursor_cm = MagicMock()
        cursor_cm.__aenter__ = AsyncMock(return_value=mock_cur)
        cursor_cm.__aexit__ = AsyncMock(return_value=False)
        mock_conn.cursor.return_value = cursor_cm

        conn_cm = MagicMock()
        conn_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        conn_cm.__aexit__ = AsyncMock(return_value=False)

        mock_pool = MagicMock()
        mock_pool.connection.return_value = conn_cm

        stats = {"/api/auth/me": {"count": 5, "p50": 1.2, "p95": 3.4, "p99": 5.0, "error_count": 0}}
        health_rows = [
            {
                "service_name": "api",
                "status": "healthy",
                "response_time_ms": 10.0,
                "endpoint_stats": stats,
            }
        ]

        await persist_metrics(mock_pool, [], health_rows)

        # Verify the dict was wrapped with Jsonb
        assert isinstance(health_rows[0]["endpoint_stats"], Jsonb)

    @pytest.mark.anyio
    async def test_noop_on_empty(self) -> None:
        from api.metrics_collector import persist_metrics

        mock_pool = MagicMock()
        # Should not raise or call anything
        await persist_metrics(mock_pool, [], [])


# ---------------------------------------------------------------------------
# Task 5: prune_old_metrics
# ---------------------------------------------------------------------------


class TestPruneOldMetrics:
    """Test prune_old_metrics deletes from both tables."""

    @pytest.mark.anyio
    async def test_deletes_both_tables(self) -> None:
        from api.metrics_collector import prune_old_metrics

        mock_cur = AsyncMock()

        mock_conn = MagicMock()
        cursor_cm = MagicMock()
        cursor_cm.__aenter__ = AsyncMock(return_value=mock_cur)
        cursor_cm.__aexit__ = AsyncMock(return_value=False)
        mock_conn.cursor.return_value = cursor_cm

        conn_cm = MagicMock()
        conn_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        conn_cm.__aexit__ = AsyncMock(return_value=False)

        mock_pool = MagicMock()
        mock_pool.connection.return_value = conn_cm

        await prune_old_metrics(mock_pool, 30)
        assert mock_cur.execute.call_count == 2
        # Verify both DELETE statements reference the tables
        calls = [str(c) for c in mock_cur.execute.call_args_list]
        combined = " ".join(calls)
        assert "queue_metrics" in combined
        assert "service_health_metrics" in combined


# ---------------------------------------------------------------------------
# Task 5: run_collector
# ---------------------------------------------------------------------------


class TestRunCollector:
    """Test run_collector loop logic."""

    @pytest.mark.anyio
    async def test_cancellation_reraises(self) -> None:
        """run_collector should re-raise CancelledError."""
        from api.metrics_collector import MetricsBuffer, run_collector

        mock_pool = MagicMock()
        config = MagicMock()
        config.rabbitmq_management_host = "localhost"
        config.rabbitmq_management_port = 15672
        config.rabbitmq_username = "guest"
        config.rabbitmq_password = "guest"
        config.metrics_retention_days = 30
        config.metrics_collection_interval = 1

        buf = MetricsBuffer(max_size=100)

        with (
            patch("api.metrics_collector.collect_queue_metrics", new_callable=AsyncMock) as mock_cq,
            patch("api.metrics_collector.collect_service_health", new_callable=AsyncMock) as mock_sh,
            patch("api.metrics_collector.persist_metrics", new_callable=AsyncMock),
            patch("api.metrics_collector.prune_old_metrics", new_callable=AsyncMock),
            patch("asyncio.sleep", side_effect=asyncio.CancelledError),
        ):
            mock_cq.return_value = []
            mock_sh.return_value = []
            with pytest.raises(asyncio.CancelledError):
                await run_collector(mock_pool, config, buf)

    @pytest.mark.anyio
    async def test_collector_attaches_endpoint_stats(self) -> None:
        """run_collector attaches endpoint_stats to a synthetic API health row."""
        from api.metrics_collector import MetricsBuffer, run_collector

        mock_pool = MagicMock()
        config = MagicMock()
        config.rabbitmq_management_host = "localhost"
        config.rabbitmq_management_port = 15672
        config.rabbitmq_username = "guest"
        config.rabbitmq_password = "guest"
        config.metrics_retention_days = 30
        config.metrics_collection_interval = 1

        buf = MetricsBuffer(max_size=100)
        buf.record("/api/search", 200, 10.0)

        persisted_health: list[list[dict[str, Any]]] = []

        async def capture_persist(_pool: Any, _q: Any, h: list[dict[str, Any]]) -> None:
            persisted_health.append(h)
            raise asyncio.CancelledError  # stop the loop

        with (
            patch("api.metrics_collector.collect_queue_metrics", new_callable=AsyncMock, return_value=[]),
            patch("api.metrics_collector.collect_service_health", new_callable=AsyncMock, return_value=[]),
            patch("api.metrics_collector.persist_metrics", side_effect=capture_persist),
            patch("api.metrics_collector.prune_old_metrics", new_callable=AsyncMock),
            pytest.raises(asyncio.CancelledError),
        ):
            await run_collector(mock_pool, config, buf)

        # Should have a synthetic "api" row with endpoint_stats
        assert len(persisted_health) == 1
        api_rows = [r for r in persisted_health[0] if r["service_name"] == "api"]
        assert len(api_rows) == 1
        assert api_rows[0]["endpoint_stats"] is not None
        assert "/api/search" in api_rows[0]["endpoint_stats"]

    @pytest.mark.anyio
    async def test_collector_attaches_stats_to_existing_api_row(self) -> None:
        """When health_rows already has an 'api' entry, endpoint_stats is attached to it."""
        from api.metrics_collector import MetricsBuffer, run_collector

        mock_pool = MagicMock()
        config = MagicMock()
        config.rabbitmq_management_host = "localhost"
        config.rabbitmq_management_port = 15672
        config.rabbitmq_username = "guest"
        config.rabbitmq_password = "guest"
        config.metrics_retention_days = 30
        config.metrics_collection_interval = 1

        buf = MetricsBuffer(max_size=100)
        buf.record("/api/search", 200, 10.0)

        existing_api_row = {"service_name": "api", "status": "healthy", "response_time_ms": 5.0, "endpoint_stats": None}

        persisted_health: list[list[dict[str, Any]]] = []

        async def capture_persist(_pool: Any, _q: Any, h: list[dict[str, Any]]) -> None:
            persisted_health.append(h)
            raise asyncio.CancelledError

        with (
            patch("api.metrics_collector.collect_queue_metrics", new_callable=AsyncMock, return_value=[]),
            patch("api.metrics_collector.collect_service_health", new_callable=AsyncMock, return_value=[existing_api_row]),
            patch("api.metrics_collector.persist_metrics", side_effect=capture_persist),
            patch("api.metrics_collector.prune_old_metrics", new_callable=AsyncMock),
            pytest.raises(asyncio.CancelledError),
        ):
            await run_collector(mock_pool, config, buf)

        assert len(persisted_health) == 1
        api_rows = [r for r in persisted_health[0] if r["service_name"] == "api"]
        assert len(api_rows) == 1
        assert api_rows[0]["endpoint_stats"] is not None

    @pytest.mark.anyio
    async def test_collector_handles_queue_metrics_error(self) -> None:
        """run_collector continues when collect_queue_metrics raises."""
        from api.metrics_collector import MetricsBuffer, run_collector

        mock_pool = MagicMock()
        config = MagicMock()
        config.rabbitmq_management_host = "localhost"
        config.rabbitmq_management_port = 15672
        config.rabbitmq_username = "guest"
        config.rabbitmq_password = "guest"
        config.metrics_retention_days = 30
        config.metrics_collection_interval = 1

        buf = MetricsBuffer(max_size=100)

        with (
            patch("api.metrics_collector.collect_queue_metrics", new_callable=AsyncMock, side_effect=RuntimeError("boom")),
            patch("api.metrics_collector.collect_service_health", new_callable=AsyncMock, return_value=[]),
            patch("api.metrics_collector.persist_metrics", new_callable=AsyncMock),
            patch("api.metrics_collector.prune_old_metrics", new_callable=AsyncMock),
            patch("asyncio.sleep", side_effect=asyncio.CancelledError),
            pytest.raises(asyncio.CancelledError),
        ):
            await run_collector(mock_pool, config, buf)

    @pytest.mark.anyio
    async def test_collector_handles_health_check_error(self) -> None:
        """run_collector continues when collect_service_health raises."""
        from api.metrics_collector import MetricsBuffer, run_collector

        mock_pool = MagicMock()
        config = MagicMock()
        config.rabbitmq_management_host = "localhost"
        config.rabbitmq_management_port = 15672
        config.rabbitmq_username = "guest"
        config.rabbitmq_password = "guest"
        config.metrics_retention_days = 30
        config.metrics_collection_interval = 1

        buf = MetricsBuffer(max_size=100)

        with (
            patch("api.metrics_collector.collect_queue_metrics", new_callable=AsyncMock, return_value=[]),
            patch("api.metrics_collector.collect_service_health", new_callable=AsyncMock, side_effect=RuntimeError("boom")),
            patch("api.metrics_collector.persist_metrics", new_callable=AsyncMock),
            patch("api.metrics_collector.prune_old_metrics", new_callable=AsyncMock),
            patch("asyncio.sleep", side_effect=asyncio.CancelledError),
            pytest.raises(asyncio.CancelledError),
        ):
            await run_collector(mock_pool, config, buf)

    @pytest.mark.anyio
    async def test_collector_handles_persist_error(self) -> None:
        """run_collector continues when persist_metrics raises (non-CancelledError)."""
        from api.metrics_collector import MetricsBuffer, run_collector

        mock_pool = MagicMock()
        config = MagicMock()
        config.rabbitmq_management_host = "localhost"
        config.rabbitmq_management_port = 15672
        config.rabbitmq_username = "guest"
        config.rabbitmq_password = "guest"
        config.metrics_retention_days = 30
        config.metrics_collection_interval = 1

        buf = MetricsBuffer(max_size=100)

        with (
            patch("api.metrics_collector.collect_queue_metrics", new_callable=AsyncMock, return_value=[]),
            patch("api.metrics_collector.collect_service_health", new_callable=AsyncMock, return_value=[]),
            patch("api.metrics_collector.persist_metrics", new_callable=AsyncMock, side_effect=RuntimeError("db error")),
            patch("api.metrics_collector.prune_old_metrics", new_callable=AsyncMock),
            patch("asyncio.sleep", side_effect=asyncio.CancelledError),
            pytest.raises(asyncio.CancelledError),
        ):
            await run_collector(mock_pool, config, buf)

    @pytest.mark.anyio
    async def test_collector_persist_failure_does_not_drop_endpoint_stats(self) -> None:
        """A failed persist must NOT discard buffered endpoint stats — they survive for the next cycle."""
        from api.metrics_collector import MetricsBuffer, run_collector

        mock_pool = MagicMock()
        config = MagicMock()
        config.rabbitmq_management_host = "localhost"
        config.rabbitmq_management_port = 15672
        config.rabbitmq_username = "guest"
        config.rabbitmq_password = "guest"
        config.metrics_retention_days = 30
        config.metrics_collection_interval = 1

        buf = MetricsBuffer(max_size=100)
        buf.record("/api/search", 200, 10.0)

        with (
            patch("api.metrics_collector.collect_queue_metrics", new_callable=AsyncMock, return_value=[]),
            patch("api.metrics_collector.collect_service_health", new_callable=AsyncMock, return_value=[]),
            patch("api.metrics_collector.persist_metrics", new_callable=AsyncMock, side_effect=RuntimeError("db error")),
            patch("api.metrics_collector.prune_old_metrics", new_callable=AsyncMock),
            patch("asyncio.sleep", side_effect=asyncio.CancelledError),
            pytest.raises(asyncio.CancelledError),
        ):
            await run_collector(mock_pool, config, buf)

        # The sample recorded before the failed cycle must still be in the buffer.
        result = buf.flush()
        assert result["/api/search"]["count"] == 1

    @pytest.mark.anyio
    async def test_collector_persist_success_clears_endpoint_stats(self) -> None:
        """A successful persist clears the buffer so the same samples aren't reported twice."""
        from api.metrics_collector import MetricsBuffer, run_collector

        mock_pool = MagicMock()
        config = MagicMock()
        config.rabbitmq_management_host = "localhost"
        config.rabbitmq_management_port = 15672
        config.rabbitmq_username = "guest"
        config.rabbitmq_password = "guest"
        config.metrics_retention_days = 30
        config.metrics_collection_interval = 1

        buf = MetricsBuffer(max_size=100)
        buf.record("/api/search", 200, 10.0)

        async def succeed_then_cancel(_pool: Any, _q: Any, _h: list[dict[str, Any]]) -> None:
            return None

        with (
            patch("api.metrics_collector.collect_queue_metrics", new_callable=AsyncMock, return_value=[]),
            patch("api.metrics_collector.collect_service_health", new_callable=AsyncMock, return_value=[]),
            patch("api.metrics_collector.persist_metrics", side_effect=succeed_then_cancel),
            patch("api.metrics_collector.prune_old_metrics", new_callable=AsyncMock),
            patch("asyncio.sleep", side_effect=asyncio.CancelledError),
            pytest.raises(asyncio.CancelledError),
        ):
            await run_collector(mock_pool, config, buf)

        assert buf.flush() == {}

    @pytest.mark.anyio
    async def test_collector_persist_success_does_not_drop_entries_recorded_during_await(self) -> None:
        """discogsography-qtts: a successful persist must only discard the
        exact batch it persisted — not entries record()ed WHILE
        persist_metrics is awaiting. The old flush()-then-clear() design
        clear()ed the whole live buffer, silently dropping anything that
        arrived during the await; drain()/restore() only ever remove the
        atomically-swapped-out snapshot."""
        from api.metrics_collector import MetricsBuffer, run_collector

        mock_pool = MagicMock()
        config = MagicMock()
        config.rabbitmq_management_host = "localhost"
        config.rabbitmq_management_port = 15672
        config.rabbitmq_username = "guest"
        config.rabbitmq_password = "guest"
        config.metrics_retention_days = 30
        config.metrics_collection_interval = 1

        buf = MetricsBuffer(max_size=100)
        buf.record("/api/before", 200, 5.0)

        async def persist_and_record_concurrently(_pool: Any, _q: Any, _h: list[dict[str, Any]]) -> None:
            # Simulate a request landing in the SAME buffer while this
            # persist call is in flight.
            buf.record("/api/during-persist", 200, 7.0)

        with (
            patch("api.metrics_collector.collect_queue_metrics", new_callable=AsyncMock, return_value=[]),
            patch("api.metrics_collector.collect_service_health", new_callable=AsyncMock, return_value=[]),
            patch("api.metrics_collector.persist_metrics", side_effect=persist_and_record_concurrently),
            patch("api.metrics_collector.prune_old_metrics", new_callable=AsyncMock),
            patch("asyncio.sleep", side_effect=asyncio.CancelledError),
            pytest.raises(asyncio.CancelledError),
        ):
            await run_collector(mock_pool, config, buf)

        result = buf.flush()
        assert "/api/before" not in result  # the persisted batch is gone
        assert result["/api/during-persist"]["count"] == 1  # survives, not dropped

    @pytest.mark.anyio
    async def test_collector_persist_failure_preserves_entries_recorded_during_await(self) -> None:
        """discogsography-qtts: entries record()ed WHILE persist_metrics is
        awaiting must survive a FAILED persist too — restore() must put the
        failed batch back ahead of them rather than discarding either set."""
        from api.metrics_collector import MetricsBuffer, run_collector

        mock_pool = MagicMock()
        config = MagicMock()
        config.rabbitmq_management_host = "localhost"
        config.rabbitmq_management_port = 15672
        config.rabbitmq_username = "guest"
        config.rabbitmq_password = "guest"
        config.metrics_retention_days = 30
        config.metrics_collection_interval = 1

        buf = MetricsBuffer(max_size=100)
        buf.record("/api/before", 200, 5.0)

        async def persist_and_record_concurrently(_pool: Any, _q: Any, _h: list[dict[str, Any]]) -> None:
            buf.record("/api/during-persist", 200, 7.0)
            raise RuntimeError("db error")

        with (
            patch("api.metrics_collector.collect_queue_metrics", new_callable=AsyncMock, return_value=[]),
            patch("api.metrics_collector.collect_service_health", new_callable=AsyncMock, return_value=[]),
            patch("api.metrics_collector.persist_metrics", side_effect=persist_and_record_concurrently),
            patch("api.metrics_collector.prune_old_metrics", new_callable=AsyncMock),
            patch("asyncio.sleep", side_effect=asyncio.CancelledError),
            pytest.raises(asyncio.CancelledError),
        ):
            await run_collector(mock_pool, config, buf)

        result = buf.flush()
        assert result["/api/before"]["count"] == 1
        assert result["/api/during-persist"]["count"] == 1

    @pytest.mark.anyio
    async def test_collector_handles_prune_error(self) -> None:
        """run_collector continues when prune_old_metrics raises."""
        from api.metrics_collector import MetricsBuffer, run_collector

        mock_pool = MagicMock()
        config = MagicMock()
        config.rabbitmq_management_host = "localhost"
        config.rabbitmq_management_port = 15672
        config.rabbitmq_username = "guest"
        config.rabbitmq_password = "guest"
        config.metrics_retention_days = 30
        config.metrics_collection_interval = 1

        buf = MetricsBuffer(max_size=100)

        with (
            patch("api.metrics_collector.collect_queue_metrics", new_callable=AsyncMock, return_value=[]),
            patch("api.metrics_collector.collect_service_health", new_callable=AsyncMock, return_value=[]),
            patch("api.metrics_collector.persist_metrics", new_callable=AsyncMock),
            patch("api.metrics_collector.prune_old_metrics", new_callable=AsyncMock, side_effect=RuntimeError("prune error")),
            patch("asyncio.sleep", side_effect=asyncio.CancelledError),
            pytest.raises(asyncio.CancelledError),
        ):
            await run_collector(mock_pool, config, buf)

    @pytest.mark.anyio
    async def test_collector_handles_flush_error(self) -> None:
        """run_collector continues when metrics_buffer.drain() raises."""
        from api.metrics_collector import MetricsBuffer, run_collector

        mock_pool = MagicMock()
        config = MagicMock()
        config.rabbitmq_management_host = "localhost"
        config.rabbitmq_management_port = 15672
        config.rabbitmq_username = "guest"
        config.rabbitmq_password = "guest"
        config.metrics_retention_days = 30
        config.metrics_collection_interval = 1

        buf = MetricsBuffer(max_size=100)
        buf.record("/api/search", 200, 10.0)

        with (
            patch("api.metrics_collector.collect_queue_metrics", new_callable=AsyncMock, return_value=[]),
            patch("api.metrics_collector.collect_service_health", new_callable=AsyncMock, return_value=[]),
            patch.object(buf, "drain", side_effect=RuntimeError("drain error")),
            patch("api.metrics_collector.persist_metrics", new_callable=AsyncMock),
            patch("api.metrics_collector.prune_old_metrics", new_callable=AsyncMock),
            patch("asyncio.sleep", side_effect=asyncio.CancelledError),
            pytest.raises(asyncio.CancelledError),
        ):
            await run_collector(mock_pool, config, buf)

    @pytest.mark.anyio
    async def test_collector_persist_cancelled_error_reraises(self) -> None:
        """run_collector re-raises CancelledError from persist_metrics."""
        from api.metrics_collector import MetricsBuffer, run_collector

        mock_pool = MagicMock()
        config = MagicMock()
        config.rabbitmq_management_host = "localhost"
        config.rabbitmq_management_port = 15672
        config.rabbitmq_username = "guest"
        config.rabbitmq_password = "guest"
        config.metrics_retention_days = 30
        config.metrics_collection_interval = 1

        buf = MetricsBuffer(max_size=100)

        with (
            patch("api.metrics_collector.collect_queue_metrics", new_callable=AsyncMock, return_value=[{"queue_name": "q"}]),
            patch("api.metrics_collector.collect_service_health", new_callable=AsyncMock, return_value=[]),
            patch("api.metrics_collector.persist_metrics", new_callable=AsyncMock, side_effect=asyncio.CancelledError),
            pytest.raises(asyncio.CancelledError),
        ):
            await run_collector(mock_pool, config, buf)

    @pytest.mark.anyio
    async def test_collector_prune_cancelled_error_reraises(self) -> None:
        """run_collector re-raises CancelledError from prune_old_metrics."""
        from api.metrics_collector import MetricsBuffer, run_collector

        mock_pool = MagicMock()
        config = MagicMock()
        config.rabbitmq_management_host = "localhost"
        config.rabbitmq_management_port = 15672
        config.rabbitmq_username = "guest"
        config.rabbitmq_password = "guest"
        config.metrics_retention_days = 30
        config.metrics_collection_interval = 1

        buf = MetricsBuffer(max_size=100)

        with (
            patch("api.metrics_collector.collect_queue_metrics", new_callable=AsyncMock, return_value=[]),
            patch("api.metrics_collector.collect_service_health", new_callable=AsyncMock, return_value=[]),
            patch("api.metrics_collector.persist_metrics", new_callable=AsyncMock),
            patch("api.metrics_collector.prune_old_metrics", new_callable=AsyncMock, side_effect=asyncio.CancelledError),
            pytest.raises(asyncio.CancelledError),
        ):
            await run_collector(mock_pool, config, buf)


class TestCollectServiceHealthException:
    """Test collect_service_health outer exception handler (line 200-202)."""

    @pytest.mark.anyio
    async def test_returns_empty_on_client_creation_failure(self) -> None:
        from api.metrics_collector import collect_service_health

        with patch("api.metrics_collector.httpx.AsyncClient", side_effect=RuntimeError("client init failed")):
            rows = await collect_service_health()
        assert rows == []
