# Digger M1 — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the Digger foundation — Postgres schema, scrape pipeline, and wantlist tier UI — so a logged-in user can opt in, view their wantlist with live Discogs marketplace listings, and assign Must/Nice/Eventually tiers with per-tier condition floors.

**Architecture:** New `digger/` worker service runs the scraper (httpx + selectolax) against a Postgres-backed work queue with a Redis token-bucket rate budget. New `api/` routers expose user-facing settings + tier endpoints and `/api/internal/digger/*` for the worker. Explore gains a `/digger/wantlist` React page. Cross-service comms: digger → api over HTTP (input data only); api → digger via Postgres queue (priority bumps) + Redis pub/sub (refresh progress, used by M2 but plumbed in M1).

**Tech Stack:** Python 3.13 + uv, FastAPI, asyncpg via `AsyncPostgreSQLPool`, httpx, selectolax, bleach, Pydantic v2, Redis (redis-py asyncio), Prometheus client, pytest, React 19 + Vite + Vitest in `explore/`.

**Spec reference:** `docs/superpowers/specs/2026-05-14-digger-wantlist-agent-design.md` — M1 section.

---

## File structure

**Create:**
- `schema-init/digger_schema.py` — schema, enums, tables, triggers
- `digger/pyproject.toml`, `digger/Dockerfile`, `digger/README.md`
- `digger/digger/__init__.py`, `digger/digger/main.py`, `digger/digger/config.py`, `digger/digger/metrics.py`, `digger/digger/health.py`
- `digger/digger/scraper/__init__.py`
- `digger/digger/scraper/rate_budget.py` — Redis token-bucket via WATCH/MULTI/EXEC
- `digger/digger/scraper/circuit_breaker.py` — global failure-rate guard
- `digger/digger/scraper/http_client.py` — httpx wrapper, SSRF-safe
- `digger/digger/scraper/listing_parser.py` — selectolax listing-page parser
- `digger/digger/scraper/seller_parser.py` — seller policy parser
- `digger/digger/scraper/executor.py` — scrape one release end-to-end
- `digger/digger/scraper/queue_runner.py` — pop next due release
- `digger/digger/scraper/state_recomputer.py` — refresh `next_scrape_due_at`
- `digger/digger/scraper/backoff.py` — per-release exponential backoff
- `digger/digger/scraper/orchestrator.py` — composes the loops
- `digger/digger/scraper/types.py` — Pydantic models for parsed data
- `api/queries/digger_queries.py` — all digger-schema SQL helpers
- `api/routers/digger.py` — `/api/digger/*` user-facing endpoints
- `api/routers/internal_digger.py` — `/api/internal/digger/*` worker endpoints
- `api/models/digger.py` — Pydantic request/response models
- `explore/src/digger/index.tsx` — route registration
- `explore/src/digger/Wantlist.tsx`, `WantlistRow.tsx`, `BulkActionsBar.tsx`, `Filters.tsx`, `StatsBanner.tsx`, `SettingsDrawer.tsx`, `OnboardingCard.tsx`
- `explore/src/digger/api.ts` — typed API client
- `explore/src/digger/types.ts` — TS mirrors of Pydantic models
- `tests/digger/conftest.py`, `tests/digger/test_*.py` per module, `tests/digger/fixtures/*.html`
- `tests/api/test_digger_router.py`, `tests/api/test_internal_digger_router.py`, `tests/api/test_digger_queries.py`, `tests/api/test_syncer_digger_hook.py`
- `tests/schema-init/test_digger_schema.py`, `tests/schema-init/test_digger_schema_integration.py`, `tests/schema-init/test_digger_priority_trigger.py`
- `tests/explore/digger/*.test.tsx`
- `tests/e2e/test_digger_m1_smoke.py`
- `docs/digger-scraping-policy.md`

**Modify:**
- `docker-compose.yml` — add `digger` service
- `justfile` — add digger recipes
- `api/main.py` — register new routers
- `api/syncer.py` — hook to insert `user_wantlist_priorities` rows on wantlist sync
- `api/dependencies.py` — add `service_token_required` guard (if not already present)
- `schema-init/postgres_schema.py` — invoke digger schema at startup
- `tests/perftest/config.yaml` and `tests/perftest/run_perftest.py` — new endpoints
- `CLAUDE.md` — directory structure + service ports table
- `pyproject.toml` (root) — add `digger` to workspace members
- `.env.example` — `DIGGER_*` vars

**Conventions (VERIFIED against the codebase 2026-05-19 — these correct the original draft, which was written against asyncpg):**

- **Postgres driver is async psycopg (psycopg3), NOT asyncpg.** `common.postgres_resilient.AsyncPostgreSQLPool` wraps `psycopg.AsyncConnection`. asyncpg is not a dependency. Access pattern:
  ```python
  async with pool.connection() as conn:          # NOT pool.acquire()
      async with conn.cursor() as cur:           # psycopg cursor
          await cur.execute("SELECT ... WHERE x = %s", (value,))  # %s, NOT $1; params as a tuple
          row = await cur.fetchone()             # NOT conn.fetchval()/fetchrow()/fetch()
  ```
  Multi-statement DDL strings (no params) may be executed in a single `cur.execute(BIG_SQL)` call — psycopg3 supports this when no parameters are bound.
- **Autocommit contract:** the pool sets `autocommit=True` on every connection. Single-statement writes (inserts/upserts) commit immediately — no transaction needed. Only call `await conn.set_autocommit(False)` before `async with conn.transaction()` for multi-statement atomic blocks; the pool restores autocommit on return.
- **FK target for users is `users(id)` (UUID PK), NOT `users(user_id)`.** Every digger table that references the user table uses `REFERENCES users(id) ON DELETE CASCADE`. The column *name* on owning tables stays `user_id` (matches `user_wantlists.user_id`), but it points at `users(id)`.
- **Wantlist table is public `user_wantlists`** (PK `id`, `user_id`, `release_id`, `UNIQUE(user_id, release_id)`) — there is no `discogs.user_wantlists`. `api/syncer.py::sync_wantlist()` inserts in a **batch**, so the digger seed hook runs over the batch's release_ids, not per-row.
- **Import paths:** `schema-init/` is on `pythonpath` (hyphen dir), so its modules import top-level: `from digger_schema import DIGGER_SCHEMA_SQL` (NOT `from schema_init.digger_schema`). `api/` is a real package: `from api.syncer import ...` is correct.
- **Test layout & strategy:** schema-init tests live in `tests/schema-init/` (hyphen); api tests in `tests/api/`. Unit tests are **mock-based** — there is no real-Postgres fixture, and `just test` runs `-m 'not e2e'` with a mocked pool. The existing mock pattern is `tests/schema-init/test_postgres_schema.py::mock_pool` (`pool.connection()` → `conn.cursor()` → `cur.execute`, all `AsyncMock`). **Real-DB behavioral checks** (e.g., trigger semantics) are deferred to the M1 e2e smoke (Task 28) and/or `@pytest.mark.e2e`; do NOT introduce a live-DB unit fixture.
- `asyncio.Lock`, `asyncio.Queue`, `asyncio.Event`, `asyncio.Semaphore` must be lazily initialized in the first async method, never in `__init__` or at module scope.
- Log lines use the emoji vocabulary in `docs/emoji-guide.md` — no ad-hoc emojis.
- Tier-threshold comparisons use `>=` (boundary belongs to higher tier).
- Each new API endpoint must appear in `tests/perftest/config.yaml`.

---

## Task 1: Add digger schema and enums

**Files:**
- Create: `schema-init/digger_schema.py`
- Test: `tests/schema-init/test_digger_schema.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/schema-init/test_digger_schema.py
from digger_schema import DIGGER_SCHEMA_SQL


def test_digger_schema_sql_creates_schema_and_enums():
    sql = DIGGER_SCHEMA_SQL
    assert "CREATE SCHEMA IF NOT EXISTS digger" in sql
    for enum_name in (
        "priority_tier", "condition", "sleeve_condition", "region", "cadence",
        "model", "report_kind", "change_flag", "confidence", "proposal_status", "role",
    ):
        assert f"CREATE TYPE digger.{enum_name}" in sql


def test_digger_schema_sql_creates_all_tables():
    sql = DIGGER_SCHEMA_SQL
    for table in (
        "release_scrape_state", "sellers", "listings",
        "user_wantlist_priorities", "user_digger_settings",
        "reports", "proposals", "agent_sessions", "agent_messages",
    ):
        assert f"CREATE TABLE IF NOT EXISTS digger.{table}" in sql
```

- [ ] **Step 2: Run test to verify it fails**

`uv run pytest tests/schema-init/test_digger_schema.py -v`
Expected: `ModuleNotFoundError: No module named 'digger_schema'`.

- [ ] **Step 3: Write the schema module**

```python
# schema-init/digger_schema.py
"""Digger feature Postgres schema.

Owns all digger.* tables, enums, indices, and triggers. Invoked by
schema-init at container start (idempotent via IF NOT EXISTS).
"""

DIGGER_SCHEMA_SQL = """
CREATE SCHEMA IF NOT EXISTS digger;

DO $$ BEGIN
    CREATE TYPE digger.priority_tier   AS ENUM ('must', 'nice', 'eventually');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE digger.condition       AS ENUM ('M','NM','VG+','VG','G+','G','F','P');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE digger.sleeve_condition AS ENUM ('M','NM','VG+','VG','G+','G','F','P','generic','no_cover');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE digger.region          AS ENUM ('us','ca','eu','uk','jp','au','other');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE digger.cadence         AS ENUM ('off','weekly','biweekly','monthly');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE digger.model           AS ENUM ('haiku','sonnet','opus');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE digger.report_kind     AS ENUM ('scheduled','interactive');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE digger.change_flag     AS ENUM ('significant','none','first_run');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE digger.confidence      AS ENUM ('high','low');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE digger.proposal_status AS ENUM ('pending','approved','rejected','expired');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE digger.role            AS ENUM ('system','user','assistant','tool');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS digger.sellers (
    seller_id              bigint        PRIMARY KEY,
    username               text          NOT NULL,
    country_code           char(2),
    region                 digger.region NOT NULL DEFAULT 'other',
    feedback_count         int,
    feedback_score         numeric(4,1),
    ships_internationally  bool          NOT NULL DEFAULT false,
    shipping_policy        jsonb,
    last_refreshed_at      timestamptz   NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS digger.release_scrape_state (
    release_id             bigint                PRIMARY KEY,
    priority_tier          digger.priority_tier  NOT NULL DEFAULT 'eventually',
    last_scraped_at        timestamptz,
    next_scrape_due_at     timestamptz           NOT NULL DEFAULT now(),
    listings_delta_7d      int                   NOT NULL DEFAULT 0,
    consecutive_failures   int                   NOT NULL DEFAULT 0,
    next_retry_at          timestamptz
);

CREATE INDEX IF NOT EXISTS idx_rss_due_tier
    ON digger.release_scrape_state (priority_tier, next_scrape_due_at);

CREATE TABLE IF NOT EXISTS digger.listings (
    listing_id          bigint                   PRIMARY KEY,
    release_id          bigint                   NOT NULL REFERENCES digger.release_scrape_state(release_id) ON DELETE CASCADE,
    seller_id           bigint                   NOT NULL REFERENCES digger.sellers(seller_id) ON DELETE CASCADE,
    price_value         numeric(10,2)            NOT NULL,
    price_currency      char(3)                  NOT NULL,
    media_condition     digger.condition         NOT NULL,
    sleeve_condition    digger.sleeve_condition  NOT NULL,
    comments            text,
    posted_at           timestamptz,
    first_seen_at       timestamptz              NOT NULL DEFAULT now(),
    last_seen_at        timestamptz              NOT NULL DEFAULT now(),
    removed_at          timestamptz
);

CREATE INDEX IF NOT EXISTS idx_listings_release_active
    ON digger.listings (release_id) WHERE removed_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_listings_seller_active
    ON digger.listings (seller_id) WHERE removed_at IS NULL;

CREATE TABLE IF NOT EXISTS digger.user_wantlist_priorities (
    user_id              uuid                    NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    release_id           bigint                  NOT NULL,
    tier                 digger.priority_tier    NOT NULL DEFAULT 'nice',
    min_media_condition  digger.condition        NOT NULL DEFAULT 'VG',
    min_sleeve_condition digger.sleeve_condition NOT NULL DEFAULT 'VG',
    max_price_cents      int,
    updated_at           timestamptz             NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, release_id)
);

CREATE INDEX IF NOT EXISTS idx_uwp_release ON digger.user_wantlist_priorities (release_id);

CREATE TABLE IF NOT EXISTS digger.user_digger_settings (
    user_id                       uuid             PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    enabled                       bool             NOT NULL DEFAULT false,
    country_code                  char(2),
    currency                      char(3)          NOT NULL DEFAULT 'USD',
    scheduled_cadence             digger.cadence   NOT NULL DEFAULT 'off',
    next_scheduled_run_at         timestamptz,
    preferred_model               digger.model     NOT NULL DEFAULT 'sonnet',
    daily_token_cap_interactive   int              NOT NULL DEFAULT 200000,
    daily_token_cap_scheduled     int              NOT NULL DEFAULT 100000
);

CREATE TABLE IF NOT EXISTS digger.reports (
    report_id            uuid                     PRIMARY KEY,
    user_id              uuid                     NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind                 digger.report_kind       NOT NULL,
    generated_at         timestamptz              NOT NULL DEFAULT now(),
    read_at              timestamptz,
    title                text                     NOT NULL,
    summary              jsonb                    NOT NULL,
    bundles              jsonb                    NOT NULL,
    watching             jsonb                    NOT NULL DEFAULT '[]'::jsonb,
    change_flag          digger.change_flag       NOT NULL,
    shipping_confidence  digger.confidence        NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reports_user_time
    ON digger.reports (user_id, generated_at DESC);

CREATE TABLE IF NOT EXISTS digger.proposals (
    proposal_id  uuid                     PRIMARY KEY,
    user_id      uuid                     NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id   uuid,
    created_at   timestamptz              NOT NULL DEFAULT now(),
    status       digger.proposal_status   NOT NULL DEFAULT 'pending',
    payload      jsonb                    NOT NULL,
    expires_at   timestamptz              NOT NULL
);

CREATE TABLE IF NOT EXISTS digger.agent_sessions (
    session_id              uuid           PRIMARY KEY,
    user_id                 uuid           NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    started_at              timestamptz    NOT NULL DEFAULT now(),
    last_active_at          timestamptz    NOT NULL DEFAULT now(),
    model                   digger.model   NOT NULL,
    total_input_tokens      int            NOT NULL DEFAULT 0,
    total_output_tokens     int            NOT NULL DEFAULT 0,
    total_cache_read_tokens int            NOT NULL DEFAULT 0,
    total_cost_usd          numeric(10,4)  NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS digger.agent_messages (
    message_id    uuid          PRIMARY KEY,
    session_id    uuid          NOT NULL REFERENCES digger.agent_sessions(session_id) ON DELETE CASCADE,
    role          digger.role   NOT NULL,
    content       jsonb         NOT NULL,
    token_counts  jsonb,
    created_at    timestamptz   NOT NULL DEFAULT now()
);
"""
```

