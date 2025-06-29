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
- `uv sync --extra dev` - Install development dependencies

### Code Quality

- `uv run pre-commit run --all-files` - Run all pre-commit hooks (all versions frozen for consistency)
- `uv run ruff check .` - Run modern Python linting
- `uv run ruff format .` - Format Python code
- `uv run mypy .` - Run type checking (from root, or individual services from their directories)
- `uv run black .` - Format Python code using Black formatter
- `uv run isort .` - Sort Python imports
- `uv run bandit -r .` - Security analysis for Python code

**All tools use configuration from `pyproject.toml`** for consistent settings across the project.

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

- `uv run pytest` - Run all tests
- `uv run pytest --cov` - Run tests with coverage

### Running Services

- `uv run python extractor/extractor.py` - Run extractor service
- `uv run python graphinator/graphinator.py` - Run graphinator service
- `uv run python tableinator/tableinator.py` - Run tableinator service

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
- **uv package manager**: 10-100x faster than pip with built-in lock files
- **Workspace architecture**: Multi-service monorepo with shared dependencies (defined in `[tool.uv.workspace]`)
- **Modern type annotations**: Uses Python 3.13 built-in generics (dict, list, tuple) instead of typing imports
- **Dataclasses**: Used for configuration and data structures
- **Pathlib**: Consistent path handling throughout
- **Modern async**: Uses asyncio.Event() instead of deprecated patterns
- **Structured logging**: JSON-structured logs with proper levels
- **Exception handling**: Comprehensive error handling with retries
- **Modern dependencies**: psycopg3, latest neo4j driver, orjson for performance
- **Python 3.13 features**: Enhanced performance, better error messages, and improved typing system

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

## Workflow Memories

- Always run from the project root.
- Always fix all ruff and mypy errors before completing.
