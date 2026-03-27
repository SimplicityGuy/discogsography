# Dashboard MusicBrainz Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the dashboard to monitor MusicBrainz pipeline services and queues alongside existing Discogs monitoring, with auto-detection for graceful degradation.

**Architecture:** Restructure `SystemMetrics` around a `pipelines` dict grouping services and queues by data source. Backend iterates `PIPELINE_CONFIGS` to collect per-pipeline metrics. Frontend renders pipeline sections conditionally based on which pipelines are present in the response.

**Tech Stack:** Python 3.13+ (FastAPI, Pydantic, httpx), JavaScript (vanilla), HTML/Tailwind CSS

**Worktree:** `.worktrees/217-dashboard-musicbrainz` on branch `feature/217-dashboard-musicbrainz`

---

### Task 1: Add PipelineMetrics model and PIPELINE_CONFIGS

**Files:**
- Modify: `dashboard/dashboard.py:60-101` (models section)
- Test: `tests/dashboard/test_dashboard_api.py`

- [ ] **Step 1: Write the failing test for new model structure**

In `tests/dashboard/test_dashboard_api_integration.py`, update the metrics structure test:

```python
def test_metrics_endpoint(self, client: TestClient) -> None:
    """Test metrics endpoint returns expected pipeline structure."""
    response = client.get("/api/metrics")
    assert response.status_code == 200
    data = response.json()
    assert "pipelines" in data
    assert "databases" in data
    assert "timestamp" in data
    # Discogs pipeline should always be present in test app
    assert "discogs" in data["pipelines"]
    discogs = data["pipelines"]["discogs"]
    assert "services" in discogs
    assert "queues" in discogs
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd .worktrees/217-dashboard-musicbrainz && uv run pytest tests/dashboard/test_dashboard_api_integration.py::TestDashboardAPIIntegration::test_metrics_endpoint -v`
Expected: FAIL — `"pipelines" not in data` (old structure has `"services"`)

- [ ] **Step 3: Add PipelineMetrics model and PIPELINE_CONFIGS to dashboard.py**

In `dashboard/dashboard.py`, after the existing model classes (line ~93), add:

```python
class PipelineMetrics(BaseModel):
    """Metrics for a single data pipeline (Discogs or MusicBrainz)."""

    services: list[ServiceStatus]
    queues: list[QueueInfo]
```

Replace the existing `SystemMetrics` class:

```python
class SystemMetrics(BaseModel):
    """Model for system-wide metrics."""

    pipelines: dict[str, PipelineMetrics]
    databases: list[DatabaseInfo]
    timestamp: datetime
```

Add pipeline configuration after the model classes:

```python
PIPELINE_CONFIGS: dict[str, dict] = {
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

- [ ] **Step 4: Run mypy to check types**

Run: `cd .worktrees/217-dashboard-musicbrainz && uv run mypy dashboard/dashboard.py`
Expected: PASS (or type errors from downstream code not yet updated — that's fine, we fix those in Task 2)

- [ ] **Step 5: Commit**

```bash
cd .worktrees/217-dashboard-musicbrainz
git add dashboard/dashboard.py
git commit -m "feat(dashboard): add PipelineMetrics model and PIPELINE_CONFIGS (#217)"
```

---

### Task 2: Refactor backend to collect metrics per pipeline

**Files:**
- Modify: `dashboard/dashboard.py:207-317` (collect_all_metrics, get_service_statuses, get_queue_info)

- [ ] **Step 1: Refactor get_service_statuses to accept service_configs parameter**

Change the method signature and body in `dashboard/dashboard.py`:

```python
async def get_service_statuses(self, service_configs: list[tuple[str, str]]) -> list[ServiceStatus]:
    """Get status of services defined in the given config list."""
    services = []

    async with httpx.AsyncClient(timeout=5.0) as client:
        for name, url in service_configs:
            try:
                response = await client.get(url)
                if response.status_code == 200:
                    data = response.json()
                    service_status = data.get("status", "healthy")
                    services.append(
                        ServiceStatus(
                            name=name,
                            status=service_status,
                            last_seen=datetime.now(UTC),
                            current_task=data.get("current_task"),
                            progress=data.get("progress"),
                            error=None,
                            extraction_progress=data.get("extraction_progress"),
                            last_extraction_time=data.get("last_extraction_time"),
                        )
                    )
                else:
                    services.append(
                        ServiceStatus(
                            name=name,
                            status="unhealthy",
                            last_seen=datetime.now(UTC),
                            current_task=None,
                            progress=None,
                            error=f"HTTP {response.status_code}",
                        )
                    )
            except Exception as e:
                services.append(
                    ServiceStatus(
                        name=name,
                        status="unknown",
                        last_seen=None,
                        current_task=None,
                        progress=None,
                        error=str(e),
                    )
                )

    return services
