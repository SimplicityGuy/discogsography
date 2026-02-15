# 📊 Monitoring & Operations

<div align="center">

**Real-time monitoring, debugging, and operational guides**

[🏠 Back to Main](../README.md) | [📚 Documentation Index](README.md) | [🏛️ Architecture](architecture.md)

</div>

## Overview

Discogsography provides comprehensive monitoring and observability features to track system health, performance, and processing progress. This guide covers dashboards, debugging tools, metrics, and operational procedures.

## 📊 Dashboard

The web-based dashboard provides real-time monitoring of all system components through a WebSocket-powered interface.

### Accessing the Dashboard

```bash
# Start all services
docker-compose up -d

# Access dashboard
open http://localhost:8003
```

### Dashboard Features

#### Service Health Panel

- **Real-time status** of all microservices
- **Health check** endpoints (✅ healthy, ❌ unhealthy)
- **Uptime tracking** for each service
- **Auto-refresh** via WebSocket updates

**Services Monitored**:

- Rust Extractor (http://localhost:8000/health)
- Graphinator (http://localhost:8001/health)
- Tableinator (http://localhost:8002/health)
- Dashboard (http://localhost:8003/health)
- Explore (http://localhost:8006/health, http://localhost:8007/health)

#### Queue Metrics Panel

- **Message counts** per queue (artists, labels, releases, masters)
- **Consumer counts** - active consumers per queue
- **Message rates** - messages/second throughput
- **Queue depth trends** - historical visualization
- **Stall detection** - alerts when queues stop processing

#### Database Statistics Panel

**Neo4j Metrics**:

- Node counts by type (Artist, Label, Release, Master, Genre, Style)
- Relationship counts
- Database size
- Connection pool status

**PostgreSQL Metrics**:

- Record counts per table
- Table sizes and index sizes
- Connection pool status
- Query performance stats

#### Activity Log Panel

- **Recent events** from all services
- **Processing updates** with timestamps
- **Error notifications** with severity levels
- **Filterable by service** and log level
- **Auto-scroll** for live updates

### WebSocket API

The dashboard uses WebSocket for real-time updates:

```javascript
// Connect to WebSocket
const ws = new WebSocket('ws://localhost:8003/ws');

// Receive updates
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(data);
};
```

**Update Types**:

- `service_health`: Service status changes
- `queue_metrics`: Queue depth and consumer updates
- `database_stats`: Database record counts
- `activity_log`: New log entries

## 🔍 Debug Utilities

### Command-Line Monitoring Tools

#### Check Service Errors

```bash
# Check for errors in all service logs
uv run task check-errors

# Or directly with Python
uv run python utilities/check_errors.py
```

**Output**:

- Counts errors by service
- Shows recent error messages
- Groups similar errors
- Highlights critical issues

#### Monitor RabbitMQ Queues

```bash
# Real-time queue monitoring
uv run task monitor

# Or directly with Python
uv run python utilities/monitor_queues.py
```

**Output**:

```
╔════════════════════════════════════════════════════════════╗
║           RabbitMQ Queue Monitor                           ║
╚════════════════════════════════════════════════════════════╝

Queue: artists_queue
├─ Messages: 1,234
├─ Consumers: 2
├─ Rate: 45.2 msg/s
└─ Status: ✅ Processing

Queue: releases_queue
├─ Messages: 5,678
├─ Consumers: 2
├─ Rate: 123.4 msg/s
└─ Status: ✅ Processing

...
```

#### System Monitor Dashboard

```bash
# Comprehensive system monitoring
uv run task system-monitor

# Or directly with Python
uv run python utilities/system_monitor.py
```

**Features**:

- CPU and memory usage per service
- Disk I/O statistics
- Network throughput
- Database connection counts
- Processing rates and bottlenecks

### Service Logs

#### View All Logs

```bash
# All services
uv run task logs

# Or with docker-compose
docker-compose logs -f

# Specific service
docker-compose logs -f extractor-rust
docker-compose logs -f graphinator
docker-compose logs -f tableinator
docker-compose logs -f dashboard
```

#### Filter Logs by Level

```bash
# Errors only
docker-compose logs | grep "ERROR"
docker-compose logs | grep "❌"

# Warnings and errors
docker-compose logs | grep -E "(WARNING|ERROR)"
docker-compose logs | grep -E "(⚠️|❌)"

# Success messages
docker-compose logs | grep "✅"

# Database queries (DEBUG level only)
docker-compose logs dashboard | grep "🔍 Executing"
```

## 📈 Metrics

### Processing Metrics

Each service tracks and logs processing statistics:

#### Extractor Metrics

```
🚀 Starting Python Extractor
📥 Downloading artists data dump
📊 Processed 10,000 artists (1,234 msg/s)
📊 Processed 50,000 artists (1,456 msg/s)
✅ Completed artists processing: 100,000 total
```

**Key Metrics**:

- Records/second processing rate
- Total records processed
- Skipped records (duplicates)
- Failed records
- Download speed (MB/s)

#### Graphinator Metrics

```
🔗 Connected to Neo4j
🐰 Connected to RabbitMQ
🔄 Processing artists queue
📊 Created 1,000 Artist nodes (234 nodes/s)
💾 Updated 50 existing Artist nodes
✅ Completed processing
```

**Key Metrics**:

- Nodes created/updated per second
- Relationships created per second
- Transaction batch sizes
- Queue processing rates
- Deduplication hits

#### Tableinator Metrics

```
🐘 Connected to PostgreSQL
🐰 Connected to RabbitMQ
🔄 Processing releases queue
📊 Inserted 5,000 releases (567 records/s)
⏩ Skipped 123 duplicates
✅ Completed processing
```

**Key Metrics**:

- Records inserted/second
- Duplicate records skipped
- Batch insert sizes
- Index creation time
- Table sizes

### Database Metrics

#### Neo4j Metrics

```cypher
-- Node counts by type
MATCH (n)
RETURN labels(n)[0] as type, count(n) as count
ORDER BY count DESC;

-- Relationship counts
MATCH ()-[r]->()
RETURN type(r) as relationship, count(r) as count
ORDER BY count DESC;

-- Database size
CALL apoc.meta.stats() YIELD labels, relTypesCount, nodeCount, relCount;
```

#### PostgreSQL Metrics

```sql
-- Record counts
SELECT 'artists' as table_name, COUNT(*) FROM artists
UNION ALL SELECT 'labels', COUNT(*) FROM labels
UNION ALL SELECT 'releases', COUNT(*) FROM releases
UNION ALL SELECT 'masters', COUNT(*) FROM masters;

-- Table sizes
SELECT
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;

-- Active connections
SELECT count(*) FROM pg_stat_activity
WHERE datname = 'discogsography';
```

### RabbitMQ Metrics

Access RabbitMQ Management UI:

```bash
open http://localhost:15672
```

Login: `discogsography` / `discogsography`

**Available Metrics**:

- Queue depth (messages ready)
- Consumer count per queue
- Message rates (publish/deliver)
- Connection counts
- Channel counts
- Memory usage

**API Access**:

```bash
# Queue overview
curl -u discogsography:discogsography \
  http://localhost:15672/api/queues

# Specific queue
curl -u discogsography:discogsography \
  http://localhost:15672/api/queues/%2F/artists_queue
```

### Redis Metrics

```bash
# Connect to Redis
docker-compose exec redis redis-cli

# Get info
INFO stats
INFO memory
INFO keyspace

# Monitor commands
MONITOR

# Get key count
DBSIZE

# Check specific keys
KEYS discovery:*
TTL discovery:genre_trends:Jazz
```

## 🔧 Health Checks

### Service Health Endpoints

All services expose HTTP health check endpoints:

```bash
# Rust Extractor
curl http://localhost:8000/health
# Response: {"status": "healthy"}

# Graphinator
curl http://localhost:8001/health
# Response: {"status": "healthy"}

# Tableinator
curl http://localhost:8002/health
# Response: {"status": "healthy"}

# Dashboard
curl http://localhost:8003/health
# Response: {"status": "healthy"}

# Explore
curl http://localhost:8007/health
# Response: {"status": "healthy"}
```

### Automated Health Monitoring

```bash
#!/bin/bash
# check-all-health.sh

services=(
  "Rust Extractor:8000"
  "Graphinator:8001"
  "Tableinator:8002"
  "Dashboard:8003"
  "Explore:8007"
)

for service in "${services[@]}"; do
  name="${service%%:*}"
  port="${service##*:}"

  response=$(curl -s http://localhost:$port/health)
  if [[ $response == *"healthy"* ]]; then
    echo "✅ $name is healthy"
  else
    echo "❌ $name is unhealthy"
  fi
done
```

### Database Health Checks

**Neo4j**:

```bash
# Check connectivity
curl http://localhost:7474

# Query test
echo "RETURN 1 as test;" | \
  cypher-shell -u neo4j -p discogsography
```

**PostgreSQL**:

```bash
# Check connectivity
PGPASSWORD=discogsography psql \
  -h localhost -p 5433 -U discogsography \
  -d discogsography -c "SELECT 1;"
```

**RabbitMQ**:

```bash
# Check management API
curl -u discogsography:discogsography \
  http://localhost:15672/api/overview
```

## ⚠️ Alerts and Notifications

### Stall Detection

The dashboard automatically detects when processing stalls:

**Conditions**:

- Queue has messages but no consumption for 5+ minutes
- Consumer count is 0 but messages exist
- Message rate drops to 0 unexpectedly

**Actions**:

- Alert displayed on dashboard
- Log entry with ⚠️ emoji
- Optional webhook notification (configure in dashboard code)

### Error Tracking

Errors are automatically tracked and reported:

```bash
# Recent errors across all services
uv run task check-errors

# Errors by service
docker-compose logs graphinator | grep "❌"

# Critical errors
docker-compose logs | grep "CRITICAL"
```

### Custom Alerts

Extend the dashboard for custom alerts:

```python
# dashboard/dashboard.py

async def check_custom_condition():
    """Custom alert condition"""
    if some_metric > threshold:
        await broadcast_alert({
            "type": "custom_alert",
            "severity": "warning",
            "message": "Custom condition triggered"
        })
```

## 🐛 Debugging Guide

### Step 1: Check Service Health

```bash
# Health check all services
./scripts/check-all-health.sh

# Or individually
curl http://localhost:8000/health  # Rust Extractor
curl http://localhost:8001/health  # Graphinator
curl http://localhost:8002/health  # Tableinator
curl http://localhost:8003/health  # Dashboard
curl http://localhost:8006/health  # Explore (service port)
curl http://localhost:8007/health  # Explore (health check port)
```

### Step 2: Enable Debug Logging

```bash
# Set LOG_LEVEL environment variable
export LOG_LEVEL=DEBUG

# Restart services
docker-compose down
docker-compose up -d

# Or for specific service
LOG_LEVEL=DEBUG uv run python dashboard/dashboard.py
```

**Debug Level Includes**:

- Database query logging with parameters
- Internal state transitions
- Cache hits/misses
- Message processing details
- Connection lifecycle events

### Step 3: Monitor Real-time Logs

```bash
# All services
docker-compose logs -f

# Specific service with timestamp
docker-compose logs -f --timestamps graphinator

# Filter for errors
docker-compose logs -f | grep -E "(ERROR|❌)"
```

### Step 4: Check Queue Status

```bash
# RabbitMQ management UI
open http://localhost:15672

# Or use CLI monitoring
uv run task monitor
```

**Look for**:

- Messages accumulating (consumers not keeping up)
- Zero consumers (service not connected)
- High unacked count (processing errors)

### Step 5: Verify Database Connectivity

```bash
# Neo4j
curl http://localhost:7474

# PostgreSQL
PGPASSWORD=discogsography psql -h localhost -p 5433 \
  -U discogsography -d discogsography -c "SELECT 1;"
```

### Step 6: Analyze Performance

```bash
# System monitoring
uv run task system-monitor

# Database query performance (Neo4j)
MATCH (n) RETURN count(n);
PROFILE MATCH (a:Artist {name: "Pink Floyd"}) RETURN a;

# PostgreSQL query performance
EXPLAIN ANALYZE
SELECT data FROM artists WHERE data->>'name' = 'Pink Floyd';
```

## 📝 Logging Configuration

### Log Levels

Set `LOG_LEVEL` environment variable:

| Level      | Use Case          | Output                      |
| ---------- | ----------------- | --------------------------- |
| `DEBUG`    | Development       | All logs + query details    |
| `INFO`     | Production        | Normal operations (default) |
| `WARNING`  | Production alerts | Warnings and errors only    |
| `ERROR`    | Critical only     | Errors only                 |
| `CRITICAL` | Emergencies       | Critical errors only        |

### Log Format

All services use consistent logging:

```
%(asctime)s - {service_name} - %(name)s - %(levelname)s - %(message)s
```

Example:

```
2025-01-15 10:30:45 - Graphinator - graphinator - INFO - 🚀 Starting service
2025-01-15 10:30:46 - Graphinator - graphinator - INFO - 🔗 Connected to Neo4j
2025-01-15 10:30:47 - Graphinator - graphinator - INFO - 🐰 Connected to RabbitMQ
```

See [Logging Guide](logging-guide.md) for complete logging documentation.

## 🎯 Performance Monitoring

### Processing Rates

Track records/second for each service:

```bash
# Watch logs for processing stats
docker-compose logs -f | grep "📊"

# Expected rates
# - Rust Extractor: 20,000-400,000+ records/s
# - Graphinator: 1,000-2,000 records/s
# - Tableinator: 3,000-5,000 records/s
```

### Resource Usage

```bash
# Docker stats
docker stats

# Specific service
docker stats discogsography-graphinator-1

# System monitor utility
uv run task system-monitor
```

### Database Performance

**Neo4j**:

```cypher
-- Query performance profiling
PROFILE MATCH (a:Artist)-[:BY]-(r:Release)
WHERE a.name = "Pink Floyd"
RETURN r.title, r.year;

-- Slow query log (check logs)
docker-compose logs neo4j | grep "slow query"
```

**PostgreSQL**:

```sql
-- Active queries
SELECT pid, query, state, query_start
FROM pg_stat_activity
WHERE datname = 'discogsography'
AND state = 'active';

-- Slow queries (requires pg_stat_statements extension)
SELECT query, mean_exec_time, calls
FROM pg_stat_statements
ORDER BY mean_exec_time DESC
LIMIT 10;
```

## Related Documentation

- [Troubleshooting Guide](troubleshooting.md) - Common issues and solutions
- [Performance Guide](performance-guide.md) - Performance optimization
- [Logging Guide](logging-guide.md) - Detailed logging documentation
- [Architecture Overview](architecture.md) - System architecture
- [Database Resilience](database-resilience.md) - Connection patterns

______________________________________________________________________

**Last Updated**: 2025-01-15
