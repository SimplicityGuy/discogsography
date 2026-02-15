# 🔧 Maintenance Guide

<div align="center">

**Keeping Discogsography up-to-date and running smoothly**

[🏠 Back to Main](../README.md) | [📚 Documentation Index](README.md) | [👨‍💻 Development Guide](development.md)

</div>

## Overview

Regular maintenance keeps Discogsography secure, performant, and up-to-date. This guide covers dependency management, database maintenance, and system health monitoring.

## 📦 Dependency Management

### Package Upgrades

Keep dependencies up-to-date with the provided upgrade script:

```bash
# Safely upgrade all dependencies (minor/patch versions)
./scripts/upgrade-packages.sh

# Preview what would be upgraded (dry run)
./scripts/upgrade-packages.sh --dry-run

# Include major version upgrades
./scripts/upgrade-packages.sh --major
```

### Upgrade Script Features

The `upgrade-packages.sh` script provides:

#### Safety Features

- 🔒 **Automatic backups** before upgrades
- ✅ **Git safety checks** (requires clean working directory)
- 🧪 **Automatic testing** after upgrades
- 🔄 **Rollback support** if upgrades fail
- 📦 **Comprehensive coverage** across all services

#### What Gets Upgraded

**Python Packages**:

- Root `pyproject.toml` dependencies
- Service-specific dependencies
- Development dependencies
- Optional dependencies

**Rust Packages** (if Extractor is used):

- `Cargo.toml` dependencies
- Cargo.lock updates

**Docker Images**:

- Base images in Dockerfiles
- Service images in docker-compose.yml

#### Upgrade Process

1. **Pre-flight checks**:

   ```bash
   # Check git status
   # Verify no uncommitted changes
   # Ensure on main branch (recommended)
   ```

1. **Backup current state**:

   ```bash
   # Create backup of pyproject.toml files
   # Create backup of Cargo.toml files
   # Create git tag for rollback
   ```

1. **Upgrade packages**:

   ```bash
   # Update Python dependencies
   uv lock --upgrade-package <package>

   # Update Rust dependencies (if applicable)
   cargo update
   ```

1. **Test upgrades**:

   ```bash
   # Run full test suite
   uv run pytest

   # Run linting
   uv run ruff check .

   # Run type checking
   uv run mypy .
   ```

1. **Commit changes** (if tests pass):

   ```bash
   git add pyproject.toml uv.lock
   git commit -m "chore: upgrade dependencies"
   ```

### Manual Dependency Updates

#### Update Specific Package

```bash
# Python package
uv add "package-name>=new.version"

# Or update to latest
uv lock --upgrade-package package-name

# Rust package (in extractor/extractor/)
cargo update -p package-name
```

#### Check for Outdated Packages

```bash
# Python packages (list outdated)
uv pip list --outdated

# Rust packages
cargo outdated
```

### Security Updates

#### Vulnerability Scanning

```bash
# Scan for known vulnerabilities
just security

# Or directly with bandit
uv run bandit -r . -ll

# Scan dependencies
uv run pip-audit
```

#### Immediate Security Updates

For critical security vulnerabilities:

```bash
# 1. Update the vulnerable package
uv add "vulnerable-package>=fixed.version"

# 2. Test immediately
just test

# 3. Deploy ASAP
docker-compose build
docker-compose up -d
```

## 🗄️ Database Maintenance

### Neo4j Maintenance

#### Regular Tasks

```cypher
-- Check database stats
CALL dbms.queryJmx('org.neo4j:*') YIELD name, attributes;

-- Check store sizes
CALL apoc.meta.stats() YIELD nodeCount, relCount, labelCount, relTypeCount;

-- List all indexes
SHOW INDEXES;

-- List all constraints
SHOW CONSTRAINTS;
```

#### Index Maintenance

```cypher
-- Rebuild index (if performance degrades)
DROP INDEX index_name IF EXISTS;
CREATE INDEX index_name FOR (n:NodeType) ON (n.property);

-- Check index usage
CALL db.index.fulltext.queryNodes('index_name', 'search term')
YIELD node, score;
```

#### Database Cleanup

```cypher
-- Remove orphaned nodes (if any)
MATCH (n) WHERE NOT (n)--() DELETE n;

-- Find duplicate nodes (by ID)
MATCH (n:Artist)
WITH n.id as id, collect(n) as nodes
WHERE size(nodes) > 1
RETURN id, size(nodes) as count
ORDER BY count DESC;
```

See [Neo4j Indexing Guide](neo4j-indexing.md) for advanced maintenance.

### PostgreSQL Maintenance

#### Regular Tasks

```sql
-- Analyze tables (update statistics)
ANALYZE artists;
ANALYZE labels;
ANALYZE masters;
ANALYZE releases;

-- Or analyze all tables
ANALYZE;

-- Vacuum tables (reclaim storage)
VACUUM ANALYZE artists;
VACUUM ANALYZE labels;
VACUUM ANALYZE masters;
VACUUM ANALYZE releases;
```

#### Index Maintenance