```

- [ ] **Step 2: Refactor get_queue_info to accept prefix parameter**

Change the method signature in `dashboard/dashboard.py`:

```python
async def get_queue_info(self, prefix: str) -> list[QueueInfo]:
    """Get RabbitMQ queue information filtered by the given prefix."""
    queues: list[QueueInfo] = []

    try:
        if not self.rabbitmq:
            return queues

        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                "http://rabbitmq:15672/api/queues",
                auth=(self.config.rabbitmq_username, self.config.rabbitmq_password),
            )

            if response.status_code == 200:
                queue_data = response.json()
                for queue in queue_data:
                    if queue["name"].startswith(prefix):
                        queues.append(
                            QueueInfo(
                                name=queue["name"],
                                messages=queue.get("messages", 0),
                                messages_ready=queue.get("messages_ready", 0),
                                messages_unacknowledged=queue.get("messages_unacknowledged", 0),
                                consumers=queue.get("consumers", 0),
                                message_rate=queue.get("message_stats", {}).get("publish_details", {}).get("rate", 0.0),
                                ack_rate=queue.get("message_stats", {}).get("ack_details", {}).get("rate", 0.0),
                            )
                        )
            elif response.status_code == 401:
                logger.warning("⚠️ RabbitMQ management API authentication failed. Queue metrics unavailable.")
            else:
                logger.warning(f"⚠️ RabbitMQ management API returned status {response.status_code}")

    except httpx.ConnectError:
        logger.debug("🐰 RabbitMQ management API unreachable. This is normal if RabbitMQ is not running.")
    except Exception as e:
        logger.error(f"❌ Error getting queue info: {e}")

    return queues
```

- [ ] **Step 3: Refactor collect_all_metrics to use pipeline configs with auto-detection**

```python
async def collect_all_metrics(self) -> SystemMetrics:
    """Collect all system metrics grouped by pipeline."""
    pipelines: dict[str, PipelineMetrics] = {}

    for pipeline_name, config in PIPELINE_CONFIGS.items():
        services = await self.get_service_statuses(config["services"])
        queues = await self.get_queue_info(config["queue_prefix"])
        # Auto-detect: include pipeline only if at least one service is reachable
        if any(s.status != "unknown" for s in services):
            pipelines[pipeline_name] = PipelineMetrics(services=services, queues=queues)

    databases = await self.get_database_info()

    return SystemMetrics(
        pipelines=pipelines,
        databases=databases,
        timestamp=datetime.now(UTC),
    )
```

- [ ] **Step 4: Run mypy**

Run: `cd .worktrees/217-dashboard-musicbrainz && uv run mypy dashboard/dashboard.py`
Expected: PASS (or errors in API endpoint functions — fixed in Task 3)

- [ ] **Step 5: Commit**

```bash
cd .worktrees/217-dashboard-musicbrainz
git add dashboard/dashboard.py
git commit -m "refactor(dashboard): collect metrics per pipeline with auto-detection (#217)"
```

---

### Task 3: Update API endpoints for pipeline-grouped responses

**Files:**
- Modify: `dashboard/dashboard.py:475-517` (API endpoints)

- [ ] **Step 1: Update /api/services endpoint**

Replace the `get_services` function:

```python
@app.get("/api/services")
async def get_services() -> JSONResponse:
    """Get service statuses grouped by pipeline."""
    API_REQUESTS.labels(endpoint="/api/services", method="GET").inc()
    if not dashboard:
        return JSONResponse(content={})
    result = {}
    for pipeline_name, config in PIPELINE_CONFIGS.items():
        services = await dashboard.get_service_statuses(config["services"])
        if any(s.status != "unknown" for s in services):
            result[pipeline_name] = [s.model_dump(mode="json") for s in services]
    return JSONResponse(content=result)
```

- [ ] **Step 2: Update /api/queues endpoint**

Replace the `get_queues` function:

```python
@app.get("/api/queues")
async def get_queues() -> JSONResponse:
    """Get queue information grouped by pipeline."""
    API_REQUESTS.labels(endpoint="/api/queues", method="GET").inc()
    if not dashboard:
        return JSONResponse(content={})
    result = {}
    for pipeline_name, config in PIPELINE_CONFIGS.items():
        queues = await dashboard.get_queue_info(config["queue_prefix"])
        if queues:
            result[pipeline_name] = [q.model_dump(mode="json") for q in queues]
    return JSONResponse(content=result)
