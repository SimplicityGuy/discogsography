# Memgraph as Neo4j Alternative — Investigation Notes

## Overview

[Memgraph](https://memgraph.com/) is an in-memory graph database that supports the Bolt protocol and Cypher query language. It positions itself as a drop-in replacement for Neo4j, and uses the same [Neo4j Python driver](https://memgraph.com/docs/client-libraries/python) (`pip install neo4j`) for client connectivity.

This document captures compatibility findings, known risks, and a benchmarking plan for evaluating Memgraph Community Edition against the current Neo4j 2026 Community deployment.

## Compatibility Summary

### What Works As-Is

The Neo4j Python driver (`AsyncGraphDatabase`, `GraphDatabase`) connects to Memgraph over Bolt with no code changes. The following Cypher features used throughout the codebase are fully supported:

- `UNWIND` / `MERGE ... SET` — batch write pattern (graphinator)
- `OPTIONAL MATCH` — used heavily in node detail and user queries
- `WITH` clause chaining — used in multi-step aggregation queries
- `SKIP` / `LIMIT` — pagination in expand and collection queries
- `CASE WHEN ... ELSE ... END` — conditional year handling
- `collect(DISTINCT x)` — aggregation in node detail queries
- `count(DISTINCT x)` — used in expand count queries
- Parameterized queries (`$name`, `$id`, `$limit`, `$offset`)
- `execute_write()` / `execute_read()` managed transactions
- Connection pooling, async sessions, circuit breaker / retry logic

The resilient driver wrapper (`common/neo4j_resilient.py`) should work without modification.

### Breaking Incompatibilities

Six areas require query or schema adaptation:

#### 1. COUNT {} Subqueries (Cypher 5.0+)

**Status:** Not supported in Memgraph.

The explore center-node queries in `api/queries/neo4j_queries.py` use `COUNT { MATCH ... }` subquery expressions:

```cypher
-- Neo4j (current)
MATCH (a:Artist {name: $name})
RETURN a.id AS id, a.name AS name,
       COUNT { MATCH (r:Release)-[:BY]->(a) RETURN DISTINCT r } AS release_count

-- Memgraph (rewrite required)
MATCH (a:Artist {name: $name})
OPTIONAL MATCH (r:Release)-[:BY]->(a)
WITH a, count(DISTINCT r) AS release_count
RETURN a.id AS id, a.name AS name, release_count
```

**Affected files:** `api/queries/neo4j_queries.py` — all 4 explore center-node queries (artist, genre, label, style).

#### 2. Fulltext Index DDL

**Status:** Different syntax.

```cypher
-- Neo4j
CREATE FULLTEXT INDEX artist_name_fulltext IF NOT EXISTS
  FOR (n:Artist) ON EACH [n.name]

-- Memgraph
CREATE TEXT INDEX artist_name_fulltext ON :Artist(name)
```

**Affected files:** `schema-init/neo4j_schema.py` — 5 fulltext index statements.

#### 3. Fulltext Search Queries

**Status:** Different procedure name and query format.

```cypher
-- Neo4j
CALL db.index.fulltext.queryNodes('artist_name_fulltext', $query)
YIELD node, score
RETURN node.id AS id, node.name AS name, score

-- Memgraph
CALL text_search.search('artist_name_fulltext', 'name:' + $query)
YIELD node, score
RETURN node.id AS id, node.name AS name, score
```

**Affected files:** `api/queries/neo4j_queries.py` — 4 autocomplete queries (artist, label, genre, style).

#### 4. Constraint DDL

**Status:** Different syntax, no `IF NOT EXISTS`.

```cypher
-- Neo4j
CREATE CONSTRAINT artist_id IF NOT EXISTS
  FOR (a:Artist) REQUIRE a.id IS UNIQUE

-- Memgraph
CREATE CONSTRAINT ON (a:Artist) ASSERT a.id IS UNIQUE
```

Memgraph does not support `IF NOT EXISTS` — schema init must handle "already exists" errors gracefully or check existing constraints before creating.

**Affected files:** `schema-init/neo4j_schema.py` — 7 constraint statements.

#### 5. Range Index DDL

**Status:** Different syntax, no named indexes, no `IF NOT EXISTS`.

```cypher
-- Neo4j
CREATE INDEX artist_sha256 IF NOT EXISTS FOR (a:Artist) ON (a.sha256)

-- Memgraph
CREATE INDEX ON :Artist(sha256)
```

**Affected files:** `schema-init/neo4j_schema.py` — 8 range index statements.

#### 6. Database Statistics / Monitoring

**Status:** Different commands.

```cypher
-- Neo4j
CALL apoc.meta.stats()      -- returns nodeCount, relCount
CALL dbms.components()       -- returns version info

-- Memgraph
SHOW STORAGE INFO            -- returns vertex_count, edge_count
SHOW VERSION                 -- returns version string
```

**Affected files:** `dashboard/dashboard.py` — monitoring queries.

## Known Memgraph Issues Relevant to Discogsography

The following open issues in the [memgraph/memgraph](https://github.com/memgraph/memgraph) repository are relevant to this project's workload:

| Issue                                                                          | Description                                                                         | Risk to Discogsography                                                                                                                        |
| ------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| [#3737, #3736, #3735, #3734](https://github.com/memgraph/memgraph/issues/3737) | Inconsistent query results — different Cypher formulations return different outputs | High — complex queries with multiple `OPTIONAL MATCH` + `collect(DISTINCT ...)` patterns (node details, user queries) could return wrong data |
| [#3825](https://github.com/memgraph/memgraph/issues/3825)                      | Text indexes don't support list-of-strings properties                               | Medium — `Release.formats` is stored as an array; text search on it won't work                                                                |
| [#3782](https://github.com/memgraph/memgraph/issues/3782)                      | Thread pool leak on high-core systems (127 threads per complex query)               | Medium — batch processing under load could exhaust resources                                                                                  |
| [#3785](https://github.com/memgraph/memgraph/issues/3785)                      | SIGSEGV crash on startup with corrupted RocksDB MANIFEST                            | Medium — durability concern for production restarts                                                                                           |
| [#3781](https://github.com/memgraph/memgraph/issues/3781)                      | Fine-grained auth queries take 32s in HA mode                                       | Low — only affects HA deployments with auth                                                                                                   |

The query result inconsistency issues (#3734–#3737) are the most concerning. The Discogsography query patterns heavily use `OPTIONAL MATCH` chains with `collect(DISTINCT ...)` and `WITH` clause aggregation — exactly the patterns where these bugs manifest.

## Memory Requirements

Memgraph is an **in-memory-first** database. The entire graph must fit in RAM. Key considerations:

- The Discogs dataset produces ~20M+ nodes and relationships
- Current Neo4j is configured for 2G heap + 1G page cache = ~3G total
- Memgraph will likely need significantly more RAM since the full graph lives in memory
- Use `SHOW STORAGE INFO` after loading a representative dataset to measure actual memory usage
- Cold start time will be longer — Memgraph must load the entire graph from disk snapshots into RAM

## Native Query Alternative: Custom Python Query Modules

Instead of adapting Cypher queries to work around Memgraph's openCypher gaps, Memgraph offers a **custom query module system** that lets you write server-side procedures in Python (or C/C++/Rust). These procedures access the graph natively via the `mgp` API and are callable from Cypher via `CALL`.

### How It Works

Custom modules are Python files placed in Memgraph's query modules directory. They use the `mgp` (Memgraph Graph Processing) API:

```python
# /usr/lib/memgraph/query_modules/discogsography.py
import mgp

@mgp.read_proc
def artist_center_node(
    ctx: mgp.ProcCtx,
    name: str,
) -> mgp.Record(
    id=str, name=str, release_count=int, label_count=int, alias_count=int
):
    """Replaces the COUNT {} subquery explore center-node query."""
    releases = set()
    labels = set()
    aliases = 0

    for vertex in ctx.graph.vertices:
        if vertex.labels and "Artist" in [str(l) for l in vertex.labels]:
            if vertex.properties.get("name") == name:
                # Count releases via outgoing BY relationships
                for edge in vertex.in_edges:
                    if edge.type == "BY":
                        releases.add(edge.from_vertex)
                        # Count labels on those releases
                        for rel_edge in edge.from_vertex.out_edges:
                            if rel_edge.type == "ON":
                                labels.add(rel_edge.to_vertex)
                # Count aliases and memberships
                for edge in vertex.out_edges:
                    if edge.type in ("ALIAS_OF", "MEMBER_OF"):
                        aliases += 1
                for edge in vertex.in_edges:
                    if edge.type == "MEMBER_OF":
                        aliases += 1

                return mgp.Record(
                    id=str(vertex.properties.get("id", "")),
                    name=name,
                    release_count=len(releases),
                    label_count=len(labels),
                    alias_count=aliases,
                )

    return mgp.Record(id="", name=name, release_count=0, label_count=0, alias_count=0)
```

Called from Cypher:

```cypher
CALL discogsography.artist_center_node('Radiohead')
YIELD id, name, release_count, label_count, alias_count
```

### What This Eliminates

| Incompatibility     | Native Solution                                                                   |
| ------------------- | --------------------------------------------------------------------------------- |
| COUNT {} subqueries | Custom `@mgp.read_proc` procedures that traverse and count natively               |
| Fulltext search     | Custom procedure wrapping `text_search.search()` with consistent return shape     |
| Database stats      | Custom procedure using `ctx.graph.vertices` count + Memgraph internals            |
| Schema idempotency  | Custom `@mgp.write_proc` that checks existing constraints/indexes before creating |

### Performance Considerations

The `mgp` API iterates vertices/edges in Python — this is **slower than Cypher** for simple queries because Memgraph's query engine is optimized C++. Custom modules make sense for:

- Queries that **cannot be expressed** in Memgraph's Cypher (COUNT subqueries)
- Complex multi-step logic that would require multiple round-trips
- Operations that need procedural control flow (idempotent schema init)

For queries that **can** be expressed in Memgraph's Cypher (UNWIND/MERGE, OPTIONAL MATCH, aggregation), native Cypher will be faster.

### Recommended Hybrid Approach

| Query Type                                 | Approach                                                    | Why                                  |
| ------------------------------------------ | ----------------------------------------------------------- | ------------------------------------ |
| Batch writes (UNWIND/MERGE)                | Memgraph Cypher                                             | Fully supported, engine-optimized    |
| Expand/pagination queries                  | Memgraph Cypher                                             | Standard Cypher, no gaps             |
| Trends/aggregation queries                 | Memgraph Cypher                                             | Standard Cypher, no gaps             |
| User collection/wantlist                   | Memgraph Cypher                                             | Standard Cypher, no gaps             |
| **Explore center-node (COUNT subqueries)** | **Custom `@mgp.read_proc`**                                 | COUNT {} not supported               |
| **Autocomplete (fulltext search)**         | **Custom `@mgp.read_proc`** wrapping `text_search.search()` | Normalize return format              |
| **Schema init**                            | **Custom `@mgp.write_proc`**                                | Idempotent constraint/index creation |
| **Dashboard stats**                        | **Custom `@mgp.read_proc`**                                 | Wraps `SHOW STORAGE INFO` parsing    |

### Additional Work Items (Native Approach)

- [ ] Create `query_modules/discogsography.py` with 4 center-node procedures (artist, genre, label, style)
- [ ] Create fulltext search wrapper procedure with consistent YIELD signature
- [ ] Create schema init procedure with idempotent constraint/index creation
- [ ] Create stats procedure returning `{node_count, rel_count, version}`
- [ ] Mount query module file into Memgraph container via Docker volume
- [ ] Call `CALL mg.load_all()` after deploying module changes
- [ ] Benchmark native procedures vs Cypher rewrites for the COUNT subquery patterns
- [ ] Test `@mgp.write_proc` for schema init atomicity

## Benchmarking

See [shared-pre-work.md](shared-pre-work.md) for the benchmark harness, workload definitions, metrics, and Docker Compose profiles shared across all candidates.

Benchmarks use synthetic data inserted directly into each database via the `GraphBackend` abstraction — no extractor or graphinator changes needed. Two scale points (`small` ~135k nodes/~540k relationships and `large` ~1.35M nodes/~5.4M relationships) provide enough signal to understand approximate orders of magnitude of performance differences.

### Docker Setup

```yaml
memgraph:
  image: memgraph/memgraph:latest
  profiles: ["memgraph"]
  ports:
    - "7688:7687"
  command: ["--bolt-server-name-for-init=Neo4j/5.2.0"]
  volumes:
    - memgraph_data:/var/lib/memgraph
```

The `--bolt-server-name-for-init=Neo4j/5.2.0` flag is required for Neo4j driver compatibility with Memgraph versions < 2.11.

### Memgraph-Specific Benchmarks

In addition to the shared workloads:

| Benchmark                | Why It Matters for Memgraph                             |
| ------------------------ | ------------------------------------------------------- |
| Cold start time          | Must load entire graph from disk snapshots into RAM     |
| Memory usage at scale    | In-memory-first — 20M+ nodes must fit in RAM            |
| Query result consistency | Verify #3734–#3737 bugs don't affect our query patterns |
| Durability overhead      | RocksDB snapshot frequency vs write throughput tradeoff |

### Execution

```bash
docker compose --profile memgraph up memgraph -d

# Synthetic data benchmarks at both scale points
uv run python -m investigations.benchmark.runner --backend memgraph --host localhost:7688 --scale small --load
uv run python -m investigations.benchmark.runner --backend memgraph --host localhost:7688 --scale small
uv run python -m investigations.benchmark.runner --backend memgraph --host localhost:7688 --scale large --load
uv run python -m investigations.benchmark.runner --backend memgraph --host localhost:7688 --scale large

uv run python -m investigations.benchmark.compare investigations/results/neo4j_*.json investigations/results/memgraph_*.json
```

## Memgraph Backend Implementation

```python
# common/memgraph_backend.py
from common.graph_backend import GraphBackend
from neo4j import AsyncGraphDatabase

class MemgraphBackend(GraphBackend):
    """Memgraph backend using the same neo4j Python driver over Bolt."""

    async def connect(self, uri, auth, **kwargs):
        self._driver = AsyncGraphDatabase.driver(f"bolt://{uri}", auth=auth, **kwargs)

    async def execute_read(self, query, params=None):
        async with self._driver.session(database="memgraph") as session:
            result = await session.run(query, params or {})
            return [dict(record) async for record in result]

    async def execute_write_batch(self, queries):
        async with self._driver.session(database="memgraph") as session:
            async def batch(tx):
                for query, params in queries:
                    await tx.run(query, params)
            await session.execute_write(batch)

    def fulltext_search_query(self, index_name, query_param):
        return (
            f"CALL text_search.search('{index_name}', 'name:' + ${query_param}) "
            f"YIELD node, score"
        )

    def stats_query(self):
        return "SHOW STORAGE INFO"

    def version_query(self):
        return "SHOW VERSION"

    def get_schema_statements(self):
        return [
            # Constraints (no IF NOT EXISTS — handle errors)
            "CREATE CONSTRAINT ON (a:Artist) ASSERT a.id IS UNIQUE",
            "CREATE CONSTRAINT ON (l:Label) ASSERT l.id IS UNIQUE",
            "CREATE CONSTRAINT ON (m:Master) ASSERT m.id IS UNIQUE",
            "CREATE CONSTRAINT ON (r:Release) ASSERT r.id IS UNIQUE",
            "CREATE CONSTRAINT ON (g:Genre) ASSERT g.name IS UNIQUE",
            "CREATE CONSTRAINT ON (s:Style) ASSERT s.name IS UNIQUE",
            "CREATE CONSTRAINT ON (u:User) ASSERT u.id IS UNIQUE",
            # Label-property indexes
            "CREATE INDEX ON :Artist(sha256)",
            "CREATE INDEX ON :Label(sha256)",
            "CREATE INDEX ON :Master(sha256)",
            "CREATE INDEX ON :Release(sha256)",
            "CREATE INDEX ON :Artist(name)",
            "CREATE INDEX ON :Label(name)",
            "CREATE INDEX ON :Release(year)",
            # Text indexes
            "CREATE TEXT INDEX artist_name_fulltext ON :Artist(name)",
            "CREATE TEXT INDEX label_name_fulltext ON :Label(name)",
            "CREATE TEXT INDEX release_title_fulltext ON :Release(title)",
            "CREATE TEXT INDEX genre_name_fulltext ON :Genre(name)",
            "CREATE TEXT INDEX style_name_fulltext ON :Style(name)",
        ]
```

## Work Items (Memgraph-Specific)

Prerequisites: Complete [shared pre-work](shared-pre-work.md) first.

- [ ] Implement `common/memgraph_backend.py` using the `neo4j` Python driver
- [ ] Rewrite 4 COUNT subquery queries as `OPTIONAL MATCH` + `count()` aggregation
- [ ] Adapt fulltext index creation to `CREATE TEXT INDEX` syntax
- [ ] Adapt fulltext search queries to `text_search.search()` procedure
- [ ] Adapt constraint creation (no `IF NOT EXISTS` — wrap in try/except)
- [ ] Adapt index creation (unnamed, no `IF NOT EXISTS`)
- [ ] Implement stats/version using `SHOW STORAGE INFO` / `SHOW VERSION`
- [ ] Verify query result consistency for `OPTIONAL MATCH` + `collect(DISTINCT ...)` patterns
- [ ] Measure RAM usage after loading full test dataset
- [ ] Measure cold start time (snapshot load into memory)
- [ ] Run full benchmark suite and compare with Neo4j baseline

## Decision Criteria

Proceed with Memgraph adoption if:

- [ ] Batch write throughput is measurably better (>2x) for the UNWIND/MERGE pattern
- [ ] Read query latency p95 is equal or better
- [ ] Fulltext search latency is comparable
- [ ] Memory requirements are acceptable for the full dataset (~20M nodes)
- [ ] Query result consistency issues (#3734–#3737) do not affect Discogsography query patterns
- [ ] Cold start time is acceptable for production restarts
- [ ] The 6 incompatibility rewrites are straightforward and pass existing tests
