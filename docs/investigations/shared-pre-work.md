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

| Area             | Method                    | Why It Varies                                         |
| ---------------- | ------------------------- | ----------------------------------------------------- |
| Schema DDL       | `get_schema_statements()` | Constraint/index syntax differs across all candidates |
| Fulltext search  | `fulltext_search_query()` | Different procedure names, query formats              |
| COUNT subqueries | `count_subquery()`        | Cypher 5.0 feature not supported by most alternatives |
| Database stats   | `stats_query()`           | APOC vs SHOW commands vs AQL                          |
| Version info     | `version_query()`         | `dbms.components()` vs `SHOW VERSION` vs HTTP API     |
| Batch writes     | `execute_write_batch()`   | Transaction semantics vary                            |

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

## 2. Benchmark Harness

### Goal

A reusable benchmark runner that inserts synthetic data directly into each database and executes identical workloads against any `GraphBackend` implementation, producing comparable metrics. Synthetic data is representative of the real Discogs dataset (~34M nodes, ~135M relationships) but scaled down to two controlled sizes. The benchmark can be fully automated without modifying the extractor or graphinator.

### Directory Structure

```
investigations/
  benchmark/
    runner.py              -- benchmark execution engine
    workloads.py           -- workload definitions (backend-agnostic)
    fixtures.py            -- synthetic data generation
    compare.py             -- side-by-side results comparison
  backends/
    base.py                -- abstract GraphBackend interface
    neo4j_backend.py       -- Neo4j implementation (reference)
    memgraph_backend.py    -- Memgraph implementation
    age_backend.py         -- Apache AGE implementation
    falkordb_backend.py    -- FalkorDB implementation
    arangodb_backend.py    -- ArangoDB implementation
  calibration/
    calibrate.py           -- hardware calibration for environment scaling
  results/                 -- JSON output per run
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

| Scale   | Artists | Labels | Masters | Releases  | Approx. Nodes | Approx. Relationships |
| ------- | ------- | ------ | ------- | --------- | ------------- | --------------------- |
| `small` | 10,000  | 5,000  | 20,000  | 100,000   | ~135,000      | ~540,000              |
| `large` | 100,000 | 50,000 | 200,000 | 1,000,000 | ~1,350,000    | ~5,400,000            |

The ratios between data types are derived from the real Discogs dataset (collected 2026-03-07):

- 18.95M releases, 9.97M artists, 2.53M masters, 2.36M labels, 16 genres, 757 styles (~33.8M total nodes)
- 134.4M relationships (3.97 relationships per node on average)
- Releases ~56%, artists ~29.5%, masters ~7.5%, labels ~7%
- The benchmark preserves these proportions and the ~4:1 relationship-to-node ratio
- **Critical:** ~58% of artists and ~39% of labels are orphans (zero relationships) — synthetic data must reproduce this

#### Relationship Generation

Synthetic data generates relationships matching the real Discogs graph structure:

| Relationship   | Pattern                       | Real Distribution (2026-03-07)                                                                                                                            |
| -------------- | ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `BY`           | release→artist, master→artist | 26M total. Per release: avg 1.21, p50=1, p90=2, p99=4, max=49. Per artist (reverse): avg 8.17, p50=2, p90=10, p99=86, max=1.3M — heavy power-law          |
| `ON`           | release→label                 | 20.7M total. Per release: avg 1.09, p50=1, p90=1, p95=2, max=100                                                                                          |
| `DERIVED_FROM` | release→master                | 19M total. ~100% of releases have a master (not 60%). Per master: avg 7.50, p50=2, p90=7, p99=32                                                          |
| `IS`           | release→genre, release→style  | 61.2M total. Genres per release: avg 1.33, p50=1, p90=2, max=15. Styles per release: avg 1.79, p50=1, p90=3, max=90. ~0% missing genre, ~8% missing style |
| `MEMBER_OF`    | artist→artist (band members)  | 2.3M total. 13.38% of artists are members, 6.55% are bands. Members per band: avg 3.54, p50=3, p90=6                                                      |
| `ALIAS_OF`     | artist→artist (aliases)       | 4.9M total. ~12.82% of artists have aliases                                                                                                               |
| `SUBLABEL_OF`  | label→label (parent labels)   | 278K total. 11.74% of labels are sublabels. Children per parent: avg 4.47, p50=1, p90=4, max=140K                                                         |
| `PART_OF`      | style→genre                   | 10.4K total (757 styles → 16 genres, ~14 per genre avg)                                                                                                   |

**Orphan nodes:** 57.81% of artists and 39.33% of labels have zero relationships of any kind. Only 28.15% of artists have any BY edges. Synthetic data must include orphan nodes at these rates.

This produces 3.97 relationships per node, matching the real dataset ratio of ~134.4M relationships across ~33.8M nodes.

#### Synthetic Data Generation

```python
# investigations/benchmark/fixtures.py
import hashlib
import random