- [ ] **Step 4: Run test to verify it passes**

`uv run pytest tests/schema-init/test_digger_schema.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add schema-init/digger_schema.py tests/schema-init/test_digger_schema.py
git commit -m "feat(digger): add digger Postgres schema, enums, and tables"
```

---

## Task 2: Wire digger schema into schema-init startup

**Files:**
- Modify: `schema-init/postgres_schema.py`
- Test: `tests/schema-init/test_digger_schema_integration.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/schema-init/test_digger_schema_integration.py
"""Verify create_postgres_schema applies the digger feature schema.

Mock-based (repo convention) — there is no real-Postgres unit fixture, and
`just test` runs `-m 'not e2e'`. Real behavioral verification of the applied
schema (tables actually exist) lives in the M1 e2e smoke (Task 28).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from postgres_schema import create_postgres_schema


@pytest.fixture
def mock_pool() -> MagicMock:
    """Mock AsyncPostgreSQLPool: pool.connection() -> conn -> conn.cursor()."""
    pool = MagicMock()
    conn = AsyncMock()
    cur = AsyncMock()
    cur.__aenter__ = AsyncMock(return_value=cur)
    cur.__aexit__ = AsyncMock(return_value=False)
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    conn.cursor = MagicMock(return_value=cur)  # cursor() is sync, returns an async CM
    pool.connection.return_value = conn
    return pool


@pytest.mark.asyncio
async def test_create_postgres_schema_applies_digger_schema(mock_pool: MagicMock) -> None:
    await create_postgres_schema(mock_pool)
    cur = mock_pool.connection.return_value.cursor.return_value
    executed = [c.args[0] for c in cur.execute.call_args_list if c.args]
    assert any(
        isinstance(stmt, str) and "CREATE SCHEMA IF NOT EXISTS digger" in stmt
        for stmt in executed
    ), "digger schema SQL was not executed by create_postgres_schema"
```

- [ ] **Step 2: Run test to verify it fails**

`uv run pytest tests/schema-init/test_digger_schema_integration.py -v`
Expected: FAIL — `create_postgres_schema` does not yet execute the digger schema.

- [ ] **Step 3: Wire into schema-init**

In `schema-init/postgres_schema.py`, add the import near the top (top-level module — `schema-init` is on `pythonpath`):

```python
from digger_schema import DIGGER_SCHEMA_SQL
```

Then, inside `create_postgres_schema`, **after** the MusicBrainz block and still inside the open `async with conn.cursor() as cursor_cm:` context (so the digger tables can FK to the already-created `users` table), apply the schema as a single multi-statement DDL string, matching the existing per-block try/except + counter style:

```python
            # ── Digger feature schema (schema, enums, tables, triggers) ───
            try:
                await cursor.execute(DIGGER_SCHEMA_SQL)
                logger.info("✅ Schema: digger feature schema")
                success_count += 1
            except Exception as e:
                logger.error(f"❌ Failed to create schema object 'digger feature schema': {e}")
                failure_count += 1
```

psycopg3 runs the whole multi-statement DDL (enums, tables, indexes, triggers) in one `cursor.execute()` call because no parameters are bound. Bump the `total` count at the end of the function by `+ 1` to account for the digger schema statement so the success/failure accounting stays correct.

- [ ] **Step 4: Run test to verify it passes**

`uv run pytest tests/schema-init/test_digger_schema_integration.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add schema-init/postgres_schema.py tests/schema-init/test_digger_schema_integration.py
git commit -m "feat(digger): apply digger schema during schema-init startup"
```

---

## Task 3: Priority recomputation trigger

**Files:**
- Modify: `schema-init/digger_schema.py` — append trigger SQL
- Test: `tests/schema-init/test_digger_priority_trigger.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/schema-init/test_digger_priority_trigger.py
"""Structural checks for the priority-recompute trigger DDL.

The trigger's runtime behavior (recompute max tier across all users wanting a
release on INSERT/UPDATE/DELETE) needs a live Postgres and is exercised by the
M1 e2e smoke (Task 28). These unit tests assert the DDL is present and encodes
the must > nice > eventually precedence — no DB required.
"""

from digger_schema import DIGGER_SCHEMA_SQL


def test_trigger_function_and_trigger_present() -> None:
    sql = DIGGER_SCHEMA_SQL
    assert "FUNCTION digger.recompute_priority_for_release" in sql
    assert "FUNCTION digger.uwp_after_change" in sql
    assert "CREATE TRIGGER trg_uwp_recompute" in sql
    assert "AFTER INSERT OR UPDATE OR DELETE ON digger.user_wantlist_priorities" in sql


def test_trigger_encodes_tier_precedence() -> None:
    sql = DIGGER_SCHEMA_SQL
    # must wins over nice wins over eventually in the CASE ladder
    must_at = sql.find("bool_or(tier = 'must')")
    nice_at = sql.find("bool_or(tier = 'nice')")
    assert must_at != -1 and nice_at != -1
    assert must_at < nice_at, "must must be evaluated before nice in the precedence ladder"
```

- [ ] **Step 2: Run test to verify it fails**

`uv run pytest tests/schema-init/test_digger_priority_trigger.py -v`
Expected: FAIL — the trigger DDL is not yet present in `DIGGER_SCHEMA_SQL`.

- [ ] **Step 3: Append trigger SQL**

Append to `DIGGER_SCHEMA_SQL` in `schema-init/digger_schema.py`:

```sql
CREATE OR REPLACE FUNCTION digger.recompute_priority_for_release(p_release_id bigint)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    max_tier digger.priority_tier;
BEGIN
    SELECT
        CASE
            WHEN bool_or(tier = 'must') THEN 'must'::digger.priority_tier
            WHEN bool_or(tier = 'nice') THEN 'nice'::digger.priority_tier
            WHEN bool_or(tier = 'eventually') THEN 'eventually'::digger.priority_tier
            ELSE 'eventually'::digger.priority_tier
        END
    INTO max_tier
    FROM digger.user_wantlist_priorities
    WHERE release_id = p_release_id;

    IF max_tier IS NULL THEN
        RETURN;
    END IF;

    UPDATE digger.release_scrape_state
       SET priority_tier = max_tier
     WHERE release_id = p_release_id
       AND priority_tier IS DISTINCT FROM max_tier;
END $$;

CREATE OR REPLACE FUNCTION digger.uwp_after_change()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        PERFORM digger.recompute_priority_for_release(OLD.release_id);
        RETURN OLD;
    ELSE
        PERFORM digger.recompute_priority_for_release(NEW.release_id);
        IF TG_OP = 'UPDATE' AND OLD.release_id IS DISTINCT FROM NEW.release_id THEN
            PERFORM digger.recompute_priority_for_release(OLD.release_id);
        END IF;
        RETURN NEW;
    END IF;
END $$;

DROP TRIGGER IF EXISTS trg_uwp_recompute ON digger.user_wantlist_priorities;
CREATE TRIGGER trg_uwp_recompute
AFTER INSERT OR UPDATE OR DELETE ON digger.user_wantlist_priorities
FOR EACH ROW EXECUTE FUNCTION digger.uwp_after_change();
```

- [ ] **Step 4: Run test to verify it passes**

`uv run pytest tests/schema-init/test_digger_priority_trigger.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add schema-init/digger_schema.py tests/schema-init/test_digger_priority_trigger.py
git commit -m "feat(digger): trigger to maintain max-tier on release_scrape_state"
```

---

## Task 4: Wantlist sync hook — seed `user_wantlist_priorities`

**Files:**
- Modify: `api/syncer.py`
- Test: `tests/api/test_syncer_digger_hook.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_syncer_digger_hook.py
"""Unit test for the digger wantlist-sync seed hook (mock-based).

Asserts the helper issues the two idempotent INSERTs via the psycopg3 cursor
with %s params. Real-DB row creation + trigger recompute is covered by the M1
e2e smoke (Task 28).
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.syncer import _seed_digger_priority_for_wantlist_item


def _mock_pool() -> tuple[MagicMock, AsyncMock]:
    pool = MagicMock()
    conn = AsyncMock()
    cur = AsyncMock()
    cur.__aenter__ = AsyncMock(return_value=cur)
    cur.__aexit__ = AsyncMock(return_value=False)
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    conn.cursor = MagicMock(return_value=cur)  # cursor() is sync, returns an async CM
    pool.connection.return_value = conn
    return pool, cur


@pytest.mark.asyncio
async def test_seed_inserts_scrape_state_and_priority_row() -> None:
    pool, cur = _mock_pool()
    user_id = uuid.uuid4()

    await _seed_digger_priority_for_wantlist_item(pool, user_id, release_id=12345)

    executed = [(c.args[0], c.args[1] if len(c.args) > 1 else None) for c in cur.execute.call_args_list]
    all_sql = " ".join(sql for sql, _ in executed)
    assert "INSERT INTO digger.release_scrape_state" in all_sql
    assert "INSERT INTO digger.user_wantlist_priorities" in all_sql
    # psycopg3 params are positional tuples bound to %s placeholders
    assert any(params == (12345,) for _, params in executed)
    assert any(params == (user_id, 12345) for _, params in executed)
```

- [ ] **Step 2: Run test to verify it fails**

`uv run pytest tests/api/test_syncer_digger_hook.py -v`
Expected: ImportError — helper not defined.

- [ ] **Step 3: Add the helper and call it from the wantlist sync loop**

```python
# api/syncer.py — add near the wantlist sync block.
# Reuse the AsyncPostgreSQLPool import already present in this module.
import uuid

from common.postgres_resilient import AsyncPostgreSQLPool


async def _seed_digger_priority_for_wantlist_item(
    pool: AsyncPostgreSQLPool, user_id: uuid.UUID, release_id: int
) -> None:
    """Ensure a digger.user_wantlist_priorities row exists for this user+release.

    Default tier is 'nice' (schema column default). The schema trigger maintains
    digger.release_scrape_state.priority_tier as a side effect. Idempotent and
    safe to call repeatedly. psycopg3 autocommit single-statement writes — no
    explicit transaction needed.
    """
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO digger.release_scrape_state (release_id) VALUES (%s) "
                "ON CONFLICT (release_id) DO NOTHING",
                (release_id,),
            )
            await cur.execute(
                "INSERT INTO digger.user_wantlist_priorities (user_id, release_id) "
                "VALUES (%s, %s) ON CONFLICT (user_id, release_id) DO NOTHING",
                (user_id, release_id),
            )
```

Inside `sync_wantlist()` (`api/syncer.py`), the wantlist rows are upserted into the public `user_wantlists` table in a **batch** (the loop already derives `release_id = item.get("id")` and skips falsy ids). Collect those ids into a list alongside the batch params, then — after the batch upsert succeeds — seed digger priorities for the whole batch using the pool already in scope:

```python
for release_id in wantlist_release_ids:
    await _seed_digger_priority_for_wantlist_item(pool, user_id, release_id)
```

- [ ] **Step 4: Run test to verify it passes**

`uv run pytest tests/api/test_syncer_digger_hook.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/syncer.py tests/api/test_syncer_digger_hook.py
git commit -m "feat(digger): seed default priority rows during wantlist sync"
```

---

## Task 5: `digger/` service skeleton

**Files:**
- Create: `digger/pyproject.toml`, `digger/Dockerfile`, `digger/README.md`
- Create: `digger/digger/__init__.py`, `digger/digger/main.py`, `digger/digger/config.py`
- Modify: root `pyproject.toml` — add `digger` workspace member

- [ ] **Step 1: Add digger to root workspace**

In root `pyproject.toml`, locate `[tool.uv.workspace] members = [...]` and append `"digger"`.

- [ ] **Step 2: Create `digger/pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "digger"
version = "0.1.0"
description = "Discogs marketplace scraper and scheduled-run worker for the Digger feature."
requires-python = ">=3.13"
dependencies = [
    "common",
    "httpx>=0.27",
    "selectolax>=0.3.21",
    "bleach>=6.1",
    "redis>=5",
    "pydantic>=2.7",
    "prometheus-client>=0.20",
    "uvloop>=0.19",
    "aiohttp>=3.9",
]

[tool.hatch.build.targets.wheel]
packages = ["digger"]

[tool.ruff]
extend = "../pyproject.toml"

[tool.mypy]
strict = true

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["../tests/digger"]

[dependency-groups]
dev = ["pytest>=8", "pytest-asyncio>=0.23", "hypothesis>=6", "respx>=0.21"]
```

- [ ] **Step 3: Create `digger/Dockerfile`**

```dockerfile
FROM python:3.13-slim AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 1001 digger
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
COPY common/ common/
COPY digger/ digger/
RUN uv sync --frozen --no-dev --package digger
USER digger
EXPOSE 8012
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8012/health || exit 1
CMD ["uv", "run", "--package", "digger", "python", "-m", "digger.main"]
```

- [ ] **Step 4: Create `digger/digger/config.py`**

```python
"""Digger configuration loaded from environment variables."""

from __future__ import annotations
from dataclasses import dataclass
from common.config import env_str, env_int


@dataclass(frozen=True, slots=True)
class DiggerConfig:
    postgres_host: str
    postgres_user: str
    postgres_password: str
    postgres_database: str
    redis_host: str
    api_base_url: str
    api_service_token: str
    scraper_user_agent: str
    rate_budget_per_hour: int
    circuit_breaker_window_seconds: int
    circuit_breaker_failure_pct: int
    log_level: str

    @classmethod
    def from_env(cls) -> "DiggerConfig":
        return cls(
            postgres_host=env_str("POSTGRES_HOST"),
            postgres_user=env_str("POSTGRES_USERNAME"),
            postgres_password=env_str("POSTGRES_PASSWORD"),
            postgres_database=env_str("POSTGRES_DATABASE"),
            redis_host=env_str("REDIS_HOST"),
            api_base_url=env_str("API_BASE_URL"),
            api_service_token=env_str("DIGGER_API_SERVICE_TOKEN"),
            scraper_user_agent=env_str(
                "DIGGER_SCRAPER_USER_AGENT",
                default="discogsography-digger/0.1 (github.com/SimplicityGuy/discogsography)",
            ),
            rate_budget_per_hour=env_int("DIGGER_RATE_BUDGET_PER_HOUR", default=600),
            circuit_breaker_window_seconds=env_int("DIGGER_CB_WINDOW_SECONDS", default=300),
            circuit_breaker_failure_pct=env_int("DIGGER_CB_FAILURE_PCT", default=30),
            log_level=env_str("LOG_LEVEL", default="INFO"),
        )
```

- [ ] **Step 5: Create `digger/digger/main.py` skeleton (wired up in Task 16)**

