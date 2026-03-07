# RabbitMQ Fanout Exchange Migration Plan

## Overview

Replace the single topic exchange with **4 fanout exchanges (one per data type)**. The extractor only declares exchanges and publishes — it has zero knowledge of consumers. Each consumer independently declares its own queues and binds them to the relevant exchanges.

## Key Design Decisions

| Decision | Current | New |
|---|---|---|
| Exchange type | 1 `topic` exchange | 4 `fanout` exchanges (per data type) |
| Exchange names | `discogsography-exchange` | `discogsography-artists`, `discogsography-labels`, `discogsography-masters`, `discogsography-releases` |
| Who declares queues | Extractor (for all consumers) | Each consumer declares its own |
| Routing keys | `"artists"`, `"labels"`, etc. | None (fanout ignores them) |
| Queues per consumer | 4 (unchanged) | 4 (unchanged) |
| DLQs per consumer | 4 (unchanged) | 4 (unchanged) |
| DLX | 1 shared topic (`discogsography-exchange.dlx`) | 4 fanout per consumer (`discogsography-graphinator-artists.dlx`, etc.) |
| Consumer cancellation | Per data-type (unchanged) | Per data-type (unchanged) |
| `DataMessage` struct | No changes needed | No changes needed |

## What Stays the Same

- Per-data-type queues, DLQs, consumer cancellation, recovery logic
- Message format (`DataMessage` and `FileCompleteMessage` unchanged)
- Consumer handler structure (per-data-type handlers in graphinator, generic handler in tableinator)
- `message_counts`, `last_message_time`, `completed_files` tracking
- Queue arguments (quorum type, delivery limit 20)
- Prefetch count (200)

## Breaking Change / Migration Note

Changing exchange type requires deleting and recreating. This is a **coordinated deployment**: stop all services, delete old exchange + queues via RabbitMQ management, start new versions. Since this processes batch exports (not live traffic), this is a clean cutover.

---

## Phase 1: Extractor (Rust)

### `extractor/src/message_queue.rs`

- Replace constants:
  - Remove: `AMQP_EXCHANGE`, `AMQP_EXCHANGE_TYPE` (Topic), `AMQP_QUEUE_PREFIX_GRAPHINATOR`, `AMQP_QUEUE_PREFIX_TABLEINATOR`
  - Add: `AMQP_EXCHANGE_PREFIX = "discogsography"`, `AMQP_EXCHANGE_TYPE = Fanout`
- Add helper to build exchange name: `format!("{}-{}", AMQP_EXCHANGE_PREFIX, data_type)` (e.g. `"discogsography-artists"`)
- **`try_connect()`**: Remove exchange declaration from connection setup (exchanges are per-data-type, declared in setup method)
- Add **`setup_exchange(&self, data_type: DataType)`**: declares the single fanout exchange for that data type (replaces `setup_queues`)
- **Delete `setup_queues()` entirely** — no queue or DLQ knowledge
- **`publish()`**: publish to `format!("discogsography-{}", data_type)` with empty routing key `""`
- **`publish_batch()`**: same exchange name change, empty routing key
- Update tests:
  - Remove `test_queue_names`, `test_queue_names_all_types`, `test_dlx_exchange_name_format`, `test_dlq_queue_names`
  - Update `test_constants` for new constants
  - Add test for exchange name generation per data type

### `extractor/src/types.rs`

- Remove `routing_key()` method from `DataType`
- Remove `test_data_type_routing_key` test

### `extractor/src/extractor.rs`

- Replace `mq.setup_queues(data_type).await?` with `mq.setup_exchange(data_type).await?`

## Phase 2: Common Python Config

### `common/config.py`

- Replace constants:
  - Remove: `AMQP_EXCHANGE = "discogsography-exchange"`, `AMQP_EXCHANGE_TYPE = "topic"`
  - Add: `AMQP_EXCHANGE_PREFIX = "discogsography"`, `AMQP_EXCHANGE_TYPE = "fanout"`
