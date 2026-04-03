# Admin Dashboard Phase 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add queue health trends and system health observability to the admin dashboard with time-series data collection and Chart.js visualizations.

**Architecture:** Background `asyncio.Task` in the API service collects queue metrics and service health every 5 minutes, stores in PostgreSQL. Two new admin endpoints return time-series data with flexible range/granularity. Dashboard gains two new tabs with Chart.js charts, SVG sparklines, and summary cards.

**Tech Stack:** Python 3.13+, FastAPI, PostgreSQL (time-series storage), Chart.js (CDN), Starlette middleware, httpx, asyncio

______________________________________________________________________

## File Map

### Files to create

| File                                  | Responsibility                                                                       |
| ------------------------------------- | ------------------------------------------------------------------------------------ |
| `api/metrics_collector.py`            | Background collector task, metrics middleware, path normalization, retention pruning |
| `api/queries/metrics_queries.py`      | SQL queries for queue history and health history endpoints                           |
| `tests/api/test_metrics_collector.py` | Tests for collector, middleware, path normalization                                  |
| `tests/api/test_metrics_queries.py`   | Tests for query functions (granularity, aggregation, edge cases)                     |

### Files to modify

| File                                  | Change                                                                        |
| ------------------------------------- | ----------------------------------------------------------------------------- |
| `schema-init/postgres_schema.py`      | Add `queue_metrics` and `service_health_metrics` tables + indexes             |
| `common/config.py`                    | Add `metrics_retention_days` and `metrics_collection_interval` to `ApiConfig` |
| `api/models.py`                       | Pydantic response models for both history endpoints                           |
| `api/routers/admin.py`                | Add 2 endpoint functions (`queues/history`, `health/history`)                 |
| `api/api.py`                          | Start collector task in lifespan, add metrics middleware                      |
| `dashboard/admin_proxy.py`            | Add 2 proxy routes                                                            |
| `dashboard/static/admin.html`         | Add Queue Trends and System Health tabs, load Chart.js CDN                    |
| `dashboard/static/admin.js`           | Fetch, render, Chart.js initialization, sparkline generation                  |
| `tests/api/test_admin_endpoints.py`   | Endpoint tests for 2 new routes                                               |
| `tests/dashboard/test_admin_proxy.py` | Proxy route tests                                                             |

______________________________________________________________________

### Task 1: Database Schema — `queue_metrics` and `service_health_metrics` tables

**Files:**

- Modify: `schema-init/postgres_schema.py:244-252` (after `idx_extraction_history_created_at`)

- [ ] **Step 1: Write test for new schema tables**

Create `tests/schema-init/test_metrics_schema.py`:

```python
"""Tests for metrics schema table definitions."""

from __future__ import annotations

from schema_init.postgres_schema import _USER_TABLES


def test_queue_metrics_table_in_schema() -> None:
    """Verify queue_metrics table definition exists in schema."""
    names = [name for name, _ in _USER_TABLES]
    assert "queue_metrics table" in names


def test_service_health_metrics_table_in_schema() -> None:
    """Verify service_health_metrics table definition exists in schema."""
    names = [name for name, _ in _USER_TABLES]
    assert "service_health_metrics table" in names


def test_queue_metrics_index_in_schema() -> None:
    """Verify composite index for queue_metrics exists."""
    names = [name for name, _ in _USER_TABLES]
    assert "idx_queue_metrics_recorded_queue" in names


def test_service_health_metrics_index_in_schema() -> None:
    """Verify composite index for service_health_metrics exists."""
    names = [name for name, _ in _USER_TABLES]
    assert "idx_service_health_recorded_service" in names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/schema-init/test_metrics_schema.py -v`
Expected: FAIL — table names not found in `_USER_TABLES`

- [ ] **Step 3: Add table definitions to schema**

In `schema-init/postgres_schema.py`, add after the `idx_extraction_history_created_at` entry (line 251) in the `_USER_TABLES` list:

```python
    (
        "queue_metrics table",
        """
        CREATE TABLE IF NOT EXISTS queue_metrics (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            recorded_at TIMESTAMPTZ NOT NULL,
            queue_name VARCHAR(100) NOT NULL,
            messages_ready INTEGER,
            messages_unacknowledged INTEGER,
            consumers INTEGER,
            publish_rate REAL,
            ack_rate REAL
        )
        """,
    ),
    (
        "idx_queue_metrics_recorded_queue",
        "CREATE INDEX IF NOT EXISTS idx_queue_metrics_recorded_queue ON queue_metrics (recorded_at, queue_name)",
    ),
    (
        "service_health_metrics table",
        """
        CREATE TABLE IF NOT EXISTS service_health_metrics (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            recorded_at TIMESTAMPTZ NOT NULL,
            service_name VARCHAR(50) NOT NULL,
            status VARCHAR(20),
            response_time_ms REAL,
            endpoint_stats JSONB
        )
        """,
    ),
    (
        "idx_service_health_recorded_service",
        "CREATE INDEX IF NOT EXISTS idx_service_health_recorded_service ON service_health_metrics (recorded_at, service_name)",
    ),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/schema-init/test_metrics_schema.py -v`
Expected: PASS — all 4 tests green

- [ ] **Step 5: Run full schema-init tests**

Run: `uv run pytest tests/schema-init/ -v`
Expected: All existing + new tests pass

- [ ] **Step 6: Commit**

```bash
git add schema-init/postgres_schema.py tests/schema-init/test_metrics_schema.py
git commit -m "feat(schema): add queue_metrics and service_health_metrics tables (#138)"
```

______________________________________________________________________

### Task 2: Config — Add metrics retention and collection interval to `ApiConfig`

**Files:**

- Modify: `common/config.py:430-440` (add fields to `ApiConfig` dataclass)

- Modify: `common/config.py:505-528` (add to `from_env` constructor)

- [ ] **Step 1: Write test for new config fields**

Create `tests/common/test_metrics_config.py`:

```python
"""Tests for metrics configuration fields on ApiConfig."""

from __future__ import annotations

import os
from unittest.mock import patch

from common.config import ApiConfig


def _make_api_config(**overrides: str) -> ApiConfig:
    """Create an ApiConfig with required env vars + overrides."""
    base_env = {
        "POSTGRES_HOST": "localhost",
        "POSTGRES_USERNAME": "test",
        "POSTGRES_PASSWORD": "test",
        "POSTGRES_DATABASE": "test",
        "JWT_SECRET_KEY": "secret",
        "NEO4J_HOST": "localhost",
        "NEO4J_USERNAME": "neo4j",
        "NEO4J_PASSWORD": "pass",
    }
    base_env.update(overrides)
    with patch.dict(os.environ, base_env, clear=False):
        return ApiConfig.from_env()


def test_default_retention_days() -> None:
    """Default metrics retention is 366 days."""
    config = _make_api_config()
    assert config.metrics_retention_days == 366


def test_default_collection_interval() -> None:
    """Default metrics collection interval is 300 seconds."""
    config = _make_api_config()
    assert config.metrics_collection_interval == 300


def test_custom_retention_days() -> None:
    """METRICS_RETENTION_DAYS env var overrides default."""
    config = _make_api_config(METRICS_RETENTION_DAYS="90")
    assert config.metrics_retention_days == 90


def test_custom_collection_interval() -> None:
    """METRICS_COLLECTION_INTERVAL env var overrides default."""
    config = _make_api_config(METRICS_COLLECTION_INTERVAL="60")
    assert config.metrics_collection_interval == 60


def test_invalid_retention_days_uses_default() -> None:
    """Non-integer METRICS_RETENTION_DAYS falls back to 366."""
    config = _make_api_config(METRICS_RETENTION_DAYS="abc")
    assert config.metrics_retention_days == 366


def test_invalid_collection_interval_uses_default() -> None:
    """Non-integer METRICS_COLLECTION_INTERVAL falls back to 300."""
    config = _make_api_config(METRICS_COLLECTION_INTERVAL="abc")
    assert config.metrics_collection_interval == 300
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/common/test_metrics_config.py -v`
Expected: FAIL — `ApiConfig` has no `metrics_retention_days` attribute

