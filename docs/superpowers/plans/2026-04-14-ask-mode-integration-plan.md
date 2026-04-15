# Ask Mode Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the cramped navbar Ask toggle with a global floating pill that sends questions through an agent, renders a dynamic-suggestion card on expand, and applies structured UI actions that mutate the graph and panes — while extracting a shared tool registry so NLQ and MCP share one tool surface.

**Architecture:** Python 3.13+ / Rust / uv-managed monorepo. Backend: FastAPI NLQ router → `NLQEngine` tool-use loop over Anthropic Messages API → `NLQToolRunner` delegating to a new `common.agent_tools` library consumed by both the engine and `mcp-server/mcp_server/server.py`. Frontend: vanilla JS modules served from `explore/static/js/`; new `nlq-pill.js`, `nlq-suggestions.js`, `nlq-action-applier.js` modules coordinated by a rewritten `nlq.js`. Tests: pytest (`uv run pytest`) for Python, Vitest (`npm test` in `explore/`) for JS, Playwright for E2E.

**Tech Stack:** Python 3.13 (FastAPI, Pydantic, Anthropic SDK, structlog), Neo4j async driver, Redis, vanilla JS (ES modules), DOMPurify, marked, Tailwind, Vitest, Playwright, pytest.

**Spec reference:** `docs/superpowers/specs/2026-04-14-ask-mode-integration-design.md`

---

## Phase 1 — Shared tool registry foundation

Create `common/agent_tools/` with pure async data-fetching functions. Start with the tools the existing NLQ engine already uses, so Phase 2 can refactor the NLQ tool runner to delegate.

### Task 1: Create `common/agent_tools/` package skeleton

**Files:**
- Create: `common/agent_tools/__init__.py`
- Create: `common/agent_tools/schemas.py`
- Create: `tests/common/test_agent_tools_package.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/common/test_agent_tools_package.py
"""Tests that the agent_tools package and its top-level exports load."""

from __future__ import annotations


def test_package_imports_cleanly() -> None:
    import common.agent_tools as at

    assert hasattr(at, "__all__")


def test_schemas_module_imports() -> None:
    from common.agent_tools import schemas

    assert schemas is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/common/test_agent_tools_package.py -v`
Expected: `ModuleNotFoundError: No module named 'common.agent_tools'`

- [ ] **Step 3: Write minimal implementation**

```python
# common/agent_tools/__init__.py
"""Shared agent tool registry.

Pure async data-fetching functions shared between the NLQ engine and the
MCP server. No framework coupling — just typed params in, typed dicts out.
"""

from __future__ import annotations


__all__: list[str] = []
```

```python
# common/agent_tools/schemas.py
"""Pydantic schemas for shared agent tool inputs and outputs."""

from __future__ import annotations
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/common/test_agent_tools_package.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add common/agent_tools/ tests/common/test_agent_tools_package.py
git commit -m "feat(common): scaffold agent_tools package"
```

### Task 2: Add `find_path` tool function

**Files:**
- Create: `common/agent_tools/graph.py`
- Modify: `common/agent_tools/__init__.py`
- Create: `tests/common/test_agent_tools_graph.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/common/test_agent_tools_graph.py
"""Tests for common.agent_tools.graph."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_find_path_resolves_names_and_returns_path() -> None:
    from common.agent_tools.graph import find_path

    driver = AsyncMock()
    resolve_name = AsyncMock(side_effect=[{"id": "42"}, {"id": "99"}])
    find_shortest_path = AsyncMock(return_value={"path": [42, 99], "length": 1})

    result = await find_path(
        driver=driver,
        from_name="Kraftwerk",
        from_type="artist",
        to_name="Afrika Bambaataa",
        to_type="artist",
        max_depth=6,
        resolve_name=resolve_name,
        find_shortest_path_fn=find_shortest_path,
    )

    assert result == {"path": [42, 99], "length": 1}
    assert resolve_name.await_count == 2
    find_shortest_path.assert_awaited_once_with(
        driver=driver,
        from_id="42",
        to_id="99",
        max_depth=6,
        from_type="artist",
        to_type="artist",
    )


@pytest.mark.asyncio
async def test_find_path_returns_error_when_source_missing() -> None:
    from common.agent_tools.graph import find_path

    driver = AsyncMock()
    resolve_name = AsyncMock(return_value=None)
    find_shortest_path = AsyncMock()

    result = await find_path(
        driver=driver,
        from_name="Nobody",
        from_type="artist",
        to_name="Kraftwerk",
        to_type="artist",
        resolve_name=resolve_name,
        find_shortest_path_fn=find_shortest_path,
    )

    assert result == {"error": "artist 'Nobody' not found"}
    find_shortest_path.assert_not_awaited()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/common/test_agent_tools_graph.py -v`
Expected: `ModuleNotFoundError: No module named 'common.agent_tools.graph'`

- [ ] **Step 3: Write minimal implementation**

```python
# common/agent_tools/graph.py
"""Graph data tools — find_path, collaborators, stats."""

from __future__ import annotations

from typing import Any, Awaitable, Callable


ResolveNameFn = Callable[[Any, str, str], Awaitable[dict[str, Any] | None]]
FindShortestPathFn = Callable[..., Awaitable[dict[str, Any] | None]]


async def find_path(
    *,
    driver: Any,
    from_name: str,
    from_type: str,
    to_name: str,
    to_type: str,
    max_depth: int = 6,
    resolve_name: ResolveNameFn,
    find_shortest_path_fn: FindShortestPathFn,
) -> dict[str, Any]:
    """Find the shortest path between two entities by name.

    The caller injects ``resolve_name`` and ``find_shortest_path_fn`` so this
    module has zero coupling to ``api.queries``. The NLQ engine and the MCP
    server each pass their own resolver bound to the same shared implementation.
    """
    from_node = await resolve_name(driver, from_name, from_type)
    if from_node is None:
        return {"error": f"{from_type} '{from_name}' not found"}
    to_node = await resolve_name(driver, to_name, to_type)
    if to_node is None:
        return {"error": f"{to_type} '{to_name}' not found"}

    result = await find_shortest_path_fn(
        driver=driver,
        from_id=str(from_node["id"]),
        to_id=str(to_node["id"]),
        max_depth=max_depth,
        from_type=from_type,
        to_type=to_type,
    )
    if result is None:
        return {"error": "No path found between the specified entities"}
    return result
```

```python
# common/agent_tools/__init__.py
"""Shared agent tool registry."""

from __future__ import annotations

from common.agent_tools.graph import find_path


__all__ = ["find_path"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/common/test_agent_tools_graph.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add common/agent_tools/graph.py common/agent_tools/__init__.py tests/common/test_agent_tools_graph.py
git commit -m "feat(common): add agent_tools.graph.find_path"
```

### Task 3: Add entity detail tools (`get_artist_details`, `get_label_details`, `get_genre_details`, `get_style_details`, `get_release_details`)

**Files:**
- Create: `common/agent_tools/entities.py`
- Modify: `common/agent_tools/__init__.py`
- Create: `tests/common/test_agent_tools_entities.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/common/test_agent_tools_entities.py
"""Tests for common.agent_tools.entities."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.mark.parametrize(
    "tool_name,entity_type",
    [
        ("get_artist_details", "artist"),
        ("get_label_details", "label"),
        ("get_genre_details", "genre"),
        ("get_style_details", "style"),
        ("get_release_details", "release"),
    ],
)
@pytest.mark.asyncio
async def test_entity_details_delegates_to_handler(tool_name: str, entity_type: str) -> None:
    import common.agent_tools.entities as entities

    driver = AsyncMock()
    handler = AsyncMock(return_value={"id": "1", "name": "Example"})
    tool = getattr(entities, tool_name)

    result = await tool(driver=driver, name="Example", handler=handler)
    assert result == {"id": "1", "name": "Example", "_entity_type": entity_type}
    handler.assert_awaited_once_with(driver, "Example")


@pytest.mark.asyncio
async def test_entity_details_returns_error_when_not_found() -> None:
    from common.agent_tools.entities import get_artist_details

    driver = AsyncMock()
    handler = AsyncMock(return_value=None)
    result = await get_artist_details(driver=driver, name="Nobody", handler=handler)
    assert result == {"error": "artist 'Nobody' not found"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/common/test_agent_tools_entities.py -v`
Expected: `ModuleNotFoundError: No module named 'common.agent_tools.entities'`

- [ ] **Step 3: Write minimal implementation**

```python
# common/agent_tools/entities.py
"""Entity detail tools."""

from __future__ import annotations

from typing import Any, Awaitable, Callable


HandlerFn = Callable[[Any, str], Awaitable[dict[str, Any] | None]]


async def _entity_details(entity_type: str, *, driver: Any, name: str, handler: HandlerFn) -> dict[str, Any]:
    node = await handler(driver, name)
    if node is None:
        return {"error": f"{entity_type} '{name}' not found"}
    result = dict(node)
    result["_entity_type"] = entity_type
    return result


async def get_artist_details(*, driver: Any, name: str, handler: HandlerFn) -> dict[str, Any]:
    return await _entity_details("artist", driver=driver, name=name, handler=handler)


async def get_label_details(*, driver: Any, name: str, handler: HandlerFn) -> dict[str, Any]:
    return await _entity_details("label", driver=driver, name=name, handler=handler)


async def get_genre_details(*, driver: Any, name: str, handler: HandlerFn) -> dict[str, Any]:
    return await _entity_details("genre", driver=driver, name=name, handler=handler)


async def get_style_details(*, driver: Any, name: str, handler: HandlerFn) -> dict[str, Any]:
    return await _entity_details("style", driver=driver, name=name, handler=handler)


async def get_release_details(*, driver: Any, name: str, handler: HandlerFn) -> dict[str, Any]:
    return await _entity_details("release", driver=driver, name=name, handler=handler)
```

Modify `common/agent_tools/__init__.py`:

```python
from common.agent_tools.entities import (
    get_artist_details,
    get_genre_details,
    get_label_details,
    get_release_details,
    get_style_details,
)
from common.agent_tools.graph import find_path


__all__ = [
    "find_path",
    "get_artist_details",
    "get_genre_details",
    "get_label_details",
    "get_release_details",
    "get_style_details",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/common/test_agent_tools_entities.py -v`
Expected: 6 passed (5 parametrized + 1 error case)

- [ ] **Step 5: Commit**

```bash
git add common/agent_tools/entities.py common/agent_tools/__init__.py tests/common/test_agent_tools_entities.py
git commit -m "feat(common): add entity detail tools to agent_tools"
```

### Task 4: Add remaining data tools — `search`, `get_collaborators`, `get_trends`, `get_graph_stats`, `get_genre_tree`

**Files:**
- Create: `common/agent_tools/discovery.py`
- Create: `common/agent_tools/stats.py`
- Modify: `common/agent_tools/__init__.py`
- Create: `tests/common/test_agent_tools_discovery.py`
- Create: `tests/common/test_agent_tools_stats.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/common/test_agent_tools_discovery.py
"""Tests for common.agent_tools.discovery (search, collaborators, trends)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_search_delegates() -> None:
    from common.agent_tools.discovery import search

    executor = AsyncMock(return_value={"results": [{"id": "1", "name": "Kraftwerk"}]})
    result = await search(
        pool=object(),
        redis=object(),
        q="Kraftwerk",
        types=["artist"],
        genres=[],
        year_min=None,
        year_max=None,
        limit=5,
        offset=0,
        search_fn=executor,
    )
    assert result == {"results": [{"id": "1", "name": "Kraftwerk"}]}
    executor.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_collaborators_wraps_list() -> None:
    from common.agent_tools.discovery import get_collaborators

    fn = AsyncMock(return_value=[{"id": "2"}])
    result = await get_collaborators(driver=object(), artist_id="1", limit=10, collaborators_fn=fn)
    assert result == {"collaborators": [{"id": "2"}]}


@pytest.mark.asyncio
async def test_get_trends_dispatches_by_type() -> None:
    from common.agent_tools.discovery import get_trends

    handler = AsyncMock(return_value=[{"year": 2025, "count": 10}])
    result = await get_trends(
        driver=object(),
        entity_type="artist",
        name="Kraftwerk",
        handler=handler,
    )
    assert result == {"trends": [{"year": 2025, "count": 10}]}


@pytest.mark.asyncio
async def test_get_trends_missing_handler_errors() -> None:
    from common.agent_tools.discovery import get_trends

    result = await get_trends(
        driver=object(),
        entity_type="artist",
        name="Kraftwerk",
        handler=None,
    )
    assert result == {"error": "Unknown trends type: artist"}
```

```python
# tests/common/test_agent_tools_stats.py
"""Tests for common.agent_tools.stats (graph_stats, genre_tree)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_get_graph_stats_delegates() -> None:
    from common.agent_tools.stats import get_graph_stats

    fn = AsyncMock(return_value={"artists": 100, "labels": 50})
    result = await get_graph_stats(driver=object(), stats_fn=fn)
    assert result == {"artists": 100, "labels": 50}


@pytest.mark.asyncio
async def test_get_genre_tree_wraps_list() -> None:
    from common.agent_tools.stats import get_genre_tree

    fn = AsyncMock(return_value=[{"name": "Electronic", "children": []}])
    result = await get_genre_tree(driver=object(), tree_fn=fn)
    assert result == {"genres": [{"name": "Electronic", "children": []}]}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/common/test_agent_tools_discovery.py tests/common/test_agent_tools_stats.py -v`
Expected: `ModuleNotFoundError: No module named 'common.agent_tools.discovery'`

- [ ] **Step 3: Write minimal implementation**

```python
# common/agent_tools/discovery.py
"""Discovery tools — search, collaborators, trends."""

from __future__ import annotations

from typing import Any, Awaitable, Callable


SearchFn = Callable[..., Awaitable[dict[str, Any]]]
CollaboratorsFn = Callable[..., Awaitable[list[dict[str, Any]]]]
TrendsHandler = Callable[[Any, str], Awaitable[list[dict[str, Any]]]]


async def search(
    *,
    pool: Any,
    redis: Any,
    q: str,
    types: list[str],
    genres: list[str],
    year_min: int | None,
    year_max: int | None,
    limit: int,
    offset: int,
    search_fn: SearchFn,
) -> dict[str, Any]:
    return await search_fn(
        pool=pool,
        redis=redis,
        q=q,
        types=types,
        genres=genres,
        year_min=year_min,
        year_max=year_max,
        limit=limit,
        offset=offset,
    )


async def get_collaborators(
    *,
    driver: Any,
    artist_id: str,
    limit: int,
    collaborators_fn: CollaboratorsFn,
) -> dict[str, Any]:
    collaborators = await collaborators_fn(driver, artist_id, limit=limit)
    return {"collaborators": collaborators}


async def get_trends(
    *,
    driver: Any,
    entity_type: str,
    name: str,
    handler: TrendsHandler | None,
) -> dict[str, Any]:
    if handler is None:
        return {"error": f"Unknown trends type: {entity_type}"}
    results = await handler(driver, name)
    return {"trends": results}
```

