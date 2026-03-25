# Admin Dashboard Phase 3 — Queue Health Trends and System Health

**Issue:** #138
**Date:** 2026-03-25
**Depends on:** Phase 1 (#104, #136) — merged. Phase 2 (#137, #199) — merged.

## Summary

Add observability panels for queue health trends over time and system health metrics. Two new admin API endpoints return time-series data from PostgreSQL. A background collector task in the API service snapshots queue and health metrics every 5 minutes. A lightweight API middleware captures per-endpoint response times. The admin dashboard gains two new tabs with Chart.js trend charts and SVG sparkline summary cards.

## Decisions

- **Collector location**: API service — already has PostgreSQL, Redis, RabbitMQ, and Neo4j connections. Dashboard stays read-only.
- **Time ranges**: Flexible `?range=` parameter (1h, 6h, 24h, 7d, 30d, 90d, 365d) with auto-selected granularity.
- **Visualization**: Chart.js for main trend charts, inline SVG sparklines for summary cards.
- **Retention**: Configurable via `METRICS_RETENTION_DAYS` env var, default 366 days. Pruned every collection cycle.
- **Health metrics**: Service health endpoint polling + API endpoint response time/error middleware.
- **Architecture**: Thin router endpoints delegating to `api/queries/metrics_queries.py`, collector logic in `api/metrics_collector.py`.

## Database Schema

Two new PostgreSQL tables in `schema-init/postgres_schema.py`.

### `queue_metrics`

| Column | Type | Notes |
|--------|------|-------|
| id | BIGSERIAL PK | |
| recorded_at | TIMESTAMPTZ NOT NULL | indexed |
| queue_name | VARCHAR(100) NOT NULL | e.g. `graphinator-artists` |
| messages_ready | INTEGER | |
| messages_unacknowledged | INTEGER | |
| consumers | INTEGER | |
| publish_rate | REAL | msgs/sec from RabbitMQ API |
| ack_rate | REAL | msgs/sec from RabbitMQ API |

Index: `idx_queue_metrics_recorded_at_queue (recorded_at, queue_name)`.

### `service_health_metrics`

| Column | Type | Notes |
|--------|------|-------|
| id | BIGSERIAL PK | |
| recorded_at | TIMESTAMPTZ NOT NULL | indexed |
| service_name | VARCHAR(50) NOT NULL | e.g. `extractor`, `api` |
| status | VARCHAR(20) | healthy/unhealthy/unknown |
| response_time_ms | REAL | health endpoint latency |
| endpoint_stats | JSONB | API-only: per-endpoint p50/p95/p99, error counts |

Index: `idx_service_health_metrics_recorded_at_service (recorded_at, service_name)`.

The `endpoint_stats` JSONB stores per-endpoint metrics collected by the API middleware:

```json
{
  "/api/search": {"count": 42, "p50": 85, "p95": 210, "p99": 480, "errors": 1},
  "/api/explore/artist/:id": {"count": 15, "p50": 120, "p95": 350, "p99": 720, "errors": 0}
}
```

Endpoint paths are normalized — UUID and integer path segments replaced with `:id`.

## Background Metric Collector

New module `api/metrics_collector.py`. An `asyncio.Task` started in the API lifespan, running every 5 minutes.

### Collection cycle

1. **Queue metrics** — HTTP call to RabbitMQ Management API (`/api/queues`), same approach as `dashboard/dashboard.py:get_queue_info()`. Filter for `discogsography` queues, extract messages_ready, messages_unacknowledged, consumers, publish_rate, ack_rate.
2. **Service health** — Concurrent HTTP calls to each service's `/health` endpoint (extractor:8000, graphinator:8001, tableinator:8002, dashboard:8003, insights:8008). Record status + response latency.
3. **API endpoint stats** — Flush the in-memory accumulator from the metrics middleware, compute percentiles, reset counters.
4. **Write to PostgreSQL** — Single transaction: batch INSERT queue rows + health rows.
5. **Prune old data** — `DELETE FROM queue_metrics WHERE recorded_at < NOW() - INTERVAL '{retention} days'`, same for `service_health_metrics`. Runs every cycle.

### Resilience

- Each collection step is independently try/except'd — RabbitMQ being down doesn't prevent health checks from being recorded.
- Uses `asyncio.sleep(300)` between cycles. Acceptable drift for 5-min snapshots.
- Logs warnings on collection failures using emojis from `docs/emoji-guide.md`. Does not crash the API service.

## API Metrics Middleware

A lightweight Starlette middleware on the API app that records per-request timing.

- Captures `(normalized_path, status_code, duration_ms)` into an in-memory list.
- **Buffer cap**: 10,000 entries between flushes to prevent memory growth. Oldest entries dropped when cap reached.
- **Path normalization**: Regex replaces UUID and integer path segments with `:id` (e.g., `/api/explore/artist/12345` → `/api/explore/artist/:id`).
- **Excluded paths**: `/health`, `/metrics`, `/api/admin/*` — admin traffic is low-volume internal, not useful for trends.
- The collector reads and resets this buffer every 5 minutes, computes p50/p95/p99 and error count per normalized endpoint.

## API Endpoints

Both protected by `require_admin` dependency.

### `GET /api/admin/queues/history?range=24h`

Queue depth time-series data.

**Query parameter:** `range` — one of `1h`, `6h`, `24h`, `7d`, `30d`, `90d`, `365d`. Default: `24h`.

**Auto-granularity mapping:**

| Range | Granularity | Max datapoints per queue |
|-------|-------------|--------------------------|
| 1h | 5 min (raw) | 12 |
| 6h | 5 min (raw) | 72 |
| 24h | 15 min (avg) | 96 |
| 7d | 1 hour (avg) | 168 |
| 30d | 6 hour (avg) | 120 |
| 90d | 1 day (avg) | 90 |
| 365d | 1 day (avg) | 365 |

Aggregation uses `date_trunc` + `AVG` in SQL for ranges beyond 6h.

**Response:**

```json
{
  "range": "24h",
  "granularity": "15min",
  "queues": {
    "graphinator-artists": {
      "current": {"messages_ready": 42, "consumers": 1, "publish_rate": 12.3, "ack_rate": 11.8},
      "history": [
        {"timestamp": "2026-03-25T10:00:00Z", "messages_ready": 38, "messages_unacknowledged": 2, "publish_rate": 11.5, "ack_rate": 10.9}
      ]
    }
  },
  "dlq_summary": {
    "graphinator-artists-dlq": {"current": 3, "history": [{"timestamp": "...", "messages_ready": 2}]}
  }
}
```

DLQ queues (names ending in `-dlq`) are separated into `dlq_summary`.

### `GET /api/admin/health/history?range=24h`

Service health and API endpoint metrics over time.

**Same `range` parameter and granularity mapping** as queues endpoint.

**Response:**

```json
{
  "range": "24h",
  "granularity": "15min",
  "services": {
    "extractor": {
      "current_status": "healthy",
      "uptime_pct": 99.8,
      "history": [
        {"timestamp": "2026-03-25T10:00:00Z", "status": "healthy", "response_time_ms": 12.5}
      ]
    }
  },
  "api_endpoints": {
    "/api/search": {
      "latest": {"p50": 85, "p95": 210, "p99": 480, "count": 42, "error_rate": 0.02},
      "history": [
        {"timestamp": "2026-03-25T10:00:00Z", "p50": 90, "p95": 200, "p99": 450, "count": 38, "error_rate": 0.01}
      ]
    }
  }
}
```

`uptime_pct` computed from ratio of `healthy` snapshots to total snapshots in the range.

### Query Module

`api/queries/metrics_queries.py` — all data-fetching logic:

```python
async def get_queue_history(pool, range_value: str) -> dict
async def get_health_history(pool, range_value: str) -> dict
```

Each function handles granularity selection and `date_trunc` aggregation internally. The router endpoints are thin wrappers.

### Router Wiring

The admin router's `configure()` gains a `rabbitmq_url` parameter for the collector's RabbitMQ Management API access. The `api/api.py` lifespan starts the collector task and adds the metrics middleware.

## Dashboard Frontend

### New Tabs

Two new tabs added to the existing tabbed interface in `admin.html`: **Queue Trends** and **System Health**.

### Chart.js

Loaded from CDN (`<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>`) in `admin.html`, matching the existing pattern of CDN-loaded Tailwind CSS.

### Queue Trends Panel

- **Range selector bar**: 1h, 6h, 24h, 7d, 30d, 90d buttons. Shared component (reused in System Health).
- **5 summary tiles** with inline SVG sparklines:
  - Total Queue Depth (with delta from period start)
  - DLQ Messages (with count delta)
  - Avg Publish Rate (/s)
  - Avg Ack Rate (/s)
  - Active Consumers
- **Chart.js line chart**: Queue depth over time. Legend toggles per queue. Tooltips on hover.
- **DLQ section**: Per-DLQ mini sparkline charts with current count.

### System Health Panel

- **Range selector bar**: Same component as Queue Trends.
- **5 service status cards**: Extractor, Graphinator, Tableinator, Dashboard, Insights. Color-coded left border (green=healthy, yellow=degraded, red=unhealthy). Shows uptime %, latency.
- **Chart.js line chart**: API response times (p50/p95/p99) over time.
- **Top endpoints table**: Sorted by request count. Columns: endpoint, requests, p50, p95, p99, error %. Error rate color-coded (green < 1%, yellow 1-5%, red > 5%).

### Behavior

- Auto-refresh every 60 seconds (matching Phase 2 pattern).
- Manual refresh button.
- Range selector state persisted in `localStorage` per tab.
- Inline warning on fetch failure (doesn't break the page).

### Dashboard Proxy Routes

```
GET /admin/api/queues/history  → GET /api/admin/queues/history
GET /admin/api/health/history  → GET /api/admin/health/history
```

Same proxy pattern as Phase 1/2 — forward auth header, re-serialize JSON, validate path segments. Query parameters forwarded as-is.

## Configuration

| Env Var | Default | Description |
|---------|---------|-------------|
| `METRICS_RETENTION_DAYS` | 366 | Days to retain metric snapshots |
| `METRICS_COLLECTION_INTERVAL` | 300 | Seconds between collection cycles |

## Error Handling

- **Collector failures**: Each step independently wrapped — partial collection still persisted.
- **Query timeouts**: 5s for SQL queries.
- **Empty data**: History arrays return empty, counts return 0. No 404s.
- **Invalid range parameter**: 422 with list of valid values.
- **Middleware buffer overflow**: Oldest entries dropped when 10K cap reached.

## File Structure

### Files to create

| File | Purpose |
|------|---------|
| `api/metrics_collector.py` | Background task: queue/health snapshot collection, retention pruning, metrics middleware |
| `api/queries/metrics_queries.py` | Query functions for history endpoints (time-series aggregation) |
| `tests/api/test_metrics_collector.py` | Unit tests for collector, middleware, path normalization |
| `tests/api/test_metrics_queries.py` | Unit tests for query functions |

### Files to modify

| File | Change |
|------|--------|
| `api/routers/admin.py` | Add 2 endpoints (`queues/history`, `health/history`) |
| `api/models.py` | Pydantic response models for both endpoints |
| `api/api.py` | Start collector task in lifespan, add metrics middleware |
| `schema-init/postgres_schema.py` | Add `queue_metrics` and `service_health_metrics` tables |
| `dashboard/admin_proxy.py` | Add 2 proxy routes |
| `dashboard/static/admin.html` | Add Queue Trends and System Health tabs, load Chart.js CDN |
| `dashboard/static/admin.js` | Fetch + render logic, Chart.js initialization, sparkline generation |
| `tests/api/test_admin_endpoints.py` | Endpoint tests for 2 new routes |
| `tests/dashboard/test_admin_proxy.py` | Proxy route tests |

## Testing

### `tests/api/test_metrics_collector.py`

- Mock RabbitMQ management API responses, verify queue metric extraction.
- Mock service health endpoints, verify status + latency capture.
- Mock metrics middleware buffer, verify percentile computation and reset.
- Verify PostgreSQL batch INSERT (mock pool).
- Verify retention pruning DELETE with correct interval.
- Test partial collection failure (RabbitMQ down, health endpoints still recorded).

### `tests/api/test_metrics_queries.py`

- Mock pool with known time-series data.
- Verify granularity selection for each range value.
- Verify `date_trunc` aggregation produces correct bucketing.
- Test DLQ separation in queue history response.
- Test uptime percentage computation.
- Test empty data (no metrics yet) returns empty arrays and 0 counts.

### `tests/api/test_admin_endpoints.py` (extend)

- Both endpoints return 200 with valid admin token.
- Both endpoints return 401/403 without admin or with user token.
- Invalid `range` parameter returns 422.
- Response shapes match Pydantic models.

### `tests/dashboard/test_admin_proxy.py` (extend)

- 2 new proxy routes forward correctly.
- Query parameters (`?range=7d`) forwarded.
- Auth header passed through.

### Middleware tests (in `test_metrics_collector.py`)

- Path normalization: `/api/explore/artist/12345` → `/api/explore/artist/:id`.
- UUID normalization: `/api/collection/abc-def-123` → `/api/collection/:id`.
- Excluded paths not recorded: `/health`, `/metrics`, `/api/admin/queues/history`.
- Buffer cap enforcement: 10,001st entry drops oldest.

## Out of Scope

- **Perftest config**: Admin-only endpoints, low traffic.
- **Rate limiting**: Existing `require_admin` auth is sufficient.
- **Alerting**: No threshold-based alerts or notifications. Future phase.
- **Chart.js unit testing**: CDN-loaded library, tested via manual visual verification.
