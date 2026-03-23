# Query Debug Logging & Database Profiling

## Problem

The API service executes Neo4j Cypher and PostgreSQL SQL queries across many files with no visibility into what queries are running or how they perform. Developers debugging slow queries or unexpected results must add ad-hoc logging, then remove it. There is no way to profile query execution plans without modifying code.

## Solution

Add opt-in query debug logging and database profiling to the API service, controlled by existing `LOG_LEVEL` and a new `DB_PROFILING` environment variable. Profiling covers both Cypher (Neo4j PROFILE/EXPLAIN) and SQL (PostgreSQL EXPLAIN (ANALYZE, BUFFERS, VERBOSE) / EXPLAIN).

## Behavior Matrix

| LOG_LEVEL | DB_PROFILING | Console log (structlog JSON)       | `/logs/profiling.log`                                               |
| --------- | ------------ | ---------------------------------- | ------------------------------------------------------------------- |
| INFO+     | any          | No query logging                   | Nothing                                                             |
| DEBUG     | unset/false  | Full query + params (Cypher & SQL) | Nothing                                                             |
| DEBUG     | true         | Full query + params (Cypher & SQL) | Full query + params + PROFILE/EXPLAIN summary (both Cypher and SQL) |

Both conditions (DEBUG **and** DB_PROFILING=true) must be met for profiling. The PROFILE/EXPLAIN summary never appears in the console log — only in the dedicated profiling log file.

## Architecture

### New Files

#### `common/query_debug.py`

Low-level debug logging utilities:

- `is_debug() -> bool` — checks if root logger is at DEBUG level.
- `is_db_profiling() -> bool` — returns True only when `is_debug()` AND `DB_PROFILING` env var is `"true"` (case-insensitive).
- `get_profiling_logger() -> logging.Logger` — lazy-initialized logger writing to `/logs/profiling.log`. Uses `propagate=False` so output stays out of the console. Human-readable text format with timestamps.
- `log_cypher_query(cypher, params)` — logs full query text + parameter values to console via structlog at DEBUG level. Uses `🔗` emoji per emoji guide.
- `log_sql_query(query, params, cursor)` — logs full SQL text + parameter values to console via structlog at DEBUG level. For `psycopg.sql.Composable` objects, renders via `query.as_string(cursor)`. Uses `🐘` emoji per emoji guide.
- `log_profile_result(cypher, params, summary)` — writes Cypher query + params + `summary.profile['args']['string-representation']` to profiling log.
- `log_explain_result(cypher, params, summary, original_error)` — writes Cypher query + params + `summary.plan['args']['string-representation']` + error details to profiling log.
- `log_sql_profile_result(sql, params, plan_text)` — writes SQL query + params + PostgreSQL `EXPLAIN (ANALYZE, BUFFERS, VERBOSE)` output to profiling log.
- `log_sql_explain_result(sql, params, plan_text, original_error)` — writes SQL query + params + PostgreSQL `EXPLAIN` output + error details to profiling log.
- `execute_sql(cursor, query, params)` — executes `await cursor.execute(query, params)`, logging the query at DEBUG level beforehand. When `is_db_profiling()` is True, runs `EXPLAIN (ANALYZE, BUFFERS, VERBOSE)` after successful execution and writes results to profiling log. On query failure with profiling enabled, runs `EXPLAIN` (without ANALYZE) as a best-effort fallback. Handles both plain string queries and `psycopg.sql.Composable` objects — for Composable, renders to string via `query.as_string(cursor)` for the log output. The `params` argument accepts `list`, `tuple`, `dict`, or `None`.

Exported from `common/__init__.py`.

#### `api/queries/helpers.py`

Consolidated Neo4j query execution helpers, replacing the duplicated copies across 4 files:

- `run_query(driver, cypher, *, timeout=None, database=None, **params) -> list[dict]`
- `run_single(driver, cypher, *, timeout=None, database=None, **params) -> dict | None`
- `run_count(driver, cypher, *, timeout=None, database=None, **params) -> int`

Each helper:

1. Logs query + params to console at DEBUG level (always, regardless of profiling).
1. If profiling enabled: prepends `PROFILE` to the Cypher query.
1. Executes the query and collects results.
1. If profiling enabled: calls `await result.consume()` **inside the session context manager** to get `ResultSummary`, writes profile to profiling log (includes query + params for correlation).
1. On timeout/exception with profiling enabled: opens a new session, re-runs with `EXPLAIN` prefix (wrapped in try/except to handle unreachable DB gracefully), writes the plan to profiling log with the original error, then re-raises the original exception.

Note: `insights_neo4j_queries.py` currently passes `database="neo4j"` to `driver.session()`. The consolidated helpers will accept an optional `database` parameter (default `None`) to support this. The `record.data()` vs `dict(record)` difference is functionally equivalent for the field projections used in these queries.

### Modified Files

#### `common/config.py`

- At end of `setup_logging()`: if DEBUG + DB_PROFILING, log a startup warning: `"⚠️ Database profiling enabled — PROFILE/EXPLAIN plans will be logged for Cypher and SQL queries"`.

#### `common/__init__.py`

- Export `execute_sql`, `is_debug`, `is_db_profiling` from `common/query_debug`.

#### `api/queries/neo4j_queries.py`

- Remove local `_run_query`, `_run_single`, `_run_count`.
- Import `run_query`, `run_single`, `run_count` from `api.queries.helpers`.
- Update all call sites (use `run_query` instead of `_run_query`, etc.).

#### `api/queries/user_queries.py`

- Remove local `_run_query`, `_run_count`.
- Import from `api.queries.helpers`.
- Update call sites.

#### `api/queries/taste_queries.py`

- Remove local `_run_query`, `_run_count`.
- Import from `api.queries.helpers`.
- Update call sites. Note: this file uses `timeout=120` as default — call sites will pass `timeout=120` explicitly.

#### `api/queries/insights_neo4j_queries.py`

- Replace inline `async with driver.session()` + `session.run()` pattern with calls to `run_query` from helpers.
- Remove direct session management.

#### `api/queries/gap_queries.py`

- Update imports from `api.queries.user_queries` to `api.queries.helpers`.

#### `api/queries/label_dna_queries.py`

- Update imports from `api.queries.neo4j_queries` to `api.queries.helpers`.

#### `api/queries/recommend_queries.py`

- Update imports from `api.queries.neo4j_queries` to `api.queries.helpers`.

#### `api/syncer.py` (Neo4j write queries)

- Two inline `session.run()` calls for collection sync and wantlist sync (lines ~211 and ~372).
- These are write operations (MERGE/CREATE). Add `log_cypher_query()` calls for DEBUG visibility but **exclude from PROFILE** — profiling write queries adds meaningful overhead and the execution plans for batch MERGE/UNWIND are rarely useful for debugging. Only read queries go through the profiled helpers.

#### SQL execution sites (~25 locations)

All `await cur.execute(query, params)` calls across these files change to `await execute_sql(cur, query, params)`:

- `api/api.py` — auth, user profile, config queries
- `api/syncer.py` — sync operations
- `api/routers/sync.py` — sync trigger endpoints
- `api/routers/collection.py` — collection format queries
- `api/queries/search_queries.py` — full-text search
- `api/queries/insights_pg_queries.py` — data completeness

Import `execute_sql` from `common` at each site.

## Profiling Log Format

### Cypher PROFILE result (successful query)

```
2026-03-19T10:15:32 ══════════════════════════════════════════════════════════
PROFILE result for Cypher query:

MATCH (a:Artist {id: $artist_id})
OPTIONAL MATCH (r:Release)-[:BY]->(a)
RETURN a.id AS artist_id, a.name AS artist_name, count(DISTINCT r) AS release_count

Parameters: {'artist_id': '12345'}

+------------------+----------------+------+--------+
| Operator         | EstimatedRows  | Rows | DbHits |
+------------------+----------------+------+--------+
| ... (Neo4j string-representation output) ...
+------------------+----------------+------+--------+
```

### Cypher EXPLAIN result (after query failure)

