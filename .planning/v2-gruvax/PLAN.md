# Plan: App Tokens + Collection API for GRUVAX v2.0

**Workflow:** One worktree per phase, one PR per phase. Atomic commits within. Each phase ends with a green CI run before next phase starts. PRs link back to this PLAN.md and SPEC.md.

**Phase numbering follows brief §5.** P1 (spike) is done — see SPEC.md §4.

## P2 — `app_tokens` schema

**Branch:** `feat/app-tokens-schema`

- `schema-init/postgres_schema.py` — append the table + 2 partial indexes from brief §3.2 to `POSTGRES_STATEMENTS` (CREATE-IF-NOT-EXISTS pattern matches existing entries).
- Verify roundtrip (`just rebuild` or local schema-init container run) — no live DB needed for tests since this repo uses mocks, but eyeball schema-init logs on the e2e stack.
- Tests in `tests/schema_init/` if any exist for postgres_schema; otherwise rely on the existing schema-init e2e smoke.

**Acceptance:**
- [ ] `schema-init` boots clean against fresh PG.
- [ ] Partial indexes exist: `idx_app_tokens_user_active`, `idx_app_tokens_token_lookup`.
- [ ] Tombstone semantics documented in postgres_schema.py comment.

## P3 — `require_app_token` dependency + tests

**Branch:** `feat/require-app-token-dep`

- New file `api/app_tokens.py`:
  - `mint_token(user_id, name, scopes)` → returns `(token_id, plaintext_dscg_token)`. Plaintext format: `dscg_` + 32 bytes `secrets.token_urlsafe` (base64url, no `=`).
  - `hash_token(plaintext)` → SHA-256 hex.
  - `require_app_token(scopes: list[str])` → dependency factory. Reads `Authorization: Bearer ...`, looks up by `token_hash` + `revoked_at IS NULL`, checks scope, returns `AppTokenAuth(user_id, token_id, scopes, name)`. Schedules `last_used_at` update via `asyncio.create_task` — failure must NOT fail the request.
  - Constant-time scope check using `secrets.compare_digest` on hash lookup (defense in depth).
- `api/dependencies.py` — re-export `require_app_token` symbol (consistent with existing `require_user` location).
- Tests in `tests/api/test_app_token_auth.py` (NEW):
  - missing `Authorization` → 401
  - malformed header (e.g. `Bearer ` empty, `Token foo`, no `Bearer`) → 401
  - unknown token → 401
  - revoked token → 401
  - valid token, missing scope → 403
  - valid token, sufficient scope → 200 + `AppTokenAuth` populated
  - `last_used_at` update raises → request still succeeds, error logged
  - Two valid tokens with same plaintext (impossible by construction) — collision-safe note

**Acceptance:**
- [ ] All 7 failure-mode tests green.
- [ ] No plaintext token in any log line (grep CI step or test).
- [ ] `require_user` tests unchanged and still pass.
- [ ] mypy + ruff clean.

## P4 — Settings UI for mint/list/revoke

**Branch:** `feat/app-tokens-settings-ui`

**Backend** (`api/routers/app_tokens.py`, NEW) — all under `Depends(require_user)`:
- `POST /api/user/app-tokens` — body `{name, scopes}`. Returns `{token_id, token, name, scopes, created_at}`. Plaintext only this once.
- `GET /api/user/app-tokens` — returns `{active: [...], revoked: [...]}`. Active rows: `{id, name, scopes, created_at, last_used_at}`. Revoked rows: `{id, name, revoked_at}`.
- `DELETE /api/user/app-tokens/{id}` — sets `revoked_at = NOW()`. 404 if not owned by current user. 204 on success.
- Wire router in `api/api.py` next to existing user routers.

**Frontend** (`explore/`) — vanilla classic-script JS per memory `project_digger_m1_execution`:
- New page `explore/static/settings/apps.html` + `explore/static/settings/apps.js` + CSS.
- Route in `explore/app.py` (or equivalent) serving the page.
- List: active + revoked sections.
- Mint form: name input, scope multiselect (only `collection:read` for v1).
- Reveal screen: large code block with plaintext, "Copy" button, prominent warning, "Done" returns to list (plaintext discarded from DOM).
- Revoke: confirm modal → DELETE call → list refresh.
- Tests in `explore/static/__tests__/apps.test.js` (Vitest) with FAKE TIMERS (per memory — leaked-timer flake).

**Acceptance:**
- [ ] User flow: mint → copy → list shows row with `last_used_at: never` → revoke → row moves to revoked tombstones section.
- [ ] Plaintext NEVER appears after navigating away from reveal screen.
- [ ] Vitest covers mint flow, list rendering, revoke confirmation.
- [ ] Python tests cover all 3 backend endpoints + ownership 404 case.

## P5 — Apply auth + rate limits to /api/user/collection endpoints

**Branch:** `feat/app-token-collection-auth`

- Decision: support BOTH `require_user` (first-party JWT) AND `require_app_token` on the three endpoints — they're additive. Use a `require_user_or_app_token(scopes=[...])` helper that returns a unified `AuthContext` exposing `user_id`. This avoids duplicating endpoint code paths.
- Update `api/routers/user.py` lines 69, 158, 169 to use the unified dep.
- Add response field `user_id` (UUID string) to all three responses — required by brief §3.5.
- Rate limits via existing `api/limiter.py` (slowapi):
  - `60/minute` per token (key derived from `token_id` for app-token; `sub` for JWT — fall back to IP if neither).
  - `600/hour` per token.
  - 429 sets `Retry-After`.
