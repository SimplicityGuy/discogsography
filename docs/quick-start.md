# 🚀 Quick Start Guide

<div align="center">

**Get Discogsography up and running in minutes**

[🏠 Back to Main](../README.md) | [📚 Documentation Index](README.md) | [🏛️ Architecture](architecture.md)

</div>

## Overview

This guide will help you get Discogsography running quickly, whether you're using Docker Compose for a simple setup or setting up a local development environment.

## ✅ Prerequisites

### System Requirements

| Requirement | Minimum | Recommended | Notes                                             |
| ----------- | ------- | ----------- | ------------------------------------------------- |
| **Python**  | 3.13+   | Latest      | Install via [uv](https://github.com/astral-sh/uv) |
| **Docker**  | 20.10+  | Latest      | With Docker Compose v2                            |
| **Storage** | 100GB   | 200GB SSD   | For data + processing                             |
| **Memory**  | 8GB     | 16GB+       | More RAM = faster processing                      |
| **Network** | 10 Mbps | 100 Mbps+   | Initial download ~50GB                            |

### Required Software

**For Docker Compose Setup**:

- Docker Engine 20.10+
- Docker Compose v2

**For Local Development**:

- Python 3.13+
- [uv](https://github.com/astral-sh/uv) package manager
- [just](https://just.systems/) task runner (optional but recommended)
- Rust toolchain (only if developing Rust Extractor)

## 🐳 Docker Compose Setup (Recommended)

The fastest way to get started is using Docker Compose, which handles all service dependencies automatically.

### Step 1: Clone the Repository

```bash
git clone https://github.com/SimplicityGuy/discogsography.git
cd discogsography
```

### Step 2: Configure Environment (Optional)

The project includes sensible defaults, but you can customize settings:

```bash
# Copy the example environment file
cp .env.example .env

# Edit .env to customize (optional)
nano .env
```

See [Configuration Guide](configuration.md) for all available settings.

### Step 3: Start All Services

```bash
# Start all services with Python Extractor (default)
docker-compose up -d

# View logs to monitor progress
docker-compose logs -f
```

### Step 4: (Optional) Use Rust Extractor

For significantly better performance, switch to the Rust-based extractor:

```bash
# Switch to Rust Extractor (20,000-400,000+ records/sec)
./scripts/switch-extractor.sh rust

# Switch back to Python Extractor if needed
./scripts/switch-extractor.sh python
```

### Step 5: Access the Services

Open your browser and visit:

- **Dashboard**: http://localhost:8003 (System monitoring)
- **Discovery**: http://localhost:8005 (AI music discovery)
- **Neo4j Browser**: http://localhost:7474 (Graph exploration)
- **RabbitMQ Management**: http://localhost:15672 (Queue monitoring)

### Service Access Details

| Service           | URL                    | Default Credentials                 | Purpose               |
| ----------------- | ---------------------- | ----------------------------------- | --------------------- |
| 📊 **Dashboard**  | http://localhost:8003  | None                                | System monitoring     |
| 🎵 **Discovery**  | http://localhost:8005  | None                                | AI music discovery    |
| 🔍 **Explore**    | http://localhost:8006  | None                                | Graph exploration     |
| 🐰 **RabbitMQ**   | http://localhost:15672 | `discogsography` / `discogsography` | Queue management      |
| 🔗 **Neo4j**      | http://localhost:7474  | `neo4j` / `discogsography`          | Graph database UI     |
| 🐘 **PostgreSQL** | `localhost:5433`       | `discogsography` / `discogsography` | Database access       |

## 💻 Local Development Setup

For development, you'll want to run services locally with hot-reload capabilities.

### Step 1: Install uv Package Manager

uv is 10-100x faster than pip for package management:

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# Verify installation
uv --version
```

### Step 2: Install just Task Runner (Optional)

just provides convenient task aliases:

```bash
# macOS
brew install just

# Linux (with cargo)
cargo install just

# Or use the installer script
curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh | bash

# Verify installation
just --version
```

### Step 3: Install Dependencies

```bash
# Install all project dependencies
just install

# Or using uv directly
uv sync --all-extras
```

### Step 4: Initialize Development Environment

```bash
# Set up pre-commit hooks
just init

# Or using uv directly
uv run pre-commit install
```

### Step 5: Start Infrastructure Services

Start the required databases and message queue:

```bash
# Start only infrastructure services
docker-compose up -d neo4j postgres rabbitmq redis
```

### Step 6: Set Up Environment Variables

Create a `.env` file or export variables:

```bash
# Core connections
export AMQP_CONNECTION="amqp://guest:guest@localhost:5672/"

# Neo4j settings
export NEO4J_ADDRESS="bolt://localhost:7687"
export NEO4J_USERNAME="neo4j"
export NEO4J_PASSWORD="discogsography"

# PostgreSQL settings
export POSTGRES_ADDRESS="localhost:5433"
export POSTGRES_USERNAME="discogsography"
export POSTGRES_PASSWORD="discogsography"
export POSTGRES_DATABASE="discogsography"

# Redis settings
export REDIS_URL="redis://localhost:6379/0"

# Optional: Set log level
export LOG_LEVEL="INFO"  # or DEBUG for detailed output
```

### Step 7: Run Individual Services

Run any service using just commands:

```bash
# Dashboard (monitoring UI)
just dashboard

# Discovery (AI service)
just discovery

# Python Extractor (data ingestion)
just pyextractor

# Rust Extractor (high-performance ingestion, requires Rust)
just rustextractor-run

# Graphinator (Neo4j builder)
just graphinator

# Tableinator (PostgreSQL builder)
just tableinator
```

Or run services directly with Python:

```bash
# Dashboard
uv run python dashboard/dashboard.py

# Discovery
uv run python discovery/discovery.py

# Python Extractor
uv run python extractor/pyextractor/extractor.py

# Graphinator
uv run python graphinator/graphinator.py

# Tableinator
uv run python tableinator/tableinator.py
```

## 🎯 Verification Steps

### 1. Check Service Health

All services expose health endpoints:

```bash
# Check each service
curl http://localhost:8000/health  # Extractor (Python or Rust)
curl http://localhost:8001/health  # Graphinator
curl http://localhost:8002/health  # Tableinator
curl http://localhost:8003/health  # Dashboard
curl http://localhost:8004/health  # Discovery
```

Expected response:

```json
{"status": "healthy"}
```

### 2. Monitor Processing

Watch the logs to see data processing:

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f extractor-python  # or extractor-rust
docker-compose logs -f graphinator
docker-compose logs -f tableinator
```

Look for log messages like:

- 🚀 Service starting messages
- 📥 Download progress
- 🔄 Processing progress
- ✅ Completion messages

### 3. Check RabbitMQ Queues

Visit http://localhost:15672 and verify:

- All 4 queues are created (artists, labels, releases, masters)
- Messages are being published and consumed
- Consumer counts are appropriate

### 4. Verify Data in Databases

**Neo4j**:

```bash
# Open Neo4j Browser
open http://localhost:7474

# Run query to count nodes
MATCH (n) RETURN labels(n)[0] as type, count(n) as count
```

**PostgreSQL**:

```bash
# Connect to database
PGPASSWORD=discogsography psql -h localhost -p 5433 -U discogsography -d discogsography

# Count records
SELECT 'artists' as table_name, COUNT(*) FROM artists
UNION ALL SELECT 'labels', COUNT(*) FROM labels
UNION ALL SELECT 'releases', COUNT(*) FROM releases
UNION ALL SELECT 'masters', COUNT(*) FROM masters;
```

## 🔍 Troubleshooting Quick Fixes

### Services Won't Start

```bash
# Check if ports are already in use
netstat -an | grep -E "(5672|7474|7687|5433|6379|8003)"

# Stop and restart all services
docker-compose down
docker-compose up -d
```

### Out of Disk Space

```bash
# Check available space
df -h

# Clean up Docker resources
docker system prune -a
```

### Connection Refused Errors

```bash
# Wait for services to fully start
docker-compose ps

# Check service logs
docker-compose logs [service-name]

# Restart specific service
docker-compose restart [service-name]
```

### Python/Rust Extractor Not Downloading Data

```bash
# Check internet connectivity
curl -I https://discogs-data-dumps.s3.us-west-2.amazonaws.com

# Check extractor logs
docker-compose logs extractor-python  # or extractor-rust

# Verify DISCOGS_ROOT permissions
ls -la /discogs-data  # or your configured path
```

For more detailed troubleshooting, see the [Troubleshooting Guide](troubleshooting.md).

## 🎓 Next Steps

Now that you have Discogsography running:

1. **Explore the Dashboard**: http://localhost:8003

   - Monitor system health
   - View processing metrics
   - Track queue depths

1. **Try Some Queries**: See [Usage Examples](usage-examples.md)

   - Neo4j graph queries
   - PostgreSQL analytics
   - Full-text search

1. **Use Discovery Service**: http://localhost:8005

   - AI-powered music recommendations
   - Semantic search
   - Industry analytics

1. **Learn the Architecture**: Read [Architecture Guide](architecture.md)

   - Understand component interactions
   - Learn about data flow
   - Explore scalability options

1. **Configure for Your Needs**: See [Configuration Guide](configuration.md)

   - Tune performance settings
   - Adjust logging levels
   - Customize data paths

## 🛠️ Development Workflow

If you're contributing to the project:

```bash
# Before making changes
just lint      # Run linters
just format    # Format code
just test      # Run tests
just security  # Security scan

# Or run everything
uv run pre-commit run --all-files
```

See [Development Guide](development.md) and [Contributing Guide](contributing.md) for more information.

## 📚 Additional Resources

- [Configuration Guide](configuration.md) - All environment variables and settings
- [Architecture Overview](architecture.md) - System design and components
- [Database Schema](database-schema.md) - Neo4j and PostgreSQL schemas
- [Monitoring Guide](monitoring.md) - Observability and debugging
- [Performance Guide](performance-guide.md) - Optimization strategies

______________________________________________________________________

**Last Updated**: 2025-01-15
