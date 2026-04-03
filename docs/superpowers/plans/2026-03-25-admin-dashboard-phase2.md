# Admin Dashboard Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add user activity stats, sync activity stats, and storage utilization endpoints to the admin dashboard with frontend panels.

**Architecture:** Thin admin router endpoints delegate to a dedicated query module (`api/queries/admin_queries.py`). Storage queries run concurrently via `asyncio.gather` with partial failure handling. Dashboard proxy forwards requests from the dashboard frontend to the API service.

**Tech Stack:** Python 3.13+, FastAPI, psycopg (async), neo4j async driver, aioredis, Pydantic v2, structlog

**Spec:** `docs/superpowers/specs/2026-03-25-admin-dashboard-phase2-design.md`

**Prerequisites:** Local `main` must include Phase 1 commit `67ff31c` from `origin/main`. Run `git pull --rebase origin main` before starting.

______________________________________________________________________

## File Map

### Files to Create

| File                              | Responsibility                                                                                                               |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `api/queries/admin_queries.py`    | All query functions: `get_user_stats`, `get_sync_activity`, `get_neo4j_storage`, `get_postgres_storage`, `get_redis_storage` |
| `tests/api/test_admin_queries.py` | Unit tests for all query functions with mocked DB connections                                                                |

### Files to Modify

| File                                  | Change                                                         |
| ------------------------------------- | -------------------------------------------------------------- |
| `api/models.py`                       | Add Pydantic response models for the 3 new endpoints           |
| `api/routers/admin.py`                | Add 3 thin endpoint functions + extend `configure()` signature |
| `api/api.py`                          | Pass `_neo4j` driver to `_admin_router.configure()`            |
| `dashboard/admin_proxy.py`            | Add 3 proxy GET routes                                         |
| `dashboard/static/admin.html`         | Add User Activity and Storage Utilization panel markup         |
| `dashboard/static/admin.js`           | Add fetch + render logic for new panels                        |
| `tests/api/test_admin_endpoints.py`   | Add tests for 3 new endpoints                                  |
| `tests/dashboard/test_admin_proxy.py` | Add tests for 3 new proxy routes                               |

______________________________________________________________________

## Task 1: Pydantic Response Models

**Files:**

- Modify: `api/models.py` (append after existing admin models, line ~369)

- Test: `tests/api/test_api_models.py` (extend)

- [ ] **Step 1: Write model validation tests**

Add to `tests/api/test_api_models.py`:

```python
# --- Admin Phase 2 Models ---


class TestAdminUserStatsModels:
    """Tests for user stats response models."""

    def test_daily_registration(self):
        from api.models import DailyRegistration
        obj = DailyRegistration(date="2026-03-18", count=5)
        assert obj.date == "2026-03-18"
        assert obj.count == 5

    def test_weekly_registration(self):
        from api.models import WeeklyRegistration
        obj = WeeklyRegistration(week_start="2026-03-17", count=12)
        assert obj.week_start == "2026-03-17"
        assert obj.count == 12

    def test_monthly_registration(self):
        from api.models import MonthlyRegistration
        obj = MonthlyRegistration(month="2026-03", count=34)
        assert obj.month == "2026-03"
        assert obj.count == 34

    def test_registration_time_series(self):
        from api.models import RegistrationTimeSeries
        obj = RegistrationTimeSeries(daily=[], weekly=[], monthly=[])
        assert obj.daily == []

    def test_user_stats_response(self):
        from api.models import UserStatsResponse
        obj = UserStatsResponse(
            total_users=150,
            active_7d=42,
            active_30d=89,
            oauth_connection_rate=0.63,
            registrations={"daily": [], "weekly": [], "monthly": []},
        )
        assert obj.total_users == 150
        assert obj.oauth_connection_rate == 0.63


class TestSyncActivityModels:
    """Tests for sync activity response models."""

    def test_sync_period_stats(self):
        from api.models import SyncPeriodStats
        obj = SyncPeriodStats(
            total_syncs=28,
            syncs_per_day=4.0,
            avg_items_synced=142.5,
            failure_rate=0.07,
            total_failures=2,
        )
        assert obj.syncs_per_day == 4.0

    def test_sync_activity_response(self):
        from api.models import SyncActivityResponse, SyncPeriodStats
        period = SyncPeriodStats(
            total_syncs=0, syncs_per_day=0.0,
            avg_items_synced=0.0, failure_rate=0.0, total_failures=0,
        )
        obj = SyncActivityResponse(period_7d=period, period_30d=period)
        assert obj.period_7d.total_syncs == 0


class TestStorageModels:
    """Tests for storage utilization response models."""

    def test_storage_source_ok(self):
        from api.models import Neo4jStorage
        obj = Neo4jStorage(status="ok", nodes=[], relationships=[], store_sizes=None)
        assert obj.status == "ok"

    def test_storage_source_error(self):
        from api.models import StorageSourceError
        obj = StorageSourceError(status="error", error="connection failed")
        assert obj.status == "error"

    def test_storage_response(self):
        from api.models import StorageResponse, StorageSourceError
        err = StorageSourceError(status="error", error="down")
        obj = StorageResponse(neo4j=err.model_dump(), postgresql=err.model_dump(), redis=err.model_dump())
        assert obj.neo4j["status"] == "error"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_api_models.py::TestAdminUserStatsModels -v --no-header 2>&1 | tail -5`