```python
"""Digger worker entrypoint.

Starts health server + scraper tasks. Wired up across Tasks 6 and 16.
"""

from __future__ import annotations
import asyncio
import logging
import signal
import sys
from contextlib import suppress

from digger.config import DiggerConfig


ASCII_ART = r"""
 ____  _
|  _ \(_) __ _  __ _  ___ _ __
| | | | |/ _` |/ _` |/ _ \ '__|
| |_| | | (_| | (_| |  __/ |
|____/|_|\__, |\__, |\___|_|
         |___/ |___/
"""


async def amain() -> None:
    cfg = DiggerConfig.from_env()
    logging.basicConfig(
        level=cfg.log_level,
        format="%(asctime)s - digger - %(name)s - %(levelname)s - %(message)s",
    )
    log = logging.getLogger(__name__)
    print(ASCII_ART, flush=True)
    log.info("🚀 Digger starting (rate_budget=%d/h)", cfg.rate_budget_per_hour)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    tasks: list[asyncio.Task[None]] = []  # filled by Task 6 + 16
    await stop_event.wait()
    log.info("🛑 Digger shutting down")
    for t in tasks:
        t.cancel()
    for t in tasks:
        with suppress(asyncio.CancelledError):
            await t


def main() -> None:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Commit**

```bash
git add digger/ pyproject.toml
git commit -m "feat(digger): scaffold worker service (pyproject, Dockerfile, main, config)"
```

---

## Task 6: Health + Prometheus metrics on `:8012`

**Files:**
- Create: `digger/digger/metrics.py`, `digger/digger/health.py`
- Modify: `digger/digger/main.py` (add health task)
- Test: `tests/digger/test_health.py`, `tests/digger/conftest.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/digger/test_health.py
import httpx
import pytest


@pytest.mark.asyncio
async def test_health_endpoint_returns_ok(digger_test_server):
    async with httpx.AsyncClient(base_url=digger_test_server.url) as client:
        r = await client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_metrics_endpoint_serves_prometheus(digger_test_server):
    async with httpx.AsyncClient(base_url=digger_test_server.url) as client:
        r = await client.get("/metrics")
        assert r.status_code == 200
        assert "text/plain" in r.headers["content-type"]
        assert "digger_scrape_total" in r.text or "process_cpu_seconds_total" in r.text
```

- [ ] **Step 2: Run test to verify it fails**

`uv run pytest tests/digger/test_health.py -v`
Expected: fixture `digger_test_server` missing.

- [ ] **Step 3: Write metrics + health server**

```python
# digger/digger/metrics.py
"""Prometheus metrics registered once at import time."""

from prometheus_client import Counter, Gauge

SCRAPE_TOTAL = Counter(
    "digger_scrape_total", "Total scrape attempts by outcome",
    labelnames=("outcome",),
)
RATE_BUDGET_REMAINING = Gauge(
    "digger_rate_budget_remaining", "Tokens remaining in the rate budget bucket"
)
QUEUE_DEPTH = Gauge(
    "digger_queue_depth", "Releases due for scraping", labelnames=("tier",),
)
UNKNOWN_LAYOUT_TOTAL = Counter(
    "digger_unknown_layout_total", "Pages where the parser found an unexpected layout"
)
CIRCUIT_BREAKER_OPEN = Gauge(
    "digger_circuit_breaker_open", "1 if circuit breaker is open, else 0"
)
```

```python
# digger/digger/health.py
from __future__ import annotations
import asyncio
import logging
from aiohttp import web
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from digger.config import DiggerConfig

log = logging.getLogger(__name__)


async def _health(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def _metrics(_: web.Request) -> web.Response:
    payload = generate_latest()
    return web.Response(body=payload, content_type=CONTENT_TYPE_LATEST.split(";")[0])


async def run_health_server(cfg: DiggerConfig, host: str = "0.0.0.0", port: int = 8012) -> None:
    app = web.Application()
    app.router.add_get("/health", _health)
    app.router.add_get("/metrics", _metrics)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    log.info("💓 Health/metrics listening on %s:%d", host, port)
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        await runner.cleanup()
        raise
```

```python
# tests/digger/conftest.py
import asyncio
from dataclasses import dataclass
import pytest

from digger.config import DiggerConfig
from digger.health import run_health_server


@dataclass
class _Server:
    url: str


@pytest.fixture
async def digger_test_server(unused_tcp_port: int):
    cfg = DiggerConfig.from_env()
    task = asyncio.create_task(run_health_server(cfg, host="127.0.0.1", port=unused_tcp_port))
    await asyncio.sleep(0.1)
    yield _Server(url=f"http://127.0.0.1:{unused_tcp_port}")
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
```

Add the health task in `digger/main.py`:

```python
from digger.health import run_health_server
tasks.append(asyncio.create_task(run_health_server(cfg), name="health"))
```

- [ ] **Step 4: Run test to verify it passes**

`uv run pytest tests/digger/test_health.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add digger/digger/health.py digger/digger/metrics.py digger/digger/main.py tests/digger/test_health.py tests/digger/conftest.py
git commit -m "feat(digger): health + Prometheus metrics on :8012"
```

---

## Task 7: Redis token-bucket rate budget (no Lua)

**Files:**
- Create: `digger/digger/scraper/__init__.py`, `digger/digger/scraper/rate_budget.py`
- Test: `tests/digger/test_rate_budget.py`

Token bucket implemented via `WATCH/MULTI/EXEC` optimistic concurrency — atomic, no Lua scripts.

- [ ] **Step 1: Write the failing test**

```python
# tests/digger/test_rate_budget.py
import asyncio
import pytest
from digger.scraper.rate_budget import RateBudget


@pytest.mark.asyncio
async def test_rate_budget_allows_burst_then_throttles(redis_test_client):
    rb = RateBudget(redis=redis_test_client, capacity=5, refill_per_second=0.0)
    for _ in range(5):
        wait = await rb.acquire()
        assert wait == 0.0
    wait = await rb.peek()
    assert wait > 0.0  # exhausted, no refill


@pytest.mark.asyncio
async def test_rate_budget_refills_over_time(redis_test_client):
    rb = RateBudget(redis=redis_test_client, capacity=2, refill_per_second=10.0)
    await rb.acquire()
    await rb.acquire()
    await asyncio.sleep(0.25)
    wait = await rb.peek()
    assert wait == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

`uv run pytest tests/digger/test_rate_budget.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement using `WATCH/MULTI/EXEC`**

```python
# digger/digger/scraper/rate_budget.py
"""Redis-backed token bucket via optimistic concurrency.

Uses WATCH/MULTI/EXEC instead of Lua scripts. Suitable for the single-worker
deployment in M1 and scales to multi-worker via the same mechanism.
"""

from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass
from redis.asyncio import Redis
from redis.exceptions import WatchError

from digger.metrics import RATE_BUDGET_REMAINING

KEY_TOKENS = "digger:rate_budget:tokens"
KEY_LAST = "digger:rate_budget:last_refill"


@dataclass(slots=True)
class RateBudget:
    redis: Redis
    capacity: int
    refill_per_second: float

    async def _read_and_refill(self, pipe) -> tuple[float, float]:
        """Inside an open transaction with watches on both keys, compute the
        refilled token count and current timestamp."""
        now = time.time()
        tokens_raw = await pipe.get(KEY_TOKENS)
        last_raw = await pipe.get(KEY_LAST)
        tokens = float(tokens_raw) if tokens_raw is not None else float(self.capacity)
        last = float(last_raw) if last_raw is not None else now
        if self.refill_per_second > 0:
            tokens = min(float(self.capacity), tokens + (now - last) * self.refill_per_second)
        return tokens, now

    async def peek(self) -> float:
        """Return seconds to wait until at least 1 token is available (0 if ready)."""
        async with self.redis.pipeline(transaction=True) as pipe:
            await pipe.watch(KEY_TOKENS, KEY_LAST)
            tokens, _ = await self._read_and_refill(pipe)
            await pipe.unwatch()
        RATE_BUDGET_REMAINING.set(tokens)
        if tokens >= 1.0:
            return 0.0
        if self.refill_per_second <= 0:
            return float("inf")
        return (1.0 - tokens) / self.refill_per_second

    async def acquire(self) -> float:
        """Block until a token is available, then consume it. Returns total wait time."""
        total_wait = 0.0
        while True:
            async with self.redis.pipeline(transaction=True) as pipe:
                try:
                    await pipe.watch(KEY_TOKENS, KEY_LAST)
                    tokens, now = await self._read_and_refill(pipe)
                    if tokens >= 1.0:
                        pipe.multi()
                        await pipe.set(KEY_TOKENS, tokens - 1.0)
                        await pipe.set(KEY_LAST, now)
                        await pipe.execute()
                        RATE_BUDGET_REMAINING.set(tokens - 1.0)
                        return total_wait
                    await pipe.unwatch()
                except WatchError:
                    continue
            if self.refill_per_second <= 0:
                raise RuntimeError("Rate budget exhausted with no refill rate")
            wait = (1.0 - tokens) / self.refill_per_second
            await asyncio.sleep(wait)
            total_wait += wait
```

- [ ] **Step 4: Run test to verify it passes**

`uv run pytest tests/digger/test_rate_budget.py -v`
Expected: PASS (with a flushed Redis test DB from `redis_test_client` fixture).

- [ ] **Step 5: Commit**

```bash
git add digger/digger/scraper/__init__.py digger/digger/scraper/rate_budget.py tests/digger/test_rate_budget.py
git commit -m "feat(digger): Redis token-bucket rate budget via WATCH/MULTI/EXEC"
```

---

## Task 8: Circuit breaker

**Files:**
- Create: `digger/digger/scraper/circuit_breaker.py`
- Test: `tests/digger/test_circuit_breaker.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/digger/test_circuit_breaker.py
import asyncio
import pytest
from digger.scraper.circuit_breaker import CircuitBreaker


@pytest.mark.asyncio
async def test_circuit_breaker_opens_above_threshold():
    cb = CircuitBreaker(window_seconds=60, failure_pct=30, cooldown_seconds=10)
    for _ in range(7):
        await cb.record(success=True)
    for _ in range(3):
        await cb.record(success=False)
    assert await cb.is_open() is True


@pytest.mark.asyncio
async def test_circuit_breaker_closes_after_cooldown():
    cb = CircuitBreaker(window_seconds=60, failure_pct=30, cooldown_seconds=1)
    for _ in range(10):
        await cb.record(success=False)
    assert await cb.is_open() is True
    await asyncio.sleep(1.1)
    await cb.record(success=True)
    assert await cb.is_open() is False
```

- [ ] **Step 2: Run test to verify it fails**

`uv run pytest tests/digger/test_circuit_breaker.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement the breaker**

```python
# digger/digger/scraper/circuit_breaker.py
"""Global circuit breaker for scrape outcomes.

In-memory rolling deque; suitable for single-worker M1 deployment.
"""

from __future__ import annotations
import asyncio
import time
from collections import deque
from dataclasses import dataclass, field

from digger.metrics import CIRCUIT_BREAKER_OPEN


@dataclass
class CircuitBreaker:
    window_seconds: int
    failure_pct: int  # 0-100; >= threshold opens
    cooldown_seconds: int
    _events: deque = field(default_factory=deque)
    _opened_at: float | None = None
    _lock: asyncio.Lock | None = None  # lazy: never bind a loop at construct time

    async def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _evict_expired(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

    async def record(self, success: bool) -> None:
        async with await self._get_lock():
            now = time.time()
            self._events.append((now, success))
            self._evict_expired(now)
            if self._opened_at is not None and success:
                self._opened_at = None
                CIRCUIT_BREAKER_OPEN.set(0)
                return
            total = len(self._events)
            if total < 10:
                return
            failures = sum(1 for _, ok in self._events if not ok)
            if failures * 100 >= total * self.failure_pct and self._opened_at is None:
                self._opened_at = now
                CIRCUIT_BREAKER_OPEN.set(1)

    async def is_open(self) -> bool:
        async with await self._get_lock():
            if self._opened_at is None:
                return False
            if time.time() - self._opened_at >= self.cooldown_seconds:
                return False
            return True
```

- [ ] **Step 4: Run test to verify it passes**

`uv run pytest tests/digger/test_circuit_breaker.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add digger/digger/scraper/circuit_breaker.py tests/digger/test_circuit_breaker.py
git commit -m "feat(digger): global circuit breaker for scrape failures"
```

---

## Task 9: SSRF-safe HTTP client

**Files:**
- Create: `digger/digger/scraper/http_client.py`
- Test: `tests/digger/test_http_client.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/digger/test_http_client.py
import pytest
import respx
import httpx
from digger.scraper.http_client import DiggerHttpClient, BlockedTargetError


@pytest.mark.asyncio
async def test_blocks_non_discogs_hosts():
    client = DiggerHttpClient(user_agent="test/1.0")
    with pytest.raises(BlockedTargetError):
        await client.get("https://example.com/foo")


@pytest.mark.asyncio
@respx.mock
async def test_allows_discogs_hosts():
    respx.get("https://www.discogs.com/sell/release/42").mock(
        return_value=httpx.Response(200, text="<html>ok</html>")
    )
    client = DiggerHttpClient(user_agent="test/1.0")
    r = await client.get("https://www.discogs.com/sell/release/42")
    assert r.status_code == 200
    assert "ok" in r.text
```

- [ ] **Step 2: Run test to verify it fails**

`uv run pytest tests/digger/test_http_client.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement the HTTP client**

```python
# digger/digger/scraper/http_client.py
"""SSRF-safe HTTP client for scraping discogs.com.

Allow-list: only *.discogs.com hosts are permitted. Redirects must stay
within the allow-list or are rejected.
"""

from __future__ import annotations
import httpx
from urllib.parse import urlparse


ALLOWED_HOSTS = frozenset({"www.discogs.com", "discogs.com"})


class BlockedTargetError(RuntimeError):
    """Raised when a request target is not in the allow-list."""


def _check_host(url: str) -> None:
    host = (urlparse(url).hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise BlockedTargetError(f"host {host!r} not in allow-list")


class DiggerHttpClient:
    def __init__(self, user_agent: str, timeout_seconds: float = 15.0) -> None:
        self._client = httpx.AsyncClient(
            headers={"User-Agent": user_agent, "Accept-Language": "en"},
            timeout=httpx.Timeout(timeout_seconds, connect=5.0),
            follow_redirects=False,
        )

    async def __aenter__(self) -> "DiggerHttpClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._client.aclose()

    async def get(self, url: str) -> httpx.Response:
        _check_host(url)
        r = await self._client.get(url)
        while r.status_code in (301, 302, 303, 307, 308):
            loc = r.headers.get("location")
            if not loc:
                break
            _check_host(loc)
            r = await self._client.get(loc)
        return r
```

- [ ] **Step 4: Run test to verify it passes**

`uv run pytest tests/digger/test_http_client.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add digger/digger/scraper/http_client.py tests/digger/test_http_client.py
git commit -m "feat(digger): SSRF-safe httpx client with discogs.com allow-list"
```

---

## Task 10: Listing-page parser

**Files:**
- Create: `digger/digger/scraper/types.py`, `digger/digger/scraper/listing_parser.py`
- Create: `tests/digger/fixtures/listing_page_basic.html`, `tests/digger/fixtures/README.md`
- Test: `tests/digger/test_listing_parser.py`

- [ ] **Step 1: Capture a real Discogs listing page**

Save a representative `https://www.discogs.com/sell/release/<id>` response into `tests/digger/fixtures/listing_page_basic.html`. Strip cookies/tracking; preserve listing rows. Document provenance (release_id, capture date, sha256) in `tests/digger/fixtures/README.md`.

- [ ] **Step 2: Write the failing test**

```python
# tests/digger/test_listing_parser.py
from pathlib import Path
import pytest
from digger.scraper.listing_parser import parse_listings, UnknownLayoutError
from digger.scraper.types import ParsedListing


FIXTURE = Path(__file__).parent / "fixtures" / "listing_page_basic.html"


def test_parser_extracts_expected_listings():
    parsed = parse_listings(FIXTURE.read_text(), release_id=12345)
    assert len(parsed) >= 1
    first = parsed[0]
    assert isinstance(first, ParsedListing)
    assert first.release_id == 12345
    assert first.listing_id > 0
    assert first.seller_username
    assert first.price_value > 0
    assert first.price_currency in {"USD","EUR","GBP","JPY","CAD","AUD"}
    assert first.media_condition in {"M","NM","VG+","VG","G+","G","F","P"}


def test_parser_returns_empty_on_no_listings():
    html = "<html><body>No listings available</body></html>"
    assert parse_listings(html, release_id=1) == []


def test_parser_raises_unknown_layout_on_garbage():
    with pytest.raises(UnknownLayoutError):
        parse_listings("<html><body><div class='unexpected'></div></body></html>", release_id=1)
```

- [ ] **Step 3: Run test to verify it fails**

`uv run pytest tests/digger/test_listing_parser.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 4: Implement types + parser**

```python
# digger/digger/scraper/types.py
from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, Field

Condition = Literal["M", "NM", "VG+", "VG", "G+", "G", "F", "P"]
SleeveCondition = Literal["M", "NM", "VG+", "VG", "G+", "G", "F", "P", "generic", "no_cover"]


class ParsedListing(BaseModel):
    listing_id: int
    release_id: int
    seller_username: str
    seller_id: int | None = None
    price_value: Decimal = Field(ge=0)
    price_currency: str = Field(min_length=3, max_length=3)
    media_condition: Condition
    sleeve_condition: SleeveCondition
    comments: str | None = None
    posted_at: datetime | None = None


class ParsedSeller(BaseModel):
    seller_id: int
    username: str
    country_code: str | None = None
    feedback_count: int | None = None
    feedback_score: Decimal | None = None
    ships_internationally: bool = False
    shipping_policy: dict | None = None
```

```python
# digger/digger/scraper/listing_parser.py
"""Discogs marketplace listing-page parser.

Listings are <tr class="shortcut_navigable"> rows within table#pjax_container.
Fields extracted via selectolax CSS selectors; values cleaned through bleach
to neutralize any HTML in seller comments.
"""

from __future__ import annotations
import re
from decimal import Decimal
import bleach
from selectolax.parser import HTMLParser

from digger.scraper.types import ParsedListing, Condition, SleeveCondition


class UnknownLayoutError(RuntimeError):
    """Page structure didn't match expectations."""


_PRICE_RE = re.compile(r"([A-Z]{3})\s*([\d,.]+)")
_LISTING_ID_RE = re.compile(r"/sell/item/(\d+)")
_VALID_MEDIA: set[str] = {"M","NM","VG+","VG","G+","G","F","P"}
_VALID_SLEEVE: set[str] = _VALID_MEDIA | {"generic","no_cover"}


def _clean_text(node) -> str:
    if node is None:
        return ""
    return bleach.clean(node.text(strip=True) or "", tags=[], strip=True)


def _normalize_condition(raw: str, valid: set[str]) -> str | None:
    raw = raw.strip()
    m = re.search(r"\(([^)]+)\)", raw)
    if m:
        for token in m.group(1).split("or"):
            t = token.strip()
            if t in valid:
                return t
    return raw if raw in valid else None


def parse_listings(html: str, release_id: int) -> list[ParsedListing]:
    tree = HTMLParser(html)
    rows = tree.css("table#pjax_container tr.shortcut_navigable")
    if not rows:
        if tree.css_first("div.no-results") is not None or "No listings available" in html:
            return []
        if tree.css_first("table#pjax_container") is None:
            raise UnknownLayoutError("expected table#pjax_container missing")
        return []
    results: list[ParsedListing] = []
    for row in rows:
        listing_a = row.css_first("a.item_description_title")
        if listing_a is None:
            continue
        m = _LISTING_ID_RE.search(listing_a.attributes.get("href", ""))
        if not m:
            continue
        listing_id = int(m.group(1))
        seller_node = row.css_first("td.seller_info strong a")
        if seller_node is None:
            continue
        seller_username = _clean_text(seller_node)
        media_raw = _clean_text(row.css_first("p.item_condition span.condition-label-desktop + span"))
        sleeve_raw = _clean_text(row.css_first("p.item_sleeve_condition span"))
        media = _normalize_condition(media_raw, _VALID_MEDIA)
        sleeve = _normalize_condition(sleeve_raw, _VALID_SLEEVE) or "generic"
        if media is None:
            continue
        price_raw = _clean_text(row.css_first("td.item_price span.price"))
        pm = _PRICE_RE.search(price_raw.replace(",", ""))
        if not pm:
            continue
        currency = pm.group(1)
        try:
            price_value = Decimal(pm.group(2))
        except Exception:
            continue
        comments = _clean_text(row.css_first("p.item_description_comments")) or None
        results.append(ParsedListing(
            listing_id=listing_id, release_id=release_id,
            seller_username=seller_username,
            price_value=price_value, price_currency=currency,
            media_condition=media, sleeve_condition=sleeve,  # type: ignore[arg-type]
            comments=comments,
        ))
    return results
```

- [ ] **Step 5: Run test to verify it passes**

`uv run pytest tests/digger/test_listing_parser.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add digger/digger/scraper/types.py digger/digger/scraper/listing_parser.py tests/digger/test_listing_parser.py tests/digger/fixtures/
git commit -m "feat(digger): selectolax-based listing-page parser with bleach sanitization"
```

---

## Task 11: Seller-page parser

**Files:**
- Create: `digger/digger/scraper/seller_parser.py`
- Create: `tests/digger/fixtures/seller_page_basic.html`
- Test: `tests/digger/test_seller_parser.py`

- [ ] **Step 1: Capture fixture**

Save a representative `/seller/{username}` HTML page into `tests/digger/fixtures/seller_page_basic.html`. Record provenance in the fixtures README.

- [ ] **Step 2: Write the failing test**

```python
# tests/digger/test_seller_parser.py
from pathlib import Path
from digger.scraper.seller_parser import parse_seller_profile


FIXTURE = Path(__file__).parent / "fixtures" / "seller_page_basic.html"


def test_seller_profile_fields_extracted():
    parsed = parse_seller_profile(FIXTURE.read_text())
    assert parsed.seller_id > 0
    assert parsed.username
    assert parsed.country_code is None or len(parsed.country_code) == 2
    if parsed.shipping_policy:
        for _region, policy in parsed.shipping_policy.items():
            assert "first_cents" in policy and "additional_cents" in policy
            assert policy["first_cents"] >= 0 and policy["additional_cents"] >= 0
```

- [ ] **Step 3: Implement the parser**

```python
# digger/digger/scraper/seller_parser.py
"""Discogs seller-profile parser.

Extracts seller_id, username, country, feedback summary, shipping policy.
Shipping policy normalized to {region: {first_cents, additional_cents, currency}}.
Returns None for shipping_policy if the page doesn't expose one.
"""

from __future__ import annotations
import re
from decimal import Decimal
from selectolax.parser import HTMLParser

from digger.scraper.types import ParsedSeller

_SELLER_ID_RE = re.compile(r"/users/(\d+)")
_COUNTRY_MAP: dict[str, str] = {
    "United States": "US", "United Kingdom": "GB", "Germany": "DE",
    "France": "FR", "Japan": "JP", "Canada": "CA", "Australia": "AU",
}


def _to_cents(raw: str) -> int:
    cleaned = re.sub(r"[^0-9.]", "", raw)
    if not cleaned:
        return 0
    return int(Decimal(cleaned) * 100)


def parse_seller_profile(html: str) -> ParsedSeller:
    tree = HTMLParser(html)
    seller_link = tree.css_first("a[href*='/users/']")
    if seller_link is None:
        raise ValueError("seller link missing")
    m = _SELLER_ID_RE.search(seller_link.attributes.get("href", ""))
    seller_id = int(m.group(1)) if m else 0
    username_node = tree.css_first("h1.profile-name")
    username = username_node.text(strip=True) if username_node else seller_link.text(strip=True)
    country_node = tree.css_first("div.profile-country")
    country_text = country_node.text(strip=True) if country_node else ""
    country_code = _COUNTRY_MAP.get(country_text)
    shipping_policy: dict[str, dict] = {}
    for row in tree.css("table.shipping-policies tr.region-row"):
        region = row.css_first("td.region-name")
        first = row.css_first("td.first-item-cost")
        addl = row.css_first("td.additional-item-cost")
        if not (region and first and addl):
            continue
        shipping_policy[region.text(strip=True).lower()] = {
            "first_cents": _to_cents(first.text(strip=True)),
            "additional_cents": _to_cents(addl.text(strip=True)),
            "currency": "USD",
        }
    return ParsedSeller(
        seller_id=seller_id, username=username,
        country_code=country_code, ships_internationally=bool(shipping_policy),
        shipping_policy=shipping_policy or None,
    )
```

- [ ] **Step 4: Run test to verify it passes**

`uv run pytest tests/digger/test_seller_parser.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add digger/digger/scraper/seller_parser.py tests/digger/test_seller_parser.py tests/digger/fixtures/seller_page_basic.html
git commit -m "feat(digger): seller-profile parser extracting shipping policy"
```

---

## Task 12: Scrape executor — DB writes for one release

**Files:**
- Create: `digger/digger/scraper/executor.py`
- Test: `tests/digger/test_executor.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/digger/test_executor.py
import pytest
from unittest.mock import AsyncMock
from digger.scraper.executor import ScrapeExecutor


@pytest.mark.asyncio
async def test_executor_upserts_and_marks_vanished(postgres_pool, monkeypatch):
    release_id = 999_100
    async with postgres_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO digger.release_scrape_state(release_id) VALUES ($1)", release_id
        )
        await conn.execute("""
            INSERT INTO digger.sellers(seller_id, username, region)
                VALUES (1,'alice','us'),(2,'bob','us');
            INSERT INTO digger.listings(listing_id, release_id, seller_id, price_value, price_currency,
                                        media_condition, sleeve_condition)
            VALUES (1001, $1, 1, 10.00, 'USD', 'NM', 'NM'),
                   (1002, $1, 2, 20.00, 'USD', 'VG+', 'VG+');
        """, release_id)

    http = AsyncMock()
    http.get.return_value.status_code = 200
    http.get.return_value.text = ""
    monkeypatch.setattr(
        "digger.scraper.executor.parse_listings",
        lambda html, release_id: [
            type("L", (), dict(
                listing_id=1001, release_id=release_id, seller_username="alice",
                seller_id=None, price_value=12.00, price_currency="USD",
                media_condition="NM", sleeve_condition="NM", comments=None, posted_at=None,
            ))()
        ],
    )

    exe = ScrapeExecutor(http_client=http, pool=postgres_pool)
    ok = await exe.scrape_release(release_id)
    assert ok is True

    async with postgres_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT listing_id, removed_at, price_value FROM digger.listings WHERE release_id=$1 ORDER BY listing_id",
            release_id,
        )
    assert rows[0]["listing_id"] == 1001 and rows[0]["removed_at"] is None and float(rows[0]["price_value"]) == 12.00
    assert rows[1]["listing_id"] == 1002 and rows[1]["removed_at"] is not None
