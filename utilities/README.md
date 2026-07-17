# Utilities

> 🔧 Debugging and monitoring tools for Discogsography development

This directory contains utility scripts to help debug, monitor, and analyze the Discogsography system during development and operations.

## 🛠️ Available Tools

### check_errors.py

Scans recent `docker compose logs` output for the pipeline services for error patterns.

```bash
# Check the last 60 minutes (default) across all pipeline services
uv run python utilities/check_errors.py

# Check a custom time window (minutes)
uv run python utilities/check_errors.py 30

# Or use just
just check-errors
```

**Features:**

- Checks `extractor-discogs`, `extractor-musicbrainz`, `graphinator`, `tableinator`, `brainzgraphinator`, and `brainztableinator` via `docker compose logs --since=<N>m`
- Matches lines against error patterns (`ERROR`, `Exception`, `Traceback`, `Failed to process...`)
- Groups and counts similar errors per service, printing `✅ No errors found` when clean

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
# Monitor with auto-refresh (default: every 5 seconds)
uv run python utilities/monitor_queues.py

# Custom refresh interval (seconds)
uv run python utilities/monitor_queues.py 10

# Or use just
just monitor
```

**Features:**

- Live updates every 5 seconds by default (configurable via a positional interval argument)
- Highlights queues with unacknowledged messages in yellow
- Running total of messages across all `discogsography`/`musicbrainz` queues

### system_monitor.py

Comprehensive system health dashboard.

```bash
# Run system monitor
uv run python utilities/system_monitor.py

# Or use just
just system-monitor
```

**Displays:**

- Docker container status and health (`docker compose ps`)
- RabbitMQ queue message counts (ready/unacked/total)
- Neo4j node counts by label (via `cypher-shell`)
- PostgreSQL table sizes and row counts (via `psql`)
- Recent `ERROR`/`Failed` log lines for the pipeline services (extractor-discogs, extractor-musicbrainz, graphinator, tableinator, brainzgraphinator, brainztableinator)

### debug_message.py

Peeks at (non-destructively, via `basic_get` + `basic_nack` requeue) a single message from a consumer queue and analyzes its structure — checks required/optional fields for the given data type and flags common issues (missing fields, malformed nested artist entries).

```bash
uv run python utilities/debug_message.py <queue_type> [consumer]
```

**Arguments:**

- `queue_type`: `artists`, `labels`, `masters`, `releases`, or `release-groups` (MusicBrainz)
- `consumer`: `graphinator`, `tableinator`, `brainzgraphinator`, or `brainztableinator` (default: `graphinator`)

### healthcheck.py

Checks whether a process matching the given name is currently running (via `psutil.process_iter`), matching against each process's command line. Exits `0` if found, `1` otherwise.

```bash
uv run python utilities/healthcheck.py <process_name>
```

## 🔒 Security Notes

These utilities include security suppressions for development use:

- `# nosec B404 B603 B607` / `# noqa: S603 S607` - For `docker compose`/`docker exec` subprocess commands

These suppressions are appropriate because:

- Tools are for development/debugging only
- No user input is passed to commands
- All connections are to localhost services
- Environment variables override any defaults

## 💡 Usage Tips

1. **Start with system_monitor.py** for overall health
1. **Use check_errors.py** when services report issues
1. **Run monitor_queues.py** to watch message flow
1. **Use debug_message.py** to inspect a queue's message structure

## 🔗 Related Documentation

- [README.md](../README.md) - Project overview
- [CLAUDE.md](../CLAUDE.md) - Development guide
- [Task Automation](../docs/task-automation.md) - Just commands
