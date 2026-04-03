# Admin Dashboard Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add admin-only endpoints for extraction history tracking, trigger extraction, and DLQ purge management to the API service.

**Architecture:** New `admin` router in the API service with separate admin auth (JWT with `"type": "admin"` claim), backed by `dashboard_admins` and `extraction_history` PostgreSQL tables. The Rust extractor gets a `POST /trigger` endpoint and an `extraction_status` field in its health response.

**Tech Stack:** Python 3.13+ / FastAPI / psycopg / aioredis (API side), Rust / axum / tokio (extractor side)

______________________________________________________________________

## Chunk 1: Database Schema & Admin Auth

### Task 1: Add database tables to schema-init

**Files:**

- Modify: `schema-init/postgres_schema.py`

- [ ] **Step 1: Read current schema file**

Read `schema-init/postgres_schema.py` to find the `_USER_TABLES` list (around line 88) where table creation statements are defined.

- [ ] **Step 2: Add dashboard_admins and extraction_history tables**

Add two new table entries to the `_USER_TABLES` list, after the existing `sync_history` entry:

```python
(
    "dashboard_admins",
    """
    CREATE TABLE IF NOT EXISTS dashboard_admins (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        email VARCHAR(255) UNIQUE NOT NULL,
        hashed_password VARCHAR(255) NOT NULL,
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    )
    """,
),
(
    "extraction_history",
    """
    CREATE TABLE IF NOT EXISTS extraction_history (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        triggered_by UUID NOT NULL REFERENCES dashboard_admins(id),
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

Also add indexes to the `_USER_TABLES` list (following the `sync_history` index pattern):

```python
(
    "idx_extraction_history_status",
    "CREATE INDEX IF NOT EXISTS idx_extraction_history_status ON extraction_history(status)",
),
(
    "idx_extraction_history_created_at",
    "CREATE INDEX IF NOT EXISTS idx_extraction_history_created_at ON extraction_history(created_at DESC)",
),
```

- [ ] **Step 3: Commit**

```bash
git add schema-init/postgres_schema.py
git commit -m "feat(schema): add dashboard_admins and extraction_history tables"
```

______________________________________________________________________

### Task 2: Add admin auth module

**Files:**

- Create: `api/admin_auth.py`

- Modify: `api/auth.py` (import reuse)

- [ ] **Step 1: Write test for admin auth functions**

Create `tests/api/test_admin_auth.py`:

```python
"""Tests for admin authentication."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.admin_auth import (
    create_admin_token,
    verify_admin_password,
)
from api.auth import _hash_password


# --- Fixtures ---

TEST_JWT_SECRET = "test-admin-secret-key-for-testing"
TEST_ADMIN_ID = "00000000-0000-0000-0000-000000000099"
TEST_ADMIN_EMAIL = "admin@test.com"


def _decode_jwt_payload(token: str) -> dict:
    """Decode JWT payload without verification (for test assertions)."""
    _, body, _ = token.split(".")
    padding = 4 - len(body) % 4
    if padding != 4:
        body += "=" * padding
    return json.loads(base64.urlsafe_b64decode(body))


# --- create_admin_token ---

class TestCreateAdminToken:
    def test_returns_token_and_ttl(self) -> None:
        token, expires_in = create_admin_token(TEST_ADMIN_ID, TEST_ADMIN_EMAIL, TEST_JWT_SECRET)
        assert isinstance(token, str)
        assert token.count(".") == 2
        assert isinstance(expires_in, int)
        assert expires_in > 0

    def test_token_has_admin_type_claim(self) -> None:
        token, _ = create_admin_token(TEST_ADMIN_ID, TEST_ADMIN_EMAIL, TEST_JWT_SECRET)
        payload = _decode_jwt_payload(token)
        assert payload["type"] == "admin"
        assert payload["sub"] == TEST_ADMIN_ID
        assert payload["email"] == TEST_ADMIN_EMAIL

    def test_token_has_jti_with_admin_prefix(self) -> None:
        token, _ = create_admin_token(TEST_ADMIN_ID, TEST_ADMIN_EMAIL, TEST_JWT_SECRET)
        payload = _decode_jwt_payload(token)
        assert payload["jti"].startswith("admin:")


# --- verify_admin_password ---

class TestVerifyAdminPassword:
    def test_correct_password(self) -> None:
        hashed = _hash_password("securepassword123")
        assert verify_admin_password("securepassword123", hashed) is True

    def test_wrong_password(self) -> None:
        hashed = _hash_password("securepassword123")
        assert verify_admin_password("wrongpassword", hashed) is False

    def test_empty_password(self) -> None:
        hashed = _hash_password("securepassword123")
        assert verify_admin_password("", hashed) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/Robert/Code/public/discogsography-admin-dashboard-104 && uv run pytest tests/api/test_admin_auth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.admin_auth'`

- [ ] **Step 3: Implement admin_auth.py**

Create `api/admin_auth.py`:

```python
"""Admin authentication utilities.

Handles admin-specific JWT creation and password verification.
Admin tokens include "type": "admin" claim and use "admin:" jti prefix
to maintain complete isolation from Discogs user tokens.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta

from api.auth import _verify_password, b64url_encode


def create_admin_token(
    admin_id: str,
    email: str,
    jwt_secret: str,
    expire_minutes: int = 30,
) -> tuple[str, int]:
    """Create a HS256 JWT for an admin user.

    Returns (token, expires_in_seconds).
    """
    expire = datetime.now(UTC) + timedelta(minutes=expire_minutes)
    payload: dict[str, object] = {
        "sub": admin_id,
        "email": email,
        "type": "admin",
        "exp": int(expire.timestamp()),
        "iat": int(datetime.now(UTC).timestamp()),
        "jti": f"admin:{secrets.token_hex(16)}",
    }

    header = b64url_encode(
        json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode()
    )
    body = b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header}.{body}".encode("ascii")
    signature = b64url_encode(
        hmac.new(
            jwt_secret.encode("utf-8"), signing_input, hashlib.sha256
        ).digest()
    )
    return f"{header}.{body}.{signature}", expire_minutes * 60


