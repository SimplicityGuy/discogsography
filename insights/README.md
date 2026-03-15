# Insights Service

Precomputed analytics and music trends engine for Discogsography.

## Overview

The Insights service runs scheduled batch analytics against Neo4j and PostgreSQL, stores precomputed results in PostgreSQL `insights.*` tables, and exposes them via read-only HTTP endpoints. Results are proxied to users through the API service at `/api/insights/*`.

## Architecture

- **Language**: Python 3.13+
- **Framework**: FastAPI with async PostgreSQL (`psycopg3`) and Neo4j (`neo4j-driver`)
- **Database**: PostgreSQL 18 (result storage), Neo4j 2026 (graph queries)
- **Service Port**: 8008
- **Health Port**: 8009

## Computation Types

| Type | Description | Source |
| ---- | ----------- | ------ |
| **Artist Centrality** | Top artists ranked by graph edge count | Neo4j |
| **Genre Trends** | Release count per decade for each genre | PostgreSQL |
| **Label Longevity** | Labels ranked by years active | PostgreSQL |
| **Monthly Anniversaries** | Releases with 25/30/40/50/75/100-year milestones | PostgreSQL |
| **Data Completeness** | Quality scores per entity type (image, year, country, genre coverage) | PostgreSQL |

## API Endpoints

All endpoints are accessed via the API service proxy at `/api/insights/*`:

| Endpoint | Method | Description |
| -------- | ------ | ----------- |
| `/api/insights/top-artists` | GET | Top artists by graph centrality |
| `/api/insights/genre-trends` | GET | Release count per decade for a genre |
| `/api/insights/label-longevity` | GET | Labels ranked by years active |
| `/api/insights/this-month` | GET | Notable release anniversaries this month |
| `/api/insights/data-completeness` | GET | Data quality scores per entity type |
| `/api/insights/status` | GET | Latest computation status for each type |

## Configuration

Environment variables:

```bash
# Neo4j connection
NEO4J_HOST=neo4j
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=discogsography

# PostgreSQL connection
POSTGRES_HOST=postgres
POSTGRES_USERNAME=discogsography
POSTGRES_PASSWORD=discogsography
POSTGRES_DATABASE=discogsography

# Scheduler interval in hours (default: 24)
INSIGHTS_SCHEDULE_HOURS=24

# Startup delay in seconds (default: 10)
STARTUP_DELAY=10

# Logging level (default: INFO)
LOG_LEVEL=INFO
```

## PostgreSQL Tables

Results are stored in the `insights` schema:

- `insights.artist_centrality` — Ranked artists by edge count
- `insights.genre_trends` — Genre release counts by decade
- `insights.label_longevity` — Ranked labels by years active
- `insights.monthly_anniversaries` — Notable release anniversaries
- `insights.data_completeness` — Data quality metrics per entity type
- `insights.computation_log` — Audit log of all computation runs

## Health Check

```bash
curl http://localhost:8009/health
```

## Related Documentation

- [Architecture Overview](../docs/architecture.md)
- [Configuration Guide](../docs/configuration.md)
- [Database Schema](../docs/database-schema.md)
