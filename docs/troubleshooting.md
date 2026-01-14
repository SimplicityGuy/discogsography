# Troubleshooting Guide

Common issues and solutions for the Discogsography project.

## Neo4j Schema Warnings

### Symptom

You see many warning messages in the Discovery service logs like:

```json
{"event":"Received notification from DBMS server: {severity: WARNING} {code: Neo.ClientNotification.Statement.UnknownRelationshipTypeWarning} {category: UNRECOGNIZED} {title: The provided relationship type is not in the database.} ...","level":"warning","lineno":337,"logger":"neo4j.notifications",...}
```

Warnings about:

- Unknown relationship types: `BY`, `IS`
- Unknown labels: `Genre`, `Style`
- Unknown properties: `profile`

### Cause

These warnings appear when:

1. The Neo4j database is **empty** (no data has been loaded yet)
1. The database is **being populated** by the graphinator service
1. The Discovery service tries to query data that doesn't exist yet

**This is normal and not an error!** The Cypher queries use `OPTIONAL MATCH` patterns that gracefully handle missing data.

### Solution

**Option 1: Suppress the warnings (Recommended)**

The warnings are already suppressed in the codebase by configuring the logging level:

```python
# In common/config.py setup_logging()
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)
logging.getLogger("neo4j").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", message="Expected a result with a single record", category=UserWarning, module="neo4j")
```

This configuration:

- Only shows actual **errors** from Neo4j, not warnings
- Keeps logs clean and focused on actionable issues
- Still logs all Discovery service operations normally

**Option 2: Populate the database**

If you want the Discovery service to return results, you need to:

1. **Run the extractor service** to download Discogs data:

   ```bash
   docker-compose up -d extractor
   docker-compose logs -f extractor
   ```

1. **Run the graphinator service** to populate Neo4j:

   ```bash
   docker-compose up -d graphinator
   docker-compose logs -f graphinator
   ```

1. **Wait for data processing** to complete (may take several hours for full dataset)

1. **Verify data in Neo4j Browser**:

   - Open http://localhost:7474
   - Run: `MATCH (n) RETURN count(n)` to see node count
   - Run: `MATCH ()-[r]->() RETURN count(r)` to see relationship count

### Expected Schema

The graphinator service creates the following schema:

**Node Labels:**

- `Artist` - Music artists and groups
- `Release` - Album releases
- `Master` - Master releases
- `Label` - Record labels
- `Genre` - Music genres
- `Style` - Music styles (sub-genres)

**Relationship Types:**

- `[:BY]` - Artist to Release/Master (created by artist)
- `[:IS]` - Release/Master to Genre/Style
- `[:MEMBER_OF]` - Artist to Artist (group membership)
- `[:ALIAS_OF]` - Artist to Artist (aliases)
- `[:SUBLABEL_OF]` - Label to Label (parent-child)
- `[:ON]` - Release to Label (released on)
- `[:DERIVED_FROM]` - Release to Master (derived from master)
- `[:PART_OF]` - Style to Genre (style is part of genre)

**Properties:**

- `Artist.id`, `Artist.name`, `Artist.profile` (may not exist for all artists)
- `Release.id`, `Release.title`, `Release.year`
- `Genre.name`, `Style.name`
- `Label.id`, `Label.name`

### Verification

After populating the database, verify the warnings are gone:

```bash
# Check Discovery service logs (should be clean now)
docker-compose logs -f discovery

# Test recommendations endpoint
curl http://localhost:8005/api/recommendations -X POST \
  -H "Content-Type: application/json" \
  -d '{"artist_name": "The Beatles", "top_n": 5}'

# Test search endpoint
curl "http://localhost:8005/api/search?q=Beatles&type=artist&limit=10"
```

## Other Common Issues

### Port Conflicts

**Symptom**: Services fail to start with "port already in use" errors.

**Solution**: Check and update ports in `docker-compose.yml` or stop conflicting services.

```bash
# Check what's using a port (e.g., 8005)
lsof -i :8005

# Kill the process
kill -9 <PID>
```

### Out of Memory

**Symptom**: Containers crash or are killed by Docker.

**Solution**: Increase Docker memory limits:

1. Open Docker Desktop → Settings → Resources
1. Increase memory allocation (recommend 8GB+ for full dataset)
1. Restart Docker

### Permission Denied

**Symptom**: Cannot write to volumes or log files.

**Solution**: Fix permissions on host directories:

```bash
chmod -R 755 logs/
chmod -R 755 data/
```

### Discovery Service Issues

#### Missing asyncpg Dependency

**Symptom**: Discovery service fails to start with error:

```
ModuleNotFoundError: No module named 'asyncpg'
```

**Cause**: The asyncpg Python package (required for async PostgreSQL connections) is not installed in the container.

**Solution**: Rebuild the discovery service container:

```bash
docker-compose build discovery
docker-compose up -d discovery
```

**Verification**: Check the service logs for successful startup:

```bash
docker-compose logs discovery | grep "Discovery service started successfully"
```

#### Cache Directory Permission Errors

**Symptom**: Discovery service fails with filesystem permission errors:

```
OSError: [Errno 30] Read-only file system: 'data'
```

**Cause**: Cache directories are not writable or the service is trying to write to a read-only filesystem.

**Solution**: The service is configured to use `/tmp` for caches which is writable. If you need to customize cache locations, ensure they are writable by UID 1000:

```bash
# Set custom cache directory (optional)
export EMBEDDINGS_CACHE_DIR=/custom/path
docker-compose up -d discovery

# Verify cache directories are accessible
docker exec -it discogsography-discovery ls -la /tmp/
```

#### Deprecated TRANSFORMERS_CACHE Warning

**Symptom**: Warnings in logs about deprecated environment variable:

```
FutureWarning: Using `TRANSFORMERS_CACHE` is deprecated and will be removed in v5 of Transformers. Use `HF_HOME` instead.
```

**Cause**: Using the old `TRANSFORMERS_CACHE` environment variable instead of the new `HF_HOME` standard.

**Solution**: The `docker-compose.yml` has been updated to use `HF_HOME`. If you see this warning:

1. Pull the latest changes
1. Rebuild the discovery service:

```bash
docker-compose build discovery
docker-compose up -d discovery
```

**Note**: The transformers library automatically uses `$HF_HOME/transformers` for cache storage.

### Enable DEBUG Logging

**When to use**: When you need detailed diagnostic information to troubleshoot issues.

**What it shows**: All services support the `LOG_LEVEL` environment variable for detailed diagnostic output:

```bash
# Enable DEBUG logging for all services
export LOG_LEVEL=DEBUG
docker-compose up -d

# Or for a specific service
LOG_LEVEL=DEBUG docker-compose up discovery

# Or run directly
LOG_LEVEL=DEBUG uv run python discovery/discovery.py
```

**DEBUG logging includes:**

- 🔍 **Database Queries**: All Neo4j and PostgreSQL queries with parameters
  ```bash
  # View Neo4j queries in real-time
  docker-compose logs -f discovery | grep "🔍 Executing Neo4j query"
  ```

- 📊 **Detailed Operation Traces**: Step-by-step execution flow
  ```bash
  # Monitor processing operations
  docker-compose logs -f graphinator | grep "🔄"
  ```

- 🧠 **ML Model Operations**: Model loading, inference, and caching
  ```bash
  # Track ML operations
  docker-compose logs discovery | grep "🧠"
  ```

- 🔄 **Cache Performance**: Cache hits, misses, and performance metrics
  ```bash
  # Monitor cache effectiveness
  docker-compose logs discovery | grep "cache"
  ```

- 📡 **Connection Events**: WebSocket, database, and RabbitMQ connections
  ```bash
  # Track connection lifecycle
  docker-compose logs -f dashboard | grep -E "🔗|🐰|🐘"
  ```

**Example DEBUG output for Neo4j query:**
```json
{
  "timestamp": "2026-01-13T20:00:00.123456Z",
  "level": "debug",
  "event": "🔍 Executing Neo4j query",
  "query": "MATCH (a:Artist) WHERE a.name CONTAINS $search RETURN a LIMIT $limit",
  "params": {"search": "Beatles", "limit": 20}
}
```

**Performance impact**: DEBUG logging increases log volume significantly. Use it for troubleshooting, then switch back to `INFO` for production.

For complete LOG_LEVEL documentation, see [Logging Configuration](logging-configuration.md).

## Getting Help

If you encounter issues not covered here:

1. **Check logs** for specific error messages
1. **Search GitHub issues**: https://github.com/simplicityguy/discogsography/issues
1. **Create a new issue** with:
   - Service name and version
   - Full error message and stack trace
   - Steps to reproduce
   - Docker/system environment details