```

- [ ] **Step 3: Verify /api/metrics and /api/databases need no changes**

`/api/metrics` already calls `collect_all_metrics()` and dumps the model — it will automatically return the new `pipelines` structure. `/api/databases` is unchanged (flat list).

- [ ] **Step 4: Update the null-dashboard fallbacks for /api/services and /api/queues**

The `if not dashboard` branches now return `{}` (empty dict) instead of `[]` (empty list), matching the new grouped response type.

- [ ] **Step 5: Run mypy and ruff**

Run: `cd .worktrees/217-dashboard-musicbrainz && uv run mypy dashboard/dashboard.py && uv run ruff check dashboard/dashboard.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd .worktrees/217-dashboard-musicbrainz
git add dashboard/dashboard.py
git commit -m "feat(dashboard): update API endpoints for pipeline-grouped responses (#217)"
```

---

### Task 4: Update test app factory for pipeline structure

**Files:**
- Modify: `tests/dashboard/dashboard_test_app.py`

- [ ] **Step 1: Update MockDashboardApp.mock_collect_metrics_loop**

Replace the `latest_metrics` dict in `mock_collect_metrics_loop` (lines 67-124):

```python
async def mock_collect_metrics_loop(self) -> None:
    """Mock metrics collection loop."""
    while True:
        try:
            self.latest_metrics = {
                "pipelines": {
                    "discogs": {
                        "services": [
                            {
                                "name": "extractor-discogs",
                                "status": "healthy",
                                "last_seen": "2024-01-01T00:00:00+00:00",
                                "current_task": None,
                                "progress": None,
                                "error": None,
                                "extraction_progress": None,
                                "last_extraction_time": None,
                            },
                            {
                                "name": "graphinator",
                                "status": "healthy",
                                "last_seen": "2024-01-01T00:00:00+00:00",
                                "current_task": None,
                                "progress": None,
                                "error": None,
                                "extraction_progress": None,
                                "last_extraction_time": None,
                            },
                            {
                                "name": "tableinator",
                                "status": "healthy",
                                "last_seen": "2024-01-01T00:00:00+00:00",
                                "current_task": None,
                                "progress": None,
                                "error": None,
                                "extraction_progress": None,
                                "last_extraction_time": None,
                            },
                        ],
                        "queues": [
                            {
                                "name": "discogsography-graphinator-artists",
                                "messages": 10,
                                "messages_ready": 5,
                                "messages_unacknowledged": 2,
                                "consumers": 1,
                                "message_rate": 0.5,
                                "ack_rate": 0.3,
                            },
                            {
                                "name": "discogsography-tableinator-artists",
                                "messages": 8,
                                "messages_ready": 3,
                                "messages_unacknowledged": 1,
                                "consumers": 1,
                                "message_rate": 0.4,
                                "ack_rate": 0.2,
                            },
                        ],
                    },
                },
                "databases": [
                    {
                        "name": "PostgreSQL",
                        "status": "healthy",
                        "connection_count": 5,
                        "size": "100.5 MB",
                        "error": None,
                    },
                    {
                        "name": "Neo4j",
                        "status": "healthy",
                        "connection_count": 1,
                        "size": "1,000 nodes, 5,000 relationships",
                        "error": None,
                    },
                ],
                "timestamp": "2024-01-01T00:00:00Z",
            }
            await self.broadcast_metrics(self.latest_metrics)
            await asyncio.sleep(2)
        except asyncio.CancelledError:
            break
```

- [ ] **Step 2: Update collect_all_metrics fallback**

```python
async def collect_all_metrics(self) -> dict[str, Any]:
    """Return mock metrics."""
    return self.latest_metrics or {
        "pipelines": {},
        "databases": [],
        "timestamp": "2024-01-01T00:00:00Z",
    }
```

- [ ] **Step 3: Update test app API endpoints for pipeline structure**

Replace `get_services` and `get_queues` in the test app:

```python
@app.get("/api/services")
async def get_services() -> dict[str, Any]:
    """Get service statuses grouped by pipeline."""
    if mock_dashboard_app and mock_dashboard_app.latest_metrics:
        pipelines = mock_dashboard_app.latest_metrics.get("pipelines", {})
        return {name: p["services"] for name, p in pipelines.items()}
    return {}

@app.get("/api/queues")
async def get_queues() -> dict[str, Any]:
    """Get queue information grouped by pipeline."""
    if mock_dashboard_app and mock_dashboard_app.latest_metrics:
        pipelines = mock_dashboard_app.latest_metrics.get("pipelines", {})
        return {name: p["queues"] for name, p in pipelines.items() if p.get("queues")}
    return {}
```

- [ ] **Step 4: Run the integration tests**

Run: `cd .worktrees/217-dashboard-musicbrainz && uv run pytest tests/dashboard/test_dashboard_api_integration.py -v`
Expected: Some tests FAIL (we update them in Task 5)

- [ ] **Step 5: Commit**

```bash
cd .worktrees/217-dashboard-musicbrainz
git add tests/dashboard/dashboard_test_app.py
git commit -m "test(dashboard): update test app factory for pipeline structure (#217)"
```

---

### Task 5: Update all dashboard tests

**Files:**
- Modify: `tests/dashboard/test_dashboard_api_integration.py`
- Modify: `tests/dashboard/test_dashboard_api.py`

- [ ] **Step 1: Update integration tests**

Replace the test methods in `test_dashboard_api_integration.py`:

```python
def test_metrics_endpoint(self, client: TestClient) -> None:
    """Test metrics endpoint returns expected pipeline structure."""
    response = client.get("/api/metrics")
    assert response.status_code == 200
    data = response.json()
    assert "pipelines" in data
    assert "databases" in data
    assert "timestamp" in data
    assert "discogs" in data["pipelines"]
    discogs = data["pipelines"]["discogs"]
    assert "services" in discogs
    assert "queues" in discogs