- [ ] **Step 3: Add config fields**

In `common/config.py`, add two fields to the `ApiConfig` dataclass (after `rabbitmq_password` at line 440):

```python
    # Admin dashboard — metrics collection
    metrics_retention_days: int = 366
    metrics_collection_interval: int = 300  # seconds
```

In `ApiConfig.from_env()`, add parsing before the `return cls(...)` call (after `rabbitmq_password` parsing, around line 527):

```python
        metrics_retention_days_str = getenv("METRICS_RETENTION_DAYS", "366")
        try:
            metrics_retention_days = int(metrics_retention_days_str)
        except ValueError:
            metrics_retention_days = 366

        metrics_collection_interval_str = getenv("METRICS_COLLECTION_INTERVAL", "300")
        try:
            metrics_collection_interval = int(metrics_collection_interval_str)
        except ValueError:
            metrics_collection_interval = 300
```

And add the two fields to the `return cls(...)` call:

```python
            metrics_retention_days=metrics_retention_days,
            metrics_collection_interval=metrics_collection_interval,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/common/test_metrics_config.py -v`
Expected: PASS — all 6 tests green

- [ ] **Step 5: Run full common tests**

Run: `uv run pytest tests/common/ -v`
Expected: All existing + new tests pass

- [ ] **Step 6: Commit**

```bash
git add common/config.py tests/common/test_metrics_config.py
git commit -m "feat(config): add metrics retention and collection interval settings (#138)"
```

______________________________________________________________________

### Task 3: Metrics Middleware — Request timing capture with path normalization

**Files:**

- Create: `api/metrics_collector.py`

- Create: `tests/api/test_metrics_collector.py`

- [ ] **Step 1: Write tests for path normalization and middleware buffer**

Create `tests/api/test_metrics_collector.py`:

```python
"""Tests for metrics collector — path normalization and middleware buffer."""

from __future__ import annotations

import pytest

from api.metrics_collector import MetricsBuffer, normalize_path


class TestNormalizePath:
    def test_integer_id(self) -> None:
        assert normalize_path("/api/explore/artist/12345") == "/api/explore/artist/:id"

    def test_uuid(self) -> None:
        assert normalize_path("/api/collection/abc12345-def6-7890-abcd-ef1234567890") == "/api/collection/:id"

    def test_multiple_ids(self) -> None:
        assert normalize_path("/api/explore/artist/123/releases/456") == "/api/explore/artist/:id/releases/:id"

    def test_no_ids(self) -> None:
        assert normalize_path("/api/search") == "/api/search"

    def test_preserves_query_free_path(self) -> None:
        assert normalize_path("/api/admin/queues/history") == "/api/admin/queues/history"


class TestMetricsBuffer:
    def test_record_and_flush(self) -> None:
        buf = MetricsBuffer(max_size=100)
        buf.record("/api/search", 200, 85.0)
        buf.record("/api/search", 200, 120.0)
        buf.record("/api/search", 500, 50.0)
        stats = buf.flush()
        assert "/api/search" in stats
        s = stats["/api/search"]
        assert s["count"] == 3
        assert s["errors"] == 1
        assert s["p50"] > 0
        assert s["p95"] >= s["p50"]
        assert s["p99"] >= s["p95"]

    def test_flush_clears_buffer(self) -> None:
        buf = MetricsBuffer(max_size=100)
        buf.record("/api/search", 200, 85.0)
        buf.flush()
        stats = buf.flush()
        assert stats == {}

    def test_max_size_drops_oldest(self) -> None:
        buf = MetricsBuffer(max_size=3)
        buf.record("/api/a", 200, 10.0)
        buf.record("/api/b", 200, 20.0)
        buf.record("/api/c", 200, 30.0)
        buf.record("/api/d", 200, 40.0)  # should drop /api/a
        assert len(buf._entries) == 3

    def test_percentile_computation(self) -> None:
        buf = MetricsBuffer(max_size=1000)
        for i in range(100):
            buf.record("/api/test", 200, float(i + 1))
        stats = buf.flush()
        s = stats["/api/test"]
        assert s["count"] == 100
        assert 49 <= s["p50"] <= 51
        assert 94 <= s["p95"] <= 96
        assert 98 <= s["p99"] <= 100

    def test_excluded_paths_not_recorded(self) -> None:
        buf = MetricsBuffer(max_size=100)
        buf.record("/health", 200, 5.0)
        buf.record("/metrics", 200, 3.0)
        buf.record("/api/admin/queues/history", 200, 50.0)
        stats = buf.flush()
        assert stats == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_metrics_collector.py::TestNormalizePath -v`
Expected: FAIL — module `api.metrics_collector` does not exist

- [ ] **Step 3: Implement path normalization and MetricsBuffer**

Create `api/metrics_collector.py`:

```python
"""Background metrics collector and request timing middleware.

Collects queue health snapshots and service health metrics every N seconds,
stores them in PostgreSQL, and prunes old data based on retention policy.
Also provides a MetricsBuffer that captures per-request API timing for
endpoint performance tracking.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import math
import re
from typing import Any

import structlog


logger = structlog.get_logger(__name__)

# Path normalization — replace integer and UUID segments with :id
_INT_SEGMENT = re.compile(r"/\d+(?=/|$)")
_UUID_SEGMENT = re.compile(r"/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?=/|$)")

# Paths excluded from metrics recording
_EXCLUDED_PREFIXES = ("/health", "/metrics", "/api/admin/")


def normalize_path(path: str) -> str:
    """Replace UUID and integer path segments with :id."""
    path = _UUID_SEGMENT.sub("/:id", path)
    path = _INT_SEGMENT.sub("/:id", path)
    return path


@dataclass
class _Entry:
    path: str
    status_code: int
    duration_ms: float


@dataclass
class MetricsBuffer:
    """Thread-safe buffer for per-request metrics with bounded size."""

    max_size: int = 10_000
    _entries: deque[_Entry] = field(default_factory=deque)

    def record(self, path: str, status_code: int, duration_ms: float) -> None:
        """Record a request metric. Excluded paths are silently dropped."""
        for prefix in _EXCLUDED_PREFIXES:
            if path.startswith(prefix):
                return
        if len(self._entries) >= self.max_size:
            self._entries.popleft()
        self._entries.append(_Entry(path=path, status_code=status_code, duration_ms=duration_ms))

    def flush(self) -> dict[str, dict[str, Any]]:
        """Compute per-endpoint stats and clear the buffer.

        Returns a dict keyed by normalized path with keys:
        count, errors, p50, p95, p99
        """
        if not self._entries:
            return {}

        # Group by path
        by_path: dict[str, list[_Entry]] = {}
        for entry in self._entries:
            by_path.setdefault(entry.path, []).append(entry)
        self._entries.clear()

        result: dict[str, dict[str, Any]] = {}
        for path, entries in by_path.items():
            durations = sorted(e.duration_ms for e in entries)
            errors = sum(1 for e in entries if e.status_code >= 500)
            n = len(durations)
            result[path] = {
                "count": n,
                "errors": errors,
                "p50": durations[_percentile_index(n, 50)],
                "p95": durations[_percentile_index(n, 95)],
                "p99": durations[_percentile_index(n, 99)],
            }
        return result


def _percentile_index(n: int, p: int) -> int:
    """Return the index for the p-th percentile in a sorted list of length n."""
    return min(max(math.ceil(n * p / 100) - 1, 0), n - 1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_metrics_collector.py -v`
Expected: PASS — all tests green

- [ ] **Step 5: Run linting**

Run: `uv run ruff check api/metrics_collector.py && uv run mypy api/metrics_collector.py`
Expected: Clean

- [ ] **Step 6: Commit**

```bash
git add api/metrics_collector.py tests/api/test_metrics_collector.py
git commit -m "feat(api): add metrics buffer with path normalization (#138)"
```

______________________________________________________________________

