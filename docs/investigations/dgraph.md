# Dgraph — Distributed Graph Database

## Overview

[Dgraph](https://github.com/dgraph-io/dgraph) is a horizontally scalable, distributed graph database with a custom query language (DQL) and native GraphQL support. Written in Go, it uses a predicate-centric data model rather than the labeled property graph model used by Neo4j.

- **Repository:** [dgraph-io/dgraph](https://github.com/dgraph-io/dgraph) (20k+ stars)
- **License:** Apache 2.0 (Community), Dgraph License (Enterprise features)
- **Latest activity:** Active development
- **Python driver:** `pydgraph` v25.x (Apache 2.0)
- **Query language:** DQL (Dgraph Query Language, formerly GraphQL+-)

## Why This Is Interesting for Discogsography

- **Natively distributed** — horizontal scaling with predicate-based sharding across Alpha nodes, unlike Neo4j's single-writer architecture
- **Built-in full-text search** — `alloftext()`/`anyoftext()` with stemming, no external index needed
- **ACID transactions** — distributed snapshot isolation across the cluster
- **Low memory footprint** — Go implementation, no JVM overhead
- **GraphQL endpoint** — native GraphQL API in addition to DQL, potentially useful for future frontend integrations
- **Shortest path built-in** — `shortest()` function for path finder features

## Critical Caveat: Complete Data Model Rewrite

Dgraph uses a **predicate-centric** model that is fundamentally different from Neo4j's labeled property graph:

- Predicates are global (a `name` predicate is shared across all types)
- Nodes don't have labels — they have `dgraph.type` predicates
- Relationships are UID predicates pointing to other nodes
- Edge properties use "facets" syntax, not first-class properties
- System-assigned UIDs; external IDs need `@upsert` predicates

### DQL vs Cypher — Side-by-Side

#### Basic Node Lookup

```cypher
-- Cypher (current)
MATCH (a:Artist {id: $id})
RETURN a.id, a.name
```

```dql
-- DQL equivalent
{
  results(func: eq(entity_id, $id)) @filter(type(Artist)) {
    id: entity_id
    name: name
  }
}
```

#### Multi-Hop Traversal

```cypher
-- Cypher
MATCH (r:Release)-[:BY]->(a:Artist {name: $name}), (r)-[:ON]->(l:Label)
RETURN l.id AS id, l.name AS name, count(DISTINCT r) AS release_count
ORDER BY release_count DESC
SKIP $offset LIMIT $limit
```

```dql
-- DQL (using reverse edges)
{
  var(func: eq(name, $name)) @filter(type(Artist)) {
    ~by {
      on {
        label_uid as uid
      }
    }
  }
  results(func: uid(label_uid), offset: $offset, first: $limit) {
    id: entity_id
    name: name
  }
}
```

#### Batch Upsert

```cypher
-- Cypher
UNWIND $artists AS artist
MERGE (a:Artist {id: artist.id})
SET a.name = artist.name, a.sha256 = artist.sha256
```

```dql
-- DQL (JSON mutation with upsert block)
upsert {
  query {
    v as var(func: eq(entity_id, "12345"))
  }
  mutation {
    set {
      uid(v) <entity_id> "12345" .
      uid(v) <name> "Aphex Twin" .
      uid(v) <sha256> "abc123" .
      uid(v) <dgraph.type> "Artist" .
    }
  }
}
```

#### Full-Text Search

```cypher
-- Cypher
CALL db.index.fulltext.queryNodes('artist_fulltext', $query)
YIELD node, score
RETURN node.id AS id, node.name AS name, score
LIMIT $limit
```

```dql
-- DQL
{
  results(func: alloftext(name, $query), first: $limit) @filter(type(Artist)) {
    id: entity_id
    name: name
  }
}
```

#### Aggregation

```cypher
-- Cypher
MATCH (r:Release)-[:BY]->(a:Artist {name: $name})
WHERE r.year > 0
WITH r.year AS year, count(DISTINCT r) AS count
RETURN year, count
ORDER BY year
```

```dql
-- DQL (value variables + groupby)
{
  var(func: eq(name, $name)) @filter(type(Artist)) {
    ~by @filter(gt(year, 0)) @groupby(year) {
      count(uid)
    }
  }
}
```

## Data Model Differences

### Neo4j Property Graph → Dgraph Predicate Model

```
Neo4j Nodes        → Dgraph Types (via dgraph.type predicate)
  :Artist          → type Artist { entity_id, name, sha256, ... }
  :Label           → type Label { entity_id, name, sha256, ... }
  :Master          → type Master { entity_id, name, sha256, year, ... }
  :Release         → type Release { entity_id, name, sha256, year, by, on, ... }
  :Genre           → type Genre { entity_id, name }
  :Style           → type Style { entity_id, name, part_of }

Neo4j Relationships → Dgraph Edge Predicates
  [:BY]            → by: [uid] @reverse @count
  [:ON]            → on: [uid] @reverse @count
  [:DERIVED_FROM]  → derived_from: [uid] @reverse @count
  [:IS] (genre)    → is_genre: [uid] @reverse @count
  [:IS] (style)    → is_style: [uid] @reverse @count
  [:MEMBER_OF]     → member_of: [uid] @reverse @count
  [:ALIAS_OF]      → alias_of: [uid] @reverse @count
  [:SUBLABEL_OF]   → sublabel_of: [uid] @reverse @count
  [:PART_OF]       → part_of: [uid] @reverse @count
```

Key differences:
- **Predicates are global** — `name` is shared across Artist, Label, Release, etc.
- **`@reverse` directive** — enables traversal in both directions without separate edge types
- **`@count` directive** — enables efficient `count()` on edge predicates
- **`@upsert` on `entity_id`** — enables find-or-create semantics for external IDs

## Compatibility Analysis

### What Translates Cleanly

| Concept                 | Cypher                       | DQL                                                  | Effort |
| ----------------------- | ---------------------------- | ---------------------------------------------------- | ------ |
| Node lookup by property | `MATCH (a:Artist {id: $id})` | `func: eq(entity_id, $id)) @filter(type(Artist))`   | Low    |
| Full-text search        | `db.index.fulltext.query...` | `func: alloftext(name, $query)`                      | Low    |
| Reverse traversal       | `(r)-[:BY]->(a)`            | `~by` (reverse edge)                                | Low    |
| Pagination              | `SKIP $offset LIMIT $limit`  | `offset: $offset, first: $limit`                     | Low    |
| Conditional upsert      | `MERGE ... SET`              | `upsert { query { ... } mutation { set { ... } } }`  | Medium |
| Batch mutation           | `UNWIND $items AS item`      | JSON array mutation                                  | Medium |

### What Requires Significant Rework

| Area                    | Why                                                  | Effort |
| ----------------------- | ---------------------------------------------------- | ------ |
| All ~50 Cypher queries  | DQL is a completely different language               | High   |
| Data model              | Predicate-centric vs labeled property graph          | High   |
| Aggregation patterns    | DQL uses value variables, not inline aggregation     | Medium |
| Edge properties         | Facets replace first-class relationship properties   | Medium |
| Driver layer            | `pydgraph` gRPC client replaces `neo4j` driver       | Medium |
| Two-process deployment  | Zero + Alpha vs single Neo4j process                 | Low    |

### Driver API

```python
import pydgraph
import json

# Sync connection via gRPC
client_stub = pydgraph.DgraphClientStub("localhost:9080")
client = pydgraph.DgraphClient(client_stub)

# Read query
txn = client.txn(read_only=True)
try:
    res = txn.query('{
      results(func: eq(name, "Radiohead")) @filter(type(Artist)) {
        entity_id
        name
      }
    }')
    data = json.loads(res.json)
finally:
    txn.discard()

# Write mutation (JSON)
txn = client.txn()
try:
    txn.mutate(set_obj={
        "dgraph.type": "Artist",
        "entity_id": "12345",
        "name": "Radiohead",
        "sha256": "abc123",
    }, commit_now=True)
finally:
    txn.discard()

# Schema management
op = pydgraph.Operation(schema="""
    entity_id: string @index(exact) @upsert .
    name: string @index(term, exact, fulltext, trigram) .
    type Artist { entity_id name sha256 }
""")
client.alter(op)
```

## Performance Considerations

### Advantages

- **Natively distributed** — predicate-based sharding means the database scales horizontally without application changes
- **Low memory overhead** — Go implementation avoids JVM memory management issues
- **Built-in full-text search** — `alloftext()`/`anyoftext()` with stemming, `allofterms()` for exact token matching, trigram index for regex
- **Shortest path** — `shortest(from: 0xA, to: 0xB)` is a first-class operation, directly relevant to the path finder feature
- **Snapshot isolation** — distributed ACID transactions with conflict detection
- **`@reverse` edges** — automatic bidirectional traversal without separate relationship types

### Concerns

- **Complete query + data model rewrite** — highest complexity of all candidates due to predicate-centric model
- **Two-process deployment** — requires both Zero (cluster coordinator) and Alpha (data server)
- **No graph algorithm library** — no equivalent to Neo4j GDS (PageRank, community detection, etc.)
- **Facets for edge properties** — less ergonomic than Neo4j's first-class relationship properties
- **Learning curve** — DQL is neither Cypher nor standard GraphQL
- **Global predicates** — `name` predicate shared across all types can cause unexpected interactions
- **pydgraph ecosystem** — smaller community than neo4j Python driver

### What to Benchmark Specifically

See [shared-pre-work.md](shared-pre-work.md) for the benchmark harness, workload definitions, metrics, and Docker Compose profiles shared across all candidates.

Benchmarks use synthetic data inserted directly into each database via the `GraphBackend` abstraction — no extractor or graphinator changes needed. Two scale points (`small` ~135k nodes/~540k relationships and `large` ~1.35M nodes/~5.4M relationships) provide enough signal to understand approximate orders of magnitude of performance differences.

In addition to the shared workloads (adapted to DQL):

| Benchmark                  | Why It Matters for Dgraph                                        |
| -------------------------- | ---------------------------------------------------------------- |
| JSON batch mutation        | Dgraph's native mutation format vs Cypher UNWIND/MERGE           |
| Upsert throughput          | Query+mutation upsert blocks vs Neo4j MERGE                      |
| Reverse edge traversal     | `~by` performance vs explicit relationship matching              |
| Full-text search latency   | Built-in `alloftext()` vs Neo4j fulltext index                   |
| Distributed transaction    | Snapshot isolation overhead for write-heavy workloads             |
| Memory efficiency          | Go implementation may use less memory than Neo4j JVM             |

### Execution

```bash
docker compose -f investigations/docker/docker-compose.dgraph.yml up -d

# Synthetic data benchmarks at both scale points
uv run python -m investigations.benchmark.runner --backend dgraph --uri localhost:9080 --scale small --clear
uv run python -m investigations.benchmark.runner --backend dgraph --uri localhost:9080 --scale large --clear

uv run python -m investigations.benchmark.compare investigations/results/neo4j_*.json investigations/results/dgraph_*.json
```

## Docker Setup

```yaml
services:
  dgraph-zero:
    image: dgraph/dgraph:latest
    command: dgraph zero --my=dgraph-zero:5080
    ports:
      - "5080:5080"    # gRPC (cluster internal)
      - "6080:6080"    # HTTP admin
    volumes:
      - dgraph_zero_data:/dgraph

  dgraph-alpha:
    image: dgraph/dgraph:latest
    command: dgraph alpha --my=dgraph-alpha:7080 --zero=dgraph-zero:5080 --security whitelist=0.0.0.0/0
    depends_on:
      dgraph-zero:
        condition: service_healthy
    ports:
      - "8080:8080"    # HTTP API + GraphQL
      - "9080:9080"    # gRPC (client connections — pydgraph connects here)
    volumes:
      - dgraph_alpha_data:/dgraph
```

Dgraph requires two processes: **Zero** (cluster coordinator, manages membership and sharding) and **Alpha** (data server, handles queries and mutations). The Ratel web UI (`dgraph/ratel:latest` on port 8000) is optional.

## Work Items (Dgraph-Specific)

Prerequisites: Complete [shared pre-work](shared-pre-work.md) first.

- [ ] Install `pydgraph` package
- [ ] Design predicate schema (scalar predicates with indexes + edge predicates)
- [ ] Define types grouping predicates for each entity (Artist, Label, Master, Release, Genre, Style)
- [ ] Implement `investigations/backends/dgraph_backend.py` with gRPC client
- [ ] Rewrite all benchmark workloads as DQL:
  - [ ] Point lookup: `func: eq(entity_id, $id)` with type filter
  - [ ] Graph traversal: reverse edge `~by` + forward edge `on`
  - [ ] Full-text search: `alloftext(name, $query)` with type filter
  - [ ] Aggregation: value variables + `@groupby`
  - [ ] Batch write: JSON mutations with `commit_now`
  - [ ] Batch write full tx: multi-mutation transaction
- [ ] Test upsert patterns for batch node creation
- [ ] Test reverse edge performance for traversal queries
- [ ] Measure memory usage vs Neo4j for the same dataset
- [ ] Run full benchmark suite (adapted to DQL) and compare with Neo4j baseline

## Decision Criteria

Proceed with Dgraph if:

- [ ] Query performance matches or exceeds Neo4j for the core workloads
- [ ] DQL query patterns are manageable for the team
- [ ] Distributed architecture provides meaningful scaling advantages
- [ ] Built-in full-text search matches Neo4j fulltext index quality
- [ ] Upsert throughput is competitive with Neo4j MERGE
- [ ] Memory usage is lower than Neo4j JVM
- [ ] `pydgraph` client is stable for production use

## When NOT to Choose Dgraph

- If the team strongly prefers Cypher and the labeled property graph model
- If graph algorithms (PageRank, community detection) are needed — Dgraph has no GDS equivalent
- If edge properties are heavily used — facets are less ergonomic than Neo4j relationship properties
- If single-process deployment simplicity is important — Dgraph requires Zero + Alpha
- If the migration budget is limited — the predicate-centric model requires the deepest conceptual shift of all candidates
