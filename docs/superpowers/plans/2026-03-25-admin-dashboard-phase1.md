# Admin Dashboard Phase 1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add force-reprocess trigger support, admin dashboard UI with login, extraction history, and DLQ purge to the existing monitoring dashboard.

**Architecture:** The extractor's trigger mechanism changes from `AtomicBool` to `Mutex<Option<bool>>` to carry a force_reprocess flag. The dashboard service proxies admin API calls to the API service via a new router. The frontend is vanilla HTML/JS matching the existing monitoring dashboard style.

**Tech Stack:** Rust (Axum), Python (FastAPI, httpx), vanilla HTML/JS, Tailwind CSS

**Spec:** `docs/superpowers/specs/2026-03-25-admin-dashboard-phase1-design.md`

______________________________________________________________________

## File Map

| File                                     | Action | Responsibility                                              |
| ---------------------------------------- | ------ | ----------------------------------------------------------- |
| `extractor/src/health.rs`                | Modify | Trigger handler: accept JSON body with `force_reprocess`    |
| `extractor/src/extractor.rs`             | Modify | `wait_for_trigger` returns `bool`; trigger branch passes it |
| `extractor/src/main.rs`                  | Modify | Replace `AtomicBool` with `Mutex<Option<bool>>`             |
| `extractor/src/tests/health_tests.rs`    | Modify | Update trigger handler tests for new type + JSON body       |
| `extractor/src/tests/extractor_tests.rs` | Modify | Update `wait_for_trigger` tests for `bool` return           |
| `api/routers/admin.py`                   | Modify | Send `force_reprocess: true` in trigger request body        |
| `tests/api/test_admin_endpoints.py`      | Modify | Verify force_reprocess in trigger request                   |
| `dashboard/admin_proxy.py`               | Create | FastAPI router proxying admin API calls                     |
| `dashboard/dashboard.py`                 | Modify | Mount admin proxy router + `/admin` route                   |
| `dashboard/static/admin.html`            | Create | Admin page (login form + admin panel)                       |
| `dashboard/static/admin.js`              | Create | Admin page logic (auth, API calls, UI)                      |
| `dashboard/static/index.html`            | Modify | Add "Admin" link in header                                  |
| `docker-compose.yml`                     | Modify | Add `API_HOST`/`API_PORT` env vars to dashboard             |
| `tests/dashboard/test_admin_proxy.py`    | Create | Proxy route tests                                           |
| `docs/admin-guide.md`                    | Create | Admin user documentation                                    |

______________________________________________________________________

### Task 1: Extractor — Replace AtomicBool Trigger with Mutex\<Option<bool>>

**Files:**

- Modify: `extractor/src/health.rs:20-28,106-117`

- Modify: `extractor/src/extractor.rs:663-671,674-681,734-748`

- Modify: `extractor/src/main.rs:4,101,104,119`

- Test: `extractor/src/tests/health_tests.rs:246-267`

- Test: `extractor/src/tests/extractor_tests.rs:936-1055`

- [ ] **Step 1: Update health.rs — change trigger type and handler**

In `extractor/src/health.rs`:

Replace the `AtomicBool` import and struct field:

```rust
// Replace:
use std::sync::atomic::{AtomicBool, Ordering};
// With:
use std::sync::Mutex;
```

Change `HealthServer` struct:

```rust
pub struct HealthServer {
    port: u16,
    state: Arc<RwLock<ExtractorState>>,
    trigger: Arc<Mutex<Option<bool>>>,
}

impl HealthServer {
    pub fn new(port: u16, state: Arc<RwLock<ExtractorState>>, trigger: Arc<Mutex<Option<bool>>>) -> Self {
        Self { port, state, trigger }
    }
    // ... run() unchanged except State type
}
```

Update all handler signatures from `Arc<AtomicBool>` to `Arc<Mutex<Option<bool>>>`.

Replace `trigger_handler`:

```rust
#[derive(serde::Deserialize)]
struct TriggerRequest {
    #[serde(default)]
    force_reprocess: bool,
}

async fn trigger_handler(
    State((state, trigger)): State<(Arc<RwLock<ExtractorState>>, Arc<Mutex<Option<bool>>>)>,
    body: Option<Json<TriggerRequest>>,
) -> (StatusCode, Json<serde_json::Value>) {
    let state = state.read().await;
    if state.extraction_status == ExtractionStatus::Running {
        return (StatusCode::CONFLICT, Json(json!({"status": "already_running"})));
    }
    drop(state);

    let force = body.map(|b| b.force_reprocess).unwrap_or(false);
    {
        let mut t = trigger.lock().unwrap();
        *t = Some(force);
    }
    info!("🔄 Extraction triggered via API (force_reprocess={})", force);

    (StatusCode::ACCEPTED, Json(json!({"status": "started", "force_reprocess": force})))
}
```

