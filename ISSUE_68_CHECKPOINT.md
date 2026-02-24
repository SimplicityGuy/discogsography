# Issue #68 Implementation Checkpoint

Branch: `feature/issue-68-consolidate-api-endpoints`

## Status: IN PROGRESS — Resume here

## Commits so far
- 7087442 feat(api): add Neo4j fields to ApiConfig for endpoint consolidation
- 68d4df7 feat(api): add routers/queries dirs and copy source files into api package

## Completed Steps
1. `common/config.py` — Added `neo4j_address`, `neo4j_username`, `neo4j_password` to `ApiConfig`. DONE.
2. `api/routers/__init__.py` — Created (empty). DONE.
3. `api/queries/__init__.py` — Created (empty). DONE.
4. `api/queries/neo4j_queries.py` — Copied from `explore/neo4j_queries.py` (no changes needed). DONE.
5. `api/queries/user_queries.py` — Copied from `explore/user_queries.py` (no changes needed). DONE.
6. `api/snapshot_store.py` — Copied from `explore/snapshot_store.py` (no changes needed). DONE.
7. `api/syncer.py` — Copied from `curator/syncer.py` (no changes needed). DONE.

## Remaining Steps — DO THESE NEXT

### Step 8: Create `api/routers/sync.py`
```python
"""Sync endpoints — migrated from curator service."""
import asyncio
from datetime import UTC, datetime
from typing import Annotated, Any
import base64
import hashlib
import hmac
import json

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import ORJSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg.rows import dict_row
import structlog

from common import AsyncPostgreSQLPool, AsyncResilientNeo4jDriver
from api.syncer import run_full_sync

logger = structlog.get_logger(__name__)

router = APIRouter()
_security = HTTPBearer()

_pool: AsyncPostgreSQLPool | None = None
_neo4j: AsyncResilientNeo4jDriver | None = None
_config: Any = None
_running_syncs: dict[str, asyncio.Task[Any]] = {}


def configure(
    pool: AsyncPostgreSQLPool,
    neo4j: AsyncResilientNeo4jDriver | None,
    config: Any,
    running_syncs: dict[str, asyncio.Task[Any]],
) -> None:
    global _pool, _neo4j, _config, _running_syncs
    _pool = pool
    _neo4j = neo4j
    _config = config
    _running_syncs = running_syncs


async def _verify_token(token: str) -> dict[str, Any]:
    if _config is None:
        raise ValueError("Service not initialized")
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid token")
    header_b64, body_b64, sig_b64 = parts
    signing_input = f"{header_b64}.{body_b64}".encode("ascii")

    def _b64url_encode(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    expected_sig = _b64url_encode(hmac.new(_config.jwt_secret_key.encode("utf-8"), signing_input, hashlib.sha256).digest())
    if not hmac.compare_digest(sig_b64, expected_sig):
        raise ValueError("Invalid token signature")
    padding = 4 - len(body_b64) % 4
    if padding != 4:
        body_b64 += "=" * padding
    payload: dict[str, Any] = json.loads(base64.urlsafe_b64decode(body_b64))
    exp = payload.get("exp")
    if exp and datetime.fromtimestamp(int(exp), UTC) < datetime.now(UTC):
        raise ValueError("Token expired")
    return payload


async def _get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_security)],
) -> dict[str, Any]:
    if _config is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")
    try:
        payload = await _verify_token(credentials.credentials)
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        return payload
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


@router.post("/api/sync", status_code=status.HTTP_202_ACCEPTED)
async def trigger_sync(
    current_user: Annotated[dict[str, Any], Depends(_get_current_user)],
) -> ORJSONResponse:
    if _pool is None or _neo4j is None or _config is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")
    user_id = current_user.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    if user_id in _running_syncs and not _running_syncs[user_id].done():
        async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT id, status FROM sync_history WHERE user_id = %s::uuid AND status = 'running' ORDER BY started_at DESC LIMIT 1",
                (user_id,),
            )
            existing = await cur.fetchone()
        if existing:
            return ORJSONResponse(
                content={"sync_id": str(existing["id"]), "status": "already_running"},
                status_code=status.HTTP_202_ACCEPTED,
            )
    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "INSERT INTO sync_history (user_id, sync_type, status) VALUES (%s::uuid, 'full', 'running') RETURNING id",
            (user_id,),
        )
        sync_row = await cur.fetchone()
    if not sync_row:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create sync record")
    from uuid import UUID
    sync_id = str(sync_row["id"])
    task = asyncio.create_task(
        run_full_sync(
            user_uuid=UUID(user_id),
            sync_id=sync_id,
            pg_pool=_pool,
            neo4j_driver=_neo4j,
            discogs_user_agent=_config.discogs_user_agent,
        )
    )
    _running_syncs[user_id] = task
    logger.info("🔄 Sync triggered", user_id=user_id, sync_id=sync_id)
    return ORJSONResponse(content={"sync_id": sync_id, "status": "started"}, status_code=status.HTTP_202_ACCEPTED)


@router.get("/api/sync/status")
async def sync_status(
    current_user: Annotated[dict[str, Any], Depends(_get_current_user)],
) -> ORJSONResponse:
    if _pool is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")
    user_id = current_user.get("sub")
    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """SELECT id, sync_type, status, items_synced, error_message, started_at, completed_at
               FROM sync_history WHERE user_id = %s::uuid ORDER BY started_at DESC LIMIT 10""",
            (user_id,),
        )
        rows = await cur.fetchall()
    history = [
        {
            "sync_id": str(row["id"]),
            "sync_type": row["sync_type"],
            "status": row["status"],
            "items_synced": row["items_synced"],
            "error": row["error_message"],
            "started_at": row["started_at"].isoformat(),
            "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
        }
        for row in rows
    ]
    return ORJSONResponse(content={"syncs": history})
```

