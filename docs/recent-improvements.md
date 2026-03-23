# 🚀 Recent Improvements

<div align="center">

**Summary of recent enhancements to the Discogsography platform**

Last Updated: 2026-03-22

</div>

## 🆕 Latest Improvements (March 2026)

### ⚡ Comprehensive Query Performance Optimization — 249x Overall Improvement (#175-#184)

**Overview**: Over 11 optimization rounds across PRs #175-#184, the entire API query layer was systematically profiled and optimized, achieving a **249x reduction in overall average latency** (10.95s → 0.044s) across 88 endpoints. See the full [Query Performance Optimizations](query-performance-optimizations.md) report for detailed analysis.

#### Optimization Rounds

| PR       | Focus                                                                       | Key Impact                                                          |
| -------- | --------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| **#175** | Initial Cypher optimization of 6 slowest queries                            | 10-100x fewer DB hits per query                                     |
| **#176** | 7 query families: CALL {} barriers, streaming aggregation, batch similarity | Path finder: 58s → 0.2s, trends: CartesianProduct eliminated        |
| **#177** | Cardinality management with per-genre LIMITs, parallel genre-emergence      | artist-similar: top-5-genre cap prevents mega-genre explosion       |
| **#179** | asyncio.gather() concurrency, pattern comprehension for planner control     | explore/genre: 4 concurrent queries vs chained OPTIONAL MATCHes     |
| **#180** | Per-genre CALL {} barriers for similarity queries                           | label-similar: 206M → 60-80M DB hits, 1GB → 200MB memory            |
| **#181** | Pre-computed Genre/Style/Label node properties at import time               | explore/genre: 200M → 6 DB hits; genre-emergence: 410M → 33 DB hits |
| **#184** | Style-based similarity, Redis caching (24h TTL), search per-table LIMIT     | trends/genre: 28s → 0.001s; artist-similar: 112s → 0.002s           |

#### Techniques Applied

- **Pre-computed node properties**: Aggregate counts (release_count, artist_count, label_count, style_count, first_year) computed during graphinator post-import step and stored on Genre/Style/Label nodes
- **CALL {} subqueries**: Prevent Neo4j planner CartesianProduct plans by creating strong barriers for traversal order
- **Pattern comprehension**: Force specific node-first traversal when even CALL {} doesn't control the planner
- **Redis cache-aside**: 24h TTL for trends, similarity, and label-DNA; 5m TTL for search results
- **Batch queries**: N+1 query patterns (800 queries → 4 queries) replaced with UNWIND-based batching
- **Per-dimension LIMIT**: Cap high-cardinality genre expansions (Rock: 6M+ releases → LIMIT 500 per genre)
- **asyncio.gather()**: Execute independent Neo4j/PostgreSQL queries concurrently
- **Relationship type filtering**: shortestPath with explicit type list eliminates unbounded BFS

#### Results by Category

| Category                   | Before     | After      | Speedup     |
| -------------------------- | ---------- | ---------- | ----------- |
| Path finder (6 endpoints)  | 58.5s      | 0.21s      | **279x**    |
| Explore genre (2)          | 24.1s      | 0.014s     | **1,721x**  |
| Trends genre (2)           | 28.6s      | 0.001s     | **28,600x** |
| Trends style (3)           | 13.2s      | 0.001s     | **13,200x** |
| Genre emergence            | 64.3s      | 0.10s      | **630x**    |
| Artist similarity (4)      | 64s        | 0.002s     | **32,000x** |
| Label similarity (3)       | 86s        | 0.001s     | **86,000x** |
| **Overall (88 endpoints)** | **10.95s** | **0.044s** | **249x**    |

______________________________________________________________________

### ⚡ Cache Label-DNA Compare, Pre-Warm Search, Increase Search TTL (#189)

**Overview**: Eliminated cold-cache penalties for label-DNA compare and common search terms by reusing Redis caches and pre-warming on startup.

#### Features

- **Label-DNA compare cache reuse**: `_build_dna` now checks and populates the same Redis cache as the `/dna` endpoint — compare was doing 15.1s cold cache because it bypassed the label DNA cache
- **Search pre-warming**: Pre-warm Redis search cache on startup for 10 common high-cardinality terms (Rock, Electronic, Jazz, etc.) that take ~9s cold
- **Increased search TTL**: Search cache TTL increased from 300s (5 min) to 3600s (1 hour) to reduce cold cache frequency

______________________________________________________________________

### ⚡ Pre-Compute Label Stats, Cache Explore/Trends, Fix Label-DNA-Compare 500 (#188)

**Overview**: Pre-compute label statistics during import, add Redis caching for explore and trends endpoints, and fix label-DNA compare 500 errors.

#### Features

- **Pre-computed label stats**: Extend `compute_genre_style_stats` to set `release_count`, `artist_count`, `genre_count` on Label nodes (batched in transactions of 100 rows)
- **Redis caching**: Cache `trends/label` (24h TTL) and `explore/artist`/`explore/label` (24h TTL) to avoid expensive COUNT traversals
- **Label-DNA compare fix**: Replace broken single-traversal Cypher with parallel `asyncio.gather` of 4 individual queries; add early return for labels below MIN_RELEASES
- **Migration script**: One-time `scripts/compute-label-stats.sh` for existing databases

______________________________________________________________________

### 🔧 Configurable Data Quality Rules for Extraction Validation (#187)

**Overview**: A configurable rule engine in the Rust extractor that validates parsed records against YAML-defined quality rules, flagging bad data without blocking the pipeline.

#### Features

- **YAML rule configuration**: Define rules per data type with 5 condition types — Required, Range, Regex, Length, and Enum
- **Observation-only pipeline stage**: Validator evaluates records between parser and batcher; all messages pass through regardless of violations
- **Raw XML reconstruction**: Parser reconstructs XML fragments from parsed element trees for comparing against parsed JSON to diagnose data vs parsing errors
- **Flagged record storage**: Writes separate XML, JSON, and JSONL files per flagged record organized by version/data_type
- **Quality report**: Tracks per-rule violation counts with deterministic output for automated analysis
- **Default rules**: Ships with `extraction-rules.yaml` covering numeric genre detection, year-out-of-range checks, missing title/name validation across all 4 data types
- **Docker integration**: Rules file mounted read-only into extractor container via docker-compose