SCALES = {
    "small": {"artists": 10_000, "labels": 5_000, "masters": 20_000, "releases": 100_000},
    "large": {"artists": 100_000, "labels": 50_000, "masters": 200_000, "releases": 1_000_000},
}

# 16 genres ranked by real release count (2026-03-07 production data)
# Weights derived from actual release counts — Rock dominates, not Electronic
GENRES = [
    "Rock", "Electronic", "Pop", "Folk, World, & Country", "Jazz",
    "Funk / Soul", "Classical", "Hip Hop", "Latin", "Stage & Screen",
    "Reggae", "Blues", "Non-Music", "Children's", "Brass & Military",
    "No Genre",
]
# Zipf weights from real data (millions of releases):
# Rock 6.18, Electronic 4.87, Pop 3.85, Folk 2.48, Jazz 1.51,
# Funk/Soul 1.29, Classical 1.20, Hip Hop 0.96, Latin 0.85, Stage&Screen 0.58, ...

# 757 styles distributed across genres with Zipf-like frequency
# Top styles: Pop Rock 928K, House 705K, Vocal 638K, Experimental 625K, Punk 575K

def generate_test_data(scale: str = "small") -> dict:
    """Generate synthetic nodes and relationships at the specified scale.

    Preserves realistic characteristics (calibrated from 2026-03-07 production data):
      - 3.97 relationships per node (matching real dataset: ~134.4M rels / ~33.8M nodes)
      - ~58% of artists and ~39% of labels are orphans (zero relationships)
      - Only ~28% of artists have any BY edges
      - Artists per release: avg 1.21, p50=1, p99=4 (NOT power-law on this side)
      - Releases per artist (reverse): avg 8.17, p50=2, heavy power-law tail
      - Genre/style distribution: 16 genres, 757 styles, Zipf-like popularity
      - SHA256 hashes on every node for deduplication testing
      - Year property on Master and Release nodes (Long type), 6.73% of masters lack it
      - No formats property on Release nodes
      - Artist name length: avg 13.77, p50=13, p99=34, max=255
      - Release title length: avg 20.96, p50=17, p99=73, max=255
      - DERIVED_FROM: ~100% of releases have a master (not 60%)
      - ~8% of releases have no style; genre coverage near-complete
      - All 8 relationship types: BY, ON, DERIVED_FROM, IS, MEMBER_OF,
        ALIAS_OF, SUBLABEL_OF, PART_OF
    """
    counts = SCALES[scale]

    artists = [
        {
            "id": str(i),                                    # String type, not integer
            "name": _random_artist_name(),           # avg len ~14, p50=13, p99=34
            "releases_url": f"https://api.discogs.com/artists/{i}/releases",
            "resource_url": f"https://api.discogs.com/artists/{i}",
            "sha256": hashlib.sha256(f"artist-{i}".encode()).hexdigest(),
        }
        for i in range(counts["artists"])
    ]

    labels = [
        {
            "id": str(i),                                    # String type
            "name": _random_label_name(),            # avg len ~20, p50=18, p99=50
            "sha256": hashlib.sha256(f"label-{i}".encode()).hexdigest(),
        }
        for i in range(counts["labels"])
    ]

    masters = [
        {
            "id": str(i),                                    # String type
            "title": _random_title(),                # avg len ~21, p50=17, p99=73
            "year": _maybe_year(),                   # 6.73% None; range 1860-2026; p50=1998; decade-weighted
            "genres": _pick_genres(),
            "styles": _maybe_pick_styles(),
            "sha256": hashlib.sha256(f"master-{i}".encode()).hexdigest(),
        }
        for i in range(counts["masters"])
    ]

    releases = [
        {
            "id": str(i),                                    # String type
            "title": _random_title(),             # avg len ~21, p50=17, p99=73
            "artist_ids": _pick_artist_ids(counts["artists"]),   # avg 1.21, p50=1, p99=4
            "label_ids": _pick_label_ids(counts["labels"]),      # avg 1.09, p50=1, p95=2
            "master_id": _pick_master(counts["masters"]),        # ~100% have a master
            "genres": _pick_genres(),                            # avg 1.33, p50=1, p90=2
            "styles": _maybe_pick_styles(),                      # avg 1.79, p50=1, p90=3; ~8% have none
            "sha256": hashlib.sha256(f"release-{i}".encode()).hexdigest(),
            "year": _maybe_year(),                            # same distribution as Master
            # Note: no formats property (does not exist in real data)
        }
        for i in range(counts["releases"])
    ]

    # Orphan nodes: ~58% of artists and ~39% of labels get no relationships at all.
    # Only ~28% of artists have BY edges. This is achieved by concentrating
    # release→artist assignments on a subset of artist IDs (power-law selection).

    # Generate relationship data for MEMBER_OF (~13.4%), ALIAS_OF (~12.8%), SUBLABEL_OF (~11.7%)
    member_of = _generate_band_memberships(artists, member_fraction=0.1338, band_fraction=0.0655, avg_members=3.54)
    alias_of = _generate_aliases(artists, fraction=0.1282)
    sublabel_of = _generate_sublabels(labels, fraction=0.1174)

    return {
        "artists": artists, "labels": labels, "masters": masters, "releases": releases,
        "member_of": member_of, "alias_of": alias_of, "sublabel_of": sublabel_of,
    }