def verify_admin_password(plain_password: str, hashed_password: str) -> bool:
    """Verify an admin password against its PBKDF2-SHA256 hash."""
    return _verify_password(plain_password, hashed_password)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/Robert/Code/public/discogsography-admin-dashboard-104 && uv run pytest tests/api/test_admin_auth.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add api/admin_auth.py tests/api/test_admin_auth.py
git commit -m "feat(admin): add admin auth module with JWT creation and password verification"
```

______________________________________________________________________

### Task 3: Add require_admin dependency

**Files:**

- Modify: `api/dependencies.py`

- Modify: `api/api.py` (reject admin tokens in `_get_current_user`)

- [ ] **Step 1: Write tests for require_admin and token isolation**

Add to `tests/api/test_admin_auth.py`:

```python
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from api.dependencies import require_admin


def _make_admin_jwt(
    admin_id: str = TEST_ADMIN_ID,
    email: str = TEST_ADMIN_EMAIL,
    exp: int = 9_999_999_999,
    secret: str = TEST_JWT_SECRET,
    token_type: str = "admin",
) -> str:
    """Create an admin JWT for testing."""
    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = b64url(json.dumps({
        "sub": admin_id, "email": email, "exp": exp,
        "type": token_type, "jti": f"admin:{secrets.token_hex(16)}",
    }, separators=(",", ":")).encode())
    signing_input = f"{header}.{body}".encode("ascii")
    sig = b64url(hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest())
    return f"{header}.{body}.{sig}"


class TestRequireAdmin:
    @pytest.mark.asyncio
    async def test_valid_admin_token(self) -> None:
        import api.dependencies as deps
        deps.configure(TEST_JWT_SECRET)

        token = _make_admin_jwt()
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        result = await require_admin(creds)
        assert result["sub"] == TEST_ADMIN_ID
        assert result["type"] == "admin"

    @pytest.mark.asyncio
    async def test_rejects_user_token(self) -> None:
        """User tokens (no type=admin) must be rejected."""
        import api.dependencies as deps
        deps.configure(TEST_JWT_SECRET)

        # Create a regular user token (no "type" claim)
        def b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

        header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
        body = b64url(json.dumps({
            "sub": "user-id", "email": "user@test.com", "exp": 9_999_999_999,
        }, separators=(",", ":")).encode())
        signing_input = f"{header}.{body}".encode("ascii")
        sig = b64url(hmac.new(TEST_JWT_SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest())
        user_token = f"{header}.{body}.{sig}"

        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=user_token)
        with pytest.raises(HTTPException) as exc_info:
            await require_admin(creds)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_rejects_no_credentials(self) -> None:
        import api.dependencies as deps
        deps.configure(TEST_JWT_SECRET)

        with pytest.raises(HTTPException) as exc_info:
            await require_admin(None)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_rejects_expired_token(self) -> None:
        import api.dependencies as deps
        deps.configure(TEST_JWT_SECRET)

        token = _make_admin_jwt(exp=1000000000)  # expired
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        with pytest.raises(HTTPException) as exc_info:
            await require_admin(creds)
        assert exc_info.value.status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/Robert/Code/public/discogsography-admin-dashboard-104 && uv run pytest tests/api/test_admin_auth.py::TestRequireAdmin -v`
Expected: FAIL with `ImportError: cannot import name 'require_admin' from 'api.dependencies'`

- [ ] **Step 3: Implement require_admin in dependencies.py**

Add a module-level `_redis` reference to `api/dependencies.py` (alongside existing `_jwt_secret`):

```python
_redis: Any = None
```

Update the `configure()` function to accept and store redis:

```python
def configure(jwt_secret: str | None, redis: Any = None) -> None:
    global _jwt_secret, _redis
    _jwt_secret = jwt_secret
    _redis = redis
```

Add `require_admin` after the existing `require_user()`:

```python
async def require_admin(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_security)],
) -> dict[str, Any]:
    """Require a valid admin JWT token. Rejects non-admin tokens with 403."""
    if _jwt_secret is None:
        raise HTTPException(status_code=503, detail="Admin endpoints not configured")
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        payload = decode_token(credentials.credentials, _jwt_secret)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
    if payload.get("type") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    # Check token revocation in Redis
    jti: str | None = payload.get("jti")
    if jti and _redis:
        revoked = await _redis.get(f"revoked:jti:{jti}")
        if revoked:
            raise HTTPException(status_code=401, detail="Token has been revoked")
    return payload
```

**Note:** Update all existing `configure()` call sites in `api/api.py` and `tests/api/conftest.py` to pass the redis parameter where needed.

- [ ] **Step 4: Add token isolation to \_get_current_user in api.py**

In `api/api.py`, inside `_get_current_user()`, after the `payload = decode_token(...)` line and before extracting `user_id`, add:

```python
    # Reject admin tokens — they must not be used as regular user tokens
    if payload.get("type") == "admin":
        raise HTTPException(status_code=401, detail="Invalid token")
```

- [ ] **Step 5: Add test for admin token rejected by user endpoints**

Add to `tests/api/test_admin_auth.py`:

```python
class TestTokenIsolation:
    def test_admin_token_rejected_by_user_endpoint(self, test_client: TestClient) -> None:
        """Admin tokens must not work on regular user endpoints like /api/auth/me."""
        token = _make_admin_jwt()
        response = test_client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401
```

This requires importing `TestClient` and using the `test_client` fixture from conftest.

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /Users/Robert/Code/public/discogsography-admin-dashboard-104 && uv run pytest tests/api/test_admin_auth.py -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add api/dependencies.py api/api.py tests/api/test_admin_auth.py
git commit -m "feat(admin): add require_admin dependency with token isolation"
```

______________________________________________________________________

### Task 4: Add Pydantic models for admin endpoints

**Files:**

- Modify: `api/models.py`

- [ ] **Step 1: Add admin models to api/models.py**

Add to the end of `api/models.py`:

```python
# --- Admin Models ---


class AdminLoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class AdminLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class ExtractionHistoryResponse(BaseModel):
    id: UUID
    triggered_by: UUID
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    duration_seconds: float | None = None
    record_counts: dict[str, int] | None
    error_message: str | None
    extractor_version: str | None
    created_at: datetime


class ExtractionListResponse(BaseModel):
    extractions: list[ExtractionHistoryResponse]
    total: int
    offset: int
    limit: int


class ExtractionTriggerResponse(BaseModel):
    id: UUID
    status: str


class DlqPurgeResponse(BaseModel):
    queue: str
    messages_purged: int
```

