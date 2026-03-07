# Shared Pre-Work — Graph Backend Abstraction and Benchmark Harness

This document describes the work required before evaluating any alternative graph database. All candidates share this foundation.

## 1. Graph Backend Abstraction Layer

### Goal

Introduce an abstract interface that isolates database-specific behavior, allowing the application to swap graph backends without modifying service code.

### Interface Design

```
common/
  graph_backend.py          -- abstract base class
  neo4j_backend.py          -- Neo4j implementation (wraps current behavior)
  neo4j_resilient.py        -- existing resilient driver (unchanged)
```

```python
# common/graph_backend.py
from abc import ABC, abstractmethod
from typing import Any

class GraphBackend(ABC):
    """Abstract interface for graph database backends."""

    # --- Connection Lifecycle ---

    @abstractmethod
    async def connect(self, uri: str, auth: tuple[str, str], **kwargs: Any) -> None:
        """Establish connection to the graph database."""

    @abstractmethod
    async def close(self) -> None:
        """Close the connection."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the database is reachable."""

    # --- Query Execution ---

    @abstractmethod
    async def execute_read(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Execute a read-only query. Returns list of record dicts."""

    @abstractmethod
    async def execute_write(self, query: str, params: dict[str, Any] | None = None) -> None:
        """Execute a write query."""

    @abstractmethod
    async def execute_write_batch(self, queries: list[tuple[str, dict[str, Any]]]) -> None:
        """Execute multiple write queries in a single transaction."""

    # --- Schema Management ---

    @abstractmethod
    def get_schema_statements(self) -> list[str]:
        """Return DDL statements for constraints, indexes, and fulltext indexes."""

    # --- Backend-Specific Query Adapters ---

    @abstractmethod
    def fulltext_search_query(self, index_name: str, query_param: str) -> str:
        """Return the fulltext search Cypher/query string for this backend."""

    @abstractmethod
    def stats_query(self) -> str:
        """Return the query to get node/relationship counts."""

    @abstractmethod
    def version_query(self) -> str:
        """Return the query to get the database version."""

    @abstractmethod
    def count_subquery(self, match_pattern: str, alias: str) -> str:
        """Return a COUNT subquery expression compatible with this backend.

        Neo4j uses: COUNT { MATCH (pattern) RETURN DISTINCT x }
        Others may need: rewritten as OPTIONAL MATCH + count(DISTINCT x) + WITH
        """
```

### Abstraction Boundaries

The interface isolates exactly the areas where backends diverge:

| Area | Method | Why It Varies |
|------|--------|---------------|
| Schema DDL | `get_schema_statements()` | Constraint/index syntax differs across all candidates |
| Fulltext search | `fulltext_search_query()` | Different procedure names, query formats |
| COUNT subqueries | `count_subquery()` | Cypher 5.0 feature not supported by most alternatives |
| Database stats | `stats_query()` | APOC vs SHOW commands vs AQL |
| Version info | `version_query()` | `dbms.components()` vs `SHOW VERSION` vs HTTP API |
| Batch writes | `execute_write_batch()` | Transaction semantics vary |

### Neo4j Backend (Reference Implementation)

Extract the current Neo4j behavior into `neo4j_backend.py` that implements `GraphBackend`:

```python
# common/neo4j_backend.py
from common.graph_backend import GraphBackend
from common.neo4j_resilient import AsyncResilientNeo4jDriver

class Neo4jBackend(GraphBackend):
    async def connect(self, uri, auth, **kwargs):
        self._driver = AsyncResilientNeo4jDriver(uri, auth, **kwargs)

    async def execute_read(self, query, params=None):
        async with await self._driver.session(database="neo4j") as session:
            result = await session.run(query, params or {})
            return [dict(record) async for record in result]

    async def execute_write_batch(self, queries):
        async with await self._driver.session(database="neo4j") as session:
            async def batch(tx):
                for query, params in queries:
                    await tx.run(query, params)
            await session.execute_write(batch)

    def fulltext_search_query(self, index_name, query_param):
        return (
            f"CALL db.index.fulltext.queryNodes('{index_name}', ${query_param}) "
            f"YIELD node, score"
        )

    def stats_query(self):
        return "CALL apoc.meta.stats() YIELD nodeCount, relCount"

    def version_query(self):
        return "CALL dbms.components() YIELD name, versions"

    # ... remaining methods
```