```python
# common/agent_tools/stats.py
"""Stats tools — graph_stats, genre_tree."""

from __future__ import annotations

from typing import Any, Awaitable, Callable


StatsFn = Callable[[Any], Awaitable[dict[str, Any]]]
TreeFn = Callable[[Any], Awaitable[list[dict[str, Any]]]]


async def get_graph_stats(*, driver: Any, stats_fn: StatsFn) -> dict[str, Any]:
    return await stats_fn(driver)


async def get_genre_tree(*, driver: Any, tree_fn: TreeFn) -> dict[str, Any]:
    tree = await tree_fn(driver)
    return {"genres": tree}
```

Update `common/agent_tools/__init__.py` to export the new symbols:

```python
from common.agent_tools.discovery import get_collaborators, get_trends, search
from common.agent_tools.entities import (
    get_artist_details,
    get_genre_details,
    get_label_details,
    get_release_details,
    get_style_details,
)
from common.agent_tools.graph import find_path
from common.agent_tools.stats import get_genre_tree, get_graph_stats


__all__ = [
    "find_path",
    "get_artist_details",
    "get_collaborators",
    "get_genre_details",
    "get_genre_tree",
    "get_graph_stats",
    "get_label_details",
    "get_release_details",
    "get_style_details",
    "get_trends",
    "search",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/common/test_agent_tools_discovery.py tests/common/test_agent_tools_stats.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add common/agent_tools/discovery.py common/agent_tools/stats.py common/agent_tools/__init__.py tests/common/test_agent_tools_discovery.py tests/common/test_agent_tools_stats.py
git commit -m "feat(common): add discovery and stats tools to agent_tools"
```

---

## Phase 2 — NLQ engine delegates to shared tools

Refactor `api/nlq/tools.py` so each `_handle_*` method is a one-line delegate into `common.agent_tools`. No behavior change — the existing integration tests must still pass.

### Task 5: Delegate `NLQToolRunner._handle_find_path` to `common.agent_tools.find_path`

**Files:**
- Modify: `api/nlq/tools.py:372-409`
- Create: `tests/api/nlq/test_tools_delegation.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/api/nlq/test_tools_delegation.py
"""Tests that NLQToolRunner delegates to common.agent_tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_handle_find_path_delegates_to_shared_tool() -> None:
    from api.nlq.tools import NLQToolRunner

    runner = NLQToolRunner(neo4j_driver=object(), pg_pool=object(), redis=object())

    with patch("common.agent_tools.find_path", new=AsyncMock(return_value={"path": [1, 2]})) as mock_shared:
        result = await runner._handle_find_path(
            {"from_id": "Kraftwerk", "to_id": "Bambaataa", "from_type": "artist", "to_type": "artist"},
            None,
        )

    assert result == {"path": [1, 2]}
    mock_shared.assert_awaited_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/nlq/test_tools_delegation.py -v`
Expected: FAIL — the current implementation does not import `common.agent_tools.find_path`.

- [ ] **Step 3: Write minimal implementation**

Replace `api/nlq/tools.py:372-409` with:

```python
    async def _handle_find_path(self, params: dict[str, Any], _user_id: str | None) -> dict[str, Any]:
        from api.queries import neo4j_queries  # noqa: PLC0415
        from common import agent_tools  # noqa: PLC0415

        async def resolve_name(driver: Any, name: str, entity_type: str) -> dict[str, Any] | None:
            if name and name.isdigit():
                return {"id": name}
            handler = neo4j_queries.EXPLORE_DISPATCH.get(entity_type)
            if handler is None:
                return None
            return await handler(driver, name)

        return await agent_tools.find_path(
            driver=self._driver,
            from_name=params.get("from_id", ""),
            from_type=params.get("from_type", ""),
            to_name=params.get("to_id", ""),
            to_type=params.get("to_type", ""),
            max_depth=params.get("max_depth", 6),
            resolve_name=resolve_name,
            find_shortest_path_fn=neo4j_queries.find_shortest_path,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/nlq/ -v`
Expected: all existing tests pass + new delegation test passes.

- [ ] **Step 5: Commit**

```bash
git add api/nlq/tools.py tests/api/nlq/test_tools_delegation.py
git commit -m "refactor(api/nlq): delegate _handle_find_path to common.agent_tools"
```

### Task 6: Delegate remaining `NLQToolRunner._handle_*` methods

**Files:**
- Modify: `api/nlq/tools.py:329-497`
- Modify: `tests/api/nlq/test_tools_delegation.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/api/nlq/test_tools_delegation.py`:

```python
@pytest.mark.asyncio
async def test_handle_explore_entity_delegates() -> None:
    from api.nlq.tools import NLQToolRunner

    runner = NLQToolRunner(neo4j_driver=object(), pg_pool=object(), redis=object())

    with patch(
        "common.agent_tools.get_artist_details",
        new=AsyncMock(return_value={"id": "1", "name": "Kraftwerk", "_entity_type": "artist"}),
    ) as mock:
        result = await runner._handle_explore_entity({"type": "artist", "name": "Kraftwerk"}, None)

    assert result["name"] == "Kraftwerk"
    mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_get_collaborators_delegates() -> None:
    from api.nlq.tools import NLQToolRunner

    runner = NLQToolRunner(neo4j_driver=object(), pg_pool=object(), redis=object())

    with patch(
        "common.agent_tools.get_collaborators",
        new=AsyncMock(return_value={"collaborators": [{"id": "2"}]}),
    ) as mock:
        result = await runner._handle_get_collaborators({"artist_id": "1", "limit": 10}, None)

    assert result == {"collaborators": [{"id": "2"}]}
    mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_get_trends_delegates() -> None:
    from api.nlq.tools import NLQToolRunner

    runner = NLQToolRunner(neo4j_driver=object(), pg_pool=object(), redis=object())

    with patch(
        "common.agent_tools.get_trends",
        new=AsyncMock(return_value={"trends": []}),
    ) as mock:
        result = await runner._handle_get_trends({"type": "artist", "name": "Kraftwerk"}, None)

    assert result == {"trends": []}
    mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_get_graph_stats_delegates() -> None:
    from api.nlq.tools import NLQToolRunner

    runner = NLQToolRunner(neo4j_driver=object(), pg_pool=object(), redis=object())

    with patch(
        "common.agent_tools.get_graph_stats",
        new=AsyncMock(return_value={"artists": 100}),
    ) as mock:
        result = await runner._handle_get_graph_stats({}, None)

    assert result == {"artists": 100}
    mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_get_genre_tree_delegates() -> None:
    from api.nlq.tools import NLQToolRunner

    runner = NLQToolRunner(neo4j_driver=object(), pg_pool=object(), redis=object())

    with patch(
        "common.agent_tools.get_genre_tree",
        new=AsyncMock(return_value={"genres": []}),
    ) as mock:
        result = await runner._handle_get_genre_tree({}, None)

    assert result == {"genres": []}
    mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_search_delegates() -> None:
    from api.nlq.tools import NLQToolRunner

    runner = NLQToolRunner(neo4j_driver=object(), pg_pool=object(), redis=object())

    with patch(
        "common.agent_tools.search",
        new=AsyncMock(return_value={"results": []}),
    ) as mock:
        result = await runner._handle_search({"q": "Kraftwerk"}, None)

    assert result == {"results": []}
    mock.assert_awaited_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/nlq/test_tools_delegation.py -v`
Expected: 6 new tests fail; `_handle_explore_entity` etc. still use `api.queries` directly.

- [ ] **Step 3: Write minimal implementation**

Replace handler bodies in `api/nlq/tools.py` (keep signatures identical):

```python
    async def _handle_search(self, params: dict[str, Any], _user_id: str | None) -> dict[str, Any]:
        from api.queries import search_queries  # noqa: PLC0415
        from common import agent_tools  # noqa: PLC0415

        return await agent_tools.search(
            pool=self._pool,
            redis=self._redis,
            q=params.get("q", ""),
            types=params.get("types", ["artist", "label", "master", "release"]),
            genres=params.get("genres", []),
            year_min=params.get("year_min"),
            year_max=params.get("year_max"),
            limit=params.get("limit", 10),
            offset=params.get("offset", 0),
            search_fn=search_queries.execute_search,
        )

    async def _handle_explore_entity(self, params: dict[str, Any], _user_id: str | None) -> dict[str, Any]:
        from api.queries import neo4j_queries  # noqa: PLC0415
        from common import agent_tools  # noqa: PLC0415

        entity_type = params.get("type", "artist")
        handler = neo4j_queries.EXPLORE_DISPATCH.get(entity_type)
        if handler is None:
            return {"error": f"Unknown explore type: {entity_type}"}

        tool_fn = {
            "artist": agent_tools.get_artist_details,
            "label": agent_tools.get_label_details,
            "genre": agent_tools.get_genre_details,
            "style": agent_tools.get_style_details,
            "release": agent_tools.get_release_details,
        }.get(entity_type)
        if tool_fn is None:
            return {"error": f"Unknown explore type: {entity_type}"}

        return await tool_fn(driver=self._driver, name=params.get("name", ""), handler=handler)

    async def _handle_get_collaborators(self, params: dict[str, Any], _user_id: str | None) -> dict[str, Any]:
        from api.queries import collaborator_queries  # noqa: PLC0415
        from common import agent_tools  # noqa: PLC0415

        return await agent_tools.get_collaborators(
            driver=self._driver,
            artist_id=params.get("artist_id", ""),
            limit=params.get("limit", 20),
            collaborators_fn=collaborator_queries.get_collaborators,
        )

    async def _handle_get_trends(self, params: dict[str, Any], _user_id: str | None) -> dict[str, Any]:
        from api.queries import neo4j_queries  # noqa: PLC0415
        from common import agent_tools  # noqa: PLC0415

        entity_type = params.get("type", "artist")
        handler = neo4j_queries.TRENDS_DISPATCH.get(entity_type)
        return await agent_tools.get_trends(
            driver=self._driver,
            entity_type=entity_type,
            name=params.get("name", ""),
            handler=handler,
        )

    async def _handle_get_genre_tree(self, _params: dict[str, Any], _user_id: str | None) -> dict[str, Any]:
        from api.queries import genre_tree_queries  # noqa: PLC0415
        from common import agent_tools  # noqa: PLC0415

        return await agent_tools.get_genre_tree(driver=self._driver, tree_fn=genre_tree_queries.get_genre_tree)

    async def _handle_get_graph_stats(self, _params: dict[str, Any], _user_id: str | None) -> dict[str, Any]:
        from api.queries import neo4j_queries  # noqa: PLC0415
        from common import agent_tools  # noqa: PLC0415

        return await agent_tools.get_graph_stats(driver=self._driver, stats_fn=neo4j_queries.get_graph_stats)
```

Leave `_handle_autocomplete`, `_handle_get_similar_artists`, `_handle_get_label_dna`, and the collection-gated handlers (`_handle_get_collection_gaps`, `_handle_get_taste_fingerprint`, `_handle_get_taste_blindspots`, `_handle_get_collection_stats`) as-is — they stay local to `api/nlq` for now because they pull in query logic we're not extracting in this PR.

- [ ] **Step 4: Run all tests to verify**

Run: `uv run pytest tests/api/nlq/ tests/common/test_agent_tools* -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add api/nlq/tools.py tests/api/nlq/test_tools_delegation.py
git commit -m "refactor(api/nlq): delegate remaining _handle_* methods to common.agent_tools"
```

---

## Phase 3 — Action contract in the NLQ engine

Extend the NLQ engine so the agent can return a list of structured UI actions alongside its text summary. Actions are validated server-side with a Pydantic discriminated union.

### Task 7: Define the `Action` schema

**Files:**
- Create: `api/nlq/actions.py`
- Create: `tests/api/nlq/test_actions.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/api/nlq/test_actions.py
"""Tests for NLQ action schema validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_seed_graph_action_validates() -> None:
    from api.nlq.actions import parse_action

    action = parse_action({"type": "seed_graph", "entities": [{"name": "Kraftwerk", "entity_type": "artist"}]})
    assert action.type == "seed_graph"
    assert action.entities[0].name == "Kraftwerk"
    assert action.entities[0].entity_type == "artist"


def test_switch_pane_action_validates() -> None:
    from api.nlq.actions import parse_action

    action = parse_action({"type": "switch_pane", "pane": "trends"})
    assert action.type == "switch_pane"
    assert action.pane == "trends"


def test_switch_pane_rejects_unknown_pane() -> None:
    from api.nlq.actions import parse_action

    with pytest.raises(ValidationError):
        parse_action({"type": "switch_pane", "pane": "not_a_real_pane"})


def test_unknown_action_type_raises() -> None:
    from api.nlq.actions import parse_action

    with pytest.raises(ValidationError):
        parse_action({"type": "time_travel", "year": 1999})


def test_seed_graph_entity_name_length_cap() -> None:
    from api.nlq.actions import parse_action

    with pytest.raises(ValidationError):
        parse_action({"type": "seed_graph", "entities": [{"name": "x" * 257, "entity_type": "artist"}]})


def test_parse_action_list_drops_malformed() -> None:
    from api.nlq.actions import parse_action_list

    raw = [
        {"type": "seed_graph", "entities": [{"name": "Kraftwerk", "entity_type": "artist"}]},
        {"type": "nonsense"},
        {"type": "focus_node", "name": "Kraftwerk", "entity_type": "artist"},
    ]
    actions = parse_action_list(raw)
    assert len(actions) == 2
    assert actions[0].type == "seed_graph"
    assert actions[1].type == "focus_node"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/nlq/test_actions.py -v`
Expected: `ModuleNotFoundError: No module named 'api.nlq.actions'`

- [ ] **Step 3: Write minimal implementation**