- [ ] **Step 2: Update extractor.rs — wait_for_trigger returns bool**

In `extractor/src/extractor.rs`:

Replace `wait_for_trigger`:

```rust
/// Wait for the trigger to be set, then take the value and return force_reprocess flag
async fn wait_for_trigger(trigger: &Arc<std::sync::Mutex<Option<bool>>>) -> bool {
    loop {
        {
            let mut t = trigger.lock().unwrap();
            if let Some(force) = t.take() {
                return force;
            }
        }
        tokio::time::sleep(Duration::from_millis(500)).await;
    }
}
```

Update `run_extraction_loop` signature — change `trigger` param type:

```rust
pub async fn run_extraction_loop(
    config: Arc<ExtractorConfig>,
    state: Arc<RwLock<ExtractorState>>,
    shutdown: Arc<tokio::sync::Notify>,
    force_reprocess: bool,
    mq_factory: Arc<dyn MessageQueueFactory>,
    trigger: Arc<std::sync::Mutex<Option<bool>>>,
    compiled_rules: Option<Arc<CompiledRulesConfig>>,
) -> Result<()> {
```

Update the trigger branch (line ~734):

```rust
force = wait_for_trigger(&trigger) => {
    info!("🔄 Extraction triggered via API (force_reprocess={})...", force);
    let start = Instant::now();
    let mut downloader = match Downloader::new(config.discogs_root.clone()).await {
        Ok(dl) => dl,
        Err(e) => {
            error!("❌ Failed to create downloader for triggered extraction: {}", e);
            continue;
        }
    };
    match process_discogs_data(config.clone(), state.clone(), shutdown.clone(), force, &mut downloader, mq_factory.clone(), compiled_rules.clone()).await {
        Ok(true) => info!("✅ Triggered extraction completed successfully in {:?}", start.elapsed()),
        Ok(false) => error!("❌ Triggered extraction completed with errors"),
        Err(e) => error!("❌ Triggered extraction failed: {}", e),
    }
}
```

- [ ] **Step 3: Update main.rs — new trigger type**

In `extractor/src/main.rs`:

Replace `use std::sync::atomic::AtomicBool;` with `use std::sync::Mutex;`.

Replace line 101: `let trigger = Arc::new(Mutex::new(None::<bool>));`

The `HealthServer::new` and `run_extraction_loop` calls stay the same (same variable, different type).

- [ ] **Step 4: Update health_tests.rs — fix trigger type in all tests**

In `extractor/src/tests/health_tests.rs`:

Replace `use std::sync::atomic::{AtomicBool, Ordering};` with `use std::sync::Mutex;`.

Every test that creates `let trigger = Arc::new(AtomicBool::new(false));` becomes:

```rust
let trigger = Arc::new(Mutex::new(None::<bool>));
```

Update `test_trigger_handler_success`:

```rust
#[tokio::test]
async fn test_trigger_handler_success() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let trigger = Arc::new(Mutex::new(None::<bool>));
    let (status, json) = trigger_handler(State((state, trigger.clone())), None).await;
    assert_eq!(status, StatusCode::ACCEPTED);
    assert_eq!(json.0["status"], "started");
    assert_eq!(json.0["force_reprocess"], false);
    assert_eq!(*trigger.lock().unwrap(), Some(false));
}
```

Update `test_trigger_handler_already_running`:

```rust
#[tokio::test]
async fn test_trigger_handler_already_running() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    {
        let mut s = state.write().await;
        s.extraction_status = ExtractionStatus::Running;
    }
    let trigger = Arc::new(Mutex::new(None::<bool>));
    let (status, json) = trigger_handler(State((state, trigger.clone())), None).await;
    assert_eq!(status, StatusCode::CONFLICT);
    assert_eq!(json.0["status"], "already_running");
    assert_eq!(*trigger.lock().unwrap(), None);
}
```

Add new test for force_reprocess=true:

```rust
#[tokio::test]
async fn test_trigger_handler_force_reprocess() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let trigger = Arc::new(Mutex::new(None::<bool>));
    let body = Some(Json(TriggerRequest { force_reprocess: true }));
    let (status, json) = trigger_handler(State((state, trigger.clone())), body).await;
    assert_eq!(status, StatusCode::ACCEPTED);
    assert_eq!(json.0["force_reprocess"], true);
    assert_eq!(*trigger.lock().unwrap(), Some(true));
}
```

- [ ] **Step 5: Update extractor_tests.rs — fix wait_for_trigger tests**

In `extractor/src/tests/extractor_tests.rs`:

Update the three `wait_for_trigger` tests to use `Mutex<Option<bool>>` and check the returned `bool`:

```rust
#[tokio::test(start_paused = true)]
async fn test_wait_for_trigger_returns_when_triggered() {
    let trigger = Arc::new(std::sync::Mutex::new(None::<bool>));
    let trigger_clone = trigger.clone();

    let handle = tokio::spawn(async move {
        wait_for_trigger(&trigger_clone).await
    });

    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;
    assert!(!handle.is_finished());

    { *trigger.lock().unwrap() = Some(true); }

    tokio::time::advance(Duration::from_millis(600)).await;
    tokio::task::yield_now().await;

    let force = handle.await.unwrap();
    assert!(force);
}

#[tokio::test(start_paused = true)]
async fn test_wait_for_trigger_clears_flag() {
    let trigger = Arc::new(std::sync::Mutex::new(Some(false)));

    let force = wait_for_trigger(&trigger).await;

    assert!(!force);
    assert_eq!(*trigger.lock().unwrap(), None);
}

#[tokio::test(start_paused = true)]
async fn test_wait_for_trigger_only_fires_once() {
    let trigger = Arc::new(std::sync::Mutex::new(Some(true)));

    let force = wait_for_trigger(&trigger).await;
    assert!(force);
    assert_eq!(*trigger.lock().unwrap(), None);

    let trigger_clone = trigger.clone();
    let handle = tokio::spawn(async move {
        wait_for_trigger(&trigger_clone).await
    });

    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;
    assert!(!handle.is_finished());

    { *trigger.lock().unwrap() = Some(false); }
    tokio::time::advance(Duration::from_millis(600)).await;
    tokio::task::yield_now().await;
    let force = handle.await.unwrap();
    assert!(!force);
}
```

- [ ] **Step 6: Build and run all extractor tests**

Run: `cd extractor && cargo test 2>&1`
Expected: All tests pass including updated trigger tests.

Run: `cargo clippy -- -D warnings 2>&1`
Expected: No warnings.

- [ ] **Step 7: Commit**

```bash
git add extractor/src/health.rs extractor/src/extractor.rs extractor/src/main.rs \
  extractor/src/tests/health_tests.rs extractor/src/tests/extractor_tests.rs
git commit -m "feat(extractor): support force_reprocess in trigger endpoint

Replace AtomicBool trigger with Mutex<Option<bool>> to carry the
force_reprocess flag from the /trigger HTTP endpoint through to
process_discogs_data. Manual triggers can now force full reprocessing."
```

______________________________________________________________________

### Task 2: API — Send force_reprocess in Trigger Request

**Files:**

- Modify: `api/routers/admin.py:308`

- Test: `tests/api/test_admin_endpoints.py:148-169`

- [ ] **Step 1: Update admin.py — add JSON body to trigger POST**

In `api/routers/admin.py`, line 308, change:

```python
resp = await client.post(trigger_url)
```

to:

```python
resp = await client.post(trigger_url, json={"force_reprocess": True})
```

- [ ] **Step 2: Update trigger test to verify force_reprocess is sent**

In `tests/api/test_admin_endpoints.py`, in `TestExtractionTrigger.test_success`, after the existing assertions add:

```python
# Verify force_reprocess was sent in request body
mock_client_instance.post.assert_called_once()
call_kwargs = mock_client_instance.post.call_args
assert call_kwargs.kwargs.get("json") == {"force_reprocess": True}
```

- [ ] **Step 3: Run API tests**

Run: `uv run pytest tests/api/test_admin_endpoints.py -x -v 2>&1`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add api/routers/admin.py tests/api/test_admin_endpoints.py
git commit -m "feat(admin): send force_reprocess=true when triggering extraction

