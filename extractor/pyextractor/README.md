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
- **NEW**: Manages AMQP connections per file, closing after completion
- **NEW**: Sends file completion notifications to downstream services
- **NEW**: Re-establishes connections when checking for new files

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

## Connection Management

### Improved Connection Lifecycle

The extractor now implements intelligent connection management:

1. **Per-File Connections**: Each file type gets its own AMQP connection
1. **Automatic Closure**: Connections are closed after file processing completes
1. **Completion Notifications**: Sends `file_complete` messages before closing
1. **Periodic Re-establishment**: Connections are re-created for periodic checks
1. **Resource Efficiency**: No idle connections during wait periods

### File Completion Messages

When a file finishes processing, the extractor sends:

```json
{
  "type": "file_complete",
  "data_type": "artists",
  "timestamp": "2024-01-01T12:00:00",
  "total_processed": 12345,
  "file": "discogs_20240101_artists.xml.gz"
}
```

This allows downstream services (graphinator, tableinator) to:

- Know when a file is complete
- Close their own consumers if needed
- Track processing progress

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
uv sync --extra pyextractor

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
docker build -f extractor/pyextractor/Dockerfile .

# Run with docker-compose
docker-compose up extractor
```

The Docker image includes a volume mount at `/discogs-data` for persistent storage of downloaded files.

## Monitoring

- Health endpoint available at `http://localhost:8000/health`
- Structured JSON logging with emoji prefixes for visual clarity
- Progress bars for long-running operations
- Detailed error messages with stack traces

### File Completion Tracking

The extractor includes intelligent file completion tracking:

- Sends "file_complete" messages when processing finishes
- Tracks completed files to prevent false stalled warnings
- Shows completion status in progress reports
- Integrates with consumer cancellation for resource cleanup

Progress reports show:

- Active extractors currently processing files
- Completed file types that have finished
- Actual stalled extractors (excludes completed files)

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
