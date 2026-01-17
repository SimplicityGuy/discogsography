# Performance Quick Fixes - Implementation Guide

## Fix #1: Increase Graphinator QoS (CRITICAL - 10-20x improvement)

### Current Code
**File**: `graphinator/graphinator.py` line 1472

```python
# Current - TOO LOW!
await channel.set_qos(prefetch_count=1, global_=True)
```

### Fixed Code
```python
# Allow multiple batches to be processed concurrently
# This enables batch processor to work on multiple batches in parallel
await channel.set_qos(prefetch_count=10, global_=True)
```

**Why this helps**: With QoS=1, only 1 message is in flight at a time. With QoS=10, we can have 10 messages being processed concurrently, which with batch_size=100 means 1000 records in the pipeline.

---

## Fix #2: Increase Tableinator Connection Pool (2.5x improvement)

### Current Code
**File**: `tableinator/tableinator.py` lines 576-583

```python
# Current - TOO SMALL!
connection_pool = ResilientPostgreSQLPool(
    connection_params=connection_params,
    max_connections=20,  # ← TOO LOW
    min_connections=2,
    max_retries=5,
    health_check_interval=30,
)
```

### Fixed Code
```python
# Increase to match prefetch_count
connection_pool = ResilientPostgreSQLPool(
    connection_params=connection_params,
    max_connections=50,  # ← INCREASED to match QoS
    min_connections=5,   # ← Also increase minimum
    max_retries=5,
    health_check_interval=30,
)
```

**Why this helps**: Current settings allow prefetch of 50 messages but only 20 concurrent connections. This creates a bottleneck where 30 messages are waiting for connections.

---

## Fix #3: Increase Batch Sizes (20-30% improvement)

### Option A: Environment Variables (Recommended)
**File**: `docker-compose.yml`

Add to graphinator environment:
```yaml
graphinator:
  environment:
    # ... existing vars ...
    NEO4J_BATCH_SIZE: "500"           # ← Increased from 100
    NEO4J_BATCH_FLUSH_INTERVAL: "2.0" # ← Reduced from 5.0 for faster flush
```

Add to tableinator environment:
```yaml
tableinator:
  environment:
    # ... existing vars ...
    POSTGRES_BATCH_SIZE: "500"           # ← Increased from 100
    POSTGRES_BATCH_FLUSH_INTERVAL: "2.0" # ← Reduced from 5.0 for faster flush
```

### Option B: Code Changes
**File**: `graphinator/batch_processor.py` line 26

```python
@dataclass
class BatchConfig:
    """Configuration for batch processing."""

    batch_size: int = 500  # ← Increased from 100
    flush_interval: float = 2.0  # ← Reduced from 5.0
    max_pending: int = 5000  # ← Increased from 1000
```

**File**: `tableinator/batch_processor.py` line 28

```python
@dataclass
class BatchConfig:
    """Configuration for batch processing."""

    batch_size: int = 500  # ← Increased from 100
    flush_interval: float = 2.0  # ← Reduced from 5.0
    max_pending: int = 5000  # ← Increased from 1000
```

**Why this helps**: Larger batches amortize the transaction overhead over more records. Neo4j and PostgreSQL both handle large batches efficiently.

---

## Fix #4: Optimize PostgreSQL Batch Insert (5-10x improvement)

### Current Code (Slow)
**File**: `tableinator/batch_processor.py` lines 293-299

```python
# Current - uses individual INSERT statements
cursor.executemany(
    sql.SQL(
        "INSERT INTO {table} (hash, data_id, data) VALUES (%s, %s, %s) "
        "ON CONFLICT (data_id) DO UPDATE SET hash = EXCLUDED.hash, data = EXCLUDED.data"
    ).format(table=sql.Identifier(data_type)),
    records_to_upsert,
)
```

### Optimized Code (Fast)

```python
# Use COPY for bulk inserts - MUCH faster
# Note: COPY doesn't support ON CONFLICT, so we need a different approach

# Step 1: Create temporary table
cursor.execute(
    sql.SQL(
        "CREATE TEMP TABLE temp_{table} "
        "(hash VARCHAR, data_id VARCHAR, data JSONB) "
        "ON COMMIT DROP"
    ).format(table=sql.Identifier(data_type))
)

# Step 2: COPY data into temp table (FAST!)
from io import StringIO
import json

buffer = StringIO()
for sha256, data_id, jsonb_data in records_to_upsert:
    # COPY expects tab-separated values
    # Escape special characters in JSON
    json_str = json.dumps(jsonb_data.obj if hasattr(jsonb_data, 'obj') else jsonb_data)
    json_str = json_str.replace('\\', '\\\\').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
    buffer.write(f"{sha256}\t{data_id}\t{json_str}\n")

buffer.seek(0)

cursor.copy_from(
    buffer,
    f"temp_{data_type}",
    columns=['hash', 'data_id', 'data'],
    sep='\t'
)

# Step 3: Merge from temp table to main table (still fast)
cursor.execute(
    sql.SQL(
        "INSERT INTO {table} (hash, data_id, data) "
        "SELECT hash, data_id, data::jsonb FROM temp_{table} "
        "ON CONFLICT (data_id) DO UPDATE "
        "SET hash = EXCLUDED.hash, data = EXCLUDED.data"
    ).format(table=sql.Identifier(data_type))
)
```