Manual trigger from admin dashboard always forces reprocessing since the
periodic scheduler already handles normal check-for-new-data flow."
```

______________________________________________________________________

### Task 3: Dashboard — Admin Proxy Router

**Files:**

- Create: `dashboard/admin_proxy.py`

- Modify: `dashboard/dashboard.py:562`

- Create: `tests/dashboard/test_admin_proxy.py`

- [ ] **Step 1: Write the proxy router test**

Create `tests/dashboard/test_admin_proxy.py`:

```python
"""Tests for admin proxy router."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.admin_proxy import router, configure


@pytest.fixture
def proxy_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    configure("localhost", 8004)
    return app


@pytest.fixture
def proxy_client(proxy_app: FastAPI) -> TestClient:
    return TestClient(proxy_app)


class TestLoginProxy:
    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_forwards_login(self, mock_cls: AsyncMock, proxy_client: TestClient) -> None:
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}
        mock_resp.content = b'{"access_token":"tok","token_type":"bearer","expires_in":1800}'
        mock_instance = AsyncMock()
        mock_instance.post = AsyncMock(return_value=mock_resp)
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_instance

        resp = proxy_client.post(
            "/admin/api/login",
            json={"email": "a@b.com", "password": "testtest"},
        )
        assert resp.status_code == 200
        assert "access_token" in resp.json()


class TestTriggerProxy:
    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_forwards_auth_header(self, mock_cls: AsyncMock, proxy_client: TestClient) -> None:
        mock_resp = AsyncMock()
        mock_resp.status_code = 202
        mock_resp.headers = {}
        mock_resp.content = b'{"id":"abc","status":"running"}'
        mock_instance = AsyncMock()
        mock_instance.post = AsyncMock(return_value=mock_resp)
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_instance

        resp = proxy_client.post(
            "/admin/api/extractions/trigger",
            headers={"Authorization": "Bearer mytoken"},
        )
        assert resp.status_code == 202
        # Verify auth header was forwarded
        call_kwargs = mock_instance.post.call_args
        assert "Bearer mytoken" in str(call_kwargs)


class TestApiUnreachable:
    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_returns_502(self, mock_cls: AsyncMock, proxy_client: TestClient) -> None:
        import httpx as httpx_mod

        mock_instance = AsyncMock()
        mock_instance.post = AsyncMock(side_effect=httpx_mod.ConnectError("refused"))
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_instance

        resp = proxy_client.post(
            "/admin/api/login",
            json={"email": "a@b.com", "password": "testtest"},
        )
        assert resp.status_code == 502
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/dashboard/test_admin_proxy.py -x -v 2>&1`
Expected: FAIL — `dashboard.admin_proxy` does not exist yet.

- [ ] **Step 3: Create admin_proxy.py**

Create `dashboard/admin_proxy.py`:

```python
"""Proxy router for admin API calls to the API service."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response
import httpx
import structlog

logger = structlog.get_logger(__name__)

router = APIRouter()

_api_host: str = "api"
_api_port: int = 8004


def configure(api_host: str, api_port: int) -> None:
    """Set API service connection details."""
    global _api_host, _api_port
    _api_host = api_host
    _api_port = api_port


def _api_base() -> str:
    return f"http://{_api_host}:{_api_port}"


async def _proxy(
    method: str,
    api_path: str,
    request: Request,
    json_body: Any = None,
) -> Response:
    """Forward a request to the API service and return the response."""
    url = f"{_api_base()}{api_path}"
    headers: dict[str, str] = {}
    auth = request.headers.get("authorization")
    if auth:
        headers["Authorization"] = auth

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if method == "GET":
                resp = await client.get(url, headers=headers)
            else:
                body = json_body if json_body is not None else await request.body()
                if isinstance(body, bytes) and body:
                    headers["Content-Type"] = "application/json"
                    resp = await client.post(url, headers=headers, content=body)
                elif json_body is not None:
                    resp = await client.post(url, headers=headers, json=json_body)
                else:
                    resp = await client.post(url, headers=headers)
    except (httpx.ConnectError, httpx.RequestError) as exc:
        logger.error("❌ API service unreachable", url=url, error=str(exc))
        return Response(content=b'{"detail":"API service unavailable"}', status_code=502, media_type="application/json")

    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.post("/admin/api/login")
async def proxy_login(request: Request) -> Response:
    """Proxy admin login."""
    return await _proxy("POST", "/api/admin/auth/login", request)


@router.post("/admin/api/logout")
async def proxy_logout(request: Request) -> Response:
    """Proxy admin logout."""
    return await _proxy("POST", "/api/admin/auth/logout", request)


@router.get("/admin/api/extractions")
async def proxy_list_extractions(request: Request) -> Response:
    """Proxy extraction list."""
    return await _proxy("GET", "/api/admin/extractions", request)