- [ ] **Step 2: Run linting to verify**

Run: `cd /Users/Robert/Code/public/discogsography-admin-dashboard-104 && uv run ruff check api/models.py`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add api/models.py
git commit -m "feat(admin): add Pydantic models for admin endpoints"
```

______________________________________________________________________

### Task 5: Add config for extractor and RabbitMQ management

**Files:**

- Modify: `common/config.py`

- [ ] **Step 1: Add fields to ApiConfig**

In `common/config.py`, add to the `ApiConfig` dataclass, in the optional fields section (after `snapshot_max_nodes`):

```python
    # Admin dashboard — extractor connection
    extractor_host: str = "extractor"
    extractor_health_port: int = 8000

    # Admin dashboard — RabbitMQ management API
    rabbitmq_management_host: str = "rabbitmq"
    rabbitmq_management_port: int = 15672
    rabbitmq_username: str = "guest"
    rabbitmq_password: str = "guest"
```

In the `from_env()` classmethod, add env var reads for these fields:

```python
    extractor_host=getenv("EXTRACTOR_HOST", "extractor"),
    extractor_health_port=int(getenv("EXTRACTOR_HEALTH_PORT", "8000")),
    rabbitmq_management_host=getenv("RABBITMQ_MANAGEMENT_HOST", getenv("RABBITMQ_HOST", "rabbitmq")),
    rabbitmq_management_port=int(getenv("RABBITMQ_MANAGEMENT_PORT", "15672")),
    rabbitmq_username=getenv("RABBITMQ_USERNAME", "guest"),
    rabbitmq_password=get_secret("RABBITMQ_PASSWORD") or "guest",
```

- [ ] **Step 2: Run type check**

Run: `cd /Users/Robert/Code/public/discogsography-admin-dashboard-104 && uv run mypy common/config.py`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add common/config.py
git commit -m "feat(config): add extractor and RabbitMQ management config to ApiConfig"
```

______________________________________________________________________

## Chunk 2: Admin Router & Endpoints

### Task 6: Create admin router with login/logout

**Files:**

- Create: `api/routers/admin.py`

- Modify: `api/api.py` (register router)

- [ ] **Step 1: Write tests for admin login/logout**

Create `tests/api/test_admin_endpoints.py`:

```python
"""Tests for admin dashboard endpoints."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from starlette.testclient import TestClient

TEST_JWT_SECRET = "test-admin-secret-key-for-testing"
TEST_ADMIN_ID = str(uuid4())
TEST_ADMIN_EMAIL = "admin@test.com"
TEST_ADMIN_PASSWORD = "securepassword123"


def _make_admin_jwt(
    admin_id: str = TEST_ADMIN_ID,
    email: str = TEST_ADMIN_EMAIL,
    exp: int = 9_999_999_999,
    secret: str = TEST_JWT_SECRET,
) -> str:
    """Create an admin JWT for testing."""
    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = b64url(json.dumps({
        "sub": admin_id, "email": email, "exp": exp,
        "type": "admin", "jti": f"admin:{secrets.token_hex(16)}",
    }, separators=(",", ":")).encode())
    signing_input = f"{header}.{body}".encode("ascii")
    sig = b64url(hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest())
    return f"{header}.{body}.{sig}"


class TestAdminLogin:
    def test_login_success(self, test_client: TestClient, mock_cur: AsyncMock) -> None:
        from api.auth import _hash_password

        hashed = _hash_password(TEST_ADMIN_PASSWORD)
        mock_cur.fetchone.return_value = {
            "id": TEST_ADMIN_ID,
            "email": TEST_ADMIN_EMAIL,
            "hashed_password": hashed,
            "is_active": True,
        }

        response = test_client.post(
            "/api/admin/auth/login",
            json={"email": TEST_ADMIN_EMAIL, "password": TEST_ADMIN_PASSWORD},
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] > 0

    def test_login_wrong_password(self, test_client: TestClient, mock_cur: AsyncMock) -> None:
        from api.auth import _hash_password

        mock_cur.fetchone.return_value = {
            "id": TEST_ADMIN_ID,
            "email": TEST_ADMIN_EMAIL,
            "hashed_password": _hash_password(TEST_ADMIN_PASSWORD),
            "is_active": True,
        }

        response = test_client.post(
            "/api/admin/auth/login",
            json={"email": TEST_ADMIN_EMAIL, "password": "wrongpassword"},
        )
        assert response.status_code == 401

    def test_login_nonexistent_admin(self, test_client: TestClient, mock_cur: AsyncMock) -> None:
        mock_cur.fetchone.return_value = None

        response = test_client.post(
            "/api/admin/auth/login",
            json={"email": "nobody@test.com", "password": "anypassword"},
        )
        assert response.status_code == 401

    def test_login_inactive_admin(self, test_client: TestClient, mock_cur: AsyncMock) -> None:
        from api.auth import _hash_password

        mock_cur.fetchone.return_value = {
            "id": TEST_ADMIN_ID,
            "email": TEST_ADMIN_EMAIL,
            "hashed_password": _hash_password(TEST_ADMIN_PASSWORD),
            "is_active": False,
        }

        response = test_client.post(
            "/api/admin/auth/login",
            json={"email": TEST_ADMIN_EMAIL, "password": TEST_ADMIN_PASSWORD},
        )
        assert response.status_code == 401


class TestAdminLogout:
    def test_logout_success(self, test_client: TestClient, mock_redis: AsyncMock) -> None:
        token = _make_admin_jwt()
        response = test_client.post(
            "/api/admin/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["logged_out"] is True

    def test_logout_no_token(self, test_client: TestClient) -> None:
        response = test_client.post("/api/admin/auth/logout")
        assert response.status_code in (401, 403)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/Robert/Code/public/discogsography-admin-dashboard-104 && uv run pytest tests/api/test_admin_endpoints.py -v`
Expected: FAIL (router does not exist)

- [ ] **Step 3: Implement admin router**

Create `api/routers/admin.py`:

```python
"""Admin dashboard router.

Provides admin authentication, extraction history, and DLQ management.
All protected endpoints require a JWT with "type": "admin" claim.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import json

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row

from api.admin_auth import create_admin_token, verify_admin_password
from api.auth import _DUMMY_HASH, _verify_password
from api.dependencies import require_admin
from api.limiter import limiter
from api.models import (
    AdminLoginRequest,
    AdminLoginResponse,
    DlqPurgeResponse,
    ExtractionHistoryResponse,
    ExtractionListResponse,
    ExtractionTriggerResponse,
)
from common.config import DATA_TYPES, ApiConfig

logger = structlog.get_logger(__name__)

router = APIRouter()

# Module-level state, set via configure()
_pool: Any = None
_redis: Any = None
_config: ApiConfig | None = None
_tracking_tasks: dict[str, asyncio.Task[Any]] = {}


def configure(pool: Any, redis: Any, config: ApiConfig) -> None:
    """Configure module state. Called during API service startup."""
    global _pool, _redis, _config
    _pool = pool
    _redis = redis
    _config = config


# --- Valid DLQ names ---

def _valid_dlq_names() -> set[str]:
    """Build set of known DLQ queue names."""
    names: set[str] = set()
    for data_type in DATA_TYPES:
        names.add(f"graphinator-{data_type}-dlq")
        names.add(f"tableinator-{data_type}-dlq")
    return names


VALID_DLQS = _valid_dlq_names()


# --- Auth endpoints ---


@router.post("/api/admin/auth/login")
@limiter.limit("5/minute")
async def admin_login(request: Request, body: AdminLoginRequest) -> JSONResponse:
    """Authenticate an admin user and return a JWT."""
    async with _pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT id, email, hashed_password, is_active FROM dashboard_admins WHERE email = %s",
                (body.email,),
            )
            admin = await cur.fetchone()

    # Timing-safe: always verify password even if admin not found
    if admin is None:
        _verify_password(body.password, _DUMMY_HASH)
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    password_ok = verify_admin_password(body.password, admin["hashed_password"])
    if not admin["is_active"] or not password_ok:
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    token, expires_in = create_admin_token(
        str(admin["id"]), admin["email"], _config.jwt_secret_key, _config.jwt_expire_minutes
    )
    logger.info("✅ Admin logged in", email=body.email)

    return JSONResponse(
        content=AdminLoginResponse(
            access_token=token, expires_in=expires_in
        ).model_dump()
    )


@router.post("/api/admin/auth/logout")
async def admin_logout(
    current_admin: dict[str, Any] = Depends(require_admin),
) -> JSONResponse:
    """Revoke the current admin token."""
    if _redis:
        jti: str | None = current_admin.get("jti")
        exp: int | None = current_admin.get("exp")
        if jti:
            now = int(datetime.now(UTC).timestamp())
            ttl = max((exp - now), 60) if exp else 3600
            await _redis.setex(f"revoked:jti:{jti}", ttl, "1")
    return JSONResponse(content={"logged_out": True})


# --- Extraction history endpoints ---


@router.get("/api/admin/extractions")
async def list_extractions(
    offset: int = 0,
    limit: int = 20,
    _: dict[str, Any] = Depends(require_admin),
) -> JSONResponse:
    """List extraction history, newest first."""
    limit = min(limit, 100)
    async with _pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT COUNT(*) as total FROM extraction_history")
            total_row = await cur.fetchone()
            total = total_row["total"]

            await cur.execute(
                """
                SELECT id, triggered_by, status, started_at, completed_at,
                       record_counts, error_message, extractor_version, created_at
                FROM extraction_history
                ORDER BY created_at DESC
                OFFSET %s LIMIT %s
                """,
                (offset, limit),
            )
            rows = await cur.fetchall()

    extractions = []
    for row in rows:
        duration = None
        if row["completed_at"] and row["started_at"]:
            duration = (row["completed_at"] - row["started_at"]).total_seconds()
        extractions.append(
            ExtractionHistoryResponse(
                id=row["id"],
                triggered_by=row["triggered_by"],
                status=row["status"],
                started_at=row["started_at"],
                completed_at=row["completed_at"],
                duration_seconds=duration,
                record_counts=row["record_counts"],
                error_message=row["error_message"],
                extractor_version=row["extractor_version"],
                created_at=row["created_at"],
            )
        )

    return JSONResponse(
        content=ExtractionListResponse(
            extractions=extractions, total=total, offset=offset, limit=limit
        ).model_dump(mode="json")
    )


@router.get("/api/admin/extractions/{extraction_id}")
async def get_extraction(
    extraction_id: UUID,
    _: dict[str, Any] = Depends(require_admin),
) -> JSONResponse:
    """Get a single extraction record."""
    async with _pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT id, triggered_by, status, started_at, completed_at,
                       record_counts, error_message, extractor_version, created_at
                FROM extraction_history WHERE id = %s
                """,
                (str(extraction_id),),
            )
            row = await cur.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Extraction not found")

    duration = None
    if row["completed_at"] and row["started_at"]:
        duration = (row["completed_at"] - row["started_at"]).total_seconds()

    return JSONResponse(
        content=ExtractionHistoryResponse(
            id=row["id"],
            triggered_by=row["triggered_by"],
            status=row["status"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            duration_seconds=duration,
            record_counts=row["record_counts"],
            error_message=row["error_message"],
            extractor_version=row["extractor_version"],
            created_at=row["created_at"],
        ).model_dump(mode="json")
    )


# --- Extraction trigger ---


@router.post("/api/admin/extractions/trigger", status_code=202)
async def trigger_extraction(
    current_admin: dict[str, Any] = Depends(require_admin),
) -> JSONResponse:
    """Trigger a new extraction run."""
    admin_id = current_admin["sub"]
    extractor_url = f"http://{_config.extractor_host}:{_config.extractor_health_port}"

    # Create pending record
    async with _pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "INSERT INTO extraction_history (triggered_by, status) VALUES (%s::uuid, 'pending') RETURNING id",
                (admin_id,),
            )
            row = await cur.fetchone()
    extraction_id = str(row["id"])

    # Call extractor trigger endpoint
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{extractor_url}/trigger")
    except httpx.RequestError:
        # Extractor unreachable — mark failed
        async with _pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE extraction_history SET status = 'failed', error_message = %s WHERE id = %s::uuid",
                    ("Extractor service unavailable", extraction_id),
                )
        raise HTTPException(status_code=503, detail="Extractor service unavailable")

    if resp.status_code == 409:
        # Already running — delete pending record
        async with _pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "DELETE FROM extraction_history WHERE id = %s::uuid",
                    (extraction_id,),
                )
        raise HTTPException(status_code=409, detail="Extraction already in progress")

    if resp.status_code != 202:
        async with _pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE extraction_history SET status = 'failed', error_message = %s WHERE id = %s::uuid",
                    (f"Unexpected response from extractor: {resp.status_code}", extraction_id),
                )
        raise HTTPException(status_code=502, detail="Unexpected extractor response")

    # Success — update to running and start tracking
    async with _pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE extraction_history SET status = 'running', started_at = NOW() WHERE id = %s::uuid",
                (extraction_id,),
            )

    # Spawn background tracking task
    task = asyncio.create_task(_track_extraction(extraction_id, extractor_url))
    _tracking_tasks[extraction_id] = task

    logger.info("🚀 Extraction triggered", extraction_id=extraction_id, admin=current_admin.get("email"))

    return JSONResponse(
        content=ExtractionTriggerResponse(
            id=extraction_id, status="running"
        ).model_dump(mode="json"),
        status_code=202,
    )


async def _track_extraction(extraction_id: str, extractor_url: str) -> None:
    """Background task: poll extractor health and update extraction_history."""
    consecutive_failures = 0
    max_failures = 5

    try:
        while True:
            await asyncio.sleep(10)

            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(f"{extractor_url}/health")
                health = resp.json()
                consecutive_failures = 0
            except (httpx.RequestError, ValueError):
                consecutive_failures += 1
                if consecutive_failures >= max_failures:
                    async with _pool.connection() as conn:
                        async with conn.cursor() as cur:
                            await cur.execute(
                                """UPDATE extraction_history
                                   SET status = 'failed', completed_at = NOW(),
                                       error_message = 'Extractor became unreachable'
                                   WHERE id = %s::uuid""",
                                (extraction_id,),
                            )
                    logger.error("❌ Extraction tracking failed — extractor unreachable", extraction_id=extraction_id)
                    return
                continue

            extraction_status = health.get("extraction_status", "unknown")
            progress = health.get("extraction_progress", {})
            record_counts = {
                "artists": progress.get("artists", 0),
                "labels": progress.get("labels", 0),
                "masters": progress.get("masters", 0),
                "releases": progress.get("releases", 0),
            }

            if extraction_status == "completed":
                async with _pool.connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            """UPDATE extraction_history
                               SET status = 'completed', completed_at = NOW(), record_counts = %s::jsonb
                               WHERE id = %s::uuid""",
                            (json.dumps(record_counts), extraction_id),
                        )
                logger.info("✅ Extraction completed", extraction_id=extraction_id, record_counts=record_counts)
                return

            if extraction_status == "failed":
                error_msg = health.get("error_message", "Extraction failed")
                async with _pool.connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            """UPDATE extraction_history
                               SET status = 'failed', completed_at = NOW(),
                                   error_message = %s, record_counts = %s::jsonb
                               WHERE id = %s::uuid""",
                            (error_msg, json.dumps(record_counts), extraction_id),
                        )
                logger.error("❌ Extraction failed", extraction_id=extraction_id)
                return

            # Still running — update progress
            async with _pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "UPDATE extraction_history SET record_counts = %s::jsonb WHERE id = %s::uuid",
                        (json.dumps(record_counts), extraction_id),
                    )

    except asyncio.CancelledError:
        logger.info("🛑 Extraction tracking cancelled", extraction_id=extraction_id)
    finally:
        _tracking_tasks.pop(extraction_id, None)


# --- DLQ purge ---


@router.post("/api/admin/dlq/purge/{queue}")
async def purge_dlq(
    queue: str,
    current_admin: dict[str, Any] = Depends(require_admin),
) -> JSONResponse:
    """Purge messages from a dead-letter queue."""
    if queue not in VALID_DLQS:
        raise HTTPException(status_code=404, detail=f"Unknown DLQ: {queue}")

    mgmt_url = f"http://{_config.rabbitmq_management_host}:{_config.rabbitmq_management_port}"
    auth = (_config.rabbitmq_username, _config.rabbitmq_password)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Get current message count first
            resp = await client.get(
                f"{mgmt_url}/api/queues/%2f/{queue}",
                auth=auth,
            )
            if resp.status_code == 404:
                raise HTTPException(status_code=404, detail=f"Queue {queue} does not exist")
            resp.raise_for_status()
            message_count = resp.json().get("messages", 0)

            # Purge the queue
            resp = await client.delete(
                f"{mgmt_url}/api/queues/%2f/{queue}/contents",
                auth=auth,
            )
            resp.raise_for_status()
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail="RabbitMQ management API unavailable") from exc

    logger.info(
        "🗑️ DLQ purged",
        queue=queue,
        messages_purged=message_count,
        admin=current_admin.get("email"),
    )

    return JSONResponse(
        content=DlqPurgeResponse(queue=queue, messages_purged=message_count).model_dump()
    )
```

