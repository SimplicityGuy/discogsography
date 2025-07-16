# Utilities

> 🔧 Debugging and monitoring tools for Discogsography development

This directory contains utility scripts to help debug, monitor, and analyze the Discogsography system during development and operations.

## 🛠️ Available Tools

### check_errors.py

Analyzes service log files for errors and warnings.

```bash
# Check all service logs
uv run python utilities/check_errors.py

# Or use taskipy
uv run task check-errors
```

**Features:**

- Scans all logs in `/logs` directory
- Highlights errors (❌) and warnings (⚠️)
- Shows timestamp and context
- Groups errors by service

### check_queues.py

Displays current RabbitMQ queue statistics.

```bash
uv run python utilities/check_queues.py
```

**Shows:**

- Queue names and message counts
- Consumer counts per queue
- Message rates (if available)
- Connection status

### monitor_queues.py

Real-time monitoring of RabbitMQ queue activity.

```bash
# Monitor with auto-refresh
uv run python utilities/monitor_queues.py

# Or use taskipy
uv run task monitor
```

**Features:**

- Live updates every 5 seconds
- Color-coded status indicators
- Message throughput tracking
- Consumer health monitoring

### system_monitor.py

Comprehensive system health dashboard.

```bash
# Run system monitor
uv run python utilities/system_monitor.py

# Or use taskipy
uv run task system-monitor
```

**Displays:**

- Service health status (all microservices)
- Database connections (Neo4j, PostgreSQL)
- Queue metrics (RabbitMQ)
- System resources (if available)

### debug_message.py

Send test messages directly to AMQP queues for debugging.

```bash
# Interactive mode
uv run python utilities/debug_message.py

# Send specific message
uv run python utilities/debug_message.py --queue artists --message '{"id": 123, "name": "Test Artist"}'
```

**Options:**

- `--queue`: Target queue name
- `--message`: JSON message to send
- `--count`: Number of messages to send
- Interactive mode for manual testing

### healthcheck.py

Simple health check utility for testing service endpoints.

```bash
# Check all services
uv run python utilities/healthcheck.py

# Check specific service
uv run python utilities/healthcheck.py --service extractor
```

## 🔒 Security Notes

These utilities include security suppressions for development use:

- `# nosec B603 B607` - For Docker subprocess commands
- `# noqa: S310` - For localhost HTTP requests
- `# nosec B105` - For hardcoded development credentials

These suppressions are appropriate because:

- Tools are for development/debugging only
- No user input is passed to commands
- All connections are to localhost services
- Environment variables override any defaults

## 💡 Usage Tips

1. **Start with system_monitor.py** for overall health
1. **Use check_errors.py** when services report issues
1. **Run monitor_queues.py** to watch message flow
1. **Use debug_message.py** to test message processing

## 🔗 Related Documentation

- [README.md](../README.md) - Project overview
- [CLAUDE.md](../CLAUDE.md) - Development guide
- [Task Automation](../docs/task-automation.md) - Taskipy commands