def test_services_endpoint(self, client: TestClient) -> None:
    """Test services endpoint returns grouped service list."""
    response = client.get("/api/services")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    assert "discogs" in data
    assert len(data["discogs"]) == 3
    service_names = {s["name"] for s in data["discogs"]}
    assert service_names == {"extractor-discogs", "graphinator", "tableinator"}

def test_queues_endpoint(self, client: TestClient) -> None:
    """Test queues endpoint returns grouped queue list."""
    response = client.get("/api/queues")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    assert "discogs" in data
    assert len(data["discogs"]) >= 2
    for queue in data["discogs"]:
        assert "name" in queue
        assert "messages" in queue
        assert "consumers" in queue
```

- [ ] **Step 2: Update test_dashboard_api.py null-dashboard tests**

Update the `test_services_endpoint_without_dashboard` and `test_queues_endpoint_without_dashboard` tests to expect `{}` instead of `[]`:

```python
def test_services_endpoint_without_dashboard(self, ...) -> None:
    """Test /api/services endpoint when dashboard is not initialized."""
    # ... same patches ...
    response = test_client.get("/api/services")
    assert response.status_code == 200
    assert response.json() == {}

def test_queues_endpoint_without_dashboard(self, ...) -> None:
    """Test /api/queues endpoint when dashboard is not initialized."""
    # ... same patches ...
    response = test_client.get("/api/queues")
    assert response.status_code == 200
    assert response.json() == {}
```

- [ ] **Step 3: Run all dashboard tests**

Run: `cd .worktrees/217-dashboard-musicbrainz && uv run pytest tests/dashboard/ -v --ignore=tests/dashboard/test_dashboard_ui.py`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
cd .worktrees/217-dashboard-musicbrainz
git add tests/dashboard/test_dashboard_api_integration.py tests/dashboard/test_dashboard_api.py
git commit -m "test(dashboard): update API tests for pipeline-grouped responses (#217)"
```

---

### Task 6: Add pipeline auto-detection tests

**Files:**
- Modify: `tests/dashboard/test_dashboard_api_integration.py`
- Modify: `tests/dashboard/dashboard_test_app.py`

- [ ] **Step 1: Write test for pipeline omission when all services unreachable**

Add to `test_dashboard_api_integration.py`:

```python
def test_musicbrainz_pipeline_absent_when_not_deployed(self, client: TestClient) -> None:
    """Test that MusicBrainz pipeline is absent when services are not deployed."""
    response = client.get("/api/metrics")
    assert response.status_code == 200
    data = response.json()
    # Test app only mocks Discogs services, MB should not appear
    assert "musicbrainz" not in data["pipelines"]
```

- [ ] **Step 2: Run test to verify it passes**

Run: `cd .worktrees/217-dashboard-musicbrainz && uv run pytest tests/dashboard/test_dashboard_api_integration.py::TestDashboardAPIIntegration::test_musicbrainz_pipeline_absent_when_not_deployed -v`
Expected: PASS (test app only provides Discogs data)

- [ ] **Step 3: Write test for pipeline inclusion when at least one service responds**

Add a second test app fixture that includes MusicBrainz data. Add to `test_dashboard_api_integration.py`:

```python
class TestDashboardPipelineDetection:
    """Test pipeline auto-detection logic."""

    @pytest.fixture
    def client_with_musicbrainz(self) -> typing.Generator[TestClient]:
        """Create test client with both pipelines."""
        from tests.dashboard.dashboard_test_app import create_test_app_with_musicbrainz

        app = create_test_app_with_musicbrainz()
        with TestClient(app) as test_client:
            yield test_client

    def test_both_pipelines_present(self, client_with_musicbrainz: TestClient) -> None:
        """Test that both pipelines appear when MB services are available."""
        response = client_with_musicbrainz.get("/api/metrics")
        assert response.status_code == 200
        data = response.json()
        assert "discogs" in data["pipelines"]
        assert "musicbrainz" in data["pipelines"]
        mb = data["pipelines"]["musicbrainz"]
        service_names = {s["name"] for s in mb["services"]}
        assert service_names == {"extractor-musicbrainz", "brainzgraphinator", "brainztableinator"}
```

- [ ] **Step 4: Add create_test_app_with_musicbrainz to dashboard_test_app.py**

Add a new factory function that includes MusicBrainz mock data. The `MockDashboardApp` gains a `with_musicbrainz` parameter:

```python
class MockDashboardApp:
    def __init__(self, include_musicbrainz: bool = False) -> None:
        # ... existing init ...
        self.include_musicbrainz = include_musicbrainz
```

In `mock_collect_metrics_loop`, after the `"discogs"` pipeline entry, conditionally add:

```python
if self.include_musicbrainz:
    self.latest_metrics["pipelines"]["musicbrainz"] = {
        "services": [
            {
                "name": "extractor-musicbrainz",
                "status": "healthy",
                "last_seen": "2024-01-01T00:00:00+00:00",
                "current_task": None,
                "progress": None,
                "error": None,
                "extraction_progress": None,
                "last_extraction_time": None,
            },
            {
                "name": "brainzgraphinator",
                "status": "healthy",
                "last_seen": "2024-01-01T00:00:00+00:00",
                "current_task": None,
                "progress": None,
                "error": None,
                "extraction_progress": None,
                "last_extraction_time": None,
            },
            {
                "name": "brainztableinator",
                "status": "healthy",
                "last_seen": "2024-01-01T00:00:00+00:00",
                "current_task": None,
                "progress": None,
                "error": None,
                "extraction_progress": None,
                "last_extraction_time": None,
            },
        ],
        "queues": [
            {
                "name": "musicbrainz-brainzgraphinator-artists",
                "messages": 5,
                "messages_ready": 3,
                "messages_unacknowledged": 1,
                "consumers": 1,
                "message_rate": 0.3,
                "ack_rate": 0.2,
            },
        ],
    }
```

Add the factory:

```python
def create_test_app_with_musicbrainz() -> FastAPI:
    """Create a test app with both Discogs and MusicBrainz pipelines."""
    # Same as create_test_app but passes include_musicbrainz=True
    # to MockDashboardApp in the lifespan
```

This reuses the same `create_test_app` logic — extract the common code into a helper that takes the `include_musicbrainz` flag.

- [ ] **Step 5: Run the new tests**

Run: `cd .worktrees/217-dashboard-musicbrainz && uv run pytest tests/dashboard/test_dashboard_api_integration.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd .worktrees/217-dashboard-musicbrainz
git add tests/dashboard/test_dashboard_api_integration.py tests/dashboard/dashboard_test_app.py
git commit -m "test(dashboard): add pipeline auto-detection tests (#217)"
```

---

### Task 7: Update index.html with pipeline sections

**Files:**
- Modify: `dashboard/static/index.html`

- [ ] **Step 1: Wrap existing service cards in a Discogs pipeline section**

Replace the service cards `<div class="grid grid-cols-3 gap-6">` block (lines 166-264) with:

```html
<!-- ================================================================
     DISCOGS PIPELINE
     ================================================================ -->
<section id="pipeline-discogs" class="space-y-8 hidden">
    <div class="flex items-center gap-3">
        <h2 class="text-sm font-bold uppercase tracking-[0.15em] t-dim">Discogs Pipeline</h2>
        <div class="flex-1 border-t b-theme"></div>
    </div>

    <!-- Discogs service cards (3-column grid) -->
    <div class="grid grid-cols-3 gap-6">
        <!-- Extractor Discogs -->
        <div id="service-extractor-discogs" class="dashboard-card p-6">
            <div class="flex items-center justify-between mb-6 border-b b-theme pb-4">
                <h3 class="text-sm font-semibold flex items-center gap-2">
                    <span class="material-symbols-outlined text-sm t-dim">output</span> Extractor
                </h3>
                <span id="discogs-extractor-discogs-status-badge" class="text-[10px] bg-yellow-500/10 text-yellow-400 px-2 py-0.5 rounded border border-yellow-500/20 uppercase font-bold">Unknown</span>
            </div>
            <div class="space-y-3">
                <div class="flex justify-between text-[10px] t-muted uppercase font-bold tracking-wider">
                    <span>Queues</span><span>State</span>
                </div>
                <div class="flex justify-between text-xs mono py-1 border-b b-row">
                    <span>Masters</span>
                    <span id="discogs-extractor-discogs-masters-state" class="t-muted">—</span>
                </div>
                <div class="flex justify-between text-xs mono py-1 border-b b-row">
                    <span>Releases</span>
                    <span id="discogs-extractor-discogs-releases-state" class="t-muted">—</span>
                </div>
                <div class="flex justify-between text-xs mono py-1 border-b b-row">
                    <span>Artists</span>
                    <span id="discogs-extractor-discogs-artists-state" class="t-muted">—</span>
                </div>
                <div class="flex justify-between text-xs mono py-1">
                    <span>Labels</span>
                    <span id="discogs-extractor-discogs-labels-state" class="t-muted">—</span>
                </div>
                <div class="flex justify-between text-[10px] t-muted uppercase font-bold tracking-wider pt-3 mt-1 border-t b-theme">
                    <span>Total Records</span>
                    <span id="discogs-extractor-discogs-total-records" class="t-high normal-case font-mono">—</span>
                </div>
            </div>
        </div>

        <!-- Graphinator -->
        <div id="service-graphinator" class="dashboard-card p-6">
            <!-- Same structure as before but IDs prefixed with discogs- -->
            <!-- e.g., discogs-graphinator-status-badge, discogs-graphinator-masters-count -->
        </div>

        <!-- Tableinator -->
        <div id="service-tableinator" class="dashboard-card p-6">
            <!-- Same structure, IDs prefixed with discogs- -->
        </div>
    </div>
</section>
```

Similarly, wrap the Queue Size Metrics and Processing Rates sections inside `<section id="pipeline-discogs">`, prefixing all element IDs with `discogs-`.

