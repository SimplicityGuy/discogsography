# Tableinator Service

Consumes Discogs data from AMQP queues and stores it in PostgreSQL relational database tables for structured querying and analysis.

## Overview

The tableinator service:

- Consumes parsed Discogs data from RabbitMQ queues
- Stores data in normalized PostgreSQL tables
- Implements efficient bulk inserts with psycopg3
- Provides deduplication using SHA256 hashes
- Maintains data integrity with transactions

## Architecture

- **Language**: Python 3.13+
- **Database**: PostgreSQL 16
- **Message Broker**: RabbitMQ (AMQP)
- **Health Port**: 8002
- **Driver**: psycopg3 with binary support

## Configuration

Environment variables:

```bash
# Service configuration
HEALTH_CHECK_PORT=8002              # Health check endpoint port

# PostgreSQL connection
POSTGRES_ADDRESS=postgres:5432
POSTGRES_USERNAME=discogsography
POSTGRES_PASSWORD=discogsography
POSTGRES_DATABASE=discogsography

# RabbitMQ
AMQP_CONNECTION=amqp://discogsography:discogsography@rabbitmq:5672
```

## Database Schema

### Tables

1. **labels**

   ```sql
   - id: INTEGER PRIMARY KEY
   - name: TEXT
   - profile: TEXT
   - urls: TEXT[]
   - hash: TEXT UNIQUE
   ```

1. **artists**

   ```sql
   - id: INTEGER PRIMARY KEY
   - name: TEXT
   - real_name: TEXT
   - profile: TEXT
   - urls: TEXT[]
   - aliases: TEXT[]
   - hash: TEXT UNIQUE
   ```

1. **releases**

   ```sql
   - id: INTEGER PRIMARY KEY
   - title: TEXT
   - year: INTEGER
   - country: TEXT
   - genres: TEXT[]
   - styles: TEXT[]
   - formats: JSONB
   - tracklist: JSONB
   - hash: TEXT UNIQUE
   ```

1. **masters**

   ```sql
   - id: INTEGER PRIMARY KEY
   - title: TEXT
   - year: INTEGER
   - genres: TEXT[]
   - styles: TEXT[]
   - main_release: INTEGER
   - hash: TEXT UNIQUE
   ```

### Indexes

- Primary key indexes on all `id` columns
- Unique indexes on all `hash` columns for deduplication
- Additional indexes on frequently queried columns

## Processing Logic

### Queue Consumption

```python
# Consumes from four queues
queues = ["labels", "artists", "releases", "masters"]
```

### Database Operations

- Uses psycopg3's native support for PostgreSQL arrays
- JSONB columns for flexible nested data (formats, tracklist)
- Prepared statements for performance
- Connection pooling for efficiency

### Deduplication

- SHA256 hash stored in each table
- `ON CONFLICT (hash) DO NOTHING` for idempotent inserts
- Ensures no duplicate processing

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

Example queries for data analysis:

```sql
-- Find most prolific labels
SELECT name, COUNT(*) as release_count
FROM labels l
JOIN releases r ON l.id = r.label_id
GROUP BY l.name
ORDER BY release_count DESC
LIMIT 10;

-- Find releases by genre and year
SELECT title, year, genres
FROM releases
WHERE 'Jazz' = ANY(genres)
  AND year BETWEEN 1950 AND 1960
ORDER BY year;

-- Find artists with most aliases
SELECT name, array_length(aliases, 1) as alias_count
FROM artists
WHERE aliases IS NOT NULL
ORDER BY alias_count DESC
LIMIT 20;
```

## Performance Features

- Bulk inserts with psycopg3's `execute_batch`
- PostgreSQL array support for multi-valued fields
- JSONB for flexible schema evolution
- Connection pooling and prepared statements

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