@router.get("/admin/api/extractions/{extraction_id}")
async def proxy_get_extraction(extraction_id: str, request: Request) -> Response:
    """Proxy single extraction."""
    return await _proxy("GET", f"/api/admin/extractions/{extraction_id}", request)


@router.post("/admin/api/extractions/trigger")
async def proxy_trigger(request: Request) -> Response:
    """Proxy extraction trigger."""
    return await _proxy("POST", "/api/admin/extractions/trigger", request)


@router.post("/admin/api/dlq/purge/{queue}")
async def proxy_dlq_purge(queue: str, request: Request) -> Response:
    """Proxy DLQ purge."""
    return await _proxy("POST", f"/api/admin/dlq/purge/{queue}", request)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/dashboard/test_admin_proxy.py -x -v 2>&1`
Expected: All tests pass.

- [ ] **Step 5: Mount proxy router in dashboard.py**

In `dashboard/dashboard.py`, before the static files mount (line 562), add:

```python
# Admin proxy routes (must be before StaticFiles catch-all)
from dashboard.admin_proxy import router as admin_router, configure as configure_admin_proxy

admin_api_host = os.getenv("API_HOST", "api")
admin_api_port = int(os.getenv("API_PORT", "8004"))
configure_admin_proxy(admin_api_host, admin_api_port)
app.include_router(admin_router)
```

Also add `import os` at the top if not already present.

The `/admin` page itself is served by the existing `StaticFiles(html=True)` mount — FastAPI serves `admin.html` when `/admin` is requested since `html=True` maps paths to `.html` files.

- [ ] **Step 6: Run dashboard tests**

Run: `uv run pytest tests/dashboard/ -x -v 2>&1`
Expected: All tests pass (existing + new proxy tests).

- [ ] **Step 7: Commit**

```bash
git add dashboard/admin_proxy.py dashboard/dashboard.py tests/dashboard/test_admin_proxy.py
git commit -m "feat(dashboard): add admin API proxy router

Proxy admin endpoints (login, logout, extractions, DLQ purge) from
dashboard service to API service. Auth header forwarded as-is."
```

______________________________________________________________________

### Task 4: Dashboard — Admin Frontend

**Files:**

- Create: `dashboard/static/admin.html`

- Create: `dashboard/static/admin.js`

- Modify: `dashboard/static/index.html:146`

- [ ] **Step 1: Create admin.html**

Create `dashboard/static/admin.html` — full HTML page with the same theme system as `index.html`. Contains:

- Login form (hidden when authenticated)
- Admin panel (hidden when not authenticated):
  - Header with email display, "Monitoring" link, logout, theme toggle
  - Extraction Control card with trigger button
  - Extraction History card with table
  - DLQ Management card with purge buttons

Use the same CSS variables (`:root` and `.dark`), same fonts (Inter, JetBrains Mono), Material Symbols icons, and `.dashboard-card` class from `index.html`.

The HTML structure mirrors the monitoring page: header → stacked dashboard-card sections.

- [ ] **Step 2: Create admin.js**

Create `dashboard/static/admin.js` — `AdminDashboard` class with:

- `constructor()` — check for stored token, show login or panel
- `login(email, password)` — POST `/admin/api/login`, store token
- `logout()` — POST `/admin/api/logout`, clear token, show login
- `authFetch(url, options)` — wrapper that adds Bearer token, handles 401
- `loadExtractions()` — GET `/admin/api/extractions`, render table
- `triggerExtraction()` — POST `/admin/api/extractions/trigger`, show status
- `purgeDlq(queue)` — POST `/admin/api/dlq/purge/{queue}` with confirm dialog
- `initThemeToggle()` — same theme logic as `dashboard.js`
- `showToast(message, type)` — success/error notification
- Auto-refresh extraction list every 30 seconds

DLQ queue names hardcoded in JS (matching `DATA_TYPES` × consumers):

```javascript
const DLQ_NAMES = [
    'graphinator-artists-dlq', 'graphinator-labels-dlq',
    'graphinator-masters-dlq', 'graphinator-releases-dlq',
    'tableinator-artists-dlq', 'tableinator-labels-dlq',
    'tableinator-masters-dlq', 'tableinator-releases-dlq',
];
```

- [ ] **Step 3: Add "Admin" link to monitoring dashboard header**

In `dashboard/static/index.html`, line 146, inside the `<div class="flex items-center space-x-4">`, before the DLQ toggle, add:

```html
<a href="/admin" class="text-xs font-bold uppercase tracking-wider t-dim hover:t-high transition-colors" style="text-decoration:none">Admin</a>
```

- [ ] **Step 4: Manual verification**

Open the monitoring dashboard and verify the "Admin" link appears in the header and navigates to `/admin`. The admin page shows a login form (actual login requires a running API service — verify the form renders correctly).

- [ ] **Step 5: Commit**

```bash
git add dashboard/static/admin.html dashboard/static/admin.js dashboard/static/index.html
git commit -m "feat(dashboard): add admin UI with login, extraction control, DLQ purge