- [ ] **Step 2: Add MusicBrainz pipeline section**

After the Discogs pipeline section, add:

```html
<!-- ================================================================
     MUSICBRAINZ PIPELINE
     ================================================================ -->
<section id="pipeline-musicbrainz" class="space-y-8 hidden">
    <div class="flex items-center gap-3">
        <h2 class="text-sm font-bold uppercase tracking-[0.15em] t-dim">MusicBrainz Pipeline</h2>
        <div class="flex-1 border-t b-theme"></div>
    </div>

    <!-- MusicBrainz service cards (3-column grid) -->
    <div class="grid grid-cols-3 gap-6">
        <!-- Extractor MusicBrainz -->
        <div id="service-extractor-musicbrainz" class="dashboard-card p-6">
            <!-- Same extractor card structure but:
                 - ID prefix: musicbrainz-
                 - Only 3 entity types: Artists, Labels, Releases (no Masters) -->
        </div>

        <!-- Brainzgraphinator -->
        <div id="service-brainzgraphinator" class="dashboard-card p-6">
            <!-- Same consumer card structure, 3 entity types, purple accent -->
        </div>

        <!-- Brainztableinator -->
        <div id="service-brainztableinator" class="dashboard-card p-6">
            <!-- Same consumer card structure, 3 entity types, blue accent -->
        </div>
    </div>

    <!-- MusicBrainz Queue Size Metrics bar chart (3 types) -->
    <!-- MusicBrainz Processing Rates gauges (3 types) -->
</section>
```

All MusicBrainz element IDs use the `musicbrainz-` prefix. The bar chart and gauge sections follow the same structure as Discogs but with 3 columns (`grid-cols-3`) instead of 4.

- [ ] **Step 3: Verify the HTML is valid**

Open the file and visually check structure. Ensure all IDs are unique and follow the `{pipeline}-{service}-{detail}` convention.

- [ ] **Step 4: Commit**

```bash
cd .worktrees/217-dashboard-musicbrainz
git add dashboard/static/index.html
git commit -m "feat(dashboard): restructure HTML into Discogs and MusicBrainz pipeline sections (#217)"
```

---

### Task 8: Update dashboard.js for pipeline-aware rendering

**Files:**
- Modify: `dashboard/static/dashboard.js`

- [ ] **Step 1: Update updateDashboard to use pipelines**

Replace the `updateDashboard` method:

```javascript
updateDashboard(data) {
    const pipelines = data.pipelines || {};
    // Show/hide pipeline sections
    for (const pipelineId of ['discogs', 'musicbrainz']) {
        const section = document.getElementById(`pipeline-${pipelineId}`);
        if (section) {
            section.classList.toggle('hidden', !(pipelineId in pipelines));
        }
    }
    // Update each active pipeline
    for (const [pipelineName, pipelineData] of Object.entries(pipelines)) {
        this.updateServices(pipelineName, pipelineData.services || []);
        this.updateQueues(pipelineName, pipelineData.queues || []);
    }
    this.updateDatabases(data.databases || []);
    this.updateLastUpdated(data.timestamp);
    // Overall status across all active pipelines
    const allServices = Object.values(pipelines).flatMap(p => p.services || []);
    this.updateOverallStatus(allServices);
}
```

- [ ] **Step 2: Update updateServices to be pipeline-scoped**

Add `pipelineName` parameter. Use `{pipelineName}-{service.name}` as the element ID prefix:

```javascript
updateServices(pipelineName, services) {
    const PIPELINE_ENTITY_TYPES = {
        discogs: ['masters', 'releases', 'artists', 'labels'],
        musicbrainz: ['artists', 'labels', 'releases'],
    };
    const types = PIPELINE_ENTITY_TYPES[pipelineName] || ['artists', 'labels', 'releases'];

    services.forEach(service => {
        const prefix = `${pipelineName}-${service.name}`;
        const badge = document.getElementById(`${prefix}-status-badge`);
        if (badge) {
            badge.className = this._serviceBadgeClasses(service.status);
            badge.textContent = this._statusLabel(service.status);
        }

        // Extractor card — use extraction_progress from health endpoint
        if (service.name.startsWith('extractor') && service.extraction_progress) {
            const progress = service.extraction_progress;
            const elapsed = service.last_extraction_time || {};

            types.forEach(type => {
                const el = document.getElementById(`${prefix}-${type}-state`);
                if (!el) return;
                const count = progress[type] || 0;
                const active = elapsed[type] != null && elapsed[type] < 30;
                if (active) {
                    el.textContent = `Processing (${count.toLocaleString()})`;
                    el.className = 'text-blue-400';
                } else {
                    el.textContent = 'Idle';
                    el.className = 'text-emerald-400';
                }
            });

            const totalEl = document.getElementById(`${prefix}-total-records`);
            if (totalEl) {
                const total = progress.total || 0;
                totalEl.textContent = total > 0 ? total.toLocaleString() : '—';
            }
        }
    });
}
```

- [ ] **Step 3: Update updateQueues to be pipeline-scoped**

