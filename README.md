# discogsography

![discogsography](https://github.com/SimplicityGuy/discogsography/actions/workflows/build.yml/badge.svg)
![License: MIT](https://img.shields.io/github/license/SimplicityGuy/discogsography)
![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)
[![uv](https://img.shields.io/badge/uv-package%20manager-orange?logo=python)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)
[![mypy](https://img.shields.io/badge/mypy-checked-blue)](http://mypy-lang.org/)
[![Bandit](https://img.shields.io/badge/security-bandit-yellow.svg)](https://github.com/PyCQA/bandit)
[![Docker](https://img.shields.io/badge/docker-ready-blue?logo=docker)](https://www.docker.com/)

A modern Python 3.13+ microservices system for processing [Discogs](https://www.discogs.com/) database exports into multiple storage backends. The system downloads monthly data dumps from Discogs, parses the XML files, and stores the data in both Neo4j (graph database) and PostgreSQL (relational database) for different query patterns and use cases.

## Overview

Discogsography consists of four microservices that work together to process and monitor the complete Discogs database:

1. **Dashboard** - Real-time monitoring dashboard with WebSocket updates for all services
1. **Extractor** - Downloads Discogs XML dumps from S3, validates checksums, parses XML to JSON, and publishes to message queues
1. **Graphinator** - Consumes messages and builds a graph database in Neo4j with relationships between artists, labels, releases, and masters
1. **Tableinator** - Consumes messages and stores denormalized data in PostgreSQL for fast queries and full-text search

### Architecture

```
┌─────────────────┐
│  Discogs S3     │
│  Data Dumps     │
└────────┬────────┘
         │ Download & Parse
         ▼
┌─────────────────┐
│   Extractor     │
│  (XML → JSON)   │
└────────┬────────┘
         │ Publish
         ▼
┌─────────────────┐
│   RabbitMQ      │
│  Message Queue  │
└───┬─────────┬───┘
    │         │
    ▼         ▼
┌─────────┐ ┌─────────────┐
│ Neo4j   │ │ PostgreSQL  │
│ Graph   │ │ Relational  │
└─────────┘ └─────────────┘
    ▲           ▲
    │           │
┌─────────┐ ┌─────────────┐
│Graphi-  │ │Tableinator  │
│nator    │ │             │
└─────────┘ └─────────────┘
```

### Features

- **Automatic Updates**: Periodic checking for new Discogs data releases (configurable interval, default 15 days)
- **Efficient Processing**: Hash-based deduplication to avoid reprocessing unchanged records
- **Concurrent Processing**: Multi-threaded XML parsing and concurrent message processing
- **Fault Tolerance**: Message acknowledgment, automatic retries, and graceful shutdown
- **Progress Tracking**: Real-time progress monitoring with detailed statistics
- **Docker Support**: Full Docker Compose setup with security hardening (non-root, read-only filesystems, capability dropping) - see [DOCKER_SECURITY.md](DOCKER_SECURITY.md) and [DOCKERFILE_STANDARDS.md](DOCKERFILE_STANDARDS.md)
- **Type Safety**: Comprehensive type hints and mypy validation
- **Security**: Bandit security scanning, secure coding practices, and container security best practices

## Quick Start

### Prerequisites

- Python 3.13+
- Docker and Docker Compose
- ~100GB free disk space for Discogs data
- 8GB+ RAM recommended

### Using Docker Compose (Recommended)

1. Clone the repository:

   ```bash
   git clone https://github.com/SimplicityGuy/discogsography.git
   cd discogsography
   ```

1. Start all services:

   ```bash
   docker-compose up -d
   ```

1. Monitor the logs:

   ```bash
   docker-compose logs -f extractor
   ```

1. Access the services:

   - **Dashboard**: http://localhost:8003 (real-time monitoring UI)
   - **RabbitMQ Management**: http://localhost:15672 (user: discogsography, pass: discogsography)
   - **Neo4j Browser**: http://localhost:7474 (user: neo4j, pass: discogsography)
   - **PostgreSQL**: localhost:5432 (user: discogsography, pass: discogsography, db: discogsography)

### Local Development

1. Install [uv](https://github.com/astral-sh/uv) package manager:

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

1. Install dependencies:

   ```bash
   uv sync --all-extras
   ```

1. Set up pre-commit hooks:

   ```bash
   uv run pre-commit install
   ```

1. Set environment variables:

   ```bash
   export AMQP_CONNECTION="amqp://guest:guest@localhost:5672/"
   export NEO4J_ADDRESS="bolt://localhost:7687"
   export NEO4J_USERNAME="neo4j"
   export NEO4J_PASSWORD="password"
   export POSTGRES_ADDRESS="localhost:5432"
   export POSTGRES_USERNAME="postgres"
   export POSTGRES_PASSWORD="password"
   export POSTGRES_DATABASE="discogsography"
   ```

1. Run services:

   ```bash
   # Terminal 1 - Dashboard
   uv run python dashboard/dashboard.py

   # Terminal 2 - Extractor
   uv run python extractor/extractor.py

   # Terminal 3 - Graphinator
   uv run python graphinator/graphinator.py

   # Terminal 4 - Tableinator
   uv run python tableinator/tableinator.py
   ```

## Configuration

### Environment Variables

| Variable | Description | Default | Service |
|----------|-------------|---------|---------|
| `AMQP_CONNECTION` | RabbitMQ connection string | Required | All |
| `DISCOGS_ROOT` | Path for downloaded files | `/discogs-data` | Extractor |
| `PERIODIC_CHECK_DAYS` | Days between update checks | `15` | Extractor |
| `NEO4J_ADDRESS` | Neo4j bolt address | Required | Dashboard, Graphinator |
| `NEO4J_USERNAME` | Neo4j username | Required | Dashboard, Graphinator |
| `NEO4J_PASSWORD` | Neo4j password | Required | Dashboard, Graphinator |
| `POSTGRES_ADDRESS` | PostgreSQL host:port | Required | Dashboard, Tableinator |
| `POSTGRES_USERNAME` | PostgreSQL username | Required | Dashboard, Tableinator |
| `POSTGRES_PASSWORD` | PostgreSQL password | Required | Dashboard, Tableinator |
| `POSTGRES_DATABASE` | PostgreSQL database | Required | Dashboard, Tableinator |

### Data Volume

The complete Discogs dataset includes:

- ~15 million releases
- ~2 million artists
- ~2 million masters
- ~1.5 million labels

Processing the full dataset requires:

- ~50GB for compressed XML files
- ~100GB for extracted data
- Several hours for initial processing (varies by hardware)

## Usage Examples

### Neo4j Queries (via Graphinator)

Find all albums by an artist:

```cypher
MATCH (a:Artist {name: "Pink Floyd"})-[:BY]-(r:Release)
RETURN r.title, r.id
LIMIT 10
```

Find all members of a band:

```cypher
MATCH (member:Artist)-[:MEMBER_OF]->(band:Artist {name: "The Beatles"})
RETURN member.name
```

Find all releases on a label:

```cypher
MATCH (r:Release)-[:ON]->(l:Label {name: "Blue Note"})
RETURN r.title, r.id
LIMIT 10
```

### PostgreSQL Queries (via Tableinator)

Search releases by title:

```sql
SELECT data->>'title' as title, data->>'year' as year
FROM releases
WHERE data->>'title' ILIKE '%dark side%'
LIMIT 10;
```

Get artist details:

```sql
SELECT data->>'name' as name, data->>'profile' as profile
FROM artists
WHERE data->>'name' = 'Miles Davis';
```

Find releases by year:

```sql
SELECT data->>'title' as title, data->>'artist' as artist
FROM releases
WHERE (data->>'year')::int = 1969
LIMIT 10;
```

## Monitoring

### Built-in Monitoring

Each service provides detailed progress logging:

- Record processing rates (records/second)
- Queue depths and consumer health
- Error counts and retry statistics
- Stall detection (no activity for >2 minutes)

### Debug Utilities

The `utilities/` directory contains helpful debugging tools:

```bash
# Check for errors in logs
uv run python utilities/check_errors.py

# Monitor queue statistics
uv run python utilities/check_queues.py

# Real-time queue monitoring
uv run python utilities/monitor_queues.py

# System health dashboard
uv run python utilities/system_monitor.py
```

## Development

### Code Quality

The project uses modern Python tooling:

- **uv**: Fast package management with lock files
- **ruff**: Fast Python linting and formatting
- **mypy**: Static type checking
- **bandit**: Security vulnerability scanning
- **pre-commit**: Automated code quality checks

Run all checks:

```bash
uv run pre-commit run --all-files
```

### Testing

Run the test suite:

```bash
uv run pytest                    # Run all tests
uv run pytest --cov              # Run with coverage report
uv run pytest -m "not e2e"       # Run all tests except E2E
uv run pytest tests/dashboard/   # Run dashboard tests only
```

For E2E tests with Playwright:

```bash
# One-time setup
uv run playwright install chromium        # Install browser
uv run playwright install-deps chromium   # Install system dependencies

# Run E2E tests (starts test server automatically)
./scripts/test-e2e.sh

# Or manually:
# Terminal 1: Start test dashboard
uv run python -m uvicorn tests.dashboard.dashboard_test_app:create_test_app --factory --host 127.0.0.1 --port 8003

# Terminal 2: Run E2E tests
uv run pytest tests/dashboard/test_dashboard_ui.py -m e2e
```

### Project Structure

```
discogsography/
├── common/             # Shared configuration and utilities
│   ├── config.py       # Configuration management
│   └── health_server.py # Health check endpoints
├── dashboard/          # Real-time monitoring dashboard
│   └── dashboard.py    # Web UI with WebSocket updates
├── extractor/          # XML parsing and message publishing
│   ├── extractor.py    # Main service
│   └── discogs.py      # S3 download logic
├── graphinator/        # Neo4j graph database service
│   └── graphinator.py  # Graph relationship builder
├── tableinator/        # PostgreSQL service
│   └── tableinator.py  # Relational data storage
├── utilities/          # Debugging and monitoring tools
├── docker-compose.yml  # Container orchestration
└── pyproject.toml      # Project metadata and dependencies
```

## Logging Conventions

All logger calls (`logger.info`, `logger.warning`, `logger.error`) in this project follow a consistent emoji pattern for visual clarity. Each message starts with an emoji followed by exactly one space before the message text.

### Emoji Key

| Emoji | Usage | Example |
|-------|-------|---------|
| 🚀 | Startup messages | `logger.info("🚀 Starting service...")` |
| ✅ | Success/completion messages | `logger.info("✅ Operation completed successfully")` |
| ❌ | Errors | `logger.error("❌ Failed to connect to database")` |
| ⚠️ | Warnings | `logger.warning("⚠️ Connection timeout, retrying...")` |
| 🛑 | Shutdown/stop messages | `logger.info("🛑 Shutting down gracefully")` |
| 📊 | Progress/statistics | `logger.info("📊 Processed 1000 records")` |
| 📥 | Downloads | `logger.info("📥 Starting download of data")` |
| ⬇️ | Downloading files | `logger.info("⬇️ Downloading file.xml")` |
| 🔄 | Processing operations | `logger.info("🔄 Processing batch of messages")` |
| ⏳ | Waiting/pending | `logger.info("⏳ Waiting for messages...")` |
| 📋 | Metadata operations | `logger.info("📋 Loaded metadata from cache")` |
| 🔍 | Checking/searching | `logger.info("🔍 Checking for updates...")` |
| 📄 | File operations | `logger.info("📄 File created successfully")` |
| 🆕 | New versions | `logger.info("🆕 Found newer version available")` |
| ⏰ | Periodic operations | `logger.info("⏰ Running periodic check")` |
| 🔧 | Setup/configuration | `logger.info("🔧 Creating database indexes")` |

### Example Usage

```python
logger.info("🚀 Starting Discogs data extractor")
logger.error("❌ Failed to connect to Neo4j: connection refused")
logger.warning("⚠️ Slow consumer detected, processing delayed")
logger.info("✅ All files processed successfully")
```

## Data Schema

### Neo4j Graph Model

The graph database uses the following node types and relationships:

**Nodes:**

- `Artist` - Musicians, bands, and other creators
- `Label` - Record labels and imprints
- `Master` - Master recordings (the "ideal" version of a release)
- `Release` - Specific releases/pressings of recordings
- `Genre` - Musical genres
- `Style` - Musical styles (sub-genres)

**Relationships:**

- `(Artist)-[:MEMBER_OF]->(Artist)` - Band membership
- `(Artist)-[:ALIAS_OF]->(Artist)` - Artist aliases
- `(Release)-[:BY]->(Artist)` - Release credits
- `(Release)-[:ON]->(Label)` - Label releases
- `(Release)-[:DERIVED_FROM]->(Master)` - Master/release connection
- `(Label)-[:SUBLABEL_OF]->(Label)` - Label hierarchy
- `(Release)-[:IS]->(Genre)` - Genre classification
- `(Release)-[:IS]->(Style)` - Style classification
- `(Style)-[:PART_OF]->(Genre)` - Style/genre hierarchy

### PostgreSQL Schema

Each table stores the complete JSON data with efficient indexing:

```sql
CREATE TABLE artists (
    data_id VARCHAR PRIMARY KEY,
    hash VARCHAR NOT NULL,
    data JSONB NOT NULL
);

CREATE TABLE labels (
    data_id VARCHAR PRIMARY KEY,
    hash VARCHAR NOT NULL,
    data JSONB NOT NULL
);

CREATE TABLE masters (
    data_id VARCHAR PRIMARY KEY,
    hash VARCHAR NOT NULL,
    data JSONB NOT NULL
);

CREATE TABLE releases (
    data_id VARCHAR PRIMARY KEY,
    hash VARCHAR NOT NULL,
    data JSONB NOT NULL
);
```

## Performance Considerations

### Processing Speed

Typical processing rates on modern hardware:

- **Extractor**: 5,000-10,000 records/second
- **Graphinator**: 1,000-2,000 records/second (Neo4j transactions)
- **Tableinator**: 3,000-5,000 records/second (PostgreSQL inserts)

### Resource Requirements

Recommended specifications for processing the full dataset:

- **CPU**: 4+ cores (8+ recommended)
- **RAM**: 8GB minimum (16GB+ recommended)
- **Storage**: 200GB+ SSD recommended
- **Network**: Stable internet for initial download (~50GB)

### Optimization Tips

1. **Neo4j Tuning**: Increase heap size in Neo4j configuration for better performance
1. **PostgreSQL Tuning**: Adjust `shared_buffers` and `work_mem` for large datasets
1. **RabbitMQ**: Monitor queue depths and adjust prefetch counts if needed
1. **Disk I/O**: Use SSD storage for Discogs data directory

## Troubleshooting

### Common Issues

**Extractor fails to download:**

- Check internet connection
- Verify S3 bucket is accessible (public bucket, no auth required)
- Ensure sufficient disk space in `DISCOGS_ROOT`

**Services can't connect to RabbitMQ:**

- Verify RabbitMQ is running: `docker-compose ps`
- Check connection string format
- Ensure network connectivity between services

**Neo4j connection errors:**

- Verify Neo4j is running and accessible
- Check bolt protocol address (usually `bolt://localhost:7687`)
- Ensure authentication credentials are correct

**PostgreSQL connection issues:**

- Verify PostgreSQL is running
- Check host:port format in `POSTGRES_ADDRESS`
- Ensure database exists and user has permissions

### Debugging Tips

1. **Check Service Logs**: Each service writes to its own log file
1. **Monitor Queues**: Use RabbitMQ management UI to check message flow
1. **Verify Data**: Query databases directly to ensure data is being stored
1. **Use Debug Utilities**: Run the tools in `utilities/` for detailed diagnostics

## Contributing

We welcome contributions! Please:

1. Fork the repository
1. Create a feature branch (`git checkout -b feature/amazing-feature`)
1. Make your changes and add tests
1. Ensure all checks pass (`uv run pre-commit run --all-files`)
1. Commit your changes (`git commit -m '✨ Add amazing feature'`)
1. Push to the branch (`git push origin feature/amazing-feature`)
1. Open a Pull Request

### Development Guidelines

- Follow the project's logging conventions (see above)
- Add type hints to all functions
- Write tests for new functionality
- Update documentation as needed
- Ensure all pre-commit hooks pass

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- [Discogs](https://www.discogs.com/) for providing the monthly data dumps
- The Python community for excellent libraries and tools
- Contributors and users of this project

## Support

- **Issues**: [GitHub Issues](https://github.com/SimplicityGuy/discogsography/issues)
- **Discussions**: [GitHub Discussions](https://github.com/SimplicityGuy/discogsography/discussions)
- **Documentation**:
  - [CLAUDE.md](CLAUDE.md) - Detailed technical documentation for development
  - [DOCKER_SECURITY.md](DOCKER_SECURITY.md) - Container security best practices
  - [DOCKERFILE_STANDARDS.md](DOCKERFILE_STANDARDS.md) - Dockerfile implementation standards