```

#### Production Data Reference (2026-03-07)

These numbers were collected from the live Neo4j instance and used to calibrate all synthetic data parameters:

| Metric                      | Value                                                                                                     |
| --------------------------- | --------------------------------------------------------------------------------------------------------- |
| Total nodes                 | 33,823,655                                                                                                |
| Total relationships         | 134,366,055                                                                                               |
| Rels per node               | 3.97                                                                                                      |
| Releases                    | 18,954,226                                                                                                |
| Artists                     | 9,974,217                                                                                                 |
| Masters                     | 2,531,018                                                                                                 |
| Labels                      | 2,363,420                                                                                                 |
| Genres                      | 16                                                                                                        |
| Styles                      | 757                                                                                                       |
| Orphan artists (no rels)    | 57.81%                                                                                                    |
| Artists with BY edges       | 28.15%                                                                                                    |
| Orphan labels (no rels)     | 39.33%                                                                                                    |
| Artists per release         | avg 1.21, p50=1, p99=4                                                                                    |
| Releases per artist         | avg 8.17, p50=2, p90=10, p99=86                                                                           |
| Labels per release          | avg 1.09, p50=1, p95=2                                                                                    |
| Releases per master         | avg 7.50, p50=2, p90=7, p99=32                                                                            |
| DERIVED_FROM coverage       | ~100% of releases                                                                                         |
| Genres per release          | avg 1.33, p50=1, p90=2                                                                                    |
| Styles per release          | avg 1.79, p50=1, p90=3                                                                                    |
| Releases with no style      | ~8.15%                                                                                                    |
| MEMBER_OF members           | 13.38% of artists                                                                                         |
| MEMBER_OF bands             | 6.55% of artists                                                                                          |
| Members per band            | avg 3.54, p50=3, p90=6                                                                                    |
| ALIAS_OF                    | 12.82% of artists                                                                                         |
| SUBLABEL_OF                 | 11.74% of labels                                                                                          |
| Children per parent label   | avg 4.47, p50=1, p90=4                                                                                    |
| Year property               | On Master and Release (Long type)                                                                         |
| Masters with no year        | 6.73%                                                                                                     |
| Artist name length          | avg 13.77, p50=13, p99=34, max=255                                                                        |
| Release title length        | avg 20.96, p50=17, p99=73, max=255                                                                        |
| Master title length         | avg 21.06, p50=17, p99=73, max=255                                                                        |
| Label name length           | avg 20.28, p50=18, p99=50, max=255                                                                        |
| All string max              | 255 (truncated/capped)                                                                                    |
| Node ID type                | String (not integer)                                                                                      |
| Node properties             | id (String), sha256 (String), name/title (String), year (Long on Master+Release)                          |
| Artist extra props          | releases_url (String), resource_url (String)                                                              |
| Year range                  | 1860–2026 (avg 1995.47, p10=1967, p50=1998, p90=2019)                                                     |
| Year distribution (masters) | pre-1950: 1%, 1950s: 3%, 1960s: 7%, 1970s: 10%, 1980s: 12%, 1990s: 18%, 2000s: 18%, 2010s: 21%, 2020s: 8% |
| Year peak                   | 2018 at 51,792 masters (all-time catalogued peak)                                                         |
| Year recent trend           | Declining from 2018 onward due to Discogs cataloguing lag, not production decline                         |
| Top genres                  | Rock (6.18M), Electronic (4.87M), Pop (3.85M), Folk (2.48M), Jazz (1.51M)                                 |
| Top styles                  | Pop Rock (928K), House (705K), Vocal (638K), Experimental (625K), Punk (575K)                             |

Data is inserted directly into each database using the `GraphBackend` abstraction — the benchmark script calls `backend.execute_write()` and `backend.execute_write_batch()` to create nodes and then relationships. This bypasses the extractor and graphinator entirely. The insertion order mirrors the graphinator's real write pattern: nodes first (artists, labels, masters, releases), then relationships (BY, ON, DERIVED_FROM, IS, MEMBER_OF, ALIAS_OF, SUBLABEL_OF, PART_OF).

#### Workload Definitions

Seven workloads matching actual Discogsography usage patterns:

```python
# investigations/benchmark/workloads.py

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
# investigations/benchmark/runner.py
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
# investigations/benchmark/compare.py

