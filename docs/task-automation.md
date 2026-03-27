# Task Automation with just

> 🤖 Streamlined development workflows using just task automation

This project uses [just](https://github.com/casey/just) for task automation, providing a simple and intuitive interface
similar to `make` or npm scripts. All tasks are defined in the `justfile` in the project root.

## 🚀 Quick Start

```bash
# Run any task
just <task-name>

# List all available tasks
just --list

# List tasks by group
just --list --list-heading ''

# Common workflows
just install      # Setup development environment
just lint         # Check code quality
just test         # Run test suite
just up           # Start all services
```

## 📋 Available Tasks

Tasks are organized into logical groups for easier navigation:

### 🛠️ Setup Group

| Task                | Description                                                              |
| ------------------- | ------------------------------------------------------------------------ |
| `install`           | Install all Python dependencies including dev extras                     |
| `install-all`       | Install all dependencies including editable packages for all services    |
| `install-e2e`       | Install dependencies for E2E testing (frozen lockfile, subset)           |
| `install-js`        | Install JavaScript dependencies for Explore frontend tests              |
| `init`              | Initialize pre-commit hooks for development                              |
| `configure-discogs` | Configure Discogs app credentials (run against API container)            |
| `update-hooks`      | Update pre-commit hooks to latest versions                               |
| `check-updates`     | Check for outdated dependencies (Python, Rust, Docker)                   |
| `update-deps`       | Update all dependencies to latest versions (Python, Rust, hooks, Docker) |
| `update-uv`         | Update uv itself to the latest version                                   |
| `lock-upgrade`      | Lock Python dependencies with upgrades (respects >= constraints)         |
| `sync`              | Sync all Python dependencies including dev and optional extras           |
| `sync-upgrade`      | Sync all Python dependencies with upgrades                               |
| `update-npm`        | Update npm dependencies in Explore frontend                              |
| `update-cargo`      | Update Rust dependencies (lock file only, within Cargo.toml)             |

### ✨ Quality Group

| Task          | Description                                        |
| ------------- | -------------------------------------------------- |
| `lint`        | Run all pre-commit hooks on all files              |
| `lint-python` | Run Python-specific linters (ruff + mypy)          |
| `format`      | Format all Python code with ruff                   |
| `security`    | Run security checks with bandit                    |
| `pip-audit`   | Run pip-audit (Python dependency vulnerability scan)|

### 🧪 Test Group

| Task                       | Description                                          |
| -------------------------- | ---------------------------------------------------- |
| `test`                     | Run unit and integration tests (excluding E2E)       |
| `test-js`                  | Run JavaScript unit tests for Explore frontend       |
| `test-js-cov`              | Run JavaScript tests with coverage                   |
| `test-cov`                 | Run tests with coverage report                       |
| `test-e2e`                 | Run end-to-end browser tests                         |
| `test-all`                 | Run all tests including E2E                          |
| `test-parallel`            | Run all service tests in parallel (Python, Rust, JS) |
| `test-api`                 | Run API service tests with coverage                  |
| `test-brainzgraphinator`  | Run brainzgraphinator service tests with coverage    |
| `test-brainztableinator`  | Run brainztableinator service tests with coverage    |
| `test-common`              | Run common/shared library tests with coverage        |
| `test-dashboard`           | Run dashboard service tests with coverage            |
| `test-explore`             | Run explore service tests with coverage              |
| `test-extractor`           | Run Rust extractor tests                             |
| `test-extractor-cov`       | Run Rust extractor tests with coverage               |
| `test-graphinator`         | Run graphinator service tests with coverage          |
| `test-insights`            | Run insights service tests with coverage             |
| `test-mcp-server`          | Run mcp-server tests with coverage                   |
| `test-schema-init`         | Run schema-init service tests with coverage          |
| `test-tableinator`         | Run tableinator service tests with coverage          |

### 🚀 Services Group

| Task                  | Description                                                   | Port |
| --------------------- | ------------------------------------------------------------- | ---- |
| `api`                 | Run the API service (user accounts & JWT authentication)      | 8004 |
| `brainzgraphinator`  | Run the brainzgraphinator service (MusicBrainz → Neo4j)      | -    |
| `brainztableinator`  | Run the brainztableinator service (MusicBrainz → PostgreSQL)  | -    |
| `dashboard`           | Run the dashboard service (monitoring UI)                     | 8003 |
| `explore`             | Run the explore service (static file serving for graph UI)    | 8006 |
| `extractor`           | Run the Rust extractor (Discogs data ingestion)               | -    |
| `graphinator`         | Run the graphinator service (Neo4j graph builder)             | -    |
| `insights`            | Run the insights service (precomputed analytics & trends)     | 8008 |
| `mcp-server`          | Run the MCP server (AI assistant knowledge graph interface)   | -    |
| `schema-init`         | Run the schema initializer (one-time Neo4j + PostgreSQL)      | -    |
| `tableinator`         | Run the tableinator service (PostgreSQL table builder)        | -    |

### 🦀 Rust Group

| Task                  | Description                                    |
| --------------------- | ---------------------------------------------- |
| `extractor-build`     | Build Rust extractor in release mode           |
| `extractor-test`      | Run Rust extractor tests                       |
| `extractor-bench`     | Run Rust extractor benchmarks                  |
| `extractor-run`       | Run Rust extractor in release mode             |
| `extractor-lint`      | Lint Rust code with clippy                     |
| `extractor-fmt`       | Format Rust code                               |
| `extractor-fmt-check` | Check Rust code formatting (for CI/pre-commit) |
| `extractor-audit`     | Run cargo-audit (Rust advisory database scan)  |
| `extractor-deny`      | Run cargo-deny (Rust license and policy check) |
| `extractor-clean`     | Clean Rust build artifacts                     |

### 🐋 Docker Group

| Task          | Description                                    |
| ------------- | ---------------------------------------------- |
| `up`          | Start all Docker services in background        |
| `down`        | Stop all Docker services                       |
| `logs`        | Show logs from all services (follow mode)      |
| `rebuild`     | Rebuild all Docker images and restart services |
| `build`       | Build specific service Docker images           |
| `build-prod`  | Build production Docker images                 |
| `deploy-prod` | Deploy services in production mode             |

### 📊 Monitor Group

| Task             | Description                              |
| ---------------- | ---------------------------------------- |
| `monitor`        | Monitor RabbitMQ queues in real-time     |
| `check-errors`   | Check for errors in service logs         |
| `system-monitor` | Monitor system resources and performance |

### 🧹 Clean Group

| Task         | Description                                             |
| ------------ | ------------------------------------------------------- |
| `clean`      | Clean project directory of temporary files and caches   |
| `deep-clean` | Deep clean including Docker volumes (use with caution!) |

## 🗑️ What Gets Cleaned

### `clean` Task Removes:

```
✓ __pycache__/          # Python bytecode cache
✓ *.egg-info/           # Package metadata
✓ .pytest_cache/        # Test cache
✓ .ruff_cache/          # Linter cache
✓ .mypy_cache/          # Type checker cache
✓ htmlcov/              # Coverage reports
✓ dist/                 # Distribution packages
✓ build/                # Build artifacts
✓ *.pyc, *.pyo          # Compiled Python files
✓ .coverage             # Coverage data
✓ coverage.xml          # Coverage XML report
✓ Rust target/          # Rust build artifacts
✓ .hypothesis/          # Hypothesis test cache
✓ .benchmarks/          # Benchmark results
```

### `deep-clean` Additionally Removes:

```
⚠️ Docker volumes       # Database data
⚠️ Docker orphans       # Unused containers
⚠️ Docker system cache  # Build cache
```

## 💡 Common Workflows

### Initial Setup

```bash
# Clone and setup project
git clone https://github.com/SimplicityGuy/discogsography.git
cd discogsography
just install
just init
```

### Development Cycle

```bash
# Before coding
just lint
just test

# After changes
just format
just lint
just test
```

### Running Services

```bash
# Start everything with Docker
just up
just logs

# Or run individual services
just dashboard           # Terminal 1
just explore             # Terminal 2
just graphinator         # Terminal 3
just tableinator         # Terminal 4
just brainzgraphinator   # Terminal 5
just brainztableinator   # Terminal 6
```

### Debugging Issues

```bash
# Check for errors
just check-errors

# Monitor queues
just monitor

# Full system health
just system-monitor
```

## ⚙️ Configuration

All task definitions are located in the root `justfile`.

### Task Definition Syntax

```just
# Simple task
task-name:
    command to run

# Multi-line task
complex-task:
    command one
    command two
    command three

# Task with dependencies
combo-task: lint test
    echo "All checks passed!"

# Task with parameters
greet name="World":
    echo "Hello, {{name}}!"

# Grouped task
[group('setup')]
my-task:
    echo 'This task belongs to the setup group'
```

### Adding New Tasks

1. Open `justfile`
1. Find the appropriate group section
1. Add your task with the group annotation:
   ```just
   [group('quality')]
   my-linter:
       echo 'Running my custom linter'
       my-linter-command --strict
   ```
1. Run it:
   ```bash
   just my-linter
   ```

## 🔄 Installing just

If you don't have `just` installed, you can install it using:

### macOS

```bash
brew install just
```

### Linux

```bash
curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh | bash -s -- --to /usr/local/bin
```

### Windows

```powershell
scoop install just
# or
cargo install just
```

### From source

```bash
cargo install just
```

## 🔗 Related Documentation

- [README.md](../README.md) - Project overview
- [CLAUDE.md](../CLAUDE.md) - Development guide
- [Docker Security](docker-security.md) - Container security
- [Dockerfile Standards](dockerfile-standards.md) - Docker best practices
- [Just Documentation](https://just.systems) - Official just documentation