### Task 4: Background Collector — Queue and health snapshot collection

**Files:**

- Modify: `api/metrics_collector.py` (add collector functions)

- Modify: `tests/api/test_metrics_collector.py` (add collector tests)

- [ ] **Step 1: Write tests for queue metric collection**

Append to `tests/api/test_metrics_collector.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch

from api.metrics_collector import collect_queue_metrics, collect_service_health


class TestCollectQueueMetrics:
    @pytest.mark.asyncio
    async def test_extracts_queue_data(self) -> None:
        """RabbitMQ management API response is parsed into queue metric dicts."""
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "name": "discogsography-graphinator-artists",
                "messages_ready": 42,
                "messages_unacknowledged": 3,
                "consumers": 1,
                "message_stats": {"publish_details": {"rate": 12.5}, "ack_details": {"rate": 11.8}},
            },
            {
                "name": "some-other-queue",
                "messages_ready": 0,
                "messages_unacknowledged": 0,
                "consumers": 0,
            },
        ]
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("api.metrics_collector.httpx.AsyncClient", return_value=mock_client):
            rows = await collect_queue_metrics("rabbitmq", 15672, "guest", "guest")

        assert len(rows) == 1
        assert rows[0]["queue_name"] == "discogsography-graphinator-artists"
        assert rows[0]["messages_ready"] == 42
        assert rows[0]["publish_rate"] == 12.5
        assert rows[0]["ack_rate"] == 11.8

    @pytest.mark.asyncio
    async def test_returns_empty_on_failure(self) -> None:
        """Connection failure returns empty list, doesn't raise."""
        import httpx as _httpx

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=_httpx.ConnectError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("api.metrics_collector.httpx.AsyncClient", return_value=mock_client):
            rows = await collect_queue_metrics("rabbitmq", 15672, "guest", "guest")

        assert rows == []


class TestCollectServiceHealth:
    @pytest.mark.asyncio
    async def test_healthy_service(self) -> None:
        """Healthy service returns status and response time."""
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "healthy"}
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("api.metrics_collector.httpx.AsyncClient", return_value=mock_client):
            rows = await collect_service_health({"extractor": ("extractor", 8000)})

        assert len(rows) == 1
        assert rows[0]["service_name"] == "extractor"
        assert rows[0]["status"] == "healthy"
        assert rows[0]["response_time_ms"] >= 0

    @pytest.mark.asyncio
    async def test_unreachable_service(self) -> None:
        """Unreachable service returns unknown status, doesn't raise."""
        import httpx as _httpx

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=_httpx.ConnectError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("api.metrics_collector.httpx.AsyncClient", return_value=mock_client):
            rows = await collect_service_health({"extractor": ("extractor", 8000)})

        assert len(rows) == 1
        assert rows[0]["status"] == "unknown"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_metrics_collector.py::TestCollectQueueMetrics -v`
Expected: FAIL — `collect_queue_metrics` not defined

- [ ] **Step 3: Implement collector functions**

Add to `api/metrics_collector.py` (after the `MetricsBuffer` class):

```python
import time

import httpx


# Service health endpoints to poll
SERVICE_ENDPOINTS: dict[str, tuple[str, int]] = {
    "extractor": ("extractor", 8000),
    "graphinator": ("graphinator", 8001),
    "tableinator": ("tableinator", 8002),
    "dashboard": ("dashboard", 8003),
    "insights": ("insights", 8008),
}


async def collect_queue_metrics(
    mgmt_host: str,
    mgmt_port: int,
    username: str,
    password: str,
) -> list[dict[str, Any]]:
    """Fetch queue metrics from RabbitMQ Management API.

    Returns a list of dicts ready for INSERT into queue_metrics.
    Filters for queues containing 'discogsography'.
    Returns empty list on failure.
    """
    url = f"http://{mgmt_host}:{mgmt_port}/api/queues"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, auth=(username, password))
        if resp.status_code != 200:
            logger.warning("⚠️ RabbitMQ management API returned non-200", status_code=resp.status_code)
            return []
        queues = resp.json()
    except (httpx.ConnectError, httpx.RequestError) as exc:
        logger.warning("⚠️ RabbitMQ management API unreachable", error=str(exc))
        return []

    rows: list[dict[str, Any]] = []
    for q in queues:
        name = q.get("name", "")
        if "discogsography" not in name:
            continue
        msg_stats = q.get("message_stats", {})
        rows.append({
            "queue_name": name,
            "messages_ready": q.get("messages_ready", 0),
            "messages_unacknowledged": q.get("messages_unacknowledged", 0),
            "consumers": q.get("consumers", 0),
            "publish_rate": msg_stats.get("publish_details", {}).get("rate", 0.0),
            "ack_rate": msg_stats.get("ack_details", {}).get("rate", 0.0),
        })
    return rows


async def collect_service_health(
    endpoints: dict[str, tuple[str, int]] | None = None,
) -> list[dict[str, Any]]:
    """Poll each service's /health endpoint and capture status + latency.

    Returns a list of dicts ready for INSERT into service_health_metrics.
    Unreachable services get status='unknown'. Never raises.
    """
    if endpoints is None:
        endpoints = SERVICE_ENDPOINTS

    rows: list[dict[str, Any]] = []
    for service_name, (host, port) in endpoints.items():
        url = f"http://{host}:{port}/health"
        try:
            start = time.monotonic()
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url)
            elapsed_ms = (time.monotonic() - start) * 1000
            if resp.status_code == 200:
                data = resp.json()
                health_status = data.get("status", "unknown")
            else:
                health_status = "unhealthy"
        except (httpx.ConnectError, httpx.RequestError):
            elapsed_ms = 0.0
            health_status = "unknown"

        rows.append({
            "service_name": service_name,
            "status": health_status,
            "response_time_ms": round(elapsed_ms, 2),
        })
    return rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_metrics_collector.py -v`
Expected: PASS — all tests green

- [ ] **Step 5: Run linting**

Run: `uv run ruff check api/metrics_collector.py && uv run mypy api/metrics_collector.py`
Expected: Clean

- [ ] **Step 6: Commit**

```bash
git add api/metrics_collector.py tests/api/test_metrics_collector.py
git commit -m "feat(api): add queue and service health collection functions (#138)"
```

______________________________________________________________________

### Task 5: Collector — PostgreSQL persistence and retention pruning

**Files:**

- Modify: `api/metrics_collector.py` (add persist + prune + run_collector)

- Modify: `tests/api/test_metrics_collector.py` (add persistence tests)

- [ ] **Step 1: Write tests for persist and prune**

Append to `tests/api/test_metrics_collector.py`:

```python
from api.metrics_collector import persist_metrics, prune_old_metrics


class TestPersistMetrics:
    @pytest.mark.asyncio
    async def test_inserts_queue_and_health_rows(self) -> None:
        """persist_metrics inserts queue and health rows in a single transaction."""
        mock_cur = AsyncMock()
        mock_conn = AsyncMock()
        cur_ctx = AsyncMock()
        cur_ctx.__aenter__ = AsyncMock(return_value=mock_cur)
        cur_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_conn.cursor = MagicMock(return_value=cur_ctx)
        conn_ctx = AsyncMock()
        conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        conn_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_pool = MagicMock()
        mock_pool.connection = MagicMock(return_value=conn_ctx)

        queue_rows = [{"queue_name": "graphinator-artists", "messages_ready": 10,
                        "messages_unacknowledged": 2, "consumers": 1,
                        "publish_rate": 5.0, "ack_rate": 4.5}]
        health_rows = [{"service_name": "extractor", "status": "healthy",
                        "response_time_ms": 12.0, "endpoint_stats": None}]

        await persist_metrics(mock_pool, queue_rows, health_rows)

        assert mock_cur.execute.call_count == 2  # 1 queue + 1 health

    @pytest.mark.asyncio
    async def test_empty_rows_no_ops(self) -> None:
        """No database calls when both lists are empty."""
        mock_pool = MagicMock()
        await persist_metrics(mock_pool, [], [])
        mock_pool.connection.assert_not_called()


class TestPruneOldMetrics:
    @pytest.mark.asyncio
    async def test_prune_executes_deletes(self) -> None:
        """prune_old_metrics runs DELETE for both tables."""
        mock_cur = AsyncMock()
        mock_conn = AsyncMock()
        cur_ctx = AsyncMock()
        cur_ctx.__aenter__ = AsyncMock(return_value=mock_cur)
        cur_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_conn.cursor = MagicMock(return_value=cur_ctx)
        conn_ctx = AsyncMock()
        conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        conn_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_pool = MagicMock()
        mock_pool.connection = MagicMock(return_value=conn_ctx)

        await prune_old_metrics(mock_pool, retention_days=90)

        assert mock_cur.execute.call_count == 2
        calls = [str(c) for c in mock_cur.execute.call_args_list]
        assert any("queue_metrics" in c for c in calls)
        assert any("service_health_metrics" in c for c in calls)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_metrics_collector.py::TestPersistMetrics -v`