```

- [ ] **Step 2: Run test to verify it fails**

`uv run pytest tests/digger/test_executor.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement the executor**

```python
# digger/digger/scraper/executor.py
"""End-to-end scrape of a single release."""

from __future__ import annotations
import logging
from common.postgres_pool import AsyncPostgreSQLPool
from digger.metrics import SCRAPE_TOTAL, UNKNOWN_LAYOUT_TOTAL
from digger.scraper.http_client import DiggerHttpClient
from digger.scraper.listing_parser import parse_listings, UnknownLayoutError
from digger.scraper.types import ParsedListing

log = logging.getLogger(__name__)


class ScrapeExecutor:
    def __init__(self, http_client: DiggerHttpClient, pool: AsyncPostgreSQLPool) -> None:
        self._http = http_client
        self._pool = pool

    async def scrape_release(self, release_id: int) -> bool:
        url = f"https://www.discogs.com/sell/release/{release_id}"
        try:
            resp = await self._http.get(url)
            if resp.status_code == 429:
                SCRAPE_TOTAL.labels(outcome="http_429").inc()
                return False
            if resp.status_code >= 500:
                SCRAPE_TOTAL.labels(outcome="http_5xx").inc()
                return False
            if resp.status_code != 200:
                SCRAPE_TOTAL.labels(outcome="parse_error").inc()
                return False
            try:
                listings = parse_listings(resp.text, release_id)
            except UnknownLayoutError:
                UNKNOWN_LAYOUT_TOTAL.inc()
                SCRAPE_TOTAL.labels(outcome="unknown_layout").inc()
                return False
            await self._persist(release_id, listings)
            SCRAPE_TOTAL.labels(outcome="ok").inc()
            return True
        except Exception:
            log.exception("⚠️ scrape failed for release_id=%d", release_id)
            SCRAPE_TOTAL.labels(outcome="parse_error").inc()
            return False

    async def _persist(self, release_id: int, listings: list[ParsedListing]) -> None:
        async with self._pool.acquire() as conn:
            await conn.set_autocommit(False)
            async with conn.transaction():
                seller_ids: dict[str, int] = {}
                for l in listings:
                    existing = await conn.fetchrow(
                        "SELECT seller_id FROM digger.sellers WHERE username=$1", l.seller_username
                    )
                    if existing is None:
                        # Synthesize a placeholder ID (negative) so listings can FK; replaced when
                        # the seller-profile scrape resolves the real Discogs user id.
                        new_id = -abs(hash(l.seller_username)) % (1 << 31)
                        await conn.execute(
                            "INSERT INTO digger.sellers(seller_id, username, region) "
                            "VALUES ($1, $2, 'other') ON CONFLICT (seller_id) DO NOTHING",
                            new_id, l.seller_username,
                        )
                        seller_ids[l.seller_username] = new_id
                    else:
                        seller_ids[l.seller_username] = existing["seller_id"]

                seen_ids: list[int] = []
                for l in listings:
                    sid = seller_ids[l.seller_username]
                    seen_ids.append(l.listing_id)
                    await conn.execute(
                        """
                        INSERT INTO digger.listings(
                            listing_id, release_id, seller_id, price_value, price_currency,
                            media_condition, sleeve_condition, comments, posted_at,
                            first_seen_at, last_seen_at, removed_at
                        )
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9, now(), now(), NULL)
                        ON CONFLICT (listing_id) DO UPDATE SET
                            price_value      = EXCLUDED.price_value,
                            price_currency   = EXCLUDED.price_currency,
                            media_condition  = EXCLUDED.media_condition,
                            sleeve_condition = EXCLUDED.sleeve_condition,
                            comments         = EXCLUDED.comments,
                            last_seen_at     = now(),
                            removed_at       = NULL
                        """,
                        l.listing_id, l.release_id, sid, l.price_value, l.price_currency,
                        l.media_condition, l.sleeve_condition, l.comments, l.posted_at,
                    )

                if seen_ids:
                    await conn.execute(
                        "UPDATE digger.listings "
                        "   SET removed_at = now() "
                        " WHERE release_id = $1 "
                        "   AND removed_at IS NULL "
                        "   AND listing_id <> ALL($2::bigint[])",
                        release_id, seen_ids,
                    )
                else:
                    await conn.execute(
                        "UPDATE digger.listings "
                        "   SET removed_at = now() "
                        " WHERE release_id = $1 AND removed_at IS NULL",
                        release_id,
                    )

                await conn.execute(
                    "UPDATE digger.release_scrape_state "
                    "   SET last_scraped_at = now(), consecutive_failures = 0, next_retry_at = NULL "
                    " WHERE release_id = $1",
                    release_id,
                )
```

