# Admin Dashboard Phase 4 — Unified Identity and Audit Log Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge `dashboard_admins` into the `users` table via an `is_admin` flag, and add a persistent audit log for all admin write actions.

**Architecture:** The `dashboard_admins` table is removed entirely (not deployed). The `users` table gains an `is_admin` column. Admin login queries `users` directly, and `require_admin` verifies `is_admin` against the database on every request. A new `admin_audit_log` table records all admin write actions via an `@audit_log` decorator, exposed through a paginated API endpoint.

**Tech Stack:** Python 3.13+, FastAPI, psycopg3 (async), Pydantic v2, structlog, vanilla JS/HTML frontend

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `schema-init/postgres_schema.py` | Modify | Remove `dashboard_admins`, add `is_admin` to `users`, update `extraction_history` FK, add `admin_audit_log` |
| `api/dependencies.py` | Modify | Add DB-verified `require_admin` with pool configuration |
| `api/audit_log.py` | Create | `record_audit_entry()` function for writing audit log entries |
| `api/queries/admin_queries.py` | Modify | Add `get_audit_log()` query function |
| `api/models.py` | Modify | Add `AuditLogEntry` and `AuditLogResponse` models |
| `api/routers/admin.py` | Modify | Query `users` for login, add inline audit logging, add audit-log endpoint |
| `dashboard/admin_proxy.py` | Modify | Add audit-log proxy route |
| `dashboard/static/admin.html` | Modify | Add Audit Log tab |
| `dashboard/static/admin.js` | Modify | Add audit log fetch, render, filter, pagination |
| `tests/api/test_dependencies.py` | Modify | Update `require_admin` tests for DB verification |
| `tests/api/test_admin_endpoints.py` | Modify | Update login tests for `users` table, add audit log endpoint tests |
| `tests/api/test_audit_log.py` | Create | Tests for `record_audit_entry()` |
| `tests/api/conftest.py` | Modify | Update `_admin_router.configure` if signature changes |
| `tests/dashboard/test_admin_proxy.py` | Modify | Add audit-log proxy test |

---

### Task 1: Schema Changes — Remove `dashboard_admins`, Add `is_admin`, Add `admin_audit_log`

**Files:**
- Modify: `schema-init/postgres_schema.py:88-288`

- [ ] **Step 1: Update `users` table to include `is_admin`**

In `schema-init/postgres_schema.py`, update the `users table` entry in `_USER_TABLES` (line 90-101):

```python
    (
        "users table",
        """
        CREATE TABLE IF NOT EXISTS users (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email           VARCHAR(255) UNIQUE NOT NULL,
            hashed_password VARCHAR(255) NOT NULL,
            is_active       BOOLEAN NOT NULL DEFAULT TRUE,
            is_admin        BOOLEAN NOT NULL DEFAULT FALSE,
            created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
        """,
    ),
```

- [ ] **Step 2: Remove `dashboard_admins` table definition**

Delete the `dashboard_admins` tuple (lines 216-227):

```python
    # DELETE THIS ENTIRE TUPLE:
    (
        "dashboard_admins",
        """
        CREATE TABLE IF NOT EXISTS dashboard_admins (
            ...
        )
        """,
    ),
```

- [ ] **Step 3: Update `extraction_history` FK to reference `users`**

Change the `extraction_history` tuple (lines 229-243) so `triggered_by` references `users(id)`:

```python
    (
        "extraction_history",
        """
        CREATE TABLE IF NOT EXISTS extraction_history (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            triggered_by UUID NOT NULL REFERENCES users(id),
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            started_at TIMESTAMP WITH TIME ZONE,
            completed_at TIMESTAMP WITH TIME ZONE,
            record_counts JSONB,
            error_message TEXT,
            extractor_version VARCHAR(50),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
        """,
    ),
```

- [ ] **Step 4: Add `admin_audit_log` table and indexes**

After the `service_health_metrics` index tuple (line 287), add:

```python
    (
        "admin_audit_log table",
        """
        CREATE TABLE IF NOT EXISTS admin_audit_log (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            admin_id UUID NOT NULL REFERENCES users(id),
            action VARCHAR(100) NOT NULL,
            target VARCHAR(255),
            details JSONB,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
        """,
    ),
    (
        "idx_audit_log_created_at",
        "CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON admin_audit_log(created_at)",
    ),
    (
        "idx_audit_log_admin_id",
        "CREATE INDEX IF NOT EXISTS idx_audit_log_admin_id ON admin_audit_log(admin_id)",
    ),
```

- [ ] **Step 5: Run schema-init tests**

Run: `uv run pytest tests/schema-init/ -v`
Expected: All existing tests pass (schema definitions are validated structurally, no runtime DB needed).

- [ ] **Step 6: Commit**

```bash
git add schema-init/postgres_schema.py
git commit -m "feat(schema): unify users/admins table, add admin_audit_log (#139)"
```

---

### Task 2: Update `require_admin` to Verify `is_admin` Against the Database

**Files:**
- Modify: `api/dependencies.py`
- Test: `tests/api/test_dependencies.py`

- [ ] **Step 1: Write failing tests for DB-verified `require_admin`**

Add these tests to `tests/api/test_dependencies.py` at the end of the `TestRequireAdmin` class. First, add imports at the top of the file:

