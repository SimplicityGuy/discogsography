"""Metrics collector — path normalization, request buffer, background collection, and persistence.

Provides:
- ``normalize_path`` — replaces UUID/integer path segments with ``:id``
- ``MetricsBuffer`` — bounded in-memory ring buffer for request latency stats
- ``collect_queue_metrics`` — polls RabbitMQ Management API for queue depths
- ``collect_service_health`` — concurrent health checks across services
- ``persist_metrics`` — batch INSERT into PostgreSQL metrics tables
- ``prune_old_metrics`` — retention-based DELETE from metrics tables
- ``run_collector`` — async loop orchestrating collection, persistence, and pruning
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
import re
import time
from typing import Any

import httpx
from psycopg.types.json import Jsonb
import structlog


logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Path normalization
# ---------------------------------------------------------------------------

_INT_SEGMENT = re.compile(r"/\d+(?=/|$)")
_UUID_SEGMENT = re.compile(r"/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?=/|$)")
_EXCLUDED_PREFIXES = ("/health", "/metrics", "/api/admin/")


def normalize_path(path: str) -> str:
    """Replace UUID and integer path segments with ``:id``."""
    path = _UUID_SEGMENT.sub("/:id", path)
    path = _INT_SEGMENT.sub("/:id", path)
    return path


# ---------------------------------------------------------------------------
# Percentile helper
# ---------------------------------------------------------------------------


def _percentile_index(n: int, p: int) -> int:
    """Return the 0-based index for the *p*-th percentile in a sorted list of *n* items.

    Uses the nearest-rank method (ceiling) to avoid returning index 0 for small datasets.
    """
    import math  # noqa: PLC0415

    idx = math.ceil(n * p / 100) - 1
    return max(idx, 0)


# ---------------------------------------------------------------------------
# MetricsBuffer
# ---------------------------------------------------------------------------


@dataclass
class _Entry:
    path: str
    status_code: int
    duration_ms: float


@dataclass
class MetricsBuffer:
    """Bounded ring buffer that accumulates per-request latency data."""

    max_size: int = 10_000
    _entries: deque[_Entry] = field(default_factory=deque)

    def record(self, path: str, status_code: int, duration_ms: float) -> None:
        """Record a request.  Excluded paths are silently dropped."""
        for prefix in _EXCLUDED_PREFIXES:
            if path.startswith(prefix):
                return
        if len(self._entries) >= self.max_size:
            self._entries.popleft()
        self._entries.append(_Entry(path=path, status_code=status_code, duration_ms=duration_ms))

    @staticmethod
    def _compute_stats(entries: deque[_Entry] | list[_Entry]) -> dict[str, dict[str, Any]]:
        """Group entries by path and compute count/percentile/error-count stats."""
        if not entries:
            return {}

        groups: dict[str, list[float]] = {}
        error_counts: dict[str, int] = {}
        for entry in entries:
            groups.setdefault(entry.path, []).append(entry.duration_ms)
            if entry.status_code >= 500:
                error_counts[entry.path] = error_counts.get(entry.path, 0) + 1

        result: dict[str, dict[str, Any]] = {}
        for path, durations in groups.items():
            durations.sort()
            n = len(durations)
            result[path] = {
                "count": n,
                "p50": durations[_percentile_index(n, 50)],
                "p95": durations[_percentile_index(n, 95)],
                "p99": durations[_percentile_index(n, 99)],
                "error_count": error_counts.get(path, 0),
            }
        return result

    def flush(self) -> dict[str, dict[str, Any]]:
        """Group buffered entries by path and compute stats, WITHOUT clearing the buffer.

        Non-destructive on purpose: the caller is responsible for calling
        :meth:`clear` only after the returned stats have been durably persisted.
        This keeps a failed persist from silently discarding the window's
        samples — they simply stay buffered (growth still bounded by
        ``max_size`` via ``record()``'s eviction) and are folded into the next
        cycle's stats until a persist finally succeeds.

        NOTE: pairing this with :meth:`clear` after an ``await`` (e.g. a
        persist call) is a TOCTOU — any entry ``record()``ed during that
        ``await`` is silently dropped by ``clear()``'s wholesale replacement,
        because it was never part of the snapshot ``flush()`` returned
        (discogsography-qtts). Callers that persist across an await should
        use :meth:`drain` / :meth:`restore` instead, which swap the buffer
        out atomically so newly-arrived entries can never be in the
        snapshot that gets dropped.
        """
        return self._compute_stats(self._entries)

    def clear(self) -> None:
        """Drop all buffered entries.  Call only after a successful persist of ``flush()``'s result."""
        self._entries = deque()

    def drain(self) -> tuple[dict[str, dict[str, Any]], deque[_Entry]]:
        """Atomically swap out the buffer and compute stats from the swapped-out copy.

        Returns ``(stats, samples)``. The swap (``samples = self._entries;
        self._entries = deque()``) is a single, non-yielding assignment, so
        any entry ``record()``ed after this call returns lands in the FRESH
        deque — never in ``samples`` — regardless of how long the caller then
        spends ``await``ing a persist. This is what makes drain/restore safe
        across an await where ``flush``/``clear`` is not: on persist failure,
        pass ``samples`` to :meth:`restore` to put them back ahead of
        whatever arrived in the meantime, instead of ``clear()`` wiping both
        the persisted snapshot AND everything recorded during the persist
        window (discogsography-qtts).
        """
        samples = self._entries
        self._entries = deque()
        try:
            stats = self._compute_stats(samples)
        except Exception:
            # Stats computation blew up on this batch — put the raw samples
            # back rather than losing them silently.
            self.restore(samples)
            raise
        return stats, samples

    def restore(self, samples: deque[_Entry]) -> None:
        """Re-prepend entries a failed persist could not durably store.

        Placed AHEAD of anything recorded since the matching :meth:`drain`
        call, then trimmed from the left (oldest-first) to ``max_size`` —
        the same eviction order :meth:`record` uses — so a restore can never
        transiently exceed the bound record() otherwise enforces.
        """
        if not samples:
            return
        self._entries.extendleft(reversed(samples))
        while len(self._entries) > self.max_size:
            self._entries.popleft()


# ---------------------------------------------------------------------------
# Task 4: Background collection
# ---------------------------------------------------------------------------

SERVICE_ENDPOINTS: dict[str, tuple[str, int]] = {
    "extractor-discogs": ("extractor-discogs", 8000),
    "extractor-musicbrainz": ("extractor-musicbrainz", 8000),
    "graphinator": ("graphinator", 8001),
    "tableinator": ("tableinator", 8002),
    "dashboard": ("dashboard", 8003),
    "api": ("api", 8005),
    "explore": ("explore", 8007),
    "insights": ("insights", 8009),
    "brainztableinator": ("brainztableinator", 8010),
    "brainzgraphinator": ("brainzgraphinator", 8011),
}


async def collect_queue_metrics(
    mgmt_host: str,
    mgmt_port: int,
    username: str,
    password: str,
) -> list[dict[str, Any]]:
    """Poll RabbitMQ Management API for discogsography queue metrics.

    Returns an empty list on any failure.
    """
    try:
        url = f"http://{mgmt_host}:{mgmt_port}/api/queues"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, auth=(username, password))
        queues: list[dict[str, Any]] = resp.json()
        rows: list[dict[str, Any]] = []
        for q in queues:
            name: str = q.get("name", "")
            if "discogsography" not in name and "musicbrainz" not in name:
                continue
            stats = q.get("message_stats", {})
            rows.append(
                {
                    "queue_name": name,
                    "messages_ready": q.get("messages_ready", 0),
                    "messages_unacknowledged": q.get("messages_unacknowledged", 0),
                    "consumers": q.get("consumers", 0),
                    "publish_rate": stats.get("publish_details", {}).get("rate", 0.0),
                    "ack_rate": stats.get("ack_details", {}).get("rate", 0.0),
                }
            )
        return rows
    except Exception:
        logger.warning("⚠️ Failed to collect queue metrics")
        return []