Add `pipelineName` parameter. The queue map and element ID lookups use the pipeline prefix:

```javascript
updateQueues(pipelineName, queues) {
    const PIPELINE_ENTITY_TYPES = {
        discogs: ['masters', 'releases', 'artists', 'labels'],
        musicbrainz: ['artists', 'labels', 'releases'],
    };
    const TYPES = PIPELINE_ENTITY_TYPES[pipelineName] || ['artists', 'labels', 'releases'];

    // Determine consumer names per pipeline
    const CONSUMERS = pipelineName === 'discogs'
        ? { graph: 'graphinator', table: 'tableinator' }
        : { graph: 'brainzgraphinator', table: 'brainztableinator' };

    const graphMap = {};
    const tableMap = {};
    const graphDlqMap = {};
    const tableDlqMap = {};

    queues.forEach(queue => {
        const name = queue.name.toLowerCase();
        const isDlq = name.endsWith('.dlq');

        for (const type of TYPES) {
            if (!name.includes(type)) continue;
            if (name.includes(CONSUMERS.graph)) {
                if (isDlq) graphDlqMap[type] = queue;
                else graphMap[type] = queue;
            } else if (name.includes(CONSUMERS.table)) {
                if (isDlq) tableDlqMap[type] = queue;
                else tableMap[type] = queue;
            }
            break;
        }
    });

    // Store maps for DLQ toggle (keyed by pipeline)
    this.currentMaps = this.currentMaps || {};
    this.currentMaps[pipelineName] = { graphMap, tableMap, graphDlqMap, tableDlqMap, CONSUMERS, TYPES };

    const isDlq = document.getElementById('dlq-toggle')?.checked ?? false;
    const activeGraphMap = isDlq ? graphDlqMap : graphMap;
    const activeTableMap = isDlq ? tableDlqMap : tableMap;

    // Update consumer cards
    TYPES.forEach(type => {
        const gEl = document.getElementById(`${pipelineName}-${CONSUMERS.graph}-${type}-count`);
        if (gEl) {
            const q = activeGraphMap[type];
            gEl.textContent = q ? q.messages.toLocaleString() : '—';
        }
        const tEl = document.getElementById(`${pipelineName}-${CONSUMERS.table}-${type}-count`);
        if (tEl) {
            const q = activeTableMap[type];
            tEl.textContent = q ? q.messages.toLocaleString() : '—';
        }
    });

    this._updateBarChart(pipelineName, activeGraphMap, activeTableMap, TYPES, isDlq);
    this._updateRateCircles(pipelineName, graphMap, tableMap, TYPES, isDlq);

    // Log high message counts
    queues.forEach(queue => {
        if (!queue.name.toLowerCase().endsWith('.dlq') && queue.messages > 1000) {
            this.addLogEntry(
                `High message count in ${queue.name}: ${queue.messages.toLocaleString()}`,
                'warning'
            );
        }
    });
}
```

- [ ] **Step 4: Update _updateBarChart and _updateRateCircles to use pipeline prefix**

Add `pipelineName` as first parameter. All element ID lookups get the pipeline prefix:

```javascript
_updateBarChart(pipelineName, graphinatorMap, tableInatorMap, types, isDlq = false) {
    const maps = this.currentMaps?.[pipelineName];
    const graphLabel = maps?.CONSUMERS?.graph || 'graphinator';
    const tableLabel = maps?.CONSUMERS?.table || 'tableinator';

    const graphLegend = document.getElementById(`${pipelineName}-chart-legend-${graphLabel}`);
    const tableLegend = document.getElementById(`${pipelineName}-chart-legend-${tableLabel}`);
    if (graphLegend) graphLegend.textContent = isDlq ? `${graphLabel} DLQ` : graphLabel;
    if (tableLegend) tableLegend.textContent = isDlq ? `${tableLabel} DLQ` : tableLabel;

    // ... rest of bar chart logic with `${pipelineName}-bar-${type}-messages` IDs ...
}

_updateRateCircles(pipelineName, graphinatorMap, tableInatorMap, types, isDlq = false) {
    const maps = this.currentMaps?.[pipelineName];
    const graphName = maps?.CONSUMERS?.graph || 'graphinator';
    const tableName = maps?.CONSUMERS?.table || 'tableinator';

    // ... rest of gauge logic with `${pipelineName}-rate-circle-${service}-${type}-publish` IDs ...
}
```

- [ ] **Step 5: Update _onDlqToggle to iterate all pipelines**

