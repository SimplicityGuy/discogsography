# Task Automation with taskipy

This project uses `taskipy` for task automation, similar to `make` or npm scripts. It's a Python-native task runner that's already included in our dev dependencies.

## Usage

```bash
# Run any defined task
uv run task <task-name>

# Examples:
uv run task clean        # Clean build artifacts
uv run task lint         # Run all linting
uv run task test         # Run tests
uv run task dashboard    # Start dashboard service
```

## Available Tasks

### Development Tasks

- `install` - Install all dependencies
- `lint` - Run all code quality checks
- `lint-python` - Run Python linting only (ruff + mypy)
- `format` - Format Python code with ruff
- `test` - Run tests (excluding E2E)
- `test-cov` - Run tests with coverage report
- `test-e2e` - Run E2E/Playwright tests
- `test-all` - Run all tests including E2E
- `security` - Run bandit security checks
- `init` - Initialize pre-commit hooks

### Cleanup Tasks

- `clean` - Clean build artifacts and caches
- `clean-all` - Deep clean including .venv (requires reinstall)

### Service Tasks

- `dashboard` - Run dashboard service
- `extractor` - Run extractor service
- `graphinator` - Run graphinator service
- `tableinator` - Run tableinator service

### Docker Tasks

- `up` - Start all services with docker-compose
- `down` - Stop all services
- `logs` - View logs for all services
- `rebuild` - Rebuild and start all services
- `build-prod` - Build production images
- `deploy-prod` - Deploy to production

### Utility Tasks

- `monitor` - Monitor RabbitMQ queues in real-time
- `check-errors` - Check service logs for errors
- `system-monitor` - System monitoring dashboard
- `check-updates` - Check for outdated dependencies
- `update-hooks` - Update pre-commit hooks to latest versions

## What Gets Cleaned

The `clean` task removes:

- `__pycache__` directories
- `*.egg-info` directories
- `.pytest_cache` directories
- `.ruff_cache` directories
- `.mypy_cache` directories
- `htmlcov` directories
- `dist` and `build` directories
- `*.pyc` and `*.pyo` files
- `.coverage` and `coverage.xml` files

## Examples

```bash
# Clean all build artifacts
uv run task clean

# Run linting and type checking
uv run task lint-python

# Run tests with coverage
uv run task test-cov

# Start the monitoring dashboard
uv run task dashboard

# Check for errors across all services
uv run task check-errors

# Deep clean (removes virtual environment too)
uv run task clean-all
```

## Configuration

All task definitions are in `pyproject.toml` under the `[tool.taskipy.tasks]` section. Tasks can be simple commands or multi-line shell scripts.