- Keep `AMQP_QUEUE_PREFIX_GRAPHINATOR` and `AMQP_QUEUE_PREFIX_TABLEINATOR`
- Add helper: exchange name = `f"{AMQP_EXCHANGE_PREFIX}-{data_type}"`

## Phase 3: Graphinator

### `graphinator/graphinator.py` — Startup queue setup

- For each data type, declare the **fanout exchange** `discogsography-{data_type}`
- Declare consumer-owned DLX: `discogsography-graphinator-{data_type}.dlx` (fanout)
- Declare DLQ: `discogsography-graphinator-{data_type}.dlq` (classic, bound to consumer DLX)
- Declare main queue: `discogsography-graphinator-{data_type}` (quorum, `x-dead-letter-exchange` -> consumer DLX)
- Bind main queue to fanout exchange (no routing key)
- Start per-data-type consumers (unchanged structure)

### Recovery (`_recover_consumers`)

- Same changes: declare fanout exchanges, consumer-owned DLX per data type
- Queue checking logic unchanged (still per-data-type queues)

### Everything else unchanged

- Message handlers, consumer cancellation, file completion tracking, progress monitoring

## Phase 4: Tableinator

### `tableinator/tableinator.py` — Same structural changes as graphinator

- Startup: declare per-data-type fanout exchanges, consumer-owned DLXs, own queues
- Recovery: same changes
- **`on_data_message()`**: Create per-data-type handler wrappers via `make_data_handler(data_type)` that inject `data_type` (replaces `message.routing_key`)
- Consumer cancellation, file completion — unchanged

## Phase 5: Dashboard

### `dashboard/dashboard.py`

- **No functional changes needed** — `get_queue_info()` queries RabbitMQ management API and filters by `queue["name"].startswith("discogsography")`. Queue names are unchanged.

### `dashboard/static/dashboard.js`

- Update comment block describing queue naming convention — remove reference to exchange routing and note fanout topology
- No functional JS changes needed

### `dashboard/README.md`

- Update references to exchange topology

### `tests/dashboard/test_dashboard_app.py`

- No changes needed

## Phase 6: Tests

### `extractor/src/message_queue.rs` (embedded tests)

- Remove: `test_queue_names`, `test_queue_names_all_types`, `test_dlx_exchange_name_format`, `test_dlq_queue_names`
- Update: `test_constants` — assert new `AMQP_EXCHANGE_PREFIX` and `AMQP_EXCHANGE_TYPE`
- Add: test for per-data-type exchange name generation

### `extractor/src/types.rs` (embedded tests)

- Remove: `test_data_type_routing_key`

### `tests/graphinator/test_graphinator.py`

- Update mock exchange declarations: fanout type, per-data-type exchange names
- Update mock DLX: consumer-owned per-data-type DLX names
- Queue bindings: no routing key

### `tests/tableinator/test_tableinator.py`

- Same exchange/DLX mock updates as graphinator
- Update `data_type` extraction: from handler wrapper instead of `message.routing_key`

## Phase 7: Documentation

### `docs/architecture.md`

- Update message flow diagram showing 4 fanout exchanges
- Note extractor decoupling
- Update exchange/queue counts

### `docs/configuration.md`

- Update `AMQP_EXCHANGE` -> `AMQP_EXCHANGE_PREFIX` documentation
- Update exchange type to `fanout`
- Remove routing key references

### `docs/consumer-cancellation.md`

- Minimal changes — per-data-type cancellation logic is unchanged

### `docs/file-completion-tracking.md`

- Minimal changes — data_type still comes from message body in `file_complete` messages

### `CLAUDE.md` (AI Development Memories section)

- Update extractor architecture bullet

## Summary

| Component | Scope of Change |
|---|---|
| Extractor | Moderate — new exchange naming, remove `setup_queues`, add `setup_exchange` |
| Common config | Small — rename constant, change type |
| Graphinator | Small — exchange declarations + DLX ownership, handlers unchanged |
| Tableinator | Small — exchange declarations + DLX ownership + data_type wrapper for handler |
| Dashboard | Minimal — comment + README updates only, no functional changes |
| Tests | Moderate — update mocks for new exchange names/types |
| Docs | Moderate — diagrams and references |
