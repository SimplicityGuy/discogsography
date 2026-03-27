# 🎵 Discogsography

<div align="center">

[![Build](https://github.com/SimplicityGuy/discogsography/actions/workflows/build.yml/badge.svg)](https://github.com/SimplicityGuy/discogsography/actions/workflows/build.yml)
[![Code Quality](https://github.com/SimplicityGuy/discogsography/actions/workflows/code-quality.yml/badge.svg)](https://github.com/SimplicityGuy/discogsography/actions/workflows/code-quality.yml)
[![Tests](https://github.com/SimplicityGuy/discogsography/actions/workflows/test.yml/badge.svg)](https://github.com/SimplicityGuy/discogsography/actions/workflows/test.yml)
[![E2E Tests](https://github.com/SimplicityGuy/discogsography/actions/workflows/e2e-test.yml/badge.svg)](https://github.com/SimplicityGuy/discogsography/actions/workflows/e2e-test.yml)
[![codecov](https://codecov.io/gh/SimplicityGuy/discogsography/branch/main/graph/badge.svg?token=K72AL2L2FY)](https://codecov.io/gh/SimplicityGuy/discogsography)
![License: MIT](https://img.shields.io/github/license/SimplicityGuy/discogsography)
![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)
![Rust](https://img.shields.io/badge/rust-stable-orange.svg)
[![uv](https://img.shields.io/badge/uv-package%20manager-orange?logo=python)](https://github.com/astral-sh/uv)
[![just](https://img.shields.io/badge/just-task%20runner-blue)](https://just.systems)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Cargo](https://img.shields.io/badge/cargo-rust%20package%20manager-brown)](https://doc.rust-lang.org/cargo/)
[![Clippy](https://img.shields.io/badge/clippy-rust%20linter-green)](https://github.com/rust-lang/rust-clippy)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)
[![mypy](https://img.shields.io/badge/mypy-checked-blue)](http://mypy-lang.org/)
[![Bandit](https://img.shields.io/badge/security-bandit-yellow.svg)](https://github.com/PyCQA/bandit)
[![Docker](https://img.shields.io/badge/docker-ready-blue?logo=docker)](https://www.docker.com/)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-powered-orange?logo=anthropic&logoColor=white)](https://claude.ai/code)

**A modern Python 3.13+ microservices platform for transforming the complete [Discogs](https://www.discogs.com/) music database into powerful, queryable knowledge graphs and analytics engines.**

[🚀 Quick Start](#-quick-start) | [📖 Documentation](#-documentation) | [🎯 Features](#-key-features) | [💬 Community](#-support--community)

</div>

## 🎯 What is Discogsography?

Discogsography transforms monthly Discogs data dumps (~11.3GB compressed XML) into:

- **🔗 Neo4j Graph Database**: Navigate complex music industry relationships
- **🐘 PostgreSQL Database**: High-performance queries and full-text search
- **🔍 Interactive Explorer**: Graph visualisation, trends, and path discovery
- **📊 Real-time Dashboard**: Monitor system health and processing metrics
- **🎵 MusicBrainz Enrichment**: Cross-reference with MusicBrainz for metadata, relationships, and external links

Perfect for music researchers, data scientists, developers, and music enthusiasts who want to explore the world's largest music database.

## 🏛️ Architecture Overview

### ⚙️ Core Services

| Service                                                       | Purpose                                          | Key Technologies                                             |
| ------------------------------------------------------------- | ------------------------------------------------ | ------------------------------------------------------------ |
| **[🔐](docs/emoji-guide.md#service-identifiers) API**         | User accounts, JWT auth, and collection sync     | `FastAPI`, `psycopg3`, `redis`, Discogs OAuth 1.0            |
| **[📊](docs/emoji-guide.md#service-identifiers) Dashboard**   | Real-time monitoring and admin panel             | `FastAPI`, WebSocket, reactive UI                            |
| **[🔍](docs/emoji-guide.md#service-identifiers) Explore**     | Serves graph exploration frontend (static files) | `FastAPI`, `Tailwind CSS`, `Alpine.js`, `D3.js`, `Plotly.js` |
| **[⚡](docs/emoji-guide.md#service-identifiers) Extractor**   | High-performance Rust-based extractor            | `tokio`, `quick-xml`, `lapin`                                |
| **[🔗](docs/emoji-guide.md#service-identifiers) Graphinator** | Builds Neo4j knowledge graphs                    | `neo4j-driver`, graph algorithms                             |
| **[🔧](docs/emoji-guide.md#service-identifiers) Schema-Init** | One-shot database schema initializer             | `neo4j-driver`, `psycopg3`                                   |
| **[🐘](docs/emoji-guide.md#service-identifiers) Tableinator** | Creates PostgreSQL analytics tables              | `psycopg3`, JSONB, full-text search                          |
| **[📈](docs/emoji-guide.md#service-identifiers) Insights**    | Precomputed analytics and music trends           | `FastAPI`, `psycopg3`, `httpx`                               |
| **[🤖](docs/emoji-guide.md#service-identifiers) MCP Server** | Exposes knowledge graph to AI assistants         | `FastMCP`, `httpx`                                           |

### 🎵 MusicBrainz Enrichment Services

| Service                                                              | Purpose                                                    | Key Technologies                    |
| -------------------------------------------------------------------- | ---------------------------------------------------------- | ----------------------------------- |
| **[🧠](docs/emoji-guide.md#service-identifiers) Brainzgraphinator** | Enriches Neo4j graph with MusicBrainz metadata and relationships | `neo4j-driver`, `pika`              |
| **[🧬](docs/emoji-guide.md#service-identifiers) Brainztableinator** | Populates PostgreSQL with MusicBrainz data and external links    | `psycopg3`, `pika`                  |

### 📐 System Architecture

```mermaid
graph TD
    S3[("🌐 Discogs S3<br/>Data Dumps")]
    MB[("🎵 MusicBrainz<br/>JSONL Dumps")]

    subgraph Pipeline ["Data Pipeline"]
        EXT[["⚡ Extractor"]]
        RMQ{{"🐰 RabbitMQ"}}
        GRAPH[["🔗 Graphinator"]]
        TABLE[["🐘 Tableinator"]]
    end

    subgraph MBPipeline ["MusicBrainz Enrichment"]
        BGRAPH[["🧠 Brainzgraphinator"]]
        BTABLE[["🧬 Brainztableinator"]]
    end

    subgraph Storage ["Storage"]
        NEO4J[("🔗 Neo4j")]
        PG[("🐘 PostgreSQL")]
        REDIS[("🔴 Redis")]
    end

    subgraph Services ["User-Facing Services"]
        API[["🔐 API"]]
        EXPLORE[["🔍 Explore"]]
        DASH[["📊 Dashboard"]]
        INSIGHTS[["📈 Insights"]]
    end

    S3 --> EXT --> RMQ
    MB --> EXT
    RMQ --> GRAPH --> NEO4J
    RMQ --> TABLE --> PG
    RMQ --> BGRAPH --> NEO4J
    RMQ --> BTABLE --> PG

    API --- NEO4J & PG & REDIS
    INSIGHTS --- PG & REDIS
    DASH -.- RMQ & NEO4J & PG

    style S3 fill:#e1f5fe,stroke:#01579b,stroke-width:2px
    style MB fill:#e1f5fe,stroke:#01579b,stroke-width:2px
    style EXT fill:#ffccbc,stroke:#d84315,stroke-width:2px
    style RMQ fill:#fff3e0,stroke:#e65100,stroke-width:2px
    style NEO4J fill:#f3e5f5,stroke:#4a148c,stroke-width:2px
    style PG fill:#e8f5e9,stroke:#1b5e20,stroke-width:2px
    style REDIS fill:#ffebee,stroke:#b71c1c,stroke-width:2px
    style GRAPH fill:#e0f2f1,stroke:#004d40,stroke-width:2px
    style TABLE fill:#fce4ec,stroke:#880e4f,stroke-width:2px
    style BGRAPH fill:#e0f2f1,stroke:#004d40,stroke-width:2px
    style BTABLE fill:#fce4ec,stroke:#880e4f,stroke-width:2px
    style API fill:#e3f2fd,stroke:#0d47a1,stroke-width:2px
    style EXPLORE fill:#e8eaf6,stroke:#283593,stroke-width:2px
    style DASH fill:#fce4ec,stroke:#880e4f,stroke-width:2px
    style INSIGHTS fill:#fff9c4,stroke:#f57f17,stroke-width:2px
```

See [Architecture Overview](docs/architecture.md) for detailed diagrams covering data pipeline, service communication, and message queue structure.

## 🌟 Key Features

- **⚡ High-Speed Processing**: ~130–480 records/second end-to-end throughput per data type with Rust-based extractor
- **🔄 Smart Deduplication**: SHA256 hash-based change detection prevents reprocessing
- **📈 Handles Big Data**: Processes 19M+ releases, 10M+ artists across ~11.3GB compressed XML
- **🔁 Auto-Recovery**: Automatic retries with exponential backoff and dead letter queues
- **🐋 Container Security**: Non-root users, read-only filesystems, dropped capabilities
- **📝 Type Safety**: Full type hints with strict mypy validation and Bandit security scanning
- **✅ Comprehensive Testing**: Unit, integration, and E2E tests with Playwright
- **🚀 Query Performance**: 249x overall query performance optimization across 88 endpoints (PRs #175–#189), plus configurable data quality rules for extraction validation (#187) — see [Recent Improvements](docs/recent-improvements.md)

## 🚀 Quick Start

```bash
# Clone and start all services
git clone https://github.com/SimplicityGuy/discogsography.git
cd discogsography
docker-compose up -d

# Access the dashboard
open http://localhost:8003
```

| Service           | URL                    | Default Credentials                 |
| ----------------- | ---------------------- | ----------------------------------- |
| 🔐 **API**        | http://localhost:8004  | Register via `/api/auth/register`   |
| 📊 **Dashboard**  | http://localhost:8003  | None                                |
| 🔗 **Neo4j**      | http://localhost:7474  | `neo4j` / `discogsography`          |
| 🐘 **PostgreSQL** | `localhost:5433`       | `discogsography` / `discogsography` |
| 🐰 **RabbitMQ**   | http://localhost:15672 | `discogsography` / `discogsography` |

See the [Quick Start Guide](docs/quick-start.md) for prerequisites, local development setup, and environment configuration.

## 📖 Documentation

### 🚀 Getting Started

| Document                                          | Purpose                                                  |
| ------------------------------------------------- | -------------------------------------------------------- |
| **[Quick Start Guide](docs/quick-start.md)**      | ⚡ Get Discogsography running in minutes                 |
| **[Configuration Guide](docs/configuration.md)**  | ⚙️ Complete environment variable and settings reference  |
| **[Architecture Overview](docs/architecture.md)** | 🏛️ System architecture, components, data flow, and scale |
| **[CLAUDE.md](CLAUDE.md)**                        | 🤖 Claude Code integration guide & development standards |

### 💡 Usage & Data

| Document                                       | Purpose                                              |
| ---------------------------------------------- | ---------------------------------------------------- |
| **[Usage Examples](docs/usage-examples.md)**   | 💡 Neo4j Cypher and PostgreSQL query examples        |
| **[Database Schema](docs/database-schema.md)** | 🗄️ Complete Neo4j graph model and PostgreSQL schema  |
| **[Monitoring Guide](docs/monitoring.md)**     | 📊 Real-time dashboard, metrics, and debug utilities |

### 👨‍💻 Development

| Document                                                           | Purpose                                               |
| ------------------------------------------------------------------ | ----------------------------------------------------- |
| **[Development Guide](docs/development.md)**                       | 💻 Project structure, tooling, and developer workflow |
| **[Testing Guide](docs/testing-guide.md)**                         | 🧪 Unit, integration, and E2E testing with Playwright |
| **[Logging Guide](docs/logging-guide.md)**                         | 📊 Structured logging standards and emoji conventions |
| **[Contributing Guide](docs/contributing.md)**                     | 🤝 How to contribute: process, standards, and PR flow |
| **[Python Version Management](docs/python-version-management.md)** | 🐍 Managing Python 3.13+ across the project           |

### 🔧 Operations

| Document                                                       | Purpose                                              |
| -------------------------------------------------------------- | ---------------------------------------------------- |
| **[Troubleshooting Guide](docs/troubleshooting.md)**           | 🔧 Common issues, solutions, and debugging steps     |
| **[Maintenance Guide](docs/maintenance.md)**                   | 🔄 Package upgrades, dependency management           |
| **[Performance Guide](docs/performance-guide.md)**             | ⚡ Database tuning, hardware specs, optimization     |
| **[Database Resilience](docs/database-resilience.md)**         | 💾 Database connection patterns & error handling     |
| **[MusicBrainz Sync Guide](docs/musicbrainz-sync.md)**        | 🎵 MusicBrainz data import and enrichment operations |

### 🐋 Infrastructure & CI/CD

| Document                                                 | Purpose                                                |
| -------------------------------------------------------- | ------------------------------------------------------ |
| **[Dockerfile Standards](docs/dockerfile-standards.md)** | 🐋 Best practices for writing Dockerfiles              |
| **[Docker Security](docs/docker-security.md)**           | 🔒 Container hardening & security practices            |
| **[GitHub Actions Guide](docs/github-actions-guide.md)** | 🚀 CI/CD workflows, automation & best practices        |
| **[Task Automation](docs/task-automation.md)**           | ⚙️ Complete `just` and `uv run task` command reference |
| **[Monorepo Guide](docs/monorepo-guide.md)**             | 📦 Managing Python monorepo with shared dependencies   |

### 📋 Reference

| Document                                                                   | Purpose                                                |
| -------------------------------------------------------------------------- | ------------------------------------------------------ |
| **[State Marker System](docs/state-marker-system.md)**                     | 📋 Extraction progress tracking & safe restart system  |
| **[State Marker Periodic Updates](docs/state-marker-periodic-updates.md)** | 💾 Periodic state saves and crash recovery             |
| **[Consumer Cancellation](docs/consumer-cancellation.md)**                 | 🔄 File completion and consumer lifecycle management   |
| **[File Completion Tracking](docs/file-completion-tracking.md)**           | 📊 Intelligent completion tracking and stall detection |
| **[Neo4j Indexing](docs/neo4j-indexing.md)**                               | 🔗 Advanced Neo4j indexing strategies                  |
| **[Platform Targeting](docs/platform-targeting.md)**                       | 🎯 Cross-platform compatibility guidelines             |
| **[Emoji Guide](docs/emoji-guide.md)**                                     | 📋 Standardized emoji usage across the project         |
| **[Recent Improvements](docs/recent-improvements.md)**                     | 🚀 Latest platform enhancements and changelog          |

## 💬 Support & Community

- 🐛 **Bug Reports**: [GitHub Issues](https://github.com/SimplicityGuy/discogsography/issues)
- 💡 **Feature Requests**: [GitHub Discussions](https://github.com/SimplicityGuy/discogsography/discussions)
- 💬 **Questions**: [Discussions Q&A](https://github.com/SimplicityGuy/discogsography/discussions/categories/q-a)
- 📚 **Full Documentation**: [docs/README.md](docs/README.md)

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

## Other Discogs Projects

Some other projects working with the monthly Discogs data dump.

- [DiscoDOS](https://github.com/JOJ0/discodo)
- [disco-quick](https://github.com/sublipri/disco-quick)
- [discogs-load](https://github.com/DylanBartels/discogs-load)

## 🙏 Acknowledgments

- 🎵 [Discogs](https://www.discogs.com/) for providing the monthly data dumps
- 🎵 [MusicBrainz](https://musicbrainz.org/) for the open music encyclopedia and twice-weekly JSONL dumps
- 🚀 [uv](https://github.com/astral-sh/uv) for blazing-fast package management
- 🔥 [Ruff](https://github.com/astral-sh/ruff) for lightning-fast linting
- 🐍 The Python community for excellent libraries and tools
- 🦀 The Rust community for excellent libraries and amazing performance

______________________________________________________________________

<div align="center">
Made with ❤️ in the Pacific Northwest
</div>
