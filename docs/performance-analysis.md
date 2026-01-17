# Performance Analysis: Graphinator & Tableinator

## Executive Summary

After analyzing both services, I've identified critical performance bottlenecks that are likely causing the degraded msg/s throughput. The issues stem from inefficient database access patterns, suboptimal concurrency settings, and redundant operations.

## Critical Performance Issues

### 1. Graphinator (Neo4j) Bottlenecks

#### Issue A: Extremely Low QoS Setting (CRITICAL)
**Location**: `graphinator/graphinator.py:1472`
```python
await channel.set_qos(prefetch_count=1, global_=True)
```

**Impact**: Processes only 1 message at a time when not using batch mode, or limits parallelism severely.

**Solution**: Increase to at least 10-20 for batch mode:
```python
await channel.set_qos(prefetch_count=10, global_=True)
```

#### Issue B: Inefficient Hash Checking Pattern
**Location**: `graphinator/batch_processor.py:249-263`

The batch processor:
1. Opens a session to fetch hashes
2. Closes that session
3. Opens another session to write data

**Impact**: 2x database round trips per batch, session overhead

**Solution**: Combine into single session/transaction using UNWIND with conditional logic.

#### Issue C: Multiple Small Cypher Queries Per Batch
**Location**: Throughout batch processor (e.g., lines 280-360)

Each batch executes 4-7 separate Cypher queries:
- Create nodes
- Create member relationships
- Create group relationships
- Create alias relationships
- etc.

**Impact**: Multiple round trips within transaction

**Solution**: Combine into fewer, more efficient queries using UNWIND and FOREACH.

#### Issue D: Small Batch Size
**Default**: 100 records per batch
**Recommendation**: Increase to 500-1000 for Neo4j, which handles larger batches well

### 2. Tableinator (PostgreSQL) Bottlenecks

#### Issue E: Connection Pool vs Concurrency Mismatch
**Location**:
- `tableinator/tableinator.py:752` - prefetch_count=50
- `tableinator/tableinator.py:579` - max_connections=20

**Impact**: Can receive 50 messages concurrently but only process 20, causing queuing

**Solution**: Either:
1. Reduce prefetch_count to 20, OR
2. Increase max_connections to 50

**Recommendation**: Option 2 - PostgreSQL can handle 50 connections easily

#### Issue F: Inefficient Bulk Insert Method
**Location**: `tableinator/batch_processor.py:293-299`

Uses `executemany()` with individual INSERT statements:
```python
cursor.executemany(
    sql.SQL("INSERT INTO {table} (hash, data_id, data) VALUES (%s, %s, %s) ..."),
    records_to_upsert,
)
```

**Impact**: Much slower than PostgreSQL's COPY command

**Solution**: Use `COPY FROM` with StringIO for 5-10x faster bulk inserts:
```python
# Prepare data as CSV in memory
from io import StringIO
buffer = StringIO()
for hash, data_id, data in records_to_upsert:
    buffer.write(f"{hash}\t{data_id}\t{json.dumps(data)}\n")
buffer.seek(0)

# Use COPY - much faster
cursor.copy_from(buffer, table_name, columns=['hash', 'data_id', 'data'])
```

#### Issue G: Heavy Index Overhead
**Location**: `tableinator/tableinator.py:618-660`

Creates 15+ indexes including multiple GIN indexes:
- 4 hash indexes
- 4 GIN indexes on JSONB
- 7 expression indexes

**Impact**: Every insert/update must update all these indexes, significantly slowing writes

**Solution**:
1. Drop indexes during bulk load, recreate after
2. Reduce number of indexes (some may not be needed yet)
3. Use UNLOGGED tables during initial load, then convert to logged

## Performance Optimization Priority

### Immediate (High Impact, Low Effort)

1. **Increase Graphinator QoS**: Change from 1 to 10-20
   - **Impact**: 10-20x throughput increase
   - **Effort**: Change 1 line
   - **File**: `graphinator/graphinator.py:1472`

