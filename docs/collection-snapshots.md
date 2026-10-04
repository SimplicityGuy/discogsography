# Immutable collection pagination

Clients that need a complete, stable collection walk can opt into a published
collection-sync generation. Existing requests without `snapshot` still use the
live Neo4j offset endpoint, including lightweight credential probes.

## Upgrade order

Deploy the updated schema-init and API, then complete a successful collection
sync for the user before enabling strict snapshot consumption in GRUVAX. Existing
installations have no published generation until that first successful sync;
the API never bootstraps from mutable rows that could contain a partial failed
sync. Generation production requires `POSTGRES_POOL_MAX_SIZE >= 2`. The default
API pool remains eight connections; no pool cap is automatically raised. A pool
of one can read already-published generations but cannot produce a new one.

## Wire contract

Authenticate with the existing user JWT or app token with `collection:read`.
Start with `GET /api/user/collection?snapshot=new&offset=0&limit=200`.
The usual `user_id`, `releases`, `total`, `offset`, `limit`, and `has_more` remain.
Every strict response, even an empty collection or a single final page, adds:

| Field | Value |
| --- | --- |
| `snapshot_token` | Opaque URL-safe authenticated token; send unchanged and never log it |
| `snapshot_generation` | Canonical UUID string |
| `snapshot_expires_at` | Fixed UTC RFC3339 string with microseconds and trailing `Z` |
| `snapshot_source` | `completed_collection_sync` |

Continue with `snapshot=<exact token>`,
`snapshot_generation=<exact initial generation>`, and the desired offset/limit.
All pages echo the exact token, generation, expiry string, and source. The token
expires 15 minutes after creation by default; requests do not extend it.
Publication of a newer generation leaves valid older tokens usable.

Authenticate before examining snapshot errors. Credential failures keep the
existing 401/403 behavior. Snapshot failures use `detail.code` and a safe message:

| HTTP status | Code | Meaning |
| --- | --- | --- |
| 409 | `snapshot_unavailable` | No successful published collection generation yet |
| 409 | `snapshot_mismatch` | Invalid token, missing/wrong expected generation, unavailable pinned generation, or invalid initial request |
| 409 | `snapshot_scope_mismatch` | Authenticated user differs from the token owner |
| 410 | `snapshot_expired` | Authenticated token has expired |

Consumers must abort the walk before replacing their collection on these errors;
do not retry a snapshot failure with a new generation or fall back to live pages.
Service failures remain service failures. Strict responses use `Cache-Control:
no-store`. Tokens use a separate HKDF/Fernet key domain and cannot authenticate
as user JWTs. API/Explore access logs redact decoded `snapshot` query keys,
including percent-encoded keys and duplicates; malformed targets fail closed.

## What a generation represents

Each collection sync stages its own per-instance PostgreSQL upsert results.
Only successful completion of collection fetching and PostgreSQL/Neo4j
reconciliation publishes that generation and atomically changes the user's
current pointer. Failed or cancelled collection work leaves the prior pointer
untouched. A subsequent wantlist failure does not retract a successfully
published collection; the overall full-sync status can still be `failed`.

This is the captured projection of a completed collection sync, not a claim
that the remote Discogs pagination itself was a point-in-time snapshot.
The frozen payload contains string `id`, nullable `instance_id`, folder,
date-added, rating, title, artist, year, formats, and the canonical label/catalog
pair. The pair requires known first-label provenance; unknown legacy provenance
produces null/null. Optional live Neo4j `genres`/`styles` enrichment is omitted
from this PostgreSQL projection rather than claiming cross-database atomicity.

Ordering is date-added descending with nulls last, numeric release ID ascending,
then numeric instance ID ascending with nulls last. Multiple copies remain
distinct. Repeated source entries for the same release/instance update the
building entry rather than duplicate it. Missing instance IDs remain null on
the wire and in PostgreSQL; Neo4j uses the internal per-release relationship key
`legacy-no-instance` for these entries. That key never becomes an API instance
ID. Source numeric zero is a real instance and remains distinct.

## Resource bounds and cleanup

The producer admits at most the configured limit or pool max minus one,
whichever is smaller, before checking out a connection. It rejects excess work
promptly and reserves a slot for authentication/page reads. A per-user session
advisory try-lock serializes producers across API processes. One owner connection
handles PostgreSQL writes, reconciliation, staging, and publication; remote HTTP
waits hold no SQL transaction and there are no nested pool checkouts. Failure or
cancellation releases ownership; an uncertain lock-release session is closed.

Global transaction serialization covers quota checks and staging writes across
users. Limits count building stages and published generations. A generation
metadata reservation consumes one stored row and 256 accounted bytes; payload
bytes use PostgreSQL's actual `pg_column_size` of JSONB. These are accounted
payload bounds, not a promise about total physical database disk size, indexes,
WAL, or dead tuples.

| Environment variable | Default |
| --- | --- |
| `COLLECTION_SNAPSHOT_ITEMS` | 100000 items per generation |
| `COLLECTION_SNAPSHOT_BYTES` | 67108864 accounted bytes per generation |
| `COLLECTION_SNAPSHOT_GENERATIONS` | 8 retained generations per user |
| `COLLECTION_SNAPSHOT_GLOBAL_ROWS` | 2000000 stored item/metadata rows |
| `COLLECTION_SNAPSHOT_GLOBAL_BYTES` | 1073741824 accounted bytes globally |
| `COLLECTION_SNAPSHOT_PRODUCERS` | 2 concurrent producers per API pool |
| `COLLECTION_SNAPSHOT_TTL_SECONDS` | 900 seconds, fixed for each issued token |

All limits must be positive. Quota exhaustion fails collection production
without evicting a current or unexpired pinned generation. A failed page's live
upserts and stage writes roll back together; earlier live pages may remain, as
with existing sync behavior, but cannot become a published generation.

Token issuance records retention transactionally before returning the token.
Cleanup considers at most 32 candidates per operation; it removes only
noncurrent, unleased generations and abandoned building stages whose producer
lock can be acquired. It never deletes a slow active producer based on age.
Cleanup runs when creating a producer or first snapshot page; durable published
state survives API restart and does not depend on Redis.

## Validation

`just test-collection-snapshots-integration` runs serial real PostgreSQL/Neo4j
producer, HTTP, ownership, cancellation, quota, retention, and logging controls
against explicitly owned `DGS_SNAPSHOTS_*` servers. The dedicated reusable test
workflow supplies exclusive disposable services; API unit tests do not collect
these integrations. The collection performance scenario uses an environment
token and measures first/continuation requests without persisting tokens in
reports. See the performance runner README for invocation.
