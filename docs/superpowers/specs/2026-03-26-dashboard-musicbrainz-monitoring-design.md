# Dashboard MusicBrainz Monitoring — Design Spec

**Issue:** #217
**Parent:** #168 (MusicBrainz integration)
**Date:** 2026-03-26

## Summary

Extend the dashboard service to monitor MusicBrainz extraction and consumer services alongside existing Discogs monitoring. The dashboard restructures around a "pipeline" concept — each data source (Discogs, MusicBrainz) is a pipeline with its own services, queues, and extraction progress. Pipelines are auto-detected: if MusicBrainz services aren't deployed, their section is hidden automatically.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Visual grouping | By data source (pipeline) | Maps to operational reasoning ("is the MB pipeline healthy?") |
| Auto-detection | Service reachability-based | Zero-config; handles phased rollout naturally |
| API response structure | Grouped `pipelines` dict (breaking change) | All consumers are internal; clean cut, no tech debt |
| Overall status | Combined across all active pipelines | A single unhealthy service anywhere = "Degraded" |

## Data Models

### New: `PipelineMetrics`

```python
class PipelineMetrics(BaseModel):
    """Metrics for a single data pipeline (Discogs or MusicBrainz)."""
    services: list[ServiceStatus]
    queues: list[QueueInfo]
```

### Changed: `SystemMetrics`

```python
class SystemMetrics(BaseModel):
    """Model for system-wide metrics."""
    pipelines: dict[str, PipelineMetrics]  # "discogs", "musicbrainz"
    databases: list[DatabaseInfo]           # shared — not per-pipeline
    timestamp: datetime
```

`ServiceStatus`, `QueueInfo`, and `DatabaseInfo` are unchanged.

## Pipeline Configuration

```python
PIPELINE_CONFIGS = {
    "discogs": {
        "services": [
            ("extractor-discogs", "http://extractor-discogs:8000/health"),
            ("graphinator", "http://graphinator:8001/health"),
            ("tableinator", "http://tableinator:8002/health"),
        ],
        "queue_prefix": "discogsography",
        "entity_types": ["masters", "releases", "artists", "labels"],
    },
    "musicbrainz": {
        "services": [
            ("extractor-musicbrainz", "http://extractor-musicbrainz:8000/health"),
            ("brainzgraphinator", "http://brainzgraphinator:8011/health"),
            ("brainztableinator", "http://brainztableinator:8010/health"),
        ],
        "queue_prefix": "musicbrainz",
        "entity_types": ["artists", "labels", "releases"],
    },
}
```

## Backend Changes (`dashboard/dashboard.py`)

### `collect_all_metrics()`

Iterates over `PIPELINE_CONFIGS`. For each pipeline, collects services and queues. A pipeline is included in the response only if at least one service has a status other than `"unknown"` (i.e., at least one service responded, even if unhealthy).

```python
async def collect_all_metrics(self) -> SystemMetrics:
    pipelines = {}
    for pipeline_name, config in PIPELINE_CONFIGS.items():
        services = await self.get_service_statuses(config["services"])
        queues = await self.get_queue_info(config["queue_prefix"])
        if any(s.status != "unknown" for s in services):
            pipelines[pipeline_name] = PipelineMetrics(services=services, queues=queues)
    databases = await self.get_database_info()
    return SystemMetrics(pipelines=pipelines, databases=databases, timestamp=datetime.now(UTC))
```

### `get_service_statuses(service_configs)`

Same logic as today, but parameterized — takes a `list[tuple[str, str]]` of `(name, url)` pairs instead of a hardcoded list.

### `get_queue_info(prefix)`

Same logic, but filters by the given `prefix` parameter instead of hardcoded `"discogsography"`.

### API Endpoints

| Endpoint | Change |
|----------|--------|
| `GET /api/metrics` | Returns `SystemMetrics` with `pipelines` dict |
| `GET /api/services` | Returns `{"discogs": [...], "musicbrainz": [...]}` (active pipelines only) |
| `GET /api/queues` | Same grouped pattern |
| `GET /api/databases` | Unchanged (flat list) |

## Frontend Changes