### Shared Query Module

Queries that work identically across all Cypher-compatible backends stay in shared modules:

```
api/queries/
  neo4j_queries.py    -- rename to graph_queries.py
  user_queries.py     -- already backend-agnostic (standard Cypher)
  gap_queries.py      -- already backend-agnostic (standard Cypher)
```

Most queries in `user_queries.py` and `gap_queries.py` use only standard Cypher (MATCH, OPTIONAL MATCH, UNWIND, MERGE, WITH, collect, count, SKIP, LIMIT) and need no adaptation.

The 4 explore center-node queries in `neo4j_queries.py` that use `COUNT { }` subqueries are the main queries requiring backend-specific rewrites.

### Service Integration

Services receive a `GraphBackend` instance via dependency injection:

```python
# api/api.py (sketch)
from common.graph_backend import GraphBackend

def create_app(graph: GraphBackend) -> FastAPI:
    app = FastAPI()
    app.state.graph = graph
    # ... routers access app.state.graph
```

Backend selection via environment variable:

```bash
GRAPH_BACKEND=neo4j      # default
GRAPH_BACKEND=memgraph
GRAPH_BACKEND=age
GRAPH_BACKEND=falkordb
GRAPH_BACKEND=arangodb
```

### Work Items

- [ ] Create `common/graph_backend.py` with abstract interface
- [ ] Create `common/neo4j_backend.py` implementing the interface with current Neo4j behavior
- [ ] Rename `api/queries/neo4j_queries.py` to `api/queries/graph_queries.py`
- [ ] Split backend-specific queries (COUNT subqueries, fulltext, stats) from shared queries
- [ ] Wire backend selection into service startup via `GRAPH_BACKEND` env var
- [ ] Update `schema-init/` to use `backend.get_schema_statements()`
- [ ] Update `dashboard/dashboard.py` to use `backend.stats_query()` and `backend.version_query()`
- [ ] Verify all existing tests pass with `Neo4jBackend`

## 2. Benchmark Harness

### Goal

A reusable benchmark runner that inserts synthetic data directly into each database and executes identical workloads against any `GraphBackend` implementation, producing comparable metrics. Synthetic data is representative of the real Discogs dataset (~34M nodes, ~135M relationships) but scaled down to two controlled sizes. The benchmark can be fully automated without modifying the extractor or graphinator.

### Directory Structure

```
benchmarks/
  __init__.py
  runner.py              -- benchmark execution engine
  workloads.py           -- workload definitions (backend-agnostic)
  fixtures.py            -- synthetic data generation
  compare.py             -- side-by-side results comparison
  results/               -- JSON output per run
    neo4j_small_2026-03-06.json
    neo4j_large_2026-03-06.json
    memgraph_small_2026-03-06.json
```

### Synthetic Data Benchmark

The benchmark uses synthetic data that is representative of real Discogs data but scaled down, inserted directly into each database using backend-specific drivers via the `GraphBackend` abstraction. No changes to the extractor or graphinator are required.

#### Why Synthetic Data?

The goal is to understand approximate orders of magnitude of performance differences between backends. Synthetic data is sufficient for this because:

- It preserves the structural characteristics that matter (fan-out, property shapes, index patterns, relationship density)
- It eliminates the need to modify the extractor's fanout logic or implement per-database graphinator backends
- It can be generated at controlled scale points for reproducible comparisons
- It isolates database performance from pipeline overhead (RabbitMQ, message parsing, etc.)

#### Scale Points

Two scale points provide enough data to understand how performance changes with volume:

| Scale | Artists | Labels | Masters | Releases | Approx. Nodes | Approx. Relationships |
|-------|---------|--------|---------|----------|----------------|------------------------|
| `small` | 10,000 | 5,000 | 20,000 | 100,000 | ~135,000 | ~540,000 |
| `large` | 100,000 | 50,000 | 200,000 | 1,000,000 | ~1,350,000 | ~5,400,000 |

The ratios between data types are derived from the real Discogs dataset:

- ~19M releases, ~10M artists, ~2.5M masters, ~2.3M labels (~34M total nodes)
- ~135M relationships (~4 relationships per node on average)
- Releases dominate at ~55%, artists ~29%, masters ~7%, labels ~7%
- The benchmark preserves these proportions and the ~4:1 relationship-to-node ratio

#### Relationship Generation

Synthetic data generates relationships matching the real Discogs graph structure:

| Relationship | Pattern | Fan-Out |
|-------------|---------|---------|
| `BY` | release→artist, master→artist | 1-5 per release/master (power-law) |
| `ON` | release→label | 1-2 per release |
| `DERIVED_FROM` | release→master | 0-1 per release (~60% have a master) |
| `IS` | release→genre, release→style, master→genre, master→style | 1-3 genres, 1-5 styles |
| `MEMBER_OF` | artist→artist (band members) | ~10% of artists are band members |
| `ALIAS_OF` | artist→artist (aliases) | ~5% of artists have aliases |
| `SUBLABEL_OF` | label→label (parent labels) | ~15% of labels have parents |
| `PART_OF` | style→genre | Each style maps to 1 genre |

This produces approximately 4 relationships per node, matching the real dataset ratio of ~135M relationships across ~34M nodes.

#### Synthetic Data Generation

```python
# benchmarks/fixtures.py
import hashlib
import random

SCALES = {
    "small": {"artists": 10_000, "labels": 5_000, "masters": 20_000, "releases": 100_000},
    "large": {"artists": 100_000, "labels": 50_000, "masters": 200_000, "releases": 1_000_000},
}

# 15 genres with Zipf-like popularity (electronic and rock dominate, like real Discogs)
GENRES = [
    "Electronic", "Rock", "Pop", "Hip Hop", "Jazz",
    "Classical", "Folk, World, & Country", "Funk / Soul", "Reggae", "Blues",
    "Latin", "Stage & Screen", "Non-Music", "Children's", "Brass & Military",
]

# ~500 styles distributed across genres with Zipf-like frequency
# Top styles (House, Techno, Punk, Ambient) appear far more often than tail styles

def generate_test_data(scale: str = "small") -> dict:
    """Generate synthetic nodes and relationships at the specified scale.

    Preserves realistic characteristics:
      - ~4 relationships per node (matching real dataset: ~135M rels / ~34M nodes)
      - Relationship fan-out: releases per artist varies from 1 to hundreds
        (power-law distribution — most artists have 1-5 releases, a few have 100+)
      - Genre/style distribution: 15 genres, ~500 styles, Zipf-like popularity
      - SHA256 hashes on every node for deduplication testing
      - Array properties (Release.formats) for index compatibility testing
      - Realistic property shapes: name lengths 2-80 chars,
        year distribution 1950-2025 weighted toward recent decades
      - All 8 relationship types: BY, ON, DERIVED_FROM, IS, MEMBER_OF,
        ALIAS_OF, SUBLABEL_OF, PART_OF
    """
    counts = SCALES[scale]

    artists = [
        {
            "id": i,
            "name": _random_artist_name(),
            "sha256": hashlib.sha256(f"artist-{i}".encode()).hexdigest(),
        }
        for i in range(counts["artists"])
    ]

    labels = [
        {
            "id": i,
            "name": _random_label_name(),
            "sha256": hashlib.sha256(f"label-{i}".encode()).hexdigest(),
        }
        for i in range(counts["labels"])
    ]

    masters = [
        {
            "id": i,
            "title": _random_title(),
            "year": _random_year(),
            "genres": _pick_genres(),
            "styles": _pick_styles(),
            "sha256": hashlib.sha256(f"master-{i}".encode()).hexdigest(),
        }
        for i in range(counts["masters"])
    ]

    releases = [
        {
            "id": i,
            "title": _random_title(),
            "year": _random_year(),
            "artist_ids": _pick_artist_ids(counts["artists"]),   # 1-5 artists (power-law)
            "label_ids": _pick_label_ids(counts["labels"]),      # 1-2 labels
            "master_id": _maybe_pick_master(counts["masters"]),  # ~60% have a master
            "genres": _pick_genres(),                            # 1-3 genres
            "styles": _pick_styles(),                            # 1-5 styles
            "formats": _pick_formats(),                          # array property
            "sha256": hashlib.sha256(f"release-{i}".encode()).hexdigest(),
        }
        for i in range(counts["releases"])
    ]

    # Generate relationship data for MEMBER_OF (~10%), ALIAS_OF (~5%), SUBLABEL_OF (~15%)
    member_of = _generate_band_memberships(artists, fraction=0.10)
    alias_of = _generate_aliases(artists, fraction=0.05)
    sublabel_of = _generate_sublabels(labels, fraction=0.15)

    return {
        "artists": artists, "labels": labels, "masters": masters, "releases": releases,
        "member_of": member_of, "alias_of": alias_of, "sublabel_of": sublabel_of,
    }
```