async def _check_one_service(
    client: httpx.AsyncClient,
    name: str,
    host: str,
    port: int,
) -> dict[str, Any]:
    """Check a single service health endpoint."""
    try:
        start = time.monotonic()
        resp = await client.get(f"http://{host}:{port}/health")
        elapsed = (time.monotonic() - start) * 1000
        status = "healthy" if resp.status_code == 200 else "unhealthy"
        return {
            "service_name": name,
            "status": status,
            "response_time_ms": round(elapsed, 2),
            "endpoint_stats": None,
        }
    except Exception:
        return {
            "service_name": name,
            "status": "unknown",
            "response_time_ms": 0.0,
            "endpoint_stats": None,
        }


async def collect_service_health(
    endpoints: dict[str, tuple[str, int]] | None = None,
) -> list[dict[str, Any]]:
    """Concurrent HTTP health checks across services.  Never raises."""
    eps = endpoints or SERVICE_ENDPOINTS
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            tasks = [_check_one_service(client, name, host, port) for name, (host, port) in eps.items()]
            results = await asyncio.gather(*tasks)
        return list(results)
    except Exception:
        logger.warning("⚠️ Failed to collect service health")
        return []


# ---------------------------------------------------------------------------
# Task 5: Persistence
# ---------------------------------------------------------------------------

