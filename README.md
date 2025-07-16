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

> A modern Python 3.13+ microservices system for processing [Discogs](https://www.discogs.com/) database exports into multiple storage backends.

Transform the entire Discogs music database into queryable graph and relational databases. This system downloads monthly data dumps from Discogs, efficiently parses XML files, and stores the data in both Neo4j (graph database) and PostgreSQL (relational database) for different query patterns and use cases.

## Overview

Discogsography consists of four microservices that work together to process and monitor the complete Discogs database:

1. **Dashboard** - Real-time monitoring dashboard with WebSocket updates for all services
1. **Extractor** - Downloads Discogs XML dumps from S3, validates checksums, parses XML to JSON, and publishes to message queues
1. **Graphinator** - Consumes messages and builds a graph database in Neo4j with relationships between artists, labels, releases, and masters
1. **Tableinator** - Consumes messages and stores denormalized data in PostgreSQL for fast queries and full-text search

### Architecture

```mermaid
graph TD
    S3[("Discogs S3<br/>Data Dumps")]
    EXT[["Extractor<br/>(XML → JSON)"]]
    RMQ{{"RabbitMQ<br/>Message Queue"}}
    NEO4J[(Neo4j<br/>Graph DB)]
    PG[(PostgreSQL<br/>Relational DB)]
    GRAPH[["Graphinator"]]
    TABLE[["Tableinator"]]
    DASH[["Dashboard<br/>(Monitoring)"]]

    S3 -->|Download & Parse| EXT
    EXT -->|Publish Messages| RMQ
    RMQ -->|Consume| GRAPH
    RMQ -->|Consume| TABLE
    GRAPH -->|Store| NEO4J
    TABLE -->|Store| PG

    DASH -.->|Monitor| EXT
    DASH -.->|Monitor| GRAPH
    DASH -.->|Monitor| TABLE
    DASH -.->|Query Stats| RMQ
    DASH -.->|Query Stats| NEO4J
    DASH -.->|Query Stats| PG

    style S3 fill:#e1f5fe
    style RMQ fill:#fff3e0
    style NEO4J fill:#f3e5f5
    style PG fill:#e8f5e9
    style DASH fill:#fce4ec
```

### Key Features

- 🔄 **Automatic Updates**: Periodic checking for new Discogs data releases (configurable interval, default 15 days)
- ⚡ **Efficient Processing**: Hash-based deduplication to avoid reprocessing unchanged records
- 🚀 **High Performance**: Multi-threaded XML parsing and concurrent message processing
- 🛡️ **Fault Tolerance**: Message acknowledgment, automatic retries, and graceful shutdown
- 📊 **Progress Tracking**: Real-time progress monitoring with detailed statistics
- 🐋 **Production-Ready Docker**: Full Docker Compose setup with security hardening
- 🔒 **Type Safety**: Comprehensive type hints and strict mypy validation
- 🔐 **Security First**: Bandit scanning, secure coding practices, and container hardening

### Documentation

- 📖 **[CLAUDE.md](CLAUDE.md)** - Detailed technical documentation for development
- 🤖 **[Task Automation](docs/task-automation.md)** - Taskipy commands and workflows
- 🔒 **[Docker Security](docs/docker-security.md)** - Container security best practices
- 🏗️ **[Dockerfile Standards](docs/dockerfile-standards.md)** - Dockerfile implementation standards

## 🚀 Quick Start

### Prerequisites

- **Python**: 3.13+ ([Install with uv](https://github.com/astral-sh/uv))
- **Docker**: Docker Desktop or Docker Engine with Compose
- **Storage**: ~100GB free disk space for Discogs data
- **Memory**: 8GB+ RAM recommended
- **Network**: Stable internet for initial download (~50GB)

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

   | Service | URL/Connection | Credentials |
   |---------|----------------|-------------|
   | 📊 **Dashboard** | http://localhost:8003 | No auth required |
   | 🐰 **RabbitMQ** | http://localhost:15672 | discogsography / discogsography |
   | 🔗 **Neo4j Browser** | http://localhost:7474 | neo4j / discogsography |
   | 🐘 **PostgreSQL** | localhost:5432 | discogsography / discogsography |

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

## ⚙️ Configuration

### Environment Variables

All services are configured via environment variables. Copy `.env.example` to `.env` and customize as needed:

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

### 💿 Data Volume

The complete Discogs dataset includes:

| Data Type | Count | Storage |
|-----------|-------|---------|
| 📀 Releases | ~15 million | ~40GB |
| 🎤 Artists | ~2 million | ~5GB |
| 🎵 Masters | ~2 million | ~3GB |
| 🏢 Labels | ~1.5 million | ~2GB |

**Total Requirements:**

- 📥 **Download**: ~50GB compressed XML files
- 💾 **Storage**: ~100GB for extracted data
- ⏱️ **Processing**: 2-6 hours (varies by hardware)

## 📊 Usage Examples

### 🔗 Neo4j Graph Queries

Explore complex relationships in the music industry:

#### Find all albums by an artist

```cypher
MATCH (a:Artist {name: "Pink Floyd"})-[:BY]-(r:Release)
RETURN r.title, r.year
ORDER BY r.year
LIMIT 10
```

#### Discover band members

```cypher
MATCH (member:Artist)-[:MEMBER_OF]->(band:Artist {name: "The Beatles"})
RETURN member.name, member.real_name
```

#### Explore label catalogs

```cypher
MATCH (r:Release)-[:ON]->(l:Label {name: "Blue Note"})
WHERE r.year >= 1950 AND r.year <= 1970
RETURN r.title, r.artist, r.year
ORDER BY r.year
```

#### Find artist collaborations

```cypher
MATCH (a1:Artist {name: "Miles Davis"})-[:COLLABORATED_WITH]-(a2:Artist)
RETURN DISTINCT a2.name
ORDER BY a2.name
```

### 🐘 PostgreSQL Queries

Fast structured queries on denormalized data:

#### Full-text search releases

```sql
SELECT
    data->>'title' as title,
    data->>'artist' as artist,
    data->>'year' as year
FROM releases
WHERE data->>'title' ILIKE '%dark side%'
ORDER BY (data->>'year')::int DESC
LIMIT 10;
```

#### Artist discography

```sql
SELECT
    data->>'title' as title,
    data->>'year' as year,
    data->'genres' as genres
FROM releases
WHERE data->>'artist' = 'Miles Davis'
AND (data->>'year')::int BETWEEN 1950 AND 1960
ORDER BY (data->>'year')::int;
```

#### Genre statistics

```sql
SELECT
    genre,
    COUNT(*) as release_count,
    MIN((data->>'year')::int) as first_release,
    MAX((data->>'year')::int) as last_release
FROM releases,
     jsonb_array_elements_text(data->'genres') as genre
GROUP BY genre
ORDER BY release_count DESC
LIMIT 20;
```

## 📈 Monitoring & Operations

### 📊 Dashboard

Access the real-time monitoring dashboard at http://localhost:8003:

- **Service Health**: Live status of all microservices
- **Queue Metrics**: Message rates, depths, and consumer counts
- **Database Stats**: Connection pools and storage usage
- **Activity Log**: Recent system events and processing updates
- **WebSocket Updates**: Real-time data without page refresh

### 🔍 Debug Utilities

Monitor and debug your system with built-in tools:

```bash
# Check service logs for errors
uv run task check-errors

# Monitor RabbitMQ queues in real-time
uv run task monitor

# Comprehensive system health dashboard
uv run task system-monitor

# View logs for all services
uv run task logs
```

### 📊 Metrics

Each service provides detailed telemetry:

- **Processing Rates**: Records/second for each data type
- **Queue Health**: Depth, consumer count, throughput
- **Error Tracking**: Failed messages, retry counts
- **Performance**: Processing time, memory usage
- **Stall Detection**: Alerts when processing stops

## 👨‍💻 Development

### 🛠️ Modern Python Stack

The project leverages cutting-edge Python tooling:

| Tool | Purpose | Configuration |
|------|---------|---------------|
| **[uv](https://github.com/astral-sh/uv)** | 10-100x faster package management | `pyproject.toml` |
| **[ruff](https://github.com/astral-sh/ruff)** | Lightning-fast linting & formatting | `pyproject.toml` |
| **[mypy](http://mypy-lang.org/)** | Strict static type checking | `pyproject.toml` |
| **[bandit](https://github.com/PyCQA/bandit)** | Security vulnerability scanning | `pyproject.toml` |
| **[pre-commit](https://pre-commit.com/)** | Git hooks for code quality | `.pre-commit-config.yaml` |

### 🧪 Testing

Comprehensive test coverage with multiple test types:

```bash
# Run all tests (excluding E2E)
uv run task test

# Run with coverage report
uv run task test-cov

# Run specific test suites
uv run pytest tests/extractor/      # Extractor tests
uv run pytest tests/graphinator/    # Graphinator tests
uv run pytest tests/tableinator/    # Tableinator tests
uv run pytest tests/dashboard/      # Dashboard tests
```

#### 🎭 E2E Testing with Playwright

```bash
# One-time browser setup
uv run playwright install chromium
uv run playwright install-deps chromium

# Run E2E tests (automatic server management)
uv run task test-e2e

# Run with specific browser
uv run pytest tests/dashboard/test_dashboard_ui.py -m e2e --browser firefox
```

### 🔧 Development Workflow

```bash
# Setup development environment
uv sync --all-extras
uv run task init  # Install pre-commit hooks

# Before committing
uv run task lint     # Run linting
uv run task format   # Format code
uv run task test     # Run tests
uv run task security # Security scan

# Or run everything at once
uv run pre-commit run --all-files
```

### 📁 Project Structure

```
discogsography/
├── 📦 common/              # Shared utilities and configuration
│   ├── config.py           # Centralized configuration management
│   └── health_server.py    # Health check endpoint server
├── 📊 dashboard/           # Real-time monitoring dashboard
│   ├── dashboard.py        # FastAPI backend with WebSocket
│   └── static/             # Frontend HTML/CSS/JS
├── 📥 extractor/           # Discogs data ingestion service
│   ├── extractor.py        # Main processing logic
│   └── discogs.py          # S3 download and validation
├── 🔗 graphinator/         # Neo4j graph database service
│   └── graphinator.py      # Graph relationship builder
├── 🐘 tableinator/         # PostgreSQL storage service
│   └── tableinator.py      # Relational data management
├── 🔧 utilities/           # Operational tools
│   ├── check_errors.py     # Log analysis
│   ├── monitor_queues.py   # Real-time queue monitoring
│   └── system_monitor.py   # System health dashboard
├── 🧪 tests/               # Comprehensive test suite
├── 📝 docs/                # Additional documentation
├── 🐋 docker-compose.yml   # Container orchestration
└── 📦 pyproject.toml       # Project configuration
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
| 🐰 | RabbitMQ connections | `logger.info("🐰 Connected to RabbitMQ")` |
| 🔗 | Neo4j connections | `logger.info("🔗 Connected to Neo4j")` |
| 🐘 | PostgreSQL operations | `logger.info("🐘 Connected to PostgreSQL")` |
| 💾 | Database save operations | `logger.info("💾 Updated artist ID=123 in Neo4j")` |
| 🏥 | Health server | `logger.info("🏥 Health server started on port 8001")` |
| ⏩ | Skipping operations | `logger.info("⏩ Skipped artist ID=123 (no changes)")` |

### Example Usage

```python
logger.info("🚀 Starting Discogs data extractor")
logger.error("❌ Failed to connect to Neo4j: connection refused")
logger.warning("⚠️ Slow consumer detected, processing delayed")
logger.info("✅ All files processed successfully")
```

## 🗄️ Data Schema

### 🔗 Neo4j Graph Model

The graph database models complex music industry relationships:

#### Node Types

| Node | Description | Key Properties |
|------|-------------|----------------|
| `Artist` | Musicians, bands, producers | id, name, real_name, profile |
| `Label` | Record labels and imprints | id, name, profile, parent_label |
| `Master` | Master recordings | id, title, year, main_release |
| `Release` | Physical/digital releases | id, title, year, country, format |
| `Genre` | Musical genres | name |
| `Style` | Sub-genres and styles | name |

#### Relationships

```
🎤 Artist Relationships:
├── MEMBER_OF ──────→ Artist (band membership)
├── ALIAS_OF ───────→ Artist (alternative names)
├── COLLABORATED_WITH → Artist (collaborations)
└── PERFORMED_ON ───→ Release (credits)

📀 Release Relationships:
├── BY ────────────→ Artist (performer credits)
├── ON ────────────→ Label (release label)
├── DERIVED_FROM ──→ Master (master recording)
├── IS ────────────→ Genre (genre classification)
└── IS ────────────→ Style (style classification)

🏢 Label Relationships:
└── SUBLABEL_OF ───→ Label (parent/child labels)

🎵 Classification:
└── Style -[:PART_OF]→ Genre (hierarchy)
```

### 🐘 PostgreSQL Schema

Optimized for fast queries and full-text search:

```sql
-- Artists table with JSONB for flexible schema
CREATE TABLE artists (
    data_id VARCHAR PRIMARY KEY,
    hash VARCHAR NOT NULL UNIQUE,
    data JSONB NOT NULL
);
CREATE INDEX idx_artists_name ON artists ((data->>'name'));
CREATE INDEX idx_artists_gin ON artists USING GIN (data);

-- Labels table
CREATE TABLE labels (
    data_id VARCHAR PRIMARY KEY,
    hash VARCHAR NOT NULL UNIQUE,
    data JSONB NOT NULL
);
CREATE INDEX idx_labels_name ON labels ((data->>'name'));

-- Masters table
CREATE TABLE masters (
    data_id VARCHAR PRIMARY KEY,
    hash VARCHAR NOT NULL UNIQUE,
    data JSONB NOT NULL
);
CREATE INDEX idx_masters_title ON masters ((data->>'title'));
CREATE INDEX idx_masters_year ON masters ((data->>'year'));

-- Releases table with extensive indexing
CREATE TABLE releases (
    data_id VARCHAR PRIMARY KEY,
    hash VARCHAR NOT NULL UNIQUE,
    data JSONB NOT NULL
);
CREATE INDEX idx_releases_title ON releases ((data->>'title'));
CREATE INDEX idx_releases_artist ON releases ((data->>'artist'));
CREATE INDEX idx_releases_year ON releases ((data->>'year'));
CREATE INDEX idx_releases_gin ON releases USING GIN (data);
```

## ⚡ Performance & Optimization

### 📊 Processing Speed

Typical processing rates on modern hardware:

| Service | Records/Second | Bottleneck |
|---------|----------------|------------|
| 📥 **Extractor** | 5,000-10,000 | XML parsing, I/O |
| 🔗 **Graphinator** | 1,000-2,000 | Neo4j transactions |
| 🐘 **Tableinator** | 3,000-5,000 | PostgreSQL inserts |

### 💻 Hardware Requirements

#### Minimum Specifications

- **CPU**: 4 cores
- **RAM**: 8GB
- **Storage**: 200GB HDD
- **Network**: 10 Mbps

#### Recommended Specifications

- **CPU**: 8+ cores
- **RAM**: 16GB+
- **Storage**: 200GB+ SSD (NVMe preferred)
- **Network**: 100 Mbps+

### 🚀 Optimization Guide

#### Database Tuning

**Neo4j Configuration:**

```properties
# neo4j.conf
dbms.memory.heap.initial_size=4g
dbms.memory.heap.max_size=4g
dbms.memory.pagecache.size=2g
```

**PostgreSQL Configuration:**

```sql
-- postgresql.conf
shared_buffers = 4GB
work_mem = 256MB
maintenance_work_mem = 1GB
effective_cache_size = 12GB
```

#### Message Queue Optimization

```yaml
# RabbitMQ prefetch for consumers
PREFETCH_COUNT: 100  # Adjust based on processing speed
```

#### Storage Performance

- Use SSD/NVMe for `/discogs-data` directory
- Enable compression for PostgreSQL tables
- Configure Neo4j for SSD optimization
- Use separate disks for databases if possible

## 🔧 Troubleshooting

### ❌ Common Issues & Solutions

#### Extractor Download Failures

```bash
# Check connectivity
curl -I https://discogs-data-dumps.s3.us-west-2.amazonaws.com

# Verify disk space
df -h /discogs-data

# Check permissions
ls -la /discogs-data
```

**Solutions:**

- ✅ Ensure internet connectivity
- ✅ Verify 100GB+ free space
- ✅ Check directory permissions

#### RabbitMQ Connection Issues

```bash
# Check RabbitMQ status
docker-compose ps rabbitmq
docker-compose logs rabbitmq

# Test connection
curl -u discogsography:discogsography http://localhost:15672/api/overview
```

**Solutions:**

- ✅ Wait for RabbitMQ startup (30-60s)
- ✅ Check firewall settings
- ✅ Verify credentials in `.env`

#### Database Connection Errors

**Neo4j:**

```bash
# Check Neo4j status
docker-compose logs neo4j
curl http://localhost:7474

# Test bolt connection
echo "MATCH (n) RETURN count(n);" | cypher-shell -u neo4j -p discogsography
```

**PostgreSQL:**

```bash
# Check PostgreSQL status
docker-compose logs postgres

# Test connection
PGPASSWORD=discogsography psql -h localhost -U discogsography -d discogsography -c "SELECT 1;"
```

### 🐛 Debugging Guide

1. **📋 Check Service Health**

   ```bash
   curl http://localhost:8000/health  # Extractor
   curl http://localhost:8001/health  # Graphinator
   curl http://localhost:8002/health  # Tableinator
   curl http://localhost:8003/health  # Dashboard
   ```

1. **📊 Monitor Real-time Logs**

   ```bash
   # All services
   uv run task logs

   # Specific service
   docker-compose logs -f extractor
   ```

1. **🔍 Analyze Errors**

   ```bash
   # Check for errors across all services
   uv run task check-errors

   # Monitor queue health
   uv run task monitor
   ```

1. **🗄️ Verify Data Storage**

   ```cypher
   -- Neo4j: Check node counts
   MATCH (n) RETURN labels(n)[0] as type, count(n) as count;
   ```

   ```sql
   -- PostgreSQL: Check table counts
   SELECT 'artists' as table_name, COUNT(*) FROM artists
   UNION ALL
   SELECT 'releases', COUNT(*) FROM releases
   UNION ALL
   SELECT 'labels', COUNT(*) FROM labels
   UNION ALL
   SELECT 'masters', COUNT(*) FROM masters;
   ```

## 🤝 Contributing

We welcome contributions! Please follow these guidelines:

### 📋 Contribution Process

1. **Fork & Clone**

   ```bash
   git clone https://github.com/YOUR_USERNAME/discogsography.git
   cd discogsography
   ```

1. **Setup Development Environment**

   ```bash
   uv sync --all-extras
   uv run task init  # Install pre-commit hooks
   ```

1. **Create Feature Branch**

   ```bash
   git checkout -b feature/amazing-feature
   ```

1. **Make Changes**

   - Write clean, documented code
   - Add comprehensive tests
   - Update relevant documentation

1. **Validate Changes**

   ```bash
   uv run task lint      # Fix any linting issues
   uv run task test      # Ensure tests pass
   uv run task security  # Check for vulnerabilities
   ```

1. **Commit with Conventional Commits**

   ```bash
   git commit -m "feat: add amazing feature"
   # Types: feat, fix, docs, style, refactor, test, chore
   ```

1. **Push & Create PR**

   ```bash
   git push origin feature/amazing-feature
   ```

### 📝 Development Standards

- **Code Style**: Follow ruff and black formatting
- **Type Hints**: Required for all functions
- **Tests**: Maintain >80% coverage
- **Docs**: Update README and docstrings
- **Logging**: Use emoji conventions (see above)
- **Security**: Pass bandit checks

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- 🎵 [Discogs](https://www.discogs.com/) for providing the monthly data dumps
- 🐍 The Python community for excellent libraries and tools
- 🌟 All contributors who help improve this project
- 🚀 [uv](https://github.com/astral-sh/uv) for blazing-fast package management
- 🔥 [Ruff](https://github.com/astral-sh/ruff) for lightning-fast linting

## 💬 Support & Community

### Get Help

- 🐛 **Bug Reports**: [GitHub Issues](https://github.com/SimplicityGuy/discogsography/issues)
- 💡 **Feature Requests**: [GitHub Discussions](https://github.com/SimplicityGuy/discogsography/discussions)
- 💬 **Questions**: [Discussions Q&A](https://github.com/SimplicityGuy/discogsography/discussions/categories/q-a)

### Documentation

- 📖 **[CLAUDE.md](CLAUDE.md)** - Detailed technical documentation
- 🤖 **[Task Automation](docs/task-automation.md)** - Available tasks and workflows
- 🔒 **[Docker Security](docs/docker-security.md)** - Security best practices
- 🏗️ **[Dockerfile Standards](docs/dockerfile-standards.md)** - Container standards
- 📦 **[Service READMEs](/)** - Individual service documentation

### Project Status

This project is actively maintained. We welcome contributions, bug reports, and feature requests!

______________________________________________________________________

<div align="center">
Made with ❤️ by the Discogsography community
</div>
