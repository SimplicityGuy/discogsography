# Milestone: App Tokens + Collection API for GRUVAX v2.0

**Status:** Drafting (P1 spike complete — catalog# decision pending user input)
**Origin brief:** External (GRUVAX repo, 2026-05-26) — pasted into session, not checked into either repo
**Cross-repo contract artifact (deliverable):** `docs/specs/v2-gruvax-integration.md` (written in P7)
**Scope:** Self-contained discogsography milestone. After it ships, GRUVAX v2.0 work begins (GRUVAX agrees to wait).

---

## 1. What GRUVAX needs from discogsography

GRUVAX v2.0 must integrate with discogsography over **HTTP API** (not direct DB read), fetching a specific *authorized user's* collection. Each GRUVAX user must **authorize** GRUVAX to read their collection. A GRUVAX deployment supports multiple per-user profiles.

This milestone adds a generic, scoped, revocable third-party app authorization mechanism — usable by GRUVAX now, and by other future third parties.

## 2. Deliverables

1. **`app_tokens` table** — third-party app authorization records (id, user_id, name, scope[], token_hash, created_at, last_used_at, revoked_at).
2. **`require_app_token` FastAPI dependency** — Bearer-token auth, scope check, async `last_used_at` update.
3. **Settings UI** — `/settings/apps` page in `explore/`: mint (one-time reveal), list active + revoked, revoke.
4. **App-token auth on three endpoints:**
   - `GET /api/user/collection`
   - `GET /api/user/collection/stats`
   - `GET /api/user/collection/timeline`
5. **Rate limits** on those endpoints: 60/min/token, 600/hr/token, 429 with `Retry-After`.
6. **`catalog_number` exposed per collection item** — see §4 spike findings; PENDING user input on approach.
7. **Cross-repo contract:** `docs/specs/v2-gruvax-integration.md`.

## 3. Out of scope (per brief §2)

- Building GRUVAX-side code.
- OAuth2 device-authorization grant (PAT-style token is sufficient).
- Per-app permissions UI beyond a flat scope list.
- `collection:write` scope.
- Webhooks to GRUVAX.
- Refactoring existing first-party JWT auth (`require_user`) or Discogs OAuth flow.

## 4. P1 spike findings (verification)

Three claims to verify per brief §3.1:

### 4.1 Are the three target endpoints already exposed?

**YES** — at `api/routers/user.py`:

| Endpoint | Line | Source |
|---|---|---|
| `GET /api/user/collection` | 69 | Neo4j (`get_user_collection`) |
| `GET /api/user/collection/stats` | 158 | Neo4j (`get_user_collection_stats`) |
| `GET /api/user/collection/timeline` | 169 | Neo4j (`get_user_collection_timeline`) |

All use `Depends(require_user)` today (first-party JWT only). Response shapes from `api/queries/user_queries.py`:

```jsonc
// /api/user/collection
{
  "releases": [
    { "id", "title", "year", "artist", "label", "genres", "styles",
      "rating", "date_added", "folder_id" }
  ],
  "total": N, "offset": 0, "limit": 50, "has_more": bool
}
```

No `catalog_number`, no `user_id`. Both must be added for the GRUVAX contract.

### 4.2 Is `catalog_number` stored anywhere?

**NO — outcome (c).** Per brief §3.1 escalation policy, this requires user confirmation before scope expansion.

Verified by code inspection (read-only — no live DB query in spike):

- **`user_collections` table** (`schema-init/postgres_schema.py:165`) — no `catalog_number` column. `metadata` JSONB is "reserved for future use" (syncer comment `api/syncer.py:165`).
- **Discogs collection syncer** (`api/syncer.py:147`) — Discogs API returns `labels[]` with `catno` per item. Syncer only reads `labels[0]["name"]` (line 148), discards `catno`.
- **Neo4j Release node** (referenced by `r.title`, `r.year`, `r.id` throughout `api/queries/user_queries.py`) — no `r.catalog_number`.
- **Graphinator** (`graphinator/graphinator.py`, `batch_processor.py`) — `grep catno catalog` returns zero matches. Bulk pipeline messages contain `catno` (preserved by Rust extractor — see `extractor/src/tests/normalize_tests.rs:304`), but graphinator drops it.
- **Tableinator** — same: zero matches.

Catalog numbers ARE in the upstream data (both Discogs API responses and bulk XML dumps), but neither persists them anywhere downstream.

### 4.3 Decision — Approach B-everywhere (no PG schema migrations)

**User decision (2026-05-26):** Approach B-everywhere with no schema changes.

| Layer | Action | Schema migration? |
|---|---|---|
| `api/syncer.py` (Discogs API → Neo4j + PG, per-user sync) | Extract `labels[0].get("catno")` per item. Neo4j: `SET r.catalog_number = $catno` on the existing Release MATCH. PG: include `{"catno": "..."}` in `user_collections.metadata` JSONB upsert (column already exists, currently always written as `None`). | None |
| `graphinator/batch_processor.py` (bulk Discogs XML → Neo4j) | On Release MERGE, also `SET r.catalog_number` from `msg.data.labels[0].catno` (Rust extractor already preserves it — verified in `extractor/src/tests/normalize_tests.rs:304`). | None |
| `tableinator/batch_processor.py` (bulk Discogs XML → PG) | **No code change required.** Table shape is `{data_id, hash, data JSONB, updated_at}` (postgres_schema.py:684); the full entity payload including `labels[].catno` is already written via `Jsonb(msg.data)` at `batch_processor.py:418`. | None |
| `api/queries/user_queries.py` | Add `r.catalog_number AS catalog_number` to `RETURN` for collection + wantlist + stats/timeline where relevant. | None |

**Why this works without schema changes:**
- Neo4j is schemaless on node properties — first write creates `r.catalog_number`.
- `user_collections.metadata JSONB` already exists (postgres_schema.py:180) — was always written as `None`; switch to `Jsonb({"catno": catno})` when catno present.
- Tableinator already stores the full payload.

**Backfill strategy:**
- Owned releases (most important for GRUVAX): one re-sync per active user via existing Discogs sync endpoint. Cheap (Discogs API only).
- Unowned releases: populated organically by next bulk Discogs ingest (graphinator will then write catno on MERGE). Discogs ships monthly XML dumps; no forced re-ingest required.
- For the immediate GRUVAX cutover, owned-release catno (via sync) is sufficient — GRUVAX only positions records the user owns.

**The only schema migration this milestone introduces is the new `app_tokens` table** (P2). That table cannot be expressed via JSONB without losing partial-index lookups by `token_hash` (the critical hot path for `require_app_token`).

## 5. Open §7 questions from the brief

| # | Question | Resolution |
|---|---|---|
| 1 | `catalog_number` not stored — scope expansion OK? | **Resolved 2026-05-26:** Approach B-everywhere with no PG schema changes. See §4.3. |
| 2 | `user_id` location — header vs response envelope | **Response envelope** (`"user_id": "<uuid>"` as a top-level field alongside `releases`/`total`/`offset`/`limit`/`has_more`). Discoverable, JSON-typed, doesn't depend on caller reading headers. |
| 3 | Scope naming — `collection:read` or `read:collection`? | Match repo conventions — check `MCP_API_TOKEN` flow and `X-Service-Token` guard for existing scope naming. If none found, default to brief's suggestion `collection:read`. |
| 4 | Token format prefix `dscg_` | Accept — no existing identifier convention conflicts on inspection. |
| 5 | Anything in §2 (out of scope) that seems mandatory? | None identified. |

## 6. Non-goals beyond brief §2

- Re-architecting `/api/user/collection` source-of-truth (stays on Neo4j).
- Adding `collection:read` to the existing MCP server flow (orthogonal — MCP uses `MCP_API_TOKEN`, separate auth path).
- Forcing a full bulk re-ingest to backfill catalog# on unowned releases (let it happen organically at next monthly Discogs dump).
- Adding a top-level `catalog_number` column to `user_collections` (we'll use existing `metadata` JSONB instead).

---

**Approved by user:** 2026-05-26 — Approach B-everywhere, JSONB metadata reuse, no PG schema migrations beyond `app_tokens`.