- Tests:
  - First-party JWT path still works (regression).
  - App-token path returns user's collection.
  - Rate-limit headers present at boundary.
  - 429 with `Retry-After` when limit exceeded (use slowapi test helper).
  - `user_id` field present in all three responses.

**Acceptance:**
- [ ] `curl -H 'Authorization: Bearer dscg_...' /api/user/collection` returns user's collection.
- [ ] Same endpoint with first-party JWT still works (regression).
- [ ] Existing collection endpoint tests still pass.
- [ ] Rate limit test green.

## P6 — `catalog_number` everywhere (no schema migrations)

**Branch:** `feat/catalog-number-everywhere`

Approach B-everywhere per SPEC.md §4.3. No PG schema migration.

### P6.1 — Sync path (`api/syncer.py`)

- Lines 147–167: extract `catno = labels[0].get("catno") if labels else None` per item.
- PG upsert (line 180-ish): change the `metadata` slot from literal `None` to `Jsonb({"catno": catno}) if catno else None`. The column is already `JSONB` (postgres_schema.py:180). Use `psycopg.types.json.Jsonb`.
- Neo4j cypher around line 200 — verify whether the existing cypher MATCHes Release by id (does not MERGE) and whether bulk-extracted Release nodes already exist before sync runs. If Release pre-exists, add `SET r.catalog_number = rel.catno` (guard with `WHERE rel.catno IS NOT NULL` so we never overwrite existing catno with null).
- Add `catno: rel.catno` to the Cypher `UNWIND $releases AS rel` payload.

### P6.2 — Graphinator path (`graphinator/batch_processor.py`)

- On the Release MERGE arm, extract `catno = msg.data.get("labels", [{}])[0].get("catno")` (defensive on empty labels).
- Add `SET r.catalog_number = $catno` to the Release MERGE cypher (guarded `WHERE $catno IS NOT NULL` if Cypher syntax permits, otherwise conditional in Python).
- This populates catno on Release nodes from bulk extraction going forward.

### P6.3 — Tableinator path

**No change.** The full entity payload including `labels[].catno` is already persisted into `data JSONB` at `tableinator/batch_processor.py:418` via `Jsonb(msg.data)`. Verified during P1 spike.

### P6.4 — Query layer (`api/queries/user_queries.py`)

- `get_user_collection` (line ~42): add `r.catalog_number AS catalog_number` to RETURN.
- `get_user_wantlist` (line ~82): same.
- Check `get_user_collection_stats` and `get_user_collection_timeline` — likely no change needed (these aggregate, don't return per-release catno) but verify.

### P6.5 — Tests

- `tests/api/test_syncer.py`: catno extracted and persisted to both stores (mocked Discogs response with `labels[].catno`).
- `tests/api/test_syncer.py`: null-safe — items where `labels` is empty or `catno` is missing → catno=None, metadata=None.
- `tests/graphinator/test_graphinator.py`: graphinator MERGE writes catno on Release node (mocked Neo4j session, assert cypher parameters).
- `tests/api/test_user_queries.py` (or wherever queries are tested): `get_user_collection` returns `catalog_number` in each item.

### Backfill (operational, not a code change)

- For active users: trigger one re-sync via existing endpoint. Most users will hit "Re-sync" voluntarily.
- For unowned releases on Release nodes: nothing to do — wait for next Discogs monthly bulk re-ingest (graphinator will then write catno).
- GRUVAX positions OWNED records → sync-path coverage is sufficient at cutover.

**Acceptance:**
- [ ] Synced collection items expose `catalog_number` (non-null where Discogs has it) on both `/api/user/collection` and `/api/user/wantlist`.
- [ ] Null-safe: items where Discogs returns no `catno` → `catalog_number: null`, no errors.
- [ ] Graphinator writes `r.catalog_number` on Release MERGE going forward.
- [ ] Tableinator unchanged and tests still green.
- [ ] No PG schema migration in this phase. (`postgres_schema.py` diff is zero.)
- [ ] `user_collections.metadata` rows for catno-bearing items contain `{"catno": "..."}` (verifiable via direct SELECT in e2e).

## P7 — Cross-repo contract artifact

**Branch:** `feat/v2-gruvax-contract-doc`

- Write `docs/specs/v2-gruvax-integration.md` with all sections from brief §3.7:
  - P1 spike outcome (cite outcome (c) + chosen approach B + final field name `catalog_number`)
  - OpenAPI fragment (YAML) for the three endpoints under app-token auth
  - Example request + response with `catalog_number` populated
  - Scope vocabulary (`collection:read`)
  - Error shapes (401/403/429)
  - Plaintext token format (`dscg_<base64url>`)
  - `user_id` location: response envelope top-level field
  - Rate-limit thresholds and `Retry-After` semantics
  - Versioning / deprecation note (when contract changes, what GRUVAX does)
- Mention this file is the *cross-repo contract* and changes require GRUVAX coordination.

**Acceptance:**
- [ ] All hand-off criteria from brief §6 demonstrably true.
- [ ] Document accurately reflects live API (cross-checked against actual response JSON from running the e2e stack).

## Ordering

P2 → P3 → P4 → P5 → P6 → P7. Within each, one worktree, one branch, one PR.

P6 *could* theoretically come earlier (the field is independent of auth), but landing it later means the contract artifact in P7 already shows the catalog_number-enabled responses, which keeps the contract document drafting linear.

## Worktree convention (per project memory)

```bash
WORKTREE=.worktrees/$BRANCH
git worktree add -b $BRANCH $WORKTREE origin/main
# work in $WORKTREE
# atomic commits
gh pr create --base main
```

Each PR description references this PLAN.md path and the P# it implements.
