# 📊 Neo4j 2026 Migration Guide

Complete migration guide for upgrading from Neo4j 5.25-community to Neo4j 2026-community with calendar versioning.

## 📋 Table of Contents

- [Overview](#overview)
- [Breaking Changes](#breaking-changes)
- [Pre-Migration Analysis](#pre-migration-analysis)
- [Required Changes](#required-changes)
- [Migration Steps](#migration-steps)
- [Validation & Testing](#validation--testing)
- [Rollback Procedure](#rollback-procedure)
- [Troubleshooting](#troubleshooting)

---

## Overview

Neo4j switched to **calendar versioning (CalVer)** starting January 2025, using the format `YYYY.MM.PATCH`. This migration upgrades from **Neo4j 5.25** to **Neo4j 2026.x**, which represents a significant architectural change.

### Current State

| Component | Current Version | Target Version |
|-----------|----------------|----------------|
| **Neo4j Server** | 5.25-community | 2026-community |
| **Python Driver** | neo4j>=5.0.0 / >=5.15.0 | neo4j>=6.1.0 |
| **APOC Plugin** | Auto-downloaded (5.x) | Auto-downloaded (2026.x) |
| **Cypher Queries** | Neo4j 5 syntax | Neo4j 2026 syntax |

### Key Benefits

✅ **Latest Features**: Access to newest Neo4j capabilities
✅ **Better Performance**: Improved query optimization
✅ **Long-term Support**: Calendar versioning provides clearer support timeline
✅ **Security Updates**: Latest security patches
✅ **Future-Proof**: Aligned with Neo4j's new versioning strategy

---

## Breaking Changes

### 1. Calendar Versioning (CalVer)

**Impact**: Major change from semantic versioning to calendar versioning.

**Before**:
```yaml
image: neo4j:5.25-community
```

**After**:
```yaml
image: neo4j:2026-community  # or neo4j:2026.01-community for specific version
```

### 2. Discovery Service Changes

**Breaking Change**: Discovery service v1 removed in Neo4j 2025.01+

**Settings Removed**:
- `server.discovery.advertised_address`
- `server.discovery.listen_address`

**Replacement**:
- Use `server.cluster.advertised_address` instead

**Impact**: ⚠️ **LOW** - You're running single-node setup, not a cluster

### 3. Python Driver Compatibility

**Breaking Change**: Neo4j 2026 requires Python driver 6.x

**Current**:
```python
neo4j>=5.0.0
neo4j>=5.15.0
```

**Required**:
```python
neo4j>=6.1.0
```

**Impact**: ⚠️ **MEDIUM** - Driver API changes possible

### 4. APOC Plugin Versioning

**Breaking Change**: APOC version must match Neo4j version

**Current**: APOC 5.x (auto-downloaded)
**Required**: APOC 2026.x (auto-downloaded)

**Impact**: ✅ **LOW** - Auto-downloaded via `NEO4J_PLUGINS` environment variable

### 5. Cypher Query Language

**Breaking Change**: Cypher 25 introduces new features and deprecations

**Potential Issues**:
- Some legacy syntax deprecated
- New reserved keywords
- Query optimization changes

**Impact**: ⚠️ **MEDIUM** - Need to audit Cypher queries

---

## Pre-Migration Analysis

### Current Neo4j Usage

#### **Services Using Neo4j**:
1. **Graphinator** - Primary graph builder (writes)
2. **Dashboard** - Statistics and monitoring (reads)
3. **Explore** - Graph exploration API (reads)
4. **Discovery** - ML/analytics engine (reads/writes)

#### **Python Driver Usage**:
- **Sync Driver**: `GraphDatabase.driver()` (limited use)
- **Async Driver**: `AsyncGraphDatabase.driver()` (primary use)
- **Resilient Wrappers**: `AsyncResilientNeo4jDriver` (all services)

#### **APOC Usage**:
Found APOC usage in:
```python
# dashboard/dashboard.py:366
result = await session.run("CALL apoc.meta.stats() YIELD nodeCount, relCount")
```

**Impact**: ✅ **LOW** - Minimal APOC usage, just metadata

#### **Cypher Query Complexity**:
- **Simple Queries**: Basic MATCH/CREATE/MERGE operations
- **Complex Queries**: Graph algorithms, recommendations, analytics
- **Batch Operations**: Large-scale MERGE operations in graphinator

#### **Configuration Settings**:
```yaml
NEO4J_PLUGINS: '["apoc"]'
NEO4J_apoc_export_file_enabled: 'true'
NEO4J_apoc_import_file_enabled: 'true'
NEO4J_apoc_import_file_use__neo4j__config: 'true'
NEO4J_ACCEPT_LICENSE_AGREEMENT: 'yes'
NEO4J_dbms_logs_debug_level: WARN
NEO4J_dbms_memory_heap_initial__size: 1G
NEO4J_dbms_memory_heap_max__size: 2G
NEO4J_dbms_memory_transaction_total_max: 6G
NEO4J_dbms_memory_pagecache_size: 1G
```

**Impact**: ✅ **LOW** - All settings compatible with Neo4j 2026

---

## Required Changes

### 1. Docker Configuration

#### **File: `docker-compose.yml`**

**Change Line 81:**
```yaml
# Before
image: neo4j:5.25-community

# After
image: neo4j:2026-community
```

**Optional: Pin to Specific Version**
```yaml
# For reproducibility
image: neo4j:2026.01-community
```

### 2. Python Driver Upgrade

#### **Files to Update:**

**`pyproject.toml` (root)**
```toml
# Before
"neo4j>=5.0.0"

# After
"neo4j>=6.1.0"
```

**Service-specific `pyproject.toml` files:**
- `dashboard/pyproject.toml`
- `graphinator/pyproject.toml`
- `explore/pyproject.toml`
- `discovery/pyproject.toml`
- `common/pyproject.toml`

**Change:**
```toml
# Before
"neo4j>=5.15.0"

# After
"neo4j>=6.1.0"
```

### 3. Driver API Changes

#### **Review Required**: Check for breaking changes in Python driver 6.x

**Potential Changes**:
- Session configuration options
- Transaction management
- Error handling
- Type hints

**Files to Audit**:
- `common/neo4j_resilient.py`
- `graphinator/graphinator.py`
- `graphinator/batch_processor.py`
- `dashboard/dashboard.py`
- `explore/explore.py`
- `discovery/*.py`

### 4. Cypher Query Audit

#### **Files with Cypher Queries** (51 files found):

**High Priority** (Complex queries):
- `graphinator/batch_processor.py` - Batch MERGE operations
- `discovery/recommender.py` - Recommendation algorithms
- `discovery/graph_explorer.py` - Graph traversal
- `discovery/analytics.py` - Analytics queries
- `discovery/community_detection.py` - Graph algorithms

**Medium Priority** (Standard queries):
- `explore/neo4j_queries.py` - Exploration queries
- `dashboard/dashboard.py` - Stats queries

**Low Priority** (Tests):
- `tests/**/*.py` - Test queries

#### **Query Compatibility Checklist**:
- [ ] Review deprecated syntax
- [ ] Check new reserved keywords
- [ ] Verify query performance
- [ ] Test batch operations
- [ ] Validate APOC calls

---

## Migration Steps

### Pre-Migration Checklist

- [ ] **Backup Neo4j Data**
  ```bash
  # Export database
  docker exec discogsography-neo4j neo4j-admin database dump neo4j --to-path=/backups
  docker cp discogsography-neo4j:/backups ./neo4j-backup-$(date +%Y%m%d)
  ```

- [ ] **Document Current State**
  ```bash
  # Node counts
  docker exec discogsography-neo4j cypher-shell -u neo4j -p discogsography \
    "MATCH (n) RETURN labels(n) as label, count(*) as count"

  # Relationship counts
  docker exec discogsography-neo4j cypher-shell -u neo4j -p discogsography \
    "MATCH ()-[r]->() RETURN type(r) as type, count(*) as count"

  # Indexes
  docker exec discogsography-neo4j cypher-shell -u neo4j -p discogsography \
    "SHOW INDEXES"

  # Constraints
  docker exec discogsography-neo4j cypher-shell -u neo4j -p discogsography \
    "SHOW CONSTRAINTS"
  ```

- [ ] **Check Disk Space**
  ```bash
  df -h
  # Need ~2x current Neo4j data size for safe migration
  ```

- [ ] **Review Release Notes**
  - [Neo4j 2025.x Changes](https://neo4j.com/docs/operations-manual/current/changes-deprecations-removals/)
  - [Migration Guide](https://neo4j.com/docs/upgrade-migration-guide/current/version-2025/upgrade/)

### Step 1: Update Python Dependencies

```bash
# Update all pyproject.toml files
uv remove neo4j
uv add "neo4j>=6.1.0"

# Sync dependencies
uv sync --all-extras
```

### Step 2: Update Driver Code (If Needed)

Check Python driver 6.x migration guide for API changes:
- [Neo4j Python Driver 6.1 Docs](https://neo4j.com/docs/api/python-driver/current/)

**Common Changes**:
- Session configuration options may have changed
- Type hints updated
- Error handling improvements

### Step 3: Update Docker Configuration

```bash
# Update docker-compose.yml
# Change line 81: neo4j:5.25-community → neo4j:2026-community
```

### Step 4: Stop Services

```bash
docker-compose down
```

### Step 5: Remove Old Neo4j Data (Development Only)

**⚠️ WARNING**: This deletes all graph data!

```bash
# Development environments only
docker volume rm discogsography_neo4j_data
docker volume rm discogsography_neo4j_logs
```

**For Production**: Keep data volumes and perform in-place upgrade (see Production Upgrade section below).

### Step 6: Pull New Neo4j Image

```bash
docker-compose pull neo4j
```

Verify the image:
```bash
docker images neo4j
# Should show: neo4j:2026-community
```

### Step 7: Start Neo4j

```bash
docker-compose up -d neo4j
```

Watch startup logs:
```bash
docker-compose logs -f neo4j
# Look for: "Started"
```

### Step 8: Verify Neo4j Version

```bash
# Check version
docker exec discogsography-neo4j neo4j --version

# Should show: neo4j 2026.x.x
```

### Step 9: Verify APOC Plugin

```bash
docker exec discogsography-neo4j cypher-shell -u neo4j -p discogsography \
  "CALL apoc.help('meta')"
```

Expected: List of APOC metadata procedures.

### Step 10: Start Services

```bash
# Start all services
docker-compose up -d

# Monitor logs
docker-compose logs -f graphinator dashboard explore discovery
```

---

## Validation & Testing

### 1. Verify Neo4j Connection

```bash
# Check health
curl http://localhost:7474

# Test Cypher shell
docker exec discogsography-neo4j cypher-shell -u neo4j -p discogsography \
  "RETURN 1 as health"
```

### 2. Test APOC Functions

```bash
docker exec discogsography-neo4j cypher-shell -u neo4j -p discogsography \
  "CALL apoc.meta.stats() YIELD nodeCount, relCount RETURN nodeCount, relCount"
```

### 3. Test Python Driver

```bash
# Run a simple query from Python
uv run python -c "
from neo4j import GraphDatabase

driver = GraphDatabase.driver('bolt://localhost:7687', auth=('neo4j', 'discogsography'))
with driver.session() as session:
    result = session.run('RETURN 1 as test')
    print(result.single()['test'])
driver.close()
"
```

### 4. Run Graphinator Test

```bash
# Test graph writing
docker-compose logs -f graphinator

# Should see successful message processing
```

### 5. Test Dashboard

```bash
# Visit dashboard
open http://localhost:8003

# Check stats are loading
```

### 6. Test Explore API

```bash
# Test exploration endpoint
curl http://localhost:8006/api/artists?limit=10
```

### 7. Run Discovery Tests

```bash
# Test recommendation engine
curl http://localhost:8005/api/similar/artist/12345
```

### 8. Run Integration Tests

```bash
# Run Neo4j-related tests
uv run pytest tests/test_neo4j*.py -v
uv run pytest tests/graphinator/ -v
uv run pytest tests/explore/ -v
uv run pytest tests/discovery/ -v
```

---

## Production Upgrade Strategy

### Option 1: In-Place Upgrade (Online Upgrade)

Neo4j supports online upgrades from 5.x to 2025.x/2026.x.

**Steps**:
1. Ensure all services are running and healthy
2. Update Docker image in docker-compose.yml
3. Run `docker-compose up -d neo4j`
4. Neo4j will automatically upgrade the database
5. Monitor logs for migration progress
6. Verify all services reconnect successfully

**Downtime**: ~5-10 minutes (during Neo4j restart)

### Option 2: Blue-Green Deployment

**Steps**:
1. Set up new Neo4j 2026 instance
2. Stop graphinator (stop writes)
3. Export data from old instance
4. Import data into new instance
5. Switch services to new instance
6. Verify and cutover

**Downtime**: ~30-60 minutes (depending on data size)

### Option 3: Parallel Running

**Steps**:
1. Run Neo4j 2026 in parallel with 5.25
2. Configure graphinator to write to both
3. Sync data between instances
4. Gradually migrate read traffic
5. Decommission old instance

**Downtime**: Near-zero (complex setup)

---

## Rollback Procedure

### Quick Rollback (Development)

```bash
# Stop everything
docker-compose down

# Restore old configuration
git checkout HEAD~1 -- docker-compose.yml pyproject.toml */pyproject.toml

# Restore old data (if backed up)
docker volume rm discogsography_neo4j_data
# Restore from backup

# Downgrade Python driver
uv remove neo4j
uv add "neo4j>=5.15.0"
uv sync

# Restart
docker-compose up -d
```

### Production Rollback

**If upgrade fails**:

1. **Stop Neo4j 2026**:
   ```bash
   docker-compose stop neo4j
   ```

2. **Restore from Backup**:
   ```bash
   # Restore database dump
   docker cp neo4j-backup-20260212/neo4j.dump discogsography-neo4j:/backups/
   docker exec discogsography-neo4j neo4j-admin database load neo4j --from-path=/backups
   ```

3. **Revert Docker Image**:
   ```yaml
   image: neo4j:5.25-community
   ```

4. **Restart**:
   ```bash
   docker-compose up -d neo4j
   ```

---

## Troubleshooting

### Issue: Neo4j Won't Start

**Symptoms**: Container keeps restarting

**Solutions**:
```bash
# Check logs
docker-compose logs neo4j

# Common issues:
# 1. Memory constraints - increase heap size
# 2. Permissions - check volume ownership
# 3. Port conflicts - check 7474/7687 availability
```

### Issue: APOC Plugin Not Found

**Symptoms**: `CALL apoc.*` returns "no such procedure"

**Solution**:
```bash
# Verify APOC is installed
docker exec discogsography-neo4j ls -la /var/lib/neo4j/plugins/

# Should show: apoc-2026.x.x-core.jar

# If missing, restart Neo4j
docker-compose restart neo4j
```

### Issue: Python Driver Incompatibility

**Symptoms**: Connection errors, API errors

**Solution**:
```bash
# Check driver version
uv run python -c "import neo4j; print(neo4j.__version__)"

# Should be: 6.1.x

# If not, reinstall
uv remove neo4j
uv add "neo4j>=6.1.0"
uv sync
```

### Issue: Query Performance Degradation

**Symptoms**: Queries running slower than before

**Solutions**:
1. **Rebuild Indexes**:
   ```cypher
   SHOW INDEXES;
   // Recreate any missing indexes
   ```

2. **Update Statistics**:
   ```cypher
   CALL db.stats.clear();
   ```

3. **Check Query Plans**:
   ```cypher
   EXPLAIN <your query>
   PROFILE <your query>
   ```

### Issue: Connection Timeouts

**Symptoms**: Services can't connect to Neo4j

**Solution**:
```bash
# Check Neo4j is listening
docker exec discogsography-neo4j ss -tlnp | grep 7687

# Test from host
nc -zv localhost 7687

# Check network connectivity
docker network inspect discogsography_discogsography
```

### Issue: Data Migration Errors

**Symptoms**: Database upgrade fails

**Solution**:
```bash
# Check Neo4j logs for specific errors
docker-compose logs neo4j | grep ERROR

# Common causes:
# 1. Incompatible schema
# 2. Corrupt data
# 3. Version incompatibility

# Resolution: Restore from backup and report issue
```

---

## Additional Resources

### Official Documentation

- [Neo4j Upgrade Guide](https://neo4j.com/docs/upgrade-migration-guide/current/)
- [Neo4j 2025.x Changes](https://neo4j.com/docs/upgrade-migration-guide/current/version-2025/upgrade/)
- [Python Driver 6.1](https://neo4j.com/docs/api/python-driver/current/)
- [APOC Documentation](https://neo4j.com/docs/apoc/current/)
- [Calendar Versioning Announcement](https://feedback.neo4j.com/changelog/important-update-calendar-versioning-cypher-25)
- [Neo4j Supported Versions](https://neo4j.com/developer/kb/neo4j-supported-versions/)

### Project Documentation

- [Architecture Overview](architecture.md)
- [Database Schema](database-schema.md)
- [Neo4j Indexing](neo4j-indexing.md)
- [Troubleshooting](troubleshooting.md)

---

## Summary

### Changes Required

| Component | Current | Target | Complexity |
|-----------|---------|--------|------------|
| Docker Image | 5.25-community | 2026-community | Low |
| Python Driver | >=5.0.0/5.15.0 | >=6.1.0 | Medium |
| APOC Plugin | Auto (5.x) | Auto (2026.x) | Low |
| Cypher Queries | 5.x syntax | 2026 syntax | Medium |
| Configuration | Compatible | Compatible | Low |

### Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Data Loss | Low | High | Backup before migration |
| Query Breakage | Medium | Medium | Audit Cypher queries |
| Driver Issues | Low | Medium | Test with driver 6.1 |
| Downtime | High | Low | Plan maintenance window |
| Performance | Low | Low | Monitor and optimize |

### Recommended Approach

1. **Development**: Clean migration (delete data, fresh start)
2. **Production**: In-place upgrade with backup (5-10 min downtime)

### Timeline Estimate

- **Planning & Backups**: 1-2 hours
- **Code Updates**: 2-4 hours
- **Testing**: 4-8 hours
- **Production Migration**: 1-2 hours
- **Total**: 1-2 days

---

**Ready to proceed with Neo4j 2026 migration!** Follow this guide for a smooth upgrade process. 🚀
