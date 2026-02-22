# ⚙️ Configuration Guide

<div align="center">

**Complete configuration reference for all Discogsography services**

[🏠 Back to Main](../README.md) | [📚 Documentation Index](README.md) | [🚀 Quick Start](quick-start.md)

</div>

## Overview

Discogsography uses environment variables for all configuration. This approach provides flexibility for different deployment environments (development, staging, production) without code changes.

## Configuration Methods

### 1. Environment File (.env)

The recommended approach is using a `.env` file:

```bash
# Copy the example file
cp .env.example .env

# Edit with your settings
nano .env
```

### 2. Direct Environment Variables

Export variables in your shell:

```bash
export AMQP_CONNECTION="amqp://discogsography:discogsography@localhost:5672/"
export NEO4J_ADDRESS="bolt://localhost:7687"
# ... other variables
```

### 3. Docker Compose

Override in `docker-compose.yml` or `docker-compose.override.yml`:

```yaml
services:
  dashboard:
    environment:
      - LOG_LEVEL=DEBUG
      - REDIS_URL=redis://redis:6379/0
```

## Core Settings

### RabbitMQ Configuration

| Variable          | Description             | Default                                                | Required |
| ----------------- | ----------------------- | ------------------------------------------------------ | -------- |
| `AMQP_CONNECTION` | RabbitMQ connection URL | `amqp://discogsography:discogsography@localhost:5672/` | Yes      |

**Used By**: All services

**Format**: `amqp://username:password@host:port/vhost`

**Examples**:

```bash
# Local development (matches docker-compose default credentials)
AMQP_CONNECTION="amqp://discogsography:discogsography@localhost:5672/"

# Docker Compose (internal network)
AMQP_CONNECTION="amqp://discogsography:discogsography@rabbitmq:5672//"

# Remote server with vhost
AMQP_CONNECTION="amqp://user:pass@rabbitmq.example.com:5672/discogsography"
```

**Connection Properties**:

- Automatic reconnection on failure
- Heartbeat: 60 seconds
- Connection timeout: 30 seconds
- Prefetch count: 100 (configurable per service)

### Data Storage

| Variable              | Description           | Default         | Required |
| --------------------- | --------------------- | --------------- | -------- |
| `DISCOGS_ROOT`        | Data storage path     | `/discogs-data` | Yes      |
| `PERIODIC_CHECK_DAYS` | Update check interval | `15`            | No       |

**Used By**: Extractor

**DISCOGS_ROOT Details**:

- Must be writable by service user (UID 1000 in Docker)
- Requires ~200GB free space for full dataset
- Contains downloaded XML files and metadata cache

**Directory Structure**:

```
/discogs-data/
├── artists/
│   ├── discogs_20250115_artists.xml.gz
│   └── .metadata_artists.json
├── labels/
│   ├── discogs_20250115_labels.xml.gz
│   └── .metadata_labels.json
├── releases/
│   ├── discogs_20250115_releases.xml.gz
│   └── .metadata_releases.json
└── masters/
    ├── discogs_20250115_masters.xml.gz
    └── .metadata_masters.json
```

**PERIODIC_CHECK_DAYS**:

- How often to check for new data dumps
- Set to `0` to disable automatic checks
- Recommended: `15` (checks twice per month)

## Database Connections

### Neo4j Configuration

| Variable         | Description    | Default                 | Required |
| ---------------- | -------------- | ----------------------- | -------- |
| `NEO4J_ADDRESS`  | Neo4j bolt URL | `bolt://localhost:7687` | Yes      |
| `NEO4J_USERNAME` | Neo4j username | `neo4j`                 | Yes      |
| `NEO4J_PASSWORD` | Neo4j password | (none)                  | Yes      |

**Used By**: Graphinator, Dashboard, Explore

**Connection Details**:

- Protocol: Bolt (binary protocol)
- Default port: 7687
- Connection pool: 50 connections (max)
- Retry logic: Exponential backoff (max 5 attempts)
- Transaction timeout: 60 seconds