Data is inserted directly into each database using the `GraphBackend` abstraction — the benchmark script calls `backend.execute_write()` and `backend.execute_write_batch()` to create nodes and then relationships. This bypasses the extractor and graphinator entirely. The insertion order mirrors the graphinator's real write pattern: nodes first (artists, labels, masters, releases), then relationships (BY, ON, DERIVED_FROM, IS, MEMBER_OF, ALIAS_OF, SUBLABEL_OF, PART_OF).

#### Workload Definitions

Seven workloads matching actual Discogsography usage patterns:

```python
# benchmarks/workloads.py

WORKLOADS = {
    "batch_write_nodes": {
        "description": "UNWIND/MERGE node creation (graphinator pattern)",
        "type": "write",
        "batch_sizes": [50, 100, 500, 1000],
        "query": """
            UNWIND $artists AS artist
            MERGE (a:Artist {id: artist.id})
            SET a.name = artist.name, a.sha256 = artist.sha256
        """,
    },

    "batch_write_full_tx": {
        "description": "Full release transaction (6 queries, graphinator pattern)",
        "type": "write",
        "note": "Measures multi-statement transaction overhead",
        # Uses execute_write_batch() with 6 queries per tx
    },

    "point_read": {
        "description": "Single node lookup by indexed property",
        "type": "read",
        "iterations": 1000,
        "query": "MATCH (a:Artist {id: $id}) RETURN a.id, a.name",
    },

    "graph_traversal": {
        "description": "Multi-hop explore/expand pattern",
        "type": "read",
        "iterations": 200,
        "query": """
            MATCH (r:Release)-[:BY]->(a:Artist {name: $name}), (r)-[:ON]->(l:Label)
            RETURN l.id AS id, l.name AS name, count(DISTINCT r) AS release_count
            ORDER BY release_count DESC
            SKIP $offset LIMIT $limit
        """,
    },

    "fulltext_search": {
        "description": "Autocomplete fulltext search",
        "type": "read",
        "iterations": 500,
        "note": "Uses backend.fulltext_search_query() — backend-specific",
    },

    "aggregation": {
        "description": "Trends query with year grouping",
        "type": "read",
        "iterations": 200,
        "query": """
            MATCH (r:Release)-[:BY]->(a:Artist {name: $name})
            WHERE r.year > 0
            WITH r.year AS year, count(DISTINCT r) AS count
            RETURN year, count
            ORDER BY year
        """,
    },

    "concurrent_mixed": {
        "description": "Simultaneous reads and writes",
        "type": "mixed",
        "readers": 4,
        "writers": 2,
        "duration_seconds": 30,
    },
}
```

#### Benchmark Runner

```python
# benchmarks/runner.py
import asyncio, json, statistics, time
from common.graph_backend import GraphBackend

async def run_benchmark(
    backend: GraphBackend,
    workload: dict,
    iterations: int = 100,
) -> dict:
    """Execute a single workload and collect latency metrics."""

    # Warmup (5 iterations, not measured)
    for _ in range(min(5, iterations)):
        await _execute_workload(backend, workload)

    latencies: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter_ns()
        await _execute_workload(backend, workload)
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
        latencies.append(elapsed_ms)

    sorted_lat = sorted(latencies)
    return {
        "workload": workload["description"],
        "iterations": iterations,
        "p50_ms": round(statistics.median(sorted_lat), 3),
        "p95_ms": round(sorted_lat[int(0.95 * len(sorted_lat))], 3),
        "p99_ms": round(sorted_lat[int(0.99 * len(sorted_lat))], 3),
        "mean_ms": round(statistics.mean(sorted_lat), 3),
        "min_ms": round(min(sorted_lat), 3),
        "max_ms": round(max(sorted_lat), 3),
        "throughput_ops_sec": round(1000.0 / statistics.mean(sorted_lat), 1),
    }
```

