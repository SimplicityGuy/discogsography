# Consumer Cancellation Feature

<div align="center">

**Automatic consumer lifecycle management for completed file processing**

Last Updated: January 2025

</div>

## Overview

The consumer cancellation feature automatically closes RabbitMQ queue consumers after files have completed processing.
This helps free up resources and provides clearer monitoring of active vs. completed file processing.

## How It Works

### Consumer Cancellation Lifecycle

```mermaid
sequenceDiagram
    participant EXT as Extractor
    participant RMQ as RabbitMQ
    participant CONS as Consumer<br/>(Graphinator/Tableinator)
    participant TIMER as Cancellation Timer

    EXT->>RMQ: Publish file_complete message
    RMQ->>CONS: Deliver file_complete message
    CONS->>CONS: Mark file as complete (🎉)
    CONS->>TIMER: Schedule cancellation (300s grace period)

    Note over CONS,TIMER: Grace period (5 minutes)

    TIMER-->>CONS: Grace period expired
    CONS->>RMQ: Cancel consumer for queue
    CONS->>CONS: Update active consumers list
    CONS->>CONS: Log consumer status

    Note over CONS: Connection remains open<br/>for other queues

    style EXT fill:#fff9c4
    style RMQ fill:#fff3e0
    style CONS fill:#e0f2f1
    style TIMER fill:#ffebee
```

### Process Steps

1. When the Python/Rust extractor sends a "file_complete" message, both tableinator and graphinator:

   - Mark the file as complete (shows 🎉 in progress reports)
   - Schedule the consumer for that queue to be canceled after a grace period
   - The default grace period is 5 minutes (300 seconds)

1. After the grace period expires:

   - The consumer for that specific queue is canceled
   - The connection and channel remain open for other queues
   - Progress reports show which consumers are active vs. canceled

1. Benefits:

   - Frees up RabbitMQ resources (connections, channels, memory)
   - Clearer monitoring - easy to see which files are still being processed
   - Prevents unnecessary network traffic for completed queues

## Configuration

### Environment Variable

- `CONSUMER_CANCEL_DELAY`: Number of seconds to wait before canceling a consumer after file completion
  - Default: 300 (5 minutes)
  - Set to 0 to disable consumer cancellation
  - Can be set per service or globally

### Examples

```bash
# Use default 5-minute delay
docker-compose up

# Use 30-second delay for faster testing
CONSUMER_CANCEL_DELAY=30 docker-compose up

# Disable consumer cancellation
CONSUMER_CANCEL_DELAY=0 docker-compose up

# Different delays per service
CONSUMER_CANCEL_DELAY=60 docker-compose up tableinator
CONSUMER_CANCEL_DELAY=120 docker-compose up graphinator
```

## Monitoring

### Progress Reports

The periodic progress reports now include consumer status:

```
📊 Progress: 1000 total messages processed (🎉 Artists: 500, Labels: 500, Masters: 0, Releases: 0)
🔌 Canceled consumers: ['artists']
✅ Active consumers: ['labels', 'masters', 'releases']
```

### Log Messages

Watch for these log messages:

- `🎉 File processing complete for {type}!` - File marked as complete
- `🔌 Canceling consumer for {type} after {delay}s grace period` - Consumer cancellation scheduled
- `✅ Consumer for {type} successfully canceled` - Consumer successfully canceled
- `❌ Failed to cancel consumer for {type}` - Cancellation failed (non-fatal)

## Testing

Use the provided test scripts:

1. **test_file_completion.py** - Tests the file completion message handling
1. **test_consumer_cancellation.py** - Tests and monitors consumer cancellation

```bash
# Run with short delay for testing
CONSUMER_CANCEL_DELAY=10 docker-compose up -d tableinator graphinator

# Send test completion messages
python test_consumer_cancellation.py

# Watch the logs
docker-compose logs -f tableinator graphinator
```

## Edge Cases Handled

1. **Multiple Completion Messages**: If multiple completion messages are received, only one cancellation is scheduled
1. **Service Restart**: Consumer tags are lost on restart, but the feature continues to work for new messages
1. **Cancellation Failure**: Failures are logged but don't crash the service
1. **Grace Period**: Ensures all in-flight messages are processed before cancellation

## Technical Details

- Uses aio_pika's `queue.cancel(consumer_tag, nowait=True)` to cancel consumers
- Consumer tags are stored when consumers are created
- Cancellation tasks are tracked to allow proper cleanup on shutdown
- The `nowait=True` parameter prevents hanging if RabbitMQ is slow to respond

## Python/Extractor Integration

Both the Python and Rust extractor services integrate with consumer cancellation by:

1. **Sending File Completion Messages**: When a file finishes processing, the extractor (Python or Rust) sends a
   "file_complete" message
1. **Tracking Completed Files**: Both extractors maintain a `completed_files` set to avoid false stalled warnings
1. **Progress Monitoring**: Completed files are excluded from stalled detection logic

This prevents the extractors from incorrectly reporting files as "stalled" when they have actually completed processing
and their consumers have been canceled.

### Recent Improvements (January 2025)

- Added `completed_files` tracking in both extractors to prevent false stalled warnings
- Enhanced progress reporting to show which file types are completed
- Fixed issue where completed files would show as stalled after 2 minutes of inactivity