**Examples**:

```bash
# Local development
NEO4J_ADDRESS="bolt://localhost:7687"
NEO4J_USERNAME="neo4j"
NEO4J_PASSWORD="password"

# Docker Compose
NEO4J_ADDRESS="bolt://neo4j:7687"
NEO4J_USERNAME="neo4j"
NEO4J_PASSWORD="discogsography"

# Neo4j Aura (cloud)
NEO4J_ADDRESS="bolt+s://xxxxx.databases.neo4j.io:7687"
NEO4J_USERNAME="neo4j"
NEO4J_PASSWORD="your-secure-password"
```

**Security Notes**:

- Use strong passwords in production
- Enable encryption with `bolt+s://` or `bolt+ssc://`
- Consider certificate validation for production
- Rotate credentials regularly

### PostgreSQL Configuration

| Variable            | Description          | Default          | Required |
| ------------------- | -------------------- | ---------------- | -------- |
| `POSTGRES_ADDRESS`  | PostgreSQL host:port | `localhost:5432` | Yes      |
| `POSTGRES_USERNAME` | PostgreSQL username  | `postgres`       | Yes      |
| `POSTGRES_PASSWORD` | PostgreSQL password  | (none)           | Yes      |
| `POSTGRES_DATABASE` | Database name        | `discogsography` | Yes      |

**Used By**: Tableinator, Dashboard

**Connection Details**:

- Protocol: PostgreSQL wire protocol
- Default port: 5432 (mapped to 5433 in Docker)
- Connection pool: 20 connections (max)
- Retry logic: Exponential backoff (max 5 attempts)
- Query timeout: 30 seconds

**Examples**:

```bash
# Local development
POSTGRES_ADDRESS="localhost:5433"
POSTGRES_USERNAME="discogsography"
POSTGRES_PASSWORD="discogsography"
POSTGRES_DATABASE="discogsography"

# Docker Compose
POSTGRES_ADDRESS="postgres:5432"
POSTGRES_USERNAME="discogsography"
POSTGRES_PASSWORD="discogsography"
POSTGRES_DATABASE="discogsography"

# Remote server with SSL
POSTGRES_ADDRESS="db.example.com:5432"
POSTGRES_USERNAME="app_user"
POSTGRES_PASSWORD="secure-password"
POSTGRES_DATABASE="discogsography_prod"
```

**Performance Tuning**:

```bash
# For services using asyncpg
POSTGRES_POOL_MIN=10
POSTGRES_POOL_MAX=20
POSTGRES_COMMAND_TIMEOUT=30
```

### Redis Configuration

| Variable    | Description          | Default                    | Required        |
| ----------- | -------------------- | -------------------------- | --------------- |
| `REDIS_URL` | Redis connection URL | `redis://localhost:6379/0` | Yes (Dashboard) |

**Used By**: Dashboard

**Connection Details**:

- Protocol: Redis protocol
- Default port: 6379
- Database: 0 (default)
- Connection pool: Automatic
- Retry logic: Exponential backoff

**Examples**:

```bash
# Local development
REDIS_URL="redis://localhost:6379/0"

# Docker Compose
REDIS_URL="redis://redis:6379/0"

# With password
REDIS_URL="redis://:password@localhost:6379/0"

# Redis Sentinel
REDIS_URL="redis+sentinel://sentinel1:26379,sentinel2:26379/myservice"
```

**Cache Configuration**:

- Default TTL: 3600 seconds (1 hour)
- Max memory: 256MB (configurable in docker-compose.yml)
- Eviction policy: allkeys-lru
- Persistence: Disabled (cache only)

## Logging Configuration

| Variable    | Description       | Default | Valid Values                                    |
| ----------- | ----------------- | ------- | ----------------------------------------------- |
| `LOG_LEVEL` | Logging verbosity | `INFO`  | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |

**Used By**: All services

**Log Level Behavior**:

| Level      | Output                                    | Use Case               |
| ---------- | ----------------------------------------- | ---------------------- |
| `DEBUG`    | All logs + query details + internal state | Development, debugging |
| `INFO`     | Normal operation logs                     | Production (default)   |
| `WARNING`  | Warnings and errors                       | Production (minimal)   |
| `ERROR`    | Errors only                               | Production (alerts)    |
| `CRITICAL` | Critical errors only                      | Production (severe)    |

**Examples**:

```bash
# Development - see everything
LOG_LEVEL=DEBUG

# Production - normal operation
LOG_LEVEL=INFO

# Production - minimal logging
LOG_LEVEL=WARNING
```

**Debug Level Features**:

- Neo4j query logging with parameters
- PostgreSQL query logging
- RabbitMQ message details
- Cache hit/miss statistics
- Internal state transitions

See [Logging Guide](logging-guide.md) for detailed logging information.

## Consumer Management

| Variable                | Description                             | Default       | Range     |
| ----------------------- | --------------------------------------- | ------------- | --------- |
| `CONSUMER_CANCEL_DELAY` | Seconds before canceling idle consumers | `300` (5 min) | 60-3600   |
| `QUEUE_CHECK_INTERVAL`  | Seconds between queue checks when idle  | `3600` (1 hr) | 300-86400 |
| `STUCK_CHECK_INTERVAL`  | Seconds between stuck-state checks      | `30`          | 5-300     |

**Used By**: Graphinator, Tableinator

**Purpose**: Smart resource management for RabbitMQ connections

**How It Works**:

1. Service processes messages from all queues
1. When all queues are empty for `CONSUMER_CANCEL_DELAY` seconds:
   - Close RabbitMQ connections
   - Stop progress logging
   - Enter "waiting" mode
1. Every `QUEUE_CHECK_INTERVAL` seconds:
   - Briefly connect to RabbitMQ
   - Check all queues for new messages
   - If messages found, restart consumers
1. When new messages detected:
   - Reconnect to RabbitMQ
   - Resume all consumers
   - Resume progress logging

**Configuration Examples**:

```bash
# Aggressive resource saving (testing)
CONSUMER_CANCEL_DELAY=60     # 1 minute
QUEUE_CHECK_INTERVAL=300     # 5 minutes

# Balanced (default)
CONSUMER_CANCEL_DELAY=300    # 5 minutes
QUEUE_CHECK_INTERVAL=3600    # 1 hour

# Conservative (always connected)
CONSUMER_CANCEL_DELAY=3600   # 1 hour
QUEUE_CHECK_INTERVAL=300     # 5 minutes (doesn't matter if rarely triggered)
```

See [Consumer Cancellation](consumer-cancellation.md) for details.

## Batch Processing Configuration

| Variable                        | Description                              | Default | Range      |
| ------------------------------- | ---------------------------------------- | ------- | ---------- |
| `NEO4J_BATCH_MODE`              | Enable batch processing for Neo4j writes | `true`  | true/false |
| `NEO4J_BATCH_SIZE`              | Records per batch for Neo4j              | `500`   | 10-1000    |
| `NEO4J_BATCH_FLUSH_INTERVAL`    | Seconds between automatic flushes        | `2.0`   | 1.0-60.0   |
| `POSTGRES_BATCH_MODE`           | Enable batch processing for PostgreSQL   | `true`  | true/false |
| `POSTGRES_BATCH_SIZE`           | Records per batch for PostgreSQL         | `500`   | 10-1000    |
| `POSTGRES_BATCH_FLUSH_INTERVAL` | Seconds between automatic flushes        | `2.0`   | 1.0-60.0   |

**Used By**: Graphinator (Neo4j), Tableinator (PostgreSQL)

**Purpose**: Improve write performance by batching multiple database operations

**How Batch Processing Works**:

1. Messages are collected into batches instead of being processed individually
1. When batch reaches `BATCH_SIZE` or `BATCH_FLUSH_INTERVAL` expires:
   - All records in batch are written in a single database operation
   - Message acknowledgments are sent after successful write
1. On service shutdown:
   - All pending batches are flushed automatically
   - No data loss occurs during graceful shutdown

