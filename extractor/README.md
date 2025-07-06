# Extractor Service

Downloads and processes Discogs database exports, publishing parsed data to AMQP queues for consumption by other services.

## Overview

The extractor service:

- Downloads Discogs XML database exports from Amazon S3
- Validates file checksums for data integrity
- Parses XML data and converts to JSON
- Publishes parsed records to RabbitMQ queues
- Implements periodic checking for new data updates
- Tracks processed records to avoid duplicates

## Architecture

- **Language**: Python 3.13+
- **Data Source**: Discogs data dumps from S3
- **Message Broker**: RabbitMQ (AMQP)
- **Health Port**: 8000
- **Check Interval**: 15 days (configurable)

## Configuration

Environment variables:

```bash
# Service configuration
HEALTH_CHECK_PORT=8000              # Health check endpoint port
PERIODIC_CHECK_DAYS=15              # Days between checking for new data

# Storage
DISCOGS_ROOT=/discogs-data          # Directory for downloaded files

# RabbitMQ
AMQP_CONNECTION=amqp://discogsography:discogsography@rabbitmq:5672
```

## Data Processing

### Supported Data Types

The extractor processes four types of Discogs data:

1. **Labels** - Record labels and companies
1. **Artists** - Musical artists and groups
1. **Releases** - Individual album/single releases
1. **Masters** - Master recordings (main releases)

### Download Process

1. Fetches latest file listings from Discogs S3 bucket
1. Compares checksums with previously downloaded files
1. Downloads only new or updated files
1. Validates checksums after download
1. Extracts compressed files (`.gz` format)

### Parsing Process

1. Streams XML files to handle large datasets efficiently
1. Converts XML records to JSON format
1. Computes SHA256 hash for each record for deduplication
1. Publishes to appropriate AMQP queue based on data type
1. Tracks progress with visual progress bars

### AMQP Publishing

- **Exchange**: `discogsography-exchange` (topic type)
- **Routing Keys**:
  - `discogsography.labels` → `labels` queue
  - `discogsography.artists` → `artists` queue
  - `discogsography.releases` → `releases` queue
  - `discogsography.masters` → `masters` queue

## Periodic Checking

After initial processing, the service continues running and periodically checks for new data:

```bash
# Run with custom check interval (e.g., daily checks)
PERIODIC_CHECK_DAYS=1 uv run python extractor/extractor.py
```

## Development

### Running Locally

```bash
# Install dependencies
uv sync --extra extractor

# Run the extractor
uv run python extractor/extractor.py
```

### Running Tests

```bash
# Run extractor tests
uv run pytest tests/extractor/ -v

# Run specific test
uv run pytest tests/extractor/test_discogs.py -v
```

## Docker

Build and run with Docker:

```bash
# Build
docker build -f extractor/Dockerfile .

# Run with docker-compose
docker-compose up extractor
```

The Docker image includes a volume mount at `/discogs-data` for persistent storage of downloaded files.

## Monitoring

- Health endpoint available at `http://localhost:8000/health`
- Structured JSON logging with emoji prefixes for visual clarity
- Progress bars for long-running operations
- Detailed error messages with stack traces

## Performance

- Streaming XML parser for memory efficiency
- Hash-based deduplication to avoid reprocessing
- Configurable batch sizes for AMQP publishing
- Automatic retry logic for network operations

## Error Handling

- Validates checksums before and after download
- Retries failed downloads with exponential backoff
- Graceful shutdown on interrupt signals
- Comprehensive exception handling with detailed logging
