# Graphinator Service

Consumes Discogs data from AMQP queues and stores it in a Neo4j graph database, creating rich relationships between music entities.

## Overview

The graphinator service:

- Consumes parsed Discogs data from RabbitMQ queues
- Creates nodes and relationships in Neo4j graph database
- Models complex music industry relationships
- Implements efficient batch processing
- Provides deduplication using SHA256 hashes

## Architecture

- **Language**: Python 3.13+
- **Database**: Neo4j 2026 (calendar versioning)
- **Message Broker**: RabbitMQ 4.x (quorum queues)
- **Health Port**: 8001
- **Processing**: Batch transactions for performance

## Configuration

Environment variables:

```bash
# Neo4j connection
NEO4J_HOST=neo4j:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=discogsography

# RabbitMQ (also supports _FILE variants for Docker secrets)
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

# Logging
LOG_LEVEL=INFO                      # Logging level (default: INFO)

# Batch Processing (Enabled by Default)
NEO4J_BATCH_MODE=true               # Enable batch processing (default: true)
NEO4J_BATCH_SIZE=100                # Records per batch (default: 100)
NEO4J_BATCH_FLUSH_INTERVAL=5.0      # Seconds between automatic flushes (default: 5.0)
```

The health server port is fixed at **8001**.

### Smart Connection Lifecycle

The graphinator implements intelligent RabbitMQ connection management:

- **Automatic Closure**: When all queues complete processing, the RabbitMQ connection is automatically closed
- **Periodic Checks**: Every `QUEUE_CHECK_INTERVAL` seconds, briefly connects to check all queues for new messages
- **Auto-Reconnection**: When messages are detected, automatically reconnects and resumes processing
- **Silent When Idle**: Progress logging stops when all queues are complete to reduce log noise

This ensures minimal resource usage while maintaining responsiveness to new data.

### Batch Processing

The graphinator implements intelligent batch processing for optimal Neo4j write performance:

- **Automatic Batching**: Messages are collected into batches instead of being processed individually
- **Dual Triggers**: Batches flush when reaching size limit (`NEO4J_BATCH_SIZE`) OR time interval (`NEO4J_BATCH_FLUSH_INTERVAL`)
- **Graceful Shutdown**: All pending batches are flushed automatically before service shutdown
- **Performance Gains**: 3-5x faster write throughput compared to individual transactions

**Configuration Examples:**

```bash
# High throughput (initial data load)
NEO4J_BATCH_SIZE=500
NEO4J_BATCH_FLUSH_INTERVAL=10.0

# Low latency (real-time updates)
NEO4J_BATCH_SIZE=10
NEO4J_BATCH_FLUSH_INTERVAL=1.0

# Disabled (per-message processing)
NEO4J_BATCH_MODE=false
```