**Performance Impact**:

- **Throughput**: 3-5x improvement in write operations per second
- **Database Load**: Fewer transactions, reduced connection overhead
- **Latency**: Slight increase (up to `BATCH_FLUSH_INTERVAL` seconds)
- **Memory**: Increased by approximately `BATCH_SIZE * record_size`

**Configuration Examples**:

```bash
# High throughput (recommended for initial data load)
NEO4J_BATCH_MODE=true
NEO4J_BATCH_SIZE=500
NEO4J_BATCH_FLUSH_INTERVAL=10.0

# Low latency (real-time updates)
NEO4J_BATCH_MODE=true
NEO4J_BATCH_SIZE=10
NEO4J_BATCH_FLUSH_INTERVAL=1.0

# Disabled (per-message processing)
NEO4J_BATCH_MODE=false
# BATCH_SIZE and FLUSH_INTERVAL ignored when disabled
```

**Best Practices**:

- **Initial Load**: Use larger batch sizes (500-1000) for faster initial data loading
- **Real-time Updates**: Use smaller batches (10-50) for lower latency
- **Memory Constrained**: Reduce batch size if memory usage is a concern
- **High Throughput**: Increase flush interval to accumulate more records
- **Testing**: Disable batch mode to debug individual record processing

**Monitoring**:

Batch processing logs provide visibility into performance:

```
🚀 Batch processing enabled (batch_size=500, flush_interval=2.0)
📦 Flushing batch for artists (size=500)
✅ Batch flushed successfully (artists: 500 records in 0.45s)
```

See [Performance Guide](performance-guide.md) for detailed optimization strategies.

## Dashboard Configuration

| Variable                       | Description                                  | Default           | Required |
| ------------------------------ | -------------------------------------------- | ----------------- | -------- |
| `RABBITMQ_MANAGEMENT_USER`     | RabbitMQ management API username             | `discogsography`  | No       |
| `RABBITMQ_MANAGEMENT_PASSWORD` | RabbitMQ management API password             | `discogsography`  | No       |
| `CORS_ORIGINS`                 | Comma-separated list of allowed CORS origins | (none — disabled) | No       |
| `CACHE_WARMING_ENABLED`        | Pre-warm cache on startup                    | `true`            | No       |
| `CACHE_WEBHOOK_SECRET`         | Secret for cache invalidation webhooks       | (none — disabled) | No       |

**Used By**: Dashboard only

**Notes**:

- `RABBITMQ_MANAGEMENT_USER` / `RABBITMQ_MANAGEMENT_PASSWORD` must match the credentials set in RabbitMQ for the management plugin
- `CORS_ORIGINS` is optional; omit it to restrict cross-origin access
- `CACHE_WEBHOOK_SECRET` enables an authenticated endpoint to invalidate cached queries

## Python Version

| Variable         | Description               | Default | Used By       |
| ---------------- | ------------------------- | ------- | ------------- |
| `PYTHON_VERSION` | Python version for builds | `3.13`  | Docker, CI/CD |

**Used By**: Build systems, CI/CD pipelines

**Purpose**: Ensure consistent Python version across environments

**Notes**:

- Minimum supported version: 3.13
- All services tested on Python 3.13+
- Older versions not supported

## Service-Specific Settings

### Schema-Init

```bash
# Required
NEO4J_ADDRESS="bolt://localhost:7687"
NEO4J_USERNAME="neo4j"
NEO4J_PASSWORD="discogsography"
POSTGRES_ADDRESS="localhost:5433"
POSTGRES_USERNAME="discogsography"
POSTGRES_PASSWORD="discogsography"
POSTGRES_DATABASE="discogsography"

# Optional
LOG_LEVEL=INFO
```

**Notes**: Schema-init is a one-shot initialiser — it exits 0 on success and 1 on failure. It has no health check port. In Docker Compose, all dependent services use `condition: service_completed_successfully`. Re-running on an already-initialised database is a no-op (all DDL uses `IF NOT EXISTS`).

