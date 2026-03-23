# API Performance Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a standalone Docker-based performance test that sequentially times all API query endpoints, driven by a YAML config of test entities.

**Architecture:** A Python script using `httpx` reads test entities from `config.yaml`, resolves entity names to IDs where needed via autocomplete, hits every query endpoint N iterations, computes timing statistics (min/avg/max/p95), and writes a JSON + console report. A Dockerfile builds a lightweight container that waits for API health before running. Results and API logs are written to a bind-mounted local directory.

**Tech Stack:** Python 3.13+, httpx, pyyaml, statistics (stdlib)

______________________________________________________________________

### Task 1: Create YAML Config

**Files:**

- Create: `tests/perftest/config.yaml`

- [ ] **Step 1: Write the default config file**

```yaml
api_base_url: "http://api:8004"
health_url: "http://api:8005/health"
iterations: 3
timeout: 30
health_retries: 30
health_interval: 5

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

- [ ] **Step 2: Commit**

```bash
git add tests/perftest/config.yaml
git commit -m "feat: add perftest default config with test entities"
```

### Task 2: Create Performance Test Runner

**Files:**

- Create: `tests/perftest/run_perftest.py`

- [ ] **Step 1: Write the test runner**

The script should:

1. Parse CLI args: `--config` (path to YAML, default `/app/config.yaml`), `--output` (results dir, default `/results`)
1. Load YAML config
1. Wait for API health with retries
1. Define endpoint test groups:
   - **Static endpoints** (no params): `year-range`, `genre-emergence`, 5 insights endpoints, `insights/status`
   - **Autocomplete** for each entity type + name from config
   - **Explore** for each entity type + name
   - **Trends** for each entity type + name
   - **Search** for each entity name (all types combined)
   - **Path** for all 6 artist pair combinations (from_type=artist, to_type=artist)
   - **ID-resolved**: resolve artist/label IDs via autocomplete node_id field, then hit label DNA, label similar, label compare, artist similar
1. For each endpoint, run N iterations recording: response time, status code, response body size
1. Compute per-endpoint stats: min, avg, max, p95, error count
1. Write results to `{output}/perftest-results.json` and a human-readable `{output}/perftest-report.txt`
1. Copy API logs from the API container's `/logs/` volume (the script will do this via shared network — actually, the entrypoint script will handle log collection)

Key implementation details:

- Use `httpx.Client` (sync) for simplicity since we want sequential timing

- Each test call: `start = time.perf_counter()`, make request, `elapsed = time.perf_counter() - start`

- For ID resolution: hit `/api/autocomplete?q={name}&type={type}&limit=1`, extract `node_id` from first result

- p95 calculation: use `statistics` module or manual sorted-index approach

- Group results by category in the report for readability

- Print a live progress line per endpoint being tested

- Exit code 0 on completion (even if some endpoints return errors — errors are reported in results)

- [ ] **Step 2: Commit**

```bash
git add tests/perftest/run_perftest.py
git commit -m "feat: add perftest runner with endpoint timing and reporting"
```

### Task 3: Create Entrypoint Script

**Files:**

- Create: `tests/perftest/entrypoint.sh`

- [ ] **Step 1: Write the entrypoint**

```bash
#!/bin/sh
set -e

echo "=================================================="
echo "  Discogsography API Performance Test"
echo "=================================================="
echo ""

# Run the performance test
python /app/run_perftest.py --config /app/config.yaml --output /results

echo ""
echo "Collecting API logs..."

# Copy API logs if the API container's log volume is accessible
# The user mounts the api_logs volume to /api-logs in the docker run command
if [ -d "/api-logs" ]; then
    cp /api-logs/api.log /results/api.log 2>/dev/null || echo "  api.log not found"
    cp /api-logs/profiling.log /results/profiling.log 2>/dev/null || echo "  profiling.log not found"
    echo "API logs copied to results directory."
else
    echo "  /api-logs not mounted — skipping log collection."
    echo "  To collect API logs, add: -v discogsography_api_logs:/api-logs:ro"
fi

echo ""
echo "Results saved to /results/"
echo "=================================================="
```

- [ ] **Step 2: Commit**

```bash
git add tests/perftest/entrypoint.sh
git commit -m "feat: add perftest entrypoint with log collection"
```

### Task 4: Create Dockerfile

**Files:**

- Create: `tests/perftest/Dockerfile`

- [ ] **Step 1: Write the Dockerfile**

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.13-slim

RUN pip install --no-cache-dir httpx pyyaml

WORKDIR /app

COPY run_perftest.py config.yaml entrypoint.sh ./
RUN chmod +x entrypoint.sh

VOLUME ["/results"]

ENTRYPOINT ["/app/entrypoint.sh"]
```

- [ ] **Step 2: Commit**

```bash
git add tests/perftest/Dockerfile
git commit -m "feat: add perftest Dockerfile"
```

### Task 5: Create README

**Files:**

- Create: `tests/perftest/README.md`

- [ ] **Step 1: Write the README**

Cover:

- What this tests (all API query endpoints)

- Prerequisites (docker-compose services running, API healthy)

- How to build the container

- How to run with bind mount + network + optional API log volume

- How to customize the YAML config

- How to read the results

- Example output

- [ ] **Step 2: Commit**

```bash
git add tests/perftest/README.md
git commit -m "docs: add perftest README with usage instructions"
```

### Task 6: Verify Build

- [ ] **Step 1: Verify Dockerfile builds**

```bash
cd tests/perftest
docker build -t discogsography/perftest .
```

- [ ] **Step 2: Verify image runs (dry-run against localhost, expect health check failure)**

Quick sanity check that the container starts and the script begins executing.
