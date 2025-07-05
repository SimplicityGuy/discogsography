# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This is a modern Python 3.13+ system for processing Discogs database exports into different storage backends. The architecture consists of three main microservices:

- **extractor/**: Downloads and parses Discogs XML exports, publishing data to AMQP queues
- **graphinator/**: Consumes AMQP messages and stores data in Neo4j graph database
- **tableinator/**: Consumes AMQP messages and stores data in PostgreSQL relational database

## Development Setup

### Initial Setup

1. **Install uv**: `curl -LsSf https://astral.sh/uv/install.sh | sh`
1. **Sync dependencies**: `uv sync --all-extras` (installs all optional dependencies)
1. **Setup pre-commit hooks**: `uv run pre-commit install`
1. **Verify setup**: `uv run ruff check . && uv run mypy .`

### Workspace Structure

This project uses uv workspaces with the following structure:

- **Root**: Shared configuration and dependencies (`config.py`)
- **extractor/**: Discogs XML processing service with its own `pyproject.toml`
- **graphinator/**: Neo4j graph database service with its own `pyproject.toml`
- **tableinator/**: PostgreSQL relational database service with its own `pyproject.toml`

Each service maintains its own dependencies while sharing common configuration.

## Development Commands

### Package Management (uv)

- `uv sync` - Install/update all dependencies from lock file
- `uv add <package>` - Add new dependency
- `uv remove <package>` - Remove dependency
- `uv run <command>` - Run command in virtual environment
- `uv sync --extra extractor` - Install extractor-specific dependencies
- `uv sync --extra graphinator` - Install graphinator-specific dependencies
- `uv sync --extra tableinator` - Install tableinator-specific dependencies
- `uv sync --extra utilities` - Install utilities dependencies (psutil, requests)
- `uv sync --extra dev` - Install development dependencies
- `uv sync --all-extras` - Install all optional dependencies

### Code Quality

- `uv run pre-commit run --all-files` - Run all pre-commit hooks (all versions frozen for consistency)
- `uv run ruff check .` - Run modern Python linting (includes flake8, isort, and more)
- `uv run ruff format .` - Format Python code (ruff's built-in formatter)
- `uv run mypy .` - Run type checking with strict settings
- `uv run black .` - Format Python code using Black formatter
- `uv run isort .` - Sort Python imports (also handled by ruff)
- `uv run bandit -r . -x "./.venv/*,./tests/*"` - Security analysis excluding virtual env and tests

**All tools use configuration from `pyproject.toml`** for consistent settings across the project.

**Tool Configurations**:

- **Ruff**: Configured with comprehensive linting rules including security (S), simplification (SIM), and more
- **MyPy**: Strict mode enabled with full type checking
- **Black**: Line length 100, targeting Python 3.13
- **isort**: Black-compatible profile with custom first-party imports
- **Bandit**: Configured to skip assert warnings (B101) for development
- **Coverage**: Configured to track all service modules
- **Pytest**: Auto-discovery with asyncio support and pythonpath configuration

**Code Standards**:

- **No tabs allowed**: All Python files must use spaces for indentation (4 spaces)
- **Line length**: 100 characters maximum
- **Python version**: 3.13+ with modern type hints
- **Import sorting**: Organized using isort with black profile

Each service can also run linting and type checking independently:

- `cd extractor && uv run mypy .` - Type check extractor service
- `cd graphinator && uv run mypy .` - Type check graphinator service
- `cd tableinator && uv run mypy .` - Type check tableinator service

### Testing

- `uv run pytest` - Run all tests (pythonpath configured in pyproject.toml)
- `uv run pytest --cov` - Run tests with coverage report
- `uv run pytest tests/test_config.py -v` - Run specific test file
- `uv run pytest -k "test_name" -v` - Run tests matching pattern
- `uv run pytest -xvs` - Run tests with verbose output, stop on first failure
- `uv run pytest --tb=short` - Run tests with shorter traceback format

**Test Structure**:

- `tests/conftest.py` - Shared pytest fixtures and test configuration
- `tests/test_config.py` - Tests for configuration management
- `tests/test_integration.py` - Integration tests for services
- `tests/extractor/test_discogs.py` - Tests for Discogs download functionality
- `tests/graphinator/test_graphinator.py` - Tests for Neo4j graphinator service
- `tests/tableinator/test_tableinator.py` - Tests for PostgreSQL tableinator service

**Test Configuration**:

- **pytest.ini_options**: Configured in pyproject.toml with pythonpath, asyncio mode, and test discovery
- **Fixtures**: Common fixtures for AMQP, Neo4j, and PostgreSQL mocking
- **Environment**: Test environment variables automatically set by conftest.py
- **Coverage**: Configured to track all service modules, excluding test files

### Running Services

- `uv run python extractor/extractor.py` - Run extractor service (with periodic checks)
- `uv run python graphinator/graphinator.py` - Run graphinator service
- `uv run python tableinator/tableinator.py` - Run tableinator service

#### Extractor Periodic Checks

The extractor service now includes automatic periodic checking for new or updated Discogs data:

- **Default interval**: 15 days
- **Configurable via**: `PERIODIC_CHECK_DAYS` environment variable
- **Behavior**: After initial processing, the service continues running and checks for updates
- **Change detection**: Uses checksums and metadata to detect new versions or file changes

Example: Run with custom check interval (e.g., daily checks):

```bash
PERIODIC_CHECK_DAYS=1 uv run python extractor/extractor.py
```

### Docker

#### Docker Compose (Recommended)

- `docker-compose up -d` - Start all services in background
- `docker-compose down` - Stop and remove all containers
- `docker-compose logs -f <service>` - Follow logs for specific service
- `docker-compose ps` - Show running containers status
- `docker-compose restart <service>` - Restart specific service
- `docker-compose exec <service> bash` - Shell into running container

#### Service URLs (when running via Docker Compose)

- **RabbitMQ Management**: http://localhost:15672 (user: discogsography, pass: discogsography)
- **Neo4j Browser**: http://localhost:7474 (user: neo4j, pass: discogsography)
- **PostgreSQL**: localhost:5432 (user: discogsography, pass: discogsography, db: discogsography)

#### Individual Service Builds

Each service can be built independently (uses root context due to shared dependencies):

- `docker build -f extractor/Dockerfile .` - Build extractor service
- `docker build -f graphinator/Dockerfile .` - Build graphinator service
- `docker build -f tableinator/Dockerfile .` - Build tableinator service

## Modern Python Features Used

- **Python 3.13**: Requires latest Python with cutting-edge type hints and performance improvements
- **uv package manager**: 10-100x faster than pip with built-in lock files and workspace support
- **Workspace architecture**: Multi-service monorepo with shared dependencies (defined in `[tool.uv.workspace]`)
- **Modern type annotations**: Uses Python 3.13 built-in generics (dict, list, tuple) instead of typing imports
- **Dataclasses**: Used for configuration and data structures with frozen=True for immutability
- **Pathlib**: Consistent path handling throughout all services
- **Modern async**: Uses asyncio.Event() and async/await patterns consistently
- **Structured logging**: JSON-structured logs with emoji prefixes for visual clarity
- **Exception handling**: Comprehensive error handling with retries and graceful degradation
- **Modern dependencies**:
  - psycopg3 with binary support for PostgreSQL
  - Latest neo4j driver with async support
  - orjson for high-performance JSON parsing
  - aio-pika for async AMQP operations
- **Python 3.13 features**: Enhanced performance, better error messages, and improved typing system
- **Development tools**:
  - Ruff for fast, comprehensive linting
  - Black for consistent code formatting
  - MyPy with strict mode for type safety
  - Pytest with asyncio support for testing
  - Pre-commit hooks for code quality

## Architecture Details

### Data Flow

1. **extractor** downloads Discogs XML dumps from S3, validates checksums, parses XML to JSON
1. Parsed data is published to AMQP exchange "discogsography-extractor" with routing keys by data type
1. **graphinator** and **tableinator** consume from queues and store in their respective databases

### Key Components

- `config.py`: Centralized configuration management with validation
- `extractor/discogs.py`: S3 download logic with proper error handling
- `extractor/extractor.py`: Main XML parsing and AMQP publishing logic
- `graphinator/graphinator.py`: Neo4j graph database consumer with modern driver
- `tableinator/tableinator.py`: PostgreSQL consumer using psycopg3

### Configuration Management

Uses modern dataclass-based configuration with environment variable validation:

- `AMQP_CONNECTION`: RabbitMQ connection string
- `DISCOGS_ROOT`: Path for downloaded files (default: /discogs-data)
- `PERIODIC_CHECK_DAYS`: Interval for checking new Discogs data (default: 15 days)
- `NEO4J_ADDRESS`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`: Neo4j connection
- `POSTGRES_ADDRESS`, `POSTGRES_USERNAME`, `POSTGRES_PASSWORD`, `POSTGRES_DATABASE`: PostgreSQL connection

### Error Handling & Reliability

- Comprehensive exception handling with logging
- Message acknowledgment/rejection for queue reliability
- Database transaction rollback on errors
- Graceful shutdown on interrupt signals
- Structured logging with correlation IDs

### Data Processing

- Uses hash-based deduplication (SHA256) to avoid reprocessing unchanged records
- Handles large XML files with streaming parser to manage memory usage
- Implements progress tracking with tqdm for long-running operations
- Modern JSON handling with orjson for performance
- Type-safe database operations with proper connection pooling

## Debugging & Monitoring

### Health Checks

All services include health checks that can be monitored:

- `docker-compose ps` - View health status of all services
- `docker inspect discogsography-<service> | grep -A5 Health` - Detailed health info

### Logging

- `docker-compose logs -f` - Follow all service logs
- `docker-compose logs -f extractor` - Follow specific service logs
- `docker-compose logs --tail=100 graphinator` - Last 100 lines from service

### Development Tools

- **Pyright**: VS Code language server configuration in `pyrightconfig.json`
- **Pre-commit**: Automated code quality checks before commits
- **Coverage**: `uv run pytest --cov` for test coverage reports
- **Type checking**: `uv run mypy .` for comprehensive type validation

### Debugging Utilities

The `utilities/` directory contains debugging tools for development:

- `check_errors.py`: Analyze service logs for errors and warnings
- `check_queues.py`: Display RabbitMQ queue statistics
- `debug_message.py`: Send test messages to AMQP queues
- `monitor_queues.py`: Real-time queue monitoring
- `system_monitor.py`: Comprehensive system health dashboard

## Security Practices

### Bandit Security Analysis

The codebase passes all bandit security checks. Development utilities use proper security annotations:

- **Subprocess calls**: Annotated with `# nosec B603 B607` for trusted Docker commands
- **Hardcoded defaults**: Annotated with `# nosec B105/B107` and `# noqa: S107` for local dev passwords
- **URL requests**: Annotated with `# nosec B310` and `# noqa: S310` for localhost-only connections

**Security principles**:

- All suppressions are line-specific, not broadly disabled
- Each suppression includes justification (development tools, no user input)
- Environment variables override all hardcoded defaults
- No user input is passed to subprocess commands

## Logging Conventions

All logger calls must follow the project's emoji pattern for visual consistency:

- **Format**: `logger.[info|warning|error]("emoji message")` with exactly one space after the emoji
- **Emoji usage**:
  - 🚀 for startup messages
  - ✅ for success/completion messages
  - ❌ for errors
  - ⚠️ for warnings
  - 🛑 for shutdown/stop messages
  - 📊 for progress/statistics
  - 📥 for downloads
  - ⬇️ for downloading files
  - 🔄 for processing operations
  - ⏳ for waiting/pending
  - 📋 for metadata operations
  - 🔍 for checking/searching
  - 📄 for file operations
  - 🆕 for new versions
  - ⏰ for periodic operations
  - 🔧 for setup/configuration

**Examples**:

```python
logger.info("🚀 Starting service...")
logger.error("❌ Failed to connect to database")
logger.warning("⚠️ Connection timeout, retrying...")
```

## GitHub Actions Caching

The GitHub workflows implement comprehensive caching to speed up CI/CD:

### Caching Strategies

1. **uv Package Manager Cache**:

   - Built-in caching via `enable-cache: true` in setup-uv action
   - Additional cache for `~/.cache/uv` and `.venv` directories
   - Cache key includes both `uv.lock` and `pyproject.toml` hashes

1. **Pre-commit Hooks Cache**:

   - Caches `~/.cache/pre-commit` directory
   - Cache key based on `.pre-commit-config.yaml` hash

1. **Pytest Cache**:

   - Caches `.pytest_cache` directory
   - Helps speed up test discovery and execution

1. **Docker Build Cache**:

   - Multiple cache sources: GitHub Actions cache, registry cache, local cache
   - Registry-based cache stored as `:buildcache` tags
   - Local cache in `/tmp/.buildx-cache` with proper rotation
   - BuildKit inline cache enabled for layer caching

1. **Arkade Tools Cache**:

   - Caches `~/.arkade` directory for hadolint and other tools

### Cache Configuration

- All caches use restore keys for fallback to older caches
- Docker caches use multiple sources for maximum hit rate
- Cache rotation implemented to prevent unbounded growth
- Platform-specific caches (Linux) for consistency

## Workflow Memories

- Always run from the project root.
- Always fix all ruff and mypy errors before completing.
- Run `uv run bandit -r . -x "./.venv/*,./tests/*"` to verify security compliance after changes.
- Scope pragmas for disabling rules to the affected lines. Avoid disabling rules for the entire file.
- Always run `uv run pre-commit run --all-files` once code changes are complete.
- All logger calls must include appropriate emojis with exactly one space after them.
- For any github actions used in the github workflows, if the action is from github or docker using the version tag is fine, but for any other, use the sha with a comment of the version.
- When updating dependencies, use `uv add` instead of manually editing pyproject.toml.
- Run `uv sync --all-extras` after any dependency changes to update the lock file.
- Use `# noqa` comments sparingly and only when absolutely necessary (e.g., `# noqa: S108` for test temp directories).
- Prefer ruff's built-in formatter over running black separately.
- Always ensure pytest tests can be run without manually setting PYTHONPATH (configured in pyproject.toml).
- GitHub workflows implement comprehensive caching for dependencies, Docker builds, and tools.