See the [Configuration Guide](../docs/configuration.md#batch-processing-configuration) for detailed tuning guidance.

## Graph Data Model

### Node Types

1. **Artist** - Musical artists

   - Properties: id, name, resource_url, releases_url, sha256
   - Relationships: MEMBER_OF (to band), ALIAS_OF (to primary)

1. **Label** - Record labels

   - Properties: id, name, sha256, release_count\*, artist_count\*, genre_count\*
   - Relationships: SUBLABEL_OF (to parent label)
   - \*Pre-computed by `compute_genre_style_stats()` (see [Pre-Computed Node Properties](#-pre-computed-node-properties))

1. **Release** - Album/single releases

   - Properties: id, title, year, formats, sha256
   - Relationships: BY (to Artist), ON (to Label), DERIVED_FROM (to Master), IS (to Genre/Style)

1. **Master** - Master recordings

   - Properties: id, title, year, sha256
   - Relationships: BY (to Artist), IS (to Genre/Style)

1. **Genre** - Musical genres

   - Properties: name, release_count\*, artist_count\*, label_count\*, style_count\*, first_year\*
   - \*Pre-computed by `compute_genre_style_stats()` (see [Pre-Computed Node Properties](#-pre-computed-node-properties))

1. **Style** - Musical styles (sub-genres)

   - Properties: name, release_count\*, artist_count\*, label_count\*, genre_count\*, first_year\*
   - Relationships: PART_OF (to Genre)
   - \*Pre-computed by `compute_genre_style_stats()` (see [Pre-Computed Node Properties](#-pre-computed-node-properties))

1. **User** - Authenticated Discogs users (created by API syncer, not graphinator)

   - Properties: id
   - Relationships: COLLECTED (to Release), WANTS (to Release)

### Relationship Types

#### Created by Graphinator

- `BY` - Release or Master performed by an artist
- `ON` - Release on a label
- `DERIVED_FROM` - Release is a pressing of a master recording
- `IS` - Release or Master classified as a genre or style
- `MEMBER_OF` - Artist is member of a group/band
- `ALIAS_OF` - Artist is an alias of another artist
- `SUBLABEL_OF` - Label is a sublabel of a parent label
- `PART_OF` - Style belongs to a genre

#### Created by API Syncer

- `COLLECTED` - User has this release in their collection
- `WANTS` - User wants this release

## Processing Logic

### Queue Consumption

```python
# Consumes from four queues
queues = ["labels", "artists", "releases", "masters"]
```

### Transaction Management

- Uses explicit transactions for data integrity
- Batch processing for performance
- Automatic rollback on errors
- Connection pooling for efficiency

### Deduplication

- SHA256 hash stored on each node
- Skip processing if hash already exists
- Ensures idempotent operations

### 🧹 Post-Extraction Cleanup

After all queues have been consumed, the graphinator performs cleanup and enrichment steps:

1. **Batch Queue Flushing** — Any remaining messages in batch queues are flushed to ensure no data is left unprocessed
2. **Stub Node Cleanup** — Removes nodes that have no `sha256` property, which are created as side effects of `MERGE` operations when referenced entities (e.g., artists, labels) haven't been ingested yet
3. **Aggregate Stats Computation** — Runs `compute_genre_style_stats()` to pre-compute node properties (see below)

### 📊 Pre-Computed Node Properties

After graph import of releases, the graphinator runs `compute_genre_style_stats()` to set aggregate properties directly on nodes. These pre-computed stats avoid expensive traversal queries at API request time.

**Genre nodes:**

| Property | Description |
|---|---|
| `release_count` | Number of releases classified as this genre |
| `artist_count` | Number of distinct artists with releases in this genre |
| `label_count` | Number of distinct labels with releases in this genre |
| `style_count` | Number of styles associated with this genre |
| `first_year` | Earliest release year for this genre |

**Style nodes:**

| Property | Description |
|---|---|
| `release_count` | Number of releases classified as this style |
| `artist_count` | Number of distinct artists with releases in this style |
| `label_count` | Number of distinct labels with releases in this style |
| `genre_count` | Number of genres associated with this style |
| `first_year` | Earliest release year for this style |

**Label nodes:**

| Property | Description |
|---|---|
| `release_count` | Number of releases on this label |
| `artist_count` | Number of distinct artists on this label |
| `genre_count` | Number of distinct genres across this label's releases |

## Development

### Running Locally

```bash
# Install dependencies
uv sync --extra graphinator

# Run the graphinator
uv run python graphinator/graphinator.py
```

### Running Tests

```bash
# Run graphinator tests
uv run pytest tests/graphinator/ -v

# Run specific test
uv run pytest tests/graphinator/test_graphinator.py -v
```

## Docker

Build and run with Docker:

```bash
# Build
docker build -f graphinator/Dockerfile .

# Run with docker-compose
docker-compose up graphinator
```

## Neo4j Queries

Example Cypher queries for exploring the data:

```cypher
// Find all releases on a label
MATCH (r:Release)-[:ON]->(l:Label {name: "Blue Note"})
RETURN r.title, r.year
ORDER BY r.year

// Find band members
MATCH (member:Artist)-[:MEMBER_OF]->(band:Artist {name: "The Beatles"})
RETURN member.name

// Find all pressings of a master recording
MATCH (r:Release)-[:DERIVED_FROM]->(m:Master {title: "Kind of Blue"})
RETURN r.title, r.year, r.formats
```

## Performance Optimization

- Connection pooling with Neo4j driver
- Batch transactions for bulk inserts
- Index creation on frequently queried properties
- Efficient Cypher queries with proper node matching

## Monitoring

- Health endpoint at `http://localhost:8001/health`
- Structured JSON logging with visual emoji prefixes
- Transaction metrics and timing
- Error tracking with detailed messages

## Error Handling

- Graceful handling of malformed messages
- Transaction rollback on failures
- Message requeuing on processing errors
- Comprehensive exception logging
