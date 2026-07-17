# 🛠️ Discogsography Scripts

This directory contains utility scripts for maintaining and updating the Discogsography project.

## 📦 update-project.sh

The main script for updating project dependencies and versions. This is a comprehensive tool that combines multiple update operations into a single, safe workflow.

### Features

- 🐍 **Python Version Updates**: Update Python version across all project files
- 📦 **Package Dependency Updates**: Update all Python packages with detailed change tracking
- 🦀 **Rust Dependency Updates**: Update all Rust crates in extractor (main, dev, and build deps)
- 🐳 **UV Package Manager Updates**: Update UV version in all Dockerfiles (including nested ones)
- 🔍 **Component Verification**: Verifies all expected components exist before updating
- 💾 **Automatic Backups**: Creates timestamped backups before making changes
- 📝 **Detailed Summaries**: Shows exactly what changed with before/after versions
- 🧪 **Automatic Testing**: Runs lints and tests after updates
- 🛡️ **Manual Verification Guide**: Provides step-by-step verification instructions

### Usage

```bash
# Basic usage - update all packages to latest compatible versions
./scripts/update-project.sh

# Update Python version
./scripts/update-project.sh --python 3.13

# Include major version upgrades
./scripts/update-project.sh --major

# Dry run - see what would change without making changes
./scripts/update-project.sh --dry-run

# Skip backups (not recommended)
./scripts/update-project.sh --no-backup

# Skip tests
./scripts/update-project.sh --skip-tests

# Combined example
./scripts/update-project.sh --python 3.13 --major --dry-run
```

### Options

- `--python VERSION`: Update Python to specified version
- `--no-backup`: Skip creating backup files
- `--dry-run`: Preview changes without applying them
- `--major`: Include major version upgrades for packages
- `--skip-tests`: Skip running tests after updates
- `--help`: Show help message

### Output

The script provides:

1. **Real-time progress** with emoji indicators
1. **Detailed change summary** showing:
   - Python version changes
   - UV package manager version changes
   - Individual package updates with version transitions
1. **Git commands** for staging and committing changes
1. **Manual verification steps** for ensuring everything works

### Component Coverage

The script now includes comprehensive component verification and updates **all** project files:

**Python Configuration**:

- ✅ Root `pyproject.toml`, `uv.lock`, and `pyrightconfig.json`
- ✅ All Python service `pyproject.toml` files (api, brainzgraphinator, brainztableinator, common, dashboard, explore, graphinator, insights, mcp-server, schema-init, tableinator)

**Docker Configuration**:

- ✅ All service Dockerfiles (api, brainzgraphinator, brainztableinator, dashboard, explore, extractor, graphinator, insights, schema-init, tableinator)
- ✅ `docs/dockerfile-standards.md`
- ✅ `docker-compose.yml` and `docker-compose.prod.yml`

**Rust Configuration**:

- ✅ `Cargo.toml` and `Cargo.lock` for extractor

**Node.js Configuration** (when present):

- ✅ `explore/package.json`

**Total: 25+ components verified and updated automatically**

### Example Output

```
🚀  Starting Project Update
============================================================

🔍  Verifying Project Components
============================================================
ℹ️  [INFO] Checking Python configuration files...
ℹ️  [INFO] Checking Dockerfiles...
ℹ️  [INFO] Found Rust extractor (Cargo.toml)
✅  [SUCCESS] Found 14/14 expected components
✅  [SUCCESS] All expected components found!

🐳  Updating UV Version in Dockerfiles
============================================================
ℹ️  [INFO] Latest UV version: 0.8.3
✅  [SUCCESS] UV version is already up to date (0.8.3)

📦  Updating Python Packages
============================================================
ℹ️  [INFO] Compiling upgraded dependencies...
✅  [SUCCESS] Dependencies compiled successfully
✅  [SUCCESS] Dependencies synced successfully

📝  Update Summary
============================================================

📦 Package Updates:
  • fastapi: 0.115.0 → 0.115.2
  • pydantic: 2.9.1 → 2.9.2
  • uvicorn: 0.32.0 → 0.32.1

🔀  Next Steps
============================================================
1. Review the changes:
   git diff --stat
   git diff uv.lock

2. Stage the changes:
   git add uv.lock

3. Commit the changes:
   git commit -m "chore: update dependencies
   - Update 3 Python packages
   "
```

