# Rust Extractor

High-performance Rust-based Discogs data extractor for the Discogsography platform.

## Overview

Rust Extractor is a Rust reimplementation of the Python-based extractor service, offering significantly improved
performance and lower resource usage. It streams and parses Discogs XML data dumps, sending processed records to
RabbitMQ for consumption by downstream services.

## Features

- **High Performance**: Leverages Rust's zero-cost abstractions and efficient XML streaming
- **Low Memory Usage**: Streaming parser maintains minimal memory footprint (~5-10MB)
- **Concurrent Processing**: Multi-threaded extraction with configurable worker pools
- **Resilient Connections**: Automatic reconnection to RabbitMQ with exponential backoff
- **Health Monitoring**: HTTP health endpoints for container orchestration
- **Progress Tracking**: Real-time extraction metrics and progress reporting
- **Periodic Checks**: Automatic checking for new Discogs data dumps
- **State Marker System**: Version-specific progress tracking for safe restarts (no duplicate processing)

## Credits

This implementation is inspired by and references the excellent [disco-quick](https://github.com/sublipri/disco-quick)
library by sublipri, which demonstrated the incredible performance gains possible with Rust-based XML parsing for
Discogs data.

## Performance Benchmarks

Based on disco-quick reference implementation:

| Data Type | Records/Second | Memory Usage |
| --------- | -------------- | ------------ |
| Artists   | ~430,000       | ~5MB         |
| Labels    | ~640,000       | ~5MB         |
| Masters   | ~95,000        | ~8MB         |
| Releases  | ~22,000        | ~10MB        |

## Configuration

Rust Extractor can be configured via environment variables or a TOML configuration file.

### Environment Variables

- `AMQP_CONNECTION`: RabbitMQ connection URL (required)
- `DISCOGS_ROOT`: Directory for Discogs data (default: `/discogs-data`)
- `PERIODIC_CHECK_DAYS`: Days between checks for new data (default: 15)
- `LOG_LEVEL`: Logging level - DEBUG, INFO, WARNING, ERROR, CRITICAL (default: INFO)
- `HEALTH_PORT`: Port for health server (default: 8000)
- `MAX_WORKERS`: Number of worker threads (default: CPU count)
- `BATCH_SIZE`: Message batch size for AMQP (default: 100)
- `FORCE_REPROCESS`: Force reprocessing of all files (default: false)

### Configuration File

Create a `config.toml`:

```toml
amqp_connection = "amqp://localhost:5672"
discogs_root = "/discogs-data"
periodic_check_days = 15
health_port = 8000
max_workers = 8
batch_size = 100
queue_size = 5000
progress_log_interval = 1000
s3_bucket = "discogs-data-dumps"
s3_region = "us-west-2"
```

## Building

### Local Development

```bash
# Build debug version
cargo build

# Build release version
cargo build --release

# Run tests
cargo test

# Run with debug logging
LOG_LEVEL=DEBUG cargo run

# Run with default (INFO) logging
cargo run
```

### Docker

```bash
# Build image
docker build -t rustextractor .

# Run container
docker run -e AMQP_CONNECTION=amqp://rabbitmq:5672 rustextractor
```

## Testing

```bash
# Run all tests
cargo test

# Run with coverage (requires cargo-tarpaulin)
cargo tarpaulin --out Html

# Run benchmarks
cargo bench
```

## State Marker System

Rust Extractor uses a version-specific state marker system to track extraction progress and enable safe restarts:

### Features

- **Version-Specific Tracking**: Each Discogs version (e.g., `20260101`) gets its own state marker file
- **Multi-Phase Monitoring**: Tracks download, processing, publishing, and overall status
- **Smart Resume Logic**: Automatically decides whether to reprocess, continue, or skip on restart
- **Per-File Progress**: Detailed tracking of individual file processing status
- **Error Recovery**: Records errors at each phase for debugging and recovery

### State Marker File

Location: `/discogs-data/.extraction_status_<version>.json`

Example:
```json
{
  "current_version": "20260101",
  "download_phase": {
    "status": "completed",
    "files_downloaded": 4,
    "bytes_downloaded": 5234567890
  },
  "processing_phase": {
    "status": "in_progress",
    "files_processed": 2,
    "records_extracted": 1234567,
    "progress_by_file": {
      "discogs_20260101_artists.xml.gz": {
        "status": "completed",
        "records_extracted": 500000
      }
    }
  },
  "summary": {
    "overall_status": "in_progress"
  }
}
```

### Processing Decisions

When the extractor restarts, it checks the state marker and decides:

| Scenario | Decision | Action |
|----------|----------|--------|
| Download failed | **Reprocess** | Re-download everything |
| Processing in progress | **Continue** | Resume unfinished files |
| All completed | **Skip** | Wait for next check |

See **[State Marker System](../../docs/state-marker-system.md)** for complete documentation.

## Architecture

Rust Extractor uses a streaming pipeline architecture:

1. **Downloader**: Fetches latest Discogs dumps from S3
1. **Parser**: Streams XML using quick-xml, extracting records
1. **Batcher**: Groups records for efficient AMQP publishing
1. **Publisher**: Sends batched messages to RabbitMQ exchanges
1. **State Tracker**: Updates progress markers at each phase

## Logging

Rust Extractor uses structured JSON logging with emoji indicators:

- 🚀 Service starting
- 📥 Download operations
- 📊 Progress updates
- ✅ Successful operations
- ⚠️ Warnings
- ❌ Errors
- 🛑 Shutdown events
- 🎉 Completion milestones

### Log Levels

Set the `LOG_LEVEL` environment variable to control logging verbosity:

- `DEBUG`: Detailed diagnostic information
- `INFO`: General informational messages (default)
- `WARNING`: Warning messages for potential issues
- `ERROR`: Error messages for failures
- `CRITICAL`: Critical errors (mapped to ERROR in Rust)

## Health Endpoints

- `GET /health`: Service health status with current metrics
- `GET /metrics`: Prometheus-compatible metrics
- `GET /ready`: Readiness probe for container orchestration

## Integration

Rust Extractor integrates with the Discogsography platform:

- Publishes to the same AMQP exchange as the Python extractor
- Maintains compatibility with existing message formats
- Supports the same data types (artists, labels, masters, releases)
- Provides equivalent health monitoring

## Migration from Python Extractor

Rust Extractor is a drop-in replacement for the Python extractor:

1. Uses the same environment variables
1. Publishes to the same AMQP queues
1. Produces identical message formats
1. Maintains the same file processing state

To migrate, simply replace the Python extractor service with rustextractor in your deployment configuration.

## License

MIT
