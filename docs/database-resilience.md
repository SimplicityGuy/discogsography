# Database Resilience Documentation

This document describes the database resilience features implemented in the Discogsography platform to handle nightly
maintenance windows and other database outages.

## Overview

All services now use resilient database connections that automatically handle:

- Nightly database maintenance windows
- Temporary network issues
- Database restarts
- Connection timeouts
- Service unavailability

## Key Features

### 1. Circuit Breaker Pattern

Each database connection uses a circuit breaker to prevent cascading failures:

- **Closed State**: Normal operation, all requests pass through
- **Open State**: After 5 consecutive failures, rejects requests immediately
- **Half-Open State**: After 30-60 seconds, allows one test request

```python
# Circuit breaker configuration
failure_threshold: 5  # Number of failures before opening
recovery_timeout: 30 - 60  # Seconds before trying half-open
```

### 2. Exponential Backoff

Failed connections retry with exponential backoff:

```yaml
# Backoff configuration
initial_delay: 0.5-1.0    # Initial retry delay (seconds)
max_delay: 30-60         # Maximum retry delay
exponential_base: 2.0    # Delay multiplier
jitter: 25%              # Random jitter to prevent thundering herd
```

### 3. Connection Health Monitoring

#### PostgreSQL

- Connection pool with 2-20 connections
- Health checks every 30 seconds
- Automatic removal of unhealthy connections
- Maintains minimum connection pool size

#### Neo4j

- Driver-level connection pooling (max 50 connections)
- Built-in keep-alive mechanism
- Session-level health checks
- Automatic reconnection on SessionExpired

#### RabbitMQ

- Robust connections with automatic recovery
- Heartbeat monitoring (600 seconds)
- Channel-level recovery
- Publisher confirmations for reliability

### 4. Message Durability

During database outages:

1. **Messages remain in RabbitMQ** (persistent storage)
1. **Failed messages are requeued** with `nack(requeue=True)`
1. **Idempotency prevents duplicates** using SHA256 hashes
1. **No data loss** - messages wait until databases recover

## Service-Specific Implementation

### Python/Rust Extractor Services

- Uses `ResilientRabbitMQConnection` for publishing
- Buffers messages during connection issues
- Retries failed publishes with backoff
- Flushes pending messages on recovery

### Graphinator Service (Neo4j)

- Uses `ResilientNeo4jDriver` with automatic reconnection
- Handles `ServiceUnavailable` and `SessionExpired` exceptions
- Requeues messages on connection failures
- Removed reactive 2-minute reconnection timer (now proactive)

### Tableinator Service (PostgreSQL)

- Uses `ResilientPostgreSQLPool` with health monitoring
- Connection pool with min/max bounds (2-20)
- Handles `InterfaceError` and `OperationalError`
- Automatic connection recycling

### Dashboard Service

- Uses all three resilient connection types
- Async implementations for non-blocking operations
- Graceful degradation when services unavailable

## Configuration

### Environment Variables

No changes required to existing environment variables. The resilient connections use the same configuration:

```bash
# Neo4j
NEO4J_ADDRESS=bolt://neo4j:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=password

# PostgreSQL
POSTGRES_ADDRESS=postgres:5432
POSTGRES_DATABASE=discogsography
POSTGRES_USERNAME=postgres
POSTGRES_PASSWORD=postgres

# RabbitMQ
AMQP_CONNECTION=amqp://guest:guest@rabbitmq:5672/
```

### Tuning Parameters

The following parameters can be adjusted in the code if needed:

```python
# Circuit Breaker
failure_threshold = 5  # Failures before circuit opens
recovery_timeout = 30  # Seconds before recovery attempt

# Retry Settings
max_retries = 5  # Maximum connection attempts
initial_delay = 1.0  # Initial retry delay
max_delay = 60.0  # Maximum retry delay

# Connection Pools
postgres_min_connections = 2
postgres_max_connections = 20
postgres_health_check_interval = 30

# Neo4j Settings
neo4j_max_connection_lifetime = 1800  # 30 minutes
neo4j_max_connection_pool_size = 50
neo4j_connection_acquisition_timeout = 60.0
```

## Behavior During Maintenance

When databases undergo nightly maintenance:

1. **Connection Detection**: Services detect connection loss within seconds
1. **Circuit Breaker Opens**: After 5 failures, prevents cascade
1. **Message Queuing**: New messages remain in RabbitMQ
1. **Exponential Backoff**: Retry attempts with increasing delays
1. **Recovery**: When database returns, connections automatically restore
1. **Message Processing**: Queued messages process in order
1. **Idempotency**: Duplicate prevention via SHA256 hashes

## Monitoring

### Health Endpoints

Each service exposes health data including connection status:

- Python Extractor: `http://localhost:8000/health`
- Rust Extractor: `http://localhost:8000/health`
- Graphinator: `http://localhost:8001/health`
- Tableinator: `http://localhost:8002/health`
- Dashboard: `http://localhost:8003/health`
- Discovery: `http://localhost:8004/health`

### Logging

Enhanced logging for connection events:

```
🔄 Creating new connection (attempt 1/5)
⚠️ Connection attempt 1 failed: Connection refused. Retrying in 1.2 seconds...
🔄 Creating new connection (attempt 2/5)
✅ Connection established successfully
🚨 Circuit breaker OPEN after 5 failures
🔄 Circuit breaker entering HALF_OPEN state
✅ Circuit breaker reset to CLOSED
```

### Metrics

The dashboard service (`/metrics` endpoint) provides Prometheus metrics for monitoring.

## Testing Database Outages

To test the resilience features:

### 1. Stop a Database

```bash
# Stop Neo4j
docker-compose stop neo4j

# Stop PostgreSQL
docker-compose stop postgres

# Stop RabbitMQ
docker-compose stop rabbitmq
```

### 2. Observe Service Behavior

Watch the logs to see connection failures and circuit breaker activation:

```bash
docker-compose logs -f graphinator
docker-compose logs -f tableinator
```

### 3. Restart Database

```bash
# Restart the stopped service
docker-compose start neo4j
docker-compose start postgres
docker-compose start rabbitmq
```

### 4. Verify Recovery

- Services should automatically reconnect
- Queued messages should process
- No data should be lost

## Best Practices

1. **Don't Panic**: Services handle outages automatically
1. **Monitor Logs**: Watch for extended outage warnings
1. **Check Queues**: Monitor RabbitMQ queue depths during outages
1. **Verify Recovery**: Ensure message processing resumes after recovery
1. **Test Regularly**: Simulate outages in non-production environments

## Troubleshooting

### Services Not Recovering

If services don't recover after database restart:

1. Check circuit breaker state in logs
1. Verify database is fully started and accepting connections
1. Restart affected service if needed: `docker-compose restart [service]`

### Messages Not Processing

If messages remain queued after recovery:

1. Check service health endpoints
1. Verify database connectivity manually
1. Look for poison messages causing repeated failures
1. Consider implementing dead letter queues (future enhancement)

### Performance Issues

If services are slow after recovery:

1. Check for message backlog in RabbitMQ
1. Monitor database connection pool usage
1. Consider increasing prefetch counts temporarily
1. Watch for circuit breaker flapping (rapid open/close)