### Step 9: Create `api/routers/explore.py`
JWT helpers: _b64url_decode, _verify_jwt, _get_optional_user (no _require_user needed in explore router)
Module state: _neo4j_driver, _jwt_secret
configure(neo4j, jwt_secret) function
Copy autocomplete cache: _autocomplete_cache, _AUTOCOMPLETE_CACHE_MAX, _get_cache_key
Copy ALL explore/expand/node/trends endpoints from explore/explore.py
Import from api.queries.neo4j_queries (not explore.neo4j_queries)
_build_categories() helper function also copied
Uses `router = APIRouter()`

### Step 10: Create `api/routers/snapshot.py`
```python
"""Snapshot endpoints — migrated from explore service."""
from fastapi import APIRouter
from fastapi.responses import ORJSONResponse
from api.models import SnapshotRequest, SnapshotResponse, SnapshotRestoreResponse
from api.snapshot_store import SnapshotStore

router = APIRouter()
_snapshot_store = SnapshotStore()

@router.post("/api/snapshot", status_code=201)
async def save_snapshot(body: SnapshotRequest) -> ORJSONResponse:
    if len(body.nodes) > _snapshot_store.max_nodes:
        return ORJSONResponse(content={"error": f"Too many nodes: maximum is {_snapshot_store.max_nodes}"}, status_code=422)
    nodes = [n.model_dump() for n in body.nodes]
    center = body.center.model_dump()
    token, expires_at = _snapshot_store.save(nodes, center)
    response = SnapshotResponse(token=token, url=f"/snapshot/{token}", expires_at=expires_at.isoformat())
    return ORJSONResponse(content=response.model_dump(), status_code=201)

@router.get("/api/snapshot/{token}")
async def restore_snapshot(token: str) -> ORJSONResponse:
    entry = _snapshot_store.load(token)
    if entry is None:
        return ORJSONResponse(content={"error": "Snapshot not found or expired"}, status_code=404)
    response = SnapshotRestoreResponse(nodes=entry["nodes"], center=entry["center"], created_at=entry["created_at"])
    return ORJSONResponse(content=response.model_dump())
```

### Step 11: Create `api/routers/user.py`
Same JWT helpers as explore router (_b64url_decode, _verify_jwt, _require_user, _get_optional_user)
configure(neo4j, jwt_secret) function
Module state: _neo4j_driver, _jwt_secret
Import from api.queries.user_queries
Copy ALL user endpoints from explore/explore.py:
  - GET /api/user/collection
  - GET /api/user/wantlist
  - GET /api/user/recommendations
  - GET /api/user/collection/stats
  - GET /api/user/status

### Step 12: Update `api/models.py`
Add at the end (after UserResponse):
```python
class SnapshotNode(BaseModel):
    id: str
    type: str

class SnapshotRequest(BaseModel):
    nodes: list[SnapshotNode]
    center: SnapshotNode
    @field_validator("nodes")
    @classmethod
    def nodes_not_empty(cls, v):
        if not v:
            raise ValueError("nodes must not be empty")
        return v

class SnapshotResponse(BaseModel):
    token: str
    url: str
    expires_at: str

class SnapshotRestoreResponse(BaseModel):
    nodes: list[SnapshotNode]
    center: SnapshotNode
    created_at: str
```

