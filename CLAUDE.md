# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This is a modern Python 3.13+ system for processing Discogs database exports into different storage backends. The architecture consists of four main microservices:

- **dashboard/**: Real-time monitoring dashboard for all services with WebSocket updates
- **extractor/**: Downloads and parses Discogs XML exports, publishing data to AMQP queues
- **graphinator/**: Consumes AMQP messages and stores data in Neo4j graph database
- **tableinator/**: Consumes AMQP messages and stores data in PostgreSQL relational database

## Development Setup

### Initial Setup

1. **Install uv**: `curl -LsSf https://astral.sh/uv/install.sh | sh`
1. **Sync dependencies**: `uv sync --all-extras` (installs all optional dependencies)
1. **Setup pre-commit hooks**: `uv run pre-commit install`
1. **Verify setup**: `uv run ruff check . && uv run mypy .`

### Python Version Management

The Python version (currently 3.13) is centralized and can be managed through:

1. **Environment Variable**: Set `PYTHON_VERSION` in your `.env` file (see `.env.example`)
1. **Update Script**: Run `./scripts/update-python-version.sh 3.14` to update all files
1. **Docker Builds**: Use `--build-arg PYTHON_VERSION=3.14` or set in `.env`
1. **GitHub Actions**: Controlled by `PYTHON_VERSION` env variable in workflow files

The Python version is automatically propagated to:

- All Dockerfiles (via build arguments)
- All pyproject.toml files (requires-python, tool configurations)
- GitHub Actions workflows
- pyrightconfig.json

### Workspace Structure

This project uses uv workspaces with the following structure:

- **Root**: Main project configuration and shared dependencies
- **common/**: Shared utilities (`config.py`, `health_server.py`)
- **dashboard/**: Monitoring dashboard with FastAPI backend and static frontend
- **extractor/**: Discogs XML processing service with its own `pyproject.toml`
- **graphinator/**: Neo4j graph database service with its own `pyproject.toml`
- **tableinator/**: PostgreSQL relational database service with its own `pyproject.toml`

Each service maintains its own dependencies while sharing common utilities.

## Development Commands

### Task Automation (taskipy)

The project uses taskipy for streamlined development workflows. All tasks are run with `uv run task <task-name>`.

See `docs/task-automation.md` for detailed task documentation.

**Development Tasks**:

- `uv run task install` - Install all dependencies including dev extras
- `uv run task lint` - Run all linting tools (ruff check and mypy)
- `uv run task format` - Format code with ruff
- `uv run task test` - Run all tests (excluding E2E by default)
- `uv run task test-e2e` - Run dashboard E2E tests with Playwright
- `uv run task security` - Run bandit security checks
- `uv run task pre-commit` - Run all pre-commit hooks
- `uv run task clean` - Clean Python cache files
- `uv run task clean-all` - Clean all generated files (cache, logs, data)

**Service Tasks**:

- `uv run task dashboard` - Run the monitoring dashboard
- `uv run task extractor` - Run the extractor service
- `uv run task graphinator` - Run the graphinator service
- `uv run task tableinator` - Run the tableinator service

**Docker Tasks**:

- `uv run task up` - Start all services with Docker Compose
- `uv run task down` - Stop all services
- `uv run task logs` - Follow logs for all services
- `uv run task rebuild` - Rebuild and start services
- `uv run task build-prod` - Build with production configuration

**Monitoring Tasks**:

- `uv run task monitor` - Monitor queue activity
- `uv run task check-errors` - Check service logs for errors
- `uv run task system-monitor` - Run comprehensive system monitor

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

- `uv run pre-commit run --all-files` - Run all pre-commit hooks (all versions frozen to commit SHAs)
  - Includes Python linting (ruff, mypy, bandit)
  - Validates Dockerfiles (hadolint)
  - Validates docker-compose files
  - Validates GitHub workflows (check-jsonschema, actionlint)
  - Validates all YAML files (yamllint)
  - Validates shell scripts (shellcheck, shfmt)
- `uv run pre-commit autoupdate --freeze` - Update and freeze pre-commit hooks to latest versions
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
- **Line length**: 100 characters maximum (150 for YAML files)
- **Python version**: 3.13+ with modern type hints
- **Import sorting**: Organized using isort with black profile
- **YAML formatting**: Validated with yamllint (config in .yamllint)
- **GitHub workflows**: Validated with check-jsonschema and actionlint

Each service can also run linting and type checking independently:

- `cd extractor && uv run mypy .` - Type check extractor service
- `cd graphinator && uv run mypy .` - Type check graphinator service
- `cd tableinator && uv run mypy .` - Type check tableinator service

### Testing

- `uv run pytest` - Run all tests (pythonpath configured in pyproject.toml)
- `uv run pytest --cov` - Run tests with coverage report
- `uv run pytest tests/test_config.py -v` - Run specific test file
- `uv run pytest -k "test_name" -v` - Run tests matching pattern
- `uv run playwright install chromium` - Install Playwright Chromium browser
- `uv run playwright install-deps chromium` - Install system dependencies for Chromium
- `uv run pytest tests/dashboard/test_dashboard_api.py` - Run dashboard API tests
- `uv run pytest tests/dashboard/test_dashboard_api_integration.py` - Run dashboard integration tests
- `uv run pytest -m "not e2e"` - Run all tests except E2E tests
- `uv run task test-e2e` - Run dashboard E2E tests with Playwright (starts test server automatically)
- `uv run pytest -xvs` - Run tests with verbose output, stop on first failure
- `uv run pytest --tb=short` - Run tests with shorter traceback format

**Test Structure**:

- `tests/conftest.py` - Shared pytest fixtures and test configuration
- `tests/test_config.py` - Tests for configuration management
- `tests/test_integration.py` - Integration tests for services
- `tests/extractor/test_discogs.py` - Tests for Discogs download functionality
- `tests/graphinator/test_graphinator.py` - Tests for Neo4j graphinator service
- `tests/tableinator/test_tableinator.py` - Tests for PostgreSQL tableinator service
- `tests/dashboard/test_dashboard_api.py` - API tests for dashboard using TestClient
- `tests/dashboard/test_dashboard_ui.py` - Playwright E2E tests (requires running dashboard)
- `tests/dashboard/conftest.py` - Mock fixtures for dashboard external dependencies

**Test Configuration**:

- **pytest.ini_options**: Configured in pyproject.toml with pythonpath, asyncio mode, and test discovery
- **Fixtures**: Common fixtures for AMQP, Neo4j, and PostgreSQL mocking
- **Environment**: Test environment variables automatically set by conftest.py
- **Coverage**: Configured to track all service modules, excluding test files
- **Dashboard Testing**: API tests use FastAPI TestClient with mocked dependencies; E2E tests use Playwright with automatic server management
- **E2E Testing**: Dashboard E2E tests are marked with `@pytest.mark.e2e` and use a `test_server` fixture for automatic server lifecycle. Tests run in headless mode by default (configured in `tests/dashboard/conftest.py`). Multi-browser testing supported (Chromium, Firefox, WebKit)

### Running Services

**Using taskipy (recommended)**:

- `uv run task dashboard` - Run monitoring dashboard
- `uv run task extractor` - Run extractor service (with periodic checks)
- `uv run task graphinator` - Run graphinator service
- `uv run task tableinator` - Run tableinator service

**Direct execution**:

- `uv run python dashboard/dashboard.py` - Run monitoring dashboard
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

**Using taskipy**:

- `uv run task up` - Start all services in background
- `uv run task down` - Stop and remove all containers
- `uv run task logs` - Follow logs for all services
- `uv run task rebuild` - Rebuild images and restart services
- `uv run task build-prod` - Build with production configuration

**Direct Commands**:

- `docker-compose up -d` - Start all services in background
- `docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d` - Start with production settings
- `docker-compose down` - Stop and remove all containers
- `docker-compose logs -f <service>` - Follow logs for specific service
- `docker-compose ps` - Show running containers status
- `docker-compose restart <service>` - Restart specific service
- `docker-compose exec <service> bash` - Shell into running container

#### Service URLs (when running via Docker Compose)

- **Dashboard**: http://localhost:8003 (Real-time monitoring dashboard)
- **RabbitMQ Management**: http://localhost:15672 (user: discogsography, pass: discogsography)
- **Neo4j Browser**: http://localhost:7474 (user: neo4j, pass: discogsography)
- **PostgreSQL**: localhost:5432 (user: discogsography, pass: discogsography, db: discogsography)

#### Individual Service Builds

Each service can be built independently (uses root context due to shared dependencies):

- `docker build --build-arg PYTHON_VERSION=3.13 -f dashboard/Dockerfile .` - Build dashboard service
- `docker build --build-arg PYTHON_VERSION=3.13 -f extractor/Dockerfile .` - Build extractor service
- `docker build --build-arg PYTHON_VERSION=3.13 -f graphinator/Dockerfile .` - Build graphinator service
- `docker build --build-arg PYTHON_VERSION=3.13 -f tableinator/Dockerfile .` - Build tableinator service

#### Docker Compose Improvements

The docker-compose.yml file includes:

1. **Health checks** - Uses pgrep to verify processes are running
1. **Security options** - `no-new-privileges:true` for service containers
1. **User mapping** - Services run as UID/GID 1000 matching Dockerfile
1. **Optimized dependencies** - Only necessary service dependencies
1. **Alpine/slim images** - Uses postgres:16-alpine and python:3.13-slim
1. **Production overlay** - docker-compose.prod.yml for production deployments
1. **Environment files** - .env.docker template for configuration

#### Docker Build Optimizations

The Dockerfiles implement several best practices:

1. **Multi-stage builds** - Separate builder stage reduces final image size
1. **BuildKit mount caching** - Uses `--mount=type=cache` for dependency caching
1. **Security updates** - Applies latest security patches in each image
1. **Non-root user** - Runs as UID/GID 1000 for consistency
1. **Health checks** - Built-in health monitoring for container orchestration
1. **Minimal layers** - Combines RUN commands to reduce layer count
1. **.dockerignore** - Excludes unnecessary files from build context
1. **Specific versions** - Pins uv version for reproducible builds
1. **Proper Python setup** - Sets PYTHONUNBUFFERED and PYTHONDONTWRITEBYTECODE
1. **Volume support** - Declares /discogs-data as volume for extractor
1. **OCI-compliant labels** - Comprehensive metadata following OCI Image Spec
1. **Dynamic build args** - Support for BUILD_DATE, BUILD_VERSION, and VCS_REF

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
  - Latest neo4j driver (5.15.0+) with async support
  - orjson for high-performance JSON parsing
  - aio-pika for async AMQP operations
  - multidict for efficient multi-value mappings
  - taskipy for Python-native task automation
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
1. **dashboard** monitors all services via health endpoints and RabbitMQ management API
1. All services write logs to both console and `/logs` directory for debugging

### Key Components

- `common/config.py`: Centralized configuration management with validation
- `common/health_server.py`: Simple HTTP health check server for service monitoring
- `dashboard/dashboard.py`: FastAPI-based monitoring dashboard with WebSocket support
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

### Dashboard

The monitoring dashboard provides real-time visibility into all services:

- **Service Health**: Live status of extractor, graphinator, and tableinator
- **Queue Metrics**: RabbitMQ queue sizes, consumer counts, and message rates
- **Database Stats**: Connection counts and sizes for PostgreSQL and Neo4j
- **Activity Log**: Recent system events and status changes
- **WebSocket Updates**: Real-time data streaming without page refresh

Access the dashboard at http://localhost:8003 when running via Docker Compose.

### Health Checks

All services expose health endpoints for monitoring:

- Dashboard: http://localhost:8003/api/metrics
- Extractor: http://localhost:8000/health
- Graphinator: http://localhost:8001/health
- Tableinator: http://localhost:8002/health

Docker Compose health checks:

- `docker-compose ps` - View health status of all services
- `docker inspect discogsography-<service> | grep -A5 Health` - Detailed health info

### Logging

**Container Logs**:

- `docker-compose logs -f` - Follow all service logs
- `docker-compose logs -f extractor` - Follow specific service logs
- `docker-compose logs --tail=100 graphinator` - Last 100 lines from service
- `uv run task logs` - Follow all logs using taskipy

**Log Files**:
All services write to log files in the `/logs` directory:

- `/logs/extractor.log` - Extractor service logs
- `/logs/graphinator.log` - Graphinator service logs
- `/logs/tableinator.log` - Tableinator service logs

These logs persist across container restarts and provide historical debugging information.

### Development Tools

- **Pyright**: VS Code language server configuration in `pyrightconfig.json`
- **Pre-commit**: Automated code quality checks before commits
- **Coverage**: `uv run pytest --cov` for test coverage reports
- **Type checking**: `uv run mypy .` for comprehensive type validation

### Debugging Utilities

The `utilities/` directory contains debugging tools for development. Access via taskipy or direct execution:

**Using taskipy**:

- `uv run task check-errors` - Analyze service logs for errors and warnings
- `uv run task monitor` - Real-time queue monitoring
- `uv run task system-monitor` - Comprehensive system health dashboard

**Direct execution**:

- `check_errors.py`: Analyze service logs for errors and warnings
- `check_queues.py`: Display RabbitMQ queue statistics
- `debug_message.py`: Send test messages to AMQP queues
- `monitor_queues.py`: Real-time queue monitoring
- `system_monitor.py`: Comprehensive system health dashboard

## Security Practices

### Bandit Security Analysis

The codebase passes all bandit security checks. Development utilities use proper security annotations:

- **Subprocess calls**: Annotated with `# nosec B603 B607` for trusted Docker commands
- **Hardcoded defaults**: Annotated with `# noqa: S107` and `# nosec B105/B107` for local dev passwords
- **URL requests**: Annotated with `# noqa: S310` and `# nosec B310` for localhost-only connections

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
  - 🐰 for RabbitMQ connections
  - 🔗 for Neo4j connections
  - 💾 for database operations
  - 🏥 for health server messages
  - ⏩ for skipping operations

**Examples**:

```python
logger.info("🚀 Starting service...")
logger.error("❌ Failed to connect to database")
logger.warning("⚠️ Connection timeout, retrying...")
```

## GitHub Actions

### Workflows

1. **build.yml** - Main CI/CD workflow that:

   - Runs code quality checks (pre-commit)
   - Runs unit tests (excluding E2E/Playwright tests)
   - Validates docker-compose files
   - Builds and pushes Docker images to GitHub Container Registry
   - Includes comprehensive caching strategies
   - **Timeout**: 15 minutes for code quality, 30 minutes for builds

1. **docker-validate.yml** - Dedicated Docker validation that:

   - Validates Dockerfiles with hadolint
   - Tests Docker builds
   - Validates docker-compose syntax and services
   - Checks security best practices
   - **Timeout**: 10 minutes for validation tasks

1. **playwright-test.yml** - Dashboard E2E testing workflow:

   - Runs only when dashboard or test files change
   - Installs Playwright browsers and dependencies
   - Executes dashboard UI tests
   - Supports multi-browser testing (Chromium, Firefox, WebKit)
   - Platform-specific testing (Ubuntu for Chrome/Firefox, macOS for Safari)
   - Mobile device emulation (iPhone 15, iPad Pro 11)
   - Video recording enabled for debugging
   - **Timeout**: 15 minutes

1. **test-all.yml** - Comprehensive test workflow:

   - Determines if dashboard tests are needed based on changed files
   - Runs unit tests separately from E2E tests
   - Conditionally runs Playwright tests only when relevant files change
   - Prevents duplicate test execution
   - **Timeout**: 15 minutes for each test job

1. **cleanup.yml** - Registry cleanup workflow:

   - Scheduled monthly cleanup of old Docker images
   - **Timeout**: 10 minutes

### Docker Compose Validation

The workflows validate docker-compose files by:

- Checking YAML syntax (via pre-commit yamllint hook)
- Validating configuration with `docker-compose config`
- Verifying all expected services are defined
- Checking service dependencies are correct
- Ensuring security options are properly set

### Playwright Setup

Playwright tests are handled in dedicated workflows:

- **playwright-test.yml**: Runs only when dashboard files change
- **test-all.yml**: Conditionally includes Playwright tests based on changed files
- Tests are marked with `@pytest.mark.e2e` for easy filtering
- Installs multiple browsers (Chromium, Firefox, WebKit) and system dependencies
- Supports cross-browser and mobile device testing
- Caches browser binaries for faster subsequent runs
- Configures environment variables for headless operation
- Uses `test_server` pytest fixture for automatic server lifecycle management
- Video recording enabled for better debugging of failures

### Test Execution Strategy

1. **Separation of Concerns**:

   - Unit tests run on every push/PR in `build.yml`
   - E2E tests run only when dashboard code changes
   - Prevents unnecessary Playwright browser downloads

1. **Conditional Execution**:

   - `test-all.yml` checks git diff for dashboard changes
   - Supports workflow_dispatch for manual full test runs
   - Avoids duplicate test execution across workflows

1. **Performance Optimization**:

   - Dashboard tests isolated to reduce CI time
   - Playwright browser cache shared across workflows
   - Separate pytest cache keys for unit vs E2E tests

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

1. **Playwright Browser Cache**:

   - Caches `~/.cache/ms-playwright` directory
   - Cache key based on `pyproject.toml` files
   - Includes system dependencies for headless Chrome

### Cache Configuration

- All caches use restore keys for fallback to older caches
- Docker caches use multiple sources for maximum hit rate
- Cache rotation implemented to prevent unbounded growth
- Platform-specific caches (Linux) for consistency

## Logging Emoji Convention

All logger calls must follow the format: emoji + single space + message. Here are the standard emoji used:

- 🚀 Starting/launching services
- ✅ Success/completion messages
- ❌ Errors and failures
- ⚠️ Warnings
- 📊 Progress updates and statistics
- 📥 Downloading/receiving data
- 🔄 Processing/updating/retrying
- 🏥 Health server messages
- 🐰 RabbitMQ connections
- 🔗 Neo4j connections
- 💾 Database operations
- 🔧 Configuration/setup operations
- 🛑 Shutdown/stop operations
- ⏳ Waiting/delay messages
- 📄 File operations
- 🔍 Search/discovery operations
- ⬇️ Downloading files
- 📋 Metadata operations
- 🆕 New versions
- ⏰ Periodic operations
- ⏩ Skipping operations (no changes needed)

## Workflow Memories

- Always run from the project root.
- Always fix all `ruff` and `mypy` errors before completing.
- Run `uv run bandit -r . -x "./.venv/*,./tests/*"` to verify security compliance after changes.
- Scope pragmas for disabling rules to the affected lines. Avoid disabling rules for the entire file.
- Logger calls must use emoji + single space + message format.
- For any GitHub actions used in the GitHub workflows, if the action is from GitHub or Docker using the version tag is fine, but for any other, use the sha with a comment of the version.
- When updating dependencies, use `uv add` instead of manually editing pyproject.toml.
- When using multiple suppression pragmas (`noqa`, `nosec`), sort them alphabetically: `# noqa` comes before `# nosec`.
- Always sort lists: `apt-get install` packages, service lists, TOML configuration arrays, etc.
- Use `DEBIAN_FRONTEND=noninteractive` for all `apt-get` commands in Dockerfiles.
- In GitHub workflows, always define environment variables in the global `env:` section, not in individual steps.
- Sort environment variables alphabetically in GitHub workflows.
- When using `docker-compose` `deploy.replicas`, `container_name` must be removed to avoid conflicts.
- After completing work, always run tests and `uv run pre-commit run --all-files`.
- Periodically commit changes with meaningful messages once tests and `pre-commit` are clean.
- Common code (`config.py`, `health_server.py`) lives in the common/ directory.
- Run `uv sync --all-extras` after any dependency changes to update the lock file.
- Use `# noqa` comments sparingly and only when absolutely necessary (e.g., `# noqa: S108` for test temp directories).
- Prefer `ruff`'s built-in formatter over running black separately.
- Always ensure `pytest` tests can be run without manually setting `PYTHONPATH` (configured in `pyproject.toml`).
- GitHub workflows implement comprehensive caching for dependencies, Docker builds, and tools.
- Do not set resource limits in `docker-compose` files.
- Use taskipy commands (e.g., `uv run task lint`) instead of direct commands when available.
- Dashboard E2E tests use `test_server` fixture, not `scripts/test-e2e.sh`.
- All services write logs to both console and `/logs` directory.
- Multi-browser testing is supported for dashboard E2E tests.
- Use `--no-sync` instead of `--frozen` in Docker startup scripts.
- Video recording is enabled for Playwright tests for debugging.
- Always use `git mv` for moving tracked files - This preserves git history and shows the operation as a rename rather than delete/add