Expected: FAIL — `persist_metrics` not defined

- [ ] **Step 3: Implement persist and prune functions**

Add to `api/metrics_collector.py`:

```python
async def persist_metrics(
    pool: Any,
    queue_rows: list[dict[str, Any]],
    health_rows: list[dict[str, Any]],
) -> None:
    """Batch INSERT queue and health metric rows into PostgreSQL."""
    if not queue_rows and not health_rows:
        return

    async with pool.connection() as conn, conn.cursor() as cur:
        for row in queue_rows:
            await cur.execute(
                """INSERT INTO queue_metrics
                   (recorded_at, queue_name, messages_ready, messages_unacknowledged,
                    consumers, publish_rate, ack_rate)
                   VALUES (NOW(), %(queue_name)s, %(messages_ready)s, %(messages_unacknowledged)s,
                           %(consumers)s, %(publish_rate)s, %(ack_rate)s)""",
                row,
            )
        for row in health_rows:
            await cur.execute(
                """INSERT INTO service_health_metrics
                   (recorded_at, service_name, status, response_time_ms, endpoint_stats)
                   VALUES (NOW(), %(service_name)s, %(status)s, %(response_time_ms)s,
                           %(endpoint_stats)s)""",
                row,
            )


async def prune_old_metrics(pool: Any, retention_days: int) -> None:
    """Delete metrics older than retention_days from both tables."""
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM queue_metrics WHERE recorded_at < NOW() - INTERVAL '%s days'",
            (retention_days,),
        )
        await cur.execute(
            "DELETE FROM service_health_metrics WHERE recorded_at < NOW() - INTERVAL '%s days'",
            (retention_days,),
        )


async def run_collector(
    pool: Any,
    config: Any,
    metrics_buffer: MetricsBuffer,
) -> None:
    """Background loop: collect metrics, persist, prune. Runs until cancelled."""
    import asyncio
    import json as _json

    while True:
        try:
            # 1. Queue metrics
            queue_rows = await collect_queue_metrics(
                config.rabbitmq_management_host,
                config.rabbitmq_management_port,
                config.rabbitmq_username,
                config.rabbitmq_password,
            )

            # 2. Service health
            health_rows = await collect_service_health()

            # 3. API endpoint stats — flush buffer and attach to 'api' health row
            endpoint_stats = metrics_buffer.flush()
            api_row_found = False
            for row in health_rows:
                if row["service_name"] == "api":
                    api_row_found = True
                    break
            # API doesn't poll itself — create a synthetic row
            if endpoint_stats:
                if not api_row_found:
                    health_rows.append({
                        "service_name": "api",
                        "status": "healthy",
                        "response_time_ms": 0.0,
                        "endpoint_stats": _json.dumps(endpoint_stats),
                    })
                else:
                    for row in health_rows:
                        if row["service_name"] == "api":
                            row["endpoint_stats"] = _json.dumps(endpoint_stats)
                            break
            # Ensure endpoint_stats is set for non-API rows
            for row in health_rows:
                if "endpoint_stats" not in row:
                    row["endpoint_stats"] = None

            # 4. Persist
            await persist_metrics(pool, queue_rows, health_rows)
            logger.info(
                "📊 Metrics collected",
                queue_count=len(queue_rows),
                health_count=len(health_rows),
                endpoint_count=len(endpoint_stats),
            )

            # 5. Prune
            await prune_old_metrics(pool, config.metrics_retention_days)

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("❌ Metrics collection cycle failed")

        await asyncio.sleep(config.metrics_collection_interval)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_metrics_collector.py -v`
Expected: PASS — all tests green

- [ ] **Step 5: Run linting**

Run: `uv run ruff check api/metrics_collector.py && uv run mypy api/metrics_collector.py`
Expected: Clean

- [ ] **Step 6: Commit**

```bash
git add api/metrics_collector.py tests/api/test_metrics_collector.py
git commit -m "feat(api): add metrics persistence, pruning, and collector loop (#138)"
```

______________________________________________________________________

### Task 6: Pydantic Response Models

**Files:**

- Modify: `api/models.py` (append after `StorageResponse` at line 513)

- [ ] **Step 1: Write test for response model validation**

Create `tests/api/test_metrics_models.py`:

```python
"""Tests for metrics response models."""

from __future__ import annotations

from api.models import (
    HealthHistoryResponse,
    QueueHistoryResponse,
)


class TestQueueHistoryResponse:
    def test_valid_response(self) -> None:
        resp = QueueHistoryResponse(
            range="24h",
            granularity="15min",
            queues={
                "graphinator-artists": {
                    "current": {"messages_ready": 42, "consumers": 1, "publish_rate": 12.3, "ack_rate": 11.8},
                    "history": [
                        {"timestamp": "2026-03-25T10:00:00Z", "messages_ready": 38,
                         "messages_unacknowledged": 2, "publish_rate": 11.5, "ack_rate": 10.9},
                    ],
                },
            },
            dlq_summary={},
        )
        assert resp.range == "24h"
        assert "graphinator-artists" in resp.queues

    def test_empty_response(self) -> None:
        resp = QueueHistoryResponse(
            range="1h", granularity="5min", queues={}, dlq_summary={},
        )
        assert resp.queues == {}


class TestHealthHistoryResponse:
    def test_valid_response(self) -> None:
        resp = HealthHistoryResponse(
            range="24h",
            granularity="15min",
            services={
                "extractor": {
                    "current_status": "healthy",
                    "uptime_pct": 99.8,
                    "history": [],
                },
            },
            api_endpoints={},
        )
        assert resp.services["extractor"]["uptime_pct"] == 99.8

    def test_empty_response(self) -> None:
        resp = HealthHistoryResponse(
            range="1h", granularity="5min", services={}, api_endpoints={},
        )
        assert resp.services == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_metrics_models.py -v`
Expected: FAIL — `QueueHistoryResponse` not defined

- [ ] **Step 3: Add Pydantic models**

Append to `api/models.py` after line 513:

```python


# --- Metrics History models (Phase 3) ---


class QueueHistoryResponse(BaseModel):
    """Response for GET /api/admin/queues/history."""

    model_config = ConfigDict(extra="forbid")

    range: str
    granularity: str
    queues: dict[str, Any]
    dlq_summary: dict[str, Any]


class HealthHistoryResponse(BaseModel):
    """Response for GET /api/admin/health/history."""

    model_config = ConfigDict(extra="forbid")

    range: str
    granularity: str
    services: dict[str, Any]
    api_endpoints: dict[str, Any]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_metrics_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/models.py tests/api/test_metrics_models.py
git commit -m "feat(api): add Pydantic response models for metrics history endpoints (#138)"
```

______________________________________________________________________

### Task 7: Query Module — Time-series aggregation queries

**Files:**

- Create: `api/queries/metrics_queries.py`

- Create: `tests/api/test_metrics_queries.py`

- [ ] **Step 1: Write tests for granularity mapping and queue history query**

Create `tests/api/test_metrics_queries.py`:

```python
"""Tests for metrics query functions."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.queries.metrics_queries import (
    GRANULARITY_MAP,
    get_health_history,
    get_queue_history,
)


def _mock_pool_with_rows(*results: list[dict[str, Any]]) -> MagicMock:
    """Create a mock pool that returns different results for successive fetchall calls."""
    mock_cur = AsyncMock()
    mock_cur.execute = AsyncMock()
    mock_cur.fetchall = AsyncMock(side_effect=list(results))

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
    return pool


class TestGranularityMap:
    def test_all_ranges_have_granularity(self) -> None:
        expected_ranges = ["1h", "6h", "24h", "7d", "30d", "90d", "365d"]
        for r in expected_ranges:
            assert r in GRANULARITY_MAP, f"Missing range: {r}"

    def test_1h_returns_raw(self) -> None:
        assert GRANULARITY_MAP["1h"]["granularity"] == "5min"

    def test_24h_returns_15min(self) -> None:
        assert GRANULARITY_MAP["24h"]["granularity"] == "15min"

    def test_90d_returns_1day(self) -> None:
        assert GRANULARITY_MAP["90d"]["granularity"] == "1day"


class TestGetQueueHistory:
    @pytest.mark.asyncio
    async def test_returns_empty_on_no_data(self) -> None:
        pool = _mock_pool_with_rows([])
        result = await get_queue_history(pool, "24h")
        assert result["range"] == "24h"
        assert result["granularity"] == "15min"
        assert result["queues"] == {}
        assert result["dlq_summary"] == {}

    @pytest.mark.asyncio
    async def test_separates_dlq_queues(self) -> None:
        rows = [
            {"queue_name": "graphinator-artists", "bucket": "2026-03-25T10:00:00",
             "messages_ready": 42.0, "messages_unacknowledged": 3.0,
             "publish_rate": 12.0, "ack_rate": 11.0, "consumers": 1.0},
            {"queue_name": "graphinator-artists-dlq", "bucket": "2026-03-25T10:00:00",
             "messages_ready": 5.0, "messages_unacknowledged": 0.0,
             "publish_rate": 0.0, "ack_rate": 0.0, "consumers": 0.0},
        ]
        pool = _mock_pool_with_rows(rows)
        result = await get_queue_history(pool, "1h")
        assert "graphinator-artists" in result["queues"]
        assert "graphinator-artists-dlq" in result["dlq_summary"]
        assert "graphinator-artists-dlq" not in result["queues"]

    @pytest.mark.asyncio
    async def test_invalid_range_raises(self) -> None:
        pool = _mock_pool_with_rows([])
        with pytest.raises(ValueError, match="Invalid range"):
            await get_queue_history(pool, "2h")


class TestGetHealthHistory:
    @pytest.mark.asyncio
    async def test_returns_empty_on_no_data(self) -> None:
        pool = _mock_pool_with_rows([], [])  # health rows, endpoint rows
        result = await get_health_history(pool, "24h")
        assert result["services"] == {}
        assert result["api_endpoints"] == {}

    @pytest.mark.asyncio
    async def test_computes_uptime_pct(self) -> None:
        health_rows = [
            {"service_name": "extractor", "bucket": "2026-03-25T10:00:00",
             "status": "healthy", "response_time_ms": 12.0},
            {"service_name": "extractor", "bucket": "2026-03-25T10:15:00",
             "status": "healthy", "response_time_ms": 15.0},
            {"service_name": "extractor", "bucket": "2026-03-25T10:30:00",
             "status": "unhealthy", "response_time_ms": 500.0},
        ]
        endpoint_rows = []
        pool = _mock_pool_with_rows(health_rows, endpoint_rows)
        result = await get_health_history(pool, "1h")
        svc = result["services"]["extractor"]
        # 2/3 healthy = 66.67%
        assert abs(svc["uptime_pct"] - 66.67) < 0.1

    @pytest.mark.asyncio
    async def test_invalid_range_raises(self) -> None:
        pool = _mock_pool_with_rows([], [])
        with pytest.raises(ValueError, match="Invalid range"):
            await get_health_history(pool, "2h")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_metrics_queries.py -v`
Expected: FAIL — module `api.queries.metrics_queries` does not exist

- [ ] **Step 3: Implement query module**

Create `api/queries/metrics_queries.py`:

```python
"""Query functions for admin dashboard Phase 3 — metrics history endpoints.

All functions receive only their connection dependency and return plain dicts
that the router serialises via Pydantic models.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from psycopg.rows import dict_row


logger = logging.getLogger(__name__)


# Range → (SQL interval, date_trunc bucket, use_raw, granularity label)
GRANULARITY_MAP: dict[str, dict[str, Any]] = {
    "1h":   {"interval": "1 hour",   "bucket": "5 minutes",  "raw": True,  "granularity": "5min"},
    "6h":   {"interval": "6 hours",  "bucket": "5 minutes",  "raw": True,  "granularity": "5min"},
    "24h":  {"interval": "24 hours", "bucket": "15 minutes", "raw": False, "granularity": "15min"},
    "7d":   {"interval": "7 days",   "bucket": "1 hour",     "raw": False, "granularity": "1hour"},
    "30d":  {"interval": "30 days",  "bucket": "6 hours",    "raw": False, "granularity": "6hour"},
    "90d":  {"interval": "90 days",  "bucket": "1 day",      "raw": False, "granularity": "1day"},
    "365d": {"interval": "365 days", "bucket": "1 day",      "raw": False, "granularity": "1day"},
}


async def get_queue_history(pool: Any, range_value: str) -> dict[str, Any]:
    """Fetch queue metrics time-series for the given range.

    Returns dict matching QueueHistoryResponse shape.
    """
    if range_value not in GRANULARITY_MAP:
        raise ValueError(f"Invalid range: {range_value}. Valid: {list(GRANULARITY_MAP.keys())}")

    g = GRANULARITY_MAP[range_value]
    interval = g["interval"]
    bucket = g["bucket"]
    granularity = g["granularity"]
    is_raw = g["raw"]

    if is_raw:
        query = """
            SELECT queue_name,
                   recorded_at::text AS bucket,
                   messages_ready,
                   messages_unacknowledged,
                   publish_rate,
                   ack_rate,
                   consumers
            FROM queue_metrics
            WHERE recorded_at >= NOW() - INTERVAL %s
            ORDER BY recorded_at
        """
        params: tuple[Any, ...] = (interval,)
    else:
        query = """
            SELECT queue_name,
                   date_trunc(%s, recorded_at)::text AS bucket,
                   AVG(messages_ready) AS messages_ready,
                   AVG(messages_unacknowledged) AS messages_unacknowledged,
                   AVG(publish_rate) AS publish_rate,
                   AVG(ack_rate) AS ack_rate,
                   AVG(consumers) AS consumers
            FROM queue_metrics
            WHERE recorded_at >= NOW() - INTERVAL %s
            GROUP BY queue_name, date_trunc(%s, recorded_at)
            ORDER BY date_trunc(%s, recorded_at)
        """
        # date_trunc needs the unit name: 'minute', 'hour', 'day'
        trunc_unit = _bucket_to_trunc_unit(bucket)
        params = (trunc_unit, interval, trunc_unit, trunc_unit)

    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, params)
        rows = await cur.fetchall()

    # Group by queue, separate DLQs
    queues: dict[str, Any] = {}
    dlq_summary: dict[str, Any] = {}

    for row in rows:
        name = row["queue_name"]
        point = {
            "timestamp": row["bucket"],
            "messages_ready": _round_or_int(row["messages_ready"], is_raw),
            "messages_unacknowledged": _round_or_int(row["messages_unacknowledged"], is_raw),
            "publish_rate": round(float(row["publish_rate"]), 2) if row["publish_rate"] is not None else 0.0,
            "ack_rate": round(float(row["ack_rate"]), 2) if row["ack_rate"] is not None else 0.0,
        }
        if not is_raw:
            point["consumers"] = round(float(row["consumers"]), 1) if row["consumers"] is not None else 0

        target = dlq_summary if name.endswith("-dlq") else queues
        if name not in target:
            target[name] = {"current": {}, "history": []}
        target[name]["history"].append(point)

    # Set "current" to last history point for each queue
    for group in (queues, dlq_summary):
        for name, data in group.items():
            if data["history"]:
                data["current"] = data["history"][-1]

    return {
        "range": range_value,
        "granularity": granularity,
        "queues": queues,
        "dlq_summary": dlq_summary,
    }


async def get_health_history(pool: Any, range_value: str) -> dict[str, Any]:
    """Fetch service health and API endpoint metrics for the given range.

    Returns dict matching HealthHistoryResponse shape.
    """
    if range_value not in GRANULARITY_MAP:
        raise ValueError(f"Invalid range: {range_value}. Valid: {list(GRANULARITY_MAP.keys())}")

    g = GRANULARITY_MAP[range_value]
    interval = g["interval"]
    bucket = g["bucket"]
    granularity = g["granularity"]
    is_raw = g["raw"]

    # Health status query — always raw (no AVG on status strings)
    health_query = """
        SELECT service_name,
               recorded_at::text AS bucket,
               status,
               response_time_ms
        FROM service_health_metrics
        WHERE recorded_at >= NOW() - INTERVAL %s
        ORDER BY recorded_at
    """

    # Endpoint stats query — get JSONB from api rows
    endpoint_query = """
        SELECT recorded_at::text AS bucket,
               endpoint_stats
        FROM service_health_metrics
        WHERE recorded_at >= NOW() - INTERVAL %s
          AND service_name = 'api'
          AND endpoint_stats IS NOT NULL
        ORDER BY recorded_at
    """

    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(health_query, (interval,))
        health_rows = await cur.fetchall()

        await cur.execute(endpoint_query, (interval,))
        endpoint_rows = await cur.fetchall()

    # Group health rows by service
    services: dict[str, Any] = {}
    for row in health_rows:
        name = row["service_name"]
        if name not in services:
            services[name] = {"current_status": "unknown", "uptime_pct": 0.0, "history": []}
        services[name]["history"].append({
            "timestamp": row["bucket"],
            "status": row["status"],
            "response_time_ms": round(float(row["response_time_ms"]), 2) if row["response_time_ms"] is not None else 0.0,
        })

    # Compute uptime_pct and current_status
    for name, data in services.items():
        total = len(data["history"])
        healthy = sum(1 for h in data["history"] if h["status"] == "healthy")
        data["uptime_pct"] = round(healthy / total * 100, 2) if total > 0 else 0.0
        if data["history"]:
            data["current_status"] = data["history"][-1]["status"]

    # Parse endpoint stats JSONB
    api_endpoints: dict[str, Any] = {}
    for row in endpoint_rows:
        stats = row["endpoint_stats"]
        if isinstance(stats, str):
            stats = json.loads(stats)
        if not isinstance(stats, dict):
            continue
        bucket_ts = row["bucket"]
        for endpoint, metrics in stats.items():
            if endpoint not in api_endpoints:
                api_endpoints[endpoint] = {"latest": {}, "history": []}
            api_endpoints[endpoint]["history"].append({
                "timestamp": bucket_ts,
                **metrics,
            })

    # Set "latest" to last history point
    for endpoint, data in api_endpoints.items():
        if data["history"]:
            data["latest"] = data["history"][-1]

    return {
        "range": range_value,
        "granularity": granularity,
        "services": services,
        "api_endpoints": api_endpoints,
    }


def _bucket_to_trunc_unit(bucket: str) -> str:
    """Convert bucket string like '15 minutes' to date_trunc unit 'minute'."""
    if "minute" in bucket:
        return "minute"
    if "hour" in bucket:
        return "hour"
    if "day" in bucket:
        return "day"
    return "hour"


def _round_or_int(value: Any, is_raw: bool) -> int | float:
    """Return int for raw values, rounded float for aggregated."""
    if value is None:
        return 0
    if is_raw:
        return int(value)
    return round(float(value), 1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_metrics_queries.py -v`
Expected: PASS — all tests green

- [ ] **Step 5: Run linting**

Run: `uv run ruff check api/queries/metrics_queries.py && uv run mypy api/queries/metrics_queries.py`
Expected: Clean

- [ ] **Step 6: Commit**

```bash
git add api/queries/metrics_queries.py tests/api/test_metrics_queries.py
git commit -m "feat(api): add metrics time-series query functions (#138)"
```

______________________________________________________________________

### Task 8: Admin Router Endpoints — `queues/history` and `health/history`

**Files:**

- Modify: `api/routers/admin.py` (add 2 endpoint functions after Phase 2 section)

- Modify: `tests/api/test_admin_endpoints.py` (add endpoint tests)

- [ ] **Step 1: Write endpoint tests**

Append to `tests/api/test_admin_endpoints.py`:

```python
class TestQueueHistory:
    @patch("api.routers.admin.get_queue_history")
    def test_success(self, mock_query: Any, test_client: TestClient) -> None:
        mock_query.return_value = {
            "range": "24h",
            "granularity": "15min",
            "queues": {},
            "dlq_summary": {},
        }
        resp = test_client.get(
            "/api/admin/queues/history?range=24h",
            headers=_admin_auth_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["range"] == "24h"
        assert data["granularity"] == "15min"

    def test_no_token_returns_401_or_403(self, test_client: TestClient) -> None:
        resp = test_client.get("/api/admin/queues/history")
        assert resp.status_code in (401, 403)

    @patch("api.routers.admin.get_queue_history")
    def test_invalid_range_returns_422(self, mock_query: Any, test_client: TestClient) -> None:
        mock_query.side_effect = ValueError("Invalid range: 2h")
        resp = test_client.get(
            "/api/admin/queues/history?range=2h",
            headers=_admin_auth_headers(),
        )
        assert resp.status_code == 422

    @patch("api.routers.admin.get_queue_history")
    def test_default_range_is_24h(self, mock_query: Any, test_client: TestClient) -> None:
        mock_query.return_value = {
            "range": "24h", "granularity": "15min", "queues": {}, "dlq_summary": {},
        }
        resp = test_client.get(
            "/api/admin/queues/history",
            headers=_admin_auth_headers(),
        )
        assert resp.status_code == 200
        mock_query.assert_called_once()
        call_args = mock_query.call_args
        assert call_args[0][1] == "24h"  # second positional arg is range


class TestHealthHistory:
    @patch("api.routers.admin.get_health_history")
    def test_success(self, mock_query: Any, test_client: TestClient) -> None:
        mock_query.return_value = {
            "range": "7d",
            "granularity": "1hour",
            "services": {},
            "api_endpoints": {},
        }
        resp = test_client.get(
            "/api/admin/health/history?range=7d",
            headers=_admin_auth_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["range"] == "7d"

    def test_no_token_returns_401_or_403(self, test_client: TestClient) -> None:
        resp = test_client.get("/api/admin/health/history")
        assert resp.status_code in (401, 403)

    @patch("api.routers.admin.get_health_history")
    def test_invalid_range_returns_422(self, mock_query: Any, test_client: TestClient) -> None:
        mock_query.side_effect = ValueError("Invalid range: bad")
        resp = test_client.get(
            "/api/admin/health/history?range=bad",
            headers=_admin_auth_headers(),
        )
        assert resp.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_admin_endpoints.py::TestQueueHistory -v`
Expected: FAIL — 404 (route not found)

- [ ] **Step 3: Add router endpoints**

In `api/routers/admin.py`, add the import at the top (after existing `from api.queries.admin_queries import ...`):

```python
from api.queries.metrics_queries import get_health_history, get_queue_history
```

Then add endpoints after the Phase 2 storage endpoint (after line 263):

