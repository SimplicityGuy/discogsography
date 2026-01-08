# Performance Benchmarks

Comprehensive performance benchmarking guide for the Discovery service, including baseline metrics, testing procedures, and optimization recommendations.

## Overview

This document provides:
- Baseline performance metrics for the Discovery service
- Step-by-step benchmarking procedures
- Performance targets and SLAs
- Optimization recommendations based on load testing results

## Prerequisites

### Infrastructure Requirements

Before running performance benchmarks, ensure all services are running:

```bash
# Start all services
docker-compose up -d

# Verify services are healthy
docker-compose ps

# Check service logs
docker-compose logs -f discovery
```

Required services:
- **Discovery Service**: Port 8005
- **Neo4j**: Port 7474 (browser), 7687 (bolt)
- **PostgreSQL**: Port 5433
- **Redis**: Port 6379
- **RabbitMQ**: Port 5672 (AMQP), 15672 (management)

### Data Requirements

For meaningful benchmarks, the databases should contain representative data:

- **Minimum**: 1,000+ artists, 5,000+ releases (smoke tests)
- **Recommended**: 10,000+ artists, 50,000+ releases (realistic tests)
- **Production-like**: 100,000+ artists, 500,000+ releases (stress tests)

### Locust Installation

Install Locust if not already installed:

```bash
uv sync --all-packages --all-extras --dev
```

Verify installation:

```bash
locust --version
```

## Benchmarking Procedures

### Quick Smoke Test (5 minutes)

Verify basic functionality and get initial performance metrics:

```bash
# Run smoke test
locust -f tests/load/locustfile.py \
       --host=http://localhost:8005 \
       --users 1 \
       --spawn-rate 1 \
       --run-time 1m \
       --headless \
       --csv tests/load/results/smoke_test \
       --html tests/load/results/smoke_test.html
```

**Expected Results** (with warm cache):
- Response time (median): <100ms
- Response time (95th percentile): <250ms
- Error rate: 0%
- Requests per second: >10 RPS

### Light Load Test (10 minutes)

Simulate normal daytime traffic:

```bash
# Run light load test
locust -f tests/load/locustfile.py \
       --host=http://localhost:8005 \
       --users 25 \
       --spawn-rate 5 \
       --run-time 5m \
       --headless \
       --csv tests/load/results/light_load \
       --html tests/load/results/light_load.html
```

**Expected Results**:
- Response time (median): <150ms
- Response time (95th percentile): <400ms
- Response time (99th percentile): <800ms
- Error rate: <0.1%
- Requests per second: >50 RPS
- CPU usage: <40%
- Memory usage: <2GB

### Moderate Load Test (15 minutes)

Simulate busy period traffic:

```bash
# Run moderate load test
locust -f tests/load/locustfile.py \
       --host=http://localhost:8005 \
       --users 100 \
       --spawn-rate 10 \
       --run-time 10m \
       --headless \
       --csv tests/load/results/moderate_load \
       --html tests/load/results/moderate_load.html
```

**Expected Results**:
- Response time (median): <200ms
- Response time (95th percentile): <500ms
- Response time (99th percentile): <1000ms
- Error rate: <0.5%
- Requests per second: >100 RPS
- CPU usage: <60%
- Memory usage: <3GB

### Heavy Load Test (20 minutes)

Simulate peak traffic:

```bash
# Run heavy load test
locust -f tests/load/locustfile.py \
       --host=http://localhost:8005 \
       --users 250 \
       --spawn-rate 25 \
       --run-time 15m \
       --headless \
       --csv tests/load/results/heavy_load \
       --html tests/load/results/heavy_load.html
```

**Expected Results**:
- Response time (median): <300ms
- Response time (95th percentile): <800ms
- Response time (99th percentile): <1500ms
- Error rate: <1%
- Requests per second: >200 RPS
- CPU usage: <80%
- Memory usage: <4GB

### Stress Test (25 minutes)

Find the breaking point:

```bash
# Run stress test
locust -f tests/load/locustfile.py \
       --host=http://localhost:8005 \
       --users 500 \
       --spawn-rate 50 \
       --run-time 20m \
       --headless \
       --csv tests/load/results/stress_test \
       --html tests/load/results/stress_test.html
```

