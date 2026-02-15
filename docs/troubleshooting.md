# 🔧 Troubleshooting Guide

<div align="center">

**Common issues and solutions for Discogsography**

[🏠 Back to Main](../README.md) | [📚 Documentation Index](README.md) | [📊 Monitoring](monitoring.md)

</div>

## Overview

This guide covers common issues you might encounter while using Discogsography and provides step-by-step solutions. For real-time monitoring and debugging tools, see the [Monitoring Guide](monitoring.md).

## 🚨 Common Issues & Solutions

### ❌ Python/Extractor Download Failures

**Symptoms**:

- Extractor fails to download data files
- Connection timeout errors
- Disk space errors
- Permission denied errors

**Diagnostic Steps**:

```bash
# Check connectivity to Discogs S3
curl -I https://discogs-data-dumps.s3.us-west-2.amazonaws.com

# Verify disk space (need 100GB+)
df -h /discogs-data

# Check permissions
ls -la /discogs-data

# View extractor logs
docker-compose logs -f extractor
```

**Solutions**:

1. **✅ Ensure internet connectivity**

   ```bash
   # Test connection
   ping discogs-data-dumps.s3.us-west-2.amazonaws.com
   ```

1. **✅ Verify 100GB+ free space**

   ```bash
   # Check available space
   df -h /discogs-data

   # Clean up if needed
   docker system prune -a --volumes
   ```

1. **✅ Check directory permissions**

   ```bash
   # Fix permissions (Docker needs write access)
   sudo chown -R 1000:1000 /discogs-data
   chmod -R 755 /discogs-data
   ```

1. **✅ Verify environment variables**

   ```bash
   # Check DISCOGS_ROOT is set correctly
   echo $DISCOGS_ROOT

   # Should point to writable directory
   ```

### ❌ RabbitMQ Connection Issues

**Symptoms**:

- Services can't connect to RabbitMQ
- "Connection refused" errors
- "Authentication failed" errors

**Diagnostic Steps**:

```bash
# Check RabbitMQ status
docker-compose ps rabbitmq
docker-compose logs rabbitmq

# Test connection
curl -u discogsography:discogsography http://localhost:15672/api/overview

# Check if port is accessible
netstat -an | grep 5672
```

**Solutions**:

1. **✅ Wait for RabbitMQ startup (30-60s)**

   ```bash
   # RabbitMQ takes time to start
   docker-compose logs -f rabbitmq | grep "started"
   ```

1. **✅ Check firewall settings**

   ```bash
   # Ensure ports 5672 and 15672 are not blocked
   # macOS/Linux
   sudo ufw status
   ```

1. **✅ Verify credentials in `.env`**

   ```bash
   # Check AMQP_CONNECTION
   echo $AMQP_CONNECTION

   # Should match RabbitMQ configuration
   ```

1. **✅ Restart RabbitMQ**

   ```bash
   docker-compose restart rabbitmq
   docker-compose logs -f rabbitmq
   ```

### ❌ Database Connection Errors

#### Neo4j Connection Issues

**Symptoms**:

- "Failed to connect to Neo4j" errors
- "Authentication failed" errors
- Timeout errors

**Diagnostic Steps**:

```bash
# Check Neo4j status
docker-compose logs neo4j

# Test HTTP access
curl http://localhost:7474

# Test bolt connection
echo "MATCH (n) RETURN count(n);" | \
  cypher-shell -u neo4j -p discogsography
```

**Solutions**:

1. **✅ Wait for Neo4j startup (30-60s)**

   ```bash
   docker-compose logs -f neo4j | grep "Started"
   ```

1. **✅ Verify credentials**

   ```bash
   # Check environment variables
   echo $NEO4J_ADDRESS
   echo $NEO4J_USERNAME
   echo $NEO4J_PASSWORD
   ```

1. **✅ Check connection string**

   ```bash
   # Should be bolt://host:7687
   # For Docker: bolt://neo4j:7687
   # For local: bolt://localhost:7687
   ```

1. **✅ Restart Neo4j**

   ```bash
   docker-compose restart neo4j
   ```

#### PostgreSQL Connection Issues

**Symptoms**:

- "Could not connect to PostgreSQL" errors
- "Authentication failed" errors
- Connection timeout errors

**Diagnostic Steps**:

```bash
# Check PostgreSQL status
docker-compose logs postgres

# Test connection
PGPASSWORD=discogsography psql \
  -h localhost -p 5433 -U discogsography \
  -d discogsography -c "SELECT 1;"
```

**Solutions**:

1. **✅ Wait for PostgreSQL startup**

   ```bash
   docker-compose logs -f postgres | grep "ready"
   ```

1. **✅ Verify credentials**

   ```bash
   echo $POSTGRES_ADDRESS
   echo $POSTGRES_USERNAME
   echo $POSTGRES_PASSWORD
   echo $POSTGRES_DATABASE
   ```

1. **✅ Check port mapping**

   ```bash
   # Default: 5433 (host) maps to 5432 (container)
   docker-compose ps postgres
   ```

1. **✅ Restart PostgreSQL**

   ```bash
   docker-compose restart postgres
   ```

### ❌ Port Conflicts

**Symptoms**:

- "Port already in use" errors
- Services fail to start
- "Address already in use" errors

**Diagnostic Steps**:

```bash
# Check what's using the ports
netstat -an | grep -E "(5672|7474|7687|5433|6379|8003|8004|8005)"

# Or on macOS
lsof -i :8005
lsof -i :7474

# List all Docker containers
docker ps -a
```

**Solutions**:

1. **✅ Stop conflicting services**

   ```bash
   # Find process using port
   lsof -i :8005

   # Kill the process
   kill -9 <PID>
   ```

1. **✅ Change port mapping**

   ```yaml
   # Edit docker-compose.yml
   ports:
     - "8006:8005"  # Use 8006 on host instead
   ```

1. **✅ Stop all Docker containers**

   ```bash
   docker-compose down
   docker-compose up -d
   ```

### ❌ Out of Memory / Disk Space

**Symptoms**:

- Containers crash or are killed
- "No space left on device" errors
- Docker build failures

**Diagnostic Steps**:

```bash
# Check available disk space
df -h

# Check Docker disk usage
docker system df

# Check container resource usage
docker stats
```

**Solutions**:

1. **✅ Increase Docker memory limits**

   - Open Docker Desktop → Settings → Resources
   - Increase memory allocation (recommend 16GB+ for full dataset)
   - Restart Docker

1. **✅ Clean up Docker resources**

   ```bash
   # Remove unused containers
   docker container prune

   # Remove unused images
   docker image prune -a

   # Remove unused volumes
   docker volume prune

   # Remove everything unused
   docker system prune -a --volumes
   ```

1. **✅ Free up disk space**

   ```bash
   # Find large files
   du -sh /path/to/data/* | sort -hr | head -10

   # Remove old logs
   find /var/log -name "*.log" -mtime +7 -delete
   ```

### ❌ Permission Denied Errors

**Symptoms**:

- Cannot write to volumes or log files
- "Permission denied" errors in logs
- Services fail to start with permission errors

**Diagnostic Steps**:

```bash
# Check file permissions
ls -la /discogs-data
ls -la logs/

# Check Docker user
docker run --rm alpine id
```

**Solutions**:

```bash
# Fix permissions on host directories
sudo chown -R 1000:1000 /discogs-data
sudo chown -R 1000:1000 logs/
chmod -R 755 /discogs-data
chmod -R 755 logs/

# For ML model caches (Discovery)
sudo chown -R 1000:1000 /models
chmod -R 755 /models
```

## 🐛 Debugging Guide

### Step 1: Check Service Health

All services expose health endpoints:

```bash
# Check each service
curl http://localhost:8000/health  # Extractor (Python or Rust)
curl http://localhost:8001/health  # Graphinator
curl http://localhost:8002/health  # Tableinator
curl http://localhost:8003/health  # Dashboard
curl http://localhost:8004/health  # Discovery (health endpoint)
curl http://localhost:8005/health  # Discovery (main port)
```

Expected response:

```json
{"status": "healthy"}
```

If unhealthy:

```bash
# View service logs
docker-compose logs [service_name]

# Restart service
docker-compose restart [service_name]
```

### Step 2: Enable Debug Logging

Set `LOG_LEVEL` environment variable for detailed output:

```bash
# Set environment variable
export LOG_LEVEL=DEBUG

# Restart services
docker-compose down
docker-compose up -d

# Or for specific service
LOG_LEVEL=DEBUG uv run python discovery/discovery.py
```

**DEBUG level includes**:

- 🔍 Database query logging with parameters
- 📊 Detailed operation traces
- 🧠 ML model operations
- 🔄 Cache hits/misses
- 📡 Internal state changes

See [Logging Configuration](logging-configuration.md) for complete details.

### Step 3: Monitor Real-time Logs

