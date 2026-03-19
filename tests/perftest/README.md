# API Performance Test

Sequential performance test runner for all Discogsography API query endpoints. Measures response times across multiple iterations and produces a detailed report with min/avg/max/p95 statistics per endpoint.

## What It Tests

The performance test covers all API endpoints that execute database queries (Neo4j, PostgreSQL, or Redis):

### Static Endpoints (no parameters)

| Endpoint | Database |
|---|---|
| `GET /api/explore/year-range` | Neo4j |
| `GET /api/explore/genre-emergence` | Neo4j |
| `GET /api/insights/top-artists` | Neo4j (via insights proxy) |
| `GET /api/insights/genre-trends` | Neo4j (via insights proxy) |
| `GET /api/insights/label-longevity` | Neo4j (via insights proxy) |
| `GET /api/insights/this-month` | Neo4j (via insights proxy) |
| `GET /api/insights/data-completeness` | PostgreSQL (via insights proxy) |
| `GET /api/insights/status` | Redis (via insights proxy) |

### Parameterized Endpoints (driven by config)

| Endpoint | Test Coverage | Database |
|---|---|---|
| `GET /api/autocomplete` | Each artist, genre, style, label | Neo4j |
| `GET /api/explore` | Each artist, genre, style, label | Neo4j |
| `GET /api/trends` | Each artist, genre, style, label | Neo4j |
| `GET /api/search` | Each entity name | PostgreSQL |
| `GET /api/path` | All artist pair combinations | Neo4j |

### ID-Resolved Endpoints (IDs resolved via autocomplete)

| Endpoint | Test Coverage | Database |
|---|---|---|
| `GET /api/label/{id}/dna` | Each label | Neo4j |
| `GET /api/label/{id}/similar` | Each label | Neo4j |
| `GET /api/label/dna/compare` | All labels combined | Neo4j |
| `GET /api/recommend/similar/artist/{id}` | Each artist | Neo4j |

## Prerequisites

The Discogsography stack must be running with data loaded:

```bash
docker compose up -d
```

Wait for the API to be healthy:

```bash
curl -f http://localhost:8005/health
```

## Build

From the repository root:

```bash
docker build -t discogsography/perftest -f tests/perftest/Dockerfile tests/perftest/
```

## Run

### Basic Run

The config file (`config.yaml`) is mounted into the container at `/config/config.yaml`. The default config is included in `tests/perftest/config.yaml`:

```bash
mkdir -p perftest-results

docker run --rm \
  --network discogsography_discogsography \
  -v "$(pwd)/perftest-results:/results" \
  -v "$(pwd)/tests/perftest/config.yaml:/config/config.yaml:ro" \
  discogsography/perftest
```

### With API Log Collection

Mount the API logs volume as read-only to copy `api.log` and `profiling.log` into the results:

```bash
mkdir -p perftest-results

docker run --rm \
  --network discogsography_discogsography \
  -v "$(pwd)/perftest-results:/results" \
  -v "$(pwd)/tests/perftest/config.yaml:/config/config.yaml:ro" \
  -v discogsography_api_logs:/api-logs:ro \
  discogsography/perftest
```

> **Tip:** To capture Cypher profiling data, restart the API with `LOG_LEVEL=DEBUG` and `CYPHER_PROFILING=true` before running the performance test. This writes query execution plans to `profiling.log`.

### With Custom Config

Create your own `config.yaml` and mount it instead:

```bash
docker run --rm \
  --network discogsography_discogsography \
  -v "$(pwd)/perftest-results:/results" \
  -v "$(pwd)/my-config.yaml:/config/config.yaml:ro" \
  -v discogsography_api_logs:/api-logs:ro \
  discogsography/perftest
```

## Configuration

The test is driven by a `config.yaml` file mounted at `/config/config.yaml`. The default config (`tests/perftest/config.yaml`) includes:

```yaml
api_base_url: "http://api:8004"
health_url: "http://api:8005/health"
iterations: 3          # Times each endpoint is called
timeout: 30            # HTTP request timeout (seconds)
health_retries: 30     # Health check retries before giving up
health_interval: 5     # Seconds between health retries

artists:
  - Indecent Noise
  - Solarstone
  - Green Day
  - Johnny Cash

genres:
  - Electronic
  - Rock

styles:
  - Trance
  - Hard Trance
  - Progressive Trance

labels:
  - Hooj Choons
  - Reprise Records
  - Tracid Traxx
```

### Configuration Notes

- **Entity names must exist in your dataset.** If an entity is not found via autocomplete, ID-resolved endpoints for that entity are skipped.
- **Artist pairs** are generated as all combinations (not permutations) — 4 artists produce 6 pairs.
- **Iterations** controls statistical accuracy. Use 1 for a quick smoke test, 5+ for reliable p95 values.

## Results

After a run, `perftest-results/` contains:

| File | Description |
|---|---|
| `perftest-report.txt` | Human-readable report with per-endpoint stats grouped by category, top 10 slowest endpoints, and summary |
| `perftest-results.json` | Machine-readable JSON with full timing data for every individual run |
| `api.log` | API service log (if API logs volume was mounted) |
| `profiling.log` | Cypher profiling output (if API logs volume was mounted and profiling was enabled) |

### Example Report Output

```
==============================================================================
  Discogsography API Performance Test Report
  Generated: 2026-03-19 14:30:00 UTC
==============================================================================

--- EXPLORE ---
  Endpoint                                              Min      Avg      Max      P95   Err
  --------------------------------------------------------------------------------------
  explore/year-range                                  0.0123s  0.0145s  0.0167s  0.0163s    0
  explore/genre-emergence                             0.0234s  0.0256s  0.0278s  0.0274s    0
  explore/artist/Indecent Noise                       0.0345s  0.0367s  0.0389s  0.0385s    0

--- SUMMARY ---
  Total endpoints tested: 62
  Total errors: 0
  Fastest avg: 0.0102s
  Slowest avg: 1.2345s
  Overall avg: 0.1234s

--- TOP 10 SLOWEST (by avg) ---
  Endpoint                                              Avg      P95
  ------------------------------------------------------------------
  path/Indecent Noise -> Johnny Cash                  1.2345s  1.3456s
```

## Network Note

The container must be on the same Docker network as the API service. The default network name is `discogsography_discogsography` (created by docker compose). Verify with:

```bash
docker network ls | grep discogsography
```
