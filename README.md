# 🎵 Discogsography

<div align="center">

[![Build](https://github.com/SimplicityGuy/discogsography/actions/workflows/build.yml/badge.svg)](https://github.com/SimplicityGuy/discogsography/actions/workflows/build.yml)
[![Code Quality](https://github.com/SimplicityGuy/discogsography/actions/workflows/code-quality.yml/badge.svg)](https://github.com/SimplicityGuy/discogsography/actions/workflows/code-quality.yml)
[![Tests](https://github.com/SimplicityGuy/discogsography/actions/workflows/test.yml/badge.svg)](https://github.com/SimplicityGuy/discogsography/actions/workflows/test.yml)
[![E2E Tests](https://github.com/SimplicityGuy/discogsography/actions/workflows/e2e-test.yml/badge.svg)](https://github.com/SimplicityGuy/discogsography/actions/workflows/e2e-test.yml)
![License: MIT](https://img.shields.io/github/license/SimplicityGuy/discogsography)
![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)
[![uv](https://img.shields.io/badge/uv-package%20manager-orange?logo=python)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)
[![mypy](https://img.shields.io/badge/mypy-checked-blue)](http://mypy-lang.org/)
[![Bandit](https://img.shields.io/badge/security-bandit-yellow.svg)](https://github.com/PyCQA/bandit)
[![Docker](https://img.shields.io/badge/docker-ready-blue?logo=docker)](https://www.docker.com/)

**A modern Python 3.13+ microservices platform for transforming the complete [Discogs](https://www.discogs.com/) music database into powerful, queryable knowledge graphs and analytics engines.**

[🚀 Quick Start](#-quick-start) | [📖 Documentation](#-documentation) | [🎯 Features](#-key-features) | [💬 Community](#-support--community) | [📋 Emoji Guide](docs/emoji-guide.md)

</div>

## 🎯 What is Discogsography?

Discogsography transforms monthly Discogs data dumps (50GB+ compressed XML) into:

- **🔗 Neo4j Graph Database**: Navigate complex music industry relationships
- **🐘 PostgreSQL Database**: High-performance queries and full-text search
- **🤖 AI Discovery Engine**: Intelligent recommendations and analytics
- **📊 Real-time Dashboard**: Monitor system health and processing metrics

Perfect for music researchers, data scientists, developers, and music enthusiasts who want to explore the world's largest music database.

## 🏛️ Architecture Overview

### ⚙️ Core Services

| Service | Purpose | Key Technologies |
|---------|---------|------------------|
| **[📥](docs/emoji-guide.md#service-identifiers) Extractor** | Downloads & processes Discogs XML dumps | `asyncio`, `orjson`, `aio-pika` |
| **[🔗](docs/emoji-guide.md#service-identifiers) Graphinator** | Builds Neo4j knowledge graphs | `neo4j-driver`, graph algorithms |
| **[🐘](docs/emoji-guide.md#service-identifiers) Tableinator** | Creates PostgreSQL analytics tables | `psycopg3`, JSONB, full-text search |
| **[🎵](docs/emoji-guide.md#service-identifiers) Discovery** | AI-powered music intelligence | `sentence-transformers`, `plotly`, `networkx` |
| **[📊](docs/emoji-guide.md#service-identifiers) Dashboard** | Real-time system monitoring | `FastAPI`, WebSocket, reactive UI |

### 📐 System Architecture

```mermaid
graph TD
    S3[("🌐 Discogs S3<br/>Monthly Data Dumps<br/>~50GB XML")]
    EXT[["📥 Extractor<br/>XML → JSON<br/>Deduplication"]]
    RMQ{{"🐰 RabbitMQ<br/>Message Broker<br/>4 Queues"}}
    NEO4J[(🔗 Neo4j<br/>Graph Database<br/>Relationships")]
    PG[(🐘 PostgreSQL<br/>Analytics DB<br/>Full-text Search")]
    GRAPH[["🔗 Graphinator<br/>Graph Builder"]]
    TABLE[["🐘 Tableinator<br/>Table Builder"]]
    DASH[["📊 Dashboard<br/>Real-time Monitor<br/>WebSocket"]]
    DISCO[["🎵 Discovery<br/>AI Engine<br/>ML Models"]]

    S3 -->|1. Download & Parse| EXT
    EXT -->|2. Publish Messages| RMQ
    RMQ -->|3a. Artists/Labels/Releases/Masters| GRAPH
    RMQ -->|3b. Artists/Labels/Releases/Masters| TABLE
    GRAPH -->|4a. Build Graph| NEO4J
    TABLE -->|4b. Store Data| PG

    DISCO -.->|Query| NEO4J
    DISCO -.->|Query| PG
    DISCO -.->|Analyze| DISCO

    DASH -.->|Monitor| EXT
    DASH -.->|Monitor| GRAPH
    DASH -.->|Monitor| TABLE
    DASH -.->|Monitor| DISCO
    DASH -.->|Stats| RMQ
    DASH -.->|Stats| NEO4J
    DASH -.->|Stats| PG

    style S3 fill:#e1f5fe,stroke:#01579b,stroke-width:2px
    style RMQ fill:#fff3e0,stroke:#e65100,stroke-width:2px
    style NEO4J fill:#f3e5f5,stroke:#4a148c,stroke-width:2px
    style PG fill:#e8f5e9,stroke:#1b5e20,stroke-width:2px
    style DASH fill:#fce4ec,stroke:#880e4f,stroke-width:2px
    style DISCO fill:#e3f2fd,stroke:#0d47a1,stroke-width:2px
```

## 🌟 Key Features

### 🚀 Performance & Scale

- **⚡ High-Speed Processing**: 5,000-10,000 records/second XML parsing
- **🔄 Smart Deduplication**: SHA256 hash-based change detection prevents reprocessing
- **📈 Handles Big Data**: Processes 15M+ releases, 2M+ artists efficiently
- **🎯 Concurrent Processing**: Multi-threaded parsing with async message handling

### 🛡️ Reliability & Operations

- **🔁 Auto-Recovery**: Automatic retries with exponential backoff
- **💾 Message Durability**: RabbitMQ persistence with dead letter queues
- **🏥 Health Monitoring**: HTTP health checks for all services
- **📊 Real-time Metrics**: WebSocket dashboard with live updates

### 🔒 Security & Quality

- **🐋 Container Security**: Non-root users, read-only filesystems, dropped capabilities
- **🔐 Code Security**: Bandit scanning, secure defaults, parameterized queries
- **📝 Type Safety**: Full type hints with strict mypy validation
- **✅ Comprehensive Testing**: Unit, integration, and E2E tests with Playwright

### 🤖 AI & Analytics

- **🧠 ML-Powered Discovery**: Semantic search using sentence transformers
- **📊 Industry Analytics**: Genre trends, label insights, market analysis
- **🔍 Graph Algorithms**: PageRank, community detection, path finding
- **🎨 Interactive Visualizations**: Plotly charts, vis.js network graphs

## 📖 Documentation

| Document | Purpose |
|----------|---------|
| **[CLAUDE.md](CLAUDE.md)** | 🤖 Claude Code integration guide & development standards |
| **[Task Automation](docs/task-automation.md)** | 🚀 Complete taskipy command reference |
| **[Docker Security](docs/docker-security.md)** | 🔒 Container hardening & security practices |
| **[Dockerfile Standards](docs/dockerfile-standards.md)** | 🏗️ Best practices for writing Dockerfiles |
| **Service Guides** | 📚 Individual README for each service |

## 🚀 Quick Start

### ✅ Prerequisites

| Requirement | Minimum | Recommended | Notes |
|-------------|---------|-------------|--------|
| **Python** | 3.13+ | Latest | Install via [uv](https://github.com/astral-sh/uv) |
| **Docker** | 20.10+ | Latest | With Docker Compose v2 |
| **Storage** | 100GB | 200GB SSD | For data + processing |
| **Memory** | 8GB | 16GB+ | More RAM = faster processing |
| **Network** | 10 Mbps | 100 Mbps+ | Initial download ~50GB |

### 🐳 Using Docker Compose (Recommended)

```bash
# 1. Clone and navigate to the repository
git clone https://github.com/SimplicityGuy/discogsography.git
cd discogsography

# 2. Copy environment template (optional - has sensible defaults)
cp .env.example .env

# 3. Start all services
docker-compose up -d

# 4. Watch the magic happen!
docker-compose logs -f

# 5. Access the dashboard
open http://localhost:8003
```

### 🌐 Service Access

| Service | URL | Default Credentials | Purpose |
|---------|-----|---------------------|---------|
| 📊 **Dashboard** | http://localhost:8003 | None | System monitoring |
| 🎵 **Discovery** | http://localhost:8005 | None | AI music discovery |
| 🐰 **RabbitMQ** | http://localhost:15672 | `discogsography` / `discogsography` | Queue management |
| 🔗 **Neo4j** | http://localhost:7474 | `neo4j` / `discogsography` | Graph exploration |
| 🐘 **PostgreSQL** | `localhost:5433` | `discogsography` / `discogsography` | Database access |

### 💻 Local Development

#### Quick Setup

```bash
# 1. Install uv (10-100x faster than pip)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Install all dependencies
uv sync --all-extras

# 3. Set up pre-commit hooks
uv run task init

# 4. Run any service
uv run task dashboard    # Monitoring UI
uv run task discovery    # AI discovery
uv run task extractor    # Data ingestion
uv run task graphinator  # Neo4j builder
uv run task tableinator  # PostgreSQL builder
```

#### Environment Setup

Create a `.env` file or export variables:

```bash
# Core connections
export AMQP_CONNECTION="amqp://guest:guest@localhost:5672/"

# Neo4j settings
export NEO4J_ADDRESS="bolt://localhost:7687"
export NEO4J_USERNAME="neo4j"
export NEO4J_PASSWORD="password"

# PostgreSQL settings
export POSTGRES_ADDRESS="localhost:5433"
export POSTGRES_USERNAME="postgres"
export POSTGRES_PASSWORD="password"
export POSTGRES_DATABASE="discogsography"
```

## ⚙️ Configuration

### 🔧 Environment Variables

All configuration is managed through environment variables. Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

#### Core Settings

| Variable | Description | Default | Used By |
|----------|-------------|---------|---------|
| `AMQP_CONNECTION` | RabbitMQ URL | `amqp://guest:guest@localhost:5672/` | All services |
| `DISCOGS_ROOT` | Data storage path | `/discogs-data` | Extractor |
| `PERIODIC_CHECK_DAYS` | Update check interval | `15` | Extractor |
| `PYTHON_VERSION` | Python version for builds | `3.13` | Docker, CI/CD |

#### Database Connections

| Variable | Description | Default | Used By |
|----------|-------------|---------|---------|
| `NEO4J_ADDRESS` | Neo4j bolt URL | `bolt://localhost:7687` | Graphinator, Dashboard, Discovery |
| `NEO4J_USERNAME` | Neo4j username | `neo4j` | Graphinator, Dashboard, Discovery |
| `NEO4J_PASSWORD` | Neo4j password | Required | Graphinator, Dashboard, Discovery |
| `POSTGRES_ADDRESS` | PostgreSQL host:port | `localhost:5432` | Tableinator, Dashboard, Discovery |
| `POSTGRES_USERNAME` | PostgreSQL username | `postgres` | Tableinator, Dashboard, Discovery |
| `POSTGRES_PASSWORD` | PostgreSQL password | Required | Tableinator, Dashboard, Discovery |
| `POSTGRES_DATABASE` | Database name | `discogsography` | Tableinator, Dashboard, Discovery |

### 💿 Dataset Scale

<div align="center">

| Data Type | Record Count | XML Size | Processing Time |
|:---------:|:------------:|:--------:|:---------------:|
| [📀](docs/emoji-guide.md#music-domain) **Releases** | ~15 million | ~40GB | 1-3 hours |
| [🎤](docs/emoji-guide.md#music-domain) **Artists** | ~2 million | ~5GB | 15-30 mins |
| [🎵](docs/emoji-guide.md#music-domain) **Masters** | ~2 million | ~3GB | 10-20 mins |
| 🏢 **Labels** | ~1.5 million | ~2GB | 10-15 mins |

**📊 Total: ~20 million records • 50GB compressed • 100GB processed**

</div>

## 💡 Usage Examples

Once your data is loaded, explore the music universe through powerful queries and AI-driven insights.

### 🔗 Neo4j Graph Queries

Navigate the interconnected world of music with Cypher queries:

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
   curl http://localhost:8004/health  # Discovery
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

## 🔧 Maintenance

### Package Upgrades

Keep dependencies up-to-date with the provided upgrade script:

```bash
# Safely upgrade all dependencies (minor/patch versions)
./scripts/upgrade-packages.sh

# Preview what would be upgraded
./scripts/upgrade-packages.sh --dry-run

# Include major version upgrades
./scripts/upgrade-packages.sh --major
```

The script includes:

- 🔒 Automatic backups before upgrades
- ✅ Git safety checks (requires clean working directory)
- 🧪 Automatic testing after upgrades
- 📦 Comprehensive dependency management across all services

See [scripts/README.md](scripts/README.md) for more maintenance scripts.

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
