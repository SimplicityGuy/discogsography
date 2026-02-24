# Issue #68 Implementation Checkpoint

Branch: `feature/issue-68-consolidate-api-endpoints`

## Status: IN PROGRESS

## Completed Steps

1. **common/config.py** - Added `neo4j_address`, `neo4j_username`, `neo4j_password` fields to `ApiConfig` dataclass and `from_env()` method. DONE.

## Remaining Steps (not yet started)

### Files to CREATE:
- `api/routers/__init__.py` (empty)
- `api/queries/__init__.py` (empty)
- `api/queries/neo4j_queries.py` (copy from explore/neo4j_queries.py, no import changes)
- `api/queries/user_queries.py` (copy from explore/user_queries.py, no import changes)
- `api/snapshot_store.py` (copy from explore/snapshot_store.py, no changes)
- `api/syncer.py` (copy from curator/syncer.py, no changes)
- `api/routers/sync.py` (new router with configure() pattern)
- `api/routers/explore.py` (new router with configure() pattern)
- `api/routers/snapshot.py` (new router)
- `api/routers/user.py` (new router)

### Files to UPDATE:
- `api/models.py` - Add SnapshotNode, SnapshotRequest, SnapshotResponse, SnapshotRestoreResponse from explore/models.py
- `api/api.py` - Add Neo4j init, _neo4j global, _running_syncs global, import+include all routers
- `api/pyproject.toml` - Add `neo4j>=6.1.0` to dependencies
- `curator/curator.py` - Strip sync routes, keep health only
- `explore/explore.py` - Strip all routes, keep health only
- `docker-compose.yml` - Remove ports 8006/8007/8010/8011, add Neo4j env to api, update depends_on
- `CLAUDE.md` - Update ports table

### Files to CREATE (tests):
- `tests/api/test_sync.py`
- `tests/api/test_explore.py`
- `tests/api/test_snapshot.py`
- `tests/api/test_user.py`

### Files to UPDATE (tests):
- `tests/api/conftest.py` - Add mock_neo4j fixture, update test_client to inject _neo4j
- `tests/curator/test_curator.py` - Remove HTTP route tests
- `tests/explore/test_explore_api.py` - Remove or update

## Key Design Decisions

- `api/routers/sync.py` imports `from api.syncer import run_full_sync` (syncer.py copied to api/)
- `api/routers/explore.py` imports from `api.queries.neo4j_queries`
- `api/routers/user.py` imports from `api.queries.user_queries`
- Each router has a `configure()` function called from `api/api.py` lifespan
- JWT helpers (_b64url_decode, _verify_jwt, _get_optional_user, _require_user) defined per-router independently
- curator service keeps minimal FastAPI app with /health only on port 8010 (internal only)
- explore service keeps minimal FastAPI app with /health only on port 8007 (internal only)

## Source Files Read

- api/api.py: Full content known
- api/models.py: Full content known
- api/pyproject.toml: Full content known
- curator/curator.py: Full content known (sync endpoints: POST /api/sync, GET /api/sync/status)
- explore/explore.py: Full content known (all routes)
- explore/models.py: Full content known
- explore/snapshot_store.py: Full content known
- common/config.py: Full content known, already updated
- tests/api/conftest.py: Full content known
- tests/curator/conftest.py: Full content known
- tests/explore/conftest.py: Full content known
- curator/pyproject.toml: Full content known
- explore/pyproject.toml: Full content known

## Files NOT YET read (need to read on resume):
- explore/neo4j_queries.py
- explore/user_queries.py
- curator/syncer.py
- docker-compose.yml (relevant sections)
- tests/curator/test_curator.py
- tests/explore/test_explore_api.py
- tests/explore/test_snapshot.py
- tests/explore/test_user_queries.py
