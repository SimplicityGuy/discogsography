# CLAUDE.md - Development Guide

## Project Overview

**Discogsography** is a Python 3.13+ / Rust microservices platform that transforms Discogs music database exports into Neo4j knowledge graphs and PostgreSQL analytics.

> **CRITICAL**: Use **[uv](https://github.com/astral-sh/uv)** exclusively for all Python operations. **Never use pip, python, pytest, or mypy directly** — always prefix with `uv run`. See [uv Commands](#uv-commands) below.

## AI Development Rules

- **ALWAYS use `uv run`** for any Python command (pytest, mypy, ruff, python scripts)
- **Use git worktrees** for all feature work — create in `.worktrees/` directory, branch from `origin/main`. Each worktree = one branch = one PR. Use the `superpowers:using-git-worktrees` skill.
- **Open a PR for every change** — never push directly to `main`
- **Mermaid diagrams** for all diagrams in Markdown files
- **Lowercase filenames** with hyphens for new markdown files (except README). Do not rename existing markdown files.
- **Emojis in GitHub Actions** step names; single quotes in `${{ }}` expressions, double quotes for YAML strings
- **Composite actions** preferred for reusable workflow steps (see `.github/actions/`)
- **Add perf tests** for new API endpoints — update `tests/perftest/config.yaml` and `tests/perftest/run_perftest.py`
- **All log messages** must use emojis from [docs/emoji-guide.md](docs/emoji-guide.md) — no ad-hoc emojis
- **pyproject.toml ordering**: `[build-system]` → `[project]` → `[project.scripts]` → `[tool.hatch...]` → tool configs (`ruff`, `mypy`, `coverage`, `pytest`) → `[dependency-groups]`. Sort dependencies alphabetically. Service-specific files extend from root config.

## Directory Structure

```
api/                  API service — all user-facing HTTP endpoints (auth, search, graph, OAuth, insights proxy, MusicBrainz)
brainzgraphinator/    Brainzgraphinator service — MusicBrainz data → Neo4j enrichment
brainztableinator/    Brainztableinator service — MusicBrainz data → PostgreSQL
common/               Shared library — config, models, utilities used by all Python services
dashboard/            Dashboard service — real-time monitoring UI
explore/              Explore service — static file serving for graph exploration frontend (Vitest for JS tests)
extractor/            Rust-based extractor — high-performance Discogs XML and MusicBrainz JSONL ingestion
graphinator/          Graphinator service — consumes messages, builds Neo4j graph
insights/             Insights service — precomputed analytics (proxied via API at /api/insights/*)
mcp-server/           MCP server — exposes knowledge graph to AI assistants via API (no direct DB access)
schema-init/          Schema initialization — one-time Neo4j and PostgreSQL schema setup
tableinator/          Tableinator service — consumes messages, builds PostgreSQL tables
utilities/            Monitoring utilities — queue monitor, error checker, system monitor
tests/                All tests organized by service (tests/api/, tests/common/, etc.)
scripts/              Build and update scripts
docs/                 Documentation
backups/              Database backups
```

## Architecture Notes

- **Extractor** supports two modes: `--source discogs` (XML → 4 fanout exchanges) and `--source musicbrainz` (JSONL → 4 fanout exchanges). It has zero knowledge of consumers.
- **Exchange naming**: `{project}-{source}-{type}` pattern — env vars `DISCOGS_EXCHANGE_PREFIX` and `MUSICBRAINZ_EXCHANGE_PREFIX`
- **Discogs exchanges**: `discogsography-discogs-{artists,labels,masters,releases}` (4 fanout exchanges)
- **MusicBrainz exchanges**: `discogsography-musicbrainz-{artists,labels,release-groups,releases}` (4 fanout exchanges)
- **Each consumer** (graphinator, tableinator, brainzgraphinator, brainztableinator) independently declares its own queues, DLQs, and DLXs.
- **Brainzgraphinator** enriches existing Neo4j nodes with MusicBrainz metadata (properties, relationships, cross-references). Skips entities without Discogs matches.
- **Brainztableinator** stores all MusicBrainz data in `musicbrainz` PostgreSQL schema — including entities without Discogs matches — with relationships and external links.
- **Insights** fetches data from API internal endpoints (`/api/internal/insights/*`) over HTTP — does NOT connect to Neo4j directly. Uses Redis for caching.
- **Explore** serves static files only — no external HTTP endpoints, no Neo4j env vars.
- **State markers**: The extractor uses version-specific state markers (`.extraction_status_<version>.json`) to track progress. See `docs/state-marker-system.md`.

## uv Commands

```bash
uv sync --all-extras             # Install/sync all dependencies
uv add package-name              # Add dependency (updates pyproject.toml + uv.lock)
uv add --dev package-name        # Add dev dependency
uv run pytest                    # Run tests
uv run mypy .                    # Type checking
uv run ruff check .              # Linting
uv run ruff format .             # Formatting
uv run python script.py          # Run any Python script
uv lock --upgrade-package name   # Update specific package
```

## just Commands (preferred)

The `justfile` is the single source of truth for all commands. Run `just --list` for the full list.

### Setup

```bash
just install              # uv sync --all-extras
just install-all          # Sync + editable install all services (CI)
just install-e2e          # Frozen sync + E2E subset (CI)
just install-js           # cd explore && npm ci
just init                 # Install pre-commit hooks
just update-deps          # Comprehensive update (Python, Rust, pre-commit, Docker)
just update-uv            # Update uv itself
just lock-upgrade         # Lock with upgrades
just sync                 # Sync all deps (dev + extras)
just sync-upgrade         # Sync with upgrades
just update-npm           # Update Explore frontend npm deps
just update-cargo         # Update Rust deps
just update-hooks         # Update pre-commit hooks
```

### Testing

```bash
just test                 # Python tests (excluding E2E)
just test-js              # JavaScript tests (Vitest)
just test-cov             # Python tests with coverage
just test-js-cov          # JavaScript tests with coverage
just test-e2e             # End-to-end browser tests
just test-all             # Everything including E2E
just test-parallel        # All service tests in parallel (fastest)
just test-api             # API tests with coverage
just test-common          # Common library tests with coverage
just test-dashboard       # Dashboard tests with coverage
just test-explore         # Explore tests with coverage
just test-extractor       # Rust extractor tests
just test-extractor-cov   # Rust tests with coverage (cargo-llvm-cov)
just test-insights        # Insights tests with coverage
just test-graphinator     # Graphinator tests with coverage
just test-schema-init     # Schema-init tests with coverage
just test-tableinator     # Tableinator tests with coverage
just test-brainzgraphinator   # Brainzgraphinator tests with coverage
just test-brainztableinator   # Brainztableinator tests with coverage
just test-mcp-server      # MCP server tests with coverage
```

### Code Quality

```bash
just lint                 # All pre-commit hooks
just lint-python          # Ruff + mypy only
just format               # Auto-format Python (ruff format)
just security             # Security checks (bandit)
just pip-audit            # Python dependency vulnerability scan
```

### Rust

```bash
just extractor-build      # Build release
just extractor-test       # Run tests
just extractor-bench      # Run benchmarks
just extractor-lint       # Clippy (warnings = errors)
just extractor-fmt        # Format code
just extractor-fmt-check  # Check formatting (CI)
just extractor-audit      # Rust advisory database scan
just extractor-deny       # Rust license and policy check
just extractor-clean      # Clean build artifacts
```

### Docker

```bash
just up                   # Start all services
just down                 # Stop all services
just logs                 # Follow service logs
just rebuild              # Down + build + up
just build                # Build all service images
just build-prod           # Build production images
just deploy-prod          # Deploy in production mode
```

### Monitoring & Cleanup

```bash
just monitor              # Monitor RabbitMQ queues
just check-errors         # Check service logs for errors
just system-monitor       # System resource monitoring
just clean                # Remove temp files and caches
just deep-clean           # Clean + Docker volumes (destructive)
```

## Service Ports

| Service | Port | Health |
|---------|------|--------|
| API | 8004 | 8005 |
| Dashboard | 8003 | 8003 |
| Explore | 8006 | 8007 |
| Insights | 8008 | 8009 |
| Extractor | — | 8000 |
| Graphinator | — | 8001 |
| Tableinator | — | 8002 |
| Brainztableinator | — | 8010 |
| Brainzgraphinator | — | 8011 |
| Neo4j | 7474 (browser), 7687 (bolt) | — |
| PostgreSQL | 5433 (mapped from 5432) | — |
| RabbitMQ | 5672 (AMQP), 15672 (management) | — |

## Environment Variables

Core variables used across services (individual components, not composite URLs):

- `NEO4J_HOST`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` — Neo4j connection
- `POSTGRES_HOST`, `POSTGRES_USERNAME`, `POSTGRES_PASSWORD`, `POSTGRES_DATABASE` — PostgreSQL connection
- `RABBITMQ_HOST`, `RABBITMQ_USERNAME`, `RABBITMQ_PASSWORD` — RabbitMQ connection
- `REDIS_HOST` — Redis hostname
- `JWT_SECRET_KEY` — HMAC-SHA256 signing secret (API only)
- `ENCRYPTION_MASTER_KEY` — HKDF master key for OAuth + TOTP encryption (API only)
- `API_BASE_URL` — API service URL (used by Explore, Insights, MCP Server)
- `LOG_LEVEL` — Logging level (defaults to INFO)

All variables support `_FILE` variants for Docker Compose runtime secrets in production. See [docs/configuration.md](docs/configuration.md) for the full reference.

## Code Style

- Type hints on all function parameters and returns
- PEP 8 with **150-character line length** (Ruff formatter)
- Descriptive variable names, docstrings on public APIs
- Logging format: `%(asctime)s - {service_name} - %(name)s - %(levelname)s - %(message)s`
- Services log to `/logs/{service_name}.log`
- Each service displays ASCII art on startup (pure text, no emojis)
- Never log sensitive data (passwords, tokens, PII)
- Run containers as non-root users
- Maintain >80% code coverage

## Common Bug Prevention

### PostgreSQL autocommit contract
- `AsyncPostgreSQLPool` sets `autocommit=True` on all connections and resets it on return to pool
- **Before `conn.transaction()`**: always call `await conn.set_autocommit(False)` first
- **After transaction exits**: autocommit is restored by the pool automatically — do not rely on manual restoration
- **Single-statement writes** (upserts, inserts): use autocommit directly, no `conn.transaction()` needed
- **Never call `await conn.commit()`** on autocommit connections — it's a no-op

### asyncio primitives
- **Never create `asyncio.Lock`, `asyncio.Queue`, `asyncio.Event`, or `asyncio.Semaphore` in `__init__` or at module level** — they bind to the current event loop at creation time
- This applies to **all** scopes: `__init__`, class bodies, module-level globals, and dataclass `field(default_factory=...)`
- Initialize as `None` in `__init__`/module scope, create lazily in the first async method or in `initialize()`
- Pattern: `self._lock: asyncio.Lock | None = None` in `__init__`, then `if self._lock is None: self._lock = asyncio.Lock()` in the first async method

### Batch processor ack/nack contract
- **`_flush_queue` is the single authority for ack/nack** — individual `_process_*_batch` methods must NEVER call ack or nack directly
- If a message is invalid (e.g., missing `id`), mark it in a set (e.g., `nack_indices`) and let `_flush_queue` handle it
- This prevents double-ack-after-nack when `_flush_queue` acks all messages after a "successful" batch that internally nacked some

### Lock scope discipline
- If a lock protects shared state, **ALL reads AND writes** of that state must acquire the lock — not just `save()`/`flush()`
- A lock that only protects serialization while mutations are unprotected is security theater

### Timestamp comparison convention
- When checking if a token/session was invalidated by an event (password change, revocation), use `<=` (inclusive) — a token issued at the exact same second as the event MUST be invalidated
- Pattern: `if issued_at <= int(changed_at):` — never use `<`

### Field name consistency
- MusicBrainz messages from the extractor use `mb_type` (not `type`) for entity type, `service` (not `type`) for external link service names
- When reading message fields, always match the exact field name the extractor outputs — check `extractor/src/jsonl_parser.rs` for the source of truth
- When adding new fields, use consistent naming: extractor defines the schema, consumers must match

### Message acknowledgment
- **Never ack a message before processing completes** — ack only after successful DB write
- **Always nack (not silently skip)** messages with missing required fields — silent skips cause data loss
- **After nack in an exception handler, always `return`** — do not fall through to subsequent processing code

### Exchange and queue naming
- Exchange pattern: `{project}-{source}-{type}` (e.g., `discogsography-discogs-artists`)
- Queue pattern: `{exchange-prefix}-{consumer}-{type}` (e.g., `discogsography-discogs-graphinator-artists`)
- Use `DISCOGS_EXCHANGE_PREFIX` and `MUSICBRAINZ_EXCHANGE_PREFIX` env vars — never hardcode exchange names
