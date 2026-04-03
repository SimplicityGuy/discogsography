# Brainzgraphinator Service

Consumes MusicBrainz data from AMQP queues and enriches existing Neo4j knowledge graph nodes with MusicBrainz metadata and relationship edges.

## Overview

The brainzgraphinator service:

- Consumes parsed MusicBrainz data from RabbitMQ queues
- Enriches existing Discogs nodes with `mb_`-prefixed properties (type, gender, dates, area, disambiguation)
- Creates 8 new relationship edge types between Discogs-matched entities
- All MB-sourced edges carry `source: 'musicbrainz'` for provenance tracking
- Skips entities without Discogs match (stored in PostgreSQL by brainztableinator)

## Architecture

- **Language**: Python 3.13+
- **Database**: Neo4j 5.x (enriches existing Discogs graph)
- **Message Broker**: RabbitMQ 4.x (quorum queues)
- **Health Port**: 8011
- **Driver**: neo4j async driver with retry and resilience

## Configuration

Environment variables:

```bash
# Neo4j connection
NEO4J_HOST=neo4j
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=neo4j

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

The health server port is fixed at **8011**.

### Smart Connection Lifecycle

The brainzgraphinator implements intelligent RabbitMQ connection management:

- **Automatic Closure**: When all queues complete processing, the RabbitMQ connection is automatically closed
- **Periodic Checks**: Every `QUEUE_CHECK_INTERVAL` seconds, briefly connects to check all queues for new messages
- **Auto-Reconnection**: When messages are detected, automatically reconnects and resumes processing
- **Stuck State Recovery**: Detects when consumers die unexpectedly and automatically recovers
- **Silent When Idle**: Progress logging stops when all queues are complete to reduce log noise

## Metadata Enrichment

The brainzgraphinator enriches existing Discogs nodes with MusicBrainz properties:

### Artist Properties

| Property            | Description                                  |
| ------------------- | -------------------------------------------- |
| `mbid`              | MusicBrainz identifier                       |
| `mb_type`           | Artist type (person, group, orchestra, etc.) |
| `mb_gender`         | Gender (for person type)                     |
| `mb_begin_date`     | Career/life begin date                       |
| `mb_end_date`       | Career/life end date                         |
| `mb_area`           | Primary area                                 |
| `mb_begin_area`     | Begin area                                   |
| `mb_end_area`       | End area                                     |
| `mb_disambiguation` | Disambiguation comment                       |

### Label Properties

| Property        | Description            |
| --------------- | ---------------------- |
| `mbid`          | MusicBrainz identifier |
| `mb_type`       | Label type             |
| `mb_label_code` | Label code             |
| `mb_begin_date` | Founded date           |
| `mb_end_date`   | Closed date            |
| `mb_area`       | Geographic area        |

### Release Properties

| Property     | Description            |
| ------------ | ---------------------- |
| `mbid`       | MusicBrainz identifier |
| `mb_barcode` | Barcode                |
| `mb_status`  | Release status         |

## Relationship Edges

Creates new relationship edges between Discogs-matched entities. Both source and target must have a Discogs match for the edge to be created.

| MB Relationship Type | Neo4j Edge Type                   |
| -------------------- | --------------------------------- |
| member of band       | `MEMBER_OF` (enriched with dates) |
| collaboration        | `COLLABORATED_WITH`               |
| teacher              | `TAUGHT`                          |
| tribute              | `TRIBUTE_TO`                      |
| founder              | `FOUNDED`                         |
| supporting musician  | `SUPPORTED`                       |
| subgroup             | `SUBGROUP_OF`                     |
| artist rename        | `RENAMED_TO`                      |

All relationship edges include `source: 'musicbrainz'` for provenance tracking.

### Design Decisions

- **Discogs-matched entities only**: Entities without a Discogs URL in the MusicBrainz data are skipped entirely in Neo4j. They are stored in PostgreSQL by brainztableinator for future use.
- **Both sides required for edges**: Relationship edges are only created when both the source and target entity have Discogs IDs in our graph.
- **`mb_` prefix**: All MusicBrainz-sourced properties use the `mb_` prefix (e.g., `mb_type`, `mb_gender`) to clearly distinguish from Discogs-sourced data. The `mbid` property is the exception.

### Example Cypher Queries

```cypher
-- Find artists enriched with MusicBrainz data
MATCH (a:Artist) WHERE a.mbid IS NOT NULL
RETURN a.name, a.mbid, a.mb_type, a.mb_area

-- Find MusicBrainz-sourced relationships
MATCH (a:Artist)-[r {source: 'musicbrainz'}]->(b:Artist)
RETURN a.name, type(r), b.name

-- Find collaborations
MATCH (a:Artist)-[:COLLABORATED_WITH]->(b:Artist)
RETURN a.name, b.name
```

## Data Types

The brainzgraphinator consumes four MusicBrainz data types (no masters, unlike Discogs):

```python
MUSICBRAINZ_DATA_TYPES = ["artists", "labels", "release-groups", "releases"]
```

## AMQP Exchanges

Subscribes to four fanout exchanges:

- `discogsography-musicbrainz-artists`
- `discogsography-musicbrainz-labels`
- `discogsography-musicbrainz-release-groups`
- `discogsography-musicbrainz-releases`

Each data type has its own consumer queue with dead letter exchange (DLX) and dead letter queue (DLQ).

## Development

### Running Locally

```bash
# Install dependencies
uv sync --extra brainzgraphinator

# Run the brainzgraphinator
uv run python brainzgraphinator/brainzgraphinator.py
```

### Running Tests

```bash
# Run brainzgraphinator tests
just test-brainzgraphinator

# Run with coverage
uv run pytest tests/brainzgraphinator/ --cov=brainzgraphinator --cov-report=term-missing
```

## Docker

Build and run with Docker:

```bash
# Build
docker build -f brainzgraphinator/Dockerfile .

# Run with docker-compose
docker-compose up brainzgraphinator
```

## Monitoring

- Health endpoint at `http://localhost:8011/health`
- Structured JSON logging with visual emoji prefixes
- Progress reporting with per-data-type message counts
- Enrichment stats tracking (entities enriched, skipped, relationships created)
- Stalled and slow consumer detection
- Idle mode with reduced logging when no messages are flowing

## Error Handling

- Idempotent writes: `MATCH...SET` for metadata, `MERGE` for edges — safe for re-import
- Message requeuing on Neo4j transient errors (ServiceUnavailable, SessionExpired)
- Dead letter queue for messages that fail after 20 delivery attempts
- Automatic recovery from stuck states (consumers died unexpectedly)
- Comprehensive exception logging with context
