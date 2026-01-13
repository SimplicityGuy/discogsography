# Load Testing Suite

Comprehensive load testing suite for the Discovery service using [Locust](https://locust.io/).

## Overview

This load testing suite simulates realistic user behavior patterns to validate the Discovery service's performance, scalability, and reliability under various load conditions.

## Features

- **5 User Classes**: Realistic behavior patterns (search, graph exploration, analytics, monitoring, mixed workflows)
- **8 Predefined Scenarios**: From smoke tests to stress tests (1-1000 concurrent users)
- **Realistic Workflows**: Multi-step user journeys with pagination and navigation
- **Comprehensive Metrics**: Response times, failure rates, requests per second
- **HTML Reports**: Visual reports with charts and statistics

## Installation

Install Locust using uv (recommended) or pip:

```bash
# Using uv (recommended)
uv pip install locust

# Or using pip
pip install locust
```

## Quick Start

### Run with Web UI

Start Locust with the web interface for interactive testing:

```bash
locust -f tests/load/locustfile.py --host=http://localhost:8005
```

Then open http://localhost:8089 in your browser to configure and start the test.

### Run Headless (Command Line)

Run tests without the web UI using predefined scenarios:

```bash
# Smoke test (1 user, 1 minute)
locust -f tests/load/locustfile.py --host=http://localhost:8005 \
       --users 1 --spawn-rate 1 --run-time 1m --headless

# Moderate load (100 users, 10 minutes)
locust -f tests/load/locustfile.py --host=http://localhost:8005 \
       --users 100 --spawn-rate 10 --run-time 10m --headless \
       --csv tests/load/results/moderate_load \
       --html tests/load/results/moderate_load.html
```

### Use Predefined Scenarios

The `scenarios.py` module provides 8 predefined scenarios with optimized parameters:

```python
from tests.load.scenarios import get_scenario_command, print_all_scenarios

# Print all available scenarios
print_all_scenarios()

# Get command for specific scenario
cmd = get_scenario_command("MODERATE_LOAD")
print(cmd)
```

Or run directly:

```bash
python -c "from tests.load.scenarios import print_all_scenarios; print_all_scenarios()"
```

## Predefined Scenarios

### SMOKE_TEST

- **Users**: 1
- **Duration**: 1 minute
- **Purpose**: Verify basic functionality

```bash
locust -f tests/load/locustfile.py --host=http://localhost:8005 \
       --users 1 --spawn-rate 1 --run-time 1m --headless \
       --csv tests/load/results/smoke_test \
       --html tests/load/results/smoke_test.html
```

### LIGHT_LOAD

- **Users**: 25
- **Duration**: 5 minutes
- **Purpose**: Simulate light daytime traffic

```bash
locust -f tests/load/locustfile.py --host=http://localhost:8005 \
       --users 25 --spawn-rate 5 --run-time 5m --headless \
       --csv tests/load/results/light_load \
       --html tests/load/results/light_load.html
```

### MODERATE_LOAD

- **Users**: 100
- **Duration**: 10 minutes
- **Purpose**: Simulate moderate busy period traffic

```bash
locust -f tests/load/locustfile.py --host=http://localhost:8005 \
       --users 100 --spawn-rate 10 --run-time 10m --headless \
       --csv tests/load/results/moderate_load \
       --html tests/load/results/moderate_load.html
```

### HEAVY_LOAD

- **Users**: 250
- **Duration**: 15 minutes
- **Purpose**: Simulate heavy peak traffic

```bash
locust -f tests/load/locustfile.py --host=http://localhost:8005 \
       --users 250 --spawn-rate 25 --run-time 15m --headless \
       --csv tests/load/results/heavy_load \
       --html tests/load/results/heavy_load.html
```

### STRESS_TEST

- **Users**: 500
- **Duration**: 20 minutes
- **Purpose**: Find breaking point

```bash
locust -f tests/load/locustfile.py --host=http://localhost:8005 \
       --users 500 --spawn-rate 50 --run-time 20m --headless \
       --csv tests/load/results/stress_test \
       --html tests/load/results/stress_test.html
```

### SPIKE_TEST

- **Users**: 200 (spawned quickly)
- **Duration**: 5 minutes
- **Purpose**: Simulate sudden traffic spike

```bash
locust -f tests/load/locustfile.py --host=http://localhost:8005 \
       --users 200 --spawn-rate 100 --run-time 5m --headless \
       --csv tests/load/results/spike_test \
       --html tests/load/results/spike_test.html
```

### ENDURANCE_TEST

- **Users**: 100
- **Duration**: 60 minutes
- **Purpose**: Long-running stability test

```bash
locust -f tests/load/locustfile.py --host=http://localhost:8005 \
       --users 100 --spawn-rate 10 --run-time 60m --headless \
       --csv tests/load/results/endurance_test \
       --html tests/load/results/endurance_test.html
```

### BREAKPOINT_TEST

- **Users**: 1000
- **Duration**: 30 minutes
- **Purpose**: Find maximum capacity

```bash
locust -f tests/load/locustfile.py --host=http://localhost:8005 \
       --users 1000 --spawn-rate 20 --run-time 30m --headless \
       --csv tests/load/results/breakpoint_test \
       --html tests/load/results/breakpoint_test.html
```

## User Classes

### SearchUser (Weight: 3)

Primary focus on searching for music:

- Artist search (50%)
- Release search (30%)
- All types search (20%)
- Paginated search (10%)

### GraphExplorerUser (Weight: 2)

Explores the knowledge graph:

- Graph exploration at depth 2 (50%)
- Deep graph exploration at depth 3 (30%)
- Graph pagination (20%)
- Artist details (10%)

### AnalyticsUser (Weight: 1)

Views analytics and trends:

- Genre trends (50%)
- Artist trends (30%)
- Genre heatmap (20%)
- Collaboration heatmap (10%)

### MonitoringUser (Weight: 0.5)

Checks service health:

- Cache statistics (50%)
- Database pool statistics (30%)
- Prometheus metrics (10%)

### RealisticUser (Weight: 5)

Combines multiple behaviors with realistic workflows:

- Complete search workflow (50%)
- Graph browsing workflow (25%)
- Analytics workflow (15%)
- Mixed search (10%)

## Configuration

Edit `tests/load/locust.conf` to change default parameters:

```conf
host = http://localhost:8005
users = 50
spawn-rate = 5
run-time = 5m
loglevel = INFO
csv = tests/load/results/locust_results
html = tests/load/results/locust_report.html
```

## Results

Results are saved to `tests/load/results/` with the following files:

- `{scenario}_stats.csv` - Request statistics
- `{scenario}_stats_history.csv` - Time-series statistics
- `{scenario}_failures.csv` - Failed requests
- `{scenario}.html` - HTML report with charts

## Metrics to Monitor

### Key Performance Indicators

1. **Response Time**:

   - p50 (median): Should be \<200ms for most endpoints
   - p95: Should be \<500ms
   - p99: Should be \<1000ms

1. **Throughput**:

   - Requests per second (RPS)
   - Target: >100 RPS for moderate load

1. **Error Rate**:

   - Should be \<1% under normal load
   - Should be \<5% under stress load

1. **Resource Usage**:

   - CPU: Monitor via `docker stats`
   - Memory: Should remain stable over time
   - Database connections: Monitor via `/api/db/pool/stats`

### Service-Specific Metrics

Monitor Discovery service metrics during load tests:

```bash
# Cache statistics
curl http://localhost:8005/api/cache/stats

# Database pool statistics
curl http://localhost:8005/api/db/pool/stats

# Prometheus metrics
curl http://localhost:8005/metrics
```

## Best Practices

1. **Start Small**: Begin with smoke tests before running stress tests
1. **Warm Up**: Allow services to warm up caches and connection pools
1. **Monitor Resources**: Watch CPU, memory, and database connections
1. **Analyze Results**: Review HTML reports and identify bottlenecks
1. **Iterate**: Optimize based on findings and re-test
1. **Document Baselines**: Record baseline performance for comparison

## Troubleshooting

### Connection Refused

Ensure the Discovery service is running:

```bash
docker-compose ps discovery
docker-compose logs -f discovery
```

### High Error Rates

Check Discovery service logs for errors:

```bash
docker-compose logs -f discovery | grep ERROR
```

### Slow Response Times

1. Check cache hit rates: `curl http://localhost:8005/api/cache/stats`
1. Check database pool: `curl http://localhost:8005/api/db/pool/stats`
1. Review Neo4j indexes: See `docs/neo4j-indexing.md`

## Advanced Usage

### Custom Scenarios

Create custom scenarios by modifying `scenarios.py` or creating new user classes in `locustfile.py`.

### Distributed Load Testing

Run Locust in distributed mode for higher load:

```bash
# Master node
locust -f tests/load/locustfile.py --master --host=http://localhost:8005

# Worker nodes (run on multiple machines)
locust -f tests/load/locustfile.py --worker --master-host=<master-ip>
```

### Environment Variables

Override host and configuration via environment variables:

```bash
export LOCUST_HOST=http://production.example.com:8005
export LOCUST_USERS=500
export LOCUST_SPAWN_RATE=50
export LOCUST_RUN_TIME=30m

locust -f tests/load/locustfile.py --headless
```

## Integration with CI/CD

Add load testing to GitHub Actions:

```yaml
- name: Run Load Tests
  run: |
    locust -f tests/load/locustfile.py \
           --host=http://localhost:8005 \
           --users 10 --spawn-rate 2 --run-time 2m \
           --headless --only-summary
```

## References

- [Locust Documentation](https://docs.locust.io/)
- [Discovery Service Architecture](../../README.md)
- [Neo4j Indexing Guide](../../docs/neo4j-indexing.md)
- [Performance Optimization](../../docs/performance.md)