## 🔧 compute-label-stats.sh

One-time migration script that pre-computes `release_count`, `artist_count`, and `genre_count` properties on all Label nodes in Neo4j. This replaces expensive per-request traversals with direct property reads (~3 DB hits instead of 1.2M). New data imports compute these stats automatically via graphinator's `compute_genre_style_stats()`.

### Usage

```bash
# Default settings
./scripts/compute-label-stats.sh

# Custom container/credentials
NEO4J_CONTAINER=my-neo4j NEO4J_PASSWORD=secret ./scripts/compute-label-stats.sh
```

### Environment Variables

- `NEO4J_CONTAINER`: Docker container name (default: `discogsography-neo4j`)
- `NEO4J_USER`: Neo4j username (default: `neo4j`)
- `NEO4J_PASSWORD`: Neo4j password (default: `discogsography`)

## 🔐 create-secrets.sh

Bootstraps the `secrets/` directory for production deployment. Run once on the host before starting `docker-compose.prod.yml`. The script is idempotent — it skips files that already exist and sets directory permissions to 700 and file permissions to 600.

### Usage

```bash
bash scripts/create-secrets.sh
```

## 🔄 migrate-master-year-to-int.sh

One-time migration script that converts `Master.year` from string to integer in Neo4j. Prior to this fix, graphinator stored `Master.year` as a raw string from the Discogs XML (e.g., `"1969"`). New ingests write integers directly; run this script once against an existing database to align historical data without a full re-ingest.

### Usage

```bash
# Default settings
./scripts/migrate-master-year-to-int.sh

# Custom container/credentials
NEO4J_CONTAINER=my-neo4j NEO4J_PASSWORD=secret ./scripts/migrate-master-year-to-int.sh
```

### Environment Variables

- `NEO4J_CONTAINER`: Docker container name (default: `discogsography-neo4j`)
- `NEO4J_USER`: Neo4j username (default: `neo4j`)
- `NEO4J_PASSWORD`: Neo4j password (default: `discogsography`)

## 📅 cleanup-implausible-years.sh

One-time cleanup that nulls out implausible release/master years (outside `[1860, current_year + 1]`) from existing data in **both** Neo4j and PostgreSQL.

Discogs *releases* carry their date in `<released>` (a date string), not `<year>`, so the extractor's year-range rules — which key on the `year` field — never fired for releases. Before the `common/data_normalizer.py` fix, a release dated `"0400-01-01"` was stored as year `400`, polluting the Insights "Genre Trends" chart. The code fix stops new bad years at ingest; this script aligns historical data without a full re-ingest. MusicBrainz entities use a different ingest path and are out of scope.

The script defaults to a **dry run** (counts only). Pass `--apply` to make changes.

### Usage

```bash
# Dry run — report how many records would be affected, no changes
./scripts/cleanup-implausible-years.sh

# Perform the cleanup
./scripts/cleanup-implausible-years.sh --apply
```

### Environment Variables

- `NEO4J_CONTAINER`: Neo4j container name (default: `discogsography-neo4j`)
- `NEO4J_USER`: Neo4j username (default: `neo4j`)
- `NEO4J_PASSWORD`: Neo4j password (default: `discogsography`)
- `POSTGRES_CONTAINER`: PostgreSQL container name (default: `discogsography-postgres`)
- `POSTGRES_USER`: PostgreSQL username (default: `discogsography`)
- `POSTGRES_DB`: PostgreSQL database (default: `discogsography`)

## 🐳 neo4j-entrypoint.sh

Thin wrapper for the Neo4j Docker container entrypoint. Reads the password from `/run/secrets/neo4j_password` and sets `NEO4J_AUTH` before delegating to the official Neo4j entrypoint. This is needed because Neo4j does not natively support the Docker `_FILE` secret convention.

### Usage

Used as the Docker entrypoint for the Neo4j container in `docker-compose.prod.yml` — not intended to be run manually.

## 🐰 rabbitmq-entrypoint.sh

