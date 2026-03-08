# Graph Database Investigations

This directory contains investigation notes for evaluating alternative graph databases against the current Neo4j 2026 Community deployment.

## Documents

| Document | Database | Status |
|----------|----------|--------|
| [shared-pre-work.md](shared-pre-work.md) | — | Implemented: backend abstraction and benchmark harness |
| [memgraph.md](memgraph.md) | Memgraph Community | Compatibility analysis complete |
| [apache-age.md](apache-age.md) | Apache AGE (PostgreSQL extension) | Compatibility analysis complete |
| [falkordb.md](falkordb.md) | FalkorDB (Redis module) | Compatibility analysis complete |
| [arangodb.md](arangodb.md) | ArangoDB Community | Compatibility analysis complete |
| [cloud-benchmark-deployment.md](cloud-benchmark-deployment.md) | — | Implemented: Hetzner Cloud convergence-based pipeline |
| [investigations/](../../investigations/) | — | Implementation: backends, benchmark harness, calibration, infra |

## Implementation

The benchmark system is fully implemented in the `investigations/` directory at the repository root:

- **5 database backends** implementing the `GraphBackend` abstraction (Neo4j, Memgraph, AGE, FalkorDB, ArangoDB)
- **Benchmark harness** with 7 workloads, synthetic data generation, and results comparison
- **Hardware calibration** for cross-environment scaling
- **Cloud infrastructure** with Ansible playbooks for Hetzner Cloud deployment
- **One-command launcher** (`run.sh`) for both local Docker and cloud modes

```bash
# Local — Docker Compose on your laptop
./investigations/run.sh

# Cloud — Hetzner VMs with dedicated hardware per database
./investigations/run.sh --cloud
```

See the [investigations README](../../investigations/README.md) for full usage details.

## Context

- **Current stack:** Neo4j 2026 Community (Bolt, Cypher, APOC) via `neo4j` Python driver
- **Dataset:** 19M+ releases, 10M+ artists, 2.5M masters, 2.3M labels from Discogs music database
- **Workload:** Batch MERGE/UNWIND writes (graphinator), fulltext search (autocomplete), multi-hop traversals (explore/expand), aggregation (trends/stats)
- **Key files affected:** `common/neo4j_resilient.py`, `schema-init/neo4j_schema.py`, `graphinator/batch_processor.py`, `api/queries/graph_queries.py`, `api/queries/user_queries.py`, `api/queries/gap_queries.py`, `dashboard/dashboard.py`