Single scrollable admin page behind login. Shows extraction control
with trigger button, history table with auto-refresh, and DLQ
management with purge buttons."
```

______________________________________________________________________

### Task 5: Docker Compose — Dashboard Environment

**Files:**

- Modify: `docker-compose.yml:438-465`

- [ ] **Step 1: Add API env vars to dashboard service**

In `docker-compose.yml`, in the `dashboard` service `environment` section (after `REDIS_HOST: redis`), add:

```yaml
      API_HOST: api
      API_PORT: "8004"
```

- [ ] **Step 2: Add API dependency**

In the `dashboard` service `depends_on` section, add:

```yaml
      api:
        condition: service_healthy
```

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "fix(compose): add API_HOST/API_PORT to dashboard service

Dashboard admin proxy needs to reach the API service for admin
endpoints."
```

______________________________________________________________________

### Task 6: Documentation — Admin Guide

**Files:**

- Create: `docs/admin-guide.md`

- [ ] **Step 1: Write admin guide**

Create `docs/admin-guide.md`:

```markdown
# Admin Guide

## Creating an Admin Account

Admin accounts are created via the `admin-setup` CLI tool inside the API container:

    docker exec -it discogsography-api-1 admin-setup \
      --email admin@example.com --password <password>

Passwords must be at least 8 characters. If the email already exists, the password is updated.

## Listing Admin Accounts

    docker exec -it discogsography-api-1 admin-setup --list

## Accessing the Admin Panel

Navigate to `http://<host>:8003/admin` and log in with your admin credentials.

The monitoring dashboard at `http://<host>:8003` remains public — no login required.

## Triggering an Extraction

Click **Trigger Extraction** in the admin panel. This forces a full reprocessing of all Discogs data files:

- Downloads the latest monthly data from the Discogs S3 bucket
- Reprocesses all files regardless of existing state markers
- Publishes records to RabbitMQ for graphinator and tableinator consumers

Use this when:

- A previous extraction failed and you want to retry
- You suspect data corruption and want a clean reprocess
- A new Discogs monthly dump has been published and you don't want to wait for the periodic check

The extraction runs asynchronously. Progress is tracked in the extraction history table.

If an extraction is already running, the trigger returns an error — wait for it to complete first.

## DLQ Management

Dead-letter queues (DLQs) collect messages that consumers failed to process. Each data type has a DLQ per consumer:

| Queue | Consumer |
|-------|----------|
| `graphinator-artists-dlq` | Graphinator |
| `graphinator-labels-dlq` | Graphinator |
| `graphinator-masters-dlq` | Graphinator |
| `graphinator-releases-dlq` | Graphinator |
| `tableinator-artists-dlq` | Tableinator |
| `tableinator-labels-dlq` | Tableinator |
| `tableinator-masters-dlq` | Tableinator |
| `tableinator-releases-dlq` | Tableinator |

**Purging** permanently deletes all messages in a DLQ. Do this when:

- Messages are known-bad and will never succeed on retry
- After fixing the root cause and retriggering an extraction

Purging cannot be undone.
```

- [ ] **Step 2: Commit**

```bash
git add docs/admin-guide.md
git commit -m "docs: add admin guide — account creation, trigger, DLQ purge"
```

______________________________________________________________________

### Task 7: Final Verification

- [ ] **Step 1: Run all Python tests**

Run: `uv run pytest tests/api/ tests/dashboard/ -x -v 2>&1`
Expected: All tests pass.

- [ ] **Step 2: Run all Rust tests**

Run: `cd extractor && cargo test 2>&1`
Expected: All tests pass.

- [ ] **Step 3: Run linting**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy . 2>&1`
Expected: Clean.

Run: `cd extractor && cargo clippy -- -D warnings && cargo fmt --check 2>&1`
Expected: Clean.

- [ ] **Step 4: Push**

```bash
git push origin feat/admin-dashboard-104
```