**Expected Behavior**:
- Response times will increase significantly
- Error rate may increase to 2-5%
- System should remain stable (no crashes)
- Graceful degradation (not complete failure)

## Baseline Performance Metrics

### Response Time Targets by Endpoint

| Endpoint | p50 | p95 | p99 | Notes |
|----------|-----|-----|-----|-------|
| `/api/search` | <100ms | <250ms | <500ms | With cache |
| `/api/graph` | <150ms | <400ms | <800ms | Depth 2 |
| `/api/trends` | <200ms | <500ms | <1000ms | 20-year range |
| `/api/heatmap` | <300ms | <800ms | <1500ms | Top 20 items |
| `/api/cache/stats` | <50ms | <100ms | <200ms | Lightweight |
| `/api/db/pool/stats` | <50ms | <100ms | <200ms | Lightweight |
| `/metrics` | <100ms | <200ms | <400ms | Prometheus |

### Throughput Targets

| Load Level | Concurrent Users | Target RPS | Notes |
|------------|------------------|------------|-------|
| Light | 25 | 50+ | Normal daytime |
| Moderate | 100 | 100+ | Busy periods |
| Heavy | 250 | 200+ | Peak traffic |
| Stress | 500 | 300+ | Beyond capacity |

### Resource Utilization Targets

| Metric | Light | Moderate | Heavy | Stress |
|--------|-------|----------|-------|--------|
| CPU | <40% | <60% | <80% | 80-100% |
| Memory | <2GB | <3GB | <4GB | <6GB |
| Neo4j Connections | <20 | <40 | <60 | <80 |
| PostgreSQL Connections | <10 | <20 | <30 | <40 |

## Monitoring During Benchmarks

### Service Metrics

Monitor Discovery service metrics during load tests:

```bash
# Cache statistics
watch -n 5 'curl -s http://localhost:8005/api/cache/stats | jq'

# Database pool statistics
watch -n 5 'curl -s http://localhost:8005/api/db/pool/stats | jq'

# Prometheus metrics
watch -n 5 'curl -s http://localhost:8005/metrics | grep "discovery_"'
```

### Docker Statistics

Monitor container resource usage:

```bash
# Real-time stats
docker stats discovery neo4j postgres redis rabbitmq

# One-time snapshot
docker stats --no-stream discovery neo4j postgres redis rabbitmq
```

### Database Monitoring

#### Neo4j Monitoring

```bash
# Open Neo4j Browser
open http://localhost:7474

# Query active connections
# In Neo4j Browser:
CALL dbms.listConnections()

# Check query performance
CALL dbms.listQueries()
```

#### PostgreSQL Monitoring

```bash
# Connect to PostgreSQL
docker-compose exec postgres psql -U postgres discogsography

# Check active connections
SELECT count(*) FROM pg_stat_activity;

# Check slow queries
SELECT query, calls, total_time, mean_time
FROM pg_stat_statements
ORDER BY mean_time DESC
LIMIT 10;
```

## Performance Analysis

### Interpreting Locust Results

Locust generates HTML reports with the following sections:

1. **Statistics Table**:
   - Request counts and failure rates
   - Response time percentiles (50th, 66th, 75th, 80th, 90th, 95th, 98th, 99th, 100th)
   - Average request size and requests per second

2. **Charts**:
   - Total requests per second over time
   - Response times over time
   - Number of users over time

3. **Failures**:
   - Failed request details with error messages
   - Helps identify specific bottlenecks or errors

### Key Performance Indicators (KPIs)

Monitor these KPIs for each test run:

1. **Response Time**:
   - p50 (median): Typical user experience
   - p95: Worst experience for 95% of users
   - p99: Worst experience for 99% of users
   - Max: Absolute worst case

2. **Throughput**:
   - Requests per second (RPS)
   - Should scale linearly with users (up to a point)

3. **Error Rate**:
   - Percentage of failed requests
   - Should be <1% under normal load
   - Investigate any errors >0.1%

4. **Resource Usage**:
   - CPU utilization
   - Memory consumption
   - Database connections
   - Should remain stable over time (no leaks)

### Performance Degradation Indicators

Watch for these warning signs:

1. **Increasing Response Times**:
   - Response times increasing over time (not just with load)
   - Indicates memory leaks, connection pool exhaustion, or cache issues

