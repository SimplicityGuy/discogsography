# MCP Server Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an MCP server that exposes the Discogsography knowledge graph as 9 tools callable by AI assistants.

**Architecture:** New `mcp-server/` package using FastMCP with lifespan-managed Neo4j and PostgreSQL connections. Reuses existing query modules from `api/queries/`. Supports stdio (Claude Desktop) and streamable-http (hosted) transports.

**Tech Stack:** Python 3.13+, mcp SDK (FastMCP), neo4j driver, psycopg, structlog

---

## File Structure

| File | Responsibility |
|------|---------------|
| `mcp-server/__init__.py` | Package marker |
| `mcp-server/server.py` | FastMCP server with lifespan, all 9 tools |
| `mcp-server/pyproject.toml` | Package metadata, entry point |
| `tests/mcp-server/__init__.py` | Test package marker |
| `tests/mcp-server/test_server.py` | Unit tests for all 9 tools |
| `pyproject.toml` (modify) | Add mcp-server to workspace, optional deps |
| `justfile` (modify) | Add test-mcp-server recipe |

## Chunk 1: Package scaffold and database lifespan

### Task 1: Create mcp-server package with pyproject.toml

**Files:**
- Create: `mcp-server/__init__.py`
- Create: `mcp-server/pyproject.toml`

- [ ] **Step 1: Create package init**

```python
# empty __init__.py
```

- [ ] **Step 2: Create pyproject.toml**

Entry point: `discogsography-mcp = "mcp_server.server:main"`

- [ ] **Step 3: Add to root workspace**

Add `"mcp-server"` to `[tool.uv.workspace]` members and add `mcp-server` optional dependency group.

- [ ] **Step 4: Install dependencies**

Run: `uv sync --all-extras`

- [ ] **Step 5: Commit**

### Task 2: Create server.py with lifespan and graph_stats tool

**Files:**
- Create: `mcp-server/server.py`

- [ ] **Step 1: Write server with lifespan managing Neo4j + PostgreSQL connections**
- [ ] **Step 2: Implement `get_graph_stats` tool (new Cypher query)**
- [ ] **Step 3: Implement `main()` entry point with transport arg parsing**
- [ ] **Step 4: Commit**

## Chunk 2: Implement all 9 tools

### Task 3: Implement search and detail tools

- [ ] **Step 1: Implement `search` tool** (wraps `execute_search` from search_queries)
- [ ] **Step 2: Implement `get_artist_details`** (wraps neo4j_queries.get_artist_details)
- [ ] **Step 3: Implement `get_label_details`**
- [ ] **Step 4: Implement `get_release_details`**
- [ ] **Step 5: Implement `get_genre_details`**
- [ ] **Step 6: Implement `get_style_details`**
- [ ] **Step 7: Commit**

### Task 4: Implement path, trends, and stats tools

- [ ] **Step 1: Implement `find_path` tool** (entity resolution + shortest path)
- [ ] **Step 2: Implement `get_trends` tool** (dispatch by entity type)
- [ ] **Step 3: Commit**

## Chunk 3: Tests

### Task 5: Write comprehensive unit tests

**Files:**
- Create: `tests/mcp-server/__init__.py`
- Create: `tests/mcp-server/test_server.py`

- [ ] **Step 1: Write tests for all 9 tools** using mocked Neo4j and PostgreSQL
- [ ] **Step 2: Write tests for lifespan initialization**
- [ ] **Step 3: Write tests for graph_stats Cypher query**
- [ ] **Step 4: Run tests**: `uv run pytest tests/mcp-server/ -v`
- [ ] **Step 5: Commit**

## Chunk 4: Integration

### Task 6: Update justfile and root config

- [ ] **Step 1: Add test-mcp-server recipe to justfile**
- [ ] **Step 2: Add coveragerc for mcp-server**
- [ ] **Step 3: Run full test suite**: `uv run pytest -m 'not e2e'`
- [ ] **Step 4: Run lint**: `uv run ruff check .`
- [ ] **Step 5: Run typecheck**: `uv run mypy .`
- [ ] **Step 6: Commit**

### Task 7: Add README

- [ ] **Step 1: Create mcp-server/README.md** with Claude Desktop config snippet, tool descriptions
- [ ] **Step 2: Commit**