#### Results Comparison

```python
# benchmarks/compare.py

def compare_results(baseline_file: str, candidate_file: str) -> None:
    """Print side-by-side comparison table with delta percentages."""
    # Output example:
    # Workload              | Neo4j p50 | Memgraph p50 | Delta
    # batch_write_nodes     | 12.3 ms   | 8.1 ms       | -34.1%
    # point_read            | 1.2 ms    | 0.4 ms       | -66.7%
```

#### Metrics Collected Per Run

| Metric | Collection Method |
|--------|-------------------|
| Latency p50 / p95 / p99 (ms) | `time.perf_counter_ns()` per operation |
| Throughput (ops/sec) | Inverse of mean latency |
| Batch throughput (records/sec) | Records in batch / batch latency |
| Memory usage (MB) | Docker `stats` or backend-specific query |
| Cold start time (sec) | Time from `docker compose up` to first successful health check |
| Disk usage (MB) | `docker system df` after data load |
| Concurrent throughput (ops/sec) | Total ops across all tasks / wall clock time |

#### Execution Script

```bash
#!/usr/bin/env bash
# benchmarks/run.sh — synthetic data benchmark

set -euo pipefail

BACKEND=${1:?Usage: ./run.sh <backend> [scale]}
SCALE=${2:-small}
TIMESTAMP=$(date +%Y-%m-%d_%H%M%S)

echo "=== Synthetic Benchmark — $BACKEND at scale=$SCALE ==="

# Generate and load synthetic data directly into the database
uv run python -m benchmarks.runner \
  --backend "$BACKEND" \
  --scale "$SCALE" \
  --load-only

# Run all workloads
uv run python -m benchmarks.runner \
  --backend "$BACKEND" \
  --scale "$SCALE" \
  --output "benchmarks/results/${BACKEND}_${SCALE}_${TIMESTAMP}.json"

echo "=== Results saved to benchmarks/results/${BACKEND}_${SCALE}_${TIMESTAMP}.json ==="
```

#### Docker Compose Profiles

Add all candidate databases as optional profiles:

```yaml
# docker-compose.yml additions

  memgraph:
    image: memgraph/memgraph:latest
    profiles: ["memgraph"]
    ports:
      - "7688:7687"
    command: ["--bolt-server-name-for-init=Neo4j/5.2.0"]
    volumes:
      - memgraph_data:/var/lib/memgraph

  falkordb:
    image: falkordb/falkordb:latest
    profiles: ["falkordb"]
    ports:
      - "6380:6379"
    volumes:
      - falkordb_data:/data

  arangodb:
    image: arangodb/arangodb:latest
    profiles: ["arangodb"]
    environment:
      ARANGO_ROOT_PASSWORD: discogsography
    ports:
      - "8529:8529"
    volumes:
      - arangodb_data:/var/lib/arangodb3

  # Apache AGE uses the existing postgres service with the extension loaded
  # See apache-age.md for setup instructions
```

#### Work Items

- [ ] Create `benchmarks/` directory structure
- [ ] Implement `fixtures.py` — synthetic data generator with realistic characteristics (power-law fan-out, Zipf genre/style distribution, SHA256 hashes, array properties, year distributions, all 8 relationship types)
- [ ] Implement `workloads.py` — seven workload definitions
- [ ] Implement `runner.py` — benchmark execution engine with direct data insertion via `GraphBackend`
- [ ] Implement `compare.py` — results comparison output
- [ ] Create `run.sh` execution script
- [ ] Add Docker Compose profiles for candidate databases
- [ ] Baseline Neo4j results at both scale points (`small` and `large`)
- [ ] Document hardware specs used for benchmarking (CPU, RAM, disk type)