def compare_results(baseline_file: str, candidate_file: str) -> None:
    """Print side-by-side comparison table with delta percentages."""
    # Output example:
    # Workload              | Neo4j p50 | Memgraph p50 | Delta
    # batch_write_nodes     | 12.3 ms   | 8.1 ms       | -34.1%
    # point_read            | 1.2 ms    | 0.4 ms       | -66.7%
```

#### Metrics Collected Per Run

| Metric                          | Collection Method                                              |
| ------------------------------- | -------------------------------------------------------------- |
| Latency p50 / p95 / p99 (ms)    | `time.perf_counter_ns()` per operation                         |
| Throughput (ops/sec)            | Inverse of mean latency                                        |
| Batch throughput (records/sec)  | Records in batch / batch latency                               |
| Memory usage (MB)               | Docker `stats` or backend-specific query                       |
| Cold start time (sec)           | Time from `docker compose up` to first successful health check |
| Disk usage (MB)                 | `docker system df` after data load                             |
| Concurrent throughput (ops/sec) | Total ops across all tasks / wall clock time                   |

#### Running Benchmarks

```bash
# Local — one command to benchmark all databases
./investigations/run.sh

# Local — single database at specific scale
./investigations/run.sh neo4j large

# Cloud — Hetzner VMs with dedicated hardware per database
./investigations/run.sh --cloud

# Run the benchmark runner directly
uv run python -m investigations.benchmark.runner \
  --backend neo4j --uri bolt://localhost:7687 --scale small --clear \
  --output investigations/results/neo4j-small.json

# Compare results
./investigations/run.sh --compare
```

#### Docker Compose Files

Per-database Docker Compose files are in `investigations/docker/`:

```
investigations/docker/
  docker-compose.neo4j.yml
  docker-compose.memgraph.yml
  docker-compose.age.yml
  docker-compose.falkordb.yml
  docker-compose.arangodb.yml
