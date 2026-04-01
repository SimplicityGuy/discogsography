# Brainztableinator Service

Consumes MusicBrainz data from AMQP queues and stores it in PostgreSQL relational database tables for structured querying and enrichment alongside Discogs data.

## Overview

The brainztableinator service:

- Consumes parsed MusicBrainz data from RabbitMQ queues
- Stores artists, labels, and releases in the `musicbrainz` PostgreSQL schema
- Records relationships and external links for each entity
- Implements upsert logic with `ON CONFLICT` for idempotent processing
- Maintains data integrity with MBID-based primary keys

## Architecture

- **Language**: Python 3.13+
- **Database**: PostgreSQL 18 (dedicated `musicbrainz` schema)
- **Message Broker**: RabbitMQ 4.x (quorum queues)
- **Health Port**: 8010
- **Driver**: psycopg3 with async connection pooling

## Configuration

Environment variables:

```bash
# PostgreSQL connection
POSTGRES_HOST=postgres
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
```

The health server port is fixed at **8010**.

### Smart Connection Lifecycle

The brainztableinator implements intelligent RabbitMQ connection management:

- **Automatic Closure**: When all queues complete processing, the RabbitMQ connection is automatically closed
- **Periodic Checks**: Every `QUEUE_CHECK_INTERVAL` seconds, briefly connects to check all queues for new messages
- **Auto-Reconnection**: When messages are detected, automatically reconnects and resumes processing
- **Stuck State Recovery**: Detects when consumers die unexpectedly and automatically recovers
- **Silent When Idle**: Progress logging stops when all queues are complete to reduce log noise

## Database Schema

The brainztableinator writes to the `musicbrainz` schema with the following tables:

### Artists

```sql
CREATE TABLE musicbrainz.artists (
    mbid          VARCHAR PRIMARY KEY,
    name          VARCHAR NOT NULL,
    sort_name     VARCHAR,
    mb_type       VARCHAR,
    disambiguation VARCHAR,
    discogs_artist_id INTEGER,
    data          JSONB NOT NULL,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);
```

### Labels

```sql
CREATE TABLE musicbrainz.labels (
    mbid          VARCHAR PRIMARY KEY,
    name          VARCHAR NOT NULL,
    mb_type       VARCHAR,
    disambiguation VARCHAR,
    discogs_label_id INTEGER,
    data          JSONB NOT NULL,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);
```

### Releases

```sql
CREATE TABLE musicbrainz.releases (
    mbid              VARCHAR PRIMARY KEY,
    name              VARCHAR NOT NULL,
    barcode           VARCHAR,
    status            VARCHAR,
    release_group_mbid VARCHAR,
    discogs_release_id INTEGER,
    data              JSONB NOT NULL,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW()
);
```

### Relationships and External Links

```sql
CREATE TABLE musicbrainz.relationships (
    id            SERIAL PRIMARY KEY,
    source_mbid   VARCHAR NOT NULL,
    source_type   VARCHAR NOT NULL,
    target_mbid   VARCHAR NOT NULL,
    rel_type      VARCHAR NOT NULL,
    direction     VARCHAR,
    attributes    JSONB,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE musicbrainz.external_links (
    id          SERIAL PRIMARY KEY,
    mbid        VARCHAR NOT NULL,
    entity_type VARCHAR NOT NULL,
    url         VARCHAR NOT NULL,
    link_type   VARCHAR,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
```

## Data Types

The brainztableinator consumes three MusicBrainz data types (no masters, unlike Discogs):

```python
MUSICBRAINZ_DATA_TYPES = ["artists", "labels", "releases"]
```

## AMQP Exchanges

Subscribes to three fanout exchanges:

- `discogsography-musicbrainz-artists`
- `discogsography-musicbrainz-labels`
- `discogsography-musicbrainz-releases`

Each data type has its own consumer queue with dead letter exchange (DLX) and dead letter queue (DLQ).

## Development

### Running Locally

```bash
# Install dependencies
uv sync --extra brainztableinator

# Run the brainztableinator
uv run python brainztableinator/brainztableinator.py
```

### Running Tests

```bash
# Run brainztableinator tests
just test-brainztableinator

# Run with coverage
uv run pytest tests/brainztableinator/ --cov=brainztableinator --cov-report=term-missing
```

## Docker

Build and run with Docker:

```bash
# Build
docker build -f brainztableinator/Dockerfile .

# Run with docker-compose
docker-compose up brainztableinator
```

## Monitoring

- Health endpoint at `http://localhost:8010/health`
- Structured JSON logging with visual emoji prefixes
- Progress reporting with per-data-type message counts
- Stalled and slow consumer detection
- Idle mode with reduced logging when no messages are flowing

## Error Handling

- Transaction rollback on failures
- Message requeuing on processing errors
- Dead letter queue for messages that fail after 20 delivery attempts
- Automatic recovery from stuck states (consumers died unexpectedly)
- Comprehensive exception logging with context