```python


# ---------------------------------------------------------------------------
# Phase 3 — Queue Health Trends & System Health
# ---------------------------------------------------------------------------


@router.get("/api/admin/queues/history")
async def admin_queue_history(
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
    range: str = "24h",  # noqa: A002
) -> JSONResponse:
    """Queue depth time-series for the given range."""
    if _pool is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")
    try:
        data = await get_queue_history(_pool, range)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return JSONResponse(content=data)


@router.get("/api/admin/health/history")
async def admin_health_history(
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
    range: str = "24h",  # noqa: A002
) -> JSONResponse:
    """Service health and API endpoint metrics for the given range."""
    if _pool is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")
    try:
        data = await get_health_history(_pool, range)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return JSONResponse(content=data)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_admin_endpoints.py::TestQueueHistory tests/api/test_admin_endpoints.py::TestHealthHistory -v`
Expected: PASS

- [ ] **Step 5: Run all admin endpoint tests**

Run: `uv run pytest tests/api/test_admin_endpoints.py -v`
Expected: All existing + new tests pass

- [ ] **Step 6: Commit**

```bash
git add api/routers/admin.py tests/api/test_admin_endpoints.py
git commit -m "feat(api): add queue history and health history admin endpoints (#138)"
```

______________________________________________________________________

### Task 9: API Lifespan — Start collector task and add metrics middleware

**Files:**

- Modify: `api/api.py:184-268` (lifespan function)

- [ ] **Step 1: Add middleware and collector startup to lifespan**

In `api/api.py`, add the import near the top (after `import api.routers.admin as _admin_router`):

```python
from api.metrics_collector import MetricsBuffer, normalize_path, run_collector
```

In the `lifespan` function, after the line `_app.state.prewarm_task = asyncio.create_task(_prewarm_search_cache())` (line 248), add:

```python
    # Start background metrics collector
    metrics_buffer = MetricsBuffer()
    _app.state.metrics_buffer = metrics_buffer
    _app.state.collector_task = asyncio.create_task(run_collector(_pool, _config, metrics_buffer))
    logger.info("📊 Metrics collector started", interval=_config.metrics_collection_interval)
```

In the shutdown section (before `if _neo4j:`), add:

```python
    if hasattr(_app.state, "collector_task"):
        _app.state.collector_task.cancel()
        await asyncio.gather(_app.state.collector_task, return_exceptions=True)
```

Then add the metrics middleware. After the `security_headers` middleware (after line 302), add:

```python


@app.middleware("http")
async def metrics_middleware(request: Request, call_next: Any) -> Any:
    """Record per-request timing for endpoint performance metrics."""
    import time as _time

    path = normalize_path(request.url.path)
    start = _time.monotonic()
    response = await call_next(request)
    elapsed_ms = (_time.monotonic() - start) * 1000
    if hasattr(app.state, "metrics_buffer"):
        app.state.metrics_buffer.record(path, response.status_code, elapsed_ms)
    return response
```

- [ ] **Step 2: Run existing API tests to verify nothing breaks**

Run: `uv run pytest tests/api/ -v`
Expected: All tests pass (middleware is a no-op when `metrics_buffer` not set)

- [ ] **Step 3: Commit**

```bash
git add api/api.py
git commit -m "feat(api): start metrics collector and add timing middleware (#138)"
```

______________________________________________________________________

### Task 10: Dashboard Proxy Routes

**Files:**

- Modify: `dashboard/admin_proxy.py` (add 2 proxy routes after Phase 2 section)

- Modify: `tests/dashboard/test_admin_proxy.py` (add proxy tests)

- [ ] **Step 1: Write proxy route tests**

Append to `tests/dashboard/test_admin_proxy.py`:

```python
class TestQueueHistoryProxy:
    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_forwards_with_query_params(self, mock_client_cls: Any, test_client: TestClient) -> None:
        mock_response = MagicMock()
        mock_response.content = b'{"range":"7d","granularity":"1hour","queues":{},"dlq_summary":{}}'
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        resp = test_client.get(
            "/admin/api/queues/history?range=7d",
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 200
        # Verify query param was forwarded
        call_url = mock_client.get.call_args[0][0]
        assert "/api/admin/queues/history" in call_url

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_api_unavailable(self, mock_client_cls: Any, test_client: TestClient) -> None:
        import httpx as _httpx

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=_httpx.ConnectError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        resp = test_client.get("/admin/api/queues/history")
        assert resp.status_code == 502


class TestHealthHistoryProxy:
    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_forwards_request(self, mock_client_cls: Any, test_client: TestClient) -> None:
        mock_response = MagicMock()
        mock_response.content = b'{"range":"24h","granularity":"15min","services":{},"api_endpoints":{}}'
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        resp = test_client.get(
            "/admin/api/health/history",
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/dashboard/test_admin_proxy.py::TestQueueHistoryProxy -v`
Expected: FAIL — 404 (route not found)

- [ ] **Step 3: Add proxy routes**

In `dashboard/admin_proxy.py`, add after the Phase 2 storage proxy (after line 215):

```python


# ---------------------------------------------------------------------------
# Phase 3 — Queue Health Trends & System Health proxy routes
# ---------------------------------------------------------------------------


@router.get("/admin/api/queues/history")
async def proxy_queue_history(request: Request) -> Response:
    """Proxy queue history requests to the API service."""
    query_string = str(request.query_params)
    url = _build_url("/api/admin/queues/history")
    if query_string:
        url = f"{url}?{query_string}"
    headers = _auth_headers(request)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
    except (httpx.ConnectError, httpx.RequestError) as exc:
        logger.error("❌ API service unreachable", url=url, error=str(exc))
        return _unavailable_response()
    return _ok_response(resp)


@router.get("/admin/api/health/history")
async def proxy_health_history(request: Request) -> Response:
    """Proxy health history requests to the API service."""
    query_string = str(request.query_params)
    url = _build_url("/api/admin/health/history")
    if query_string:
        url = f"{url}?{query_string}"
    headers = _auth_headers(request)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
    except (httpx.ConnectError, httpx.RequestError) as exc:
        logger.error("❌ API service unreachable", url=url, error=str(exc))
        return _unavailable_response()
    return _ok_response(resp)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/dashboard/test_admin_proxy.py -v`
Expected: All existing + new tests pass

- [ ] **Step 5: Commit**

```bash
git add dashboard/admin_proxy.py tests/dashboard/test_admin_proxy.py
git commit -m "feat(dashboard): add queue and health history proxy routes (#138)"
```

______________________________________________________________________

### Task 11: Frontend — Admin HTML tabs and Chart.js CDN

**Files:**

- Modify: `dashboard/static/admin.html`

- [ ] **Step 1: Add Chart.js CDN and new tabs**

In `dashboard/static/admin.html`, add the Chart.js CDN script tag in the `<head>` section (after the Tailwind CSS CDN):

```html
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
```

Add two new tab buttons to the tab bar (after the existing Storage tab button):

```html
<button class="tab-btn" data-tab="queue-trends">Queue Trends</button>
<button class="tab-btn" data-tab="system-health">System Health</button>
```

Add two new tab content sections (after the existing Storage tab content):

