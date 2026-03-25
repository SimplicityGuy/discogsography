# Admin Dashboard Phase 1 — Design Spec

## Overview

Add a web-based admin panel to the existing Dashboard service (port 8003) that enables authenticated administrators to trigger extraction reprocessing, view extraction history, and purge dead-letter queues. The monitoring dashboard remains public and unauthenticated.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Where does admin UI live? | Dashboard service (port 8003) | Single operational UI; dashboard proxies API calls |
| Navigation pattern | Separate `/admin` page | Monitoring stays public; admin is login-gated |
| Manual trigger behavior | Always force reprocess | Periodic scheduler already handles normal checks; manual trigger implies intent to reprocess |
| Admin page layout | Single scrollable page | Matches monitoring dashboard pattern; simple |

## 1. Force Reprocess — Extractor Changes

### Current State

The extractor's `/trigger` endpoint (`health.rs`) accepts no body and sets an `AtomicBool` flag. The `run_extraction_loop` picks up this flag via `wait_for_trigger()` and calls `process_discogs_data` with `force_reprocess=false` hardcoded.

### Changes

**Replace `AtomicBool` trigger with `Arc<Mutex<Option<bool>>>`:**

- `None` = no trigger pending
- `Some(force)` = trigger pending with force_reprocess flag

**`health.rs` — `trigger_handler`:**

- Accept optional JSON body: `{"force_reprocess": true}`
- If no body or missing field, default `force_reprocess` to `false`
- Check extraction status; return 409 if running
- Store `Some(force_reprocess)` in the shared trigger state

**`extractor.rs` — `wait_for_trigger`:**

- Change return type from `()` to `bool` (the force_reprocess value)
- Poll the `Mutex<Option<bool>>`, take the value when `Some`

**`extractor.rs` — `run_extraction_loop` trigger branch:**

- Pass the returned `force_reprocess` bool to `process_discogs_data` instead of hardcoded `false`

**`main.rs`:**

- Replace `Arc<AtomicBool>` with `Arc<Mutex<Option<bool>>>` for trigger state
- Thread through to `HealthServer::new` and `run_extraction_loop`

**`api/routers/admin.py` — `trigger_extraction`:**

- Send `{"force_reprocess": true}` as JSON body when calling extractor `/trigger`

### Files Modified

- `extractor/src/health.rs`
- `extractor/src/extractor.rs`
- `extractor/src/main.rs`
- `api/routers/admin.py`

## 2. Dashboard Admin UI

### Architecture

The dashboard service gets a new proxy router (`admin_proxy.py`) that forwards authenticated requests to the API service. The frontend is vanilla HTML/JS using the same Tailwind CSS, Inter/JetBrains Mono fonts, Material Symbols icons, and light/dark theme CSS variables as the existing monitoring dashboard.

### New Files

| File | Purpose |
|------|---------|
| `dashboard/static/admin.html` | Admin page — login form + admin panel |
| `dashboard/static/admin.js` | Admin page logic — auth, API calls, UI updates |
| `dashboard/admin_proxy.py` | FastAPI router — proxy endpoints to API service |

### Proxy Routes (`admin_proxy.py`)

| Dashboard Route | Forwards To (API Service) | Method |
|---|---|---|
| `/admin/api/login` | `/api/admin/auth/login` | POST |
| `/admin/api/logout` | `/api/admin/auth/logout` | POST |
| `/admin/api/extractions` | `/api/admin/extractions` | GET |
| `/admin/api/extractions/{id}` | `/api/admin/extractions/{id}` | GET |
| `/admin/api/extractions/trigger` | `/api/admin/extractions/trigger` | POST |
| `/admin/api/dlq/purge/{queue}` | `/api/admin/dlq/purge/{queue}` | POST |

The proxy:

- Forwards `Authorization` header as-is to the API service
- Returns the API response status and body unchanged
- Uses `httpx.AsyncClient` with a 30-second timeout (extractions can take time)
- Reads `API_HOST` and `API_PORT` from environment (defaults: `api`, `8004`)

### Dashboard Service Changes (`dashboard.py`)

- Import and mount the `admin_proxy` router
- Serve `/admin` route to return `admin.html`
- Add `API_HOST`/`API_PORT` environment variables to config

### Frontend Flow (`admin.html` + `admin.js`)

```
Visit /admin
  ├─ No JWT in localStorage → Show login form
  │   └─ Submit → POST /admin/api/login → Store JWT → Show admin panel
  └─ JWT exists → Show admin panel
      ├─ Extraction Control section
      │   └─ "Trigger Extraction" button → POST /admin/api/extractions/trigger
      │       └─ Shows spinner while running, success/error toast
      ├─ Extraction History section
      │   └─ Table: date, status (color-coded badge), duration, record counts
      │       └─ Auto-refreshes every 30 seconds while panel is visible
      ├─ DLQ Management section
      │   └─ List of valid DLQ names with "Purge" button each
      │       └─ Confirmation dialog before purge
      └─ Header: email display, "Monitoring" link, Logout button
          └─ Logout → POST /admin/api/logout → Clear JWT → Show login
```

**Auth handling:**

- JWT stored in `localStorage` under key `admin_token`
- Attached to all API requests as `Authorization: Bearer <token>`
- On any 401 response: clear stored token, redirect to login form
- Admin tokens expire after 30 minutes (server-side); frontend handles gracefully

**UI style:**

- Same CSS variables as monitoring dashboard (light/dark theme)
- `.dashboard-card` class for card containers
- Material Symbols Outlined for icons
- Status badges: emerald for completed/healthy, red for failed, yellow for running/pending
- JetBrains Mono for data values (record counts, timestamps, IDs)

### Navigation

- Monitoring page (`index.html`): Add "Admin" link in header (right side, before theme toggle)
- Admin page (`admin.html`): Add "Monitoring" link in header

### Docker/Compose Changes

- Dashboard Dockerfile: No changes needed (static files already served via `StaticFiles`)
- `docker-compose.yml`: Add `API_HOST: api` and `API_PORT: "8004"` to dashboard service environment
- Dashboard `depends_on`: Add `api` service dependency

## 3. Admin User Documentation

New file: `docs/admin-guide.md`

Contents:

1. **Creating an admin account** — `docker exec` into the API container and run the `admin-setup` CLI:
   ```
   docker exec -it discogsography-api-1 admin-setup \
     --email admin@example.com --password <min-8-chars>
   ```
2. **Listing admin accounts** — `admin-setup --list`
3. **Accessing the admin panel** — `http://<host>:8003/admin`
4. **Triggering extraction** — What it does (forces full reprocessing regardless of state markers), when to use it
5. **DLQ management** — What DLQs are, valid queue names, when purging is appropriate

## 4. Testing

### Rust (extractor)

- Update `wait_for_trigger` tests for new `Option<bool>` return type (returns force flag)
- Update `trigger_handler` tests: verify JSON body parsing, default `force_reprocess=false` when no body, `force_reprocess=true` when specified
- Update `test_trigger_handler_already_running` and `test_trigger_handler_success` for new trigger state type

### Python (admin proxy)

- New test file: `tests/dashboard/test_admin_proxy.py`
- Test each proxy route with mocked `httpx` calls to the API service
- Test Authorization header forwarding
- Test error handling (API unreachable, 4xx/5xx responses)

### Python (admin API)

- Update `trigger_extraction` test to verify `force_reprocess=true` is sent in the request body to the extractor
- Existing admin endpoint tests remain valid

### Out of Scope

- E2E browser tests for the admin UI (follow-up PR)
- Admin account management via the admin UI (CLI-only for phase 1)