#### Documentation

- Design spec: `docs/superpowers/specs/2026-03-21-data-quality-rules-design.md`
- Implementation plan: `docs/superpowers/plans/2026-03-21-data-quality-rules.md`

______________________________________________________________________

### ⚡ Optimize 6 Query Families for Fewer DB Hits and Faster Cold Cache (#186)

**Overview**: Targeted optimization of 6 query families — genre-emergence, artist-similar, label-DNA, search, and data-completeness — for dramatic reductions in DB hits and cold cache latency.

#### Features

- **Genre-emergence**: Read pre-computed `first_year` from Genre/Style nodes instead of live traversal (183.5M → ~50 DB accesses)
- **Artist-similar**: Cap inner release scan at 100K per genre to prevent full traversal of mega-genres like Rock (7M releases → 100K sampled)
- **Label-DNA**: Batch 4 separate identity/genre/style/decade queries into a single `get_label_full_profile` traversal (6 queries → 3 for cold cache)
- **Search**: Cap total count, type counts, genre facets, and decade facets at 10K rows per table to prevent full scans on common terms
- **Data-completeness**: Add Redis caching (6h TTL) to prevent repeated full table scans of the releases table

______________________________________________________________________

### 🔄 CI: Skip Heavy Jobs for Markdown-Only Changes (#185)

**Overview**: GitHub Actions workflows now detect when a PR only changes markdown files and skip heavy jobs (build, test, lint) to save CI minutes.

______________________________________________________________________

### ⚡ Cypher Query Optimization — 10-100x Fewer DB Hits (#175)

**Overview**: Optimized the 6 slowest Cypher queries identified by the query profiling infrastructure, achieving 10-100x fewer database hits per query.

#### Features

- **Targeted optimization**: Profiling data from #174 identified the exact bottleneck queries
- **Better index usage**: Rewrote queries to leverage existing indexes more effectively
- **Reduced traversals**: Minimized relationship traversals and node lookups
- **Measurable impact**: Before/after perftest results stored in `perftest-results/`

______________________________________________________________________

### 🔬 Query Debug Profiling for SQL and Perftest Coverage (#174)

**Overview**: Expanded the query profiling infrastructure to cover SQL queries alongside Cypher, and broadened the perftest suite to cover additional API endpoints.

#### Features

- **SQL profiling**: Added `EXPLAIN ANALYZE` profiling for PostgreSQL queries alongside existing Cypher `PROFILE`
- **Perftest expansion**: Additional API endpoints covered in `tests/perftest/config.yaml`
- **Latency reports**: p50, p95, p99 latency measurements with statistical accuracy
- **Query plan inspection**: Automated query plan analysis for identifying performance regressions

______________________________________________________________________

### 🦀 Neo4j Rust Driver Extension — Up to 10x Driver Performance (#173)

**Overview**: Switched to `neo4j-rust-ext`, a Rust-backed extension for the Neo4j Python driver that accelerates Bolt protocol serialization/deserialization.

#### Features

- **Drop-in replacement**: No code changes required — the Rust extension transparently accelerates the existing `neo4j` Python driver
- **Up to 10x faster**: Bolt protocol handling moved from Python to compiled Rust code
- **All services benefit**: API, Graphinator, Dashboard, and Schema-Init all use the Neo4j driver

______________________________________________________________________

### 🧪 JavaScript Testing Framework with Vitest (#147)

**Overview**: Added a JavaScript testing framework using Vitest for the Explore frontend, enabling unit testing of the modular JS codebase (app.js, graph.js, api-client.js, etc.).

#### Features

- **Vitest framework**: Fast, modern JS test runner with native ES module support
- **Task runner integration**: `just test-js` and `just test-js-cov` commands for running JS tests
- **CI integration**: JavaScript tests run as part of the `test.yml` GitHub Actions workflow
- **Parallel execution**: JS tests run alongside Python and Rust tests in `just test-parallel`

______________________________________________________________________

### 🔗 Graph-Powered Music Discovery (#82, #148)

**Overview**: Added graph-powered music discovery features including artist similarity scoring, "Explore from Here" navigation, and multi-signal recommendation engine.

#### Features

- **Artist similarity**: Graph-based similarity scoring using shared labels, genres, styles, and collaborations
- **Explore from Here**: Navigate the knowledge graph starting from any artist, label, or release node
- **Multi-signal recommendations**: Combines graph proximity, genre overlap, and collaboration patterns to surface related artists and releases
- **Explore UI integration**: Discovery features accessible from the Explore frontend

______________________________________________________________________

### 🏺 Vinyl Archaeology Snapshot Comparison (#126, #146)

**Overview**: Extended the Vinyl Archaeology time-travel feature with snapshot comparison capabilities, allowing users to compare the state of the knowledge graph at different points in music history.

#### Features

- **Snapshot comparison**: Compare graph state between two points in time
- **Visual diff**: See what changed in the graph between selected time periods
- **Explore UI integration**: Comparison controls integrated into the timeline scrubber

______________________________________________________________________

### 🎨 Unified Explore Styling (#141, #144)

**Overview**: Unified the Explore frontend styling with the Dashboard design system, ensuring visual consistency across the platform.

#### Features

- **Shared design system**: Explore now uses the same Tailwind CSS theme, color palette, and component styles as the Dashboard
- **Consistent typography**: Unified font usage (Inter + JetBrains Mono) across both frontends
- **Dark theme alignment**: Explore dark theme matches Dashboard for a cohesive user experience

______________________________________________________________________

### 📈 Insights Enhancements — Redis Caching, Explore UI, Auto-Refresh (#130-133, #143)

**Overview**: Enhanced the Insights service with Redis caching for computed results, an Insights panel in the Explore UI, auto-refresh polling, and configurable milestone years.

#### Features

- **Redis caching**: Cache-aside pattern with TTL matching the schedule interval; cache invalidated after each computation run
- **Explore UI panel**: New "Insights" tab in the Explore frontend displaying precomputed analytics
- **Auto-refresh polling**: Explore UI polls for updated insights every 60 seconds
- **Configurable milestones**: `INSIGHTS_MILESTONE_YEARS` environment variable controls which anniversary years are highlighted (e.g., 25, 50, 75, 100)
- **`REDIS_HOST` for Insights**: Insights service now connects to Redis for caching