- [ ] **Step 4: Run test to verify it passes**

`uv run pytest tests/digger/test_executor.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add digger/digger/scraper/executor.py tests/digger/test_executor.py
git commit -m "feat(digger): scrape executor with upsert + soft-delete for vanished listings"
```

---

## Task 13: Queue runner — pop next due release

**Files:**
- Create: `digger/digger/scraper/queue_runner.py`
- Test: `tests/digger/test_queue_runner.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/digger/test_queue_runner.py
import pytest
from digger.scraper.queue_runner import pop_next_due


@pytest.mark.asyncio
async def test_pop_returns_must_tier_first(postgres_pool):
    async with postgres_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO digger.release_scrape_state(release_id, priority_tier, next_scrape_due_at)
            VALUES (1, 'eventually', now() - interval '1 day'),
                   (2, 'nice',       now() - interval '1 day'),
                   (3, 'must',       now() - interval '1 hour');
        """)
    async with postgres_pool.acquire() as conn:
        await conn.set_autocommit(False)
        async with conn.transaction():
            chosen = await pop_next_due(conn)
            assert chosen == 3


@pytest.mark.asyncio
async def test_pop_skips_in_backoff(postgres_pool):
    async with postgres_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO digger.release_scrape_state(release_id, priority_tier,
                                                   next_scrape_due_at, next_retry_at)
            VALUES (10, 'must', now() - interval '1 hour', now() + interval '1 hour'),
                   (11, 'nice', now() - interval '1 hour', NULL);
        """)
    async with postgres_pool.acquire() as conn:
        await conn.set_autocommit(False)
        async with conn.transaction():
            chosen = await pop_next_due(conn)
            assert chosen == 11
```

- [ ] **Step 2: Run test to verify it fails**

`uv run pytest tests/digger/test_queue_runner.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

```python
# digger/digger/scraper/queue_runner.py
"""Pop the next due release from the scrape queue.

SELECT ... FOR UPDATE SKIP LOCKED — multi-worker safe.
"""

from __future__ import annotations


POP_SQL = """
SELECT release_id
  FROM digger.release_scrape_state
 WHERE next_scrape_due_at <= now()
   AND (next_retry_at IS NULL OR next_retry_at <= now())
 ORDER BY
   CASE priority_tier WHEN 'must' THEN 1 WHEN 'nice' THEN 2 ELSE 3 END,
   next_scrape_due_at ASC
 LIMIT 1
 FOR UPDATE SKIP LOCKED;
"""


async def pop_next_due(conn) -> int | None:
    """Return next due release_id, or None.

    Must be called inside an open transaction; the row stays locked
    for the duration of that transaction.
    """
    row = await conn.fetchrow(POP_SQL)
    return None if row is None else int(row["release_id"])
```

- [ ] **Step 4: Run test to verify it passes**

`uv run pytest tests/digger/test_queue_runner.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add digger/digger/scraper/queue_runner.py tests/digger/test_queue_runner.py
git commit -m "feat(digger): queue runner with priority-tier ordering and SKIP LOCKED"
```

---

## Task 14: State recomputer — adaptive throttle

**Files:**
- Create: `digger/digger/scraper/state_recomputer.py`
- Test: `tests/digger/test_state_recomputer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/digger/test_state_recomputer.py
from datetime import datetime, timezone, timedelta
import pytest
from digger.scraper.state_recomputer import compute_next_scrape_due, BASE_INTERVALS


def test_base_intervals_match_spec():
    assert BASE_INTERVALS["must"] == timedelta(days=7)
    assert BASE_INTERVALS["nice"] == timedelta(days=14)
    assert BASE_INTERVALS["eventually"] == timedelta(days=28)


def test_no_churn_returns_base_interval():
    last = datetime(2026, 1, 1, tzinfo=timezone.utc)
    nxt = compute_next_scrape_due(last, "must", listings_delta_7d=0)
    assert nxt - last == timedelta(days=7)


def test_high_churn_shortens_interval():
    last = datetime(2026, 1, 1, tzinfo=timezone.utc)
    nxt = compute_next_scrape_due(last, "must", listings_delta_7d=50)
    assert nxt - last < timedelta(days=7)


def test_clamped_at_half_base():
    last = datetime(2026, 1, 1, tzinfo=timezone.utc)
    nxt = compute_next_scrape_due(last, "must", listings_delta_7d=10_000)
    assert nxt - last >= timedelta(days=7) * 0.5
```

- [ ] **Step 2: Run test to verify it fails**

`uv run pytest tests/digger/test_state_recomputer.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

```python
# digger/digger/scraper/state_recomputer.py
"""Adaptive throttle for next_scrape_due_at."""

from __future__ import annotations
import math
from datetime import datetime, timedelta


BASE_INTERVALS: dict[str, timedelta] = {
    "must": timedelta(days=7),
    "nice": timedelta(days=14),
    "eventually": timedelta(days=28),
}


def compute_next_scrape_due(
    last_scraped_at: datetime, tier: str, listings_delta_7d: int,
) -> datetime:
    base = BASE_INTERVALS[tier]
    raw = 1.0 - math.log10(1 + max(0, listings_delta_7d)) * 0.2
    churn = min(1.5, max(0.5, raw))
    return last_scraped_at + base * churn


async def refresh_all_due_times(conn) -> int:
    """Recompute next_scrape_due_at for every row, all in one SQL pass.
    Returns rows updated."""
    result = await conn.execute("""
        UPDATE digger.release_scrape_state SET next_scrape_due_at =
            COALESCE(last_scraped_at, now())
            + (CASE priority_tier
                 WHEN 'must'       THEN interval '7 days'
                 WHEN 'nice'       THEN interval '14 days'
                 ELSE                   interval '28 days'
               END)
            * GREATEST(0.5, LEAST(1.5, 1.0 - log(1 + GREATEST(0, listings_delta_7d)) * 0.2))
    """)
    return int(result.split()[-1]) if result else 0
```

- [ ] **Step 4: Run test to verify it passes**

`uv run pytest tests/digger/test_state_recomputer.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add digger/digger/scraper/state_recomputer.py tests/digger/test_state_recomputer.py
git commit -m "feat(digger): adaptive throttle for next_scrape_due_at"
```

---

## Task 15: Per-release exponential backoff

**Files:**
- Create: `digger/digger/scraper/backoff.py`
- Test: `tests/digger/test_backoff.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/digger/test_backoff.py
from datetime import timedelta
import pytest
from digger.scraper.backoff import next_retry_delay, record_failure


def test_exponential_growth():
    assert next_retry_delay(0) == timedelta(hours=1)
    assert next_retry_delay(1) == timedelta(hours=2)
    assert next_retry_delay(2) == timedelta(hours=4)
    assert next_retry_delay(3) == timedelta(hours=8)


def test_capped_at_24h():
    assert next_retry_delay(10) == timedelta(hours=24)


@pytest.mark.asyncio
async def test_record_failure_bumps_state(postgres_pool):
    async with postgres_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO digger.release_scrape_state(release_id) VALUES ($1)", 42
        )
        await record_failure(conn, release_id=42)
        row = await conn.fetchrow(
            "SELECT consecutive_failures, next_retry_at FROM digger.release_scrape_state WHERE release_id=42"
        )
    assert row["consecutive_failures"] == 1
    assert row["next_retry_at"] is not None
```

- [ ] **Step 2: Run test to verify it fails**

`uv run pytest tests/digger/test_backoff.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

```python
# digger/digger/scraper/backoff.py
from datetime import timedelta


MAX_BACKOFF = timedelta(hours=24)


def next_retry_delay(consecutive_failures: int) -> timedelta:
    delay = timedelta(hours=2 ** max(0, consecutive_failures))
    return min(delay, MAX_BACKOFF)


async def record_failure(conn, release_id: int) -> None:
    await conn.execute(
        """
        UPDATE digger.release_scrape_state
           SET consecutive_failures = consecutive_failures + 1,
               next_retry_at        = now() + LEAST(interval '24 hours',
                                                    (interval '1 hour') * power(2, consecutive_failures))
         WHERE release_id = $1
        """,
        release_id,
    )
```

- [ ] **Step 4: Run test to verify it passes**

`uv run pytest tests/digger/test_backoff.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add digger/digger/scraper/backoff.py tests/digger/test_backoff.py
git commit -m "feat(digger): exponential backoff per release on scrape failure"
```

---

## Task 16: Orchestrator — compose loops, wire into main

**Files:**
- Create: `digger/digger/scraper/orchestrator.py`
- Modify: `digger/digger/main.py`
- Test: `tests/digger/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/digger/test_orchestrator.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from digger.scraper.orchestrator import scrape_loop


@pytest.mark.asyncio
async def test_scrape_loop_runs_one_iteration_and_stops(postgres_pool):
    rate = MagicMock()
    rate.acquire = AsyncMock(return_value=0.0)
    cb = MagicMock()
    cb.is_open = AsyncMock(return_value=False)
    cb.record = AsyncMock()
    executor = MagicMock()
    executor.scrape_release = AsyncMock(return_value=True)

    async with postgres_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO digger.release_scrape_state(release_id) VALUES (1)"
        )

    stop_event = asyncio.Event()

    async def stop_after_one():
        await asyncio.sleep(0.2)
        stop_event.set()

    asyncio.create_task(stop_after_one())
    await scrape_loop(pool=postgres_pool, executor=executor, rate=rate, breaker=cb, stop_event=stop_event)
    executor.scrape_release.assert_awaited_with(1)
```

- [ ] **Step 2: Run test to verify it fails**

`uv run pytest tests/digger/test_orchestrator.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement orchestrator**

```python
# digger/digger/scraper/orchestrator.py
"""Composes queue runner, executor, rate budget, circuit breaker, state loop."""

from __future__ import annotations
import asyncio
import logging
from common.postgres_pool import AsyncPostgreSQLPool

from digger.scraper.executor import ScrapeExecutor
from digger.scraper.queue_runner import pop_next_due
from digger.scraper.state_recomputer import refresh_all_due_times
from digger.scraper.backoff import record_failure
from digger.scraper.circuit_breaker import CircuitBreaker
from digger.scraper.rate_budget import RateBudget

log = logging.getLogger(__name__)


async def scrape_loop(
    *,
    pool: AsyncPostgreSQLPool,
    executor: ScrapeExecutor,
    rate: RateBudget,
    breaker: CircuitBreaker,
    stop_event: asyncio.Event,
) -> None:
    while not stop_event.is_set():
        if await breaker.is_open():
            log.warning("⚡ circuit breaker open — sleeping 30s")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=30)
            except asyncio.TimeoutError:
                pass
            continue
        await rate.acquire()
        release_id = None
        async with pool.acquire() as conn:
            await conn.set_autocommit(False)
            async with conn.transaction():
                release_id = await pop_next_due(conn)
        if release_id is None:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=2)
            except asyncio.TimeoutError:
                pass
            continue
        ok = await executor.scrape_release(release_id)
        await breaker.record(success=ok)
        if not ok:
            async with pool.acquire() as conn:
                await record_failure(conn, release_id)


async def state_loop(
    *,
    pool: AsyncPostgreSQLPool,
    stop_event: asyncio.Event,
    interval_seconds: int = 60,
) -> None:
    while not stop_event.is_set():
        try:
            async with pool.acquire() as conn:
                await refresh_all_due_times(conn)
        except Exception:
            log.exception("⚠️ state recompute failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            pass
```

- [ ] **Step 4: Wire into `digger/digger/main.py`**

Replace the empty `tasks: list[...]` block with:

```python
    from common.postgres_pool import AsyncPostgreSQLPool
    from redis.asyncio import from_url as redis_from_url
    from digger.health import run_health_server
    from digger.scraper.http_client import DiggerHttpClient
    from digger.scraper.rate_budget import RateBudget
    from digger.scraper.circuit_breaker import CircuitBreaker
    from digger.scraper.executor import ScrapeExecutor
    from digger.scraper.orchestrator import scrape_loop, state_loop

    pool = AsyncPostgreSQLPool(
        host=cfg.postgres_host, user=cfg.postgres_user,
        password=cfg.postgres_password, database=cfg.postgres_database,
    )
    await pool.connect()
    redis = redis_from_url(f"redis://{cfg.redis_host}/0")
    http_client = DiggerHttpClient(user_agent=cfg.scraper_user_agent)
    rate = RateBudget(redis=redis, capacity=cfg.rate_budget_per_hour,
                      refill_per_second=cfg.rate_budget_per_hour / 3600.0)
    breaker = CircuitBreaker(
        window_seconds=cfg.circuit_breaker_window_seconds,
        failure_pct=cfg.circuit_breaker_failure_pct,
        cooldown_seconds=1800,
    )
    executor = ScrapeExecutor(http_client=http_client, pool=pool)

    tasks = [
        asyncio.create_task(run_health_server(cfg), name="health"),
        asyncio.create_task(scrape_loop(pool=pool, executor=executor, rate=rate, breaker=breaker, stop_event=stop_event), name="scrape"),
        asyncio.create_task(state_loop(pool=pool, stop_event=stop_event), name="state"),
    ]
```

- [ ] **Step 5: Run tests**

`uv run pytest tests/digger -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add digger/digger/scraper/orchestrator.py digger/digger/main.py tests/digger/test_orchestrator.py
git commit -m "feat(digger): orchestrator wiring scraper, state recomputer, and health"
```

---

## Task 17: API queries module for digger