Expected: FAIL with `ImportError` (models don't exist yet)

- [ ] **Step 3: Write Pydantic models**

Append to `api/models.py` after the existing `DlqPurgeResponse` class:

```python
# ---------------------------------------------------------------------------
# Admin Phase 2 — User Activity & Storage models
# ---------------------------------------------------------------------------


class DailyRegistration(BaseModel):
    """A single day's registration count."""

    date: str
    count: int


class WeeklyRegistration(BaseModel):
    """A single week's registration count."""

    week_start: str
    count: int


class MonthlyRegistration(BaseModel):
    """A single month's registration count."""

    month: str
    count: int


class RegistrationTimeSeries(BaseModel):
    """Registration counts over time."""

    daily: list[DailyRegistration]
    weekly: list[WeeklyRegistration]
    monthly: list[MonthlyRegistration]


class UserStatsResponse(BaseModel):
    """User activity statistics."""

    total_users: int
    active_7d: int
    active_30d: int
    oauth_connection_rate: float
    registrations: RegistrationTimeSeries


class SyncPeriodStats(BaseModel):
    """Sync activity stats for a single time period."""

    total_syncs: int
    syncs_per_day: float
    avg_items_synced: float
    failure_rate: float
    total_failures: int


class SyncActivityResponse(BaseModel):
    """Sync activity stats for 7d and 30d windows."""

    model_config = ConfigDict(populate_by_name=True)

    period_7d: SyncPeriodStats = Field(alias="period_7d")
    period_30d: SyncPeriodStats = Field(alias="period_30d")


class NodeCount(BaseModel):
    """Count of nodes by label."""

    label: str
    count: int


class RelationshipCount(BaseModel):
    """Count of relationships by type."""

    type: str
    count: int


class StoreSizes(BaseModel):
    """Neo4j store sizes in human-readable format."""

    total: str
    nodes: str
    relationships: str
    strings: str


class Neo4jStorage(BaseModel):
    """Neo4j storage utilization."""

    status: str
    nodes: list[NodeCount] = []
    relationships: list[RelationshipCount] = []
    store_sizes: StoreSizes | None = None


class TableSize(BaseModel):
    """PostgreSQL table size info."""

    name: str
    row_count: int
    size: str
    index_size: str


class PostgresStorage(BaseModel):
    """PostgreSQL storage utilization."""

    status: str
    tables: list[TableSize] = []
    total_size: str = ""


class RedisKeyPrefix(BaseModel):
    """Redis key count by prefix."""

    prefix: str
    count: int


class RedisStorage(BaseModel):
    """Redis storage utilization."""

    status: str
    memory_used: str = ""
    memory_peak: str = ""
    total_keys: int = 0
    keys_by_prefix: list[RedisKeyPrefix] = []


class StorageSourceError(BaseModel):
    """Error response for a single storage source."""

    status: str = "error"
    error: str


class StorageResponse(BaseModel):
    """Combined storage utilization response (values can be typed storage or error dict)."""

    neo4j: dict[str, Any]
    postgresql: dict[str, Any]
    redis: dict[str, Any]
```

**Important:** Add `from typing import Any` to the existing imports at the top of `api/models.py` (it is not currently imported). Add it alongside the other stdlib imports.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_api_models.py::TestAdminUserStatsModels tests/api/test_api_models.py::TestSyncActivityModels tests/api/test_api_models.py::TestStorageModels -v --no-header 2>&1 | tail -15`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add api/models.py tests/api/test_api_models.py
git commit -m "feat(admin): add Pydantic models for Phase 2 endpoints (#137)"
```

______________________________________________________________________

## Task 2: User Stats Query Function

**Files:**

- Create: `api/queries/admin_queries.py`

- Create: `tests/api/test_admin_queries.py`

- [ ] **Step 1: Write failing tests for `get_user_stats`**

Create `tests/api/test_admin_queries.py`:

```python
"""Tests for api/queries/admin_queries.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def _mock_pool_with_rows(*query_results: list[dict]) -> MagicMock:
    """Build a mock pool whose cursor returns different results for successive queries.

    Each element in *query_results* is the list of dicts returned by fetchall()
    (or fetchone() returning the first element) for the corresponding execute() call.
    """
    results_iter = iter(query_results)

    mock_cur = AsyncMock()

    async def _execute_side_effect(*_args, **_kwargs):
        mock_cur._current_result = next(results_iter)

    mock_cur.execute = AsyncMock(side_effect=_execute_side_effect)
    mock_cur.fetchone = AsyncMock(side_effect=lambda: mock_cur._current_result[0] if mock_cur._current_result else None)
    mock_cur.fetchall = AsyncMock(side_effect=lambda: mock_cur._current_result)
    mock_cur._current_result = []

    mock_conn = AsyncMock()
    mock_conn.cursor = MagicMock(return_value=mock_cur)
    mock_conn.__aenter__ = AsyncMock(return_value=mock_cur)
    mock_conn.__aexit__ = AsyncMock(return_value=False)

    mock_pool = MagicMock()
    mock_pool.connection = MagicMock(return_value=mock_conn)
    mock_conn_ctx = AsyncMock()
    mock_conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_pool.connection = MagicMock(return_value=mock_conn_ctx)

    return mock_pool


class TestGetUserStats:
    """Tests for get_user_stats query function."""

    @pytest.mark.asyncio
    async def test_basic_user_stats(self):
        from api.queries.admin_queries import get_user_stats

        pool = _mock_pool_with_rows(
            # total_users + oauth + active counts
            [{"total_users": 150, "oauth_users": 95, "active_7d": 42, "active_30d": 89}],
            # daily registrations
            [{"date": "2026-03-18", "count": 5}],
            # weekly registrations
            [{"week_start": "2026-03-17", "count": 12}],
            # monthly registrations
            [{"month": "2026-03", "count": 34}],
        )

        result = await get_user_stats(pool)

        assert result["total_users"] == 150
        assert result["active_7d"] == 42
        assert result["active_30d"] == 89
        assert result["oauth_connection_rate"] == pytest.approx(95 / 150)
        assert result["registrations"]["daily"] == [{"date": "2026-03-18", "count": 5}]
        assert result["registrations"]["weekly"] == [{"week_start": "2026-03-17", "count": 12}]
        assert result["registrations"]["monthly"] == [{"month": "2026-03", "count": 34}]

    @pytest.mark.asyncio
    async def test_zero_users(self):
        from api.queries.admin_queries import get_user_stats

        pool = _mock_pool_with_rows(
            [{"total_users": 0, "oauth_users": 0, "active_7d": 0, "active_30d": 0}],
            [],  # daily
            [],  # weekly
            [],  # monthly
        )

        result = await get_user_stats(pool)

        assert result["total_users"] == 0
        assert result["oauth_connection_rate"] == 0.0
        assert result["registrations"]["daily"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_admin_queries.py::TestGetUserStats -v --no-header 2>&1 | tail -5`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `get_user_stats`**

Create `api/queries/admin_queries.py`:

```python
"""Query functions for admin dashboard Phase 2 endpoints.

All functions receive only their connection dependency and return plain dicts
that the router serialises via Pydantic models.
"""

from __future__ import annotations

import logging
from typing import Any

from psycopg.rows import dict_row

from common.query_debug import execute_sql


logger = logging.getLogger(__name__)


async def get_user_stats(pool: Any) -> dict[str, Any]:
    """Fetch user registration stats, active user counts, and OAuth rate.

    "Active" = user has at least one sync_history row with started_at in the window.
    """
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            # Summary counts — single query joining users, oauth_tokens, sync_history
            await execute_sql(
                cur,
                """
                SELECT
                    (SELECT COUNT(*) FROM users) AS total_users,
                    (SELECT COUNT(DISTINCT user_id) FROM oauth_tokens WHERE provider = 'discogs') AS oauth_users,
                    (SELECT COUNT(DISTINCT user_id) FROM sync_history
                     WHERE started_at >= NOW() - INTERVAL '7 days') AS active_7d,
                    (SELECT COUNT(DISTINCT user_id) FROM sync_history
                     WHERE started_at >= NOW() - INTERVAL '30 days') AS active_30d
                """,
            )
            summary = await cur.fetchone()

            total = summary["total_users"]
            oauth_rate = round(summary["oauth_users"] / total, 4) if total > 0 else 0.0

            # Daily registrations (last 30 days)
            await execute_sql(
                cur,
                """
                SELECT date_trunc('day', created_at)::date::text AS date,
                       COUNT(*) AS count
                FROM users
                WHERE created_at >= NOW() - INTERVAL '30 days'
                GROUP BY 1 ORDER BY 1
                """,
            )
            daily = [dict(row) for row in await cur.fetchall()]

            # Weekly registrations (last 12 weeks)
            await execute_sql(
                cur,
                """
                SELECT date_trunc('week', created_at)::date::text AS week_start,
                       COUNT(*) AS count
                FROM users
                WHERE created_at >= NOW() - INTERVAL '12 weeks'
                GROUP BY 1 ORDER BY 1
                """,
            )
            weekly = [dict(row) for row in await cur.fetchall()]

            # Monthly registrations (last 12 months)
            await execute_sql(
                cur,
                """
                SELECT to_char(date_trunc('month', created_at), 'YYYY-MM') AS month,
                       COUNT(*) AS count
                FROM users
                WHERE created_at >= NOW() - INTERVAL '12 months'
                GROUP BY 1 ORDER BY 1
                """,
            )
            monthly = [dict(row) for row in await cur.fetchall()]

    return {
        "total_users": total,
        "active_7d": summary["active_7d"],
        "active_30d": summary["active_30d"],
        "oauth_connection_rate": oauth_rate,
        "registrations": {
            "daily": daily,
            "weekly": weekly,
            "monthly": monthly,
        },
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_admin_queries.py::TestGetUserStats -v --no-header 2>&1 | tail -10`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add api/queries/admin_queries.py tests/api/test_admin_queries.py
git commit -m "feat(admin): add get_user_stats query function (#137)"
```

______________________________________________________________________

## Task 3: Sync Activity Query Function

**Files:**

- Modify: `api/queries/admin_queries.py`

- Modify: `tests/api/test_admin_queries.py`

- [ ] **Step 1: Write failing tests for `get_sync_activity`**

Add to `tests/api/test_admin_queries.py`:

```python
class TestGetSyncActivity:
    """Tests for get_sync_activity query function."""

    @pytest.mark.asyncio
    async def test_basic_sync_activity(self):
        from api.queries.admin_queries import get_sync_activity

        pool = _mock_pool_with_rows(
            # 7d stats
            [{"total_syncs": 28, "total_failures": 2, "avg_items": 142.5}],
            # 30d stats
            [{"total_syncs": 95, "total_failures": 5, "avg_items": 138.2}],
        )

        result = await get_sync_activity(pool)

        assert result["period_7d"]["total_syncs"] == 28
        assert result["period_7d"]["syncs_per_day"] == pytest.approx(4.0)
        assert result["period_7d"]["failure_rate"] == pytest.approx(2 / 28)
        assert result["period_30d"]["total_syncs"] == 95

    @pytest.mark.asyncio
    async def test_zero_syncs(self):
        from api.queries.admin_queries import get_sync_activity

        pool = _mock_pool_with_rows(
            [{"total_syncs": 0, "total_failures": 0, "avg_items": None}],
            [{"total_syncs": 0, "total_failures": 0, "avg_items": None}],
        )

        result = await get_sync_activity(pool)

        assert result["period_7d"]["syncs_per_day"] == 0.0
        assert result["period_7d"]["failure_rate"] == 0.0
        assert result["period_7d"]["avg_items_synced"] == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_admin_queries.py::TestGetSyncActivity -v --no-header 2>&1 | tail -5`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `get_sync_activity`**

Add to `api/queries/admin_queries.py`:

```python
async def get_sync_activity(pool: Any) -> dict[str, Any]:
    """Fetch sync activity stats for 7d and 30d windows."""

    async def _query_period(cur: Any, days: int) -> dict[str, Any]:
        await execute_sql(
            cur,
            """
            SELECT
                COUNT(*) AS total_syncs,
                COUNT(*) FILTER (WHERE status = 'failed') AS total_failures,
                AVG(COALESCE(items_synced, 0)) AS avg_items
            FROM sync_history
            WHERE started_at >= NOW() - make_interval(days => %s)
            """,
            (days,),
        )
        row = await cur.fetchone()
        total = row["total_syncs"]
        return {
            "total_syncs": total,
            "syncs_per_day": round(total / days, 2) if total > 0 else 0.0,
            "avg_items_synced": round(float(row["avg_items"]), 1) if row["avg_items"] is not None else 0.0,
            "failure_rate": round(row["total_failures"] / total, 4) if total > 0 else 0.0,
            "total_failures": row["total_failures"],
        }

    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            period_7d = await _query_period(cur, 7)
            period_30d = await _query_period(cur, 30)

    return {"period_7d": period_7d, "period_30d": period_30d}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_admin_queries.py::TestGetSyncActivity -v --no-header 2>&1 | tail -10`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add api/queries/admin_queries.py tests/api/test_admin_queries.py
git commit -m "feat(admin): add get_sync_activity query function (#137)"
```

______________________________________________________________________

## Task 4: Storage Query Functions (Neo4j, PostgreSQL, Redis)

**Files:**

- Modify: `api/queries/admin_queries.py`

- Modify: `tests/api/test_admin_queries.py`

- [ ] **Step 1: Write failing tests for storage functions**

Add to `tests/api/test_admin_queries.py`:

```python
class TestGetNeo4jStorage:
    """Tests for get_neo4j_storage query function."""

    @pytest.mark.asyncio
    async def test_basic_neo4j_storage(self):
        from api.queries.admin_queries import get_neo4j_storage

        # Mock driver session().run() returning apoc.meta.stats() result
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value={
            "labels": {"Artist": 245000, "Label": 5000},
            "relTypesCount": {"RELEASED_ON": 890000, "BY": 600000},
        })

        mock_session = AsyncMock()
        mock_session.run = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_driver = MagicMock()
        mock_driver.session = MagicMock(return_value=mock_session)

        result = await get_neo4j_storage(mock_driver)

        assert result["status"] == "ok"
        assert {"label": "Artist", "count": 245000} in result["nodes"]
        assert {"type": "RELEASED_ON", "count": 890000} in result["relationships"]

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

        pool = _mock_pool_with_rows(
            # table sizes
            [
                {"table_name": "users", "row_estimate": 150,
                 "total_size": "48 kB", "index_size": "32 kB"},
            ],
            # total DB size
            [{"total_size": "156 MB"}],
        )

        result = await get_postgres_storage(pool)

        assert result["status"] == "ok"
        assert result["tables"][0]["name"] == "users"
        assert result["total_size"] == "156 MB"


class TestGetRedisStorage:
    """Tests for get_redis_storage query function."""

    @pytest.mark.asyncio
    async def test_basic_redis_storage(self):
        from api.queries.admin_queries import get_redis_storage

        mock_redis = AsyncMock()
        mock_redis.info = AsyncMock(side_effect=lambda section: {
            "memory": {"used_memory_human": "12.5M", "used_memory_peak_human": "15.2M"},
            "keyspace": {"db0": {"keys": 342}},
        }.get(section, {}))
        mock_redis.scan = AsyncMock(return_value=(0, [b"cache:foo", b"cache:bar", b"revoked:jti:abc"]))

        result = await get_redis_storage(mock_redis)

        assert result["status"] == "ok"
        assert result["memory_used"] == "12.5M"
        assert result["total_keys"] == 342

    @pytest.mark.asyncio
    async def test_redis_none(self):
        from api.queries.admin_queries import get_redis_storage

        result = await get_redis_storage(None)

        assert result["status"] == "error"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_admin_queries.py::TestGetNeo4jStorage tests/api/test_admin_queries.py::TestGetPostgresStorage tests/api/test_admin_queries.py::TestGetRedisStorage -v --no-header 2>&1 | tail -10`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement storage query functions**

Add to `api/queries/admin_queries.py`:

```python
async def get_neo4j_storage(driver: Any) -> dict[str, Any]:
    """Fetch Neo4j node/relationship counts and store sizes.

    Uses CALL apoc.meta.stats() which is already available in the project
    (see dashboard/dashboard.py). Store sizes via JMX may not be available
    in all editions — returns null if unavailable.
    """
    if driver is None:
        return {"status": "error", "error": "Neo4j driver not configured"}

    async with driver.session() as session:
        result = await session.run("CALL apoc.meta.stats() YIELD labels, relTypesCount")
        record = await result.single()

        nodes = [
            {"label": label, "count": count}
            for label, count in sorted(record["labels"].items())
        ]
        relationships = [
            {"type": rel_type, "count": count}
            for rel_type, count in sorted(record["relTypesCount"].items())
        ]

    # Store sizes via JMX — best effort
    store_sizes = None
    try:
        async with driver.session() as session:
            result = await session.run(
                "CALL dbms.queryJmx('org.neo4j:instance=kernel#0,name=Store sizes') "
                "YIELD attributes RETURN attributes"
            )
            record = await result.single()
            if record and record.get("attributes"):
                attrs = record["attributes"]

                def _fmt(key: str) -> str:
                    val = attrs.get(key, {})
                    bytes_val = val.get("value", 0) if isinstance(val, dict) else 0
                    if bytes_val >= 1_073_741_824:
                        return f"{bytes_val / 1_073_741_824:.1f} GB"
                    if bytes_val >= 1_048_576:
                        return f"{bytes_val / 1_048_576:.0f} MB"
                    return f"{bytes_val / 1024:.0f} kB"

                store_sizes = {
                    "total": _fmt("TotalStoreSize"),
                    "nodes": _fmt("NodeStoreSize"),
                    "relationships": _fmt("RelationshipStoreSize"),
                    "strings": _fmt("StringStoreSize"),
                }
    except Exception:
        logger.debug("⚙️ Neo4j JMX store sizes not available — skipping")

    return {
        "status": "ok",
        "nodes": nodes,
        "relationships": relationships,
        "store_sizes": store_sizes,
    }


async def get_postgres_storage(pool: Any) -> dict[str, Any]:
    """Fetch PostgreSQL table sizes, row counts, and total DB size."""
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await execute_sql(
                cur,
                """
                SELECT
                    relname AS table_name,
                    n_live_tup AS row_estimate,
                    pg_size_pretty(pg_total_relation_size(relid)) AS total_size,
                    pg_size_pretty(pg_indexes_size(relid)) AS index_size
                FROM pg_stat_user_tables
                ORDER BY pg_total_relation_size(relid) DESC
                """,
            )
            tables = [
                {
                    "name": row["table_name"],
                    "row_count": row["row_estimate"],
                    "size": row["total_size"],
                    "index_size": row["index_size"],
                }
                for row in await cur.fetchall()
            ]

            await execute_sql(
                cur,
                "SELECT pg_size_pretty(pg_database_size(current_database())) AS total_size",
            )
            db_size_row = await cur.fetchone()
            total_size = db_size_row["total_size"] if db_size_row else "0 bytes"

    return {"status": "ok", "tables": tables, "total_size": total_size}


async def get_redis_storage(redis: Any) -> dict[str, Any]:
    """Fetch Redis memory usage and key counts by prefix.

    Uses SCAN (not KEYS *) to avoid blocking Redis.
    """
    if redis is None:
        return {"status": "error", "error": "Redis not configured"}

    memory_info = await redis.info("memory")
    keyspace_info = await redis.info("keyspace")

    # Total keys from keyspace info
    total_keys = 0
    for db_info in keyspace_info.values():
        if isinstance(db_info, dict) and "keys" in db_info:
            total_keys += db_info["keys"]

    # Scan keys and group by prefix (first segment before ':')
    prefix_counts: dict[str, int] = {}
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor=cursor, count=500)
        for key in keys:
            key_str = key if isinstance(key, str) else key.decode("utf-8", errors="replace")
            prefix = key_str.split(":")[0] + ":" if ":" in key_str else key_str
            prefix_counts[prefix] = prefix_counts.get(prefix, 0) + 1
        if cursor == 0:
            break

    keys_by_prefix = [
        {"prefix": prefix, "count": count}
        for prefix, count in sorted(prefix_counts.items(), key=lambda x: -x[1])
    ]

    return {
        "status": "ok",
        "memory_used": memory_info.get("used_memory_human", ""),
        "memory_peak": memory_info.get("used_memory_peak_human", ""),
        "total_keys": total_keys,
        "keys_by_prefix": keys_by_prefix,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_admin_queries.py -v --no-header 2>&1 | tail -20`
Expected: All PASS

- [ ] **Step 5: Run linting**

Run: `uv run ruff check api/queries/admin_queries.py tests/api/test_admin_queries.py`
Fix any issues.

- [ ] **Step 6: Commit**

```bash
git add api/queries/admin_queries.py tests/api/test_admin_queries.py
git commit -m "feat(admin): add storage query functions for Neo4j, PostgreSQL, Redis (#137)"
```

______________________________________________________________________

## Task 5: Admin Router Endpoints

**Files:**

- Modify: `api/routers/admin.py` — add 3 endpoints + extend `configure()`

- Modify: `api/api.py` — pass `_neo4j` to admin configure

- Modify: `tests/api/test_admin_endpoints.py` — add endpoint tests

- [ ] **Step 1: Write failing endpoint tests**

Add to `tests/api/test_admin_endpoints.py`:

```python
# ---------------------------------------------------------------------------
# Phase 2 endpoint tests — User Stats, Sync Activity, Storage
# ---------------------------------------------------------------------------


class TestUserStatsEndpoint:
    """Tests for GET /api/admin/users/stats."""

    def test_returns_200_with_admin_token(self, test_client: TestClient):
        with patch("api.routers.admin.get_user_stats", new_callable=AsyncMock) as mock_fn:
            mock_fn.return_value = {
                "total_users": 10, "active_7d": 5, "active_30d": 8,
                "oauth_connection_rate": 0.5,
                "registrations": {"daily": [], "weekly": [], "monthly": []},
            }
            resp = test_client.get("/api/admin/users/stats", headers=_admin_auth_headers())
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_users"] == 10

    def test_rejects_without_token(self, test_client: TestClient):
        resp = test_client.get("/api/admin/users/stats")
        assert resp.status_code == 401

    def test_rejects_user_token(self, test_client: TestClient, valid_token: str):
        resp = test_client.get(
            "/api/admin/users/stats",
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert resp.status_code in (401, 403)


class TestSyncActivityEndpoint:
    """Tests for GET /api/admin/users/sync-activity."""

    def test_returns_200_with_admin_token(self, test_client: TestClient):
        with patch("api.routers.admin.get_sync_activity", new_callable=AsyncMock) as mock_fn:
            period = {
                "total_syncs": 10, "syncs_per_day": 1.4,
                "avg_items_synced": 50.0, "failure_rate": 0.1, "total_failures": 1,
            }
            mock_fn.return_value = {"period_7d": period, "period_30d": period}
            resp = test_client.get("/api/admin/users/sync-activity", headers=_admin_auth_headers())
            assert resp.status_code == 200

    def test_rejects_without_token(self, test_client: TestClient):
        resp = test_client.get("/api/admin/users/sync-activity")
        assert resp.status_code == 401


class TestStorageEndpoint:
    """Tests for GET /api/admin/storage."""

    def test_returns_200_with_all_sources(self, test_client: TestClient):
        with (
            patch("api.routers.admin.get_neo4j_storage", new_callable=AsyncMock) as mock_neo4j,
            patch("api.routers.admin.get_postgres_storage", new_callable=AsyncMock) as mock_pg,
            patch("api.routers.admin.get_redis_storage", new_callable=AsyncMock) as mock_redis,
        ):
            mock_neo4j.return_value = {"status": "ok", "nodes": [], "relationships": [], "store_sizes": None}
            mock_pg.return_value = {"status": "ok", "tables": [], "total_size": "10 MB"}
            mock_redis.return_value = {"status": "ok", "memory_used": "1M", "memory_peak": "2M", "total_keys": 5, "keys_by_prefix": []}
            resp = test_client.get("/api/admin/storage", headers=_admin_auth_headers())
            assert resp.status_code == 200
            data = resp.json()
            assert data["neo4j"]["status"] == "ok"
            assert data["postgresql"]["status"] == "ok"
            assert data["redis"]["status"] == "ok"

    def test_partial_failure(self, test_client: TestClient):
        with (
            patch("api.routers.admin.get_neo4j_storage", new_callable=AsyncMock) as mock_neo4j,
            patch("api.routers.admin.get_postgres_storage", new_callable=AsyncMock) as mock_pg,
            patch("api.routers.admin.get_redis_storage", new_callable=AsyncMock) as mock_redis,
        ):
            mock_neo4j.side_effect = Exception("connection refused")
            mock_pg.return_value = {"status": "ok", "tables": [], "total_size": "10 MB"}
            mock_redis.return_value = {"status": "ok", "memory_used": "1M", "memory_peak": "2M", "total_keys": 0, "keys_by_prefix": []}
            resp = test_client.get("/api/admin/storage", headers=_admin_auth_headers())
            assert resp.status_code == 200
            data = resp.json()
            assert data["neo4j"]["status"] == "error"
            assert data["postgresql"]["status"] == "ok"

    def test_rejects_without_token(self, test_client: TestClient):
        resp = test_client.get("/api/admin/storage")
        assert resp.status_code == 401
```

Note: The test file already imports `patch` from `unittest.mock` and defines `_admin_auth_headers()` locally. The fixture is `test_client` (from `tests/api/conftest.py`), and `valid_token` provides a user JWT for rejection tests. The existing test file defines its own `_make_admin_jwt()` helper — reuse that for admin auth headers.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_admin_endpoints.py::TestUserStatsEndpoint -v --no-header 2>&1 | tail -5`
Expected: FAIL (endpoint doesn't exist yet)

- [ ] **Step 3: Extend admin router `configure()` and add endpoints**

In `api/routers/admin.py`, modify the `configure()` function and add imports + endpoints:

Add to imports at top:

```python
from api.queries.admin_queries import (
    get_neo4j_storage,
    get_postgres_storage,
    get_redis_storage,
    get_sync_activity,
    get_user_stats,
)
```

Update module-level state and configure:

```python
# Module-level state (set via configure())
_pool: Any = None
_redis: Any = None
_config: ApiConfig | None = None
_neo4j_driver: Any = None


def configure(pool: Any, redis: Any, config: ApiConfig, neo4j_driver: Any = None) -> None:
    """Initialise module state — called once during app lifespan startup."""
    global _pool, _redis, _config, _neo4j_driver
    _pool = pool
    _redis = redis
    _config = config
    _neo4j_driver = neo4j_driver
```

Add new endpoints at the end of the file (before the background task helpers):

```python
# ---------------------------------------------------------------------------
# Phase 2 — User Activity & Storage endpoints
# ---------------------------------------------------------------------------


@router.get("/api/admin/users/stats")
async def admin_user_stats(
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
) -> JSONResponse:
    """User registration stats, active users, and OAuth connection rate."""
    if _pool is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")
    data = await get_user_stats(_pool)
    return JSONResponse(content=data)


@router.get("/api/admin/users/sync-activity")
async def admin_sync_activity(
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
) -> JSONResponse:
    """Sync activity stats for 7d and 30d windows."""
    if _pool is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")
    data = await get_sync_activity(_pool)
    return JSONResponse(content=data)


@router.get("/api/admin/storage")
async def admin_storage(
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
) -> JSONResponse:
    """Storage utilization for Neo4j, PostgreSQL, and Redis."""
    results = await asyncio.gather(
        get_neo4j_storage(_neo4j_driver),
        get_postgres_storage(_pool),
        get_redis_storage(_redis),
        return_exceptions=True,
    )

    def _wrap(result: Any, name: str) -> dict[str, Any]:
        if isinstance(result, BaseException):
            logger.warning("⚠️ Storage query failed", source=name, error=str(result))
            return {"status": "error", "error": str(result)}
        return result

    return JSONResponse(content={
        "neo4j": _wrap(results[0], "neo4j"),
        "postgresql": _wrap(results[1], "postgresql"),
        "redis": _wrap(results[2], "redis"),
    })
```

- [ ] **Step 4: Update conftest to pass neo4j_driver to admin configure**

In `tests/api/conftest.py`, find the line that calls `_admin_router.configure(mock_pool, mock_redis, test_api_config)` and add the neo4j driver:

```python
_admin_router.configure(mock_pool, mock_redis, test_api_config, neo4j_driver=mock_neo4j)
```

Where `mock_neo4j` is the existing mock Neo4j driver fixture already defined in the conftest. Check the conftest to find the correct variable name.

- [ ] **Step 5: Update `api/api.py` to pass Neo4j driver**

In `api/api.py`, change line 237 from:

```python
_admin_router.configure(_pool, _redis, _config)
```

to:

```python
_admin_router.configure(_pool, _redis, _config, neo4j_driver=_neo4j)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_admin_endpoints.py::TestUserStatsEndpoint tests/api/test_admin_endpoints.py::TestSyncActivityEndpoint tests/api/test_admin_endpoints.py::TestStorageEndpoint -v --no-header 2>&1 | tail -20`
Expected: All PASS

- [ ] **Step 7: Run full admin test suite**

Run: `uv run pytest tests/api/test_admin_endpoints.py tests/api/test_admin_auth.py -v --no-header 2>&1 | tail -20`
Expected: All PASS (no regressions)

- [ ] **Step 8: Commit**

```bash
git add api/routers/admin.py api/api.py tests/api/conftest.py tests/api/test_admin_endpoints.py
git commit -m "feat(admin): add user stats, sync activity, and storage endpoints (#137)"
```

______________________________________________________________________

## Task 6: Dashboard Proxy Routes

**Files:**

- Modify: `dashboard/admin_proxy.py`

- Modify: `tests/dashboard/test_admin_proxy.py`

- [ ] **Step 1: Write failing proxy tests**

Add to `tests/dashboard/test_admin_proxy.py`:

```python
# ---------------------------------------------------------------------------
# Phase 2 proxy route tests
# ---------------------------------------------------------------------------


class TestUserStatsProxy:
    """Tests for GET /admin/api/users/stats proxy."""

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_forwards_get_request(self, mock_cls: AsyncMock, proxy_client: TestClient) -> None:
        mock_response = MagicMock()
        mock_response.content = b'{"total_users": 10}'
        mock_response.status_code = 200
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        mock_cls.return_value = mock_instance
        resp = proxy_client.get("/admin/api/users/stats", headers={"Authorization": "Bearer tok"})
        assert resp.status_code == 200


class TestSyncActivityProxy:
    """Tests for GET /admin/api/users/sync-activity proxy."""

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_forwards_get_request(self, mock_cls: AsyncMock, proxy_client: TestClient) -> None:
        mock_response = MagicMock()
        mock_response.content = b'{"period_7d": {}}'
        mock_response.status_code = 200
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        mock_cls.return_value = mock_instance
        resp = proxy_client.get("/admin/api/users/sync-activity", headers={"Authorization": "Bearer tok"})
        assert resp.status_code == 200


class TestStorageProxy:
    """Tests for GET /admin/api/storage proxy."""

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_forwards_get_request(self, mock_cls: AsyncMock, proxy_client: TestClient) -> None:
        mock_response = MagicMock()
        mock_response.content = b'{"neo4j": {}, "postgresql": {}, "redis": {}}'
        mock_response.status_code = 200
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        mock_cls.return_value = mock_instance
        resp = proxy_client.get("/admin/api/storage", headers={"Authorization": "Bearer tok"})
        assert resp.status_code == 200
```

Note: The existing proxy tests use `proxy_client` fixture and `@patch("dashboard.admin_proxy.httpx.AsyncClient")`. Check the existing test file for the exact fixture and mock patterns — adapt if they differ.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/dashboard/test_admin_proxy.py::TestUserStatsProxy -v --no-header 2>&1 | tail -5`
Expected: FAIL (404 — routes don't exist)

- [ ] **Step 3: Add proxy routes**

Add to `dashboard/admin_proxy.py` before the existing `@router.post("/admin/api/dlq/purge/{queue}")`:

```python
# ---------------------------------------------------------------------------
# Phase 2 — User Activity & Storage proxy routes
# ---------------------------------------------------------------------------


@router.get("/admin/api/users/stats")
async def proxy_user_stats(request: Request) -> Response:
    """Proxy user stats requests to the API service."""
    url = _build_url("/api/admin/users/stats")
    headers = _auth_headers(request)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
    except (httpx.ConnectError, httpx.RequestError) as exc:
        logger.error("❌ API service unreachable", url=url, error=str(exc))
        return _unavailable_response()
    return _ok_response(resp)


@router.get("/admin/api/users/sync-activity")
async def proxy_sync_activity(request: Request) -> Response:
    """Proxy sync activity requests to the API service."""
    url = _build_url("/api/admin/users/sync-activity")
    headers = _auth_headers(request)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
    except (httpx.ConnectError, httpx.RequestError) as exc:
        logger.error("❌ API service unreachable", url=url, error=str(exc))
        return _unavailable_response()
    return _ok_response(resp)


@router.get("/admin/api/storage")
async def proxy_storage(request: Request) -> Response:
    """Proxy storage utilization requests to the API service."""
    url = _build_url("/api/admin/storage")
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

Run: `uv run pytest tests/dashboard/test_admin_proxy.py -v --no-header 2>&1 | tail -15`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add dashboard/admin_proxy.py tests/dashboard/test_admin_proxy.py
git commit -m "feat(admin): add dashboard proxy routes for Phase 2 endpoints (#137)"
```

______________________________________________________________________

## Task 7: Dashboard Frontend — User Activity Panel

**Files:**

- Modify: `dashboard/static/admin.html`

- Modify: `dashboard/static/admin.js`

- [ ] **Step 1: Read existing admin.html and admin.js**

Read both files from `origin/main` to understand the current structure, CSS patterns, and JavaScript conventions used in Phase 1.

```bash
git show origin/main:dashboard/static/admin.html | wc -l
git show origin/main:dashboard/static/admin.js | wc -l
```

- [ ] **Step 2: Add User Activity panel HTML**

Add a new tab button and panel section to `admin.html`, following the existing tab pattern. The panel should contain:

- A "User Activity" tab button alongside existing tabs
- Summary cards section (Total Users, Active 7d, Active 30d, OAuth Rate)
- Sync activity cards section (Syncs/Day, Avg Items, Failure Rate)
- Registration table section (daily last 30 days)
- Refresh button + auto-refresh indicator

Follow the existing CSS class naming and card layout pattern from Phase 1.

- [ ] **Step 3: Add User Activity JS logic**

Add to `admin.js`:

- `fetchUserStats()` — calls `/admin/api/users/stats`, populates cards and registration table

- `fetchSyncActivity()` — calls `/admin/api/users/sync-activity`, populates sync cards

- Wire into the auto-refresh timer (60s interval)

- Wire into tab switching logic

- Handle errors gracefully (show inline warning, don't break the page)

- [ ] **Step 4: Manual verification**

Open `http://localhost:8003/admin.html` in a browser (if services are running) or verify the HTML structure is correct by reading the file.

- [ ] **Step 5: Commit**

```bash
git add dashboard/static/admin.html dashboard/static/admin.js
git commit -m "feat(admin): add User Activity panel to dashboard frontend (#137)"
```

______________________________________________________________________

## Task 8: Dashboard Frontend — Storage Utilization Panel

**Files:**

- Modify: `dashboard/static/admin.html`

- Modify: `dashboard/static/admin.js`

- [ ] **Step 1: Add Storage panel HTML**

Add to `admin.html`:

- A "Storage" tab button

- Three collapsible sections: Neo4j, PostgreSQL, Redis

- Each section has a status badge and a data table

- Summary cards for total DB size, memory used, etc.

- [ ] **Step 2: Add Storage JS logic**

Add to `admin.js`:

- `fetchStorage()` — calls `/admin/api/storage`, populates all three sections

- Status badge rendering (green "ok" / red "error")

- Collapsible section toggle

- Error section display (when a source returns `status: "error"`)

- Wire into auto-refresh and tab switching

- [ ] **Step 3: Manual verification**

Verify HTML structure is correct by reading the file.

- [ ] **Step 4: Commit**

```bash
git add dashboard/static/admin.html dashboard/static/admin.js
git commit -m "feat(admin): add Storage Utilization panel to dashboard frontend (#137)"
```

______________________________________________________________________

## Task 9: Final Validation

**Files:** All modified files

- [ ] **Step 1: Run full test suite**

```bash
uv run pytest tests/api/test_admin_endpoints.py tests/api/test_admin_auth.py tests/api/test_admin_queries.py tests/api/test_api_models.py tests/dashboard/test_admin_proxy.py -v --no-header 2>&1 | tail -30
```

Expected: All PASS

- [ ] **Step 2: Run linting and type checking**

```bash
uv run ruff check api/queries/admin_queries.py api/routers/admin.py api/models.py api/api.py dashboard/admin_proxy.py
uv run mypy api/queries/admin_queries.py api/routers/admin.py api/models.py
```

Fix any issues.

- [ ] **Step 3: Run broader test suite to check for regressions**

```bash
just test
```

Expected: All PASS, no regressions

- [ ] **Step 4: Verify test coverage**

```bash
uv run pytest tests/api/test_admin_queries.py tests/api/test_admin_endpoints.py --cov=api.queries.admin_queries --cov=api.routers.admin --cov-report=term-missing --no-header 2>&1 | tail -20
```

Target: >80% coverage on new code.

- [ ] **Step 5: Final commit (if any linting/type fixes needed)**

```bash
git add -u
git commit -m "fix(admin): address linting and type-checking issues (#137)"
```
