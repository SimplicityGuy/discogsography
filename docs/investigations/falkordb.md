# FalkorDB — Redis-Based Graph Database

## Overview

[FalkorDB](https://github.com/FalkorDB/FalkorDB) is an ultra-fast graph database that runs as a Redis module. It uses sparse matrices (GraphBLAS) for adjacency representation and linear algebra for query execution — an architecturally different approach from both Neo4j (native graph storage) and Memgraph (in-memory native).

- **Repository:** [FalkorDB/FalkorDB](https://github.com/FalkorDB/FalkorDB) (3.7k stars)
- **License:** SSPLv1 (Server Side Public License — same model as MongoDB)
- **Requires:** Redis 7.4+
- **Python driver:** `falkordb` package (sync + async)
- **Query language:** openCypher with extensions

## Why This Is Interesting for Discogsography

- **Redis integration** — Discogsography already runs Redis for caching, OAuth state, snapshots, and JWT revocation. Graph data could live in the same Redis instance or a dedicated one.
- **Sparse matrix engine** — GraphBLAS-based adjacency representation could outperform Neo4j for specific access patterns (batch writes, neighborhood queries).
- **Low latency** — designed for sub-millisecond responses on graph queries.
- **openCypher** — most existing Cypher queries should work with minor adaptation.

## Compatibility Analysis

### Supported Cypher Features

FalkorDB implements openCypher with extensions:

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
- `CALL` procedure support

### Breaking Incompatibilities

#### 1. Driver Change

FalkorDB uses its own Python client, not the Neo4j driver:

```python
from falkordb import FalkorDB

# Synchronous
db = FalkorDB(host="localhost", port=6379)
graph = db.select_graph("discogsography")

# Write query
result = graph.query(
    "MERGE (a:Artist {id: $id}) SET a.name = $name",
    params={"id": "123", "name": "Radiohead"},
)

# Read-only query
result = graph.ro_query(
    "MATCH (a:Artist {name: $name}) RETURN a.id, a.name",
    params={"name": "Radiohead"},
)

for row in result.result_set:
    print(row)
```

```python
# Asynchronous
from falkordb.asyncio import FalkorDB as AsyncFalkorDB
from redis.asyncio import BlockingConnectionPool

pool = BlockingConnectionPool(max_connections=50, host="localhost", port=6379)
db = AsyncFalkorDB(connection_pool=pool)
graph = db.select_graph("discogsography")

result = await graph.query("MATCH (a:Artist {id: $id}) RETURN a", params={"id": "123"})
```

**Impact:** The entire driver layer (`common/neo4j_resilient.py`) must be reimplemented. The async client exists but uses `redis.asyncio` connection pooling, not Bolt.

#### 2. COUNT {} Subqueries

**Likely not supported** (openCypher spec does not include Cypher 5.0 subqueries). Rewrite as `OPTIONAL MATCH` + `count()` + `WITH`.

**Affected:** 4 explore center-node queries.

#### 3. Fulltext Index Syntax

FalkorDB has its own fulltext index implementation:

```cypher
-- FalkorDB fulltext index creation
CALL db.idx.fulltext.createNodeIndex('Artist', 'name')
CALL db.idx.fulltext.createNodeIndex('Label', 'name')
CALL db.idx.fulltext.createNodeIndex('Release', 'title')

-- FalkorDB fulltext query
CALL db.idx.fulltext.queryNodes('Artist', 'Radiohead')
YIELD node
RETURN node.id, node.name
```

The procedure name (`db.idx.fulltext`) differs from Neo4j (`db.index.fulltext`), and the index creation syntax differs, but the query pattern is similar.

**Affected:** 5 fulltext index creation statements, 4 autocomplete queries.

#### 4. Constraint Syntax

FalkorDB uses its own constraint syntax:

```cypher
-- FalkorDB
CREATE CONSTRAINT ON (a:Artist) ASSERT a.id IS UNIQUE

-- Neo4j
CREATE CONSTRAINT artist_id IF NOT EXISTS FOR (a:Artist) REQUIRE a.id IS UNIQUE
```

No `IF NOT EXISTS` support — schema init must handle idempotency.

**Affected:** 7 constraint statements.

#### 5. Index Syntax

```cypher
-- FalkorDB
CREATE INDEX FOR (a:Artist) ON (a.sha256)

-- Neo4j
CREATE INDEX artist_sha256 IF NOT EXISTS FOR (a:Artist) ON (a.sha256)
```

No named indexes, no `IF NOT EXISTS`.

**Affected:** 8 range index statements.

#### 6. Database Statistics / Monitoring

FalkorDB exposes graph info through Redis commands:

```python
# Graph info via Redis
graph.query("CALL db.labels()")     # List all labels
graph.query("CALL db.propertyKeys()")  # List all property keys

# Node/relationship counts
graph.query("MATCH (n) RETURN count(n)")
graph.query("MATCH ()-[r]->() RETURN count(r)")

# Redis-level stats
import redis
r = redis.Redis()
r.info("memory")    # Memory usage
r.info("server")    # Version info
```

**Affected:** Dashboard monitoring queries.

#### 7. Transaction Model

FalkorDB uses Redis's single-threaded execution model. Write queries are atomic but there are no multi-statement transactions in the Neo4j sense:

```python
# Neo4j: multiple queries in one transaction
async def batch(tx):
    await tx.run(query1, params1)
    await tx.run(query2, params2)
await session.execute_write(batch)

# FalkorDB: each query() call is its own atomic operation
# Multi-statement "transactions" require MULTI/EXEC Redis commands
# or combining operations into a single Cypher query
```

This is a significant architectural difference. The graphinator batch processor runs 4–6 Cypher statements per transaction. In FalkorDB, these would either need to be combined into fewer, larger queries or wrapped in Redis MULTI/EXEC blocks.

**Affected:** `graphinator/batch_processor.py` — batch transaction logic.

### Compatibility Summary

| Feature | Neo4j | FalkorDB | Adaptation |
|---------|-------|----------|------------|
| Cypher queries | Native | openCypher | Minor syntax adjustments |
| UNWIND / MERGE | Native | Supported | Works as-is |
| OPTIONAL MATCH | Native | Supported | Works as-is |
| COUNT {} subqueries | Supported | Not supported | Rewrite as aggregation |
| Fulltext search | `db.index.fulltext.queryNodes()` | `db.idx.fulltext.queryNodes()` | Different procedure name |
| Constraints | Cypher DDL with IF NOT EXISTS | Different syntax, no IF NOT EXISTS | Idempotency handling |
| Driver | `neo4j` (Bolt, async) | `falkordb` (Redis protocol, async) | Complete driver change |
| Multi-statement tx | `execute_write()` with callback | Redis MULTI/EXEC or single queries | Batch processor rework |
| Stats/monitoring | APOC procedures | Redis INFO + Cypher procedures | Reimplemented |
| Connection protocol | Bolt (7687) | Redis (6379) | Different protocol |

## Performance Considerations

### Advantages

- **Sparse matrix operations** — GraphBLAS-accelerated adjacency traversal could be very fast for neighborhood queries
- **In-memory with persistence** — Redis RDB/AOF persistence with in-memory query execution
- **Low overhead** — no JVM (unlike Neo4j), C implementation
- **Batch-friendly** — sparse matrix updates can be efficient for bulk operations

### Concerns

- **Single-threaded execution** — Redis is single-threaded; complex queries block other operations
- **No multi-statement transactions** — batch processor architecture needs rethinking
- **Memory** — all data in memory (Redis model); 20M+ nodes needs significant RAM
- **SSPLv1 license** — more restrictive than Apache 2.0 or GPL; may affect deployment options
- **Smaller ecosystem** — fewer production references, smaller community than Neo4j or Memgraph

### What to Benchmark Specifically

In addition to the [shared workloads](shared-pre-work.md#workload-definitions):

| Benchmark | Why It Matters for FalkorDB |
|-----------|---------------------------|
| Single-threaded throughput ceiling | Redis is single-threaded — what's the max ops/sec for mixed workloads? |
| Large UNWIND batches | How does sparse matrix update scale with batch size? |
| Multi-query "transaction" | Compare Redis MULTI/EXEC vs Neo4j execute_write for 6-query batches |
| Memory usage vs dataset size | Critical — all data in Redis memory |
| Persistence overhead | RDB/AOF impact on write throughput |
| Concurrent readers | Read replicas or single-instance bottleneck? |

## Native Query Alternative: Redis Commands + Consolidated Cypher

FalkorDB exposes two native layers below Cypher: **Redis commands** for graph-level operations and **built-in procedures** for metadata/search. Additionally, many Cypher incompatibilities can be eliminated by consolidating multi-statement transactions into single queries.

### Redis Command API

FalkorDB is a Redis module. All graph operations ultimately execute as Redis commands:

```bash
# Direct Redis commands (via redis-cli or redis-py)
GRAPH.QUERY discogsography "MATCH (a:Artist {id: '123'}) RETURN a"
GRAPH.RO_QUERY discogsography "MATCH (a:Artist {name: 'Radiohead'}) RETURN a"
GRAPH.DELETE discogsography
GRAPH.LIST
GRAPH.EXPLAIN discogsography "MATCH (a:Artist) RETURN a"
GRAPH.PROFILE discogsography "MATCH (a:Artist) RETURN a"
GRAPH.SLOWLOG discogsography
GRAPH.INFO discogsography
```

The Python client wraps these, but you can also use `redis-py` directly for lower-level control:

```python
import redis.asyncio as aioredis

r = aioredis.Redis(host="localhost", port=6379)

# Execute graph query via raw Redis command
result = await r.execute_command(
    "GRAPH.QUERY", "discogsography",
    "MATCH (a:Artist {name: $name}) RETURN a.id, a.name",
    "--compact", "name", "Radiohead"
)

# Schema operations via Redis commands
await r.execute_command(
    "GRAPH.CONSTRAINT", "CREATE", "discogsography",
    "UNIQUE", "NODE", "Artist", "PROPERTIES", "1", "id"
)

# Memory and stats via Redis commands
memory_info = await r.execute_command("GRAPH.MEMORY", "USAGE", "discogsography")
info = await r.info("server")  # Redis version, uptime, etc.
```

### Solving the Multi-Statement Transaction Problem

The biggest FalkorDB incompatibility is the lack of multi-statement transactions (graphinator runs 4–6 queries per batch). Two native approaches solve this:

#### Approach A: Consolidated Single-Query Batches

Combine multiple MERGE statements into a single query using `WITH` chaining:

```cypher
-- Instead of 6 separate queries in a transaction, one query:
UNWIND $releases AS release
MERGE (r:Release {id: release.id})
SET r.title = release.title, r.year = release.year, r.sha256 = release.sha256
WITH r, release
UNWIND release.artists AS artist_id
MERGE (a:Artist {id: artist_id})
MERGE (r)-[:BY]->(a)
WITH r, release
UNWIND release.labels AS label_id
MERGE (l:Label {id: label_id})
MERGE (r)-[:ON]->(l)
WITH r, release
WHERE release.master_id IS NOT NULL
MERGE (m:Master {id: release.master_id})
MERGE (r)-[:DERIVED_FROM]->(m)
```

This is a single atomic operation — no multi-statement transaction needed.

**Trade-off:** The query is more complex and may use more memory during execution (all UNWINDs buffered). Needs benchmarking at batch sizes >100.

#### Approach B: Redis MULTI/EXEC

Wrap multiple GRAPH.QUERY commands in a Redis transaction:

```python
async def batch_write(redis: aioredis.Redis, queries: list[tuple[str, dict]]):
    pipe = redis.pipeline(transaction=True)  # MULTI
    for query, params in queries:
        # Build parameterized query string
        param_str = " ".join(f"{k}={format_value(v)}" for k, v in params.items())
        pipe.execute_command(
            "GRAPH.QUERY", "discogsography",
            f"CYPHER {param_str} {query}"
        )
    results = await pipe.execute()  # EXEC
    return results
```

**Trade-off:** Redis MULTI/EXEC provides atomicity (all-or-nothing) but not isolation — other clients can observe intermediate states between commands within the MULTI block. For the graphinator use case (idempotent MERGE), this is acceptable.

### Fulltext Search via Built-in Procedures

FalkorDB has its own fulltext procedures that are close to Neo4j's but with slightly different names:

```cypher
-- Create fulltext index (built-in procedure)
CALL db.idx.fulltext.createNodeIndex('Artist', 'name')
CALL db.idx.fulltext.createNodeIndex({label: 'Artist', stopwords: ['the', 'a']}, 'name')

-- Query fulltext index
CALL db.idx.fulltext.queryNodes('Artist', 'radiohead')
YIELD node
RETURN node.id AS id, node.name AS name

-- Drop fulltext index
CALL db.idx.fulltext.drop('Artist')
```

The key difference from Neo4j: FalkorDB indexes by **label name** rather than by a custom index name. The `YIELD` clause returns `node` but not `score` by default.

### COUNT Subquery Workaround via CALL Subquery

FalkorDB supports `CALL {}` subqueries (unlike Memgraph), which can replace COUNT {} subqueries:

```cypher
-- FalkorDB CALL subquery approach
MATCH (a:Artist {name: $name})
CALL {
    WITH a
    MATCH (r:Release)-[:BY]->(a)
    RETURN count(DISTINCT r) AS release_count
}
CALL {
    WITH a
    MATCH (r:Release)-[:BY]->(a), (r)-[:ON]->(l:Label)
    RETURN count(DISTINCT l) AS label_count
}
RETURN a.id AS id, a.name AS name, release_count, label_count
```

If `CALL {}` subqueries work in FalkorDB, this eliminates the COUNT {} incompatibility entirely with minimal rewrite.

### Schema Management via Redis Commands

```python
# Create constraints via GRAPH.CONSTRAINT command
await r.execute_command(
    "GRAPH.CONSTRAINT", "CREATE", "discogsography",
    "UNIQUE", "NODE", "Artist", "PROPERTIES", "1", "id"
)

# List constraints
await r.execute_command("GRAPH.CONSTRAINT", "LIST", "discogsography")

# Create index via Cypher
await r.execute_command(
    "GRAPH.QUERY", "discogsography",
    "CREATE INDEX FOR (a:Artist) ON (a.sha256)"
)

# Graph info (node/edge counts, memory)
await r.execute_command("GRAPH.INFO", "discogsography")
memory = await r.execute_command("GRAPH.MEMORY", "USAGE", "discogsography")
```

### What This Eliminates

| Incompatibility | Native Solution |
|----------------|----------------|
| Multi-statement transactions | Consolidated single queries OR Redis MULTI/EXEC |
| COUNT {} subqueries | `CALL {}` subqueries (if supported) or pre-aggregation |
| Fulltext search | `db.idx.fulltext.queryNodes` — close to Neo4j, minor name difference |
| Schema idempotency | `GRAPH.CONSTRAINT CREATE` — Redis command, handle errors |
| Stats/monitoring | `GRAPH.INFO`, `GRAPH.MEMORY`, Redis `INFO` commands |
| Driver abstraction | `redis-py` async — mature, well-tested library |

### Recommended Hybrid Approach

| Query Type | Approach | Why |
|-----------|----------|-----|
| Batch writes | **Consolidated Cypher** (single query with WITH chaining) | Atomic, no transaction needed |
| Explore center-node | **CALL {} subqueries** (if supported) or pre-aggregation | Avoids COUNT {} gap |
| Fulltext search | **Built-in `db.idx.fulltext`** procedures | Native, close to Neo4j |
| Expand/pagination | **Standard Cypher** | Fully supported |
| Schema init | **Redis `GRAPH.CONSTRAINT`** commands | Idempotent, command-level |
| Stats/monitoring | **Redis commands** (`GRAPH.INFO`, `GRAPH.MEMORY`, `INFO`) | Native, no Cypher needed |
| All other reads | **Standard Cypher** via `GRAPH.RO_QUERY` | Fully supported |

### Additional Work Items (Native Approach)

- [ ] Verify `CALL {}` subquery support in FalkorDB (test with center-node query pattern)
- [ ] Prototype consolidated single-query batch writes with WITH chaining
- [ ] Benchmark consolidated query vs sequential queries for batch sizes 50, 100, 500
- [ ] Implement batch writer using `redis-py` MULTI/EXEC as fallback
- [ ] Implement schema init using `GRAPH.CONSTRAINT CREATE` Redis commands
- [ ] Implement stats collection using `GRAPH.INFO` and `GRAPH.MEMORY` Redis commands
- [ ] Test `db.idx.fulltext.queryNodes` return format (does it include score?)
- [ ] Create `redis-py` async backend as alternative to `falkordb` client

## Docker Setup

```yaml
# docker-compose.yml addition
falkordb:
  image: falkordb/falkordb:latest
  profiles: ["falkordb"]
  ports:
    - "6380:6379"     # Different host port to avoid conflict with existing Redis
  command: >
    --loadmodule /usr/lib/redis/modules/falkordb.so
    --save 60 1
    --appendonly yes
  volumes:
    - falkordb_data:/data
  healthcheck:
    test: ["CMD", "redis-cli", "ping"]
    interval: 10s
    timeout: 5s
    retries: 5
```

## FalkorDB Backend Implementation

```python
# common/falkordb_backend.py
from falkordb.asyncio import FalkorDB as AsyncFalkorDB
from redis.asyncio import BlockingConnectionPool
from common.graph_backend import GraphBackend

class FalkorDBBackend(GraphBackend):
    async def connect(self, uri, auth, **kwargs):
        host, port = uri.split(":")
        pool = BlockingConnectionPool(
            max_connections=kwargs.get("max_connections", 50),
            host=host, port=int(port),
            password=auth[1] if auth[1] else None,
        )
        self._db = AsyncFalkorDB(connection_pool=pool)
        self._graph = self._db.select_graph("discogsography")

    async def execute_read(self, query, params=None):
        result = await self._graph.ro_query(query, params=params or {})
        # Convert FalkorDB result_set to list[dict]
        return [dict(zip(result.header, row)) for row in result.result_set]

    async def execute_write(self, query, params=None):
        await self._graph.query(query, params=params or {})

    async def execute_write_batch(self, queries):
        # FalkorDB has no multi-statement transactions
        # Option 1: Execute sequentially (no atomicity guarantee)
        for query, params in queries:
            await self._graph.query(query, params=params)
        # Option 2: Use Redis MULTI/EXEC (needs investigation)

    def fulltext_search_query(self, index_name, query_param):
        # FalkorDB uses db.idx.fulltext (not db.index.fulltext)
        label = index_name.split("_")[0].capitalize()
        return (
            f"CALL db.idx.fulltext.queryNodes('{label}', ${query_param}) "
            f"YIELD node"
        )

    def stats_query(self):
        return "MATCH (n) RETURN count(n) AS node_count"

    def version_query(self):
        # Use Redis INFO command instead of Cypher
        return "CALL dbms.info()"

    def get_schema_statements(self):
        return [
            "CREATE CONSTRAINT ON (a:Artist) ASSERT a.id IS UNIQUE",
            "CREATE CONSTRAINT ON (l:Label) ASSERT l.id IS UNIQUE",
            "CREATE CONSTRAINT ON (m:Master) ASSERT m.id IS UNIQUE",
            "CREATE CONSTRAINT ON (r:Release) ASSERT r.id IS UNIQUE",
            "CREATE CONSTRAINT ON (g:Genre) ASSERT g.name IS UNIQUE",
            "CREATE CONSTRAINT ON (s:Style) ASSERT s.name IS UNIQUE",
            "CREATE CONSTRAINT ON (u:User) ASSERT u.id IS UNIQUE",
            "CREATE INDEX FOR (a:Artist) ON (a.sha256)",
            "CREATE INDEX FOR (l:Label) ON (l.sha256)",
            "CREATE INDEX FOR (m:Master) ON (m.sha256)",
            "CREATE INDEX FOR (r:Release) ON (r.sha256)",
            "CREATE INDEX FOR (a:Artist) ON (a.name)",
            "CREATE INDEX FOR (l:Label) ON (l.name)",
            "CREATE INDEX FOR (r:Release) ON (r.year)",
            "CALL db.idx.fulltext.createNodeIndex('Artist', 'name')",
            "CALL db.idx.fulltext.createNodeIndex('Label', 'name')",
            "CALL db.idx.fulltext.createNodeIndex('Release', 'title')",
            "CALL db.idx.fulltext.createNodeIndex('Genre', 'name')",
            "CALL db.idx.fulltext.createNodeIndex('Style', 'name')",
        ]
```

## Work Items (FalkorDB-Specific)

Prerequisites: Complete [shared pre-work](shared-pre-work.md) first.

- [ ] Verify Redis version compatibility (project currently runs Redis for caching — check version)
- [ ] Implement `common/falkordb_backend.py` with async `falkordb` client
- [ ] Investigate Redis MULTI/EXEC for multi-statement transaction support
- [ ] Rewrite 4 COUNT subquery queries as `OPTIONAL MATCH` + `count()` aggregation
- [ ] Adapt fulltext index creation (`db.idx.fulltext.createNodeIndex`)
- [ ] Adapt fulltext search queries (`db.idx.fulltext.queryNodes`)
- [ ] Implement constraint/index creation with idempotency handling (try/except for "already exists")
- [ ] Implement stats/version queries using Redis INFO + Cypher procedures
- [ ] Test batch write patterns — compare sequential query execution vs Redis MULTI/EXEC
- [ ] Test single-threaded throughput ceiling under concurrent load
- [ ] Measure memory usage after loading full test dataset
- [ ] Run full benchmark suite and compare with Neo4j baseline
- [ ] Evaluate SSPLv1 license implications for the project's deployment model

## Decision Criteria

Proceed with FalkorDB if:

- [ ] Query throughput is significantly better (>2x) than Neo4j for the workload mix
- [ ] The single-threaded execution model does not create a bottleneck under concurrent API + graphinator load
- [ ] A workable solution exists for multi-statement batch transactions (MULTI/EXEC or query consolidation)
- [ ] Memory requirements are acceptable for the full dataset (~20M nodes)
- [ ] SSPLv1 license is acceptable for the project's use case
- [ ] The smaller ecosystem and community do not pose an unacceptable support risk
- [ ] Fulltext search via `db.idx.fulltext` performs comparably to Neo4j's implementation