```sql
-- Check index usage
SELECT
    schemaname,
    tablename,
    indexname,
    idx_scan as scans,
    idx_tup_read as tuples_read,
    idx_tup_fetch as tuples_fetched
FROM pg_stat_user_indexes
ORDER BY idx_scan DESC;

-- Rebuild index (if needed)
REINDEX INDEX idx_releases_title;

-- Rebuild all indexes on table
REINDEX TABLE releases;
```

#### Table Maintenance

```sql
-- Check table bloat
SELECT
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS total_size,
    pg_size_pretty(pg_relation_size(schemaname||'.'||tablename)) AS table_size,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename) -
                   pg_relation_size(schemaname||'.'||tablename)) AS index_size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;

-- Check for dead tuples
SELECT
    schemaname,
    tablename,
    n_live_tup as live_tuples,
    n_dead_tup as dead_tuples,
    round(n_dead_tup * 100.0 / NULLIF(n_live_tup + n_dead_tup, 0), 2) as dead_pct
FROM pg_stat_user_tables
ORDER BY dead_pct DESC;
```

#### Performance Optimization

```sql
-- Check slow queries (requires pg_stat_statements extension)
SELECT
    query,
    calls,
    total_exec_time,
    mean_exec_time,
    max_exec_time
FROM pg_stat_statements
ORDER BY mean_exec_time DESC
LIMIT 10;

-- Check cache hit ratio (should be >90%)
SELECT
    sum(heap_blks_read) as heap_read,
    sum(heap_blks_hit) as heap_hit,
    round(sum(heap_blks_hit) * 100.0 / NULLIF(sum(heap_blks_hit) + sum(heap_blks_read), 0), 2) as cache_hit_ratio
FROM pg_statio_user_tables;
```

### RabbitMQ Maintenance

#### Queue Management

```bash
# List all queues
curl -u discogsography:discogsography \
  http://localhost:15672/api/queues

# Purge a queue (if needed)
curl -u discogsography:discogsography \
  -X DELETE \
  http://localhost:15672/api/queues/%2F/queue_name/contents

# Delete a queue
curl -u discogsography:discogsography \
  -X DELETE \
  http://localhost:15672/api/queues/%2F/queue_name
```

#### Connection Management

```bash
# List connections
curl -u discogsography:discogsography \
  http://localhost:15672/api/connections

# Close a connection
curl -u discogsography:discogsography \
  -X DELETE \
  http://localhost:15672/api/connections/connection_name
```

### Redis Maintenance

```bash
# Connect to Redis
docker-compose exec redis redis-cli

# Check memory usage
INFO memory

# Check key statistics
INFO keyspace

# Clear cache (if needed)
FLUSHDB

# Clear all databases
FLUSHALL

# Check specific key
TTL discovery:genre_trends:Jazz
GET discovery:artist_network:Miles_Davis
```

## 🐋 Docker Maintenance

### Image Cleanup

```bash
# Remove unused images
docker image prune -a

# Remove all stopped containers
docker container prune

# Remove all unused volumes
docker volume prune

# Remove all unused networks
docker network prune

# Remove everything unused
docker system prune -a --volumes
```

### Rebuild Images

```bash
# Rebuild all images
docker-compose build --no-cache

# Rebuild specific service
docker-compose build --no-cache dashboard

# Rebuild and restart
docker-compose up -d --build
```

### Volume Management

```bash
# List volumes
docker volume ls

# Inspect volume
docker volume inspect discogsography_neo4j_data

# Backup volume
docker run --rm \
  -v discogsography_neo4j_data:/data \
  -v $(pwd)/backups:/backup \
  alpine tar czf /backup/neo4j-backup-$(date +%Y%m%d).tar.gz /data

# Restore volume
docker run --rm \
  -v discogsography_neo4j_data:/data \
  -v $(pwd)/backups:/backup \
  alpine tar xzf /backup/neo4j-backup-20250115.tar.gz -C /
```

## 📊 Log Management

### Log Rotation

Configure log rotation in `/etc/logrotate.d/discogsography`:

```
/var/log/discogsography/*.log {
    daily
    rotate 7
    compress
    delaycompress
    notifempty
    create 0644 discogsography discogsography
    sharedscripts
    postrotate
        docker-compose restart
    endscript
}
```

### Log Cleanup

```bash
# Clean old logs (older than 7 days)
find /var/log/discogsography -name "*.log" -mtime +7 -delete

# Or with Docker
docker-compose logs --tail=1000 > recent-logs.txt
docker-compose logs --since 24h > last-24h.txt
```

### Log Analysis

```bash
# Check for errors
uv run task check-errors

# View recent errors
docker-compose logs --since 1h | grep "ERROR"

# Count errors by service
docker-compose logs | grep "ERROR" | cut -d' ' -f2 | sort | uniq -c
```

## 🔍 Health Monitoring

### Automated Health Checks

Create a monitoring script `scripts/health-check.sh`:

```bash
#!/bin/bash

services=(
  "Extractor:8000"
  "Graphinator:8001"
  "Tableinator:8002"
  "Dashboard:8003"
  "Discovery:8004"
)

all_healthy=true

for service in "${services[@]}"; do
  name="${service%%:*}"
  port="${service##*:}"

  response=$(curl -s http://localhost:$port/health)
  if [[ $response == *"healthy"* ]]; then
    echo "✅ $name is healthy"
  else
    echo "❌ $name is unhealthy"
    all_healthy=false
  fi
done

if $all_healthy; then
  echo "✅ All services healthy"
  exit 0
else
  echo "❌ Some services unhealthy"
  exit 1
fi
```

### Cron Jobs

Schedule regular maintenance:

```bash
# Edit crontab
crontab -e

# Add maintenance jobs
# Health check every 5 minutes
*/5 * * * * /path/to/scripts/health-check.sh

# Vacuum PostgreSQL daily at 2 AM
0 2 * * * docker-compose exec postgres vacuumdb -z -d discogsography

# Backup databases weekly on Sunday at 3 AM
0 3 * * 0 /path/to/scripts/backup-databases.sh

# Clean old logs weekly on Sunday at 4 AM
0 4 * * 0 find /var/log/discogsography -name "*.log" -mtime +7 -delete
```

## 🔄 Backup and Restore

### Database Backups

#### Neo4j Backup

```bash
# Backup Neo4j database
docker-compose exec neo4j neo4j-admin backup \
  --backup-dir=/backups \
  --name=neo4j-$(date +%Y%m%d)

# Or backup the volume
docker run --rm \
  -v discogsography_neo4j_data:/data \
  -v $(pwd)/backups:/backup \
  alpine tar czf /backup/neo4j-$(date +%Y%m%d).tar.gz /data
```

#### PostgreSQL Backup

```bash
# Backup PostgreSQL database
PGPASSWORD=discogsography pg_dump \
  -h localhost -p 5433 -U discogsography \
  discogsography > backups/postgres-$(date +%Y%m%d).sql

# Or use Docker
docker-compose exec postgres pg_dump \
  -U discogsography discogsography \
  > backups/postgres-$(date +%Y%m%d).sql
```

### Restore Databases

#### Neo4j Restore

```bash
# Restore from backup
docker-compose exec neo4j neo4j-admin restore \
  --from=/backups/neo4j-20250115 \
  --database=neo4j
```

#### PostgreSQL Restore

```bash
# Restore from backup
PGPASSWORD=discogsography psql \
  -h localhost -p 5433 -U discogsography \
  discogsography < backups/postgres-20250115.sql

# Or with Docker
docker-compose exec -T postgres psql \
  -U discogsography discogsography \
  < backups/postgres-20250115.sql
```

## 📈 Performance Monitoring

### System Resources

```bash
# Monitor Docker resource usage
docker stats

# Continuous monitoring
watch -n 1 docker stats

# Monitor specific service
docker stats discogsography-dashboard-1
```

### Application Metrics

```bash
# Queue monitoring
uv run task monitor

# System monitoring
uv run task system-monitor

# Check processing rates
docker-compose logs -f | grep "📊"
```

## 🔐 Security Maintenance

### Regular Security Tasks

```bash
# Scan for vulnerabilities
just security

# Scan dependencies
uv run pip-audit

# Update security-sensitive packages
uv add "package-name>=secure.version"

# Review Docker images
docker scout cves discogsography-dashboard
```

### Access Control Review

```bash
# Review database users
# Neo4j
curl -u neo4j:password http://localhost:7474/user/neo4j/

# PostgreSQL
PGPASSWORD=discogsography psql -h localhost -p 5433 \
  -U discogsography -d discogsography -c "\du"

# RabbitMQ
curl -u discogsography:discogsography \
  http://localhost:15672/api/users
```

## 📚 Documentation Maintenance

### Keep Docs Updated

- Update version numbers
- Refresh screenshots
- Update code examples
- Add new features to guides
- Remove deprecated information

### Documentation Checklist

- [ ] README.md reflects current features
- [ ] Configuration guide has all env vars
- [ ] Architecture diagrams are current
- [ ] Quick start guide works
- [ ] All code examples run
- [ ] Links are not broken
- [ ] "Last Updated" dates are current

## 🔄 Upgrade Procedures

### Major Version Upgrades

When upgrading to a new major version:

1. **Review changelog** for breaking changes
1. **Backup all databases**
1. **Test in development** environment first
1. **Update documentation**
1. **Notify users** of changes
1. **Deploy to production**
1. **Monitor for issues**

### Python Version Upgrades

```bash
# Update Python version in pyproject.toml
requires-python = ">=3.14"

# Update Dockerfiles
FROM python:3.14-slim

# Update CI/CD
# Edit .github/workflows/*.yml

# Test thoroughly
just test
just test-e2e
```

## Related Documentation

- [Development Guide](development.md) - Development setup
- [Performance Guide](performance-guide.md) - Performance optimization
- [Database Resilience](database-resilience.md) - Connection patterns
- [Troubleshooting Guide](troubleshooting.md) - Common issues

______________________________________________________________________

**Last Updated**: 2025-01-15