_INSERT_QUEUE_SQL = """
INSERT INTO queue_metrics (recorded_at, queue_name, messages_ready, messages_unacknowledged, consumers, publish_rate, ack_rate)
VALUES (NOW(), %(queue_name)s, %(messages_ready)s, %(messages_unacknowledged)s, %(consumers)s, %(publish_rate)s, %(ack_rate)s)
"""

_INSERT_HEALTH_SQL = """
INSERT INTO service_health_metrics (recorded_at, service_name, status, response_time_ms, endpoint_stats)
VALUES (NOW(), %(service_name)s, %(status)s, %(response_time_ms)s, %(endpoint_stats)s)
"""


async def persist_metrics(
    pool: Any,
    queue_rows: list[dict[str, Any]],
    health_rows: list[dict[str, Any]],
) -> None:
    """Batch INSERT queue and health metrics rows.  No-op if both lists are empty."""
    if not queue_rows and not health_rows:
        return

    for row in health_rows:
        if row.get("endpoint_stats") is not None:
            row["endpoint_stats"] = Jsonb(row["endpoint_stats"])

    async with pool.connection() as conn, conn.cursor() as cur:
        if queue_rows:
            await cur.executemany(_INSERT_QUEUE_SQL, queue_rows)
        if health_rows:
            await cur.executemany(_INSERT_HEALTH_SQL, health_rows)


_DELETE_QUEUE_SQL = "DELETE FROM queue_metrics WHERE recorded_at < NOW() - make_interval(days => %s)"
_DELETE_HEALTH_SQL = "DELETE FROM service_health_metrics WHERE recorded_at < NOW() - make_interval(days => %s)"


async def prune_old_metrics(pool: Any, retention_days: int) -> None:
    """Delete metrics older than *retention_days* from both tables."""
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(_DELETE_QUEUE_SQL, (retention_days,))
        await cur.execute(_DELETE_HEALTH_SQL, (retention_days,))


# ---------------------------------------------------------------------------
# Task 5: Collector loop
# ---------------------------------------------------------------------------


async def run_collector(
    pool: Any,
    config: Any,
    metrics_buffer: MetricsBuffer,
) -> None:
    """Async loop: collect, persist, prune, sleep.  Re-raises ``CancelledError``."""
    while True:
        queue_rows: list[dict[str, Any]] = []
        health_rows: list[dict[str, Any]] = []

        # 1. Collect queue metrics
        try:
            queue_rows = await collect_queue_metrics(
                config.rabbitmq_management_host,
                config.rabbitmq_management_port,
                config.rabbitmq_username,
                config.rabbitmq_password,
            )
        except Exception:
            logger.error("❌ Error collecting queue metrics")

        # 2. Collect service health
        try:
            health_rows = await collect_service_health()
        except Exception:
            logger.error("❌ Error collecting service health")

        # 3. Drain metrics buffer — an ATOMIC swap (not the non-destructive
        # flush()), so any request recorded during the persist `await` below
        # lands in the buffer's fresh deque and is never part of the samples
        # a failed persist has to restore or a successful one discards
        # (discogsography-qtts). Attach endpoint_stats to the API health row.
        endpoint_stats: dict[str, dict[str, Any]] = {}
        buffer_samples: deque[Any] = deque()
        try:
            endpoint_stats, buffer_samples = metrics_buffer.drain()
            if endpoint_stats:
                # Find existing API row or create synthetic one
                api_row = next((r for r in health_rows if r["service_name"] == "api"), None)
                if api_row is not None:
                    api_row["endpoint_stats"] = endpoint_stats
                else:
                    health_rows.append(
                        {
                            "service_name": "api",
                            "status": "healthy",
                            "response_time_ms": 0.0,
                            "endpoint_stats": endpoint_stats,
                        }
                    )
                logger.info("📊 Flushed endpoint stats", paths=len(endpoint_stats))
        except Exception:
            logger.error("❌ Error flushing metrics buffer")

        # 4. Persist — only drop the drained endpoint stats once they're durably
        # written. On failure (including cancellation) they are restored
        # AHEAD of anything recorded during this await, instead of being lost
        # (drain() already removed them from the live buffer, so a `clear()`-
        # style "leave them buffered" is no longer available — restore() is
        # the equivalent for the atomic-swap design).
        try:
            await persist_metrics(pool, queue_rows, health_rows)
            logger.info("📊 Persisted metrics", queues=len(queue_rows), health=len(health_rows))
        except asyncio.CancelledError:
            metrics_buffer.restore(buffer_samples)
            raise
        except Exception:
            logger.error("❌ Error persisting metrics")
            metrics_buffer.restore(buffer_samples)

        # 5. Prune
        try:
            await prune_old_metrics(pool, config.metrics_retention_days)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.error("❌ Error pruning old metrics")

        # 6. Sleep
        await asyncio.sleep(config.metrics_collection_interval)