```python
# api/nlq/actions.py
"""NLQ action schemas and validation."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

import structlog
from pydantic import BaseModel, Field, TypeAdapter, ValidationError


logger = structlog.get_logger(__name__)

_MAX_FIELD_LEN = 256

EntityType = Literal["artist", "label", "genre", "style", "release"]
PaneName = Literal["explore", "trends", "insights", "genres", "credits"]
FilterDimension = Literal["year", "genre", "label"]


class _SeedEntity(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=_MAX_FIELD_LEN)]
    entity_type: EntityType


class SeedGraphAction(BaseModel):
    type: Literal["seed_graph"] = "seed_graph"
    entities: list[_SeedEntity]
    replace: bool = False


class HighlightPathAction(BaseModel):
    type: Literal["highlight_path"] = "highlight_path"
    nodes: list[Annotated[str, Field(min_length=1, max_length=_MAX_FIELD_LEN)]]


class FocusNodeAction(BaseModel):
    type: Literal["focus_node"] = "focus_node"
    name: Annotated[str, Field(min_length=1, max_length=_MAX_FIELD_LEN)]
    entity_type: EntityType


class FilterGraphAction(BaseModel):
    type: Literal["filter_graph"] = "filter_graph"
    by: FilterDimension
    value: Annotated[str | int | tuple[int, int], Field()]


class FindPathAction(BaseModel):
    type: Literal["find_path"] = "find_path"
    from_name: Annotated[str, Field(min_length=1, max_length=_MAX_FIELD_LEN, alias="from")]
    to_name: Annotated[str, Field(min_length=1, max_length=_MAX_FIELD_LEN, alias="to")]
    from_type: EntityType
    to_type: EntityType

    model_config = {"populate_by_name": True}


class ShowCreditsAction(BaseModel):
    type: Literal["show_credits"] = "show_credits"
    name: Annotated[str, Field(min_length=1, max_length=_MAX_FIELD_LEN)]
    entity_type: EntityType


class SwitchPaneAction(BaseModel):
    type: Literal["switch_pane"] = "switch_pane"
    pane: PaneName


class OpenInsightTileAction(BaseModel):
    type: Literal["open_insight_tile"] = "open_insight_tile"
    tile_id: Annotated[str, Field(min_length=1, max_length=_MAX_FIELD_LEN)]


class SetTrendRangeAction(BaseModel):
    type: Literal["set_trend_range"] = "set_trend_range"
    from_year: Annotated[str, Field(min_length=4, max_length=10, alias="from")]
    to_year: Annotated[str, Field(min_length=4, max_length=10, alias="to")]

    model_config = {"populate_by_name": True}


class SuggestFollowupsAction(BaseModel):
    type: Literal["suggest_followups"] = "suggest_followups"
    queries: list[Annotated[str, Field(min_length=1, max_length=_MAX_FIELD_LEN)]]


Action = Annotated[
    Union[
        SeedGraphAction,
        HighlightPathAction,
        FocusNodeAction,
        FilterGraphAction,
        FindPathAction,
        ShowCreditsAction,
        SwitchPaneAction,
        OpenInsightTileAction,
        SetTrendRangeAction,
        SuggestFollowupsAction,
    ],
    Field(discriminator="type"),
]

_action_adapter: TypeAdapter[Action] = TypeAdapter(Action)


def parse_action(raw: dict[str, Any]) -> Action:
    """Parse and validate a single action. Raises ValidationError on failure."""
    return _action_adapter.validate_python(raw)


def parse_action_list(raw: list[dict[str, Any]]) -> list[Action]:
    """Parse a list of raw action dicts, dropping malformed entries with a warning."""
    parsed: list[Action] = []
    for item in raw:
        try:
            parsed.append(parse_action(item))
        except ValidationError as exc:
            logger.warning("⚠️ dropping malformed NLQ action", item=item, errors=exc.errors())
    return parsed
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/api/nlq/test_actions.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add api/nlq/actions.py tests/api/nlq/test_actions.py
git commit -m "feat(api/nlq): add Action discriminated-union schema"
```

### Task 8: Extend `NLQResult` with `actions[]` and wire through the engine

**Files:**
- Modify: `api/nlq/engine.py`
- Create: `tests/api/nlq/test_engine_actions.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/api/nlq/test_engine_actions.py
"""Tests that NLQEngine returns an action list in NLQResult."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_result_includes_actions_when_agent_emits_them() -> None:
    from api.nlq.actions import SeedGraphAction
    from api.nlq.config import NLQConfig
    from api.nlq.engine import NLQContext, NLQEngine

    first = MagicMock()
    first.stop_reason = "tool_use"
    first.content = [MagicMock(type="tool_use", id="tu1", name="search", input={"q": "Kraftwerk"})]

    final = MagicMock()
    final.stop_reason = "end_turn"
    final.content = [
        MagicMock(
            type="text",
            text='Here is the answer.\n\n<!--actions:[{"type":"seed_graph","entities":[{"name":"Kraftwerk","entity_type":"artist"}]}]-->',
        )
    ]

    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock(side_effect=[first, final])

    tool_runner = MagicMock()
    tool_runner.execute = AsyncMock(return_value={"results": []})
    tool_runner.extract_entities = MagicMock(return_value=[])

    engine = NLQEngine(NLQConfig(), client, tool_runner)
    result = await engine.run("Tell me about Kraftwerk", NLQContext())

    assert result.summary == "Here is the answer."
    assert len(result.actions) == 1
    assert isinstance(result.actions[0], SeedGraphAction)


@pytest.mark.asyncio
async def test_result_has_empty_actions_when_none_emitted() -> None:
    from api.nlq.config import NLQConfig
    from api.nlq.engine import NLQContext, NLQEngine

    final = MagicMock()
    final.stop_reason = "end_turn"
    final.content = [MagicMock(type="text", text="Just a text answer.")]

    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock(return_value=final)

    engine = NLQEngine(NLQConfig(), client, MagicMock())
    result = await engine.run("Hi", NLQContext())

    assert result.summary == "Just a text answer."
    assert result.actions == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/nlq/test_engine_actions.py -v`
Expected: `AttributeError: 'NLQResult' object has no attribute 'actions'`

- [ ] **Step 3: Write minimal implementation**

In `api/nlq/engine.py`:

Add the import at the top:

```python
import re

from api.nlq.actions import Action, parse_action_list
```

Extend `NLQResult`:

```python
@dataclass
class NLQResult:
    """Result returned by the NLQ engine."""

    summary: str
    entities: list[dict[str, Any]] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
```

Add the helper at the bottom of the file:

```python
_ACTIONS_MARKER_RE = re.compile(r"<!--actions:(\[.*?\])-->", re.DOTALL)


def _extract_actions(text: str) -> tuple[str, list[Action]]:
    """Strip an optional ``<!--actions:[...]-->`` marker from the agent's text.

    The system prompt instructs the agent to append its structured UI actions
    inside this marker at the end of its response. We strip the marker from the
    user-visible summary and parse the JSON list.
    """
    match = _ACTIONS_MARKER_RE.search(text)
    if not match:
        return text, []
    raw_json = match.group(1)
    cleaned = _ACTIONS_MARKER_RE.sub("", text).strip()
    try:
        import json  # noqa: PLC0415

        raw = json.loads(raw_json)
        if not isinstance(raw, list):
            return cleaned, []
        return cleaned, parse_action_list(raw)
    except (json.JSONDecodeError, ValueError):
        logger.warning("⚠️ NLQ actions marker contained invalid JSON")
        return cleaned, []
```

Update `NLQEngine._build_result` to parse actions from the summary:

```python
    def _build_result(
        self,
        summary: str,
        entities: list[dict[str, Any]],
        tools_used: list[str],
    ) -> NLQResult:
        """Build an NLQResult with guardrails, deduplication, and action extraction."""
        if not tools_used:
            summary = _apply_off_topic_guardrail(summary)
        cleaned_summary, actions = _extract_actions(summary)
        deduped = _deduplicate_entities(entities)
        return NLQResult(summary=cleaned_summary, entities=deduped, tools_used=tools_used, actions=actions)
```

Update the non-tool-stop branch at `engine.py:163-169` to also use `_build_result`:

```python
            if not tool_results:
                summary = _extract_text(response)
                return self._build_result(summary, entities, tools_used)
```

Extend the system prompt with the actions instruction. Append this block to `_SYSTEM_PROMPT`:

```python
_ACTIONS_INSTRUCTION = """

When your answer should mutate the UI, append a machine-readable actions block \
at the end of your response, formatted exactly as:

    <!--actions:[{"type":"seed_graph","entities":[{"name":"Kraftwerk","entity_type":"artist"}]}]-->

The marker is invisible to the user; the UI strips it out. Supported action \
types: seed_graph, highlight_path, focus_node, filter_graph, find_path, \
show_credits, switch_pane, open_insight_tile, set_trend_range, suggest_followups. \
Only emit actions that directly follow from the user's question."""

_SYSTEM_PROMPT = _SYSTEM_PROMPT + _ACTIONS_INSTRUCTION
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/nlq/test_engine_actions.py tests/api/nlq/test_actions.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add api/nlq/engine.py tests/api/nlq/test_engine_actions.py
git commit -m "feat(api/nlq): NLQResult carries agent-emitted UI actions"
```

### Task 9: Emit `actions` SSE event in the router

**Files:**
- Modify: `api/routers/nlq.py:144-196`
- Create: `tests/api/test_nlq_sse.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_nlq_sse.py
"""Tests for NLQ SSE streaming including the actions event."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_sse_emits_actions_event_before_result() -> None:
    from api.nlq.actions import SeedGraphAction, _SeedEntity  # type: ignore[attr-defined]
    from api.nlq.engine import NLQResult
    from api.routers import nlq as nlq_router

    engine = MagicMock()
    engine.run = AsyncMock(
        return_value=NLQResult(
            summary="Here is the answer.",
            entities=[],
            tools_used=["search"],
            actions=[SeedGraphAction(entities=[_SeedEntity(name="Kraftwerk", entity_type="artist")])],
        )
    )
    nlq_router._engine = engine

    response = nlq_router._stream_response("Tell me about Kraftwerk", None, None)
    events: list[dict[str, str]] = []
    async for event in response.body_iterator:
        events.append(event)

    kinds = [e.get("event") for e in events]
    assert "actions" in kinds
    assert "result" in kinds
    actions_idx = kinds.index("actions")
    result_idx = kinds.index("result")
    assert actions_idx < result_idx
    actions_event = events[actions_idx]
    payload = json.loads(actions_event["data"])
    assert payload["actions"][0]["type"] == "seed_graph"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_nlq_sse.py -v`
Expected: FAIL — router does not emit an `actions` event today.

- [ ] **Step 3: Write minimal implementation**

Modify `_stream_response` in `api/routers/nlq.py` so that after the engine returns, it emits an `actions` event before the `result` event:

```python
        try:
            result = await engine_task
        except Exception as exc:
            logger.error("❌ NLQ engine error", error=str(exc), exc_info=True)
            yield {"event": "error", "data": json.dumps({"error": "An internal error occurred"})}
            return

        yield {
            "event": "actions",
            "data": json.dumps(
                {"actions": [action.model_dump(by_alias=True, mode="json") for action in result.actions]}
            ),
        }

        response_data = {
            "query": query,
            "summary": result.summary,
            "entities": result.entities,
            "tools_used": result.tools_used,
            "cached": False,
        }
        yield {"event": "result", "data": json.dumps(response_data)}
```

Also update the non-SSE JSON response branch to include `actions`:

```python
    response_data = {
        "query": body.query,
        "summary": result.summary,
        "entities": result.entities,
        "tools_used": result.tools_used,
        "actions": [action.model_dump(by_alias=True, mode="json") for action in result.actions],
        "cached": False,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_nlq_sse.py -v`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add api/routers/nlq.py tests/api/test_nlq_sse.py
git commit -m "feat(api/routers/nlq): emit actions SSE event before result"
```

---

## Phase 4 — Suggestions endpoint

Add `GET /api/nlq/suggestions` with template-based suggestions and a 5-minute Redis cache.

### Task 10: Suggestion template engine

**Files:**
- Create: `api/nlq/suggestions.py`
- Create: `tests/api/nlq/test_suggestions.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/api/nlq/test_suggestions.py
"""Tests for NLQ template-based suggestions."""

from __future__ import annotations


def test_suggestions_explore_no_focus_uses_default_set() -> None:
    from api.nlq.suggestions import build_suggestions

    result = build_suggestions(pane="explore", focus=None, focus_type=None)
    assert len(result) >= 4
    assert all(isinstance(q, str) for q in result)


def test_suggestions_explore_with_artist_focus_substitutes_name() -> None:
    from api.nlq.suggestions import build_suggestions

    result = build_suggestions(pane="explore", focus="Kraftwerk", focus_type="artist")
    assert any("Kraftwerk" in q for q in result)
    assert len(result) >= 4
    assert len(result) <= 6


def test_suggestions_unknown_pane_falls_back_to_default() -> None:
    from api.nlq.suggestions import build_suggestions

    result = build_suggestions(pane="nonexistent", focus=None, focus_type=None)
    assert len(result) >= 4


def test_suggestions_focus_length_cap() -> None:
    from api.nlq.suggestions import build_suggestions

    oversized = "x" * 1000
    result = build_suggestions(pane="explore", focus=oversized, focus_type="artist")
    assert all(len(q) <= 256 for q in result)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/nlq/test_suggestions.py -v`
Expected: `ModuleNotFoundError: No module named 'api.nlq.suggestions'`

- [ ] **Step 3: Write minimal implementation**

```python
# api/nlq/suggestions.py
"""Template-based suggestion engine for the NLQ Ask pill."""

from __future__ import annotations


_MAX_FOCUS_LEN = 120
_MAX_SUGGESTION_LEN = 256

_DEFAULT_EXPLORE = [
    "How are Kraftwerk and Afrika Bambaataa connected?",
    "What genres emerged in the 1990s?",
    "Most prolific electronic label",
    "Show the shortest path from David Bowie to Daft Punk",
]

_DEFAULT_TRENDS = [
    "Which labels grew the most in 2024?",
    "Show the trend of techno releases over the last decade",
    "Peak year for Detroit techno",
    "Which genres are declining since 2020?",
]

_DEFAULT_INSIGHTS = [
    "Biggest labels of 2024",
    "Most connected artists overall",
    "Top collaborators in electronic music",
    "Rarest releases on Warp Records",
]

_DEFAULT_GENRES = [
    "What genres split off from house in the 1990s?",
    "Parent genre of jungle",
    "Sub-genres of ambient",
    "Genres that combine jazz and electronic",
]

_DEFAULT_CREDITS = [
    "Who produced 'Computer World'?",
    "Engineers credited on Kraftwerk releases",
    "Writers who collaborated with Brian Eno",
    "Vocalists credited on Massive Attack releases",
]

_PANE_DEFAULTS: dict[str, list[str]] = {
    "explore": _DEFAULT_EXPLORE,
    "trends": _DEFAULT_TRENDS,
    "insights": _DEFAULT_INSIGHTS,
    "genres": _DEFAULT_GENRES,
    "credits": _DEFAULT_CREDITS,
}

_ARTIST_TEMPLATES = [
    "Who influenced {focus}?",
    "What labels has {focus} released on?",
    "{focus}'s collaborators in the 70s",
    "Most prolific decade for {focus}",
    "How are {focus} and Kraftwerk connected?",
]

_LABEL_TEMPLATES = [
    "Biggest artists on {focus}",
    "Genres most associated with {focus}",
    "Peak year for {focus}",
    "Artists who moved from {focus} to a rival label",
]

_GENRE_TEMPLATES = [
    "Who are the pioneers of {focus}?",
    "Sub-genres of {focus}",
    "Labels most associated with {focus}",
    "How did {focus} evolve between 1990 and 2010?",
]


