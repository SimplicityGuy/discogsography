# 📦 Monorepo Structure Guide

> Understanding and working with Discogsography's uv workspace-based monorepo

## Overview

Discogsography uses a **monorepo** structure with **uv workspaces**, allowing multiple services to share code while
maintaining independent dependencies. This guide explains how to effectively work within this structure.

## 🏗️ Repository Structure

```mermaid
graph TD
    Root[discogsography/<br/>Root Workspace]

    RootFiles[pyproject.toml<br/>uv.lock<br/>.python-version]

    API[api/<br/>API Service]
    APIFiles[api.py<br/>routers/]

    Common[common/<br/>Shared Library]
    CommonFiles[config.py<br/>health_server.py]

    Dashboard[dashboard/<br/>Monitoring Service]
    DashFiles[dashboard.py<br/>static/]

    Extractor[extractor/<br/>Data Extraction]
    ExtractorFiles[src/main.rs<br/>Cargo.toml]

    Explore[explore/<br/>Static File Serving]
    ExploreFiles[explore.py]

    Graphinator[graphinator/<br/>Neo4j Service]
    GraphFiles[graphinator.py]

    SchemaInit[schema-init/<br/>DB Schema Init]
    SchemaFiles[neo4j_schema.py<br/>postgres_schema.py]

    Tableinator[tableinator/<br/>PostgreSQL Service]
    TableFiles[tableinator.py]

    BrainzGraph[brainzgraphinator/<br/>MusicBrainz Neo4j]
    BrainzGraphFiles[brainzgraphinator.py]

    BrainzTable[brainztableinator/<br/>MusicBrainz PostgreSQL]
    BrainzTableFiles[brainztableinator.py]

    Insights[insights/<br/>Analytics Service]
    InsightsFiles[insights.py<br/>computations.py]

    MCPServer[mcp-server/<br/>AI Assistant MCP]
    MCPFiles[server.py]

    Root --> RootFiles
    Root --> API
    Root --> Common
    Root --> Dashboard
    Root --> Extractor
    Root --> Explore
    Root --> Graphinator
    Root --> SchemaInit
    Root --> Tableinator
    Root --> BrainzGraph
    Root --> BrainzTable
    Root --> Insights
    Root --> MCPServer

    API --> APIFiles
    Common --> CommonFiles
    Dashboard --> DashFiles
    Extractor --> ExtractorFiles
    Explore --> ExploreFiles
    Graphinator --> GraphFiles
    SchemaInit --> SchemaFiles
    Tableinator --> TableFiles
    BrainzGraph --> BrainzGraphFiles
    BrainzTable --> BrainzTableFiles
    Insights --> InsightsFiles
    MCPServer --> MCPFiles

    style Root fill:#f3e5f5,stroke:#9c27b0,stroke-width:3px
    style API fill:#e1f5fe,stroke:#0288d1,stroke-width:2px
    style Common fill:#e8f5e9,stroke:#4caf50,stroke-width:2px
    style Dashboard fill:#e3f2fd,stroke:#2196f3,stroke-width:2px
    style Extractor fill:#fff3e0,stroke:#ff9800,stroke-width:2px
    style Explore fill:#fce4ec,stroke:#e91e63,stroke-width:2px
    style Graphinator fill:#f3e5f5,stroke:#9c27b0,stroke-width:2px
    style SchemaInit fill:#f1f8e9,stroke:#689f38,stroke-width:2px
    style Tableinator fill:#e0f2f1,stroke:#009688,stroke-width:2px
    style BrainzGraph fill:#e0f7fa,stroke:#00838f,stroke-width:2px
    style BrainzTable fill:#fff8e1,stroke:#ff8f00,stroke-width:2px
    style Insights fill:#fff9c4,stroke:#f57f17,stroke-width:2px
    style MCPServer fill:#ede7f6,stroke:#5e35b1,stroke-width:2px
```

### Directory Structure Details

