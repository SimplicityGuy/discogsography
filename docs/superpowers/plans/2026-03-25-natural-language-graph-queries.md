# Natural Language Graph Queries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a natural language query interface that translates plain English questions into knowledge graph API calls using Claude's native tool-use, returning natural language summaries with clickable entity references.

**Architecture:** NLQ engine lives inside the API service (`api/nlq/`), calling existing query functions directly. Claude tool-use loop (max 5 iterations) handles multi-step reasoning. Two-tier tool set: 10 public tools always available, 4 more when authenticated. Minimal "Ask" pane in Explore UI with SSE status streaming.

**Tech Stack:** Python 3.13+, `anthropic` SDK, FastAPI SSE (via `sse-starlette`), Redis caching, Vitest for frontend tests.

______________________________________________________________________

## File Structure

### New Files

| File                                | Responsibility                                                            |
| ----------------------------------- | ------------------------------------------------------------------------- |
| `api/nlq/__init__.py`               | Package init — exports `NLQEngine`, `NLQConfig`                           |
| `api/nlq/config.py`                 | NLQ-specific config dataclass, loaded from env vars                       |
| `api/nlq/tools.py`                  | Tool definitions (schemas + execution wrappers) for Claude tool-use       |
| `api/nlq/engine.py`                 | Core engine: builds Claude request, runs tool-use loop, extracts entities |
| `api/routers/nlq.py`                | FastAPI router: POST /api/nlq/query (JSON + SSE), GET /api/nlq/status     |
| `explore/static/js/nlq.js`          | Frontend "Ask" pane: input, SSE status, result display, entity linking    |
| `tests/api/nlq/__init__.py`         | Test package init                                                         |
| `tests/api/nlq/conftest.py`         | Shared NLQ test fixtures (mock Anthropic client, mock tools)              |
| `tests/api/nlq/test_config.py`      | NLQ config loading tests                                                  |
| `tests/api/nlq/test_tools.py`       | Tool wrapper unit tests                                                   |
| `tests/api/nlq/test_engine.py`      | Engine tool-use loop tests                                                |
| `tests/api/nlq/test_nlq_router.py`  | Router endpoint tests                                                     |
| `tests/mcp-server/test_nlq_tool.py` | MCP nlq_query tool tests                                                  |
| `explore/__tests__/nlq.test.js`     | Frontend NLQ pane Vitest tests                                            |

### Modified Files

| File                              | Change                                                |
| --------------------------------- | ----------------------------------------------------- |
| `pyproject.toml`                  | Add `anthropic` + `sse-starlette` to `api` extras     |
| `common/config.py`                | Add NLQ fields to `ApiConfig`                         |
| `api/api.py`                      | Import + wire NLQ router, configure in lifespan       |
| `tests/api/conftest.py`           | Add NLQ router configuration to `test_client` fixture |
| `mcp-server/mcp_server/server.py` | Add `nlq_query` tool + `_api_post` helper             |
| `explore/static/js/api-client.js` | Add `askNlq()` method with SSE support                |
| `explore/static/js/app.js`        | Register NLQ pane, add Search/Ask toggle logic        |
| `explore/static/index.html`       | Add Ask pane HTML markup                              |
| `docker-compose.yml`              | Add NLQ env vars to API service                       |

______________________________________________________________________

## Task 1: Add Dependencies

**Files:**

- Modify: `pyproject.toml:34-47`

- [ ] **Step 1: Add anthropic and sse-starlette to api extras**

In `pyproject.toml`, add `anthropic` and `sse-starlette` to the `api` optional dependencies (keep alphabetical order):

```toml
[project.optional-dependencies]
api = [
    "anthropic>=0.42.0",
    "cryptography>=43.0.0",
    "fastapi>=0.115.6",
    "httpx>=0.27.0",
    "neo4j-rust-ext>=6.1.0",
    "orjson>=3.9.0",
    "psycopg[binary]>=3.1.0",
    "pydantic>=2.10.5",
    "redis[hiredis]>=6.2.0",
    "slowapi>=0.1.9",
    "sse-starlette>=2.0.0",
    "structlog>=24.0.0",
    "uvicorn[standard]>=0.34.0",
]
```

