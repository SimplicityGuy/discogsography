"""Query debug logging and Cypher profiling utilities.

Provides debug-level query logging for Cypher and SQL queries, plus optional
PROFILE/EXPLAIN result logging to a dedicated profiling log file.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any


_logger = logging.getLogger(__name__)

PROFILING_LOG_PATH = Path("/logs/profiling.log")

_profiling_logger: logging.Logger | None = None


def is_debug() -> bool:
    """Check if the root logger is at DEBUG level."""
    return logging.getLogger().isEnabledFor(logging.DEBUG)


def is_cypher_profiling() -> bool:
    """Check if Cypher profiling is enabled.

    Returns True only when the root logger is at DEBUG level AND the
    ``CYPHER_PROFILING`` environment variable is set to ``"true"``
    (case-insensitive).
    """
    return is_debug() and os.environ.get("CYPHER_PROFILING", "").lower() == "true"


def get_profiling_logger() -> logging.Logger:
    """Return a lazy-initialized logger that writes to the profiling log file.

    The logger is cached in the module-level ``_profiling_logger`` variable.
    It uses ``propagate=False`` so profiling output does not appear in the
    normal application logs.
    """
    global _profiling_logger

    if _profiling_logger is not None:
        return _profiling_logger

    logger = logging.getLogger("cypher_profiling")
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
    return logger


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


async def execute_sql(cursor: Any, query: Any, params: Any = None) -> None:
    """Execute a SQL query with debug logging.

    Calls :func:`log_sql_query` then awaits ``cursor.execute(query, params)``.

    Args:
        cursor: An async database cursor.
        query: The SQL query.
        params: Optional query parameters.
    """
    log_sql_query(query, params, cursor)
    await cursor.execute(query, params)


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