```html
<!-- Queue Trends Tab -->
<div id="queue-trends-tab" class="tab-content hidden">
    <div id="queue-trends-controls" class="flex justify-between items-center mb-4">
        <div id="queue-range-selector" class="flex gap-1">
            <button class="range-btn px-3 py-1 rounded text-sm bg-gray-700 text-gray-400" data-range="1h">1h</button>
            <button class="range-btn px-3 py-1 rounded text-sm bg-gray-700 text-gray-400" data-range="6h">6h</button>
            <button class="range-btn px-3 py-1 rounded text-sm bg-indigo-600 text-white font-semibold" data-range="24h">24h</button>
            <button class="range-btn px-3 py-1 rounded text-sm bg-gray-700 text-gray-400" data-range="7d">7d</button>
            <button class="range-btn px-3 py-1 rounded text-sm bg-gray-700 text-gray-400" data-range="30d">30d</button>
            <button class="range-btn px-3 py-1 rounded text-sm bg-gray-700 text-gray-400" data-range="90d">90d</button>
        </div>
        <div class="flex items-center gap-2">
            <span class="text-gray-500 text-xs">Auto-refresh 60s</span>
            <button id="queue-refresh-btn" class="px-2 py-1 rounded text-sm bg-gray-700 text-gray-400">&#8635; Refresh</button>
        </div>
    </div>
    <div id="queue-summary-tiles" class="grid grid-cols-5 gap-3 mb-5"></div>
    <div class="bg-gray-800 rounded-lg p-4 mb-4">
        <div class="flex justify-between items-center mb-3">
            <span class="text-white text-sm font-semibold">Queue Depth Over Time</span>
            <div id="queue-chart-legend" class="flex gap-3 text-xs"></div>
        </div>
        <canvas id="queue-depth-chart" height="180"></canvas>
    </div>
    <div class="bg-gray-800 rounded-lg p-4">
        <span class="text-white text-sm font-semibold">DLQ Message Counts</span>
        <div id="dlq-grid" class="grid grid-cols-2 gap-3 mt-3"></div>
    </div>
</div>

<!-- System Health Tab -->
<div id="system-health-tab" class="tab-content hidden">
    <div id="health-controls" class="flex justify-between items-center mb-4">
        <div id="health-range-selector" class="flex gap-1">
            <button class="range-btn px-3 py-1 rounded text-sm bg-gray-700 text-gray-400" data-range="1h">1h</button>
            <button class="range-btn px-3 py-1 rounded text-sm bg-gray-700 text-gray-400" data-range="6h">6h</button>
            <button class="range-btn px-3 py-1 rounded text-sm bg-indigo-600 text-white font-semibold" data-range="24h">24h</button>
            <button class="range-btn px-3 py-1 rounded text-sm bg-gray-700 text-gray-400" data-range="7d">7d</button>
            <button class="range-btn px-3 py-1 rounded text-sm bg-gray-700 text-gray-400" data-range="30d">30d</button>
            <button class="range-btn px-3 py-1 rounded text-sm bg-gray-700 text-gray-400" data-range="90d">90d</button>
        </div>
        <button id="health-refresh-btn" class="px-2 py-1 rounded text-sm bg-gray-700 text-gray-400">&#8635; Refresh</button>
    </div>
    <div id="service-status-cards" class="grid grid-cols-5 gap-3 mb-5"></div>
    <div class="bg-gray-800 rounded-lg p-4 mb-4">
        <div class="flex justify-between items-center mb-3">
            <span class="text-white text-sm font-semibold">API Response Times</span>
            <div class="flex gap-3 text-xs">
                <span class="text-emerald-400">&#9679; p50</span>
                <span class="text-amber-400">&#9679; p95</span>
                <span class="text-red-400">&#9679; p99</span>
            </div>
        </div>
        <canvas id="response-time-chart" height="150"></canvas>
    </div>
    <div class="bg-gray-800 rounded-lg p-4">
        <span class="text-white text-sm font-semibold">Top Endpoints (by request count)</span>
        <table id="endpoints-table" class="w-full mt-3 text-sm">
            <thead>
                <tr class="text-gray-400 text-left border-b border-gray-700">
                    <th class="px-3 py-2">Endpoint</th>
                    <th class="px-3 py-2 text-right">Requests</th>
                    <th class="px-3 py-2 text-right">p50</th>
                    <th class="px-3 py-2 text-right">p95</th>
                    <th class="px-3 py-2 text-right">p99</th>
                    <th class="px-3 py-2 text-right">Error %</th>
                </tr>
            </thead>
            <tbody id="endpoints-tbody" class="text-white"></tbody>
        </table>
    </div>
</div>
```

- [ ] **Step 2: Verify the HTML renders correctly**

Open the admin dashboard in a browser and verify the two new tabs appear. They will be empty until JS is wired.

- [ ] **Step 3: Commit**

```bash
git add dashboard/static/admin.html
git commit -m "feat(dashboard): add Queue Trends and System Health tab markup (#138)"
```

______________________________________________________________________

### Task 12: Frontend — JavaScript logic for Queue Trends and System Health

**Files:**

- Modify: `dashboard/static/admin.js`

- [ ] **Step 1: Add Queue Trends fetch and render logic**

Add the following to `dashboard/static/admin.js` (in the appropriate section, following the existing panel patterns):

Queue Trends functionality:

- `fetchQueueHistory(range)` — calls `/admin/api/queues/history?range=<range>`, updates summary tiles, Chart.js chart, and DLQ grid

- Range selector click handlers on `#queue-range-selector` buttons — updates active state, re-fetches with new range, stores in `localStorage`

- `renderQueueSummaryTiles(data)` — renders 5 tiles (Total Queue Depth, DLQ Messages, Avg Publish Rate, Avg Ack Rate, Active Consumers) with inline SVG sparklines

- `renderQueueDepthChart(data)` — initializes/updates a Chart.js line chart on `#queue-depth-chart` canvas with one dataset per queue

- `renderDlqGrid(data)` — renders per-DLQ cards with mini SVG sparklines and current count

- `generateSparklineSVG(points, color, width, height)` — utility to create inline SVG polyline from array of numbers

- Auto-refresh via `setInterval(fetchQueueHistory, 60000)`

- Manual refresh button handler on `#queue-refresh-btn`

- [ ] **Step 2: Add System Health fetch and render logic**

System Health functionality:

- `fetchHealthHistory(range)` — calls `/admin/api/health/history?range=<range>`, updates service cards, Chart.js chart, and endpoints table

- Range selector and refresh handlers (same pattern as Queue Trends)

- `renderServiceCards(data)` — renders 5 service status cards with color-coded borders (green/yellow/red), uptime %, latency

- `renderResponseTimeChart(data)` — Chart.js line chart with 3 datasets (p50, p95, p99) aggregated across all endpoints

- `renderEndpointsTable(data)` — populates `#endpoints-tbody` sorted by request count, error rate color-coded

- Auto-refresh and manual refresh (same pattern)

- [ ] **Step 3: Test in browser**

Open the admin dashboard, log in, navigate to Queue Trends and System Health tabs. Verify:

- Range selector buttons toggle correctly and persist selection in localStorage

- Charts render (will show "no data" until collector has run)

- Auto-refresh fires every 60 seconds

- Manual refresh button works

- Both tabs handle API errors gracefully (inline warning, no page crash)

- [ ] **Step 4: Commit**

```bash
git add dashboard/static/admin.js
git commit -m "feat(dashboard): add Queue Trends and System Health JavaScript (#138)"
```

______________________________________________________________________

### Task 13: Final Integration — Run all tests and lint

**Files:** None (verification only)

- [ ] **Step 1: Run full Python test suite**

Run: `just test`
Expected: All tests pass including new ones

- [ ] **Step 2: Run JavaScript tests**

Run: `just test-js`
Expected: All tests pass

- [ ] **Step 3: Run linting**

Run: `just lint`
Expected: Clean — no ruff, mypy, or other lint errors

- [ ] **Step 4: Run format check**

Run: `just format`
Expected: No formatting changes needed (or auto-fixed)

- [ ] **Step 5: Final commit if any formatting fixes**

```bash
git add -u
git commit -m "style: format Phase 3 code (#138)"
```

______________________________________________________________________

### Task 14: Documentation — Update admin guide and diagrams

**Files:**

- Modify: `docs/admin-guide.md`

- [ ] **Step 1: Add Phase 3 section to admin guide**

Add a section documenting:

- New endpoints: `GET /api/admin/queues/history?range=`, `GET /api/admin/health/history?range=`

- Valid range values: 1h, 6h, 24h, 7d, 30d, 90d, 365d

- New config: `METRICS_RETENTION_DAYS` (default 366), `METRICS_COLLECTION_INTERVAL` (default 300)

- New database tables: `queue_metrics`, `service_health_metrics`

- Dashboard: Queue Trends and System Health tabs

- [ ] **Step 2: Commit**

```bash
git add docs/admin-guide.md
git commit -m "docs: update admin guide with Phase 3 endpoints and config (#138)"
```
