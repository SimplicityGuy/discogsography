# Query Debug Logging & Cypher Profiling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add opt-in query debug logging and Cypher profiling to the API service so developers can see full queries with parameters at DEBUG level and get PROFILE/EXPLAIN output for Cypher queries.

**Architecture:** Two new modules — `common/query_debug.py` for logging utilities and profiling logger setup, `api/queries/helpers.py` for consolidated Neo4j query helpers. All existing duplicated `_run_query`/`_run_single`/`_run_count` converge into the shared helpers. SQL execution sites use a new `execute_sql` wrapper. Profiling output goes to `/logs/profiling.log` only.

**Tech Stack:** Python 3.13+, structlog, stdlib logging, neo4j async driver, psycopg

**Spec:** `docs/superpowers/specs/2026-03-19-query-debug-profiling-design.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `common/query_debug.py` | Debug logging utilities, profiling logger, `execute_sql` wrapper |
| Create | `api/queries/helpers.py` | Consolidated `run_query`, `run_single`, `run_count` with profiling |
| Create | `tests/common/test_query_debug.py` | Tests for query_debug utilities |
| Create | `tests/api/test_query_helpers.py` | Tests for consolidated Neo4j helpers |
| Modify | `common/__init__.py` | Export new utilities |
| Modify | `common/config.py:216-335` | Add profiling startup warning |
| Modify | `api/queries/neo4j_queries.py:43-63` | Remove local helpers, import from helpers.py |
| Modify | `api/queries/user_queries.py:19-31` | Remove local helpers, import from helpers.py |
| Modify | `api/queries/taste_queries.py:13-25` | Remove local helpers, import from helpers.py |
| Modify | `api/queries/insights_neo4j_queries.py` | Replace inline session.run with helpers |
| Modify | `api/queries/gap_queries.py:16` | Update import path |
| Modify | `api/queries/label_dna_queries.py:10` | Update import path |
| Modify | `api/queries/recommend_queries.py:11` | Update import path |
| Modify | `api/syncer.py:211,372` | Add debug logging for write queries |
| Modify | `api/api.py` | Use `execute_sql` for SQL calls |
| Modify | `api/queries/search_queries.py` | Use `execute_sql` for SQL calls |
| Modify | `api/queries/insights_pg_queries.py:52` | Use `execute_sql` for SQL calls |
| Modify | `api/routers/sync.py` | Use `execute_sql` for SQL calls |
| Modify | `api/routers/collection.py:78` | Use `execute_sql` for SQL calls |
| Modify | `api/syncer.py` | Use `execute_sql` for SQL calls |
| Modify | Existing test files | Update imports from old helper locations |

---

### Task 1: Create `common/query_debug.py` with tests

**Files:**
- Create: `common/query_debug.py`
- Create: `tests/common/test_query_debug.py`
- Modify: `common/__init__.py`

- [ ] **Step 1: Write tests for `is_debug` and `is_cypher_profiling`**

Create `tests/common/test_query_debug.py`:

```python
"""Tests for common/query_debug.py debug logging utilities."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from common.query_debug import (
    execute_sql,
    is_cypher_profiling,
    is_debug,
    log_cypher_query,
    log_explain_result,
    log_profile_result,
    log_sql_query,
)


@pytest.fixture(autouse=True)
def _restore_root_log_level() -> None:
    """Save and restore root logger level to prevent test pollution."""
    original = logging.getLogger().level
    yield  # type: ignore[misc]
    logging.getLogger().setLevel(original)


class TestIsDebug:
    def test_true_when_debug(self) -> None:
        logging.getLogger().setLevel(logging.DEBUG)
        assert is_debug() is True

    def test_false_when_info(self) -> None:
        logging.getLogger().setLevel(logging.INFO)
        assert is_debug() is False

    def test_false_when_warning(self) -> None:
        logging.getLogger().setLevel(logging.WARNING)
        assert is_debug() is False


class TestIsCypherProfiling:
    def test_true_when_debug_and_env_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        logging.getLogger().setLevel(logging.DEBUG)
        monkeypatch.setenv("CYPHER_PROFILING", "true")
        assert is_cypher_profiling() is True

    def test_true_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        logging.getLogger().setLevel(logging.DEBUG)
        monkeypatch.setenv("CYPHER_PROFILING", "True")
        assert is_cypher_profiling() is True

    def test_false_when_not_debug(self, monkeypatch: pytest.MonkeyPatch) -> None:
        logging.getLogger().setLevel(logging.INFO)
        monkeypatch.setenv("CYPHER_PROFILING", "true")
        assert is_cypher_profiling() is False

    def test_false_when_env_not_set(self) -> None:
        logging.getLogger().setLevel(logging.DEBUG)
        assert is_cypher_profiling() is False

    def test_false_when_env_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        logging.getLogger().setLevel(logging.DEBUG)
        monkeypatch.setenv("CYPHER_PROFILING", "false")
        assert is_cypher_profiling() is False
```

- [ ] **Step 2: Write tests for `log_cypher_query` and `log_sql_query`**

Append to `tests/common/test_query_debug.py`:

```python
class TestLogCypherQuery:
    def test_logs_at_debug_level(self, caplog: pytest.LogCaptureFixture) -> None:
        logging.getLogger().setLevel(logging.DEBUG)
        with caplog.at_level(logging.DEBUG):
            log_cypher_query("MATCH (a:Artist) RETURN a", {"limit": 10})
        assert "MATCH (a:Artist) RETURN a" in caplog.text

    def test_no_log_when_not_debug(self, caplog: pytest.LogCaptureFixture) -> None:
        logging.getLogger().setLevel(logging.INFO)
        with caplog.at_level(logging.INFO):
            log_cypher_query("MATCH (a:Artist) RETURN a", {"limit": 10})
        assert "MATCH (a:Artist)" not in caplog.text


class TestLogSqlQuery:
    def test_logs_string_query(self, caplog: pytest.LogCaptureFixture) -> None:
        logging.getLogger().setLevel(logging.DEBUG)
        cursor = MagicMock()
        with caplog.at_level(logging.DEBUG):
            log_sql_query("SELECT * FROM artists WHERE id = %s", [123], cursor)
        assert "SELECT * FROM artists" in caplog.text

    def test_logs_composable_query(self, caplog: pytest.LogCaptureFixture) -> None:
        logging.getLogger().setLevel(logging.DEBUG)
        composable = MagicMock()
        composable.as_string.return_value = "SELECT * FROM artists"
        cursor = MagicMock()
        with caplog.at_level(logging.DEBUG):
            log_sql_query(composable, [123], cursor)
        assert "SELECT * FROM artists" in caplog.text
```

- [ ] **Step 3: Write tests for `execute_sql`**

Append to `tests/common/test_query_debug.py`:

```python
class TestExecuteSql:
    @pytest.mark.asyncio
    async def test_delegates_to_cursor_execute(self) -> None:
        cursor = AsyncMock()
        await execute_sql(cursor, "SELECT 1", None)
        cursor.execute.assert_awaited_once_with("SELECT 1", None)

    @pytest.mark.asyncio
    async def test_delegates_with_params(self) -> None:
        cursor = AsyncMock()
        await execute_sql(cursor, "SELECT * FROM t WHERE id = %s", [42])
        cursor.execute.assert_awaited_once_with("SELECT * FROM t WHERE id = %s", [42])

    @pytest.mark.asyncio
    async def test_logs_when_debug(self, caplog: pytest.LogCaptureFixture) -> None:
        logging.getLogger().setLevel(logging.DEBUG)
        cursor = AsyncMock()
        with caplog.at_level(logging.DEBUG):
            await execute_sql(cursor, "SELECT * FROM artists", None)
        assert "SELECT * FROM artists" in caplog.text

    @pytest.mark.asyncio
    async def test_no_log_when_info(self, caplog: pytest.LogCaptureFixture) -> None:
        logging.getLogger().setLevel(logging.INFO)
        cursor = AsyncMock()
        with caplog.at_level(logging.INFO):
            await execute_sql(cursor, "SELECT * FROM artists", None)
        assert "SELECT * FROM artists" not in caplog.text
```

- [ ] **Step 4: Write tests for `log_profile_result` and `log_explain_result`**

Append to `tests/common/test_query_debug.py`:

```python
class TestLogProfileResult:
    def test_writes_to_profiling_logger(self, tmp_path: Path) -> None:
        from common import query_debug

        # Reset cached logger so we can point it at tmp_path
        query_debug._profiling_logger = None
        with patch.object(query_debug, "get_profiling_logger") as mock_get:
            mock_logger = logging.getLogger("test_profile")
            handler = logging.FileHandler(tmp_path / "profiling.log")
            mock_logger.addHandler(handler)
            mock_logger.setLevel(logging.DEBUG)
            mock_get.return_value = mock_logger

            summary = MagicMock()
            summary.profile = {"args": {"string-representation": "Operator | Rows\nNodeScan | 10"}}
            log_profile_result("MATCH (a) RETURN a", {"id": "1"}, summary)

            handler.flush()
            content = (tmp_path / "profiling.log").read_text()
            assert "PROFILE result" in content
            assert "MATCH (a) RETURN a" in content
            assert "NodeScan" in content

    def test_handles_missing_profile(self) -> None:
        from common import query_debug

        with patch.object(query_debug, "get_profiling_logger") as mock_get:
            mock_logger = MagicMock()
            mock_get.return_value = mock_logger
            summary = MagicMock()
            summary.profile = None
            log_profile_result("MATCH (a) RETURN a", {}, summary)
            mock_logger.info.assert_called_once()


class TestLogExplainResult:
    def test_writes_error_and_plan(self, tmp_path: Path) -> None:
        from common import query_debug

        query_debug._profiling_logger = None
        with patch.object(query_debug, "get_profiling_logger") as mock_get:
            mock_logger = logging.getLogger("test_explain")
            handler = logging.FileHandler(tmp_path / "profiling.log")
            mock_logger.addHandler(handler)
            mock_logger.setLevel(logging.DEBUG)
            mock_get.return_value = mock_logger

            summary = MagicMock()
            summary.plan = {"args": {"string-representation": "Planner: COST\nNodeScan | 10"}}
            error = TimeoutError("query timed out")
            log_explain_result("MATCH (a) RETURN a", {"id": "1"}, summary, error)

            handler.flush()
            content = (tmp_path / "profiling.log").read_text()
            assert "EXPLAIN (after error)" in content
            assert "MATCH (a) RETURN a" in content
            assert "TimeoutError" in content
            assert "NodeScan" in content
```

Add `from pathlib import Path` to the imports at the top of the test file.

- [ ] **Step 5: Run tests to verify they fail**

Run: `uv run pytest tests/common/test_query_debug.py -v`
Expected: FAIL — `common/query_debug.py` does not exist yet.

- [ ] **Step 6: Implement `common/query_debug.py`**

Create `common/query_debug.py`:

Note: Uses stdlib `logging.getLogger()` for `_logger` rather than `structlog.get_logger()`.
This ensures `caplog` captures debug output in tests without requiring structlog configuration.
The output still flows through the structlog `ProcessorFormatter` when `setup_logging()` has
been called (i.e., in production), because `setup_logging()` configures the root logger's
handlers with structlog formatters.

```python
"""Query debug logging and Cypher profiling utilities.

