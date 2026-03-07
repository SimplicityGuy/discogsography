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

A reusable benchmark runner that loads identical test data and executes identical workloads against any `GraphBackend` implementation, producing comparable metrics.

### Directory Structure

```
benchmarks/
  __init__.py
  runner.py              -- benchmark execution engine
  workloads.py           -- workload definitions (backend-agnostic)
  fixtures.py            -- test data generation
  compare.py             -- side-by-side results comparison
  results/               -- JSON output per run
    neo4j_2026-03-06.json
    memgraph_2026-03-06.json
```

### Test Data Generation

Generate a representative subset of the Discogs graph:

```python
# benchmarks/fixtures.py

def generate_test_data(scale: str = "small") -> dict:
    """Generate test data at different scales.

    Scales:
      small:  1k artists, 500 labels, 2k masters, 10k releases
      medium: 10k artists, 5k labels, 20k masters, 100k releases
      large:  100k artists, 50k labels, 200k masters, 1M releases
    """
```

Data characteristics to preserve:
- Realistic relationship fan-out (releases per artist, releases per label)
- Genre/style distribution matching real Discogs data
- SHA256 hashes for deduplication testing
- Array properties (`Release.formats`) for index compatibility testing

### Workload Definitions

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

### Benchmark Runner

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

### Results Comparison

```python
# benchmarks/compare.py

def compare_results(baseline_file: str, candidate_file: str) -> None:
    """Print side-by-side comparison table with delta percentages."""
    # Output example:
    # Workload              | Neo4j p50 | Memgraph p50 | Delta
    # batch_write_nodes     | 12.3 ms   | 8.1 ms       | -34.1%
    # point_read            | 1.2 ms    | 0.4 ms       | -66.7%
```

### Metrics Collected Per Run

| Metric | Collection Method |
|--------|-------------------|
| Latency p50 / p95 / p99 (ms) | `time.perf_counter_ns()` per operation |
| Throughput (ops/sec) | Inverse of mean latency |
| Batch throughput (records/sec) | Records in batch / batch latency |
| Memory usage (MB) | Docker `stats` or backend-specific query |
| Cold start time (sec) | Time from `docker compose up` to first successful health check |
| Disk usage (MB) | `docker system df` after data load |
| Concurrent throughput (ops/sec) | Total ops across all tasks / wall clock time |

### Execution Script

```bash
#!/usr/bin/env bash
# benchmarks/run.sh

set -euo pipefail

BACKEND=${1:?Usage: ./run.sh <backend> [scale]}
SCALE=${2:-small}
TIMESTAMP=$(date +%Y-%m-%d_%H%M%S)

echo "=== Benchmarking $BACKEND at scale=$SCALE ==="

# Load test data
uv run python -m benchmarks.runner \
  --backend "$BACKEND" \
  --scale "$SCALE" \
  --load-only

# Run benchmarks
uv run python -m benchmarks.runner \
  --backend "$BACKEND" \
  --scale "$SCALE" \
  --output "benchmarks/results/${BACKEND}_${TIMESTAMP}.json"

echo "=== Results saved to benchmarks/results/${BACKEND}_${TIMESTAMP}.json ==="
```

### Docker Compose Profiles

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

### Work Items

- [ ] Create `benchmarks/` directory structure
- [ ] Implement `fixtures.py` — test data generator at small/medium/large scales
- [ ] Implement `runner.py` — benchmark execution engine
- [ ] Implement `workloads.py` — workload definitions
- [ ] Implement `compare.py` — results comparison output
- [ ] Create `run.sh` execution script
- [ ] Add Docker Compose profiles for candidate databases
- [ ] Baseline Neo4j results at all three scales
- [ ] Document hardware specs used for benchmarking (CPU, RAM, disk type)
