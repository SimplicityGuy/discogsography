# Apache AGE — PostgreSQL Graph Extension

## Overview

[Apache AGE](https://github.com/apache/age) (A Graph Extension) adds openCypher graph query capabilities to PostgreSQL as an extension. Instead of running a separate graph database, graph data lives alongside existing relational tables inside the same PostgreSQL instance.

- **Repository:** [apache/age](https://github.com/apache/age) (4.3k stars, Apache 2.0 license)
- **Latest release:** v1.7.0 (January 2026)
- **Supported PostgreSQL:** 11–18
- **Python driver:** `apache-age-python` (wraps psycopg3)
- **Query language:** openCypher subset + SQL hybrid

## Why This Is Interesting for Discogsography

Discogsography already runs PostgreSQL 18 for the tableinator analytics tables. Apache AGE would:

1. **Eliminate Neo4j entirely** — graph data lives in the existing PostgreSQL instance
2. **Remove an infrastructure service** — one fewer container, backup target, monitoring endpoint
3. **Enable SQL+Cypher hybrid queries** — join graph traversals with JSONB analytics data in a single query
4. **Simplify the stack** — same connection pool, same auth, same backup strategy

## Compatibility Analysis

### Supported Cypher Features

AGE implements the openCypher specification. The following features used by Discogsography are supported:

- `MATCH` / `OPTIONAL MATCH`
- `MERGE` / `CREATE` / `SET` / `DELETE`
- `WITH` clause chaining
- `UNWIND`
- `RETURN` with aliasing
- `ORDER BY` / `SKIP` / `LIMIT`
- `WHERE` with property predicates
- `CASE WHEN ... ELSE ... END`
- `count()`, `collect()` aggregation functions
- Parameterized queries

### Breaking Incompatibilities

#### 1. Query Wrapping — All Cypher Runs Inside SQL

AGE Cypher queries are executed as SQL function calls, not standalone Cypher:

```sql
-- AGE requires wrapping all Cypher in ag_catalog.cypher()
SELECT * FROM ag_catalog.cypher('discogsography', $$
    MATCH (a:Artist {name: 'Radiohead'})
    RETURN a.id, a.name
$$) AS (id agtype, name agtype);
```

Every query in `api/queries/graph_queries.py`, `user_queries.py`, and `gap_queries.py` must be wrapped. The return columns must be declared in the SQL `AS` clause.

**Impact:** All ~50 Cypher queries need SQL wrapping. This is mechanical but tedious.

#### 2. COUNT {} Subqueries

**Not supported.** Same as Memgraph — rewrite as `OPTIONAL MATCH` + `count()` + `WITH`.

**Affected:** 4 explore center-node queries.

#### 3. No Fulltext Index Procedures

AGE does not have its own fulltext search. Instead, use PostgreSQL's native `tsvector` / `tsquery` full-text search on the underlying graph tables, or maintain a parallel text search strategy.

Options:
- **Option A:** Run fulltext queries as pure SQL against PostgreSQL's existing tsvector indexes (the tableinator tables already have these)
- **Option B:** Create tsvector indexes on AGE's internal vertex tables
- **Option C:** Keep fulltext search as a separate SQL path, not through the graph layer

**Affected:** 4 autocomplete queries — must be reimplemented as SQL, not Cypher.

#### 4. Constraint and Index Syntax

AGE uses PostgreSQL-native constraints and indexes on internal tables, not Cypher DDL:

```sql
-- AGE does not use CREATE CONSTRAINT in Cypher
-- Instead, create unique indexes on the internal vertex tables
-- or use ag_catalog functions

-- Create a graph
SELECT * FROM ag_catalog.create_graph('discogsography');

-- Labels are created implicitly on first MERGE/CREATE
-- Indexes use PostgreSQL DDL on the internal tables
```

**Affected:** All 20 schema-init statements must be reimplemented.

#### 5. No APOC / No Database Procedures

No equivalent to `CALL apoc.meta.stats()` or `CALL dbms.components()`. Use PostgreSQL system catalogs instead:

```sql
-- Node count
SELECT count(*) FROM ag_catalog.cypher('discogsography', $$
    MATCH (n) RETURN count(n)
$$) AS (count agtype);

-- Or query internal AGE tables directly
SELECT count(*) FROM discogsography._ag_label_vertex;

-- Version
SELECT version();  -- PostgreSQL version
SELECT extversion FROM pg_extension WHERE extname = 'age';
```

#### 6. Driver Change

AGE uses the `apache-age-python` package wrapping psycopg3, not the `neo4j` Python driver:

```python
import age

# Connection via psycopg3
conn = age.connect(
    host="localhost", port=5432,
    dbname="discogsography",
    user="postgres", password="discogsography",
    graph="discogsography"
)

# Execute Cypher
with conn.cursor() as cur:
    cur.execute("""
        SELECT * FROM ag_catalog.cypher('discogsography', $$
            MATCH (a:Artist {name: $name})
            RETURN a.id, a.name
        $$, %s) AS (id agtype, name agtype)
    """, (age.to_agtype({"name": "Radiohead"}),))
    results = cur.fetchall()
```

**No async support** in the AGE Python driver currently. The project uses async throughout (`AsyncGraphDatabase`, `AsyncResilientNeo4jDriver`). Options:
- Use psycopg3's native async support (`AsyncConnection`) and execute AGE queries directly
- Contribute async support to the AGE Python driver
- Use synchronous queries in a thread pool executor

#### 7. Result Type Handling

AGE returns `agtype` values that must be cast or parsed. The AGE Python driver handles unmarshaling to `Vertex`, `Edge`, and `Path` objects, but the API differs from Neo4j's `Record` interface.

### Compatibility Summary

| Feature | Neo4j | Apache AGE | Adaptation |
|---------|-------|------------|------------|
| Cypher queries | Native | Wrapped in SQL | All queries wrapped |
| UNWIND / MERGE | Native | Supported | Works inside SQL wrapper |
| OPTIONAL MATCH | Native | Supported | Works inside SQL wrapper |
| COUNT {} subqueries | Supported | Not supported | Rewrite as aggregation |
| Fulltext search | `db.index.fulltext.queryNodes()` | Not available | Use PostgreSQL tsvector |
| Constraints | Cypher DDL | PostgreSQL DDL | Reimplemented |
| Indexes | Cypher DDL | PostgreSQL DDL | Reimplemented |
| Driver | `neo4j` (async) | `apache-age-python` (sync) | New driver, async wrapper needed |
| Stats/monitoring | APOC procedures | PostgreSQL system catalogs | Reimplemented |
| Transactions | `execute_write()` | psycopg3 transactions | Different API |

## Performance Considerations

### Advantages

- **No network hop** — graph queries execute inside PostgreSQL, no Bolt protocol overhead
- **Shared buffer pool** — PostgreSQL's page cache serves both graph and relational data
- **Mature optimizer** — PostgreSQL's query planner is battle-tested
- **ACID out of the box** — same transaction guarantees as the rest of the data

### Concerns

- **Not a native graph engine** — graph data stored in relational tables with adjacency list pattern; deep traversals may be slower than native graph storage
- **No graph-specific optimizations** — no index-free adjacency, no native relationship storage
- **Extension maturity** — AGE is younger than Neo4j; fewer production deployments at scale
- **Memory** — no dedicated graph memory tuning; shares PostgreSQL's `shared_buffers`

### What to Benchmark Specifically

See [shared-pre-work.md](shared-pre-work.md) for the benchmark harness, workload definitions, metrics, and Docker Compose profiles shared across all candidates.

Benchmarks use synthetic data inserted directly into each database via the `GraphBackend` abstraction — no extractor or graphinator changes needed. Two scale points (`small` ~135k nodes/~540k relationships and `large` ~1.35M nodes/~5.4M relationships) provide enough signal to understand approximate orders of magnitude of performance differences.

In addition to the shared workloads:

| Benchmark | Why It Matters for AGE |
|-----------|----------------------|
| Deep traversal (3+ hops) | Tests whether relational joins keep up with native graph traversal |
| SQL+Cypher hybrid query | Unique to AGE — join graph data with JSONB analytics in one query |
| Concurrent writes + reads | Tests PostgreSQL lock contention on graph tables |
| Large UNWIND batches | Tests whether AGE's MERGE performance degrades at batch sizes >500 |
| Schema init time | AGE creates internal tables per label; may be slower than Neo4j constraint creation |

### Execution

```bash
docker compose --profile age up postgres-age -d

# Synthetic data benchmarks at both scale points
uv run python -m benchmarks.runner --backend age --host localhost:5434 --scale small --load
uv run python -m benchmarks.runner --backend age --host localhost:5434 --scale small
uv run python -m benchmarks.runner --backend age --host localhost:5434 --scale large --load
uv run python -m benchmarks.runner --backend age --host localhost:5434 --scale large

uv run python -m benchmarks.compare benchmarks/results/neo4j_*.json benchmarks/results/age_*.json
```

### Hybrid Query Example (Unique to AGE)

This query type is only possible with AGE — joining graph traversal with JSONB analytics:

```sql
-- Find artists in the graph, enriched with JSONB data from tableinator
SELECT g.name, g.release_count, t.data->>'profile' AS profile
FROM ag_catalog.cypher('discogsography', $$
    MATCH (r:Release)-[:BY]->(a:Artist {name: 'Radiohead'})
    RETURN a.name AS name, count(r) AS release_count
$$) AS g(name agtype, release_count agtype)
JOIN artists t ON t.data_id = g.name::text;
```

## Native Query Alternative: Pure SQL on AGE Internal Tables

Instead of wrapping Cypher in `ag_catalog.cypher()` SQL calls, AGE's graph data is stored in regular PostgreSQL tables. You can query these tables directly with pure SQL, completely bypassing the Cypher layer and its limitations.

### How AGE Stores Graph Data

When AGE creates a graph named `discogsography`, it creates a PostgreSQL schema with internal tables:

```
discogsography.Artist       -- vertex table for :Artist nodes
discogsography.Label        -- vertex table for :Label nodes
discogsography.Release      -- vertex table for :Release nodes
discogsography.BY           -- edge table for [:BY] relationships
discogsography.ON           -- edge table for [:ON] relationships
discogsography._ag_label_vertex   -- base vertex table
discogsography._ag_label_edge     -- base edge table
```

Each vertex table has columns: `id` (graphid type), `properties` (agtype — JSON-like). Each edge table has: `id`, `start_id`, `end_id`, `properties`.

### Pure SQL Approach

Instead of:
```sql
SELECT * FROM ag_catalog.cypher('discogsography', $$
    MATCH (a:Artist {name: $name})
    RETURN a.id, a.name, COUNT { MATCH (r:Release)-[:BY]->(a) RETURN DISTINCT r } AS release_count
$$) AS (id agtype, name agtype, release_count agtype)
```

Write pure SQL against the internal tables:
```sql
-- Explore center-node: Artist with release count, label count, alias count
SELECT
    a.properties->>'id' AS id,
    a.properties->>'name' AS name,
    COALESCE(rel.release_count, 0) AS release_count,
    COALESCE(lbl.label_count, 0) AS label_count,
    COALESCE(als.alias_count, 0) AS alias_count
FROM discogsography."Artist" a
LEFT JOIN LATERAL (
    SELECT count(DISTINCT b.start_id) AS release_count
    FROM discogsography."BY" b
    WHERE b.end_id = a.id
) rel ON true
LEFT JOIN LATERAL (
    SELECT count(DISTINCT o.end_id) AS label_count
    FROM discogsography."BY" b
    JOIN discogsography."ON" o ON o.start_id = b.start_id
    WHERE b.end_id = a.id
) lbl ON true
LEFT JOIN LATERAL (
    SELECT count(*) AS alias_count
    FROM (
        SELECT 1 FROM discogsography."ALIAS_OF" WHERE start_id = a.id
        UNION ALL
        SELECT 1 FROM discogsography."MEMBER_OF" WHERE start_id = a.id
        UNION ALL
        SELECT 1 FROM discogsography."MEMBER_OF" WHERE end_id = a.id
    ) x
) als ON true
WHERE a.properties->>'name' = $1;
```

### Fulltext Search via PostgreSQL Native

No Cypher fulltext procedures needed — use PostgreSQL's native full-text search directly:

```sql
-- Create tsvector index on AGE vertex table
CREATE INDEX artist_name_fts
    ON discogsography."Artist"
    USING GIN (to_tsvector('english', properties->>'name'));

-- Autocomplete query with ranking and highlighting
SELECT
    properties->>'id' AS id,
    properties->>'name' AS name,
    ts_rank(to_tsvector('english', properties->>'name'), query) AS score,
    ts_headline('english', properties->>'name', query) AS highlight
FROM discogsography."Artist",
     plainto_tsquery('english', $1) query
WHERE to_tsvector('english', properties->>'name') @@ query
ORDER BY score DESC
LIMIT $2;
```

This is more powerful than Neo4j's fulltext search — PostgreSQL supports configurable analyzers, stemming, synonyms, phrase search, and BM25-like ranking out of the box.

### Batch Writes via SQL

Instead of UNWIND/MERGE through Cypher, use PostgreSQL's `INSERT ... ON CONFLICT`:

```sql
-- Upsert artists (equivalent to UNWIND/MERGE)
INSERT INTO discogsography."Artist" (id, properties)
SELECT
    ag_catalog.graphid(label_id, data_id),
    ag_catalog.agtype_build_map(
        'id', artist->>'id',
        'name', artist->>'name',
        'sha256', artist->>'sha256'
    )
FROM jsonb_array_elements($1::jsonb) AS artist
ON CONFLICT (id) DO UPDATE
    SET properties = EXCLUDED.properties;
```

Or use PostgreSQL's `COPY` for bulk loading, which is significantly faster than any Cypher approach.

### Database Stats via SQL

```sql
-- Node and relationship counts
SELECT
    (SELECT count(*) FROM discogsography._ag_label_vertex) AS node_count,
    (SELECT count(*) FROM discogsography._ag_label_edge) AS rel_count;

-- Version info
SELECT version() AS pg_version,
       (SELECT extversion FROM pg_extension WHERE extname = 'age') AS age_version;

-- Per-label counts
SELECT label, count(*) FROM (
    SELECT 'Artist' AS label FROM discogsography."Artist"
    UNION ALL
    SELECT 'Release' FROM discogsography."Release"
    UNION ALL
    SELECT 'Label' FROM discogsography."Label"
) x GROUP BY label;
```

### What This Eliminates

| Incompatibility | Pure SQL Solution |
|----------------|-------------------|
| Cypher SQL wrapping | Not needed — query internal tables directly |
| COUNT {} subqueries | `LEFT JOIN LATERAL (SELECT count(...))` — standard SQL |
| Fulltext search | PostgreSQL `tsvector` / `tsquery` with GIN indexes |
| Return column declaration | Standard SQL `SELECT` — no `AS (col type, ...)` needed |
| Schema DDL | Standard PostgreSQL `CREATE INDEX`, `ALTER TABLE` |
| Stats/monitoring | Standard PostgreSQL system catalogs |
| Async support | psycopg3 `AsyncConnection` — fully supported, no AGE driver needed |

### Performance Implications

**Advantages of pure SQL:**
- PostgreSQL's query planner optimizes JOIN order, index usage, and parallel execution
- `LATERAL` subqueries are well-optimized in PostgreSQL 18
- `INSERT ... ON CONFLICT` is faster than Cypher MERGE for bulk operations
- `COPY` command for bulk loading is orders of magnitude faster
- Full access to PostgreSQL's `EXPLAIN ANALYZE` for query tuning

**Concerns:**
- Graph traversals become JOIN chains — deep traversals (3+ hops) produce complex multi-way JOINs
- No index-free adjacency — each hop requires an index lookup on edge tables
- AGE internal table structure may change between versions (not a stable API)
- Properties are stored as `agtype` (JSON-like) — property access requires `->>`  extraction

### Recommended Hybrid Approach

| Query Type | Approach | Why |
|-----------|----------|-----|
| Batch writes | **Pure SQL** (`INSERT ... ON CONFLICT` or `COPY`) | Much faster than Cypher MERGE |
| Fulltext search | **Pure SQL** (tsvector/tsquery) | More powerful than any Cypher fulltext |
| Center-node counts | **Pure SQL** (LATERAL subqueries) | Eliminates COUNT {} incompatibility |
| Stats/monitoring | **Pure SQL** (system catalogs) | Standard PostgreSQL |
| Schema init | **Pure SQL** (CREATE INDEX, etc.) | Standard PostgreSQL DDL |
| 1-2 hop traversals | **Either** SQL or Cypher | Both work well for shallow traversals |
| Deep traversals (3+ hops) | **Cypher** via `ag_catalog.cypher()` | Graph pattern matching is more readable |
| Gap analysis | **Cypher** via `ag_catalog.cypher()` | Exclusion patterns are cleaner in Cypher |

The most performant approach uses **Cypher for graph pattern matching** (traversals, path finding) and **pure SQL for everything else** (fulltext, aggregation, batch writes, stats).

### Additional Work Items (Native SQL Approach)

- [ ] Map AGE internal table names for all 7 node labels and 11 relationship types
- [ ] Create PostgreSQL tsvector indexes on AGE vertex tables (5 indexes)
- [ ] Rewrite 4 autocomplete queries as pure SQL with `ts_rank` / `ts_headline`
- [ ] Rewrite 4 center-node queries as pure SQL with `LATERAL` subqueries
- [ ] Rewrite batch write queries as `INSERT ... ON CONFLICT` (4 entity types + relationships)
- [ ] Implement stats/version as pure SQL against system catalogs
- [ ] Test `COPY` for initial bulk load performance
- [ ] Benchmark pure SQL traversal (JOINs) vs Cypher traversal for 1, 2, and 3 hop depths
- [ ] Verify AGE internal table schema stability across AGE versions
- [ ] Create integration tests verifying SQL and Cypher produce identical results

## Docker Setup

AGE runs as a PostgreSQL extension. Two options:

### Option A: Add Extension to Existing PostgreSQL Container

```dockerfile
# Dockerfile.postgres-age
FROM postgres:18
RUN apt-get update && apt-get install -y \
    postgresql-18-age \
    && rm -rf /var/lib/apt/lists/*
```

```yaml
# docker-compose.yml — replace postgres image
postgres:
  build:
    context: .
    dockerfile: Dockerfile.postgres-age
  # ... existing postgres config unchanged
```

### Option B: Use Official AGE Docker Image

```yaml
# docker-compose.yml — benchmark profile
postgres-age:
  image: apache/age:latest
  profiles: ["age"]
  environment:
    POSTGRES_PASSWORD: discogsography
    POSTGRES_DB: discogsography
  ports:
    - "5434:5432"    # Different host port
  volumes:
    - age_data:/var/lib/postgresql/data
```

## AGE Backend Implementation

```python
# common/age_backend.py
import psycopg  # psycopg3
from common.graph_backend import GraphBackend

class AGEBackend(GraphBackend):
    async def connect(self, uri, auth, **kwargs):
        self._conn = await psycopg.AsyncConnection.connect(
            host=uri, user=auth[0], password=auth[1],
            dbname="discogsography", autocommit=False,
        )
        # Load AGE extension
        async with self._conn.cursor() as cur:
            await cur.execute("LOAD 'age'")
            await cur.execute("SET search_path = ag_catalog, '$user', public")

    async def execute_read(self, query, params=None):
        async with self._conn.cursor() as cur:
            await cur.execute(
                self._wrap_cypher(query),
                self._convert_params(params),
            )
            columns = [desc.name for desc in cur.description]
            return [dict(zip(columns, row)) for row in await cur.fetchall()]

    def _wrap_cypher(self, cypher: str) -> str:
        """Wrap a Cypher query in ag_catalog.cypher() SQL call."""
        # This needs return column inference or explicit declaration
        return f"SELECT * FROM ag_catalog.cypher('discogsography', $$ {cypher} $$) AS ..."

    def fulltext_search_query(self, index_name, query_param):
        # AGE doesn't have fulltext — delegate to PostgreSQL tsvector
        raise NotImplementedError("Use PostgreSQL tsvector for fulltext search")

    def stats_query(self):
        return "SELECT count(*) FROM discogsography._ag_label_vertex"

    def version_query(self):
        return "SELECT extversion FROM pg_extension WHERE extname = 'age'"

    def get_schema_statements(self):
        return [
            "LOAD 'age'",
            "SET search_path = ag_catalog, '$user', public",
            "SELECT * FROM ag_catalog.create_graph('discogsography')",
            # Labels are created implicitly on first MERGE
            # Indexes created as PostgreSQL DDL on internal tables
        ]
```

## Work Items (AGE-Specific)

Prerequisites: Complete [shared pre-work](shared-pre-work.md) first.

- [ ] Build or source a PostgreSQL 18 + AGE Docker image
- [ ] Implement `common/age_backend.py` with psycopg3 async
- [ ] Solve the return-column declaration problem (AGE requires `AS (col type, ...)` in SQL wrapper)
- [ ] Wrap all ~50 Cypher queries in `ag_catalog.cypher()` SQL calls
- [ ] Rewrite 4 COUNT subquery queries as `OPTIONAL MATCH` + `count()` aggregation
- [ ] Implement fulltext search as pure PostgreSQL tsvector (bypass graph layer)
- [ ] Implement schema init as PostgreSQL DDL (indexes on AGE internal tables)
- [ ] Implement stats/version queries using PostgreSQL system catalogs
- [ ] Test UNWIND/MERGE batch writes at scale (100, 500, 1000 batch sizes)
- [ ] Test deep traversal queries (3+ hops) for performance vs Neo4j
- [ ] Test hybrid SQL+Cypher queries (unique value proposition)
- [ ] Run full benchmark suite and compare with Neo4j baseline
- [ ] Document memory usage and disk usage after full data load

## Decision Criteria

Proceed with Apache AGE if:

- [ ] Batch MERGE/UNWIND throughput is within 50% of Neo4j (infrastructure savings compensate)
- [ ] Read query latency p95 is acceptable for the explore/expand patterns
- [ ] Deep traversals (3+ hops) don't degrade significantly
- [ ] Hybrid SQL+Cypher queries provide measurable value
- [ ] The async psycopg3 approach works reliably for the AGE extension
- [ ] AGE extension is stable on PostgreSQL 18 under concurrent read/write load
- [ ] Total infrastructure cost savings justify the migration effort
