# Graph Database Investigations

This directory contains investigation notes for evaluating alternative graph databases against the current Neo4j 2026 Community deployment.

## Documents

| Document | Database | Status |
|----------|----------|--------|
| [shared-pre-work.md](shared-pre-work.md) | — | Pre-requisite work shared across all evaluations |
| [memgraph.md](memgraph.md) | Memgraph Community | Compatibility analysis complete |
| [apache-age.md](apache-age.md) | Apache AGE (PostgreSQL extension) | Compatibility analysis complete |
| [falkordb.md](falkordb.md) | FalkorDB (Redis module) | Compatibility analysis complete |
| [arangodb.md](arangodb.md) | ArangoDB Community | Compatibility analysis complete |
| [cloud-benchmark-deployment.md](cloud-benchmark-deployment.md) | — | Cloud deployment plan for parallel benchmarking |

## Evaluation Order

1. Complete the [shared pre-work](shared-pre-work.md) first — graph backend abstraction layer and benchmark harness
2. Deploy cloud infrastructure per [cloud-benchmark-deployment.md](cloud-benchmark-deployment.md)
3. Evaluate candidates in priority order: Memgraph > Apache AGE > FalkorDB > ArangoDB
4. Each database doc contains a self-contained task list for that evaluation

## Context

- **Current stack:** Neo4j 2026 Community (Bolt, Cypher, APOC) via `neo4j` Python driver
- **Dataset:** ~20M+ nodes and relationships from Discogs music database
- **Workload:** Batch MERGE/UNWIND writes (graphinator), fulltext search (autocomplete), multi-hop traversals (explore/expand), aggregation (trends/stats)
- **Key files affected:** `common/neo4j_resilient.py`, `schema-init/neo4j_schema.py`, `graphinator/batch_processor.py`, `api/queries/neo4j_queries.py`, `api/queries/user_queries.py`, `api/queries/gap_queries.py`, `dashboard/dashboard.py`
