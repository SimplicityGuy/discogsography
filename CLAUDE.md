# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This is a modern Python 3.13+ system for processing Discogs database exports into different storage backends. The architecture consists of three main microservices:

- **extractor/**: Downloads and parses Discogs XML exports, publishing data to AMQP queues
- **graphinator/**: Consumes AMQP messages and stores data in Neo4j graph database
- **tableinator/**: Consumes AMQP messages and stores data in PostgreSQL relational database

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

- `uv run pre-commit run --all-files` - Run all pre-commit hooks
- `uv run ruff check .` - Run modern Python linting
- `uv run ruff format .` - Format Python code (alternative to black)
- `uv run mypy .` - Run type checking
- `uv run black .` - Format Python code (line length: 100)
- `uv run isort .` - Sort Python imports

### Testing

- `uv run pytest` - Run all tests
- `uv run pytest --cov` - Run tests with coverage

### Running Services

- `uv run python extractor/extractor.py` - Run extractor service
- `uv run python graphinator/graphinator.py` - Run graphinator service
- `uv run python tableinator/tableinator.py` - Run tableinator service

### Docker

Each service can be built independently:

- `docker build extractor/` - Build extractor service
- `docker build graphinator/` - Build graphinator service
- `docker build tableinator/` - Build tableinator service

## Modern Python Features Used

- **Python 3.13**: Requires latest Python with cutting-edge type hints and performance improvements
- **uv package manager**: 10-100x faster than pip with built-in lock files
- **Workspace architecture**: Multi-service monorepo with shared dependencies
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