______________________________________________________________________

### 📈 Insights Service — Precomputed Analytics and Music Trends (#85)

**Overview**: Added a new Insights microservice that runs scheduled batch analytics against Neo4j and PostgreSQL, stores precomputed results, and exposes them via read-only HTTP endpoints proxied through the API service.

#### Features

- **5 computation types**: Artist centrality (graph edge count), genre trends (release count by decade), label longevity (years active), monthly anniversaries (25/30/40/50/75/100-year milestones), and data completeness scores
- **Scheduled execution**: Configurable interval via `INSIGHTS_SCHEDULE_HOURS` (default: 24 hours)
- **API proxy endpoints**: All results accessible via `/api/insights/*` (top-artists, genre-trends, label-longevity, this-month, data-completeness, status)
- **PostgreSQL storage**: Results stored in `insights.*` schema tables with computation audit log

#### Changes

- `insights/insights.py` — Main service with scheduler loop and health server (port 8008/8009)
- `insights/computations.py` — Computation orchestration for all 5 insight types
- `insights/models.py` — Pydantic response models
- `api/routers/insights.py` — API proxy router forwarding to insights service
- `schema-init/postgres_schema.py` — `insights.*` table definitions
- `docker-compose.yml` — New insights service container
- `docker-compose.prod.yml` — Production overrides with secrets

______________________________________________________________________

### 🔍 Unified Search UI — Full-Text Search with Filters (#134)

**Overview**: Added a search pane to the Explore frontend with full-text search across all entity types, powered by the existing `GET /api/search` endpoint.

#### Features

- **Search pane**: Dedicated tab in the Explore UI for full-text search
- **Entity type filters**: Filter results by artists, labels, releases, or masters
- **Paginated results**: Browse through large result sets
- **Graph integration**: Click search results to navigate to nodes in the graph

______________________________________________________________________

### 🏺 Vinyl Archaeology — Time-Travel Through the Knowledge Graph (#113)

**Overview**: Added time-travel filtering capabilities that let users explore the knowledge graph as it existed at any point in music history.

#### Features

- **Year-range endpoint**: `GET /api/explore/year-range` returns min/max release years in the dataset
- **Genre emergence**: `GET /api/explore/genre-emergence?before_year=N` returns genres that existed before a given year
- **Time-filtered expansion**: `before_year` parameter on `/api/expand` filters graph expansion by release year
- **Timeline scrubber UI**: Interactive slider in Explore frontend for setting the time-travel year

______________________________________________________________________

### 🧬 Label DNA — Fingerprint and Compare Record Labels (#101)

**Overview**: Added Label DNA endpoints that create unique fingerprints for record labels based on their genre, style, and format profiles, and allow comparing labels for similarity.

#### Features

- **Label identity**: `/api/label/{label_id}/dna` returns a label's identity profile (genres, styles, formats, decades active)
- **Similar labels**: `/api/label/{label_id}/similar` returns labels with similar DNA profiles
- **Label comparison**: `/api/label/dna/compare` compares two labels and returns a similarity score
- **Genre/style profiles**: Percentage breakdown of a label's releases by genre and style

______________________________________________________________________

### 🎨 Taste Fingerprint — Personal Collection Analytics (#114)

**Overview**: Added taste fingerprint analytics that analyze a user's personal collection to generate insights about their musical preferences.

#### Features

- **Taste heatmap**: `GET /api/user/taste/heatmap` — genre x decade heatmap of the user's collection
- **Full fingerprint**: `GET /api/user/taste/fingerprint` — combined heatmap, obscurity score, drift analysis, and blind spots
- **Blind spots**: `GET /api/user/taste/blindspots` — genres where favorite artists release but user hasn't collected
- **Taste card**: `GET /api/user/taste/card` — shareable SVG visualization of taste profile
- **Dashboard strip**: Taste fingerprint summary displayed in the Explore Collection pane

______________________________________________________________________

### 📅 Collection Timeline and Evolution (#100)

**Overview**: Added collection timeline endpoints that show how a user's collection has evolved over time.

#### Features

- **Collection timeline**: `GET /api/user/collection/timeline` — chronological view of collection additions
- **Collection evolution**: `GET /api/user/collection/evolution` — statistical evolution of collection over time

______________________________________________________________________

### 📊 Database Count Parity — Post-Extraction Cleanup

**Overview**: After extraction, database record counts could drift from the extractor's counts due to stub nodes in Neo4j (created by cross-type MERGE operations) and stale rows in PostgreSQL (left over from prior extractions). A new `extraction_complete` message and per-consumer cleanup phase ensures count parity after every run.

#### Changes

- **Extractor** (`extractor.rs`, `message_queue.rs`, `types.rs`): Records `extraction_started_at` and sends an `extraction_complete` message to all 4 fanout exchanges after all files finish. The message includes `version`, `started_at`, and per-type `record_counts`.
- **Graphinator** (`graphinator.py`): On `extraction_complete`, flushes remaining batches and deletes stub nodes (nodes without a `sha256` property) for the given data type.
- **Tableinator** (`tableinator.py`): On `extraction_complete`, flushes remaining batches and purges stale rows where `updated_at < started_at`. Single-message upsert uses `CASE` expressions to skip JSONB data rewrite for unchanged rows while always refreshing `updated_at`.
- **Schema** (`postgres_schema.py`): Added `updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()` column and index to all entity tables, with a migration for existing tables.
- **Batch processor** (`batch_processor.py`): Upsert SQL sets `updated_at = NOW()` on insert and conflict update. Unchanged rows (hash match) skip the data rewrite but get a lightweight bulk `UPDATE ... SET updated_at = NOW()` to stay marked as current.

#### Benefits

- Database counts match extractor counts after each run
- No manual cleanup needed between extractions
- Handles both additions and removals in Discogs dumps

______________________________________________________________________

### 🔍 Collection Gap Analysis — "Complete My Collection"

**Overview**: Added gap analysis endpoints that let users discover which releases they are missing from a label, artist, or master.