```

Cloud deployments use Jinja2 templates in `investigations/infra/templates/` that are deployed to each database host.

## 3. Scaling Results to Your Environment

### Goal

Allow anyone to take the Hetzner CX53 benchmark results and estimate how the same workloads would perform on their own hardware, without re-running the full benchmark suite.

### How It Works

A lightweight calibration script runs portable micro-benchmarks that stress the same hardware dimensions as the database workloads:

| Dimension           | Calibration Test               | Database Workloads Affected                                 |
| ------------------- | ------------------------------ | ----------------------------------------------------------- |
| CPU (single-thread) | SHA-256 hashing throughput     | Query parsing, single-query execution, aggregation          |
| CPU (multi-thread)  | SHA-256 across all cores       | Concurrent mixed workloads                                  |
| Memory bandwidth    | 64 MB sequential read/write    | In-memory databases (Memgraph, FalkorDB), large result sets |
| Sequential I/O      | 256 MB write + read with fsync | Bulk data loading, WAL writes, batch inserts                |
| Random I/O          | 4 KB random reads (IOPS)       | Index lookups, point reads, graph traversals                |
| Python sort         | Sort 1M floats                 | In-process query overhead                                   |

By comparing calibration output from the benchmark host against your machine, per-dimension scaling factors are computed. These are then applied to each workload type using a weighted model that reflects which hardware dimensions matter most for that workload.

### Step-by-Step

**1. Run calibration on your machine:**

```bash
uv run python investigations/calibration/calibrate.py run --output my-calibration.json
```

This takes ~30 seconds and produces a JSON file with your hardware profile.

**2. Get the baseline calibration from the benchmark host:**

The Hetzner CX53 calibration file is saved alongside benchmark results at `investigations/results/baseline-calibration.json` after each benchmark run.

**3. Scale the benchmark results:**

```bash
uv run python investigations/calibration/calibrate.py scale \
  --baseline investigations/results/baseline-calibration.json \
  --local my-calibration.json \
  --benchmark-results investigations/results/neo4j-large-*.json \
  --output my-neo4j-estimates.json
```

This prints a summary table and optionally saves full scaled results.

### Example Output

```
Per-dimension scaling factors (local / baseline):
  Dimension            Factor   Interpretation
  -------------------- --------  ------------------------------
  CPU (single)            1.850  Local is 1.9x faster
  CPU (multi)             2.400  Local is 2.4x faster
  Memory bandwidth        1.320  Local is 1.3x faster
  Sequential I/O          3.100  Local is 3.1x faster
  Random I/O              5.200  Local is 5.2x faster

Scaled workload estimates:
  Workload                            Type                 Factor  p50 (orig)    p50 (est)
  ----------------------------------- -------------------- -------  ------------  ------------
  autocomplete_artist                 fulltext_search        2.933       2.1 ms        0.7 ms
  explore_center_artist               graph_traversal        2.576       8.4 ms        3.3 ms
  point_read                          point_read             3.560       1.2 ms        0.3 ms
  batch_write_nodes                   batch_write_nodes      3.270      12.3 ms        3.8 ms
```

### Workload Weight Model

Each workload type maps to a set of weights reflecting which hardware dimensions dominate its performance:

| Workload Type       | CPU-ST | CPU-MT | Memory | Seq-IO | Rand-IO |
| ------------------- | ------ | ------ | ------ | ------ | ------- |
| point_read          | 0.3    | 0.0    | 0.2    | 0.0    | 0.5     |
| graph_traversal     | 0.4    | 0.0    | 0.3    | 0.0    | 0.3     |
| fulltext_search     | 0.3    | 0.0    | 0.3    | 0.0    | 0.4     |
| aggregation         | 0.5    | 0.0    | 0.3    | 0.0    | 0.2     |
| batch_write_nodes   | 0.2    | 0.1    | 0.1    | 0.3    | 0.3     |
| batch_write_full_tx | 0.2    | 0.1    | 0.1    | 0.3    | 0.3     |
| concurrent_mixed    | 0.1    | 0.4    | 0.2    | 0.1    | 0.2     |

The composite scaling factor for a workload = weighted sum of per-dimension factors. A latency value is divided by this factor; a throughput value is multiplied.

### Limitations

These are order-of-magnitude estimates, not precise predictions. Factors not captured:

- **Database internals**: Buffer pool sizing, query planner, internal concurrency, JIT compilation
- **OS and kernel tuning**: Filesystem type, I/O scheduler, transparent huge pages, swappiness
- **Dataset fit**: Whether the working set fits in RAM changes performance characteristics entirely
- **Caching effects**: Warm cache behavior differs significantly from cold starts
- **Network latency**: Only relevant if the database runs on a different host than the benchmark client

Use the scaled numbers to understand whether your hardware is in the same ballpark as the benchmark host, significantly faster, or significantly slower — not for precise SLA planning.
