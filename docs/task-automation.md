# Task Automation with just

> 🤖 Streamlined development workflows using just task automation

This project uses [just](https://github.com/casey/just) for task automation, providing a simple and intuitive interface similar to `make` or npm scripts. All tasks are defined in the `justfile` in the project root.

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

| Task | Description |
|------|-------------|
| `install` | Install all dependencies including dev extras |
| `init` | Initialize pre-commit hooks for development |
| `update-hooks` | Update pre-commit hooks to latest versions |
| `check-updates` | Check for outdated dependencies |

### ✨ Quality Group

| Task | Description |
|------|-------------|
| `lint` | Run all pre-commit hooks on all files |
| `lint-python` | Run Python-specific linters (ruff + mypy) |
| `format` | Format all Python code with ruff |
| `security` | Run security checks with bandit |

### 🧪 Test Group

| Task | Description |
|------|-------------|
| `test` | Run unit and integration tests (excluding E2E) |
| `test-cov` | Run tests with coverage report |
| `test-e2e` | Run end-to-end browser tests |
| `test-all` | Run all tests including E2E |

### 🚀 Services Group

| Task | Description | Port |
|------|-------------|------|
| `dashboard` | Run the dashboard service (monitoring UI) | 8000 |
| `discovery` | Run the discovery service (AI-powered music intelligence) | 8001 |
| `pyextractor` | Run the Python extractor service | - |
| `extractor` | Run the Python extractor service (backwards compatibility) | - |
| `graphinator` | Run the graphinator service (Neo4j graph builder) | - |
| `tableinator` | Run the tableinator service (PostgreSQL table builder) | - |

### 🦀 Rust Group

| Task | Description |
|------|-------------|
| `rustextractor-build` | Build Rust extractor in release mode |
| `rustextractor-test` | Run Rust extractor tests |
| `rustextractor-bench` | Run Rust extractor benchmarks |
| `rustextractor-run` | Run Rust extractor in release mode |
| `rustextractor-lint` | Lint Rust code with clippy |
| `rustextractor-fmt` | Format Rust code |
| `rustextractor-clean` | Clean Rust build artifacts |

### 🐋 Docker Group

| Task | Description |
|------|-------------|
| `up` | Start all Docker services in background |
| `down` | Stop all Docker services |
| `logs` | Show logs from all services (follow mode) |
| `rebuild` | Rebuild all Docker images and restart services |
| `build` | Build specific service Docker images |
| `build-prod` | Build production Docker images |
| `deploy-prod` | Deploy services in production mode |

### 📊 Monitor Group

| Task | Description |
|------|-------------|
| `monitor` | Monitor RabbitMQ queues in real-time |
| `check-errors` | Check for errors in service logs |
| `system-monitor` | Monitor system resources and performance |

### 🧹 Clean Group

| Task | Description |
|------|-------------|
| `clean` | Clean project directory of temporary files and caches |
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
just dashboard    # Terminal 1
just pyextractor  # Terminal 2
just graphinator  # Terminal 3
just tableinator  # Terminal 4
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