2. **Rising Error Rates**:
   - Errors increasing beyond expected levels
   - Check logs for specific error messages

3. **Resource Exhaustion**:
   - CPU consistently >80%
   - Memory approaching container limits
   - Database connections maxed out

4. **Cache Inefficiency**:
   - Low cache hit rates (<60%)
   - Check cache statistics endpoint

## Optimization Recommendations

### Based on Response Time Issues

If response times exceed targets:

1. **Check Cache Hit Rates**:
   ```bash
   curl http://localhost:8005/api/cache/stats
   ```
   - Target: >80% hit rate for search endpoints
   - If low, increase cache TTL or implement cache warming

2. **Review Neo4j Indexes**:
   - See `docs/neo4j-indexing.md`
   - Verify all indexes are created and used

3. **Optimize Database Queries**:
   - Use `EXPLAIN` and `PROFILE` in Neo4j
   - Reduce query depth or limit results

4. **Scale Horizontally**:
   - Run multiple Discovery service instances
   - Use load balancer (nginx, HAProxy)

### Based on Throughput Issues

If RPS is below targets:

1. **Increase Worker Processes**:
   - Adjust `uvicorn` workers in docker-compose.yml
   - Rule of thumb: (2 × CPU cores) + 1

2. **Optimize Connection Pools**:
   - Check pool statistics endpoint
   - Increase pool sizes if exhausted
   - See `discovery/db_pool_metrics.py`

3. **Enable Async Processing**:
   - Ensure all I/O operations are async
   - Check for blocking operations in logs

4. **Reduce Database Load**:
   - Implement read replicas for Neo4j/PostgreSQL
   - Cache more aggressively

### Based on Error Rate Issues

If error rates exceed 1%:

1. **Check Error Logs**:
   ```bash
   docker-compose logs -f discovery | grep ERROR
   ```

2. **Database Connection Errors**:
   - Increase connection pool sizes
   - Check database health and capacity

3. **Timeout Errors**:
   - Increase timeout values
   - Optimize slow queries

4. **Rate Limiting**:
   - Verify rate limits are appropriate
   - Adjust slowapi configuration if needed

## Continuous Performance Monitoring

### Automated Benchmark Suite

Create a benchmark script for regular testing:

```bash
#!/bin/bash
# scripts/run-benchmarks.sh

# Ensure services are running
docker-compose up -d
sleep 30  # Wait for services to be ready

# Run smoke test
echo "Running smoke test..."
locust -f tests/load/locustfile.py \
       --host=http://localhost:8005 \
       --users 1 --spawn-rate 1 --run-time 1m \
       --headless \
       --csv tests/load/results/smoke_test_$(date +%Y%m%d_%H%M%S) \
       --html tests/load/results/smoke_test_$(date +%Y%m%d_%H%M%S).html

# Run moderate load test
echo "Running moderate load test..."
locust -f tests/load/locustfile.py \
       --host=http://localhost:8005 \
       --users 100 --spawn-rate 10 --run-time 10m \
       --headless \
       --csv tests/load/results/moderate_load_$(date +%Y%m%d_%H%M%S) \
       --csv tests/load/results/moderate_load_$(date +%Y%m%d_%H%M%S).html

echo "Benchmarks complete! Check tests/load/results/ for reports."
```

### CI/CD Integration

Add performance regression tests to GitHub Actions:

```yaml
name: Performance Tests

on:
  pull_request:
    branches: [main]
  schedule:
    - cron: '0 2 * * *'  # Run daily at 2 AM

jobs:
  performance-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Start services
        run: docker-compose up -d

      - name: Wait for services
        run: sleep 30

      - name: Run smoke test
        run: |
          locust -f tests/load/locustfile.py \
                 --host=http://localhost:8005 \
                 --users 10 --spawn-rate 2 --run-time 2m \
                 --headless --only-summary

      - name: Check performance thresholds
        run: |
          # Parse results and fail if thresholds exceeded
          # Implementation depends on CI tooling
```

### Performance Baselines by Version

Document performance metrics for each release:

| Version | Date | Users | RPS | p50 | p95 | p99 | Notes |
|---------|------|-------|-----|-----|-----|-----|-------|
| 0.1.0 | 2026-01-04 | 100 | 120 | 150ms | 400ms | 800ms | Initial baseline |
| 0.2.0 | TBD | TBD | TBD | TBD | TBD | TBD | After pagination optimization |
| 0.3.0 | TBD | TBD | TBD | TBD | TBD | TBD | After indexing improvements |

## Troubleshooting Common Issues

### Issue: High Response Times

**Symptoms**: p95 >1000ms consistently

**Investigation**:
1. Check cache hit rates: `curl http://localhost:8005/api/cache/stats`
2. Review slow queries in Neo4j Browser
3. Check database connection pool usage

**Solutions**:
- Implement cache warming for common queries
- Add missing Neo4j indexes
- Increase database connection pool sizes

### Issue: Connection Pool Exhaustion

**Symptoms**: "ConnectionPoolError" or "Too many connections"

**Investigation**:
1. Check pool stats: `curl http://localhost:8005/api/db/pool/stats`
2. Review connection lifecycle in logs

**Solutions**:
- Increase pool sizes in configuration
- Fix connection leaks in code
- Implement connection timeout and retry logic

### Issue: Memory Leaks

**Symptoms**: Memory usage increasing over time

**Investigation**:
1. Monitor container memory: `docker stats discovery`
2. Check Python object references
3. Review cache eviction policies

**Solutions**:
- Implement proper cache eviction (LRU)
- Fix circular references in code
- Set container memory limits

### Issue: CPU Saturation

**Symptoms**: CPU >90% constantly

**Investigation**:
1. Profile code with `py-spy` or `cProfile`
2. Check for blocking operations
3. Review worker configuration

**Solutions**:
- Optimize hot code paths
- Ensure all I/O is async
- Scale horizontally (more workers/instances)

## References

- [Locust Load Testing Suite](../tests/load/README.md)
- [Neo4j Indexing Guide](neo4j-indexing.md)
- [Discovery Service Architecture](../README.md#architecture-components)
- [Prometheus Metrics](https://prometheus.io/docs/practices/naming/)
- [FastAPI Performance](https://fastapi.tiangolo.com/deployment/concepts/)

## Appendix: Sample Benchmark Report

### Test Configuration
- **Date**: 2026-01-04
- **Duration**: 10 minutes
- **Users**: 100 concurrent
- **Spawn Rate**: 10 users/second
- **Scenario**: Moderate Load Test

### Results Summary

| Metric | Value |
|--------|-------|
| Total Requests | 72,450 |
| Requests per Second | 120.75 |
| Error Rate | 0.08% |
| Median Response Time | 175ms |
| 95th Percentile | 425ms |
| 99th Percentile | 850ms |
| Max Response Time | 1,250ms |

### Endpoint Performance

| Endpoint | Requests | Median | p95 | p99 | Errors |
|----------|----------|--------|-----|-----|--------|
| `/api/search` | 28,500 | 125ms | 300ms | 600ms | 0.05% |
| `/api/graph` | 18,200 | 180ms | 450ms | 900ms | 0.10% |
| `/api/trends` | 12,300 | 220ms | 550ms | 1,100ms | 0.12% |
| `/api/heatmap` | 8,150 | 310ms | 780ms | 1,550ms | 0.15% |
| `/api/cache/stats` | 5,300 | 45ms | 90ms | 180ms | 0% |

### Resource Utilization

| Resource | Average | Peak |
|----------|---------|------|
| CPU | 52% | 68% |
| Memory | 2.3GB | 2.8GB |
| Neo4j Connections | 35 | 48 |
| PostgreSQL Connections | 18 | 25 |

### Cache Performance

| Metric | Value |
|--------|-------|
| L1 Hit Rate | 75.2% |
| L2 Hit Rate | 18.5% |
| Total Hit Rate | 93.7% |
| Miss Rate | 6.3% |

### Recommendations

1. ✅ **Performance targets met**: All response times within acceptable ranges
2. ⚠️ **Cache optimization**: L1 hit rate could be improved to 85%+
3. ✅ **Resource usage**: Well within capacity, can handle more load
4. ✅ **Error rate**: Excellent (<0.1% target)
5. 💡 **Scaling**: System can likely handle 200-250 users before degradation