When LOG_LEVEL=DEBUG, logs full query text with parameter values for both
Cypher and SQL queries. When CYPHER_PROFILING=true (and DEBUG), writes
PROFILE/EXPLAIN summaries to /logs/profiling.log.
"""

import logging
import os
from pathlib import Path
from typing import Any


_logger = logging.getLogger("query_debug")
_profiling_logger: logging.Logger | None = None


def is_debug() -> bool:
    """Check if the root logger is at DEBUG level."""
    return logging.getLogger().isEnabledFor(logging.DEBUG)


def is_cypher_profiling() -> bool:
    """Check if Cypher profiling is enabled (DEBUG + CYPHER_PROFILING=true)."""
    return is_debug() and os.getenv("CYPHER_PROFILING", "").lower() == "true"


def get_profiling_logger() -> logging.Logger:
    """Get or create the profiling file logger (writes to /logs/profiling.log)."""
    global _profiling_logger  # noqa: PLW0603
    if _profiling_logger is None:
        _profiling_logger = logging.getLogger("cypher_profiling")
        _profiling_logger.setLevel(logging.DEBUG)
        _profiling_logger.propagate = False
        log_dir = Path("/logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_dir / "profiling.log")
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        _profiling_logger.addHandler(handler)
    return _profiling_logger


def log_cypher_query(cypher: str, params: dict[str, Any]) -> None:
    """Log a Cypher query with parameters at DEBUG level."""
    if is_debug():
        _logger.debug("🔗 Cypher query: %s | params: %s", cypher.strip(), params)


def log_sql_query(
    query: Any,
    params: list[Any] | tuple[Any, ...] | dict[str, Any] | None,
    cursor: Any,
) -> None:
    """Log a SQL query with parameters at DEBUG level.

    Handles both plain string queries and psycopg sql.Composable objects.
    """
    if is_debug():
        query_str = query.as_string(cursor) if hasattr(query, "as_string") else str(query)
        _logger.debug("🐘 SQL query: %s | params: %s", query_str.strip(), params)


async def execute_sql(
    cursor: Any,
    query: Any,
    params: list[Any] | tuple[Any, ...] | dict[str, Any] | None = None,
) -> None:
    """Execute a SQL query, logging at DEBUG level beforehand."""
    log_sql_query(query, params, cursor)
    await cursor.execute(query, params)


def log_profile_result(cypher: str, params: dict[str, Any], summary: Any) -> None:
    """Write PROFILE results to the profiling log file."""
    profiling_log = get_profiling_logger()
    profile = getattr(summary, "profile", None)
    text = ""
    if profile:
        args = profile.get("args", {}) if isinstance(profile, dict) else getattr(profile, "args", {})
        text = args.get("string-representation", str(profile))

    profiling_log.info(
        "\n══════════════════════════════════════════════════════════\n"
        "PROFILE result for Cypher query:\n\n"
        "%s\n\n"
        "Parameters: %s\n\n"
        "%s",
        cypher.strip(),
        params,
        text,
    )


def log_explain_result(
    cypher: str,
    params: dict[str, Any],
    summary: Any,
    original_error: Exception,
) -> None:
    """Write EXPLAIN results to the profiling log file after a query failure."""
    profiling_log = get_profiling_logger()
    plan = getattr(summary, "plan", None)
    text = ""
    if plan:
        args = plan.get("args", {}) if isinstance(plan, dict) else getattr(plan, "args", {})
        text = args.get("string-representation", str(plan))

    profiling_log.info(
        "\n══════════════════════════════════════════════════════════\n"
        "EXPLAIN (after error) for Cypher query:\n\n"
        "%s\n\n"
        "Parameters: %s\n"
        "Original error: %s: %s\n\n"
        "%s",
        cypher.strip(),
        params,
        type(original_error).__name__,
        original_error,
        text,
    )
```

- [ ] **Step 7: Export from `common/__init__.py`**

Add to imports in `common/__init__.py`:

```python
from common.query_debug import (
    execute_sql,
    is_cypher_profiling,
    is_debug,
    log_cypher_query,
    log_sql_query,
)
```

Add to `__all__` list:

```python
    "execute_sql",
    "is_cypher_profiling",
    "is_debug",
    "log_cypher_query",
    "log_sql_query",
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/common/test_query_debug.py -v`
Expected: All PASS.

- [ ] **Step 9: Commit**

```bash
git add common/query_debug.py tests/common/test_query_debug.py common/__init__.py
git commit -m "feat: add query debug logging utilities (common/query_debug.py)"
```

---

### Task 2: Create `api/queries/helpers.py` with tests

**Files:**
- Create: `api/queries/helpers.py`
- Create: `tests/api/test_query_helpers.py`

- [ ] **Step 1: Write tests for `run_query`**

Create `tests/api/test_query_helpers.py`:

```python
"""Tests for api/queries/helpers.py consolidated Neo4j query helpers."""

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class _AsyncIter:
    """Async iterator for mock Neo4j results."""

    def __init__(self, records: list[dict[str, Any]]) -> None:
        self._records = records
        self._index = 0

    def __aiter__(self) -> "_AsyncIter":
        return self

    async def __anext__(self) -> dict[str, Any]:
        if self._index >= len(self._records):
            raise StopAsyncIteration
        record = self._records[self._index]
        self._index += 1
        return record


class _MockResult:
    """Mock Neo4j result supporting async iteration, .single(), and .consume()."""

    def __init__(
        self,
        records: list[dict[str, Any]] | None = None,
        single: dict[str, Any] | None = None,
    ) -> None:
        self._records = records or []
        self._single = single
        self._summary = MagicMock()
        self._summary.profile = None
        self._summary.plan = None

    def __aiter__(self) -> _AsyncIter:
        return _AsyncIter(self._records)

    async def single(self) -> dict[str, Any] | None:
        return self._single

    async def consume(self) -> MagicMock:
        return self._summary


def _make_driver(
    records: list[dict[str, Any]] | None = None,
    single: dict[str, Any] | None = None,
) -> MagicMock:
    """Build a minimal mock AsyncResilientNeo4jDriver."""
    mock_result = _MockResult(records=records, single=single)
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.run = AsyncMock(return_value=mock_result)

    driver = MagicMock()
    driver.session = MagicMock(return_value=mock_session)
    return driver


@pytest.fixture(autouse=True)
def _restore_root_log_level() -> None:
    """Save and restore root logger level to prevent test pollution."""
    original = logging.getLogger().level
    yield  # type: ignore[misc]
    logging.getLogger().setLevel(original)


class TestRunQuery:
    @pytest.mark.asyncio
    async def test_returns_list_of_dicts(self) -> None:
        from api.queries.helpers import run_query

        driver = _make_driver(records=[{"id": "1", "name": "Test"}])
        result = await run_query(driver, "MATCH (a) RETURN a", id="1")
        assert result == [{"id": "1", "name": "Test"}]

    @pytest.mark.asyncio
    async def test_passes_timeout(self) -> None:
        from api.queries.helpers import run_query

        driver = _make_driver(records=[])
        await run_query(driver, "MATCH (a) RETURN a", timeout=60)
        session = driver.session.return_value.__aenter__.return_value
        session.run.assert_awaited_once()
        call_kwargs = session.run.call_args
        assert call_kwargs[1].get("timeout") == 60

    @pytest.mark.asyncio
    async def test_passes_database(self) -> None:
        from api.queries.helpers import run_query

        driver = _make_driver(records=[])
        await run_query(driver, "MATCH (a) RETURN a", database="neo4j")
        driver.session.assert_called_with(database="neo4j")

    @pytest.mark.asyncio
    async def test_logs_at_debug(self, caplog: pytest.LogCaptureFixture) -> None:
        from api.queries.helpers import run_query

        logging.getLogger().setLevel(logging.DEBUG)
        driver = _make_driver(records=[])
        with caplog.at_level(logging.DEBUG):
            await run_query(driver, "MATCH (a) RETURN a", name="test")
        assert "MATCH (a) RETURN a" in caplog.text

    @pytest.mark.asyncio
    async def test_no_log_at_info(self, caplog: pytest.LogCaptureFixture) -> None:
        from api.queries.helpers import run_query

        logging.getLogger().setLevel(logging.INFO)
        driver = _make_driver(records=[])
        with caplog.at_level(logging.INFO):
            await run_query(driver, "MATCH (a) RETURN a", name="test")
        assert "MATCH (a) RETURN a" not in caplog.text

    @pytest.mark.asyncio
    async def test_profile_prefix_when_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from api.queries.helpers import run_query

        logging.getLogger().setLevel(logging.DEBUG)
        monkeypatch.setenv("CYPHER_PROFILING", "true")
        driver = _make_driver(records=[])
        await run_query(driver, "MATCH (a) RETURN a")
        session = driver.session.return_value.__aenter__.return_value
        call_args = session.run.call_args[0]
        assert call_args[0].startswith("PROFILE ")

    @pytest.mark.asyncio
    async def test_no_profile_prefix_when_disabled(self) -> None:
        from api.queries.helpers import run_query

        logging.getLogger().setLevel(logging.INFO)
        driver = _make_driver(records=[])
        await run_query(driver, "MATCH (a) RETURN a")
        session = driver.session.return_value.__aenter__.return_value
        call_args = session.run.call_args[0]
        assert not call_args[0].startswith("PROFILE ")


class TestRunSingle:
    @pytest.mark.asyncio
    async def test_returns_dict(self) -> None:
        from api.queries.helpers import run_single

        driver = _make_driver(single={"id": "1", "name": "Test"})
        result = await run_single(driver, "MATCH (a) RETURN a", id="1")
        assert result == {"id": "1", "name": "Test"}

    @pytest.mark.asyncio
    async def test_returns_none_when_no_result(self) -> None:
        from api.queries.helpers import run_single

        driver = _make_driver(single=None)
        result = await run_single(driver, "MATCH (a) RETURN a", id="1")
        assert result is None


class TestRunCount:
    @pytest.mark.asyncio
    async def test_returns_count(self) -> None:
        from api.queries.helpers import run_count

        driver = _make_driver(single={"total": 42})
        result = await run_count(driver, "MATCH (a) RETURN count(a) AS total")
        assert result == 42

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_result(self) -> None:
        from api.queries.helpers import run_count

        driver = _make_driver(single=None)
        result = await run_count(driver, "MATCH (a) RETURN count(a) AS total")
        assert result == 0


class TestExplainFallback:
    """Test that EXPLAIN is attempted when a profiled query fails."""

    @pytest.mark.asyncio
    async def test_explain_on_error_and_reraises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from api.queries.helpers import run_query

        logging.getLogger().setLevel(logging.DEBUG)
        monkeypatch.setenv("CYPHER_PROFILING", "true")

        # First session raises, second session (for EXPLAIN) succeeds
        error = RuntimeError("query timed out")
        explain_summary = MagicMock()
        explain_summary.plan = {"args": {"string-representation": "NodeScan"}}
        explain_result = MagicMock()
        explain_result.consume = AsyncMock(return_value=explain_summary)

        call_count = 0

        async def _run_side_effect(*args: Any, **kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise error
            return explain_result

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.run = AsyncMock(side_effect=_run_side_effect)

        driver = MagicMock()
        driver.session = MagicMock(return_value=mock_session)

        with patch("api.queries.helpers.log_explain_result") as mock_log_explain:
            with pytest.raises(RuntimeError, match="query timed out"):
                await run_query(driver, "MATCH (a) RETURN a")
            mock_log_explain.assert_called_once()

    @pytest.mark.asyncio
    async def test_explain_failure_is_swallowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If EXPLAIN itself fails, the original error is still raised."""
        from api.queries.helpers import run_query

        logging.getLogger().setLevel(logging.DEBUG)
        monkeypatch.setenv("CYPHER_PROFILING", "true")

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.run = AsyncMock(side_effect=RuntimeError("db down"))

        driver = MagicMock()
        driver.session = MagicMock(return_value=mock_session)

        with pytest.raises(RuntimeError, match="db down"):
            await run_query(driver, "MATCH (a) RETURN a")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_query_helpers.py -v`
Expected: FAIL — `api/queries/helpers.py` does not exist yet.

- [ ] **Step 3: Implement `api/queries/helpers.py`**

Create `api/queries/helpers.py`:

```python
"""Consolidated Neo4j Cypher query execution helpers.

Centralizes _run_query, _run_single, _run_count that were previously
duplicated across neo4j_queries.py, user_queries.py, taste_queries.py,
and insights_neo4j_queries.py. Adds DEBUG query logging and optional
PROFILE/EXPLAIN support.
"""

