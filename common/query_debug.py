"""Query debug logging and database profiling utilities.

Provides debug-level query logging for Cypher and SQL queries, plus optional
PROFILE/EXPLAIN result logging to a dedicated profiling log file.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import threading
from typing import Any


_logger = logging.getLogger(__name__)

PROFILING_LOG_PATH = Path("/logs/profiling.log")

_profiling_logger: logging.Logger | None = None


def is_debug() -> bool:
    """Check if the root logger is at DEBUG level."""
    return logging.getLogger().isEnabledFor(logging.DEBUG)


def is_db_profiling() -> bool:
    """Check if database profiling is enabled.

    Returns True only when the root logger is at DEBUG level AND the
    ``DB_PROFILING`` environment variable is set to ``"true"``
    (case-insensitive).
    """
    return is_debug() and os.environ.get("DB_PROFILING", "").lower() == "true"


_profiling_logger_lock = threading.Lock()


def get_profiling_logger() -> logging.Logger:
    """Return a lazy-initialized logger that writes to the profiling log file.

    The logger is cached in the module-level ``_profiling_logger`` variable.
    It uses ``propagate=False`` so profiling output does not appear in the
    normal application logs.
    """
    global _profiling_logger

    if _profiling_logger is not None:
        return _profiling_logger

    with _profiling_logger_lock:
        # Double-check after acquiring lock
        if _profiling_logger is None:
            logger = logging.getLogger("db_profiling")
            logger.setLevel(logging.DEBUG)
            logger.propagate = False

            # Remove any existing handlers to avoid duplicates
            logger.handlers.clear()

            # Ensure log directory exists
            PROFILING_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

            handler = logging.FileHandler(PROFILING_LOG_PATH)
            handler.setLevel(logging.DEBUG)
            formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)

            _profiling_logger = logger

    return _profiling_logger  # guaranteed non-None after lock block


def log_cypher_query(cypher: str, params: dict[str, Any] | None) -> None:
    """Log a Cypher query at DEBUG level.

    Args:
        cypher: The Cypher query string.
        params: Query parameters.
    """
    _logger.debug("🔗 Cypher query: %s | params: %s", cypher, params)


def log_sql_query(query: Any, params: Any, cursor: Any) -> None:
    """Log a SQL query at DEBUG level.

    For ``psycopg.sql.Composable`` objects (detected via ``hasattr(query,
    "as_string")``), the query is rendered via ``query.as_string(cursor)``.

    Args:
        query: The SQL query (string or Composable).
        params: Query parameters.
        cursor: The database cursor (used for rendering Composable queries).
    """
    rendered = query.as_string(cursor) if hasattr(query, "as_string") else query
    _logger.debug("🐘 SQL query: %s | params: %s", rendered, params)


def _render_sql(query: Any, cursor: Any) -> str:
    """Render a SQL query to a string for logging.

    Args:
        query: The SQL query (string or Composable).
        cursor: The database cursor (used for rendering Composable queries).

    Returns:
        The rendered SQL string.
    """
    return query.as_string(cursor) if hasattr(query, "as_string") else str(query)


async def execute_sql(cursor: Any, query: Any, params: Any = None) -> None:
    """Execute a SQL query with debug logging and optional profiling.

    Calls :func:`log_sql_query` then awaits ``cursor.execute(query, params)``.
    When :func:`is_db_profiling` is ``True``, runs
    ``EXPLAIN (ANALYZE, BUFFERS, VERBOSE)`` after the query and writes the
    execution plan to the profiling log.  On query failure, runs ``EXPLAIN``
    (without ANALYZE) as a best-effort fallback.

    Args:
        cursor: An async database cursor.
        query: The SQL query.
        params: Optional query parameters.
    """
    log_sql_query(query, params, cursor)

    profiling = is_db_profiling()

    try:
        await cursor.execute(query, params)
        if profiling:
            await _try_sql_profile(cursor, query, params)
    except Exception as exc:
        if profiling:
            await _try_sql_explain_on_error(cursor, query, params, exc)
        raise


async def _try_sql_profile(cursor: Any, query: Any, params: Any) -> None:
    """Best-effort EXPLAIN (ANALYZE, BUFFERS, VERBOSE) after successful SQL execution.

    Uses a separate cursor to avoid overwriting the original query results.

    Args:
        cursor: An async database cursor.
        query: The original SQL query.
        params: Query parameters.
    """
    try:
        rendered = _render_sql(query, cursor)
        explain_query = f"EXPLAIN (ANALYZE, BUFFERS, VERBOSE) {rendered}"
        async with cursor.connection.cursor() as explain_cur:
            await explain_cur.execute(explain_query, params)  # nosemgrep
            rows = await explain_cur.fetchall()
        plan_text = "\n".join(row[0] for row in rows)
        log_sql_profile_result(rendered, params, plan_text)
    except Exception:  # noqa: S110
        pass  # nosec B110 — best-effort; query may not support EXPLAIN


async def _try_sql_explain_on_error(cursor: Any, query: Any, params: Any, error: BaseException) -> None:
    """Best-effort EXPLAIN (without ANALYZE) after SQL failure.

    Uses a separate cursor to avoid overwriting the original query results.

    Args:
        cursor: An async database cursor.
        query: The original SQL query.
        params: Query parameters.
        error: The original exception.
    """
    try:
        rendered = _render_sql(query, cursor)
        explain_query = f"EXPLAIN {rendered}"
        async with cursor.connection.cursor() as explain_cur:
            await explain_cur.execute(explain_query, params)  # nosemgrep
            rows = await explain_cur.fetchall()
        plan_text = "\n".join(row[0] for row in rows)
        log_sql_explain_result(rendered, params, plan_text, error)
    except Exception:  # noqa: S110
        pass  # nosec B110 — best-effort; DB may be unreachable


def log_profile_result(cypher: str, params: dict[str, Any] | None, summary: Any) -> None:
    """Write PROFILE results to the profiling log.

    Args:
        cypher: The Cypher query string.
        params: Query parameters.
        summary: The Neo4j result summary containing a ``profile`` attribute.
    """
    profile = summary.profile
    if isinstance(profile, dict):
        string_repr = profile.get("args", {}).get("string-representation", "")
    else:
        string_repr = profile.args.get("string-representation", "")

    prof_logger = get_profiling_logger()
    prof_logger.info(
        "\n══════════════════════════════════════════════════════════\nPROFILE result for Cypher query:\n\n%s\n\nParameters: %s\n\n%s",
        cypher,
        params,
        string_repr,
    )


def log_explain_result(
    cypher: str,
    params: dict[str, Any] | None,
    summary: Any,
    original_error: BaseException,
) -> None:
    """Write EXPLAIN results to the profiling log after a query failure.

    Args:
        cypher: The Cypher query string.
        params: Query parameters.
        summary: The Neo4j result summary containing a ``plan`` attribute.
        original_error: The exception that triggered the EXPLAIN fallback.
    """
    plan = summary.plan
    string_repr = plan.get("args", {}).get("string-representation", "") if isinstance(plan, dict) else plan.args.get("string-representation", "")

    error_type = type(original_error).__name__
    error_msg = str(original_error)

    prof_logger = get_profiling_logger()
    prof_logger.info(
        "\n══════════════════════════════════════════════════════════\n"
        "EXPLAIN (after error) for Cypher query:\n\n"
        "%s\n\n"
        "Parameters: %s\n"
        "Original error: %s: %s\n\n"
        "%s",
        cypher,
        params,
        error_type,
        error_msg,
        string_repr,
    )


def log_sql_profile_result(sql: str, params: Any, plan_text: str) -> None:
    """Write EXPLAIN (ANALYZE, BUFFERS, VERBOSE) results to the profiling log.

    Args:
        sql: The SQL query string.
        params: Query parameters.
        plan_text: The execution plan output from PostgreSQL.
    """
    prof_logger = get_profiling_logger()
    prof_logger.info(
        "\n══════════════════════════════════════════════════════════\n"
        "EXPLAIN (ANALYZE, BUFFERS, VERBOSE) result for SQL query:\n\n"
        "%s\n\n"
        "Parameters: %s\n\n"
        "%s",
        sql,
        params,
        plan_text,
    )


def log_sql_explain_result(
    sql: str,
    params: Any,
    plan_text: str,
    original_error: BaseException,
) -> None:
    """Write EXPLAIN results to the profiling log after a SQL query failure.

    Args:
        sql: The SQL query string.
        params: Query parameters.
        plan_text: The execution plan output from PostgreSQL.
        original_error: The exception that triggered the EXPLAIN fallback.
    """
    error_type = type(original_error).__name__
    error_msg = str(original_error)

    prof_logger = get_profiling_logger()
    prof_logger.info(
        "\n══════════════════════════════════════════════════════════\n"
        "EXPLAIN (after error) for SQL query:\n\n"
        "%s\n\n"
        "Parameters: %s\n"
        "Original error: %s: %s\n\n"
        "%s",
        sql,
        params,
        error_type,
        error_msg,
        plan_text,
    )