#### Features

- **Three gap analysis endpoints**: `/api/collection/gaps/label/{id}`, `/api/collection/gaps/artist/{id}`, `/api/collection/gaps/master/{id}`
- **Format filtering**: `/api/collection/formats` returns distinct formats in the user's collection; gap results can be filtered by format
- **Wantlist awareness**: Gap results indicate which missing releases are already on the user's wantlist; optional `exclude_wantlist` filter
- **Summary counts**: Each response includes total/owned/missing counts for the entity
- **Frontend integration**: "What am I missing?" button on artist and label nodes in the Explore info panel opens a dedicated Missing pane with paginated results, format filters, and wantlist toggle

#### Changes

- `api/routers/collection.py` — New router with gap analysis and format endpoints
- `api/queries/gap_queries.py` — Cypher queries for label, artist, and master gaps
- `explore/static/js/user-panes.js` — Gap analysis pane rendering (table, filters, pagination)
- `explore/static/js/app.js` — Info panel "What am I missing?" button wiring
- `explore/static/js/api-client.js` — `getCollectionGaps()` and `getCollectionFormats()` methods
- `explore/static/index.html` — Gaps pane and nav tab
- `explore/static/css/styles.css` — Gap analysis styles

______________________________________________________________________

### 🗑️ Curator Service Removal

**Overview**: Removed the Curator service entirely — it was dead code after sync logic was migrated to `api/routers/sync.py` during the API consolidation.

#### Changes

- Deleted `curator/` directory (service code, Dockerfile, pyproject.toml)
- Removed Curator from `docker-compose.yml`
- No functionality lost — sync endpoints continue to work at `POST /api/sync` and `GET /api/sync/status`

#### Benefits

- Reduced operational complexity (one fewer container to build, deploy, and monitor)
- Cleaner codebase with no dead code

______________________________________________________________________

### 🎨 Explore UI Redesign — Tailwind CSS + Alpine.js

**Overview**: Complete frontend redesign of the Explore service, migrating from Bootstrap + jQuery to Tailwind CSS + Alpine.js.

#### Changes

- **Tailwind CSS**: Dark theme matching the Dashboard redesign. Stylesheet built at Docker image build time by a dedicated `css-builder` Node stage (`tailwind.config.js` + `tailwind.input.css` → `explore/static/tailwind.css`)
- **Alpine.js**: Replaced jQuery with Alpine.js for reactive UI state management (modals, auth state, panel toggling)
- **Modular JS**: Split monolithic JavaScript into focused modules (`app.js`, `graph.js`, `trends.js`, `auth.js`, `autocomplete.js`, `api-client.js`, `user-panes.js`)
- **D3.js + Plotly.js**: Retained for graph visualization and trends charts (unchanged)

#### Static Files

| File                            | Change                                                                   |
| ------------------------------- | ------------------------------------------------------------------------ |
| `explore/static/index.html`     | Complete rewrite (dark Tailwind theme + Alpine.js)                       |
| `explore/static/tailwind.css`   | New — generated at Docker build time by css-builder Node stage           |
| `explore/static/css/styles.css` | Simplified to base reset + custom styles                                 |
| `explore/static/js/*.js`        | New — modular JS replacing monolithic script                             |
| `explore/tailwind.config.js`    | New — Tailwind CLI config (content paths, plugins)                       |
| `explore/tailwind.input.css`    | New — Tailwind source directives (`@tailwind base/components/utilities`) |

______________________________________________________________________

### 🔧 Shared OAuth, Auth, and Dependency Refactor

**Overview**: Consolidated shared code (OAuth helpers, auth utilities, and dependency injection) into `common/` and `api/` to reduce duplication across services.

- Extracted shared JWT decode helpers to `api/auth.py`
- Consolidated OAuth token encryption/decryption into `common/oauth.py`
- Removed duplicated implementations from individual routers

### ⚡ PostgreSQL Performance Optimizations

**Overview**: Improved query performance, indexing, and batch write throughput for PostgreSQL.

- Optimized high-frequency queries with targeted indexes
- Improved batch write logic in Tableinator for higher throughput
- Added missing indexes on `user_collections` table including full JSONB `formats` column

### ⚡ Neo4j Query and Index Optimizations

**Overview**: Improved Neo4j query performance with better index coverage and query planning.

- Added missing composite indexes for frequent query patterns
- Optimized graph traversal queries in API explore/expand endpoints
- Schema-init now creates all performance-critical indexes on first run

### 🔍 Explore Auth UI and E2E Tests

**Overview**: Added authentication UI to the Explore frontend and comprehensive E2E tests.

- Login/register UI integrated into the Explore static frontend
- User collection and wantlist panes visible after authentication
- Playwright E2E tests covering auth flow and personalized UI states

### 🔒 Autocomplete Minimum Length Raised to 3

**Overview**: Autocomplete endpoint now requires at least 3 characters to reduce noise and improve index performance.

- `GET /api/autocomplete?q=...` now returns `422` for queries shorter than 3 characters
- Frontend debounce threshold updated to match

### 🔒 Explore No Longer Uses Neo4j Directly

**Overview**: The Explore service now serves static files only and proxies all `/api/*` requests to the API service.

- Removed direct Neo4j connection from Explore — no `NEO4J_*` env vars required
- All graph queries go through the API service (configured via `API_BASE_URL`)
- Explore configuration simplified to `API_BASE_URL` and optional `CORS_ORIGINS`

______________________________________________________________________

## 📋 Overview

This document tracks recent improvements made to the Discogsography platform, focusing on CI/CD, automation, and
development experience enhancements.

## 🆕 Latest Improvements (February 2026 — Continued)

### 🔴 Redis-Backed Snapshot Store — Issue #55 (February 2026)

**Overview**: Migrated `SnapshotStore` from an in-memory Python dict to Redis (`redis.asyncio`), eliminating all limitations of the previous in-memory approach.

#### Changes