- [ ] **Step 2: Install dependencies**

Run: `uv sync --all-extras`
Expected: Dependencies install successfully, `uv.lock` updated.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add anthropic and sse-starlette dependencies for NLQ (#203)"
```

______________________________________________________________________

## Task 2: NLQ Configuration

**Files:**

- Create: `api/nlq/__init__.py`

- Create: `api/nlq/config.py`

- Modify: `common/config.py`

- Create: `tests/api/nlq/__init__.py`

- Create: `tests/api/nlq/test_config.py`

- [ ] **Step 1: Write failing tests for NLQ config**

Create `tests/api/nlq/__init__.py` (empty file).

Create `tests/api/nlq/test_config.py`:

```python
"""Tests for NLQ configuration."""

import os
from unittest.mock import patch

import pytest

from api.nlq.config import NLQConfig


class TestNLQConfig:
    """NLQ configuration loading from environment."""

    def test_defaults(self) -> None:
        config = NLQConfig()
        assert config.enabled is False
        assert config.api_key is None
        assert config.model == "claude-sonnet-4-20250514"
        assert config.max_iterations == 5
        assert config.max_query_length == 500
        assert config.cache_ttl == 3600
        assert config.rate_limit == "10/minute"

    def test_from_env_enabled(self) -> None:
        env = {
            "NLQ_ENABLED": "true",
            "NLQ_API_KEY": "sk-ant-test-key",
            "NLQ_MODEL": "claude-haiku-4-5-20251001",
        }
        with patch.dict(os.environ, env):
            config = NLQConfig.from_env()
        assert config.enabled is True
        assert config.api_key == "sk-ant-test-key"
        assert config.model == "claude-haiku-4-5-20251001"

    def test_from_env_disabled_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            config = NLQConfig.from_env()
        assert config.enabled is False

    def test_is_available_requires_enabled_and_key(self) -> None:
        assert NLQConfig(enabled=False, api_key="sk-test").is_available is False
        assert NLQConfig(enabled=True, api_key=None).is_available is False
        assert NLQConfig(enabled=True, api_key="sk-test").is_available is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/nlq/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.nlq'`

- [ ] **Step 3: Create NLQ package and config**

Create `api/nlq/__init__.py`:

```python
"""Natural Language Graph Queries — Claude-powered conversational access to the knowledge graph."""
```

Create `api/nlq/config.py`:

```python
"""NLQ configuration — loaded from environment variables."""

from dataclasses import dataclass
from os import getenv

from common.config import get_secret


@dataclass(frozen=True)
class NLQConfig:
    """Configuration for the NLQ engine."""

    enabled: bool = False
    api_key: str | None = None
    model: str = "claude-sonnet-4-20250514"
    max_iterations: int = 5
    max_query_length: int = 500
    cache_ttl: int = 3600
    rate_limit: str = "10/minute"

    @property
    def is_available(self) -> bool:
        """Return True if NLQ is both enabled and has a valid API key."""
        return self.enabled and self.api_key is not None

    @classmethod
    def from_env(cls) -> "NLQConfig":
        """Create NLQ configuration from environment variables."""
        return cls(
            enabled=getenv("NLQ_ENABLED", "false").lower() == "true",
            api_key=get_secret("NLQ_API_KEY"),
            model=getenv("NLQ_MODEL", "claude-sonnet-4-20250514"),
            max_iterations=int(getenv("NLQ_MAX_ITERATIONS", "5")),
            max_query_length=int(getenv("NLQ_MAX_QUERY_LENGTH", "500")),
            cache_ttl=int(getenv("NLQ_CACHE_TTL", "3600")),
            rate_limit=getenv("NLQ_RATE_LIMIT", "10/minute"),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/nlq/test_config.py -v`
Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add api/nlq/__init__.py api/nlq/config.py tests/api/nlq/__init__.py tests/api/nlq/test_config.py
git commit -m "feat(nlq): add NLQ configuration with env var loading (#203)"
```

______________________________________________________________________

## Task 3: Tool Definitions and Runner

**Files:**

- Create: `api/nlq/tools.py`

- Create: `tests/api/nlq/conftest.py`

- Create: `tests/api/nlq/test_tools.py`

- [ ] **Step 1: Write failing tests for tool definitions**

Create `tests/api/nlq/conftest.py`:

```python
"""Shared fixtures for NLQ tests."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_neo4j_driver() -> MagicMock:
    """Mock Neo4j driver for NLQ tool tests."""
    return MagicMock()


@pytest.fixture
def mock_pg_pool() -> MagicMock:
    """Mock PostgreSQL pool for NLQ tool tests."""
    return MagicMock()


@pytest.fixture
def mock_redis_client() -> AsyncMock:
    """Mock Redis client for NLQ tool tests."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock()
    return redis
```

Create `tests/api/nlq/test_tools.py`:

```python
"""Tests for NLQ tool definitions and execution."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.nlq.tools import (
    NLQToolRunner,
    get_authenticated_tool_schemas,
    get_public_tool_schemas,
)


class TestToolSchemas:
    """Tool schema definitions."""

    def test_public_tools_returns_10_schemas(self) -> None:
        schemas = get_public_tool_schemas()
        assert len(schemas) == 10
        names = {s["name"] for s in schemas}
        assert "search" in names
        assert "autocomplete" in names
        assert "explore_entity" in names
        assert "find_path" in names
        assert "get_collaborators" in names
        assert "get_similar_artists" in names
        assert "get_label_dna" in names
        assert "get_trends" in names
        assert "get_genre_tree" in names
        assert "get_graph_stats" in names

    def test_authenticated_tools_returns_4_schemas(self) -> None:
        schemas = get_authenticated_tool_schemas()
        assert len(schemas) == 4
        names = {s["name"] for s in schemas}
        assert "get_collection_gaps" in names
        assert "get_taste_fingerprint" in names
        assert "get_taste_blindspots" in names
        assert "get_collection_stats" in names

    def test_all_schemas_have_required_fields(self) -> None:
        for schema in get_public_tool_schemas() + get_authenticated_tool_schemas():
            assert "name" in schema
            assert "description" in schema
            assert "input_schema" in schema
            assert schema["input_schema"]["type"] == "object"


class TestToolRunner:
    """Tool execution via NLQToolRunner."""

    @pytest.fixture
    def runner(self, mock_neo4j_driver: MagicMock, mock_pg_pool: MagicMock, mock_redis_client: AsyncMock) -> NLQToolRunner:
        return NLQToolRunner(
            neo4j_driver=mock_neo4j_driver,
            pg_pool=mock_pg_pool,
            redis=mock_redis_client,
        )

    @pytest.mark.asyncio
    async def test_execute_search(self, runner: NLQToolRunner) -> None:
        expected = {"query": "miles", "total": 1, "results": [{"name": "Miles Davis"}]}
        with patch("api.nlq.tools.execute_search", new_callable=AsyncMock, return_value=expected):
            result = await runner.execute("search", {"query": "miles"})
        assert result["total"] == 1

    @pytest.mark.asyncio
    async def test_execute_autocomplete(self, runner: NLQToolRunner) -> None:
        expected = [{"id": "123", "name": "Radiohead", "type": "artist"}]
        with patch("api.nlq.tools.autocomplete_artist", new_callable=AsyncMock, return_value=expected):
            result = await runner.execute("autocomplete", {"query": "radio", "entity_type": "artist"})
        assert result["results"][0]["name"] == "Radiohead"

    @pytest.mark.asyncio
    async def test_execute_unknown_tool_returns_error(self, runner: NLQToolRunner) -> None:
        result = await runner.execute("nonexistent_tool", {})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_extract_entities_from_search(self, runner: NLQToolRunner) -> None:
        result = {
            "results": [
                {"type": "artist", "id": "123", "name": "Miles Davis"},
                {"type": "label", "id": "456", "name": "Blue Note"},
            ],
        }
        entities = runner.extract_entities("search", result)
        assert len(entities) == 2
        assert entities[0] == {"id": "123", "name": "Miles Davis", "type": "artist"}

    @pytest.mark.asyncio
    async def test_extract_entities_from_autocomplete(self, runner: NLQToolRunner) -> None:
        result = {"results": [{"id": "123", "name": "Radiohead", "type": "artist"}]}
        entities = runner.extract_entities("autocomplete", result)
        assert len(entities) == 1

    @pytest.mark.asyncio
    async def test_extract_entities_returns_empty_on_error(self, runner: NLQToolRunner) -> None:
        result = {"error": "not found"}
        entities = runner.extract_entities("search", result)
        assert entities == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/nlq/test_tools.py -v`
Expected: FAIL — `ImportError: cannot import name 'NLQToolRunner'`

- [ ] **Step 3: Implement tool definitions and runner**

Create `api/nlq/tools.py`. This file defines 14 tool schemas (10 public + 4 authenticated) and an `NLQToolRunner` class that dispatches tool calls to existing query functions. Each tool handler validates parameters and calls the underlying function directly (no HTTP). The `extract_entities` method pulls entity references from tool results for UI linking.

Key patterns:

- `_tool()` helper builds Anthropic tool-use schema dicts
- `get_public_tool_schemas()` and `get_authenticated_tool_schemas()` return the schema lists
- `NLQToolRunner.execute(tool_name, params, user_id)` dispatches to handler methods
- `NLQToolRunner.extract_entities(tool_name, result)` extracts `{id, name, type}` dicts
- Handlers use lazy imports for query modules to avoid circular imports
- Error results return `{"error": "..."}` dicts
- Auth-required tools check `user_id is not None`

The tool runner wraps these existing functions:

- `search_queries.execute_search()`
- `neo4j_queries.AUTOCOMPLETE_DISPATCH[type]()`
- `neo4j_queries.EXPLORE_DISPATCH[type]()`
- `neo4j_queries.find_shortest_path()`
- `collaborator_queries.get_collaborators()`
- `neo4j_queries.get_similar_artists()`
- `label_dna_queries.get_label_full_profile()`
- `neo4j_queries.TRENDS_DISPATCH[type]()`
- `genre_tree_queries.get_genre_tree()`
- `neo4j_queries.get_graph_stats()`
- `gap_queries.get_label_gaps()` / `get_artist_gaps()`
- `taste_queries.get_taste_heatmap()`
- `taste_queries.get_blind_spots()`
- `taste_queries.get_collection_count()`

See the design spec at `docs/superpowers/specs/2026-03-25-natural-language-graph-queries-design.md` for exact tool schemas and parameter definitions.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/nlq/test_tools.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add api/nlq/tools.py tests/api/nlq/conftest.py tests/api/nlq/test_tools.py
git commit -m "feat(nlq): add tool definitions and runner with 14 tools (#203)"
```

______________________________________________________________________

## Task 4: NLQ Engine (Tool-Use Loop)

**Files:**

- Create: `api/nlq/engine.py`

- Create: `tests/api/nlq/test_engine.py`

- [ ] **Step 1: Write failing tests for the engine**

Create `tests/api/nlq/test_engine.py`. Tests cover:

- Single tool call → text response
- Multi-step tool calls (3 iterations)
- Max iterations cap (stops at limit)
- Authenticated context adds auth tools to request
- Unauthenticated context excludes auth tools
- Off-topic guardrail: zero tools + substantive answer → redirect
- Off-topic guardrail: zero tools + refusal → pass through

Each test mocks the Anthropic client with pre-scripted responses using `_make_text_response()` and `_make_tool_use_response()` helpers. See design spec for the engine's `NLQContext`, `NLQResult` dataclasses and system prompt content.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/nlq/test_engine.py -v`
Expected: FAIL — `ImportError: cannot import name 'NLQEngine'`

- [ ] **Step 3: Implement the NLQ engine**

Create `api/nlq/engine.py`. Key components:

- `_SYSTEM_PROMPT`: Static prompt instructing Claude to use tools, ground answers in data, stay on-topic
- `_AUTH_ADDENDUM`: Added when user is authenticated
- `_OFF_TOPIC_REDIRECT`: Canned message for off-topic queries
- `NLQContext(user_id, current_entity_id, current_entity_type)`: Query context
- `NLQResult(summary, entities, tools_used)`: Query result
- `NLQEngine.run(query, context, on_status)`: Runs the tool-use loop (max_iterations), returns NLQResult
- Off-topic guardrail: if zero tools used and response doesn't contain refusal keywords, replace with redirect
- Entity deduplication by (id, type)

See design spec for exact system prompt text and engine pseudocode.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/nlq/test_engine.py -v`
Expected: All 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add api/nlq/engine.py tests/api/nlq/test_engine.py
git commit -m "feat(nlq): add NLQ engine with tool-use loop and guardrails (#203)"
```

______________________________________________________________________

## Task 5: NLQ Router (API Endpoints)

**Files:**

- Create: `api/routers/nlq.py`

- Modify: `api/api.py`

- Modify: `tests/api/conftest.py`

- Create: `tests/api/nlq/test_nlq_router.py`

- [ ] **Step 1: Write failing tests for the router**

Create `tests/api/nlq/test_nlq_router.py`. Tests cover:

- `GET /api/nlq/status` returns `{"enabled": true}` when available
- `GET /api/nlq/status` returns `{"enabled": false}` when disabled
- `POST /api/nlq/query` returns 503 when disabled
- `POST /api/nlq/query` returns 400 for empty query
- `POST /api/nlq/query` returns 400 for query over max length
- `POST /api/nlq/query` returns 200 with NLQResult
- `POST /api/nlq/query` returns cached result with `cached: true`

Tests manipulate `nlq_router._nlq_config` and `nlq_router._engine` module globals directly, following the pattern used by existing router tests (e.g., `test_search.py`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/nlq/test_nlq_router.py -v`
Expected: FAIL — `ImportError: No module named 'api.routers.nlq'`

- [ ] **Step 3: Implement the NLQ router**

Create `api/routers/nlq.py`. Key components:

- `configure(nlq_config, engine, redis)`: Sets module globals

- `NLQQueryRequest(query, context)`: Pydantic request model

- `GET /api/nlq/status`: Returns `{"enabled": bool}`

- `POST /api/nlq/query`: Validates input, checks cache (public queries only), runs engine, caches result

- SSE streaming via `sse_starlette.EventSourceResponse` when `Accept: text/event-stream`

- Rate limited at 10/minute via `@limiter.limit()`

- Auth context extracted from Bearer token (optional — unauthenticated is fine)

- Cache key: `nlq:{sha256(normalized_query)[:16]}`

- [ ] **Step 4: Wire the NLQ router into the API service**

In `api/api.py`:

- Add `import api.routers.nlq as _nlq_router` with the other router imports

- In `lifespan()`, after existing configure calls: create `NLQConfig.from_env()`, conditionally create `AsyncAnthropic` client + `NLQToolRunner` + `NLQEngine`, call `_nlq_router.configure()`

- Add `app.include_router(_nlq_router.router)` with other includes

- [ ] **Step 5: Update test conftest to wire NLQ router**

In `tests/api/conftest.py` `test_client` fixture, add NLQ router configuration with disabled config:

```python
    import api.routers.nlq as _nlq_router
    from api.nlq.config import NLQConfig
    _nlq_router.configure(NLQConfig(), None, mock_redis)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/api/nlq/ -v`
Expected: All tests PASS.

- [ ] **Step 7: Run full API test suite to verify no regressions**

Run: `just test-api`
Expected: All existing tests PASS.

- [ ] **Step 8: Commit**

```bash
git add api/routers/nlq.py api/api.py tests/api/conftest.py tests/api/nlq/test_nlq_router.py
git commit -m "feat(nlq): add NLQ router with query endpoint and SSE streaming (#203)"
```

______________________________________________________________________

## Task 6: MCP Server Integration

**Files:**

- Modify: `mcp-server/mcp_server/server.py`

- Create: `tests/mcp-server/test_nlq_tool.py`

- [ ] **Step 1: Write failing test for the MCP nlq_query tool**

Create `tests/mcp-server/test_nlq_tool.py`. Tests:

- `nlq_query` sends POST to `/api/nlq/query` and returns result
- `nlq_query` handles 503 disabled response

Uses existing MCP test patterns: `AppContext` fixture, `mock_context` fixture, `_mock_response` helper.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/mcp-server/test_nlq_tool.py -v`
Expected: FAIL — `ImportError: cannot import name 'nlq_query'`

- [ ] **Step 3: Add nlq_query tool and \_api_post helper to MCP server**

In `mcp-server/mcp_server/server.py`:

- Add `_api_post(app, path, json_data)` helper near `_api_get`

- Add `nlq_query(query, ctx)` tool with `@mcp.tool()` decorator

- Tool calls `_api_post(app, "/api/nlq/query", json_data={"query": query})`

- Returns `resp.json()`

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/mcp-server/test_nlq_tool.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Run full MCP test suite**

Run: `just test-mcp-server`
Expected: All existing tests PASS.

- [ ] **Step 6: Commit**

```bash
git add mcp-server/mcp_server/server.py tests/mcp-server/test_nlq_tool.py
git commit -m "feat(mcp): add nlq_query tool for natural language graph queries (#203)"
```

______________________________________________________________________

## Task 7: Frontend — Ask Pane

**Files:**

- Create: `explore/static/js/nlq.js`

- Modify: `explore/static/js/api-client.js`

- Modify: `explore/static/js/app.js`

- Modify: `explore/static/index.html`

- Create: `explore/__tests__/nlq.test.js`

- [ ] **Step 1: Write failing frontend tests**

Create `explore/__tests__/nlq.test.js`. Tests:

- `checkNlqStatus()` returns enabled status
- `checkNlqStatus()` returns disabled on error
- `askNlq()` POSTs query and returns result
- `askNlq()` passes context when provided
- `askNlq()` returns null on failure

Uses existing Vitest patterns: `loadScript()`, `createMockFetch()`, `vi.stubGlobal('fetch', ...)`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd explore && npx vitest run __tests__/nlq.test.js`
Expected: FAIL — `checkNlqStatus` and `askNlq` are not defined.

- [ ] **Step 3: Add NLQ methods to api-client.js**

Add `checkNlqStatus()`, `askNlq(query, context)`, and `askNlqStream(query, context, onStatus, onResult, onError)` methods to the `ApiClient` class.

- `checkNlqStatus()`: GET `/api/nlq/status`, returns `{enabled: false}` on error

- `askNlq()`: POST `/api/nlq/query` with JSON body, returns result or null

- `askNlqStream()`: POST with `Accept: text/event-stream`, reads SSE events via ReadableStream

- [ ] **Step 4: Create the NLQ panel JavaScript**

Create `explore/static/js/nlq.js`. The `NLQPanel` class:

- Binds to DOM elements (`nlqInput`, `nlqSubmit`, `nlqStatus`, `nlqResult`, `nlqExamples`)
- `checkEnabled()`: calls `apiClient.checkNlqStatus()`
- `_submit()`: sends query via `askNlqStream()`, shows status events, renders result
- `_linkifyEntities(text, entities)`: matches entity names in text and wraps in anchor tags with `data-entity-name` and `data-entity-type` attributes. Uses `textContent` for user text and safe DOM construction for entity links to prevent XSS.
- `onExploreEntity` callback for entity link clicks
- Example query chips trigger queries on click

**Security note:** Entity names come from the API (graph data, not user input), but the panel must still use safe DOM methods. Use `document.createElement()` and `textContent` assignment instead of string concatenation with `innerHTML`. Entity link creation uses `setAttribute()` for data attributes.

- [ ] **Step 5: Add HTML markup for the Ask pane**

In `explore/static/index.html`:

- Add `<script src="js/nlq.js"></script>` with other JS includes

- Add Search/Ask toggle: `<div id="searchAskToggle">` with two toggle buttons

- Add NLQ panel: `<div id="nlqPanel">` with input, submit button, status area, result area, example chips

- Add CSS for `.nlq-panel`, `.nlq-input`, `.nlq-status`, `.nlq-result`, `.nlq-entity-link`, `.nlq-tool-pill`, `.nlq-example-chip`

- [ ] **Step 6: Wire NLQ panel into app.js**

In `explore/static/js/app.js`:

- Create `NLQPanel` instance

- Set `onExploreEntity` callback to switch back to explore mode and load entity

- Call `checkEnabled()` on page load, show toggle if enabled

- Bind Search/Ask toggle buttons

- Add `?` keyboard shortcut for Ask mode

- [ ] **Step 7: Run frontend tests**

Run: `cd explore && npx vitest run __tests__/nlq.test.js`
Expected: All tests PASS.

- [ ] **Step 8: Commit**

```bash
git add explore/static/js/nlq.js explore/static/js/api-client.js explore/static/js/app.js explore/static/index.html explore/__tests__/nlq.test.js
git commit -m "feat(explore): add NLQ Ask pane with SSE streaming and entity linking (#203)"
```

______________________________________________________________________

## Task 8: Docker and CI Configuration

**Files:**

- Modify: `docker-compose.yml`

- [ ] **Step 1: Add NLQ env vars to docker-compose.yml**

Add to the API service's `environment` section:

```yaml
      # NLQ (Natural Language Queries) — disabled by default
      NLQ_ENABLED: "${NLQ_ENABLED:-false}"
      NLQ_API_KEY: "${NLQ_API_KEY:-}"
      NLQ_MODEL: "${NLQ_MODEL:-claude-sonnet-4-20250514}"
```

- [ ] **Step 2: Verify CI test workflow covers NLQ tests**

NLQ tests in `tests/api/nlq/` are covered by `just test-api`. MCP tests covered by `just test-mcp-server`. No CI changes needed.

Verify: `uv run pytest tests/api/nlq/ -v && uv run pytest tests/mcp-server/test_nlq_tool.py -v`
Expected: All NLQ tests PASS.

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "chore: add NLQ environment variables to docker-compose (#203)"
```

______________________________________________________________________

## Task 9: Lint, Type Check, and Final Verification

**Files:** All new and modified files.

- [ ] **Step 1: Run ruff lint**

Run: `just lint-python`
Expected: No new lint errors. Fix any issues.

- [ ] **Step 2: Run mypy type check**

Run: `uv run mypy api/nlq/ api/routers/nlq.py`
Expected: No type errors. Fix any issues.

- [ ] **Step 3: Run full test suite**

Run: `just test-api && just test-mcp-server && just test-js`
Expected: All tests PASS with >=80% coverage on new code.

- [ ] **Step 4: Fix any issues found and commit**

```bash
git add -A
git commit -m "chore(nlq): lint and type fixes (#203)"
```

______________________________________________________________________

## Task 10: Documentation and Final Commit

**Files:**

- Modify: `docs/emoji-guide.md` (if new emojis used)

- [ ] **Step 1: Verify emoji compliance**

Check that all log messages in NLQ code use emojis from `docs/emoji-guide.md`. The engine uses:

- `🔥` for errors (existing in guide)
- `⚠️` for warnings (existing in guide)
- `🔄` for cache operations (existing in guide)
- `🧠` for NLQ engine init — check if this is in the guide. If not, add it.

Read `docs/emoji-guide.md` and add `🧠` for "AI/NLQ operations" if missing.

- [ ] **Step 2: Commit any doc updates**

```bash
git add docs/emoji-guide.md
git commit -m "docs: add AI/NLQ emoji to emoji guide (#203)"
```

- [ ] **Step 3: Create summary commit message for PR**

All implementation is complete. The feature is behind `NLQ_ENABLED=false` by default and requires `NLQ_API_KEY` to be set.