```python
from unittest.mock import AsyncMock, MagicMock
```

Then add a helper after `_make_valid_token`:

```python
def _make_admin_token(
    admin_id: str = "admin-1",
    email: str = "admin@test.com",
    secret: str = TEST_SECRET,
) -> str:
    """Create a valid admin JWT for testing."""
    import base64
    import hashlib
    import hmac
    import json

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = b64url(
        json.dumps(
            {"sub": admin_id, "email": email, "exp": 9_999_999_999, "type": "admin", "jti": "admin:test123"},
            separators=(",", ":"),
        ).encode()
    )
    signing_input = f"{header}.{body}".encode("ascii")
    sig = b64url(hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest())
    return f"{header}.{body}.{sig}"
```

Then add tests to the `TestRequireAdmin` class:

```python
    @pytest.mark.asyncio
    async def test_raises_403_when_type_is_not_admin(self) -> None:
        configure(TEST_SECRET)
        from fastapi import HTTPException

        token = _make_valid_token()
        creds = _make_credentials(token)
        with pytest.raises(HTTPException) as exc_info:
            await require_admin(creds)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_raises_401_when_no_credentials(self) -> None:
        configure(TEST_SECRET)
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await require_admin(None)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_raises_401_for_invalid_token(self) -> None:
        configure(TEST_SECRET)
        from fastapi import HTTPException

        creds = _make_credentials("bad.token.value")
        with pytest.raises(HTTPException) as exc_info:
            await require_admin(creds)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_db_verified_admin_succeeds(self) -> None:
        """Valid admin token + DB confirms is_admin=True -> returns payload."""
        mock_pool = MagicMock()
        mock_cur = AsyncMock()
        mock_cur.fetchone = AsyncMock(return_value={"is_admin": True})
        mock_conn = AsyncMock()
        cur_ctx = AsyncMock()
        cur_ctx.__aenter__ = AsyncMock(return_value=mock_cur)
        cur_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_conn.cursor = MagicMock(return_value=cur_ctx)
        conn_ctx = AsyncMock()
        conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        conn_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_pool.connection = MagicMock(return_value=conn_ctx)

        configure(TEST_SECRET, pool=mock_pool)

        token = _make_admin_token()
        creds = _make_credentials(token)
        result = await require_admin(creds)
        assert result["sub"] == "admin-1"
        assert result["type"] == "admin"

    @pytest.mark.asyncio
    async def test_db_verified_admin_rejects_non_admin(self) -> None:
        """Valid admin token but DB says is_admin=False -> 403."""
        mock_pool = MagicMock()
        mock_cur = AsyncMock()
        mock_cur.fetchone = AsyncMock(return_value={"is_admin": False})
        mock_conn = AsyncMock()
        cur_ctx = AsyncMock()
        cur_ctx.__aenter__ = AsyncMock(return_value=mock_cur)
        cur_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_conn.cursor = MagicMock(return_value=cur_ctx)
        conn_ctx = AsyncMock()
        conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        conn_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_pool.connection = MagicMock(return_value=conn_ctx)

        configure(TEST_SECRET, pool=mock_pool)
        from fastapi import HTTPException

        token = _make_admin_token()
        creds = _make_credentials(token)
        with pytest.raises(HTTPException) as exc_info:
            await require_admin(creds)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_db_verified_admin_rejects_missing_user(self) -> None:
        """Valid admin token but user not found in DB -> 403."""
        mock_pool = MagicMock()
        mock_cur = AsyncMock()
        mock_cur.fetchone = AsyncMock(return_value=None)
        mock_conn = AsyncMock()
        cur_ctx = AsyncMock()
        cur_ctx.__aenter__ = AsyncMock(return_value=mock_cur)
        cur_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_conn.cursor = MagicMock(return_value=cur_ctx)
        conn_ctx = AsyncMock()
        conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        conn_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_pool.connection = MagicMock(return_value=conn_ctx)

        configure(TEST_SECRET, pool=mock_pool)
        from fastapi import HTTPException

        token = _make_admin_token()
        creds = _make_credentials(token)
        with pytest.raises(HTTPException) as exc_info:
            await require_admin(creds)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_revoked_token_rejected(self) -> None:
        """Valid admin token but revoked in Redis -> 401."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="1")
        configure(TEST_SECRET, redis=mock_redis)
        from fastapi import HTTPException

        token = _make_admin_token()
        creds = _make_credentials(token)
        with pytest.raises(HTTPException) as exc_info:
            await require_admin(creds)
        assert exc_info.value.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_dependencies.py::TestRequireAdmin -v`