def build_suggestions(
    *,
    pane: str,
    focus: str | None,
    focus_type: str | None,
) -> list[str]:
    """Return 4-6 suggested queries for the given context."""
    if focus is None or focus_type is None:
        return _PANE_DEFAULTS.get(pane, _DEFAULT_EXPLORE)[:6]

    focus_trimmed = focus.strip()[:_MAX_FOCUS_LEN]
    if not focus_trimmed:
        return _PANE_DEFAULTS.get(pane, _DEFAULT_EXPLORE)[:6]

    templates = {
        "artist": _ARTIST_TEMPLATES,
        "label": _LABEL_TEMPLATES,
        "genre": _GENRE_TEMPLATES,
        "style": _GENRE_TEMPLATES,
    }.get(focus_type, _ARTIST_TEMPLATES)

    rendered = [t.format(focus=focus_trimmed) for t in templates]
    capped = [q[:_MAX_SUGGESTION_LEN] for q in rendered]
    return capped[:6]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/nlq/test_suggestions.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add api/nlq/suggestions.py tests/api/nlq/test_suggestions.py
git commit -m "feat(api/nlq): template-based suggestion engine"
```

### Task 11: `/api/nlq/suggestions` endpoint with Redis caching

**Files:**
- Modify: `api/routers/nlq.py`
- Create: `tests/api/test_nlq_suggestions_endpoint.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_nlq_suggestions_endpoint.py
"""Tests for GET /api/nlq/suggestions."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_suggestions_endpoint_returns_chips() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.nlq.config import NLQConfig
    from api.routers import nlq as nlq_router

    nlq_router.configure(NLQConfig(), engine=None, redis=None, jwt_secret=None)
    app = FastAPI()
    app.include_router(nlq_router.router)

    with TestClient(app) as client:
        response = client.get("/api/nlq/suggestions", params={"pane": "explore"})
        assert response.status_code == 200
        body = response.json()
        assert "suggestions" in body
        assert len(body["suggestions"]) >= 4


@pytest.mark.asyncio
async def test_suggestions_endpoint_uses_redis_cache() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.nlq.config import NLQConfig
    from api.routers import nlq as nlq_router

    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock()

    nlq_router.configure(NLQConfig(), engine=None, redis=redis, jwt_secret=None)
    app = FastAPI()
    app.include_router(nlq_router.router)

    with TestClient(app) as client:
        response = client.get("/api/nlq/suggestions", params={"pane": "explore", "focus": "Kraftwerk", "focus_type": "artist"})
        assert response.status_code == 200

    redis.get.assert_awaited_once()
    redis.setex.assert_awaited_once()
    args = redis.setex.call_args.args
    assert 300 in args  # TTL is 5 minutes
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_nlq_suggestions_endpoint.py -v`
Expected: 404 — endpoint does not exist yet.

- [ ] **Step 3: Write minimal implementation**

Add to `api/routers/nlq.py`:

```python
from api.nlq.suggestions import build_suggestions

_SUGGESTIONS_CACHE_TTL = 300  # 5 minutes


@router.get("/api/nlq/suggestions")
@limiter.limit("100/minute")
async def nlq_suggestions(
    request: Request,
    pane: str = "explore",
    focus: str | None = None,
    focus_type: str | None = None,
) -> JSONResponse:
    """Return dynamic suggested queries for the Ask pill."""
    cache_key = f"nlq:suggest:{pane}:{focus or ''}:{focus_type or ''}"
    if _redis is not None:
        try:
            cached = await _redis.get(cache_key)
            if cached is not None:
                return JSONResponse(content=json.loads(cached))
        except Exception:
            logger.debug("⚠️ NLQ suggestions cache read failed", key=cache_key)

    suggestions = build_suggestions(pane=pane, focus=focus, focus_type=focus_type)
    payload = {"suggestions": suggestions}

    if _redis is not None:
        try:
            await _redis.setex(cache_key, _SUGGESTIONS_CACHE_TTL, json.dumps(payload))
        except Exception:
            logger.debug("⚠️ NLQ suggestions cache write failed", key=cache_key)

    return JSONResponse(content=payload)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_nlq_suggestions_endpoint.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add api/routers/nlq.py tests/api/test_nlq_suggestions_endpoint.py
git commit -m "feat(api/routers/nlq): add /api/nlq/suggestions endpoint"
```

---

## Phase 5 — MCP server refactor

Rewrite each `@mcp.tool()` in `mcp-server/mcp_server/server.py` to delegate to `common.agent_tools`. Existing behavior preserved — Claude Desktop should see no change.

### Task 12: Refactor MCP `find_path` to shared tool

**Files:**
- Modify: `mcp-server/mcp_server/server.py` (the `find_path` block near line 263)
- Create: `tests/mcp-server/test_mcp_tools_regression.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/mcp-server/test_mcp_tools_regression.py
"""Regression tests: MCP tools must return the same shape after refactor."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_mcp_find_path_calls_shared_tool() -> None:
    with patch("common.agent_tools.find_path", new=AsyncMock(return_value={"path": [1, 2]})) as mock:
        from mcp_server.server import find_path as mcp_find_path

        ctx = AsyncMock()
        ctx.request_context.lifespan_context = AsyncMock()

        result = await mcp_find_path(
            from_id="Kraftwerk",
            from_type="artist",
            to_id="Bambaataa",
            to_type="artist",
            ctx=ctx,
        )

        assert result == {"path": [1, 2]} or result.get("path") == [1, 2]
        mock.assert_awaited_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/mcp-server/test_mcp_tools_regression.py -v`
Expected: FAIL — current MCP `find_path` calls `_api_post` directly.

- [ ] **Step 3: Write minimal implementation**

In `mcp-server/mcp_server/server.py`, introduce a helper:

```python
async def _call_shared_find_path(app: AppContext, **kwargs: Any) -> dict[str, Any]:
    """Delegate to common.agent_tools.find_path using API-backed resolvers."""
    from common import agent_tools

    async def resolve_name(_driver: Any, name: str, entity_type: str) -> dict[str, Any] | None:
        resp = await _api_get(app, f"/api/{entity_type}/{name}")
        if "error" in resp:
            return None
        return {"id": resp.get("id", "")}

    async def find_shortest_path_fn(**params: Any) -> dict[str, Any] | None:
        return await _api_post(app, "/api/path", json_data=params)

    return await agent_tools.find_path(
        driver=None,
        resolve_name=resolve_name,
        find_shortest_path_fn=find_shortest_path_fn,
        **kwargs,
    )