**Why this helps**: COPY is PostgreSQL's native bulk load command, much faster than individual INSERTs (even with executemany).

---

## Fix #5: Reduce Index Overhead During Bulk Load

### Strategy: Drop indexes, load data, recreate indexes

**File**: `tableinator/tableinator.py` - Add helper functions

```python
def drop_indexes(cursor, data_type: str) -> list[str]:
    """Drop all indexes except primary key. Returns list of dropped index names."""
    # Get all indexes for the table
    cursor.execute(
        """
        SELECT indexname
        FROM pg_indexes
        WHERE tablename = %s
        AND indexname != %s  -- Keep primary key
        """,
        (data_type, f"{data_type}_pkey")
    )

    dropped = []
    for row in cursor.fetchall():
        index_name = row[0]
        try:
            cursor.execute(sql.SQL("DROP INDEX IF EXISTS {}").format(
                sql.Identifier(index_name)
            ))
            dropped.append(index_name)
            logger.info(f"🗑️ Dropped index {index_name} for bulk load")
        except Exception as e:
            logger.warning(f"⚠️ Could not drop index {index_name}: {e}")

    return dropped


def recreate_indexes(cursor, data_type: str):
    """Recreate indexes after bulk load."""
    # Hash index
    cursor.execute(
        sql.SQL("CREATE INDEX IF NOT EXISTS {index} ON {table} (hash)").format(
            index=sql.Identifier(f"idx_{data_type}_hash"),
            table=sql.Identifier(data_type),
        )
    )

    # GIN index on JSONB
    cursor.execute(
        sql.SQL("CREATE INDEX IF NOT EXISTS {index} ON {table} USING GIN (data)").format(
            index=sql.Identifier(f"idx_{data_type}_gin"),
            table=sql.Identifier(data_type),
        )
    )

    # Data-type specific indexes...
    # (Only recreate the most critical ones)
```

**When to use**: During initial bulk load. Not needed for incremental updates.

---

## Implementation Priority

### Phase 1: Immediate Changes (< 5 minutes)

1. **Graphinator QoS**: Change line in `graphinator/graphinator.py:1472`
2. **Tableinator Pool**: Change line in `tableinator/tableinator.py:579`
3. **Batch Sizes**: Add environment variables to `docker-compose.yml`

**Commands**:
```bash
# Edit the files
code graphinator/graphinator.py:1472
code tableinator/tableinator.py:579-583
code docker-compose.yml

# Rebuild and restart
docker-compose build graphinator tableinator
docker-compose up -d graphinator tableinator
```

**Expected improvement**: 10-15x throughput increase

### Phase 2: Code Optimization (1-2 hours)

4. **Implement COPY**: Rewrite `tableinator/batch_processor.py:248-306`
5. **Index Management**: Add index drop/recreate functions

**Expected improvement**: Additional 5-10x throughput increase

---

## Testing the Improvements

### Before Changes - Baseline
```bash
# Monitor message rates
docker-compose logs -f graphinator | grep "Batch processed"
docker-compose logs -f tableinator | grep "Batch processed"

# Example output:
# ✅ Batch processed data_type=artists batch_size=100 duration_ms=523 records_per_sec=191
```

### After Phase 1 - Should see major improvement
```bash
# Same monitoring commands
# Expected output:
# ✅ Batch processed data_type=artists batch_size=500 duration_ms=487 records_per_sec=1026
```

### Calculate Improvement
```python
# Before: 191 records/sec
# After:  1026 records/sec
# Improvement: 5.37x faster
```

---

## Rollback Plan

If issues occur:

```bash
# Revert to previous images
docker-compose down
git checkout HEAD~1  # Or specific commit
docker-compose build graphinator tableinator
docker-compose up -d
```

Or modify environment variables:
```yaml
NEO4J_BATCH_SIZE: "100"  # Original value
```

---

## Environment Variable Summary

**Add to `docker-compose.yml`**:

```yaml
graphinator:
  environment:
    # ... existing vars ...
    NEO4J_BATCH_SIZE: "500"
    NEO4J_BATCH_FLUSH_INTERVAL: "2.0"

tableinator:
  environment:
    # ... existing vars ...
    POSTGRES_BATCH_SIZE: "500"
    POSTGRES_BATCH_FLUSH_INTERVAL: "2.0"
```

---

## Success Metrics

Track these metrics before and after:

1. **Throughput**: Messages per second (from "Batch processed" logs)
2. **Latency**: duration_ms per batch
3. **Queue Depth**: Number of pending messages in RabbitMQ
4. **Database CPU**: Monitor with `docker stats`
5. **Memory Usage**: Check for any increases

**Target Goals**:
- **Phase 1**: 500-1000 msg/s (10-15x improvement)
- **Phase 2**: 2000-5000 msg/s (additional 3-5x improvement)
