# Task Automation with taskipy

> 🤖 Streamlined development workflows using Python-native task automation

This project uses [taskipy](https://github.com/taskipy/taskipy) for task automation, providing a simple and intuitive interface similar to `make` or npm scripts. All tasks are defined in `pyproject.toml` and run through the `uv` package manager.

## 🚀 Quick Start

```bash
# Run any task
uv run task <task-name>

# List all available tasks
uv run task --list

# Common workflows
uv run task install      # Setup development environment
uv run task lint         # Check code quality
uv run task test         # Run test suite
uv run task up           # Start all services
```

## 📋 Available Tasks

### 🧪 Development Tasks

| Task | Description | Command |
|------|-------------|---------|
| `install` | Install all dependencies including dev extras | `uv sync --all-extras` |
| `lint` | Run all code quality checks | `ruff check . && mypy .` |
| `lint-python` | Python linting only (ruff + mypy) | `ruff check . && mypy .` |
| `format` | Auto-format code with ruff | `ruff format .` |
| `test` | Run tests (excluding E2E) | `pytest -m "not e2e"` |
| `test-cov` | Run tests with coverage report | `pytest --cov --cov-report=term-missing` |
| `test-e2e` | Run Playwright E2E tests | `pytest -m e2e --headed=false` |
| `test-all` | Run all tests including E2E | `pytest` |
| `security` | Security vulnerability scan | `bandit -r . -x "./.venv/*,./tests/*"` |
| `pre-commit` | Run all pre-commit hooks | `pre-commit run --all-files` |
| `init` | Initialize pre-commit hooks | `pre-commit install` |

### 🧹 Cleanup Tasks

| Task | Description | Command |
|------|-------------|---------|
| `clean` | Clean build artifacts and caches | Removes `__pycache__`, `.pytest_cache`, etc. |
| `clean-all` | Deep clean including .venv | ⚠️ Requires full reinstall after |

### 🚀 Service Tasks

| Task | Description | Port |
|------|-------------|------|
| `dashboard` | Start monitoring dashboard | 8003 |
| `extractor` | Start data extractor service | 8000 |
| `graphinator` | Start Neo4j service | 8001 |
| `tableinator` | Start PostgreSQL service | 8002 |

### 🐋 Docker Tasks

| Task | Description | Details |
|------|-------------|---------|
| `up` | Start all services | `docker-compose up -d` |
| `down` | Stop all services | `docker-compose down` |
| `logs` | Follow all service logs | `docker-compose logs -f` |
| `rebuild` | Rebuild and restart | `docker-compose up -d --build` |
| `build-prod` | Build production images | Uses production overlay |
| `deploy-prod` | Deploy to production | Build and start with prod config |

### 📊 Monitoring Tasks

| Task | Description | Purpose |
|------|-------------|---------|
| `monitor` | Real-time queue monitoring | Watch RabbitMQ activity |
| `check-errors` | Analyze service logs | Find errors and warnings |
| `system-monitor` | System health dashboard | Comprehensive monitoring |
| `check-updates` | Check dependencies | Find outdated packages |
| `update-hooks` | Update pre-commit | Freeze to latest versions |

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
```

### `clean-all` Additionally Removes:

```
⚠️ .venv/               # Virtual environment
⚠️ logs/                # Service logs
⚠️ /discogs-data/       # Downloaded data
```

## 💡 Common Workflows

### Initial Setup

```bash
# Clone and setup project
git clone https://github.com/SimplicityGuy/discogsography.git
cd discogsography
uv run task install
uv run task init
```

### Development Cycle

```bash
# Before coding
uv run task lint
uv run task test

# After changes
uv run task format
uv run task lint
uv run task test

# Before commit
uv run task pre-commit
```

### Running Services

```bash
# Start everything with Docker
uv run task up
uv run task logs

# Or run individual services
uv run task dashboard    # Terminal 1
uv run task extractor   # Terminal 2
uv run task graphinator # Terminal 3
uv run task tableinator # Terminal 4
```

### Debugging Issues

```bash
# Check for errors
uv run task check-errors

# Monitor queues
uv run task monitor

# Full system health
uv run task system-monitor
```

## ⚙️ Configuration

All task definitions are located in the root `pyproject.toml` file under the `[tool.taskipy.tasks]` section.

### Task Definition Syntax

```toml
[tool.taskipy.tasks]
# Simple command
task-name = "command to run"

# Multi-line command
complex-task = """
    command one && \
    command two && \
    command three
"""

# Using other tasks
combo-task = "task lint && task test"
```

### Adding New Tasks

1. Open `pyproject.toml`
1. Navigate to `[tool.taskipy.tasks]`
1. Add your task:
   ```toml
   my-task = "echo 'Hello from my task!'"
   ```
1. Run it:
   ```bash
   uv run task my-task
   ```

## 🔗 Related Documentation

- [README.md](../README.md) - Project overview
- [CLAUDE.md](../CLAUDE.md) - Development guide
- [Docker Security](docker-security.md) - Container security
- [Dockerfile Standards](dockerfile-standards.md) - Docker best practices