- [ ] **Step 4: Register admin router in api.py**

In `api/api.py`, add at the top with other router imports:

```python
from api.routers import admin as _admin_router
```

In the `lifespan()` function, after the other `configure()` calls (around line 204), add:

```python
    _admin_router.configure(_pool, _redis, _config)
```

After the other `app.include_router()` calls, add:

```python
app.include_router(_admin_router.router)
```

- [ ] **Step 5: Update test_client fixture in conftest.py**

In `tests/api/conftest.py`, inside the `test_client` fixture where other routers are configured, add:

```python
    from api.routers import admin as _admin_router
    _admin_router.configure(mock_pool, mock_redis, test_api_config)
```

- [ ] **Step 6: Run tests**

Run: `cd /Users/Robert/Code/public/discogsography-admin-dashboard-104 && uv run pytest tests/api/test_admin_endpoints.py -v`
Expected: All tests PASS

- [ ] **Step 7: Run existing tests to check for regressions**

Run: `cd /Users/Robert/Code/public/discogsography-admin-dashboard-104 && uv run pytest tests/api/ -v`
Expected: All tests PASS (including existing tests — verify token isolation didn't break anything)

- [ ] **Step 8: Commit**

```bash
git add api/routers/admin.py api/api.py tests/api/test_admin_endpoints.py tests/api/conftest.py
git commit -m "feat(admin): add admin router with login, logout, extraction history, trigger, and DLQ purge"
```

______________________________________________________________________

### Task 7: Add extraction trigger and DLQ purge tests

**Files:**

- Modify: `tests/api/test_admin_endpoints.py`

- [ ] **Step 1: Add trigger and DLQ tests**

Add to `tests/api/test_admin_endpoints.py`:

```python
class TestExtractionTrigger:
    @patch("api.routers.admin.httpx.AsyncClient")
    def test_trigger_success(
        self, mock_httpx_cls: MagicMock, test_client: TestClient, mock_cur: AsyncMock
    ) -> None:
        mock_cur.fetchone.return_value = {"id": str(uuid4())}
        mock_resp = MagicMock()
        mock_resp.status_code = 202
        mock_resp.json.return_value = {"status": "started"}
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_httpx_cls.return_value = mock_client

        token = _make_admin_jwt()
        response = test_client.post(
            "/api/admin/extractions/trigger",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 202
        assert response.json()["status"] == "running"

    @patch("api.routers.admin.httpx.AsyncClient")
    def test_trigger_already_running(
        self, mock_httpx_cls: MagicMock, test_client: TestClient, mock_cur: AsyncMock
    ) -> None:
        mock_cur.fetchone.return_value = {"id": str(uuid4())}
        mock_resp = MagicMock()
        mock_resp.status_code = 409
        mock_resp.json.return_value = {"status": "already_running"}
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_httpx_cls.return_value = mock_client

        token = _make_admin_jwt()
        response = test_client.post(
            "/api/admin/extractions/trigger",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 409

    def test_trigger_unauthorized(self, test_client: TestClient) -> None:
        response = test_client.post("/api/admin/extractions/trigger")
        assert response.status_code in (401, 403)


class TestExtractionList:
    def test_list_extractions(self, test_client: TestClient, mock_cur: AsyncMock) -> None:
        mock_cur.fetchone.return_value = {"total": 0}
        mock_cur.fetchall.return_value = []

        token = _make_admin_jwt()
        response = test_client.get(
            "/api/admin/extractions",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["extractions"] == []

    def test_list_extractions_unauthorized(self, test_client: TestClient) -> None:
        response = test_client.get("/api/admin/extractions")
        assert response.status_code in (401, 403)


class TestDlqPurge:
    @patch("api.routers.admin.httpx.AsyncClient")
    def test_purge_valid_queue(
        self, mock_httpx_cls: MagicMock, test_client: TestClient
    ) -> None:
        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 200
        mock_get_resp.json.return_value = {"messages": 5}
        mock_get_resp.raise_for_status = MagicMock()
        mock_del_resp = MagicMock()
        mock_del_resp.status_code = 204
        mock_del_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_get_resp
        mock_client.delete.return_value = mock_del_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_httpx_cls.return_value = mock_client

        token = _make_admin_jwt()
        response = test_client.post(
            "/api/admin/dlq/purge/graphinator-artists-dlq",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["messages_purged"] == 5

    def test_purge_invalid_queue(self, test_client: TestClient) -> None:
        token = _make_admin_jwt()
        response = test_client.post(
            "/api/admin/dlq/purge/nonexistent-queue",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404

    def test_purge_unauthorized(self, test_client: TestClient) -> None:
        response = test_client.post("/api/admin/dlq/purge/graphinator-artists-dlq")
        assert response.status_code in (401, 403)
```

- [ ] **Step 2: Run all admin tests**

Run: `cd /Users/Robert/Code/public/discogsography-admin-dashboard-104 && uv run pytest tests/api/test_admin_endpoints.py tests/api/test_admin_auth.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/api/test_admin_endpoints.py
git commit -m "test(admin): add trigger, extraction list, and DLQ purge tests"
```

______________________________________________________________________

## Chunk 3: Admin CLI, Extractor Changes & Integration

### Task 8: Create admin-setup CLI tool

**Files:**

- Create: `api/admin_setup.py`

- Modify: `api/pyproject.toml`

- [ ] **Step 1: Implement admin_setup.py**

Create `api/admin_setup.py`:

```python
"""CLI tool for managing admin accounts.

Usage:
    admin-setup --email admin@example.com --password mysecretpw
    admin-setup --list
"""

from __future__ import annotations

import argparse
import sys
from os import getenv

import psycopg

from api.auth import _hash_password
from common.config import get_secret


def _build_conninfo() -> str:
    """Build PostgreSQL connection string from environment variables."""
    host = getenv("POSTGRES_HOST", "localhost")
    port = getenv("POSTGRES_PORT", "5432")
    user = get_secret("POSTGRES_USERNAME") or "postgres"
    password = get_secret("POSTGRES_PASSWORD") or "postgres"
    database = getenv("POSTGRES_DATABASE", "discogsography")
    return f"host={host} port={port} user={user} password={password} dbname={database}"


def add_admin(conninfo: str, email: str, password: str) -> None:
    """Insert a new admin account into dashboard_admins."""
    hashed = _hash_password(password)

    upsert_sql = """
        INSERT INTO dashboard_admins (email, hashed_password)
        VALUES (%s, %s)
        ON CONFLICT (email) DO UPDATE SET
            hashed_password = EXCLUDED.hashed_password,
            updated_at = NOW()
    """
    with psycopg.connect(conninfo) as conn:
        with conn.cursor() as cur:
            cur.execute(upsert_sql, (email.strip().lower(), hashed))
    print(f"✅ Admin account '{email}' created/updated successfully.")


def list_admins(conninfo: str) -> None:
    """List all admin accounts (email + active status)."""
    with psycopg.connect(conninfo) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT email, is_active, created_at FROM dashboard_admins ORDER BY created_at"
            )
            rows = cur.fetchall()

    if not rows:
        print("No admin accounts found.")
        return

    print(f"{'Email':<40} {'Active':<8} {'Created'}")
    print("-" * 70)
    for email, is_active, created_at in rows:
        status = "Yes" if is_active else "No"
        print(f"{email:<40} {status:<8} {created_at}")


def main() -> None:
    """Entry point for the admin-setup CLI tool."""
    parser = argparse.ArgumentParser(
        prog="admin-setup",
        description="Manage admin accounts for the dashboard.",
    )
    parser.add_argument("--email", metavar="EMAIL", help="Admin email address")
    parser.add_argument("--password", metavar="PW", help="Admin password (min 8 chars)")
    parser.add_argument("--list", action="store_true", help="List existing admin accounts")

    args = parser.parse_args()

    if not args.list and not (args.email and args.password):
        parser.print_help()
        sys.exit(1)

    if args.password and len(args.password) < 8:
        print("❌ Password must be at least 8 characters.")
        sys.exit(1)

    conninfo = _build_conninfo()

    if args.list:
        list_admins(conninfo)
    else:
        add_admin(conninfo, args.email, args.password)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Add entry point to pyproject.toml**

In `api/pyproject.toml`, in the `[project.scripts]` section, add:

```toml
admin-setup = "api.admin_setup:main"
```

- [ ] **Step 3: Run linting**

Run: `cd /Users/Robert/Code/public/discogsography-admin-dashboard-104 && uv run ruff check api/admin_setup.py`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add api/admin_setup.py api/pyproject.toml
git commit -m "feat(admin): add admin-setup CLI tool for managing admin accounts"
```

______________________________________________________________________

### Task 9: Extend Rust extractor with trigger endpoint and extraction_status

**Files:**

- Modify: `extractor/src/health.rs`

- Modify: `extractor/src/extractor.rs` (add extraction_status to state)

- Modify: `extractor/src/main.rs` (wire trigger flag)

- Modify: `extractor/src/tests/health_tests.rs`

- [ ] **Step 1: Add extraction_status to ExtractorState**

In `extractor/src/extractor.rs`, add a new field to `ExtractorState`:

```rust
/// State shared across the extractor
#[derive(Debug, Default)]
pub struct ExtractorState {
    pub extraction_progress: ExtractionProgress,
    pub last_extraction_time: HashMap<DataType, Instant>,
    pub completed_files: HashSet<String>,
    pub active_connections: HashMap<DataType, String>,
    pub error_count: u64,
    pub extraction_status: ExtractionStatus,
}

/// Lifecycle status of the extraction process
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum ExtractionStatus {
    #[default]
    Idle,
    Running,
    Completed,
    Failed,
}

impl ExtractionStatus {
    pub fn as_str(&self) -> &'static str {
        match self {
            ExtractionStatus::Idle => "idle",
            ExtractionStatus::Running => "running",
            ExtractionStatus::Completed => "completed",
            ExtractionStatus::Failed => "failed",
        }
    }
}
```

Update `process_discogs_data()` to set extraction_status:

- At the start (after resetting progress): `s.extraction_status = ExtractionStatus::Running;`
- On success (end of function): `s.extraction_status = ExtractionStatus::Completed;`
- On failure: `s.extraction_status = ExtractionStatus::Failed;`

Update `run_extraction_loop()` to check a trigger flag. Add a `trigger: Arc<AtomicBool>` parameter and check it in the loop alongside the sleep/shutdown select:

```rust
pub async fn run_extraction_loop(
    config: Arc<ExtractorConfig>,
    state: Arc<RwLock<ExtractorState>>,
    shutdown: Arc<tokio::sync::Notify>,
    force_reprocess: bool,
    mq_factory: Arc<dyn MessageQueueFactory>,
    trigger: Arc<std::sync::atomic::AtomicBool>,
) -> Result<()> {
    // ... initial processing (unchanged) ...

    // Start periodic check loop
    loop {
        let check_interval = Duration::from_secs(config.periodic_check_days * 24 * 60 * 60);
        info!("⏰ Waiting {} days before next check...", config.periodic_check_days);

        tokio::select! {
            _ = sleep(check_interval) => {
                // ... existing periodic check logic ...
            }
            _ = wait_for_trigger(&trigger) => {
                info!("🔄 Extraction triggered via API...");
                // ... same extraction logic as periodic check ...
            }
            _ = shutdown.notified() => {
                info!("🛑 Shutdown requested, stopping periodic checks");
                break;
            }
        }
    }

    Ok(())
}

/// Wait until the trigger flag is set, then clear it
async fn wait_for_trigger(trigger: &Arc<std::sync::atomic::AtomicBool>) {
    loop {
        if trigger.compare_exchange(
            true, false,
            std::sync::atomic::Ordering::SeqCst,
            std::sync::atomic::Ordering::SeqCst,
        ).is_ok() {
            return;
        }
        tokio::time::sleep(Duration::from_millis(500)).await;
    }
}
```

- [ ] **Step 2: Add trigger endpoint to health.rs**

In `extractor/src/health.rs`, add the `POST /trigger` route and update the health response:

```rust
use std::sync::atomic::{AtomicBool, Ordering};
use axum::routing::post;

use crate::extractor::ExtractionStatus;

pub struct HealthServer {
    port: u16,
    state: Arc<RwLock<ExtractorState>>,
    trigger: Arc<AtomicBool>,
}

impl HealthServer {
    pub fn new(port: u16, state: Arc<RwLock<ExtractorState>>, trigger: Arc<AtomicBool>) -> Self {
        Self { port, state, trigger }
    }

    pub async fn run(self) -> anyhow::Result<()> {
        let app = Router::new()
            .route("/health", get(health_handler))
            .route("/metrics", get(metrics_handler))
            .route("/ready", get(ready_handler))
            .route("/trigger", post(trigger_handler))
            .layer(CorsLayer::permissive())
            .layer(TraceLayer::new_for_http())
            .with_state((self.state, self.trigger));
        // ...
    }
}
```

Update all handlers to accept the new state tuple type `State<(Arc<RwLock<ExtractorState>>, Arc<AtomicBool>)>`:

```rust
async fn health_handler(
    State((state, _)): State<(Arc<RwLock<ExtractorState>>, Arc<AtomicBool>)>,
) -> (StatusCode, Json<serde_json::Value>) {
    let state = state.read().await;
    let health = json!({
        "status": "healthy",
        "service": "rust-extractor",
        "extraction_status": state.extraction_status.as_str(),
        // ... existing fields unchanged ...
    });
    (StatusCode::OK, Json(health))
}

async fn trigger_handler(
    State((state, trigger)): State<(Arc<RwLock<ExtractorState>>, Arc<AtomicBool>)>,
) -> (StatusCode, Json<serde_json::Value>) {
    let state = state.read().await;
    if state.extraction_status == ExtractionStatus::Running {
        return (
            StatusCode::CONFLICT,
            Json(json!({"status": "already_running"})),
        );
    }
    drop(state); // Release read lock before setting trigger

    trigger.store(true, Ordering::SeqCst);
    info!("🔄 Extraction triggered via API");

    (
        StatusCode::ACCEPTED,
        Json(json!({"status": "started"})),
    )
}
```

- [ ] **Step 3: Update main.rs to wire trigger flag**

In `extractor/src/main.rs`:

```rust
use std::sync::atomic::AtomicBool;

// In main():
let trigger = Arc::new(AtomicBool::new(false));

let health_server = HealthServer::new(config.health_port, state.clone(), trigger.clone());
// ...

let extraction_result = extractor::run_extraction_loop(
    config.clone(), state.clone(), shutdown.clone(),
    args.force_reprocess, mq_factory, trigger.clone(),
).await;
```

- [ ] **Step 4: Update health tests**

Update `extractor/src/tests/health_tests.rs` to pass the new state tuple:

For each existing test that calls handlers directly, update the `State(...)` argument from `State(state)` to `State((state, Arc::new(AtomicBool::new(false))))`.

**Also update `HealthServer::new` constructor calls** in `test_health_server_new` and `test_health_server_run_and_endpoints`:

```rust
// Before:
let server = HealthServer::new(8000, state.clone());
// After:
let server = HealthServer::new(8000, state.clone(), Arc::new(AtomicBool::new(false)));
```

Add new tests:

```rust
#[tokio::test]
async fn test_trigger_handler_success() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let trigger = Arc::new(AtomicBool::new(false));
    let (status, json) = trigger_handler(State((state, trigger.clone()))).await;

    assert_eq!(status, StatusCode::ACCEPTED);
    assert_eq!(json.0["status"], "started");
    assert!(trigger.load(Ordering::SeqCst)); // trigger flag should be set
}

#[tokio::test]
async fn test_trigger_handler_already_running() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    {
        let mut s = state.write().await;
        s.extraction_status = ExtractionStatus::Running;
    }
    let trigger = Arc::new(AtomicBool::new(false));
    let (status, json) = trigger_handler(State((state, trigger.clone()))).await;

    assert_eq!(status, StatusCode::CONFLICT);
    assert_eq!(json.0["status"], "already_running");
    assert!(!trigger.load(Ordering::SeqCst)); // trigger flag should NOT be set
}

#[tokio::test]
async fn test_health_includes_extraction_status() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    let trigger = Arc::new(AtomicBool::new(false));
    let (_, json) = health_handler(State((state, trigger))).await;
    assert_eq!(json.0["extraction_status"], "idle");
}

#[tokio::test]
async fn test_health_extraction_status_running() {
    let state = Arc::new(RwLock::new(ExtractorState::default()));
    {
        let mut s = state.write().await;
        s.extraction_status = ExtractionStatus::Running;
    }
    let trigger = Arc::new(AtomicBool::new(false));
    let (_, json) = health_handler(State((state, trigger))).await;
    assert_eq!(json.0["extraction_status"], "running");
}
```

- [ ] **Step 5: Run Rust tests**

Run: `cd /Users/Robert/Code/public/discogsography-admin-dashboard-104/extractor && cargo test`
Expected: All tests PASS

- [ ] **Step 6: Run clippy**

Run: `cd /Users/Robert/Code/public/discogsography-admin-dashboard-104/extractor && cargo clippy -- -D warnings`
Expected: No warnings

- [ ] **Step 7: Commit**

```bash
git add extractor/src/health.rs extractor/src/extractor.rs extractor/src/main.rs extractor/src/tests/health_tests.rs
git commit -m "feat(extractor): add POST /trigger endpoint and extraction_status to health response"
```

______________________________________________________________________

### Task 10: Add httpx dependency and run full test suite

**Files:**

- Modify: `api/pyproject.toml` (if httpx not already a dependency)

- [ ] **Step 1: Check if httpx is already a dependency**

Read `api/pyproject.toml` and check if `httpx` is listed. If not, add it:

```bash
cd /Users/Robert/Code/public/discogsography-admin-dashboard-104/api && uv add httpx
```

- [ ] **Step 2: Run full Python test suite**

Run: `cd /Users/Robert/Code/public/discogsography-admin-dashboard-104 && uv run pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 3: Run type checking**

Run: `cd /Users/Robert/Code/public/discogsography-admin-dashboard-104 && uv run mypy api/`
Expected: No errors (or only pre-existing issues)

- [ ] **Step 4: Run linting**

Run: `cd /Users/Robert/Code/public/discogsography-admin-dashboard-104 && uv run ruff check .`
Expected: No errors

- [ ] **Step 5: Commit any remaining changes**

```bash
git add -A
git commit -m "chore: add httpx dependency and fix any remaining issues"
```

______________________________________________________________________

### Task 11: Final integration verification

- [ ] **Step 1: Run full test suite one final time**

```bash
cd /Users/Robert/Code/public/discogsography-admin-dashboard-104
uv run pytest tests/ -v
cd extractor && cargo test
```

- [ ] **Step 2: Verify no regressions in existing endpoints**

Run: `cd /Users/Robert/Code/public/discogsography-admin-dashboard-104 && uv run pytest tests/api/test_auth.py tests/api/test_sync.py -v`
Expected: All existing tests still pass (especially auth tests after token isolation change)

- [ ] **Step 3: Commit if any fixes needed, then push**

```bash
git push -u origin feat/admin-dashboard-104
```
