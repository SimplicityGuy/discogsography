# 👨‍💻 Development Guide

<div align="center">

**Complete developer guide for contributing to Discogsography**

[🏠 Back to Main](../README.md) | [📚 Documentation Index](README.md) | [🚀 Quick Start](quick-start.md)

</div>

## Overview

This guide covers the development workflow, tools, and best practices for working on Discogsography. Whether you're fixing bugs, adding features, or improving performance, this guide will help you get started.

## 🛠️ Modern Python Stack

Discogsography leverages cutting-edge Python tooling for maximum developer productivity and code quality.

### Core Tools

| Tool                                          | Purpose                             | Configuration             |
| --------------------------------------------- | ----------------------------------- | ------------------------- |
| **[uv](https://github.com/astral-sh/uv)**     | 10-100x faster package management   | `pyproject.toml`          |
| **[ruff](https://github.com/astral-sh/ruff)** | Lightning-fast linting & formatting | `pyproject.toml`          |
| **[mypy](http://mypy-lang.org/)**             | Strict static type checking         | `pyproject.toml`          |
| **[bandit](https://github.com/PyCQA/bandit)** | Security vulnerability scanning     | `pyproject.toml`          |
| **[pre-commit](https://pre-commit.com/)**     | Git hooks for code quality          | `.pre-commit-config.yaml` |
| **[just](https://just.systems/)**             | Task runner (like make, but better) | `justfile`                |

### Why These Tools?

**uv**: 10-100x faster than pip, with better dependency resolution
**ruff**: Replaces flake8, isort, pyupgrade, and more - all in one fast tool
**mypy**: Catch type errors before runtime
**bandit**: Find security vulnerabilities automatically
**pre-commit**: Ensure code quality before every commit
**just**: Simple, cross-platform task automation

## 📦 Project Structure

```
discogsography/
├── 🔐 api/                 # User auth, graph queries, OAuth, sync
│   ├── api.py              # FastAPI application entry point
│   ├── auth.py             # JWT helpers and OAuth token encryption
│   ├── limiter.py          # Shared slowapi rate-limiter instance
│   ├── setup.py            # discogs-setup CLI tool
│   ├── routers/            # FastAPI routers (auth, explore, sync, user, snapshot, oauth)
│   ├── README.md
│   └── __init__.py
├── 📦 common/              # Shared utilities and configuration
│   ├── config.py           # Centralized configuration management
│   ├── health_server.py    # Health check endpoint server
│   └── __init__.py
├── 📊 dashboard/           # Real-time monitoring dashboard
│   ├── dashboard.py        # FastAPI backend with WebSocket
│   ├── tailwind.config.js  # Tailwind CLI configuration (content paths, plugins)
│   ├── tailwind.input.css  # Tailwind source directives (@tailwind base/…)
│   ├── static/             # Frontend HTML/CSS/JS (Tailwind, SVG gauges)
│   │   ├── index.html
│   │   ├── tailwind.css    # Generated at Docker build time by css-builder stage
│   │   ├── styles.css
│   │   └── dashboard.js
│   ├── README.md
│   └── __init__.py
├── 📥 extractor/           # Rust-based high-performance extractor
│   ├── src/
│   │   └── main.rs         # Rust processing logic
│   ├── benches/            # Rust benchmarks
│   ├── tests/              # Rust unit tests
│   ├── Cargo.toml          # Rust dependencies
│   └── README.md
├── 🔍 explore/             # Static frontend for graph exploration UI
│   ├── explore.py          # FastAPI static file server (health check only)
│   ├── tailwind.config.js  # Tailwind CLI configuration (content paths, plugins)
│   ├── tailwind.input.css  # Tailwind source directives (@tailwind base/…)
│   ├── static/             # Frontend HTML/CSS/JS (Tailwind, Alpine.js, D3.js, Plotly.js)
│   │   ├── index.html
│   │   ├── tailwind.css    # Generated at Docker build time by css-builder stage
│   │   ├── css/styles.css
│   │   └── js/             # Modular JS (app, graph, trends, auth, etc.)
│   ├── README.md
│   └── __init__.py
├── 🔗 graphinator/         # Neo4j graph database service
│   ├── graphinator.py      # Graph relationship builder
│   ├── README.md
│   └── __init__.py
├── 🔧 schema-init/         # One-shot database schema initializer
│   ├── schema_init.py      # Entry point — creates Neo4j + PostgreSQL schema
│   ├── neo4j_schema.py     # Neo4j constraints and indexes
│   ├── postgres_schema.py  # PostgreSQL tables and indexes
│   ├── Dockerfile
│   └── __init__.py
├── 🐘 tableinator/         # PostgreSQL storage service
│   ├── tableinator.py      # Relational data management
│   ├── README.md
│   └── __init__.py
├── 🔧 utilities/           # Operational tools
│   ├── check_errors.py     # Log analysis
│   ├── monitor_queues.py   # Real-time queue monitoring
│   ├── system_monitor.py   # System health dashboard
│   └── __init__.py
├── 🧪 tests/               # Comprehensive test suite
│   ├── common/             # Common module tests
│   ├── dashboard/          # Dashboard tests (including E2E)
│   ├── explore/            # Explore service tests
│   ├── graphinator/        # Graphinator tests
│   ├── load/               # Load tests (Locust)
│   ├── schema-init/        # Schema initializer tests
│   └── tableinator/        # Tableinator tests
├── 📝 docs/                # Documentation
├── 📜 scripts/             # Utility scripts
│   ├── update-project.sh   # Dependency upgrade automation
│   └── README.md
├── 🐋 docker-compose.yml   # Container orchestration
├── 📄 .env.example         # Environment variable template
├── 📄 .pre-commit-config.yaml # Pre-commit hooks configuration
├── 📄 justfile             # Task automation
├── 📄 pyproject.toml       # Project configuration (root)
└── 📄 README.md            # Project overview
```

## 🚀 Development Setup

### 1. Install Prerequisites

```bash
# Install uv (package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install just (task runner)
brew install just  # macOS
# or: cargo install just
# or: https://just.systems/install.sh

# Verify installations
uv --version
just --version
```

### 2. Clone and Install Dependencies

```bash
# Clone repository
git clone https://github.com/SimplicityGuy/discogsography.git
cd discogsography

# Install all dependencies (including dev dependencies)
just install

# Or using uv directly
uv sync --all-extras
```

### 3. Initialize Development Environment

```bash
# Install pre-commit hooks
just init

# Or using uv directly
uv run pre-commit install
```

### 4. Start Infrastructure Services

```bash
# Start databases and message queue
docker-compose up -d neo4j postgres rabbitmq redis

# Verify they're running
docker-compose ps
```

### 5. Configure Environment

```bash
# Copy example environment file
cp .env.example .env

# Edit for local development (or use defaults)
nano .env
```

See [Configuration Guide](configuration.md) for all environment variables.

## 🔧 Development Workflow

### Running Services Locally

```bash
# Dashboard (monitoring UI)
just dashboard

# Explore (graph exploration & trends)
just explore

# Extractor (Rust-based data ingestion - requires cargo)
just extractor-run

# Graphinator (Neo4j builder)
just graphinator

# Tableinator (PostgreSQL builder)
just tableinator
```

### Code Quality Checks

```bash
# Run all quality checks
just lint      # Linting with ruff
just format    # Code formatting with ruff
just typecheck # Type checking with mypy
just security  # Security scan with bandit

# Or run everything at once
uv run pre-commit run --all-files
```

### Making Changes

1. **Create a branch**:

   ```bash
   git checkout -b feature/my-feature
   ```

1. **Make your changes**:

   - Follow coding standards (see below)
   - Add type hints
   - Write docstrings
   - Update tests

1. **Test your changes**:

   ```bash
   just test       # Run tests
   just test-cov   # With coverage
   ```

1. **Check code quality**:

   ```bash
   just lint
   just format
   just typecheck
   just security
   ```

1. **Commit changes**:

   ```bash
   git add .
   git commit -m "feat: add amazing feature"
   # Pre-commit hooks will run automatically
   ```

1. **Push and create PR**:

   ```bash
   git push origin feature/my-feature
   # Create pull request on GitHub
   ```

## 🧪 Testing

### Test Suite Structure

```
tests/
├── api/              # API service tests (auth, routers, queries)
├── common/           # Common module tests
├── dashboard/        # Dashboard tests
│   └── test_dashboard_ui.py  # E2E tests with Playwright
├── explore/          # Explore service tests
├── graphinator/      # Graphinator tests
├── load/             # Load tests (Locust)
├── schema-init/      # Schema initializer tests
└── tableinator/      # Tableinator tests
```

### Running Tests

Tests run in **parallel by default** using `pytest-xdist` (`-n auto --dist loadfile` is set in `pyproject.toml`). This reduces the full suite from ~15 minutes to ~5 minutes.

```bash
# All tests (excluding E2E) — runs in parallel automatically
just test

# With coverage report (parallel)
just test-cov

# Specific test file
uv run pytest tests/extractor/test_extractor.py

# Specific test function
uv run pytest tests/extractor/test_extractor.py::test_parse_artist

# Sequential execution (for debugging, shows cleaner output)
uv run pytest -n 0 -s

# With verbose output
uv run pytest -v
```

### E2E Testing with Playwright

```bash
# One-time setup
uv run playwright install chromium
uv run playwright install-deps chromium

# Run E2E tests
just test-e2e

# Or directly
uv run pytest tests/dashboard/test_dashboard_ui.py -m e2e

# With specific browser
uv run pytest tests/dashboard/test_dashboard_ui.py -m e2e --browser firefox

# Run in headed mode (see browser)
uv run pytest tests/dashboard/test_dashboard_ui.py -m e2e --headed
```

See [Testing Guide](testing-guide.md) for comprehensive testing documentation.

## 📝 Coding Standards

### Python Code Style

**Follow PEP 8** with these tools:

- **ruff**: Linting and formatting (replaces flake8, isort, pyupgrade)
- **black**: Code formatting (88 character line length)
- **mypy**: Static type checking

```bash
# Auto-format code
just format

# Check for issues
just lint

# Type check
just typecheck
```

### Type Hints

**Always use type hints** for function parameters and return values:

```python
# ✅ Good
def process_artist(artist_id: str, data: dict) -> bool:
    """Process artist data."""
    ...

# ❌ Bad
def process_artist(artist_id, data):
    ...
```

### Docstrings

**Write docstrings** for all public functions and classes:

```python
def calculate_similarity(artist1: str, artist2: str) -> float:
    """Calculate similarity score between two artists.

    Args:
        artist1: Name of first artist
        artist2: Name of second artist

    Returns:
        Similarity score between 0.0 and 1.0

    Raises:
        ValueError: If artist names are empty
    """
    ...
```

### Logging

**Use emoji-prefixed logging** for consistency (with structlog — see [Logging Guide](logging-guide.md)):

```python
import structlog

logger = structlog.get_logger(__name__)

# Startup
logger.info("🚀 Starting service...")

# Success
logger.info("✅ Operation completed successfully")

# Error
logger.error("❌ Failed to connect to database")

# Warning
logger.warning("⚠️ Connection timeout, retrying...")

# Progress
logger.info("📊 Processed 1000 records")
```

See [Logging Guide](logging-guide.md) and [Emoji Guide](emoji-guide.md) for complete logging standards.

### Error Handling

**Always handle errors gracefully**:

```python
# ✅ Good
try:
    result = perform_operation()
except ValueError as e:
    logger.error(f"❌ Invalid value: {e}")
    raise
except ConnectionError as e:
    logger.warning(f"⚠️ Connection failed: {e}, retrying...")
    retry_operation()

# ❌ Bad
try:
    result = perform_operation()
except:  # Don't use bare except
    pass  # Don't silently ignore errors
```

### Security

**Never log sensitive data**:

```python
# ✅ Good
logger.info(f"🔗 Connecting to database at {host}")

# ❌ Bad
logger.info(f"🔗 Connecting with password: {password}")
```

**Use parameterized queries**:

```python
# ✅ Good
cursor.execute(
    "SELECT * FROM artists WHERE name = %s",
    (artist_name,)
)

# ❌ Bad (SQL injection vulnerability)
cursor.execute(f"SELECT * FROM artists WHERE name = '{artist_name}'")
```

## 🔍 Debugging

### Enable Debug Logging

```bash
# Set environment variable
export LOG_LEVEL=DEBUG

# Run service
uv run python dashboard/dashboard.py

# Or with Docker
LOG_LEVEL=DEBUG docker-compose up
```

### Using Python Debugger

```python
# Add breakpoint
import pdb; pdb.set_trace()

# Or Python 3.7+
breakpoint()
```

### VS Code Debugging

Create `.vscode/launch.json`:

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Python: Dashboard",
      "type": "python",
      "request": "launch",
      "program": "${workspaceFolder}/dashboard/dashboard.py",
      "console": "integratedTerminal",
      "env": {
        "LOG_LEVEL": "DEBUG"
      }
    }
  ]
}
```

## 📊 Performance Profiling

### Profile Python Code

```python
import cProfile
import pstats

# Profile function
profiler = cProfile.Profile()
profiler.enable()

# Your code here
process_data()

profiler.disable()
stats = pstats.Stats(profiler)
stats.sort_stats('cumulative')
stats.print_stats(20)  # Top 20 functions
```

### Memory Profiling

```bash
# Install memory profiler
uv add --dev memory-profiler

# Run with profiler
uv run python -m memory_profiler script.py
```

## 🔐 Security

### Security Scanning

```bash
# Scan for vulnerabilities
just security

# Or directly
uv run bandit -r . -ll
```

### Dependency Scanning

```bash
# Check for known vulnerabilities
uv run pip-audit

# Update dependencies
./scripts/update-project.sh
```

## 📚 Documentation

### Writing Documentation

- Use Markdown for all documentation
- Follow the [Emoji Guide](emoji-guide.md) for consistency
- Add Mermaid diagrams where helpful
- Include code examples
- Keep documentation up-to-date

### Generating Documentation

```bash
# Add new documentation to docs/
# Update docs/README.md
# Link from main README.md
```

## 🎯 Best Practices

### General Guidelines

1. **Write tests first** (TDD when possible)
1. **Keep functions small** and focused
1. **Use descriptive variable names**
1. **Avoid magic numbers** - use constants
1. **Handle errors explicitly**
1. **Log important events**
1. **Document complex logic**
1. **Optimize only when needed** (measure first)

### Git Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add new feature
fix: correct bug
docs: update documentation
style: format code
refactor: restructure code
test: add tests
chore: update dependencies
```

### Code Review Checklist

- [ ] Code follows style guide
- [ ] Tests are included and pass
- [ ] Type hints are complete
- [ ] Documentation is updated
- [ ] No security vulnerabilities
- [ ] Performance is acceptable
- [ ] Error handling is robust
- [ ] Logging is appropriate

## 🔄 Continuous Integration

### GitHub Actions

The project uses GitHub Actions for CI/CD:

- **Build**: Verify Docker images build correctly
- **Code Quality**: Run linters and type checkers
- **Tests**: Run unit and integration tests
- **E2E Tests**: Run Playwright tests
- **Security**: Scan for vulnerabilities

See [GitHub Actions Guide](github-actions-guide.md) for details.

### Pre-commit Hooks

Local checks before commit:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/pre-commit/mirrors-mypy
    hooks:
      - id: mypy
```

## 🐛 Troubleshooting Development Issues

### uv Issues

```bash
# Clear cache
uv cache clean

# Reinstall dependencies
rm -rf .venv
uv sync --all-extras
```

### Pre-commit Issues

```bash
# Update pre-commit
uv run pre-commit autoupdate

# Re-install hooks
uv run pre-commit install --install-hooks
```

### Test Failures

```bash
# Run single test with verbose output
uv run pytest tests/path/to/test.py::test_name -vv

# Show stdout
uv run pytest -s

# Debug with pdb
uv run pytest --pdb
```

## Related Documentation

- [Testing Guide](testing-guide.md) - Comprehensive testing documentation
- [Contributing Guide](contributing.md) - How to contribute
- [GitHub Actions Guide](github-actions-guide.md) - CI/CD workflows
- [Logging Guide](logging-guide.md) - Logging standards
- [Emoji Guide](emoji-guide.md) - Emoji conventions

______________________________________________________________________

**Last Updated**: 2026-03-04