```
2026-03-19T10:15:32 ══════════════════════════════════════════════════════════
EXPLAIN (after error) for Cypher query:

MATCH (a:Artist {id: $artist_id})
OPTIONAL MATCH (r:Release)-[:BY]->(a)
RETURN a.id AS artist_id, a.name AS artist_name, count(DISTINCT r) AS release_count

Parameters: {'artist_id': '12345'}
Original error: TransientError: query timed out after 120000ms

... (Neo4j plan string-representation output) ...
```

### SQL EXPLAIN (ANALYZE, BUFFERS, VERBOSE) result (successful query)

```
2026-03-19T10:15:32 ══════════════════════════════════════════════════════════
EXPLAIN (ANALYZE, BUFFERS, VERBOSE) result for SQL query:

SELECT * FROM artists WHERE id = %s

Parameters: [12345]

Seq Scan on public.artists  (cost=0.00..1.05 rows=1 width=64) (actual time=0.012..0.013 rows=1 loops=1)
  Output: id, name, profile
  Filter: (artists.id = 12345)
  Buffers: shared hit=1
Planning Time: 0.045 ms
Execution Time: 0.028 ms
```

### SQL EXPLAIN result (after query failure)

```
2026-03-19T10:15:32 ══════════════════════════════════════════════════════════
EXPLAIN (after error) for SQL query:

SELECT * FROM bad_table WHERE id = %s

Parameters: [12345]
Original error: UndefinedTable: relation "bad_table" does not exist

Seq Scan on bad_table  (cost=0.00..1.05 rows=1 width=64)
```

## Environment Variables

| Variable       | Values                                | Default         | Description                                                                                                                                             |
| -------------- | ------------------------------------- | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `LOG_LEVEL`    | DEBUG, INFO, WARNING, ERROR, CRITICAL | INFO            | Existing. DEBUG enables query logging.                                                                                                                  |
| `DB_PROFILING` | true, false                           | (unset = false) | When true AND LOG_LEVEL=DEBUG, adds PROFILE to Cypher queries and EXPLAIN (ANALYZE, BUFFERS, VERBOSE) to SQL queries, writing results to profiling log. |

## Security Considerations

- Query parameters (which may contain user IDs, search terms) are only logged at DEBUG level. Production should use INFO or higher.
- A startup warning is logged when profiling is active to make it obvious.
- PROFILE/EXPLAIN ANALYZE adds execution overhead — it should never be enabled in production.
- The profiling log file is in `/logs/` alongside existing service logs, governed by the same volume mounts and access controls.

## Testing

- Unit tests for `is_debug()`, `is_db_profiling()` with mocked env/log level.
- Unit tests for `execute_sql` verifying it delegates to `cursor.execute` and logs at DEBUG.
- Unit tests for `execute_sql` verifying SQL profiling (EXPLAIN ANALYZE after success, EXPLAIN after failure).
- Unit tests for `log_sql_profile_result` and `log_sql_explain_result`.
- Unit tests for `run_query`/`run_single`/`run_count` verifying:
  - Normal execution unchanged when not DEBUG.
  - Query + params logged when DEBUG.
  - PROFILE prefix added when profiling enabled.
  - EXPLAIN fallback on exception when profiling enabled.
- Integration test: run a query with profiling enabled, verify profiling.log is written.

## Notes

- **PROFILE with CALL procedures**: Neo4j fulltext index queries (e.g., `CALL db.index.fulltext.queryNodes(...)` used in autocomplete) support PROFILE. The PROFILE keyword prepends the entire statement and works with CALL.
- **Write query exclusion**: The syncer's MERGE/UNWIND batch writes are excluded from PROFILE (debug-logged only) since profiling write queries adds overhead without useful diagnostic value.
- **SQL profiling**: `EXPLAIN (ANALYZE, BUFFERS, VERBOSE)` is used for successful SQL queries to get actual execution times and buffer usage. On failure, plain `EXPLAIN` (without ANALYZE) is used since the query cannot be re-executed.
- **Backward compatibility**: The `timeout` parameter defaults to `None` in the consolidated helpers, matching `neo4j_queries.py` behavior. Call sites in `taste_queries.py` (which previously defaulted to 120) will pass `timeout=120` explicitly. `user_queries.py` had no timeout, which maps to `None` — no change needed.

## No New Dependencies

Uses only structlog, logging stdlib, and existing neo4j/psycopg driver APIs.
