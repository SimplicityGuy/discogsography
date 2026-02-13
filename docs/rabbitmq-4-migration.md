# 🐰 RabbitMQ 4.x Migration Guide

Complete migration guide for upgrading from RabbitMQ 3.13 to 4.x with quorum queues and dead-letter exchange (DLX) for poison message handling.

## 📋 Table of Contents

- [Overview](#overview)
- [What Changed](#what-changed)
- [Pre-Migration Checklist](#pre-migration-checklist)
- [Migration Steps](#migration-steps)
- [Validation & Testing](#validation--testing)
- [Monitoring](#monitoring)
- [Rollback Procedure](#rollback-procedure)
- [Troubleshooting](#troubleshooting)

---

## Overview

This migration upgrades your Discogsography project from RabbitMQ 3.13 to RabbitMQ 4.x and migrates all queues from **classic queues** to **quorum queues** with **dead-letter exchange** (DLX) for handling poison messages.

### Key Benefits

✅ **High Availability**: Quorum queues replicate across multiple nodes
✅ **Data Safety**: Raft consensus ensures no message loss
✅ **Poison Message Handling**: Automatic retry limits prevent infinite loops
✅ **Future-Proof**: Quorum queues are the default in RabbitMQ 4.2+

### Changes Made

| Component | Change |
|-----------|--------|
| **Docker Image** | `rabbitmq:3.13-management` → `rabbitmq:4-management` |
| **Queue Type** | Classic → Quorum |
| **Redelivery Limit** | None → 20 attempts |
| **Dead-Letter Exchange** | None → `discogsography.dlx` |
| **Dead-Letter Queues** | None → 8 DLQs (4 per service) |

---

## What Changed

### 1. Docker Configuration

**File: `docker-compose.yml`**
```yaml
# Before
image: rabbitmq:3.13-management

# After
image: rabbitmq:4-management
environment:
  RABBITMQ_DEFAULT_QUEUE_TYPE: quorum
```

### 2. Queue Architecture

**Before:**
```
Extractor → Exchange → [Classic Queues] → Consumers
```

**After:**
```
                    ┌─→ Quorum Queue (graphinator-artists) ─→ Consumer
                    │   └─→ DLQ (after 20 retries)
Extractor → Exchange┼─→ Quorum Queue (graphinator-labels) ─→ Consumer
                    │   └─→ DLQ (after 20 retries)
                    └─→ ... (8 total queues + 8 DLQs)
```

### 3. Queue Declaration Changes

**Python Services (Extractor, Graphinator, Tableinator):**
```python
# Added DLX exchange
dlx_exchange = f"{AMQP_EXCHANGE}.dlx"

# Added queue arguments
queue_args = {
    "x-queue-type": "quorum",
    "x-dead-letter-exchange": dlx_exchange,
    "x-delivery-limit": 20,
}

# Added DLQs for each main queue
dlq_name = f"{queue_name}.dlq"
```

**Rust Extractor:**
```rust
// Added DLX exchange
let dlx_exchange = format!("{}.dlx", AMQP_EXCHANGE);

// Added queue arguments
let mut queue_args = FieldTable::default();
queue_args.insert("x-queue-type".into(), AMQPValue::LongString("quorum".into()));
queue_args.insert("x-dead-letter-exchange".into(), AMQPValue::LongString(dlx_exchange.clone().into()));
queue_args.insert("x-delivery-limit".into(), AMQPValue::LongInt(20));
```

### 4. New Queue Structure

**Main Queues (Quorum):**
- `graphinator-artists`
- `graphinator-labels`
- `graphinator-masters`
- `graphinator-releases`
- `tableinator-artists`
- `tableinator-labels`
- `tableinator-masters`
- `tableinator-releases`

**Dead-Letter Queues (Classic):**
- `graphinator-artists.dlq`
- `graphinator-labels.dlq`
- `graphinator-masters.dlq`
- `graphinator-releases.dlq`
- `tableinator-artists.dlq`
- `tableinator-labels.dlq`
- `tableinator-masters.dlq`
- `tableinator-releases.dlq`

**Exchanges:**
- `discogsography` (main exchange - topic)
- `discogsography.dlx` (dead-letter exchange - topic)

---

## Pre-Migration Checklist

Before starting the migration, ensure:

- [ ] **Backup RabbitMQ data** (if in production)
  ```bash
  docker exec discogsography-rabbitmq rabbitmqctl export_definitions /tmp/definitions.json
  docker cp discogsography-rabbitmq:/tmp/definitions.json ./rabbitmq-backup.json
  ```

- [ ] **Check disk space** (quorum queues use ~3x storage for replication)
  ```bash
  df -h
  ```

- [ ] **Note current queue depths**
  ```bash
  docker exec discogsography-rabbitmq rabbitmqctl list_queues name messages
  ```

- [ ] **Stop all consumers** to drain queues (optional but recommended)
  ```bash
  docker-compose stop extractor graphinator tableinator
  ```

- [ ] **Wait for queues to empty** (optional but cleaner)
  ```bash
  # Monitor until all queues show 0 messages
  docker exec discogsography-rabbitmq rabbitmqctl list_queues name messages
  ```

---

## Migration Steps

### Step 1: Pull Latest Code

Ensure you have the latest code with RabbitMQ 4.x changes:

```bash
git pull origin main
```

### Step 2: Stop All Services

```bash
docker-compose down
```

**⚠️ Important:** This will disconnect all services from RabbitMQ.

### Step 3: Remove Old RabbitMQ Data (Development Only)

**⚠️ WARNING:** This deletes all existing queues and messages!

```bash
# Development environments only
docker volume rm discogsography_rabbitmq_data
```

**For Production:** Skip this step to preserve existing data. RabbitMQ 4.x can coexist with classic queues, but new queues will be created as quorum.

### Step 4: Pull New RabbitMQ Image

```bash
docker-compose pull rabbitmq
```

Verify the image version:
```bash
docker images rabbitmq
# Should show: rabbitmq:4-management
```

### Step 5: Start RabbitMQ

```bash
docker-compose up -d rabbitmq
```

Wait for RabbitMQ to be healthy:
```bash
docker-compose logs -f rabbitmq
# Look for: "Server startup complete"
```

### Step 6: Verify RabbitMQ Version

```bash
docker exec discogsography-rabbitmq rabbitmqctl version
# Should show: 4.x.x
```

### Step 7: Start Services

```bash
# Start extractor (creates queues)
docker-compose up -d extractor

# Wait 10 seconds for queues to be created
sleep 10

# Start consumers
docker-compose up -d graphinator tableinator

# Start dashboard
docker-compose up -d dashboard
```

---

## Validation & Testing

### 1. Verify Queue Types

```bash
docker exec discogsography-rabbitmq rabbitmqctl list_queues name type durable auto_delete arguments
```

**Expected Output:**
```
graphinator-artists    quorum    true    false    [{x-queue-type,<<"quorum">>},{x-dead-letter-exchange,<<"discogsography.dlx">>},{x-delivery-limit,20}]
graphinator-artists.dlq    classic    true    false    [{x-queue-type,<<"classic">>}]
...
```

### 2. Verify Exchanges

```bash
docker exec discogsography-rabbitmq rabbitmqctl list_exchanges name type durable
```

**Expected Output:**
```
discogsography        topic    true
discogsography.dlx    topic    true
```

### 3. Verify Bindings

```bash
docker exec discogsography-rabbitmq rabbitmqctl list_bindings
```

**Expected:**
- Main queues bound to `discogsography` exchange
- DLQs bound to `discogsography.dlx` exchange

### 4. Test Message Flow

Start a small extraction to verify messages flow correctly:

```bash
# Check extractor logs
docker-compose logs -f extractor

# Check consumer logs
docker-compose logs -f graphinator tableinator
```

**Verify:**
- ✅ Messages published successfully
- ✅ Messages consumed successfully
- ✅ No errors in logs

### 5. Test Poison Message Handling (Optional)

To test DLQ functionality, you would need to:
1. Inject a malformed message
2. Verify it gets redelivered 20 times
3. Confirm it moves to DLQ

**This is advanced testing and not required for basic migration.**

### 6. Check RabbitMQ Management UI

Visit http://localhost:15672 (user: `discogsography`, pass: `discogsography`)

**Verify:**
- [ ] All 8 main queues show type "quorum"
- [ ] All 8 DLQs show type "classic"
- [ ] Both exchanges exist
- [ ] Bindings are correct

---

## Monitoring

### Key Metrics to Watch

**1. Queue Depth**
```bash
watch -n 5 'docker exec discogsography-rabbitmq rabbitmqctl list_queues name messages'
```

**2. Consumer Count**
```bash
docker exec discogsography-rabbitmq rabbitmqctl list_queues name consumers
```

**3. DLQ Depth (Poison Messages)**
```bash
docker exec discogsography-rabbitmq rabbitmqctl list_queues name messages | grep dlq
```

**4. Redelivery Counts**
```bash
# Check message headers in RabbitMQ Management UI
# Messages should have "x-delivery-count" header
```

### Dashboard Monitoring

The dashboard at http://localhost:8003 shows:
- Queue depths
- Processing rates
- Consumer status

### Log Monitoring

```bash
# Watch all service logs
docker-compose logs -f

# Watch specific service
docker-compose logs -f graphinator
```

---

## Rollback Procedure

If you need to rollback to RabbitMQ 3.13:

### Step 1: Stop All Services

```bash
docker-compose down
```

### Step 2: Restore Old Configuration

```bash
git checkout HEAD~1 -- docker-compose.yml
git checkout HEAD~1 -- extractor/
git checkout HEAD~1 -- graphinator/
git checkout HEAD~1 -- tableinator/
```

### Step 3: Remove RabbitMQ Data

```bash
docker volume rm discogsography_rabbitmq_data
```

### Step 4: Restore Backup (If Available)

```bash
docker-compose up -d rabbitmq
# Wait for startup
docker cp ./rabbitmq-backup.json discogsography-rabbitmq:/tmp/definitions.json
docker exec discogsography-rabbitmq rabbitmqctl import_definitions /tmp/definitions.json
```

### Step 5: Restart Services

```bash
docker-compose up -d
```

---

## Troubleshooting

### Issue: Queues Not Created

**Symptoms:** No queues visible in RabbitMQ Management UI

**Solution:**
```bash
# Check extractor logs
docker-compose logs extractor

# Manually trigger queue creation by restarting extractor
docker-compose restart extractor
```

### Issue: "Queue Not Found" Errors

**Symptoms:** Consumers can't find queues

**Solution:**
```bash
# Ensure extractor started first (it creates queues)
docker-compose up -d extractor
sleep 10
docker-compose up -d graphinator tableinator
```

### Issue: DLQs Filling Up

**Symptoms:** Dead-letter queues accumulating messages

**Cause:** Messages are failing 20+ times (poison messages)

**Solution:**
1. Inspect DLQ messages in Management UI
2. Identify problematic records
3. Fix data quality or consumer logic
4. Purge DLQ or requeue after fix:
   ```bash
   docker exec discogsography-rabbitmq rabbitmqctl purge_queue graphinator-artists.dlq
   ```

### Issue: High Latency

**Symptoms:** Slower message processing

**Cause:** Quorum queues have higher latency due to consensus

**Solution:**
- Expected behavior - trade-off for data safety
- Ensure proper QoS settings (prefetch_count=200)
- Monitor if latency is acceptable for your use case
- If needed, increase batch sizes for better throughput

### Issue: High Disk Usage

**Symptoms:** RabbitMQ using 3x more disk space

**Cause:** Quorum queues replicate data (even in single-node setup)

**Solution:**
- Expected behavior for quorum queues
- Ensure adequate disk space
- Monitor with: `df -h`
- Consider `x-max-length` if needed (not set by default)

### Issue: Connection Refused

**Symptoms:** Services can't connect to RabbitMQ

**Solution:**
```bash
# Check RabbitMQ health
docker-compose ps rabbitmq

# Check logs
docker-compose logs rabbitmq

# Wait for "Server startup complete" message
```

---

## Additional Resources

### RabbitMQ 4.x Documentation

- [RabbitMQ 4.0 Release Notes](https://github.com/rabbitmq/rabbitmq-server/blob/main/release-notes/4.0.1.md)
- [Quorum Queues Guide](https://www.rabbitmq.com/docs/quorum-queues)
- [Dead Letter Exchanges](https://www.rabbitmq.com/docs/dlx)
- [Migration from Classic to Quorum](https://www.rabbitmq.com/blog/2023/03/02/quorum-queues-migration)

### Project Documentation

- [Architecture Overview](architecture.md)
- [Monitoring Guide](monitoring.md)
- [Troubleshooting Guide](troubleshooting.md)

---

## Summary

✅ **Completed:**
- Docker image upgraded to RabbitMQ 4
- All queues migrated to quorum type
- Dead-letter exchange configured
- 8 DLQs created for poison messages
- Automatic retry limit set to 20

✅ **Benefits:**
- High availability and data safety
- Poison message protection
- Future-proof architecture
- Better fault tolerance

⚠️ **Trade-offs:**
- Slightly higher latency
- Higher disk usage (~3x)
- More complex queue architecture

🎯 **Next Steps:**
1. Monitor queue depths and DLQs
2. Test with full Discogs extraction
3. Tune batch sizes if needed
4. Document any custom poison message handling

---

**Questions or Issues?** Check the [Troubleshooting](#troubleshooting) section or open a GitHub issue.