```

Replace the `find_path` tool body:

```python
@mcp.tool()
async def find_path(
    from_id: str,
    from_type: str,
    to_id: str,
    to_type: str,
    max_depth: int = 6,
    ctx: Context = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Find the shortest path between two entities in the graph."""
    app = _ctx(ctx)
    return await _call_shared_find_path(
        app,
        from_name=from_id,
        from_type=from_type,
        to_name=to_id,
        to_type=to_type,
        max_depth=max_depth,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/mcp-server/test_mcp_tools_regression.py -v`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add mcp-server/mcp_server/server.py tests/mcp-server/test_mcp_tools_regression.py
git commit -m "refactor(mcp-server): route find_path through common.agent_tools"
```

### Task 13: Verify all MCP tool names still exported after refactor

**Files:**
- Modify: `tests/mcp-server/test_mcp_tools_regression.py`

- [ ] **Step 1: Add export test**

```python
@pytest.mark.asyncio
async def test_mcp_tool_names_still_exported() -> None:
    from mcp_server.server import (
        find_path,
        get_artist_details,
        get_collaborators,
        get_genre_details,
        get_genre_tree,
        get_graph_stats,
        get_label_details,
        get_release_details,
        get_style_details,
        get_trends,
        nlq_query,
        search,
    )

    for fn in (
        find_path,
        get_artist_details,
        get_collaborators,
        get_genre_details,
        get_genre_tree,
        get_graph_stats,
        get_label_details,
        get_release_details,
        get_style_details,
        get_trends,
        nlq_query,
        search,
    ):
        assert callable(fn)
```

- [ ] **Step 2: Run test**

Run: `uv run pytest tests/mcp-server/test_mcp_tools_regression.py::test_mcp_tool_names_still_exported -v`
Expected: PASS if all names are still exported.

- [ ] **Step 3: If failing, restore any missing export and re-run**

- [ ] **Step 4: Run full MCP regression file**

Run: `uv run pytest tests/mcp-server/ -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tests/mcp-server/test_mcp_tools_regression.py
git commit -m "test(mcp-server): assert public tool exports"
```

---

## Phase 6 — Frontend pill component

### Task 14: Scaffold `nlq-pill.js` with collapsed-state render and test harness

**Files:**
- Create: `explore/static/js/nlq-pill.js`
- Create: `explore/__tests__/nlq-pill.test.js`
- Modify: `explore/static/index.html` (add a mount point div near the bottom of body)

- [ ] **Step 1: Write the failing test**

```javascript
// explore/__tests__/nlq-pill.test.js
import { describe, it, expect, beforeEach } from 'vitest';
import { NlqPill } from '../static/js/nlq-pill.js';

describe('NlqPill', () => {
    beforeEach(() => {
        document.body.replaceChildren();
        const mount = document.createElement('div');
        mount.id = 'nlqPillMount';
        document.body.appendChild(mount);
    });

    it('mounts a collapsed pill by default', () => {
        const pill = new NlqPill({ mountId: 'nlqPillMount' });
        pill.mount();
        const el = document.querySelector('[data-testid="nlq-pill-collapsed"]');
        expect(el).not.toBeNull();
        expect(el.textContent).toContain('Ask the graph');
    });

    it('shows keyboard hint', () => {
        const pill = new NlqPill({ mountId: 'nlqPillMount' });
        pill.mount();
        const kbd = document.querySelector('[data-testid="nlq-pill-collapsed"] kbd');
        expect(kbd).not.toBeNull();
        expect(kbd.textContent).toMatch(/⌘K|Ctrl\+K/);
    });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd explore && npm test -- nlq-pill`
Expected: module missing.

- [ ] **Step 3: Write minimal implementation**

```javascript
// explore/static/js/nlq-pill.js
/**
 * Global floating Ask pill — state machine: collapsed → expanded → loading → summary.
 */

export class NlqPill {
    constructor({ mountId = 'nlqPillMount' } = {}) {
        this.mountId = mountId;
        this.state = 'collapsed';
        this.root = null;
    }

    mount() {
        const mount = document.getElementById(this.mountId);
        if (!mount) return;
        this.root = document.createElement('div');
        this.root.className = 'nlq-pill-root';
        mount.appendChild(this.root);
        this._render();
    }

    _render() {
        if (!this.root) return;
        while (this.root.firstChild) this.root.removeChild(this.root.firstChild);
        if (this.state === 'collapsed') {
            this._renderCollapsed();
        }
    }

    _renderCollapsed() {
        const pill = document.createElement('button');
        pill.type = 'button';
        pill.setAttribute('data-testid', 'nlq-pill-collapsed');
        pill.className = 'nlq-pill-collapsed';
        const sparkle = document.createElement('span');
        sparkle.className = 'nlq-pill-sparkle';
        sparkle.textContent = '✨';
        const label = document.createElement('span');
        label.textContent = ' Ask the graph ';
        const kbd = document.createElement('kbd');
        kbd.textContent = '⌘K';
        pill.appendChild(sparkle);
        pill.appendChild(label);
        pill.appendChild(kbd);
        this.root.appendChild(pill);
    }
}
```

Also add the mount point to `explore/static/index.html` (just before `</body>`):

```html
<div id="nlqPillMount"></div>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd explore && npm test -- nlq-pill`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add explore/static/js/nlq-pill.js explore/__tests__/nlq-pill.test.js explore/static/index.html
git commit -m "feat(explore): scaffold NlqPill component with collapsed state"
```

### Task 15: Expand / collapse transitions + keyboard shortcut

**Files:**
- Modify: `explore/static/js/nlq-pill.js`
- Modify: `explore/__tests__/nlq-pill.test.js`

- [ ] **Step 1: Write the failing test**

Append to `explore/__tests__/nlq-pill.test.js`:

```javascript
import { fireEvent } from '@testing-library/dom';

describe('NlqPill interactions', () => {
    beforeEach(() => {
        document.body.replaceChildren();
        const mount = document.createElement('div');
        mount.id = 'nlqPillMount';
        document.body.appendChild(mount);
    });

    it('expands on pill click', () => {
        const pill = new NlqPill({ mountId: 'nlqPillMount' });
        pill.mount();
        document.querySelector('[data-testid="nlq-pill-collapsed"]').click();
        expect(pill.state).toBe('expanded');
        expect(document.querySelector('[data-testid="nlq-pill-expanded"]')).not.toBeNull();
    });

    it('expands on ⌘K', () => {
        const pill = new NlqPill({ mountId: 'nlqPillMount' });
        pill.mount();
        fireEvent.keyDown(document, { key: 'k', metaKey: true });
        expect(pill.state).toBe('expanded');
    });

    it('expands on ? when no input focused', () => {
        const pill = new NlqPill({ mountId: 'nlqPillMount' });
        pill.mount();
        fireEvent.keyDown(document, { key: '?' });
        expect(pill.state).toBe('expanded');
    });

    it('does NOT expand on ? when an input is focused', () => {
        const other = document.createElement('input');
        other.id = 'other';
        document.body.appendChild(other);
        const pill = new NlqPill({ mountId: 'nlqPillMount' });
        pill.mount();
        other.focus();
        fireEvent.keyDown(other, { key: '?' });
        expect(pill.state).toBe('collapsed');
    });

    it('collapses on Esc', () => {
        const pill = new NlqPill({ mountId: 'nlqPillMount' });
        pill.mount();
        pill.expand();
        fireEvent.keyDown(document, { key: 'Escape' });
        expect(pill.state).toBe('collapsed');
    });
});
```

Ensure `@testing-library/dom` is installed:

```bash
cd explore && npm install --save-dev @testing-library/dom
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd explore && npm test -- nlq-pill`
Expected: 5 new tests fail.

- [ ] **Step 3: Write minimal implementation**

Extend `nlq-pill.js`:

```javascript
    mount() {
        const mount = document.getElementById(this.mountId);
        if (!mount) return;
        this.root = document.createElement('div');
        this.root.className = 'nlq-pill-root';
        mount.appendChild(this.root);
        this._render();
        this._bindGlobalKeys();
    }

    _bindGlobalKeys() {
        document.addEventListener('keydown', (e) => {
            const target = e.target;
            const inInput = target && target.matches && target.matches('input, textarea, [contenteditable]');
            if (e.key === 'k' && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                this.expand();
            } else if (e.key === '?' && !inInput) {
                e.preventDefault();
                this.expand();
            } else if (e.key === 'Escape' && this.state === 'expanded') {
                e.preventDefault();
                this.collapse();
            }
        });
    }

    expand() {
        if (this.state === 'expanded') return;
        this.state = 'expanded';
        this._render();
        const input = this.root.querySelector('[data-testid="nlq-pill-input"]');
        if (input) input.focus();
    }

    collapse() {
        if (this.state === 'collapsed') return;
        this.state = 'collapsed';
        this._render();
    }

    _render() {
        if (!this.root) return;
        while (this.root.firstChild) this.root.removeChild(this.root.firstChild);
        if (this.state === 'collapsed') {
            this._renderCollapsed();
        } else if (this.state === 'expanded') {
            this._renderExpanded();
        }
    }

    _renderExpanded() {
        const card = document.createElement('div');
        card.setAttribute('data-testid', 'nlq-pill-expanded');
        card.className = 'nlq-pill-expanded';
        const input = document.createElement('input');
        input.type = 'text';
        input.setAttribute('data-testid', 'nlq-pill-input');
        input.className = 'nlq-pill-input';
        input.placeholder = 'Ask anything about the music graph…';
        input.maxLength = 500;
        card.appendChild(input);
        this.root.appendChild(card);
    }
```

Extend `_renderCollapsed` to hook the click:

```javascript
    _renderCollapsed() {
        const pill = document.createElement('button');
        pill.type = 'button';
        pill.setAttribute('data-testid', 'nlq-pill-collapsed');
        pill.className = 'nlq-pill-collapsed';
        pill.addEventListener('click', () => this.expand());
        const sparkle = document.createElement('span');
        sparkle.className = 'nlq-pill-sparkle';
        sparkle.textContent = '✨';
        const label = document.createElement('span');
        label.textContent = ' Ask the graph ';
        const kbd = document.createElement('kbd');
        kbd.textContent = '⌘K';
        pill.appendChild(sparkle);
        pill.appendChild(label);
        pill.appendChild(kbd);
        this.root.appendChild(pill);
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd explore && npm test -- nlq-pill`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add explore/static/js/nlq-pill.js explore/__tests__/nlq-pill.test.js explore/package.json explore/package-lock.json
git commit -m "feat(explore): NlqPill expand/collapse with keyboard shortcuts"
```

---

## Phase 7 — Suggestions & history chips

### Task 16: `nlq-suggestions.js` — fetch and render dynamic + recent chips

**Files:**
- Create: `explore/static/js/nlq-suggestions.js`
- Create: `explore/__tests__/nlq-suggestions.test.js`

- [ ] **Step 1: Write the failing test**

```javascript
// explore/__tests__/nlq-suggestions.test.js
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { NlqSuggestions } from '../static/js/nlq-suggestions.js';

describe('NlqSuggestions', () => {
    let container;

    beforeEach(() => {
        document.body.replaceChildren();
        container = document.createElement('div');
        document.body.appendChild(container);
        localStorage.clear();
    });

    it('renders fetched suggestions as chips', async () => {
        const fetchFn = vi.fn().mockResolvedValue({ suggestions: ['Query A', 'Query B'] });
        const sug = new NlqSuggestions({ container, fetchFn });
        await sug.render({ pane: 'explore', focus: 'Kraftwerk', focusType: 'artist' });
        const chips = container.querySelectorAll('[data-testid="nlq-suggestion-chip"]');
        expect(chips.length).toBe(2);
        expect(chips[0].textContent).toContain('Query A');
    });

    it('renders recent chips from localStorage', async () => {
        localStorage.setItem('nlq.history', JSON.stringify(['Recent 1', 'Recent 2']));
        const fetchFn = vi.fn().mockResolvedValue({ suggestions: [] });
        const sug = new NlqSuggestions({ container, fetchFn });
        await sug.render({ pane: 'explore' });
        const recents = container.querySelectorAll('[data-testid="nlq-recent-chip"]');
        expect(recents.length).toBe(2);
    });

    it('calls onPick with the chip text', async () => {
        const fetchFn = vi.fn().mockResolvedValue({ suggestions: ['Query A'] });
        const onPick = vi.fn();
        const sug = new NlqSuggestions({ container, fetchFn, onPick });
        await sug.render({ pane: 'explore' });
        container.querySelector('[data-testid="nlq-suggestion-chip"]').click();
        expect(onPick).toHaveBeenCalledWith('Query A');
    });

    it('falls back to recent only when fetch fails', async () => {
        localStorage.setItem('nlq.history', JSON.stringify(['Recent 1']));
        const fetchFn = vi.fn().mockRejectedValue(new Error('boom'));
        const sug = new NlqSuggestions({ container, fetchFn });
        await sug.render({ pane: 'explore' });
        expect(container.querySelectorAll('[data-testid="nlq-suggestion-chip"]').length).toBe(0);
        expect(container.querySelectorAll('[data-testid="nlq-recent-chip"]').length).toBe(1);
    });

    it('prepends a query via addRecent and caps history at 5', () => {
        NlqSuggestions.addRecent('Q1');
        NlqSuggestions.addRecent('Q2');
        NlqSuggestions.addRecent('Q3');
        NlqSuggestions.addRecent('Q4');
        NlqSuggestions.addRecent('Q5');
        NlqSuggestions.addRecent('Q6');
        const history = JSON.parse(localStorage.getItem('nlq.history'));
        expect(history).toEqual(['Q6', 'Q5', 'Q4', 'Q3', 'Q2']);
    });

    it('resets corrupt history silently', () => {
        localStorage.setItem('nlq.history', 'not json');
        const history = NlqSuggestions.loadRecent();
        expect(history).toEqual([]);
    });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd explore && npm test -- nlq-suggestions`
Expected: module missing.

- [ ] **Step 3: Write minimal implementation**

```javascript
// explore/static/js/nlq-suggestions.js
const STORAGE_KEY = 'nlq.history';
const HISTORY_CAP = 5;

export class NlqSuggestions {
    constructor({ container, fetchFn, onPick = null }) {
        this.container = container;
        this.fetchFn = fetchFn;
        this.onPick = onPick;
    }

    async render({ pane, focus = null, focusType = null }) {
        this._clear();
        let suggestions = [];
        try {
            const result = await this.fetchFn({ pane, focus, focusType });
            suggestions = result?.suggestions ?? [];
        } catch (err) {
            console.warn('🤷 NLQ suggestions fetch failed', err);
        }
        this._renderChipRow('Suggested for you', suggestions, 'nlq-suggestion-chip');
        const recent = NlqSuggestions.loadRecent();
        this._renderChipRow('Recent', recent, 'nlq-recent-chip');
    }

    _clear() {
        while (this.container.firstChild) this.container.removeChild(this.container.firstChild);
    }

    _renderChipRow(label, items, testId) {
        if (!items || items.length === 0) return;
        const row = document.createElement('div');
        row.className = 'nlq-chip-row';
        const heading = document.createElement('div');
        heading.className = 'nlq-chip-label';
        heading.textContent = label;
        row.appendChild(heading);
        for (const text of items) {
            const chip = document.createElement('button');
            chip.type = 'button';
            chip.className = 'nlq-chip';
            chip.setAttribute('data-testid', testId);
            chip.textContent = text;
            chip.addEventListener('click', () => {
                if (this.onPick) this.onPick(text);
            });
            row.appendChild(chip);
        }
        this.container.appendChild(row);
    }

    static loadRecent() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            if (!raw) return [];
            const parsed = JSON.parse(raw);
            if (!Array.isArray(parsed)) {
                localStorage.removeItem(STORAGE_KEY);
                console.info('ℹ️ NLQ history reset (not an array)');
                return [];
            }
            return parsed;
        } catch {
            localStorage.removeItem(STORAGE_KEY);
            console.info('ℹ️ NLQ history reset (corrupt)');
            return [];
        }
    }

    static addRecent(query) {
        const trimmed = (query ?? '').trim();
        if (!trimmed) return;
        const current = NlqSuggestions.loadRecent().filter((q) => q !== trimmed);
        current.unshift(trimmed);
        const capped = current.slice(0, HISTORY_CAP);
        localStorage.setItem(STORAGE_KEY, JSON.stringify(capped));
    }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd explore && npm test -- nlq-suggestions`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add explore/static/js/nlq-suggestions.js explore/__tests__/nlq-suggestions.test.js
git commit -m "feat(explore): NlqSuggestions chip renderer and history store"
```

### Task 17: Integrate suggestions into the expanded pill

**Files:**
- Modify: `explore/static/js/nlq-pill.js`
- Modify: `explore/__tests__/nlq-pill.test.js`

- [ ] **Step 1: Write the failing test**

Append to `nlq-pill.test.js`:

```javascript
describe('NlqPill suggestions integration', () => {
    beforeEach(() => {
        document.body.replaceChildren();
        const mount = document.createElement('div');
        mount.id = 'nlqPillMount';
        document.body.appendChild(mount);
        localStorage.clear();
    });

    it('renders suggestions into the expanded card', async () => {
        const fetchFn = vi.fn().mockResolvedValue({ suggestions: ['Suggested Q'] });
        const pill = new NlqPill({ mountId: 'nlqPillMount', fetchSuggestions: fetchFn });
        pill.mount();
        pill.expand();
        await Promise.resolve();
        await Promise.resolve();
        const chip = document.querySelector('[data-testid="nlq-suggestion-chip"]');
        expect(chip).not.toBeNull();
    });

    it('picks a suggestion into the input on click', async () => {
        const fetchFn = vi.fn().mockResolvedValue({ suggestions: ['Suggested Q'] });
        const onSubmit = vi.fn();
        const pill = new NlqPill({ mountId: 'nlqPillMount', fetchSuggestions: fetchFn, onSubmit });
        pill.mount();
        pill.expand();
        await Promise.resolve();
        await Promise.resolve();
        document.querySelector('[data-testid="nlq-suggestion-chip"]').click();
        expect(onSubmit).toHaveBeenCalledWith('Suggested Q');
    });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd explore && npm test -- nlq-pill`
Expected: 2 new tests fail.

- [ ] **Step 3: Write minimal implementation**

Update `nlq-pill.js`:

```javascript
import { NlqSuggestions } from './nlq-suggestions.js';
```

Update the constructor and `_renderExpanded`:

```javascript
    constructor({
        mountId = 'nlqPillMount',
        fetchSuggestions = null,
        getContext = () => ({ pane: 'explore' }),
        onSubmit = null,
    } = {}) {
        this.mountId = mountId;
        this.fetchSuggestions = fetchSuggestions;
        this.getContext = getContext;
        this.onSubmit = onSubmit;
        this.state = 'collapsed';
        this.root = null;
    }

    _renderExpanded() {
        const card = document.createElement('div');
        card.setAttribute('data-testid', 'nlq-pill-expanded');
        card.className = 'nlq-pill-expanded';

        const input = document.createElement('input');
        input.type = 'text';
        input.setAttribute('data-testid', 'nlq-pill-input');
        input.className = 'nlq-pill-input';
        input.placeholder = 'Ask anything about the music graph…';
        input.maxLength = 500;
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                this._submitQuery(input.value);
            }
        });
        card.appendChild(input);

        const chipsContainer = document.createElement('div');
        chipsContainer.className = 'nlq-pill-chips';
        card.appendChild(chipsContainer);

        this.root.appendChild(card);

        if (this.fetchSuggestions) {
            this._suggestions = new NlqSuggestions({
                container: chipsContainer,
                fetchFn: this.fetchSuggestions,
                onPick: (text) => {
                    input.value = text;
                    this._submitQuery(text);
                },
            });
            const ctx = this.getContext();
            this._suggestions.render({ pane: ctx.pane, focus: ctx.focus, focusType: ctx.focusType });
        }
    }

    _submitQuery(query) {
        const trimmed = (query || '').trim();
        if (!trimmed) return;
        NlqSuggestions.addRecent(trimmed);
        this.collapse();
        if (this.onSubmit) this.onSubmit(trimmed);
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd explore && npm test -- nlq-pill`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add explore/static/js/nlq-pill.js explore/__tests__/nlq-pill.test.js
git commit -m "feat(explore): NlqPill wires suggestions into expanded card"
```

---

## Phase 8 — Action applier

### Task 18: `nlq-action-applier.js` — validation, execution order, snapshot

**Files:**
- Create: `explore/static/js/nlq-action-applier.js`
- Create: `explore/__tests__/nlq-action-applier.test.js`

- [ ] **Step 1: Write the failing test**

```javascript
// explore/__tests__/nlq-action-applier.test.js
import { describe, it, expect, vi } from 'vitest';
import { NlqActionApplier } from '../static/js/nlq-action-applier.js';

function mockHandlers() {
    return {
        switchPane: vi.fn(),
        setTrendRange: vi.fn(),
        filterGraph: vi.fn(),
        seedGraph: vi.fn(),
        findPath: vi.fn(),
        showCredits: vi.fn(),
        highlightPath: vi.fn(),
        focusNode: vi.fn(),
        openInsightTile: vi.fn(),
        suggestFollowups: vi.fn(),
    };
}

function mockSnapshotter() {
    return {
        capture: vi.fn().mockReturnValue({ tag: 'snap1' }),
        restore: vi.fn(),
    };
}

describe('NlqActionApplier', () => {
    it('applies switch_pane before seed_graph regardless of list order', () => {
        const handlers = mockHandlers();
        const snap = mockSnapshotter();
        const applier = new NlqActionApplier({ handlers, snapshotter: snap });
        applier.apply([
            { type: 'seed_graph', entities: [{ name: 'Kraftwerk', entity_type: 'artist' }] },
            { type: 'switch_pane', pane: 'trends' },
        ]);
        const callOrder = [
            handlers.switchPane.mock.invocationCallOrder[0],
            handlers.seedGraph.mock.invocationCallOrder[0],
        ];
        expect(callOrder[0]).toBeLessThan(callOrder[1]);
    });

    it('skips unknown types and continues', () => {
        const handlers = mockHandlers();
        const applier = new NlqActionApplier({ handlers, snapshotter: mockSnapshotter() });
        const result = applier.apply([
            { type: 'nonsense' },
            { type: 'focus_node', name: 'Kraftwerk', entity_type: 'artist' },
        ]);
        expect(handlers.focusNode).toHaveBeenCalledWith({ name: 'Kraftwerk', entity_type: 'artist' });
        expect(result.applied).toBe(1);
        expect(result.skipped).toBe(1);
    });

    it('snapshots before applying and restores on undo', () => {
        const handlers = mockHandlers();
        const snap = mockSnapshotter();
        const applier = new NlqActionApplier({ handlers, snapshotter: snap });
        applier.apply([{ type: 'seed_graph', entities: [{ name: 'K', entity_type: 'artist' }] }]);
        expect(snap.capture).toHaveBeenCalledTimes(1);
        applier.undo();
        expect(snap.restore).toHaveBeenCalledWith({ tag: 'snap1' });
    });

    it('counts a failing handler as skipped', () => {
        const handlers = mockHandlers();
        handlers.seedGraph.mockImplementation(() => { throw new Error('boom'); });
        const applier = new NlqActionApplier({ handlers, snapshotter: mockSnapshotter() });
        const result = applier.apply([{ type: 'seed_graph', entities: [] }]);
        expect(result.applied).toBe(0);
        expect(result.skipped).toBe(1);
    });

    it('validates seed_graph entity shape and skips malformed entries', () => {
        const handlers = mockHandlers();
        const applier = new NlqActionApplier({ handlers, snapshotter: mockSnapshotter() });
        const result = applier.apply([
            { type: 'seed_graph', entities: [{ name: 'K', entity_type: 'artist' }, { name: '', entity_type: 'artist' }] },
        ]);
        const callArg = handlers.seedGraph.mock.calls[0][0];
        expect(callArg.entities).toHaveLength(1);
        expect(result.applied).toBe(1);
    });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd explore && npm test -- nlq-action-applier`
Expected: module missing.

- [ ] **Step 3: Write minimal implementation**

```javascript
// explore/static/js/nlq-action-applier.js
const ORDER = [
    'switch_pane',
    'set_trend_range',
    'filter_graph',
    'seed_graph',
    'find_path',
    'show_credits',
    'highlight_path',
    'focus_node',
    'open_insight_tile',
    'suggest_followups',
];

const MAX_LEN = 256;
const VALID_ENTITY_TYPES = new Set(['artist', 'label', 'genre', 'style', 'release']);
const VALID_PANES = new Set(['explore', 'trends', 'insights', 'genres', 'credits']);

function capStr(value) {
    return typeof value === 'string' ? value.slice(0, MAX_LEN) : value;
}

function sanitizeSeedGraph(action) {
    const entities = Array.isArray(action.entities) ? action.entities : [];
    const clean = entities
        .filter((e) => e && typeof e.name === 'string' && e.name.length > 0 && VALID_ENTITY_TYPES.has(e.entity_type))
        .map((e) => ({ name: capStr(e.name), entity_type: e.entity_type }));
    return { type: 'seed_graph', entities: clean, replace: !!action.replace };
}

function sanitizeSwitchPane(action) {
    if (!VALID_PANES.has(action.pane)) return null;
    return { type: 'switch_pane', pane: action.pane };
}

function sanitizeFocusNode(action) {
    if (typeof action.name !== 'string' || !VALID_ENTITY_TYPES.has(action.entity_type)) return null;
    return { type: 'focus_node', name: capStr(action.name), entity_type: action.entity_type };
}

const SANITIZERS = {
    seed_graph: sanitizeSeedGraph,
    switch_pane: sanitizeSwitchPane,
    focus_node: sanitizeFocusNode,
    highlight_path: (a) => ({ type: 'highlight_path', nodes: (a.nodes || []).map(capStr).filter(Boolean) }),
    filter_graph: (a) => ({ type: 'filter_graph', by: a.by, value: a.value }),
    find_path: (a) => ({ type: 'find_path', from: capStr(a.from), to: capStr(a.to), from_type: a.from_type, to_type: a.to_type }),
    show_credits: (a) => ({ type: 'show_credits', name: capStr(a.name), entity_type: a.entity_type }),
    open_insight_tile: (a) => ({ type: 'open_insight_tile', tile_id: capStr(a.tile_id) }),
    set_trend_range: (a) => ({ type: 'set_trend_range', from: capStr(a.from), to: capStr(a.to) }),
    suggest_followups: (a) => ({ type: 'suggest_followups', queries: (a.queries || []).map(capStr) }),
};

export class NlqActionApplier {
    constructor({ handlers, snapshotter }) {
        this.handlers = handlers;
        this.snapshotter = snapshotter;
        this._lastSnapshot = null;
    }

    apply(rawActions) {
        const sorted = [...(rawActions || [])].sort((a, b) => {
            const ai = ORDER.indexOf(a.type);
            const bi = ORDER.indexOf(b.type);
            return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
        });

        this._lastSnapshot = this.snapshotter.capture();
        let applied = 0;
        let skipped = 0;

        for (const raw of sorted) {
            const sanitizer = SANITIZERS[raw.type];
            if (!sanitizer) {
                console.warn('🤷 unknown NLQ action type', raw.type);
                skipped += 1;
                continue;
            }
            const clean = sanitizer(raw);
            if (!clean) {
                skipped += 1;
                continue;
            }
            const handler = this._handlerFor(clean.type);
            if (!handler) {
                skipped += 1;
                continue;
            }
            try {
                handler(clean);
                applied += 1;
            } catch (err) {
                console.error('❌ NLQ action handler failed', clean.type, err);
                skipped += 1;
            }
        }

        return { applied, skipped };
    }

    _handlerFor(type) {
        const map = {
            switch_pane: this.handlers.switchPane,
            set_trend_range: this.handlers.setTrendRange,
            filter_graph: this.handlers.filterGraph,
            seed_graph: this.handlers.seedGraph,
            find_path: this.handlers.findPath,
            show_credits: this.handlers.showCredits,
            highlight_path: this.handlers.highlightPath,
            focus_node: this.handlers.focusNode,
            open_insight_tile: this.handlers.openInsightTile,
            suggest_followups: this.handlers.suggestFollowups,
        };
        return map[type];
    }

    undo() {
        if (this._lastSnapshot != null) {
            this.snapshotter.restore(this._lastSnapshot);
            this._lastSnapshot = null;
        }
    }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd explore && npm test -- nlq-action-applier`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add explore/static/js/nlq-action-applier.js explore/__tests__/nlq-action-applier.test.js
git commit -m "feat(explore): NlqActionApplier with ordering, sanitization, and undo"
```

### Task 19: Wire action handlers to existing subsystems

**Files:**
- Create: `explore/static/js/nlq-handlers.js`
- Create: `explore/__tests__/nlq-handlers.test.js`

- [ ] **Step 1: Write the failing test**

```javascript
// explore/__tests__/nlq-handlers.test.js
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { buildHandlers, buildSnapshotter } from '../static/js/nlq-handlers.js';

describe('buildHandlers', () => {
    let app;

    beforeEach(() => {
        app = {
            _switchPane: vi.fn(),
            _loadExplore: vi.fn(),
            graph: {
                clearAll: vi.fn(),
                addEntity: vi.fn(),
                highlightPath: vi.fn(),
                focusNode: vi.fn(),
                snapshot: vi.fn().mockReturnValue({ nodes: [], edges: [] }),
                restore: vi.fn(),
            },
        };
    });

    it('switchPane delegates to app._switchPane', () => {
        const handlers = buildHandlers({ app });
        handlers.switchPane({ pane: 'trends' });
        expect(app._switchPane).toHaveBeenCalledWith('trends');
    });

    it('seedGraph clears when replace=true', () => {
        const handlers = buildHandlers({ app });
        handlers.seedGraph({ entities: [{ name: 'Kraftwerk', entity_type: 'artist' }], replace: true });
        expect(app.graph.clearAll).toHaveBeenCalled();
        expect(app.graph.addEntity).toHaveBeenCalledWith({ name: 'Kraftwerk', entity_type: 'artist' });
    });

    it('focusNode triggers _loadExplore', () => {
        const handlers = buildHandlers({ app });
        handlers.focusNode({ name: 'Kraftwerk', entity_type: 'artist' });
        expect(app._loadExplore).toHaveBeenCalledWith('Kraftwerk', 'artist');
    });

    it('snapshotter captures graph + active pane', () => {
        app.activePane = 'explore';
        const snap = buildSnapshotter({ app });
        const s = snap.capture();
        expect(s.pane).toBe('explore');
        expect(app.graph.snapshot).toHaveBeenCalled();
    });

    it('snapshotter restore dispatches to graph and pane', () => {
        const snap = buildSnapshotter({ app });
        snap.restore({ pane: 'trends', graph: { nodes: [1] } });
        expect(app._switchPane).toHaveBeenCalledWith('trends');
        expect(app.graph.restore).toHaveBeenCalledWith({ nodes: [1] });
    });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd explore && npm test -- nlq-handlers`
Expected: missing module.

- [ ] **Step 3: Write minimal implementation**

```javascript
// explore/static/js/nlq-handlers.js
/**
 * Bridges NlqActionApplier actions to existing explore subsystems.
 *
 * Each handler takes the sanitized action object and dispatches to the right
 * app/graph/insights method. All handlers are sync — async subsystem calls
 * fire-and-forget here; the applier waits for none of them.
 */

export function buildHandlers({ app }) {
    return {
        switchPane: ({ pane }) => {
            app._switchPane?.(pane);
        },
        setTrendRange: ({ from, to }) => {
            app.trends?.setRange?.(from, to);
        },
        filterGraph: ({ by, value }) => {
            app.graph?.applyFilter?.(by, value);
        },
        seedGraph: ({ entities, replace }) => {
            if (replace) app.graph?.clearAll?.();
            for (const ent of entities || []) {
                app.graph?.addEntity?.(ent);
            }
        },
        findPath: ({ from, to, from_type, to_type }) => {
            app.graph?.findPath?.({ from, to, fromType: from_type, toType: to_type });
        },
        showCredits: ({ name, entity_type }) => {
            app.credits?.show?.(name, entity_type);
        },
        highlightPath: ({ nodes }) => {
            app.graph?.highlightPath?.(nodes);
        },
        focusNode: ({ name, entity_type }) => {
            app._loadExplore?.(name, entity_type);
        },
        openInsightTile: ({ tile_id }) => {
            app.insights?.openTile?.(tile_id);
        },
        suggestFollowups: ({ queries }) => {
            app.nlq?.setFollowups?.(queries);
        },
    };
}

export function buildSnapshotter({ app }) {
    return {
        capture: () => ({
            pane: app.activePane,
            graph: app.graph?.snapshot?.() ?? null,
            trendRange: app.trends?.getRange?.() ?? null,
        }),
        restore: (snap) => {
            if (!snap) return;
            if (snap.pane) app._switchPane?.(snap.pane);
            if (snap.graph) app.graph?.restore?.(snap.graph);
            if (snap.trendRange) app.trends?.setRange?.(snap.trendRange.from, snap.trendRange.to);
        },
    };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd explore && npm test -- nlq-handlers`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add explore/static/js/nlq-handlers.js explore/__tests__/nlq-handlers.test.js
git commit -m "feat(explore): nlq-handlers bridge to graph/insights/trends"
```

### Task 20: Add `snapshot`, `restore`, `addEntity`, `clearAll` methods to `graph.js`

**Files:**
- Modify: `explore/static/js/graph.js`
- Create: `explore/__tests__/graph-snapshot.test.js`

- [ ] **Step 1: Write the failing test**

```javascript
// explore/__tests__/graph-snapshot.test.js
import { describe, it, expect, beforeEach, vi } from 'vitest';

describe('GraphViz snapshot/restore', () => {
    beforeEach(() => {
        document.body.replaceChildren();
        const container = document.createElement('div');
        container.id = 'graphContainer';
        container.style.width = '400px';
        container.style.height = '400px';
        document.body.appendChild(container);

        // Minimal d3 stub so GraphViz constructor does not throw in jsdom
        global.d3 = global.d3 || {
            select: () => ({
                selectAll: () => ({ remove: () => ({}) }),
                append: () => ({ attr: () => ({}), call: () => ({}) }),
                call: () => ({}),
            }),
            zoom: () => ({ on: () => ({}), scaleBy: () => ({}), transform: () => ({}) }),
            zoomIdentity: { translate: () => ({ scale: () => ({}) }) },
            forceSimulation: () => ({
                force: () => ({ force: () => ({ force: () => ({ force: () => ({ on: () => ({}), stop: () => ({}), alpha: () => ({ restart: () => ({}) }), nodes: () => ({}) }) }) }) }),
            }),
            forceLink: () => ({ id: () => ({ distance: () => ({}) }), links: () => ({}) }),
            forceManyBody: () => ({ strength: () => ({}) }),
            forceCenter: () => ({}),
            forceCollide: () => ({}),
        };
    });

    it('snapshot returns the current nodes and edges', async () => {
        const { GraphViz } = await import('../static/js/graph.js');
        const graph = new GraphViz('graphContainer');
        graph.nodes = [{ id: '1', name: 'Kraftwerk' }];
        graph.edges = [{ source: '1', target: '2' }];
        const snap = graph.snapshot();
        expect(snap.nodes).toEqual([{ id: '1', name: 'Kraftwerk' }]);
        expect(snap.edges).toEqual([{ source: '1', target: '2' }]);
    });

    it('restore replaces nodes and edges', async () => {
        const { GraphViz } = await import('../static/js/graph.js');
        const graph = new GraphViz('graphContainer');
        graph._render = vi.fn();
        graph.restore({ nodes: [{ id: '2' }], edges: [] });
        expect(graph.nodes).toEqual([{ id: '2' }]);
        expect(graph.edges).toEqual([]);
        expect(graph._render).toHaveBeenCalled();
    });

    it('clearAll empties nodes and edges', async () => {
        const { GraphViz } = await import('../static/js/graph.js');
        const graph = new GraphViz('graphContainer');
        graph.nodes = [{ id: '1' }];
        graph.edges = [{ source: '1', target: '2' }];
        graph._render = vi.fn();
        graph.clearAll();
        expect(graph.nodes).toEqual([]);
        expect(graph.edges).toEqual([]);
    });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd explore && npm test -- graph-snapshot`
Expected: methods missing on `GraphViz`.

- [ ] **Step 3: Write minimal implementation**

Add `export` to the `GraphViz` class declaration if not already exported, and add the methods inside the class:

```javascript
    snapshot() {
        return {
            nodes: JSON.parse(JSON.stringify(this.nodes || [])),
            edges: JSON.parse(JSON.stringify(this.edges || [])),
        };
    }

    restore(snap) {
        this.nodes = snap.nodes || [];
        this.edges = snap.edges || [];
        if (this._render) this._render();
    }

    clearAll() {
        this.nodes = [];
        this.edges = [];
        if (this._render) this._render();
    }

    addEntity(entity) {
        if (this._app && this._app._loadExplore) {
            this._app._loadExplore(entity.name, entity.entity_type);
            return;
        }
        this.nodes = [...(this.nodes || []), { id: entity.name, name: entity.name, type: entity.entity_type }];
        if (this._render) this._render();
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd explore && npm test -- graph-snapshot`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add explore/static/js/graph.js explore/__tests__/graph-snapshot.test.js
git commit -m "feat(explore/graph): snapshot/restore/clear/addEntity for NLQ actions"
```

---

## Phase 9 — Markdown rendering and summary strip

### Task 21: DOMPurify-backed markdown renderer with entity span injection

**Files:**
- Create: `explore/static/js/nlq-markdown.js`
- Create: `explore/__tests__/nlq-markdown.test.js`
- Modify: `explore/package.json` to add `dompurify` and `marked` as dependencies

The renderer never assigns to `innerHTML`. It uses `DOMPurify.sanitize(html, { RETURN_DOM_FRAGMENT: true })` to get a sanitized DocumentFragment directly, then walks it to inject entity anchors created via `createElement` + `textContent`.

- [ ] **Step 1: Write the failing test**

```javascript
// explore/__tests__/nlq-markdown.test.js
import { describe, it, expect, vi } from 'vitest';
import { renderSummary } from '../static/js/nlq-markdown.js';

describe('renderSummary', () => {
    it('renders **bold** as <strong>', () => {
        const container = document.createElement('div');
        renderSummary(container, '**Kraftwerk** released an album.', []);
        expect(container.querySelector('strong')).not.toBeNull();
        expect(container.querySelector('strong').textContent).toBe('Kraftwerk');
    });

    it('does NOT render a script tag', () => {
        const container = document.createElement('div');
        renderSummary(container, '<script>alert(1)</script>hi', []);
        expect(container.querySelector('script')).toBeNull();
        expect(container.textContent).toContain('hi');
    });

    it('wraps entity names in anchor elements', () => {
        const container = document.createElement('div');
        const onClick = vi.fn();
        renderSummary(container, 'Kraftwerk is awesome.', [{ name: 'Kraftwerk', type: 'artist' }], onClick);
        const link = container.querySelector('a[data-entity-name="Kraftwerk"]');
        expect(link).not.toBeNull();
        link.click();
        expect(onClick).toHaveBeenCalledWith('Kraftwerk', 'artist');
    });

    it('handles entity names inside bold markdown', () => {
        const container = document.createElement('div');
        renderSummary(container, '**Kraftwerk** is awesome.', [{ name: 'Kraftwerk', type: 'artist' }]);
        const strong = container.querySelector('strong');
        expect(strong).not.toBeNull();
        const link = strong.querySelector('a[data-entity-name="Kraftwerk"]');
        expect(link).not.toBeNull();
    });

    it('disallows anchor tags from the markdown source', () => {
        const container = document.createElement('div');
        renderSummary(container, '[link](javascript:alert(1))', []);
        // The only <a> allowed is the one injected by the entity code; none from markdown
        const mdLink = container.querySelector('a:not(.nlq-entity-link)');
        expect(mdLink).toBeNull();
    });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd explore && npm test -- nlq-markdown`
Expected: module missing.

- [ ] **Step 3: Install deps and write the module**

```bash
cd explore && npm install --save dompurify marked
```

```javascript
// explore/static/js/nlq-markdown.js
import DOMPurify from 'dompurify';
import { marked } from 'marked';

const ALLOWED_TAGS = ['strong', 'em', 'code', 'p', 'br'];
const ALLOWED_ATTR = [];

marked.setOptions({ gfm: false, breaks: false });

/**
 * Render a markdown summary into `container`, injecting entity links.
 * Never uses innerHTML — DOMPurify returns a DocumentFragment directly.
 *
 * @param {HTMLElement} container
 * @param {string} summary - Markdown text from the agent.
 * @param {Array<{name:string,type:string}>} entities
 * @param {(name:string,type:string) => void} [onEntityClick]
 */
export function renderSummary(container, summary, entities, onEntityClick) {
    while (container.firstChild) container.removeChild(container.firstChild);

    const dirtyHtml = marked.parse(summary || '');
    const fragment = DOMPurify.sanitize(dirtyHtml, {
        ALLOWED_TAGS,
        ALLOWED_ATTR,
        RETURN_DOM_FRAGMENT: true,
    });

    _injectEntities(fragment, entities || [], onEntityClick);
    container.appendChild(fragment);
}

function _injectEntities(root, entities, onEntityClick) {
    if (entities.length === 0) return;
    const sorted = [...entities].sort((a, b) => (b.name || '').length - (a.name || '').length);
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const textNodes = [];
    let node;
    while ((node = walker.nextNode())) textNodes.push(node);
    for (const textNode of textNodes) {
        _wrapEntitiesInTextNode(textNode, sorted, onEntityClick);
    }
}

function _wrapEntitiesInTextNode(textNode, entities, onEntityClick) {
    const text = textNode.nodeValue || '';
    const matches = [];
    for (const entity of entities) {
        if (!entity.name) continue;
        let searchFrom = 0;
        while (searchFrom < text.length) {
            const idx = text.indexOf(entity.name, searchFrom);
            if (idx === -1) break;
            const end = idx + entity.name.length;
            const overlaps = matches.some((m) => idx < m.end && end > m.start);
            if (!overlaps) matches.push({ start: idx, end, entity });
            searchFrom = idx + 1;
        }
    }
    if (matches.length === 0) return;
    matches.sort((a, b) => a.start - b.start);

    const parent = textNode.parentNode;
    const fragment = document.createDocumentFragment();
    let cursor = 0;
    for (const match of matches) {
        if (match.start > cursor) {
            fragment.appendChild(document.createTextNode(text.slice(cursor, match.start)));
        }
        const link = document.createElement('a');
        link.textContent = match.entity.name;
        link.className = 'nlq-entity-link';
        link.setAttribute('data-entity-name', match.entity.name);
        link.setAttribute('data-entity-type', match.entity.type || 'artist');
        link.setAttribute('href', '#');
        link.addEventListener('click', (e) => {
            e.preventDefault();
            if (onEntityClick) onEntityClick(match.entity.name, match.entity.type || 'artist');
        });
        fragment.appendChild(link);
        cursor = match.end;
    }
    if (cursor < text.length) {
        fragment.appendChild(document.createTextNode(text.slice(cursor)));
    }
    parent.replaceChild(fragment, textNode);
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd explore && npm test -- nlq-markdown`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add explore/static/js/nlq-markdown.js explore/__tests__/nlq-markdown.test.js explore/package.json explore/package-lock.json
git commit -m "feat(explore): DOMPurify-backed NLQ markdown renderer with entity injection"
```

### Task 22: Summary strip component

**Files:**
- Create: `explore/static/js/nlq-summary-strip.js`
- Create: `explore/__tests__/nlq-summary-strip.test.js`

- [ ] **Step 1: Write the failing test**

```javascript
// explore/__tests__/nlq-summary-strip.test.js
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { NlqSummaryStrip } from '../static/js/nlq-summary-strip.js';

describe('NlqSummaryStrip', () => {
    let container;

    beforeEach(() => {
        document.body.replaceChildren();
        container = document.createElement('div');
        document.body.appendChild(container);
    });

    it('renders summary text and action log', () => {
        const strip = new NlqSummaryStrip({ container });
        strip.show({
            summary: '**Kraftwerk** released albums.',
            entities: [{ name: 'Kraftwerk', type: 'artist' }],
            appliedActions: ['seed_graph', 'highlight_path'],
            skipped: 0,
        });
        expect(container.querySelector('strong')).not.toBeNull();
        expect(container.textContent).toContain('seed_graph');
        expect(container.textContent).toContain('highlight_path');
    });

    it('shows skipped count when nonzero', () => {
        const strip = new NlqSummaryStrip({ container });
        strip.show({ summary: 'x', entities: [], appliedActions: [], skipped: 2 });
        expect(container.textContent).toContain('2 action(s) skipped');
    });

    it('dismiss button clears the strip', () => {
        const strip = new NlqSummaryStrip({ container });
        strip.show({ summary: 'x', entities: [], appliedActions: [], skipped: 0 });
        container.querySelector('[data-testid="nlq-strip-dismiss"]').click();
        expect(container.querySelector('[data-testid="nlq-strip"]')).toBeNull();
    });

    it('undo button fires onUndo', () => {
        const onUndo = vi.fn();
        const strip = new NlqSummaryStrip({ container, onUndo });
        strip.show({ summary: 'x', entities: [], appliedActions: ['seed_graph'], skipped: 0 });
        container.querySelector('[data-testid="nlq-strip-undo"]').click();
        expect(onUndo).toHaveBeenCalledTimes(1);
    });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd explore && npm test -- nlq-summary-strip`
Expected: module missing.

- [ ] **Step 3: Write minimal implementation**

```javascript
// explore/static/js/nlq-summary-strip.js
import { renderSummary } from './nlq-markdown.js';

export class NlqSummaryStrip {
    constructor({ container, onUndo = null, onEntityClick = null }) {
        this.container = container;
        this.onUndo = onUndo;
        this.onEntityClick = onEntityClick;
    }

    show({ summary, entities, appliedActions, skipped }) {
        this.hide();

        const strip = document.createElement('div');
        strip.setAttribute('data-testid', 'nlq-strip');
        strip.className = 'nlq-summary-strip';

        const summaryEl = document.createElement('div');
        summaryEl.className = 'nlq-summary-text';
        renderSummary(summaryEl, summary, entities, this.onEntityClick);
        strip.appendChild(summaryEl);

        const footer = document.createElement('div');
        footer.className = 'nlq-summary-footer';
        const log = document.createElement('span');
        log.className = 'nlq-action-log';
        const appliedText = (appliedActions || []).map((a) => `✓ ${a}`).join(' • ');
        const skippedText = skipped > 0 ? ` (${skipped} action(s) skipped)` : '';
        log.textContent = appliedText + skippedText;
        footer.appendChild(log);

        if ((appliedActions || []).length > 0 && this.onUndo) {
            const undoBtn = document.createElement('button');
            undoBtn.type = 'button';
            undoBtn.setAttribute('data-testid', 'nlq-strip-undo');
            undoBtn.className = 'nlq-strip-btn';
            undoBtn.textContent = '↶ Undo';
            undoBtn.addEventListener('click', () => this.onUndo());
            footer.appendChild(undoBtn);
        }

        const dismiss = document.createElement('button');
        dismiss.type = 'button';
        dismiss.setAttribute('data-testid', 'nlq-strip-dismiss');
        dismiss.className = 'nlq-strip-btn';
        dismiss.textContent = '✕';
        dismiss.addEventListener('click', () => this.hide());
        footer.appendChild(dismiss);

        strip.appendChild(footer);
        this.container.appendChild(strip);
    }

    hide() {
        const existing = this.container.querySelector('[data-testid="nlq-strip"]');
        if (existing) existing.remove();
    }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd explore && npm test -- nlq-summary-strip`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add explore/static/js/nlq-summary-strip.js explore/__tests__/nlq-summary-strip.test.js
git commit -m "feat(explore): NlqSummaryStrip with undo and dismiss"
```

---

## Phase 10 — Integration, cleanup, E2E

### Task 23: Rewrite `nlq.js` as thin coordinator

**Files:**
- Rewrite: `explore/static/js/nlq.js`
- Modify: `explore/static/js/api-client.js` (add `fetchNlqSuggestions`)
- Create: `explore/__tests__/api-client-nlq-suggestions.test.js`

- [ ] **Step 1: Write the failing test for the suggestions API method**

```javascript
// explore/__tests__/api-client-nlq-suggestions.test.js
import { describe, it, expect, vi } from 'vitest';

describe('apiClient.fetchNlqSuggestions', () => {
    it('calls the suggestions endpoint with context params', async () => {
        global.fetch = vi.fn().mockResolvedValue({
            ok: true,
            json: async () => ({ suggestions: ['a', 'b'] }),
        });
        await import('../static/js/api-client.js');
        const result = await window.apiClient.fetchNlqSuggestions({ pane: 'explore', focus: 'K', focusType: 'artist' });
        expect(result.suggestions).toEqual(['a', 'b']);
        const calledUrl = global.fetch.mock.calls[0][0];
        expect(calledUrl).toContain('/api/nlq/suggestions');
        expect(calledUrl).toContain('pane=explore');
        expect(calledUrl).toContain('focus=K');
    });
});
```

- [ ] **Step 2: Run — FAIL**

Run: `cd explore && npm test -- api-client-nlq-suggestions`
Expected: `fetchNlqSuggestions is not a function`.

- [ ] **Step 3: Add the method**

In `explore/static/js/api-client.js`, add:

```javascript
    async fetchNlqSuggestions({ pane, focus = null, focusType = null }) {
        const params = new URLSearchParams({ pane });
        if (focus) params.set('focus', focus);
        if (focusType) params.set('focus_type', focusType);
        const response = await fetch(`/api/nlq/suggestions?${params.toString()}`);
        if (!response.ok) throw new Error(`Suggestions fetch failed: ${response.status}`);
        return await response.json();
    }
```

- [ ] **Step 4: Run — PASS**

Run: `cd explore && npm test -- api-client-nlq-suggestions`

- [ ] **Step 5: Rewrite `nlq.js`**

Replace the entire file:

```javascript
// explore/static/js/nlq.js
/**
 * NLQ orchestrator: pill + suggestions + action applier + summary strip.
 *
 * Kept as a thin coordinator — business logic lives in the individual
 * components imported below.
 */
import { NlqActionApplier } from './nlq-action-applier.js';
import { NlqPill } from './nlq-pill.js';
import { NlqSuggestions } from './nlq-suggestions.js';
import { NlqSummaryStrip } from './nlq-summary-strip.js';
import { buildHandlers, buildSnapshotter } from './nlq-handlers.js';

export function initNlq({ app, apiClient, mountId = 'nlqPillMount', stripMountId = 'nlqStripMount' }) {
    const handlers = buildHandlers({ app });
    const snapshotter = buildSnapshotter({ app });
    const applier = new NlqActionApplier({ handlers, snapshotter });

    const stripEl = document.getElementById(stripMountId) || document.body;
    const strip = new NlqSummaryStrip({
        container: stripEl,
        onUndo: () => applier.undo(),
        onEntityClick: (name, type) => app._loadExplore?.(name, type),
    });

    const pill = new NlqPill({
        mountId,
        fetchSuggestions: (ctx) => apiClient.fetchNlqSuggestions(ctx),
        getContext: () => ({
            pane: app.activePane || 'explore',
            focus: app.currentEntity?.name ?? null,
            focusType: app.currentEntity?.type ?? null,
        }),
        onSubmit: (query) => _submit({ query, app, apiClient, applier, strip, pill }),
    });

    apiClient.checkNlqStatus().then((status) => {
        if (status && status.enabled === true) pill.mount();
    });
}

function _submit({ query, app, apiClient, applier, strip, pill }) {
    pill.setLoading?.(true);
    strip.hide();

    const appliedActionTypes = [];

    apiClient.askNlqStream(
        query,
        {
            entity_id: app.currentEntity?.name ?? null,
            entity_type: app.currentEntity?.type ?? null,
        },
        () => {},
        (result) => {
            const actions = result.actions || [];
            appliedActionTypes.push(...actions.map((a) => a.type));
            const counts = applier.apply(actions);
            strip.show({
                summary: result.summary || '',
                entities: result.entities || [],
                appliedActions: appliedActionTypes,
                skipped: counts.skipped,
            });
            pill.setLoading?.(false);
            pill.flash?.(`✓ ${counts.applied} actions applied`);
        },
        (err) => {
            console.error('❌ NLQ stream error', err);
            pill.setLoading?.(false);
            strip.show({ summary: 'Request failed — please try again.', entities: [], appliedActions: [], skipped: 0 });
        },
    );
}

if (typeof window !== 'undefined') {
    window.NlqInit = initNlq;
}
```

- [ ] **Step 6: Run the full explore test suite**

Run: `cd explore && npm test`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add explore/static/js/nlq.js explore/static/js/api-client.js explore/__tests__/api-client-nlq-suggestions.test.js
git commit -m "feat(explore): rewrite nlq.js as thin orchestrator over new components"
```

### Task 24: Remove old navbar Ask toggle and panel

**Files:**
- Modify: `explore/static/index.html` (remove `#searchAskToggle`, `#nlqPanel`, `#nlqExamples`)
- Modify: `explore/static/js/app.js:1561-1612` (remove old NLQ panel setup IIFE)
- Create: `explore/__tests__/no-legacy-nlq-navbar.test.js`

- [ ] **Step 1: Write the failing test**

```javascript
// explore/__tests__/no-legacy-nlq-navbar.test.js
import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const indexHtml = fs.readFileSync(path.join(__dirname, '..', 'static', 'index.html'), 'utf8');
const appJs = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'app.js'), 'utf8');

describe('legacy NLQ navbar removed', () => {
    it('index.html has no searchAskToggle', () => {
        expect(indexHtml).not.toContain('searchAskToggle');
    });

    it('index.html has no nlqPanel in the navbar', () => {
        expect(indexHtml).not.toContain('id="nlqPanel"');
    });

    it('index.html has no hardcoded nlqExamples', () => {
        expect(indexHtml).not.toContain('id="nlqExamples"');
    });

    it('app.js has no searchModeBtn handler', () => {
        expect(appJs).not.toContain('searchModeBtn');
    });
});
```

- [ ] **Step 2: Run the test — FAIL**

Run: `cd explore && npm test -- no-legacy-nlq-navbar`
Expected: 4 failures.

- [ ] **Step 3: Delete the markup and handler**

In `explore/static/index.html`, delete the entire block from `<!-- NLQ Search/Ask toggle + panel -->` through the closing `</div>` that wraps `#nlqExamples` (approximately lines 471-499). If the `navbar-search-extras` wrapper is now empty, delete it too.

In `explore/static/js/app.js`, delete the entire IIFE from the `// NLQ panel setup` comment through `})();` (lines 1561-1612).

- [ ] **Step 4: Run — PASS**

Run: `cd explore && npm test -- no-legacy-nlq-navbar`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add explore/static/index.html explore/static/js/app.js explore/__tests__/no-legacy-nlq-navbar.test.js
git commit -m "chore(explore): remove legacy navbar NLQ toggle and panel"
```

### Task 25: Wire `initNlq` into app startup and add the strip mount point

**Files:**
- Modify: `explore/static/index.html` (add `<div id="nlqStripMount">`)
- Modify: `explore/static/js/app.js` (call `initNlq` after app construction)
- Create: `explore/__tests__/nlq-init.test.js`

- [ ] **Step 1: Write the failing test**

```javascript
// explore/__tests__/nlq-init.test.js
import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const indexHtml = fs.readFileSync(path.join(__dirname, '..', 'static', 'index.html'), 'utf8');
const appJs = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'app.js'), 'utf8');

describe('NLQ init wiring', () => {
    it('index.html has nlqPillMount and nlqStripMount', () => {
        expect(indexHtml).toContain('id="nlqPillMount"');
        expect(indexHtml).toContain('id="nlqStripMount"');
    });

    it('app.js imports and calls initNlq', () => {
        expect(appJs).toContain("import { initNlq }");
        expect(appJs).toContain('initNlq(');
    });
});
```

- [ ] **Step 2: Run — FAIL**

Run: `cd explore && npm test -- nlq-init`

- [ ] **Step 3: Write minimal implementation**

In `explore/static/index.html`, just before `</body>`:

```html
<div id="nlqPillMount"></div>
<div id="nlqStripMount"></div>
```

In `explore/static/js/app.js`, add at the top with other imports:

```javascript
import { initNlq } from './nlq.js';
```

At the bottom of the file, after `window.exploreApp = ...`:

```javascript
initNlq({
    app: window.exploreApp,
    apiClient: window.apiClient,
});
```

- [ ] **Step 4: Run — PASS**

Run: `cd explore && npm test -- nlq-init`

- [ ] **Step 5: Commit**

```bash
git add explore/static/index.html explore/static/js/app.js explore/__tests__/nlq-init.test.js
git commit -m "feat(explore): wire initNlq into app startup"
```

### Task 26: Pill CSS — collapsed, expanded, loading, chips

**Files:**
- Create: `explore/static/css/nlq-pill.css`
- Modify: `explore/static/index.html` (link the new stylesheet)

- [ ] **Step 1: Manual state check**

Run: `just up` from the repo root. Open `http://localhost:8006`. Verify the pill mount area is currently empty or unstyled. Visual check only — no test.

- [ ] **Step 2: Write the stylesheet**

```css
/* explore/static/css/nlq-pill.css */
.nlq-pill-root {
    position: fixed;
    inset: auto 0 16px 0;
    display: flex;
    justify-content: center;
    z-index: 1500;
    pointer-events: none;
}
.nlq-pill-root > * { pointer-events: auto; }

.nlq-pill-collapsed {
    background: linear-gradient(135deg, #9b8dff, #6b5ddf);
    color: #fff;
    padding: 8px 20px;
    border-radius: 999px;
    font-size: 13px;
    font-weight: 600;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    box-shadow: 0 4px 20px rgba(155, 141, 255, 0.5);
    cursor: pointer;
    transition: transform 0.15s ease;
    border: none;
}
.nlq-pill-collapsed:hover { transform: scale(1.03); }
.nlq-pill-collapsed kbd {
    background: rgba(255, 255, 255, 0.2);
    padding: 2px 6px;
    border-radius: 3px;
    font-family: monospace;
    font-size: 10px;
}
.nlq-pill-sparkle { font-size: 14px; }

.nlq-pill-expanded {
    background: #141420;
    border: 1px solid #9b8dff;
    border-radius: 14px;
    box-shadow: 0 12px 48px rgba(155, 141, 255, 0.4);
    padding: 16px;
    width: min(560px, calc(100vw - 48px));
    display: flex;
    flex-direction: column;
    gap: 12px;
}

.nlq-pill-input {
    background: #0a0a14;
    border: 1px solid #9b8dff;
    border-radius: 999px;
    padding: 10px 18px;
    color: #fff;
    font-size: 13px;
    outline: none;
}

.nlq-pill-chips { display: flex; flex-direction: column; gap: 8px; }
.nlq-chip-row { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.nlq-chip-label {
    font-size: 9px;
    color: #666;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    flex-basis: 100%;
}
.nlq-chip {
    background: #1a1a24;
    border: 1px solid #333;
    border-radius: 999px;
    padding: 4px 10px;
    font-size: 11px;
    color: #bbb;
    cursor: pointer;
    transition: all 0.15s;
}
.nlq-chip:hover { border-color: #9b8dff; color: #9b8dff; }

.nlq-summary-strip {
    position: fixed;
    left: 50%;
    bottom: 64px;
    transform: translateX(-50%);
    width: min(640px, calc(100vw - 48px));
    background: rgba(20, 20, 32, 0.95);
    border: 1px solid #9b8dff;
    border-radius: 8px;
    padding: 10px 14px;
    color: #ddd;
    font-size: 12px;
    backdrop-filter: blur(6px);
    z-index: 1499;
}
.nlq-summary-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: 6px;
    font-size: 10px;
    color: #888;
}
.nlq-strip-btn {
    background: transparent;
    border: none;
    color: #9b8dff;
    cursor: pointer;
    font-size: 11px;
    padding: 2px 6px;
}
.nlq-entity-link {
    color: #9b8dff;
    text-decoration: underline;
    cursor: pointer;
}
```

Link the stylesheet in `explore/static/index.html` `<head>`:

```html
<link rel="stylesheet" href="/css/nlq-pill.css">
```

- [ ] **Step 3: Verify in the browser**

Run: `just up` from repo root. Navigate to `http://localhost:8006`. Click the pill, verify the expanded card renders with chip rows. Submit a canned query, verify the summary strip appears and the graph mutates.

- [ ] **Step 4: Commit**

```bash
git add explore/static/css/nlq-pill.css explore/static/index.html
git commit -m "style(explore): NLQ pill, expanded card, and summary strip CSS"
```

### Task 27: Playwright E2E — click pill, submit, graph mutates

**Files:**
- Create: `tests/e2e/test_ask_pill.py`
- Modify: `tests/e2e/conftest.py` (add `explore_url` fixture if missing)

- [ ] **Step 1: Write the failing test**

```python
# tests/e2e/test_ask_pill.py
"""E2E: the Ask pill expands, submits, and applies actions to the graph."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect


@pytest.mark.e2e
def test_ask_pill_collapsed_to_submit_to_graph_mutation(page: Page, explore_url: str) -> None:
    page.goto(explore_url)

    pill = page.locator('[data-testid="nlq-pill-collapsed"]')
    expect(pill).to_be_visible()

    pill.click()
    expanded = page.locator('[data-testid="nlq-pill-expanded"]')
    expect(expanded).to_be_visible()

    input_el = page.locator('[data-testid="nlq-pill-input"]')
    expect(input_el).to_be_focused()

    input_el.fill('What labels has Kraftwerk released on?')
    input_el.press('Enter')

    strip = page.locator('[data-testid="nlq-strip"]')
    expect(strip).to_be_visible(timeout=15_000)

    nodes = page.locator('#graphContainer svg g.node')
    expect(nodes.first).to_be_visible(timeout=5_000)
```

Ensure `tests/e2e/conftest.py` has the fixture:

```python
import pytest


@pytest.fixture(scope="session")
def explore_url() -> str:
    return "http://localhost:8006"
```

- [ ] **Step 2: Run against a dev server**

Run: `just up` in one terminal, then `uv run pytest tests/e2e/test_ask_pill.py -v` in another.
Expected: FAIL if the Anthropic API key is not configured or the pill is not mounted. Otherwise PASS.

- [ ] **Step 3: Fix selectors or setup and re-run until green**

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/test_ask_pill.py tests/e2e/conftest.py
git commit -m "test(e2e): Ask pill expand-and-submit end-to-end"
```

### Task 28: Playwright E2E — cross-pane action flow

**Files:**
- Create: `tests/e2e/test_ask_cross_pane.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/e2e/test_ask_cross_pane.py
"""E2E: an Ask query that triggers switch_pane should navigate and render."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect


@pytest.mark.e2e
def test_ask_switch_pane_to_insights(page: Page, explore_url: str) -> None:
    page.goto(explore_url)
    page.locator('[data-testid="nlq-pill-collapsed"]').click()
    input_el = page.locator('[data-testid="nlq-pill-input"]')
    input_el.fill('Show me the biggest labels of 2024')
    input_el.press('Enter')

    expect(page.locator('[data-testid="nlq-strip"]')).to_be_visible(timeout=15_000)

    insights_link = page.locator('.nav-link[data-pane="insights"].active')
    expect(insights_link).to_be_visible(timeout=5_000)
```

- [ ] **Step 2: Run**

Run: `uv run pytest tests/e2e/test_ask_cross_pane.py -v`
Expected: PASS if the real agent emits `switch_pane` for this query.

- [ ] **Step 3: Commit**

```bash
git add tests/e2e/test_ask_cross_pane.py
git commit -m "test(e2e): Ask cross-pane switch to insights"
```

### Task 29: Perftest entries

**Files:**
- Modify: `tests/perftest/config.yaml`
- Modify: `tests/perftest/run_perftest.py`

- [ ] **Step 1: Add perftest scenarios**

Append to `tests/perftest/config.yaml`:

```yaml
- name: nlq_query_simple
  method: POST
  path: /api/nlq/query
  body:
    query: "Most prolific electronic label"
  target_p95_ms: 4000

- name: nlq_suggestions
  method: GET
  path: /api/nlq/suggestions?pane=explore
  target_p95_ms: 200
```

Pattern-follow the existing scenario runner in `tests/perftest/run_perftest.py` to ensure it picks up the new entries (no code change expected if it iterates scenarios generically).

- [ ] **Step 2: Run the perftest locally**

Run: `uv run python tests/perftest/run_perftest.py --scenario nlq_suggestions`
Expected: PASS with p95 < 200ms.

- [ ] **Step 3: Commit**

```bash
git add tests/perftest/config.yaml tests/perftest/run_perftest.py
git commit -m "test(perftest): add NLQ query and suggestions scenarios"
```

### Task 30: Full regression + lint + coverage

- [ ] **Step 1: Run the Python test suite**

Run: `just test-parallel`
Expected: all pass.

- [ ] **Step 2: Run the JS test suite with coverage**

Run: `just test-js-cov`
Expected: all pass, coverage >80% on new modules.

- [ ] **Step 3: Run lint and format**

Run: `just lint`
Expected: green.

- [ ] **Step 4: Run semgrep**

Run: `uv run semgrep --config=auto common/ api/ mcp-server/ explore/static/js/`
Expected: no new findings.

- [ ] **Step 5: Commit any lint/format fixes**

```bash
git add -u
git commit -m "chore: lint and format fixes after NLQ ask mode redesign"
```

### Task 31: Open PR

- [ ] **Step 1: Push the branch**

```bash
git push -u origin worktree-fix-ai-ask
```

- [ ] **Step 2: Open PR**

```bash
gh pr create --title "feat: redesign Ask as a global pill with agent-driven UI actions" --body "$(cat <<'EOF'
## Summary

- Replaces the cramped navbar Ask toggle with a global floating pill that expands into a rich card with dynamic suggestions and recent-query history
- Adds a Tier 3 action vocabulary: the agent can drive the graph, switch panes, and open insight tiles alongside its text answer
- Fixes the markdown-in-summary bug via DOMPurify and injects entity links with proper DOM APIs
- Extracts `common/agent_tools/` so the NLQ engine and the MCP server share one tool registry

## Test plan

- [ ] `just test-parallel` green
- [ ] `just test-js-cov` green with >80% coverage on new frontend modules
- [ ] `just lint` clean
- [ ] E2E: click pill, submit a query, graph mutates, summary strip renders
- [ ] E2E: cross-pane query triggers pane switch
- [ ] Perftest: /api/nlq/suggestions p95 < 200ms
- [ ] MCP regression: Claude Desktop tools still return the same shape

Spec: docs/superpowers/specs/2026-04-14-ask-mode-integration-design.md
Plan: docs/superpowers/plans/2026-04-14-ask-mode-integration-plan.md

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Report PR URL to user**
