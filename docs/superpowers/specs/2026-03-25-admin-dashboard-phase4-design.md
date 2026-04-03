# Admin Dashboard Phase 4 — Unified Identity and Audit Log

**Issues:** #139, #104
**Date:** 2026-03-25
**Status:** Approved

## Overview

Two changes to the admin dashboard:

1. **Unified identity** — merge `dashboard_admins` into the `users` table via an `is_admin` flag, eliminating separate admin credentials
1. **Persistent audit log** — record all admin write actions to a new `admin_audit_log` table with a paginated API endpoint and dashboard UI

## Feature 1: Unified Identity

### Schema Changes

**`users` table** — add column:

```sql
ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT FALSE;
```

**`dashboard_admins` table** — remove entirely from `postgres_schema.py` (not deployed, no migration needed).

**`extraction_history.triggered_by`** — FK changes from `dashboard_admins(id)` to `users(id)`.

### Auth Flow

Admin login (`POST /api/admin/auth/login`) queries `users` instead of `dashboard_admins`:

1. Look up user by email in `users` table
1. Verify password with `_verify_password`
1. Check `is_admin = true` — return 403 if not
1. Issue admin JWT with `"type": "admin"` claim

The `require_admin` dependency verifies admin status against the database on every request, not just the JWT claim:

1. Extract `sub` (user ID) from JWT
1. Verify JWT signature (rejects tampered tokens)
1. Check Redis revocation list (rejects logged-out tokens)
1. Query `SELECT is_admin FROM users WHERE id = $1 AND is_active = true`
1. If `is_admin` is not `true` in the DB, return 403

The `"type": "admin"` JWT claim serves as a fast pre-check only. The database is the source of truth.

### Security Layers

1. **JWT signature verification** — HMAC-signed with server-side secret; rejects any tampered payload
1. **DB `is_admin` check** — rejects valid non-admin tokens even if they contain `"type": "admin"`
1. **Redis revocation list** — rejects revoked tokens (logout)

### Admin Promotion

No UI. Admins are promoted via direct SQL:

```sql
UPDATE users SET is_admin = true WHERE email = 'admin@example.com';
```

Same pattern as the existing `discogs-setup` CLI approach.

### Dashboard Access Control

Non-admin users who navigate to the admin dashboard see the login form. Their credentials are rejected with 403 since `is_admin = false`. The frontend already gates all admin content behind a valid admin JWT.

## Feature 2: Persistent Audit Log

### Schema

```sql
CREATE TABLE IF NOT EXISTS admin_audit_log (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_id    UUID NOT NULL REFERENCES users(id),
    action      VARCHAR(100) NOT NULL,
    target      VARCHAR(255),
    details     JSONB,
    created_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON admin_audit_log(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_log_admin_id ON admin_audit_log(admin_id);
```

Data is retained indefinitely in the database. The API defaults to returning the last 90 days.

### Decorator Pattern

A `@audit_log(action="...")` decorator wraps admin endpoint handlers:

- Runs the handler first
- Records the action to `admin_audit_log` after the response is computed
- If the handler raises an exception, records the error in `details`
- If the audit write itself fails, logs a warning but does not fail the request
- Extracts `admin_id` from the resolved `require_admin` dependency
- Populates `target` and `details` from path params, body, or response

**Special case: login/logout.** The login endpoint runs before `require_admin` is available (the user isn't authenticated yet). Login and logout audit entries are recorded inline in the handler rather than via the decorator — login records the looked-up user ID on success, and `null` admin_id on failure; logout extracts admin_id from the token before revocation.

### Audited Actions

| Action               | Target      | Details                    |
| -------------------- | ----------- | -------------------------- |
| `admin.login`        | admin email | `{"success": true/false}`  |
| `admin.logout`       | admin email | `{}`                       |
| `extraction.trigger` | —           | `{"extraction_id": "..."}` |
| `dlq.purge`          | queue name  | `{"purged_count": N}`      |

### API Endpoint

`GET /api/admin/audit-log` — admin-only, paginated:

- **Query params:** `page` (default 1), `page_size` (default 50, max 100), `action` (optional filter), `admin_id` (optional filter)
- **Default window:** last 90 days
- **Response:** `{"entries": [...], "total": N, "page": N, "page_size": N}`

Each entry:

```json
{
  "id": "uuid",
  "admin_id": "uuid",
  "admin_email": "admin@example.com",
  "action": "extraction.trigger",
  "target": null,
  "details": {"extraction_id": "uuid"},
  "created_at": "2026-03-25T12:00:00Z"
}
```

### Dashboard Proxy

`GET /admin/api/audit-log` → `/api/admin/audit-log` (query params forwarded).

### Frontend

New "Audit Log" tab in `admin.html`:

- Paginated table: timestamp, admin email, action, target, details
- Filter dropdown by action type
- Pagination controls (previous/next)
- Auto-refresh every 60 seconds (consistent with other tabs)

## Files Changed

| File                             | Change                                                                                                            |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `schema-init/postgres_schema.py` | Remove `dashboard_admins`, add `is_admin` to `users`, add `admin_audit_log` table, update `extraction_history` FK |
| `api/routers/admin.py`           | Query `users` instead of `dashboard_admins`, add audit log decorator, add `GET /api/admin/audit-log`              |
| `api/admin_auth.py`              | No changes (already generic)                                                                                      |
| `api/dependencies.py`            | Update `require_admin` to check `users.is_admin` with DB verification                                             |
| `api/audit_log.py`               | New — decorator and DB write function                                                                             |
| `api/queries/admin_queries.py`   | Add `get_audit_log` query function                                                                                |
| `api/models.py`                  | Add `AuditLogEntry` and `AuditLogResponse` Pydantic models                                                        |
| `dashboard/admin_proxy.py`       | Add audit-log proxy route                                                                                         |
| `dashboard/static/admin.html`    | Add Audit Log tab                                                                                                 |
| `dashboard/static/admin.js`      | Add audit log fetch, render, filter, pagination                                                                   |
| `tests/api/test_admin.py`        | Update for `users` table, add audit log tests                                                                     |
| `tests/api/test_audit_log.py`    | New — decorator and endpoint tests                                                                                |

## Testing Strategy

- Unit tests for the audit log decorator (mock DB, verify correct action/target/details recorded)
- Unit tests for the `get_audit_log` query function (pagination, filtering, 90-day window)
- Integration tests for updated admin login (verify `users` table lookup, 403 for non-admins)
- Integration tests for `require_admin` DB verification (forged JWT claims rejected)
- Frontend: verify Audit Log tab renders, filters work, pagination works
