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
- **Database**: Neo4j 5.x
- **Message Broker**: RabbitMQ (AMQP)
- **Health Port**: 8001
- **Processing**: Batch transactions for performance

## Configuration

Environment variables:

```bash
# Service configuration
HEALTH_CHECK_PORT=8001              # Health check endpoint port

# Neo4j connection
NEO4J_ADDRESS=neo4j:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=discogsography

# RabbitMQ
AMQP_CONNECTION=amqp://discogsography:discogsography@rabbitmq:5672
```

## Graph Data Model

### Node Types

1. **Label** - Record labels

   - Properties: id, name, profile, urls, hash
   - Relationships: RELEASED (to releases)

1. **Artist** - Musical artists

   - Properties: id, name, real_name, profile, urls, hash
   - Relationships: MEMBER_OF, COLLABORATED_WITH, PERFORMED_ON

1. **Release** - Album/single releases

   - Properties: id, title, year, country, genres, styles, hash
   - Relationships: RELEASED_BY, PERFORMED_BY, VARIANT_OF

1. **Master** - Master recordings

   - Properties: id, title, year, genres, styles, hash
   - Relationships: HAS_RELEASE, MAIN_RELEASE

### Relationship Types

- `RELEASED` - Label released a recording
- `PERFORMED_ON` - Artist performed on a release
- `MEMBER_OF` - Artist is member of a group
- `COLLABORATED_WITH` - Artists collaborated
- `VARIANT_OF` - Release is variant of master
- `HAS_RELEASE` - Master has multiple releases

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
// Find all releases by a label
MATCH (l:Label {name: "Blue Note"})-[:RELEASED]->(r:Release)
RETURN r.title, r.year
ORDER BY r.year

// Find artist collaborations
MATCH (a1:Artist)-[:COLLABORATED_WITH]->(a2:Artist)
RETURN a1.name, a2.name
LIMIT 25

// Find all variants of a master recording
MATCH (m:Master {title: "Kind of Blue"})-[:HAS_RELEASE]->(r:Release)
RETURN r.title, r.country, r.year
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