```
discogsography/                    # Root workspace
├── pyproject.toml                 # Root configuration & shared dev dependencies
├── uv.lock                        # Single lock file for entire workspace
├── .python-version                # Python version for uv
│
├── api/                           # API service (workspace member)
│   ├── pyproject.toml            # Service-specific dependencies
│   ├── api.py                    # Service entry point
│   └── routers/                  # FastAPI routers
│
├── common/                        # Shared library (workspace member)
│   ├── pyproject.toml            # Declares [project] with name
│   ├── __init__.py
│   ├── config.py                 # Shared configuration
│   └── health_server.py          # Shared health check server
│
├── dashboard/                     # Service (workspace member)
│   ├── pyproject.toml           # Service-specific dependencies
│   ├── dashboard.py             # Service entry point
│   └── static/                  # Service assets
│
├── extractor/                     # Data extraction service (Rust — not a uv workspace member)
│   ├── Cargo.toml                # Rust dependencies
│   └── src/
│       └── main.rs              # Rust entry point
│
├── explore/                       # Static file serving (workspace member)
│   ├── pyproject.toml            # Service dependencies
│   └── explore.py                # Service entry point
│
├── graphinator/                   # Service (workspace member)
│   ├── pyproject.toml           # Neo4j dependencies
│   └── graphinator.py
│
├── brainzgraphinator/             # MusicBrainz Neo4j enrichment (workspace member)
│   ├── pyproject.toml           # Service dependencies
│   └── brainzgraphinator.py
│
├── brainztableinator/             # MusicBrainz PostgreSQL storage (workspace member)
│   ├── pyproject.toml           # Service dependencies
│   └── brainztableinator.py
│
├── insights/                      # Precomputed analytics (workspace member)
│   ├── pyproject.toml           # Service dependencies
│   ├── insights.py              # Service entry point
│   └── computations.py          # Computation orchestration
│
├── mcp-server/                    # AI assistant MCP server (workspace member)
│   ├── pyproject.toml           # Service dependencies
│   └── server.py                # FastMCP server
│
├── schema-init/                   # Database schema initializer (workspace member)
│   ├── pyproject.toml           # Schema dependencies
│   ├── neo4j_schema.py          # Neo4j constraints & indexes
│   └── postgres_schema.py       # PostgreSQL tables
│
└── tableinator/                   # Service (workspace member)
    ├── pyproject.toml           # PostgreSQL dependencies
    └── tableinator.py
```

## 🔑 Key Concepts

### 1. Workspace Members

Each service is a **workspace member** with its own `pyproject.toml`:

```toml
# dashboard/pyproject.toml
[project]
name = "dashboard"
version = "1.0.0"
dependencies = [
    "fastapi>=0.115.6",
    "websockets>=14.1",
    # Service-specific deps
]
```

### 2. Shared Dependencies

The root `pyproject.toml` defines:

- Development dependencies (testing, linting)
- Tool configurations (ruff, mypy, pytest)
- Workspace member declarations

```toml
# Root pyproject.toml
[tool.uv.workspace]
members = [
    "api",
    "brainzgraphinator",
    "brainztableinator",
    "common",
    "dashboard",
    "explore",
    "graphinator",
    "insights",
    "mcp-server",
    "schema-init",
    "tableinator"
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3.4",
    "ruff>=0.8.6",
    "mypy>=1.14.1",
    # Shared dev tools
]
```

### 3. Single Lock File

- **One `uv.lock`** at the root locks ALL dependencies
- Ensures version consistency across services
- Updated automatically by uv

## 📋 Common Tasks

### Installing Dependencies

```bash
# Install everything (recommended for development)
uv sync --all-extras

# Install specific service dependencies
uv sync --extra dashboard

# Install only dev dependencies
uv sync --extra dev
```

### Adding Dependencies

```bash
# Add to specific service
cd dashboard
uv add fastapi  # Adds to dashboard/pyproject.toml

# Add dev dependency (from root)
uv add --dev pytest-asyncio

# Add with version constraint
uv add "neo4j>=5.15.0"
```