### `dashboard.js`

**`updateDashboard(data)`** changes from flat access to pipeline-aware:

```javascript
updateDashboard(data) {
    this.updatePipelines(data.pipelines);
    this.updateDatabases(data.databases);
    this.updateLastUpdated(data.timestamp);
    const allServices = Object.values(data.pipelines || {}).flatMap(p => p.services);
    this.updateOverallStatus(allServices);
}
```

**`updatePipelines(pipelines)`** — new method. Iterates over pipeline keys, shows/hides pipeline sections, and calls `updateServices` and `updateQueues` scoped to each pipeline. Element IDs are prefixed by pipeline name (e.g., `discogs-extractor-discogs-status-badge`).

**Queue handling** — each pipeline gets its own DLQ toggle, bar chart, and rate gauges. MusicBrainz uses 3 entity types (no masters).

### `index.html`

Two pipeline sections, both starting with `hidden` class:

```html
<section id="pipeline-discogs" class="hidden">
    <h2>Discogs Pipeline</h2>
    <!-- extractor-discogs card, graphinator card, tableinator card -->
    <!-- Queue bar chart + rate gauges for 4 types: masters, releases, artists, labels -->
</section>

<section id="pipeline-musicbrainz" class="hidden">
    <h2>MusicBrainz Pipeline</h2>
    <!-- extractor-musicbrainz card, brainzgraphinator card, brainztableinator card -->
    <!-- Queue bar chart + rate gauges for 3 types: artists, labels, releases -->
</section>
```

Sections are shown/hidden by JS based on which pipeline keys are present in the response. The databases section remains below both pipelines, unchanged.

### Element ID Convention

All service-related element IDs follow the pattern `{pipeline}-{service}-{detail}`. Examples:

| Old ID | New ID |
|--------|--------|
| `extractor-status-badge` | `discogs-extractor-discogs-status-badge` |
| `extractor-masters-state` | `discogs-extractor-discogs-masters-state` |
| `graphinator-masters-count` | `discogs-graphinator-masters-count` |
| (new) | `musicbrainz-extractor-musicbrainz-status-badge` |
| (new) | `musicbrainz-brainzgraphinator-artists-count` |

Queue chart/gauge IDs follow: `{pipeline}-bar-{type}-messages`, `{pipeline}-rate-circle-{service}-{type}-publish`, etc.

All references in `dashboard.js`, `index.html`, and tests update accordingly.

## Admin Proxy Changes (`dashboard/admin_proxy.py`)

Add one new proxy route for MusicBrainz extraction trigger:

- `POST /admin/api/extractions/trigger-musicbrainz` → API `/api/admin/extractions/trigger` with `source: "musicbrainz"` in the request body

No other admin proxy changes needed — queue history and health history endpoints from the API already return data for all queues and services.

## Docker Changes

No changes to `depends_on` for the dashboard service. The dashboard starts independently of MB services. Auto-detection handles their presence or absence at runtime.

## Test Changes

### `tests/dashboard/conftest.py`

Update mock fixtures to provide `PIPELINE_CONFIGS`-shaped data and `PipelineMetrics` responses.

### `tests/dashboard/test_dashboard_api.py`

- `/api/metrics` returns `pipelines` dict instead of flat `services`/`queues`
- `/api/services` and `/api/queues` return grouped responses
- New test: pipeline omitted when all its services are unreachable
- New test: pipeline included when at least one service responds

### `tests/dashboard/test_dashboard_api_integration.py`

Update for the new response shape.

### `tests/dashboard/dashboard_test_app.py`

Update test app factory to match new `SystemMetrics` structure.

### `tests/dashboard/test_dashboard_ui.py`

Update E2E tests for new pipeline section IDs and element ID prefixes.

### `tests/dashboard/test_admin_proxy.py`

Add test for the new `trigger-musicbrainz` proxy route.

## Out of Scope

- MusicBrainz-specific admin dashboard pages (separate issue)
- Per-pipeline database metrics (databases are shared)
- Configurable pipeline definitions via env vars (hardcoded is sufficient)
- Changes to the API service's admin endpoints