### Step 13: Update `api/api.py`
Add after existing globals:
```python
_neo4j: AsyncResilientNeo4jDriver | None = None
_running_syncs: dict[str, asyncio.Task[Any]] = {}
```
Add imports at top:
```python
import asyncio
from common import AsyncResilientNeo4jDriver  # add to existing common import
import api.routers.sync as _sync_router
import api.routers.explore as _explore_router
import api.routers.snapshot as _snapshot_router
import api.routers.user as _user_router
```
In lifespan, after redis init, add:
```python
if _config.neo4j_address and _config.neo4j_username and _config.neo4j_password:
    _neo4j = AsyncResilientNeo4jDriver(
        uri=_config.neo4j_address,
        auth=(_config.neo4j_username, _config.neo4j_password),
        max_retries=5,
        encrypted=False,
    )
    logger.info("🔗 Neo4j driver initialized")

jwt_secret_for_neo4j = _config.jwt_secret_key if _config.neo4j_address else None
_sync_router.configure(_pool, _neo4j, _config, _running_syncs)
_explore_router.configure(_neo4j, jwt_secret_for_neo4j)
_user_router.configure(_neo4j, jwt_secret_for_neo4j)
```
In shutdown section, add before pool.close():
```python
for task in _running_syncs.values():
    task.cancel()
if _running_syncs:
    await asyncio.gather(*_running_syncs.values(), return_exceptions=True)
if _neo4j:
    await _neo4j.close()
```
After `app = FastAPI(...)` and middleware, add:
```python
app.include_router(_sync_router.router)
app.include_router(_explore_router.router)
app.include_router(_snapshot_router.router)
app.include_router(_user_router.router)
```

### Step 14: Update `api/pyproject.toml`
Add `"neo4j>=6.1.0",` to dependencies list (alphabetically between httpx and orjson).

### Step 15: Strip `curator/curator.py` to health-only
Remove: _security, _verify_token, _get_current_user, trigger_sync, sync_status, _running_syncs
Keep: _pool, _neo4j, _config, get_health_data, lifespan (with full pool+neo4j init), app (/health only), main()
IMPORTANT: lifespan still needs `global _pool, _neo4j, _config` — curator still initializes connections for its own health check

### Step 16: Strip `explore/explore.py` to health-only
Remove all routes except /health, remove all JWT helpers, remove autocomplete cache
Keep: neo4j_driver global, config global, get_health_data, lifespan, app (/health only), if __name__ == "__main__" block
Remove: snapshot_store global, _security, _b64url_decode, _verify_jwt, _get_optional_user, _require_user, _autocomplete_cache, _AUTOCOMPLETE_CACHE_MAX, _get_cache_key, _build_categories
Remove imports: snapshot/user_queries/neo4j_queries imports, SnapshotRequest/Response etc, StaticFiles mount

### Step 17: Update `docker-compose.yml`
- Remove ports `8010:8010` and `8011:8011` from curator
- Remove ports `8006:8006` and `8007:8007` from explore
- Add to api environment: NEO4J_ADDRESS, NEO4J_USERNAME, NEO4J_PASSWORD
- Add neo4j to api depends_on
- Remove curator from api depends_on (api no longer depends on curator)

### Step 18: Update `tests/api/conftest.py`
- Add NEO4J env vars to setdefault block
- Add `mock_neo4j` fixture (same as curator conftest)
- Update `test_api_config` to include neo4j fields
- Update `test_client` to also inject `_neo4j` and `_running_syncs` into api_module

### Step 19: Update `tests/curator/test_curator.py`
Remove TestTriggerSyncEndpoint, TestSyncStatusEndpoint, TestVerifyToken classes (moved to api)
Keep: TestGetHealthData, TestHealthEndpoint
Update get_health_data test — after stripping curator, `active_syncs` key is REMOVED from health data

### Step 20: Create `tests/api/test_sync.py`
Adapt TestTriggerSyncEndpoint + TestSyncStatusEndpoint from test_curator.py
Use `api.routers.sync` module paths in patches (not `curator.curator`)
Use `api_module._running_syncs` for state manipulation
The conftest test_client must inject _neo4j too

### Step 21: Create `tests/api/test_explore.py`
Adapt from tests/explore/test_explore_api.py
Use `api.routers.explore` module paths in patches
test_client uses api conftest (not explore conftest)
mock_neo4j_driver injected into api.routers.explore._neo4j_driver

### Step 22: Create `tests/api/test_snapshot.py`
Adapt from tests/explore/test_snapshot.py
Import SnapshotStore from `api.snapshot_store`
Use `api.routers.snapshot._snapshot_store` for store manipulation
Remove references to `explore.explore.snapshot_store`

### Step 23: Create `tests/api/test_user.py`
User endpoint tests adapted from explore service
Use `api.routers.user` module

### Step 24: Update `CLAUDE.md` (project CLAUDE.md in discogsography root)
Remove `Curator: 8010 (service), 8011 (health)` and `Explore: 8006 (service), 8007 (health)` from port table

## Key Design Facts
- `_running_syncs` lives in `api/api.py` at module level; same dict passed to `_sync_router.configure()`
- `api/routers/sync.py` stores a reference to that same dict (mutation visible to both)
- `api/routers/snapshot.py` has its own `_snapshot_store = SnapshotStore()` instance
- `api/routers/explore.py` imports AUTOCOMPLETE_DISPATCH etc from `api.queries.neo4j_queries`
- `api/routers/user.py` imports user_queries functions from `api.queries.user_queries`
- curator still runs on port 8010 internally (no external exposure)
- explore still runs on port 8007 internally (no external exposure)
- `ExploreConfig` in common/config.py stays — explore service still uses it
