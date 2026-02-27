# ⚙️ Configuration Guide

<div align="center">

**Complete configuration reference for all Discogsography services**

[🏠 Back to Main](../README.md) | [📚 Documentation Index](README.md) | [🚀 Quick Start](quick-start.md)

</div>

## Overview

Discogsography uses environment variables for all configuration. This approach provides flexibility for different deployment environments (development, staging, production) without code changes.

## Configuration Methods

### 1. Environment File (.env) — Development

The recommended approach for local development is a `.env` file:

```bash
# Copy the example file
cp .env.example .env

# Edit with your settings
nano .env
```

> **Production**: Do not use `.env` files with real credentials in production. Use Docker Compose runtime secrets instead — see [Production Secrets](#production-secrets) below.

### 2. Direct Environment Variables — Development

Export variables in your shell:

```bash
export AMQP_CONNECTION="amqp://discogsography:discogsography@localhost:5672/"
export NEO4J_HOST="bolt://localhost:7687"
# ... other variables
```

### 3. Docker Compose Runtime Secrets — Production

In production, credentials are mounted as in-memory tmpfs files via `docker-compose.prod.yml`. Secret values are never visible in `docker inspect`, never written to disk, and flushed when the container stops.

```bash
# Generate secrets once (idempotent)
bash scripts/create-secrets.sh

# Start with production overlay
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

See [Production Secrets](#production-secrets) below and [Docker Security](docker-security.md) for full details.

### 4. Docker Compose Override

Override non-secret settings in `docker-compose.yml` or `docker-compose.override.yml`:

```yaml
services:
  dashboard:
    environment:
      - LOG_LEVEL=DEBUG
      - REDIS_HOST=redis://redis:6379/0
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
| `NEO4J_HOST`  | Neo4j bolt URL | `bolt://localhost:7687` | Yes      |
| `NEO4J_USERNAME` | Neo4j username | `neo4j`                 | Yes      |
| `NEO4J_PASSWORD` | Neo4j password | (none)                  | Yes      |

**Used By**: Graphinator, Dashboard, Explore, Curator

**Connection Details**:

- Protocol: Bolt (binary protocol)
- Default port: 7687
- Connection pool: 50 connections (max)
- Retry logic: Exponential backoff (max 5 attempts)
- Transaction timeout: 60 seconds

**Examples**:

```bash
# Local development
NEO4J_HOST="bolt://localhost:7687"
NEO4J_USERNAME="neo4j"
NEO4J_PASSWORD="password"

# Docker Compose
NEO4J_HOST="bolt://neo4j:7687"
NEO4J_USERNAME="neo4j"
NEO4J_PASSWORD="discogsography"

# Neo4j Aura (cloud)
NEO4J_HOST="bolt+s://xxxxx.databases.neo4j.io:7687"
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
| `POSTGRES_HOST`  | PostgreSQL host:port | `localhost:5432` | Yes      |
| `POSTGRES_USERNAME` | PostgreSQL username  | `postgres`       | Yes      |
| `POSTGRES_PASSWORD` | PostgreSQL password  | (none)           | Yes      |
| `POSTGRES_DATABASE` | Database name        | `discogsography` | Yes      |

**Used By**: Tableinator, Dashboard, API, Curator

**Connection Details**:

- Protocol: PostgreSQL wire protocol
- Default port: 5432 (mapped to 5433 in Docker)
- Connection pool: 20 connections (max)
- Retry logic: Exponential backoff (max 5 attempts)
- Query timeout: 30 seconds

**Examples**:

```bash
# Local development
POSTGRES_HOST="localhost:5433"
POSTGRES_USERNAME="discogsography"
POSTGRES_PASSWORD="discogsography"
POSTGRES_DATABASE="discogsography"

# Docker Compose
POSTGRES_HOST="postgres:5432"
POSTGRES_USERNAME="discogsography"
POSTGRES_PASSWORD="discogsography"
POSTGRES_DATABASE="discogsography"

# Remote server with SSL
POSTGRES_HOST="db.example.com:5432"
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

| Variable    | Description          | Default                    | Required             |
| ----------- | -------------------- | -------------------------- | -------------------- |
| `REDIS_HOST` | Redis connection URL | `redis://localhost:6379/0` | Yes (Dashboard, API) |

**Used By**: Dashboard, API

**Connection Details**:

- Protocol: Redis protocol
- Default port: 6379
- Database: 0 (default)
- Connection pool: Automatic
- Retry logic: Exponential backoff

**Examples**:

```bash
# Local development
REDIS_HOST="redis://localhost:6379/0"

# Docker Compose
REDIS_HOST="redis://redis:6379/0"

# With password
REDIS_HOST="redis://:password@localhost:6379/0"

# Redis Sentinel
REDIS_HOST="redis+sentinel://sentinel1:26379,sentinel2:26379/myservice"
```

**Cache Configuration**:

- Default TTL: 3600 seconds (1 hour)
- Max memory: 256MB (configurable in docker-compose.yml)
- Eviction policy: allkeys-lru
- Persistence: Disabled (cache only)

## JWT Configuration

| Variable             | Description                         | Default | Required           |
| -------------------- | ----------------------------------- | ------- | ------------------ |
| `JWT_SECRET_KEY`     | HMAC-SHA256 signing secret          | (none)  | Yes (API, Curator) |
| `JWT_EXPIRE_MINUTES` | Token lifetime in minutes           | `1440`  | No                 |
| `DISCOGS_USER_AGENT` | User-Agent for Discogs API requests | (none)  | Yes (API, Curator) |

**Used By**: API, Curator

**JWT Details**:

- Algorithm: HS256 (HMAC-SHA256)
- Token format: Standard JWT (`header.body.signature`, base64url-encoded)
- Payload claims: `sub` (user UUID), `email`, `iat`, `exp`
- The same `JWT_SECRET_KEY` must be set in both API and Curator — tokens issued by API are validated locally by Curator

**Security Notes**:

- Use a cryptographically random secret of at least 32 bytes in production
- Rotate the secret to invalidate all existing tokens
- Never log or expose `JWT_SECRET_KEY`
- In production, supply via `JWT_SECRET_KEY_FILE` pointing to a Docker secret file — see [Production Secrets](#production-secrets)

**Examples**:

```bash
# Generate a secure random secret (Linux/macOS)
JWT_SECRET_KEY=$(openssl rand -hex 32)

# Set token lifetime
JWT_EXPIRE_MINUTES=1440   # 24 hours (default)
JWT_EXPIRE_MINUTES=60     # 1 hour (more secure)
JWT_EXPIRE_MINUTES=10080  # 7 days (more convenient)

# Discogs User-Agent (required for Discogs API)
DISCOGS_USER_AGENT="Discogsography/1.0 +https://github.com/SimplicityGuy/discogsography"
```

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

**Used By**: Dashboard only (for `RABBITMQ_MANAGEMENT_USER`, `CACHE_WARMING_ENABLED`, `CACHE_WEBHOOK_SECRET`); `CORS_ORIGINS` is also supported by the API service — see the [API](#api) section above.

**Notes**:

- `RABBITMQ_MANAGEMENT_USER` / `RABBITMQ_MANAGEMENT_PASSWORD` must match the credentials set in RabbitMQ for the management plugin. In production these are supplied via `RABBITMQ_MANAGEMENT_USER_FILE` / `RABBITMQ_MANAGEMENT_PASSWORD_FILE` (Docker secrets)
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

### API

```bash
# Required
POSTGRES_HOST="localhost:5433"
POSTGRES_USERNAME="discogsography"
POSTGRES_PASSWORD="discogsography"
POSTGRES_DATABASE="discogsography"
REDIS_HOST="redis://localhost:6379/0"
JWT_SECRET_KEY="your-secret-key-here"
DISCOGS_USER_AGENT="Discogsography/1.0 +https://github.com/SimplicityGuy/discogsography"

# Required — Discogs OAuth token encryption (Fernet symmetric key)
# Generate with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
# In production, supply via OAUTH_ENCRYPTION_KEY_FILE (Docker secret)
OAUTH_ENCRYPTION_KEY="your-fernet-key-here"

# Optional — CORS origins (comma-separated; omit to disable CORS)
CORS_ORIGINS="http://localhost:8003,http://localhost:8006"

# Optional — snapshot settings
SNAPSHOT_TTL_DAYS=28     # Snapshot expiry in days (default: 28)
SNAPSHOT_MAX_NODES=100   # Max nodes per snapshot (default: 100)

# Optional
JWT_EXPIRE_MINUTES=1440
LOG_LEVEL=INFO
```

Health check: http://localhost:8004/health (service), http://localhost:8005/health (health check port)

**Notes**: After startup, set Discogs app credentials using the `discogs-setup` CLI bundled in the API container:

```bash
docker exec <api-container> discogs-setup \
  --consumer-key YOUR_CONSUMER_KEY \
  --consumer-secret YOUR_CONSUMER_SECRET

# Verify (values are masked)
docker exec <api-container> discogs-setup --show
```

See the [API README](../api/README.md#operator-setup) for full setup instructions.

### Curator

```bash
# Required
POSTGRES_HOST="localhost:5433"
POSTGRES_USERNAME="discogsography"
POSTGRES_PASSWORD="discogsography"
POSTGRES_DATABASE="discogsography"
NEO4J_HOST="bolt://localhost:7687"
NEO4J_USERNAME="neo4j"
NEO4J_PASSWORD="discogsography"
JWT_SECRET_KEY="your-secret-key-here"  # Must match API service
DISCOGS_USER_AGENT="Discogsography/1.0 +https://github.com/SimplicityGuy/discogsography"

# Optional
LOG_LEVEL=INFO
```

Health check: http://localhost:8010/health (service), http://localhost:8011/health (health check port)

**Notes**: Curator validates JWTs locally using the same `JWT_SECRET_KEY` as the API service. It reads Discogs OAuth tokens from the `oauth_tokens` PostgreSQL table, which is populated when users connect their Discogs accounts through the API.

### Schema-Init

```bash
# Required
NEO4J_HOST="bolt://localhost:7687"
NEO4J_USERNAME="neo4j"
NEO4J_PASSWORD="discogsography"
POSTGRES_HOST="localhost:5433"
POSTGRES_USERNAME="discogsography"
POSTGRES_PASSWORD="discogsography"
POSTGRES_DATABASE="discogsography"

# Optional
LOG_LEVEL=INFO
```

**Notes**: Schema-init is a one-shot initializer — it exits 0 on success and 1 on failure. It has no health check port. In Docker Compose, all dependent services use `condition: service_completed_successfully`. Re-running on an already-initialized database is a no-op (all DDL uses `IF NOT EXISTS`).

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
NEO4J_HOST="bolt://localhost:7687"
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
POSTGRES_HOST="localhost:5433"
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
NEO4J_HOST="bolt://localhost:7687"
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
NEO4J_HOST="bolt://localhost:7687"
NEO4J_USERNAME="neo4j"
NEO4J_PASSWORD="discogsography"
POSTGRES_HOST="localhost:5433"
POSTGRES_USERNAME="discogsography"
POSTGRES_PASSWORD="discogsography"
POSTGRES_DATABASE="discogsography"
REDIS_HOST="redis://localhost:6379/0"

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
NEO4J_HOST=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=development

# PostgreSQL
POSTGRES_HOST=localhost:5433
POSTGRES_USERNAME=postgres
POSTGRES_PASSWORD=development
POSTGRES_DATABASE=discogsography_dev

# Redis
REDIS_HOST=redis://localhost:6379/0

# JWT (API + Curator)
JWT_SECRET_KEY=dev-secret-key-not-for-production
JWT_EXPIRE_MINUTES=1440
DISCOGS_USER_AGENT="Discogsography/1.0-dev +https://github.com/SimplicityGuy/discogsography"

# Data
DISCOGS_ROOT=/tmp/discogs-data-dev
PERIODIC_CHECK_DAYS=0

# Logging
LOG_LEVEL=DEBUG

# Consumer Management (aggressive for testing)
CONSUMER_CANCEL_DELAY=60
QUEUE_CHECK_INTERVAL=300
```

### Production Secrets

In production, all sensitive credentials are delivered as Docker Compose runtime secrets — never as plain environment variables. The `docker-compose.prod.yml` overlay wires everything up automatically.

**Step 1 — Bootstrap secrets** (run once; safe to re-run, skips existing files):

```bash
bash scripts/create-secrets.sh
```

This creates `secrets/` with these files (all `chmod 600`, directory `chmod 700`):

```
secrets/
├── jwt_secret_key.txt        # openssl rand -hex 32
├── neo4j_password.txt        # openssl rand -base64 24
├── oauth_encryption_key.txt  # Fernet.generate_key()
├── postgres_password.txt     # openssl rand -base64 24
├── postgres_username.txt         # discogsography
├── rabbitmq_password.txt     # openssl rand -base64 24
└── rabbitmq_username.txt         # discogsography
```

See `secrets.example/` for reference placeholders and generation commands.

**Step 2 — Set non-secret production environment** (safe to commit, no credentials):

```bash
# RabbitMQ
AMQP_CONNECTION=amqp://discogsography:@rabbitmq:5672/

# Neo4j
NEO4J_HOST=bolt+s://neo4j.prod.internal:7687

# PostgreSQL
POSTGRES_HOST=postgres.prod.internal:5432
POSTGRES_DATABASE=discogsography

# Redis
REDIS_HOST=redis://redis:6379/0

# JWT (optional non-secret settings)
JWT_EXPIRE_MINUTES=1440
DISCOGS_USER_AGENT="Discogsography/1.0 +https://github.com/SimplicityGuy/discogsography"

# Data
DISCOGS_ROOT=/mnt/data/discogs
PERIODIC_CHECK_DAYS=15

# Logging
LOG_LEVEL=INFO

# Consumer Management
CONSUMER_CANCEL_DELAY=300
QUEUE_CHECK_INTERVAL=3600
```

**Step 3 — Start with the production overlay**:

```bash
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Credentials are mounted at `/run/secrets/<name>` inside each container and read automatically. See [Docker Security](docker-security.md) for the full secrets table and Neo4j entrypoint details.

## Security Best Practices

### Password Management

**Never commit credentials**:

```bash
# ❌ BAD — hardcoded password in any committed file
NEO4J_PASSWORD=supersecret

# ✅ GOOD — Docker Compose runtime secret (production)
# secrets/neo4j_password.txt contains the value, mounted at /run/secrets/neo4j_password
# docker-compose.prod.yml wires it up automatically via get_secret()
```

For production deployments, use `docker-compose.prod.yml` with `scripts/create-secrets.sh`. For other platforms:

- **Kubernetes**: Kubernetes Secrets or an external secrets operator
- **HashiCorp Vault**: Vault Agent Injector or the Vault CSI provider
- **AWS**: Secrets Manager with the AWS Secrets and Configuration Provider
- **Azure**: Azure Key Vault with the CSI Secrets Store driver

### Connection Encryption

Enable encryption for production:

```bash
# Neo4j with TLS
NEO4J_HOST=bolt+s://neo4j.example.com:7687

# PostgreSQL with SSL (via connection string)
POSTGRES_HOST=postgres.example.com:5432?sslmode=require

# Redis with TLS
REDIS_HOST=rediss://:password@redis.example.com:6380/0
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
curl http://localhost:8005/health  # API (health check port)
curl http://localhost:8007/health  # Explore
curl http://localhost:8011/health  # Curator (health check port)
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
- [Docker Security](docker-security.md) - Runtime secrets, container hardening, and production setup
- [Architecture Overview](architecture.md) - Understand service dependencies
- [Database Resilience](database-resilience.md) - Connection patterns
- [Logging Guide](logging-guide.md) - Logging configuration details
- [Performance Guide](performance-guide.md) - Performance tuning settings

______________________________________________________________________

**Last Updated**: 2026-02-25