from typing import Any

from common import AsyncResilientNeo4jDriver
from common.query_debug import (
    is_cypher_profiling,
    log_cypher_query,
    log_explain_result,
    log_profile_result,
)


async def _try_explain_on_error(
    driver: AsyncResilientNeo4jDriver,
    cypher: str,
    params: dict[str, Any],
    error: Exception,
    database: str | None = None,
) -> None:
    """Best-effort EXPLAIN after a query failure, logging the plan."""
    try:
        session_kwargs: dict[str, Any] = {}
        if database:
            session_kwargs["database"] = database
        async with driver.session(**session_kwargs) as session:
            explain_cypher = f"EXPLAIN {cypher}"
            result = await session.run(explain_cypher, params)
            summary = await result.consume()
            log_explain_result(cypher, params, summary, error)
    except Exception:
        pass  # Best effort — DB may be unreachable


async def run_query(
    driver: AsyncResilientNeo4jDriver,
    cypher: str,
    *,
    timeout: float | None = None,
    database: str | None = None,
    **params: Any,
) -> list[dict[str, Any]]:
    """Execute a Cypher query and return all results as a list of dicts."""
    log_cypher_query(cypher, params)
    profiling = is_cypher_profiling()
    actual_cypher = f"PROFILE {cypher}" if profiling else cypher

    run_kwargs: dict[str, Any] = {}
    if timeout is not None:
        run_kwargs["timeout"] = timeout

    session_kwargs: dict[str, Any] = {}
    if database:
        session_kwargs["database"] = database

    try:
        async with driver.session(**session_kwargs) as session:
            result = await session.run(actual_cypher, params, **run_kwargs)
            records = [dict(record) async for record in result]
            if profiling:
                summary = await result.consume()
                log_profile_result(cypher, params, summary)
            return records
    except Exception as e:
        if profiling:
            await _try_explain_on_error(driver, cypher, params, e, database)
        raise


