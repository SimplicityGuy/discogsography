# Graph Database Investigations

Benchmark harness for evaluating Neo4j alternatives: Memgraph, Apache AGE, FalkorDB, and ArangoDB.

## Quick Start

**One command to benchmark everything:**

```bash
# Local — Docker Compose on your laptop
./investigations/run.sh

# Cloud — Hetzner VMs with dedicated hardware per database
./investigations/run.sh --cloud
```

### Local mode (default)

Starts each database in Docker (one at a time), generates synthetic data, runs all 7 workloads, and prints a comparison table.

**Prerequisites:** Docker Desktop running, uv installed, run from repository root.

### Cloud mode (`--cloud`)

Uses a **convergence model** — run the command repeatedly and it advances the pipeline:

1. **1st run:** Provisions controller + 3 DB servers + baseline. Runs calibration, deploys databases, starts benchmarks.
2. **2nd+ runs:** Checks status, tears down completed servers, provisions remaining databases.
3. **Final run:** All done — tears down DB servers, fetches results. Controller remains for inspection.

All prerequisites (Ansible, SSH keys, vault) are auto-installed — the only thing you need is a Hetzner Cloud API token.

**Estimated cost:** ~€3.57 for a full run (~24 hours).

## Usage

```bash
# Benchmark all databases locally at small scale (~135k nodes)
./investigations/run.sh

# Benchmark a single database
./investigations/run.sh neo4j
./investigations/run.sh memgraph
./investigations/run.sh age
./investigations/run.sh falkordb
./investigations/run.sh arangodb

# Benchmark at large scale (~1.35M nodes)
./investigations/run.sh neo4j large

# Compare existing results
./investigations/run.sh --compare

# Full cloud pipeline (convergence — run repeatedly)
./investigations/run.sh --cloud

# Limit concurrent servers (default: 5)
./investigations/run.sh --cloud --server-limit 3

# Fetch results from cloud to investigations/results/
./investigations/run.sh --fetch

# Destroy all cloud infrastructure
./investigations/run.sh --teardown

# Remove vault, SSH keys, and vault password
./investigations/run.sh --clean

# Run the benchmark runner directly
uv run python -m investigations.benchmark.runner \
  --backend neo4j --uri bolt://localhost:7687 --scale small
```

## Environment Variables

All optional. Defaults work for local Docker.

| Variable | Default | Description |
|----------|---------|-------------|
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j Bolt endpoint |
| `NEO4J_USER` | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | `discogsography` | Neo4j password |
| `MEMGRAPH_URI` | `bolt://localhost:7688` | Memgraph Bolt endpoint |
| `AGE_URI` | `postgresql://discogsography:discogsography@localhost:5433/discogsography` | PostgreSQL+AGE connection string |
| `FALKORDB_URI` | `redis://localhost:6380` | FalkorDB Redis endpoint |
| `ARANGODB_URI` | `http://localhost:8529` | ArangoDB HTTP endpoint |
| `ARANGODB_USER` | `root` | ArangoDB username |
| `ARANGODB_PASSWORD` | `discogsography` | ArangoDB password |
| `BENCHMARK_SCALE` | `small` | Scale point: `small` or `large` |

## Directory Structure

```
investigations/
  README.md                         # This file
  run.sh                            # One-command launcher
  pyproject.toml                    # Investigation-specific dependencies
  backends/                         # GraphBackend implementations
    base.py                         # Abstract base class
    neo4j_backend.py                # Neo4j (reference implementation)
    memgraph_backend.py             # Memgraph Community
    age_backend.py                  # Apache AGE (PostgreSQL extension)
    falkordb_backend.py             # FalkorDB (Redis module)
    arangodb_backend.py             # ArangoDB Community
  benchmark/                        # Benchmark harness
    fixtures.py                     # Synthetic data generation
    workloads.py                    # 7 workload definitions
    runner.py                       # CLI benchmark runner
    compare.py                      # Side-by-side results comparison
  calibration/                      # Hardware calibration for scaling results
    calibrate.py                    # Micro-benchmarks + scaling logic
  results/                          # All output (benchmarks, calibration, metrics, logs)
  docker/                           # Per-database Docker Compose files
    docker-compose.neo4j.yml
    docker-compose.memgraph.yml
    docker-compose.age.yml
    docker-compose.falkordb.yml
    docker-compose.arangodb.yml
  infra/                            # Cloud deployment (Ansible + Hetzner)
    ansible.cfg                     # Ansible configuration
    playbooks/                      # 13 playbooks (provision, setup, benchmark, teardown)
    templates/                      # Jinja2 templates (Docker Compose, runner scripts, metrics)
    inventory/                      # Generated host inventory (not in git)
```