### Extractor

```bash
# Required
AMQP_CONNECTION="amqp://discogsography:discogsography@localhost:5672/"
DISCOGS_ROOT="/discogs-data"

# Optional
PERIODIC_CHECK_DAYS=15
LOG_LEVEL=INFO
```

Health check: http://localhost:8000/health

### Graphinator

```bash
# Required
AMQP_CONNECTION="amqp://discogsography:discogsography@localhost:5672/"
NEO4J_ADDRESS="bolt://localhost:7687"
NEO4J_USERNAME="neo4j"
NEO4J_PASSWORD="discogsography"

# Optional - Consumer Management
CONSUMER_CANCEL_DELAY=300
QUEUE_CHECK_INTERVAL=3600
STUCK_CHECK_INTERVAL=30    # Seconds between stuck-state checks

# Optional - Batch Processing (enabled by default)
NEO4J_BATCH_MODE=true
NEO4J_BATCH_SIZE=500
NEO4J_BATCH_FLUSH_INTERVAL=2.0

# Optional - Logging
LOG_LEVEL=INFO
```

Health check: http://localhost:8001/health

### Tableinator

```bash
# Required
AMQP_CONNECTION="amqp://discogsography:discogsography@localhost:5672/"
POSTGRES_ADDRESS="localhost:5433"
POSTGRES_USERNAME="discogsography"
POSTGRES_PASSWORD="discogsography"
POSTGRES_DATABASE="discogsography"

# Optional - Consumer Management
CONSUMER_CANCEL_DELAY=300
QUEUE_CHECK_INTERVAL=3600
STUCK_CHECK_INTERVAL=30    # Seconds between stuck-state checks

# Optional - Batch Processing (enabled by default)
POSTGRES_BATCH_MODE=true
POSTGRES_BATCH_SIZE=500
POSTGRES_BATCH_FLUSH_INTERVAL=2.0

# Optional - Logging
LOG_LEVEL=INFO
```

Health check: http://localhost:8002/health

### Explore

```bash
# Required
NEO4J_ADDRESS="bolt://localhost:7687"
NEO4J_USERNAME="neo4j"
NEO4J_PASSWORD="discogsography"

# Optional
LOG_LEVEL=INFO
```

Health check: http://localhost:8006/health (service), http://localhost:8007/health (health check port)

### Dashboard

```bash
# Required
AMQP_CONNECTION="amqp://discogsography:discogsography@localhost:5672/"
NEO4J_ADDRESS="bolt://localhost:7687"
NEO4J_USERNAME="neo4j"
NEO4J_PASSWORD="discogsography"
POSTGRES_ADDRESS="localhost:5433"
POSTGRES_USERNAME="discogsography"
POSTGRES_PASSWORD="discogsography"
POSTGRES_DATABASE="discogsography"
REDIS_URL="redis://localhost:6379/0"

# Optional - RabbitMQ Management API access
RABBITMQ_MANAGEMENT_USER=discogsography
RABBITMQ_MANAGEMENT_PASSWORD=discogsography

# Optional - CORS
CORS_ORIGINS="http://localhost:8003,http://localhost:8006"  # comma-separated origins

# Optional - Cache
CACHE_WARMING_ENABLED=true         # Pre-warm cache on startup
CACHE_WEBHOOK_SECRET=              # Secret for cache invalidation webhooks

# Optional - Logging
LOG_LEVEL=INFO
```

Health check: http://localhost:8003/health

## Environment Templates

### Development (.env.development)

```bash
# RabbitMQ
AMQP_CONNECTION=amqp://discogsography:discogsography@localhost:5672/

# Neo4j
NEO4J_ADDRESS=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=development

# PostgreSQL
POSTGRES_ADDRESS=localhost:5433
POSTGRES_USERNAME=postgres
POSTGRES_PASSWORD=development
POSTGRES_DATABASE=discogsography_dev

# Redis
REDIS_URL=redis://localhost:6379/0

# Data
DISCOGS_ROOT=/tmp/discogs-data-dev
PERIODIC_CHECK_DAYS=0

# Logging
LOG_LEVEL=DEBUG

# Consumer Management (aggressive for testing)
CONSUMER_CANCEL_DELAY=60
QUEUE_CHECK_INTERVAL=300
```

