# Incremental Processing

This document describes the incremental processing feature for Discogsography, which enables efficient processing of large Discogs data dumps by tracking changes and only processing modified records.

## Overview

The incremental processing feature addresses the challenge of processing very large XML files (40-50GB compressed) by:

1. **Change Detection**: Computing hashes for each record to detect changes
1. **State Tracking**: Maintaining processing state in PostgreSQL
1. **Selective Processing**: Only publishing changed records to downstream services
1. **Real-time Notifications**: Broadcasting changes via WebSocket for immediate updates

## Architecture

### Components

1. **ProcessingStateTracker** (`common/processing_state.py`)

   - Manages processing state in PostgreSQL
   - Tracks individual record hashes
   - Detects created, updated, and deleted records
   - Maintains processing run history

1. **IncrementalExtractor** (`extractor/incremental_extractor.py`)

   - Enhanced version of the standard extractor
   - Integrates with ProcessingStateTracker
   - Publishes only changed records
   - Sends change notifications to a dedicated queue

1. **Database Schema** (`migrations/001_incremental_processing.sql`)

   - `processing_state`: Overall processing state per data type
   - `record_processing_state`: Individual record tracking
   - `data_changelog`: Change history
   - `processing_runs`: Processing run metadata

1. **Changes Consumer** (`common/changes_consumer.py`)

   - Base class for services consuming change notifications
   - Enables real-time updates in downstream services

## Setup

### 1. Configure PostgreSQL

Add PostgreSQL environment variables:

```bash
export POSTGRES_ADDRESS="localhost:5432"
export POSTGRES_USERNAME="discogsography"
export POSTGRES_PASSWORD="discogsography"
export POSTGRES_DATABASE="discogsography"
```

### 2. Run Database Migrations

```bash
# Using taskipy
uv run task migrate

# Or directly
uv run python scripts/run_migrations.py
```

### 3. Switch to Incremental Mode

```bash
# Switch to incremental mode
uv run task switch-mode incremental

# Switch back to normal mode
uv run task switch-mode normal
```

### 4. Run the Incremental Extractor

```bash
# Using taskipy
uv run task incremental-extractor

# Or via Docker Compose (after switching mode)
docker-compose restart extractor
```

## How It Works

### Initial Processing

1. **File Detection**: The extractor checks if files have been processed before
1. **Checksum Validation**: Compares file checksums to detect new versions
1. **Full Scan**: On first run, processes all records and stores their hashes
1. **State Storage**: Saves processing state and record hashes in PostgreSQL

### Subsequent Processing

1. **Change Detection**:

   - Computes hash for each record
   - Compares with stored hash
   - Identifies created, updated, or unchanged records

1. **Selective Publishing**:

   - Only publishes changed records to RabbitMQ
   - Adds `_change_type` metadata to messages
   - Sends notifications to changes queue

1. **Deletion Detection**:

   - Tracks which records were seen in current run
   - Identifies records not present (deleted)
   - Publishes deletion notifications

### Change Notifications

Change notifications are published to a dedicated queue with routing key `{data_type}.changes`:

```json
{
  "data_type": "artists",
  "record_id": "123",
  "change_type": "updated",
  "processing_run_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

## Performance Benefits

1. **Reduced Processing Time**:

   - Initial run: Full processing (2-6 hours)
   - Subsequent runs: Only changed records (minutes to hours)

1. **Lower Resource Usage**:

   - Reduced message queue traffic
   - Less database write operations
   - Lower network bandwidth

1. **Real-time Updates**:

   - WebSocket notifications for immediate UI updates
   - Targeted reprocessing in downstream services

## Monitoring

The dashboard provides real-time visibility into incremental processing:

- **Change Statistics**: Created, updated, deleted, unchanged counts
- **Processing Progress**: Records processed per second
- **WebSocket Notifications**: Real-time change alerts

## API Integration

### Consuming Changes

Services can extend the `ChangesConsumer` base class:

```python
from common.changes_consumer import ChangesConsumer

class MyServiceChangesConsumer(ChangesConsumer):
    async def process_change(self, change_data: dict[str, Any]) -> None:
        # Handle the change notification
        if change_data["change_type"] == "created":
            # Process new record
        elif change_data["change_type"] == "updated":
            # Update existing record
        elif change_data["change_type"] == "deleted":
            # Remove record
```

### WebSocket Updates

Connect to the dashboard WebSocket endpoint to receive real-time notifications:

```javascript
const ws = new WebSocket('ws://localhost:8003/ws');

ws.onmessage = (event) => {
  const message = JSON.parse(event.data);
  if (message.type === 'change_notification') {
    const change = message.data;
    console.log(`${change.data_type} ${change.record_id} was ${change.change_type}`);
  }
};
```

## Migration from Normal Mode

1. **Data Compatibility**: Incremental mode is fully compatible with existing data
1. **Gradual Migration**: Can switch between modes without data loss
1. **Initial Indexing**: First incremental run will index all existing records

## Best Practices

1. **Regular Processing**: Run at the configured interval (default: 15 days)
1. **Monitor Change Rates**: High change rates may indicate data quality issues
1. **Backup State**: Regular PostgreSQL backups preserve processing history
1. **Parallel Processing**: Can run multiple data types concurrently

## Troubleshooting

### Common Issues

1. **High Memory Usage**

   - Solution: Reduce batch size in incremental_extractor.py
   - Default: 100 messages per batch

1. **Slow Change Detection**

   - Solution: Ensure PostgreSQL indexes are created
   - Check: `record_processing_state` table indexes

1. **Missing Changes**

   - Solution: Check processing_runs table for errors
   - Verify: Record hashes are being computed correctly

### Debugging

Enable debug logging for detailed information:

```bash
export LOG_LEVEL=DEBUG
uv run task incremental-extractor
```

Check processing state:

```sql
-- View processing state
SELECT * FROM processing_state;

-- Check recent processing runs
SELECT * FROM processing_runs ORDER BY started_at DESC LIMIT 10;

-- View recent changes
SELECT * FROM data_changelog ORDER BY change_detected_at DESC LIMIT 100;
```

## Future Enhancements

1. **Partial File Processing**: Resume processing from last position
1. **Parallel Record Processing**: Multi-threaded change detection
1. **Change Analytics**: Dashboard showing change trends over time
1. **Selective Reprocessing**: Reprocess specific records on demand
