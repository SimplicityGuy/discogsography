# Tableinator Service

Consumes Discogs data from AMQP queues and stores it in PostgreSQL relational database tables for structured querying and analysis.

## Overview

The tableinator service:

- Consumes parsed Discogs data from RabbitMQ queues
- Stores data as JSONB in PostgreSQL tables
- Implements efficient bulk inserts with psycopg3
- Provides deduplication using SHA256 hashes
- Maintains data integrity with transactions

## Architecture

- **Language**: Python 3.13+
- **Database**: PostgreSQL 18 (with JSONB performance improvements)
- **Message Broker**: RabbitMQ 4.x (quorum queues)
- **Health Port**: 8002
- **Driver**: psycopg3 with binary support

## Configuration

Environment variables:

```bash
# PostgreSQL connection
POSTGRES_HOST=postgres:5432
POSTGRES_USERNAME=discogsography
POSTGRES_PASSWORD=discogsography
POSTGRES_DATABASE=discogsography

# RabbitMQ (individual vars; also supports _FILE variants for Docker secrets)
RABBITMQ_USERNAME=discogsography
RABBITMQ_PASSWORD=discogsography
RABBITMQ_HOST=rabbitmq              # Default: rabbitmq
RABBITMQ_PORT=5672                  # Default: 5672

# Consumer Management (Smart Connection Lifecycle)
CONSUMER_CANCEL_DELAY=300           # Seconds before canceling idle consumers (default: 5 min)
QUEUE_CHECK_INTERVAL=3600           # Seconds between queue checks when idle (default: 1 hr)
STUCK_CHECK_INTERVAL=30             # Seconds between stuck-state checks (default: 30)

# Idle Mode
STARTUP_IDLE_TIMEOUT=30             # Seconds after startup with no messages before idle mode (default: 30)
IDLE_LOG_INTERVAL=300               # Seconds between idle status logs (default: 300)
STARTUP_DELAY=5                     # Seconds to wait for dependent services at startup (default: 5)

# Batch Processing (Enabled by Default)
POSTGRES_BATCH_MODE=true            # Enable batch processing (default: true)
POSTGRES_BATCH_SIZE=100             # Records per batch (default: 100)
POSTGRES_BATCH_FLUSH_INTERVAL=5.0   # Seconds between automatic flushes (default: 5.0)
```

The health server port is fixed at **8002**.

### Smart Connection Lifecycle

The tableinator implements intelligent RabbitMQ connection management:

- **Automatic Closure**: When all queues complete processing, the RabbitMQ connection is automatically closed
- **Periodic Checks**: Every `QUEUE_CHECK_INTERVAL` seconds, briefly connects to check all queues for new messages
- **Auto-Reconnection**: When messages are detected, automatically reconnects and resumes processing
- **Silent When Idle**: Progress logging stops when all queues are complete to reduce log noise

This ensures minimal resource usage while maintaining responsiveness to new data.

### Batch Processing

The tableinator implements intelligent batch processing for optimal PostgreSQL write performance:

- **Automatic Batching**: Messages are collected into batches instead of being processed individually
- **Dual Triggers**: Batches flush when reaching size limit (`POSTGRES_BATCH_SIZE`) OR time interval (`POSTGRES_BATCH_FLUSH_INTERVAL`)
- **Graceful Shutdown**: All pending batches are flushed automatically before service shutdown
- **Performance Gains**: 3-5x faster write throughput compared to individual transactions

**Configuration Examples:**

```bash
# High throughput (initial data load)
POSTGRES_BATCH_SIZE=500
POSTGRES_BATCH_FLUSH_INTERVAL=10.0

# Low latency (real-time updates)
POSTGRES_BATCH_SIZE=10
POSTGRES_BATCH_FLUSH_INTERVAL=1.0

# Disabled (per-message processing)
POSTGRES_BATCH_MODE=false
```

See the [Configuration Guide](../docs/configuration.md#batch-processing-configuration) for detailed tuning guidance.

## Database Schema

All four entity tables (artists, labels, masters, releases) share the same structure:

```sql
CREATE TABLE IF NOT EXISTS <entity_type> (
    data_id VARCHAR PRIMARY KEY,     -- Discogs entity ID
    hash    VARCHAR NOT NULL,        -- SHA256 hash for change detection
    data    JSONB   NOT NULL         -- Complete normalized record
);

CREATE INDEX IF NOT EXISTS idx_<entity>_hash ON <entity> (hash);
```

The `data` column stores the full normalized record from `normalize_record()`, preserving all fields (profile, tracklist, notes, etc.) as JSONB.

### Indexes

- Primary key on `data_id` for each table
- Hash index on `hash` for change detection lookups

## Processing Logic

### Queue Consumption

```python
# Consumes from four queues
queues = ["labels", "artists", "releases", "masters"]
```

### Database Operations

- Uses psycopg3 with JSONB storage for all entity data
- Connection pooling for efficiency

### Upsert Strategy

- SHA256 hash stored alongside each record
- `ON CONFLICT (data_id) DO UPDATE SET hash, data WHERE hash != EXCLUDED.hash`
- Skips writes when the hash is unchanged (no-op update)
- Updates data when the hash differs (content changed)

## Development

### Running Locally

```bash
# Install dependencies
uv sync --extra tableinator

# Run the tableinator
uv run python tableinator/tableinator.py
```

### Running Tests

```bash
# Run tableinator tests
uv run pytest tests/tableinator/ -v

# Run specific test
uv run pytest tests/tableinator/test_tableinator.py -v
```

## Docker

Build and run with Docker:

```bash
# Build
docker build -f tableinator/Dockerfile .

# Run with docker-compose
docker-compose up tableinator
```

## SQL Queries

Example queries for data analysis (using JSONB operators):

```sql
-- Find all releases by title (JSONB field access)
SELECT data_id, data->>'title' AS title, data->>'year' AS year
FROM releases
WHERE data->>'title' ILIKE '%Kind of Blue%';

-- Count records per entity type
SELECT 'artists' AS entity, COUNT(*) FROM artists
UNION ALL
SELECT 'labels', COUNT(*) FROM labels
UNION ALL
SELECT 'masters', COUNT(*) FROM masters
UNION ALL
SELECT 'releases', COUNT(*) FROM releases;

-- Find artists by name
SELECT data_id, data->>'name' AS name
FROM artists
WHERE data->>'name' ILIKE '%Beatles%';
```

## Performance Features

- Batch upserts with psycopg3
- JSONB storage for flexible schema evolution
- Connection pooling
- Hash-based change detection to skip unchanged records

## Monitoring

- Health endpoint at `http://localhost:8002/health`
- Structured JSON logging with visual emoji prefixes
- Insert timing and row count metrics
- Error tracking with detailed messages

## Error Handling

- Transaction rollback on failures
- Message requeuing on processing errors
- Graceful handling of constraint violations
- Comprehensive exception logging with context