```bash
# All services
docker-compose logs -f

# Specific service with timestamp
docker-compose logs -f --timestamps graphinator

# Filter for errors
docker-compose logs -f | grep -E "(ERROR|❌)"

# Filter for Neo4j queries (DEBUG mode)
docker-compose logs -f discovery | grep "🔍 Executing Neo4j query"
```

### Step 4: Check Queue Status

```bash
# RabbitMQ management UI
open http://localhost:15672

# Or use CLI monitoring
uv run task monitor

# Or API
curl -u discogsography:discogsography \
  http://localhost:15672/api/queues
```

**Look for**:

- Messages accumulating (consumers not keeping up)
- Zero consumers (service not connected)
- High unacked count (processing errors)

### Step 5: Verify Database Connectivity

**Neo4j**:

```bash
# Browser access
curl http://localhost:7474

# Query test
echo "MATCH (n) RETURN count(n) as total;" | \
  cypher-shell -u neo4j -p discogsography
```

**PostgreSQL**:

```bash
# Connection test
PGPASSWORD=discogsography psql \
  -h localhost -p 5433 -U discogsography \
  -d discogsography -c "SELECT 1;"

# Check record counts
PGPASSWORD=discogsography psql \
  -h localhost -p 5433 -U discogsography \
  -d discogsography \
  -c "SELECT 'artists' as table, COUNT(*) FROM artists \
      UNION ALL SELECT 'releases', COUNT(*) FROM releases;"
```

### Step 6: Verify Data Storage

**Neo4j - Check node counts**:

```cypher
MATCH (n)
RETURN labels(n)[0] as type, count(n) as count
ORDER BY count DESC;
```

**PostgreSQL - Check table counts**:

```sql
SELECT 'artists' as table_name, COUNT(*) FROM artists
UNION ALL
SELECT 'releases', COUNT(*) FROM releases
UNION ALL
SELECT 'labels', COUNT(*) FROM labels
UNION ALL
SELECT 'masters', COUNT(*) FROM masters;
```

**Expected counts** (full dataset):

- Artists: ~2 million
- Releases: ~15 million
- Labels: ~1.5 million
- Masters: ~2 million

## 🔍 Service-Specific Issues

### Neo4j Schema Warnings

**Symptoms**:
You see many warning messages in the Discovery service logs like:

```json
{"event":"Received notification from DBMS server: {severity: WARNING} {code: Neo.ClientNotification.Statement.UnknownRelationshipTypeWarning} ...","level":"warning",...}
```

Warnings about:

- Unknown relationship types: `BY`, `IS`
- Unknown labels: `Genre`, `Style`
- Unknown properties: `profile`

**Cause**:
These warnings appear when:

1. The Neo4j database is **empty** (no data has been loaded yet)
1. The database is **being populated** by the graphinator service
1. The Discovery service tries to query data that doesn't exist yet

**This is normal and not an error!** The Cypher queries use `OPTIONAL MATCH` patterns that gracefully handle missing data.

**Solution 1: Suppress the warnings (Recommended)**

The warnings are already suppressed in the codebase by configuring the logging level:

```python
# In common/config.py setup_logging()
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)
logging.getLogger("neo4j").setLevel(logging.ERROR)
```

**Solution 2: Populate the database**

Run the extractor and graphinator to load data:

```bash
# Start extractor (Python or Rust)
docker-compose up -d extractor
docker-compose logs -f extractor

# Start graphinator
docker-compose up -d graphinator
docker-compose logs -f graphinator

# Verify data in Neo4j
curl http://localhost:7474
```

### Discovery Service Issues

#### Missing asyncpg Dependency

**Symptom**:

```
ModuleNotFoundError: No module named 'asyncpg'
```

**Solution**:

```bash
docker-compose build discovery
docker-compose up -d discovery
```

#### Cache Directory Permission Errors

**Symptom**:

```
OSError: [Errno 30] Read-only file system: 'data'
```

**Solution**:
Ensure cache directories are writable by UID 1000:

```bash
# Verify cache directories
docker exec -it discogsography-discovery ls -la /tmp/

# Fix permissions if needed
sudo chown -R 1000:1000 /models
chmod -R 755 /models
```

#### Deprecated TRANSFORMERS_CACHE Warning

**Symptom**:

```
FutureWarning: Using `TRANSFORMERS_CACHE` is deprecated. Use `HF_HOME` instead.
```

**Solution**:

```bash
# Update to latest code
git pull

# Rebuild discovery service
docker-compose build discovery
docker-compose up -d discovery
```

### Dashboard Issues

#### WebSocket Connection Failures

**Symptom**:

- Dashboard shows "Disconnected" status
- Real-time updates not working
- Browser console shows WebSocket errors

**Solution**:

```bash
# Check dashboard is running
curl http://localhost:8003/health

# Restart dashboard
docker-compose restart dashboard

# Check browser console for errors
# F12 → Console tab
```

#### Stale Data Display

**Symptom**:

- Dashboard shows old data
- Metrics don't update

**Solution**:

```bash
# Clear Redis cache
docker-compose exec redis redis-cli FLUSHDB

# Restart dashboard
docker-compose restart dashboard

# Refresh browser (Cmd+Shift+R / Ctrl+Shift+F5)
```

### Extractor Issues (Python/Rust)

#### Stuck on "Checking for updates"

**Symptom**:

- Extractor logs show "🔍 Checking for updates..." repeatedly
- No download progress
- Runs indefinitely

**Solution**:

```bash
# Check network connectivity
curl -I https://discogs-data-dumps.s3.us-west-2.amazonaws.com

# Restart extractor
docker-compose restart extractor  # or extractor

# Check logs
docker-compose logs -f extractor
```

#### Slow Download Speed

**Symptom**:

- Download takes very long
- Slow progress messages
- Low MB/s rate

**Solutions**:

1. **Check network speed**

   ```bash
   # Test download speed
   speedtest-cli
   ```

1. **Switch to Extractor** (20-400x faster)

   ```bash
   ./scripts/switch-extractor.sh rust
   ```

1. **Resume interrupted download**

   - Extractor automatically resumes from last position
   - Check for partial `.xml.gz` files in `/discogs-data`

## 📊 Performance Issues

### Slow Query Performance

**Symptoms**:

- Queries take too long
- Dashboard slow to load
- Discovery service timeouts

**Diagnostic Steps**:

**Neo4j**:

```cypher
-- Profile slow query
PROFILE MATCH (a:Artist {name: "Pink Floyd"})-[:BY]-(r:Release)
RETURN r.title, r.year;

-- Check index usage
SHOW INDEXES;
```

**PostgreSQL**:

```sql
-- Analyze query performance
EXPLAIN ANALYZE
SELECT data FROM artists WHERE data->>'name' = 'Pink Floyd';

-- Check index usage
SELECT * FROM pg_stat_user_indexes
ORDER BY idx_scan DESC;
```

**Solutions**:

1. **Add missing indexes** (see [Database Schema](database-schema.md))
1. **Run VACUUM ANALYZE** on PostgreSQL
1. **Increase database memory** (see [Configuration](configuration.md))
1. **Enable query caching** in Redis

### High Memory Usage

**Symptoms**:

- Services using excessive RAM
- OOM (Out of Memory) kills
- System slowdown

**Solutions**:

```bash
# Check resource usage
docker stats

# Limit service memory in docker-compose.yml
services:
  discovery:
    deploy:
      resources:
        limits:
          memory: 2G

# Restart with new limits
docker-compose up -d
```

## 🔧 Development Issues

### Pre-commit Hooks Failing

**Symptom**:

- Commits blocked by pre-commit
- Linting or formatting errors

**Solution**:

```bash
# Auto-fix issues
just format
just lint

# Run all checks
uv run pre-commit run --all-files

# Update hooks
uv run pre-commit autoupdate
```

### Tests Failing

**Symptom**:

- Test suite fails
- CI/CD pipeline broken

**Solution**:

```bash
# Run tests with verbose output
uv run pytest -vv

# Run specific test
uv run pytest tests/path/to/test.py::test_name

# Debug with pdb
uv run pytest --pdb

# Check coverage
uv run pytest --cov
```

## 📚 Additional Resources

- [Monitoring Guide](monitoring.md) - Real-time monitoring and debugging
- [Configuration Guide](configuration.md) - Environment variables
- [Development Guide](development.md) - Development setup
- [Performance Guide](performance-guide.md) - Optimization strategies
- [Database Resilience](database-resilience.md) - Connection patterns

## 💬 Getting Help

If you encounter issues not covered here:

1. **Check logs** for specific error messages

   ```bash
   docker-compose logs -f [service]
   uv run task check-errors
   ```

1. **Search GitHub issues**: https://github.com/simplicityguy/discogsography/issues

1. **Create a new issue** with:

   - Service name and version
   - Full error message and stack trace
   - Steps to reproduce
   - Docker/system environment details
   - Relevant logs

1. **Ask in Discussions**: https://github.com/simplicityguy/discogsography/discussions

______________________________________________________________________

**Last Updated**: 2025-01-15