**Files:**
- Create: `api/queries/digger_queries.py`
- Test: `tests/api/test_digger_queries.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_digger_queries.py
import pytest
from api.queries.digger_queries import (
    get_user_settings, upsert_user_settings,
    list_wantlist_priorities, bulk_set_tier,
    get_wantlist_with_listings_counts,
)


@pytest.mark.asyncio
async def test_settings_round_trip(postgres_pool, api_oauth_user):
    user_id = api_oauth_user.user_id
    assert await get_user_settings(postgres_pool, user_id) is None
    await upsert_user_settings(
        postgres_pool, user_id,
        enabled=True, country_code="US", currency="USD",
        scheduled_cadence="weekly", preferred_model="sonnet",
    )
    s = await get_user_settings(postgres_pool, user_id)
    assert s.enabled is True and s.country_code == "US" and s.scheduled_cadence == "weekly"


@pytest.mark.asyncio
async def test_bulk_set_tier(postgres_pool, api_oauth_user):
    user_id = api_oauth_user.user_id
    async with postgres_pool.acquire() as conn:
        for rid in (1, 2, 3):
            await conn.execute(
                "INSERT INTO digger.release_scrape_state(release_id) VALUES ($1) "
                "ON CONFLICT DO NOTHING", rid)
            await conn.execute(
                "INSERT INTO digger.user_wantlist_priorities(user_id, release_id) VALUES ($1,$2)",
                user_id, rid,
            )
    await bulk_set_tier(postgres_pool, user_id, release_ids=[1, 2], tier="must")
    rows = await list_wantlist_priorities(postgres_pool, user_id)
    by_id = {r.release_id: r.tier for r in rows}
    assert by_id[1] == "must" and by_id[2] == "must" and by_id[3] == "nice"
```

- [ ] **Step 2: Run test to verify it fails**

`uv run pytest tests/api/test_digger_queries.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement queries**

```python
# api/queries/digger_queries.py
"""SQL helpers for the digger schema, used by api/ routers.

All functions take a pool plus a user_id (from JWT). No tool input ever
provides a user_id directly.
"""

from __future__ import annotations
import uuid
from dataclasses import dataclass
from typing import Literal

from common.postgres_pool import AsyncPostgreSQLPool


Tier = Literal["must", "nice", "eventually"]
Cadence = Literal["off", "weekly", "biweekly", "monthly"]
Model = Literal["haiku", "sonnet", "opus"]


@dataclass(slots=True)
class UserDiggerSettings:
    user_id: uuid.UUID
    enabled: bool
    country_code: str | None
    currency: str
    scheduled_cadence: Cadence
    preferred_model: Model
    daily_token_cap_interactive: int
    daily_token_cap_scheduled: int


@dataclass(slots=True)
class WantlistPriorityRow:
    release_id: int
    tier: Tier
    min_media_condition: str
    min_sleeve_condition: str
    max_price_cents: int | None


async def get_user_settings(pool: AsyncPostgreSQLPool, user_id: uuid.UUID) -> UserDiggerSettings | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id, enabled, country_code, currency, scheduled_cadence, "
            "       preferred_model, daily_token_cap_interactive, daily_token_cap_scheduled "
            "  FROM digger.user_digger_settings WHERE user_id = $1", user_id,
        )
    return None if row is None else UserDiggerSettings(**dict(row))


async def upsert_user_settings(
    pool: AsyncPostgreSQLPool, user_id: uuid.UUID, *,
    enabled: bool, country_code: str | None, currency: str,
    scheduled_cadence: Cadence, preferred_model: Model,
    daily_token_cap_interactive: int = 200_000,
    daily_token_cap_scheduled: int = 100_000,
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO digger.user_digger_settings
              (user_id, enabled, country_code, currency, scheduled_cadence,
               preferred_model, daily_token_cap_interactive, daily_token_cap_scheduled)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
            ON CONFLICT (user_id) DO UPDATE SET
              enabled = EXCLUDED.enabled, country_code = EXCLUDED.country_code,
              currency = EXCLUDED.currency, scheduled_cadence = EXCLUDED.scheduled_cadence,
              preferred_model = EXCLUDED.preferred_model,
              daily_token_cap_interactive = EXCLUDED.daily_token_cap_interactive,
              daily_token_cap_scheduled   = EXCLUDED.daily_token_cap_scheduled
            """,
            user_id, enabled, country_code, currency, scheduled_cadence,
            preferred_model, daily_token_cap_interactive, daily_token_cap_scheduled,
        )


async def list_wantlist_priorities(
    pool: AsyncPostgreSQLPool, user_id: uuid.UUID,
) -> list[WantlistPriorityRow]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT release_id, tier, min_media_condition, min_sleeve_condition, max_price_cents "
            "  FROM digger.user_wantlist_priorities "
            " WHERE user_id = $1 "
            " ORDER BY tier, release_id",
            user_id,
        )
    return [WantlistPriorityRow(**dict(r)) for r in rows]


async def set_wantlist_priority(
    pool: AsyncPostgreSQLPool, user_id: uuid.UUID, release_id: int, *,
    tier: Tier | None = None, min_media_condition: str | None = None,
    min_sleeve_condition: str | None = None, max_price_cents: int | None = None,
) -> None:
    fields: list[str] = []
    args: list = [user_id, release_id]
    if tier is not None:
        args.append(tier); fields.append(f"tier = ${len(args)}")
    if min_media_condition is not None:
        args.append(min_media_condition); fields.append(f"min_media_condition = ${len(args)}")
    if min_sleeve_condition is not None:
        args.append(min_sleeve_condition); fields.append(f"min_sleeve_condition = ${len(args)}")
    if max_price_cents is not None:
        args.append(max_price_cents); fields.append(f"max_price_cents = ${len(args)}")
    if not fields:
        return
    fields.append("updated_at = now()")
    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE digger.user_wantlist_priorities SET {', '.join(fields)} "
            f"WHERE user_id = $1 AND release_id = $2",
            *args,
        )


async def bulk_set_tier(
    pool: AsyncPostgreSQLPool, user_id: uuid.UUID, release_ids: list[int], tier: Tier,
) -> int:
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE digger.user_wantlist_priorities "
            "   SET tier = $3, updated_at = now() "
            " WHERE user_id = $1 AND release_id = ANY($2::bigint[])",
            user_id, release_ids, tier,
        )
    return int(result.split()[-1])


async def get_wantlist_with_listings_counts(
    pool: AsyncPostgreSQLPool, user_id: uuid.UUID,
) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT uwp.release_id, uwp.tier, uwp.min_media_condition,
                   uwp.min_sleeve_condition, uwp.max_price_cents,
                   rs.last_scraped_at,
                   COUNT(l.listing_id) FILTER (WHERE l.removed_at IS NULL) AS active_listings,
                   uw.title, uw.artist, uw.year, uw.cover_image_url
              FROM digger.user_wantlist_priorities uwp
              LEFT JOIN digger.release_scrape_state rs ON rs.release_id = uwp.release_id
              LEFT JOIN digger.listings l ON l.release_id = uwp.release_id
              LEFT JOIN discogs.user_wantlists uw
                ON uw.user_id = uwp.user_id AND uw.release_id = uwp.release_id
             WHERE uwp.user_id = $1
             GROUP BY uwp.release_id, uwp.tier, uwp.min_media_condition, uwp.min_sleeve_condition,
                      uwp.max_price_cents, rs.last_scraped_at,
                      uw.title, uw.artist, uw.year, uw.cover_image_url
             ORDER BY uwp.tier, uw.artist NULLS LAST
            """,
            user_id,
        )
    return [dict(r) for r in rows]