Expected: New DB-verified tests fail (current `require_admin` doesn't accept `pool` or check DB).

- [ ] **Step 3: Update `configure()` and `require_admin` in `api/dependencies.py`**

Update `api/dependencies.py` to accept a pool and verify `is_admin` in the DB:

```python
"""Shared FastAPI dependency functions for API routers."""

from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.auth import decode_token


_security = HTTPBearer(auto_error=False)
_jwt_secret: str | None = None
_redis: Any = None
_pool: Any = None


def configure(jwt_secret: str | None, redis: Any = None, pool: Any = None) -> None:
    global _jwt_secret, _redis, _pool
    _jwt_secret = jwt_secret
    _redis = redis
    _pool = pool


async def get_optional_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_security)],
) -> dict[str, Any] | None:
    if credentials is None or _jwt_secret is None:
        return None
    try:
        return decode_token(credentials.credentials, _jwt_secret)
    except ValueError:
        return None


async def require_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_security)],
) -> dict[str, Any]:
    if _jwt_secret is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Personalized endpoints not enabled")
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required", headers={"WWW-Authenticate": "Bearer"})
    try:
        return decode_token(credentials.credentials, _jwt_secret)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token", headers={"WWW-Authenticate": "Bearer"}
        ) from exc


async def require_admin(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_security)],
) -> dict[str, Any]:
    """Require a valid admin JWT token with DB verification of is_admin."""
    if _jwt_secret is None:
        raise HTTPException(status_code=503, detail="Admin endpoints not configured")
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        payload = decode_token(credentials.credentials, _jwt_secret)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
    # Fast pre-check: reject tokens that don't claim admin type
    if payload.get("type") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    # Check token revocation in Redis
    jti: str | None = payload.get("jti")
    if jti and _redis:
        revoked = await _redis.get(f"revoked:jti:{jti}")
        if revoked:
            raise HTTPException(status_code=401, detail="Token has been revoked")
    # DB verification: confirm user exists and is_admin=True
    if _pool is not None:
        from psycopg.rows import dict_row

        async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT is_admin FROM users WHERE id = %s AND is_active = true",
                (payload["sub"],),
            )
            row = await cur.fetchone()
        if row is None or not row["is_admin"]:
            raise HTTPException(status_code=403, detail="Admin access required")
    return payload
```

- [ ] **Step 4: Update `configure()` calls that pass dependencies**

In `api/api.py`, find the `dependencies.configure` call in the lifespan and add `pool=_pool`:

```python
# Find this line:
dependencies.configure(config.jwt_secret_key, _redis)
# Replace with:
dependencies.configure(config.jwt_secret_key, _redis, pool=_pool)
```

In `tests/api/conftest.py`, after the `_admin_router.configure(...)` line (line 198), add:

```python
    import api.dependencies as _deps
    _deps.configure(TEST_JWT_SECRET, mock_redis, pool=mock_pool)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_dependencies.py -v`
Expected: All tests pass including new DB-verified admin tests.

- [ ] **Step 6: Commit**

```bash
git add api/dependencies.py tests/api/test_dependencies.py tests/api/conftest.py
git commit -m "feat(auth): verify is_admin against DB in require_admin (#139)"
```

---

### Task 3: Create `record_audit_entry()` Function

**Files:**
- Create: `api/audit_log.py`
- Create: `tests/api/test_audit_log.py`

- [ ] **Step 1: Write failing tests for `record_audit_entry`**

Create `tests/api/test_audit_log.py`:

```python
"""Tests for admin audit log recording."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.audit_log import record_audit_entry


def _make_mock_pool(mock_cur: AsyncMock | None = None) -> tuple[MagicMock, AsyncMock]:
    """Create a mock pool with optional pre-configured cursor."""
    if mock_cur is None:
        mock_cur = AsyncMock()
        mock_cur.execute = AsyncMock()
    pool = MagicMock()
    mock_conn = AsyncMock()
    cur_ctx = AsyncMock()
    cur_ctx.__aenter__ = AsyncMock(return_value=mock_cur)
    cur_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_conn.cursor = MagicMock(return_value=cur_ctx)
    conn_ctx = AsyncMock()
    conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    conn_ctx.__aexit__ = AsyncMock(return_value=False)
    pool.connection = MagicMock(return_value=conn_ctx)
    return pool, mock_cur


class TestRecordAuditEntry:
    @pytest.mark.asyncio
    async def test_records_action_with_all_fields(self) -> None:
        pool, mock_cur = _make_mock_pool()
        await record_audit_entry(
            pool=pool,
            admin_id="admin-uuid-123",
            action="extraction.trigger",
            target=None,
            details={"extraction_id": "ext-uuid-456"},
        )
        mock_cur.execute.assert_called_once()
        call_args = mock_cur.execute.call_args
        sql = call_args[0][0]
        params = call_args[0][1]
        assert "admin_audit_log" in sql
        assert params[0] == "admin-uuid-123"
        assert params[1] == "extraction.trigger"
        assert params[2] is None  # target
        assert '"extraction_id"' in params[3]  # details JSON string

    @pytest.mark.asyncio
    async def test_records_action_with_target(self) -> None:
        pool, mock_cur = _make_mock_pool()
        await record_audit_entry(
            pool=pool,
            admin_id="admin-uuid-123",
            action="dlq.purge",
            target="graphinator-artists-dlq",
            details={"purged_count": 5},
        )
        mock_cur.execute.assert_called_once()
        params = mock_cur.execute.call_args[0][1]
        assert params[1] == "dlq.purge"
        assert params[2] == "graphinator-artists-dlq"

    @pytest.mark.asyncio
    async def test_records_action_without_details(self) -> None:
        pool, mock_cur = _make_mock_pool()
        await record_audit_entry(
            pool=pool,
            admin_id="admin-uuid-123",
            action="admin.logout",
            target="admin@test.com",
        )
        mock_cur.execute.assert_called_once()
        params = mock_cur.execute.call_args[0][1]
        assert params[3] is None  # details

    @pytest.mark.asyncio
    async def test_does_not_raise_on_db_error(self) -> None:
        """Audit log failures should not crash the request."""
        pool, mock_cur = _make_mock_pool()
        mock_cur.execute = AsyncMock(side_effect=Exception("DB connection lost"))
        # Should not raise
        await record_audit_entry(
            pool=pool,
            admin_id="admin-uuid-123",
            action="admin.login",
            target="admin@test.com",
        )

    @pytest.mark.asyncio
    async def test_skips_when_pool_is_none(self) -> None:
        """No-op when pool is None."""
        # Should not raise
        await record_audit_entry(
            pool=None,
            admin_id="admin-uuid-123",
            action="admin.login",
            target="admin@test.com",
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_audit_log.py -v`
Expected: ImportError — `api.audit_log` does not exist.

- [ ] **Step 3: Implement `record_audit_entry`**

Create `api/audit_log.py`:

```python
"""Admin audit log — records admin actions to the admin_audit_log table."""

from __future__ import annotations

import json
from typing import Any

import structlog


logger = structlog.get_logger(__name__)


async def record_audit_entry(
    *,
    pool: Any,
    admin_id: str,
    action: str,
    target: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Write an audit log entry. Never raises — failures are logged as warnings."""
    if pool is None:
        return
    try:
        details_json = json.dumps(details) if details else None
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO admin_audit_log (admin_id, action, target, details) VALUES (%s::uuid, %s, %s, %s::jsonb)",
                (admin_id, action, target, details_json),
            )
        logger.debug("📋 Audit entry recorded", action=action, admin_id=admin_id)
    except Exception:
        logger.warning("⚠️ Failed to record audit entry", action=action, admin_id=admin_id, exc_info=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_audit_log.py -v`
Expected: All 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add api/audit_log.py tests/api/test_audit_log.py
git commit -m "feat(audit): add record_audit_entry function (#139)"
```

---

### Task 4: Add Pydantic Models for Audit Log

**Files:**
- Modify: `api/models.py:368-370`

- [ ] **Step 1: Add audit log models**

After the `DlqPurgeResponse` model in `api/models.py` (around line 370), add:

```python
class AuditLogEntry(BaseModel):
    id: UUID
    admin_id: UUID
    admin_email: str
    action: str
    target: str | None
    details: dict[str, Any] | None
    created_at: datetime


class AuditLogResponse(BaseModel):
    entries: list[AuditLogEntry]
    total: int
    page: int
    page_size: int
```

Ensure `Any` is imported from `typing` (it should already be) and `UUID` from `uuid` and `datetime` from `datetime` (both should already be imported at the top of the file).

- [ ] **Step 2: Run model tests**

Run: `uv run pytest tests/api/test_api_models.py -v`
Expected: Existing model tests still pass.

- [ ] **Step 3: Commit**

```bash
git add api/models.py
git commit -m "feat(models): add AuditLogEntry and AuditLogResponse (#139)"
```

---

### Task 5: Add `get_audit_log` Query Function

**Files:**
- Modify: `api/queries/admin_queries.py`
- Test: `tests/api/test_admin_queries.py`

- [ ] **Step 1: Write failing tests for `get_audit_log`**

Add to `tests/api/test_admin_queries.py`. Ensure the file imports `datetime` and `UTC` from `datetime`, and `AsyncMock`, `MagicMock` from `unittest.mock`:

```python
class TestGetAuditLog:
    @pytest.mark.asyncio
    async def test_returns_paginated_entries(self) -> None:
        from api.queries.admin_queries import get_audit_log

        mock_cur = AsyncMock()
        mock_cur.fetchone = AsyncMock(return_value={"total": 2})
        mock_cur.fetchall = AsyncMock(
            return_value=[
                {
                    "id": "uuid-1",
                    "admin_id": "admin-uuid",
                    "admin_email": "admin@test.com",
                    "action": "admin.login",
                    "target": "admin@test.com",
                    "details": {"success": True},
                    "created_at": datetime.now(UTC),
                },
                {
                    "id": "uuid-2",
                    "admin_id": "admin-uuid",
                    "admin_email": "admin@test.com",
                    "action": "dlq.purge",
                    "target": "graphinator-artists-dlq",
                    "details": {"purged_count": 3},
                    "created_at": datetime.now(UTC),
                },
            ]
        )
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

        result = await get_audit_log(pool, page=1, page_size=50)
        assert result["total"] == 2
        assert len(result["entries"]) == 2
        assert result["page"] == 1
        assert result["page_size"] == 50

    @pytest.mark.asyncio
    async def test_filters_by_action(self) -> None:
        from api.queries.admin_queries import get_audit_log

        mock_cur = AsyncMock()
        mock_cur.fetchone = AsyncMock(return_value={"total": 0})
        mock_cur.fetchall = AsyncMock(return_value=[])
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

        await get_audit_log(pool, page=1, page_size=50, action_filter="dlq.purge")

        # Verify the SQL includes action filter
        count_call = mock_cur.execute.call_args_list[0]
        assert "action = %s" in count_call[0][0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_admin_queries.py::TestGetAuditLog -v`
Expected: ImportError or AttributeError — `get_audit_log` does not exist.

- [ ] **Step 3: Implement `get_audit_log` query function**

Add to `api/queries/admin_queries.py`:

```python
async def get_audit_log(
    pool: Any,
    page: int = 1,
    page_size: int = 50,
    action_filter: str | None = None,
    admin_id_filter: str | None = None,
) -> dict[str, Any]:
    """Fetch paginated audit log entries (last 90 days by default)."""
    from psycopg.rows import dict_row

    where_clauses = ["a.created_at >= NOW() - INTERVAL '90 days'"]
    params: list[Any] = []

    if action_filter:
        where_clauses.append("a.action = %s")
        params.append(action_filter)
    if admin_id_filter:
        where_clauses.append("a.admin_id = %s::uuid")
        params.append(admin_id_filter)

    where_sql = " AND ".join(where_clauses)
    offset = (page - 1) * page_size

    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            f"SELECT count(*) AS total FROM admin_audit_log a WHERE {where_sql}",  # noqa: S608
            params,
        )
        total_row = await cur.fetchone()
        total = total_row["total"] if total_row else 0

        await cur.execute(
            f"""SELECT a.id, a.admin_id, u.email AS admin_email, a.action, a.target, a.details, a.created_at
                FROM admin_audit_log a
                JOIN users u ON u.id = a.admin_id
                WHERE {where_sql}
                ORDER BY a.created_at DESC
                LIMIT %s OFFSET %s""",  # noqa: S608
            [*params, page_size, offset],
        )
        entries = await cur.fetchall()

    return {
        "entries": entries,
        "total": total,
        "page": page,
        "page_size": page_size,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_admin_queries.py::TestGetAuditLog -v`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add api/queries/admin_queries.py tests/api/test_admin_queries.py
git commit -m "feat(queries): add get_audit_log query function (#139)"
```

---

### Task 6: Update Admin Router — Login Queries `users`, Add Audit Logging, Add Audit Log Endpoint

**Files:**
- Modify: `api/routers/admin.py`
- Modify: `tests/api/test_admin_endpoints.py`

- [ ] **Step 1: Write failing tests for updated login and audit log endpoint**

In `tests/api/test_admin_endpoints.py`, update `_make_admin_row` (around line 69) to include `is_admin`:

```python
def _make_admin_row(
    admin_id: str = TEST_ADMIN_ID,
    email: str = TEST_ADMIN_EMAIL,
    is_active: bool = True,
    is_admin: bool = True,
    password: str | None = None,
) -> dict[str, Any]:
    """Create a sample users DB row for an admin."""
    if password is None:
        password = "adminpassword123"
    return {
        "id": admin_id,
        "email": email,
        "hashed_password": _hash_password(password),
        "is_active": is_active,
        "is_admin": is_admin,
        "created_at": datetime.now(UTC),
    }
```

Add a test to `TestAdminLogin` for non-admin user:

```python
    def test_non_admin_user_gets_403(self, test_client: TestClient, mock_cur: AsyncMock) -> None:
        admin_row = _make_admin_row(is_admin=False)
        mock_cur.fetchone = AsyncMock(return_value=admin_row)

        resp = test_client.post(
            "/api/admin/auth/login",
            json={"email": TEST_ADMIN_EMAIL, "password": "adminpassword123"},
        )
        assert resp.status_code == 403
```

Add a new test class for the audit log endpoint:

```python
class TestAuditLog:
    @patch("api.routers.admin.get_audit_log")
    def test_list_audit_log(self, mock_get_audit_log: Any, test_client: TestClient) -> None:
        mock_get_audit_log.return_value = {
            "entries": [
                {
                    "id": "uuid-1",
                    "admin_id": TEST_ADMIN_ID,
                    "admin_email": TEST_ADMIN_EMAIL,
                    "action": "admin.login",
                    "target": TEST_ADMIN_EMAIL,
                    "details": {"success": True},
                    "created_at": datetime.now(UTC).isoformat(),
                },
            ],
            "total": 1,
            "page": 1,
            "page_size": 50,
        }

        resp = test_client.get(
            "/api/admin/audit-log",
            headers=_admin_auth_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["entries"]) == 1
        assert data["entries"][0]["action"] == "admin.login"

    def test_audit_log_requires_admin(self, test_client: TestClient) -> None:
        resp = test_client.get("/api/admin/audit-log")
        assert resp.status_code in (401, 403)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_admin_endpoints.py::TestAdminLogin::test_non_admin_user_gets_403 tests/api/test_admin_endpoints.py::TestAuditLog -v`
Expected: Tests fail (login doesn't check `is_admin`, audit-log endpoint doesn't exist).

- [ ] **Step 3: Update admin router**

In `api/routers/admin.py`, make these changes:

**a. Add imports:**

```python
from api.audit_log import record_audit_entry
from api.queries.admin_queries import (
    get_audit_log,
    get_neo4j_storage,
    get_postgres_storage,
    get_redis_storage,
    get_sync_activity,
    get_user_stats,
)
```

**b. Update `admin_login` SQL query (line 80-84) to use `users` table:**

```python
        await cur.execute(
            "SELECT id, email, hashed_password, is_active, is_admin FROM users WHERE email = %s",
            (body.email,),
        )
        admin = await cur.fetchone()
```

**c. After the password check (lines 91-93), add `is_admin` check and audit logging:**

Replace lines 91-93 with:

```python
    password_ok = verify_admin_password(body.password, admin["hashed_password"])
    if not admin["is_active"] or not password_ok:
        await record_audit_entry(pool=_pool, admin_id=str(admin["id"]), action="admin.login", target=body.email, details={"success": False})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")

    if not admin.get("is_admin"):
        await record_audit_entry(pool=_pool, admin_id=str(admin["id"]), action="admin.login", target=body.email, details={"success": False, "reason": "not_admin"})
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
```

**d. After the token creation and before the return (after line 96), add success audit entry:**

```python
    await record_audit_entry(pool=_pool, admin_id=str(admin["id"]), action="admin.login", target=body.email, details={"success": True})
```

**e. In `admin_logout`, after the Redis revocation block (after line 114), add:**

```python
    admin_email = current_admin.get("email", "unknown")
    await record_audit_entry(pool=_pool, admin_id=current_admin["sub"], action="admin.logout", target=admin_email)
```

**f. In `trigger_extraction`, after the successful trigger log (line 420), add:**

```python
            await record_audit_entry(pool=_pool, admin_id=str(admin_id), action="extraction.trigger", details={"extraction_id": extraction_id})
```

**g. In `purge_dlq`, after the existing log line (line 502), add:**

```python
    await record_audit_entry(pool=_pool, admin_id=current_admin["sub"], action="dlq.purge", target=queue, details={"purged_count": messages_purged})
```

**h. Add audit log endpoint after the DLQ purge endpoint:**

```python
# ---------------------------------------------------------------------------
# Phase 4 — Audit Log
# ---------------------------------------------------------------------------


@router.get("/api/admin/audit-log")
async def list_audit_log(
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
    page: int = 1,
    page_size: int = 50,
    action: str | None = None,
    admin_id: str | None = None,
) -> JSONResponse:
    """Paginated admin audit log (last 90 days by default)."""
    if _pool is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")

    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)

    data = await get_audit_log(_pool, page=page, page_size=page_size, action_filter=action, admin_id_filter=admin_id)
    return JSONResponse(content=data)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_admin_endpoints.py -v`
Expected: All tests pass including new ones.

- [ ] **Step 5: Commit**

```bash
git add api/routers/admin.py tests/api/test_admin_endpoints.py
git commit -m "feat(admin): unify login with users table, add audit logging and endpoint (#139)"
```

---

### Task 7: Update `api/api.py` Lifespan — Pass Pool to Dependencies

**Files:**
- Modify: `api/api.py`
- Modify: `tests/api/conftest.py`

- [ ] **Step 1: Update `api/api.py` to pass pool to dependencies.configure**

Find the `dependencies.configure` call in the lifespan and add `pool=_pool`:

```python
# Find this line:
dependencies.configure(config.jwt_secret_key, _redis)
# Replace with:
dependencies.configure(config.jwt_secret_key, _redis, pool=_pool)
```

- [ ] **Step 2: Update test conftest**

In `tests/api/conftest.py`, after the `_admin_router.configure(...)` line (line 198), add:

```python
    import api.dependencies as _deps
    _deps.configure(TEST_JWT_SECRET, mock_redis, pool=mock_pool)
```

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest tests/api/ -v --timeout=60`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add api/api.py tests/api/conftest.py
git commit -m "feat(api): pass pool to dependencies for DB-verified admin auth (#139)"
```

---

### Task 8: Add Audit Log Proxy Route

**Files:**
- Modify: `dashboard/admin_proxy.py`
- Test: `tests/dashboard/test_admin_proxy.py`

- [ ] **Step 1: Add audit-log proxy route**

At the end of `dashboard/admin_proxy.py`, add:

```python
# ---------------------------------------------------------------------------
# Phase 4 — Audit Log proxy route
# ---------------------------------------------------------------------------


@router.get("/admin/api/audit-log")
async def proxy_audit_log(
    request: Request,
    page: int | None = Query(default=None, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=100),
    action: str | None = Query(default=None, pattern=r"^[a-z][a-z0-9_.]+$"),
    admin_id: str | None = Query(default=None, pattern=r"^[a-f0-9-]+$"),
) -> Response:
    """Proxy audit log requests to the API service."""
    url = _build_url("/api/admin/audit-log")
    params: dict[str, str] = {}
    if page is not None:
        params["page"] = str(page)
    if page_size is not None:
        params["page_size"] = str(page_size)
    if action is not None:
        params["action"] = action
    if admin_id is not None:
        params["admin_id"] = admin_id
    headers = _auth_headers(request)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers, params=params)
    except (httpx.ConnectError, httpx.RequestError) as exc:
        logger.error("❌ API service unreachable", url=url, error=str(exc))
        return _unavailable_response()
    return _ok_response(resp)
```

- [ ] **Step 2: Add test for audit-log proxy**

In `tests/dashboard/test_admin_proxy.py`, add a test (follow the existing pattern in the file):

```python
class TestAuditLogProxy:
    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_proxy_audit_log(self, mock_client_cls, dashboard_client):
        mock_resp = MagicMock()
        mock_resp.content = b'{"entries":[],"total":0,"page":1,"page_size":50}'
        mock_resp.status_code = 200
        mock_instance = AsyncMock()
        mock_instance.get = AsyncMock(return_value=mock_resp)
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_instance

        resp = dashboard_client.get(
            "/admin/api/audit-log",
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 200
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/dashboard/test_admin_proxy.py -v`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add dashboard/admin_proxy.py tests/dashboard/test_admin_proxy.py
git commit -m "feat(proxy): add audit-log proxy route (#139)"
```

---

### Task 9: Frontend — Add Audit Log Tab

**Files:**
- Modify: `dashboard/static/admin.html`
- Modify: `dashboard/static/admin.js`

- [ ] **Step 1: Add Audit Log tab button to `admin.html`**

Find the tab navigation buttons (around line 279, after the System Health button). Add:

```html
<button class="tab-btn" data-tab="audit-log" id="tab-btn-audit-log">
    <span class="material-symbols-outlined text-sm">history</span> Audit Log
</button>
```

- [ ] **Step 2: Add Audit Log tab content section to `admin.html`**

After the last tab content `div` (the `tab-system-health` section), add:

```html
<!-- Audit Log Tab -->
<div id="tab-audit-log" class="space-y-6" style="display:none">
    <section class="dashboard-card p-6">
        <div class="flex items-center justify-between mb-4 border-b b-theme pb-4">
            <h3 class="text-sm font-semibold flex items-center gap-2">
                <span class="material-symbols-outlined text-sm t-dim">history</span> Admin Audit Log
            </h3>
            <div class="flex items-center gap-3">
                <select id="al-action-filter" class="text-xs bg-transparent border b-theme rounded px-2 py-1">
                    <option value="">All Actions</option>
                    <option value="admin.login">Login</option>
                    <option value="admin.logout">Logout</option>
                    <option value="extraction.trigger">Extraction Trigger</option>
                    <option value="dlq.purge">DLQ Purge</option>
                </select>
                <span class="text-[10px] t-muted">Auto-refresh 60s</span>
                <span id="al-loading" class="text-xs t-muted" style="display:none">Loading...</span>
                <span id="al-error" class="text-xs text-amber-500 flex items-center gap-1" style="display:none">
                    <span class="material-symbols-outlined text-xs">warning</span>
                    <span id="al-error-msg"></span>
                </span>
                <button id="al-refresh-btn" class="text-xs font-bold uppercase tracking-wider t-dim hover:t-primary transition-colors flex items-center gap-1">
                    <span class="material-symbols-outlined text-sm">refresh</span> Refresh
                </button>
            </div>
        </div>
        <div class="overflow-x-auto">
            <table class="w-full text-xs">
                <thead>
                    <tr class="border-b b-theme">
                        <th class="text-left py-2 px-3 t-muted font-medium">Timestamp</th>
                        <th class="text-left py-2 px-3 t-muted font-medium">Admin</th>
                        <th class="text-left py-2 px-3 t-muted font-medium">Action</th>
                        <th class="text-left py-2 px-3 t-muted font-medium">Target</th>
                        <th class="text-left py-2 px-3 t-muted font-medium">Details</th>
                    </tr>
                </thead>
                <tbody id="al-table-body">
                    <tr><td colspan="5" class="text-center py-8 t-muted">Loading...</td></tr>
                </tbody>
            </table>
        </div>
        <div id="al-pagination" class="flex items-center justify-between mt-4 pt-4 border-t b-theme" style="display:none">
            <span id="al-page-info" class="text-xs t-muted"></span>
            <div class="flex gap-2">
                <button id="al-prev-btn" class="text-xs font-bold uppercase tracking-wider t-dim hover:t-primary transition-colors px-3 py-1 border b-theme rounded" disabled>Previous</button>
                <button id="al-next-btn" class="text-xs font-bold uppercase tracking-wider t-dim hover:t-primary transition-colors px-3 py-1 border b-theme rounded" disabled>Next</button>
            </div>
        </div>
    </section>
</div>
```

- [ ] **Step 3: Update `admin.js` — add `audit-log` to panels array**

Find the `switchTab` method and the `panels` array (containing `'extractions', 'dlq', 'users', 'storage', 'queue-trends', 'system-health'`). Add `'audit-log'`:

```javascript
const panels = ['extractions', 'dlq', 'users', 'storage', 'queue-trends', 'system-health', 'audit-log'];
```

- [ ] **Step 4: Update `admin.js` — add state and event bindings**

In the constructor, add:

```javascript
this._auditLogPage = 1;
```

In `bindEvents()`, add:

```javascript
const alRefreshBtn = document.getElementById('al-refresh-btn');
if (alRefreshBtn) alRefreshBtn.addEventListener('click', () => this.fetchAuditLog());

const alActionFilter = document.getElementById('al-action-filter');
if (alActionFilter) alActionFilter.addEventListener('change', () => { this._auditLogPage = 1; this.fetchAuditLog(); });

const alPrevBtn = document.getElementById('al-prev-btn');
if (alPrevBtn) alPrevBtn.addEventListener('click', () => { if (this._auditLogPage > 1) { this._auditLogPage--; this.fetchAuditLog(); } });

const alNextBtn = document.getElementById('al-next-btn');
if (alNextBtn) alNextBtn.addEventListener('click', () => { this._auditLogPage++; this.fetchAuditLog(); });
```

- [ ] **Step 5: Update `admin.js` — add tab switch and auto-refresh handlers**

In the `switchTab` method, find the `else if` chain for tab-specific data loading. Add:

```javascript
} else if (tabName === 'audit-log') {
    this.fetchAuditLog();
}
```

In `startAutoRefresh`, add to the `else if` chain:

```javascript
} else if (this.activeTab === 'audit-log') {
    this.fetchAuditLog();
}
```

- [ ] **Step 6: Update `admin.js` — add `fetchAuditLog` and `renderAuditLog` methods**

Add these methods to the `AdminDashboard` class. The `renderAuditLog` method uses safe DOM manipulation (no raw HTML injection):

```javascript
async fetchAuditLog() {
    const loading = document.getElementById('al-loading');
    const error = document.getElementById('al-error');
    const errorMsg = document.getElementById('al-error-msg');

    if (loading) loading.style.display = '';
    if (error) error.style.display = 'none';

    const actionFilter = document.getElementById('al-action-filter')?.value || '';
    let url = `/admin/api/audit-log?page=${this._auditLogPage}&page_size=50`;
    if (actionFilter) url += `&action=${encodeURIComponent(actionFilter)}`;

    try {
        const resp = await this.authFetch(url);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        this.renderAuditLog(data);
    } catch (err) {
        if (errorMsg) errorMsg.textContent = err.message;
        if (error) error.style.display = '';
    } finally {
        if (loading) loading.style.display = 'none';
    }
}