```javascript
_onDlqToggle() {
    if (!this.currentMaps) return;
    const isDlq = document.getElementById('dlq-toggle')?.checked ?? false;

    for (const [pipelineName, maps] of Object.entries(this.currentMaps)) {
        const { graphMap, tableMap, graphDlqMap, tableDlqMap, CONSUMERS, TYPES } = maps;
        const activeGraphMap = isDlq ? graphDlqMap : graphMap;
        const activeTableMap = isDlq ? tableDlqMap : tableMap;

        TYPES.forEach(type => {
            const gEl = document.getElementById(`${pipelineName}-${CONSUMERS.graph}-${type}-count`);
            if (gEl) {
                const q = activeGraphMap[type];
                gEl.textContent = q ? q.messages.toLocaleString() : '—';
            }
            const tEl = document.getElementById(`${pipelineName}-${CONSUMERS.table}-${type}-count`);
            if (tEl) {
                const q = activeTableMap[type];
                tEl.textContent = q ? q.messages.toLocaleString() : '—';
            }
        });

        this._updateBarChart(pipelineName, activeGraphMap, activeTableMap, TYPES, isDlq);
        this._updateRateCircles(pipelineName, graphMap, tableMap, TYPES, isDlq);
    }
}
```

- [ ] **Step 6: Commit**

```bash
cd .worktrees/217-dashboard-musicbrainz
git add dashboard/static/dashboard.js
git commit -m "feat(dashboard): update JS for pipeline-aware rendering (#217)"
```

---

### Task 9: Add admin proxy route for MusicBrainz extraction trigger

**Files:**
- Modify: `dashboard/admin_proxy.py`
- Modify: `tests/dashboard/test_admin_proxy.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/dashboard/test_admin_proxy.py`:

```python
async def test_proxy_trigger_musicbrainz(self, client: AsyncClient) -> None:
    """Test MusicBrainz extraction trigger proxy."""
    with patch("dashboard.admin_proxy._forward_request", new_callable=AsyncMock) as mock_forward:
        mock_forward.return_value = Response(status_code=200)
        response = await client.post(
            "/admin/api/extractions/trigger-musicbrainz",
            json={},
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code == 200
        # Verify the source was injected into the body
        call_args = mock_forward.call_args
        assert call_args is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd .worktrees/217-dashboard-musicbrainz && uv run pytest tests/dashboard/test_admin_proxy.py -k "trigger_musicbrainz" -v`
Expected: FAIL — route not found (404)

- [ ] **Step 3: Add the proxy route**

In `dashboard/admin_proxy.py`, after the existing `proxy_trigger` route:

```python
@router.post("/admin/api/extractions/trigger-musicbrainz")
async def proxy_trigger_musicbrainz(request: Request) -> Response:
    """Proxy MusicBrainz extraction trigger requests to the API service."""
    url = _build_url("/api/admin/extractions/trigger")
    headers = _auth_headers(request)
    sanitised_body = await _validated_json_body(request)
    if sanitised_body is None:
        sanitised_body = {}
    sanitised_body["source"] = "musicbrainz"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=headers, json=sanitised_body)
    except httpx.ConnectError as exc:
        logger.error("❌ API service unreachable", url=url, error=str(exc))
        return _unavailable_response()
    return _ok_response(resp)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd .worktrees/217-dashboard-musicbrainz && uv run pytest tests/dashboard/test_admin_proxy.py -k "trigger_musicbrainz" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd .worktrees/217-dashboard-musicbrainz
git add dashboard/admin_proxy.py tests/dashboard/test_admin_proxy.py
git commit -m "feat(dashboard): add admin proxy route for MusicBrainz extraction trigger (#217)"
```

---

### Task 10: Run full test suite and fix issues

**Files:**
- All modified files

- [ ] **Step 1: Run full dashboard test suite**

Run: `cd .worktrees/217-dashboard-musicbrainz && uv run pytest tests/dashboard/ -v --ignore=tests/dashboard/test_dashboard_ui.py`
Expected: PASS

- [ ] **Step 2: Run mypy**

Run: `cd .worktrees/217-dashboard-musicbrainz && uv run mypy dashboard/`
Expected: PASS

- [ ] **Step 3: Run ruff**

Run: `cd .worktrees/217-dashboard-musicbrainz && uv run ruff check dashboard/ tests/dashboard/`
Expected: PASS

- [ ] **Step 4: Run ruff format**

Run: `cd .worktrees/217-dashboard-musicbrainz && uv run ruff format dashboard/ tests/dashboard/`
Expected: No changes (or reformats as needed)

- [ ] **Step 5: Fix any failures and commit**

If any tests, type checks, or lint issues, fix them and commit:

```bash
cd .worktrees/217-dashboard-musicbrainz
git add -A
git commit -m "fix(dashboard): address test/lint issues from MusicBrainz monitoring (#217)"
```

---

### Task 11: Update documentation

**Files:**
- Modify: `dashboard/README.md`
- Modify: `docs/monitoring.md` (if it references dashboard API structure)

- [ ] **Step 1: Update dashboard README with new pipeline structure**

Update the API section of `dashboard/README.md` to document:
- The new `pipelines` dict in `/api/metrics`
- The grouped responses from `/api/services` and `/api/queues`
- The new `/admin/api/extractions/trigger-musicbrainz` route
- The MusicBrainz pipeline auto-detection behavior

- [ ] **Step 2: Commit**

```bash
cd .worktrees/217-dashboard-musicbrainz
git add dashboard/README.md docs/monitoring.md
git commit -m "docs(dashboard): update README for MusicBrainz pipeline monitoring (#217)"
```