- **`api/snapshot_store.py`**: Rewritten as an async Redis-backed store. `save()` and `load()` are now coroutines. TTL eviction is handled natively by Redis (`SET ... EX`) — the manual `_evict_expired()` scan is gone.
- **`api/routers/snapshot.py`**: `configure()` now accepts a `redis_client` parameter; endpoint handlers `await` the async store methods.
- **`api/api.py`**: Passes the existing `_redis` client to `_snapshot_router.configure()` at startup.
- **`explore/snapshot_store.py`**: Deleted — dead code after API consolidation (the snapshot router has lived in `api/` since issue #72).
- **`pyproject.toml`**: Added `fakeredis>=2.0.0` to dev dependencies for test isolation.
- **Tests**: `tests/api/` and `tests/explore/` snapshot tests updated to use `fakeredis.aioredis.FakeRedis` (backed by a shared `fakeredis.FakeServer` fixture); unit tests converted to `async` with `@pytest.mark.asyncio`.

#### Benefits

| Before                                | After                                       |
| ------------------------------------- | ------------------------------------------- |
| Lost on service restart               | Persists across restarts (`appendonly yes`) |
| Process-local only                    | Shared across multiple API replicas         |
| O(n) lazy eviction scan on every save | Native Redis TTL — zero overhead            |
| Unbounded memory growth               | Bounded by Redis `maxmemory 512mb` + LRU    |

______________________________________________________________________

### 🔒 Security Hardening — Issue #71 (February 2026)

**Overview**: Addressed a set of security findings (issue #71) across the API service.

#### Changes

- **OAuth token encryption**: Discogs OAuth access tokens are now encrypted at rest using Fernet symmetric encryption before being stored in PostgreSQL. A new `OAUTH_ENCRYPTION_KEY` env var is required for the API container.
- **Constant-time login**: Login and registration now use constant-time comparison to prevent user enumeration via timing attacks.
- **Blind registration**: Duplicate email registration returns the same `201` response to prevent account enumeration.
- **JWT logout with JTI blacklist**: `POST /api/auth/logout` now revokes the token's `jti` claim in Redis (TTL = token expiry), making logout stateful.
- **Snapshot auth required**: `POST /api/snapshot` now requires a valid JWT token.
- **Rate limiting**: Added SlowAPI rate limits — register (3/min), login (5/min), sync (2/10min), autocomplete (30/min). Per-user sync cooldown (600 s) stored in Redis.
- **Security response headers**: All responses now include `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, and `Permissions-Policy`.
- **CORS**: Origins configurable via `CORS_ORIGINS` env var (comma-separated; disabled by default).
- **Input validation**: JWT algorithm validated to be `HS256`; Discogs API response bodies redacted from error messages.

#### Refactoring

- Extracted shared JWT helpers to `api/auth.py` (`b64url_encode/decode`, `decode_token`) — removed duplicated implementations from individual routers.
- Added `api/limiter.py` for a shared SlowAPI `Limiter` instance.
- Replaced all `type: ignore` pragmas with proper type narrowing across the codebase.

______________________________________________________________________

### 👤 Discogs User Integration (February 2026)

**Overview**: Full Discogs account linking, collection and wantlist sync, and personalised graph exploration.

#### Features

- **OAuth 1.0a OOB flow**: Users connect their Discogs account via `GET /api/oauth/authorize/discogs` → `POST /api/oauth/verify/discogs`. State token stored in Redis with TTL.
- **Collection & wantlist sync**: `POST /api/sync` triggers a background sync in the API service that fetches the user's Discogs collection and wantlist and writes `COLLECTED` / `WANTS` relationships to Neo4j.
- **Sync history**: `GET /api/sync/status` returns the last 10 sync operations with status, item count, and error details.
- **User endpoints**: `/api/user/collection`, `/api/user/wantlist`, `/api/user/recommendations`, `/api/user/collection/stats`, `/api/user/status` for personalised graph data.
- **Operator setup**: Discogs app credentials configured once via the `discogs-setup` CLI bundled in the API container (reads/writes the `app_config` table).

______________________________________________________________________

### 🏗️ API Consolidation (February 2026)

**Overview**: All user-facing HTTP endpoints consolidated into the central **API service**. The Curator service was removed entirely — its sync logic now lives in `api/routers/sync.py`. Explore now serves static files only.

#### Before / After

| Endpoint group       | Before                  | After               |
| -------------------- | ----------------------- | ------------------- |
| Graph queries        | Explore service (:8006) | API service (:8004) |
| Sync triggers        | Curator service (:8010) | API service (:8004) |
| User collection data | (new)                   | API service (:8004) |

#### Benefits

- Single port (8004) for all client-facing API calls — simpler frontend configuration.
- Curator eliminated as a separate service — sync logic migrated directly into the API, reducing operational complexity.
- Explore is now a static file server only, reducing its attack surface.
- Shared JWT authentication and rate limiting enforced uniformly at the API layer.

______________________________________________________________________

### 🎨 Dashboard UI Redesign (February 2026)

**Overview**: Complete frontend redesign based on a new Stitch-generated dark theme.

#### Changes

- **Tailwind CSS**: Replaced hand-written CSS with Tailwind CSS (Inter + JetBrains Mono fonts,
  Material Symbols Outlined icons). The stylesheet is built at Docker image build time by a
  dedicated `css-builder` Node stage using the Tailwind CLI (`tailwind.config.js` +
  `tailwind.input.css` → `dashboard/static/tailwind.css`), eliminating any CDN dependency at
  runtime.
- **Logo placeholder**: `<div id="app-logo">` with prominent comment block for easy brand swapping
- **Service cards**: Per-service sections (`#service-extractor`, `#service-graphinator`, `#service-tableinator`) with
  per-queue-type rows showing state/counts
- **Queue Size Metrics**: CSS height bars replace the previous Chart.js canvas — no CDN JS dependency
- **Processing Rates**: SVG circular gauges with `stroke-dashoffset` animation for publish and ack rates per queue type
- **Database cards**: `#db-neo4j` and `#db-postgresql` with status badges and live stats
- **Event log**: `#activityLog` with `.connection-status` / `.status-indicator` / `.status-text` kept for Playwright
  test compatibility
- **E2E tests updated**: `test_dashboard_ui.py` selectors updated to match the new HTML structure

#### Static Files

| File                                   | Change                                                                       |
| -------------------------------------- | ---------------------------------------------------------------------------- |
| `dashboard/static/index.html`          | Complete rewrite (dark Tailwind theme)                                       |
| `dashboard/static/tailwind.css`        | New — generated at Docker build time by css-builder Node stage               |
| `dashboard/static/styles.css`          | Simplified to base reset + legacy selector stubs                             |
| `dashboard/static/dashboard.js`        | Complete rewrite (Chart.js removed, SVG gauges + CSS bars)                   |
| `dashboard/tailwind.config.js`         | New — Tailwind CLI config (content paths, forms + container-queries plugins) |
| `dashboard/tailwind.input.css`         | New — Tailwind source directives (`@tailwind base/components/utilities`)     |
| `tests/dashboard/test_dashboard_ui.py` | Updated Playwright selectors                                                 |

### 🧹 Code Simplification & Test Coverage (February 2026)

**Overview**: Simplified service code across all five components and improved test coverage from 92% to 94%.

#### Code Simplification

Reduced complexity and improved readability across all Python and Rust services without changing behavior:

**Dashboard** (`dashboard/dashboard.py`):

- Extracted `_get_or_create_gauge()` and `_get_or_create_counter()` helpers to eliminate duplicate
  Prometheus metric registration try/except blocks
- Fixed WebSocket connection tracking to use `set.discard()` instead of `list.remove()` to avoid
  `ValueError` on double-removal, and to track connection count accurately with `Gauge.set()`
- Hardened PostgreSQL address parsing to handle addresses without an explicit port (defaults to 5432)

**API** (`api/routers/explore.py`, `api/neo4j_queries.py` — previously in explore service, consolidated into API):

- Added `_run_query()`, `_run_single()`, and `_run_count()` helpers to eliminate ~20 repeated
  `async with driver.session()` blocks across all query functions
- Merged duplicate `autocomplete_genre()` and `autocomplete_style()` implementations into a single
  `_autocomplete_prefix()` helper
- Simplified `_build_categories()` using early returns instead of a mutable accumulator variable

**Graphinator** (`graphinator/graphinator.py`):

- Removed dead code branches and simplified control flow in message handlers
- Consolidated repeated node-merge patterns and deduplication logic

**Tableinator** (`tableinator/tableinator.py`):

- Simplified batch processing logic and removed redundant state tracking
- Consolidated repeated table and index creation patterns

**Extractor** (Rust, `extractor/src/`):

- Removed unused `types.rs` module entirely
- Removed dead S3 configuration fields (`s3_bucket`, `s3_region`) and `max_temp_size`
- Removed unused `from_file()` config loader (environment variables are the only supported method)
- Simplified error handling and control flow across all modules

#### Test Coverage Improvement

Increased overall test coverage from **92% → 94%** (774 → 798 tests):

| File                           | Coverage |
| ------------------------------ | -------- |
| `graphinator/graphinator.py`   | 82%      |
| `common/postgres_resilient.py` | 90%      |
| `dashboard/dashboard.py`       | 93%      |
| `tableinator/tableinator.py`   | 96%      |
| `common/rabbitmq_resilient.py` | 92%      |
| `common/neo4j_resilient.py`    | 98%      |
| `explore/explore.py`           | 97%      |

New tests cover previously untested paths including: config errors and early returns, Neo4j and
PostgreSQL connection failures, async queue edge cases (`QueueFull`/`QueueEmpty`), WebSocket
exception cleanup, batch processor flush errors in finally blocks, and missing-ID edge cases in
graph entity processing.

### 🚀 Infrastructure Upgrades (February 2026)

**Overview**: Completed three major infrastructure upgrades to modernize the platform's core dependencies.

#### RabbitMQ 4.x Upgrade

**Upgrade**: RabbitMQ 3.13-management → 4-management (4.2.3)

**Key Changes**:

- **Quorum Queues**: Migrated all 8 message queues from classic to quorum type for improved data safety and replication
- **Dead-Letter Exchanges (DLX)**: Each consumer declares its own DLQs and consumer-owned DLXs for poison message handling
- **Delivery Limit**: Set to 20 retries before routing to DLQ, preventing infinite retry loops
- **Files Modified**: docker-compose.yml, extractor.py, graphinator.py, tableinator.py, message_queue.rs

**Benefits**:

- ✅ High availability with Raft consensus
- ✅ Automatic data replication across cluster nodes
- ✅ Poison message handling prevents infinite retries
- ✅ Better data safety for critical music metadata

#### Neo4j 2026 Upgrade

**Upgrade**: Neo4j 5.25-community → 2026-community (calendar versioning)

**Key Changes**:

- **Calendar Versioning**: Switched from semantic versioning (5.x) to calendar versioning (YYYY.MM.PATCH)
- **Python Driver**: Upgraded neo4j driver from 5.x → 6.1.x across all services
- **Files Modified**: docker-compose.yml + pyproject.toml files (root, common, api, graphinator, dashboard)

**Benefits**:

- ✅ Access to latest Neo4j features and optimizations
- ✅ Improved graph query performance
- ✅ Better APOC plugin compatibility
- ✅ Future-proofed for 2026 releases

#### PostgreSQL 18 Upgrade

**Upgrade**: PostgreSQL 16-alpine → 18-alpine

**Key Changes**:

- **JSONB Performance**: 10-15% faster JSONB operations (heavily used in tableinator)
- **Data Checksums**: Enabled by default for automatic corruption detection
- **GIN Indexes**: Improved query planning for JSONB GIN indexes
- **Files Modified**: docker-compose.yml only (psycopg3 already compatible!)

**Benefits**:

- ✅ 10-15% faster JSONB queries (used extensively in releases, artists, labels, masters tables)
- ✅ Improved GIN index performance for containment queries
- ✅ Data integrity with automatic checksums
- ✅ 20-30% faster VACUUM operations
- ✅ **Zero code changes required** - psycopg3 is fully compatible

#### Migration Summary

| Component      | Old Version     | New Version    | Code Changes                   |
| -------------- | --------------- | -------------- | ------------------------------ |
| **RabbitMQ**   | 3.13-management | 4-management   | 5 files (queue declarations)   |
| **Neo4j**      | 5.25-community  | 2026-community | 7 files (driver version bumps) |
| **PostgreSQL** | 16-alpine       | 18-alpine      | 0 files (fully compatible!)    |

**Total Documentation**: 3 comprehensive migration guides created (one per service)

**Migration Guides**:

______________________________________________________________________

### 📋 State Marker System

**Problem**: When the extractor service restarted, it couldn't determine whether to continue processing, re-process, or skip already-processed Discogs data versions, potentially leading to duplicate processing or missed updates.

**Solution**: Implemented a comprehensive state marker system that tracks extraction progress across all phases.

#### Key Features

- **Version-Specific Tracking**: Each Discogs version (e.g., `20260101`) gets its own state marker file
- **Multi-Phase Monitoring**: Tracks download, processing, publishing, and overall status
- **Smart Resume Logic**: Automatically decides whether to reprocess, continue, or skip on restart
- **Per-File Progress**: Detailed tracking of individual file processing status
- **Error Recovery**: Records errors at each phase for debugging and recovery

#### Implementation

- ✅ **Rust Implementation**: `extractor/extractor/src/state_marker.rs` with 11 unit tests
- ✅ **Python Implementation**: `common/state_marker.py` with 22 unit tests
- ✅ **Documentation**: Complete usage guide in `docs/state-marker-system.md`
- ✅ **Cross-Platform**: Rust extractor and Python `common` library share identical state marker functionality

#### Benefits

- **Restart Safety**: No duplicate processing after service restarts
- **Progress Visibility**: Clear view of extraction status at any time
- **Idempotency**: Safe to restart at any point without data corruption
- **Efficiency**: Skip already-completed work automatically
- **Observability**: Detailed metrics for monitoring and debugging

#### File Structure

```json
{
  "current_version": "20260101",
  "download_phase": { "status": "completed", "files_downloaded": 4, ... },
  "processing_phase": { "status": "in_progress", "files_processed": 2, ... },
  "publishing_phase": { "status": "in_progress", "messages_published": 1234567, ... },
  "summary": { "overall_status": "in_progress", ... }
}
```

#### Processing Decisions

| Scenario               | Decision      | Action                  |
| ---------------------- | ------------- | ----------------------- |
| Download failed        | **Reprocess** | Re-download everything  |
| Processing in progress | **Continue**  | Resume unfinished files |
| All completed          | **Skip**      | Wait for next check     |

See **[State Marker System](state-marker-system.md)** for complete documentation.

### 💾 State Marker Periodic Updates

**Problem**: Extractor only saved state at file boundaries (start/complete), meaning a crash during processing could lose hours of progress. State files showed 0 records even after hours of processing.

**Solution**: Implemented periodic state marker updates every 5,000 records in extractor's existing behavior.

#### Key Changes

- ✅ **Config**: Added `state_save_interval` parameter (default: 5,000 records)
- ✅ **Batcher**: Modified `message_batcher` to save state periodically during processing
- ✅ **Tests**: Updated all 125 tests to pass with new signature
- ✅ **Consistency**: Both extractors now have identical periodic save behavior

#### Benefits

- **Crash Recovery**: Resume from last checkpoint (max 5,000 records lost vs. entire file)
- **Progress Visibility**: Real-time progress updates in state file
- **Minimal Overhead**: ~1-2ms per save, ~580 saves for 2.9M records (negligible)
- **Production-Ready**: Tested with multi-million record files

#### Performance Impact

| File     | Records | Saves  | Overhead |
| -------- | ------- | ------ | -------- |
| Masters  | 2.9M    | ~580   | \<2s     |
| Releases | 20M     | ~4,000 | \<10s    |

See **[State Marker Periodic Updates](state-marker-periodic-updates.md)** for implementation details.

## 🎯 GitHub Actions Improvements

### 🎨 Visual Consistency

- ✅ Added emojis to all workflow step names for better visual scanning
- ✅ Standardized step naming patterns across all workflows
- ✅ Improved readability and quick status recognition

### 🛡️ Security Enhancements

- ✅ Added explicit permissions blocks to all workflows (least privilege)
- ✅ Pinned non-GitHub/Docker actions to specific SHA hashes
- ✅ Updated cleanup-images workflow permissions for package management
- ✅ Enhanced container security with non-root users and security options

### ⚡ Performance Optimizations

#### Composite Actions Created

1. **`setup-python-uv`** - Consolidated Python/UV setup with caching
1. **`docker-build-cache`** - Advanced Docker layer caching management
1. **`retry-step`** - Retry logic with exponential backoff

#### Workflow Optimizations

- ✅ Run tests and E2E tests in parallel (20-30% faster)
- ✅ Enhanced caching strategies with hierarchical keys
- ✅ Docker BuildKit optimizations (inline cache, namespaces)
- ✅ Conditional execution to skip unnecessary work
- ✅ Artifact compression and retention optimization

#### Monitoring & Metrics

- ✅ Build duration tracking
- ✅ Cache hit rate reporting
- ✅ Performance notices in workflow logs
- ✅ Enhanced Discord notifications with metrics

### 🎨 Quote Standardization

- ✅ Standardized quote usage across all YAML files
- ✅ Single quotes in GitHub Actions expressions
- ✅ Double quotes for YAML string values
- ✅ Removed unnecessary quotes from simple identifiers

## 📖 Documentation Updates

### New Documentation

- ✅ **[GitHub Actions Guide](github-actions-guide.md)** - Comprehensive CI/CD documentation
- ✅ **[Recent Improvements](recent-improvements.md)** - This document

### Updated Documentation

- ✅ **README.md** - Added workflow status badges and links
- ✅ **CLAUDE.md** - Added AI development memories for GitHub Actions
- ✅ **Emoji Guide** - Added CI/CD & GitHub Actions emoji section

## 🔧 Technical Improvements

### Dependency Management

- ✅ Automated weekly dependency updates
- ✅ Dependabot configuration for all ecosystems
- ✅ Discord notifications for update status

### Code Quality

- ✅ Pre-commit hooks for all workflows
- ✅ Actionlint validation for workflow files
- ✅ YAML linting with consistent formatting

## 📊 Metrics & Results

### Performance Gains

- **Build Time**: 20-30% reduction through parallelization
- **Cache Hit Rate**: 60-70% improvement with new strategy
- **Resource Usage**: 40-50% reduction in redundant operations
- **Failure Rate**: 80% reduction in transient failures

### Workflow Status

All workflows now have status badges for quick health monitoring:

- [![Build](https://github.com/SimplicityGuy/discogsography/actions/workflows/build.yml/badge.svg)](https://github.com/SimplicityGuy/discogsography/actions/workflows/build.yml)
- [![Code Quality](https://github.com/SimplicityGuy/discogsography/actions/workflows/code-quality.yml/badge.svg)](https://github.com/SimplicityGuy/discogsography/actions/workflows/code-quality.yml)
- [![Tests](https://github.com/SimplicityGuy/discogsography/actions/workflows/test.yml/badge.svg)](https://github.com/SimplicityGuy/discogsography/actions/workflows/test.yml)
- [![E2E Tests](https://github.com/SimplicityGuy/discogsography/actions/workflows/e2e-test.yml/badge.svg)](https://github.com/SimplicityGuy/discogsography/actions/workflows/e2e-test.yml)

## 🔄 Message Processing Improvements (January 2026)

### Consumer Lifecycle Management

- ✅ Implemented automatic consumer cancellation after file completion
- ✅ Added grace period configuration (`CONSUMER_CANCEL_DELAY`)
- ✅ Enhanced progress reporting with consumer status
- ✅ Freed up RabbitMQ resources for completed files

### File Completion Tracking

- ✅ Added intelligent file completion tracking in extractor
- ✅ Prevented false stalled extractor warnings for completed files
- ✅ Enhanced progress monitoring with completion status
- ✅ Improved debugging with clear active vs. completed indicators

### Smart RabbitMQ Connection Lifecycle (January 2026)

**Resource Optimization & Intelligent Connection Management**

- ✅ **Automatic Connection Closure**: RabbitMQ connections automatically close when all consumers are idle
- ✅ **Periodic Queue Checking**: New `QUEUE_CHECK_INTERVAL` (default: 1 hour) for checking queues without persistent connections
- ✅ **Auto-Reconnection**: Automatically detects new messages and restarts consumers
- ✅ **Silent When Idle**: Progress logging stops when all queues are complete to reduce log noise
- ✅ **Type Safety**: Added explicit type annotations for better code quality

**Benefits:**

- **Resource Efficiency**: 90%+ reduction in idle RabbitMQ connection resources
- **Cleaner Logs**: No repetitive progress messages when idle
- **Automatic Recovery**: Services automatically resume when new data arrives
- **Zero Configuration**: Works out of the box with sensible defaults

**Configuration:**

```bash
QUEUE_CHECK_INTERVAL=3600    # Check queues every hour when idle (default)
CONSUMER_CANCEL_DELAY=300    # Wait 5 minutes before canceling consumers (default)
```

### Documentation

- ✅ Created comprehensive [File Completion Tracking](file-completion-tracking.md) guide
- ✅ Updated [Consumer Cancellation](consumer-cancellation.md) documentation
- ✅ Added complete documentation index at [docs/README.md](README.md)
- ✅ Linked all documentation from main README
- ✅ Updated main README with smart connection lifecycle documentation
- ✅ Updated tableinator and graphinator READMEs with new environment variables
- ✅ Documented deprecated settings with migration guidance
- ✅ Cleaned up outdated progress and coverage reports

### Batch Processing Performance Optimization (January 2026)

**Database Write Performance Enhancement**

- ✅ **Graphinator Batch Processing**: Implemented batch processing for Neo4j writes
- ✅ **Tableinator Batch Processing**: Implemented batch processing for PostgreSQL writes
- ✅ **Configurable Batch Sizes**: Environment variables for tuning batch size and flush interval
- ✅ **Automatic Flushing**: Time-based and size-based batch flushing
- ✅ **Graceful Shutdown**: All pending batches flushed before service shutdown
- ✅ **SHA256 Hash Deduplication**: Added hash-based indexes for efficient duplicate detection

**Performance Improvements:**

- **Neo4j**: 3-5x faster write throughput with batch processing
- **PostgreSQL**: 3-5x faster write throughput with batch processing
- **Memory Efficiency**: Optimized batch memory usage with configurable limits
- **Reduced Database Load**: Fewer transactions and connection overhead

**Configuration:**

```bash
# Neo4j Batch Processing
NEO4J_BATCH_MODE=true           # Enable batch mode (default)
NEO4J_BATCH_SIZE=500            # Records per batch (default)
NEO4J_BATCH_FLUSH_INTERVAL=2.0  # Seconds between flushes (default)

# PostgreSQL Batch Processing
POSTGRES_BATCH_MODE=true           # Enable batch mode (default)
POSTGRES_BATCH_SIZE=500            # Records per batch (default)
POSTGRES_BATCH_FLUSH_INTERVAL=2.0  # Seconds between flushes (default)
```

**Benefits:**

- **Throughput**: Process 3-5x more records per second
- **Database Load**: Significant reduction in transaction overhead
- **Resource Usage**: More efficient use of database connections
- **Tunable**: Configure batch size and interval based on workload

See [Configuration Guide](configuration.md#batch-processing-configuration) for detailed tuning guidance.

## 🎯 Next Steps

### Planned Improvements

- [ ] Implement semantic versioning with automated releases
- [ ] Add performance benchmarking workflows
- [ ] Create development environment setup workflow
- [ ] Implement automated changelog generation
- [ ] Persist file completion state across restarts
- [ ] Add batch processing metrics to monitoring dashboard

### Monitoring Enhancements

- [ ] Add workflow analytics dashboard
- [ ] Implement cost tracking for GitHub Actions
- [ ] Create automated performance reports
- [ ] Add completion metrics to monitoring dashboard

## 🤝 Contributing

When contributing to workflows:

1. Follow the established emoji patterns
1. Use composite actions for reusable steps
1. Ensure all workflows have appropriate permissions
1. Add tests for new functionality
1. Update documentation accordingly

## 📚 Resources

- [GitHub Actions Guide](github-actions-guide.md)
- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Composite Actions Best Practices](https://docs.github.com/en/actions/creating-actions/creating-a-composite-action)