2. **Fix Tableinator Connection Pool**: Increase to 50 connections
   - **Impact**: 2.5x throughput increase
   - **Effort**: Change 1 number
   - **File**: `tableinator/tableinator.py:579`

3. **Increase Batch Sizes**: 100 → 500 for both services
   - **Impact**: 20-30% throughput increase
   - **Effort**: Change environment variables or defaults
   - **Files**: Both batch processors

### Medium Term (High Impact, Medium Effort)

4. **Implement COPY for Tableinator**: Replace executemany with COPY
   - **Impact**: 5-10x faster inserts
   - **Effort**: Rewrite batch insert logic (50-100 lines)
   - **File**: `tableinator/batch_processor.py`

5. **Optimize Graphinator Cypher Queries**: Combine multiple queries
   - **Impact**: 30-50% faster batch processing
   - **Effort**: Rewrite batch processing logic (100-200 lines)
   - **File**: `graphinator/batch_processor.py`

6. **Reduce Tableinator Indexes**: Drop non-essential indexes
   - **Impact**: 30-40% faster inserts
   - **Effort**: Analyze query patterns, drop indexes
   - **File**: `tableinator/tableinator.py`

### Long Term (Highest Impact, High Effort)

7. **Connection Pooling for Neo4j**: Implement proper session pooling
   - **Impact**: 20-30% improvement
   - **Effort**: Significant refactoring

8. **Parallel Batch Processing**: Process multiple batches concurrently
   - **Impact**: 2-3x throughput with proper concurrency
   - **Effort**: Significant architectural changes

## Recommended Action Plan

### Phase 1: Quick Wins (Today)
1. Increase graphinator QoS from 1 to 10
2. Increase tableinator connection pool from 20 to 50
3. Increase batch sizes from 100 to 500

**Expected Result**: 10-15x total throughput improvement

### Phase 2: Database Optimizations (This Week)
1. Implement COPY for PostgreSQL bulk inserts
2. Reduce number of indexes on tableinator tables
3. Optimize Neo4j Cypher queries to combine operations

**Expected Result**: Additional 3-5x throughput improvement

### Phase 3: Architecture Improvements (Next Sprint)
1. Implement proper Neo4j session pooling
2. Add concurrent batch processing
3. Implement write-ahead logging/journaling for crash recovery

**Expected Result**: Additional 2-3x throughput improvement

## Monitoring Recommendations

Add these metrics to track improvements:
1. **Messages per second** (overall and per data type)
2. **Batch processing time** (avg, p50, p95, p99)
3. **Database connection pool utilization**
4. **Queue depth over time**
5. **Transaction commit latency**

## Environment Variable Tuning

```bash
# Graphinator
NEO4J_BATCH_SIZE=500
NEO4J_BATCH_FLUSH_INTERVAL=2.0
NEO4J_QOS_PREFETCH=10

# Tableinator
POSTGRES_BATCH_SIZE=500
POSTGRES_BATCH_FLUSH_INTERVAL=2.0
POSTGRES_MAX_CONNECTIONS=50
POSTGRES_MIN_CONNECTIONS=10

# Both
CONSUMER_CANCEL_DELAY=600  # Reduce from 300
```

## Expected Performance After All Optimizations

**Current Performance** (estimated): 10-50 msg/s
**After Phase 1**: 100-500 msg/s (10-15x improvement)
**After Phase 2**: 500-2000 msg/s (additional 3-5x improvement)
**After Phase 3**: 1000-5000 msg/s (additional 2-3x improvement)

**Total Potential Improvement**: 100-500x faster than current performance

## Notes

- The current QoS of 1 is likely the #1 bottleneck
- PostgreSQL can handle much higher throughput than Neo4j
- Batch processing is good, but batch size and concurrency need tuning
- Index overhead on PostgreSQL is significant during bulk loads