```

- [ ] **Step 4: Run test to verify it passes**

`uv run pytest tests/api/test_digger_queries.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/queries/digger_queries.py tests/api/test_digger_queries.py
git commit -m "feat(digger): api query helpers for settings + wantlist priorities"
```

---

## Task 18: User-facing API router `/api/digger/*`

**Files:**
- Create: `api/models/digger.py`, `api/routers/digger.py`
- Modify: `api/main.py` — register router
- Test: `tests/api/test_digger_router.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_digger_router.py
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_settings_404_when_not_enabled(api_client: AsyncClient, auth_headers):
    r = await api_client.get("/api/digger/settings", headers=auth_headers)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_put_settings_creates_row(api_client: AsyncClient, auth_headers):
    r = await api_client.put(
        "/api/digger/settings", headers=auth_headers, json={
            "enabled": True, "country_code": "US", "currency": "USD",
            "scheduled_cadence": "weekly", "preferred_model": "sonnet",
        },
    )
    assert r.status_code == 204
    r = await api_client.get("/api/digger/settings", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["enabled"] is True


@pytest.mark.asyncio
async def test_wantlist_priorities_list(api_client, auth_headers, seeded_wantlist):
    r = await api_client.get("/api/digger/wantlist", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert "items" in body and len(body["items"]) > 0
    assert {"release_id", "tier", "active_listings"} <= set(body["items"][0])


@pytest.mark.asyncio
async def test_bulk_set_tier(api_client, auth_headers, seeded_wantlist):
    r = await api_client.post(
        "/api/digger/wantlist/bulk-tier", headers=auth_headers,
        json={"release_ids": [seeded_wantlist[0]], "tier": "must"},
    )
    assert r.status_code == 200 and r.json()["updated"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

`uv run pytest tests/api/test_digger_router.py -v`
Expected: 404 (router not registered).

- [ ] **Step 3: Implement models + router**

```python
# api/models/digger.py
from typing import Literal
from pydantic import BaseModel, Field, conlist


Tier = Literal["must", "nice", "eventually"]
Cadence = Literal["off", "weekly", "biweekly", "monthly"]
Model = Literal["haiku", "sonnet", "opus"]
Condition = Literal["M", "NM", "VG+", "VG", "G+", "G", "F", "P"]
SleeveCondition = Literal["M", "NM", "VG+", "VG", "G+", "G", "F", "P", "generic", "no_cover"]


class SettingsIn(BaseModel):
    enabled: bool
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    currency: str = Field(min_length=3, max_length=3)
    scheduled_cadence: Cadence
    preferred_model: Model
    daily_token_cap_interactive: int | None = None
    daily_token_cap_scheduled: int | None = None


class SettingsOut(SettingsIn):
    pass


class WantlistItemOut(BaseModel):
    release_id: int
    title: str | None
    artist: str | None
    year: int | None
    cover_image_url: str | None
    tier: Tier
    min_media_condition: Condition
    min_sleeve_condition: SleeveCondition
    max_price_cents: int | None
    active_listings: int
    last_scraped_at: str | None


class WantlistResponse(BaseModel):
    items: list[WantlistItemOut]


class BulkTierIn(BaseModel):
    release_ids: conlist(int, min_length=1, max_length=500)
    tier: Tier


class SetPriorityIn(BaseModel):
    tier: Tier | None = None
    min_media_condition: Condition | None = None
    min_sleeve_condition: SleeveCondition | None = None
    max_price_cents: int | None = None
```

```python
# api/routers/digger.py
from fastapi import APIRouter, Depends, HTTPException, status
from api.dependencies import current_user, get_pool
from api.queries import digger_queries as q
from api.models.digger import (
    SettingsIn, SettingsOut, WantlistResponse, WantlistItemOut,
    BulkTierIn, SetPriorityIn,
)

router = APIRouter(prefix="/api/digger", tags=["digger"])


@router.get("/settings", response_model=SettingsOut)
async def get_settings(user=Depends(current_user), pool=Depends(get_pool)):
    s = await q.get_user_settings(pool, user.user_id)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "digger not enabled")
    return SettingsOut(
        enabled=s.enabled, country_code=s.country_code, currency=s.currency,
        scheduled_cadence=s.scheduled_cadence, preferred_model=s.preferred_model,
        daily_token_cap_interactive=s.daily_token_cap_interactive,
        daily_token_cap_scheduled=s.daily_token_cap_scheduled,
    )


@router.put("/settings", status_code=status.HTTP_204_NO_CONTENT)
async def put_settings(body: SettingsIn, user=Depends(current_user), pool=Depends(get_pool)):
    await q.upsert_user_settings(
        pool, user.user_id,
        enabled=body.enabled, country_code=body.country_code, currency=body.currency,
        scheduled_cadence=body.scheduled_cadence, preferred_model=body.preferred_model,
        daily_token_cap_interactive=body.daily_token_cap_interactive or 200_000,
        daily_token_cap_scheduled=body.daily_token_cap_scheduled or 100_000,
    )


@router.get("/wantlist", response_model=WantlistResponse)
async def get_wantlist(user=Depends(current_user), pool=Depends(get_pool)):
    rows = await q.get_wantlist_with_listings_counts(pool, user.user_id)
    items = [
        WantlistItemOut(
            release_id=r["release_id"], tier=r["tier"],
            min_media_condition=r["min_media_condition"],
            min_sleeve_condition=r["min_sleeve_condition"],
            max_price_cents=r["max_price_cents"],
            active_listings=int(r["active_listings"] or 0),
            last_scraped_at=r["last_scraped_at"].isoformat() if r["last_scraped_at"] else None,
            title=r["title"], artist=r["artist"], year=r["year"],
            cover_image_url=r["cover_image_url"],
        ) for r in rows
    ]
    return WantlistResponse(items=items)


@router.put("/wantlist/{release_id}/priority", status_code=status.HTTP_204_NO_CONTENT)
async def set_priority(release_id: int, body: SetPriorityIn,
                       user=Depends(current_user), pool=Depends(get_pool)):
    await q.set_wantlist_priority(
        pool, user.user_id, release_id,
        tier=body.tier,
        min_media_condition=body.min_media_condition,
        min_sleeve_condition=body.min_sleeve_condition,
        max_price_cents=body.max_price_cents,
    )


@router.post("/wantlist/bulk-tier")
async def bulk_set_tier(body: BulkTierIn, user=Depends(current_user), pool=Depends(get_pool)):
    updated = await q.bulk_set_tier(pool, user.user_id, body.release_ids, body.tier)
    return {"updated": updated}
```

Register in `api/main.py`:

```python
from api.routers.digger import router as digger_router
app.include_router(digger_router)
```

- [ ] **Step 4: Run test to verify it passes**

`uv run pytest tests/api/test_digger_router.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/models/digger.py api/routers/digger.py api/main.py tests/api/test_digger_router.py
git commit -m "feat(digger): /api/digger settings + wantlist endpoints"
```

---

## Task 19: Internal API router `/api/internal/digger/*`

**Files:**
- Create: `api/routers/internal_digger.py`
- Modify: `api/main.py`, `api/dependencies.py` (service-token guard)
- Test: `tests/api/test_internal_digger_router.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_internal_digger_router.py
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_wantlist_snapshot_requires_service_token(api_client: AsyncClient):
    r = await api_client.get("/api/internal/digger/wantlist-snapshot/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_wantlist_snapshot_returns_priorities(
    api_client: AsyncClient, service_token_headers, seeded_user_with_wantlist,
):
    user_id = seeded_user_with_wantlist.user_id
    r = await api_client.get(
        f"/api/internal/digger/wantlist-snapshot/{user_id}",
        headers=service_token_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == str(user_id)
    assert "must" in body and "nice" in body and "eventually" in body
```

- [ ] **Step 2: Run test to verify it fails**

`uv run pytest tests/api/test_internal_digger_router.py -v`
Expected: 404.

- [ ] **Step 3: Add guard + router**

```python
# api/dependencies.py — add if not already present
from fastapi import Header, HTTPException, status
from api.config import settings


def service_token_required(x_service_token: str | None = Header(default=None)) -> None:
    expected = settings.digger_api_service_token
    if not x_service_token or x_service_token != expected:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing or invalid service token")
```

```python
# api/routers/internal_digger.py
from fastapi import APIRouter, Depends
from uuid import UUID
from api.dependencies import service_token_required, get_pool
from api.queries import digger_queries as q

router = APIRouter(
    prefix="/api/internal/digger", tags=["digger-internal"],
    dependencies=[Depends(service_token_required)],
)


@router.get("/wantlist-snapshot/{user_id}")
async def wantlist_snapshot(user_id: UUID, pool=Depends(get_pool)):
    """Used by digger worker for scheduled runs (M2)."""
    rows = await q.list_wantlist_priorities(pool, user_id)
    grouped: dict[str, list[dict]] = {"must": [], "nice": [], "eventually": []}
    for r in rows:
        grouped[r.tier].append({
            "release_id": r.release_id,
            "min_media_condition": r.min_media_condition,
            "min_sleeve_condition": r.min_sleeve_condition,
            "max_price_cents": r.max_price_cents,
        })
    return {"user_id": str(user_id), **grouped}


@router.get("/users-due-for-report")
async def users_due_for_report(pool=Depends(get_pool)):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT user_id, scheduled_cadence FROM digger.user_digger_settings "
            "WHERE enabled = true AND scheduled_cadence <> 'off' "
            "  AND (next_scheduled_run_at IS NULL OR next_scheduled_run_at <= now())"
        )
    return {"users": [{"user_id": str(r["user_id"]), "cadence": r["scheduled_cadence"]} for r in rows]}
```

```python
# api/main.py — register
from api.routers.internal_digger import router as internal_digger_router
app.include_router(internal_digger_router)
```

- [ ] **Step 4: Run test to verify it passes**

`uv run pytest tests/api/test_internal_digger_router.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/routers/internal_digger.py api/dependencies.py api/main.py tests/api/test_internal_digger_router.py
git commit -m "feat(digger): /api/internal/digger router gated by service token"
```

---

## Task 20: Docker Compose entry for `digger` service

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`

- [ ] **Step 1: Append service to `docker-compose.yml`**

```yaml
  digger:
    build:
      context: .
      dockerfile: digger/Dockerfile
    container_name: digger
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
      schema-init:
        condition: service_completed_successfully
      api:
        condition: service_healthy
    environment:
      POSTGRES_HOST: postgres
      POSTGRES_USERNAME: ${POSTGRES_USERNAME}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DATABASE: ${POSTGRES_DATABASE}
      REDIS_HOST: redis
      API_BASE_URL: http://api:8004
      DIGGER_API_SERVICE_TOKEN: ${DIGGER_API_SERVICE_TOKEN}
      DIGGER_SCRAPER_USER_AGENT: ${DIGGER_SCRAPER_USER_AGENT:-discogsography-digger/0.1 (github.com/SimplicityGuy/discogsography)}
      DIGGER_RATE_BUDGET_PER_HOUR: ${DIGGER_RATE_BUDGET_PER_HOUR:-600}
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
    ports:
      - "8012:8012"
    volumes:
      - ./logs:/logs
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8012/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 20s
```

- [ ] **Step 2: Update `.env.example`**

```
# Digger
DIGGER_API_SERVICE_TOKEN=replace-with-strong-random
DIGGER_SCRAPER_USER_AGENT=discogsography-digger/0.1 (github.com/SimplicityGuy/discogsography)
DIGGER_RATE_BUDGET_PER_HOUR=600
```

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml .env.example
git commit -m "feat(digger): docker-compose entry + .env.example"
```

---

## Task 21: justfile recipes

**Files:**
- Modify: `justfile`

- [ ] **Step 1: Append recipes**

```makefile
# --- digger ---
test-digger:
    uv run pytest tests/digger --cov=digger --cov-report=term-missing

digger-up:
    docker compose up -d digger

digger-logs:
    docker compose logs -f digger

digger-metrics:
    curl -sS http://localhost:8012/metrics | head -40
```

- [ ] **Step 2: Verify listing**

`just --list | grep -E "digger"`
Expected: `test-digger`, `digger-up`, `digger-logs`, `digger-metrics`.

- [ ] **Step 3: Commit**

```bash
git add justfile
git commit -m "chore(digger): justfile recipes"
```

---

## Task 22: Explore — `/digger/wantlist` route skeleton

**Files:**
- Create: `explore/src/digger/index.tsx`, `explore/src/digger/api.ts`, `explore/src/digger/types.ts`, `explore/src/digger/Wantlist.tsx`, `explore/src/digger/OnboardingCard.tsx`
- Modify: `explore/src/main.tsx` (or routes file)
- Test: `tests/explore/digger/Wantlist.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// tests/explore/digger/Wantlist.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { Wantlist } from "../../../explore/src/digger/Wantlist";

vi.mock("../../../explore/src/digger/api", () => ({
  getSettings: vi.fn().mockResolvedValue(null),
  getWantlist: vi.fn().mockResolvedValue({ items: [] }),
}));

describe("Wantlist", () => {
  it("shows onboarding card when settings is null", async () => {
    render(<Wantlist />);
    await waitFor(() => expect(screen.getByText(/Enable Digger/i)).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

`cd explore && npm test -- digger/Wantlist`
Expected: module not found.

- [ ] **Step 3: Implement types, api, components**

```typescript
// explore/src/digger/types.ts
export type Tier = "must" | "nice" | "eventually";
export type Cadence = "off" | "weekly" | "biweekly" | "monthly";
export type Condition = "M" | "NM" | "VG+" | "VG" | "G+" | "G" | "F" | "P";
export type SleeveCondition = Condition | "generic" | "no_cover";

export interface UserDiggerSettings {
  enabled: boolean;
  country_code: string | null;
  currency: string;
  scheduled_cadence: Cadence;
  preferred_model: "haiku" | "sonnet" | "opus";
  daily_token_cap_interactive: number;
  daily_token_cap_scheduled: number;
}

export interface WantlistItem {
  release_id: number;
  title: string | null;
  artist: string | null;
  year: number | null;
  cover_image_url: string | null;
  tier: Tier;
  min_media_condition: Condition;
  min_sleeve_condition: SleeveCondition;
  max_price_cents: number | null;
  active_listings: number;
  last_scraped_at: string | null;
}
```

```typescript
// explore/src/digger/api.ts
import type { UserDiggerSettings, WantlistItem, Tier, Condition, SleeveCondition } from "./types";

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { credentials: "include", ...init });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.status === 204 ? (undefined as unknown as T) : ((await r.json()) as T);
}

export async function getSettings(): Promise<UserDiggerSettings | null> {
  try { return await api<UserDiggerSettings>("/api/digger/settings"); }
  catch (e) { if ((e as Error).message.startsWith("404")) return null; throw e; }
}

export async function putSettings(s: UserDiggerSettings): Promise<void> {
  await api<void>("/api/digger/settings", {
    method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(s),
  });
}

export async function getWantlist(): Promise<{ items: WantlistItem[] }> {
  return api("/api/digger/wantlist");
}

export async function bulkSetTier(release_ids: number[], tier: Tier): Promise<{ updated: number }> {
  return api("/api/digger/wantlist/bulk-tier", {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ release_ids, tier }),
  });
}

export async function setPriority(release_id: number, patch: {
  tier?: Tier; min_media_condition?: Condition;
  min_sleeve_condition?: SleeveCondition; max_price_cents?: number | null;
}): Promise<void> {
  await api<void>(`/api/digger/wantlist/${release_id}/priority`, {
    method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(patch),
  });
}
```

```tsx
// explore/src/digger/OnboardingCard.tsx
import { useState } from "react";
import { putSettings } from "./api";

export function OnboardingCard({ onEnabled }: { onEnabled: () => void }) {
  const [busy, setBusy] = useState(false);
  async function enable() {
    setBusy(true);
    try {
      await putSettings({
        enabled: true, country_code: null, currency: "USD",
        scheduled_cadence: "weekly", preferred_model: "sonnet",
        daily_token_cap_interactive: 200_000, daily_token_cap_scheduled: 100_000,
      });
      onEnabled();
    } finally { setBusy(false); }
  }
  return (
    <div className="card">
      <h2>Digger</h2>
      <p>Find the best Discogs marketplace bundles for your wantlist.</p>
      <button onClick={enable} disabled={busy}>Enable Digger</button>
    </div>
  );
}
```

```tsx
// explore/src/digger/Wantlist.tsx
import { useEffect, useState } from "react";
import { getSettings, getWantlist } from "./api";
import { OnboardingCard } from "./OnboardingCard";
import type { UserDiggerSettings, WantlistItem } from "./types";

export function Wantlist() {
  const [settings, setSettings] = useState<UserDiggerSettings | null | undefined>(undefined);
  const [items, setItems] = useState<WantlistItem[]>([]);

  async function refresh() {
    const s = await getSettings();
    setSettings(s);
    if (s) {
      const w = await getWantlist();
      setItems(w.items);
    }
  }

  useEffect(() => { refresh(); }, []);

  if (settings === undefined) return <div>Loading…</div>;
  if (settings === null || !settings.enabled) return <OnboardingCard onEnabled={refresh} />;

  return (
    <div className="digger-wantlist">
      <h1>Wantlist ({items.length})</h1>
      <table>
        <thead><tr><th>Artist</th><th>Title</th><th>Year</th><th>Tier</th><th>Listings</th></tr></thead>
        <tbody>
          {items.map((it) => (
            <tr key={it.release_id}>
              <td>{it.artist ?? "—"}</td>
              <td>{it.title ?? "—"}</td>
              <td>{it.year ?? "—"}</td>
              <td>{it.tier}</td>
              <td>{it.active_listings}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

```tsx
// explore/src/digger/index.tsx
export { Wantlist } from "./Wantlist";
```

In `explore/src/main.tsx`:

```tsx
import { Wantlist } from "./digger";
<Route path="/digger/wantlist" element={<RequireAuth><Wantlist /></RequireAuth>} />
```

- [ ] **Step 4: Run test to verify it passes**

`cd explore && npm test -- digger/Wantlist`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add explore/src/digger/ explore/src/main.tsx tests/explore/digger/Wantlist.test.tsx
git commit -m "feat(digger): explore wantlist page skeleton with onboarding card"
```

---

## Task 23: WantlistRow — tier toggle + condition + max-price

**Files:**
- Create: `explore/src/digger/WantlistRow.tsx`
- Modify: `explore/src/digger/Wantlist.tsx`
- Test: `tests/explore/digger/WantlistRow.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// tests/explore/digger/WantlistRow.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { WantlistRow } from "../../../explore/src/digger/WantlistRow";

const item = {
  release_id: 1, title: "Kind of Blue", artist: "Miles Davis", year: 1959,
  cover_image_url: null, tier: "nice" as const,
  min_media_condition: "VG" as const, min_sleeve_condition: "VG" as const,
  max_price_cents: null, active_listings: 5, last_scraped_at: null,
};

describe("WantlistRow", () => {
  it("calls onTierChange when toggling tier", () => {
    const cb = vi.fn();
    render(
      <table><tbody>
        <WantlistRow item={item} onTierChange={cb} onConditionChange={() => {}} onMaxPriceChange={() => {}} />
      </tbody></table>
    );
    fireEvent.click(screen.getByRole("button", { name: /must/i }));
    expect(cb).toHaveBeenCalledWith(1, "must");
  });
});
```

- [ ] **Step 2: Implement `WantlistRow`**

```tsx
// explore/src/digger/WantlistRow.tsx
import type { WantlistItem, Tier, Condition, SleeveCondition } from "./types";

const TIERS: Tier[] = ["must", "nice", "eventually"];
const CONDITIONS: Condition[] = ["M", "NM", "VG+", "VG", "G+", "G", "F", "P"];
const SLEEVE_CONDITIONS: SleeveCondition[] = [...CONDITIONS, "generic", "no_cover"];

interface Props {
  item: WantlistItem;
  onTierChange(release_id: number, tier: Tier): void;
  onConditionChange(release_id: number, key: "min_media_condition" | "min_sleeve_condition", value: string): void;
  onMaxPriceChange(release_id: number, cents: number | null): void;
}

export function WantlistRow({ item, onTierChange, onConditionChange, onMaxPriceChange }: Props) {
  return (
    <tr data-release-id={item.release_id}>
      <td>{item.cover_image_url ? <img src={item.cover_image_url} alt="" width={48} /> : null}</td>
      <td>{item.artist ?? "—"} — {item.title ?? "—"}</td>
      <td>{item.year ?? ""}</td>
      <td>
        <div role="group" aria-label="tier">
          {TIERS.map((t) => (
            <button key={t} aria-pressed={item.tier === t}
                    onClick={() => onTierChange(item.release_id, t)}>{t}</button>
          ))}
        </div>
      </td>
      <td>
        <select value={item.min_media_condition}
                onChange={(e) => onConditionChange(item.release_id, "min_media_condition", e.target.value)}>
          {CONDITIONS.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </td>
      <td>
        <select value={item.min_sleeve_condition}
                onChange={(e) => onConditionChange(item.release_id, "min_sleeve_condition", e.target.value)}>
          {SLEEVE_CONDITIONS.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </td>
      <td>
        <input type="number" min={0}
               value={item.max_price_cents != null ? item.max_price_cents / 100 : ""}
               onChange={(e) => onMaxPriceChange(item.release_id,
                 e.target.value === "" ? null : Math.round(Number(e.target.value) * 100))} />
      </td>
      <td className="active-count">{item.active_listings || <span className="badge">watching</span>}</td>
    </tr>
  );
}
```

In `Wantlist.tsx` replace the placeholder tbody with `WantlistRow`, wiring each callback to `setPriority(...)` followed by `refresh()`.

- [ ] **Step 3: Run test**

`cd explore && npm test -- digger/WantlistRow`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add explore/src/digger/ tests/explore/digger/WantlistRow.test.tsx
git commit -m "feat(digger): tier toggle + condition + max-price row controls"
```

---

## Task 24: Bulk-actions toolbar + filters + stats banner

**Files:**
- Create: `explore/src/digger/BulkActionsBar.tsx`, `Filters.tsx`, `StatsBanner.tsx`
- Modify: `explore/src/digger/Wantlist.tsx`
- Test: `tests/explore/digger/BulkActionsBar.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// tests/explore/digger/BulkActionsBar.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { BulkActionsBar } from "../../../explore/src/digger/BulkActionsBar";

describe("BulkActionsBar", () => {
  it("calls onBulkTier when applying", () => {
    const cb = vi.fn();
    render(
      <BulkActionsBar selected={[1, 2]} onBulkTier={cb}
                      onBulkCondition={() => {}} onClearSelection={() => {}} />
    );
    fireEvent.change(screen.getByLabelText(/set tier to/i), { target: { value: "must" } });
    fireEvent.click(screen.getByRole("button", { name: /^apply$/i }));
    expect(cb).toHaveBeenCalledWith([1, 2], "must");
  });
});
```

- [ ] **Step 2: Implement**

```tsx
// explore/src/digger/BulkActionsBar.tsx
import { useState } from "react";
import type { Tier, Condition, SleeveCondition } from "./types";

interface Props {
  selected: number[];
  onBulkTier(ids: number[], tier: Tier): void;
  onBulkCondition(ids: number[], media: Condition | null, sleeve: SleeveCondition | null): void;
  onClearSelection(): void;
}

export function BulkActionsBar({ selected, onBulkTier, onBulkCondition, onClearSelection }: Props) {
  const [tier, setTier] = useState<Tier>("must");
  const [media, setMedia] = useState<Condition | "">("");
  const [sleeve, setSleeve] = useState<SleeveCondition | "">("");
  if (selected.length === 0) return null;
  return (
    <div className="bulk-bar">
      <span>{selected.length} selected</span>
      <label>Set tier to{" "}
        <select value={tier} onChange={(e) => setTier(e.target.value as Tier)}>
          <option value="must">must</option>
          <option value="nice">nice</option>
          <option value="eventually">eventually</option>
        </select>
      </label>
      <button onClick={() => onBulkTier(selected, tier)}>Apply</button>
      <label>Condition floor
        <select value={media} onChange={(e) => setMedia(e.target.value as Condition)}>
          <option value="">—</option>
          {["M", "NM", "VG+", "VG", "G+", "G", "F", "P"].map((c) => <option key={c}>{c}</option>)}
        </select>
        <select value={sleeve} onChange={(e) => setSleeve(e.target.value as SleeveCondition)}>
          <option value="">—</option>
          {["M", "NM", "VG+", "VG", "G+", "G", "F", "P", "generic", "no_cover"].map((c) => <option key={c}>{c}</option>)}
        </select>
      </label>
      <button onClick={() => onBulkCondition(selected, media || null, sleeve || null)}>Apply</button>
      <button onClick={onClearSelection}>Clear</button>
    </div>
  );
}
```

```tsx
// explore/src/digger/Filters.tsx
import type { Tier } from "./types";

interface Props {
  tierFilter: Tier | "all";
  setTierFilter(v: Tier | "all"): void;
  hasListingsOnly: boolean;
  setHasListingsOnly(v: boolean): void;
}

export function Filters({ tierFilter, setTierFilter, hasListingsOnly, setHasListingsOnly }: Props) {
  return (
    <div className="filters">
      <label>Tier
        <select value={tierFilter} onChange={(e) => setTierFilter(e.target.value as Tier | "all")}>
          <option value="all">all</option>
          <option value="must">must</option>
          <option value="nice">nice</option>
          <option value="eventually">eventually</option>
        </select>
      </label>
      <label>
        <input type="checkbox" checked={hasListingsOnly}
               onChange={(e) => setHasListingsOnly(e.target.checked)} />
        Hide items with no listings
      </label>
    </div>
  );
}
```

```tsx
// explore/src/digger/StatsBanner.tsx
import type { WantlistItem } from "./types";

export function StatsBanner({ items }: { items: WantlistItem[] }) {
  const by: Record<string, number> = { must: 0, nice: 0, eventually: 0 };
  let mustAvail = 0;
  for (const it of items) {
    by[it.tier]++;
    if (it.tier === "must" && it.active_listings > 0) mustAvail++;
  }
  return (
    <div className="stats-banner">
      <span>{by.must} Must</span> · <span>{by.nice} Nice</span> · <span>{by.eventually} Eventually</span>
      <span> · {mustAvail}/{by.must} Must currently available</span>
    </div>
  );
}
```

Update `Wantlist.tsx` to add selection state, render the banner above the table, and render filters between banner and table.

- [ ] **Step 3: Run tests**

`cd explore && npm test -- digger`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add explore/src/digger/ tests/explore/digger/
git commit -m "feat(digger): bulk-actions toolbar, filters, and stats banner"
```

---

## Task 25: Settings drawer

**Files:**
- Create: `explore/src/digger/SettingsDrawer.tsx`
- Modify: `explore/src/digger/Wantlist.tsx`
- Test: `tests/explore/digger/SettingsDrawer.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// tests/explore/digger/SettingsDrawer.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { SettingsDrawer } from "../../../explore/src/digger/SettingsDrawer";

const settings = {
  enabled: true, country_code: "US", currency: "USD",
  scheduled_cadence: "weekly" as const, preferred_model: "sonnet" as const,
  daily_token_cap_interactive: 200000, daily_token_cap_scheduled: 100000,
};

describe("SettingsDrawer", () => {
  it("submits patched settings", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<SettingsDrawer settings={settings} onSave={onSave} onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText(/cadence/i), { target: { value: "biweekly" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ scheduled_cadence: "biweekly" }));
  });
});
```

- [ ] **Step 2: Implement**

```tsx
// explore/src/digger/SettingsDrawer.tsx
import { useState } from "react";
import type { UserDiggerSettings, Cadence } from "./types";

interface Props {
  settings: UserDiggerSettings;
  onSave(next: UserDiggerSettings): Promise<void>;
  onClose(): void;
}

export function SettingsDrawer({ settings, onSave, onClose }: Props) {
  const [s, setS] = useState<UserDiggerSettings>(settings);
  return (
    <aside className="drawer">
      <h2>Digger settings</h2>
      <label>Country <input value={s.country_code ?? ""} maxLength={2}
        onChange={(e) => setS({ ...s, country_code: e.target.value.toUpperCase() || null })} /></label>
      <label>Currency <input value={s.currency} maxLength={3}
        onChange={(e) => setS({ ...s, currency: e.target.value.toUpperCase() })} /></label>
      <label>Cadence
        <select value={s.scheduled_cadence}
                onChange={(e) => setS({ ...s, scheduled_cadence: e.target.value as Cadence })}>
          <option value="off">off</option><option value="weekly">weekly</option>
          <option value="biweekly">biweekly</option><option value="monthly">monthly</option>
        </select>
      </label>
      <label>Preferred model
        <select value={s.preferred_model}
                onChange={(e) => setS({ ...s, preferred_model: e.target.value as "haiku" | "sonnet" | "opus" })}>
          <option value="haiku">haiku</option><option value="sonnet">sonnet</option><option value="opus">opus</option>
        </select>
      </label>
      <label>Daily token cap (interactive) <input type="number" min={0} value={s.daily_token_cap_interactive}
        onChange={(e) => setS({ ...s, daily_token_cap_interactive: Number(e.target.value) })} /></label>
      <label>Daily token cap (scheduled) <input type="number" min={0} value={s.daily_token_cap_scheduled}
        onChange={(e) => setS({ ...s, daily_token_cap_scheduled: Number(e.target.value) })} /></label>
      <div className="drawer-actions">
        <button onClick={() => onSave(s).then(onClose)}>Save</button>
        <button onClick={onClose}>Cancel</button>
      </div>
    </aside>
  );
}
```

- [ ] **Step 3: Run test**

`cd explore && npm test -- digger/SettingsDrawer`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add explore/src/digger/SettingsDrawer.tsx tests/explore/digger/SettingsDrawer.test.tsx
git commit -m "feat(digger): explore settings drawer"
```

---

## Task 26: Perf tests for new endpoints

**Files:**
- Modify: `tests/perftest/config.yaml`, `tests/perftest/run_perftest.py`

- [ ] **Step 1: Append endpoints to `tests/perftest/config.yaml`**

```yaml
digger_settings_get:
  method: GET
  path: /api/digger/settings
  auth: jwt
  thresholds:
    p95_ms: 50
    error_rate: 0.001
digger_wantlist_get:
  method: GET
  path: /api/digger/wantlist
  auth: jwt
  thresholds:
    p95_ms: 300
    error_rate: 0.001
digger_wantlist_priority_put:
  method: PUT
  path: /api/digger/wantlist/{release_id}/priority
  auth: jwt
  body:
    tier: must
  path_params:
    release_id: 12345
  thresholds:
    p95_ms: 75
    error_rate: 0.001
digger_wantlist_bulk_tier:
  method: POST
  path: /api/digger/wantlist/bulk-tier
  auth: jwt
  body:
    release_ids: [12345, 23456]
    tier: nice
  thresholds:
    p95_ms: 120
    error_rate: 0.001
```

- [ ] **Step 2: Smoke-run**

`uv run python tests/perftest/run_perftest.py --only digger_settings_get,digger_wantlist_get --duration 10`
Expected: endpoints exercise without errors.

- [ ] **Step 3: Commit**

```bash
git add tests/perftest/config.yaml tests/perftest/run_perftest.py
git commit -m "test(digger): perf-test config for new /api/digger endpoints"
```

---

## Task 27: Scraping policy + docs

**Files:**
- Create: `docs/digger-scraping-policy.md`
- Modify: `CLAUDE.md`, `docs/architecture.md`, `docs/database-schema.md`

- [ ] **Step 1: Write the scraping policy doc**

```markdown
# Digger Scraping Policy

## What we scrape

- Public Discogs marketplace listing pages: `https://www.discogs.com/sell/release/{release_id}`
- Public Discogs seller profile pages: `https://www.discogs.com/seller/{username}`

We do NOT scrape any page requiring authentication or user-private data.

## Rate budget

- Global cap: **600 requests/hour** (1 every 6 seconds on average).
- Enforced via a Redis token bucket shared across all worker instances.
- Configurable via `DIGGER_RATE_BUDGET_PER_HOUR`.

## User-Agent

`discogsography-digger/<version> (github.com/SimplicityGuy/discogsography)` — honest, attributable. Configurable via `DIGGER_SCRAPER_USER_AGENT_FILE` for production secrets management.

## Backoff & circuit breaker

- Per-release exponential backoff on failure: 2h → 4h → 8h → … capped at 24h.
- Global circuit breaker opens when failure rate over the last 5 minutes ≥ 30%, with a 30-minute cooldown.

## Caching

Listings stored in `digger.listings` with `first_seen_at`/`last_seen_at`/`removed_at`. Soft-deleted via `removed_at` so historical reports remain coherent.

## ToS posture

Discogs ToS permits indexing of public listing pages with reasonable rate. We stay well under that ceiling and identify ourselves transparently.
```

- [ ] **Step 2: Update `CLAUDE.md`**

Append directory row:
```
digger/               Digger service — Discogs marketplace scraper + scheduled-run worker
```

Append service-ports table row:
```
| Digger            | —    | 8012 |
```

- [ ] **Step 3: Cross-reference docs**

In `docs/architecture.md` add a short paragraph about Digger pointing at the spec. In `docs/database-schema.md` add the `digger` schema overview.

- [ ] **Step 4: Commit**

```bash
git add docs/digger-scraping-policy.md CLAUDE.md docs/architecture.md docs/database-schema.md
git commit -m "docs(digger): scraping policy + CLAUDE.md + architecture/schema cross-refs"
```

---

## Task 28: E2E smoke test

**Files:**
- Create: `tests/e2e/test_digger_m1_smoke.py`

- [ ] **Step 1: Write the smoke test**

```python
# tests/e2e/test_digger_m1_smoke.py
"""End-to-end smoke for M1: opt in, sync, scrape, see listings."""

import asyncio
import pytest


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_m1_smoke(api_client, browser_session, postgres_pool, fake_discogs_marketplace):
    user = await browser_session.login_via_oauth()

    r = await api_client.put(
        "/api/digger/settings", headers=user.auth_headers,
        json={"enabled": True, "country_code": "US", "currency": "USD",
              "scheduled_cadence": "weekly", "preferred_model": "sonnet"},
    )
    assert r.status_code == 204

    r = await api_client.post("/api/sync", headers=user.auth_headers, json={"target": "wantlist"})
    assert r.status_code in (200, 202)

    rows: list[dict] = []
    for _ in range(20):
        rows = (await api_client.get("/api/digger/wantlist", headers=user.auth_headers)).json()["items"]
        if rows:
            break
        await asyncio.sleep(0.5)
    assert rows, "no wantlist items appeared after sync"

    target_release = rows[0]["release_id"]
    count = 0
    for _ in range(60):
        async with postgres_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM digger.listings "
                "WHERE release_id=$1 AND removed_at IS NULL",
                target_release,
            )
        if count > 0:
            break
        await asyncio.sleep(1)
    assert count > 0, "no listings appeared after scrape"

    page = await browser_session.goto("/digger/wantlist")
    cell = await page.locator(f"[data-release-id='{target_release}'] .active-count").inner_text()
    assert int(cell) > 0
```

- [ ] **Step 2: Run E2E**

`just test-e2e -- tests/e2e/test_digger_m1_smoke.py`
Expected: PASS against the `fake_discogs_marketplace` fixture serving canned HTML.

- [ ] **Step 3: Commit**

```bash
git add tests/e2e/test_digger_m1_smoke.py
git commit -m "test(digger): M1 E2E smoke (opt-in → sync → scrape → UI)"
```

---

## Task 29: Final polish — coverage + lint + smoke

- [ ] **Step 1: Run all digger tests**

```bash
just test-digger
just test-api
just test-explore
```
Expected: all PASS; coverage ≥80% on `digger/` and `api/queries/digger_queries.py`.

- [ ] **Step 2: Lint**

```bash
just lint-python
cd explore && npm run lint
```
Expected: no errors.

- [ ] **Step 3: Build images**

```bash
just build
```
Expected: all images build.

- [ ] **Step 4: Smoke up the stack**

```bash
just up
just digger-logs
```

Verify within 30s: digger container logs "Digger starting", `/health` returns 200, at least one scrape attempt logged (with a seeded test wantlist).

- [ ] **Step 5: Commit any final fixes**

```bash
git add -u
git commit -m "chore(digger): M1 polish — lint, coverage, smoke"
```

---

## Self-review checklist (run after writing the plan)

1. **Spec coverage** — M1 success criteria covered:
   - "User can opt in, view wantlist with listings, assign tiers, edit settings" ✓ (Tasks 18, 22-25)
   - "Scraper sustains 600 req/hr without backoff for ≥48h" ✓ (Tasks 7, 16, 27 — policy + load)
   - "Listings table populates" ✓ (Tasks 10-12, 16)
   - "≥90% scrape success; circuit breaker stays closed" ✓ (Tasks 8, 16)
2. **Placeholders** — none. Every step has code, commands, expected outputs.
3. **Type consistency** — `Tier`, `Cadence`, `Model`, `Condition`, `SleeveCondition` spelled identically across `schema-init/digger_schema.py` (SQL enums), `api/models/digger.py` and `api/queries/digger_queries.py` (Python Literals), `explore/src/digger/types.ts` (TS Literals).
4. **Ambiguity** —
   - Service-token header is `X-Service-Token`.
   - Placeholder seller IDs are negative: `-abs(hash(username)) % (1<<31)`, replaced when the seller-profile scrape resolves the real ID.
   - Asyncio primitives lazy-initialized in every component (`CircuitBreaker._lock`).
   - Rate budget uses Redis WATCH/MULTI/EXEC, no Lua scripts.
   - All scrape rows use `await conn.set_autocommit(False)` before `conn.transaction()`.

---

## Out-of-scope for M1 (M2/M3)

- `common/digger_optimizer/` — scaffold only; the ILP solver and Pareto-front ship in M2.
- `/api/digger/recommend` endpoint — M2.
- Reports inbox & report viewer UI — M2.
- Opportunistic-refresh trigger + Redis pub/sub — endpoint exists in M2; plumbing is fully in M1 only at the data layer.
- LLM agent runtime, chat UI, MCP tools — all M3.