### Production (.env.production)

```bash
# RabbitMQ
AMQP_CONNECTION=amqp://prod_user:${RABBITMQ_PASSWORD}@rabbitmq.prod.internal:5672/

# Neo4j
NEO4J_ADDRESS=bolt+s://neo4j.prod.internal:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=${NEO4J_PASSWORD}

# PostgreSQL
POSTGRES_ADDRESS=postgres.prod.internal:5432
POSTGRES_USERNAME=discogsography_app
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
POSTGRES_DATABASE=discogsography

# Redis
REDIS_URL=redis://:${REDIS_PASSWORD}@redis.prod.internal:6379/0

# Data
DISCOGS_ROOT=/mnt/data/discogs
PERIODIC_CHECK_DAYS=15

# Logging
LOG_LEVEL=INFO

# Consumer Management
CONSUMER_CANCEL_DELAY=300
QUEUE_CHECK_INTERVAL=3600
```

## Security Best Practices

### Password Management

**Never commit passwords**:

```bash
# ❌ BAD - hardcoded password
NEO4J_PASSWORD=supersecret

# ✅ GOOD - reference to secret
NEO4J_PASSWORD=${NEO4J_PASSWORD}
```

Use secret management systems:

- Docker Secrets
- Kubernetes Secrets
- HashiCorp Vault
- AWS Secrets Manager
- Azure Key Vault

### Connection Encryption

Enable encryption for production:

```bash
# Neo4j with TLS
NEO4J_ADDRESS=bolt+s://neo4j.example.com:7687

# PostgreSQL with SSL (via connection string)
POSTGRES_ADDRESS=postgres.example.com:5432?sslmode=require

# Redis with TLS
REDIS_URL=rediss://:password@redis.example.com:6380/0
```

### Access Control

Use least-privilege principles:

```bash
# ❌ BAD - using admin credentials
NEO4J_USERNAME=admin
POSTGRES_USERNAME=postgres

# ✅ GOOD - dedicated service accounts
NEO4J_USERNAME=discogsography_app
POSTGRES_USERNAME=discogsography_app
```

## Validation and Testing

### Validate Configuration

```bash
# Check if all required variables are set
./scripts/check-config.sh

# Test database connections
./scripts/test-connections.sh
```

### Health Checks

Verify all services are configured correctly:

```bash
# Check all health endpoints
curl http://localhost:8000/health  # Extractor
curl http://localhost:8001/health  # Graphinator
curl http://localhost:8002/health  # Tableinator
curl http://localhost:8003/health  # Dashboard
curl http://localhost:8007/health  # Explore
```

Expected response for all:

```json
{"status": "healthy"}
```

## Troubleshooting

### Common Configuration Issues

**Connection Refused Errors**:

- Check host and port are correct
- Verify service is running
- Check firewall rules
- Wait for service startup (databases can take 30-60s)

**Authentication Failures**:

- Verify username and password
- Check password special characters are properly escaped
- Ensure credentials match database configuration

**Cache Directory Errors**:

- Verify directory exists
- Check write permissions (UID 1000 for Docker)
- Ensure sufficient disk space

**Environment Variables Not Loading**:

- Check `.env` file is in correct location
- Verify no syntax errors in `.env`
- Restart services after changes
- For Docker: rebuild images if needed

See [Troubleshooting Guide](troubleshooting.md) for more solutions.

## Related Documentation

- [Quick Start Guide](quick-start.md) - Get started with default configuration
- [Architecture Overview](architecture.md) - Understand service dependencies
- [Database Resilience](database-resilience.md) - Connection patterns
- [Logging Guide](logging-guide.md) - Logging configuration details
- [Performance Guide](performance-guide.md) - Performance tuning settings

______________________________________________________________________

**Last Updated**: 2026-02-18