### Running Services

```bash
# From project root (recommended)
uv run python dashboard/dashboard.py
uv run python explore/explore.py

# Using just commands
just dashboard
just extractor
```

### Import Patterns

```python
# Services can import from common
from common.config import Config
from common.health_server import HealthServer


# Or from explore
from common.health_server import HealthServer
# But NOT from other services (bad practice)
# from dashboard.something import thing  # ❌ Don't do this
```

## 🛠️ Development Workflow

### 1. Making Changes to Shared Code

When modifying `common/`:

```bash
# 1. Make your changes in common/
edit common/config.py

# 2. No reinstall needed - changes are immediate
# (common is installed in editable mode)

# 3. Test affected services
just test
```

### 2. Adding a New Service

```bash
# 1. Create service directory
mkdir myservice
cd myservice

# 2. Create pyproject.toml
cat > pyproject.toml << EOF
[project]
name = "myservice"
version = "1.0.0"
dependencies = [
    # Service dependencies
]
EOF

# 3. Add to root pyproject.toml
# Edit [tool.uv.workspace] members list

# 4. Sync workspace
cd ..
uv sync
```

### 3. Service-Specific Testing

```bash
# Test single service
uv run pytest tests/dashboard/

# Test with coverage
uv run pytest tests/dashboard/ --cov=dashboard

# Test everything
just test
```

## ⚠️ Common Pitfalls

### 1. Wrong Directory

```bash
# ❌ Bad: Running from service directory
cd dashboard
uv run python dashboard.py  # May fail to find imports

# ✅ Good: Running from root
uv run python dashboard/dashboard.py
```

### 2. Manual Dependency Edits

```bash
# ❌ Bad: Editing pyproject.toml manually
# Can break uv.lock consistency

# ✅ Good: Using uv commands
uv add package-name
```

### 3. Cross-Service Imports

```python
# ❌ Bad: Services importing from each other
# dashboard/dashboard.py
from dashboard.something import thing

# ✅ Good: Only import from common
from common.config import Config
```

### 4. Installing Without Workspace

```bash
# ❌ Bad: Installing service in isolation
cd dashboard
pip install -e .

# ✅ Good: Using uv sync from root
uv sync --all-extras
```

## 🐳 Docker Considerations

Each service has its own Dockerfile but shares the workspace structure:

```dockerfile
# Copy entire workspace
COPY pyproject.toml uv.lock ./
COPY common ./common
COPY dashboard ./dashboard

# Install specific service
RUN uv sync --frozen --no-dev --extra dashboard
```

## 🎯 Best Practices

1. **Always Work from Root**: Run commands from project root
1. **Use uv Commands**: Don't edit dependency files manually
1. **Shared Code in common/**: Put reusable code here
1. **Service Independence**: Services shouldn't depend on each other
1. **Test After Changes**: Especially when modifying common/
1. **Keep Services Focused**: Each service should have a single responsibility

## 📊 Workspace Benefits

| Benefit                 | Description                         |
| ----------------------- | ----------------------------------- |
| **Code Reuse**          | Share utilities via common/         |
| **Version Consistency** | Single lock file prevents conflicts |
| **Faster Installation** | uv caches dependencies efficiently  |
| **Atomic Updates**      | Update all services simultaneously  |
| **Simplified CI/CD**    | One install step for everything     |

## 🔍 Debugging

### Check Workspace Members

```bash
# Show dependency tree
uv tree

# List installed packages
uv pip list
```

### Verify Installation

```bash
# Check if service is installed
uv run python -c "import dashboard; print(dashboard.__file__)"
```

### Force Reinstall

```bash
# Clean install
rm -rf .venv
uv sync --all-extras
```

## 📚 Further Reading

- [uv Workspaces Documentation](https://github.com/astral-sh/uv)
- [Task Automation](task-automation.md) - Task commands
- [Docker Standards](dockerfile-standards.md) - Container setup