async def run_single(
    driver: AsyncResilientNeo4jDriver,
    cypher: str,
    *,
    timeout: float | None = None,
    database: str | None = None,
    **params: Any,
) -> dict[str, Any] | None:
    """Execute a Cypher query and return a single result, or None."""
    log_cypher_query(cypher, params)
    profiling = is_cypher_profiling()
    actual_cypher = f"PROFILE {cypher}" if profiling else cypher

    run_kwargs: dict[str, Any] = {}
    if timeout is not None:
        run_kwargs["timeout"] = timeout

    session_kwargs: dict[str, Any] = {}
    if database:
        session_kwargs["database"] = database

    try:
        async with driver.session(**session_kwargs) as session:
            result = await session.run(actual_cypher, params, **run_kwargs)
            record = await result.single()
            if profiling:
                summary = await result.consume()
                log_profile_result(cypher, params, summary)
            return dict(record) if record else None
    except Exception as e:
        if profiling:
            await _try_explain_on_error(driver, cypher, params, e, database)
        raise


async def run_count(
    driver: AsyncResilientNeo4jDriver,
    cypher: str,
    *,
    timeout: float | None = None,
    database: str | None = None,
    **params: Any,
) -> int:
    """Execute a count Cypher query and return the integer result."""
    log_cypher_query(cypher, params)
    profiling = is_cypher_profiling()
    actual_cypher = f"PROFILE {cypher}" if profiling else cypher

    run_kwargs: dict[str, Any] = {}
    if timeout is not None:
        run_kwargs["timeout"] = timeout

    session_kwargs: dict[str, Any] = {}
    if database:
        session_kwargs["database"] = database

    try:
        async with driver.session(**session_kwargs) as session:
            result = await session.run(actual_cypher, params, **run_kwargs)
            record = await result.single()
            if profiling:
                summary = await result.consume()
                log_profile_result(cypher, params, summary)
            return int(record["total"]) if record else 0
    except Exception as e:
        if profiling:
            await _try_explain_on_error(driver, cypher, params, e, database)
        raise
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_query_helpers.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add api/queries/helpers.py tests/api/test_query_helpers.py
git commit -m "feat: add consolidated Neo4j query helpers with profiling (api/queries/helpers.py)"
```

---

### Task 3: Migrate `neo4j_queries.py` to use shared helpers

**Files:**
- Modify: `api/queries/neo4j_queries.py`

- [ ] **Step 1: Remove local helper definitions and add import**

In `api/queries/neo4j_queries.py`, remove lines 43-63 (the three local helper functions) and replace with:

```python
from api.queries.helpers import run_count, run_query, run_single
```

**Keep** `from common import AsyncResilientNeo4jDriver` — it is still used as a type annotation in `find_shortest_path` and other function signatures in this file.

- [ ] **Step 2: Replace all `_run_query` calls with `run_query`, `_run_single` with `run_single`, `_run_count` with `run_count`**

Use find-and-replace across the file:
- `_run_query(` → `run_query(`
- `_run_single(` → `run_single(`
- `_run_count(` → `run_count(`

- [ ] **Step 3: Run existing tests**

Run: `uv run pytest tests/api/test_neo4j_queries.py -v`
Expected: All PASS. The mock driver pattern is the same.

- [ ] **Step 4: Commit**

```bash
git add api/queries/neo4j_queries.py
git commit -m "refactor: migrate neo4j_queries.py to shared query helpers"
```

---

### Task 4: Migrate `user_queries.py` to use shared helpers

**Files:**
- Modify: `api/queries/user_queries.py`

- [ ] **Step 1: Remove local helpers and add import**

Remove lines 19-31 (local `_run_query` and `_run_count`). Add import:

```python
from api.queries.helpers import run_count, run_query
```

- [ ] **Step 2: Replace `_run_query` with `run_query` and `_run_count` with `run_count`**

Find-and-replace across the file.

- [ ] **Step 3: Run existing tests**

Run: `uv run pytest tests/api/test_user_queries.py -v`
Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add api/queries/user_queries.py
git commit -m "refactor: migrate user_queries.py to shared query helpers"
```

---

### Task 5: Migrate `taste_queries.py` to use shared helpers

**Files:**
- Modify: `api/queries/taste_queries.py`

- [ ] **Step 1: Remove local helpers and add import**

Remove lines 13-25 (local `_run_query` and `_run_count`). Add import:

```python
from api.queries.helpers import run_count, run_query
```

- [ ] **Step 2: Replace calls and add explicit timeout**

Replace `_run_query` with `run_query` and `_run_count` with `run_count`. The old helpers had `timeout=120` as default. Each call site in this file should now pass `timeout=120` explicitly. For example:

```python
# Old:
cells, total = await asyncio.gather(
    _run_query(driver, cypher, user_id=user_id),
    _run_count(driver, count_cypher, user_id=user_id),
)
# New:
cells, total = await asyncio.gather(
    run_query(driver, cypher, timeout=120, user_id=user_id),
    run_count(driver, count_cypher, timeout=120, user_id=user_id),
)
```

- [ ] **Step 3: Run existing tests**

Run: `uv run pytest tests/api/test_taste_queries.py -v`
Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add api/queries/taste_queries.py
git commit -m "refactor: migrate taste_queries.py to shared query helpers"
```

---

### Task 6: Migrate `insights_neo4j_queries.py` to use shared helpers

**Files:**
- Modify: `api/queries/insights_neo4j_queries.py`

- [ ] **Step 1: Replace inline session management with helper calls**

Add import:

```python
from api.queries.helpers import run_query
```

For each of the 4 query functions, replace the inline `async with driver.session(database="neo4j")` pattern with `run_query(driver, cypher, database="neo4j", **params)`. For example, `query_artist_centrality`:

```python
async def query_artist_centrality(driver: Any, limit: int = 100) -> list[dict[str, Any]]:
    cypher = """
    MATCH (a:Artist)
    WITH a, size([(a)-[]-() | 1]) AS edge_count
    ORDER BY edge_count DESC
    LIMIT $limit
    RETURN a.id AS artist_id, a.name AS artist_name, edge_count
    """
    results = await run_query(driver, cypher, database="neo4j", limit=limit)
    logger.info("🔍 Artist centrality query complete", count=len(results))
    return results
```

Note: The old code used `record.data()` while the helper uses `dict(record)`. These are functionally equivalent for the field projections used here — both produce `dict[str, Any]` from the record.

Apply the same pattern to all remaining functions. Here are the complete rewrites for the non-trivial ones:

**`query_genre_trends`** (has conditional params):

```python
async def query_genre_trends(driver: Any, genre: str | None = None) -> list[dict[str, Any]]:
    if genre:
        cypher = """
        MATCH (r:Release)-[:HAS_GENRE]->(g:Genre {name: $genre})
        WHERE r.year IS NOT NULL AND r.year > 0
        WITH g.name AS genre, (r.year / 10) * 10 AS decade, count(r) AS release_count
        ORDER BY decade
        RETURN genre, decade, release_count
        """
        results = await run_query(driver, cypher, database="neo4j", genre=genre)
    else:
        cypher = """
        MATCH (r:Release)-[:HAS_GENRE]->(g:Genre)
        WHERE r.year IS NOT NULL AND r.year > 0
        WITH g.name AS genre, (r.year / 10) * 10 AS decade, count(r) AS release_count
        ORDER BY genre, decade
        RETURN genre, decade, release_count
        """
        results = await run_query(driver, cypher, database="neo4j")
    logger.info("🔍 Genre trends query complete", count=len(results), genre=genre)
    return results
```

**`query_label_longevity`**:

```python
async def query_label_longevity(driver: Any, limit: int = 50) -> list[dict[str, Any]]:
    cypher = """..."""  # (same as existing)
    results = await run_query(driver, cypher, database="neo4j", limit=limit)
    logger.info("🔍 Label longevity query complete", count=len(results))
    return results
```

**`query_monthly_anniversaries`** (has computed list param):

```python
async def query_monthly_anniversaries(
    driver: Any, current_year: int, current_month: int,
    milestone_years: list[int] | None = None,
) -> list[dict[str, Any]]:
    if milestone_years is None:
        milestone_years = [25, 30, 40, 50, 75, 100]
    target_years = [current_year - m for m in milestone_years]
    cypher = """..."""  # (same as existing)
    results = await run_query(driver, cypher, database="neo4j", target_years=target_years)
    logger.info("🔍 Monthly anniversaries query complete", count=len(results),
                month=current_month, year=current_year)
    return results
```

- [ ] **Step 2: Run existing tests**

Run: `uv run pytest tests/insights/test_neo4j_queries.py -v`
Expected: All PASS.

- [ ] **Step 3: Commit**

```bash
git add api/queries/insights_neo4j_queries.py
git commit -m "refactor: migrate insights_neo4j_queries.py to shared query helpers"
```

---

### Task 7: Update import paths in dependent query files

**Files:**
- Modify: `api/queries/gap_queries.py:16`
- Modify: `api/queries/label_dna_queries.py:10`
- Modify: `api/queries/recommend_queries.py:11`

- [ ] **Step 1: Update gap_queries.py import**

Change line 16 from:
```python
from api.queries.user_queries import _run_count, _run_query
```
to:
```python
from api.queries.helpers import run_count, run_query
```

Replace `_run_query` with `run_query` and `_run_count` with `run_count` throughout the file.

- [ ] **Step 2: Update label_dna_queries.py import**

Change line 10 from:
```python
from api.queries.neo4j_queries import _run_query, _run_single
```
to:
```python
from api.queries.helpers import run_query, run_single
```

Replace `_run_query` with `run_query` and `_run_single` with `run_single` throughout the file.

- [ ] **Step 3: Update recommend_queries.py import**

Change line 11 from:
```python
from api.queries.neo4j_queries import _run_query, _run_single
```
to:
```python
from api.queries.helpers import run_query, run_single
```

Replace `_run_query` with `run_query` and `_run_single` with `run_single` throughout the file.

- [ ] **Step 4: Run tests for all affected files**

Run: `uv run pytest tests/api/test_gap_queries.py tests/api/test_label_dna_queries.py tests/api/test_recommend_queries.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add api/queries/gap_queries.py api/queries/label_dna_queries.py api/queries/recommend_queries.py
git commit -m "refactor: update query file imports to use shared helpers"
```

---

### Task 8: Add debug logging to syncer write queries

**Files:**
- Modify: `api/syncer.py`

- [ ] **Step 1: Add import**

Add to syncer.py imports:

```python
from common.query_debug import log_cypher_query
```

- [ ] **Step 2: Add debug logging before each session.run()**

Before the `session.run()` at line ~211 (collection sync), add:

```python
log_cypher_query(cypher, {"user_id": str(user_uuid), "discogs_username": discogs_username, "releases": f"[{len(neo4j_releases)} items]", "synced_at": "..."})
```

Before the `session.run()` at line ~372 (wantlist sync), add the same pattern with the wantlist params.

Note: For write queries we log a summary (item count) rather than the full list of release data to avoid enormous log entries. We do NOT add PROFILE to these — they are write queries excluded from profiling per spec.

- [ ] **Step 3: Run existing tests**

Run: `uv run pytest tests/api/test_syncer.py -v`
Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add api/syncer.py
git commit -m "feat: add debug logging for syncer Neo4j write queries"
```

---

### Task 9: Migrate SQL execution sites to `execute_sql`

**Files:**
- Modify: `api/api.py` (lines 298, 346, 415, 442, 452, 603, 658, 694)
- Modify: `api/queries/search_queries.py` (lines 152, 182, 207, 225, 250)
- Modify: `api/queries/insights_pg_queries.py` (line 52)
- Modify: `api/routers/sync.py` (lines 107, 118, 155)
- Modify: `api/routers/collection.py` (line 78)
- Modify: `api/syncer.py` (lines 417, 435, 487)

- [ ] **Step 1: Add `execute_sql` import to each file**

Add to each file's imports:

```python
from common import execute_sql
```

- [ ] **Step 2: Replace `await cur.execute(query, params)` with `await execute_sql(cur, query, params)` in api/api.py**

For each of the 8 call sites in api.py, change:
```python
await cur.execute(query, params)
```
to:
```python
await execute_sql(cur, query, params)
```

Where `params` is the second argument (or `None` if not present). Some calls use positional args — keep the same structure:
```python
# Old:
await cur.execute("SELECT value FROM app_config WHERE key = %s", (key,))
# New:
await execute_sql(cur, "SELECT value FROM app_config WHERE key = %s", (key,))
```

- [ ] **Step 3: Replace in search_queries.py**

5 call sites. Same pattern. Note the `# nosemgrep` comments should be preserved:

```python
# Old:
await cur.execute(query, params)  # nosemgrep
# New:
await execute_sql(cur, query, params)  # nosemgrep
```

- [ ] **Step 4: Replace in insights_pg_queries.py**

1 call site:
```python
# Old:
await cursor.execute(_COMBINED_QUERIES[entity_type])
# New:
await execute_sql(cursor, _COMBINED_QUERIES[entity_type])
```

- [ ] **Step 5: Replace in routers/sync.py**

3 call sites. Same pattern.

- [ ] **Step 6: Replace in routers/collection.py**

1 call site. Same pattern.

- [ ] **Step 7: Replace in syncer.py (SQL calls only)**

3 call sites (lines 417, 435, 487). Same pattern. Note: the `executemany` calls at lines 157 and 323 are batch inserts — leave these as-is since `execute_sql` wraps `execute`, not `executemany`.

- [ ] **Step 8: Run full test suite**

Run: `uv run pytest tests/api/ -v --timeout=60`
Expected: All PASS.

- [ ] **Step 9: Commit**

```bash
git add api/api.py api/queries/search_queries.py api/queries/insights_pg_queries.py api/routers/sync.py api/routers/collection.py api/syncer.py
git commit -m "feat: add debug SQL query logging via execute_sql wrapper"
```

---

### Task 10: Add profiling startup warning to `setup_logging`

**Files:**
- Modify: `common/config.py`

- [ ] **Step 1: Add startup warning**

At the end of `setup_logging()` (after line 335), add:

```python
    # Warn if Cypher profiling is active
    if level.upper() == "DEBUG" and getenv("CYPHER_PROFILING", "").lower() == "true":
        log.warning(
            "⚠️ Cypher profiling enabled — PROFILE prefix will be added to all Cypher queries",
            cypher_profiling=True,
        )
```

- [ ] **Step 2: Run config tests**

Run: `uv run pytest tests/common/test_config.py -v`
Expected: All PASS.

- [ ] **Step 3: Commit**

```bash
git add common/config.py
git commit -m "feat: log startup warning when Cypher profiling is active"
```

---

### Task 11: Update existing test imports

**Files:**
- Modify: `tests/api/test_neo4j_queries.py`
- Modify: `tests/api/test_user_queries.py`

- [ ] **Step 1: Delete `TestRunHelpers` class from `tests/api/test_neo4j_queries.py`**

Delete lines 127-181 (the `TestRunHelpers` class and its 6 test methods) from `tests/api/test_neo4j_queries.py`. These tests directly import `_run_query`, `_run_single`, `_run_count` from `neo4j_queries.py` which no longer exist there. The equivalent tests are now in `tests/api/test_query_helpers.py` (Task 2).

The affected imports (inside each test method, not at module level):
```python
# DELETE these 6 test methods that use:
from api.queries.neo4j_queries import _run_query   # lines 135, 144
from api.queries.neo4j_queries import _run_single   # lines 152, 161
from api.queries.neo4j_queries import _run_count    # lines 169, 177
```

- [ ] **Step 2: Update `tests/api/test_user_queries.py` helper imports**

This file has test methods that import `_run_query` and `_run_count` from `user_queries.py` (lines 78, 87, 102, 110). These are inline imports inside test methods. Update each occurrence:

```python
# Old (inside test methods):
from api.queries.user_queries import _run_query
from api.queries.user_queries import _run_count

# New:
from api.queries.helpers import run_query
from api.queries.helpers import run_count
```

Also update the function call references in those tests from `_run_query` to `run_query` and `_run_count` to `run_count`.

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest tests/ -v --timeout=60 -x`
Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/api/test_neo4j_queries.py tests/api/test_user_queries.py
git commit -m "test: update test imports for consolidated query helpers"
```

---

### Task 12: Final verification

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest tests/ -v --timeout=60`
Expected: All PASS.

- [ ] **Step 2: Run linter**

Run: `just lint`
Expected: All PASS.

- [ ] **Step 3: Run type checker**

Run: `uv run mypy api/ common/`
Expected: No new errors.

- [ ] **Step 4: Verify no remaining references to old helpers**

Run: `grep -r "_run_query\|_run_single\|_run_count" api/ --include="*.py"`
Expected: No results (all references migrated).

- [ ] **Step 5: Final commit if any fixups needed**

```bash
git add -A
git commit -m "chore: final cleanup for query debug logging"
```
