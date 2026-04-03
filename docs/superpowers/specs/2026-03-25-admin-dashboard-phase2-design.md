# Admin Dashboard Phase 2 — User Activity and Storage Utilization

**Issue:** #137
**Date:** 2026-03-25
**Depends on:** Phase 1 (#104, #136) — merged on `origin/main` (commit 67ff31c). Local `main` must be rebased/merged before starting work.

## Summary

Add three new admin API endpoints for user activity stats, sync activity stats, and storage utilization. Extend the admin dashboard frontend with two new panels to display this data. All endpoints protected by existing `require_admin` dependency.

## Decisions

- **Response style**: Summary numbers + time-series data (charts-ready)
- **Storage endpoint**: Single endpoint querying all three databases concurrently, partial results on failure
- **Sync activity windows**: Fixed 7d and 30d periods (matching active user windows)
- **Scope**: Full end-to-end — API endpoints, dashboard proxy routes, and frontend panels
- **Architecture**: Thin router endpoints delegating to a dedicated query module (`api/queries/admin_queries.py`)

## API Endpoints

### `GET /api/admin/users/stats`

User registration summary with time-series, active user counts, and OAuth connection rate.

```json
{
  "total_users": 150,
  "active_7d": 42,
  "active_30d": 89,
  "oauth_connection_rate": 0.63,
  "registrations": {
    "daily": [{"date": "2026-03-18", "count": 5}],
    "weekly": [{"week_start": "2026-03-17", "count": 12}],
    "monthly": [{"month": "2026-03", "count": 34}]
  }
}
```

- Queries `users` and `oauth_tokens` tables
- Time-series uses `date_trunc` for grouping
- Daily: last 30 days, weekly: last 12 weeks, monthly: last 12 months
- `oauth_connection_rate`: users with a Discogs OAuth token (`WHERE provider = 'discogs'`) / total users (0.0 when no users, guarded with `NULLIF`)
- **"Active" definition**: Users with at least one `sync_history` row where `started_at` falls within the window. The `users` table has no `last_login_at` column, so sync activity is the best available proxy for user engagement.

### `GET /api/admin/users/sync-activity`

Sync stats for fixed 7d and 30d windows.

```json
{
  "period_7d": {
    "total_syncs": 28,
    "syncs_per_day": 4.0,
    "avg_items_synced": 142.5,
    "failure_rate": 0.07,
    "total_failures": 2
  },
  "period_30d": {
    "total_syncs": 95,
    "syncs_per_day": 3.17,
    "avg_items_synced": 138.2,
    "failure_rate": 0.05,
    "total_failures": 5
  }
}
```

- Queries `sync_history` table with `WHERE started_at >= NOW() - INTERVAL 'N days'`
- **Failure detection**: `WHERE status = 'failed'` (the `status` column is VARCHAR(50), valid values: `pending`, `running`, `completed`, `failed`)
- `failure_rate` and `syncs_per_day` guarded against division by zero with `NULLIF`/`COALESCE`
- `avg_items_synced` computed from `items_synced` column (nullable — `COALESCE` to 0)

### `GET /api/admin/storage`

Combined storage utilization for Neo4j, PostgreSQL, and Redis. Queried concurrently via `asyncio.gather(return_exceptions=True)`.

```json
{
  "neo4j": {
    "status": "ok",
    "nodes": [{"label": "Artist", "count": 245000}],
    "relationships": [{"type": "RELEASED_ON", "count": 890000}],
    "store_sizes": {
      "total": "2.1 GB",
      "nodes": "800 MB",
      "relationships": "1.1 GB",
      "strings": "200 MB"
    }
  },
  "postgresql": {
    "status": "ok",
    "tables": [{"name": "users", "row_count": 150, "size": "48 kB", "index_size": "32 kB"}],
    "total_size": "156 MB"
  },
  "redis": {
    "status": "ok",
    "memory_used": "12.5 MB",
    "memory_peak": "15.2 MB",
    "total_keys": 342,
    "keys_by_prefix": [{"prefix": "cache:", "count": 280}, {"prefix": "revoked:", "count": 62}]
  }
}
```

On source failure, that source returns `{"status": "error", "error": "connection failed"}` — other sources still return normally.

**Query details:**

- Neo4j: `CALL apoc.meta.stats()` for node/relationship counts by label/type (already used in `dashboard/dashboard.py`). Store sizes (bytes) require JMX queries (`CALL dbms.queryJmx('org.neo4j:*')`) which may not be available in all editions — `store_sizes` returns `null` if unavailable rather than failing.
- PostgreSQL: `pg_total_relation_size`, `pg_indexes_size`, `pg_stat_user_tables` for row estimates
- Redis: `INFO memory`, `INFO keyspace`, `SCAN` with prefix grouping (not `KEYS *`)

## File Structure

### Files to create

- `api/queries/admin_queries.py` — All query functions for the 3 endpoints
- `tests/api/test_admin_queries.py` — Unit tests for query functions

### Files to modify

- `api/routers/admin.py` — Add 3 thin endpoint functions
- `api/models.py` — Pydantic response models for 3 endpoints
- `api/api.py` — Pass Neo4j driver to admin router `configure()` call
- `dashboard/admin_proxy.py` — Add 3 proxy routes
- `dashboard/static/admin.html` — Add user activity and storage panels
- `dashboard/static/admin.js` — Fetch + render logic for new panels
- `tests/api/test_admin.py` — Endpoint integration tests
- `tests/dashboard/test_admin_proxy.py` — Proxy route tests

## Query Module Design

`api/queries/admin_queries.py` contains all data-fetching logic:

```python
# PostgreSQL user/sync queries
async def get_user_stats(pool) -> dict
async def get_sync_activity(pool) -> dict

# Neo4j system catalog queries
async def get_neo4j_storage(driver) -> dict

# PostgreSQL system catalog queries
async def get_postgres_storage(pool) -> dict

# Redis info queries
async def get_redis_storage(redis) -> dict
```

Each function receives only its connection dependency. The storage endpoint in the router calls the three storage functions via `asyncio.gather(return_exceptions=True)`.

## Router Wiring

The admin router's `configure()` already receives `pool`, `redis`, and `config`. The new signature will be:

```python
def configure(pool: Any, redis: Any, config: Any, neo4j_driver: Any = None) -> None:
```

The `neo4j_driver` parameter is optional (defaulting to `None`) for backward compatibility. When `None`, the storage endpoint returns `{"status": "error", "error": "Neo4j driver not configured"}` for the Neo4j section. This requires a small change to `api/api.py` lifespan to pass the driver.

## Out of Scope

- **Perftest config**: Admin endpoints are low-traffic, internal-only — no perf testing needed.
- **Rate limiting**: Existing `require_admin` auth is sufficient; admin endpoints are not public-facing. Can be added later if needed.

## Dashboard Frontend

### User Activity Panel

- **Summary cards row**: Total Users, Active (7d), Active (30d), OAuth Rate (%)
- **Sync activity cards row**: Syncs/Day (7d), Avg Items Synced (7d), Failure Rate (7d) — 30d values shown as secondary text
- **Registration table**: Daily registrations for last 30 days (plain HTML table, no charting library)

### Storage Utilization Panel

- **Three collapsible sections**: Neo4j, PostgreSQL, Redis
- **Status badge**: Green "ok" / red "error" per source
- **Neo4j**: Tables for node counts by label, relationship counts by type, store sizes
- **PostgreSQL**: Table of table names with row count, data size, index size; total DB size summary
- **Redis**: Memory used/peak, total keys, keys-by-prefix table

### Behavior

- Auto-refresh every 60 seconds (matching explore frontend Insights tab pattern)
- Manual refresh button
- Inline warning on fetch failure or source error (doesn't break the page)

### Dashboard Proxy Routes

```
GET /admin/api/users/stats         → GET /api/admin/users/stats
GET /admin/api/users/sync-activity → GET /api/admin/users/sync-activity
GET /admin/api/storage             → GET /api/admin/storage
```

Same proxy pattern as Phase 1 — forward auth header, re-serialize JSON, validate path segments.

## Error Handling

- **Query timeouts**: 5s for SQL, 10s for Neo4j catalog queries, 5s for Redis
- **Division by zero**: Guarded in SQL with `NULLIF`/`COALESCE`
- **Storage partial failure**: `asyncio.gather(return_exceptions=True)` — each source independently wrapped
- **Empty data**: Time-series returns empty arrays, counts return 0 (no 404s)
- **Redis key scan**: `SCAN` with count hint (not `KEYS *`) to avoid blocking

## Testing

### `tests/api/test_admin_queries.py`

- Mock database connections (pool, driver, redis)
- Test each query function returns expected shape
- Test edge cases: empty tables, zero users, no sync history, no OAuth tokens
- Test division-by-zero guarding (oauth_connection_rate, failure_rate, syncs_per_day)

### `tests/api/test_admin.py` (extend)

- All 3 endpoints return 200 with valid admin token
- All 3 endpoints return 401/403 without admin or with user token
- Storage endpoint returns partial results when one source fails
- Response shapes match Pydantic models

### `tests/dashboard/test_admin_proxy.py` (extend)

- 3 new proxy routes forward correctly
- Auth header passed through