renderAuditLog(data) {
    const tbody = document.getElementById('al-table-body');
    if (!tbody) return;

    // Clear existing rows
    while (tbody.firstChild) tbody.removeChild(tbody.firstChild);

    if (!data.entries || data.entries.length === 0) {
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.setAttribute('colspan', '5');
        td.className = 'text-center py-8 t-muted';
        td.textContent = 'No audit log entries';
        tr.appendChild(td);
        tbody.appendChild(tr);
    } else {
        for (const entry of data.entries) {
            const tr = document.createElement('tr');
            tr.className = 'border-b b-theme hover:bg-white/5 transition-colors';

            const tdTs = document.createElement('td');
            tdTs.className = 'py-2 px-3 t-muted whitespace-nowrap';
            tdTs.textContent = new Date(entry.created_at).toLocaleString();
            tr.appendChild(tdTs);

            const tdAdmin = document.createElement('td');
            tdAdmin.className = 'py-2 px-3';
            tdAdmin.textContent = entry.admin_email;
            tr.appendChild(tdAdmin);

            const tdAction = document.createElement('td');
            tdAction.className = 'py-2 px-3';
            const badge = document.createElement('span');
            badge.className = 'inline-block px-2 py-0.5 rounded text-[10px] font-medium bg-blue-500/10 text-blue-400';
            badge.textContent = entry.action;
            tdAction.appendChild(badge);
            tr.appendChild(tdAction);

            const tdTarget = document.createElement('td');
            tdTarget.className = 'py-2 px-3 t-muted';
            tdTarget.textContent = entry.target || '\u2014';
            tr.appendChild(tdTarget);

            const tdDetails = document.createElement('td');
            tdDetails.className = 'py-2 px-3 t-muted text-[10px] font-mono max-w-[200px] truncate';
            const detailsText = entry.details ? JSON.stringify(entry.details) : '\u2014';
            tdDetails.textContent = detailsText;
            tdDetails.title = detailsText;
            tr.appendChild(tdDetails);

            tbody.appendChild(tr);
        }
    }

    // Pagination controls
    const pagination = document.getElementById('al-pagination');
    const pageInfo = document.getElementById('al-page-info');
    const prevBtn = document.getElementById('al-prev-btn');
    const nextBtn = document.getElementById('al-next-btn');

    if (pagination && data.total > 0) {
        pagination.style.display = '';
        const totalPages = Math.ceil(data.total / data.page_size);
        if (pageInfo) pageInfo.textContent = `Page ${data.page} of ${totalPages} (${data.total} entries)`;
        if (prevBtn) prevBtn.disabled = data.page <= 1;
        if (nextBtn) nextBtn.disabled = data.page >= totalPages;
    } else if (pagination) {
        pagination.style.display = 'none';
    }
}
```

- [ ] **Step 7: Run frontend tests**

Run: `just test-js`
Expected: All JavaScript tests pass.

- [ ] **Step 8: Commit**

```bash
git add dashboard/static/admin.html dashboard/static/admin.js
git commit -m "feat(dashboard): add Audit Log tab to admin UI (#139)"
```

---

### Task 10: Run Full Test Suite and Lint

**Files:** None (verification only)

- [ ] **Step 1: Run all Python tests**

Run: `just test`
Expected: All tests pass.

- [ ] **Step 2: Run linting**

Run: `just lint-python`
Expected: No lint errors.

- [ ] **Step 3: Run type checking**

Run: `uv run mypy api/ --ignore-missing-imports`
Expected: No type errors in changed files.

- [ ] **Step 4: Run JavaScript tests**

Run: `just test-js`
Expected: All tests pass.

- [ ] **Step 5: Fix any issues found**

Address any test failures or lint errors before proceeding.

- [ ] **Step 6: Final commit (if any fixes needed)**

```bash
git add -A
git commit -m "fix: resolve lint/test issues for admin phase 4 (#139)"
```
