# PostgreSQL Connection-Pool Exhaustion — Root-Cause Analysis

## Context

In production all long-lived services connect to a shared PostgreSQL through a
**PgBouncer pooler in session-pooling mode** (`POSTGRES_HOST=pgbouncer:6432`). In
session mode every client connection is pinned to a dedicated Postgres backend for its
entire lifetime — there is no multiplexing, even while the connection is idle. PgBouncer
enforces a **per-database backend cap of 45**. The total number of Postgres connections
the discogsography app holds open is therefore its real footprint and must stay modest.

### Observed symptoms (during a MusicBrainz bulk import)

- `brainztableinator` logs repeatedly: `⚠️ Connection pool exhausted (attempt 1/5),
  waiting for available connection...` (`common/postgres_resilient.py:512`).
- PgBouncer: 45/45 server connections in use, 0 idle, ~18 client connections queued, max
  wait ~78–107 s (hard `query_wait_timeout` is 120 s).
- Postgres: ~46 backends — 3 active, 14 idle, 29 *idle in transaction*. The
  *idle in transaction* backends cycle sub-millisecond running
  `INSERT INTO musicbrainz.relationships (...)` — genuine work, not a hung leak.
- No crashes (the 5-retry resilient pool absorbs it), but the import is throttled and
  constantly churning on "pool exhausted".

The app collectively wants ~63 connections against a 45 cap.

---

## 1. Per-service connection-pool sizing

The pool class is `AsyncPostgreSQLPool` in `common/postgres_resilient.py:303` with
constructor defaults `max_connections=20, min_connections=2`. Each service overrides
these at construction.

### Before this change

| Service | Pool site (before) | min | max | Write model |
| --- | --- | --- | --- | --- |
| api | `api/api.py:218` | 2 | 10 | connection-per-request |
| tableinator | `tableinator/tableinator.py:893` | 5 | 50 | **batched** — `BatchProcessor`, semaphore caps concurrent flushes at 2 |
| brainztableinator | `brainztableinator/brainztableinator.py:964` | 5 | 50 | **one transaction per message**, prefetch 200 × 4 consumers |
| insights | `insights/insights.py:116` | 1 | 5 | periodic batch analytics |
| dashboard | `dashboard/dashboard.py:173` | — | — | single `AsyncResilientPostgreSQL` (~1 backend), no pool |
| graphinator / brainzgraphinator | — | — | — | Neo4j only, no PostgreSQL |

**Sum of pool maxima = 10 + 50 + 50 + 5 = 115** (plus ~1 for dashboard) — **2.5× the
45-backend cap.** The sizes were not coordinated against the shared budget; the two
`*tableinator` values are a copy-pasted `max=50` "to match prefetch_count" (see the
comment that was at `tableinator/tableinator.py:891`). Under session pooling, every one
of these is a real, exclusively-held backend.

Two facts make this the primary root cause:

- **`brainztableinator` alone (max 50) exceeds the entire 45 cap.** A single importer can
  starve the whole database of backends.
- Even the **idle** footprint was wasteful: the `min` connections (5 + 5 + 2 + 1 = 13,
  plus dashboard) are pinned backends held even when a service is doing nothing — e.g.
  `tableinator` sits idle during a MusicBrainz import but still holds its 5 minimum.

### After this change

Pool sizes are now **budget-aware, env-overridable defaults** resolved by
`resolve_postgres_pool_sizes()` (`common/config.py`) and stored on each service config
(`postgres_pool_min_size` / `postgres_pool_max_size`):

| Service | min | max |
| --- | --- | --- |
| api | 2 | 8 |
| tableinator | 2 | 12 |
| brainztableinator | 2 | 12 |
| insights | 1 | 4 |
| dashboard | ~1 (single connection, unchanged) |

**Sum of maxima = 8 + 12 + 12 + 4 ≈ 36 (+1 dashboard) ≤ 45**, with headroom for
health-check transients. Idle footprint (sum of minima) drops to **8**. Worst realistic
concurrent demand during a MusicBrainz import — `brainztableinator` saturated at 12 +
`tableinator` idle min 2 + api ~8 + insights ~4 + dashboard 1 ≈ **27**, comfortably under
45. Operators can clamp the whole fleet at once with `POSTGRES_POOL_MIN_SIZE` /
`POSTGRES_POOL_MAX_SIZE` without a code change.

---

## 2. Transaction scope

`brainztableinator`'s write path holds one transaction per message:

```python
# brainztableinator/brainztableinator.py (on_data_message)
async with connection_pool.connection() as conn:
    await conn.set_autocommit(False)
    async with conn.transaction():
        await processor(conn, data)   # entity upsert + N relationships + M external links
```

The transaction window itself is correctly scoped to a single message (`BEGIN → work →
COMMIT`) and is **not** held across message-fetch waits or batch boundaries. However the
*work inside it* was the problem: each processor issued **one `INSERT` per child row** in
a Python `for` loop (`_insert_relationship` / `_insert_external_link`, called once per
relationship and once per external link). Between each statement the connection sits
*idle in transaction* — pinning a backend — while Python builds and dispatches the next
`INSERT` and waits a network round-trip through PgBouncer → Postgres. An artist with many
relations produced many sequential round-trips, all inside one open transaction. This is
exactly the observed "29 backends *idle in transaction*, cycling sub-millisecond on
`INSERT INTO musicbrainz.relationships`".