## Benchmark Workloads

| Workload | Type | Iterations | What It Tests |
|----------|------|-----------|---------------|
| `batch_write_nodes` | write | 50 | UNWIND/MERGE node creation (graphinator pattern) |
| `batch_write_full_tx` | write | 50 | Multi-statement transaction overhead |
| `point_read` | read | 1000 | Single node lookup by indexed property |
| `graph_traversal` | read | 200 | Multi-hop explore/expand pattern |
| `fulltext_search` | read | 500 | Autocomplete fulltext search |
| `aggregation` | read | 200 | Year-grouped trends query |
| `concurrent_mixed` | mixed | 30s | 4 readers + 2 writers simultaneously |

## Synthetic Data

Data is generated to match real Discogs production proportions (calibrated 2026-03-07):

| Scale | Artists | Labels | Masters | Releases | Approx. Nodes | Approx. Rels |
|-------|---------|--------|---------|----------|---------------|--------------|
| `small` | 10,000 | 5,000 | 20,000 | 100,000 | ~135,000 | ~540,000 |
| `large` | 100,000 | 50,000 | 200,000 | 1,000,000 | ~1,350,000 | ~5,400,000 |

Key characteristics preserved:
- 3.97 relationships per node
- ~58% orphan artists, ~39% orphan labels
- Power-law artist popularity distribution
- Zipf-like genre/style distributions
- All 8 relationship types (BY, ON, DERIVED_FROM, IS, MEMBER_OF, ALIAS_OF, SUBLABEL_OF, PART_OF)

## Results Output

Each run produces a JSON file in `investigations/results/`:

```json
{
  "backend": "neo4j",
  "scale": "small",
  "timestamp": "2026-03-07T12:00:00Z",
  "insertion_metrics": {
    "total_duration_sec": 45.2,
    "artists": {"count": 10000, "duration_sec": 2.1, "records_per_sec": 4761.9}
  },
  "benchmarks": {
    "point_read": {"p50_ms": 1.2, "p95_ms": 3.1, "p99_ms": 8.4, "throughput_ops_sec": 833.3},
    "graph_traversal": {"p50_ms": 8.4, "p95_ms": 22.1, "p99_ms": 45.0}
  }
}
```

## Hardware Calibration

Scale benchmark results to your hardware using the calibration tool:

```bash
# Run calibration (~30 seconds)
uv run python investigations/calibration/calibrate.py run --output my-calibration.json

# Scale results from another environment
uv run python investigations/calibration/calibrate.py scale \
  --baseline hetzner-calibration.json \
  --local my-calibration.json \
  --benchmark-results investigations/results/neo4j-large-*.json
```

See [docs/investigations/shared-pre-work.md](../docs/investigations/shared-pre-work.md) for methodology details.

## Related Documentation

- [docs/investigations/README.md](../docs/investigations/README.md) — Investigation overview and evaluation order
- [docs/investigations/shared-pre-work.md](../docs/investigations/shared-pre-work.md) — Abstraction layer design and benchmark spec
- [docs/investigations/cloud-benchmark-deployment.md](../docs/investigations/cloud-benchmark-deployment.md) — Hetzner Cloud deployment details
- [investigations/infra/README.md](infra/README.md) — Cloud infrastructure reference (playbooks, convergence model, server layout)
- [docs/investigations/memgraph.md](../docs/investigations/memgraph.md) — Memgraph compatibility analysis
- [docs/investigations/apache-age.md](../docs/investigations/apache-age.md) — Apache AGE compatibility analysis
- [docs/investigations/falkordb.md](../docs/investigations/falkordb.md) — FalkorDB compatibility analysis
- [docs/investigations/arangodb.md](../docs/investigations/arangodb.md) — ArangoDB compatibility analysis