Thin wrapper for the RabbitMQ Docker container entrypoint. Reads `/run/secrets/rabbitmq_username` and `/run/secrets/rabbitmq_password` and sets `RABBITMQ_DEFAULT_USER` / `RABBITMQ_DEFAULT_PASS` before delegating to the official RabbitMQ entrypoint. This is needed because RabbitMQ does not natively support the Docker `_FILE` secret convention.

### Usage

Used as the Docker entrypoint for the RabbitMQ container in `docker-compose.prod.yml` — not intended to be run manually.

## 🔁 migrate-encryption-key.sh

Migrates OAuth tokens to a new `ENCRYPTION_MASTER_KEY`. Generates a new HKDF master key locally and re-encrypts existing OAuth tokens inside the API container. PostgreSQL credentials are read from the container's own environment.

### Usage

```bash
./scripts/migrate-encryption-key.sh --old-key "$OLD_KEY" \
  --new-key-file secrets/encryption_master_key.txt discogsography-api
```

The `<api-container>` argument must be the API service container (has Python, psycopg, and cryptography installed) — not the postgres container.

## 🎨 generate_brand_assets.py

Generates the full "Constellation Vinyl" brand asset set (icon mark, banner, square logo, OG image, design showcase, favicons, `site.webmanifest`) for the `explore/` and `dashboard/` static directories.

### Usage

```bash
# Generate to explore/ and dashboard/
uv run python scripts/generate_brand_assets.py

# Generate to /tmp/brand_test/ for preview
uv run python scripts/generate_brand_assets.py --test
```

## 🔑 reset-password.sh

Resets a user's password in the Discogsography PostgreSQL database. Generates a PBKDF2-SHA256 hash matching the format used by `api/auth.py` and updates the user record by email address.

### Usage

```bash
./scripts/reset-password.sh <container_name> <postgres_password> <email> <new_password>

# Example
./scripts/reset-password.sh postgres discogsography user@example.com mynewpassword123
```

Password must be at least 8 characters.

## 🧪 test-database-resilience.sh

Interactive test script that simulates database outages to verify resilience features. Stops and restarts Neo4j and PostgreSQL containers while checking service health endpoints, validating that circuit breakers and retry logic handle outages gracefully.

### Usage

```bash
./scripts/test-database-resilience.sh
```

Requires all services to be running before starting. The script prompts for confirmation before proceeding.

## 🤖 GitHub Actions Integration

The project includes automated weekly dependency updates via GitHub Actions.

### Workflow: `.github/workflows/update-dependencies.yml`

- **Schedule**: Runs every Monday at 9:00 AM UTC
- **Manual trigger**: Can be run manually with options
- **Creates PR**: Opens a PR on the `automation/updates` branch
- **Auto-assigns**: Assigns to repository owner for review

### Manual Workflow Trigger

You can manually trigger the workflow from the Actions tab with options:

- **Update Python version**: Toggle to update Python
- **Python version**: Specify version (if updating)
- **Major upgrades**: Include major version updates

### PR Review Process

1. The bot creates a PR with detailed summary
1. Review the changes in the Files tab
1. Check that CI passes
1. Test locally if needed
1. Merge when satisfied

## 🛡️ Safety Features

All scripts include safety measures:

1. **Git state check**: Won't run with uncommitted changes
1. **Automatic backups**: Creates timestamped backups
1. **Dry run mode**: Preview changes before applying
1. **Error handling**: Graceful error recovery
1. **Restoration instructions**: Clear steps to undo changes

## 📋 Best Practices

1. **Always commit current changes** before running update scripts
1. **Use dry run** first to preview changes
1. **Review the summary** carefully before committing
1. **Run manual verification** for production deployments
1. **Keep backups** until changes are verified

## 🔧 Troubleshooting

### Script won't run

- Ensure you're in the project root directory
- Check that `uv`, `git`, `curl`, and `jq` are installed
- Commit or stash any uncommitted changes

### Updates fail

- Check the error message for specific issues
- Restore from backup if needed
- Try updating packages individually
- Check for conflicting dependency requirements

### GitHub Action fails

- Check the workflow logs in the Actions tab
- Ensure branch protection rules allow the bot to create PRs
- Verify the GITHUB_TOKEN has appropriate permissions