By contrast `tableinator` writes a whole batch of messages in **one** transaction
through its `BatchProcessor` (`tableinator/batch_processor.py:386`), so it holds far fewer
transactions open for far less wall-clock — which is why it never exhausted the pool
despite the identical `max=50`.

**Fix:** the per-row loops are replaced with batched `_insert_relationships` /
`_insert_external_links` that issue a single `executemany(...)` for the whole set
(psycopg3 pipelines `executemany`), collapsing N + M round-trips into 2 and shrinking the
*idle in transaction* window proportionally.

---

## 3. Connection acquisition / release

Acquisition/release is correct in every service — connections are taken per-operation via
the `async with pool.connection()` context manager and returned promptly in the `finally`
block (`common/postgres_resilient.py:469-585`), which also restores `autocommit=True`
before returning the connection to the pool. No service holds a pooled connection idle for
the lifetime of a worker.

The pressure was therefore **not** a leak or a held-open connection; it was **too many
connections acquired concurrently at once**: `brainztableinator` sets channel QoS
`prefetch_count=200` (`brainztableinator.py:1047` and the reconnect path at `:354`), and
declares **4 consumers** (one per MusicBrainz data type). With per-consumer prefetch that
is up to **800 messages in flight simultaneously**, each running `on_data_message`, each
trying to check out a pooled connection. Demand (≤ 800) vastly exceeds the pool max (50),
which itself exceeds the PgBouncer cap (45) — so the pool is permanently driven to its
ceiling and the "exhausted, waiting" retry path runs continuously.

**Fix:** prefetch is now coupled to pool capacity. Both `set_qos` calls use
**channel-global QoS** (`global_=True`) with `prefetch_count = postgres_pool_max_size`
(`_channel_prefetch()`), so the broker never delivers more unacked messages than the pool
can service. Backpressure moves to RabbitMQ — where it belongs — instead of the pool's
retry loop. `tableinator` keeps its high prefetch because its `BatchProcessor` semaphore
already decouples prefetch from connection demand (its prefetch fills an in-memory batch,
not a connection each).

---

## 4. Write efficiency

The bulk path can do the same work with far fewer connection-seconds:

- **Batched child inserts (implemented):** `executemany` for relationships and external
  links cuts per-message round-trips from `1 + N + M` to `1 + 2`, shortening each
  transaction and freeing the backend sooner — fewer connection-seconds per message means
  lower concurrency is needed for the same throughput.
- **Bounded concurrency (implemented):** capping in-flight handlers to the pool size
  removes the retry churn that was itself throttling the import. 12 clean concurrent
  writers with no churn sustain more useful throughput than "50 wanted, constantly
  retrying".
- **Future option (not implemented):** adopt `tableinator`'s `BatchProcessor` pattern in
  `brainztableinator` (accumulate many messages, write each entity type in one batched
  transaction). This would push connection demand even lower, at the cost of a larger,
  MusicBrainz-schema-specific refactor. Recommended only if 12 concurrent writers prove
  insufficient.

---

## 5. Resilient-pool retry behavior

The "exhausted" path (`common/postgres_resilient.py:502-515`): when the pool is at
`max_connections` and empty, the caller waits on `asyncio.wait_for(self.connections.get(),
timeout=backoff.get_delay(retry_count))`; on `TimeoutError` it increments `retry_count`,
logs the warning, and retries. After `max_retries` (5) it raises
`Failed to get PostgreSQL connection after 5 attempts` (`:543`). With
`ExponentialBackoff(initial_delay=0.5, max_delay=30)` the cumulative wait across 5
attempts is bounded at roughly 0.5 + 1 + 2 + 4 + 8 ≈ 15 s, well under PgBouncer's 120 s
`query_wait_timeout`, and it **does** surface a clear hard failure rather than silently
degrading.

The retry logic is sound as a safety net and is **left unchanged**. The concern is not its
correctness but that it was being used as a substitute for correct sizing: the system was
relying on retries to paper over structural oversubscription. With sizing and prefetch
fixed, this path should rarely trigger.

---

## Recommendation & tradeoffs

This is fundamentally an **app-side over-pooling** problem, so the fix is app-side and
preferred over asking the platform to raise the cap:

1. **Right-size pools to fit the shared budget** (sum of maxima 115 → ~36) and make them
   env-overridable. *Tradeoff:* lower per-service ceiling; mitigated by coupling prefetch
   so the ceiling is never the bottleneck, and by the fact that `tableinator`'s real usage
   was only ~2-3 connections anyway.
2. **Couple `brainztableinator` prefetch to pool capacity** (channel-global QoS). *Tradeoff:*
   fewer messages buffered in the consumer; the broker holds them instead — which is the
   correct place for backpressure. One hot queue can use the whole budget (desired).
3. **Batch child-row inserts** to shrink the *idle in transaction* window. *Tradeoff:* a
   single `executemany` is now all-or-nothing within the message's transaction (already
   the semantics, since it was one transaction per message).

**When to raise the PgBouncer cap instead:** only if, after these fixes, measured import
throughput at 12 concurrent writers is genuinely insufficient for the business need. In
that case the principled move is to raise the cap **and** the relevant
`POSTGRES_POOL_MAX_SIZE` *together* (keeping the sum of service maxima under the new cap) —
never to let a single service's pool max exceed the cap, which is what caused this
incident. The 45 cap is not currently the limiting factor; the uncoordinated 115 of demand
was.
